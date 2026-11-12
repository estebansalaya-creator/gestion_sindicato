"""
tesoreria.py — Tablas de tesorería: cuentas de fondos (con sus chequeras),
códigos de banco del BCRA, conceptos de gasto y motivos de ingreso.

Portado de `gestion_adm/tesoreria_routes.py` (abm_bancos, abm_cuentas_fondos,
abm_chequeras, abm_concepto_gastos, abm_motivos_ingreso) con el sistema de
estilos de este proyecto. Lo que cambia:

- Cada pantalla es una opción de menú y el permiso se controla en el servidor
  (`db.puede`), también en los POST.
- Un concepto o un motivo que se usa no se borra: se desactiva. En gestion_adm
  el DELETE rebotaba por FK o, donde no hay FK (el detalle de las
  liquidaciones), dejaba renglones apuntando a un concepto que ya no existe.
- Una cuenta de fondos con movimientos o chequeras no se borra: se deshabilita.
- La cuenta contable se elige del plan: solo imputables y activas, agrupadas
  por clase. Una imputación que no está en el plan (las que vinieron de la obra
  social) se muestra como tal y no deja guardar hasta elegir una válida.
- El banco de una cuenta sale del CBU (sus tres primeros dígitos): si se elige
  otro, no se guarda.
- Sin el formato de transferencias masivas: acá todavía no hay generador de
  archivos. La columna queda sin tocar.

Datos iniciales: importar_aeda_tesoreria.py (plan de cuentas, conceptos,
motivos, cuentas y chequeras de AEDA) y sql/tesoreria_20261108.sql (bancos).
"""

from __future__ import annotations

import re

import pymysql
from flask import Blueprint, flash, redirect, render_template, request, url_for

from afiliados import cbu_valido
import transferencias_formatos as tf
from db import get_connection, puede, validasesion

tesoreria_bp = Blueprint("tesoreria", __name__, url_prefix="/tesoreria")

TIPOS_CUENTA = [("B", "Banco"), ("C", "Caja"), ("R", "Cartera"), ("I", "Inversiones"),
                ("T", "Tarjeta"), ("O", "Otra")]
TIPOS_CUENTA_TXT = dict(TIPOS_CUENTA)
#: Los tipos que tienen banco, número de cuenta y CBU. En un banco son
#: obligatorios; en inversiones (un plazo fijo), opcionales.
CON_BANCO = ("B", "I")
#: Clase de un concepto de reintegro (sql/reintegros_clase_20261111.sql).
CLASES_REINTEGRO = {"subsidio": "Subsidio", "reintegro": "Reintegro"}

#: Dónde se usa cada tabla. Lo que se usa no se borra.
USOS_CONCEPTO = [("c_proveedores_cuentas_gasto", "id_concepto_gasto"),
                 ("c_reintegro_afiliados_detalle", "id_concepto_gasto"),
                 ("c_pasivo_liquidacion_detalle", "id_concepto_liquidacion"),
                 ("pago_ordenes_concepto_det", "id_concepto_gasto"),
                 ("conc_reglas", "id_concepto_gasto")]
USOS_MOTIVO = [("ingreso_ordenes_detalle", "id_motivo_ingreso"),
               ("pago_ordenes_concepto_det", "id_motivo_ingreso"),
               ("conc_reglas", "id_motivo_ingreso")]
USOS_CUENTA = [("c_movimientos_de_fondos", "c_cuentas_de_fondosId"),
               ("pago_pagos_instrumentos", "id_cuenta_fondos"),
               ("ingreso_ordenes", "id_cuenta"),
               ("ingreso_ordenes_cuentas", "id_cuenta_fondos"),
               ("c_movimiento_entre_cuentas_det", "id_cuenta_fondos"),
               ("c_extractos_bancarios", "c_cuentas_de_fondos_id"),
               ("conciliacion_header", "id_cuenta"),
               ("conc_reglas", "id_cuenta_destino"),
               ("c_inversiones", "c_cuentas_de_fondosId"),
               ("c_valores_de_terceros", "id_cuenta_fondos"),
               ("c_comprobantes_emitidos_cobranza", "id_cuenta_fondos")]

#: Los dos catálogos simples: misma pantalla, mismas reglas.
CATALOGOS = {
    "conceptos": {"tabla": "c_concepto_de_gastos", "endpoint": "tesoreria.conceptos_gasto",
                  "titulo": "Conceptos de gasto", "singular": "concepto de gasto", "articulo": "el",
                  "largo": 50, "usos": USOS_CONCEPTO,
                  "ayuda": "A qué cuenta del plan va cada gasto: la liquidación de un comprobante, un "
                           "reintegro, una orden de pago por concepto."},
    "motivos": {"tabla": "c_motivos_de_ingreso", "endpoint": "tesoreria.motivos_ingreso",
                "titulo": "Motivos de ingreso", "singular": "motivo de ingreso", "articulo": "el",
                "largo": 100, "usos": USOS_MOTIVO,
                "ayuda": "A qué cuenta del plan va cada ingreso: cuota sindical, fiscalización, "
                         "alquileres, intereses."},
}


def usos(cur, lista) -> dict:
    """id → en cuántas filas se usa, sumando las tablas de la lista."""
    n: dict = {}
    for tabla, col in lista:
        cur.execute(f"SELECT {col} AS id, COUNT(*) AS n FROM {tabla} WHERE {col} IS NOT NULL GROUP BY {col}")
        for f in cur.fetchall():
            n[f["id"]] = n.get(f["id"], 0) + f["n"]
    return n


def conceptos_activos(cur, solo_reintegro=False) -> list[dict]:
    """Los conceptos de gasto que se ofrecen al cargar. Sin la columna `activo`
    (falta sql/tesoreria_20261108.sql) se ofrecen todos, como antes."""
    filtro = " AND es_reintegro = 1" if solo_reintegro else ""
    try:
        cur.execute(f"SELECT id, descripcion FROM c_concepto_de_gastos WHERE activo = 1{filtro} "
                    "ORDER BY descripcion")
    except pymysql.err.OperationalError:
        cur.execute(f"SELECT id, descripcion FROM c_concepto_de_gastos WHERE 1 = 1{filtro} ORDER BY descripcion")
    return cur.fetchall()


def cuentas_imputables(cur, clases=None) -> list[dict]:
    """Las cuentas del plan que aceptan movimientos, con la clase para agrupar."""
    sql = """SELECT p.id_cuenta AS id, p.codigo, p.nombre,
                    CONCAT(p.codigo, '  ', p.nombre) AS texto,
                    CONCAT(COALESCE(cl.codigo, ''), ' · ', COALESCE(cl.clasificacion, 'Sin clasificar')) AS grupo
               FROM c_plan_de_cuentas p
               LEFT JOIN c_clasificacion_plan_cuentas cl ON cl.codigo = p.id_clasificacion
              WHERE p.permite_movimiento = 1 AND p.activa = 1"""
    params = []
    if clases:
        sql += f" AND p.id_clasificacion IN ({', '.join(['%s'] * len(clases))})"
        params = list(clases)
    cur.execute(sql + " ORDER BY p.codigo", params)
    return cur.fetchall()


def _cuenta_valida(cur, id_cuenta, clases=None) -> str | None:
    """El error si la cuenta contable no sirve para imputar; None si sirve."""
    if not id_cuenta:
        return "La cuenta contable es obligatoria."
    cur.execute("SELECT codigo, nombre, permite_movimiento, activa, id_clasificacion "
                "FROM c_plan_de_cuentas WHERE id_cuenta = %s", (id_cuenta,))
    c = cur.fetchone()
    if not c:
        return "La cuenta contable no está en el plan de cuentas: elegí una de la lista."
    if not c["permite_movimiento"] or not c["activa"]:
        return f"La cuenta {c['codigo']} {c['nombre']} es un título o está inactiva: no acepta imputaciones."
    if clases and c["id_clasificacion"] not in clases:
        return f"La cuenta {c['codigo']} {c['nombre']} no es de activo: una cuenta de fondos se imputa al activo."
    return None


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


def _id(nombre):
    v = (request.form.get(nombre) or "").strip()
    return int(v) if v.isdigit() else None


def _digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


# ─────────────────────────────────────────────────────────────────────────────
# Códigos de banco del BCRA
# ─────────────────────────────────────────────────────────────────────────────

@tesoreria_bp.route("/bancos", methods=["GET", "POST"])
def bancos():
    salida = _guardia("tesoreria.bancos")
    if salida:
        return salida
    errores, banco = [], None

    if request.method == "POST":
        accion, bid = request.form.get("accion", ""), _id("id")
        with get_connection() as conn:
            with conn.cursor() as cur:
                if accion == "borrar" and bid:
                    cur.execute("SELECT COUNT(*) AS n FROM c_cuentas_de_fondos WHERE c_codigo_de_bancoId = %s", (bid,))
                    n = cur.fetchone()["n"]
                    if n:
                        flash(f"!No se puede eliminar: lo usan {n} cuentas de fondos.")
                    else:
                        cur.execute("DELETE FROM c_codigo_de_banco WHERE id = %s", (bid,))
                        flash("Banco eliminado.")
                    return redirect(url_for("tesoreria.bancos"))

                codigo = _digitos(request.form.get("codigo"))
                nombre = _texto("nombre", 100).upper()
                if not codigo:
                    errores.append("El código del BCRA es obligatorio: los tres dígitos con que empieza el CBU.")
                elif len(codigo) > 5:
                    errores.append("El código del BCRA tiene hasta cinco dígitos.")
                codigo = codigo.zfill(3)
                if not nombre:
                    errores.append("El nombre es obligatorio.")
                if not errores:
                    cur.execute("SELECT id, nombre FROM c_codigo_de_banco WHERE codigo = %s AND id <> %s",
                                (codigo, bid or 0))
                    otro = cur.fetchone()
                    if otro:
                        errores.append(f"El código {codigo} ya es de {otro['nombre']}.")
                if not errores:
                    if bid:
                        cur.execute("UPDATE c_codigo_de_banco SET codigo = %s, nombre = %s WHERE id = %s",
                                    (codigo, nombre, bid))
                        flash(f"Banco {codigo} actualizado.")
                    else:
                        cur.execute("INSERT INTO c_codigo_de_banco (codigo, nombre) VALUES (%s, %s)",
                                    (codigo, nombre))
                        flash(f"Banco {codigo} agregado.")
                    return redirect(url_for("tesoreria.bancos"))
                banco = {"id": bid, "codigo": codigo, "nombre": nombre}

    with get_connection() as conn:
        with conn.cursor() as cur:
            edit_id = request.args.get("edit", type=int)
            if edit_id and banco is None:
                cur.execute("SELECT * FROM c_codigo_de_banco WHERE id = %s", (edit_id,))
                banco = cur.fetchone()
                if not banco:
                    flash("!El banco no existe.")
                    return redirect(url_for("tesoreria.bancos"))
            cur.execute("""SELECT b.id, b.codigo, b.nombre,
                                  (SELECT COUNT(*) FROM c_cuentas_de_fondos c WHERE c.c_codigo_de_bancoId = b.id) AS cuentas
                             FROM c_codigo_de_banco b ORDER BY b.codigo""")
            lista = cur.fetchall()
    nuevo = bool(request.args.get("nuevo"))
    return render_template("tesoreria/bancos.html", bancos=lista, banco=banco, errores=errores,
                           abrir_ficha=bool(banco or errores or nuevo))


# ─────────────────────────────────────────────────────────────────────────────
# Conceptos de gasto y motivos de ingreso
# ─────────────────────────────────────────────────────────────────────────────

def _catalogo(clave):
    cat = CATALOGOS[clave]
    salida = _guardia(cat["endpoint"])
    if salida:
        return salida
    tabla, errores, registro = cat["tabla"], [], None
    es_concepto = clave == "conceptos"
    hay_clase = False
    if es_concepto:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT COUNT(*) AS n FROM information_schema.columns
                                WHERE table_schema = DATABASE() AND table_name = 'c_concepto_de_gastos'
                                  AND column_name = 'clase_reintegro'""")
                hay_clase = bool(cur.fetchone()["n"])

    if request.method == "POST":
        accion, rid = request.form.get("accion", ""), _id("id")
        with get_connection() as conn:
            with conn.cursor() as cur:
                if accion in ("borrar", "baja", "reactivar") and rid:
                    cur.execute(f"SELECT descripcion FROM {tabla} WHERE id = %s", (rid,))
                    f = cur.fetchone()
                    if not f:
                        flash("!Ya no existe.")
                    elif accion == "borrar":
                        n = usos(cur, cat["usos"]).get(rid, 0)
                        if n:
                            flash(f"!«{f['descripcion']}» se usa en {n} renglones: no se puede eliminar. "
                                  "Desactivalo para que no se ofrezca más.")
                        else:
                            cur.execute(f"DELETE FROM {tabla} WHERE id = %s", (rid,))
                            flash(f"«{f['descripcion']}» eliminado.")
                    else:
                        cur.execute(f"UPDATE {tabla} SET activo = %s WHERE id = %s",
                                    (1 if accion == "reactivar" else 0, rid))
                        flash(f"«{f['descripcion']}» " + ("reactivado." if accion == "reactivar"
                                                           else "desactivado: ya no se ofrece."))
                    return redirect(url_for(cat["endpoint"]))

                registro = {
                    "id": rid, "descripcion": _texto("descripcion", cat["largo"]).upper(),
                    "c_plan_de_cuentasId": _id("c_plan_de_cuentasId"), "c_especiesId": _id("c_especiesId"),
                    "activo": 1 if request.form.get("activo") else 0,
                }
                if es_concepto:
                    registro.update(arca_tasa_ivaid=_id("arca_tasa_ivaid"),
                                    es_reintegro=1 if request.form.get("es_reintegro") else 0)
                    # Subsidio o reintegro de un gasto: solo para los que se
                    # ofrecen en los reintegros (sql/reintegros_clase_20261111.sql).
                    if hay_clase:
                        clase = request.form.get("clase_reintegro") or None
                        registro["clase_reintegro"] = (clase if clase in CLASES_REINTEGRO and registro["es_reintegro"]
                                                       else None)
                if not registro["descripcion"]:
                    errores.append("La descripción es obligatoria.")
                else:
                    cur.execute(f"SELECT id FROM {tabla} WHERE descripcion = %s AND id <> %s",
                                (registro["descripcion"], rid or 0))
                    if cur.fetchone():
                        errores.append(f"Ya hay un {cat['singular']} «{registro['descripcion']}».")
                e = _cuenta_valida(cur, registro["c_plan_de_cuentasId"])
                if e:
                    errores.append(e)
                if es_concepto and not registro["c_especiesId"]:
                    errores.append("La moneda es obligatoria.")
                if es_concepto and not registro["arca_tasa_ivaid"]:
                    errores.append("La alícuota de IVA es obligatoria.")
                if not errores:
                    cols = [k for k in registro if k != "id"]
                    if rid:
                        cur.execute(f"UPDATE {tabla} SET {', '.join(c + ' = %s' for c in cols)} WHERE id = %s",
                                    [registro[c] for c in cols] + [rid])
                        flash(f"«{registro['descripcion']}» actualizado.")
                    else:
                        if es_concepto:
                            cols.append("esliquidacion")
                            registro["esliquidacion"] = 0
                        cur.execute(f"INSERT INTO {tabla} ({', '.join(cols)}) "
                                    f"VALUES ({', '.join(['%s'] * len(cols))})", [registro[c] for c in cols])
                        flash(f"«{registro['descripcion']}» agregado.")
                    return redirect(url_for(cat["endpoint"]))

    with get_connection() as conn:
        with conn.cursor() as cur:
            edit_id = request.args.get("edit", type=int)
            if edit_id and registro is None:
                cur.execute(f"SELECT * FROM {tabla} WHERE id = %s", (edit_id,))
                registro = cur.fetchone()
                if not registro:
                    flash("!Ya no existe.")
                    return redirect(url_for(cat["endpoint"]))
            extra = (", t.descripcion AS tasa, x.es_reintegro"
                     + (", x.clase_reintegro" if hay_clase else "")) if es_concepto else ""
            join = "LEFT JOIN arca_tasa_iva t ON t.id = x.arca_tasa_ivaid" if es_concepto else ""
            cur.execute(f"""SELECT x.id, x.descripcion, x.activo, x.c_plan_de_cuentasId,
                                   p.codigo AS cuenta_codigo, p.nombre AS cuenta_nombre,
                                   p.permite_movimiento AS cuenta_imputable,
                                   e.simbolo AS moneda {extra}
                              FROM {tabla} x
                              LEFT JOIN c_plan_de_cuentas p ON p.id_cuenta = x.c_plan_de_cuentasId
                              LEFT JOIN c_especies e ON e.id = x.c_especiesId
                              {join}
                             ORDER BY x.descripcion""")
            filas = cur.fetchall()
            n = usos(cur, cat["usos"])
            for f in filas:
                f["usos"] = n.get(f["id"], 0)
            plan = cuentas_imputables(cur)
            cur.execute("SELECT id, CONCAT(simbolo, ' ', nombre) AS nombre FROM c_especies ORDER BY id")
            especies = cur.fetchall()
            tasas = []
            if es_concepto:
                cur.execute("SELECT id, descripcion FROM arca_tasa_iva ORDER BY alicuota, id")
                tasas = cur.fetchall()
    nuevo = bool(request.args.get("nuevo"))
    if registro is None and nuevo:
        registro = {"activo": 1, "c_especiesId": especies[0]["id"] if especies else None,
                    "arca_tasa_ivaid": next((t["id"] for t in tasas if t["descripcion"] == "No Gravado"), None)}
    return render_template("tesoreria/catalogo.html", cat=cat, clave=clave, filas=filas, registro=registro,
                           errores=errores, plan=plan, especies=especies, tasas=tasas,
                           hay_clase=hay_clase, clases_reintegro=CLASES_REINTEGRO,
                           abrir_ficha=bool(registro or errores))


@tesoreria_bp.route("/conceptos_gasto", methods=["GET", "POST"])
def conceptos_gasto():
    return _catalogo("conceptos")


@tesoreria_bp.route("/motivos_ingreso", methods=["GET", "POST"])
def motivos_ingreso():
    return _catalogo("motivos")


# ─────────────────────────────────────────────────────────────────────────────
# Cuentas de fondos
# ─────────────────────────────────────────────────────────────────────────────

def _leer_cuenta(cur, cid) -> tuple[dict, list[str]]:
    errores = []
    c = {
        "id": cid, "tipo_de_cuenta": (request.form.get("tipo_de_cuenta") or "").strip().upper(),
        "nombre": _texto("nombre", 100), "c_codigo_de_bancoId": _id("c_codigo_de_bancoId"),
        "numero_de_cuenta": _texto("numero_de_cuenta", 20) or None,
        "cbu": _digitos(request.form.get("cbu")) or None, "alias": _texto("alias", 100) or None,
        "c_especiesId": _id("c_especiesId"), "c_plan_de_cuentasId": _id("c_plan_de_cuentasId"),
        "habilitada": 1 if request.form.get("habilitada") else 0,
        "esdepago": 1 if request.form.get("esdepago") else 0,
        "comentario": _texto("comentario", 250) or None,
        "formato_transferencia": _texto("formato_transferencia", 30) or None,
    }
    # La predeterminada es una de las de pago: es la que viene elegida al cargar
    # un instrumento, y ese desplegable solo muestra las de pago.
    c["predeterminada"] = 1 if c["esdepago"] and c["habilitada"] and request.form.get("predeterminada") else 0
    if c["tipo_de_cuenta"] not in TIPOS_CUENTA_TXT:
        errores.append("El tipo de cuenta es obligatorio.")
    if not c["nombre"]:
        errores.append("El nombre es obligatorio.")
    if c["tipo_de_cuenta"] in CON_BANCO:
        if c["cbu"] and not cbu_valido(c["cbu"]):
            errores.append("El CBU no verifica: son 22 dígitos y los dos verificadores tienen que cerrar.")
        elif c["cbu"]:
            cur.execute("SELECT id, codigo, nombre FROM c_codigo_de_banco WHERE codigo = %s", (c["cbu"][:3],))
            del_cbu = cur.fetchone()
            if not del_cbu:
                errores.append(f"El CBU es del banco {c['cbu'][:3]}, que no está en la tabla de bancos.")
            elif c["c_codigo_de_bancoId"] and c["c_codigo_de_bancoId"] != del_cbu["id"]:
                errores.append(f"El CBU es de {del_cbu['nombre']} ({del_cbu['codigo']}), no del banco elegido.")
            else:
                c["c_codigo_de_bancoId"] = del_cbu["id"]
        if c["formato_transferencia"]:
            fmt = tf.FORMATOS.get(c["formato_transferencia"])
            banco = c["cbu"][:3] if c["cbu"] else None
            if not banco and c["c_codigo_de_bancoId"]:
                cur.execute("SELECT codigo FROM c_codigo_de_banco WHERE id = %s", (c["c_codigo_de_bancoId"],))
                banco = ((cur.fetchone() or {}).get("codigo") or "").zfill(3) or None
            if not fmt:
                errores.append("El formato de transferencias no existe.")
            elif banco and fmt["banco"] != banco:
                errores.append(f"El formato {fmt['nombre']} es de otro banco: el archivo rebotaría.")
        if c["tipo_de_cuenta"] == "B":
            if not c["numero_de_cuenta"]:
                errores.append("El número de cuenta es obligatorio en un banco.")
            if not c["cbu"]:
                errores.append("El CBU es obligatorio en un banco.")
    else:
        c.update(c_codigo_de_bancoId=None, numero_de_cuenta=None, cbu=None)
    if c["tipo_de_cuenta"] != "B":
        c["formato_transferencia"] = None
    if not c["c_especiesId"]:
        errores.append("La moneda es obligatoria.")
    e = _cuenta_valida(cur, c["c_plan_de_cuentasId"], clases=(1,))
    if e:
        errores.append(e)
    return c, errores


COLS_CUENTA = ("tipo_de_cuenta", "nombre", "c_codigo_de_bancoId", "numero_de_cuenta", "cbu", "alias",
               "c_especiesId", "c_plan_de_cuentasId", "habilitada", "esdepago", "predeterminada", "comentario",
               "formato_transferencia")


@tesoreria_bp.route("/cuentas_fondos", methods=["GET", "POST"])
def cuentas_fondos():
    salida = _guardia("tesoreria.cuentas_fondos")
    if salida:
        return salida
    errores, cuenta = [], None

    if request.method == "POST":
        accion, cid = request.form.get("accion", ""), _id("id")
        with get_connection() as conn:
            if accion in ("borrar", "baja", "reactivar") and cid:
                with conn.cursor() as cur:
                    cur.execute("SELECT nombre FROM c_cuentas_de_fondos WHERE id = %s", (cid,))
                    f = cur.fetchone()
                    if not f:
                        flash("!La cuenta ya no existe.")
                    elif accion == "borrar":
                        n = usos(cur, USOS_CUENTA).get(cid, 0)
                        cur.execute("SELECT COUNT(*) AS n FROM c_chequeras WHERE c_cuentas_de_fondosId = %s", (cid,))
                        q = cur.fetchone()["n"]
                        if n or q:
                            flash(f"!«{f['nombre']}» tiene " + (f"{n} movimientos" if n else f"{q} chequeras")
                                  + ": no se puede eliminar. Deshabilitala.")
                        else:
                            cur.execute("DELETE FROM c_cuentas_de_fondos WHERE id = %s", (cid,))
                            flash(f"«{f['nombre']}» eliminada.")
                    else:
                        cur.execute("UPDATE c_cuentas_de_fondos SET habilitada = %s"
                                    + (", predeterminada = 0" if accion == "baja" else "") + " WHERE id = %s",
                                    (1 if accion == "reactivar" else 0, cid))
                        flash(f"«{f['nombre']}» " + ("habilitada." if accion == "reactivar" else "deshabilitada."))
                return redirect(url_for("tesoreria.cuentas_fondos"))

            with conn.cursor() as cur:
                cuenta, errores = _leer_cuenta(cur, cid)
            if not errores:
                conn.begin()
                try:
                    with conn.cursor() as cur:
                        # Apagar la anterior ANTES de escribir la nueva: el índice
                        # único rebota dos encendidas aunque sea dentro de la
                        # transacción.
                        if cuenta["predeterminada"]:
                            cur.execute("UPDATE c_cuentas_de_fondos SET predeterminada = 0 "
                                        "WHERE predeterminada = 1 AND id <> %s", (cid or 0,))
                        if cid:
                            cur.execute(f"UPDATE c_cuentas_de_fondos SET {', '.join(c + ' = %s' for c in COLS_CUENTA)} "
                                        "WHERE id = %s", [cuenta[c] for c in COLS_CUENTA] + [cid])
                        else:
                            cur.execute(f"INSERT INTO c_cuentas_de_fondos ({', '.join(COLS_CUENTA)}) "
                                        f"VALUES ({', '.join(['%s'] * len(COLS_CUENTA))})",
                                        [cuenta[c] for c in COLS_CUENTA])
                            cid = cur.lastrowid
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                flash(f"«{cuenta['nombre']}» guardada." + (" Es la que viene elegida al cargar un instrumento "
                                                           "de pago." if cuenta["predeterminada"] else ""))
                return redirect(url_for("tesoreria.cuentas_fondos", edit=cid))

    with get_connection() as conn:
        with conn.cursor() as cur:
            edit_id = request.args.get("edit", type=int)
            if edit_id and cuenta is None:
                cur.execute("SELECT * FROM c_cuentas_de_fondos WHERE id = %s", (edit_id,))
                cuenta = cur.fetchone()
                if not cuenta:
                    flash("!La cuenta ya no existe.")
                    return redirect(url_for("tesoreria.cuentas_fondos"))
            cur.execute("""SELECT c.*, b.codigo AS banco_codigo, b.nombre AS banco_nombre, e.simbolo AS moneda,
                                  p.codigo AS cuenta_codigo, p.nombre AS cuenta_nombre,
                                  (SELECT COUNT(*) FROM c_chequeras q WHERE q.c_cuentas_de_fondosId = c.id) AS chequeras
                             FROM c_cuentas_de_fondos c
                             LEFT JOIN c_codigo_de_banco b ON b.id = c.c_codigo_de_bancoId
                             LEFT JOIN c_especies e ON e.id = c.c_especiesId
                             LEFT JOIN c_plan_de_cuentas p ON p.id_cuenta = c.c_plan_de_cuentasId
                            ORDER BY c.habilitada DESC, c.tipo_de_cuenta, c.nombre""")
            cuentas = cur.fetchall()
            n = usos(cur, USOS_CUENTA)
            for c in cuentas:
                c["movimientos"] = n.get(c["id"], 0)
            cur.execute("SELECT id, codigo, nombre FROM c_codigo_de_banco ORDER BY codigo")
            lista_bancos = cur.fetchall()
            cur.execute("SELECT id, CONCAT(simbolo, ' ', nombre) AS nombre FROM c_especies ORDER BY id")
            especies = cur.fetchall()
            plan = cuentas_imputables(cur, clases=(1,))
            chequeras = []
            if cuenta and cuenta.get("id") and cuenta.get("tipo_de_cuenta") == "B":
                cur.execute("""SELECT q.*,
                                      (SELECT COUNT(*) FROM c_debitos_creditos_bancarios d
                                        WHERE d.c_chequerasId = q.id AND d.estado <> 'anulado') AS emitidos
                                 FROM c_chequeras q WHERE q.c_cuentas_de_fondosId = %s
                                ORDER BY q.numero_desde""", (cuenta["id"],))
                chequeras = cur.fetchall()
    nuevo = bool(request.args.get("nuevo"))
    if cuenta is None and nuevo:
        cuenta = {"habilitada": 1, "c_especiesId": especies[0]["id"] if especies else None}
    return render_template("tesoreria/cuentas_fondos.html", cuentas=cuentas, cuenta=cuenta, errores=errores,
                           bancos=lista_bancos, especies=especies, plan=plan, chequeras=chequeras,
                           tipos=TIPOS_CUENTA, tipos_txt=TIPOS_CUENTA_TXT, con_banco=CON_BANCO,
                           formatos=tf.FORMATOS,
                           abrir_ficha=bool(cuenta or errores))


@tesoreria_bp.route("/cuentas_fondos/<int:id_cuenta>/chequeras", methods=["POST"])
def chequeras(id_cuenta):
    """Las chequeras van dentro de la cuenta: una chequera no existe sin su
    cuenta, y al lado del CBU y del número es donde se controla."""
    salida = _guardia("tesoreria.cuentas_fondos")
    if salida:
        return salida
    volver = redirect(url_for("tesoreria.cuentas_fondos", edit=id_cuenta) + "#chequeras")
    accion = request.form.get("accion", "")
    qid = _id("id")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT tipo_de_cuenta FROM c_cuentas_de_fondos WHERE id = %s", (id_cuenta,))
            c = cur.fetchone()
            if not c or c["tipo_de_cuenta"] != "B":
                flash("!Solo las cuentas de banco tienen chequeras.")
                return volver
            if accion == "borrar" and qid:
                # Con cheques emitidos, borrarla los dejaría sin talonario.
                cur.execute("SELECT COUNT(*) AS n FROM c_debitos_creditos_bancarios WHERE c_chequerasId = %s", (qid,))
                if cur.fetchone()["n"]:
                    cur.execute("UPDATE c_chequeras SET habilitada = 0 WHERE id = %s AND c_cuentas_de_fondosId = %s",
                                (qid, id_cuenta))
                    flash("!La chequera tiene cheques emitidos: se deshabilitó en vez de eliminarse.")
                else:
                    cur.execute("DELETE FROM c_chequeras WHERE id = %s AND c_cuentas_de_fondosId = %s",
                                (qid, id_cuenta))
                    flash("Chequera eliminada.")
                return volver

            desde, hasta = _digitos(request.form.get("numero_desde")), _digitos(request.form.get("numero_hasta"))
            ultimo = _digitos(request.form.get("ultimo_utilizado"))
            if not desde or not hasta:
                flash("!Falta el rango de números de la chequera.")
                return volver
            desde, hasta = int(desde), int(hasta)
            if hasta < desde:
                flash("!El número final no puede ser menor que el inicial.")
                return volver
            # En pantalla se pide el último usado, que es como se lee un
            # talonario; se guarda el próximo, que es lo que necesita quien emite.
            ultimo = int(ultimo) if ultimo else desde - 1
            if ultimo < desde - 1 or ultimo > hasta:
                flash(f"!El último usado tiene que estar entre {desde} y {hasta} (o vacío si no se usó ninguno).")
                return volver
            cur.execute("""SELECT numero_desde, numero_hasta FROM c_chequeras
                            WHERE c_cuentas_de_fondosId = %s AND id <> %s
                              AND numero_desde <= %s AND numero_hasta >= %s LIMIT 1""",
                        (id_cuenta, qid or 0, hasta, desde))
            choque = cur.fetchone()
            if choque:
                flash(f"!El rango se superpone con la chequera {choque['numero_desde']}–{choque['numero_hasta']}.")
                return volver
            tipo = request.form.get("tipo_cheque") if request.form.get("tipo_cheque") in ("al_dia", "diferido") \
                else "al_dia"
            impresion = request.form.get("impresion") if request.form.get("impresion") in ("manual", "automatica") \
                else "manual"
            valores = (_texto("descripcion", 100) or None, tipo, impresion, desde, hasta, ultimo + 1,
                       1 if request.form.get("habilitada") else 0)
            if qid:
                cur.execute("""UPDATE c_chequeras SET descripcion = %s, tipo_cheque = %s, impresion = %s,
                                      numero_desde = %s, numero_hasta = %s, proximo_numero = %s, habilitada = %s
                                WHERE id = %s AND c_cuentas_de_fondosId = %s""", valores + (qid, id_cuenta))
                flash("Chequera actualizada.")
            else:
                cur.execute("""INSERT INTO c_chequeras (descripcion, tipo_cheque, impresion, numero_desde,
                                                        numero_hasta, proximo_numero, habilitada, c_cuentas_de_fondosId)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""", valores + (id_cuenta,))
                flash("Chequera agregada.")
    return volver
