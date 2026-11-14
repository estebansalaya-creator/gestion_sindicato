"""
fisca_aplicaciones.py — Aplicación de cobros a las cuotas sindicales.

Qué parte de cada cobro cancela qué liquidación (`fisca_aplicacion`,
sql/fisca_aplicaciones_20261114.sql). La usan la cuenta corriente de
empleadores (cc_empleadores.py), la emisión de recibos (fisca_recibos.py) y la
aplicación automática por consola (aplicar_cobros.py).

    cobro          renglón de una orden de ingreso NO anulada con el CUIT del
                   empleador (`ingreso_ordenes_detalle.cuit`) y clase
                   cuota_sindical o motivo CUOTA SINDICAL / INGRESOS POR
                   FISCALIZACION: los recibos y los AEDA-RC / AEDA-OI
    liquidación    `fisca_liquidacion` vigente: un CUIT y un período

    saldo del período   = liquidado − aplicado
    cobro sin aplicar   = importe − aplicado
    saldo del empleador = liquidado − cobrado (las aplicaciones no lo cambian)

Solo cuentan las aplicaciones de cobros vivos a liquidaciones vigentes del
mismo CUIT. Las demás (la orden se anuló, la liquidación se anuló al
reliquidar) las saca `aplicar_automatico`, con su rastro.

APLICACIÓN AUTOMÁTICA (`aplicar_automatico`)
  1. Limpia: lo aplicado a una orden o una liquidación anulada sale; si una
     liquidación quedó con más aplicado que su importe (se reliquidó por
     menos), se recorta lo automático más nuevo primero. Lo manual no se toca:
     se informa como «aplicado de más».
  2. Cada cobro, a su propio período, hasta el saldo del período (origen
     «periodo»).
  3. Con `deuda_vieja`: lo que sigue sin aplicar, a la deuda más vieja del
     mismo CUIT, de los cobros más viejos a los más nuevos, y solo a períodos
     que ya habían empezado cuando se cobró (origen «deuda_vieja»). Un cobro
     cuyo período todavía no está liquidado espera a su liquidación: no se usa
     para la deuda vieja. Es la regla que se decidió para aplicar cobros (la
     de `fisca_recibos.distribuir`).
Desaplicar deja el rastro en `fisca_aplicacion_baja` (quién, cuándo, por qué).
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from decimal import Decimal

CENT = Decimal("0.01")
#: Motivos de ingreso que son pagos del empleador (además de toda orden de clase cuota_sindical).
MOTIVOS_COBRO = ("CUOTA SINDICAL", "INGRESOS POR FISCALIZACION")
RE_PERIODO_SQL = "'^(19|20)[0-9]{2}(0[1-9]|1[0-2])$'"
ORIGENES = {"periodo": "A su período", "deuda_vieja": "A la deuda más vieja", "recibo": "Al emitir el recibo",
            "manual": "Manual"}



def sql_aplicado_cobro(d: str = "d") -> str:
    """Lo aplicado del renglón `d` (de una orden no anulada) a liquidaciones vigentes de su CUIT."""
    return f"""COALESCE((SELECT SUM(ap.importe) FROM fisca_aplicacion ap
                          JOIN fisca_liquidacion lq ON lq.id = ap.id_liquidacion AND lq.estado = 'vigente'
                                                   AND lq.cuit = {d}.cuit
                         WHERE ap.id_detalle = {d}.id), 0)"""


def sql_aplicado_liq(l: str = "l") -> str:
    """Lo aplicado a la liquidación `l` desde cobros vivos de su CUIT."""
    return f"""COALESCE((SELECT SUM(ap.importe) FROM fisca_aplicacion ap
                          JOIN ingreso_ordenes_detalle dq ON dq.id = ap.id_detalle AND dq.cuit = {l}.cuit
                          JOIN ingreso_ordenes oq ON oq.id = dq.id_orden AND oq.estado <> 'anulado'
                         WHERE ap.id_liquidacion = {l}.id), 0)"""


#: Los cobros, renglón por renglón, con lo aplicado. `per` es el período si es
#: AAAAMM; si no, NULL. Para agregar condiciones: «AND …» al final.
SQL_COBROS = f"""
    SELECT d.id AS id_detalle, d.id_orden, d.cuit, d.importe, d.descripcion,
           CASE WHEN d.periodo REGEXP {RE_PERIODO_SQL} THEN d.periodo END AS per,
           d.periodo AS periodo_cargado, o.fecha, o.nro_orden, o.clase, o.origen,
           m.descripcion AS motivo,
           {sql_aplicado_cobro("d")} AS aplicado
      FROM ingreso_ordenes_detalle d
      JOIN ingreso_ordenes o ON o.id = d.id_orden
      LEFT JOIN c_motivos_de_ingreso m ON m.id = d.id_motivo_ingreso
     WHERE o.estado <> 'anulado' AND d.cuit REGEXP '^[0-9]{{11}}$'
       AND (o.clase = 'cuota_sindical' OR m.descripcion IN ({', '.join(['%s'] * len(MOTIVOS_COBRO))}))
"""


class ErrorAplicacion(Exception):
    """Lo que impide aplicar o desaplicar: se muestra tal cual."""


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


def _pesos(v) -> str:
    entero, _, dec = f"{float(v or 0):,.2f}".partition(".")
    return f"$ {entero.replace(',', '.')},{dec}"


def _per(p: str | None) -> str:
    return f"{p[:4]}-{p[4:]}" if p else "—"


def falta_esquema(cur) -> bool:
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.tables
                    WHERE table_schema = DATABASE() AND table_name IN ('fisca_aplicacion', 'fisca_aplicacion_baja')""")
    return cur.fetchone()["n"] < 2


# ─────────────────────────────────────────────────────────────────────────────
# Lectura
# ─────────────────────────────────────────────────────────────────────────────

def cobros_de(cur, cuit: str) -> list[dict]:
    cur.execute(SQL_COBROS + " AND d.cuit = %s ORDER BY o.fecha, o.id, d.id", list(MOTIVOS_COBRO) + [cuit])
    out = list(cur.fetchall())
    for c in out:
        c["importe"], c["aplicado"] = _d(c["importe"]), _d(c["aplicado"])
        c["sin_aplicar"] = c["importe"] - c["aplicado"]
    return out


def liquidaciones_de(cur, cuit: str) -> list[dict]:
    """Las vigentes del CUIT con lo aplicado y el saldo, de la más vieja a la más nueva."""
    cur.execute(f"""SELECT l.id, l.periodo, l.vencimiento, l.origen, l.afiliados, l.afiliados_activos,
                           l.activos_con_ddjj, l.porc_ddjj, l.remuneracion, l.importe, l.aeda_importe, l.observaciones,
                           {sql_aplicado_liq("l")} AS aplicado
                      FROM fisca_liquidacion l
                     WHERE l.estado = 'vigente' AND l.cuit = %s ORDER BY l.periodo""", (cuit,))
    out = list(cur.fetchall())
    for l in out:
        l["importe"], l["aplicado"] = _d(l["importe"]), _d(l["aplicado"])
        l["saldo"] = l["importe"] - l["aplicado"]
    return out


def aplicaciones_de(cur, cuit: str) -> list[dict]:
    """Todas las aplicaciones de cobros o liquidaciones del CUIT, con `viva`
    (cuenta) y, si no, por qué no."""
    cur.execute("""SELECT a.id, a.id_detalle, a.id_liquidacion, a.importe, a.origen, a.fecha, a.observaciones,
                          u.nombre AS usuario, d.cuit AS cuit_cobro, d.importe AS importe_cobro,
                          d.periodo AS periodo_cobro, o.id AS id_orden, o.nro_orden, o.fecha AS fecha_cobro,
                          o.clase, o.estado AS estado_orden, l.cuit AS cuit_liq, l.periodo, l.estado AS estado_liq,
                          l.importe AS importe_liq
                     FROM fisca_aplicacion a
                     JOIN ingreso_ordenes_detalle d ON d.id = a.id_detalle
                     JOIN ingreso_ordenes o ON o.id = d.id_orden
                     JOIN fisca_liquidacion l ON l.id = a.id_liquidacion
                     LEFT JOIN s_usuarios u ON u.id = a.id_usuario
                    WHERE d.cuit = %s OR l.cuit = %s
                    ORDER BY l.periodo, o.fecha, a.id""", (cuit, cuit))
    out = list(cur.fetchall())
    for a in out:
        a["importe"] = _d(a["importe"])
        a["muerta"] = ("la orden de ingreso está anulada" if a["estado_orden"] == "anulado"
                       else "la liquidación está anulada" if a["estado_liq"] != "vigente"
                       else "el cobro es de otro CUIT" if a["cuit_cobro"] != a["cuit_liq"] else None)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Aplicar y desaplicar, de a uno
# ─────────────────────────────────────────────────────────────────────────────

def aplicar(cur, id_detalle: int, id_liquidacion: int, importe, origen: str, id_usuario,
            observaciones: str | None = None) -> dict:
    """Aplica `importe` del cobro a la liquidación. Con las dos filas
    bloqueadas: lo que se valida es lo que se graba."""
    importe = _d(importe).quantize(CENT)
    if importe <= 0:
        raise ErrorAplicacion("El importe tiene que ser mayor que cero.")
    if origen not in ORIGENES:
        raise ErrorAplicacion(f"Origen desconocido: {origen}.")
    cur.execute(SQL_COBROS + " AND d.id = %s", list(MOTIVOS_COBRO) + [id_detalle])
    c = cur.fetchone()
    cur.execute("SELECT id FROM ingreso_ordenes_detalle WHERE id = %s FOR UPDATE", (id_detalle,))
    cur.execute("SELECT id, cuit, periodo, importe, estado FROM fisca_liquidacion WHERE id = %s FOR UPDATE",
                (id_liquidacion,))
    l = cur.fetchone()
    if not c:
        raise ErrorAplicacion("Ese cobro no existe, está anulado o no es de cuota sindical.")
    if not l or l["estado"] != "vigente":
        raise ErrorAplicacion("Esa liquidación no existe o está anulada.")
    if l["cuit"] != c["cuit"]:
        raise ErrorAplicacion("El cobro y la liquidación son de CUIT distintos.")
    libre = _d(c["importe"]) - _d(c["aplicado"])
    cur.execute(f"SELECT {sql_aplicado_liq('l')} AS n FROM fisca_liquidacion l WHERE l.id = %s", (id_liquidacion,))
    saldo = _d(l["importe"]) - _d(cur.fetchone()["n"])
    if importe > libre + Decimal("0.005"):
        raise ErrorAplicacion(f"Al cobro le quedan {_pesos(libre)} sin aplicar.")
    if importe > saldo + Decimal("0.005"):
        raise ErrorAplicacion(f"A la cuota de {_per(l['periodo'])} le quedan {_pesos(saldo)} de saldo.")
    cur.execute("""INSERT INTO fisca_aplicacion (id_detalle, id_liquidacion, importe, origen, fecha, observaciones, id_usuario)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE importe = importe + VALUES(importe),
                                           observaciones = COALESCE(VALUES(observaciones), observaciones)""",
                (id_detalle, id_liquidacion, importe, origen, datetime.date.today(),
                 (observaciones or "").strip()[:255] or None, id_usuario))
    return {"importe": importe, "periodo": l["periodo"], "cuit": l["cuit"]}


def desaplicar(cur, id_aplic: int, importe, motivo: str, id_usuario) -> dict:
    """Desaplica toda la aplicación o una parte. El motivo es obligatorio."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise ErrorAplicacion("Escribí el motivo: queda registrado junto con quién desaplicó.")
    cur.execute("""SELECT a.*, l.periodo, l.cuit FROM fisca_aplicacion a
                     JOIN fisca_liquidacion l ON l.id = a.id_liquidacion WHERE a.id = %s FOR UPDATE""", (id_aplic,))
    a = cur.fetchone()
    if not a:
        raise ErrorAplicacion("Esa aplicación ya no existe.")
    total = _d(a["importe"])
    importe = total if importe in (None, "") else _d(importe).quantize(CENT)
    if importe <= 0:
        raise ErrorAplicacion("El importe tiene que ser mayor que cero.")
    if importe > total + Decimal("0.005"):
        raise ErrorAplicacion(f"No se puede desaplicar más de lo aplicado ({_pesos(total)}).")
    _baja(cur, a, min(importe, total), motivo, id_usuario)
    return {"importe": min(importe, total), "periodo": a["periodo"], "cuit": a["cuit"]}


def _baja(cur, a: dict, importe: Decimal, motivo: str, id_usuario) -> None:
    cur.execute("""INSERT INTO fisca_aplicacion_baja (id_aplicacion, id_detalle, id_liquidacion, importe, origen,
                                                      fecha_aplicacion, motivo, id_usuario)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (a["id"], a["id_detalle"], a["id_liquidacion"], importe, a["origen"], a.get("fecha"),
                 motivo[:255], id_usuario))
    if importe >= _d(a["importe"]) - Decimal("0.005"):
        cur.execute("DELETE FROM fisca_aplicacion WHERE id = %s", (a["id"],))
    else:
        cur.execute("UPDATE fisca_aplicacion SET importe = importe - %s WHERE id = %s", (importe, a["id"]))


# ─────────────────────────────────────────────────────────────────────────────
# Aplicación automática
# ─────────────────────────────────────────────────────────────────────────────

def _en(campo: str, valores) -> tuple[str, list]:
    valores = sorted(set(valores))
    return f" AND {campo} IN ({', '.join(['%s'] * len(valores))})", valores


def aplicar_automatico(cur, cuits=None, deuda_vieja: bool = False, id_usuario=None,
                       ids_detalle=None, origen_periodo: str = "periodo") -> dict:
    """Ver el encabezado del módulo. `cuits`: solo esos (None = todos).
    `ids_detalle`: solo esos cobros (lo usa la emisión del recibo, con
    `origen_periodo='recibo'`). Con el cursor de una transacción."""
    hoy = datetime.date.today()
    r = {"cuits": 0, "limpiadas": 0, "recortadas": 0, "recortado": Decimal("0"),
         "a_periodo": 0, "importe_periodo": Decimal("0"), "a_deuda": 0, "importe_deuda": Decimal("0"),
         "de_mas": 0, "importe_de_mas": Decimal("0"), "sin_aplicar": Decimal("0")}
    f_cob, p_cob = ("", [])
    f_liq, p_liq = ("", [])
    f_apl, p_apl = ("", [])
    if cuits is not None:
        cuits = [c for c in cuits if c]
        if not cuits:
            return r
        f_cob, p_cob = _en("d.cuit", cuits)
        f_liq, p_liq = _en("l.cuit", cuits)
        f_apl, p_apl = _en("l.cuit", cuits)
    if ids_detalle is not None:
        f_cob2, p_cob2 = _en("d.id", ids_detalle) if ids_detalle else (" AND 1 = 0", [])
    else:
        f_cob2, p_cob2 = "", []

    # 1. Limpiar.
    cur.execute(f"""SELECT a.*, o.estado AS estado_orden, l.estado AS estado_liq, l.cuit AS cuit_liq,
                           d.cuit AS cuit_cobro, l.importe AS importe_liq, l.periodo
                      FROM fisca_aplicacion a
                      JOIN ingreso_ordenes_detalle d ON d.id = a.id_detalle
                      JOIN ingreso_ordenes o ON o.id = d.id_orden
                      JOIN fisca_liquidacion l ON l.id = a.id_liquidacion
                     WHERE 1 = 1{f_apl}
                     ORDER BY a.id_liquidacion, a.creado DESC, a.id DESC FOR UPDATE""", p_apl)
    apps = list(cur.fetchall())
    vivas = []
    for a in apps:
        motivo = ("La orden de ingreso se anuló" if a["estado_orden"] == "anulado"
                  else "La liquidación se anuló" if a["estado_liq"] != "vigente"
                  else "El cobro es de otro CUIT" if a["cuit_liq"] != a["cuit_cobro"] else None)
        if motivo:
            _baja(cur, a, _d(a["importe"]), motivo + " (aplicación automática)", id_usuario)
            r["limpiadas"] += 1
        else:
            vivas.append(a)
    por_liq = defaultdict(list)
    for a in vivas:
        por_liq[a["id_liquidacion"]].append(a)
    aplic_liq, aplic_det = defaultdict(Decimal), defaultdict(Decimal)
    for id_liq, lista in por_liq.items():
        tope = _d(lista[0]["importe_liq"])
        total = sum((_d(a["importe"]) for a in lista), Decimal("0"))
        exceso = total - tope
        # Lo automático más nuevo primero (la lista viene por creado DESC); lo manual, al final y no se toca.
        for a in sorted(lista, key=lambda x: x["origen"] == "manual"):
            imp = _d(a["importe"])
            if exceso > Decimal("0.005") and a["origen"] != "manual":
                corte = min(exceso, imp)
                _baja(cur, a, corte, f"La liquidación de {_per(a['periodo'])} bajó a {_pesos(tope)} "
                                     "(aplicación automática)", id_usuario)
                r["recortadas"] += 1
                r["recortado"] += corte
                exceso -= corte
                imp -= corte
            aplic_liq[id_liq] += imp
            aplic_det[a["id_detalle"]] += imp
        if exceso > Decimal("0.005"):
            r["de_mas"] += 1
            r["importe_de_mas"] += exceso

    # 2 y 3. Lo que falta aplicar.
    cur.execute(f"""SELECT d.id, d.cuit, d.importe, o.fecha,
                           CASE WHEN d.periodo REGEXP {RE_PERIODO_SQL} THEN d.periodo END AS per
                      FROM ingreso_ordenes_detalle d
                      JOIN ingreso_ordenes o ON o.id = d.id_orden
                      LEFT JOIN c_motivos_de_ingreso m ON m.id = d.id_motivo_ingreso
                     WHERE o.estado <> 'anulado' AND d.cuit REGEXP '^[0-9]{{11}}$'
                       AND (o.clase = 'cuota_sindical' OR m.descripcion IN ({', '.join(['%s'] * len(MOTIVOS_COBRO))}))
                       {f_cob}{f_cob2}
                     ORDER BY o.fecha, o.id, d.id""", list(MOTIVOS_COBRO) + p_cob + p_cob2)
    cobros = list(cur.fetchall())
    cur.execute(f"""SELECT l.id, l.cuit, l.periodo, l.importe FROM fisca_liquidacion l
                     WHERE l.estado = 'vigente'{f_liq} ORDER BY l.periodo""", p_liq)
    liqs = list(cur.fetchall())
    liq_de = {(l["cuit"], l["periodo"]): l for l in liqs}
    saldo = {l["id"]: _d(l["importe"]) - aplic_liq[l["id"]] for l in liqs}
    nuevas = defaultdict(Decimal)                     # (id_detalle, id_liq, origen) → importe
    libre = {}
    for c in cobros:
        libre[c["id"]] = _d(c["importe"]) - aplic_det[c["id"]]
        l = liq_de.get((c["cuit"], c["per"])) if c["per"] else None
        if l and libre[c["id"]] > Decimal("0.005") and saldo[l["id"]] > Decimal("0.005"):
            imp = min(libre[c["id"]], saldo[l["id"]])
            nuevas[(c["id"], l["id"], origen_periodo)] += imp
            libre[c["id"]] -= imp
            saldo[l["id"]] -= imp
            r["a_periodo"] += 1
            r["importe_periodo"] += imp
    if deuda_vieja:
        liqs_de = defaultdict(list)
        for l in liqs:
            liqs_de[l["cuit"]].append(l)
        for c in cobros:
            # Un cobro de un período que todavía no se liquidó espera a su liquidación.
            if c["per"] and (c["cuit"], c["per"]) not in liq_de:
                continue
            hasta = f"{c['fecha']:%Y%m}" if c["fecha"] else None
            for l in liqs_de[c["cuit"]]:
                if libre[c["id"]] <= Decimal("0.005"):
                    break
                if saldo[l["id"]] <= Decimal("0.005") or (hasta and l["periodo"] > hasta):
                    continue
                imp = min(libre[c["id"]], saldo[l["id"]])
                nuevas[(c["id"], l["id"], "deuda_vieja")] += imp
                libre[c["id"]] -= imp
                saldo[l["id"]] -= imp
                r["a_deuda"] += 1
                r["importe_deuda"] += imp
    if nuevas:
        cur.executemany("""INSERT INTO fisca_aplicacion (id_detalle, id_liquidacion, importe, origen, fecha, id_usuario)
                           VALUES (%s, %s, %s, %s, %s, %s)
                           ON DUPLICATE KEY UPDATE importe = importe + VALUES(importe)""",
                        [(d, l, imp.quantize(CENT), o, hoy, id_usuario) for (d, l, o), imp in nuevas.items()
                         if imp.quantize(CENT) > 0])
    r["cuits"] = len({c["cuit"] for c in cobros} | {l["cuit"] for l in liqs})
    r["sin_aplicar"] = sum((v for v in libre.values() if v > 0), Decimal("0"))
    return r


def texto_resultado(r: dict) -> str:
    partes = []
    if r["a_periodo"]:
        partes.append(f"{r['a_periodo']} cobro(s) a su período ({_pesos(r['importe_periodo'])})")
    if r["a_deuda"]:
        partes.append(f"{r['a_deuda']} aplicación(es) a la deuda más vieja ({_pesos(r['importe_deuda'])})")
    if r["limpiadas"]:
        partes.append(f"{r['limpiadas']} quitada(s) por estar anulada la orden o la liquidación")
    if r["recortadas"]:
        partes.append(f"{r['recortadas']} recortada(s) porque la liquidación bajó ({_pesos(r['recortado'])})")
    texto = ("Aplicación automática: " + "; ".join(partes) + ".") if partes else \
        "Aplicación automática: no había nada para aplicar."
    if r["de_mas"]:
        texto += (f" Atención: {r['de_mas']} liquidación(es) tienen más aplicado a mano que su importe "
                  f"({_pesos(r['importe_de_mas'])}): revisalas.")
    return texto
