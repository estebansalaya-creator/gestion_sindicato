"""
cc_empleadores.py — Cuenta corriente de empleadores (cuota sindical).

    /empleadores/cc                 bandeja: empleadores con su saldo (menú 12)
    /empleadores/cc/<cuit>          estado de cuenta del CUIT, por período, con los recibos

Lo que el empleador tiene que pagar contra lo que pagó, por CUIT y período:

    Debe    la liquidación vigente de cuota sindical (`fisca_liquidacion`, por
            DDJJ de OSEDA, Libro de Sueldos Digital, nómina o AEDA)
    Haber   lo cobrado: renglones de órdenes de ingreso no anuladas con el CUIT
            del empleador (`ingreso_ordenes_detalle.cuit`) y motivo cuota
            sindical o ingresos por fiscalización (los recibos de Emisión de
            Recibos y los «AEDA-RC» / «AEDA-OI» que trajo importar_aeda_fondos.py)

    Saldo = Debe − Haber: positivo, el empleador debe; negativo, pagó de más.

Es la regla de `fisca_recibos.saldos_de`. Lo cobrado se mira por período: un
cobro sin período (o con uno que no es AAAAMM, como el 252505 de AEDA) entra
en el saldo total pero no cancela ningún período; un período pagado de más no
compensa otro. «Vencido» = saldo de los períodos cuyo vencimiento ya pasó.
Todavía no hay aplicación de cobros a la deuda ni intereses por mora.

Solo lectura: lo cobrado se carga en Emisión de Recibos; lo liquidado, en
Liquidación de Cuota Sindical o con la presentación del LSD.
"""

from __future__ import annotations

import datetime
import logging
import re
from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for

from db import get_connection, puede, validasesion

log = logging.getLogger(__name__)

cc_emp_bp = Blueprint("cc_emp", __name__, url_prefix="/empleadores/cc")

URL = "/empleadores/cc"
#: Motivos de ingreso que son pagos del empleador (además de toda orden de clase cuota_sindical).
MOTIVOS_COBRO = ("CUOTA SINDICAL", "INGRESOS POR FISCALIZACION")
#: Un período válido: AAAAMM.
RE_PERIODO_SQL = "'^(19|20)[0-9]{2}(0[1-9]|1[0-2])$'"
ORIGENES = {"ddjj": "DDJJ OSEDA", "lsd": "Libro de Sueldos", "nomina": "Nómina", "aeda": "AEDA"}

# Lo cobrado, renglón por renglón. `per` es el período si es válido; si no, NULL.
SQL_COBROS = f"""
    SELECT d.id AS id_detalle, d.id_orden, d.cuit, d.importe, d.descripcion,
           CASE WHEN d.periodo REGEXP {RE_PERIODO_SQL} THEN d.periodo END AS per,
           d.periodo AS periodo_cargado, o.fecha, o.nro_orden, o.clase, o.origen,
           m.descripcion AS motivo
      FROM ingreso_ordenes_detalle d
      JOIN ingreso_ordenes o ON o.id = d.id_orden
      LEFT JOIN c_motivos_de_ingreso m ON m.id = d.id_motivo_ingreso
     WHERE o.estado <> 'anulado' AND d.cuit REGEXP '^[0-9]{{11}}$'
       AND (o.clase = 'cuota_sindical' OR m.descripcion IN ({', '.join(['%s'] * len(MOTIVOS_COBRO))}))
"""


def _guardia():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede(URL):
        flash("!No tenés permiso para esa pantalla.")
        return redirect(url_for("menu"))
    return None


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


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
    """Un renglón por CUIT con liquidaciones o cobros. Con un rango de períodos,
    solo lo de esos períodos (los cobros sin período quedan afuera)."""
    # Los parámetros, en el orden en que aparecen en el texto: el CTE de los
    # cobros (los motivos), las liquidaciones, los cobros y los períodos.
    p_liq, p_cob, p_per = [], [], []
    r_liq = _rango("l", "periodo", f, p_liq)
    r_cob = (" AND c.per IS NOT NULL" + _rango("c", "per", f, p_cob)) if (f["desde"] or f["hasta"]) else ""
    r_per = _rango("l", "periodo", f, p_per)
    params = list(MOTIVOS_COBRO) + p_liq + p_cob + p_per
    where, having = "", {"deuda": "saldo > 0.01", "favor": "saldo < -0.01"}.get(f["saldo"], "1 = 1")
    if f["q"]:
        digitos = re.sub(r"\D", "", f["q"])
        where = "WHERE (e.razon_social LIKE %s OR e.nombre_fantasia LIKE %s" + (" OR t.cuit LIKE %s)" if digitos else ")")
        params += [f"%{f['q']}%"] * 2 + ([f"%{digitos}%"] if digitos else [])
        having = "1 = 1"
    cur.execute(f"""
        WITH cob AS ({SQL_COBROS}),
        liq AS (SELECT l.cuit, SUM(l.importe) AS liquidado, COUNT(*) AS periodos, MAX(l.periodo) AS ultimo_liq,
                       SUM(l.aeda_importe) AS aeda
                  FROM fisca_liquidacion l WHERE l.estado = 'vigente'{r_liq} GROUP BY l.cuit),
        cobt AS (SELECT c.cuit, SUM(c.importe) AS cobrado, COUNT(DISTINCT c.id_orden) AS recibos,
                        MAX(c.fecha) AS ultimo_pago, SUM(CASE WHEN c.per IS NULL THEN c.importe ELSE 0 END) AS sin_periodo
                   FROM cob c WHERE 1 = 1{r_cob} GROUP BY c.cuit),
        per AS (SELECT l.cuit, l.importe - COALESCE(x.imp, 0) AS saldo, l.vencimiento
                  FROM fisca_liquidacion l
                  LEFT JOIN (SELECT cuit, per, SUM(importe) AS imp FROM cob WHERE per IS NOT NULL GROUP BY cuit, per) x
                         ON x.cuit = l.cuit AND x.per = l.periodo
                 WHERE l.estado = 'vigente'{r_per}),
        adeu AS (SELECT cuit, SUM(saldo > 0.01) AS periodos_deuda,
                        SUM(CASE WHEN saldo > 0.01 AND vencimiento < CURDATE() THEN saldo ELSE 0 END) AS vencido
                   FROM per GROUP BY cuit),
        t AS (SELECT cuit FROM liq UNION SELECT cuit FROM cobt)
        SELECT t.cuit, e.id AS id_empresa, e.razon_social, e.nombre_fantasia,
               COALESCE(liq.liquidado, 0) AS liquidado, COALESCE(cobt.cobrado, 0) AS cobrado,
               COALESCE(liq.liquidado, 0) - COALESCE(cobt.cobrado, 0) AS saldo,
               COALESCE(liq.periodos, 0) AS periodos, liq.ultimo_liq, COALESCE(cobt.recibos, 0) AS recibos,
               cobt.ultimo_pago, COALESCE(cobt.sin_periodo, 0) AS sin_periodo,
               COALESCE(adeu.periodos_deuda, 0) AS periodos_deuda, COALESCE(adeu.vencido, 0) AS vencido
          FROM t
          LEFT JOIN liq  ON liq.cuit = t.cuit
          LEFT JOIN cobt ON cobt.cuit = t.cuit
          LEFT JOIN adeu ON adeu.cuit = t.cuit
          LEFT JOIN p_empresas e ON e.CUIT = CAST(t.cuit AS UNSIGNED)
          {where}
        HAVING {having}
         ORDER BY saldo DESC, e.razon_social""", params)
    return list(cur.fetchall())


@cc_emp_bp.route("")
def bandeja():
    salida = _guardia()
    if salida:
        return salida
    f = _filtros_bandeja(request.args)
    with get_connection() as conn:
        with conn.cursor() as cur:
            filas = consultar_bandeja(cur, f)
    tot = {k: sum((_d(x[k]) for x in filas), Decimal("0")) for k in ("liquidado", "cobrado", "saldo", "vencido")}
    return render_template("empleadores/cc_bandeja.html", filas=filas, f=f, tot=tot,
                           hay_filtros=bool(f["q"] or f["saldo"] != "deuda" or f["desde"] or f["hasta"]))


# ─────────────────────────────────────────────────────────────────────────────
# Estado de cuenta
# ─────────────────────────────────────────────────────────────────────────────

def estado_cuenta_de(cur, cuit: str, desde: str | None = None, hasta: str | None = None) -> dict:
    """Los períodos del CUIT (liquidados o cobrados) con su saldo y el acumulado,
    y los cobros. Lo anterior a `desde` entra como saldo anterior."""
    hoy = datetime.date.today()
    cur.execute("""SELECT l.id, l.periodo, l.vencimiento, l.origen, l.afiliados, l.afiliados_activos,
                          l.activos_con_ddjj, l.porc_ddjj, l.remuneracion, l.importe, l.aeda_importe,
                          l.observaciones
                     FROM fisca_liquidacion l WHERE l.estado = 'vigente' AND l.cuit = %s""", (cuit,))
    liqs = {x["periodo"]: x for x in cur.fetchall()}
    cur.execute(SQL_COBROS + " AND d.cuit = %s ORDER BY o.fecha, o.id, d.id", list(MOTIVOS_COBRO) + [cuit])
    cobros = list(cur.fetchall())

    por_per: dict[str, Decimal] = {}
    for c in cobros:
        if c["per"]:
            por_per[c["per"]] = por_per.get(c["per"], Decimal("0")) + _d(c["importe"])
    periodos = []
    for p in sorted(set(liqs) | set(por_per)):
        l = liqs.get(p)
        liq, cob = _d(l["importe"]) if l else Decimal("0"), por_per.get(p, Decimal("0"))
        saldo = liq - cob
        venc = l["vencimiento"] if l else None
        periodos.append({"periodo": p, "liq": l, "liquidado": liq, "cobrado": cob, "saldo": saldo,
                         "vencimiento": venc,
                         "mora": (hoy - venc).days if (venc and saldo > Decimal("0.01") and venc < hoy) else None})
    sin_periodo = [c for c in cobros if not c["per"]]
    total_sin_per = sum((_d(c["importe"]) for c in sin_periodo), Decimal("0"))

    anterior = sum((x["saldo"] for x in periodos if desde and x["periodo"] < desde), Decimal("0"))
    visibles = [x for x in periodos if (not desde or x["periodo"] >= desde) and (not hasta or x["periodo"] <= hasta)]
    acum = anterior
    for x in visibles:
        acum += x["saldo"]
        x["acumulado"] = acum
    en_rango = lambda c: c["per"] and (not desde or c["per"] >= desde) and (not hasta or c["per"] <= hasta)  # noqa: E731
    return {
        "periodos": visibles, "anterior": anterior,
        "cobros": [c for c in cobros if en_rango(c) or (not desde and not hasta and not c["per"])],
        "sin_periodo": sin_periodo, "total_sin_periodo": total_sin_per,
        "liquidado": sum((x["liquidado"] for x in visibles), Decimal("0")),
        "cobrado": sum((x["cobrado"] for x in visibles), Decimal("0")),
        "saldo_total": sum((x["saldo"] for x in periodos), Decimal("0")) - total_sin_per,
        "vencido": sum((x["saldo"] for x in periodos if x["mora"] is not None), Decimal("0")),
        "periodos_deuda": sum(1 for x in periodos if x["saldo"] > Decimal("0.01")),
    }


@cc_emp_bp.route("/<cuit>")
def estado_cuenta(cuit):
    salida = _guardia()
    if salida:
        return salida
    cuit = re.sub(r"\D", "", cuit or "")
    if len(cuit) != 11:
        flash("!El CUIT tiene que tener 11 dígitos.")
        return redirect(url_for("cc_emp.bandeja"))
    desde, hasta = periodo_de(request.args.get("desde")), periodo_de(request.args.get("hasta"))
    solo_saldo = request.args.get("con_saldo") == "1"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, CUIT, razon_social, nombre_fantasia FROM p_empresas WHERE CUIT = %s""",
                        (int(cuit),))
            empresa = cur.fetchone()
            ec = estado_cuenta_de(cur, cuit, desde, hasta)
    if not empresa and not ec["periodos"] and not ec["cobros"] and not ec["sin_periodo"]:
        flash(f"!El CUIT {cuit} no tiene liquidaciones ni cobros de cuota sindical.")
        return redirect(url_for("cc_emp.bandeja"))
    if solo_saldo:
        ec["periodos"] = [x for x in ec["periodos"] if abs(x["saldo"]) > Decimal("0.01")]
    return render_template("empleadores/cc_estado_cuenta.html", cuit=cuit, empresa=empresa, ec=ec,
                           desde=desde, hasta=hasta, solo_saldo=solo_saldo, origenes=ORIGENES,
                           hay_filtros=bool(desde or hasta or solo_saldo),
                           puede_liq=puede("/fiscalizacion/liquidacion"), puede_rec=puede("/fiscalizacion/recibos"),
                           puede_ingreso=puede("/tesoreria/movimientos") or puede("/tesoreria/nueva_orden_concepto"),
                           puede_empleador=puede("/empleadores"))
