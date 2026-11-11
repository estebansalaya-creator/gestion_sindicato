"""
tesoreria_panel.py — Panel de Control de Tesorería (`/tesoreria`, menú 61).

Portado de `gestion_adm/tesoreria_routes.index`, sin lo de la obra social
(débito automático) ni la posición por conciliación (`flujo_fondos`, que acá no
existe todavía: no hay conciliaciones). Una foto de hoy:

  - qué hay que hacer: órdenes por aprobar o por pagar, comprobantes liquidados
    sin orden, reintegros con saldo, transferencias que no salieron en un
    archivo, valores de terceros en cartera;
  - cuánto hay: el saldo del libro (`v_saldos_cuentas_fondos`) y el del
    extracto, por cuenta, con su diferencia;
  - el estado de los extractos de cada banco.

Cada número lleva a la pantalla donde se resuelve, si el usuario la tiene.

EL SALDO DEL LIBRO NO ES TODAVÍA LA PLATA QUE HAY
El historial de AEDA no se importó al libro de fondos: el saldo es el de lo
cargado en el sistema. Mientras ninguna cuenta tenga movimientos, el panel lo
dice en vez de mostrar ceros que parecen saldos.
"""

from __future__ import annotations

import datetime

from flask import Blueprint, flash, redirect, render_template, url_for

import transferencias_lote as tl
from db import get_connection, puede, validasesion
from pagos_datos import ESTADO_TIPO, ESTADOS_ORDEN
from tesoreria import TIPOS_CUENTA_TXT

tes_panel_bp = Blueprint("tes_panel", __name__, url_prefix="/tesoreria")

#: Estados de una orden que piden algo a Tesorería, en el orden del circuito.
ESTADOS_PANEL = ("borrador", "pendiente_aprobacion", "aprobada", "rechazada")


def _u(endpoint, permiso=None, **kw):
    """La URL si el usuario tiene la pantalla (o la opción de menú `permiso`,
    para una que no es opción de menú); si no, None: el número va sin enlace."""
    url = url_for(endpoint, **kw)
    return url if puede(url_for(permiso) if permiso else url.split("?")[0]) else None


@tes_panel_bp.route("")
def panel():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede(url_for("tes_panel.panel")):
        flash("!No tenés permiso para esa pantalla.")
        return redirect(url_for("menu"))
    hoy = datetime.date.today()
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Saldo del libro (lo registrado) y del extracto (lo que informa el
            # banco). La diferencia son los cheques en circulación y lo que
            # falta conciliar o cargar.
            cur.execute("""
                SELECT cf.id, cf.nombre, cf.tipo_de_cuenta, cf.cbu, cf.predeterminada,
                       b.nombre AS banco, e.simbolo AS moneda,
                       COALESCE(s.saldo, 0) AS saldo_libro, s.ultimo_movimiento,
                       (SELECT COUNT(*) FROM c_movimientos_de_fondos m
                         WHERE m.c_cuentas_de_fondosId = cf.id AND m.fecha_anulacion IS NULL) AS movimientos,
                       x.saldo_extracto, x.ultimo_extracto, x.ultimo_import, COALESCE(x.renglones, 0) AS renglones
                  FROM c_cuentas_de_fondos cf
                  LEFT JOIN c_especies e ON e.id = cf.c_especiesId
                  LEFT JOIN c_codigo_de_banco b ON b.id = cf.c_codigo_de_bancoId
                  LEFT JOIN v_saldos_cuentas_fondos s ON s.id_cuenta = cf.id
                  LEFT JOIN (SELECT c_cuentas_de_fondos_id AS id_cuenta,
                                    COALESCE(SUM(credito), 0) - COALESCE(SUM(debito), 0) AS saldo_extracto,
                                    MAX(fecham) AS ultimo_extracto, MAX(importado) AS ultimo_import,
                                    COUNT(*) AS renglones
                               FROM c_extractos_bancarios GROUP BY c_cuentas_de_fondos_id) x ON x.id_cuenta = cf.id
                 WHERE cf.habilitada = 1
                 ORDER BY FIELD(cf.tipo_de_cuenta, 'C', 'R', 'B', 'I'), cf.nombre""")
            cuentas = cur.fetchall()
            for c in cuentas:
                c["tipo_txt"] = TIPOS_CUENTA_TXT.get(c["tipo_de_cuenta"], c["tipo_de_cuenta"])
                c["diferencia"] = (float(c["saldo_libro"]) - float(c["saldo_extracto"])
                                   if c["renglones"] else None)
                c["dias_extracto"] = (hoy - c["ultimo_extracto"]).days if c["ultimo_extracto"] else None

            cur.execute("""SELECT estado, COUNT(*) AS cant, COALESCE(SUM(importe_total), 0) AS total
                             FROM pago_ordenes GROUP BY estado""")
            por_estado = {r["estado"]: r for r in cur.fetchall()}

            cur.execute("""SELECT COUNT(*) AS cant, COALESCE(SUM(saldo_pendiente), 0) AS total
                             FROM v_expedientes_liquidados_impagos""")
            liquidados = cur.fetchone()

            cur.execute("""SELECT COUNT(*) AS cant, COALESCE(SUM(importe), 0) AS total,
                                  SUM(fecha_vencimiento IS NOT NULL AND fecha_vencimiento <= CURDATE()) AS para_depositar
                             FROM c_valores_de_terceros WHERE estado = 'en_cartera'""")
            cartera = cur.fetchone()

            pendientes = tl.pagos_transferibles(cur, limite=5000)
            sin_destino = sum(1 for p in pendientes if p["motivo"])
            transf = {"cant": len(pendientes), "sin_destino": sin_destino,
                      "total": sum(float(p["importe"] or 0) for p in pendientes),
                      "desde": min((p["fecha_pago"] for p in pendientes), default=None)}

    try:
        import reintegros_datos
        con_saldo = reintegros_datos.listar_con_saldo()
        reintegros = {"cant": len(con_saldo), "total": sum(float(r["saldo"] or 0) for r in con_saldo)}
    except Exception as e:                                      # noqa: BLE001
        reintegros = None
        flash(f"!No se pudieron leer los reintegros con saldo: {e}")

    estados_txt = dict(ESTADOS_ORDEN)
    ordenes = [{"estado": k, "texto": estados_txt.get(k, k), "tipo": ESTADO_TIPO.get(k, "neutro"),
                "cant": (por_estado.get(k) or {}).get("cant", 0), "total": (por_estado.get(k) or {}).get("total", 0)}
               for k in ESTADOS_PANEL]
    libro_vacio = not any(c["movimientos"] for c in cuentas)

    accesos = [(t, u) for t, u in [
        ("Emisión de pagos", _u("pagos.emision")),
        ("Transferencias masivas", _u("transferencias.index")),
        ("Subdiario", _u("tes_mov.subdiario")),
        ("Orden de ingreso", _u("tes_mov.orden_ingreso")),
        ("Movimiento entre cuentas", _u("tes_mov.movimiento_nuevo", operacion="transferencia")),
    ] if u]
    return render_template(
        "tesoreria/panel.html", hoy=hoy, cuentas=cuentas, ordenes=ordenes, liquidados=liquidados,
        cartera=cartera, transf=transf, reintegros=reintegros, libro_vacio=libro_vacio, accesos=accesos,
        bancos=[c for c in cuentas if c["tipo_de_cuenta"] == "B"],
        total_libro=sum(float(c["saldo_libro"]) for c in cuentas if c["moneda"] in (None, "$")),
        url_ordenes=_u("pagos.ordenes"), url_emision=_u("pagos.emision"),
        url_nueva_orden=_u("pagos.nueva", permiso="pagos.ordenes"),
        url_reintegros=_u("reintegros.ordenes"), url_transf=_u("transferencias.index"),
        url_subdiario=_u("tes_mov.subdiario"),
        url_deposito=_u("tes_mov.movimiento_nuevo", operacion="deposito"), url_cuentas=_u("tesoreria.cuentas_fondos"))
