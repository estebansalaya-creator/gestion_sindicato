"""
ben_campanias.py — Beneficios › Campañas (pedido del 17/11/2026).

«Una opción dentro del menú de beneficios donde se puedan cargar flyers de
campañas que se puedan enviar por correo a los afiliados.»

  · Una campaña (`ben_campania`) es el flyer (imagen o PDF), el asunto, el texto
    y a quién va: los titulares activos, titulares y familiares activos, los
    adheridos de un convenio (los de la nómina de este mes) o una LISTA ARMADA
    CON LOS FILTROS DEL PADRÓN (pedido del 17/11/2026; los mismos de Consulta del
    Padrón: buscar, estado, titular o familiar, sexo, edad, atributo). Los filtros
    se guardan en la campaña (`filtro`, JSON) y la lista se arma con ellos al
    mandarla; desde la Consulta del Padrón, «Campaña con estos filtros» la abre
    con los filtros que se están mirando. La ficha baja la lista en Excel.
  · Las direcciones salen de los CONTACTOS del afiliado (`s_contactos`,
    entidad «afiliado»: vinieron de AEDA): `p_afiliados` no tiene columna de
    correo. Una por afiliado (la principal o la primera), sin repetir
    direcciones, sin las que pidieron no recibir más (`ben_baja_correo`).
  · Sale por el CORREO SALIENTE del sistema (mailer.py, la cuenta de Correo
    Saliente), un mail por destinatario —nunca una lista en copia—, con el
    flyer dentro del mensaje si es una imagen (y adjunto si es un PDF) y al pie
    el enlace para no recibir más (Ley 25.326). Queda en el registro de envíos.
  · Mandar a 2.800 direcciones lleva tiempo y choca con el límite de 24 horas
    de la cuenta: al ENVIAR se arma la lista (`ben_campania_envio`, un renglón
    por dirección) y la manda un hilo en segundo plano, de a una. Si se llega al
    límite o la cuenta falla, la campaña queda PAUSADA con el motivo y se
    REANUDA desde donde quedó (la lista está en la base: un reinicio de la web
    no pierde nada). Mientras tanto la ficha muestra el avance.
  · Antes, «Enviarme una prueba» la manda a una dirección cualquiera, sin tocar la lista.

Pantallas (blueprint `ben_camp`, /beneficios/campanias, menú 127):
  lista · /nueva · /<id> ficha · /<id>/editar · /<id>/flyer · /<id>/probar ·
  /<id>/enviar · /<id>/pausar · /<id>/reanudar · /<id>/cancelar · /<id>/estado (JSON)
El padrón de entrega del beneficio (quién retiró la caja navideña…) está en ben_entregas.py.
Pública, sin sesión: /beneficios/baja/<token> (no recibir más).
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import html
import logging
import os
import re
import threading
import time
import uuid
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, send_file,
                   url_for)

import almacenamiento
import exportar
import mailer
from db import get_connection, puede, usuario_actual, validasesion

log = logging.getLogger(__name__)

ben_camp_bp = Blueprint("ben_camp", __name__, url_prefix="/beneficios")

URL = "/beneficios/campanias"
SQL_ESQUEMA = "sql/beneficios_correo_20261117.sql"
CODIGO = "campania"          # mail_envios.codigo
MAX_MB = 5
EXTENSIONES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
               ".webp": "image/webp", ".pdf": "application/pdf"}
#: Entre mail y mail: Gmail no quiere ráfagas.
PAUSA_SEGUNDOS = 1.0
#: Tantos errores seguidos es que algo anda mal con la cuenta: se pausa.
ERRORES_SEGUIDOS_MAX = 10

DESTINOS = {
    "titulares": "Titulares activos",
    "todos": "Titulares y familiares activos",
    "adheridos": "Adheridos de un convenio (nómina de este mes)",
    "padron": "Según los filtros del padrón",
}
#: Los filtros del padrón que se guardan en la campaña (afiliados._filtros_listado).
FILTROS = ("q", "estado", "tipo", "sexo", "edad_desde", "edad_hasta", "atributo")
SQL_ESQUEMA_PADRON = "sql/beneficios_campanias_padron_20261117.sql"
ESTADOS = {
    "borrador": ("Borrador", "neutro"),
    "enviando": ("Enviando", "proceso"),
    "pausada": ("Pausada", "warn"),
    "enviada": ("Enviada", "ok"),
    "cancelada": ("Cancelada", "danger"),
}

_LOCK = threading.Lock()
_CORRIENDO: set[int] = set()


class ErrorCampania(ValueError):
    """Un error de validación: el texto va directo a la pantalla."""


# =============================================================================
# El mensaje (sin base: lo prueba tests/test_ben_campanias.py)
# =============================================================================

def _clave() -> bytes:
    return (os.getenv("SIND_SECRET_KEY") or "sin-clave").encode()


def token_baja(email: str, clave: bytes | None = None) -> str:
    """El enlace de «no recibir más» lleva la dirección y su firma: no se puede
    dar de baja a otro cambiando la URL."""
    e = (email or "").strip().lower()
    firma = hmac.new(clave or _clave(), e.encode(), hashlib.sha256).hexdigest()[:20]
    return base64.urlsafe_b64encode(e.encode()).decode().rstrip("=") + "." + firma


def email_de_token(token: str, clave: bytes | None = None) -> str | None:
    try:
        parte, firma = token.rsplit(".", 1)
        e = base64.urlsafe_b64decode(parte + "=" * (-len(parte) % 4)).decode()
    except Exception:                                        # noqa: BLE001 — token roto
        return None
    ok = hmac.new(clave or _clave(), e.encode(), hashlib.sha256).hexdigest()[:20]
    return e if hmac.compare_digest(ok, firma) else None


def texto_con_datos(texto: str, nombre: str | None) -> str:
    """El único dato que se reemplaza: {nombre} (el nombre de pila si se puede)."""
    return (texto or "").replace("{nombre}", (nombre or "").strip() or "afiliado/a")


def nombre_corto(apellido_nombres: str | None) -> str:
    """«PEREZ JUAN CARLOS» → «Juan Carlos» (apellido simple, como lo carga AEDA)."""
    partes = (apellido_nombres or "").split()
    return " ".join(p.capitalize() for p in partes[1:]) if len(partes) > 1 else (apellido_nombres or "").title()


def html_del_cuerpo(texto: str) -> str:
    """Párrafos y saltos de línea; los enlaces sueltos se vuelven clicables. Sin HTML del usuario."""
    out = []
    for par in re.split(r"\n\s*\n", (texto or "").strip()):
        t = html.escape(par).replace("\n", "<br>")
        t = re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', t)
        if t:
            out.append(f'<p style="margin:0 0 12px">{t}</p>')
    return "".join(out)


def armar_mensaje(camp: dict, dest: dict, de: dict, flyer: bytes | None, url_baja: str, institucion: str) -> EmailMessage:
    """El mail de un destinatario: texto, HTML con el flyer (imagen) o el PDF adjunto, y el pie de baja."""
    texto = texto_con_datos(camp.get("cuerpo") or "", nombre_corto(dest.get("nombre")))
    tipo = camp.get("flyer_tipo") or ""
    es_imagen = bool(flyer) and tipo.startswith("image/")
    pie_txt = (f"\n\n—\n{institucion}\nSi no querés recibir más estas novedades: {url_baja}")
    msg = EmailMessage()
    msg["From"] = formataddr((de.get("nombre") or "", de["email"]))
    msg["To"] = formataddr((dest.get("nombre") or "", dest["email"]))
    msg["Subject"] = camp["asunto"]
    if de.get("responder_a"):
        msg["Reply-To"] = de["responder_a"]
    msg["List-Unsubscribe"] = f"<{url_baja}>"
    msg.set_content(texto + ("\n\n(El flyer va adjunto.)" if flyer and not es_imagen else "") + pie_txt)
    cid = make_msgid(domain="sindicato")
    img = (f'<p style="margin:16px 0"><img src="cid:{cid[1:-1]}" alt="{html.escape(camp.get("titulo") or "")}" '
           f'style="max-width:100%;height:auto;border:0"></p>') if es_imagen else ""
    cuerpo_html = (f'<div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;color:#1f2937;max-width:640px">'
                   f'{html_del_cuerpo(texto)}{img}'
                   f'<hr style="border:0;border-top:1px solid #e5e7eb;margin:20px 0 10px">'
                   f'<p style="font-size:12px;color:#6b7280;margin:0">{html.escape(institucion)} · '
                   f'<a href="{html.escape(url_baja)}" style="color:#6b7280">No quiero recibir más estas novedades</a></p></div>')
    msg.add_alternative(cuerpo_html, subtype="html")
    if es_imagen:
        sub = tipo.split("/", 1)[1]
        msg.get_payload()[1].add_related(flyer, maintype="image", subtype=sub, cid=cid,
                                         filename=camp.get("flyer_nombre") or f"flyer.{sub}")
    elif flyer:
        msg.add_attachment(flyer, maintype="application", subtype="pdf", filename=camp.get("flyer_nombre") or "flyer.pdf")
    return msg


# =============================================================================
# Destinatarios
# =============================================================================

def hay_esquema(cur) -> bool:
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_schema = DATABASE()
                     AND table_name IN ('ben_campania', 'ben_campania_envio', 'ben_baja_correo')""")
    return int(cur.fetchone()["n"] or 0) == 3


def filtro_de(datos) -> dict:
    """Los filtros del padrón (de un formulario, de la URL o del JSON guardado),
    validados como los valida la Consulta del Padrón."""
    import afiliados
    f = afiliados._filtros_listado(datos or {})
    return {k: f[k] for k in FILTROS}


def describir_filtro(f: dict | None, atributos: dict | None = None) -> str:
    """«Activos · solo titulares · mujeres · 30 a 50 años · …», para la ficha y la lista."""
    if not f:
        return "Activos del padrón"
    partes = [{"activo": "Activos", "baja": "Bajas", "todos": "Activos y bajas"}.get(f.get("estado"), "Activos")]
    partes += [{"titular": "solo titulares", "familiar": "solo familiares"}[f["tipo"]]] if f.get("tipo") else []
    partes += [{"F": "femenino", "M": "masculino", "X": "sexo X", "-": "sin sexo cargado"}[f["sexo"]]] if f.get("sexo") else []
    d, h = f.get("edad_desde"), f.get("edad_hasta")
    if d is not None or h is not None:
        partes.append(f"{d} a {h} años" if d is not None and h is not None
                      else (f"{d} años o más" if d is not None else f"hasta {h} años"))
    a = f.get("atributo") or ""
    if a == "con":
        partes.append("con algún atributo")
    elif a == "sin":
        partes.append("sin atributos")
    elif a:
        partes.append("atributo «" + str((atributos or {}).get(int(a), a)) + "»")
    if f.get("q"):
        partes.append(f"«{f['q']}»")
    return " · ".join(partes)


def _filtro_guardado(camp: dict) -> dict | None:
    import json
    v = camp.get("filtro")
    if not v:
        return None
    return filtro_de(json.loads(v) if isinstance(v, (str, bytes)) else v)


def atributos_activos(cur) -> list[dict]:
    try:
        cur.execute("SELECT id, rotulo FROM p_afiliado_atributo WHERE activo = 1 ORDER BY rotulo")
        return cur.fetchall()
    except Exception:                                        # noqa: BLE001
        return []


def personas(cur, destino: str, id_convenio: int | None = None, filtro: dict | None = None) -> list[dict]:
    """[{id_afiliado, apellido_nombres}]: las personas del grupo elegido en «A quién
    va», tengan o no correo. Es la lista del correo antes de mirar las direcciones
    y la del padrón de entrega del beneficio (ben_entregas.py)."""
    if destino == "padron":
        import afiliados
        where, params = afiliados._where_listado({**filtro_de({}), **(filtro or {})})
        cur.execute(f"SELECT a.id_afiliado, a.apellido_nombres {afiliados.SQL_LISTADO_FROM} {where}", params)
    elif destino == "adheridos":
        if not id_convenio:
            raise ErrorCampania("Elegí el convenio.")
        mes = datetime.date.today().strftime("%Y%m")
        cur.execute("""SELECT DISTINCT a.id_afiliado, a.apellido_nombres FROM ben_adherido b
                         JOIN p_afiliados a ON a.id_afiliado = b.id_afiliado
                        WHERE b.id_convenio = %s AND b.periodo_desde <= %s
                          AND (b.periodo_hasta IS NULL OR b.periodo_hasta >= %s)""", (id_convenio, mes, mes))
    else:
        cur.execute(f"""SELECT a.id_afiliado, a.apellido_nombres FROM p_afiliados a
                         WHERE (a.fecha_baja IS NULL OR a.fecha_baja > CURDATE())
                           {"AND a.cod_parentesco = 0" if destino == "titulares" else ""}""")
    return cur.fetchall()


def destinatarios(cur, destino: str, id_convenio: int | None = None,
                  filtro: dict | None = None) -> tuple[list[dict], dict]:
    """[{id_afiliado, nombre, email}] sin direcciones repetidas ni dadas de baja,
    y la cuenta: {"personas", "sin_correo", "baja", "repetidas"}."""
    grupo = personas(cur, destino, id_convenio, filtro)
    cur.execute("""SELECT entidad_id, email FROM s_contactos
                    WHERE entidad_tipo = 'afiliado' AND activo = 1 AND email LIKE '%@%'
                    ORDER BY principal DESC, id""")
    correo: dict[int, str] = {}
    for c in cur.fetchall():
        e = (c["email"] or "").strip().lower()
        if mailer.RE_EMAIL.match(e):
            correo.setdefault(c["entidad_id"], e)
    cur.execute("SELECT LOWER(email) AS e FROM ben_baja_correo")
    bajas = {r["e"] for r in cur.fetchall()}
    out, vistos = [], set()
    cuenta = {"personas": len(grupo), "sin_correo": 0, "baja": 0, "repetidas": 0}
    for p in grupo:
        e = correo.get(p["id_afiliado"])
        if not e:
            cuenta["sin_correo"] += 1
        elif e in bajas:
            cuenta["baja"] += 1
        elif e in vistos:
            cuenta["repetidas"] += 1
        else:
            vistos.add(e)
            out.append({"id_afiliado": p["id_afiliado"], "nombre": p["apellido_nombres"], "email": e})
    return out, cuenta


# =============================================================================
# Archivos
# =============================================================================

def _base() -> Path:
    return almacenamiento.base()


def ruta_flyer(camp: dict) -> Path | None:
    rel = camp.get("flyer_archivo")
    if not rel:
        return None
    base = _base().resolve()
    real = (base / rel).resolve()
    if base not in real.parents:
        return None
    real = almacenamiento.local(real)      # el envío en segundo plano también lo encuentra
    return real if real.exists() else None


def _guardar_flyer(archivo) -> tuple[str, str, str]:
    original = Path(archivo.filename or "").name.strip() or "flyer"
    ext = Path(original).suffix.lower()
    if ext not in EXTENSIONES:
        raise ErrorCampania(f"{original}: el flyer tiene que ser una imagen (PNG, JPG, GIF, WEBP) o un PDF.")
    carpeta = _base() / "campanias"
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre = uuid.uuid4().hex + ext
    destino = carpeta / nombre
    archivo.save(destino)
    tam = destino.stat().st_size
    if not tam or tam > MAX_MB * 1024 * 1024:
        destino.unlink(missing_ok=True)
        raise ErrorCampania(f"{original}: " + ("está vacío." if not tam else f"supera los {MAX_MB} MB."))
    almacenamiento.respaldar(destino, tipo_mime=EXTENSIONES[ext])
    return f"campanias/{nombre}", original[:200], EXTENSIONES[ext]


# =============================================================================
# El envío, en segundo plano
# =============================================================================

def url_publica() -> str:
    base = os.getenv("SIND_URL_PUBLICA", "").strip().rstrip("/")
    return base or request.url_root.rstrip("/")


def _institucion(cur) -> str:
    try:
        cur.execute("SELECT nombre, sigla FROM s_institucion WHERE id = 1")
        i = cur.fetchone() or {}
        return i.get("nombre") or i.get("sigla") or "El sindicato"
    except Exception:                                        # noqa: BLE001
        return "El sindicato"


def puede_eliminar(camp: dict, en_curso: bool = False) -> str | None:
    """Por qué no se puede eliminar la campaña (None = se puede).

    No mientras se envía (hay un hilo leyendo la lista) ni con padrón de entrega:
    se perdería quién retiró el beneficio (ben_entrega cae en cascada)."""
    if camp.get("estado") == "enviando" or en_curso:
        return "La campaña se está enviando: pausala o cancelala antes de eliminarla."
    if camp.get("entrega_generada"):
        return "La campaña tiene padrón de entrega: no se elimina (se perdería quién retiró)."
    return None


def corriendo(id_camp: int) -> bool:
    with _LOCK:
        return id_camp in _CORRIENDO


def empezar(id_camp: int, base_url: str, uid) -> bool:
    """Arranca el hilo de la campaña si no está corriendo en este proceso."""
    with _LOCK:
        if id_camp in _CORRIENDO:
            return False
        _CORRIENDO.add(id_camp)
    threading.Thread(target=_tanda, args=(id_camp, base_url, uid), daemon=True, name=f"campania-{id_camp}").start()
    return True


def _tanda(id_camp: int, base_url: str, uid, pausa: float = PAUSA_SEGUNDOS) -> None:
    seguidos = 0
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM ben_campania WHERE id = %s", (id_camp,))
                camp = cur.fetchone()
                institucion = _institucion(cur)
            conn.commit()
            ruta = ruta_flyer(camp)
            flyer = ruta.read_bytes() if ruta else None
            de = mailer.remitente(conn, {})
            while True:
                with conn.cursor() as cur:
                    cur.execute("SELECT estado FROM ben_campania WHERE id = %s", (id_camp,))
                    if (cur.fetchone() or {}).get("estado") != "enviando":
                        return                      # la pausaron o la cancelaron
                    cur.execute("""SELECT * FROM ben_campania_envio WHERE id_campania = %s AND estado = 'pendiente'
                                    ORDER BY id LIMIT 1""", (id_camp,))
                    dest = cur.fetchone()
                conn.commit()
                if not dest:
                    with conn.cursor() as cur:
                        cur.execute("""UPDATE ben_campania SET estado = 'enviada', envio_hasta = NOW(), nota = NULL
                                        WHERE id = %s AND estado = 'enviando'""", (id_camp,))
                    conn.commit()
                    return
                url_baja = f"{base_url}/beneficios/baja/{token_baja(dest['email'])}"
                msg = armar_mensaje(camp, dest, de, flyer, url_baja, institucion)
                try:
                    r = mailer.entregar(conn, msg, codigo=CODIGO, entidad_tipo="afiliado", entidad_id=dest["id_afiliado"],
                                        origen_tipo="campania", origen_id=id_camp, id_usuario=uid,
                                        cuerpo_log=texto_con_datos(camp.get("cuerpo") or "", nombre_corto(dest["nombre"])),
                                        adjuntos_log=camp.get("flyer_nombre"), de=de)
                except mailer.MailError as e:
                    _pausar(conn, id_camp, str(e))
                    return
                with conn.cursor() as cur:
                    cur.execute("UPDATE ben_campania_envio SET estado = %s, error = %s, enviado_at = NOW() WHERE id = %s",
                                ("ok" if r["estado"] == "ok" else "error", r["error"], dest["id"]))
                    cur.execute(f"UPDATE ben_campania SET {'enviados = enviados + 1' if r['estado'] == 'ok' else 'errores = errores + 1'} "
                                "WHERE id = %s", (id_camp,))
                conn.commit()
                seguidos = 0 if r["estado"] == "ok" else seguidos + 1
                if seguidos >= ERRORES_SEGUIDOS_MAX:
                    _pausar(conn, id_camp, f"{seguidos} errores seguidos; el último: {r['error']}")
                    return
                if pausa:
                    time.sleep(pausa)
    except Exception as e:                                   # noqa: BLE001
        log.exception("Campaña %s", id_camp)
        try:
            with get_connection() as conn:
                _pausar(conn, id_camp, f"Se cortó: {e}")
        except Exception:                                    # noqa: BLE001
            log.exception("No se pudo pausar la campaña %s", id_camp)
    finally:
        with _LOCK:
            _CORRIENDO.discard(id_camp)


def _pausar(conn, id_camp: int, nota: str) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE ben_campania SET estado = 'pausada', nota = %s WHERE id = %s AND estado = 'enviando'",
                    (nota[:500], id_camp))
    conn.commit()


# =============================================================================
# Pantallas
# =============================================================================

def _guardia():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede(URL):
        flash("!No tenés permiso para las campañas.")
        return redirect(url_for("menu"))
    return None


def _uid():
    return (usuario_actual() or {}).get("id")


def _convenios(cur) -> list[dict]:
    try:
        cur.execute("SELECT id, nombre FROM ben_convenio WHERE activo = 1 ORDER BY nombre")
        return cur.fetchall()
    except Exception:                                        # noqa: BLE001 — sin la tabla
        return []


def _leer(cur, id_camp) -> dict:
    cur.execute("""SELECT c.*, u.nombre AS usuario, v.nombre AS convenio FROM ben_campania c
                     LEFT JOIN s_usuarios u ON u.id = c.id_usuario
                     LEFT JOIN ben_convenio v ON v.id = c.id_convenio WHERE c.id = %s""", (id_camp,))
    c = cur.fetchone()
    if not c:
        abort(404)
    return c


@ben_camp_bp.route("/campanias")
def lista():
    salida = _guardia()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            if not hay_esquema(cur):
                flash(f"!Falta correr {SQL_ESQUEMA}.")
                return render_template("beneficios/campanias.html", filas=[], estados=ESTADOS, destinos=DESTINOS, cfg={})
            cur.execute("""SELECT c.*, u.nombre AS usuario, v.nombre AS convenio,
                                  (SELECT COUNT(*) FROM ben_campania_envio e WHERE e.id_campania = c.id AND e.estado = 'pendiente') AS pendientes
                             FROM ben_campania c LEFT JOIN s_usuarios u ON u.id = c.id_usuario
                             LEFT JOIN ben_convenio v ON v.id = c.id_convenio
                            ORDER BY c.id DESC""")
            filas = cur.fetchall()
            cfg = mailer.config(conn)
            atributos = {a["id"]: a["rotulo"] for a in atributos_activos(cur)}
    for f in filas:
        f["corriendo"] = corriendo(f["id"])
        f["no_eliminar"] = puede_eliminar(f, f["corriendo"])
        f["filtro_txt"] = describir_filtro(_filtro_guardado(f), atributos) if f["destino"] == "padron" else None
    return render_template("beneficios/campanias.html", filas=filas, estados=ESTADOS, destinos=DESTINOS, cfg=cfg)


@ben_camp_bp.route("/campanias/nueva", methods=["GET", "POST"])
@ben_camp_bp.route("/campanias/<int:id_camp>/editar", methods=["GET", "POST"])
def editar(id_camp=None):
    salida = _guardia()
    if salida:
        return salida
    errores, camp, filtro = [], {}, None
    with get_connection() as conn:
        with conn.cursor() as cur:
            if not hay_esquema(cur):
                flash(f"!Falta correr {SQL_ESQUEMA}.")
                return redirect(url_for("ben_camp.lista"))
            convenios = _convenios(cur)
            if id_camp:
                camp = _leer(cur, id_camp)
                if camp["estado"] != "borrador":
                    flash("!Una campaña que ya se empezó a mandar no se cambia: hacé una nueva.")
                    return redirect(url_for("ben_camp.ficha", id_camp=id_camp))
            if request.method == "POST":
                f = request.form
                camp = {**camp, "titulo": " ".join((f.get("titulo") or "").split())[:150],
                        "asunto": " ".join((f.get("asunto") or "").split())[:200],
                        "cuerpo": (f.get("cuerpo") or "").strip()[:20000] or None,
                        "destino": f.get("destino") if f.get("destino") in DESTINOS else "titulares",
                        "id_convenio": f.get("id_convenio", type=int) if f.get("destino") == "adheridos" else None}
                filtro = filtro_de({k[2:]: v for k, v in f.items() if k.startswith("f_")}) \
                    if camp["destino"] == "padron" else None
                if camp["destino"] == "padron" and not _hay_columna_filtro(cur):
                    errores.append(f"Para mandar a una lista del padrón falta correr {SQL_ESQUEMA_PADRON}.")
                if not camp["titulo"]:
                    errores.append("Poné un título para reconocerla en la lista.")
                if not camp["asunto"]:
                    errores.append("El asunto es obligatorio.")
                if camp["destino"] == "adheridos" and not camp["id_convenio"]:
                    errores.append("Elegí el convenio.")
                archivo = request.files.get("flyer")
                nuevo = None
                if not errores and archivo and archivo.filename:
                    try:
                        nuevo = _guardar_flyer(archivo)
                    except ErrorCampania as e:
                        errores.append(str(e))
                if not errores and not (nuevo or camp.get("flyer_archivo")) and not camp["cuerpo"]:
                    errores.append("Cargá el flyer o el texto: el mail no puede ir vacío.")
                if not errores:
                    valores = [camp["titulo"], camp["asunto"], camp["cuerpo"], camp["destino"], camp["id_convenio"]]
                    try:
                        if id_camp:
                            cur.execute("""UPDATE ben_campania SET titulo = %s, asunto = %s, cuerpo = %s, destino = %s,
                                                  id_convenio = %s WHERE id = %s""", (*valores, id_camp))
                        else:
                            cur.execute("""INSERT INTO ben_campania (titulo, asunto, cuerpo, destino, id_convenio, id_usuario)
                                           VALUES (%s, %s, %s, %s, %s, %s)""", (*valores, _uid()))
                            id_camp = cur.lastrowid
                        if _hay_columna_filtro(cur):
                            import json
                            cur.execute("UPDATE ben_campania SET filtro = %s WHERE id = %s",
                                        (json.dumps(filtro, ensure_ascii=False) if filtro else None, id_camp))
                        if nuevo:
                            anterior = ruta_flyer(camp) if camp.get("flyer_archivo") else None
                            cur.execute("""UPDATE ben_campania SET flyer_archivo = %s, flyer_nombre = %s, flyer_tipo = %s
                                            WHERE id = %s""", (*nuevo, id_camp))
                        conn.commit()
                    except Exception:
                        conn.rollback()
                        if nuevo:
                            almacenamiento.borrar(_base() / nuevo[0])
                        raise
                    if nuevo and anterior:
                        almacenamiento.borrar(anterior)
                    flash("Campaña guardada. Mirá cómo queda y mandate una prueba antes de enviarla.")
                    return redirect(url_for("ben_camp.ficha", id_camp=id_camp))
                if nuevo:
                    almacenamiento.borrar(_base() / nuevo[0])
            atributos = atributos_activos(cur)
    if request.method == "GET":
        if not id_camp and request.args.get("destino") in DESTINOS:
            # «Campaña con estos filtros» de la Consulta del Padrón.
            camp = {"destino": request.args["destino"]}
            if camp["destino"] == "padron":
                filtro = filtro_de(request.args)
        else:
            filtro = _filtro_guardado(camp) if camp else None
    return render_template("beneficios/campania_form.html", camp=camp, errores=errores, destinos=DESTINOS,
                           convenios=convenios, max_mb=MAX_MB, filtro=filtro or filtro_de({}), atributos=atributos)


def _hay_columna_filtro(cur) -> bool:
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.columns WHERE table_schema = DATABASE()
                     AND table_name = 'ben_campania' AND column_name = 'filtro'""")
    return bool(cur.fetchone()["n"])


@ben_camp_bp.route("/campanias/contar")
def contar():
    """Cuántos le llegan con un destino y unos filtros (el formulario lo pregunta mientras se elige)."""
    if not validasesion() or not puede(URL):
        return jsonify({"error": "sin permiso"}), 403
    destino = request.args.get("destino") if request.args.get("destino") in DESTINOS else "titulares"
    filtro = filtro_de({k[2:]: v for k, v in request.args.items() if k.startswith("f_")}) if destino == "padron" else None
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                lista, cuenta = destinatarios(cur, destino, request.args.get("id_convenio", type=int), filtro)
    except ErrorCampania as e:
        return jsonify({"error": str(e)})
    return jsonify({"direcciones": len(lista), **cuenta})


@ben_camp_bp.route("/campanias/<int:id_camp>")
def ficha(id_camp):
    salida = _guardia()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            camp = _leer(cur, id_camp)
            cuenta, lista_dest = None, []
            if camp["estado"] == "borrador":
                try:
                    lista_dest, cuenta = destinatarios(cur, camp["destino"], camp["id_convenio"], _filtro_guardado(camp))
                except ErrorCampania as e:
                    flash("!" + str(e))
            atributos = {a["id"]: a["rotulo"] for a in atributos_activos(cur)}
            cur.execute("""SELECT estado, COUNT(*) AS n FROM ben_campania_envio WHERE id_campania = %s GROUP BY estado""",
                        (id_camp,))
            por_estado = {r["estado"]: r["n"] for r in cur.fetchall()}
            cur.execute("""SELECT * FROM ben_campania_envio WHERE id_campania = %s AND estado IN ('error', 'baja')
                            ORDER BY id LIMIT 500""", (id_camp,))
            con_error = cur.fetchall()
            cfg = mailer.config(conn)
            institucion = _institucion(cur)
    vista = html_del_cuerpo(texto_con_datos(camp.get("cuerpo") or "", "Juan"))
    return render_template("beneficios/campania.html", camp=camp, cuenta=cuenta, n_dest=len(lista_dest),
                           por_estado=por_estado, con_error=con_error, cfg=cfg, estados=ESTADOS, destinos=DESTINOS,
                           vista=vista, institucion=institucion, corriendo=corriendo(id_camp),
                           es_imagen=(camp.get("flyer_tipo") or "").startswith("image/"),
                           filtro_txt=describir_filtro(_filtro_guardado(camp), atributos) if camp["destino"] == "padron" else None)


@ben_camp_bp.route("/campanias/<int:id_camp>/flyer")
def flyer(id_camp):
    salida = _guardia()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            camp = _leer(cur, id_camp)
    ruta = ruta_flyer(camp)
    if not ruta:
        abort(404)
    return send_file(ruta, mimetype=camp.get("flyer_tipo"), download_name=camp.get("flyer_nombre") or ruta.name)


@ben_camp_bp.route("/campanias/<int:id_camp>/probar", methods=["POST"])
def probar(id_camp):
    salida = _guardia()
    if salida:
        return salida
    destino = (request.form.get("destino") or "").strip().lower()
    if not mailer.RE_EMAIL.match(destino):
        flash("!La dirección de prueba no es válida.")
        return redirect(url_for("ben_camp.ficha", id_camp=id_camp))
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                camp = _leer(cur, id_camp)
                institucion = _institucion(cur)
            ruta = ruta_flyer(camp)
            de = mailer.remitente(conn, {})
            camp_prueba = {**camp, "asunto": "[PRUEBA] " + camp["asunto"]}
            msg = armar_mensaje(camp_prueba, {"email": destino, "nombre": (usuario_actual() or {}).get("nombre")}, de,
                                ruta.read_bytes() if ruta else None, f"{url_publica()}/beneficios/baja/{token_baja(destino)}",
                                institucion)
            r = mailer.entregar(conn, msg, codigo=CODIGO, origen_tipo="campania_prueba", origen_id=id_camp,
                                id_usuario=_uid(), cuerpo_log=camp.get("cuerpo"), adjuntos_log=camp.get("flyer_nombre"),
                                de=de)
        flash(f"Prueba enviada a {destino}." if r["estado"] == "ok" else f"!La prueba no salió: {r['error']}")
    except mailer.MailError as e:
        flash("!" + str(e))
    return redirect(url_for("ben_camp.ficha", id_camp=id_camp))


@ben_camp_bp.route("/campanias/<int:id_camp>/enviar", methods=["POST"])
def enviar(id_camp):
    """Arma la lista (una vez) y arranca el envío en segundo plano."""
    salida = _guardia()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            cfg = mailer.config(conn)
            camp = _leer(cur, id_camp)
            if camp["estado"] != "borrador":
                flash("!Esa campaña ya se envió o se está enviando.")
                return redirect(url_for("ben_camp.ficha", id_camp=id_camp))
            if not cfg.get("activo") or not cfg.get("host"):
                flash("!El correo saliente no está configurado o está apagado (Administración del Sistema › Correo Saliente).")
                return redirect(url_for("ben_camp.ficha", id_camp=id_camp))
            try:
                lista_dest, _ = destinatarios(cur, camp["destino"], camp["id_convenio"], _filtro_guardado(camp))
            except ErrorCampania as e:
                flash("!" + str(e))
                return redirect(url_for("ben_camp.ficha", id_camp=id_camp))
            if not lista_dest:
                flash("!No hay a quién mandarle: nadie de ese grupo tiene correo cargado en sus contactos.")
                return redirect(url_for("ben_camp.ficha", id_camp=id_camp))
            cur.executemany("""INSERT IGNORE INTO ben_campania_envio (id_campania, id_afiliado, email, nombre)
                               VALUES (%s, %s, %s, %s)""",
                            [(id_camp, d["id_afiliado"], d["email"], (d["nombre"] or "")[:150]) for d in lista_dest])
            cur.execute("""UPDATE ben_campania SET estado = 'enviando', total = %s, envio_desde = NOW(), nota = NULL
                            WHERE id = %s AND estado = 'borrador'""", (len(lista_dest), id_camp))
        conn.commit()
    empezar(id_camp, url_publica(), _uid())
    flash(f"Envío empezado: {len(lista_dest)} direcciones, de a una. La pantalla muestra el avance; se puede cerrar.")
    return redirect(url_for("ben_camp.ficha", id_camp=id_camp))


@ben_camp_bp.route("/campanias/<int:id_camp>/<accion>", methods=["POST"])
def cambiar(id_camp, accion):
    salida = _guardia()
    if salida:
        return salida
    if accion not in ("pausar", "reanudar", "cancelar", "borrar"):
        abort(404)
    with get_connection() as conn:
        with conn.cursor() as cur:
            camp = _leer(cur, id_camp)
            if accion == "pausar" and camp["estado"] == "enviando":
                cur.execute("UPDATE ben_campania SET estado = 'pausada', nota = 'La pausó un usuario.' WHERE id = %s", (id_camp,))
                flash("Campaña pausada: termina el mail que está saliendo y se detiene.")
            elif accion == "reanudar" and camp["estado"] in ("pausada", "enviando"):
                cur.execute("UPDATE ben_campania SET estado = 'enviando', nota = NULL WHERE id = %s", (id_camp,))
                conn.commit()
                flash("Envío reanudado desde donde quedó." if empezar(id_camp, url_publica(), _uid())
                      else "Ya se está enviando.")
            elif accion == "cancelar" and camp["estado"] in ("pausada", "enviando"):
                cur.execute("UPDATE ben_campania SET estado = 'cancelada', envio_hasta = NOW() WHERE id = %s", (id_camp,))
                flash("Campaña cancelada: lo que faltaba no se manda.")
            elif accion == "borrar":
                # Se elimina en cualquier estado salvo mientras sale (pedido del 23/11/2026).
                # La lista (ben_campania_envio) se va con ella por la FK; lo que salió queda
                # en mail_envios (Correo Saliente › Envíos), que no tiene FK a la campaña.
                motivo = puede_eliminar(camp, corriendo(id_camp))
                if motivo:
                    flash("!" + motivo)
                else:
                    cur.execute("DELETE FROM ben_campania WHERE id = %s", (id_camp,))
                    conn.commit()
                    if camp.get("flyer_archivo"):
                        almacenamiento.borrar(_base() / camp["flyer_archivo"])
                    flash("Borrador eliminado." if camp["estado"] == "borrador" else
                          f"Campaña «{camp['titulo']}» eliminada. Los correos que salieron siguen en Correo Saliente › Envíos.")
                    return redirect(url_for("ben_camp.lista"))
            else:
                flash("!No se puede hacer eso en el estado en que está.")
        conn.commit()
    return redirect(url_for("ben_camp.ficha", id_camp=id_camp))


@ben_camp_bp.route("/campanias/<int:id_camp>/lista.xlsx")
def lista_xlsx(id_camp):
    """A quiénes le llega (borrador) o le llegó (ya enviada), en Excel."""
    salida = _guardia()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            camp = _leer(cur, id_camp)
            if camp["estado"] == "borrador":
                lista, _ = destinatarios(cur, camp["destino"], camp["id_convenio"], _filtro_guardado(camp))
                filas = [[d["nombre"], d["email"], ""] for d in lista]
            else:
                cur.execute("""SELECT nombre, email, estado, enviado_at FROM ben_campania_envio
                                WHERE id_campania = %s ORDER BY nombre""", (id_camp,))
                filas = [[r["nombre"], r["email"], {"ok": "Enviado", "error": "Error", "baja": "Pidió la baja",
                                                     "pendiente": "Pendiente"}[r["estado"]]] for r in cur.fetchall()]
    contenido = exportar.xlsx("Lista", [{"titulo": "Apellido y nombres"}, {"titulo": "Correo"}, {"titulo": "Estado"}],
                              filas, encabezado=[f"Campaña: {camp['titulo']}", ""])
    from flask import Response
    nombre = re.sub(r"[^\w\- ]", "", camp["titulo"])[:60].strip() or f"campania_{id_camp}"
    return Response(contenido, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="Lista {nombre}.xlsx"'})


@ben_camp_bp.route("/campanias/<int:id_camp>/estado")
def estado(id_camp):
    if not validasesion() or not puede(URL):
        return jsonify({"error": "sin permiso"}), 403
    with get_connection() as conn:
        with conn.cursor() as cur:
            camp = _leer(cur, id_camp)
            cur.execute("SELECT COUNT(*) AS n FROM ben_campania_envio WHERE id_campania = %s AND estado = 'pendiente'",
                        (id_camp,))
            pend = cur.fetchone()["n"]
    return jsonify({"estado": camp["estado"], "total": camp["total"], "enviados": camp["enviados"],
                    "errores": camp["errores"], "pendientes": pend, "nota": camp["nota"], "corriendo": corriendo(id_camp)})


# ── Pública: no recibir más ──────────────────────────────────────────────────

@ben_camp_bp.route("/baja/<token>", methods=["GET", "POST"])
def baja(token):
    """Sin sesión: la dirección sale del token firmado. GET pregunta, POST registra
    (un lector de correo que «abre» los enlaces no da de baja a nadie)."""
    email = email_de_token(token)
    if not email:
        return render_template("beneficios/baja.html", email=None, hecho=False, institucion=None), 404
    hecho = False
    with get_connection() as conn:
        with conn.cursor() as cur:
            institucion = _institucion(cur)
            if request.method == "POST":
                cur.execute("""INSERT INTO ben_baja_correo (email, origen) VALUES (%s, 'enlace')
                               ON DUPLICATE KEY UPDATE fecha = fecha""", (email,))
                cur.execute("UPDATE ben_campania_envio SET estado = 'baja' WHERE email = %s AND estado = 'pendiente'", (email,))
                conn.commit()
                hecho = True
            else:
                cur.execute("SELECT 1 FROM ben_baja_correo WHERE email = %s", (email,))
                hecho = bool(cur.fetchone())
    return render_template("beneficios/baja.html", email=email, hecho=hecho, institucion=institucion)
