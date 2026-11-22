# -*- coding: utf-8 -*-
"""
mensajes.py — Mensajes internos entre los usuarios del sistema
Prefijo: /mensajes

Registrar en app.py:
    from mensajes import mensajes_bp
    app.register_blueprint(mensajes_bp, url_prefix="/mensajes")

DE DONDE VIENE
--------------
Es el chat de gestion_adm (mensajes.py, 21 y 22/11/2026), copiado el
22/11/2026 con la sesión (`sind_`), el permiso (`db.puede`) y la carpeta de
adjuntos (SIND_ADJUNTOS y el bucket, almacenamiento.py) de acá. Las tablas son las mismas, en `sindicato`.

gestion_adm lo había copiado del chat de la financiera (PHP, inc/chat.php +
chat_api.php + chat_adjunto.php) SIN dos cosas:

- el hilo de las solicitudes de préstamo (el tipo SOLICITUD): acá no hay
  solicitudes, así que quedan sólo las conversaciones directas y los grupos;
- las llamadas: Llamar, WhatsApp y la videollamada (Jitsi). `s_usuarios` no
  tiene celular y la sala de video no se usa.

Los mensajes de voz sí quedan: son un adjunto de audio, no una llamada.

QUIEN LO USA
------------
Quien tiene el menú `/mensajes` (por su rol o suelto, como cualquier
pantalla: db.roles_y_menu). Le puede escribir a cualquier usuario activo que también lo tenga: escribirle
a alguien que no puede abrir Mensajes sería mandar algo que nunca va a leer.

LAS TABLAS (sql/chat_mensajes_20261122.sql)
------------------------------------------------
    chat_conversaciones  DIRECTA (clave_directa «menor-mayor»: una sola entre
                         dos personas) o GRUPO (con nombre).
    chat_participantes   quién está, si administra el grupo, hasta qué
                         mensaje leyó y si la silenció.
    chat_mensajes        texto y/o adjunto. id_usuario NULL = aviso del
                         sistema («Ana agregó a Luis»).

No leídos: cada participante guarda `ultimo_leido` y la conversación su
`ultimo_mensaje_id`. Hay algo nuevo si el segundo es mayor: sin marcar
mensaje por mensaje, y el contador de la barra es una consulta indexada.

Los mensajes no se borran: el autor lo retira (`borrado_el`) y queda
«Mensaje eliminado»; el archivo deja de servirse.

ADJUNTOS
--------
El archivo no va a la base: `SIND_ADJUNTOS / chat / <conv> / <32 hex>.<ext>`,
con su copia al bucket si hay (almacenamiento.py). Se sirve por /mensajes/adjunto/<id>, que controla que quien lo pide
participe de la conversación. El tipo se reconoce por el contenido, no por la
extensión que trae.

ESTADO DE LOS USUARIOS (22/11/2026)
-----------------------------------
«En línea» o «Últ. vez hoy a las 14:32», como en WhatsApp. Sale de
`chat_presencia` (en el mismo script): una fila por usuario con
la última vez que se lo vio, que anotan las consultas que el chat ya hace
(el contador de la barra, la lista, la conversación abierta) y cada pantalla
que se dibuja. No hay un pedido extra para esto. Se lo ve «en línea» si
pasaron menos de EN_LINEA_SEG segundos; al cerrar sesión o el navegador deja
de estarlo solo, al vencer ese plazo. Sin la tabla el chat anda igual, sin
estados.

LLEGADA DE MENSAJES
-------------------
No hay websockets: la pantalla consulta la API cada pocos segundos con una
conversación abierta, cada 10 la lista, y el botón de la barra cada 20 (el
contador). Ver static/js/chat.js.

LOS POST
--------
La aplicación no tiene token CSRF. Para que otro sitio no pueda mandar
mensajes en nombre de alguien con un formulario armado, los POST de la API
exigen el encabezado `X-Chat: 1`, que un formulario de otro origen no puede
poner (haría falta CORS, que acá no hay).
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
import re
import secrets
import unicodedata
from contextlib import contextmanager
from pathlib import Path

from flask import (Blueprint, abort, g, jsonify, redirect, render_template,
                   request, send_file, session, url_for)

import almacenamiento
from db import get_connection, puede, validasesion

log = logging.getLogger(__name__)

mensajes_bp = Blueprint("mensajes", __name__)

#: El menú que da acceso: el permiso de toda la pantalla (la API y los adjuntos).
URL_MENU = "/mensajes"

TEXTO_MAX = 4000            # caracteres por mensaje
GRUPO_NOMBRE_MAX = 80
PAGINA = 50                 # mensajes por tanda al abrir o al ir hacia atrás
LISTA_MAX = 200             # conversaciones en la lista
VOZ_MAX_SEG = 300           # un mensaje de voz dura hasta 5 minutos (chat.js corta solo)
MAX_BYTES = 20 * 1024 * 1024   # IIS corta en 30 MB (maxAllowedContentLength)
#: Dónde van los adjuntos: la carpeta de los comprobantes, el logo y la documentación.
def _adjuntos() -> Path:
    return almacenamiento.base()


def _borrar(ruta: Path) -> None:
    almacenamiento.borrar(ruta)               # disco y bucket


#: «En línea» si se lo vio hace menos que esto. El contador de la barra consulta
#: cada 20 s con la pestaña a la vista y cada 60 s con la pestaña oculta.
EN_LINEA_SEG = 90

#: Lo que se puede mandar: extensión → (mime, se muestra en el navegador).
#: PDF, imágenes y audio se reconocen por el contenido; Office por el
#: contenedor (ZIP para los nuevos, OLE para .doc/.xls) y la extensión;
#: texto por la extensión y por no traer bytes binarios. Office y texto
#: siempre se descargan.
TIPOS = {
    "pdf":  ("application/pdf", True),
    "jpg":  ("image/jpeg", True),
    "png":  ("image/png", True),
    "gif":  ("image/gif", True),
    "webp": ("image/webp", True),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", False),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", False),
    "xls":  ("application/vnd.ms-excel", False),
    "doc":  ("application/msword", False),
    "csv":  ("text/csv", False),
    "txt":  ("text/plain", False),
    "webm": ("audio/webm", True),
    "ogg":  ("audio/ogg", True),
    "m4a":  ("audio/mp4", True),
    "mp3":  ("audio/mpeg", True),
}

#: La hora del negocio. El contenedor de Railway corre en UTC.
_ART = _dt.timezone(_dt.timedelta(hours=-3))


class ChatError(Exception):
    """Error con el texto para la persona y el código HTTP de la respuesta."""

    def __init__(self, mensaje: str, http: int = 400):
        super().__init__(mensaje)
        self.http = http


# ── Sesión y permiso ─────────────────────────────────────────────────────────

def _yo() -> int:
    return int(session.get("sind_usuario_id") or 0)


def _mi_nombre() -> str:
    return session.get("sind_usuario_nombre") or session.get("sind_usuario_email") or "?"


def habilitado() -> bool:
    """¿Tiene el menú Mensajes? Sin el ítem creado en s_menu, nadie."""
    if not validasesion() or not _yo():
        return False
    return puede(URL_MENU)


@contextmanager
def _cursor():
    with get_connection() as conn:
        with conn.cursor() as cur:
            yield conn, cur


@contextmanager
def _transaccion(conn):
    conn.begin()
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _limpio(texto: str, largo: int) -> str:
    return re.sub(r"\s+", " ", texto or "").strip()[:largo]


def _peso(n: int) -> str:
    n = int(n or 0)
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{max(1, round(n / 1024))} KB"
    return f"{n / 1024 ** 2:.1f} MB".replace(".", ",")


def _lista_nombres(nombres: list[str]) -> str:
    """«Ana», «Ana y Luis», «Ana, Luis y Marta»."""
    if len(nombres) <= 1:
        return nombres[0] if nombres else ""
    return ", ".join(nombres[:-1]) + " y " + nombres[-1]


# ── Conversaciones ───────────────────────────────────────────────────────────

def conversacion(cur, id_conv: int) -> dict | None:
    """La conversación si el usuario participa, con su fila en 'participante'."""
    if not id_conv or id_conv <= 0:
        return None
    cur.execute("SELECT * FROM chat_conversaciones WHERE id_conversacion = %s", (id_conv,))
    c = cur.fetchone()
    if not c:
        return None
    cur.execute("SELECT * FROM chat_participantes WHERE id_conversacion = %s AND id_usuario = %s",
                (id_conv, _yo()))
    c["participante"] = cur.fetchone()
    return c if c["participante"] else None


def conversacion_o_error(cur, id_conv: int) -> dict:
    c = conversacion(cur, id_conv)
    if not c:
        raise ChatError("Esa conversación no existe o no participás de ella.", 404)
    return c


def _usuario_activo(cur, id_usuario: int) -> dict:
    cur.execute("SELECT id, nombre FROM s_usuarios WHERE id = %s AND activo = 1", (id_usuario,))
    u = cur.fetchone() if id_usuario and id_usuario > 0 else None
    if not u:
        raise ChatError("Ese usuario no existe o está dado de baja.")
    return u


def directa(cur, otro: int) -> int:
    """La conversación entre el usuario y otro: la busca o la crea."""
    yo = _yo()
    if otro == yo:
        raise ChatError("No podés escribirte a vos mismo.")
    _usuario_activo(cur, otro)
    clave = f"{min(yo, otro)}-{max(yo, otro)}"
    # Si los dos la abren a la vez, el índice único deja una sola y
    # LAST_INSERT_ID devuelve esa.
    cur.execute("""INSERT INTO chat_conversaciones (tipo, clave_directa, creado_por)
                   VALUES ('DIRECTA', %s, %s)
                   ON DUPLICATE KEY UPDATE id_conversacion = LAST_INSERT_ID(id_conversacion)""",
                (clave, yo))
    id_conv = int(cur.lastrowid)
    cur.execute("INSERT IGNORE INTO chat_participantes (id_conversacion, id_usuario) VALUES (%s, %s), (%s, %s)",
                (id_conv, yo, id_conv, otro))
    return id_conv


def _nombre_grupo(nombre: str) -> str:
    n = _limpio(nombre, GRUPO_NOMBRE_MAX)
    if not n:
        raise ChatError("Poné un nombre para el grupo.")
    return n


def aviso(cur, id_conv: int, texto: str) -> int:
    """Aviso del sistema (sin autor). Va dentro de la transacción del que llama."""
    cur.execute("INSERT INTO chat_mensajes (id_conversacion, id_usuario, texto) VALUES (%s, NULL, %s)",
                (id_conv, texto[:500]))
    id_msj = int(cur.lastrowid)
    cur.execute("UPDATE chat_conversaciones SET ultimo_mensaje_id = %s, ultimo_mensaje_el = NOW() "
                "WHERE id_conversacion = %s", (id_msj, id_conv))
    # El que hizo el cambio ya lo sabe: no le cuenta como no leído.
    cur.execute("UPDATE chat_participantes SET ultimo_leido = %s WHERE id_conversacion = %s AND id_usuario = %s",
                (id_msj, id_conv, _yo()))
    return id_msj


def grupo_crear(conn, cur, nombre: str, miembros: list[int]) -> int:
    """Crea un grupo con el usuario como administrador. Devuelve el id."""
    nombre = _nombre_grupo(nombre)
    yo = _yo()
    ids = list(dict.fromkeys(i for i in miembros if i > 0 and i != yo))
    if not ids:
        raise ChatError("Elegí al menos una persona para el grupo.")
    nombres = [_usuario_activo(cur, i)["nombre"] for i in ids]
    with _transaccion(conn):
        cur.execute("INSERT INTO chat_conversaciones (tipo, nombre, creado_por) VALUES ('GRUPO', %s, %s)",
                    (nombre, yo))
        id_conv = int(cur.lastrowid)
        cur.execute("INSERT INTO chat_participantes (id_conversacion, id_usuario, es_admin) VALUES (%s, %s, 1)",
                    (id_conv, yo))
        for i in ids:
            cur.execute("INSERT INTO chat_participantes (id_conversacion, id_usuario) VALUES (%s, %s)",
                        (id_conv, i))
        aviso(cur, id_conv, f"{_mi_nombre()} creó el grupo «{nombre}» con {_lista_nombres(nombres)}.")
    return id_conv


def grupo_editar(conn, cur, id_conv: int, nombre: str | None, agregar: list[int], quitar: list[int]) -> None:
    """Renombra, agrega y saca integrantes (sólo quien lo administra)."""
    c = conversacion_o_error(cur, id_conv)
    if c["tipo"] != "GRUPO":
        raise ChatError("Sólo los grupos tienen integrantes para editar.")
    if not int(c["participante"]["es_admin"]):
        raise ChatError("Sólo quien administra el grupo lo puede editar.", 403)
    yo = _yo()
    with _transaccion(conn):
        if nombre and _nombre_grupo(nombre) != c["nombre"]:
            nombre = _nombre_grupo(nombre)
            cur.execute("UPDATE chat_conversaciones SET nombre = %s WHERE id_conversacion = %s", (nombre, id_conv))
            aviso(cur, id_conv, f"{_mi_nombre()} le cambió el nombre al grupo: «{nombre}».")
        suma = []
        for uid in dict.fromkeys(agregar):
            if uid <= 0:
                continue
            u = _usuario_activo(cur, uid)
            # Entra con todo lo anterior leído: no le aparece la historia como nueva.
            cur.execute("""INSERT IGNORE INTO chat_participantes (id_conversacion, id_usuario, ultimo_leido)
                           SELECT %s, %s, ultimo_mensaje_id FROM chat_conversaciones WHERE id_conversacion = %s""",
                        (id_conv, uid, id_conv))
            if cur.rowcount > 0:
                suma.append(u["nombre"])
        if suma:
            aviso(cur, id_conv, f"{_mi_nombre()} agregó a {_lista_nombres(suma)}.")
        resta = []
        for uid in dict.fromkeys(quitar):
            if uid <= 0 or uid == yo:
                continue
            cur.execute("""SELECT u.nombre FROM chat_participantes p JOIN s_usuarios u ON u.id = p.id_usuario
                            WHERE p.id_conversacion = %s AND p.id_usuario = %s""", (id_conv, uid))
            u = cur.fetchone()
            if u:
                cur.execute("DELETE FROM chat_participantes WHERE id_conversacion = %s AND id_usuario = %s",
                            (id_conv, uid))
                resta.append(u["nombre"])
        if resta:
            aviso(cur, id_conv, f"{_mi_nombre()} sacó del grupo a {_lista_nombres(resta)}.")


def grupo_salir(conn, cur, id_conv: int) -> None:
    """Salir de un grupo. Si era el único administrador, pasa a serlo el más antiguo."""
    c = conversacion_o_error(cur, id_conv)
    if c["tipo"] != "GRUPO":
        raise ChatError("Sólo se puede salir de un grupo.")
    with _transaccion(conn):
        cur.execute("DELETE FROM chat_participantes WHERE id_conversacion = %s AND id_usuario = %s",
                    (id_conv, _yo()))
        cur.execute("SELECT COUNT(*) AS n FROM chat_participantes WHERE id_conversacion = %s AND es_admin = 1",
                    (id_conv,))
        if int(cur.fetchone()["n"]) == 0:
            cur.execute("""UPDATE chat_participantes SET es_admin = 1 WHERE id_conversacion = %s
                            ORDER BY agregado_el, id_usuario LIMIT 1""", (id_conv,))
        aviso(cur, id_conv, f"{_mi_nombre()} salió del grupo.")


# ── Adjuntos ─────────────────────────────────────────────────────────────────

def detectar_tipo(cabeza: bytes, nombre: str) -> str | None:
    """Extensión de TIPOS según el contenido, o None si no es algo que se acepte."""
    b = cabeza
    if b.startswith(b"%PDF"):
        return "pdf"
    if b.startswith(b"\xFF\xD8\xFF"):
        return "jpg"
    if b.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "webp"
    declarada = Path(nombre or "").suffix.lower().lstrip(".")
    if declarada in ("xlsx", "docx") and b.startswith(b"PK\x03\x04"):
        return declarada
    if declarada in ("xls", "doc") and b.startswith(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"):
        return declarada
    if declarada in ("csv", "txt") and b"\0" not in b:
        return declarada
    # Audio
    if b.startswith(b"\x1A\x45\xDF\xA3"):
        return "webm"                     # EBML: lo que graban Chrome, Edge y Firefox
    if b.startswith(b"OggS"):
        return "ogg"                      # también los .opus de WhatsApp
    if b[4:8] == b"ftyp":
        return "m4a"                      # lo que graba Safari (iPhone)
    if b.startswith(b"ID3") or (declarada == "mp3" and len(b) > 1 and b[0] == 0xFF and (b[1] & 0xE0) == 0xE0):
        return "mp3"
    return None


def _nombre_archivo(nombre: str) -> str:
    """El nombre como lo subieron, sin carpetas ni caracteres de control."""
    n = (nombre or "").replace("\\", "/").split("/")[-1]
    n = "".join(ch for ch in n if unicodedata.category(ch)[0] != "C").strip()
    return (n or "archivo")[:200]


def _carpeta_chat() -> Path:
    return _adjuntos() / "chat"


def guardar_adjunto(id_conv: int, archivo) -> dict:
    """Guarda el archivo subido y devuelve los datos para el mensaje."""
    nombre = _nombre_archivo(archivo.filename)
    datos = archivo.read(MAX_BYTES + 1)
    if not datos:
        raise ChatError(f"{nombre}: no se pudo subir o está vacío.")
    if len(datos) > MAX_BYTES:
        raise ChatError(f"{nombre}: pesa más de {_peso(MAX_BYTES)}, que es el máximo.")
    ext = detectar_tipo(datos[:8192], nombre)
    if ext is None:
        raise ChatError(f"{nombre}: se pueden mandar PDF, imágenes (JPG, PNG, GIF, WEBP), Word, "
                        "Excel, CSV, texto o audio.")
    rel = f"chat/{id_conv}/{secrets.token_hex(16)}.{ext}"
    destino = _adjuntos() / rel
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(datos)
    except OSError as e:
        raise ChatError(f"{nombre}: no se pudo guardar ({e}).", 500)
    almacenamiento.respaldar(destino, datos, TIPOS[ext][0])
    return {"archivo": rel, "ruta": destino, "nombre": nombre, "mime": TIPOS[ext][0],
            "bytes": len(datos), "ext": ext}


_REL_OK = re.compile(r"^chat/\d+/[0-9a-f]{32}\.[a-z0-9]{2,4}$")


def ruta_adjunto(rel: str) -> Path | None:
    """La ruta en disco de un adjunto guardado, o None si la ruta no es una de las nuestras."""
    if not rel or not _REL_OK.match(rel):
        return None
    return _adjuntos() / rel


# ── Mensajes ─────────────────────────────────────────────────────────────────

def enviar(conn, cur, id_conv: int, texto: str, archivo, duracion_voz: int | None = None) -> int:
    """Manda un mensaje (texto, adjunto o los dos). Con duracion_voz es un mensaje de voz."""
    conversacion_o_error(cur, id_conv)
    texto = (texto or "").replace("\r\n", "\n").strip()
    if not texto and archivo is None:
        raise ChatError("Escribí un mensaje o elegí un archivo.")
    if len(texto) > TEXTO_MAX:
        raise ChatError(f"El mensaje es muy largo (hasta {TEXTO_MAX:,} caracteres).".replace(",", "."))
    if duracion_voz is not None and archivo is None:
        raise ChatError("No llegó el audio. Probá grabarlo de nuevo.")
    adj = guardar_adjunto(id_conv, archivo) if archivo is not None else None
    if duracion_voz is not None:
        if not adj["mime"].startswith("audio/"):
            _borrar(adj["ruta"])
            raise ChatError("El mensaje de voz no llegó como audio. Probá grabarlo de nuevo.")
        adj["nombre"] = f"Mensaje de voz.{adj['ext']}"
        adj["duracion"] = max(1, min(VOZ_MAX_SEG + 5, int(duracion_voz)))
    try:
        with _transaccion(conn):
            cur.execute("""INSERT INTO chat_mensajes
                             (id_conversacion, id_usuario, texto, adjunto_archivo, adjunto_nombre,
                              adjunto_mime, adjunto_bytes, adjunto_duracion)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                        (id_conv, _yo(), texto or None,
                         adj and adj["archivo"], adj and adj["nombre"], adj and adj["mime"],
                         adj and adj["bytes"], adj and adj.get("duracion")))
            id_msj = int(cur.lastrowid)
            cur.execute("UPDATE chat_conversaciones SET ultimo_mensaje_id = %s, ultimo_mensaje_el = NOW() "
                        "WHERE id_conversacion = %s", (id_msj, id_conv))
            cur.execute("UPDATE chat_participantes SET ultimo_leido = %s "
                        "WHERE id_conversacion = %s AND id_usuario = %s", (id_msj, id_conv, _yo()))
    except BaseException:
        if adj:
            _borrar(adj["ruta"])      # sin mensaje no queda archivo huérfano
        raise
    return id_msj


def retirar(cur, id_msj: int) -> None:
    """El autor retira su mensaje: queda «Mensaje eliminado» y el archivo deja de servirse."""
    cur.execute("SELECT id_conversacion, id_usuario FROM chat_mensajes WHERE id_mensaje = %s", (id_msj,))
    m = cur.fetchone()
    if not m or not conversacion(cur, int(m["id_conversacion"])):
        raise ChatError("Ese mensaje no existe.", 404)
    if m["id_usuario"] is None or int(m["id_usuario"]) != _yo():
        raise ChatError("Sólo podés eliminar tus mensajes.", 403)
    cur.execute("UPDATE chat_mensajes SET borrado_el = NOW() WHERE id_mensaje = %s AND borrado_el IS NULL",
                (id_msj,))


def _url_adjunto(id_msj: int) -> str:
    return url_for("mensajes.adjunto", id_mensaje=id_msj)


def mensajes(cur, id_conv: int, desde: int = 0, antes: int = 0) -> list[dict]:
    """
    Mensajes en orden, como los usa la pantalla.
      desde > 0: los posteriores a ese id (lo nuevo desde la última consulta)
      antes > 0: la tanda anterior a ese id (ir hacia atrás)
      los dos 0: la última tanda
    """
    sel = """SELECT m.*, u.nombre AS autor
               FROM chat_mensajes m LEFT JOIN s_usuarios u ON u.id = m.id_usuario
              WHERE m.id_conversacion = %s """
    if desde > 0:
        cur.execute(sel + "AND m.id_mensaje > %s ORDER BY m.id_mensaje LIMIT 500", (id_conv, desde))
        filas = cur.fetchall()
    elif antes > 0:
        cur.execute(sel + f"AND m.id_mensaje < %s ORDER BY m.id_mensaje DESC LIMIT {PAGINA}", (id_conv, antes))
        filas = list(reversed(cur.fetchall()))
    else:
        cur.execute(sel + f"ORDER BY m.id_mensaje DESC LIMIT {PAGINA}", (id_conv,))
        filas = list(reversed(cur.fetchall()))
    yo = _yo()
    out = []
    for m in filas:
        borrado = m["borrado_el"] is not None
        adj = None
        if not borrado and m["adjunto_nombre"] is not None:
            mime = m["adjunto_mime"] or ""
            adj = {"nombre": m["adjunto_nombre"], "peso": _peso(m["adjunto_bytes"]),
                   "imagen": mime.startswith("image/"), "audio": mime.startswith("audio/"),
                   "duracion": int(m["adjunto_duracion"]) if m["adjunto_duracion"] is not None else None,
                   "url": _url_adjunto(int(m["id_mensaje"]))}
        creado = m["creado_el"]
        out.append({
            "id":      int(m["id_mensaje"]),
            "autor":   m["autor"],
            "propio":  m["id_usuario"] is not None and int(m["id_usuario"]) == yo,
            "sistema": m["id_usuario"] is None,
            "texto":   None if borrado else m["texto"],
            "borrado": borrado,
            "adjunto": adj,
            "fecha":   creado.strftime("%Y-%m-%d"),
            "hora":    creado.strftime("%H:%M"),
        })
    return out


def marcar_leido(cur, id_conv: int, hasta: int) -> None:
    """Marca leído hasta ese mensaje (nunca hacia atrás)."""
    if hasta > 0:
        cur.execute("""UPDATE chat_participantes p
                         JOIN chat_conversaciones c ON c.id_conversacion = p.id_conversacion
                          SET p.ultimo_leido = LEAST(%s, c.ultimo_mensaje_id)
                        WHERE p.id_conversacion = %s AND p.id_usuario = %s AND p.ultimo_leido < %s""",
                    (hasta, id_conv, _yo(), hasta))


def lectores(cur, id_conv: int) -> list[dict]:
    """Hasta qué mensaje leyó cada uno de los demás (las tildes y el «Visto por»)."""
    cur.execute("""SELECT u.nombre, p.ultimo_leido FROM chat_participantes p JOIN s_usuarios u ON u.id = p.id_usuario
                    WHERE p.id_conversacion = %s AND p.id_usuario <> %s ORDER BY u.nombre""", (id_conv, _yo()))
    return [{"nombre": r["nombre"], "hasta": int(r["ultimo_leido"])} for r in cur.fetchall()]


# ── Listas ───────────────────────────────────────────────────────────────────

def _cuando(dt: _dt.datetime | None) -> str:
    """«14:32» si es de hoy, «ayer», o «18/11»."""
    if not dt:
        return ""
    hoy = _dt.datetime.now(_ART).date()
    if dt.date() == hoy:
        return dt.strftime("%H:%M")
    if dt.date() == hoy - _dt.timedelta(days=1):
        return "ayer"
    return dt.strftime("%d/%m")


def _resumen_adjunto(nombre: str | None, mime: str | None) -> str:
    """Lo que se ve en la lista cuando el último mensaje es sólo un archivo."""
    nombre, mime = nombre or "", mime or ""
    if mime.startswith("audio/"):
        return "🎤 Mensaje de voz" if nombre.startswith("Mensaje de voz") else "🎵 " + nombre
    return ("📷 " if mime.startswith("image/") else "📎 ") + nombre


def lista(cur) -> list[dict]:
    """Las conversaciones del usuario, la más reciente primero."""
    yo = _yo()
    cur.execute(f"""
        SELECT c.id_conversacion, c.tipo, c.nombre, c.ultimo_mensaje_id, c.ultimo_mensaje_el, c.creado_el,
               p.ultimo_leido, p.silenciada, p.es_admin,
               (SELECT u.nombre FROM chat_participantes o JOIN s_usuarios u ON u.id = o.id_usuario
                 WHERE o.id_conversacion = c.id_conversacion AND o.id_usuario <> p.id_usuario LIMIT 1) AS otro,
               (SELECT o.id_usuario FROM chat_participantes o
                 WHERE o.id_conversacion = c.id_conversacion AND o.id_usuario <> p.id_usuario LIMIT 1) AS otro_id,
               (SELECT u.activo FROM chat_participantes o JOIN s_usuarios u ON u.id = o.id_usuario
                 WHERE o.id_conversacion = c.id_conversacion AND o.id_usuario <> p.id_usuario LIMIT 1) AS otro_activo,
               m.texto AS ult_texto, m.adjunto_nombre AS ult_adjunto, m.adjunto_mime AS ult_mime,
               m.borrado_el AS ult_borrado, m.id_usuario AS ult_uid, um.nombre AS ult_autor,
               (SELECT COUNT(*) FROM chat_mensajes x
                 WHERE x.id_conversacion = c.id_conversacion AND x.id_mensaje > p.ultimo_leido) AS no_leidos
          FROM chat_participantes p
          JOIN chat_conversaciones c ON c.id_conversacion = p.id_conversacion
          LEFT JOIN chat_mensajes m ON m.id_mensaje = c.ultimo_mensaje_id
          LEFT JOIN s_usuarios um ON um.id = m.id_usuario
         WHERE p.id_usuario = %s AND (c.tipo <> 'DIRECTA' OR c.ultimo_mensaje_id > 0)
         ORDER BY COALESCE(c.ultimo_mensaje_el, c.creado_el) DESC
         LIMIT {LISTA_MAX}""", (yo,))
    filas = cur.fetchall()
    pres = presencias(cur, [f["otro_id"] for f in filas if f["tipo"] == "DIRECTA"])
    out = []
    for f in filas:
        titulo = f["nombre"] if f["tipo"] == "GRUPO" else (f["otro"] or "(sin el otro usuario)")
        ult = ""
        if int(f["ultimo_mensaje_id"]) > 0:
            if f["ult_borrado"] is not None:
                ult = "Mensaje eliminado"
            elif f["ult_texto"]:
                ult = f["ult_texto"]
            else:
                ult = _resumen_adjunto(f["ult_adjunto"], f["ult_mime"])
            if f["ult_uid"] is not None:
                propio = int(f["ult_uid"]) == yo
                if f["tipo"] != "DIRECTA":
                    ult = ("Vos" if propio else (f["ult_autor"] or "").split(" ")[0]) + ": " + ult
                elif propio:
                    ult = "Vos: " + ult
        out.append({
            "id":         int(f["id_conversacion"]),
            "tipo":       f["tipo"],
            "titulo":     titulo,
            "inactivo":   f["tipo"] == "DIRECTA" and f["otro_activo"] is not None and not int(f["otro_activo"]),
            "ultimo":     re.sub(r"\s+", " ", ult)[:90],
            "cuando":     _cuando(f["ultimo_mensaje_el"]),
            "no_leidos":  int(f["no_leidos"]),
            "silenciada": bool(int(f["silenciada"])),
            "admin":      bool(int(f["es_admin"])),
            # El estado del otro, sólo en las directas (en un grupo no dice nada de uno).
            **(pres.get(int(f["otro_id"]), {"en_linea": False, "estado": ""})
               if f["tipo"] == "DIRECTA" and f["otro_id"] is not None else {"en_linea": False, "estado": ""}),
        })
    return out


def no_leidos(cur) -> dict:
    """
    Para el botón de la barra: cuántas conversaciones tienen algo sin leer (sin
    las silenciadas) y el id del mensaje sin leer más nuevo. Con ese id chat.js
    decide si suena: suena cuando aparece uno más nuevo que el último que ya
    sonó (los ids de mensaje son una sola numeración para todas).
    """
    cur.execute("""SELECT COUNT(*) AS n, COALESCE(MAX(c.ultimo_mensaje_id), 0) AS ultimo
                     FROM chat_participantes p
                     JOIN chat_conversaciones c ON c.id_conversacion = p.id_conversacion
                    WHERE p.id_usuario = %s AND p.silenciada = 0 AND c.ultimo_mensaje_id > p.ultimo_leido""",
                (_yo(),))
    r = cur.fetchone() or {}
    return {"no_leidos": int(r.get("n") or 0), "ultimo": int(r.get("ultimo") or 0)}


# ── Estado de los usuarios (en línea / última vez) ───────────────────────────

#: ¿Existe chat_presencia? Se mira una vez por minuto hasta que aparece: así
#: el chat sigue andando si el script de la tabla todavía no se corrió.
_PRESENCIA = {"hay": False, "revisado": None}


def _hay_presencia(cur) -> bool:
    import time
    if _PRESENCIA["hay"]:
        return True
    ahora = time.monotonic()
    if _PRESENCIA["revisado"] is not None and ahora - _PRESENCIA["revisado"] < 60:
        return False
    _PRESENCIA["revisado"] = ahora
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.tables
                    WHERE table_schema = DATABASE() AND table_name = 'chat_presencia'""")
    _PRESENCIA["hay"] = bool(int((cur.fetchone() or {}).get("n") or 0))
    return _PRESENCIA["hay"]


def marcar_presencia(cur) -> None:
    """Anota que el usuario está. Escribe como mucho una vez cada 15 segundos. Nunca lanza."""
    try:
        if _yo() and _hay_presencia(cur):
            cur.execute("""INSERT INTO chat_presencia (id_usuario, visto_el) VALUES (%s, NOW())
                           ON DUPLICATE KEY UPDATE
                              visto_el = IF(visto_el < NOW() - INTERVAL 15 SECOND, NOW(), visto_el)""",
                        (_yo(),))
    except Exception as e:                                   # noqa: BLE001
        log.warning("Mensajes: no se pudo anotar la presencia: %s", e)


def _estado(visto: _dt.datetime | None, segundos) -> dict:
    """{en_linea, estado}: «En línea», «Últ. vez hoy a las 14:32», «… ayer a las…», «… el 18/11»."""
    if visto is None or segundos is None:
        return {"en_linea": False, "estado": ""}
    if int(segundos) <= EN_LINEA_SEG:
        return {"en_linea": True, "estado": "En línea"}
    hoy = _dt.datetime.now(_ART).date()
    hora = visto.strftime("%H:%M")
    if visto.date() == hoy:
        txt = f"hoy a las {hora}"
    elif visto.date() == hoy - _dt.timedelta(days=1):
        txt = f"ayer a las {hora}"
    elif visto.year == hoy.year:
        txt = "el " + visto.strftime("%d/%m")
    else:
        txt = "el " + visto.strftime("%d/%m/%Y")
    return {"en_linea": False, "estado": "Últ. vez " + txt}


def presencias(cur, ids) -> dict[int, dict]:
    """id de usuario → {en_linea, estado}. Los que nunca se vieron, con estado vacío."""
    ids = sorted({int(i) for i in ids if i})
    vacio = {"en_linea": False, "estado": ""}
    out = {i: dict(vacio) for i in ids}
    if not ids or not _hay_presencia(cur):
        return out
    marcas = ",".join(["%s"] * len(ids))
    cur.execute(f"""SELECT id_usuario, visto_el, TIMESTAMPDIFF(SECOND, visto_el, NOW()) AS seg
                      FROM chat_presencia WHERE id_usuario IN ({marcas})""", ids)
    for r in cur.fetchall():
        out[int(r["id_usuario"])] = _estado(r["visto_el"], r["seg"])
    return out


def presencia_conv(cur, c: dict) -> dict:
    """Lo que muestra la cabecera: el estado del otro (directa) o cuántos están en línea (grupo)."""
    cur.execute("SELECT id_usuario FROM chat_participantes WHERE id_conversacion = %s AND id_usuario <> %s",
                (int(c["id_conversacion"]), _yo()))
    otros = [int(r["id_usuario"]) for r in cur.fetchall()]
    pres = presencias(cur, otros)
    if c["tipo"] == "DIRECTA":
        return pres.get(otros[0], {"en_linea": False, "estado": ""}) if otros else {"en_linea": False, "estado": ""}
    n = sum(1 for p in pres.values() if p["en_linea"])
    return {"en_linea": n > 0, "estado": (f"{n} en línea" if n else ""), "ids": [i for i, p in pres.items() if p["en_linea"]]}


def usuarios(cur) -> list[dict]:
    """A quién se le puede escribir: activos con el menú Mensajes, sin el actual, con sus roles."""
    cur.execute("""
        SELECT u.id, u.nombre,
               COALESCE(GROUP_CONCAT(DISTINCT r.nombre ORDER BY r.prioridad DESC SEPARATOR ', '), '') AS roles
          FROM s_usuarios u
          LEFT JOIN s_usuario_rol ur ON ur.usuario_id = u.id
          LEFT JOIN s_roles r ON r.id = ur.rol_id AND r.activo = 1
         WHERE u.activo = 1 AND u.id <> %s
           AND EXISTS (SELECT 1 FROM s_menu m
                        WHERE m.url = %s AND m.activo = 1
                          AND m.id IN (SELECT mu.menu_id FROM s_menu_usuario mu WHERE mu.usuario_id = u.id))
         GROUP BY u.id, u.nombre
         ORDER BY u.nombre""", (_yo(), URL_MENU))
    filas = cur.fetchall()
    pres = presencias(cur, [u["id"] for u in filas])
    return [{"id": int(u["id"]), "nombre": u["nombre"], "roles": u["roles"] or "", **pres[int(u["id"])]}
            for u in filas]


def integrantes(cur, id_conv: int) -> list[dict]:
    cur.execute("""SELECT u.id, u.nombre, p.es_admin, u.activo
                     FROM chat_participantes p JOIN s_usuarios u ON u.id = p.id_usuario
                    WHERE p.id_conversacion = %s ORDER BY p.es_admin DESC, u.nombre""", (id_conv,))
    filas = cur.fetchall()
    pres = presencias(cur, [u["id"] for u in filas])
    return [{"id": int(u["id"]), "nombre": u["nombre"], "admin": bool(int(u["es_admin"])),
             "activo": bool(int(u["activo"])), **pres[int(u["id"])]} for u in filas]


def titulo(cur, c: dict) -> str:
    if c["tipo"] == "GRUPO":
        return c["nombre"] or ""
    cur.execute("""SELECT u.nombre FROM chat_participantes p JOIN s_usuarios u ON u.id = p.id_usuario
                    WHERE p.id_conversacion = %s AND p.id_usuario <> %s LIMIT 1""",
                (int(c["id_conversacion"]), _yo()))
    o = cur.fetchone()
    return o["nombre"] if o else ""


# ── El botón de la barra ─────────────────────────────────────────────────────

@mensajes_bp.app_context_processor
def _contexto_encabezado():
    """
    `chat_encabezado`: {n, ultimo, href} para dibujar el botón Mensajes en
    base.html, o None si el usuario no tiene la opción. Se calcula una vez por
    request (un render puede incluir varios templates).
    """
    if "chat_encabezado" in g:
        return {"chat_encabezado": g.chat_encabezado, "chat_v": _version_js()}
    datos = None
    try:
        if habilitado() and request.blueprint != "mensajes":
            with _cursor() as (_conn, cur):
                marcar_presencia(cur)
                datos = no_leidos(cur)
            aca = request.full_path.rstrip("?") if request.method == "GET" else ""
            datos["href"] = url_for("mensajes.index", volver=aca) if _volver_ok(aca) and aca != "/menu" \
                else url_for("mensajes.index")
    except Exception as e:                                   # noqa: BLE001
        # Sin las tablas (o sin conexión) la pantalla tiene que seguir andando.
        log.warning("Mensajes: no se pudo armar el contador de la barra: %s", e)
        datos = None
    g.chat_encabezado = datos
    return {"chat_encabezado": datos, "chat_v": _version_js()}


def _version_js() -> int:
    """La fecha de chat.js, para el `?v=`: sin eso el navegador sigue con la vieja."""
    try:
        return int((Path(__file__).resolve().parent / "static" / "js" / "chat.js").stat().st_mtime)
    except OSError:
        return 0


def _volver_ok(url: str) -> bool:
    """Una ruta de esta aplicación (no `//otro.sitio`), que no sea Mensajes."""
    return bool(url) and url.startswith("/") and not url.startswith("//") \
        and not url.startswith(URL_MENU)


# ── Rutas ────────────────────────────────────────────────────────────────────

@mensajes_bp.route("")
def index():
    """La pantalla: lista de conversaciones + la conversación abierta. Todo lo arma chat.js."""
    if not validasesion():
        return redirect(url_for("login"))
    volver = request.args.get("volver") or ""
    if not _volver_ok(volver):
        volver = url_for("menu")
    error = None
    try:
        with _cursor() as (_conn, cur):
            cur.execute("SELECT 1 FROM chat_conversaciones LIMIT 1")
    except Exception as e:                                   # noqa: BLE001
        error = ("Faltan las tablas de mensajes: correr sql/chat_mensajes_20261122.sql."
                 if "1146" in str(e) else f"No se pudo abrir Mensajes: {e}")
    return render_template("mensajes/index.html", volver=volver, error=error,
                           max_peso=_peso(MAX_BYTES))


def _responder(datos: dict, http: int = 200):
    datos = dict(datos)
    datos["ok"] = http < 400
    r = jsonify(datos)
    r.status_code = http
    r.headers["Cache-Control"] = "no-store"
    return r


def _ids(clave: str) -> list[int]:
    """Lista de enteros de un campo que puede venir como miembros[] o «1,2,3»."""
    valores = request.form.getlist(clave + "[]") or request.form.getlist(clave)
    out = []
    for v in valores:
        for x in str(v).split(","):
            x = x.strip()
            if x.isdigit() and int(x) > 0:
                out.append(int(x))
    return out


def _int(fuente, clave: str) -> int:
    try:
        return int(fuente.get(clave) or 0)
    except (TypeError, ValueError):
        return 0


@mensajes_bp.route("/api", methods=["GET", "POST"])
def api():
    """
    GET  accion=contador                        conversaciones con algo sin leer
    GET  accion=lista                           conversaciones del usuario
    GET  accion=usuarios                        a quién se le puede escribir
    GET  accion=mensajes&conv=N                 la última tanda
         &desde=ID | &antes=ID                  lo posterior / la tanda anterior
         &leer=1                                marca leído hasta lo devuelto
    POST accion=enviar    conv | para, texto, archivo (voz=1, duracion=seg)
    POST accion=abrir     para                  la directa con alguien
    POST accion=grupo     nombre, miembros[]
    POST accion=editar    conv, nombre, agregar[], quitar[]
    POST accion=salir     conv
    POST accion=silenciar conv, si (1|0)
    POST accion=retirar   mensaje
    POST accion=leido     conv, hasta
    """
    if not validasesion() or not _yo():
        return _responder({"error": "La sesión se cerró. Volvé a ingresar."}, 401)
    try:
        if not habilitado():
            raise ChatError("No tenés la opción Mensajes.", 403)
        if request.method == "GET":
            return _api_get(request.args.get("accion") or "")
        if request.headers.get("X-Chat") != "1":
            raise ChatError("Pedido no válido. Recargá la pantalla.", 400)
        return _api_post(request.form.get("accion") or "")
    except ChatError as e:
        return _responder({"error": str(e)}, e.http)
    except Exception as e:                                   # noqa: BLE001
        cod = getattr(e, "args", [None])[0]
        if cod == 1146:
            return _responder({"error": "Faltan las tablas de mensajes: correr "
                                        "sql/chat_mensajes_20261122.sql."}, 500)
        if cod == 1142:
            return _responder({"error": "El usuario de la base no tiene permiso de escritura sobre las "
                                        "tablas de mensajes (app_sindicato necesita INSERT y UPDATE)."}, 500)
        log.exception("Mensajes: error en la API")
        return _responder({"error": f"No se pudo: {type(e).__name__}: {e}"}, 500)


def _api_get(accion: str):
    with _cursor() as (_conn, cur):
        marcar_presencia(cur)
        if accion == "contador":
            return _responder(no_leidos(cur))
        if accion == "lista":
            return _responder({"conversaciones": lista(cur), **no_leidos(cur)})
        if accion == "usuarios":
            return _responder({"usuarios": usuarios(cur)})
        if accion == "mensajes":
            id_conv = _int(request.args, "conv")
            c = conversacion_o_error(cur, id_conv)
            desde = _int(request.args, "desde")
            msjs = mensajes(cur, id_conv, desde, _int(request.args, "antes"))
            if request.args.get("leer") == "1" and msjs:
                marcar_leido(cur, id_conv, max(m["id"] for m in msjs))
            datos = {"mensajes": msjs, "lectores": lectores(cur, id_conv), "presencia": presencia_conv(cur, c)}
            if desde == 0:
                # Al abrirla: los datos de la cabecera.
                p = c["participante"]
                datos["conv"] = {
                    "id": id_conv, "tipo": c["tipo"], "titulo": titulo(cur, c),
                    "admin": bool(int(p["es_admin"])), "silenciada": bool(int(p["silenciada"])),
                    "participa": True,
                    "integrantes": [] if c["tipo"] == "DIRECTA" else integrantes(cur, id_conv),
                    "hay_mas": len(msjs) >= PAGINA,
                }
            return _responder(datos)
    raise ChatError("Acción desconocida.")


def _api_post(accion: str):
    with _cursor() as (conn, cur):
        if accion == "enviar":
            para = _int(request.form, "para")
            id_conv = directa(cur, para) if para > 0 else _int(request.form, "conv")
            archivos = [a for a in request.files.getlist("archivo") if a and a.filename]
            if len(archivos) > 1:
                raise ChatError("Mandá los archivos de a uno.")
            voz = _int(request.form, "duracion") if request.form.get("voz") == "1" else None
            id_msj = enviar(conn, cur, id_conv, request.form.get("texto") or "",
                            archivos[0] if archivos else None, voz)
            return _responder({"conv": id_conv, "mensaje": id_msj})
        if accion == "abrir":
            return _responder({"conv": directa(cur, _int(request.form, "para"))})
        if accion == "grupo":
            return _responder({"conv": grupo_crear(conn, cur, request.form.get("nombre") or "", _ids("miembros"))})
        if accion == "editar":
            id_conv = _int(request.form, "conv")
            grupo_editar(conn, cur, id_conv, request.form.get("nombre"), _ids("agregar"), _ids("quitar"))
            return _responder({"conv": id_conv})
        if accion == "salir":
            grupo_salir(conn, cur, _int(request.form, "conv"))
            return _responder({})
        if accion == "silenciar":
            id_conv = _int(request.form, "conv")
            conversacion_o_error(cur, id_conv)
            cur.execute("UPDATE chat_participantes SET silenciada = %s WHERE id_conversacion = %s AND id_usuario = %s",
                        (1 if request.form.get("si") == "1" else 0, id_conv, _yo()))
            return _responder({})
        if accion == "retirar":
            retirar(cur, _int(request.form, "mensaje"))
            return _responder({})
        if accion == "leido":
            id_conv = _int(request.form, "conv")
            conversacion_o_error(cur, id_conv)
            marcar_leido(cur, id_conv, _int(request.form, "hasta"))
            return _responder({})
    raise ChatError("Acción desconocida.")


@mensajes_bp.route("/adjunto/<int:id_mensaje>")
def adjunto(id_mensaje: int):
    """
    El archivo de un mensaje. PDF, imágenes y audio se muestran; el resto se
    descarga (y con ?bajar=1, todo). Sólo para quien participa de la
    conversación, y no si el autor retiró el mensaje. Acepta pedidos por
    partes (Range): el iPhone no reproduce un audio sin eso.
    """
    if not validasesion():
        return redirect(url_for("login"))
    if not habilitado():
        abort(403)
    with _cursor() as (_conn, cur):
        cur.execute("""SELECT id_conversacion, adjunto_archivo, adjunto_nombre, borrado_el
                         FROM chat_mensajes WHERE id_mensaje = %s""", (id_mensaje,))
        m = cur.fetchone()
        c = conversacion(cur, int(m["id_conversacion"])) if m else None
    if not m or not c or not m["adjunto_archivo"] or m["borrado_el"] is not None:
        return "No existe ese archivo o no participás de la conversación.", 404
    ruta = ruta_adjunto(m["adjunto_archivo"])
    ext = Path(m["adjunto_archivo"]).suffix.lstrip(".")
    if ruta is None or ext not in TIPOS:
        abort(404)
    mime, en_linea = TIPOS[ext]
    como_descarga = not en_linea or request.args.get("bajar") == "1"
    ruta = almacenamiento.local(ruta)          # después de un deploy, lo trae del bucket
    if not ruta.is_file():
        return "El archivo no está en el disco ni en el bucket.", 404
    r = send_file(ruta, mimetype=mime, as_attachment=como_descarga,
                  download_name=m["adjunto_nombre"], conditional=True, max_age=0)
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Cache-Control"] = "private, no-store"
    return r
