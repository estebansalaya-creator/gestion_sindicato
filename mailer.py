# -*- coding: utf-8 -*-
"""
mailer.py — Envío de avisos por mail
=====================================

Copia del de gestion_adm (OSEDA), pedido del 17/11/2026: «configurar correo
saliente como en oseda». Mismas tablas (`mail_config`, `mail_remitentes`,
`mail_tipos`, `mail_tipo_copias`, `mail_envios`, que vinieron con la base) y la
misma pantalla (Administración del Sistema › Correo Saliente, correo.py). La
clave de cifrado es `SIND_FERNET_KEY` (secretos.py). Lo propio del sindicato:
`entregar()`, que manda un mensaje ya armado y lo registra —lo usan las
campañas de Beneficios (ben_campanias.py), que llevan HTML y el flyer—, y
`p_afiliados` sin columna de correo: el del afiliado sale de sus contactos.

Todo lo que sale va hacia afuera: afiliados, empresas y proveedores. No hay
avisos internos, así que el destinatario nunca se configura como una lista de
direcciones: sale del registro sobre el que se está avisando.

DE DONDE SALE EL DESTINATARIO
-----------------------------
De `s_contactos`, que es la tabla genérica de contactos —entidad_tipo,
entidad_id, con `area`, `cargo` y `principal`—. Y no de cualquiera: cada tipo
de aviso declara a qué contacto le escribe. Un proveedor puede tener uno de
Administración, que recibe los comprobantes, y otro de Cobranzas, que no tiene
por qué recibirlos.

El orden es: los contactos del área que pide el tipo, si no el principal, si no
la columna `email` del maestro. El último escalón existe porque hoy los
contactos están casi vacíos; el día que se carguen deja de usarse solo.

UNA SOLA CUENTA, MUCHOS REMITENTES
----------------------------------
Se manda por el SMTP de la obra social. Lo que cambia es el `From` que ve el
que recibe, según el área dueña del aviso o la persona que lo mandó. Eso exige
que el dominio autorice esas direcciones —SPF y DKIM—: si no, el mail sale, no
da error, y cae en spam. Es la clase de falla que se descubre cuando nadie
contesta.

Con Gmail, además, la cuenta sólo respeta un `From` que tenga agregado como
«Enviar correo como»; si no, lo cambia por el suyo sin avisar.

UN REMITENTE CON CUENTA PROPIA (2026-11-05)
-------------------------------------------
Un remitente puede tener su propia cuenta —`mail_remitentes.smtp_usuario` y
la contraseña de aplicación cifrada en `smtp_password_cif`—: el aviso que lo
usa sale por esa cuenta y no por la general. Mismo servidor, puerto y
seguridad que la general (es el mismo Google Workspace). Lo pidió Esteban
para que el instructivo a proveedores salga de verdad de sistemas@: queda en
los «Enviados» de esa casilla y usa su propio cupo de Gmail.

Si el remitente tiene usuario pero la contraseña falta o no se descifra, el
aviso NO sale por la cuenta general: daría un mail con otro remitente sin que
nadie se entere. Da error y lo dice.

LAS PLANTILLAS SE EDITAN DESDE LA PANTALLA
------------------------------------------
Y por lo tanto se renderizan en un entorno restringido de Jinja. Una plantilla
editable es código que ejecuta el servidor: con el entorno común, un `{{
''.__class__.__mro__ }}` abre la puerta a leer o correr cualquier cosa. El
`SandboxedEnvironment` bloquea el acceso a atributos internos. Sólo la editan
administradores, pero eso es un control de acceso, no una defensa.

NO MANDA NADA SI NO ESTA ENCENDIDO
----------------------------------
`mail_config.activo` arranca en 0. Un sistema que empieza a mandar mails a
4.635 afiliados porque alguien probó un botón es peor que uno que no manda.
"""

from __future__ import annotations

import datetime
import errno
import logging
import re
import smtplib
import socket
import time
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from pathlib import Path

from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

log = logging.getLogger(__name__)

#: Solo ASCII imprimible: «!» a «?» y «A» a «~» (todo menos el espacio, la arroba y lo que no es
#: ASCII). Una «ñ» o un acento no van en una dirección de correo: smtplib ni siquiera arma el
#: encabezado (`formataddr` levanta UnicodeEncodeError) y Gmail o Hotmail no los aceptan. Pasó el
#: 24/11/2026 con «jibañez@…», que cortó la campaña entera.
RE_EMAIL = re.compile(r"^[!-?A-~]+@[!-?A-~]+\.[!-?A-~]+$")

# El maestro de cada clase de entidad, para el respaldo cuando no hay contacto
# cargado. `c_proveedores` no tiene columna de mail: por eso no está.
# (tabla, primary key, columna del mail, expresión del nombre).
#
# `p_afiliados` NO tiene `id`: su clave es `id_afiliado`. `p_empresas` sí. Es
# lo que guarda `s_contactos.entidad_id`, y confundirlas hace que el aviso
# salga a la dirección de otra persona, que es peor que no salir.
#
# En el sindicato `p_afiliados` no tiene columna de correo: el del afiliado está
# solo en sus contactos (s_contactos, vinieron de AEDA).
MAESTROS = {
    "empresa":  ("p_empresas", "id", "email", "razon_social"),
}


class MailError(Exception):
    """Algo impide mandar. El mensaje se le muestra a la persona."""


class MailConexionError(MailError):
    """El servidor no deja mandar: no responde, corta la conexión o frena a la
    cuenta (el límite de Gmail). No es culpa del destinatario: con el siguiente
    pasaría lo mismo.

    Hasta el 24/11/2026 esto quedaba como error DEL DESTINATARIO: una campaña
    marcaba a diez afiliados con «Connection unexpectedly closed», se pausaba, y
    al reanudarla marcaba a otros diez. Esos afiliados no se vuelven a intentar
    (se manda a los pendientes), así que se quedaban sin el mail. Ahora la
    campaña se pausa en el primero y él queda pendiente.
    """


# ===========================================================================
# Configuración
# ===========================================================================

def config(conn) -> dict:
    """La cuenta con la que se manda, con la clave ya descifrada."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM mail_config WHERE id = 1")
        cfg = cur.fetchone() or {}

    cfg["password"] = ""
    if cfg.get("password_cif"):
        try:
            from secretos import descifrar_secret
            cfg["password"] = descifrar_secret(cfg["password_cif"])
        except Exception as e:
            # No se propaga: la pantalla de configuración tiene que poder
            # abrirse para arreglar justamente esto. Se avisa al usar.
            log.error("No se pudo descifrar la clave del SMTP: %s", e)
            cfg["password_error"] = str(e)
    return cfg


def _validar_config(cfg: dict):
    if not cfg:
        raise MailError("No hay configuración de correo cargada.")
    if not cfg.get("activo"):
        raise MailError("El envío de mails está apagado. Un administrador "
                        "tiene que activarlo en la configuración de correo.")
    if not cfg.get("host"):
        raise MailError("Falta el servidor SMTP en la configuración de correo.")
    if cfg.get("password_error"):
        raise MailError(f"La clave del SMTP no se puede descifrar "
                        f"({cfg['password_error']}). Volvé a cargarla.")


# ===========================================================================
# Destinatarios
# ===========================================================================

def destinatarios(conn, tipo: dict, entidad_id: int) -> tuple[list[dict], str]:
    """A quién le llega este aviso, y de dónde salió la dirección.

    Devuelve la lista de {nombre, email} y una etiqueta del origen, que sirve
    para mostrarle a la persona por qué le va a llegar a esa dirección antes de
    apretar mandar.
    """
    ent = tipo["entidad_tipo"]
    id_area = tipo.get("id_contacto_area")

    with conn.cursor() as cur:
        # 1) Los contactos del área que pide el tipo. Se compara por id contra
        #    `c_areas_contacto`, no por texto: cuando era texto libre alcanzaba
        #    con que alguien escribiera «Admin.» o dejara un espacio adelante
        #    para que el aviso no le llegara a nadie, y sin que se notara.
        if id_area:
            cur.execute("""
                SELECT c.nombre, c.email, c.cargo, c.principal, a.nombre AS area
                  FROM s_contactos c
                  JOIN c_areas_contacto a ON a.id = c.id_area_contacto
                 WHERE c.entidad_tipo = %s AND c.entidad_id = %s
                   AND c.activo = 1 AND c.email IS NOT NULL AND c.email <> ''
                   AND c.id_area_contacto = %s
                 ORDER BY c.principal DESC, c.id
            """, (ent, entidad_id, id_area))
            filas = cur.fetchall()
            if filas:
                if not tipo.get("contacto_todos"):
                    filas = filas[:1]
                return [dict(nombre=f["nombre"], email=f["email"]) for f in filas], \
                       f"contacto de {filas[0]['area']}"

            if not tipo.get("contacto_respaldo"):
                cur.execute("SELECT nombre FROM c_areas_contacto WHERE id = %s", (id_area,))
                a = (cur.fetchone() or {}).get("nombre") or "esa área"
                return [], f"sin contacto de {a}"

        # 2) El principal, o todos si el tipo lo pide.
        cur.execute("""
            SELECT nombre, email, principal
              FROM s_contactos
             WHERE entidad_tipo = %s AND entidad_id = %s
               AND activo = 1 AND email IS NOT NULL AND email <> ''
             ORDER BY principal DESC, id
        """, (ent, entidad_id))
        filas = cur.fetchall()
        if filas:
            if not tipo.get("contacto_todos"):
                filas = filas[:1]
            return [dict(nombre=f["nombre"], email=f["email"]) for f in filas], \
                   "contacto principal"

        # 3) El mail del maestro. Es el escalón que hoy sostiene todo, porque
        #    los contactos están casi vacíos, y el que va a dejar de usarse
        #    solo a medida que se carguen.
        if ent in MAESTROS:
            tabla, pk, col, nombre_expr = MAESTROS[ent]
            cur.execute(f"""SELECT {col} AS email, {nombre_expr} AS nombre
                              FROM {tabla} WHERE {pk} = %s""", (entidad_id,))
            f = cur.fetchone() or {}
            if (f.get("email") or "").strip():
                return [dict(nombre=f.get("nombre") or "", email=f["email"].strip())], \
                       f"mail cargado en {tabla}"

    return [], "sin dirección"


def copias(conn, codigo: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("""SELECT email, modo FROM mail_tipo_copias
                        WHERE codigo = %s AND activo = 1""", (codigo,))
        return cur.fetchall()


# ===========================================================================
# Remitente
# ===========================================================================

def remitente(conn, tipo: dict, id_usuario: int = None,
              como_usuario: bool = False) -> dict:
    """El `From` del aviso: nombre, dirección, responder_a y firma.

    Manda el remitente propio del tipo. Si el tipo lo permite y se pidió
    expresamente, sale desde la dirección de la persona. Si no hay ninguno de
    los dos, el de la configuración general.
    """
    cfg = config(conn)

    if como_usuario and tipo.get("permite_remitente_usuario") and id_usuario:
        with conn.cursor() as cur:
            # `SELECT *`: trae la cuenta propia si la tabla ya tiene las
            # columnas (sql/mail_remitentes_cuenta_propia_20261105.sql), y
            # sigue andando si el SQL todavía no se corrió.
            cur.execute("""SELECT * FROM mail_remitentes
                            WHERE tipo = 'usuario' AND id_usuario = %s AND activo = 1
                            LIMIT 1""", (id_usuario,))
            r = cur.fetchone()
            if r and (r.get("email") or "").strip():
                return dict(r)
            # Sin remitente cargado, la dirección del propio usuario.
            cur.execute("SELECT nombre, email FROM s_usuarios WHERE id = %s",
                        (id_usuario,))
            u = cur.fetchone() or {}
            if (u.get("email") or "").strip():
                return {"nombre": u.get("nombre") or "", "email": u["email"],
                        "responder_a": None, "firma": None}

    if tipo.get("id_remitente"):
        with conn.cursor() as cur:
            cur.execute("""SELECT * FROM mail_remitentes WHERE id = %s AND activo = 1""",
                        (tipo["id_remitente"],))
            r = cur.fetchone()
            if r:
                return dict(r)

    return {"nombre": cfg.get("remitente_nombre") or "",
            "email": cfg.get("remitente_email") or cfg.get("usuario") or "",
            "responder_a": cfg.get("responder_a"), "firma": None}


# ===========================================================================
# Plantillas
# ===========================================================================

# Restringido a propósito: las plantillas las edita gente desde una pantalla,
# y una plantilla es código que corre en el servidor. Ver la nota de arriba.
_JINJA = SandboxedEnvironment(autoescape=False, undefined=StrictUndefined)


def render(texto: str, datos: dict) -> str:
    """Reemplaza las llaves de la plantilla con los datos del registro.

    Con `StrictUndefined`: si la plantilla usa un dato que no se pasó, falla
    en vez de mandar «Hola :» con el nombre vacío. Un mail mal armado que sale
    no se puede volver atrás.
    """
    try:
        return _JINJA.from_string(texto or "").render(**(datos or {}))
    except Exception as e:
        raise MailError(f"La plantilla no se pudo armar: {e}. Revisá que estén "
                        f"todos los datos que usa el texto.") from e


# ===========================================================================
# Envío
# ===========================================================================

def _direccion(nombre: str, email: str) -> str:
    return formataddr((nombre or "", email))


def _validar_direcciones(lista: list[dict]):
    malas = [d["email"] for d in lista
             if not RE_EMAIL.match((d.get("email") or "").strip())]
    if malas:
        raise MailError("Direcciones inválidas: " + ", ".join(malas))


def _limite_alcanzado(conn, cfg: dict) -> bool:
    """Freno de seguridad. Ver `mail_config.limite_diario`.

    Cuenta las últimas 24 horas, no el día calendario: es la ventana con la que
    cuenta Google (2.000 mensajes por casilla cada 24 horas móviles). Por día
    calendario dejaba mandar 1.000 a las 23 y otros 1.000 a la 1, que para
    Google son 2.000 en dos horas y la casilla queda bloqueada hasta un día.
    """
    tope = int(cfg.get("limite_diario") or 0)
    if tope <= 0:
        return False
    with conn.cursor() as cur:
        cur.execute("""SELECT COUNT(*) n FROM mail_envios
                        WHERE estado = 'ok' AND enviado_at >= NOW() - INTERVAL 24 HOUR""")
        return (cur.fetchone() or {}).get("n", 0) >= tope


def cuenta_de_envio(cfg: dict, de: dict) -> dict:
    """La cuenta por la que sale: la propia del remitente si tiene, si no la
    general. Devuelve la configuración que espera `_entregar`."""
    usuario = (de.get("smtp_usuario") or "").strip()
    if not usuario:
        return cfg
    cifrada = de.get("smtp_password_cif")
    if not cifrada:
        raise MailError(f"El remitente {de.get('email')} sale con la cuenta {usuario}, "
                        f"pero no tiene cargada la contraseña. Cargala en "
                        f"Configuración de correo › Remitentes.")
    try:
        from secretos import descifrar_secret
        clave = descifrar_secret(cifrada)
    except Exception as e:                                   # noqa: BLE001
        raise MailError(f"La contraseña de la cuenta {usuario} no se puede descifrar "
                        f"({e}). Volvé a cargarla en Configuración de correo › "
                        f"Remitentes.") from e
    return dict(cfg, usuario=usuario, password=clave)


def enviar(conn, codigo: str, entidad_id: int, datos: dict = None,
           adjuntos: list = None, id_usuario: int = None,
           como_usuario: bool = False, probar: bool = False,
           origen_tipo: str = None, origen_id: int = None,
           para_manual: list = None) -> dict:
    """Manda un aviso y lo deja registrado.

    `probar=True` arma todo y no manda: devuelve el mail como saldría. Sirve
    para la vista previa, que es lo único que evita descubrir un error de
    redacción después de mandarlo.

    `origen_tipo` / `origen_id` son de qué documento salió: `('orden_pago', 20521)`.
    Sin eso, dos comprobantes mandados al mismo proveedor quedan como dos filas
    idénticas y no hay forma de contestar «¿a este pago ya se lo mandé?». La
    entidad —el proveedor— dice a quién le llegó; el origen, por qué.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM mail_tipos WHERE codigo = %s AND activo = 1",
                    (codigo,))
        tipo = cur.fetchone()
    if not tipo:
        raise MailError(f"El aviso «{codigo}» no existe o está desactivado.")

    cfg = config(conn)
    if not probar:
        _validar_config(cfg)
        if _limite_alcanzado(conn, cfg):
            # «Se alcanzó el límite de» lo reconoce el envío programado para
            # dejar el aviso pendiente en vez de marcarlo con error.
            raise MailError(f"Se alcanzó el límite de {cfg['limite_diario']} "
                            f"mails en las últimas 24 horas. Es un freno de "
                            f"seguridad: Gmail corta en 2.000 y deja la casilla "
                            f"sin poder mandar hasta un día. Para mandar más, "
                            f"programalo en tandas.")

    # `para_manual` es para los documentos que no tienen a quién mandarle por
    # ficha: una orden de pago por concepto —una comisión, un impuesto— no
    # cuelga de ningún proveedor, y sin esto no había forma de mandarle el
    # comprobante a nadie. Se escribe la dirección al mandarlo.
    #
    # Queda registrado igual en `mail_envios`, con `entidad_id` en NULL: el
    # renglón del log dice a qué dirección salió y de qué documento, que es lo
    # que después hace falta para contestar «¿esto ya se mandó?».
    if para_manual:
        para, origen = list(para_manual), "dirección escrita a mano"
    else:
        para, origen = destinatarios(conn, tipo, entidad_id)
    if not para:
        raise MailError(f"No hay dirección de correo para este destinatario "
                        f"({origen}). Cargala en sus contactos.")
    _validar_direcciones(para)

    de = remitente(conn, tipo, id_usuario, como_usuario)
    if not (de.get("email") or "").strip():
        raise MailError("No hay remitente configurado para este aviso.")

    asunto = render(tipo["asunto"], datos)
    cuerpo = render(tipo["cuerpo"], datos)
    if de.get("firma"):
        cuerpo = f"{cuerpo}\n\n{de['firma']}"

    msg = EmailMessage()
    msg["From"] = _direccion(de.get("nombre"), de["email"])
    msg["To"] = ", ".join(_direccion(d.get("nombre"), d["email"]) for d in para)
    msg["Subject"] = asunto
    if de.get("responder_a"):
        msg["Reply-To"] = de["responder_a"]

    cc = [c for c in copias(conn, codigo) if c["modo"] == "cc"]
    cco = [c for c in copias(conn, codigo) if c["modo"] == "cco"]
    if cc:
        msg["Cc"] = ", ".join(c["email"] for c in cc)
    msg.set_content(cuerpo)

    nombres_adj = []
    import almacenamiento
    for ruta in (adjuntos or []):
        p = almacenamiento.local(ruta)
        if not p.is_file():
            raise MailError(f"No se encuentra el adjunto {p.name}.")
        msg.add_attachment(p.read_bytes(), maintype="application",
                           subtype="octet-stream", filename=p.name)
        nombres_adj.append(p.name)

    resultado = {"para": [d["email"] for d in para], "origen": origen,
                 "remitente": de["email"], "asunto": asunto, "cuerpo": cuerpo,
                 "adjuntos": nombres_adj, "copias": [c["email"] for c in cc + cco],
                 "cuenta": (de.get("smtp_usuario") or "").strip()
                           or cfg.get("usuario") or ""}

    if probar:
        resultado["estado"] = "prueba"
        return resultado

    cfg_envio = cuenta_de_envio(cfg, de)

    todos = [d["email"] for d in para] + [c["email"] for c in cc + cco]
    estado, error = "ok", None
    try:
        # `send_message` NO levanta excepción cuando el servidor rechaza a
        # ALGUNOS destinatarios: sólo cuando los rechaza a todos. Los parciales
        # vuelven en un diccionario {dirección: (código, motivo)} que antes se
        # descartaba, y el envío quedaba registrado como «ok» a secas.
        #
        # Es el peor de los tres finales posibles: el mail salió para dos de
        # tres, el tercero nunca se enteró, y en el log no había nada que lo
        # dijera. Ahora el rechazo queda escrito con el código y el motivo que
        # devolvió el servidor.
        rechazados = _entregar(cfg_envio, msg, todos) or {}
        if rechazados:
            detalle = "; ".join(
                f"{dir_}: {_texto_respuesta(resp)}" for dir_, resp in rechazados.items())
            error = f"El servidor no aceptó {len(rechazados)} de {len(todos)} destinatarios — {detalle}"[:600]
            log.warning("El aviso %s salió con rechazos parciales: %s", codigo, detalle)
    except Exception as e:
        estado, error = "error", str(e)[:600]
        log.exception("Enviando el aviso %s a %s", codigo, todos)

    # El registro va afuera de la transacción del llamador y no falla el envío:
    # si el mail salió, perder la anotación es molesto; hacer creer que no salió
    # y que alguien lo mande de nuevo es peor.
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO mail_envios
                    (codigo, entidad_tipo, entidad_id, origen_tipo, origen_id,
                     para, copias, remitente,
                     asunto, cuerpo, adjuntos, estado, error, id_usuario)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (codigo, tipo["entidad_tipo"], entidad_id,
                  origen_tipo, origen_id,
                  ", ".join(d["email"] for d in para)[:400],
                  ", ".join(c["email"] for c in cc + cco)[:400] or None,
                  de["email"], asunto[:300], cuerpo,
                  ", ".join(nombres_adj)[:600] or None, estado, error, id_usuario))
        conn.commit()
    except Exception:
        log.exception("No se pudo registrar el envío de %s", codigo)

    if estado == "error":
        raise MailError(f"No se pudo enviar: {error}")

    resultado["estado"] = "ok"
    return resultado


def entregar(conn, msg: EmailMessage, *, codigo: str, entidad_tipo: str | None = None,
             entidad_id: int | None = None, origen_tipo: str | None = None, origen_id: int | None = None,
             id_usuario: int | None = None, cuerpo_log: str | None = None, adjuntos_log: str | None = None,
             de: dict | None = None) -> dict:
    """Manda un mensaje ya armado (From, To, Subject, cuerpo) y lo registra en
    `mail_envios`. Lo usan las campañas, que arman su propio HTML con el flyer.

    Con la misma configuración, el mismo freno de 24 horas y el mismo registro
    que `enviar()`. Devuelve {"estado": "ok"|"error", "error": …}; un error de
    configuración o el límite levantan MailError (no tiene sentido seguir con
    el siguiente destinatario). Lo que es del servidor y no del destinatario
    (no responde, corta, frena a la cuenta) queda registrado y levanta
    MailConexionError, que también es MailError: la campaña se pausa y el
    destinatario sigue pendiente.
    """
    cfg = config(conn)
    _validar_config(cfg)
    if _limite_alcanzado(conn, cfg):
        raise MailError(f"Se alcanzó el límite de {cfg['limite_diario']} mails en las últimas 24 horas.")
    de = de or {"nombre": cfg.get("remitente_nombre") or "",
                "email": cfg.get("remitente_email") or cfg.get("usuario") or "",
                "responder_a": cfg.get("responder_a")}
    if not (de.get("email") or "").strip():
        raise MailError("No hay remitente configurado: completalo en Correo Saliente.")
    if not msg.get("From"):
        msg["From"] = _direccion(de.get("nombre"), de["email"])
    if de.get("responder_a") and not msg.get("Reply-To"):
        msg["Reply-To"] = de["responder_a"]
    destinos = [parseaddr(x)[1] for x in (msg.get("To") or "").split(",") if parseaddr(x)[1]]
    _validar_direcciones([{"email": d} for d in destinos])
    cfg_envio = cuenta_de_envio(cfg, de)
    estado, error, cortar = "ok", None, None
    try:
        rechazados = _entregar(cfg_envio, msg, destinos) or {}
        if rechazados:
            estado = "error"
            error = "; ".join(f"{d}: {_texto_respuesta(r)}" for d, r in rechazados.items())[:600]
    except smtplib.SMTPAuthenticationError as e:
        raise MailError(f"El servidor rechazó el usuario o la contraseña ({_texto_respuesta((e.smtp_code, e.smtp_error))}).") from e
    except MailConexionError as e:
        # Queda en el registro y se corta: el que llama (la campaña) se pausa y
        # este destinatario sigue pendiente.
        estado, error, cortar = "error", str(e)[:600], e
        log.warning("Enviando %s a %s: %s", codigo, destinos, e)
    except smtplib.SMTPRecipientsRefused as e:
        estado = "error"
        error = "; ".join(f"{d}: {_texto_respuesta(r)}" for d, r in e.recipients.items())[:600]
    except Exception as e:                                   # noqa: BLE001
        estado, error = "error", str(e)[:600]
        log.warning("Enviando %s a %s: %s", codigo, destinos, e)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO mail_envios
                    (codigo, entidad_tipo, entidad_id, origen_tipo, origen_id, para, copias, remitente,
                     asunto, cuerpo, adjuntos, estado, error, id_usuario)
                VALUES (%s,%s,%s,%s,%s,%s,NULL,%s,%s,%s,%s,%s,%s,%s)
            """, (codigo, entidad_tipo, entidad_id, origen_tipo, origen_id, ", ".join(destinos)[:400],
                  de["email"], (msg.get("Subject") or "")[:300], cuerpo_log, adjuntos_log, estado, error,
                  id_usuario))
        conn.commit()
    except Exception:                                        # noqa: BLE001
        log.exception("No se pudo registrar el envío de %s", codigo)
    if cortar:
        raise cortar
    return {"estado": estado, "error": error}


def _texto_respuesta(resp) -> str:
    """`(550, b'5.1.1 User unknown')` → `550 5.1.1 User unknown`.

    El servidor contesta en bytes y el código aparte. Guardarlo tal cual deja
    en la base un `(550, b'...')` que hay que traducir mentalmente cada vez.
    """
    try:
        codigo, texto = resp
        if isinstance(texto, (bytes, bytearray)):
            texto = texto.decode("utf-8", "replace")
        return f"{codigo} {texto}".strip()
    except Exception:                                        # noqa: BLE001
        return str(resp)


#: Los pasos de la conversación con el servidor: el error dice en cuál falló.
PASOS = {
    "conectar": "al conectar",
    "tls": "al iniciar el cifrado (STARTTLS)",
    "login": "al iniciar sesión",
    "remitente": "al presentar el remitente",
    "enviar": "al entregar el mensaje",
}

#: Qué suele ser, según el paso. Es lo que se le dice a la persona.
SUGERENCIAS = {
    "conectar": ("Suele ser la red desde donde sale el sistema: el puerto de correo bloqueado (Railway no deja "
                 "salir SMTP salvo en el plan Pro) o el servidor o el puerto mal cargados."),
    "tls": "Revisá la seguridad: con el puerto 587 va STARTTLS; con el 465, SSL.",
    "login": "Revisá el usuario y la contraseña de aplicación de la cuenta.",
    "remitente": ("Con Gmail suele ser el límite de envíos de la cuenta: se libera solo, 24 horas después de "
                  "los mails que lo llenaron."),
    "enviar": ("Con Gmail suele ser el límite de envíos de la cuenta: se libera solo, 24 horas después de "
               "los mails que lo llenaron."),
}


def _que_paso(e: BaseException) -> str:
    """La falla en castellano. El orden importa: las de smtplib son OSError."""
    if isinstance(e, smtplib.SMTPServerDisconnected):
        return "el servidor cortó la conexión sin responder"
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        resp = next(iter(e.recipients.values()), None)
        return f"el servidor respondió «{_texto_respuesta(resp)}»"
    if isinstance(e, smtplib.SMTPResponseException):
        return f"el servidor respondió «{_texto_respuesta((e.smtp_code, e.smtp_error))}»"
    if isinstance(e, TimeoutError):                         # socket.timeout también
        return "el servidor no respondió a tiempo"
    if isinstance(e, ConnectionRefusedError):
        return "la conexión fue rechazada"
    if isinstance(e, ConnectionResetError):
        return "la conexión se cortó del otro lado"
    if isinstance(e, socket.gaierror):
        return "no se encontró el servidor (el nombre no resuelve)"
    if isinstance(e, OSError) and e.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH):
        return "no hay salida de red hacia el servidor"
    return str(e) or type(e).__name__


def motivo_conexion(paso: str, servidor: str, e: BaseException) -> str:
    """`No se pudo mandar por smtp.gmail.com:587: el servidor cortó la conexión
    sin responder, al conectar. Suele ser…` — qué pasó, en qué paso y qué mirar."""
    texto = f"No se pudo mandar por {servidor}: {_que_paso(e)}, {PASOS.get(paso, paso)}."
    sugerencia = SUGERENCIAS.get(paso)
    return f"{texto} {sugerencia}" if sugerencia else texto


def _abrir(cfg: dict):
    """La conexión, como la usa el envío: (smtp, servidor). Puede fallar al conectar."""
    puerto = int(cfg.get("puerto") or 587)
    clase = smtplib.SMTP_SSL if (cfg.get("seguridad") or "starttls") == "ssl" else smtplib.SMTP
    return clase(cfg["host"], puerto, timeout=30)


def _servidor(cfg: dict) -> str:
    return f"{cfg.get('host')}:{int(cfg.get('puerto') or 587)}"


def _cerrar(smtp) -> None:
    if smtp is None:
        return
    try:
        smtp.quit()
    except Exception:                                        # noqa: BLE001
        pass


def _entregar(cfg: dict, msg: EmailMessage, destinos: list[str]):
    """La conexión con el servidor. Separado para poder simularlo al probar.

    Devuelve lo que devuelve `send_message`: el diccionario de destinatarios
    RECHAZADOS, vacío cuando el servidor los aceptó a todos. No se descarta
    porque un rechazo parcial no levanta excepción y es, si no, invisible.

    Lo que no es de los destinatarios —el servidor no responde, corta, no deja
    iniciar sesión por un rato, frena a la cuenta— sale como MailConexionError
    con el paso en que pasó: «Connection unexpectedly closed» a secas no dice
    si es la red, la cuenta o el límite. Usuario o contraseña rechazados siguen
    saliendo como SMTPAuthenticationError (`entregar` los traduce), y que el
    servidor rechace a TODOS los destinatarios, como SMTPRecipientsRefused.
    """
    servidor, paso, smtp = _servidor(cfg), "conectar", None
    try:
        smtp = _abrir(cfg)
        if (cfg.get("seguridad") or "starttls") == "starttls":
            paso = "tls"
            smtp.starttls()
        if cfg.get("usuario"):
            paso = "login"
            smtp.login(cfg["usuario"], cfg.get("password") or "")
        paso = "enviar"
        return smtp.send_message(msg, to_addrs=destinos)
    except smtplib.SMTPAuthenticationError:
        raise
    except smtplib.SMTPRecipientsRefused as e:
        # Los rechazó a todos: es de ellos (la dirección no existe), salvo un 421,
        # que es el servidor yéndose (Gmail lo usa para frenar ráfagas).
        if any((r or (0,))[0] == 421 for r in e.recipients.values()):
            raise MailConexionError(motivo_conexion(paso, servidor, e)) from e
        raise
    except (smtplib.SMTPException, OSError) as e:
        # Un rechazo del remitente o del mensaje (MAIL FROM, DATA) también es de la
        # cuenta o del mensaje, no del destinatario: Gmail avisa ahí su límite
        # diario («550 5.4.5 Daily user sending limit exceeded»).
        raise MailConexionError(motivo_conexion(paso, servidor, e)) from e
    finally:
        _cerrar(smtp)


def diagnosticar(conn) -> list[dict]:
    """Conecta, inicia sesión, presenta el remitente y se va, SIN mandar nada.

    Para saber en qué paso se corta sin gastar un mail ni molestar a nadie (pedido
    del 24/11/2026: la campaña daba «Connection unexpectedly closed» y no había
    forma de saber si era la red, la cuenta o el límite de Gmail). No necesita el
    envío activo y no cuenta para el límite. Devuelve un renglón por paso
    {paso, ok, ms, detalle}; el primero que falla es el último. La respuesta al
    EHLO de Gmail trae la IP desde la que sale el sistema.
    """
    cfg = config(conn)
    if not cfg.get("host"):
        raise MailError("Falta el servidor SMTP en la configuración de correo.")
    if cfg.get("password_error"):
        raise MailError(f"La clave del SMTP no se puede descifrar ({cfg['password_error']}). Volvé a cargarla.")
    servidor, pasos, smtp = _servidor(cfg), [], None
    remitente = cfg.get("remitente_email") or cfg.get("usuario") or ""

    def paso(clave, nombre, hacer):
        inicio = time.monotonic()
        try:
            resp = hacer()
        except smtplib.SMTPAuthenticationError as e:
            detalle = (f"el servidor rechazó el usuario o la contraseña "
                       f"({_texto_respuesta((e.smtp_code, e.smtp_error))}). {SUGERENCIAS['login']}")
            pasos.append({"paso": nombre, "ok": False, "ms": int((time.monotonic() - inicio) * 1000),
                          "detalle": detalle})
            return False
        except (smtplib.SMTPException, OSError) as e:
            pasos.append({"paso": nombre, "ok": False, "ms": int((time.monotonic() - inicio) * 1000),
                          "detalle": motivo_conexion(clave, servidor, e)})
            return False
        codigo = resp[0] if isinstance(resp, tuple) else None
        bien = codigo is None or 200 <= codigo < 400
        detalle = _texto_respuesta(resp) if isinstance(resp, tuple) else ""
        if not bien:
            detalle = motivo_conexion(clave, servidor, smtplib.SMTPResponseException(*resp))
        pasos.append({"paso": nombre, "ok": bien, "ms": int((time.monotonic() - inicio) * 1000),
                      "detalle": detalle.splitlines()[0] if bien and detalle else detalle})
        return bien

    caja = {}

    def conectar():
        caja["smtp"] = _abrir(cfg)
        return caja["smtp"].ehlo()

    try:
        if not paso("conectar", f"Conectar con {servidor}", conectar):
            return pasos
        smtp = caja["smtp"]
        if (cfg.get("seguridad") or "starttls") == "starttls" and not paso("tls", "Cifrado (STARTTLS)", smtp.starttls):
            return pasos
        if cfg.get("usuario") and not paso("login", f"Iniciar sesión como {cfg['usuario']}",
                                           lambda: smtp.login(cfg["usuario"], cfg.get("password") or "")):
            return pasos
        if remitente and paso("remitente", f"Presentar el remitente {remitente}", lambda: smtp.mail(remitente)):
            try:
                smtp.rset()                                  # no se manda nada: se deshace el MAIL FROM
            except Exception:                                # noqa: BLE001
                pass
        return pasos
    finally:
        _cerrar(caja.get("smtp"))


def probar_conexion(conn, destino: str) -> str:
    """Manda un mail de prueba. Es lo que confirma que la clave anda.

    Se hace aparte de `enviar()` porque no hay ningún tipo de aviso ni ninguna
    entidad de por medio: es sólo el servidor.
    """
    cfg = config(conn)
    _validar_config(cfg)
    if not RE_EMAIL.match((destino or "").strip()):
        raise MailError("La dirección de prueba no es válida.")

    msg = EmailMessage()
    msg["From"] = _direccion(cfg.get("remitente_nombre"),
                             cfg.get("remitente_email") or cfg.get("usuario"))
    msg["To"] = destino
    msg["Subject"] = "Prueba de configuración de correo"
    msg.set_content(
        "Este es un mail de prueba del sistema de gestión.\n\n"
        f"Servidor: {cfg['host']}:{cfg['puerto']} ({cfg['seguridad']})\n"
        f"Enviado: {datetime.datetime.now():%d/%m/%Y %H:%M}\n\n"
        "Si te llegó, la configuración funciona.")
    _entregar(cfg, msg, [destino])

    with conn.cursor() as cur:
        cur.execute("UPDATE mail_config SET probado_at = NOW() WHERE id = 1")
    conn.commit()
    return f"Mail de prueba enviado a {destino}."
