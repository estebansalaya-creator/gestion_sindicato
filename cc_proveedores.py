"""
cc_proveedores.py — Cuenta corriente de proveedores y aplicación de comprobantes.

Portado de gestion_adm/cc_proveedores_routes.py, con el sistema de estilos de
acá y sin lo de la obra social (visibilidad por áreas, Integración, dispensas
de trazabilidad, firma del contador).

    /proveedores/cc                         bandeja: proveedores con saldo (menú 33)
    /proveedores/cc/cuit/<cuit>             el estado de cuenta por CUIT
    /proveedores/cc/<id>                    estado de cuenta, cronológico o por aplicación
    /proveedores/cc/<id>/aplicaciones_de    JSON: con qué se canceló un renglón (?liq= o ?pago=)
    /proveedores/cc/aplicaciones            aplicar y desaplicar (menú 36)
    /proveedores/cc/aplicaciones/aplicar    POST
    /proveedores/cc/aplicaciones/<id>/deshacer   POST

Convención única: saldo = Debe − Haber. Negativo = acreedor (le debemos al
proveedor); positivo = deudor (saldo a favor nuestro). Los movimientos salen de
`v_cc_proveedores_movimientos`: las liquidaciones cerradas van al Haber, los
pagos y anticipos al Debe.

Un comprobante se cancela de tres maneras, cada una con su fecha:
    1. pago directo        c_pasivo_liquidacion.id_pago          pago_pagos.fecha_pago
    2. aplicación recibida c_pasivo_aplicacion.id_liq_debito     c_pasivo_aplicacion.fecha
    3. nota de crédito     c_pasivo_aplicacion.id_liq_credito    c_pasivo_aplicacion.fecha
Aplicar no mueve fondos ni cambia el saldo total del proveedor: cambia qué
comprobantes quedan abiertos.
"""

from __future__ import annotations

import datetime
import logging
import re

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

import anulaciones
import pagos_datos as pd
from db import get_connection, puede, usuario_actual, validasesion
from numeracion import nro_visible, sql_nro_orden_visible, sql_nro_visible

log = logging.getLogger(__name__)

cc_prov_bp = Blueprint("cc_prov", __name__, url_prefix="/proveedores/cc")

URL_CC = "/proveedores/cc"
URL_APLICACIONES = "/proveedores/cc/aplicaciones"

#: ¿Nota de crédito? Lo dice el TIPO de comprobante, no el signo que puso
#: quien cargó (la misma regla que comprobantes_datos.es_credito), como SQL
#: sobre el alias de `arca_tipo_comprobante`.
def sql_es_credito(tc: str = "tc") -> str:
    return f"COALESCE({tc}.descripcion REGEXP 'nota.*cr[eé]dito', 0)"


#: Cómo se nombra cada origen de una aplicación. `pago` la escribe la emisión
#: de la orden de pago; `migracion`, importar_aeda_cc_proveedores.py.
ORIGENES_APLICACION = {"manual": "Manual", "pago": "Orden de pago", "migracion": "Migrada"}

#: El proveedor de cada orden: por los expedientes de sus renglones o, en un
#: anticipo puro (pagado antes de que exista la factura), por su detalle.
SQL_ORDEN_PROVEEDOR = """
    SELECT id_orden, MIN(id_proveedor) AS id_proveedor FROM (
        SELECT od.id_orden, e.id_proveedor
          FROM pago_ordenes_detalle od JOIN me_expedientes e ON e.id = od.id_expediente
         WHERE e.id_proveedor IS NOT NULL AND e.estado NOT IN ('anulado', 'reintegro')
        UNION
        SELECT ad.id_orden, ad.id_proveedor FROM pago_ordenes_anticipo_det ad
         WHERE ad.id_proveedor IS NOT NULL) u
     GROUP BY id_orden"""


# ─────────────────────────────────────────────────────────────────────────────
# Ayudas
# ─────────────────────────────────────────────────────────────────────────────

def _guardia(*urls, api=False):
    if not validasesion():
        return (jsonify(error="La sesión venció: volvé a entrar."), 401) if api else redirect(url_for("login"))
    if not any(puede(u) for u in urls):
        if api:
            return jsonify(error="No tenés permiso."), 403
        flash("!No tenés permiso para esa pantalla.")
        return redirect(url_for("menu"))
    return None


def _restar_meses(fecha: datetime.date, meses: int) -> datetime.date:
    """31/03 menos un mes es 28/02 (o 29), no una fecha inválida."""
    total = fecha.year * 12 + fecha.month - 1 - meses
    anio, mes = divmod(total, 12)
    mes += 1
    siguiente = datetime.date(anio + (mes == 12), mes % 12 + 1, 1)
    return datetime.date(anio, mes, min(fecha.day, (siguiente - datetime.timedelta(days=1)).day))


def _fecha(texto) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat((texto or "").strip())
    except ValueError:
        return None


def _pesos(v) -> str:
    entero, _, dec = f"{float(v or 0):,.2f}".partition(".")
    return f"$ {entero.replace(',', '.')},{dec}"


def _rubros(cur) -> list[dict]:
    cur.execute("SELECT id, nombre FROM c_rubros_de_pasivo ORDER BY nombre")
    return list(cur.fetchall())


def _proveedor(cur, id_proveedor) -> dict | None:
    cur.execute("""SELECT id, cuit, razon_social, nombre_fantasia, activo, cbu, cbu_alias
                     FROM c_proveedores WHERE id = %s""", (id_proveedor,))
    return cur.fetchone()


def _where_comprobante(cbte: str, campos=("nro_referencia", "concepto")) -> tuple[str, list]:
    """El filtro por número de comprobante: (condición, params).

    La vista guarda «Factura B 00143-00008532» y la gente tipea «8532» o
    «143-8532», como está impreso. Con guion se arma el número canónico con los
    ceros de los dos lados; sin guion se buscan los dígitos dentro de los
    dígitos guardados. Se miran los dos campos: en un pago `nro_referencia` es
    el número interno y el que se lee en pantalla («Pago 21412») está en el
    concepto."""
    cbte = (cbte or "").strip()
    if not cbte:
        return "", []

    def _o(plantilla):
        return "(" + " OR ".join(plantilla.format(c=c) for c in campos) + ")"

    m = re.match(r"^\s*(\d{1,5})\s*-\s*(\d{1,8})\s*$", cbte)
    if m:
        return _o("{c} LIKE %s"), [f"%{m.group(1).zfill(5)}-{m.group(2).zfill(8)}%"] * len(campos)
    digitos = re.sub(r"\D", "", cbte)
    if digitos:
        return _o("REPLACE(REPLACE({c}, '-', ''), ' ', '') LIKE %s"), [f"%{digitos}%"] * len(campos)
    return _o("{c} LIKE %s"), [f"%{cbte}%"] * len(campos)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Bandeja: proveedores con saldo
# ─────────────────────────────────────────────────────────────────────────────

def _filtros_bandeja(args) -> dict:
    saldo = args.get("saldo", "acreedor")
    return {"q": (args.get("q") or "").strip(),
            "saldo": saldo if saldo in ("acreedor", "deudor", "todos") else "acreedor",
            "rubro": int(args["rubro"]) if (args.get("rubro") or "").isdigit() else None,
            "activo": args.get("activo", "1") == "1",
            "hasta": _fecha(args.get("hasta"))}


def _consultar_bandeja(cur, f) -> list[dict]:
    """Los proveedores con su saldo al corte. El agregado va sobre los
    movimientos (la vista de saldos no corta por fecha) y, con un rubro, es el
    saldo de ESA cuenta, no el total mezclado del proveedor.

    Buscar un proveedor (razón social, nombre de fantasía o CUIT) manda sobre
    el resto: quien lo busca quiere encontrarlo, esté activo o no y tenga el
    saldo que tenga (como en gestion_adm)."""
    params, join = [], ""
    busca = bool(f["q"])
    if f["hasta"] and not busca:
        join += " AND m.fecha <= %s"
        params.append(f["hasta"])
    if f["rubro"] and not busca:
        join += " AND m.id_rubro_pasivo = %s"
        params.append(f["rubro"])
    if busca:
        where = "(p.razon_social LIKE %s OR p.nombre_fantasia LIKE %s OR p.cuit LIKE %s)"
        params += [f"%{f['q']}%"] * 3
        having = "1 = 1"
    else:
        where = "p.activo = 1" if f["activo"] else "1 = 1"
        having = {"acreedor": "saldo < -0.01", "deudor": "saldo > 0.01"}.get(f["saldo"],
                                                                            "ultimo_movimiento IS NOT NULL")
    cur.execute(f"""
        SELECT p.id AS id_proveedor, p.cuit, p.razon_social, p.nombre_fantasia, p.activo,
               COALESCE(SUM(m.debe), 0) AS total_debe, COALESCE(SUM(m.haber), 0) AS total_haber,
               COALESCE(SUM(m.debe), 0) - COALESCE(SUM(m.haber), 0) AS saldo,
               MAX(m.fecha) AS ultimo_movimiento,
               COUNT(DISTINCT CASE WHEN m.tipo = 'liquidacion' THEN m.id_liquidacion END) AS cant_liquidaciones,
               COUNT(DISTINCT CASE WHEN m.tipo <> 'liquidacion' THEN COALESCE(m.id_pago, -m.id_orden) END) AS cant_pagos
          FROM c_proveedores p
          LEFT JOIN v_cc_proveedores_movimientos m ON m.id_proveedor = p.id{join}
         WHERE {where}
         GROUP BY p.id, p.cuit, p.razon_social, p.nombre_fantasia, p.activo
        HAVING {having}
         ORDER BY saldo, p.razon_social""", params)
    return list(cur.fetchall())


def _pendiente_auditoria(cur, id_proveedor=None) -> dict:
    """{id_proveedor: {n, importe}}: lo ingresado por la mesa con la liquidación
    todavía abierta. No es deuda (la vista solo toma liquidaciones cerradas),
    pero tiene que verse: en unos días lo va a ser."""
    filtro = "AND e.id_proveedor = %s" if id_proveedor else ""
    cur.execute(f"""SELECT e.id_proveedor, COUNT(*) AS n, COALESCE(SUM(l.importe_liquidado), 0) AS importe
                      FROM c_pasivo_liquidacion l JOIN me_expedientes e ON e.id = l.id_expediente
                     WHERE l.fecha_cierre IS NULL AND e.id_proveedor IS NOT NULL
                       AND e.estado NOT IN ('anulado', 'rechazado', 'reintegro') {filtro}
                     GROUP BY e.id_proveedor""", (id_proveedor,) if id_proveedor else ())
    return {r["id_proveedor"]: r for r in cur.fetchall()}


@cc_prov_bp.route("")
def bandeja():
    salida = _guardia(URL_CC)
    if salida:
        return salida
    f = _filtros_bandeja(request.args)
    with get_connection() as conn:
        with conn.cursor() as cur:
            rubros = _rubros(cur)
            filas = _consultar_bandeja(cur, f)
            pend = _pendiente_auditoria(cur)
    for p in filas:
        x = pend.get(p["id_proveedor"])
        p["pend_n"] = x["n"] if x else 0
        p["pend_importe"] = float(x["importe"]) if x else 0.0
    nombre_rubro = next((r["nombre"] for r in rubros if r["id"] == f["rubro"]), "")
    return render_template("proveedores/cc_bandeja.html", filas=filas, rubros=rubros, f=f, nombre_rubro=nombre_rubro,
                           total_debe=sum(float(p["total_debe"] or 0) for p in filas),
                           total_haber=sum(float(p["total_haber"] or 0) for p in filas),
                           hay_filtros=bool(f["q"] or f["saldo"] != "acreedor" or f["rubro"] or not f["activo"]
                                            or f["hasta"]),
                           puede_aplicar=puede(URL_APLICACIONES))


@cc_prov_bp.route("/cuit/<cuit>")
def por_cuit(cuit):
    """El estado de cuenta por CUIT: las demás grillas muestran el CUIT, no el id."""
    salida = _guardia(URL_CC)
    if salida:
        return salida
    limpio = re.sub(r"\D", "", cuit or "").zfill(11)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id FROM c_proveedores
                            WHERE cuit = %s OR (cuit REGEXP '^[0-9]+$' AND CAST(cuit AS UNSIGNED) = %s)
                            ORDER BY cuit = %s DESC LIMIT 1""", (limpio, int(limpio), limpio))
            p = cur.fetchone()
    if not p:
        flash(f"!El CUIT {limpio} no está dado de alta como proveedor.")
        return redirect(url_for("cc_prov.bandeja"))
    return redirect(url_for("cc_prov.estado_cuenta", id_proveedor=p["id"], **request.args))


# ─────────────────────────────────────────────────────────────────────────────
# 2. Estado de cuenta
# ─────────────────────────────────────────────────────────────────────────────

def _filtros_estado_cuenta(args) -> dict:
    """Por defecto, los últimos 6 meses (lo anterior entra como saldo
    anterior). «No vino el parámetro» (primera entrada) no es lo mismo que
    «vino vacío» (borró la fecha a propósito: sin límite)."""
    hoy = datetime.date.today()
    desde = _restar_meses(hoy, 6) if args.get("desde") is None else _fecha(args.get("desde"))
    hasta = _fecha(args.get("hasta"))
    con_saldo = args.get("con_saldo") == "1"
    vista = args.get("vista") if args.get("vista") in ("cronologica", "aplicacion") else "cronologica"
    return {"hoy": hoy, "desde": desde, "hasta": hasta, "con_saldo": con_saldo, "vista": vista,
            "rubro": int(args["rubro"]) if (args.get("rubro") or "").isdigit() else None,
            "cbte": (args.get("cbte") or "").strip(),
            # El corte de lo que se calcula «al» una fecha. Con «solo con saldo»
            # se quiere el saldo de hoy, no el de una fecha.
            "f_hasta": datetime.date(2999, 12, 31) if con_saldo or not hasta else hasta}


def _marcar_comprobantes(cur, movimientos) -> None:
    """Cuelga de cada liquidación el comprobante, su tipo y sus marcas."""
    exp_ids = sorted({m["id_expediente"] for m in movimientos if m["tipo"] == "liquidacion" and m["id_expediente"]})
    if not exp_ids:
        return
    cur.execute(f"""
        SELECT e.id AS id_expediente, e.nro_expediente, c.id AS id_comprobante, c.ruta_local,
               tc.descripcion AS tipo_desc, {sql_es_credito()} AS es_credito,
               c.constatacion_resultado, c.leido_automatico, c.verificado_visual
          FROM me_expedientes e
          JOIN f_comprobantes_arca c ON c.id = e.id_comprobante
          LEFT JOIN arca_tipo_comprobante tc ON tc.codigo = LPAD(c.tipo_comprobante, 3, '0')
         WHERE e.id IN ({','.join(['%s'] * len(exp_ids))})""", exp_ids)
    por_exp = {r["id_expediente"]: r for r in cur.fetchall()}
    cur.execute(f"SELECT id, nro_expediente FROM me_expedientes WHERE id IN ({','.join(['%s'] * len(exp_ids))})",
                exp_ids)
    nros = {r["id"]: r["nro_expediente"] for r in cur.fetchall()}
    for m in movimientos:
        if m["tipo"] != "liquidacion":
            continue
        d = por_exp.get(m["id_expediente"]) or {}
        m["marcas"] = d or None
        m["id_comprobante"] = d.get("id_comprobante")
        m["con_pdf"] = bool((d.get("ruta_local") or "").strip())
        m["es_credito"] = bool(d.get("es_credito"))
        m["nro_expediente"] = nros.get(m["id_expediente"])


def _creditos_al_debe(movimientos) -> None:
    """La nota de crédito va al Debe, no al Haber con signo menos.

    La vista manda toda liquidación al Haber, y el crédito se guarda negativo:
    una nota de crédito se veía como una factura que resta. De qué lado va lo
    dice el TIPO del comprobante; sin comprobante, el signo. Si el tipo y el
    signo no coinciden (una nota de crédito cargada en positivo) la fila no se
    mueve —moverla cambiaría el saldo— y se marca `signo_dudoso`.

    No cambia ningún número: 0 − (−x) = (+x) − 0."""
    for m in movimientos:
        if m["tipo"] != "liquidacion":
            continue
        haber = float(m["haber"] or 0)
        es_credito = m.get("es_credito") if m.get("id_comprobante") else haber < 0
        if es_credito and haber < 0:
            m["debe"], m["haber"] = float(m["debe"] or 0) - haber, 0.0
        elif es_credito and haber > 0:
            m["signo_dudoso"] = "una nota de crédito con el importe en positivo"
        elif not es_credito and haber < 0:
            m["signo_dudoso"] = "un débito con el importe en negativo"


def _saldo_pagos(cur, id_proveedor, f_hasta) -> dict:
    """{id_pago: {importe, saldo, estado, es_anticipo}}: lo que sigue sin
    imputar de cada pago y anticipo del proveedor al corte. Un pago se consume
    por vínculo directo (`c_pasivo_liquidacion.id_pago`) o por aplicación; cada
    forma con su fecha. Sin esto la columna «Saldo comp.» no cerraba con el
    saldo: los comprobantes descontaban y el pago no sumaba nada."""
    cur.execute(f"""
        SELECT p.id AS id_pago, p.importe_total,
               (SELECT SUM(ad.importe) FROM pago_ordenes_anticipo_det ad
                 WHERE ad.id_orden = p.id_orden AND ad.id_proveedor = %s) AS importe_anticipo,
               COALESCE((SELECT SUM(l2.importe_liquidado
                                    - COALESCE((SELECT SUM(a2.importe_aplicado) FROM c_pasivo_aplicacion a2
                                                 WHERE a2.id_liq_debito = l2.id AND a2.fecha <= %s), 0))
                           FROM c_pasivo_liquidacion l2 JOIN me_expedientes e2 ON e2.id = l2.id_expediente
                          WHERE l2.id_pago = p.id AND e2.estado <> 'anulado' AND l2.fecha_cierre <= %s), 0)
               + COALESCE((SELECT SUM(a3.importe_aplicado) FROM c_pasivo_aplicacion a3
                            WHERE a3.id_pago = p.id AND a3.fecha <= %s), 0) AS consumido
          FROM pago_pagos p
          JOIN ({SQL_ORDEN_PROVEEDOR}) op ON op.id_orden = p.id_orden
         WHERE p.estado <> 'anulado' AND op.id_proveedor = %s""",
                (id_proveedor, f_hasta, f_hasta, f_hasta, id_proveedor))
    out = {}
    for r in cur.fetchall():
        es_anticipo = r["importe_anticipo"] is not None
        importe = float((r["importe_anticipo"] if es_anticipo else r["importe_total"]) or 0)
        consumido = float(r["consumido"] or 0)
        saldo = round(importe - consumido, 2)
        estado = "aplicado" if saldo <= 0.01 else "parcial" if consumido > 0.01 else "disponible"
        out[r["id_pago"]] = {"importe": importe, "saldo": saldo, "estado": estado, "es_anticipo": es_anticipo}
    return out


def _numerar_pagos(cur, movimientos) -> None:
    """El número que se lee de cada pago (el de AEDA si vino de allá: la vista
    trae el interno) y, del anticipo sin pagar, el de la orden."""
    ids = sorted({m["id_pago"] for m in movimientos if m["tipo"] != "liquidacion" and m["id_pago"]})
    nros = {}
    if ids:
        cur.execute(f"SELECT id, {sql_nro_visible('p')} AS nro FROM pago_pagos p "
                    f"WHERE id IN ({','.join(['%s'] * len(ids))})", ids)
        nros = {r["id"]: r["nro"] for r in cur.fetchall()}
    for m in movimientos:
        if m["tipo"] == "liquidacion":
            m["numero"] = m["nro_referencia"]
        elif m["id_pago"]:
            m["numero"] = f"Pago {nros.get(m['id_pago']) or m['nro_referencia']}"
        else:
            m["numero"] = f"Orden {m['nro_referencia']}"


_ETIQUETA_ANTICIPO = {"aplicado": "Anticipo aplicado", "parcial": "Anticipo aplicado en parte",
                      "disponible": "Anticipo"}


def _concepto_anticipo(concepto, estado) -> str:
    """«Anticipo · Pago 1234» → «Anticipo aplicado · Pago 1234»: el número queda."""
    etiqueta = _ETIQUETA_ANTICIPO.get(estado, "Anticipo")
    partes = (concepto or "").split(" · ")
    if partes and partes[0].strip().lower().startswith("anticipo"):
        partes[0] = etiqueta
    else:
        partes.insert(0, etiqueta)
    return " · ".join(p for p in partes if p)


def _saldo_comprobantes(cur, id_proveedor, f_hasta) -> dict:
    """{id_liquidacion: saldo} con signo deudor: la factura negativa (le
    debemos) y cada cancelación la acerca a cero; la nota de crédito, positiva
    mientras no se aplique. El corte va a cada forma de cancelación por su
    propia fecha: el saldo al 31/03 no descuenta una nota aplicada en abril. El
    'desde' no interviene: lo cancelado antes del período sigue cancelado."""
    cur.execute("""
        SELECT l.id, l.importe_liquidado,
               CASE WHEN l.id_pago IS NOT NULL AND p.fecha_pago <= %s THEN l.importe_liquidado ELSE 0 END AS pagado,
               COALESCE((SELECT SUM(a.importe_aplicado) FROM c_pasivo_aplicacion a
                          WHERE a.id_liq_debito = l.id AND a.fecha <= %s), 0) AS recibido,
               COALESCE((SELECT SUM(a.importe_aplicado) FROM c_pasivo_aplicacion a
                          WHERE a.id_liq_credito = l.id AND a.fecha <= %s), 0) AS entregado
          FROM c_pasivo_liquidacion l
          JOIN me_expedientes e ON e.id = l.id_expediente
          LEFT JOIN pago_pagos p ON p.id = l.id_pago
         WHERE e.id_proveedor = %s AND e.estado NOT IN ('anulado', 'reintegro') AND l.fecha_cierre IS NOT NULL""",
                (f_hasta, f_hasta, f_hasta, id_proveedor))
    return {r["id"]: round(-float(r["importe_liquidado"] or 0) + float(r["pagado"] or 0)
                           + float(r["recibido"] or 0) - float(r["entregado"] or 0), 2)
            for r in cur.fetchall()}


def _cancelaciones(cur, id_proveedor, f_hasta) -> dict:
    """{id_liquidacion: [cancelación, …]} para la vista por aplicación: con qué
    se canceló cada comprobante (pago directo, pago o nota de crédito aplicada)
    y, en una nota de crédito, a qué comprobantes se aplicó. Con el corte
    'hasta' y sin el 'desde': un pago anterior al período igual cancela."""
    cur.execute(f"""
        SELECT l.id AS id_liquidacion, p.fecha_pago AS fecha, l.importe_liquidado AS importe,
               'directo' AS forma, CONCAT('Pago ', {sql_nro_visible('p')}) AS texto, p.id_orden,
               NULL AS id_exp_otro, NULL AS nro_exp_otro, NULL AS id_aplicacion, NULL AS origen, NULL AS usuario,
               NULL AS observaciones, 1 AS es_pago
          FROM c_pasivo_liquidacion l
          JOIN me_expedientes e ON e.id = l.id_expediente
          JOIN pago_pagos p ON p.id = l.id_pago
         WHERE e.id_proveedor = %s AND p.fecha_pago <= %s
        UNION ALL
        SELECT ap.id_liq_debito, ap.fecha, ap.importe_aplicado, 'recibida',
               COALESCE(CONCAT('Pago ', {sql_nro_visible('pg')}),
                        CONCAT(COALESCE(tcc.descripcion, 'Nota de crédito'), ' ',
                               COALESCE(cc.numero_completo, ec.nro_expediente))),
               pg.id_orden, ec.id, ec.nro_expediente, ap.id, ap.origen, u.nombre, ap.observaciones,
               ap.id_pago IS NOT NULL
          FROM c_pasivo_aplicacion ap
          JOIN c_pasivo_liquidacion ld ON ld.id = ap.id_liq_debito
          JOIN me_expedientes ed ON ed.id = ld.id_expediente
          LEFT JOIN pago_pagos pg ON pg.id = ap.id_pago
          LEFT JOIN c_pasivo_liquidacion lc ON lc.id = ap.id_liq_credito
          LEFT JOIN me_expedientes ec ON ec.id = lc.id_expediente
          LEFT JOIN f_comprobantes_arca cc ON cc.id = ec.id_comprobante
          LEFT JOIN arca_tipo_comprobante tcc ON tcc.codigo = LPAD(cc.tipo_comprobante, 3, '0')
          LEFT JOIN s_usuarios u ON u.id = ap.id_usuario
         WHERE ed.id_proveedor = %s AND ap.fecha <= %s
        UNION ALL
        SELECT ap.id_liq_credito, ap.fecha, ap.importe_aplicado, 'entregada',
               CONCAT(COALESCE(tcd.descripcion, 'Comprobante'), ' ', COALESCE(cd.numero_completo, ed.nro_expediente)),
               NULL, ed.id, ed.nro_expediente, ap.id, ap.origen, u.nombre, ap.observaciones, 0
          FROM c_pasivo_aplicacion ap
          JOIN c_pasivo_liquidacion lc ON lc.id = ap.id_liq_credito
          JOIN me_expedientes ec ON ec.id = lc.id_expediente
          JOIN c_pasivo_liquidacion ld ON ld.id = ap.id_liq_debito
          JOIN me_expedientes ed ON ed.id = ld.id_expediente
          LEFT JOIN f_comprobantes_arca cd ON cd.id = ed.id_comprobante
          LEFT JOIN arca_tipo_comprobante tcd ON tcd.codigo = LPAD(cd.tipo_comprobante, 3, '0')
          LEFT JOIN s_usuarios u ON u.id = ap.id_usuario
         WHERE ec.id_proveedor = %s AND ap.fecha <= %s
         ORDER BY fecha""", (id_proveedor, f_hasta) * 3)
    out: dict = {}
    for r in cur.fetchall():
        out.setdefault(r["id_liquidacion"], []).append(r)
    return out


def _ctx_estado_cuenta(cur, id_proveedor, f) -> dict | None:
    proveedor = _proveedor(cur, id_proveedor)
    if not proveedor:
        return None
    rubros = _rubros(cur)
    rubro = f["rubro"] if any(r["id"] == f["rubro"] for r in rubros) else None
    f_rubro, p_rubro = (" AND id_rubro_pasivo = %s", [rubro]) if rubro else ("", [])
    w_cbte, p_cbte = _where_comprobante(f["cbte"])
    # El comprobante buscado y «solo con saldo» mandan sobre las fechas: una
    # factura impaga de hace dos años sigue siendo deuda, y el corte de seis
    # meses es justo lo que la esconde.
    con_periodo = not f["con_saldo"] and not w_cbte

    saldo_ant = 0.0
    if con_periodo and f["desde"]:
        cur.execute(f"""SELECT COALESCE(SUM(debe), 0) - COALESCE(SUM(haber), 0) AS saldo
                          FROM v_cc_proveedores_movimientos
                         WHERE id_proveedor = %s AND fecha < %s{f_rubro}""", [id_proveedor, f["desde"]] + p_rubro)
        saldo_ant = float(cur.fetchone()["saldo"] or 0)

    saldo_comp = _saldo_comprobantes(cur, id_proveedor, f["f_hasta"])

    where, params = ["id_proveedor = %s"], [id_proveedor]
    if rubro:
        where.append("id_rubro_pasivo = %s"); params.append(rubro)
    if w_cbte:
        where.append(w_cbte); params += p_cbte
    if con_periodo and f["desde"]:
        where.append("fecha >= %s"); params.append(f["desde"])
    if con_periodo and f["hasta"]:
        where.append("fecha <= %s"); params.append(f["hasta"])
    cur.execute(f"""SELECT * FROM v_cc_proveedores_movimientos WHERE {' AND '.join(where)}
                     ORDER BY fecha, tipo DESC, id_liquidacion, id_pago""", params)
    movimientos = [dict(m) for m in cur.fetchall()]
    _marcar_comprobantes(cur, movimientos)
    _creditos_al_debe(movimientos)

    # Pagos y anticipos: cuánto de esa plata sigue sin imputar. La vista no
    # distingue el anticipo consumido de un pago común; acá sí importa.
    saldo_pago = _saldo_pagos(cur, id_proveedor, f["f_hasta"])
    _numerar_pagos(cur, movimientos)
    for m in movimientos:
        if m["tipo"] == "liquidacion":
            m["saldo_comp"] = saldo_comp.get(m["id_liquidacion"])
            # El concepto de la vista repite el comprobante; sin comprobante
            # (solo expediente) dice el asunto, y ese sí se muestra.
            m["detalle"] = "" if m.get("id_comprobante") else (m["concepto"] or "")
            continue
        dato = saldo_pago.get(m["id_pago"]) if m["id_pago"] else None
        if not dato:
            # Anticipo con la orden aprobada y sin pagar: la plata no salió.
            m["saldo_comp"] = None
            m["sin_pago"] = not m["id_pago"]
            continue
        m["saldo_comp"] = dato["saldo"]
        if dato["es_anticipo"]:
            m["es_anticipo"] = True
            m["concepto"] = _concepto_anticipo(m["concepto"], dato["estado"])
    for m in movimientos:
        if m["tipo"] != "liquidacion":
            # «Anticipo aplicado · Pago 4021»: el número va en su columna.
            m["detalle"] = (m["concepto"] or "").split(" · ")[0] if m["tipo"] == "anticipo" or " · " in (
                m["concepto"] or "") else ""

    if f["con_saldo"]:
        movimientos = [m for m in movimientos if abs(m.get("saldo_comp") or 0) > 0.01]

    saldo = saldo_ant
    for m in movimientos:
        m["debe"], m["haber"] = float(m["debe"] or 0), float(m["haber"] or 0)
        # Con «solo con saldo» la columna acumulada suma lo pendiente: acumular
        # debe y haber daría lo facturado, no lo que falta.
        saldo += float(m["saldo_comp"] or 0) if f["con_saldo"] else m["debe"] - m["haber"]
        m["saldo_acum"] = round(saldo, 2)

    total_debe = sum(m["debe"] for m in movimientos)
    total_haber = sum(m["haber"] for m in movimientos)
    total_saldo_comp = round(sum(m["saldo_comp"] or 0 for m in movimientos), 2)
    saldo_final = total_saldo_comp if f["con_saldo"] else round(saldo_ant + total_debe - total_haber, 2)

    # Vista por aplicación: un renglón por comprobante y forma de cancelarlo
    # (el comprobante se repite en cada uno), así la grilla filtra y exporta.
    # Vista por aplicación (la de gestion_adm): cada comprobante y, debajo, con
    # qué se canceló (pago directo, pago o nota de crédito aplicada) o, si es
    # una nota de crédito, a qué comprobantes se aplicó.
    grupos = []
    if f["vista"] == "aplicacion":
        canc = _cancelaciones(cur, id_proveedor, f["f_hasta"])
        for m in movimientos:
            if m["tipo"] != "liquidacion":
                continue
            pagos = canc.get(m["id_liquidacion"]) or []
            grupos.append({**m, "pagos": pagos, "liquidado": m["haber"] or m["debe"], "saldo_comp": m["saldo_comp"] or 0,
                           "aplicado": round(sum(float(c["importe"] or 0) for c in pagos), 2)})

    pend = _pendiente_auditoria(cur, id_proveedor).get(id_proveedor)
    return {"proveedor": proveedor, "rubros": rubros, "rubro": rubro,
            "nombre_rubro": next((r["nombre"] for r in rubros if r["id"] == rubro), ""),
            "movimientos": movimientos, "grupos": grupos, "saldo_anterior": saldo_ant,
            "total_debe": total_debe, "total_haber": total_haber, "saldo_final": saldo_final,
            "total_saldo_comp": total_saldo_comp, "con_periodo": con_periodo,
            "pendiente": {"n": pend["n"], "importe": float(pend["importe"])} if pend else {"n": 0, "importe": 0.0}}


@cc_prov_bp.route("/<int:id_proveedor>")
def estado_cuenta(id_proveedor):
    salida = _guardia(URL_CC)
    if salida:
        return salida
    f = _filtros_estado_cuenta(request.args)
    with get_connection() as conn:
        with conn.cursor() as cur:
            ctx = _ctx_estado_cuenta(cur, id_proveedor, f)
            exps_impagos = len(pd.expedientes_disponibles(cur, id_proveedor)) if ctx else 0
    if not ctx:
        flash("!El proveedor no existe.")
        return redirect(url_for("cc_prov.bandeja"))
    return render_template("proveedores/cc_estado_cuenta.html", f=f, origenes=ORIGENES_APLICACION,
                           desde_12m=_restar_meses(f["hoy"], 12).isoformat(),
                           hay_filtros=bool(request.args.get("desde") is not None or f["hasta"] or f["cbte"]
                                            or f["con_saldo"]),
                           puede_aplicar=puede(URL_APLICACIONES), puede_ordenes=puede(url_for("pagos.ordenes")),
                           puede_mesa=puede(url_for("mesa.bandeja")), exps_impagos=exps_impagos, **ctx)


@cc_prov_bp.route("/<int:id_proveedor>/pdf")
def pdf_estado_cuenta(id_proveedor):
    """El estado de cuenta en PDF, con los mismos filtros que la pantalla (el
    mismo `_ctx_estado_cuenta`: si cada uno calculara por su lado, el PDF
    terminaría diciendo otra cosa). Siempre cronológico."""
    salida = _guardia(URL_CC)
    if salida:
        return salida
    f = _filtros_estado_cuenta(request.args)
    f["vista"] = "cronologica"
    with get_connection() as conn:
        with conn.cursor() as cur:
            ctx = _ctx_estado_cuenta(cur, id_proveedor, f)
    if not ctx:
        flash("!El proveedor no existe.")
        return redirect(url_for("cc_prov.bandeja"))
    import pagos_pdf
    from xml.sax.saxutils import escape
    p = ctx["proveedor"]
    hoy = f["hoy"]
    doc = pagos_pdf._Doc("Estado de Cuenta", "Proveedor")
    periodo = (f"{f['desde'].strftime('%d/%m/%Y') if f['desde'] else 'Inicio'} al "
               f"{(f['hasta'] or hoy).strftime('%d/%m/%Y')}") if ctx["con_periodo"] else (
        "comprobantes con saldo, a hoy" if f["con_saldo"] else f"comprobante «{escape(f['cbte'])}», toda la cuenta")
    doc.datos("Proveedor", [("Razón social", escape(p["razon_social"] or "")),
                            ("CUIT", pagos_pdf._cuit(p["cuit"])),
                            ("CBU", escape(" / ".join(x for x in (p["cbu"], p["cbu_alias"]) if x))),
                            ("Rubro de pasivo", escape(ctx["nombre_rubro"])),
                            ("Período", periodo)])

    def imp(v):
        return pagos_pdf._pesos(v).replace("$ ", "") if abs(float(v or 0)) > 0.005 else "—"

    filas = []
    if ctx["con_periodo"] and f["desde"]:
        filas.append(["", "", "<i>Saldo anterior</i>", "", "", f"<b>{imp(ctx['saldo_anterior'])}</b>"])
    for m in ctx["movimientos"]:
        filas.append([m["fecha"].strftime("%d/%m/%Y") if m["fecha"] else "—",
                      f"<font face='Courier'>{escape(m.get('numero') or m['nro_referencia'] or '')}</font>",
                      escape((m["concepto"] or "")[:70]), imp(m["debe"]), imp(m["haber"]),
                      f"<b>{imp(m['saldo_acum'])}</b>"])
    if filas:
        filas.append(["", "", "<b>Total del período</b>" if ctx["con_periodo"] else "<b>Total</b>",
                      f"<b>{imp(ctx['total_debe'])}</b>", f"<b>{imp(ctx['total_haber'])}</b>", ""])
    doc.tabla("Movimientos", ["Fecha", "Referencia", "Concepto", "Débito", "Crédito", "Saldo"], filas,
              [1.9, 3.2, 5.8, 2.3, 2.3, 2.3], derecha=(3, 4, 5),
              total=("Pendiente" if f["con_saldo"] else "Saldo final", imp(ctx["saldo_final"])))
    s = ctx["saldo_final"]
    doc.story.append(doc.P(f"Saldo = Debe − Haber: {'acreedor, se le debe al proveedor' if s < -0.01 else 'deudor, a favor nuestro' if s > 0.01 else 'sin saldo'}. "
                           f"Generado el {datetime.datetime.now():%d/%m/%Y %H:%M}.", fontSize=7, textColor=doc.MUTED))
    if ctx["pendiente"]["n"]:
        doc.story.append(doc.P(f"Además hay {ctx['pendiente']['n']} comprobante(s) sin auditar por "
                               f"{pagos_pdf._pesos(ctx['pendiente']['importe'])}, que no suman al saldo.",
                               fontSize=7, textColor=doc.MUTED))
    return pagos_pdf.respuesta(doc.pdf(f"Estado de cuenta {p['razon_social']}"),
                               f"CC_{p['cuit'] or id_proveedor}_{hoy.isoformat()}.pdf")


# ── Las aplicaciones de un renglón (el botón del estado de cuenta) ───────────

def _aplicaciones_de(cur, id_proveedor, id_liquidacion=None, id_pago=None) -> list[dict]:
    """Con qué se canceló una liquidación, o a qué se imputó un pago, de la más
    vieja a la más nueva. Los expedientes anulados se muestran marcados: una
    factura anulada con un pago encima es justo lo que hay que desaplicar."""
    tipo_cd = "LEFT JOIN arca_tipo_comprobante tcd ON tcd.codigo = LPAD(cd.tipo_comprobante, 3, '0')"
    usuario = "LEFT JOIN s_usuarios u ON u.id = ap.id_usuario"
    if id_liquidacion:
        sql = f"""
            SELECT p.fecha_pago AS fecha, l.importe_liquidado AS importe, 'directo' AS forma, 'pago' AS clase,
                   p.id AS id_pago, p.id_orden AS id_orden, {sql_nro_visible('p')} AS nro_pago,
                   NULL AS id_expediente, NULL AS nro_expediente, NULL AS estado_expediente,
                   NULL AS comprobante, NULL AS tipo_cbte, NULL AS origen, NULL AS id_aplicacion, NULL AS usuario
              FROM c_pasivo_liquidacion l
              JOIN me_expedientes e ON e.id = l.id_expediente
              JOIN pago_pagos p ON p.id = l.id_pago
             WHERE l.id = %s AND e.id_proveedor = %s
            UNION ALL
            SELECT ap.fecha, ap.importe_aplicado, 'recibida', IF(ap.id_pago IS NOT NULL, 'pago', 'credito'),
                   ap.id_pago, pg.id_orden, {sql_nro_visible('pg')}, ec.id, ec.nro_expediente, ec.estado,
                   cd.numero_completo, tcd.descripcion, ap.origen, ap.id, u.nombre
              FROM c_pasivo_aplicacion ap
              JOIN c_pasivo_liquidacion ld ON ld.id = ap.id_liq_debito
              JOIN me_expedientes ed ON ed.id = ld.id_expediente
              LEFT JOIN pago_pagos pg ON pg.id = ap.id_pago
              LEFT JOIN c_pasivo_liquidacion lc ON lc.id = ap.id_liq_credito
              LEFT JOIN me_expedientes ec ON ec.id = lc.id_expediente
              LEFT JOIN f_comprobantes_arca cd ON cd.id = ec.id_comprobante
              {tipo_cd} {usuario}
             WHERE ap.id_liq_debito = %s AND ed.id_proveedor = %s
            UNION ALL
            SELECT ap.fecha, ap.importe_aplicado, 'entregada', 'factura', NULL, NULL, NULL,
                   ed.id, ed.nro_expediente, ed.estado, cd.numero_completo, tcd.descripcion, ap.origen, ap.id, u.nombre
              FROM c_pasivo_aplicacion ap
              JOIN c_pasivo_liquidacion lc ON lc.id = ap.id_liq_credito
              JOIN me_expedientes ec ON ec.id = lc.id_expediente
              JOIN c_pasivo_liquidacion ld ON ld.id = ap.id_liq_debito
              JOIN me_expedientes ed ON ed.id = ld.id_expediente
              LEFT JOIN f_comprobantes_arca cd ON cd.id = ed.id_comprobante
              {tipo_cd} {usuario}
             WHERE ap.id_liq_credito = %s AND ec.id_proveedor = %s"""
        params = [id_liquidacion, id_proveedor] * 3
    elif id_pago:
        sql = f"""
            SELECT p.fecha_pago AS fecha, l.importe_liquidado AS importe, 'directo' AS forma, 'factura' AS clase,
                   NULL AS id_pago, NULL AS id_orden, NULL AS nro_pago, e.id AS id_expediente,
                   e.nro_expediente AS nro_expediente, e.estado AS estado_expediente,
                   cd.numero_completo AS comprobante, tcd.descripcion AS tipo_cbte,
                   NULL AS origen, NULL AS id_aplicacion, NULL AS usuario
              FROM c_pasivo_liquidacion l
              JOIN me_expedientes e ON e.id = l.id_expediente
              JOIN pago_pagos p ON p.id = l.id_pago
              LEFT JOIN f_comprobantes_arca cd ON cd.id = e.id_comprobante
              {tipo_cd}
             WHERE l.id_pago = %s AND e.id_proveedor = %s
            UNION ALL
            SELECT ap.fecha, ap.importe_aplicado, 'entregada', 'factura', NULL, NULL, NULL,
                   ed.id, ed.nro_expediente, ed.estado, cd.numero_completo, tcd.descripcion, ap.origen, ap.id, u.nombre
              FROM c_pasivo_aplicacion ap
              JOIN c_pasivo_liquidacion ld ON ld.id = ap.id_liq_debito
              JOIN me_expedientes ed ON ed.id = ld.id_expediente
              LEFT JOIN f_comprobantes_arca cd ON cd.id = ed.id_comprobante
              {tipo_cd} {usuario}
             WHERE ap.id_pago = %s AND ed.id_proveedor = %s"""
        params = [id_pago, id_proveedor] * 2
    else:
        return []
    cur.execute(f"SELECT * FROM ({sql}) x ORDER BY fecha, id_aplicacion", params)
    return list(cur.fetchall())


def _aplicacion_json(f) -> dict:
    if f["clase"] == "pago":
        que = f"Pago {f['nro_pago'] or f['id_pago']}"
        href = url_for("pagos.orden", id_orden=f["id_orden"]) if f["id_orden"] and puede(
            url_for("pagos.ordenes")) else None
    else:
        que = " ".join(str(x) for x in (f["tipo_cbte"], f["comprobante"]) if x) or "Comprobante sin número"
        if f["nro_expediente"]:
            que += f" — {f['nro_expediente']}"
        href = url_for("mesa.detalle", exp_id=f["id_expediente"]) if f["id_expediente"] and puede(
            url_for("mesa.bandeja")) else None
    forma = {"directo": "Pago directo de la orden", "recibida": "Aplicado a este comprobante",
             "entregada": "Aplicado a ese comprobante"}[f["forma"]]
    if f["origen"]:
        forma += f" · {ORIGENES_APLICACION.get(f['origen'], f['origen'])}"
    if f["usuario"]:
        forma += f" · {f['usuario']}"
    return {"fecha": f["fecha"].strftime("%d/%m/%Y") if f["fecha"] else "", "que": que, "href": href,
            "forma": forma, "anulado": (f["estado_expediente"] or "") == "anulado",
            "importe": round(float(f["importe"] or 0), 2)}


@cc_prov_bp.route("/<int:id_proveedor>/aplicaciones_de")
def aplicaciones_de(id_proveedor):
    """JSON con las aplicaciones de un renglón: `?liq=` o `?pago=`."""
    salida = _guardia(URL_CC, URL_APLICACIONES, api=True)
    if salida:
        return salida
    liq, pago = request.args.get("liq", type=int), request.args.get("pago", type=int)
    with get_connection() as conn:
        with conn.cursor() as cur:
            filas = [_aplicacion_json(f) for f in _aplicaciones_de(cur, id_proveedor, liq, pago)]
    return jsonify({"filas": filas, "total": round(sum(f["importe"] for f in filas), 2)})


# ─────────────────────────────────────────────────────────────────────────────
# 3. Aplicación de comprobantes
# ─────────────────────────────────────────────────────────────────────────────

def _pagos_con_saldo(cur, id_proveedor) -> list[dict]:
    """Pagos y anticipos del proveedor con saldo a cuenta: lo pagado menos lo
    que cubrió por vínculo directo y por aplicaciones. El pago es del
    proveedor por su ORDEN (expedientes o detalle del anticipo), no por la
    liquidación: uno sin vincular igual es plata entregada."""
    cur.execute(f"""
        SELECT p.id, p.nro_pago, p.nro_origen, p.fecha_pago, p.importe_total, p.id_orden, o.clase,
               {sql_nro_orden_visible('o')} AS nro_orden_vis,
               COALESCE(
                 (SELECT MIN(ad.id_rubro_pasivo) FROM pago_ordenes_anticipo_det ad
                   WHERE ad.id_orden = p.id_orden AND ad.id_rubro_pasivo IS NOT NULL),
                 (SELECT IF(COUNT(DISTINCT l3.id_rubro_pasivo) = 1, MIN(l3.id_rubro_pasivo), NULL)
                    FROM pago_ordenes_detalle od3 JOIN c_pasivo_liquidacion l3 ON l3.id = od3.id_liquidacion
                   WHERE od3.id_orden = p.id_orden),
                 (SELECT IF(COUNT(DISTINCT l4.id_rubro_pasivo) = 1, MIN(l4.id_rubro_pasivo), NULL)
                    FROM c_pasivo_aplicacion a4 JOIN c_pasivo_liquidacion l4 ON l4.id = a4.id_liq_debito
                   WHERE a4.id_pago = p.id)) AS id_rubro_pasivo,
               COALESCE((SELECT SUM(l2.importe_liquidado
                                    - COALESCE((SELECT SUM(a2.importe_aplicado) FROM c_pasivo_aplicacion a2
                                                 WHERE a2.id_liq_debito = l2.id), 0))
                           FROM c_pasivo_liquidacion l2 JOIN me_expedientes e2 ON e2.id = l2.id_expediente
                          WHERE l2.id_pago = p.id AND e2.estado <> 'anulado'), 0)
               + COALESCE((SELECT SUM(a3.importe_aplicado) FROM c_pasivo_aplicacion a3
                            WHERE a3.id_pago = p.id), 0) AS consumido
          FROM pago_pagos p
          JOIN pago_ordenes o ON o.id = p.id_orden
          JOIN ({SQL_ORDEN_PROVEEDOR}) op ON op.id_orden = p.id_orden
         WHERE p.estado <> 'anulado' AND op.id_proveedor = %s
         ORDER BY p.fecha_pago, p.id""", (id_proveedor,))
    pagos = []
    for r in cur.fetchall():
        saldo = round(float(r["importe_total"] or 0) - float(r["consumido"] or 0), 2)
        if saldo > 0.01:
            r.update(saldo=saldo, es_pago=True, referencia=f"Pago {nro_visible(r)}",
                     descripcion="Anticipo" if r["clase"] == "anticipo" else "Pago a cuenta",
                     fecha=r["fecha_pago"], aplicado=round(float(r["consumido"] or 0), 2))
            pagos.append(r)
    return pagos


def _comprobantes_con_saldo(cur, id_proveedor) -> tuple[list[dict], list[dict]]:
    """(débitos, créditos) pendientes de aplicar.

    Débito = liquidación cerrada en positivo, menos su pago directo y lo ya
    aplicado. Lo que está en una orden de pago viva (sin pagar) está
    reservado: si se le aplica una nota de crédito y después se paga la orden,
    se paga de más; por eso se aplica, como máximo, lo que no está en la orden.
    Crédito = liquidación en negativo menos lo ya aplicado, y los pagos con
    saldo a cuenta (para el que aplica son lo mismo: algo que resta). El signo
    elige la columna; si el TIPO dice otra cosa se marca `signo_dudoso` (una
    nota de crédito cargada en positivo cae del lado de las facturas)."""
    cur.execute(f"""
        SELECT l.id, l.fecha_cierre, l.importe_liquidado, l.id_pago, l.id_rubro_pasivo, r.nombre AS rubro,
               e.id AS id_expediente, e.nro_expediente, e.estado AS estado_expediente,
               c.id AS id_comprobante, c.numero_completo, c.tipo_comprobante, c.fecha_emision, c.ruta_local,
               c.constatacion_resultado, c.leido_automatico, c.verificado_visual,
               tc.descripcion AS tipo_desc, {sql_es_credito()} AS es_credito,
               COALESCE((SELECT SUM(a.importe_aplicado) FROM c_pasivo_aplicacion a
                          WHERE a.id_liq_debito = l.id), 0) AS aplicado_debito,
               COALESCE((SELECT SUM(a.importe_aplicado) FROM c_pasivo_aplicacion a
                          WHERE a.id_liq_credito = l.id), 0) AS aplicado_credito,
               COALESCE((SELECT SUM(d2.importe) FROM pago_ordenes_detalle d2
                           JOIN pago_ordenes o2 ON o2.id = d2.id_orden
                          WHERE d2.id_liquidacion = l.id AND {pd.SQL_ORDEN_RESERVA}), 0) AS reservado,
               (SELECT GROUP_CONCAT(DISTINCT {sql_nro_orden_visible('o2')} SEPARATOR ', ')
                  FROM pago_ordenes_detalle d2 JOIN pago_ordenes o2 ON o2.id = d2.id_orden
                 WHERE d2.id_liquidacion = l.id AND {pd.SQL_ORDEN_RESERVA}) AS ordenes
          FROM c_pasivo_liquidacion l
          JOIN me_expedientes e ON e.id = l.id_expediente
          LEFT JOIN f_comprobantes_arca c ON c.id = e.id_comprobante
          LEFT JOIN arca_tipo_comprobante tc ON tc.codigo = LPAD(c.tipo_comprobante, 3, '0')
          LEFT JOIN c_rubros_de_pasivo r ON r.id = l.id_rubro_pasivo
         WHERE e.id_proveedor = %s AND e.estado NOT IN ('anulado', 'reintegro')
           AND l.fecha_cierre IS NOT NULL AND ABS(l.importe_liquidado) > 0.01
         ORDER BY COALESCE(c.fecha_emision, l.fecha_cierre), l.id""", (id_proveedor,))
    debitos, creditos = [], []
    for r in cur.fetchall():
        imp = float(r["importe_liquidado"])
        r.update(referencia=r["numero_completo"] or r["nro_expediente"], descripcion=r["tipo_desc"] or "Comprobante",
                 es_pago=False, fecha=r["fecha_emision"] or r["fecha_cierre"])
        if r["tipo_comprobante"]:
            if r["es_credito"] and imp > 0:
                r["signo_dudoso"] = "Es una nota de crédito y el importe está en positivo"
            elif not r["es_credito"] and imp < 0:
                r["signo_dudoso"] = "Es un débito y el importe está en negativo"
        if imp > 0:
            r["aplicado"] = round(float(r["aplicado_debito"]), 2)
            r["saldo"] = round(imp - (imp if r["id_pago"] else 0) - r["aplicado"], 2)
            r["reservado"] = round(float(r["reservado"] or 0), 2)
            r["disponible"] = round(max(r["saldo"] - r["reservado"], 0), 2)
            if r["saldo"] > 0.01:
                debitos.append(r)
        else:
            r["aplicado"] = round(float(r["aplicado_credito"]), 2)
            r["saldo"] = round(abs(imp) - r["aplicado"], 2)
            r["disponible"] = r["saldo"]
            if r["saldo"] > 0.01:
                creditos.append(r)
    for p in _pagos_con_saldo(cur, id_proveedor):
        p["disponible"] = p["saldo"]
        creditos.append(p)
    nombres = {}
    ids = {c["id_rubro_pasivo"] for c in creditos if c.get("es_pago") and c["id_rubro_pasivo"]}
    if ids:
        cur.execute(f"SELECT id, nombre FROM c_rubros_de_pasivo WHERE id IN ({','.join(['%s'] * len(ids))})",
                    sorted(ids))
        nombres = {r["id"]: r["nombre"] for r in cur.fetchall()}
    for c in creditos:
        if c.get("es_pago"):
            c["rubro"] = nombres.get(c["id_rubro_pasivo"])
    return debitos, creditos


def _sugeridos(cur) -> list[dict]:
    """Los proveedores donde hay algo que aplicar: saldo de los DOS signos, un
    comprobante abierto y algo con qué cancelarlo. Las aplicaciones se agrupan
    una vez arriba: con subconsultas por pago no terminaba nunca."""
    cur.execute(f"""
        WITH apl_deb AS (SELECT id_liq_debito AS id, SUM(importe_aplicado) AS imp
                           FROM c_pasivo_aplicacion GROUP BY id_liq_debito),
             apl_cre AS (SELECT id_liq_credito AS id, SUM(importe_aplicado) AS imp
                           FROM c_pasivo_aplicacion WHERE id_liq_credito IS NOT NULL GROUP BY id_liq_credito),
             apl_pago AS (SELECT id_pago AS id, SUM(importe_aplicado) AS imp
                            FROM c_pasivo_aplicacion WHERE id_pago IS NOT NULL GROUP BY id_pago),
             cons_dir AS (SELECT l.id_pago AS id, SUM(l.importe_liquidado - COALESCE(ad.imp, 0)) AS imp
                            FROM c_pasivo_liquidacion l
                            JOIN me_expedientes e ON e.id = l.id_expediente AND e.estado <> 'anulado'
                            LEFT JOIN apl_deb ad ON ad.id = l.id
                           WHERE l.id_pago IS NOT NULL GROUP BY l.id_pago),
             orden_prov AS ({SQL_ORDEN_PROVEEDOR}),
             deb AS (SELECT e.id_proveedor, COUNT(*) AS n, SUM(l.importe_liquidado - COALESCE(ad.imp, 0)) AS imp
                       FROM c_pasivo_liquidacion l
                       JOIN me_expedientes e ON e.id = l.id_expediente
                       LEFT JOIN apl_deb ad ON ad.id = l.id
                      WHERE l.importe_liquidado > 0.01 AND l.id_pago IS NULL AND l.fecha_cierre IS NOT NULL
                        AND e.estado NOT IN ('anulado', 'reintegro')
                        AND l.importe_liquidado - COALESCE(ad.imp, 0) > 0.01
                      GROUP BY e.id_proveedor),
             cre AS (SELECT id_proveedor, SUM(n) AS n, SUM(imp) AS imp FROM (
                       SELECT e.id_proveedor, COUNT(*) AS n, SUM(ABS(l.importe_liquidado) - COALESCE(ac.imp, 0)) AS imp
                         FROM c_pasivo_liquidacion l
                         JOIN me_expedientes e ON e.id = l.id_expediente
                         LEFT JOIN apl_cre ac ON ac.id = l.id
                        WHERE l.importe_liquidado < -0.01 AND l.fecha_cierre IS NOT NULL
                          AND e.estado NOT IN ('anulado', 'reintegro')
                          AND ABS(l.importe_liquidado) - COALESCE(ac.imp, 0) > 0.01
                        GROUP BY e.id_proveedor
                       UNION ALL
                       SELECT op.id_proveedor, COUNT(*),
                              SUM(p.importe_total - COALESCE(cd.imp, 0) - COALESCE(ap.imp, 0))
                         FROM pago_pagos p
                         JOIN orden_prov op ON op.id_orden = p.id_orden
                         LEFT JOIN cons_dir cd ON cd.id = p.id
                         LEFT JOIN apl_pago ap ON ap.id = p.id
                        WHERE p.estado <> 'anulado'
                          AND p.importe_total - COALESCE(cd.imp, 0) - COALESCE(ap.imp, 0) > 0.01
                        GROUP BY op.id_proveedor) x
                      GROUP BY id_proveedor)
        SELECT d.id_proveedor, p.cuit, p.razon_social, p.nombre_fantasia,
               d.n AS debitos, d.imp AS debito_pendiente, c.n AS creditos, c.imp AS credito_pendiente,
               LEAST(d.imp, c.imp) AS aplicable
          FROM deb d
          JOIN cre c ON c.id_proveedor = d.id_proveedor
          JOIN c_proveedores p ON p.id = d.id_proveedor
         ORDER BY aplicable DESC""")
    return list(cur.fetchall())


def _consultar_aplicadas(cur, id_proveedor) -> list[dict]:
    """Todas las aplicaciones del proveedor (la grilla filtra y exporta). El
    proveedor es el de la FACTURA; el estado del expediente no filtra: una
    factura anulada que se quedó con un pago aplicado es justo una de las que
    hay que desaplicar."""
    cur.execute(f"""
        SELECT ap.id, ap.importe_aplicado, ap.fecha, ap.origen, ap.observaciones, ap.id_pago, ap.id_liq_credito,
               ed.id AS id_exp_debito, ed.nro_expediente AS exp_debito, ed.estado AS estado_debito,
               cd.numero_completo AS comp_debito, tcd.descripcion AS tipo_debito,
               ec.id AS id_exp_credito, ec.nro_expediente AS exp_credito,
               cc.numero_completo AS comp_credito, tcc.descripcion AS tipo_credito,
               {sql_nro_visible('pg')} AS nro_pago_vis, pg.id_orden, pg.fecha_pago, o.clase AS clase_orden,
               u.nombre AS usuario
          FROM c_pasivo_aplicacion ap
          JOIN c_pasivo_liquidacion ld ON ld.id = ap.id_liq_debito
          JOIN me_expedientes ed ON ed.id = ld.id_expediente
          LEFT JOIN f_comprobantes_arca cd ON cd.id = ed.id_comprobante
          LEFT JOIN arca_tipo_comprobante tcd ON tcd.codigo = LPAD(cd.tipo_comprobante, 3, '0')
          LEFT JOIN c_pasivo_liquidacion lc ON lc.id = ap.id_liq_credito
          LEFT JOIN me_expedientes ec ON ec.id = lc.id_expediente
          LEFT JOIN f_comprobantes_arca cc ON cc.id = ec.id_comprobante
          LEFT JOIN arca_tipo_comprobante tcc ON tcc.codigo = LPAD(cc.tipo_comprobante, 3, '0')
          LEFT JOIN pago_pagos pg ON pg.id = ap.id_pago
          LEFT JOIN pago_ordenes o ON o.id = pg.id_orden
          LEFT JOIN s_usuarios u ON u.id = ap.id_usuario
         WHERE ed.id_proveedor = %s
         ORDER BY ap.fecha DESC, ap.id DESC""", (id_proveedor,))
    filas = list(cur.fetchall())
    for r in filas:
        r["es_pago"] = r["id_pago"] is not None
        r["origen_txt"] = ORIGENES_APLICACION.get(r["origen"], r["origen"])
        if r["es_pago"]:
            r["credito_txt"] = f"Pago {r['nro_pago_vis'] or ''}".strip()
        else:
            r["credito_txt"] = " ".join(str(x) for x in (r["tipo_credito"] or "Nota de crédito",
                                                         r["comp_credito"] or r["exp_credito"]) if x)
        r["debito_txt"] = " ".join(str(x) for x in (r["tipo_debito"] or "Comprobante",
                                                    r["comp_debito"] or r["exp_debito"]) if x)
    return filas


def recalcular_estado(cur, ids_liquidacion) -> list[dict]:
    """Deja cada expediente como dicen sus aplicaciones: «pagado» si el
    comprobante quedó cancelado entero, «liquidado» si le queda saldo. La
    misma regla que la emisión del pago (pagos_datos.ejecutar_pago) y que
    importar_aeda_cc_proveedores.py; el comprobante sigue al expediente. Solo
    pasa de uno a otro de esos dos estados: un anulado o un reintegro no se
    tocan. Devuelve los cambios."""
    ids = sorted({int(i) for i in ids_liquidacion if i})
    if not ids:
        return []
    cur.execute(f"""
        SELECT l.id, l.importe_liquidado, l.id_pago AS id_pago_liq, e.id AS id_expediente, e.estado,
               e.id_pago, e.id_comprobante, e.nro_expediente,
               COALESCE((SELECT SUM(a.importe_aplicado) FROM c_pasivo_aplicacion a
                          WHERE a.id_liq_debito = l.id), 0) AS recibido,
               COALESCE((SELECT SUM(a.importe_aplicado) FROM c_pasivo_aplicacion a
                          WHERE a.id_liq_credito = l.id), 0) AS entregado,
               (SELECT a.id_pago FROM c_pasivo_aplicacion a
                 WHERE a.id_liq_debito = l.id AND a.id_pago IS NOT NULL
                 ORDER BY a.fecha DESC, a.id DESC LIMIT 1) AS ultimo_pago
          FROM c_pasivo_liquidacion l JOIN me_expedientes e ON e.id = l.id_expediente
         WHERE l.id IN ({','.join(['%s'] * len(ids))}) AND l.fecha_cierre IS NOT NULL
           AND e.estado IN ('liquidado', 'pagado')
           FOR UPDATE""", ids)
    cambios = []
    for r in cur.fetchall():
        imp = float(r["importe_liquidado"] or 0)
        if imp >= 0:
            saldo = imp - (imp if r["id_pago_liq"] else 0) - float(r["recibido"])
        else:
            saldo = abs(imp) - float(r["entregado"])
        estado = "pagado" if saldo <= 0.01 else "liquidado"
        id_pago = (r["id_pago_liq"] or r["ultimo_pago"]) if estado == "pagado" else None
        if estado == r["estado"] and id_pago == r["id_pago"]:
            continue
        cur.execute("UPDATE me_expedientes SET estado = %s, id_pago = %s WHERE id = %s",
                    (estado, id_pago, r["id_expediente"]))
        if r["id_comprobante"]:
            cur.execute("UPDATE f_comprobantes_arca SET estado = %s WHERE id = %s AND estado IN ('liquidado', 'pagado')",
                        (estado, r["id_comprobante"]))
        cambios.append({"nro_expediente": r["nro_expediente"], "antes": r["estado"], "ahora": estado})
    return cambios


def _desaplicar(cur, id_aplic, id_proveedor, importe, motivo, id_usuario) -> dict:
    """Desaplica una aplicación, entera (importe None) o en parte, dentro de la
    transacción de quien llama: el rastro, el borrado y el estado de los
    expedientes van juntos o no va ninguno. ValueError con el texto para el
    usuario si no se puede; todo se valida antes de la primera escritura."""
    motivo = (motivo or "").strip()[:255]
    if not motivo:
        raise ValueError("Hace falta un motivo para desaplicar.")
    cur.execute(f"""
        SELECT ap.*, ed.id_proveedor,
               COALESCE(cd.numero_completo, ed.nro_expediente) AS ref_debito,
               COALESCE(cc.numero_completo, ec.nro_expediente, CONCAT('Pago ', {sql_nro_visible('pg')})) AS ref_credito
          FROM c_pasivo_aplicacion ap
          JOIN c_pasivo_liquidacion ld ON ld.id = ap.id_liq_debito
          JOIN me_expedientes ed ON ed.id = ld.id_expediente
          LEFT JOIN f_comprobantes_arca cd ON cd.id = ed.id_comprobante
          LEFT JOIN c_pasivo_liquidacion lc ON lc.id = ap.id_liq_credito
          LEFT JOIN me_expedientes ec ON ec.id = lc.id_expediente
          LEFT JOIN f_comprobantes_arca cc ON cc.id = ec.id_comprobante
          LEFT JOIN pago_pagos pg ON pg.id = ap.id_pago
         WHERE ap.id = %s
           FOR UPDATE""", (id_aplic,))
    ap = cur.fetchone()
    if not ap:
        raise ValueError("La aplicación ya no existe: puede que otro usuario la haya desaplicado recién.")
    if id_proveedor and ap["id_proveedor"] != id_proveedor:
        raise ValueError("La aplicación no es de este proveedor.")
    # La regla de anular: un período contable cerrado no se toca. Va la fecha
    # de la aplicación, que es la que corta el saldo por comprobante.
    fuera = anulaciones._fuera_de_periodo(cur, ap["fecha"])
    if fuera:
        raise ValueError(f"No se puede desaplicar porque {fuera}.")
    aplicado = round(float(ap["importe_aplicado"]), 2)
    importe = aplicado if importe is None else round(float(importe), 2)
    if importe <= 0:
        raise ValueError("El importe a desaplicar tiene que ser mayor que cero.")
    if importe > aplicado + 0.005:
        raise ValueError(f"No se puede desaplicar {_pesos(importe)}: la aplicación es de {_pesos(aplicado)}.")
    total = importe >= aplicado - 0.005

    cur.execute("""INSERT INTO c_pasivo_aplicacion_baja
                     (id_aplicacion, id_liq_credito, id_pago, id_liq_debito, importe_aplicado, importe_desaplicado,
                      total, fecha_aplicacion, origen, observaciones, id_usuario_aplicacion, motivo, id_usuario)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (ap["id"], ap["id_liq_credito"], ap["id_pago"], ap["id_liq_debito"], aplicado,
                 aplicado if total else importe, 1 if total else 0, ap["fecha"], ap["origen"],
                 ap["observaciones"], ap["id_usuario"], motivo, id_usuario))
    if total:
        cur.execute("DELETE FROM c_pasivo_aplicacion WHERE id = %s", (id_aplic,))
    else:
        cur.execute("UPDATE c_pasivo_aplicacion SET importe_aplicado = importe_aplicado - %s WHERE id = %s",
                    (importe, id_aplic))
    # La factura (y la nota de crédito) vuelven a tener saldo: si estaban
    # «pagado», vuelven a «liquidado», que es lo que las ofrece otra vez para
    # una orden de pago. En gestion_adm la parcial no tocaba el estado y la
    # factura quedaba con saldo y sin pantalla desde donde pagarla.
    cambios = recalcular_estado(cur, [ap["id_liq_debito"], ap["id_liq_credito"]])
    return {"importe": importe, "total": total, "es_pago": ap["id_pago"] is not None, "origen": ap["origen"],
            "ref_debito": ap["ref_debito"], "ref_credito": ap["ref_credito"], "cambios": cambios}


@cc_prov_bp.route("/aplicaciones")
def aplicaciones():
    salida = _guardia(URL_APLICACIONES)
    if salida:
        return salida
    id_proveedor = request.args.get("id_proveedor", type=int)
    ctx = {"proveedor": None, "sugeridos": [], "debitos": [], "creditos": [], "aplicadas": []}
    with get_connection() as conn:
        with conn.cursor() as cur:
            if id_proveedor:
                ctx["proveedor"] = _proveedor(cur, id_proveedor)
                if not ctx["proveedor"]:
                    flash("!El proveedor no existe.")
                    return redirect(url_for("cc_prov.aplicaciones"))
                ctx["debitos"], ctx["creditos"] = _comprobantes_con_saldo(cur, id_proveedor)
                ctx["aplicadas"] = _consultar_aplicadas(cur, id_proveedor)
            else:
                ctx["sugeridos"] = _sugeridos(cur)
                # Para desaplicar hace falta llegar a un proveedor que no tiene
                # nada pendiente (la nota de crédito aplicada entera a la factura
                # equivocada lo deja sin crédito): todos los que tienen alguna
                # aplicación, en una segunda grilla.
                ya = {s["id_proveedor"] for s in ctx["sugeridos"]}
                cur.execute("""SELECT p.id, p.cuit, p.razon_social, p.nombre_fantasia, COUNT(*) AS aplicaciones,
                                      SUM(ap.origen = 'manual') AS manuales, MAX(ap.fecha) AS ultima
                                 FROM c_pasivo_aplicacion ap
                                 JOIN c_pasivo_liquidacion ld ON ld.id = ap.id_liq_debito
                                 JOIN me_expedientes ed ON ed.id = ld.id_expediente
                                 JOIN c_proveedores p ON p.id = ed.id_proveedor
                                GROUP BY p.id, p.cuit, p.razon_social, p.nombre_fantasia
                                ORDER BY p.razon_social""")
                ctx["otros"] = [o for o in cur.fetchall() if o["id"] not in ya]
    rubros = sorted({x["rubro"] for x in ctx["debitos"] + ctx["creditos"] if x.get("rubro")})
    return render_template("proveedores/cc_aplicaciones.html", origenes=ORIGENES_APLICACION, rubros=rubros,
                           puede_cc=puede(URL_CC), **ctx)


@cc_prov_bp.route("/aplicaciones/aplicar", methods=["POST"])
def aplicar():
    """Aplica un crédito (nota de crédito o pago con saldo) contra un débito."""
    salida = _guardia(URL_APLICACIONES)
    if salida:
        return salida
    id_proveedor = request.form.get("id_proveedor", type=int)
    id_credito = request.form.get("id_credito", type=int)
    id_debito = request.form.get("id_debito", type=int)
    credito_es_pago = request.form.get("credito_es_pago") == "1"
    importe = pd.leer_importe(request.form.get("importe"))
    observ = (request.form.get("observaciones") or "").strip()[:255] or None
    destino = url_for("cc_prov.aplicaciones", id_proveedor=id_proveedor)
    if not (id_proveedor and id_credito and id_debito):
        flash("!Elegí un débito y un crédito.")
        return redirect(destino)
    if importe is None or importe <= 0:
        flash("!El importe a aplicar tiene que ser mayor que cero.")
        return redirect(destino)
    usuario = usuario_actual() or {}
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            fuera = anulaciones._fuera_de_periodo(cur, datetime.date.today())
            if fuera:
                raise ValueError(f"No se puede aplicar porque {fuera}.")
            # Se bloquean las dos puntas y se revalida contra la base, no contra
            # lo que vino del formulario: entre que se cargó la pantalla y se
            # apretó Aplicar, otro usuario pudo consumir el saldo.
            cur.execute("SELECT id FROM c_pasivo_liquidacion WHERE id IN (%s, %s) FOR UPDATE",
                        (id_debito, id_credito if not credito_es_pago else id_debito))
            if credito_es_pago:
                cur.execute("SELECT id FROM pago_pagos WHERE id = %s FOR UPDATE", (id_credito,))
            debitos, creditos = _comprobantes_con_saldo(cur, id_proveedor)
            deb = next((d for d in debitos if d["id"] == id_debito), None)
            # Un pago y una liquidación pueden tener el mismo id.
            cre = next((c for c in creditos if c["id"] == id_credito and c["es_pago"] == credito_es_pago), None)
            if not deb:
                raise ValueError("El débito elegido ya no tiene saldo pendiente.")
            if not cre:
                raise ValueError("El crédito elegido ya no tiene saldo disponible.")
            if not credito_es_pago and cre["id"] == deb["id"]:
                raise ValueError("Un comprobante no se aplica contra sí mismo.")
            # El rubro de pasivo separa cuentas que no se compensan entre sí.
            # Sin rubro de un lado no se bloquea: no hay con qué decidir.
            if deb["id_rubro_pasivo"] and cre["id_rubro_pasivo"] and deb["id_rubro_pasivo"] != cre["id_rubro_pasivo"]:
                raise ValueError(f"El crédito es de «{cre['rubro']}» y el débito de «{deb['rubro']}»: solo se "
                                 "compensan comprobantes del mismo rubro de pasivo.")
            tope = min(deb["disponible"], cre["disponible"])
            if deb["disponible"] <= 0.01:
                raise ValueError(f"Lo que le queda a {deb['referencia']} está en la orden de pago {deb['ordenes']}, "
                                 "sin pagar. Para aplicarle el crédito, anulá la orden (o pagala y aplicá lo que sobre).")
            if importe > tope + 0.01:
                raise ValueError(f"No se puede aplicar {_pesos(importe)}: el máximo entre esos dos es {_pesos(tope)}"
                                 + (f" (de la factura, {_pesos(deb['reservado'])} están en la orden {deb['ordenes']})"
                                    if deb["reservado"] > 0.01 else "") + ".")
            columna = "id_pago" if credito_es_pago else "id_liq_credito"
            cur.execute(f"""INSERT INTO c_pasivo_aplicacion
                              ({columna}, id_liq_debito, importe_aplicado, fecha, origen, observaciones, id_usuario)
                            VALUES (%s, %s, %s, CURDATE(), 'manual', %s, %s)
                            ON DUPLICATE KEY UPDATE importe_aplicado = importe_aplicado + VALUES(importe_aplicado),
                                                    observaciones = COALESCE(VALUES(observaciones), observaciones)""",
                        (id_credito, id_debito, importe, observ, usuario.get("id")))
            cambios = recalcular_estado(cur, [id_debito] + ([] if credito_es_pago else [id_credito]))
        conn.commit()
    except ValueError as e:
        conn.rollback()
        flash(f"!{e}")
        return redirect(destino)
    except Exception:
        conn.rollback()
        log.exception("aplicar %s → %s", id_credito, id_debito)
        raise
    finally:
        conn.close()
    nombre_cre = cre["referencia"] if cre["es_pago"] else f"{cre['descripcion']} {cre['referencia']}"
    msg = f"Aplicado {_pesos(importe)}: {nombre_cre} → {deb['descripcion']} {deb['referencia']}."
    pagados = [c["nro_expediente"] for c in cambios if c["ahora"] == "pagado"]
    if pagados:
        msg += f" Quedó cancelado: {', '.join(pagados)}."
    flash(msg)
    return redirect(destino)


@cc_prov_bp.route("/aplicaciones/<int:id_aplic>/deshacer", methods=["POST"])
def deshacer(id_aplic):
    """Desaplica una nota de crédito o un pago, entero o en parte. Vuelve a la
    pantalla de la que vino (Aplicación de comprobantes o el estado de cuenta
    por aplicación), con sus filtros."""
    salida = _guardia(URL_APLICACIONES)
    if salida:
        return salida
    id_proveedor = request.form.get("id_proveedor", type=int)
    volver = (request.form.get("volver") or "").strip()
    # Solo rutas internas: una URL completa sería una redirección abierta.
    if not (volver.startswith("/") and not volver.startswith("//") and "\\" not in volver):
        volver = url_for("cc_prov.aplicaciones", id_proveedor=id_proveedor)
    txt = (request.form.get("importe") or "").strip()
    importe = pd.leer_importe(txt) if txt else None
    if txt and importe is None:
        flash(f"!Importe inválido: «{txt}».")
        return redirect(volver)
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            r = _desaplicar(cur, id_aplic, id_proveedor, importe, request.form.get("motivo"),
                            (usuario_actual() or {}).get("id"))
        conn.commit()
    except ValueError as e:
        conn.rollback()
        flash(f"!{e}")
        return redirect(volver)
    except Exception:
        conn.rollback()
        log.exception("desaplicar %s", id_aplic)
        raise
    finally:
        conn.close()
    credito = r["ref_credito"] or ("el pago" if r["es_pago"] else "la nota de crédito")
    msg = (f"Desaplicado {_pesos(r['importe'])} de {credito} → {r['ref_debito']}"
           f"{'' if r['total'] else ' (en parte: el resto sigue aplicado)'}. ")
    msg += ("El pago vuelve a quedar como saldo a cuenta." if r["es_pago"]
            else "La nota de crédito vuelve a quedar disponible.")
    if any(c["ahora"] == "liquidado" for c in r["cambios"]):
        msg += (" La factura volvió a «liquidado» y se ofrece de nuevo para una orden de pago: aplicale el saldo "
                "a cuenta antes de pagarla otra vez.")
    if r["origen"] == "migracion":
        msg = ("!" + msg + " Era una aplicación de AEDA: si se vuelve a correr importar_aeda_cc_proveedores.py "
               "vuelve, porque AEDA manda. Corregila también allá.")
    flash(msg)
    return redirect(volver)
