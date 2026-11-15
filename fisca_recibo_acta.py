"""
fisca_recibo_acta.py — El recibo de fiscalización: cobra un acta, a las cuotas de su acuerdo de pago.

Pedido del 14/11/2026 (sql/fisca_recibos_talonarios_20261114.sql): «los de
fiscalización se emiten a un acta, como en OSEDA». En OSEDA el recibo de
fiscalización se imputa a las cuotas del acuerdo del acta (una cuota = pago
único): acá igual. Sale de dos lugares, con las mismas reglas (`emitir`):

    Emisión de Recibos   una acreditación del extracto que se emite como
                         «Fiscalización»: fecha, cuenta e importe del banco, y
                         queda conciliada si hay una conciliación abierta
    El acuerdo de pago   «Cobrar»: fecha y cuenta de fondos (banco o caja), como
                         la cobranza de acuerdos de gestion_adm

EL RECIBO
  Orden de ingreso de clase «fiscalizacion», con `id_acta` e `id_acuerdo`, del
  talonario de fiscalización (recibos_talonario.py). Qué cuota paga y cuánto:
  `fisca_acuerdo_imputacion`; lo pagado de una cuota es lo de sus recibos no
  anulados. Una imputación no pasa el saldo de la cuota y todas suman el
  importe del recibo. Un acuerdo anulado o cancelado no se cobra; uno
  judicializado sí (como OSEDA).

CAPITAL E INTERÉS (`partir`)
  El acuerdo financia el total del acta (deuda + intereses) más el interés de
  financiación. Cada recibo se parte en la misma proporción que guardan lo que
  falta del capital y lo que falta del acuerdo:
      capital = importe × capital que falta / lo que falta pagar del acuerdo
  y el que termina de pagar el acuerdo se lleva todo el capital que queda. El
  capital que falta es el saldo de hoy de las cuotas sindicales del acta (lo
  liquidado vigente menos lo aplicado: si el empleador pagó un período por su
  cuenta, ese ya no se cobra dos veces).
  - Capital: un renglón por período del acta, del más viejo al más nuevo, hasta
    su saldo (motivo INGRESOS POR FISCALIZACION, con el período y el CUIT): se
    aplica a la cuota sindical de ese período (fisca_aplicaciones, origen
    «recibo») y la cuenta corriente del empleador baja.
  - Interés: un renglón con lo demás (motivo INTERESES POR FISCALIZACION): es el
    resarcitorio del acta y la financiación; no es cobro de cuota y no se aplica.
  Proporcional y no «primero el interés» (art. 903 CCyC): decidido así para que
  la cuenta corriente vaya bajando con cada cuota. A revisar con el contador.

EL ACUERDO (`recalcular_acuerdo`)
  Sin saldo en las cuotas pasa solo a «cancelado» (con el motivo MOTIVO_PAGADO);
  si se anula un recibo y vuelve a deber, vuelve a «vigente». Un acuerdo con
  recibos no se modifica (el cronograma tiene cobros encima).
"""

from __future__ import annotations

import datetime
from decimal import ROUND_HALF_UP, Decimal

import conciliacion
import fisca_aplicaciones as fa
import movimientos_fondos as mf
import recibos_talonario as RT
from numeracion import proximo_numero

CENT = Decimal("0.01")
MOTIVO_CAPITAL = "INGRESOS POR FISCALIZACION"
MOTIVO_INTERES = "INTERESES POR FISCALIZACION"
MOTIVO_PAGADO = "Pagado con los recibos de fiscalización"
ESTADOS_COBRABLES = ("vigente", "judicializado")
#: Cuentas desde las que se cobra a mano: banco y caja (la cartera pide los valores de terceros).
TIPOS_CUENTA_COBRO = ("B", "C")


class ErrorCobro(ValueError):
    """Lo que impide emitir: el texto va a la pantalla."""


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


def pesos(v) -> str:
    entero, _, dec = f"{float(v or 0):,.2f}".partition(".")
    return f"$ {entero.replace(',', '.')},{dec}"


def periodo_txt(p) -> str:
    p = str(p or "")
    return f"{p[:4]}-{p[4:]}" if len(p) == 6 else p


def id_motivo(cur, descripcion: str) -> int:
    cur.execute("SELECT id FROM c_motivos_de_ingreso WHERE UPPER(descripcion) = %s ORDER BY activo DESC, id LIMIT 1",
                (descripcion,))
    r = cur.fetchone()
    if not r:
        raise ErrorCobro(f"No existe el motivo de ingreso «{descripcion}»: correr {RT.SQL_ESQUEMA}.")
    return r["id"]


# ─────────────────────────────────────────────────────────────────────────────
# Lo que se debe
# ─────────────────────────────────────────────────────────────────────────────

SQL_PAGADO_CUOTA = """COALESCE((SELECT SUM(i.importe) FROM fisca_acuerdo_imputacion i
                                  JOIN ingreso_ordenes o ON o.id = i.id_orden AND o.estado <> 'anulado'
                                 WHERE i.id_cuota = c.id), 0)"""


def cuotas_de(cur, id_acuerdo: int) -> list[dict]:
    """El cronograma con lo pagado y el saldo de cada cuota."""
    cur.execute(f"""SELECT c.id, c.nro_cuota, c.vencimiento, c.importe, {SQL_PAGADO_CUOTA} AS pagado
                      FROM fisca_acuerdo_cuota c WHERE c.id_acuerdo = %s ORDER BY c.nro_cuota""", (id_acuerdo,))
    hoy = datetime.date.today()
    out = list(cur.fetchall())
    for c in out:
        c["importe"], c["pagado"] = _d(c["importe"]), _d(c["pagado"])
        c["saldo"] = max(c["importe"] - c["pagado"], Decimal("0"))
        c["estado"] = ("pagada" if c["saldo"] < CENT else "vencida" if c["vencimiento"] < hoy
                       else "parcial" if c["pagado"] > 0 else "pendiente")
    return out


def recibos_de(cur, id_acuerdo: int) -> list[dict]:
    """Los recibos del acuerdo (también los anulados), con lo que imputó cada uno."""
    cur.execute(f"""SELECT o.id AS id_orden, o.nro_orden, o.fecha, o.importe_total, o.estado, o.origen, o.motivo_anulacion,
                           {RT.sql_texto('o', 't')} AS nro_recibo, cf.nombre AS cuenta,
                           (SELECT GROUP_CONCAT(c.nro_cuota ORDER BY c.nro_cuota SEPARATOR ', ')
                              FROM fisca_acuerdo_imputacion i JOIN fisca_acuerdo_cuota c ON c.id = i.id_cuota
                             WHERE i.id_orden = o.id) AS cuotas
                      FROM ingreso_ordenes o
                      LEFT JOIN c_talonario t ON t.id = o.id_talonario
                      LEFT JOIN c_cuentas_de_fondos cf ON cf.id = o.id_cuenta
                     WHERE o.id_acuerdo = %s ORDER BY o.fecha, o.id""", (id_acuerdo,))
    return list(cur.fetchall())


def periodos_del_acta(cur, id_acta: int, cuit: str) -> list[dict]:
    """Los períodos del acta con el saldo de HOY de su cuota sindical (liquidación vigente)."""
    cur.execute(f"""SELECT ap.periodo, l.id AS id_liquidacion, l.importe, {fa.sql_aplicado_liq('l')} AS aplicado
                      FROM fisca_acta_periodo ap
                      LEFT JOIN fisca_liquidacion l ON l.cuit = %s AND l.periodo = ap.periodo AND l.estado = 'vigente'
                     WHERE ap.id_acta = %s ORDER BY ap.periodo""", (cuit, id_acta))
    out = []
    for f in cur.fetchall():
        saldo = (_d(f["importe"]) - _d(f["aplicado"])) if f["id_liquidacion"] else Decimal("0")
        out.append({"periodo": f["periodo"], "id_liquidacion": f["id_liquidacion"], "saldo": max(saldo, Decimal("0"))})
    return out


def estado_cobro(cur, x: dict) -> dict:
    """Lo que falta del acuerdo y del capital: lo que necesita `partir` y la pantalla."""
    cuotas = cuotas_de(cur, x["id"])
    periodos = periodos_del_acta(cur, x["id_acta"], x["cuit"])
    return {"cuotas": cuotas, "periodos": periodos,
            "falta_acuerdo": sum((c["saldo"] for c in cuotas), Decimal("0")),
            "pagado": sum((c["pagado"] for c in cuotas), Decimal("0")),
            "falta_capital": sum((p["saldo"] for p in periodos), Decimal("0"))}


def partir(importe: Decimal, falta_capital: Decimal, falta_acuerdo: Decimal) -> tuple[Decimal, Decimal]:
    """(capital, interés) de un pago. Ver el encabezado."""
    importe = _d(importe)
    if importe <= 0 or falta_capital <= 0:
        return Decimal("0.00"), importe
    if falta_acuerdo <= 0 or importe + CENT > falta_acuerdo:
        capital = falta_capital
    else:
        capital = (importe * falta_capital / falta_acuerdo).quantize(CENT, ROUND_HALF_UP)
    capital = min(capital, falta_capital, importe)
    return capital, importe - capital


def repartir_capital(capital: Decimal, periodos: list[dict]) -> list[tuple[str, Decimal]]:
    """El capital a los períodos del acta, del más viejo al más nuevo, hasta su saldo."""
    out, resto = [], _d(capital)
    for p in periodos:
        if resto < CENT:
            break
        if p["saldo"] < CENT:
            continue
        imp = min(resto, p["saldo"])
        out.append((p["periodo"], imp))
        resto -= imp
    return out


def sugerir(cuotas: list[dict], importe) -> list[tuple[int, Decimal]]:
    """El pago a las cuotas con saldo, de la primera a la última."""
    out, resto = [], _d(importe)
    for c in cuotas:
        if resto < CENT:
            break
        if c["saldo"] < CENT:
            continue
        imp = min(resto, c["saldo"])
        out.append((c["id"], imp))
        resto -= imp
    return out


def acuerdos_cobrables(cur, cuit: str) -> list[dict]:
    """Los acuerdos del CUIT que se pueden cobrar y deben algo (para el extracto)."""
    cur.execute("""SELECT x.id, x.nro_acuerdo, x.id_acta, x.cuit, x.razon_social, x.estado, x.monto_total,
                          x.cantidad_cuotas, a.nro_acta
                     FROM fisca_acuerdo x JOIN fisca_acta a ON a.id = x.id_acta
                    WHERE x.cuit = %s AND x.estado IN ('vigente', 'judicializado') AND a.estado <> 'anulada'
                    ORDER BY x.fecha_acuerdo, x.id""", (cuit,))
    out = []
    for x in cur.fetchall():
        x["falta"] = sum((c["saldo"] for c in cuotas_de(cur, x["id"])), Decimal("0"))
        if x["falta"] >= CENT:
            out.append(x)
    return out


def con_acuerdo(cur, cuits) -> set[str]:
    """Los CUIT con un acuerdo de pago cobrable (sus pagos no se emiten en lote como cuota)."""
    cuits = sorted({c for c in cuits if c})
    if not cuits:
        return set()
    cur.execute(f"""SELECT DISTINCT x.cuit FROM fisca_acuerdo x JOIN fisca_acta a ON a.id = x.id_acta
                     WHERE x.estado IN ('vigente', 'judicializado') AND a.estado <> 'anulada'
                       AND x.cuit IN ({','.join(['%s'] * len(cuits))})""", cuits)
    return {f["cuit"] for f in cur.fetchall()}


def tiene_recibos(cur, id_acuerdo: int) -> int:
    cur.execute("""SELECT COUNT(DISTINCT i.id_orden) AS n FROM fisca_acuerdo_imputacion i
                     JOIN ingreso_ordenes o ON o.id = i.id_orden AND o.estado <> 'anulado'
                    WHERE i.id_acuerdo = %s""", (id_acuerdo,))
    return int((cur.fetchone() or {}).get("n") or 0)


# ─────────────────────────────────────────────────────────────────────────────
# Emitir
# ─────────────────────────────────────────────────────────────────────────────

def conciliar_en_el_acto(cur, id_cuenta: int, fecha: datetime.date, id_orden: int, total: Decimal,
                         id_extracto: int, id_motivo_ingreso: int, uid) -> str | None:
    """Si la cuenta tiene una conciliación abierta que incluye la fecha, el
    recibo queda conciliado con la acreditación (como lo que genera la
    conciliación). Devuelve el período de la conciliación o None."""
    cur.execute("""SELECT * FROM conciliacion_header
                    WHERE id_cuenta = %s AND estado IN ('abierto', 'en_proceso') AND %s BETWEEN fecha_desde AND fecha_hasta
                    ORDER BY fecha_desde DESC LIMIT 1""", (id_cuenta, fecha))
    conc = cur.fetchone()
    if not conc:
        return None
    dcs = conciliacion._dc_de(cur, "ingreso", id_orden, id_cuenta)
    neto = sum((_d(d["importe_credito"]) - _d(d["importe_debito"]) for d in dcs), Decimal("0"))
    if not dcs or abs(neto - _d(total)) >= CENT:
        return None
    conciliacion._grabar_grupo(
        cur, conc, [{"id": id_extracto, "neto": float(total)}],
        [conciliacion.formatear_libro_min(d, "ingreso", id_orden) for d in dcs], uid, None,
        origen="automatico", tipo_interno="motivo_ingreso", id_motivo_ingreso=id_motivo_ingreso)
    return conc["periodo"]


def _cuenta_cobro(cur, id_cuenta) -> dict:
    cur.execute("SELECT id, nombre, tipo_de_cuenta, habilitada FROM c_cuentas_de_fondos WHERE id = %s", (id_cuenta,))
    c = cur.fetchone()
    if not c or not c["habilitada"]:
        raise ErrorCobro("Elegí una cuenta de fondos habilitada.")
    if c["tipo_de_cuenta"] not in TIPOS_CUENTA_COBRO:
        raise ErrorCobro("Se cobra en un banco o en la caja. Un cheque se carga con su orden de ingreso en Tesorería.")
    return c


def recalcular_acuerdo(cur, id_acuerdo: int, uid=None) -> str | None:
    """Sin saldo, «cancelado»; si vuelve a deber y lo había cancelado el pago, «vigente».
    Devuelve el estado nuevo, o None si no cambió."""
    cur.execute("SELECT id, estado, motivo_estado FROM fisca_acuerdo WHERE id = %s FOR UPDATE", (id_acuerdo,))
    x = cur.fetchone()
    if not x:
        return None
    falta = sum((c["saldo"] for c in cuotas_de(cur, id_acuerdo)), Decimal("0"))
    if x["estado"] == "vigente" and falta < CENT:
        cur.execute("""UPDATE fisca_acuerdo SET estado = 'cancelado', fecha_estado = NOW(), id_usuario_estado = %s,
                              motivo_estado = %s WHERE id = %s""", (uid, MOTIVO_PAGADO, id_acuerdo))
        return "cancelado"
    if x["estado"] == "cancelado" and (x["motivo_estado"] or "").startswith(MOTIVO_PAGADO) and falta >= CENT:
        cur.execute("""UPDATE fisca_acuerdo SET estado = 'vigente', fecha_estado = NULL, id_usuario_estado = NULL,
                              motivo_estado = NULL WHERE id = %s""", (id_acuerdo,))
        return "vigente"
    return None


def emitir(cur, *, id_acuerdo: int, imputaciones: list[tuple[int, Decimal]], uid, fecha: datetime.date | None = None,
           id_cuenta: int | None = None, extracto: dict | None = None, observaciones: str | None = None,
           fecha_valida=None) -> dict:
    """Emite el recibo de fiscalización. Con el cursor de una transacción: si
    algo falla, no queda nada. `extracto`: la acreditación ya bloqueada (de
    fisca_recibos._extracto_bloqueado); manda su fecha, su cuenta y su importe.
    `fecha_valida(cur, fecha)`: el control de fecha de tesorería (período
    cerrado, futura). Devuelve id_orden, nro, conciliado, razon, capital, interes."""
    cur.execute("""SELECT x.*, a.nro_acta, a.estado AS estado_acta FROM fisca_acuerdo x JOIN fisca_acta a ON a.id = x.id_acta
                    WHERE x.id = %s FOR UPDATE""", (id_acuerdo,))
    x = cur.fetchone()
    if not x:
        raise ErrorCobro("No existe ese acuerdo de pago.")
    if x["estado"] not in ESTADOS_COBRABLES:
        raise ErrorCobro(f"El acuerdo {x['nro_acuerdo']} está {x['estado']}: no se cobra.")
    if x["estado_acta"] == "anulada":
        raise ErrorCobro(f"El acta {x['nro_acta']} está anulada.")
    cur.execute("SELECT id FROM fisca_acuerdo_cuota WHERE id_acuerdo = %s FOR UPDATE", (id_acuerdo,))
    est = estado_cobro(cur, x)
    por_id = {c["id"]: c for c in est["cuotas"]}

    imput, vistos = [], set()
    for id_cuota, imp in imputaciones:
        imp = _d(imp).quantize(CENT, ROUND_HALF_UP)
        if imp <= 0:
            continue
        c = por_id.get(id_cuota)
        if not c:
            raise ErrorCobro("Hay una cuota que no es de este acuerdo.")
        if id_cuota in vistos:
            raise ErrorCobro(f"La cuota {c['nro_cuota']} está dos veces.")
        vistos.add(id_cuota)
        if imp > c["saldo"] + Decimal("0.004"):
            raise ErrorCobro(f"A la cuota {c['nro_cuota']} le faltan {pesos(c['saldo'])}: no se le imputan {pesos(imp)}.")
        imput.append((c, imp))
    if not imput:
        raise ErrorCobro("Imputá el pago a al menos una cuota.")
    total = sum((imp for _, imp in imput), Decimal("0"))

    if extracto:
        fecha, id_cuenta = extracto["fecham"], extracto["c_cuentas_de_fondos_id"]
        if abs(total - _d(extracto["credito"])) >= CENT:
            raise ErrorCobro(f"Las cuotas suman {pesos(total)} y la acreditación es de {pesos(extracto['credito'])}: "
                             "tienen que dar lo mismo.")
    else:
        _cuenta_cobro(cur, id_cuenta)
    if fecha_valida:
        error = fecha_valida(cur, fecha)
        if error:
            raise ErrorCobro(error)
    if fecha < x["fecha_acuerdo"]:
        raise ErrorCobro("El cobro no puede ser anterior a la fecha del acuerdo.")

    capital, interes = partir(total, est["falta_capital"], est["falta_acuerdo"])
    renglones_capital = repartir_capital(capital, est["periodos"])
    capital = sum((imp for _, imp in renglones_capital), Decimal("0"))
    interes = total - capital

    cuit = x["cuit"]
    razon = (x["razon_social"] or "").strip()
    talon = RT.reservar(cur, "fiscalizacion")
    nro_orden = proximo_numero(cur, "ingreso_ordenes", fecha)
    mot_cap, mot_int = id_motivo(cur, MOTIVO_CAPITAL), id_motivo(cur, MOTIVO_INTERES)
    cuotas_txt = ", ".join(f"{c['nro_cuota']} ({pesos(imp)})" for c, imp in imput)
    obs = " · ".join(v for v in (
        f"Recibo de fiscalización del acta {x['nro_acta']}, acuerdo {x['nro_acuerdo']}",
        f"cuota{'s' if len(imput) > 1 else ''} {cuotas_txt}",
        (f"acreditación del {extracto['fecham']:%d/%m/%Y} en {extracto['cuenta']}"
         + (f", ref. {extracto['ref_nro']}" if extracto.get("ref_nro") else "")) if extracto else None,
        observaciones) if v)[:2000]
    cur.execute("""INSERT INTO ingreso_ordenes (nro_orden, id_talonario, nro_recibo, clase, anio, fecha, estado, id_cuenta,
                                                importe_total, moneda, origen, id_acta, id_acuerdo, observaciones,
                                                id_usuario_creacion)
                   VALUES (%s, %s, %s, 'fiscalizacion', %s, %s, 'confirmado', %s, %s, 'ARS', %s, %s, %s, %s, %s)""",
                (nro_orden, talon["id"], talon["nro"], fecha.year, fecha, id_cuenta, total,
                 "extracto" if extracto else "manual", x["id_acta"], id_acuerdo, obs, uid))
    id_orden = cur.lastrowid
    id_ext = extracto["id"] if extracto else None
    ids_capital = []
    for p, imp in renglones_capital:
        cur.execute("""INSERT INTO ingreso_ordenes_detalle (id_orden, tipo, id_motivo_ingreso, descripcion, importe, moneda,
                                                            periodo, cuit, id_extracto_origen)
                       VALUES (%s, 'ingreso', %s, %s, %s, 'ARS', %s, %s, %s)""",
                    (id_orden, mot_cap, f"FISCALIZACION {periodo_txt(p)} · ACTA {x['nro_acta']} · {razon} (CUIT {cuit})"[:200],
                     imp, p, cuit, id_ext))
        ids_capital.append(cur.lastrowid)
    if interes >= CENT:
        cur.execute("""INSERT INTO ingreso_ordenes_detalle (id_orden, tipo, id_motivo_ingreso, descripcion, importe, moneda,
                                                            periodo, cuit, id_extracto_origen)
                       VALUES (%s, 'ingreso', %s, %s, %s, 'ARS', NULL, %s, %s)""",
                    (id_orden, mot_int, f"INTERESES ACTA {x['nro_acta']} · ACUERDO {x['nro_acuerdo']} · {razon} (CUIT {cuit})"[:200],
                     interes, cuit, id_ext))
    cur.executemany("INSERT INTO fisca_acuerdo_imputacion (id_orden, id_acuerdo, id_cuota, importe) VALUES (%s, %s, %s, %s)",
                    [(id_orden, id_acuerdo, c["id"], imp) for c, imp in imput])
    if ids_capital:
        fa.aplicar_automatico(cur, cuits=[cuit], ids_detalle=ids_capital, origen_periodo="recibo", id_usuario=uid)
    cur.execute("INSERT INTO ingreso_ordenes_cuentas (id_orden, id_cuenta_fondos, importe) VALUES (%s, %s, %s)",
                (id_orden, id_cuenta, total))
    mf.registrar_ingreso(cur, id_orden)
    nuevo_estado = recalcular_acuerdo(cur, id_acuerdo, uid)
    conciliado = (conciliar_en_el_acto(cur, id_cuenta, fecha, id_orden, total, id_ext, mot_cap, uid)
                  if extracto else None)
    return {"id_orden": id_orden, "nro": talon["texto"], "nro_orden": nro_orden, "conciliado": conciliado,
            "razon": razon, "capital": capital, "interes": interes, "total": total,
            "acuerdo_cancelado": nuevo_estado == "cancelado", "nro_acuerdo": x["nro_acuerdo"]}
