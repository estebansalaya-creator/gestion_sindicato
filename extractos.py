"""
extractos.py — Tesorería › Extractos Bancarios (menú 71).

Portado de `gestion_adm/extractos_bancarios_routes.py` con el sistema de
estilos de acá:

    /tesoreria/extractos                 el extracto de una cuenta: ?cuenta, ?desde, ?hasta
    /tesoreria/extractos/importar        POST: uno o varios archivos (o una carpeta)
    /tesoreria/extractos/<id>/borrar     POST: un renglón que no entró en ninguna conciliación

Los parsers y el control de cuenta están en `extractos_bancarios.py`.

QUE CAMBIA RESPECTO DE GESTION_ADM
- Sin las solapas de Conciliación Prisma y de transferencias: Prisma es del
  débito automático de la obra social, y la conciliación se hace en su pantalla
  (conciliacion.py) contra el libro del sindicato.
- Importar es un diálogo de la misma pantalla, no una solapa: el extracto y lo
  que se acaba de importar se ven juntos.
- La grilla trae el período entero (tope `TOPE`) para filtrar, ordenar y
  exportar como todas; el Excel es el de la barra, no una ruta aparte.
- Cada renglón dice si ya está conciliado o en qué conciliación está, y uno
  que entró en una conciliación no se borra: se perdería el rastro de con qué
  se concilió (antes el DELETE fallaba contra la clave foránea, o borraba
  si no la había).
- El saldo que informa el banco (columna Saldo) se muestra: es el que la
  conciliación toma como saldo de cierre.
"""

from __future__ import annotations

import datetime
import logging
import os

from flask import Blueprint, flash, redirect, render_template, request, url_for

from db import get_connection, puede, validasesion
from extractos_bancarios import (CuentaEquivocada, _fecha_del_nombre, detectar_banco, get_cuentas,
                                 importar_extracto)

log = logging.getLogger(__name__)

extractos_bp = Blueprint("extractos", __name__, url_prefix="/tesoreria/extractos")

URL = "/tesoreria/extractos"

BANCOS = {"BNA": "Banco Nación", "ICBC": "ICBC"}

#: Renglones que trae la grilla como máximo. Un mes de la recaudadora son
#: unos cientos; con más, se avisa y se pide acotar las fechas.
TOPE = 5000


def _guardia():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede(URL):
        flash("!No tenés permiso para esa pantalla.")
        return redirect(url_for("menu"))
    return None


def _pesos(v) -> str:
    entero, _, dec = f"{float(v or 0):,.2f}".partition(".")
    return f"$ {entero.replace(',', '.')},{dec}"


def _fecha(texto) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat((texto or "").strip())
    except ValueError:
        return None


def _rango_por_defecto(cur, id_cuenta) -> tuple[datetime.date, datetime.date]:
    """El mes del último movimiento importado de la cuenta; sin extracto, el
    mes en curso. Abrir la pantalla en el mes de hoy mostraba una grilla vacía
    hasta que alguien importara el extracto del día."""
    hoy = datetime.date.today()
    cur.execute("SELECT MAX(fecham) AS f FROM c_extractos_bancarios WHERE c_cuentas_de_fondos_id = %s", (id_cuenta,))
    ultima = (cur.fetchone() or {}).get("f") or hoy
    return ultima.replace(day=1), ultima


@extractos_bp.route("")
def index():
    salida = _guardia()
    if salida:
        return salida

    id_cuenta = request.args.get("cuenta", type=int)
    desde, hasta = _fecha(request.args.get("desde")), _fecha(request.args.get("hasta"))
    filas, resumen, excedido, cuenta = [], {}, False, None

    with get_connection() as conn:
        cuentas = get_cuentas(conn)
        if not id_cuenta and cuentas:
            id_cuenta = cuentas[0]["id"]
        cuenta = next((c for c in cuentas if c["id"] == id_cuenta), None)
        with conn.cursor() as cur:
            if cuenta:
                d0, h0 = _rango_por_defecto(cur, id_cuenta)
                desde, hasta = desde or d0, hasta or h0
                cur.execute("""
                    SELECT e.id, e.fecham, e.fechav, e.ref_nro, e.debito, e.credito, e.saldo, e.concepto, e.cuit,
                           e.origen, e.importado, e.conciliado,
                           ch.id AS id_conc, ch.periodo, ch.estado AS estado_conc, ci.estado AS estado_item
                      FROM c_extractos_bancarios e
                      LEFT JOIN conciliacion_items ci ON ci.id_extracto = e.id
                      LEFT JOIN conciliacion_header ch ON ch.id = ci.id_conciliacion
                     WHERE e.c_cuentas_de_fondos_id = %s AND e.fecham BETWEEN %s AND %s
                     ORDER BY e.fecham, e.id
                     LIMIT %s""", (id_cuenta, desde, hasta, TOPE + 1))
                filas = cur.fetchall()
                excedido = len(filas) > TOPE
                filas = filas[:TOPE]
                cur.execute("""
                    SELECT COALESCE(SUM(credito), 0) AS creditos, COALESCE(SUM(debito), 0) AS debitos, COUNT(*) AS cant,
                           MAX(importado) AS ultimo_import
                      FROM c_extractos_bancarios
                     WHERE c_cuentas_de_fondos_id = %s AND fecham BETWEEN %s AND %s""", (id_cuenta, desde, hasta))
                resumen = cur.fetchone()
                # La conciliación de cada período de la cuenta: para ir de acá a ella.
                cur.execute("""SELECT id, periodo, estado FROM conciliacion_header
                                WHERE id_cuenta = %s AND fecha_desde <= %s AND fecha_hasta >= %s
                                ORDER BY periodo""", (id_cuenta, hasta, desde))
                resumen["conciliaciones"] = cur.fetchall()
                import conciliacion          # el saldo de cierre se calcula igual que en la conciliación
                resumen["saldo_banco"] = conciliacion.saldo_extracto_cierre(cur, id_cuenta, desde, hasta)

    for f in filas:
        if f["conciliado"] or f["estado_conc"] == "cerrado":
            f["estado_txt"], f["estado_tipo"] = "Conciliado", "ok"
        elif f["id_conc"] and f["estado_item"] == "conciliado":
            f["estado_txt"], f["estado_tipo"] = "Conciliado (abierta)", "ok"
        elif f["id_conc"] and f["estado_item"] == "excepcion":
            f["estado_txt"], f["estado_tipo"] = "Excepción", "warn"
        elif f["id_conc"]:
            f["estado_txt"], f["estado_tipo"] = "En conciliación", "proceso"
        else:
            f["estado_txt"], f["estado_tipo"] = "Pendiente", "neutro"

    return render_template("tesoreria/extractos.html", cuentas=cuentas, cuenta=cuenta, id_cuenta=id_cuenta,
                           desde=desde, hasta=hasta, filas=filas, resumen=resumen, excedido=excedido, tope=TOPE,
                           bancos=BANCOS, puede_conc=puede("/tesoreria/conc"))


@extractos_bp.route("/importar", methods=["POST"])
def importar():
    salida = _guardia()
    if salida:
        return salida

    # Al elegir una carpeta el navegador manda todos sus archivos con el mismo
    # name, así que siempre se trabaja con una lista.
    archivos = [f for f in request.files.getlist("archivo") if f and f.filename]
    id_cuenta = request.form.get("id_cuenta", type=int)
    banco_sel = (request.form.get("banco") or "").strip().upper()
    volver = redirect(url_for("extractos.index", cuenta=id_cuenta) if id_cuenta else url_for("extractos.index"))

    if not id_cuenta:
        flash("!Elegí la cuenta bancaria del extracto.")
        return volver
    if not archivos:
        flash("!Elegí uno o más archivos, o una carpeta.")
        return volver

    # De una carpeta vienen también PDFs, Excels y subcarpetas.
    candidatos = [f for f in archivos if f.filename.lower().rsplit(".", 1)[-1] in ("csv", "txt")]
    ignorados = len(archivos) - len(candidatos)
    if not candidatos:
        flash(f"!No hay archivos .csv ni .txt para importar ({ignorados} ignorados).")
        return volver

    # En orden cronológico según la fecha del nombre: los duplicados los
    # resuelve el número de operación, pero así el extracto queda cargado en
    # orden y el resultado se lee mejor.
    candidatos.sort(key=lambda f: (_fecha_del_nombre(os.path.basename(f.filename)) or datetime.date.min,
                                   os.path.basename(f.filename)))

    total = {"archivos": 0, "insertados": 0, "descartados": 0, "errores": 0, "credito": 0.0, "debito": 0.0,
             "desde": None, "hasta": None}
    problemas: list[tuple[str, str]] = []

    with get_connection() as conn:
        for archivo in candidatos:
            nombre = os.path.basename(archivo.filename)
            raw = archivo.read()
            try:
                contenido = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                contenido = raw.decode("latin-1")
            banco = banco_sel or detectar_banco(nombre, contenido)
            if not banco:
                problemas.append((nombre, "no se reconoce el banco: elegilo en «Banco / formato»"))
                continue
            if banco not in BANCOS:
                problemas.append((nombre, f"el banco «{banco}» no tiene lector"))
                continue
            try:
                res = importar_extracto(conn, id_cuenta, banco, contenido, nombre)
            except CuentaEquivocada as e:
                problemas.append((nombre, str(e)))
                continue
            except Exception as e:                           # noqa: BLE001 — se informa por archivo
                log.exception("Extracto %s: falló la importación", nombre)
                problemas.append((nombre, f"no se pudo importar ({e})"))
                continue
            total["archivos"] += 1
            total["insertados"] += res["insertados"]
            total["descartados"] += res["descartados_por_duplicado"]
            total["errores"] += res["errores"]
            total["credito"] += res["total_credito"]
            total["debito"] += res["total_debito"]
            if res.get("aviso_cuenta"):
                problemas.append((nombre, res["aviso_cuenta"]))
            for d in res.get("detalle_errores") or []:
                problemas.append((nombre, d))
        if total["insertados"]:
            with conn.cursor() as cur:
                cur.execute("""SELECT MIN(fecham) AS d, MAX(fecham) AS h FROM c_extractos_bancarios
                                WHERE c_cuentas_de_fondos_id = %s AND importado >= NOW() - INTERVAL 10 MINUTE""",
                            (id_cuenta,))
                r = cur.fetchone() or {}
                total["desde"], total["hasta"] = r.get("d"), r.get("h")

    if total["archivos"]:
        if total["insertados"] == 0 and total["descartados"]:
            flash(f"!Ningún movimiento nuevo: los {total['descartados']} renglones ya estaban cargados en esta cuenta.")
        else:
            partes = [f"{total['insertados']} movimientos importados"
                      + (f" de {total['archivos']} archivos" if total["archivos"] > 1 else "")]
            if total["descartados"]:
                partes.append(f"{total['descartados']} ya estaban cargados")
            if total["insertados"]:
                partes.append(f"créditos {_pesos(total['credito'])}, débitos {_pesos(total['debito'])}")
            flash(("!" if total["errores"] else "") + " · ".join(partes) + ".")
    if ignorados:
        flash(f"!Se ignoraron {ignorados} archivos que no son .csv ni .txt.")
    for nombre, motivo in problemas[:10]:
        flash(f"!{nombre}: {motivo}")
    if len(problemas) > 10:
        flash(f"!…y {len(problemas) - 10} avisos más.")

    # Se vuelve mostrando lo que se acaba de importar.
    if total["desde"]:
        return redirect(url_for("extractos.index", cuenta=id_cuenta, desde=total["desde"].isoformat(),
                                hasta=total["hasta"].isoformat()))
    return volver


@extractos_bp.route("/<int:id_extracto>/borrar", methods=["POST"])
def borrar(id_extracto):
    salida = _guardia()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, c_cuentas_de_fondos_id AS cuenta, fecham, conciliado FROM c_extractos_bancarios WHERE id = %s",
                        (id_extracto,))
            e = cur.fetchone()
            if not e:
                flash("!Ese renglón del extracto no existe.")
                return redirect(url_for("extractos.index"))
            cur.execute("""SELECT ch.periodo FROM conciliacion_items ci JOIN conciliacion_header ch ON ch.id = ci.id_conciliacion
                            WHERE ci.id_extracto = %s LIMIT 1""", (id_extracto,))
            en_conc = cur.fetchone()
            if e["conciliado"] or en_conc:
                per = en_conc["periodo"] if en_conc else ""
                flash(f"!No se borra: el renglón está en la conciliación {per[:4]}-{per[4:]}. "
                      "Primero hay que sacarlo de ahí (desvincularlo o quitar la excepción).")
            else:
                cur.execute("DELETE FROM c_extractos_bancarios WHERE id = %s", (id_extracto,))
                flash("Renglón del extracto eliminado.")
    return redirect(url_for("extractos.index", cuenta=e["cuenta"], desde=request.form.get("desde") or None,
                            hasta=request.form.get("hasta") or None))
