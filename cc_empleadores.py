"""
cc_empleadores.py — Cuenta corriente de empleadores (cuota sindical) y
aplicación de cobros a las cuotas.

    /empleadores/cc                              bandeja: empleadores con su saldo (menú 12)
    /empleadores/cc/<cuit>                       estado de cuenta del CUIT, por período, con los cobros
    /empleadores/cc/<cuit>/<periodo>             la cuota de un período: liquidación, cobros aplicados, afiliados
    /empleadores/cc/aplicaciones                 aplicar y desaplicar (menú 13); ?cuit= un empleador
    /empleadores/cc/aplicaciones/aplicar         POST
    /empleadores/cc/aplicaciones/<id>/desaplicar POST
    /empleadores/cc/aplicaciones/automatica      POST (un CUIT o todos)

Lo que el empleador tiene que pagar contra lo que pagó:

    Debe    la liquidación vigente de cuota sindical (`fisca_liquidacion`, por
            DDJJ de OSEDA, Libro de Sueldos Digital, nómina o AEDA)
    Haber   lo cobrado: los cobros de fisca_aplicaciones.py (recibos de cuota
            sindical, AEDA-RC, ingresos por fiscalización con el CUIT)

    Saldo = Debe − Haber: positivo, el empleador debe; negativo, pagó de más.

Qué cobro cancela qué período lo dicen las aplicaciones (`fisca_aplicacion`):
saldo del período = liquidado − aplicado; lo cobrado sin aplicar es saldo a
favor del empleador, todavía sin período. «Vencido» = saldo de los períodos
cuyo vencimiento ya pasó. Lo liquidado se carga en Liquidación de Cuota
Sindical o con la presentación del LSD; lo cobrado, en Emisión de Recibos.
"""

from __future__ import annotations

import datetime
import logging
import re
from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for

import fisca_actas
import fisca_aplicaciones as fa
import fisca_liquidacion as fl
from db import get_connection, puede, usuario_actual, validasesion
from pagos_datos import leer_importe

log = logging.getLogger(__name__)

cc_emp_bp = Blueprint("cc_emp", __name__, url_prefix="/empleadores/cc")

URL = "/empleadores/cc"
URL_APLIC = "/empleadores/cc/aplicaciones"
ORIGENES = {"ddjj": "DDJJ OSEDA", "lsd": "Libro de Sueldos", "nomina": "Nómina", "aeda": "AEDA"}
AVISO_ESQUEMA = "!Falta correr sql/fisca_aplicaciones_20261114.sql en la base (DBeaver, como root)."


def _guardia(*urls):
    if not validasesion():
        return redirect(url_for("login"))
    if not any(puede(u) for u in urls):
        flash("!No tenés permiso para esa pantalla.")
        return redirect(url_for("menu"))
    return None


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


def _uid():
    return (usuario_actual() or {}).get("id")


def _cuit(v) -> str | None:
    t = re.sub(r"\D", "", v or "")
    return t if len(t) == 11 else None


def periodo_de(texto) -> str | None:
    """'2026-10' o '202610' → '202610'."""
    t = re.sub(r"\D", "", texto or "")
    if len(t) == 6 and 1 <= int(t[4:]) <= 12:
        return t
    return None


def _filtros_bandeja(args) -> dict:
    saldo = args.get("saldo", "deuda")
    return {"q": (args.get("q") or "").strip(),
            "saldo": saldo if saldo in ("deuda", "favor", "todos") else "deuda",
            "desde": periodo_de(args.get("desde")), "hasta": periodo_de(args.get("hasta"))}


def _rango(alias: str, campo: str, f: dict, params: list) -> str:
    sql = ""
    if f["desde"]:
        sql += f" AND {alias}.{campo} >= %s"
        params.append(f["desde"])
    if f["hasta"]:
        sql += f" AND {alias}.{campo} <= %s"
        params.append(f["hasta"])
    return sql


def consultar_bandeja(cur, f: dict) -> list[dict]:
    """Un renglón por CUIT con liquidaciones o cobros. Sin rango, el saldo es
    liquidado − cobrado. Con un rango de períodos es lo liquidado de esos
    períodos menos lo aplicado a ellos (`cobrado` pasa a ser lo aplicado)."""
    con_rango = bool(f["desde"] or f["hasta"])
    p_liq = []
    r_liq = _rango("l", "periodo", f, p_liq)
    params = list(fa.MOTIVOS_COBRO) + p_liq
    where, having = "", {"deuda": "saldo > 0.01", "favor": "saldo < -0.01"}.get(f["saldo"], "1 = 1")
    if f["q"]:
        digitos = re.sub(r"\D", "", f["q"])
        where = "WHERE (e.razon_social LIKE %s OR e.nombre_fantasia LIKE %s" + (" OR t.cuit LIKE %s)" if digitos else ")")
        params += [f"%{f['q']}%"] * 2 + ([f"%{digitos}%"] if digitos else [])
        having = "1 = 1"
    cobrado = "COALESCE(liq.aplicado, 0)" if con_rango else "COALESCE(cobt.cobrado, 0)"
    cur.execute(f"""
        WITH cob AS ({fa.SQL_COBROS}),
        lq AS (SELECT l.cuit, l.periodo, l.importe, l.vencimiento, {fa.sql_aplicado_liq('l')} AS aplicado
                 FROM fisca_liquidacion l WHERE l.estado = 'vigente'{r_liq}),
        liq AS (SELECT cuit, SUM(importe) AS liquidado, SUM(aplicado) AS aplicado, COUNT(*) AS periodos,
                       MAX(periodo) AS ultimo_liq, SUM(importe - aplicado > 0.01) AS periodos_deuda,
                       SUM(CASE WHEN importe - aplicado > 0.01 AND vencimiento < CURDATE()
                                THEN importe - aplicado ELSE 0 END) AS vencido
                  FROM lq GROUP BY cuit),
        cobt AS (SELECT c.cuit, SUM(c.importe) AS cobrado, SUM(c.importe - c.aplicado) AS sin_aplicar,
                        COUNT(DISTINCT c.id_orden) AS recibos, MAX(c.fecha) AS ultimo_pago
                   FROM cob c GROUP BY c.cuit),
        t AS (SELECT cuit FROM liq UNION SELECT cuit FROM cobt{' WHERE 1 = 0' if con_rango else ''})
        SELECT t.cuit, e.id AS id_empresa, e.razon_social, e.nombre_fantasia,
               COALESCE(liq.liquidado, 0) AS liquidado, {cobrado} AS cobrado,
               COALESCE(liq.liquidado, 0) - {cobrado} AS saldo,
               COALESCE(liq.periodos, 0) AS periodos, liq.ultimo_liq, COALESCE(cobt.recibos, 0) AS recibos,
               cobt.ultimo_pago, COALESCE(cobt.sin_aplicar, 0) AS sin_aplicar,
               COALESCE(liq.periodos_deuda, 0) AS periodos_deuda, COALESCE(liq.vencido, 0) AS vencido
          FROM t
          LEFT JOIN liq  ON liq.cuit = t.cuit
          LEFT JOIN cobt ON cobt.cuit = t.cuit
          LEFT JOIN p_empresas e ON e.CUIT = CAST(t.cuit AS UNSIGNED)
          {where}
        HAVING {having}
         ORDER BY saldo DESC, e.razon_social""", params)
    return list(cur.fetchall())


@cc_emp_bp.route("")
def bandeja():
    salida = _guardia(URL)
    if salida:
        return salida
    f = _filtros_bandeja(request.args)
    with get_connection() as conn:
        with conn.cursor() as cur:
            if fa.falta_esquema(cur):
                flash(AVISO_ESQUEMA)
                filas = []
            else:
                filas = consultar_bandeja(cur, f)
    tot = {k: sum((_d(x[k]) for x in filas), Decimal("0"))
           for k in ("liquidado", "cobrado", "saldo", "vencido", "sin_aplicar")}
    return render_template("empleadores/cc_bandeja.html", filas=filas, f=f, tot=tot,
                           hay_filtros=bool(f["q"] or f["saldo"] != "deuda" or f["desde"] or f["hasta"]),
                           puede_aplicar=puede(URL_APLIC))


# ─────────────────────────────────────────────────────────────────────────────
# Estado de cuenta
# ─────────────────────────────────────────────────────────────────────────────

def estado_cuenta_de(cur, cuit: str, desde: str | None = None, hasta: str | None = None) -> dict:
    """Los períodos liquidados del CUIT con lo aplicado, el saldo y el
    acumulado, y los cobros. Lo anterior a `desde` entra como saldo anterior."""
    hoy = datetime.date.today()
    liqs = fa.liquidaciones_de(cur, cuit)
    cobros = fa.cobros_de(cur, cuit)
    aplicado_a = {}                                   # id_detalle → [período, …]
    for a in fa.aplicaciones_de(cur, cuit):
        if not a["muerta"]:
            aplicado_a.setdefault(a["id_detalle"], []).append(a["periodo"])
    for c in cobros:
        c["periodos_aplicados"] = sorted(set(aplicado_a.get(c["id_detalle"], [])))
    actas = fisca_actas.actas_por_periodo(cur, cuit)

    periodos = []
    for l in liqs:
        venc = l["vencimiento"]
        periodos.append({"periodo": l["periodo"], "liq": l, "liquidado": l["importe"], "cobrado": l["aplicado"],
                         "acta": actas.get(l["periodo"]),
                         "saldo": l["saldo"], "vencimiento": venc,
                         "mora": (hoy - venc).days if (venc and l["saldo"] > Decimal("0.01") and venc < hoy) else None})
    sin_aplicar = sum((c["sin_aplicar"] for c in cobros), Decimal("0"))
    anterior = sum((x["saldo"] for x in periodos if desde and x["periodo"] < desde), Decimal("0"))
    visibles = [x for x in periodos if (not desde or x["periodo"] >= desde) and (not hasta or x["periodo"] <= hasta)]
    acum = anterior
    for x in visibles:
        acum += x["saldo"]
        x["acumulado"] = acum

    def en_rango(p):
        return bool(p) and (not desde or p >= desde) and (not hasta or p <= hasta)
    if desde or hasta:
        cobros = [c for c in cobros if en_rango(c["per"]) or any(en_rango(p) for p in c["periodos_aplicados"])]
    return {
        "periodos": visibles, "anterior": anterior, "cobros": cobros,
        "liquidado": sum((x["liquidado"] for x in visibles), Decimal("0")),
        "cobrado": sum((x["cobrado"] for x in visibles), Decimal("0")),
        "sin_aplicar": sin_aplicar,
        "saldo_total": sum((x["saldo"] for x in periodos), Decimal("0")) - sin_aplicar,
        "vencido": sum((x["saldo"] for x in periodos if x["mora"] is not None), Decimal("0")),
        "periodos_deuda": sum(1 for x in periodos if x["saldo"] > Decimal("0.01")),
    }


def _empresa(cur, cuit: str) -> dict | None:
    cur.execute("SELECT id, CUIT, razon_social, nombre_fantasia FROM p_empresas WHERE CUIT = %s", (int(cuit),))
    return cur.fetchone()


@cc_emp_bp.route("/<cuit>")
def estado_cuenta(cuit):
    salida = _guardia(URL)
    if salida:
        return salida
    cuit = _cuit(cuit)
    if not cuit:
        flash("!El CUIT tiene que tener 11 dígitos.")
        return redirect(url_for("cc_emp.bandeja"))
    desde, hasta = periodo_de(request.args.get("desde")), periodo_de(request.args.get("hasta"))
    solo_saldo = request.args.get("con_saldo") == "1"
    with get_connection() as conn:
        with conn.cursor() as cur:
            if fa.falta_esquema(cur):
                flash(AVISO_ESQUEMA)
                return redirect(url_for("cc_emp.bandeja"))
            empresa = _empresa(cur, cuit)
            ec = estado_cuenta_de(cur, cuit, desde, hasta)
    if not empresa and not ec["periodos"] and not ec["cobros"]:
        flash(f"!El CUIT {cuit} no tiene liquidaciones ni cobros de cuota sindical.")
        return redirect(url_for("cc_emp.bandeja"))
    if solo_saldo:
        ec["periodos"] = [x for x in ec["periodos"] if abs(x["saldo"]) > Decimal("0.01")]
    return render_template("empleadores/cc_estado_cuenta.html", cuit=cuit, empresa=empresa, ec=ec,
                           desde=desde, hasta=hasta, solo_saldo=solo_saldo, origenes=ORIGENES,
                           hay_filtros=bool(desde or hasta or solo_saldo),
                           puede_liq=puede("/fiscalizacion/liquidacion"), puede_rec=puede("/fiscalizacion/recibos"),
                           puede_ingreso=puede("/tesoreria/movimientos") or puede("/tesoreria/nueva_orden_concepto"),
                           puede_empleador=puede("/empleadores"), puede_aplicar=puede(URL_APLIC),
                           puede_actas=puede(fisca_actas.URL_ACTAS))


@cc_emp_bp.route("/<cuit>/<periodo>")
def periodo(cuit, periodo):
    """La cuota de un período, dentro de la cuenta corriente: la liquidación,
    lo aplicado y el saldo, los cobros que la cancelan, los cobros de ese
    período que siguen sin aplicar y los afiliados liquidados."""
    salida = _guardia(URL)
    if salida:
        return salida
    cuit, per = _cuit(cuit), periodo_de(periodo)
    if not (cuit and per):
        flash("!El CUIT o el período no son válidos.")
        return redirect(url_for("cc_emp.bandeja"))
    with get_connection() as conn:
        with conn.cursor() as cur:
            if fa.falta_esquema(cur):
                flash(AVISO_ESQUEMA)
                return redirect(url_for("cc_emp.bandeja"))
            # La vigente; si no hay, la última anulada (para ver por qué).
            cur.execute(f"""SELECT l.*, e.razon_social, e.id AS id_empresa, u.nombre AS usuario,
                                   {fa.sql_aplicado_liq('l')} AS aplicado
                              FROM fisca_liquidacion l
                              LEFT JOIN p_empresas e ON e.CUIT = CAST(l.cuit AS UNSIGNED)
                              LEFT JOIN s_usuarios u ON u.id = l.id_usuario
                             WHERE l.cuit = %s AND l.periodo = %s
                             ORDER BY l.estado = 'vigente' DESC, l.id DESC LIMIT 1""", (cuit, per))
            liq = cur.fetchone()
            if not liq:
                flash(f"!El CUIT {cuit} no tiene liquidación de {per[:4]}-{per[4:]}.")
                return redirect(url_for("cc_emp.estado_cuenta", cuit=cuit))
            cur.execute("""SELECT d.*, COALESCE(d.apellido_nombres, a.apellido_nombres) AS nombre
                             FROM fisca_liquidacion_detalle d
                             LEFT JOIN p_afiliados a ON a.id_afiliado = d.id_afiliado
                            WHERE d.id_liquidacion = %s
                            ORDER BY d.fuente = 'sin_ddjj', nombre, d.cuil""", (liq["id"],))
            detalle = cur.fetchall()
            aplicadas = [a for a in fa.aplicaciones_de(cur, cuit) if a["id_liquidacion"] == liq["id"]]
            pendientes = [c for c in fa.cobros_de(cur, cuit) if c["per"] == per and c["sin_aplicar"] > Decimal("0.01")]
    liq["importe"], liq["aplicado"] = _d(liq["importe"]), _d(liq["aplicado"])
    vigente = liq["estado"] == "vigente"
    liq["saldo"] = liq["importe"] - liq["aplicado"] if vigente else Decimal("0")
    hoy = datetime.date.today()
    mora = ((hoy - liq["vencimiento"]).days
            if vigente and liq["vencimiento"] and liq["saldo"] > Decimal("0.01") and liq["vencimiento"] < hoy else None)
    return render_template("empleadores/cc_periodo.html", cuit=cuit, liq=liq, detalle=detalle, aplicadas=aplicadas,
                           pendientes=pendientes, mora=mora, origenes=fl.ORIGENES, origen_tipo=fl.ORIGEN_TIPO,
                           fuentes=fl.FUENTES, fuente_tipo=fl.FUENTE_TIPO, origenes_aplic=fa.ORIGENES,
                           volver=request.args.get("volver") if (request.args.get("volver") or "").startswith(URL) else None,
                           puede_aplicar=puede(URL_APLIC), puede_rec=puede("/fiscalizacion/recibos"),
                           puede_ingreso=puede("/tesoreria/movimientos") or puede("/tesoreria/nueva_orden_concepto"),
                           puede_empleador=puede("/empleadores"), puede_padron=puede("/afiliados/padron"))


# ─────────────────────────────────────────────────────────────────────────────
# Aplicación de cobros
# ─────────────────────────────────────────────────────────────────────────────

def candidatos(cur) -> list[dict]:
    """Los CUIT con cobros sin aplicar Y cuotas con saldo: lo que se puede aplicar."""
    cur.execute(f"""
        WITH cob AS ({fa.SQL_COBROS}),
        c AS (SELECT cuit, SUM(importe - aplicado) AS sin_aplicar, SUM(importe - aplicado > 0.01) AS cobros
                FROM cob GROUP BY cuit HAVING sin_aplicar > 0.01),
        lq AS (SELECT l.cuit, l.importe - {fa.sql_aplicado_liq('l')} AS saldo
                 FROM fisca_liquidacion l WHERE l.estado = 'vigente'),
        l AS (SELECT cuit, SUM(saldo) AS deuda, COUNT(*) AS cuotas FROM lq WHERE saldo > 0.01 GROUP BY cuit)
        SELECT c.cuit, e.razon_social, e.nombre_fantasia, c.sin_aplicar, c.cobros, l.deuda, l.cuotas,
               LEAST(c.sin_aplicar, l.deuda) AS aplicable
          FROM c JOIN l ON l.cuit = c.cuit
          LEFT JOIN p_empresas e ON e.CUIT = CAST(c.cuit AS UNSIGNED)
         ORDER BY aplicable DESC""", list(fa.MOTIVOS_COBRO))
    return list(cur.fetchall())


def _pesos(v) -> str:
    entero, _, dec = f"{float(v or 0):,.2f}".partition(".")
    return f"$ {entero.replace(',', '.')},{dec}"


def _volver_aplic(cuit=None):
    destino = request.form.get("volver") or ""
    if destino.startswith("/empleadores/cc"):
        return redirect(destino)
    return redirect(url_for("cc_emp.aplicaciones", cuit=cuit) if cuit else url_for("cc_emp.aplicaciones"))


@cc_emp_bp.route("/aplicaciones")
def aplicaciones():
    salida = _guardia(URL_APLIC)
    if salida:
        return salida
    cuit = _cuit(request.args.get("cuit"))
    if request.args.get("cuit") and not cuit:
        flash("!El CUIT tiene que tener 11 dígitos.")
    with get_connection() as conn:
        with conn.cursor() as cur:
            if fa.falta_esquema(cur):
                flash(AVISO_ESQUEMA)
                return render_template("empleadores/cc_aplicaciones.html", cuit=None, sugeridos=[],
                                       falta_esquema=True, puede_cc=puede(URL))
            if not cuit:
                return render_template("empleadores/cc_aplicaciones.html", cuit=None, sugeridos=candidatos(cur),
                                       puede_cc=puede(URL), falta_esquema=False)
            empresa = _empresa(cur, cuit)
            liqs = fa.liquidaciones_de(cur, cuit)
            cobros = fa.cobros_de(cur, cuit)
            aplics = fa.aplicaciones_de(cur, cuit)
    return render_template("empleadores/cc_aplicaciones.html", cuit=cuit, empresa=empresa, falta_esquema=False,
                           cuotas=[l for l in liqs if l["saldo"] > Decimal("0.01")],
                           de_mas=[l for l in liqs if l["saldo"] < Decimal("-0.01")],
                           cobros=[c for c in cobros if c["sin_aplicar"] > Decimal("0.01")],
                           aplicadas=aplics, origenes=fa.ORIGENES, puede_cc=puede(URL),
                           hoy=datetime.date.today(), puede_rec=puede("/fiscalizacion/recibos"),
                           puede_ingreso=puede("/tesoreria/movimientos") or puede("/tesoreria/nueva_orden_concepto"))


@cc_emp_bp.route("/aplicaciones/aplicar", methods=["POST"])
def aplicar():
    salida = _guardia(URL_APLIC)
    if salida:
        return salida
    cuit = _cuit(request.form.get("cuit"))
    importe = leer_importe(request.form.get("importe"))
    id_det = request.form.get("id_detalle", type=int)
    id_liq = request.form.get("id_liquidacion", type=int)
    if not (id_det and id_liq):
        flash("!Elegí un cobro y una cuota.")
        return _volver_aplic(cuit)
    if importe is None:
        flash("!El importe no es válido.")
        return _volver_aplic(cuit)
    with get_connection() as conn:
        try:
            with conn.cursor() as cur:
                r = fa.aplicar(cur, id_det, id_liq, importe, "manual", _uid(), request.form.get("observaciones"))
            conn.commit()
            flash(f"Aplicados {_pesos(r['importe'])} a la cuota de {r['periodo'][:4]}-{r['periodo'][4:]}.")
        except fa.ErrorAplicacion as e:
            conn.rollback()
            flash("!" + str(e))
        except Exception:
            conn.rollback()
            raise
    return _volver_aplic(cuit)


@cc_emp_bp.route("/aplicaciones/<int:id_aplic>/desaplicar", methods=["POST"])
def desaplicar(id_aplic):
    salida = _guardia(URL_APLIC)
    if salida:
        return salida
    cuit = _cuit(request.form.get("cuit"))
    texto = (request.form.get("importe") or "").strip()
    importe = leer_importe(texto) if texto else None
    if texto and importe is None:
        flash("!El importe no es válido.")
        return _volver_aplic(cuit)
    with get_connection() as conn:
        try:
            with conn.cursor() as cur:
                r = fa.desaplicar(cur, id_aplic, importe, request.form.get("motivo"), _uid())
            conn.commit()
            flash(f"Desaplicados {_pesos(r['importe'])} de la cuota de {r['periodo'][:4]}-{r['periodo'][4:]}: "
                  "el cobro vuelve a quedar sin aplicar.")
        except fa.ErrorAplicacion as e:
            conn.rollback()
            flash("!" + str(e))
        except Exception:
            conn.rollback()
            raise
    return _volver_aplic(cuit)


@cc_emp_bp.route("/aplicaciones/automatica", methods=["POST"])
def automatica():
    salida = _guardia(URL_APLIC)
    if salida:
        return salida
    cuit = _cuit(request.form.get("cuit"))
    deuda_vieja = request.form.get("deuda_vieja") == "1"
    with get_connection() as conn:
        try:
            with conn.cursor() as cur:
                r = fa.aplicar_automatico(cur, cuits=[cuit] if cuit else None, deuda_vieja=deuda_vieja,
                                          id_usuario=_uid())
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    flash(("!" if r["de_mas"] else "") + fa.texto_resultado(r))
    return _volver_aplic(cuit)
