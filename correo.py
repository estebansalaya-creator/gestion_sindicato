"""
correo.py — Configuración del correo saliente
=============================================
Copia de mail_routes.py de gestion_adm (pedido del 17/11/2026: «configurar
correo saliente como en oseda»), con el sistema de estilos de acá.
Administración del Sistema › Correo Saliente (`/admin/correo`, menú 210,
sql/beneficios_correo_20261117.sql). El permiso es la opción de menú.

QUE HAY ACA Y QUE NO
--------------------
Sólo la configuración de la cuenta con la que sale todo, y la prueba que
confirma que anda. El motor —destinatarios, plantillas, envío, registro— vive
en `mailer.py` y no se toca desde acá.

Los avisos se disparan desde el módulo dueño de cada uno. Las campañas a
afiliados (Beneficios › Campañas, ben_campanias.py) usan esta misma cuenta,
el mismo límite de 24 horas y el mismo registro de envíos.

POR QUE LA CLAVE NO VUELVE A LA PANTALLA
----------------------------------------
El formulario muestra si hay clave guardada, nunca cuál es. Se guarda cifrada
con Fernet —`secretos.cifrar_secret`— y sólo se descifra en el momento de
entregar el mail. Un campo de contraseña relleno es una contraseña que viaja en
cada carga de la página y queda en el historial del navegador.

Dejar el campo vacío al guardar conserva la que estaba: es lo que se necesita
para poder cambiar el puerto sin volver a tipear la clave.

Lo mismo vale para la CUENTA PROPIA de un remitente (2026-11-05): usuario y
contraseña de aplicación con los que sale el aviso que lo usa, en lugar de la
cuenta general. Ver mailer.py, «Un remitente con cuenta propia».
"""

from __future__ import annotations

import logging
import re

from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash)

from db import get_connection, puede, usuario_actual, validasesion
import mailer
import paginar

log = logging.getLogger(__name__)

mail_bp = Blueprint("correo", __name__, url_prefix="/admin/correo")
URL = "/admin/correo"
SQL_ESQUEMA = "sql/beneficios_correo_20261117.sql"

SEGURIDADES = [
    ("starttls", "STARTTLS (puerto 587, lo habitual)"),
    ("ssl",      "SSL/TLS directo (puerto 465)"),
    ("ninguna",  "Sin cifrado (sólo para un servidor interno)"),
]


def _login():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede(URL):
        flash("!No tenés permiso para la configuración del correo.")
        return redirect(url_for("menu"))
    return None


def _uid():
    return (usuario_actual() or {}).get("id")


@mail_bp.route("", methods=["GET"])
def config():
    redir = _login()
    if redir:
        return redir

    cfg, tipos, ultimos = {}, [], []
    remitentes, areas, usuarios, editando = [], [], [], None
    try:
        with get_connection() as conn:
            cfg = mailer.config(conn)
            with conn.cursor() as cur:
                # El remitente de cada aviso se muestra resuelto: qué dirección
                # va a salir, no el id que la apunta.
                cur.execute("""
                    SELECT t.codigo, t.nombre, t.entidad_tipo, t.activo,
                           t.id_remitente, t.permite_remitente_usuario,
                           r.nombre AS remit_nombre, r.email AS remit_email,
                           r.activo AS remit_activo
                      FROM mail_tipos t
                      LEFT JOIN mail_remitentes r ON r.id = t.id_remitente
                     ORDER BY t.nombre
                """)
                tipos = cur.fetchall() or []

                cur.execute("""
                    SELECT r.*, a.nombre AS area_nombre, u.nombre AS usuario_nombre
                      FROM mail_remitentes r
                      LEFT JOIN s_areas    a ON a.id = r.id_area
                      LEFT JOIN s_usuarios u ON u.id = r.id_usuario
                     ORDER BY r.activo DESC, r.nombre
                """)
                remitentes = cur.fetchall() or []

                cur.execute("SELECT id, nombre FROM s_areas ORDER BY nombre")
                areas = cur.fetchall() or []
                cur.execute("""SELECT id, nombre, email FROM s_usuarios
                                WHERE activo = 1 AND email IS NOT NULL AND email <> ''
                                ORDER BY nombre""")
                usuarios = cur.fetchall() or []

                # Edición por `?edit=ID`, como el resto de los ABM.
                id_edit = request.args.get("edit", type=int)
                if id_edit:
                    editando = next((r for r in remitentes if r["id"] == id_edit), None)
                # Los últimos envíos, para saber si algo salió y con qué
                # resultado sin tener que ir a la base.
                cur.execute("""
                    SELECT codigo, para, asunto, estado, error, enviado_at
                      FROM mail_envios ORDER BY id DESC LIMIT 15
                """)
                ultimos = cur.fetchall() or []
    except Exception as e:                                   # noqa: BLE001
        flash(f"!No se pudo leer la configuración: {e}")

    return render_template(
        "admin/correo.html",
        cfg=cfg, tipos=tipos, ultimos=ultimos,
        remitentes=remitentes, areas=areas, usuarios=usuarios,
        editando=editando,
        seguridades=SEGURIDADES,
        tiene_clave=bool(cfg.get("password") or cfg.get("password_cif")),
        hay_cifrado=_hay_cifrado(), sql_esquema=SQL_ESQUEMA,
    )


def _hay_cifrado() -> bool:
    try:
        import secretos
        return secretos.hay_clave()
    except Exception:                                        # noqa: BLE001 — falta cryptography
        return False


# ══════════════════════════════════════════════════════════════════════════════
# REMITENTES
# ══════════════════════════════════════════════════════════════════════════════
#
# Una sola cuenta SMTP manda todo; lo que cambia es el `From` que ve quien
# recibe. Tesorería avisa una transferencia desde tesoreria@, Afiliaciones manda
# el carnet desde afiliaciones@, y el que contesta le contesta al área que le
# escribió y no a una casilla general que nadie mira.
#
# EL DOMINIO TIENE QUE AUTORIZAR CADA DIRECCION
# ---------------------------------------------
# Mandar desde una dirección que el SPF del dominio no habilita hace que el mail
# SALGA, no dé error, y caiga en spam. Es la falla que se descubre cuando nadie
# contesta, dos semanas después. Por eso la pantalla lo dice y por eso conviene
# probar cada remitente nuevo antes de atarlo a un aviso.

@mail_bp.route("/remitentes/guardar", methods=["POST"])
def remitente_guardar():
    redir = _login()
    if redir:
        return redir

    volver = redirect(url_for("correo.config"))
    f = request.form

    tipo   = (f.get("tipo") or "area").strip()
    nombre = (f.get("nombre") or "").strip()
    email  = (f.get("email") or "").strip()

    if tipo not in ("area", "usuario"):
        flash("!Tipo de remitente no válido.")
        return volver
    if not nombre:
        flash("!El nombre visible es obligatorio.")
        return volver
    if not mailer.RE_EMAIL.match(email):
        flash("!La dirección no es válida.")
        return volver

    responder_a = (f.get("responder_a") or "").strip()
    if responder_a and not mailer.RE_EMAIL.match(responder_a):
        flash("!La dirección de «responder a» no es válida.")
        return volver

    id_area    = f.get("id_area", type=int) if tipo == "area" else None
    id_usuario = f.get("id_usuario", type=int) if tipo == "usuario" else None
    if tipo == "usuario" and not id_usuario:
        flash("!Elegí el usuario del remitente.")
        return volver

    id_remit = f.get("id", type=int)
    activo   = 1 if f.get("activo") else 0
    firma    = (f.get("firma") or "").strip() or None

    # La cuenta propia: vacía = sale por la general. La contraseña vacía
    # conserva la guardada, como la de la configuración general.
    smtp_usuario = (f.get("smtp_usuario") or "").strip()
    smtp_clave = _clave_de_aplicacion(f.get("smtp_password") or "")
    if smtp_usuario and not mailer.RE_EMAIL.match(smtp_usuario):
        flash("!El usuario de la cuenta propia tiene que ser una dirección de correo.")
        return volver
    if smtp_clave:
        import secretos
        if not secretos.hay_clave():
            flash("!El servidor no tiene configurado el cifrado (SIND_FERNET_KEY): "
                  "no se puede guardar la contraseña.")
            return volver

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                hay_cuenta = _hay_cuenta_propia(cur)
                if (smtp_usuario or smtp_clave) and not hay_cuenta:
                    flash("!Para la cuenta propia falta correr "
                          "sql/mail_remitentes_cuenta_propia_20261105.sql.")
                    return volver
                if smtp_usuario and not smtp_clave:
                    guardada = None
                    if id_remit:
                        cur.execute("SELECT smtp_password_cif FROM mail_remitentes "
                                    "WHERE id = %s", (id_remit,))
                        guardada = (cur.fetchone() or {}).get("smtp_password_cif")
                    if not guardada:
                        flash("!Cargá la contraseña de aplicación de la cuenta "
                              f"{smtp_usuario}.")
                        return volver
                if id_remit:
                    cur.execute("""
                        UPDATE mail_remitentes
                           SET tipo=%s, id_area=%s, id_usuario=%s, nombre=%s,
                               email=%s, responder_a=%s, firma=%s, activo=%s
                         WHERE id=%s
                    """, (tipo, id_area, id_usuario, nombre, email,
                          responder_a or None, firma, activo, id_remit))
                    flash("Remitente actualizado.")
                else:
                    cur.execute("""
                        INSERT INTO mail_remitentes
                              (tipo, id_area, id_usuario, nombre, email,
                               responder_a, firma, activo)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (tipo, id_area, id_usuario, nombre, email,
                          responder_a or None, firma, activo))
                    id_remit = cur.lastrowid
                    flash("Remitente creado. Asignalo al aviso que corresponda "
                          "en el cuadro de abajo.")
                if hay_cuenta:
                    if not smtp_usuario:
                        cur.execute("""UPDATE mail_remitentes
                                          SET smtp_usuario = NULL, smtp_password_cif = NULL
                                        WHERE id = %s""", (id_remit,))
                    elif smtp_clave:
                        from secretos import cifrar_secret
                        cur.execute("""UPDATE mail_remitentes
                                          SET smtp_usuario = %s, smtp_password_cif = %s
                                        WHERE id = %s""",
                                    (smtp_usuario, cifrar_secret(smtp_clave), id_remit))
                    else:
                        cur.execute("UPDATE mail_remitentes SET smtp_usuario = %s "
                                    "WHERE id = %s", (smtp_usuario, id_remit))
                    if smtp_usuario:
                        flash(f"Sale con su propia cuenta, {smtp_usuario}. Probalo "
                              "antes de mandar avisos con este remitente.")
            conn.commit()
    except Exception as e:                                   # noqa: BLE001
        flash(f"!No se pudo guardar el remitente: {e}")
    return volver


def _clave_de_aplicacion(texto: str) -> str:
    """Google muestra la contraseña de aplicación en cuatro grupos
    («abcd efgh ijkl mnop»): esa forma se guarda sin los espacios. Cualquier
    otra, tal como se escribió (sin los espacios de las puntas)."""
    t = (texto or "").strip()
    if re.fullmatch(r"[A-Za-z]{4}( [A-Za-z]{4}){3}", t):
        return t.replace(" ", "")
    return t


def _hay_cuenta_propia(cur) -> bool:
    """mail_remitentes ya tiene las columnas de la cuenta propia."""
    cur.execute("""SELECT 1 AS si FROM information_schema.columns
                    WHERE table_schema = DATABASE() AND table_name = 'mail_remitentes'
                      AND column_name = 'smtp_password_cif'""")
    return bool(cur.fetchone())


@mail_bp.route("/remitentes/<int:id_remit>/borrar", methods=["POST"])
def remitente_borrar(id_remit: int):
    """Lo desactiva; no lo borra.

    Los avisos ya mandados quedaron registrados con esa dirección, y algún tipo
    puede seguir apuntándole. Desactivar corta el uso futuro sin romper lo que
    ya pasó — y `remitente()` cae a la configuración general, así que el aviso
    sigue saliendo.
    """
    redir = _login()
    if redir:
        return redir
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE mail_remitentes SET activo = 0 WHERE id = %s",
                            (id_remit,))
            conn.commit()
        flash("Remitente desactivado. Los avisos que lo usaban vuelven a salir "
              "desde la dirección general.")
    except Exception as e:                                   # noqa: BLE001
        flash(f"!No se pudo desactivar: {e}")
    return redirect(url_for("correo.config"))


@mail_bp.route("/tipos/asignar", methods=["POST"])
def tipo_asignar():
    """Qué remitente usa cada aviso, y si el aviso está encendido.

    Se guarda todo el cuadro de una: son seis filas y cambiarlas de a una,
    recargando la pantalla cada vez, es peor.
    """
    redir = _login()
    if redir:
        return redir

    volver = redirect(url_for("correo.config"))
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT codigo FROM mail_tipos")
                codigos = [r["codigo"] for r in (cur.fetchall() or [])]
                for cod in codigos:
                    # Un valor vacío es «usá el remitente general», que es
                    # NULL en la columna y no un id inventado.
                    id_rem = request.form.get(f"remit_{cod}", type=int)
                    activo = 1 if request.form.get(f"activo_{cod}") else 0
                    usuario = 1 if request.form.get(f"usuario_{cod}") else 0
                    cur.execute("""
                        UPDATE mail_tipos
                           SET id_remitente = %s, activo = %s,
                               permite_remitente_usuario = %s
                         WHERE codigo = %s
                    """, (id_rem or None, activo, usuario, cod))
            conn.commit()
        flash("Remitentes de los avisos guardados.")
    except Exception as e:                                   # noqa: BLE001
        flash(f"!No se pudo guardar: {e}")
    return volver


@mail_bp.route("/guardar", methods=["POST"])
def guardar():
    redir = _login()
    if redir:
        return redir

    volver = redirect(url_for("correo.config"))
    f = request.form

    host = (f.get("host") or "").strip()
    if not host:
        flash("!El servidor SMTP es obligatorio.")
        return volver

    try:
        puerto = int(f.get("puerto") or 587)
    except ValueError:
        flash("!El puerto tiene que ser un número.")
        return volver

    seguridad = (f.get("seguridad") or "starttls").strip()
    if seguridad not in dict(SEGURIDADES):
        flash("!Tipo de seguridad no válido.")
        return volver

    remitente_email = (f.get("remitente_email") or "").strip()
    if remitente_email and not mailer.RE_EMAIL.match(remitente_email):
        flash("!La dirección del remitente no es válida.")
        return volver

    responder_a = (f.get("responder_a") or "").strip()
    if responder_a and not mailer.RE_EMAIL.match(responder_a):
        flash("!La dirección de «responder a» no es válida.")
        return volver

    try:
        limite = int(f.get("limite_diario") or 500)
    except ValueError:
        limite = 500

    clave = f.get("password") or ""
    activo = 1 if f.get("activo") else 0

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                campos = [
                    "host = %s", "puerto = %s", "seguridad = %s", "usuario = %s",
                    "remitente_nombre = %s", "remitente_email = %s",
                    "responder_a = %s", "limite_diario = %s", "activo = %s",
                    "actualizado_por = %s",
                ]
                valores = [host, puerto, seguridad,
                           (f.get("usuario") or "").strip() or None,
                           (f.get("remitente_nombre") or "").strip() or None,
                           remitente_email or None, responder_a or None,
                           limite, activo, _uid()]

                # Vacía significa «dejá la que está», no «borrala». Cambiar el
                # puerto no tiene por qué obligar a tipear la clave de nuevo.
                if clave:
                    from secretos import cifrar_secret
                    campos.append("password_cif = %s")
                    valores.append(cifrar_secret(clave))

                cur.execute(f"UPDATE mail_config SET {', '.join(campos)} WHERE id = 1",
                            valores)
                if cur.rowcount == 0:
                    cur.execute("SELECT id FROM mail_config WHERE id = 1")
                    if not cur.fetchone():
                        flash("!Falta la fila de configuración (mail_config id=1).")
                        return volver
            conn.commit()
        flash("Configuración guardada." +
              ("" if activo else " El envío sigue APAGADO."))
    except Exception as e:                                   # noqa: BLE001
        flash(f"!No se pudo guardar: {e}")
    return volver


# ══════════════════════════════════════════════════════════════════════════════
# LOG DE ENVIOS
# ══════════════════════════════════════════════════════════════════════════════

@mail_bp.route("/envios")
def envios():
    """Qué se mandó, a quién y con qué resultado.

    Es la pantalla a la que apunta la columna «Comprobante» de pagos emitidos:
    con `origen_tipo` y `origen_id` en la URL muestra los envíos de ESE
    documento, y sin ellos el log completo.

    SOLO LECTURA
    ------------
    No hay «reenviar» acá. Reenviar es una decisión que se toma mirando el
    documento —la orden, el pago—, no una lista de correos; y desde acá sería
    fácil disparar cincuenta sin ver qué son.
    """
    redir = _login()
    if redir:
        return redir

    origen_tipo = (request.args.get("origen_tipo") or "").strip()
    origen_id   = request.args.get("origen_id", type=int)
    f_codigo    = (request.args.get("codigo") or "").strip()
    f_estado    = (request.args.get("estado") or "").strip()
    f_q         = (request.args.get("q") or "").strip()
    page        = max(1, request.args.get("pagina", type=int) or 1)
    POR_PAGINA  = 50

    envios_l, codigos, total, paginas = [], [], 0, 1
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                where, params = ["1=1"], []
                if origen_tipo and origen_id:
                    where.append("e.origen_tipo = %s AND e.origen_id = %s")
                    params += [origen_tipo, origen_id]
                if f_codigo:
                    where.append("e.codigo = %s"); params.append(f_codigo)
                if f_estado:
                    where.append("e.estado = %s"); params.append(f_estado)
                if f_q:
                    where.append("(e.para LIKE %s OR e.asunto LIKE %s)")
                    params += [f"%{f_q}%", f"%{f_q}%"]
                w = " AND ".join(where)

                cur.execute(f"SELECT COUNT(*) AS n FROM mail_envios e WHERE {w}", params)
                total   = int((cur.fetchone() or {}).get("n") or 0)
                paginas = max(1, -(-total // POR_PAGINA))
                page    = min(page, paginas)

                cur.execute(f"""
                    SELECT e.*, t.nombre AS tipo_nombre, u.nombre AS usuario_nombre
                      FROM mail_envios e
                      LEFT JOIN mail_tipos t ON t.codigo = e.codigo
                      LEFT JOIN s_usuarios u ON u.id = e.id_usuario
                     WHERE {w}
                     ORDER BY e.id DESC
                     LIMIT %s OFFSET %s
                """, params + [POR_PAGINA, (page - 1) * POR_PAGINA])
                envios_l = cur.fetchall() or []

                cur.execute("SELECT codigo, nombre FROM mail_tipos ORDER BY nombre")
                codigos = cur.fetchall() or []
    except Exception as e:                                   # noqa: BLE001
        flash(f"!No se pudo leer el log: {e}")

    return render_template(
        "admin/correo_envios.html",
        envios=envios_l, codigos=codigos, total=total,
        pag=paginar.paginador(total, page, POR_PAGINA, "correo.envios",
                              {k: v for k, v in {"origen_tipo": origen_tipo, "origen_id": origen_id,
                                                 "codigo": f_codigo, "estado": f_estado, "q": f_q}.items() if v}),
        filtros={"origen_tipo": origen_tipo, "origen_id": origen_id,
                 "codigo": f_codigo, "estado": f_estado, "q": f_q},
    )


@mail_bp.route("/probar", methods=["POST"])
def probar():
    """Manda un mail de prueba. Es lo único que confirma que la clave anda.

    Guardar la configuración no valida nada: el servidor puede rechazar la
    clave, o el puerto puede estar cerrado, y eso no se descubre hasta que
    alguien intenta entregar algo.
    """
    redir = _login()
    if redir:
        return redir

    destino = (request.form.get("destino") or "").strip()
    try:
        with get_connection() as conn:
            flash("" + mailer.probar_conexion(conn, destino))
    except mailer.MailError as e:
        flash(f"!{e}")
    except Exception as e:                                   # noqa: BLE001
        log.exception("Probando el SMTP")
        flash(f"!No se pudo enviar la prueba: {e}")
    return redirect(url_for("correo.config"))
