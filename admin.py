"""
admin.py — Administración del sistema (/admin/...).

Las pantallas de «Administración del Sistema» de gestion_adm (`abm_usuarios`,
`abm_roles`, `abm_menu_usuario`, `abm_menu`, `abm_areas`, `abm_area_usuario`)
con el sistema de estilos de acá:

    /admin/usuarios        alta, edición, roles, contraseña, baja y eliminación
    /admin/roles           los roles fijos: descripción, estado y sus opciones de menú
    /admin/permisos        opciones sueltas para una persona (?usuario=ID)
    /admin/menu            el árbol del menú (?edit=ID, ?nuevo=1, ?padre=ID)
    /admin/areas           el organigrama (?edit=ID, ?nuevo=1, ?padre=ID)
    /admin/areas_usuario   a qué áreas pertenece cada persona (?usuario=ID)

«Datos del Sindicato» (/admin/institucion) está en institucion.py.

PERMISOS
El permiso es la opción de menú, como en el resto del sistema (`db.puede`). En
gestion_adm estas pantallas pedían el rol Administrador por nombre; acá basta
con tener la opción, y lo que impide que el sistema quede sin forma de
administrarse son tres reglas:

  - Siempre queda al menos un usuario activo con el rol Administrador.
  - El rol Administrador no puede perder Usuarios, Roles ni Menú
    (`MENU_PROTEGIDO`), ni desactivarse.
  - Esas tres opciones no se desactivan, no se eliminan y no cambian de URL.

Los permisos se leen al iniciar sesión (`sind_menu_ids`): un cambio rige para
los demás desde su próximo ingreso. El de quien hace el cambio se refresca en
el momento (`_refrescar_sesion`).

DÓNDE SE USA UN USUARIO O UN ÁREA
No hay una lista a mano como `_ACTIVIDAD_USUARIO` de gestion_adm, que se
desactualizaba con cada tabla nueva: se leen las claves foráneas de la base
(`_referencias`). Las que borran en cascada son la configuración del propio
usuario (roles, permisos, áreas, accesos directos) y no cuentan; cualquier
otra sí, incluidas las SET NULL: borrar al usuario dejaría expedientes y
órdenes sin saber quién los hizo.
"""

from __future__ import annotations

import re

from flask import (Blueprint, current_app, flash, redirect, render_template, request,
                   session, url_for)
from werkzeug.exceptions import HTTPException, NotFound
from werkzeug.security import generate_password_hash

from db import get_connection, puede, roles_y_menu, validasesion

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

ROL_ADMIN = "Administrador"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CLAVE_MIN = 8

#: Niveles que dibuja el menú lateral de base.html (ítem, hijo, nieto, bisnieto).
MENU_NIVELES = 4
#: Los del organigrama, como en gestion_adm.
AREA_NIVELES = 5

#: Sin estas tres nadie podría volver a dar permisos ni arreglar el menú.
MENU_PROTEGIDO = ("/admin/usuarios", "/admin/roles", "/admin/menu")

#: Cómo se nombra cada tabla que referencia a un usuario o a un área.
ETIQUETAS = {
    "c_movimiento_entre_cuentas": "movimientos entre cuentas",
    "c_nomina_empleados": "empleados de la nómina",
    "c_proveedores": "proveedores (destino en la mesa)",
    "c_reintegro_afiliados": "reintegros",
    "c_reintegro_afiliados_aprobacion": "aprobaciones de reintegros",
    "c_reintegro_afiliados_detalle_adjunto": "adjuntos de reintegros",
    "conciliacion_header": "conciliaciones",
    "f_comprobantes_arca": "comprobantes",
    "ingreso_ordenes": "órdenes de ingreso",
    "mail_remitentes": "remitentes de correo",
    "mail_tipos": "tipos de correo",
    "me_expediente_movimientos": "movimientos de expedientes",
    "me_expedientes": "expedientes",
    "pago_config_aprobadores": "aprobadores de pagos",
    "pago_imputaciones": "imputaciones de pago",
    "pago_ordenes": "órdenes de pago",
    "pago_ordenes_aprobacion": "aprobaciones de órdenes de pago",
    "pago_pagos": "pagos",
    "pago_retenciones": "retenciones",
}


# =============================================================================
# Comunes
# =============================================================================

def _guardia(endpoint):
    """Redirección si no hay sesión o no tiene la opción de menú; None si pasa."""
    if not validasesion():
        return redirect(url_for("login"))
    if not puede(url_for(endpoint)):
        flash("!No tenés permiso para esa pantalla.")
        return redirect(url_for("menu"))
    return None


def _texto(nombre, largo):
    return re.sub(r"\s+", " ", (request.form.get(nombre) or "").strip())[:largo]


def _id(nombre, fuente=None):
    v = ((fuente or request.form).get(nombre) or "").strip()
    return int(v) if v.isdigit() else None


def _ids(nombre) -> set[int]:
    return {int(v) for v in request.form.getlist(nombre) if v.isdigit()}


def _entero(nombre, defecto=0):
    v = (request.form.get(nombre) or "").strip()
    return int(v) if re.fullmatch(r"-?\d{1,5}", v) else defecto


def _refrescar_sesion():
    """
    Vuelve a leer roles y permisos de quien está usando el sistema. Sin esto,
    quien se saca o se da una opción la seguiría viendo (o no) hasta salir y
    volver a entrar, y parecería que guardar no anduvo.
    """
    uid = session.get("sind_usuario_id")
    if uid:
        roles, menu_ids = roles_y_menu(uid)
        session["sind_roles"] = roles
        session["sind_menu_ids"] = menu_ids


def _arbol(items: list[dict]) -> list[dict]:
    """
    La lista plana de `s_menu` o `s_areas` en el orden del árbol, sin recursión
    en Jinja. Cada nodo lleva `prof` (0 = raíz, para la sangría), `ancestros`
    (ids, de la raíz hacia abajo) y `n_hijos`. Los ítems ya vienen ordenados
    por orden y nombre. Lo que no se alcanza desde una raíz —un ciclo cargado a
    mano— sale al final como raíz, para que se vea y se pueda arreglar.
    """
    ids = {i["id"] for i in items}
    hijos: dict = {}
    for i in items:
        p = i["padre_id"] if i["padre_id"] in ids else None
        hijos.setdefault(p, []).append(i)
    salida, vistos = [], set()

    def bajar(padre, prof, anc):
        for i in hijos.get(padre, []):
            if i["id"] in vistos:
                continue
            vistos.add(i["id"])
            salida.append(dict(i, prof=prof, ancestros=anc, n_hijos=len(hijos.get(i["id"], []))))
            bajar(i["id"], prof + 1, anc + [i["id"]])

    bajar(None, 0, [])
    for i in items:
        if i["id"] not in vistos:
            vistos.add(i["id"])
            salida.append(dict(i, prof=0, ancestros=[], n_hijos=len(hijos.get(i["id"], []))))
    return salida


def _descendientes(arbol: list[dict], nodo_id: int) -> set[int]:
    return {n["id"] for n in arbol if nodo_id in n["ancestros"]}


def _altura(arbol: list[dict], nodo_id: int) -> int:
    """Cuántos niveles tiene el subárbol que cuelga del nodo, contándolo (una hoja = 1)."""
    base = next((n["prof"] for n in arbol if n["id"] == nodo_id), 0)
    return 1 + max((n["prof"] - base for n in arbol if nodo_id in n["ancestros"]), default=0)


def _con_ancestros(ids, por_id: dict) -> set[int]:
    """
    Los ids y todas sus ramas. El menú lateral descarta una opción cuya rama
    no está permitida (`app._armar_arbol`): tildar «Usuarios» sin
    «Administración del Sistema» no la mostraría.
    """
    res = set()
    for i in ids:
        while i in por_id and i not in res:
            res.add(i)
            i = por_id[i]["padre_id"]
    return res


def _rearmar_niveles(cur, tabla):
    """
    `nivel` es la profundidad en el árbol. Se recalcula entera después de cada
    cambio: mover una rama cambia el nivel de todo lo que cuelga de ella, y en
    gestion_adm solo se actualizaba el ítem movido.
    """
    cur.execute(f"SELECT id, padre_id, nivel FROM {tabla} ORDER BY orden, nombre")
    for n in _arbol(cur.fetchall()):
        if n["nivel"] != n["prof"] + 1:
            cur.execute(f"UPDATE {tabla} SET nivel = %s WHERE id = %s", (n["prof"] + 1, n["id"]))


def _referencias(cur, tabla) -> dict[str, list[str]]:
    """Tablas y columnas que apuntan a `tabla` sin borrado en cascada (de las FK de la base)."""
    cur.execute("""
        SELECT k.TABLE_NAME AS tabla, k.COLUMN_NAME AS columna
          FROM information_schema.KEY_COLUMN_USAGE k
          JOIN information_schema.REFERENTIAL_CONSTRAINTS rc
            ON rc.CONSTRAINT_SCHEMA = k.CONSTRAINT_SCHEMA AND rc.CONSTRAINT_NAME = k.CONSTRAINT_NAME
         WHERE k.TABLE_SCHEMA = DATABASE() AND k.REFERENCED_TABLE_NAME = %s
           AND rc.DELETE_RULE <> 'CASCADE' AND k.TABLE_NAME <> %s
         ORDER BY k.TABLE_NAME, k.COLUMN_NAME
    """, (tabla, tabla))
    refs: dict = {}
    for f in cur.fetchall():
        refs.setdefault(f["tabla"], []).append(f["columna"])
    return refs


def _usos(cur, tabla, ids) -> dict[int, list[tuple[int, str]]]:
    """
    Dónde figura cada id: {id: [(cuántas filas, qué), ...]}. Una fila que lo
    nombra en dos columnas (creó y anuló la misma orden) cuenta una vez.
    """
    ids = [i for i in ids if i]
    res = {i: [] for i in ids}
    refs = _referencias(cur, tabla)
    if not ids or not refs:
        return res
    partes = []
    for t, cols in refs.items():
        cond = " OR ".join(f"x.`{c}` = b.id" for c in cols)
        partes.append(f"(SELECT COUNT(*) FROM `{t}` x WHERE {cond}) AS `{t}`")
    marcas = ",".join(["%s"] * len(ids))
    cur.execute(f"SELECT b.id, {', '.join(partes)} FROM `{tabla}` b WHERE b.id IN ({marcas})", ids)
    for f in cur.fetchall():
        res[f["id"]] = [(f[t], ETIQUETAS.get(t, t)) for t in refs if f[t]]
    return res


def _texto_usos(usos) -> str:
    return ", ".join(f"{n} {etiqueta}" for n, etiqueta in usos)


def _es_admin(cur, usuario_id) -> bool:
    cur.execute("""SELECT 1 FROM s_usuario_rol ur JOIN s_roles r ON r.id = ur.rol_id
                    WHERE ur.usuario_id = %s AND r.nombre = %s LIMIT 1""", (usuario_id, ROL_ADMIN))
    return cur.fetchone() is not None


def _otros_admins(cur, usuario_id) -> int:
    """Usuarios activos con el rol Administrador, sin contar a `usuario_id`."""
    cur.execute("""
        SELECT COUNT(DISTINCT u.id) AS n
          FROM s_usuarios u
          JOIN s_usuario_rol ur ON ur.usuario_id = u.id
          JOIN s_roles r ON r.id = ur.rol_id AND r.nombre = %s AND r.activo = 1
         WHERE u.activo = 1 AND u.id <> %s
    """, (ROL_ADMIN, usuario_id or 0))
    return cur.fetchone()["n"]


def _ruta_existe(url) -> bool:
    """Si la URL de una opción tiene pantalla en esta aplicación (o da «pantalla pendiente»)."""
    try:
        current_app.url_map.bind("localhost").match(url.split("?")[0], method="GET")
        return True
    except NotFound:
        return False
    except HTTPException:        # redirección por la barra final, método no permitido
        return True


def _menu_completo(cur) -> list[dict]:
    cur.execute("""SELECT id, padre_id, nombre, url, icono_svg, orden, nivel, activo
                     FROM s_menu ORDER BY orden, nombre""")
    return cur.fetchall()


def _usuarios_para_elegir(cur) -> list[dict]:
    cur.execute("""SELECT u.id, u.nombre, u.email, u.activo,
                          GROUP_CONCAT(r.nombre ORDER BY r.prioridad DESC SEPARATOR ', ') AS roles
                     FROM s_usuarios u
                     LEFT JOIN s_usuario_rol ur ON ur.usuario_id = u.id
                     LEFT JOIN s_roles r ON r.id = ur.rol_id
                    GROUP BY u.id, u.nombre, u.email, u.activo
                    ORDER BY u.activo DESC, u.nombre""")
    return cur.fetchall()


# =============================================================================
# Usuarios
# =============================================================================

@admin_bp.route("/usuarios", methods=["GET", "POST"])
def usuarios():
    salida = _guardia("admin.usuarios")
    if salida:
        return salida
    yo = session.get("sind_usuario_id")
    errores, reg = [], None

    if request.method == "POST":
        accion, uid = request.form.get("accion", ""), _id("id")
        with get_connection() as conn:
            with conn.cursor() as cur:
                if accion in ("baja", "reactivar", "borrar") and uid:
                    cur.execute("SELECT id, nombre, activo FROM s_usuarios WHERE id = %s", (uid,))
                    u = cur.fetchone()
                    if not u:
                        flash("!El usuario ya no existe.")
                    elif accion == "reactivar":
                        cur.execute("UPDATE s_usuarios SET activo = 1 WHERE id = %s", (uid,))
                        flash(f"«{u['nombre']}» reactivado: ya puede volver a entrar.")
                    elif uid == yo:
                        flash("!No podés dar de baja ni eliminar tu propio usuario: quedarías afuera "
                              "sin poder volver a entrar.")
                    elif _es_admin(cur, uid) and not _otros_admins(cur, uid):
                        flash("!Es el único administrador activo: el sistema quedaría sin nadie que "
                              "pueda administrarlo. Dale el rol a otra persona antes.")
                    elif accion == "baja":
                        cur.execute("UPDATE s_usuarios SET activo = 0 WHERE id = %s", (uid,))
                        flash(f"«{u['nombre']}» dado de baja: no puede iniciar sesión y lo que hizo "
                              "sigue a su nombre.")
                    else:
                        usos = _usos(cur, "s_usuarios", [uid])[uid]
                        if usos:
                            flash(f"!No se puede eliminar a «{u['nombre']}»: figura en {_texto_usos(usos)}. "
                                  "Borrarlo dejaría esos registros sin saber quién los hizo. Dalo de baja.")
                        else:
                            # Roles, permisos, áreas y accesos directos se van solos (CASCADE).
                            cur.execute("DELETE FROM s_usuarios WHERE id = %s", (uid,))
                            flash(f"«{u['nombre']}» eliminado.")
                    return redirect(url_for("admin.usuarios"))
                if accion != "guardar":
                    return redirect(url_for("admin.usuarios"))

                reg = {"id": uid, "email": _texto("email", 150).lower().replace(" ", ""),
                       "nombre": _texto("nombre", 150), "activo": 1 if request.form.get("activo") else 0,
                       "rol_ids": _ids("rol_ids")}
                clave, clave2 = request.form.get("password") or "", request.form.get("password2") or ""

                if not reg["email"]:
                    errores.append("El email es obligatorio: es con lo que la persona entra.")
                elif not EMAIL_RE.match(reg["email"]):
                    errores.append(f"«{reg['email']}» no es un email válido.")
                else:
                    cur.execute("SELECT nombre FROM s_usuarios WHERE email = %s AND id <> %s",
                                (reg["email"], uid or 0))
                    otro = cur.fetchone()
                    if otro:
                        errores.append(f"El email {reg['email']} ya es de «{otro['nombre']}».")
                if not reg["nombre"]:
                    errores.append("El nombre es obligatorio.")
                if not uid and not clave:
                    errores.append("La contraseña es obligatoria en el alta: el sistema no tiene otra "
                                   "forma de entrar.")
                if clave or clave2:
                    if clave != clave2:
                        errores.append("Las dos contraseñas no coinciden.")
                    elif len(clave) < CLAVE_MIN:
                        errores.append(f"La contraseña tiene que tener al menos {CLAVE_MIN} caracteres.")

                # Solo los roles activos se eligen; los inactivos (autogestión)
                # que ya tenga se conservan al guardar.
                cur.execute("SELECT id, nombre FROM s_roles WHERE activo = 1")
                activos = {f["id"]: f["nombre"] for f in cur.fetchall()}
                reg["rol_ids"] &= set(activos)
                nombres = {activos[i] for i in reg["rol_ids"]}

                if uid and uid == yo:
                    if not reg["activo"]:
                        errores.append("No podés darte de baja a vos mismo.")
                    if _es_admin(cur, uid) and ROL_ADMIN not in nombres:
                        errores.append("No podés quitarte el rol Administrador: perderías el acceso a "
                                       "esta pantalla. Que lo haga otro administrador.")
                if (uid and not errores and _es_admin(cur, uid)
                        and not (reg["activo"] and ROL_ADMIN in nombres) and not _otros_admins(cur, uid)):
                    errores.append("Es el único administrador activo: el sistema quedaría sin nadie que "
                                   "pueda administrarlo. Dale el rol a otra persona antes.")

                if not errores:
                    if uid:
                        cur.execute("UPDATE s_usuarios SET email = %s, nombre = %s, activo = %s WHERE id = %s",
                                    (reg["email"], reg["nombre"], reg["activo"], uid))
                    else:
                        cur.execute("INSERT INTO s_usuarios (email, nombre, activo) VALUES (%s, %s, %s)",
                                    (reg["email"], reg["nombre"], reg["activo"]))
                        uid = cur.lastrowid
                    if clave:
                        cur.execute("UPDATE s_usuarios SET password_hash = %s WHERE id = %s",
                                    (generate_password_hash(clave), uid))
                    cur.execute("""DELETE ur FROM s_usuario_rol ur JOIN s_roles r ON r.id = ur.rol_id
                                    WHERE ur.usuario_id = %s AND r.activo = 1""", (uid,))
                    for rid in sorted(reg["rol_ids"]):
                        cur.execute("INSERT INTO s_usuario_rol (usuario_id, rol_id) VALUES (%s, %s)", (uid, rid))
                    if uid == yo:
                        _refrescar_sesion()
                    flash(f"«{reg['nombre']}» " + ("actualizado." if reg["id"] else "dado de alta.")
                          + (" La contraseña quedó cambiada." if clave and reg["id"] else "")
                          + ("" if uid == yo or not reg["id"] else
                             " Si cambiaron sus roles, los ve desde su próximo ingreso."))
                    return redirect(url_for("admin.usuarios"))

    with get_connection() as conn:
        with conn.cursor() as cur:
            edit_id = request.args.get("edit", type=int)
            if edit_id and reg is None:
                cur.execute("""SELECT id, email, nombre, activo, ultimo_acceso, creado,
                                      (password_hash IS NOT NULL) AS tiene_clave
                                 FROM s_usuarios WHERE id = %s""", (edit_id,))
                reg = cur.fetchone()
                if not reg:
                    flash("!El usuario no existe.")
                    return redirect(url_for("admin.usuarios"))
                cur.execute("SELECT rol_id FROM s_usuario_rol WHERE usuario_id = %s", (edit_id,))
                reg["rol_ids"] = {f["rol_id"] for f in cur.fetchall()}
            elif reg and reg.get("id"):
                # Con errores se redibuja lo escrito; lo que no viaja en el form sale de la base.
                cur.execute("""SELECT ultimo_acceso, creado, (password_hash IS NOT NULL) AS tiene_clave
                                 FROM s_usuarios WHERE id = %s""", (reg["id"],))
                reg.update(cur.fetchone() or {})
                cur.execute("""SELECT ur.rol_id FROM s_usuario_rol ur JOIN s_roles r ON r.id = ur.rol_id
                                WHERE ur.usuario_id = %s AND r.activo = 0""", (reg["id"],))
                reg["rol_ids"] |= {f["rol_id"] for f in cur.fetchall()}

            cur.execute("""
                SELECT u.id, u.email, u.nombre, u.activo, u.ultimo_acceso, u.creado,
                       (u.password_hash IS NOT NULL) AS tiene_clave,
                       GROUP_CONCAT(r.nombre ORDER BY r.prioridad DESC SEPARATOR ', ') AS roles,
                       GROUP_CONCAT(r.id) AS rol_ids,
                       (SELECT COUNT(*) FROM s_menu_usuario mu WHERE mu.usuario_id = u.id) AS extras,
                       (SELECT GROUP_CONCAT(a.nombre ORDER BY a.nombre SEPARATOR ', ')
                          FROM s_area_usuario au JOIN s_areas a ON a.id = au.area_id
                         WHERE au.usuario_id = u.id) AS areas
                  FROM s_usuarios u
                  LEFT JOIN s_usuario_rol ur ON ur.usuario_id = u.id
                  LEFT JOIN s_roles r ON r.id = ur.rol_id
                 GROUP BY u.id
                 ORDER BY u.nombre
            """)
            lista = cur.fetchall()
            usos = _usos(cur, "s_usuarios", [u["id"] for u in lista])
            for u in lista:
                u["usos"] = usos.get(u["id"], [])
            cur.execute("SELECT id, nombre, descripcion, activo FROM s_roles ORDER BY prioridad DESC, nombre")
            roles = cur.fetchall()

    nuevo = bool(request.args.get("nuevo"))
    if reg is None and nuevo:
        reg = {"activo": 1, "rol_ids": set()}
    return render_template("admin/usuarios.html", usuarios=lista, reg=reg, roles=roles, errores=errores,
                           yo=yo, clave_min=CLAVE_MIN, abrir_ficha=bool(reg or errores))


# =============================================================================
# Roles
# =============================================================================

@admin_bp.route("/roles", methods=["GET", "POST"])
def roles():
    """
    Los roles son fijos, como en gestion_adm: el nombre es la clave que usa el
    código (`db.tiene_rol`), así que no se crean, no se borran y no se
    renombran desde acá. Se edita la descripción, si está activo y qué
    opciones del menú tiene. `db_usuario` (con qué usuario de MySQL conecta el
    rol) se ve pero no se cambia: necesita la variable de entorno con la
    contraseña, y eso es del servidor.
    """
    salida = _guardia("admin.roles")
    if salida:
        return salida
    errores, rol, marcadas = [], None, None

    if request.method == "POST":
        rid = _id("id")
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM s_roles WHERE id = %s", (rid or 0,))
                rol = cur.fetchone()
                if request.form.get("accion") != "guardar" or not rol:
                    flash("!Los roles son fijos: no se crean ni se eliminan desde esta pantalla.")
                    return redirect(url_for("admin.roles"))
                menu = _menu_completo(cur)
                por_id = {m["id"]: m for m in menu}
                marcadas = _con_ancestros(_ids("menu_ids") & set(por_id), por_id)
                rol.update(descripcion=_texto("descripcion", 250) or None,
                           activo=1 if request.form.get("activo") else 0)

                if rol["nombre"] == ROL_ADMIN:
                    if not rol["activo"]:
                        errores.append("El rol Administrador no se desactiva: el sistema quedaría sin "
                                       "nadie que pueda administrarlo.")
                    faltan = [m["nombre"] for m in menu if m["url"] in MENU_PROTEGIDO and m["id"] not in marcadas]
                    if faltan:
                        errores.append("El rol Administrador tiene que conservar " + ", ".join(faltan)
                                       + ": sin esas pantallas nadie podría volver a dar permisos.")
                if not errores:
                    cur.execute("UPDATE s_roles SET descripcion = %s, activo = %s WHERE id = %s",
                                (rol["descripcion"], rol["activo"], rid))
                    cur.execute("DELETE FROM s_menu_rol WHERE rol_id = %s", (rid,))
                    if marcadas:
                        cur.executemany("INSERT INTO s_menu_rol (menu_id, rol_id) VALUES (%s, %s)",
                                        [(m, rid) for m in sorted(marcadas)])
                    _refrescar_sesion()
                    flash(f"Rol «{rol['nombre']}» guardado con {len(marcadas)} opciones de menú. Quienes lo "
                          "tienen ven el cambio desde su próximo ingreso.")
                    return redirect(url_for("admin.roles"))

    with get_connection() as conn:
        with conn.cursor() as cur:
            edit_id = request.args.get("edit", type=int)
            if edit_id and rol is None:
                cur.execute("SELECT * FROM s_roles WHERE id = %s", (edit_id,))
                rol = cur.fetchone()
                if not rol:
                    flash("!El rol no existe.")
                    return redirect(url_for("admin.roles"))
            if rol and marcadas is None:
                cur.execute("SELECT menu_id FROM s_menu_rol WHERE rol_id = %s", (rol["id"],))
                marcadas = {f["menu_id"] for f in cur.fetchall()}
            cur.execute("""
                SELECT r.*,
                       (SELECT COUNT(*) FROM s_usuario_rol ur JOIN s_usuarios u ON u.id = ur.usuario_id
                         WHERE ur.rol_id = r.id AND u.activo = 1) AS usuarios,
                       (SELECT COUNT(*) FROM s_menu_rol mr JOIN s_menu m ON m.id = mr.menu_id
                         WHERE mr.rol_id = r.id AND m.activo = 1 AND m.url IS NOT NULL) AS pantallas
                  FROM s_roles r ORDER BY r.prioridad DESC, r.nombre
            """)
            lista = cur.fetchall()
            arbol = _arbol(_menu_completo(cur)) if rol else []
    protegidas = {n["id"] for n in arbol if n["url"] in MENU_PROTEGIDO} if rol and rol["nombre"] == ROL_ADMIN else set()
    return render_template("admin/roles.html", roles=lista, rol=rol, arbol=arbol, marcadas=marcadas or set(),
                           protegidas=protegidas, errores=errores, abrir_ficha=bool(rol))


# =============================================================================
# Permisos por usuario
# =============================================================================

@admin_bp.route("/permisos", methods=["GET", "POST"])
def permisos():
    """
    Opciones sueltas para una persona, además de las de sus roles
    (`s_menu_usuario`). Lo que dan los roles se ve tildado y sin poder tocarse:
    para quitarlo hay que cambiar el rol, porque el permiso es la suma
    (`db.roles_y_menu`). En gestion_adm esta pantalla era la lista completa
    —copiaba lo del rol—, y un cambio en el rol no le llegaba a quien ya tenía
    sus permisos copiados.
    """
    salida = _guardia("admin.permisos")
    if salida:
        return salida
    fuente = request.form if request.method == "POST" else request.args
    uid = _id("usuario", fuente)

    with get_connection() as conn:
        with conn.cursor() as cur:
            usuarios_ = _usuarios_para_elegir(cur)
            usuario = next((u for u in usuarios_ if u["id"] == uid), None)
            menu = _menu_completo(cur)
            por_id = {m["id"]: m for m in menu}
            por_rol: dict[int, list[str]] = {}
            extras: set[int] = set()
            if usuario:
                cur.execute("""SELECT mr.menu_id, r.nombre
                                 FROM s_menu_rol mr
                                 JOIN s_usuario_rol ur ON ur.rol_id = mr.rol_id
                                 JOIN s_roles r ON r.id = mr.rol_id AND r.activo = 1
                                WHERE ur.usuario_id = %s ORDER BY r.prioridad DESC""", (uid,))
                for f in cur.fetchall():
                    por_rol.setdefault(f["menu_id"], []).append(f["nombre"])

            if request.method == "POST":
                if not usuario:
                    flash("!Elegí un usuario.")
                    return redirect(url_for("admin.permisos"))
                nuevas = _con_ancestros(_ids("menu_ids") & set(por_id), por_id) - set(por_rol)
                cur.execute("DELETE FROM s_menu_usuario WHERE usuario_id = %s", (uid,))
                if nuevas:
                    cur.executemany("INSERT INTO s_menu_usuario (usuario_id, menu_id) VALUES (%s, %s)",
                                    [(uid, m) for m in sorted(nuevas)])
                if uid == session.get("sind_usuario_id"):
                    _refrescar_sesion()
                    flash(f"Tus permisos quedaron guardados: {len(nuevas)} opciones además de las de tus roles.")
                else:
                    flash(f"Permisos de «{usuario['nombre']}» guardados: {len(nuevas)} opciones además de las "
                          "de sus roles. Los ve desde su próximo ingreso.")
                return redirect(url_for("admin.permisos", usuario=uid))

            if usuario:
                cur.execute("SELECT menu_id FROM s_menu_usuario WHERE usuario_id = %s", (uid,))
                extras = {f["menu_id"] for f in cur.fetchall()}
    return render_template("admin/permisos.html", usuarios=usuarios_, usuario=usuario,
                           arbol=_arbol(menu) if usuario else [], por_rol=por_rol, extras=extras)


# =============================================================================
# Menú
# =============================================================================

_SVG_PROHIBIDO = re.compile(r"<\s*script|<\s*foreignObject|\son\w+\s*=|javascript:", re.I)


def _icono_valido(svg) -> str | None:
    """
    El ícono se dibuja tal cual en el menú (`|safe` en base.html): tiene que
    ser un SVG y nada más. Lo carga un administrador, pero un ícono copiado de
    internet puede traer un `onload`.
    """
    if not svg:
        return None
    if not (svg.lower().startswith("<svg") and svg.lower().rstrip().endswith("</svg>")):
        return "El ícono tiene que ser un SVG completo, de <svg …> a </svg>."
    if _SVG_PROHIBIDO.search(svg):
        return "El ícono trae código (script, on…=, javascript:): no se guarda."
    if len(svg) > 6000:
        return "El ícono es demasiado largo (más de 6.000 caracteres)."
    return None


@admin_bp.route("/menu", methods=["GET", "POST"])
def menu():
    salida = _guardia("admin.menu")
    if salida:
        return salida
    errores, item = [], None

    if request.method == "POST":
        accion, mid = request.form.get("accion", ""), _id("id")
        with get_connection() as conn:
            with conn.cursor() as cur:
                arbol = _arbol(_menu_completo(cur))
                por_id = {n["id"]: n for n in arbol}
                actual = por_id.get(mid) if mid else None
                if mid and not actual:
                    flash("!La opción ya no existe.")
                    return redirect(url_for("admin.menu"))
                protegida = bool(actual and actual["url"] in MENU_PROTEGIDO)

                if accion in ("borrar", "baja", "reactivar") and actual:
                    if accion == "reactivar":
                        cur.execute("UPDATE s_menu SET activo = 1 WHERE id = %s", (mid,))
                        flash(f"«{actual['nombre']}» reactivada.")
                    elif protegida:
                        flash(f"!«{actual['nombre']}» no se desactiva ni se elimina: sin esa pantalla nadie "
                              "podría volver a dar permisos.")
                    elif accion == "baja":
                        cur.execute("UPDATE s_menu SET activo = 0 WHERE id = %s", (mid,))
                        flash(f"«{actual['nombre']}» desactivada: deja de verse en el menú y de dar permiso "
                              "a su pantalla" + (", y con ella todo lo que cuelga de su rama." if actual["n_hijos"] else "."))
                    elif actual["n_hijos"]:
                        n = actual["n_hijos"]
                        flash(f"!«{actual['nombre']}» tiene {n} {'opción' if n == 1 else 'opciones'} debajo. "
                              f"{'Movela o eliminala' if n == 1 else 'Movelas o eliminalas'} antes: la base "
                              f"{'la borraría' if n == 1 else 'las borraría'} junto con ella.")
                    else:
                        cur.execute("DELETE FROM s_menu WHERE id = %s", (mid,))
                        flash(f"«{actual['nombre']}» eliminada, y quitada de los roles y usuarios que la tenían.")
                    return redirect(url_for("admin.menu"))
                if accion != "guardar":
                    return redirect(url_for("admin.menu"))

                item = {"id": mid, "padre_id": _id("padre_id"), "nombre": _texto("nombre", 100),
                        "url": _texto("url", 255).replace(" ", "") or None,
                        "icono_svg": (request.form.get("icono_svg") or "").strip() or None,
                        "orden": _entero("orden"), "activo": 1 if request.form.get("activo") else 0,
                        "protegida": protegida}
                if not item["nombre"]:
                    errores.append("El nombre es obligatorio.")
                if item["url"]:
                    if not item["url"].startswith("/"):
                        errores.append(f"«{item['url']}» no es una ruta: empieza con «/». Dejala vacía si la "
                                       "opción solo agrupa otras.")
                    else:
                        otra = next((n for n in arbol if n["url"] == item["url"] and n["id"] != mid), None)
                        if otra:
                            errores.append(f"La URL {item['url']} ya es de «{otra['nombre']}»: dos opciones con "
                                           "la misma pantalla no se distinguen al dar permisos.")
                padre = por_id.get(item["padre_id"]) if item["padre_id"] else None
                if item["padre_id"] and not padre:
                    errores.append("La rama elegida ya no existe.")
                elif padre and mid and (padre["id"] == mid or padre["id"] in _descendientes(arbol, mid)):
                    errores.append("Una opción no puede ir dentro de sí misma ni de una de las suyas.")
                elif padre and padre["url"]:
                    errores.append(f"«{padre['nombre']}» abre una pantalla: una opción con URL no puede "
                                   "tener opciones debajo (el menú no la despliega).")
                else:
                    prof = (padre["prof"] + 1) if padre else 0
                    alto = _altura(arbol, mid) if mid else 1
                    if prof + alto > MENU_NIVELES:
                        errores.append(f"El menú tiene hasta {MENU_NIVELES} niveles y así quedarían "
                                       f"{prof + alto}.")
                if mid and actual["n_hijos"] and item["url"]:
                    errores.append("Tiene opciones debajo: es una rama y no lleva URL.")
                if protegida:
                    if item["url"] != actual["url"]:
                        errores.append(f"La URL de «{actual['nombre']}» no se cambia: sin esa pantalla nadie "
                                       "podría volver a dar permisos.")
                    if not item["activo"]:
                        errores.append(f"«{actual['nombre']}» no se desactiva.")
                e = _icono_valido(item["icono_svg"])
                if e:
                    errores.append(e)

                if not errores:
                    cols = ("padre_id", "nombre", "url", "icono_svg", "orden", "activo")
                    if mid:
                        cur.execute(f"UPDATE s_menu SET {', '.join(c + ' = %s' for c in cols)} WHERE id = %s",
                                    [item[c] for c in cols] + [mid])
                    else:
                        cur.execute(f"INSERT INTO s_menu ({', '.join(cols)}, nivel) "
                                    f"VALUES ({', '.join(['%s'] * len(cols))}, 1)", [item[c] for c in cols])
                        mid = cur.lastrowid
                    _rearmar_niveles(cur, "s_menu")
                    flash(f"«{item['nombre']}» " + ("guardada." if item["id"] else
                          "agregada. Todavía no la tiene nadie: asignala en Roles."))
                    return redirect(url_for("admin.menu", _anchor=f"m{mid}"))

    with get_connection() as conn:
        with conn.cursor() as cur:
            menu_ = _menu_completo(cur)
            cur.execute("""SELECT mr.menu_id, GROUP_CONCAT(r.nombre ORDER BY r.prioridad DESC SEPARATOR ', ') AS roles
                             FROM s_menu_rol mr JOIN s_roles r ON r.id = mr.rol_id GROUP BY mr.menu_id""")
            roles_de = {f["menu_id"]: f["roles"] for f in cur.fetchall()}
            cur.execute("SELECT menu_id, COUNT(*) AS n FROM s_menu_usuario GROUP BY menu_id")
            extras_de = {f["menu_id"]: f["n"] for f in cur.fetchall()}
    arbol = _arbol(menu_)
    for n in arbol:
        n["roles"] = roles_de.get(n["id"])
        n["extras"] = extras_de.get(n["id"], 0)
        n["pantalla"] = _ruta_existe(n["url"]) if n["url"] else None
        n["protegida"] = n["url"] in MENU_PROTEGIDO

    edit_id = request.args.get("edit", type=int)
    if edit_id and item is None:
        item = next((n for n in arbol if n["id"] == edit_id), None)
        if not item:
            flash("!La opción no existe.")
            return redirect(url_for("admin.menu"))
    if item is None and (request.args.get("nuevo") or request.args.get("padre")):
        item = {"activo": 1, "padre_id": request.args.get("padre", type=int), "orden": 0}
        hermanos = [n["orden"] for n in arbol if n["padre_id"] == item["padre_id"]]
        item["orden"] = (max(hermanos) + 1) if hermanos else 1
    excluir = ({item["id"]} | _descendientes(arbol, item["id"])) if item and item.get("id") else set()
    ramas = [n for n in arbol if not n["url"] and n["id"] not in excluir and n["prof"] < MENU_NIVELES - 1]
    return render_template("admin/menu.html", arbol=arbol, item=item, ramas=ramas, errores=errores,
                           niveles=MENU_NIVELES, abrir_ficha=bool(item or errores))


# =============================================================================
# Áreas
# =============================================================================

@admin_bp.route("/areas", methods=["GET", "POST"])
def areas():
    """
    El organigrama: a dónde se deriva un expediente en la mesa de entradas.
    Un área que se usa (expedientes, movimientos, proveedores, nómina) no se
    elimina —el expediente perdería a dónde fue—: se desactiva. Al eliminar
    una sin uso, sus subáreas pasan a colgar del área madre, como en gestion_adm.
    """
    salida = _guardia("admin.areas")
    if salida:
        return salida
    errores, area = [], None

    if request.method == "POST":
        accion, aid = request.form.get("accion", ""), _id("id")
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, padre_id, nombre, descripcion, orden, nivel, activo FROM s_areas "
                            "ORDER BY orden, nombre")
                arbol = _arbol(cur.fetchall())
                por_id = {n["id"]: n for n in arbol}
                actual = por_id.get(aid) if aid else None
                if aid and not actual:
                    flash("!El área ya no existe.")
                    return redirect(url_for("admin.areas"))

                if accion in ("borrar", "baja", "reactivar") and actual:
                    if accion in ("baja", "reactivar"):
                        cur.execute("UPDATE s_areas SET activo = %s WHERE id = %s",
                                    (1 if accion == "reactivar" else 0, aid))
                        flash(f"«{actual['nombre']}» " + ("reactivada." if accion == "reactivar" else
                              "desactivada: ya no se ofrece para derivar. Lo que se derivó ahí lo sigue diciendo."))
                    else:
                        usos = _usos(cur, "s_areas", [aid])[aid]
                        if usos:
                            flash(f"!No se puede eliminar «{actual['nombre']}»: figura en {_texto_usos(usos)}. "
                                  "Desactivala.")
                        else:
                            cur.execute("UPDATE s_areas SET padre_id = %s WHERE padre_id = %s",
                                        (actual["padre_id"], aid))
                            cur.execute("DELETE FROM s_areas WHERE id = %s", (aid,))
                            _rearmar_niveles(cur, "s_areas")
                            n = actual["n_hijos"]
                            flash(f"«{actual['nombre']}» eliminada" + (
                                "; su subárea pasó a depender de su área madre." if n == 1 else
                                f"; sus {n} subáreas pasaron a depender de su área madre." if n else "."))
                    return redirect(url_for("admin.areas"))
                if accion != "guardar":
                    return redirect(url_for("admin.areas"))

                area = {"id": aid, "padre_id": _id("padre_id"), "nombre": _texto("nombre", 100),
                        "descripcion": _texto("descripcion", 250) or None, "orden": _entero("orden"),
                        "activo": 1 if request.form.get("activo") else 0}
                if not area["nombre"]:
                    errores.append("El nombre es obligatorio.")
                else:
                    gemela = next((n for n in arbol if n["nombre"].upper() == area["nombre"].upper()
                                   and n["padre_id"] == area["padre_id"] and n["id"] != aid), None)
                    if gemela:
                        errores.append(f"Ya hay un área «{gemela['nombre']}» en ese lugar del organigrama: "
                                       "al derivar no se distinguirían.")
                padre = por_id.get(area["padre_id"]) if area["padre_id"] else None
                if area["padre_id"] and not padre:
                    errores.append("El área madre ya no existe.")
                elif padre and aid and (padre["id"] == aid or padre["id"] in _descendientes(arbol, aid)):
                    errores.append("Un área no puede depender de sí misma ni de una de sus subáreas.")
                elif ((padre["prof"] + 1) if padre else 0) + (_altura(arbol, aid) if aid else 1) > AREA_NIVELES:
                    errores.append(f"El organigrama tiene hasta {AREA_NIVELES} niveles.")

                if not errores:
                    cols = ("padre_id", "nombre", "descripcion", "orden", "activo")
                    if aid:
                        cur.execute(f"UPDATE s_areas SET {', '.join(c + ' = %s' for c in cols)} WHERE id = %s",
                                    [area[c] for c in cols] + [aid])
                    else:
                        cur.execute(f"INSERT INTO s_areas ({', '.join(cols)}, nivel) "
                                    f"VALUES ({', '.join(['%s'] * len(cols))}, 1)", [area[c] for c in cols])
                    _rearmar_niveles(cur, "s_areas")
                    flash(f"Área «{area['nombre']}» " + ("guardada." if aid else "agregada."))
                    return redirect(url_for("admin.areas"))

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT a.id, a.padre_id, a.nombre, a.descripcion, a.orden, a.nivel, a.activo,
                                  (SELECT COUNT(*) FROM s_area_usuario au JOIN s_usuarios u ON u.id = au.usuario_id
                                    WHERE au.area_id = a.id AND u.activo = 1) AS usuarios
                             FROM s_areas a ORDER BY a.orden, a.nombre""")
            arbol = _arbol(cur.fetchall())
            usos = _usos(cur, "s_areas", [n["id"] for n in arbol])
    for n in arbol:
        n["usos"] = usos.get(n["id"], [])

    edit_id = request.args.get("edit", type=int)
    if edit_id and area is None:
        area = next((n for n in arbol if n["id"] == edit_id), None)
        if not area:
            flash("!El área no existe.")
            return redirect(url_for("admin.areas"))
    if area is None and (request.args.get("nuevo") or request.args.get("padre")):
        area = {"activo": 1, "padre_id": request.args.get("padre", type=int)}
        hermanos = [n["orden"] for n in arbol if n["padre_id"] == area["padre_id"]]
        area["orden"] = (max(hermanos) + 1) if hermanos else 1
    excluir = ({area["id"]} | _descendientes(arbol, area["id"])) if area and area.get("id") else set()
    madres = [n for n in arbol if n["id"] not in excluir and n["prof"] < AREA_NIVELES - 1]
    return render_template("admin/areas.html", arbol=arbol, area=area, madres=madres, errores=errores,
                           niveles=AREA_NIVELES, abrir_ficha=bool(area or errores))


# =============================================================================
# Áreas por usuario
# =============================================================================

@admin_bp.route("/areas_usuario", methods=["GET", "POST"])
def areas_usuario():
    """
    A qué áreas pertenece cada persona y con qué función (`rol_area`, texto
    libre: «Jefe», «Auditor»). La mesa de entradas lo usa para ofrecer, al
    derivar, a las personas del área. Solo las áreas activas: las asignaciones
    a una desactivada se conservan al guardar.
    """
    salida = _guardia("admin.areas_usuario")
    if salida:
        return salida
    fuente = request.form if request.method == "POST" else request.args
    uid = _id("usuario", fuente)

    with get_connection() as conn:
        with conn.cursor() as cur:
            usuarios_ = _usuarios_para_elegir(cur)
            usuario = next((u for u in usuarios_ if u["id"] == uid), None)
            cur.execute("SELECT id, padre_id, nombre, descripcion, orden, nivel, activo FROM s_areas "
                        "ORDER BY orden, nombre")
            arbol = _arbol(cur.fetchall())
            activas = {n["id"] for n in arbol if n["activo"]}

            if request.method == "POST":
                if not usuario:
                    flash("!Elegí un usuario.")
                    return redirect(url_for("admin.areas_usuario"))
                elegidas = _ids("area_ids") & activas
                cur.execute("""DELETE au FROM s_area_usuario au JOIN s_areas a ON a.id = au.area_id
                                WHERE au.usuario_id = %s AND a.activo = 1""", (uid,))
                if elegidas:
                    cur.executemany(
                        "INSERT INTO s_area_usuario (usuario_id, area_id, rol_area) VALUES (%s, %s, %s)",
                        [(uid, a, _texto(f"rol_area_{a}", 100) or None) for a in sorted(elegidas)])
                flash(f"Áreas de «{usuario['nombre']}» guardadas: {len(elegidas)}.")
                return redirect(url_for("admin.areas_usuario", usuario=uid))

            asignadas = {}
            if usuario:
                cur.execute("SELECT area_id, rol_area FROM s_area_usuario WHERE usuario_id = %s", (uid,))
                asignadas = {f["area_id"]: f["rol_area"] or "" for f in cur.fetchall()}
            cur.execute("""SELECT au.area_id, GROUP_CONCAT(u.nombre ORDER BY u.nombre SEPARATOR ', ') AS personas
                             FROM s_area_usuario au JOIN s_usuarios u ON u.id = au.usuario_id AND u.activo = 1
                            GROUP BY au.area_id""")
            personas = {f["area_id"]: f["personas"] for f in cur.fetchall()}
    return render_template("admin/areas_usuario.html", usuarios=usuarios_, usuario=usuario,
                           arbol=arbol if usuario else [], asignadas=asignadas, personas=personas)
