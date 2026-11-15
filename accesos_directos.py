"""
accesos_directos.py — Las pantallas que cada usuario fija en su panel de inicio
(pedido del 15/11/2026: «hacela funcionar»). El de gestion_adm
(`accesos_directos.py`, `templates/menu.html`) con las claves de sesión y los
estilos de acá.

La chincheta de cada pantalla del menú lateral (base.html, `fijarAcceso`) la
fija o la saca; el **panel de inicio** (/menu, el botón Inicio) muestra las
fijadas como tarjetas, agrupadas por el módulo del que cuelgan, que se ordenan
arrastrando y se sacan con la X. Quien no fijó ninguna sigue entrando al Panel
de Fiscalización, como antes: nadie se encuentra con un inicio vacío.

**Se guarda el `menu_id`**, no el nombre ni la URL (`s_accesos_directos`, que
vino con la base: uno por usuario y opción, con su orden): si la pantalla
cambia de nombre o de dirección, el acceso la sigue.

**El permiso sigue siendo la opción de menú.** Solo se fija una pantalla (con
URL, activa) que está entre las de la sesión (`sind_menu_ids`), y al listar se
vuelve a cruzar con ellas: si a alguien le sacan una pantalla, su tarjeta deja
de verse sola; no se borra, porque el permiso puede volver.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from db import get_connection, validasesion

accesos_bp = Blueprint("accesos", __name__, url_prefix="/accesos-directos")


def _usuario_id() -> int | None:
    return session.get("sind_usuario_id")


def _menus() -> list[int]:
    return [int(x) for x in (session.get("sind_menu_ids") or [])]


def con_modulo(filas: list[dict], ramas: dict) -> list[dict]:
    """A cada acceso, el módulo del que cuelga: la rama de más arriba del menú,
    subiendo por `padre_id` (`ramas`: id → fila de s_menu). Aparte para
    probarlo sin base."""
    for fila in filas:
        raiz, padre, vistos = None, ramas.get(fila.get("padre_id")), set()
        while padre and padre["id"] not in vistos:
            vistos.add(padre["id"])          # un padre_id circular no cuelga
            raiz = padre
            padre = ramas.get(padre.get("padre_id"))
        fila["modulo_id"] = raiz["id"] if raiz else 0
        fila["modulo"] = raiz["nombre"] if raiz else "General"
        fila["modulo_icono"] = (raiz or {}).get("icono_svg")
    return filas


def agrupar(accesos: list[dict]) -> list[dict]:
    """Las tarjetas en una caja por módulo. El orden de los módulos sale del de
    las tarjetas (manda la primera de cada uno): arrastrar una tarjeta adelante
    también sube su módulo, sin un segundo orden que guardar."""
    grupos, indice = [], {}
    for a in accesos:
        clave = a.get("modulo_id") or 0
        if clave not in indice:
            indice[clave] = {"modulo_id": clave, "modulo": a.get("modulo") or "General",
                             "icono": a.get("modulo_icono"), "items": []}
            grupos.append(indice[clave])
        indice[clave]["items"].append(a)
    return grupos


def listar(usuario_id: int | None = None) -> list[dict]:
    """Las tarjetas del panel, en orden, solo de pantallas que la sesión tiene."""
    usuario_id = usuario_id or _usuario_id()
    habilitados = _menus()
    if not usuario_id or not habilitados:
        return []
    marcas = ",".join(["%s"] * len(habilitados))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT a.menu_id, a.orden, m.nombre, m.url, m.icono_svg, m.padre_id
                  FROM s_accesos_directos a
                  JOIN s_menu m ON m.id = a.menu_id AND m.activo = 1
                 WHERE a.usuario_id = %s AND a.menu_id IN ({marcas})
                   AND m.url IS NOT NULL AND m.url <> ''
                 ORDER BY a.orden, m.nombre""", [usuario_id] + habilitados)
            filas = cur.fetchall()
            if not filas:
                return []
            # El menú entero de una vez: son unas decenas de filas y evita una
            # consulta por tarjeta.
            cur.execute("SELECT id, padre_id, nombre, icono_svg FROM s_menu")
            ramas = {f["id"]: f for f in cur.fetchall()}
    return con_modulo(filas, ramas)


def _menu_id() -> int:
    datos = request.get_json(silent=True) or {}
    try:
        return int(datos.get("menu_id") or request.form.get("menu_id") or 0)
    except (TypeError, ValueError):
        return 0


@accesos_bp.route("/alternar", methods=["POST"])
def alternar():
    """La chincheta: fija o saca la pantalla. Devuelve cómo quedó."""
    if not validasesion():
        return jsonify({"error": "La sesión venció: volvé a ingresar."}), 401
    usuario_id, menu_id = _usuario_id(), _menu_id()
    if not usuario_id or not menu_id:
        return jsonify({"error": "Falta la opción de menú."}), 400
    if menu_id not in _menus():
        return jsonify({"error": "Esa pantalla no está entre tus permisos."}), 403

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT nombre, url FROM s_menu WHERE id = %s AND activo = 1", (menu_id,))
            m = cur.fetchone()
            if not m or not m["url"]:
                return jsonify({"error": "Solo se fijan pantallas, no las ramas del menú."}), 400
            cur.execute("SELECT id FROM s_accesos_directos WHERE usuario_id = %s AND menu_id = %s",
                        (usuario_id, menu_id))
            ya = cur.fetchone()
            if ya:
                cur.execute("DELETE FROM s_accesos_directos WHERE id = %s", (ya["id"],))
                return jsonify({"fijado": False})
            # Al final: el usuario lo acomoda arrastrando si lo quiere en otro lugar.
            cur.execute("SELECT COALESCE(MAX(orden), 0) + 1 AS prox FROM s_accesos_directos "
                        "WHERE usuario_id = %s", (usuario_id,))
            prox = cur.fetchone()["prox"]
            cur.execute("""INSERT INTO s_accesos_directos (usuario_id, menu_id, orden) VALUES (%s, %s, %s)
                           ON DUPLICATE KEY UPDATE orden = VALUES(orden)""", (usuario_id, menu_id, prox))
    return jsonify({"fijado": True, "nombre": m["nombre"], "url": m["url"]})


@accesos_bp.route("/quitar", methods=["POST"])
def quitar():
    """La X de la tarjeta."""
    if not validasesion():
        return jsonify({"error": "La sesión venció: volvé a ingresar."}), 401
    usuario_id, menu_id = _usuario_id(), _menu_id()
    if not usuario_id or not menu_id:
        return jsonify({"error": "Falta la opción de menú."}), 400
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM s_accesos_directos WHERE usuario_id = %s AND menu_id = %s",
                        (usuario_id, menu_id))
    return jsonify({"ok": True})


@accesos_bp.route("/ordenar", methods=["POST"])
def ordenar():
    """El orden después de arrastrar: llega la lista entera de menu_id, como
    quedó en la pantalla (es lo que el navegador ya sabe)."""
    if not validasesion():
        return jsonify({"error": "La sesión venció: volvé a ingresar."}), 401
    usuario_id = _usuario_id()
    orden = (request.get_json(silent=True) or {}).get("orden")
    if not usuario_id or not isinstance(orden, list):
        return jsonify({"error": "Orden inválido."}), 400
    try:
        ids = [int(x) for x in orden]
    except (TypeError, ValueError):
        return jsonify({"error": "Orden inválido."}), 400
    with get_connection() as conn:
        with conn.cursor() as cur:
            for posicion, menu_id in enumerate(ids, start=1):
                cur.execute("UPDATE s_accesos_directos SET orden = %s WHERE usuario_id = %s AND menu_id = %s",
                            (posicion, usuario_id, menu_id))
    return jsonify({"ok": True})
