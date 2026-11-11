"""
talonarios.py — Talonarios de comprobantes propios (/admin/talonarios, menú 209).

Portado de `gestion_adm/talonarios_routes.py`. Tres niveles, una pantalla con
tres solapas:

    c_contable_comprobante_tipo   Tipos de comprobante (Recibo, Factura…): de qué lado de
      └── c_talonario_clasificacion   la cuenta va (debe / haber). Clasificaciones: agrupan
            └── c_talonario            talonarios de un tipo. Talonarios: punto de venta,
                                       letra, rango y por dónde va la numeración.

FORMULARIOS SATÉLITE
Para cargar un talonario hace falta una clasificación, y para ella un tipo. Si
no existe, se crea desde el mismo formulario, en un diálogo, sin perder lo
tipeado (`/api/clasificacion`, `/api/tipo`, JSON): queda elegida al volver.

REGLAS (las de gestion_adm, más las de un talonario usado)
- Usado = emitió algún comprobante (`ultimo_emitido` dentro del rango o filas en
  `c_comprobantes_emitidos`). Uno usado no se elimina (se deshabilita) y no le
  cambia el punto de venta, la letra, el número desde ni la clasificación: los
  comprobantes emitidos quedarían con un número que el talonario ya no dice.
  El hasta solo crece hasta cubrir lo emitido.
- `ultimo_emitido` nunca retrocede.
- Dos talonarios del mismo tipo de comprobante, punto de venta y letra no se
  superponen: emitirían el mismo número (en gestion_adm se miraba por
  clasificación, y dos clasificaciones del mismo tipo lo permitían).
- Un tipo o una clasificación que se usa no se elimina; a uno con comprobantes
  emitidos no se le cambia el lado de la cuenta (debe / haber) ni el tipo.

FUERA, POR SER DE LA OBRA SOCIAL O NO EXISTIR ACÁ
La factura electrónica con ARCA (WSFEv1: tipo ARCA, ambiente, concepto) y el
editor del modelo de impresión. `codigo_arca_comprobante_tipo` y `template`
quedan en la tabla y no se tocan.
"""

from __future__ import annotations

import re

import pymysql
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from db import get_connection, puede, validasesion

talonarios_bp = Blueprint("talonarios", __name__, url_prefix="/admin/talonarios")

LETRAS = ["A", "B", "C", "E", "M", "R", "X"]
LADOS = [("D", "Debe — suma a la deuda (factura, nota de débito)"),
         ("C", "Haber — la cancela (recibo, nota de crédito)")]


# =============================================================================
# Comunes
# =============================================================================

def _permiso() -> bool:
    return validasesion() and puede(url_for("talonarios.index"))


def _guardia():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede(url_for("talonarios.index")):
        flash("!No tenés permiso para los talonarios.")
        return redirect(url_for("menu"))
    return None


def _texto(nombre, largo):
    return re.sub(r"\s+", " ", (request.form.get(nombre) or "").strip())[:largo]


def _entero(nombre):
    v = (request.form.get(nombre) or "").strip().replace(".", "")
    return int(v) if v.isdigit() else None


def _volver(solapa, **kw):
    return redirect(url_for("talonarios.index", solapa=solapa, **kw))


def _emitidos(cur, id_tal) -> int:
    cur.execute("SELECT COUNT(*) AS n FROM c_comprobantes_emitidos WHERE id_talonario = %s", (id_tal,))
    return int(cur.fetchone()["n"] or 0)


def _usado(cur, t) -> bool:
    return (t["ultimo_emitido"] or 0) >= t["numero_desde"] or _emitidos(cur, t["id"]) > 0


def _clasif_con_emitidos(cur, id_clasif) -> int:
    cur.execute("""SELECT COUNT(*) AS n FROM c_comprobantes_emitidos ce
                     JOIN c_talonario t ON t.id = ce.id_talonario
                    WHERE t.c_talonario_clasificacionId = %s""", (id_clasif,))
    n = int(cur.fetchone()["n"] or 0)
    cur.execute("""SELECT COUNT(*) AS n FROM c_talonario
                    WHERE c_talonario_clasificacionId = %s AND ultimo_emitido >= numero_desde""", (id_clasif,))
    return n + int(cur.fetchone()["n"] or 0)


def _validar_tipo(cur, tid, nombre, lado) -> list[str]:
    errores = []
    if not nombre:
        errores.append("El nombre del tipo es obligatorio.")
    else:
        cur.execute("SELECT id FROM c_contable_comprobante_tipo WHERE nombre = %s AND id <> %s", (nombre, tid or 0))
        if cur.fetchone():
            errores.append(f"Ya hay un tipo «{nombre}».")
    if lado not in ("D", "C"):
        errores.append("Elegí de qué lado de la cuenta va: debe o haber.")
    if tid and not errores:
        cur.execute("SELECT debito_credito FROM c_contable_comprobante_tipo WHERE id = %s", (tid,))
        antes = cur.fetchone()
        if antes and antes["debito_credito"] != lado:
            cur.execute("SELECT id FROM c_talonario_clasificacion WHERE id_comprobante_tipo = %s", (tid,))
            if any(_clasif_con_emitidos(cur, c["id"]) for c in cur.fetchall()):
                errores.append("Hay comprobantes emitidos de este tipo: cambiarle el lado daría vuelta su efecto "
                               "en las cuentas corrientes. Creá otro tipo.")
    return errores


def _validar_clasif(cur, cid, descripcion, id_tipo) -> list[str]:
    errores = []
    if not descripcion:
        errores.append("La descripción de la clasificación es obligatoria.")
    else:
        cur.execute("SELECT id FROM c_talonario_clasificacion WHERE descripcion = %s AND id <> %s", (descripcion, cid or 0))
        if cur.fetchone():
            errores.append(f"Ya hay una clasificación «{descripcion}».")
    cur.execute("SELECT id FROM c_contable_comprobante_tipo WHERE id = %s", (id_tipo or 0,))
    if not cur.fetchone():
        errores.append("Elegí el tipo de comprobante.")
    if cid and not errores:
        cur.execute("SELECT id_comprobante_tipo FROM c_talonario_clasificacion WHERE id = %s", (cid,))
        antes = cur.fetchone()
        if antes and antes["id_comprobante_tipo"] != id_tipo and _clasif_con_emitidos(cur, cid):
            errores.append("La clasificación tiene comprobantes emitidos: no se le cambia el tipo.")
    return errores


# =============================================================================
# Pantalla
# =============================================================================

@talonarios_bp.route("", methods=["GET", "POST"])
def index():
    salida = _guardia()
    if salida:
        return salida
    errores, form, solapa = [], None, request.args.get("solapa") or "talonarios"

    if request.method == "POST":
        accion = request.form.get("accion", "")
        rid = _entero("id")
        with get_connection() as conn:
            with conn.cursor() as cur:
                # ── Talonarios ──
                if accion in ("habilitar", "borrar") and rid:
                    cur.execute("SELECT * FROM c_talonario WHERE id = %s", (rid,))
                    t = cur.fetchone()
                    if not t:
                        flash("!El talonario ya no existe.")
                    elif accion == "habilitar":
                        cur.execute("UPDATE c_talonario SET habilitado = 1 - habilitado WHERE id = %s", (rid,))
                        flash(f"Talonario «{t['nombre']}» " + ("deshabilitado." if t["habilitado"] else "habilitado."))
                    elif _usado(cur, t):
                        flash(f"!«{t['nombre']}» ya emitió comprobantes: no se elimina, se deshabilita.")
                    else:
                        cur.execute("DELETE FROM c_talonario WHERE id = %s", (rid,))
                        flash(f"Talonario «{t['nombre']}» eliminado.")
                    return _volver("talonarios")

                if accion == "guardar_talonario":
                    solapa = "talonarios"
                    form = {"id": rid, "nombre": _texto("nombre", 50), "letra": (request.form.get("letra") or "").upper()[:1],
                            "punto_de_venta": _entero("punto_de_venta"), "numero_desde": _entero("numero_desde"),
                            "numero_hasta": _entero("numero_hasta"), "ultimo_emitido": _entero("ultimo_emitido"),
                            "c_talonario_clasificacionId": _entero("clasificacion"),
                            "habilitado": 1 if request.form.get("habilitado") else 0,
                            "comentario": _texto("comentario", 250) or None}
                    errores = _validar_talonario(cur, form)
                    if not errores:
                        cols = ["nombre", "letra", "punto_de_venta", "numero_desde", "numero_hasta", "ultimo_emitido",
                                "c_talonario_clasificacionId", "habilitado", "comentario"]
                        try:
                            if rid:
                                cur.execute(f"UPDATE c_talonario SET {', '.join(c + ' = %s' for c in cols)} WHERE id = %s",
                                            [form[c] for c in cols] + [rid])
                                flash(f"Talonario «{form['nombre']}» guardado.")
                            else:
                                cur.execute(f"INSERT INTO c_talonario ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                                            [form[c] for c in cols])
                                flash(f"Talonario «{form['nombre']}» creado: el primer número es {form['numero_desde']}.")
                            return _volver("talonarios")
                        except pymysql.IntegrityError:
                            errores.append("Ya hay un talonario igual: misma clasificación, nombre, letra, punto de venta y rango.")

                # ── Clasificaciones ──
                if accion == "borrar_clasif" and rid:
                    cur.execute("SELECT descripcion FROM c_talonario_clasificacion WHERE id = %s", (rid,))
                    c = cur.fetchone()
                    cur.execute("SELECT COUNT(*) AS n FROM c_talonario WHERE c_talonario_clasificacionId = %s", (rid,))
                    n = cur.fetchone()["n"]
                    if not c:
                        flash("!La clasificación ya no existe.")
                    elif n:
                        flash(f"!«{c['descripcion']}» tiene {n} talonario(s): no se elimina.")
                    else:
                        cur.execute("DELETE FROM c_talonario_clasificacion WHERE id = %s", (rid,))
                        flash(f"Clasificación «{c['descripcion']}» eliminada.")
                    return _volver("clasificaciones")
                if accion == "guardar_clasif":
                    solapa = "clasificaciones"
                    form = {"id": rid, "descripcion": _texto("descripcion", 150), "id_comprobante_tipo": _entero("id_comprobante_tipo")}
                    errores = _validar_clasif(cur, rid, form["descripcion"], form["id_comprobante_tipo"])
                    if not errores:
                        if rid:
                            cur.execute("UPDATE c_talonario_clasificacion SET descripcion = %s, id_comprobante_tipo = %s WHERE id = %s",
                                        (form["descripcion"], form["id_comprobante_tipo"], rid))
                        else:
                            cur.execute("INSERT INTO c_talonario_clasificacion (descripcion, id_comprobante_tipo) VALUES (%s, %s)",
                                        (form["descripcion"], form["id_comprobante_tipo"]))
                        flash(f"Clasificación «{form['descripcion']}» guardada.")
                        return _volver("clasificaciones")

                # ── Tipos de comprobante ──
                if accion == "borrar_tipo" and rid:
                    cur.execute("SELECT nombre FROM c_contable_comprobante_tipo WHERE id = %s", (rid,))
                    tp = cur.fetchone()
                    cur.execute("SELECT COUNT(*) AS n FROM c_talonario_clasificacion WHERE id_comprobante_tipo = %s", (rid,))
                    n = cur.fetchone()["n"]
                    if not tp:
                        flash("!El tipo ya no existe.")
                    elif n:
                        flash(f"!«{tp['nombre']}» tiene {n} clasificación(es): no se elimina.")
                    else:
                        cur.execute("DELETE FROM c_contable_comprobante_tipo WHERE id = %s", (rid,))
                        flash(f"Tipo «{tp['nombre']}» eliminado.")
                    return _volver("tipos")
                if accion == "guardar_tipo":
                    solapa = "tipos"
                    form = {"id": rid, "nombre": _texto("nombre", 50), "debito_credito": request.form.get("debito_credito") or "",
                            "propio": 1 if request.form.get("propio") else 0}
                    errores = _validar_tipo(cur, rid, form["nombre"], form["debito_credito"])
                    if not errores:
                        if rid:
                            cur.execute("UPDATE c_contable_comprobante_tipo SET nombre = %s, debito_credito = %s, propio = %s WHERE id = %s",
                                        (form["nombre"], form["debito_credito"], form["propio"], rid))
                        else:
                            cur.execute("INSERT INTO c_contable_comprobante_tipo (nombre, debito_credito, propio) VALUES (%s, %s, %s)",
                                        (form["nombre"], form["debito_credito"], form["propio"]))
                        flash(f"Tipo «{form['nombre']}» guardado.")
                        return _volver("tipos")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT t.*, cl.descripcion AS clasificacion, ct.nombre AS tipo, ct.debito_credito,
                       (t.numero_hasta - t.numero_desde + 1) AS capacidad,
                       GREATEST(LEAST(t.ultimo_emitido, t.numero_hasta) - t.numero_desde + 1, 0) AS usados,
                       (SELECT COUNT(*) FROM c_comprobantes_emitidos ce WHERE ce.id_talonario = t.id) AS emitidos
                  FROM c_talonario t
                  JOIN c_talonario_clasificacion cl ON cl.id = t.c_talonario_clasificacionId
                  JOIN c_contable_comprobante_tipo ct ON ct.id = cl.id_comprobante_tipo
                 ORDER BY t.habilitado DESC, cl.descripcion, t.punto_de_venta, t.numero_desde""")
            talonarios = cur.fetchall()
            cur.execute("""
                SELECT cl.*, ct.nombre AS tipo, ct.debito_credito,
                       (SELECT COUNT(*) FROM c_talonario t WHERE t.c_talonario_clasificacionId = cl.id) AS talonarios
                  FROM c_talonario_clasificacion cl JOIN c_contable_comprobante_tipo ct ON ct.id = cl.id_comprobante_tipo
                 ORDER BY ct.nombre, cl.descripcion""")
            clasificaciones = cur.fetchall()
            cur.execute("""
                SELECT ct.*, (SELECT COUNT(*) FROM c_talonario_clasificacion cl WHERE cl.id_comprobante_tipo = ct.id) AS clasificaciones
                  FROM c_contable_comprobante_tipo ct ORDER BY ct.nombre""")
            tipos = cur.fetchall()

            if form is None:
                if request.args.get("edit", type=int):
                    solapa = "talonarios"
                    form = next((dict(t) for t in talonarios if t["id"] == request.args.get("edit", type=int)), None)
                elif request.args.get("edit_clasif", type=int):
                    solapa = "clasificaciones"
                    form = next((dict(c) for c in clasificaciones if c["id"] == request.args.get("edit_clasif", type=int)), None)
                elif request.args.get("edit_tipo", type=int):
                    solapa = "tipos"
                    form = next((dict(t) for t in tipos if t["id"] == request.args.get("edit_tipo", type=int)), None)
                elif request.args.get("nuevo"):
                    form = {"habilitado": 1, "propio": 1, "numero_desde": 1, "numero_hasta": 99999999, "letra": "X",
                            "punto_de_venta": 1}
            if form and form.get("id") and solapa == "talonarios":
                cur.execute("SELECT * FROM c_talonario WHERE id = %s", (form["id"],))
                actual = cur.fetchone()
                form["usado"] = bool(actual and _usado(cur, actual))

    for t in talonarios:
        cap = int(t["capacidad"] or 0)
        t["usados"] = int(t["usados"] or 0)
        t["restantes"] = max(cap - t["usados"], 0)
        t["pct_uso"] = round(t["usados"] * 100 / cap, 1) if cap else 0
        t["proximo"] = max(t["ultimo_emitido"] + 1, t["numero_desde"])
        t["agotado"] = t["restantes"] == 0
        t["por_agotar"] = not t["agotado"] and t["pct_uso"] >= 90
        t["usado"] = t["usados"] > 0 or t["emitidos"] > 0
    return render_template("admin/talonarios.html", talonarios=talonarios, clasificaciones=clasificaciones, tipos=tipos,
                           form=form, errores=errores, solapa=solapa, letras=LETRAS, lados=LADOS)


def _validar_talonario(cur, f) -> list[str]:
    errores = []
    if not f["nombre"]:
        errores.append("El nombre es obligatorio.")
    if f["letra"] not in LETRAS:
        errores.append(f"La letra es una de {', '.join(LETRAS)}.")
    cur.execute("""SELECT cl.id, cl.id_comprobante_tipo FROM c_talonario_clasificacion cl WHERE cl.id = %s""",
                (f["c_talonario_clasificacionId"] or 0,))
    clasif = cur.fetchone()
    if not clasif:
        errores.append("Elegí la clasificación (o creala con «Nueva»).")
    if not f["punto_de_venta"] or not 1 <= f["punto_de_venta"] <= 99998:
        errores.append("El punto de venta va de 1 a 99998.")
    if not f["numero_desde"]:
        errores.append("El número desde tiene que ser mayor que cero.")
    if not f["numero_hasta"] or (f["numero_desde"] and f["numero_hasta"] < f["numero_desde"]):
        errores.append("El número hasta no puede ser menor que el desde.")
    if errores:
        return errores
    if f["ultimo_emitido"] is None:
        f["ultimo_emitido"] = f["numero_desde"] - 1
    if not f["numero_desde"] - 1 <= f["ultimo_emitido"] <= f["numero_hasta"]:
        errores.append(f"El último emitido va de {f['numero_desde'] - 1} (ninguno) a {f['numero_hasta']}.")

    if f["id"]:
        cur.execute("SELECT * FROM c_talonario WHERE id = %s", (f["id"],))
        antes = cur.fetchone()
        if not antes:
            return ["El talonario ya no existe."]
        if f["ultimo_emitido"] < max(antes["ultimo_emitido"] or 0, antes["numero_desde"] - 1):
            errores.append(f"El último emitido no retrocede: va por {antes['ultimo_emitido']}.")
        if _usado(cur, antes):
            for campo, nombre in (("punto_de_venta", "el punto de venta"), ("letra", "la letra"),
                                  ("numero_desde", "el número desde"), ("c_talonario_clasificacionId", "la clasificación")):
                if str(antes[campo]) != str(f[campo]):
                    errores.append(f"El talonario ya emitió comprobantes: no se le cambia {nombre}.")
            cur.execute("SELECT MAX(numero_desde) AS m FROM c_comprobantes_emitidos WHERE id_talonario = %s", (f["id"],))
            mayor = max(cur.fetchone()["m"] or 0, antes["ultimo_emitido"] or 0)
            if f["numero_hasta"] < mayor:
                errores.append(f"El número hasta no puede quedar por debajo de lo emitido ({mayor}).")
    # Mismo tipo de comprobante, punto de venta y letra: los rangos no se pisan.
    cur.execute("""SELECT t.nombre, t.numero_desde, t.numero_hasta, cl.descripcion
                     FROM c_talonario t JOIN c_talonario_clasificacion cl ON cl.id = t.c_talonario_clasificacionId
                    WHERE cl.id_comprobante_tipo = %s AND t.punto_de_venta = %s AND t.letra = %s AND t.id <> %s
                      AND t.numero_desde <= %s AND t.numero_hasta >= %s LIMIT 1""",
                (clasif["id_comprobante_tipo"], f["punto_de_venta"], f["letra"], f["id"] or 0,
                 f["numero_hasta"], f["numero_desde"]))
    choque = cur.fetchone()
    if choque:
        errores.append(f"El rango se superpone con «{choque['nombre']}» ({choque['numero_desde']}–{choque['numero_hasta']}, "
                       f"{choque['descripcion']}): mismo tipo de comprobante, punto de venta y letra, emitirían el mismo número.")
    return errores


# =============================================================================
# Formularios satélite (JSON): crear sin salir del formulario
# =============================================================================

@talonarios_bp.route("/api/tipo", methods=["POST"])
def api_tipo():
    if not _permiso():
        return jsonify(error="No tenés permiso."), 403
    nombre = " ".join((request.form.get("nombre") or "").split())[:50]
    lado = request.form.get("debito_credito") or ""
    with get_connection() as conn:
        with conn.cursor() as cur:
            errores = _validar_tipo(cur, None, nombre, lado)
            if errores:
                return jsonify(error=" ".join(errores)), 400
            cur.execute("INSERT INTO c_contable_comprobante_tipo (nombre, debito_credito, propio) VALUES (%s, %s, %s)",
                        (nombre, lado, 1 if request.form.get("propio") else 0))
            nuevo = cur.lastrowid
    return jsonify(id=nuevo, nombre=nombre, debito_credito=lado)


@talonarios_bp.route("/api/clasificacion", methods=["POST"])
def api_clasificacion():
    if not _permiso():
        return jsonify(error="No tenés permiso."), 403
    descripcion = " ".join((request.form.get("descripcion") or "").split())[:150]
    v = (request.form.get("id_comprobante_tipo") or "").strip()
    id_tipo = int(v) if v.isdigit() else None
    with get_connection() as conn:
        with conn.cursor() as cur:
            errores = _validar_clasif(cur, None, descripcion, id_tipo)
            if errores:
                return jsonify(error=" ".join(errores)), 400
            cur.execute("INSERT INTO c_talonario_clasificacion (descripcion, id_comprobante_tipo) VALUES (%s, %s)",
                        (descripcion, id_tipo))
            nuevo = cur.lastrowid
            cur.execute("SELECT nombre, debito_credito FROM c_contable_comprobante_tipo WHERE id = %s", (id_tipo,))
            tp = cur.fetchone()
    return jsonify(id=nuevo, descripcion=descripcion, tipo=tp["nombre"], debito_credito=tp["debito_credito"])
