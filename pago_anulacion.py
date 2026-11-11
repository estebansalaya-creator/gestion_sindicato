"""
pago_anulacion.py — Deshacer un pago emitido, o anular una orden sin pago.

Portado de `gestion_adm/pago_anulacion.py`. Las dos funciones reciben el
cursor de la transacción de quien llama: si algo falla, no queda nada a medias.

Anular un PAGO deshace, en orden inverso al que se construyó: la aplicación
contra las liquidaciones (se borra: es una relación, no un hecho; todas las
vistas de saldo la suman sin filtrar), los expedientes vuelven a liquidados,
los renglones de sueldos quedan sin pagar, retenciones y certificados se
marcan anulados (son hechos frente a ARCA), las imputaciones contables, el
detalle bancario, el libro de fondos (fecha de anulación, no se borra) y el
pago. La orden vuelve a «aprobada» si no le queda otro pago vivo.

Anular una ORDEN solo se puede sin pago vivo: la orden es una intención.
Libera los expedientes y recalcula los reintegros que tenía.
"""

from __future__ import annotations

import logging

import anulaciones
import movimientos_fondos as mf
from numeracion import nro_orden_visible, sql_nro_orden_visible

log = logging.getLogger(__name__)


def _fila(cur, sql, params=()):
    cur.execute(sql, params)
    return cur.fetchone()


def anular(cur, id_pago: int, motivo: str, id_usuario: int | None = None) -> dict:
    """Anula el pago y todo lo que escribió. ValueError (texto para el
    usuario) si no se puede."""
    motivo = (motivo or "").strip()[:250]
    if not motivo:
        raise ValueError("Hace falta un motivo para anular.")
    pago = _fila(cur, f"""SELECT p.*, o.clase, {sql_nro_orden_visible('o')} AS nro_orden_vis
                            FROM pago_pagos p JOIN pago_ordenes o ON o.id = p.id_orden
                           WHERE p.id = %s FOR UPDATE""", (id_pago,))
    if not pago:
        raise ValueError("El pago no existe.")
    if pago["estado"] == "anulado":
        raise ValueError("El pago ya estaba anulado.")
    impedimentos = anulaciones.motivos_para_no_anular(cur, "pago", id_pago, pago.get("fecha_pago"))
    if impedimentos:
        raise ValueError("No se puede anular porque " + "; ".join(impedimentos) + ".")

    r = {"nro_pago": pago["nro_pago"], "importe": pago["importe_total"], "nro_orden": pago["nro_orden_vis"],
         "clase": pago["clase"]}
    ap = _fila(cur, "SELECT COUNT(*) AS n, COALESCE(SUM(importe_aplicado), 0) AS imp "
                    "FROM c_pasivo_aplicacion WHERE id_pago = %s", (id_pago,))
    r["aplicaciones"], r["importe_desaplicado"] = ap["n"] or 0, ap["imp"] or 0
    cur.execute("DELETE FROM c_pasivo_aplicacion WHERE id_pago = %s", (id_pago,))
    cur.execute("UPDATE me_expedientes SET estado = 'liquidado', id_pago = NULL "
                "WHERE id_pago = %s AND estado = 'pagado'", (id_pago,))
    r["expedientes"] = cur.rowcount
    cur.execute("UPDATE pago_ordenes_sueldos_det SET id_pago = NULL WHERE id_pago = %s", (id_pago,))
    r["renglones_sueldos"] = cur.rowcount
    cur.execute("""UPDATE pago_retenciones SET anulado = 1, fecha_anulacion = NOW(), id_usuario_anulacion = %s
                    WHERE id_pago = %s AND COALESCE(anulado, 0) = 0""", (id_usuario, id_pago))
    r["retenciones"] = cur.rowcount
    r["certificados_en_sire"] = _fila(cur, "SELECT COUNT(*) AS n FROM pago_retenciones_certificado "
                                           "WHERE id_pago = %s AND exportado_sire = 1", (id_pago,))["n"] or 0
    cur.execute("""UPDATE pago_retenciones_certificado
                      SET estado = 'anulado', fecha_anulacion = NOW(), motivo_anulacion = %s, id_usuario_anulacion = %s
                    WHERE id_pago = %s AND COALESCE(estado, '') <> 'anulado'""", (motivo[:200], id_usuario, id_pago))
    r["certificados"] = cur.rowcount
    cur.execute("""UPDATE pago_imputaciones SET anulado = 1, fecha_anulacion = NOW(), id_usuario_anulacion = %s
                    WHERE id_pago = %s AND COALESCE(anulado, 0) = 0""", (id_usuario, id_pago))
    r["imputaciones"] = cur.rowcount
    cur.execute("""UPDATE c_debitos_creditos_bancarios dc
                     JOIN c_movimientos_de_fondos m ON m.id = dc.c_movimientos_de_fondosId
                      SET dc.estado = 'anulado'
                    WHERE m.pago_pagosId = %s""", (id_pago,))
    r["instrumentos_bancarios"] = cur.rowcount
    mf.anular(cur, "pago", id_pago, f"Pago anulado: {motivo}", id_usuario)
    cur.execute("""UPDATE pago_pagos SET estado = 'anulado', fecha_anulacion = NOW(), motivo_anulacion = %s,
                          id_usuario_anulacion = %s WHERE id = %s""", (motivo, id_usuario, id_pago))
    vivos = _fila(cur, "SELECT COUNT(*) AS n FROM pago_pagos WHERE id_orden = %s AND estado <> 'anulado'",
                  (pago["id_orden"],))
    r["orden_reabierta"] = (vivos["n"] or 0) == 0
    if r["orden_reabierta"]:
        cur.execute("UPDATE pago_ordenes SET estado = 'aprobada' WHERE id = %s AND estado = 'pagada'",
                    (pago["id_orden"],))
    log.info("pago %s (%s) anulado por usuario %s: %s | %s", id_pago, pago["nro_pago"], id_usuario, motivo, r)
    return r


def anular_orden(cur, id_orden: int, motivo: str, id_usuario: int | None = None) -> dict:
    """Anula una orden SIN pago vivo y libera lo que tenía tomado."""
    orden = _fila(cur, "SELECT id, nro_orden, nro_origen, clase, estado, importe_total "
                       "FROM pago_ordenes WHERE id = %s FOR UPDATE", (id_orden,))
    if not orden:
        raise ValueError("La orden no existe.")
    nro = nro_orden_visible(orden)
    if orden["estado"] == "anulada":
        raise ValueError(f"La orden {nro} ya está anulada.")
    vivos = _fila(cur, """SELECT COUNT(*) AS n, GROUP_CONCAT(nro_pago ORDER BY id SEPARATOR ', ') AS nros
                            FROM pago_pagos WHERE id_orden = %s AND estado <> 'anulado'""", (id_orden,))
    if vivos and vivos["n"]:
        raise ValueError(f"La orden {nro} tiene el pago {vivos['nros']} emitido. Anulá primero el pago —eso "
                         "revierte el libro de fondos, las retenciones y las aplicaciones— y después la orden.")
    motivo = (motivo or "").strip()[:250] or "sin motivo"
    cur.execute("""UPDATE pago_ordenes SET estado = 'anulada', fecha_anulacion = NOW(), motivo_anulacion = %s,
                          id_usuario_anulacion = %s WHERE id = %s""", (motivo, id_usuario, id_orden))
    cur.execute("UPDATE me_expedientes SET id_orden_pago = NULL WHERE id_orden_pago = %s", (id_orden,))
    liberados = cur.rowcount
    reintegros = _recalcular_reintegros(cur, id_orden)
    log.info("orden %s (%s) anulada por usuario %s: %s | %s expedientes, %s reintegros",
             id_orden, orden["nro_orden"], id_usuario, motivo, liberados, reintegros)
    return {"nro_orden": nro, "clase": orden["clase"], "importe": float(orden["importe_total"] or 0),
            "expedientes_liberados": liberados, "reintegros_liberados": reintegros}


def _recalcular_reintegros(cur, id_orden: int) -> int:
    """Los reintegros de la orden anulada vuelven al estado que dice su saldo:
    sin otra orden viva, `aprobada`; con saldo, `pago_parcial`; sin saldo,
    `con_orden`. En gestion_adm volvían todos a `aprobada`, aunque tuvieran
    otra orden parcial viva. `v_reintegro_saldo` no cuenta las anuladas."""
    cur.execute("""SELECT r.id, s.en_ordenes, s.saldo,
                          (SELECT MAX(d.id_orden) FROM pago_ordenes_reintegro_det d
                             JOIN pago_ordenes o ON o.id = d.id_orden
                            WHERE d.id_reintegro = r.id AND o.estado <> 'anulada') AS ultima
                     FROM pago_ordenes_reintegro_det rd
                     JOIN c_reintegro_afiliados r ON r.id = rd.id_reintegro
                     JOIN v_reintegro_saldo s ON s.id_reintegro = r.id
                    WHERE rd.id_orden = %s AND r.estado IN ('con_orden', 'pago_parcial')""", (id_orden,))
    filas = cur.fetchall()
    for f in filas:
        estado = ("aprobada" if not f["en_ordenes"] else "pago_parcial" if (f["saldo"] or 0) > 0.009
                  else "con_orden")
        cur.execute("UPDATE c_reintegro_afiliados SET estado = %s, id_orden_pago = %s WHERE id = %s",
                    (estado, f["ultima"], f["id"]))
    return len(filas)
