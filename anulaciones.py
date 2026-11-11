"""
anulaciones.py — Cuándo se puede anular un comprobante que movió plata.

Portado de `gestion_adm/anulaciones.py` (las reglas; la pantalla Tesorería →
Anulaciones viene con la etapa de movimientos). Un comprobante de fondos se
puede anular solo si:

  1. su período contable no está cerrado ni bloqueado (`c_periodos`);
  2. no está conciliado contra el extracto bancario;
  3. no salió en un archivo de transferencias.

`motivos_para_no_anular()` devuelve TODOS los impedimentos, en castellano, o
una lista vacía. Si una verificación falla, se informa como impedimento: ante
la duda no se anula.
"""

from __future__ import annotations

import datetime

#: Con True, solo se anula dentro del mes corriente. En gestion_adm está
#: apagado mientras nadie cierre los períodos.
EXIGIR_MES_CORRIENTE = False

_CONCILIADO = "(ci.estado = 'conciliado' OR ch.estado = 'cerrado')"


def _fuera_de_periodo(cur, fecha) -> str | None:
    if not fecha:
        return "el comprobante no tiene fecha"
    if isinstance(fecha, datetime.datetime):
        fecha = fecha.date()
    cur.execute("""SELECT estado FROM c_periodos WHERE %s BETWEEN fecha_inicio AND fecha_fin
                    ORDER BY id_periodo DESC LIMIT 1""", (fecha,))
    per = cur.fetchone()
    if per and per.get("estado") in ("cerrado", "bloqueado"):
        return f"el período contable de esa fecha está {per['estado']}"
    if EXIGIR_MES_CORRIENTE:
        hoy = datetime.date.today()
        if (fecha.year, fecha.month) != (hoy.year, hoy.month):
            return (f"es de {fecha:%Y-%m} y solo se puede anular dentro del mismo período ({hoy:%Y-%m})")
    return None


def sql_pago_conciliado(p: str = "p") -> str:
    """La condición «el extracto ya mostró este pago», como SQL sobre el alias
    `p` de `pago_pagos`. Es la que usa `_conciliado_pago` y la que filtra la
    grilla de transferencias masivas: una sola regla para las dos preguntas."""
    return f"""(EXISTS (SELECT 1 FROM conciliacion_items ci JOIN conciliacion_header ch ON ch.id = ci.id_conciliacion
                    WHERE ci.id_pago_pagos = {p}.id AND {_CONCILIADO})
        OR EXISTS (SELECT 1 FROM conciliacion_comprobantes cc
                     JOIN conciliacion_items ci ON ci.id = cc.id_item JOIN conciliacion_header ch ON ch.id = ci.id_conciliacion
                    WHERE cc.id_pago = {p}.id AND {_CONCILIADO})
        OR EXISTS (SELECT 1 FROM conciliacion_comprobantes cc
                     JOIN conciliacion_items ci ON ci.id_grupo = cc.id_grupo JOIN conciliacion_header ch ON ch.id = ci.id_conciliacion
                    WHERE cc.id_pago = {p}.id AND cc.id_grupo IS NOT NULL AND {_CONCILIADO})
        OR EXISTS (SELECT 1 FROM conciliacion_comprobantes cc
                     JOIN c_movimientos_de_fondos mf ON mf.id = cc.id_movimiento
                     LEFT JOIN conciliacion_items ci ON ci.id = cc.id_item
                     LEFT JOIN conciliacion_header ch ON ch.id = ci.id_conciliacion
                    WHERE mf.pago_pagosId = {p}.id AND (ci.id IS NULL OR {_CONCILIADO})))"""


def _conciliado_pago(cur, id_pago: int) -> bool:
    cur.execute(f"SELECT {sql_pago_conciliado('p')} AS c FROM pago_pagos p WHERE p.id = %s", (id_pago,))
    return bool((cur.fetchone() or {}).get("c"))


def _conciliado_ingreso(cur, id_orden: int) -> bool:
    cur.execute(f"""SELECT 1 FROM conciliacion_comprobantes cc
                      JOIN conciliacion_items ci ON ci.id = cc.id_item
                      JOIN conciliacion_header ch ON ch.id = ci.id_conciliacion
                     WHERE cc.id_ingreso = %s AND {_CONCILIADO} LIMIT 1""", (id_orden,))
    return cur.fetchone() is not None


def _conciliado_movimiento(cur, id_movimiento: int) -> bool:
    cur.execute(f"""SELECT 1 FROM c_movimientos_de_fondos mf
                      JOIN c_debitos_creditos_bancarios dc ON dc.c_movimientos_de_fondosId = mf.id
                      JOIN conciliacion_items ci ON ci.id_debito_credito = dc.id
                      JOIN conciliacion_header ch ON ch.id = ci.id_conciliacion
                     WHERE mf.c_movimiento_entre_cuentasId = %s AND {_CONCILIADO} LIMIT 1""", (id_movimiento,))
    return cur.fetchone() is not None


def ya_transferido(cur, id_pago: int) -> bool:
    """¿Salió en un archivo de transferencias? Solo renglones incluidos de lotes
    no anulados."""
    cur.execute("""SELECT 1 FROM pago_transferencias_lote_det d
                     JOIN pago_transferencias_lote l ON l.id = d.id_lote
                    WHERE d.id_pago = %s AND d.incluida = 1 AND l.fecha_anulacion IS NULL LIMIT 1""", (id_pago,))
    return cur.fetchone() is not None


def motivos_para_no_anular(cur, origen: str, id_comprobante: int, fecha=None) -> list[str]:
    """`origen`: 'pago' | 'ingreso' | 'movimiento' (el vocabulario del libro de fondos)."""
    if fecha is None:
        col = {"pago": "pago_pagosId", "ingreso": "ingreso_ordenesId",
               "movimiento": "c_movimiento_entre_cuentasId"}[origen]
        cur.execute(f"SELECT MIN(fecha) AS fecha FROM c_movimientos_de_fondos WHERE {col} = %s", (id_comprobante,))
        fecha = (cur.fetchone() or {}).get("fecha")
    motivos = []
    fuera = _fuera_de_periodo(cur, fecha)
    if fuera:
        motivos.append(fuera)
    try:
        if origen == "pago":
            if _conciliado_pago(cur, id_comprobante):
                motivos.append("está conciliado con el extracto bancario")
            if ya_transferido(cur, id_comprobante):
                motivos.append("ya salió en un archivo de transferencias")
        elif origen == "ingreso" and _conciliado_ingreso(cur, id_comprobante):
            motivos.append("está conciliado con el extracto bancario")
        elif origen == "movimiento" and _conciliado_movimiento(cur, id_comprobante):
            motivos.append("está conciliado con el extracto bancario")
    except Exception as e:                                  # noqa: BLE001 — ante la duda, no se anula
        motivos.append(f"no se pudo verificar la conciliación ({e})")
    return motivos
