"""
retenciones.py — Motor de retenciones del circuito de pagos.

Portado de `gestion_adm/retenciones.py`. Lo que cambia:

- El sindicato es el agente de retención: la configuración sale de «Datos del
  sindicato» (`s_institucion`, columnas con los mismos nombres que
  `os_parametros`), no de los parámetros de la obra social.
- Sin Integración (Discapacidad): ni órdenes ni acumulado de esa clase.
- Régimen, monotributo y resumen del régimen son los de `rg830.py`, que ya usa
  la ficha del proveedor: una sola definición.

Qué se retiene
--------------
  IVA        RG 2854   base = neto gravado de cada comprobante
  GANANCIAS  RG 830    una por proveedor; base = importe a pagar de la orden
                       dividido (1 + alícuota de IVA elegida en Datos del
                       sindicato); régimen del proveedor y todo lo demás
                       (escala o alícuota fija, mínimo no sujeto, retención
                       mínima) de la fila vigente de rg830_escala. Acumulado
                       MENSUAL: el mínimo se descuenta una vez por mes y se
                       resta lo ya retenido en el mes.
  IIBB                 base = neto gravado de cada comprobante
  SUSS                 base = total sin IVA ni otros tributos

    retenciones = calcular_retenciones_orden(conn, id_orden, fecha_pago, avisos=[])
    # [{id_expediente, id_proveedor, tipo, regimen, base_calculo, alicuota,
    #   importe, origen_alicuota, id_certificado}, …]
"""

from __future__ import annotations

import datetime
from decimal import ROUND_HALF_UP, Decimal

from rg830 import _pesos, es_monotributista, normalizar_regimen

REGIMENES = {"IVA": "RG 2854", "GANANCIAS": "RG 830", "IIBB": "IIBB", "SUSS": "SUSS"}

#: Con qué se netea la orden si Datos del sindicato no tiene la alícuota de IVA
#: elegida: la general. Netear al 21% es mejor que no netear, que retiene de
#: más sobre una base con IVA adentro.
ALICUOTA_IVA_DEFAULT = Decimal("21")

#: Desde cuándo cuenta lo ya pagado y lo ya retenido en el mes. Es la fecha del
#: criterio «base = importe de la orden neteado de IVA» en gestion_adm; las
#: retenciones de AEDA de septiembre en adelante entran en el acumulado.
FECHA_INICIO_CRITERIO = datetime.date(2026, 9, 1)


def _d(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:                                    # noqa: BLE001
        return Decimal("0")


def _round2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def configuracion(conn) -> dict:
    """De qué impuestos el sindicato es agente, con qué alícuotas por defecto,
    y la alícuota de IVA con que se netea la base de Ganancias."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT i.ret_iva, i.ret_iva_alicuota, i.ret_ganancias, i.ret_ganancias_alicuota,
                   i.ret_iibb, i.ret_iibb_alicuota, i.ret_suss, i.ret_suss_alicuota,
                   t.alicuota AS iva_alicuota
              FROM s_institucion i
              LEFT JOIN arca_tasa_iva t ON t.id = i.ret_arca_tasa_ivaid
             ORDER BY i.id LIMIT 1""")
        return cur.fetchone() or {}


def divisor_iva(conf: dict) -> Decimal:
    """1 + alícuota/100. Cero es válido (la tasa «Exento»): el divisor es 1."""
    alic = conf.get("iva_alicuota")
    alic = ALICUOTA_IVA_DEFAULT if alic is None else _d(alic)
    if alic < 0:
        alic = ALICUOTA_IVA_DEFAULT
    return Decimal("1") + alic / Decimal("100")


def _importe_orden(conn, id_orden: int) -> Decimal:
    with conn.cursor() as cur:
        cur.execute("SELECT importe_total FROM pago_ordenes WHERE id = %s", (id_orden,))
        row = cur.fetchone()
    return _d(row["importe_total"]) if row else Decimal("0")


def _get_proveedor(conn, id_proveedor: int) -> dict:
    with conn.cursor() as cur:
        cur.execute("""SELECT id, cuit, razon_social, condicion_iva,
                              ret_iva, ret_iva_alicuota, ret_iva_padron,
                              ret_ganancias, ret_ganancias_codigo_sir,
                              ret_iibb, ret_iibb_alicuota, ret_suss, ret_suss_alicuota
                         FROM c_proveedores WHERE id = %s""", (id_proveedor,))
        return cur.fetchone() or {}


class RegimenIncompleto(Exception):
    """La fila del régimen existe pero no alcanza para calcular."""


def regimen_ganancias(conn, codigo, fecha: datetime.date) -> dict | None:
    """La fila de `rg830_escala` vigente en `fecha` para el régimen, con sus
    tramos. None si el régimen está vacío o no tiene fila vigente y activa.
    El código se compara normalizado a tres dígitos de los dos lados: la tabla
    guarda «94» y los proveedores «094»."""
    cod = normalizar_regimen(codigo)
    if not cod:
        return None
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, codigo_regimen, descripcion, tipo_calculo, alicuota_fija, alicuota_no_inscripto,
                   monto_no_sujeto_inscripto, monto_no_sujeto_no_inscripto,
                   retencion_minima_inscripto, retencion_minima_no_inscripto, resolucion
              FROM rg830_escala
             WHERE LPAD(TRIM(codigo_regimen), 3, '0') = %s AND activa = 1
               AND vigencia_desde <= %s AND (vigencia_hasta IS NULL OR vigencia_hasta >= %s)
             ORDER BY vigencia_desde DESC LIMIT 1""", (cod, fecha, fecha))
        escala = cur.fetchone()
        if not escala:
            return None
        cur.execute("""SELECT tramo_desde, tramo_hasta, importe_fijo, alicuota, excedente_sobre
                         FROM rg830_escala_tramos WHERE id_escala = %s
                        ORDER BY orden, tramo_desde""", (escala["id"],))
        tramos = list(cur.fetchall())
    return dict(escala, codigo=cod, tramos=tramos)


def _calcular_por_tramos(base: Decimal, tramos: list) -> Decimal:
    """importe fijo del tramo + (base − excedente) × alícuota."""
    for t in tramos:
        desde, hasta = _d(t["tramo_desde"]), (_d(t["tramo_hasta"]) if t["tramo_hasta"] is not None else None)
        if base > desde and (hasta is None or base <= hasta):
            return _round2(_d(t["importe_fijo"]) + (base - _d(t["excedente_sobre"])) * _d(t["alicuota"]) / 100)
    return Decimal("0")


def retencion_ganancias(reg: dict, base: Decimal, alicuota_certificado: Decimal | None = None) -> dict:
    """Lo que corresponde retener en el MES sobre `base` (lo pagado en el mes
    más este pago, neteado de IVA). Lo ya retenido lo resta quien llama."""
    base = _d(base)
    minimo = _d(reg.get("monto_no_sujeto_inscripto"))
    sujeto = base - minimo if base > minimo else Decimal("0")
    out = {"sujeto": _round2(sujeto), "retencion": Decimal("0"), "alicuota": Decimal("0"),
           "minimo": minimo, "retencion_minima": _d(reg.get("retencion_minima_inscripto"))}
    cod = reg.get("codigo") or normalizar_regimen(reg.get("codigo_regimen"))
    if alicuota_certificado is not None:
        out["alicuota"] = _d(alicuota_certificado)
        out["retencion"] = _round2(sujeto * out["alicuota"] / 100)
        return out
    if reg.get("tipo_calculo") == "escala":
        if not reg.get("tramos"):
            raise RegimenIncompleto(f"el régimen {cod} es por escala progresiva y no tiene tramos cargados "
                                    "en la tabla RG 830")
        if sujeto > 0:
            out["retencion"] = _calcular_por_tramos(sujeto, reg["tramos"])
            out["alicuota"] = _round2(out["retencion"] * 100 / sujeto)
        return out
    alic = _d(reg.get("alicuota_fija"))
    if alic <= 0:
        raise RegimenIncompleto(f"el régimen {cod} es de alícuota fija y no tiene la alícuota cargada "
                                "en la tabla RG 830")
    out["alicuota"] = alic
    out["retencion"] = _round2(sujeto * alic / 100)
    return out


def _certificado_vigente(conn, id_proveedor: int, impuesto: str, fecha: datetime.date) -> dict | None:
    """Certificado de exclusión o alícuota reducida vigente (impuesto 1
    Ganancias, 2 IVA, 3 IIBB, 4 SUSS)."""
    cod = {"GANANCIAS": 1, "IVA": 2, "IIBB": 3, "SUSS": 4}.get(impuesto)
    with conn.cursor() as cur:
        cur.execute("""SELECT id, alicuota AS alicuota_reducida
                         FROM c_proveedores_certificados_exencion
                        WHERE id_proveedor = %s AND impuesto = %s AND fecha_desde <= %s AND fecha_hasta >= %s
                        ORDER BY fecha_hasta LIMIT 1""", (id_proveedor, cod, fecha, fecha))
        return cur.fetchone()


def acumulado_ganancias_mes(conn, id_proveedor: int, anio: int, mes: int,
                            excluir_id_pago: int | None = None, divisor: Decimal | None = None) -> Decimal:
    """Lo pagado al proveedor en el mes (órdenes de comprobantes y anticipos),
    neteado de IVA igual que la base del pago. Cada pago una vez."""
    if divisor is None:
        divisor = divisor_iva(configuracion(conn))
    bruto = Decimal("0")
    consultas = (
        """SELECT p.id, MAX(p.importe_total) AS bruto
             FROM pago_pagos p
             JOIN pago_ordenes_detalle d ON d.id_orden = p.id_orden
             JOIN me_expedientes e ON e.id = d.id_expediente
            WHERE e.id_proveedor = %s""",
        """SELECT p.id, MAX(p.importe_total) AS bruto
             FROM pago_pagos p
             JOIN pago_ordenes_anticipo_det d ON d.id_orden = p.id_orden
            WHERE d.id_proveedor = %s""",
    )
    with conn.cursor() as cur:
        for sql in consultas:
            cur.execute(f"""SELECT COALESCE(SUM(x.bruto), 0) AS acumulado FROM ({sql}
                               AND YEAR(p.fecha_pago) = %s AND MONTH(p.fecha_pago) = %s
                               AND p.fecha_pago >= %s AND p.estado <> 'anulado'
                               AND (%s IS NULL OR p.id <> %s)
                             GROUP BY p.id) x""",
                        (id_proveedor, anio, mes, FECHA_INICIO_CRITERIO, excluir_id_pago, excluir_id_pago))
            bruto += _d(cur.fetchone()["acumulado"])
    return _round2(bruto / divisor) if divisor and divisor > 0 else _round2(bruto)


def retenido_ganancias_mes(conn, id_proveedor: int, anio: int, mes: int) -> Decimal:
    with conn.cursor() as cur:
        cur.execute("""SELECT COALESCE(SUM(importe), 0) AS retenido FROM pago_retenciones
                        WHERE id_proveedor = %s AND tipo = 'GANANCIAS' AND COALESCE(anulado, 0) = 0
                          AND YEAR(fecha) = %s AND MONTH(fecha) = %s AND fecha >= %s""",
                    (id_proveedor, anio, mes, FECHA_INICIO_CRITERIO))
        return _d(cur.fetchone()["retenido"])


def _avisar(avisos: list | None, texto: str) -> None:
    if avisos is not None and texto not in avisos:
        avisos.append(texto)


def _alicuota(conn, conf, prov, impuesto, clave, id_prov, fecha):
    """Certificado vigente, si no la del proveedor, si no la del sindicato."""
    cert = _certificado_vigente(conn, id_prov, impuesto, fecha)
    if cert:
        return _d(cert["alicuota_reducida"]), "certificado", cert["id"]
    if prov.get(f"ret_{clave}_alicuota"):
        return _d(prov[f"ret_{clave}_alicuota"]), "proveedor", None
    return _d(conf.get(f"ret_{clave}_alicuota")), "os_parametros", None   # el valor del enum: «del agente»


def calcular_retenciones_orden(conn, id_orden: int, fecha_pago, avisos: list | None = None) -> list[dict]:
    """Las retenciones a practicar al pagar la orden. Si el sindicato no es
    agente de un impuesto o el proveedor no la tiene tildada, no sale la línea.
    `avisos` junta lo que impidió calcular Ganancias o no llegó al mínimo."""
    if isinstance(fecha_pago, str):
        fecha_pago = datetime.date.fromisoformat(fecha_pago[:10])
    conf = configuracion(conn)
    resultado = []
    with conn.cursor() as cur:
        cur.execute("SELECT clase FROM pago_ordenes WHERE id = %s", (id_orden,))
        clase = (cur.fetchone() or {}).get("clase")
        if clase == "proveedor":
            cur.execute("""
                SELECT e.id AS id_expediente, e.id_proveedor,
                       COALESCE(fa.importe_neto_gravado, 0) AS neto_gravado,
                       COALESCE(fa.importe_total, e.importe_total, 0) - COALESCE(fa.importe_iva, 0)
                         - COALESCE(fa.importe_otros, 0) AS total,
                       COALESCE(fa.importe_total, e.importe_total, 0) AS bruto
                  FROM pago_ordenes_detalle d
                  JOIN me_expedientes e ON e.id = d.id_expediente
                  LEFT JOIN f_comprobantes_arca fa ON fa.id = e.id_comprobante
                 WHERE d.id_orden = %s AND e.id_proveedor IS NOT NULL""", (id_orden,))
        elif clase == "anticipo":
            # Sin neto gravado discriminado: el IVA va en la factura final.
            cur.execute("""SELECT NULL AS id_expediente, d.id_proveedor, 0 AS neto_gravado,
                                  COALESCE(d.importe, 0) AS total, COALESCE(d.importe, 0) AS bruto
                             FROM pago_ordenes_anticipo_det d
                            WHERE d.id_orden = %s AND d.id_proveedor IS NOT NULL""", (id_orden,))
        else:
            # Concepto, reintegro, sueldos: no hay proveedor al que retenerle.
            return []
        renglones = list(cur.fetchall())

    proveedores: dict[int, dict] = {}
    brutos: dict[int, Decimal] = {}
    for r in renglones:
        id_prov = r["id_proveedor"]
        prov = proveedores.setdefault(id_prov, _get_proveedor(conn, id_prov))
        neto, total, bruto = _d(r["neto_gravado"]), _d(r["total"]), _d(r["bruto"])
        for impuesto, clave, base, cond in (("IVA", "iva", neto, neto > 0), ("IIBB", "iibb", neto, neto > 0),
                                            ("SUSS", "suss", total, total > 0)):
            if not (conf.get(f"ret_{clave}") and prov.get(f"ret_{clave}") and cond):
                continue
            alic, origen, id_cert = _alicuota(conn, conf, prov, impuesto, clave, id_prov, fecha_pago)
            importe = _round2(base * alic / 100)
            if importe > 0:
                resultado.append({"id_expediente": r["id_expediente"], "id_proveedor": id_prov, "tipo": impuesto,
                                  "regimen": REGIMENES[impuesto], "base_calculo": float(base),
                                  "alicuota": float(alic), "importe": float(importe),
                                  "origen_alicuota": origen, "id_certificado": id_cert})
        if bruto > 0:
            brutos[id_prov] = brutos.get(id_prov, Decimal("0")) + bruto

    # Base de Ganancias: el importe de la orden neteado de IVA, repartido por
    # lo que factura cada proveedor si hubiera más de uno (no debería: una
    # orden es de un proveedor).
    divisor = divisor_iva(conf)
    bruto_orden = _importe_orden(conn, id_orden)
    suma = sum(brutos.values(), Decimal("0"))
    for id_prov, bruto_prov in brutos.items():
        if bruto_orden <= 0:
            asignado = bruto_prov
        elif len(brutos) == 1:
            asignado = bruto_orden
        elif suma > 0:
            asignado = bruto_orden * bruto_prov / suma
        else:
            continue
        base = _round2(asignado / divisor) if divisor > 0 else _round2(asignado)
        prov = proveedores[id_prov]
        if not (conf.get("ret_ganancias") and prov.get("ret_ganancias") and base > 0):
            continue
        nombre = prov.get("razon_social") or f"proveedor #{id_prov}"
        if es_monotributista(prov.get("condicion_iva")):
            _avisar(avisos, f"{nombre}: es monotributista; no corresponde retenerle Ganancias aunque tenga "
                            "la retención tildada. Destildala en su ficha.")
            continue
        reg = regimen_ganancias(conn, prov.get("ret_ganancias_codigo_sir"), fecha_pago)
        if not reg:
            cod = normalizar_regimen(prov.get("ret_ganancias_codigo_sir"))
            _avisar(avisos, f"{nombre}: " + (f"el régimen {cod} no tiene una escala vigente al "
                                             f"{fecha_pago:%d/%m/%Y} en la tabla RG 830" if cod
                                             else "tiene la retención tildada pero no tiene régimen")
                    + ". No se le retiene Ganancias hasta que se elija el régimen en su ficha o se cargue "
                      "en Tesorería → Tablas → Escala RG 830.")
            continue
        acum = acumulado_ganancias_mes(conn, id_prov, fecha_pago.year, fecha_pago.month, divisor=divisor)
        cert = _certificado_vigente(conn, id_prov, "GANANCIAS", fecha_pago)
        try:
            calc = retencion_ganancias(reg, acum + base, _d(cert["alicuota_reducida"]) if cert else None)
        except RegimenIncompleto as e:
            _avisar(avisos, f"{nombre}: {e}. No se le retiene Ganancias.")
            continue
        if calc["retencion"] <= 0:
            continue
        importe = _round2(calc["retencion"] - retenido_ganancias_mes(conn, id_prov, fecha_pago.year,
                                                                      fecha_pago.month))
        if importe <= 0:
            continue
        if importe < calc["retencion_minima"]:
            _avisar(avisos, f"{nombre}: correspondería retener {_pesos(importe)}, menos que la retención mínima "
                            f"de {_pesos(calc['retencion_minima'])} del régimen {reg['codigo']}. No se retiene "
                            "en este pago; queda en el acumulado del mes.")
            continue
        resultado.append({"id_expediente": None, "id_proveedor": id_prov, "tipo": "GANANCIAS",
                          "regimen": reg["codigo"], "base_calculo": float(calc["sujeto"]),
                          "alicuota": float(calc["alicuota"]), "importe": float(importe),
                          "origen_alicuota": "certificado" if cert else "escala",
                          "id_certificado": cert["id"] if cert else None})
    return resultado


def total_retenciones(retenciones: list[dict]) -> float:
    return round(sum(float(r["importe"]) for r in retenciones), 2)
