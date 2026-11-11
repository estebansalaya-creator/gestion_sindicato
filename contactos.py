"""
contactos.py — Contactos de terceros (`s_contactos`).

Mismo método que el ABM de proveedores de `gestion_adm`: la lógica vive acá una
sola vez y cada pantalla incluye el parcial `_contactos.html`. Importa que sea
uno solo porque de estos contactos sale el destinatario de los avisos: con un
formulario por pantalla, el mismo dato se guardaría distinto según desde dónde
se cargó, y el mail le llegaría a quien no es.

DIFERENCIA CON EL ORIGINAL: LAS TRANSACCIONES SON DE VERDAD
-----------------------------------------------------------
El de `gestion_adm` dice «va en la misma transacción» y llama a `conn.commit()`,
pero su conexión abre con `autocommit=True` —igual que la nuestra—, así que cada
sentencia ya quedó confirmada cuando llega el commit, que no hace nada. En la
práctica, si el INSERT del contacto anduviera y el UPDATE que apaga los demás
principales fallara, la entidad quedaba con dos principales.

Acá el bloque abre con `conn.begin()`, que suspende el autocommit hasta el
`commit()`. Con eso «marcar principal» pasa a ser una operación sola: o quedan
uno prendido y el resto apagados, o no cambia nada.
"""

import logging
import re

from flask import (Blueprint, request, redirect, url_for, flash, jsonify)

from db import get_connection, puede, validasesion

log = logging.getLogger(__name__)

contactos_bp = Blueprint("contactos", __name__, url_prefix="/contactos")

# Se valida contra esta lista y no contra lo que venga en la URL: `entidad_tipo`
# entra en un WHERE y en un INSERT, y un valor inventado ensucia la tabla sin
# que nadie lo vea.
#
# Una línea por pantalla que tenga contactos. `c_proveedores` existe en la base
# pero no tiene pantalla, y declarar acá un `volver` a un endpoint inexistente
# es peor que no declararlo: no falla al importar, falla al redirigir, con la
# fila ya guardada. Cuando esa pantalla exista, se agrega su línea.
ENTIDADES = {
    "empresa":  {"tabla": "p_empresas",  "pk": "id",
                 "volver": "empleadores.abm_empleadores"},
    "afiliado": {"tabla": "p_afiliados", "pk": "id_afiliado",
                 "volver": "afiliados.abm_afiliados",
                 # Modificar los contactos de un afiliado es modificar el
                 # padrón: pide el mismo permiso que el ABM.
                 "permiso": "afiliados.abm_afiliados"},
    "proveedor": {"tabla": "c_proveedores", "pk": "id",
                  "volver": "proveedores.abm",
                  "permiso": "proveedores.abm"},
}

RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def areas(cur) -> list[dict]:
    """El catálogo de áreas del tercero, para el combo."""
    cur.execute("""SELECT id, nombre, descripcion FROM c_areas_contacto
                    WHERE activo = 1 ORDER BY orden, nombre""")
    return cur.fetchall()


def de(cur, entidad_tipo: str, entidad_id: int) -> list[dict]:
    """
    Los contactos activos de una entidad, con el nombre del área resuelto.

    El principal primero: es el que usa el envío cuando el aviso no pide un
    área en particular.
    """
    cur.execute("""
        SELECT c.*, a.nombre AS area
          FROM s_contactos c
          LEFT JOIN c_areas_contacto a ON a.id = c.id_area_contacto
         WHERE c.entidad_tipo = %s AND c.entidad_id = %s AND c.activo = 1
         ORDER BY c.principal DESC, a.orden, c.nombre
    """, (entidad_tipo, entidad_id))
    return cur.fetchall()


def _marcar_principal(cur, entidad_tipo: str, entidad_id: int, id_contacto: int):
    """Apaga el resto de los principales de la misma entidad."""
    cur.execute("""UPDATE s_contactos SET principal = 0
                    WHERE entidad_tipo = %s AND entidad_id = %s AND id <> %s""",
                (entidad_tipo, entidad_id, id_contacto or 0))


def _datos_del_form(form) -> dict:
    d = {
        "nombre":            (form.get("nombre") or "").strip(),
        "cargo":             (form.get("cargo") or "").strip() or None,
        "id_area_contacto":  form.get("id_area_contacto") or None,
        "telefono":          (form.get("telefono") or "").strip() or None,
        "celular":           (form.get("celular") or "").strip() or None,
        "email":             (form.get("email") or "").strip() or None,
        "principal":         1 if form.get("principal") else 0,
    }
    if d["id_area_contacto"]:
        d["id_area_contacto"] = int(d["id_area_contacto"])
    return d


def _validar(d: dict) -> list[str]:
    errores = []
    if not d["nombre"]:
        errores.append("El nombre es obligatorio.")
    # El mail no es obligatorio —un contacto puede ser solo telefónico— pero si
    # está tiene que servir: una dirección mal escrita no falla al guardarla,
    # falla al mandar, cuando ya nadie está mirando.
    if d["email"] and not RE_EMAIL.match(d["email"]):
        errores.append(f"La dirección «{d['email']}» no es válida.")
    return errores


@contactos_bp.route("/<entidad_tipo>/<int:entidad_id>", methods=["POST"])
def guardar(entidad_tipo, entidad_id):
    """Alta, edición y baja lógica de un contacto."""
    if not validasesion():
        return redirect(url_for("login"))

    if entidad_tipo not in ENTIDADES:
        flash("Tipo de entidad desconocido.")
        return redirect(url_for("menu"))

    accion = request.form.get("accion", "")
    volver = request.form.get("volver")
    if not volver:
        volver = url_for(ENTIDADES[entidad_tipo]["volver"], edit=entidad_id)

    permiso = ENTIDADES[entidad_tipo].get("permiso")
    if permiso and not puede(url_for(permiso)):
        flash("!No tenés permiso para modificar estos contactos.")
        return redirect(volver)

    try:
        with get_connection() as conn:
            # Suspende el autocommit: lo de acá adentro queda todo o nada.
            conn.begin()
            with conn.cursor() as cur:

                if accion == "borrar":
                    # Baja lógica: el contacto puede estar referido en la
                    # bitácora de envíos, y borrarlo de verdad dejaría sin
                    # explicación a quién se le mandó.
                    cur.execute("""UPDATE s_contactos SET activo = 0
                                    WHERE id = %s AND entidad_tipo = %s AND entidad_id = %s""",
                                (request.form.get("id"), entidad_tipo, entidad_id))
                    conn.commit()
                    flash("Contacto eliminado.")
                    return redirect(volver)

                d = _datos_del_form(request.form)
                errores = _validar(d)
                if errores:
                    conn.rollback()
                    for e in errores:
                        flash(e)
                    return redirect(volver)

                if accion == "editar":
                    id_contacto = int(request.form.get("id") or 0)
                    cur.execute("""
                        UPDATE s_contactos
                           SET nombre=%s, cargo=%s, id_area_contacto=%s,
                               telefono=%s, celular=%s, email=%s, principal=%s,
                               actualizado=NOW()
                         WHERE id=%s AND entidad_tipo=%s AND entidad_id=%s
                    """, (d["nombre"], d["cargo"], d["id_area_contacto"],
                          d["telefono"], d["celular"], d["email"], d["principal"],
                          id_contacto, entidad_tipo, entidad_id))
                    if d["principal"]:
                        _marcar_principal(cur, entidad_tipo, entidad_id, id_contacto)
                    conn.commit()
                    flash("Contacto actualizado.")
                    return redirect(volver)

                # Alta. El primero de una entidad queda principal aunque no se
                # haya tildado: si no, no hay a quién mandarle cuando el aviso
                # no pide un área.
                cur.execute("""SELECT COUNT(*) AS n FROM s_contactos
                                WHERE entidad_tipo=%s AND entidad_id=%s AND activo=1""",
                            (entidad_tipo, entidad_id))
                primero = not (cur.fetchone() or {}).get("n")

                cur.execute("""
                    INSERT INTO s_contactos
                        (entidad_tipo, entidad_id, nombre, cargo, id_area_contacto,
                         telefono, celular, email, principal, activo,
                         creado, actualizado)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,1,NOW(),NOW())
                """, (entidad_tipo, entidad_id, d["nombre"], d["cargo"],
                      d["id_area_contacto"], d["telefono"], d["celular"],
                      d["email"], 1 if (d["principal"] or primero) else 0))
                # `lastrowid` se lee dentro del context manager del cursor:
                # afuera ya está cerrado.
                nuevo = cur.lastrowid
                if d["principal"] or primero:
                    _marcar_principal(cur, entidad_tipo, entidad_id, nuevo)
                conn.commit()
                flash("Contacto agregado.")

    except Exception as e:
        # Se reporta, no se traga. Va por flash y no como excepción porque el
        # contacto es un bloque lateral de una pantalla más grande: volar toda
        # la pantalla por un contacto mal cargado pierde el resto del trabajo.
        log.exception("Guardando contacto de %s %s", entidad_tipo, entidad_id)
        flash(f"No se pudo guardar el contacto: {e}")

    return redirect(volver)


@contactos_bp.route("/areas", methods=["GET", "POST"], endpoint="abm_areas")
def abm_areas():
    """
    El catálogo de áreas. Permite crear una desde el formulario del contacto.

    Se puede crear al vuelo porque la alternativa —mandar a la persona a otra
    pantalla en medio de la carga— termina en que elige cualquiera con tal de
    seguir, y el catálogo deja de significar algo.
    """
    if not validasesion():
        return jsonify({"error": "sesión vencida"}), 401

    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()
        if not nombre:
            return jsonify({"error": "Falta el nombre."}), 400
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    # La unicidad la aplica la base, no el código: dos personas
                    # cargando a la vez pasan cualquier control previo.
                    cur.execute("""INSERT INTO c_areas_contacto (nombre, orden, activo)
                                   VALUES (%s, 999, 1)
                                   ON DUPLICATE KEY UPDATE activo = 1""", (nombre,))
                    cur.execute("SELECT id, nombre FROM c_areas_contacto WHERE nombre = %s",
                                (nombre,))
                    area = cur.fetchone()
            return jsonify(area)
        except Exception as e:
            log.exception("Creando área de contacto")
            return jsonify({"error": str(e)}), 500

    with get_connection() as conn:
        with conn.cursor() as cur:
            return jsonify(areas(cur))
