"""
tesoreria_movimientos.py — Movimientos de fondos de Tesorería.

Portado de `gestion_adm/tesoreria_routes.py` con el sistema de estilos de acá:

    /tesoreria/movimientos                   Subdiario de Cuentas de Fondos (menú 65)
    /tesoreria/movimientos/nuevo/<operacion> transferencia (62), deposito (63), extraccion (64)
    /tesoreria/nueva_orden_concepto         Orden de Ingreso (56)
    /tesoreria/anulaciones                   Anulaciones (74); /anular POST
    /tesoreria/movimiento/<id>               ficha del movimiento entre cuentas
    /tesoreria/ingreso/<id>                  ficha de la orden de ingreso

Todo escribe en el libro único de tesorería (`c_movimientos_de_fondos`) con
`movimientos_fondos.py`, el mismo que usa el circuito de pagos.

QUÉ CAMBIA RESPECTO DE GESTION_ADM
- El permiso es la opción de menú, controlado también en los POST. Las fichas
  las ve quien tenga cualquiera de estas pantallas.
- Cada operación valida el tipo de las cuentas en el servidor: una extracción
  sale de un banco y entra a una caja, aunque alguien arme el POST a mano.
- No se carga nada con fecha de un período contable cerrado (la misma regla
  que impide anularlo, `anulaciones._fuera_de_periodo`).
- La orden de ingreso se numera con su fecha (AAMM de la orden), no con la de
  hoy: una orden de octubre cargada en noviembre es 2610-…
- Anular una orden de ingreso con cheques de terceros: si siguen en cartera
  pasan a «anulado»; si alguno ya se depositó, no se anula (antes quedaban en
  cartera cheques de una orden anulada, y se podían depositar).
- Anular un pago desde acá es del rol Administrador, como en la ficha de la orden.
- Un pago importado de AEDA (`nro_pago` AEDA-PG-…) no se anula acá: se anula en
  AEDA y `importar_aeda_cc_proveedores.py` lo trae anulado.
- El subdiario trae el filtro completo (tope `TOPE_SUBDIARIO`) para que la
  grilla ordene, filtre y exporte como todas. El saldo corre solo con una
  cuenta elegida y sin filtros de origen ni de importe: con ellos, la columna
  no sería el saldo de nada.

Sin PDF de la ficha todavía (gestion_adm usa su `exportar_pdf`, que acá no
está): la ficha se imprime desde el navegador.
"""

from __future__ import annotations

import datetime
import logging

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

import anulaciones
import movimientos_fondos as mf
import pago_anulacion
from db import get_connection, puede, tiene_rol, validasesion
from empleadores import cuit_valido
from numeracion import proximo_numero, sql_nro_orden_visible, sql_nro_visible
from pagos_datos import leer_importe
from tesoreria import TIPOS_CUENTA_TXT

log = logging.getLogger(__name__)

tes_mov_bp = Blueprint("tes_mov", __name__, url_prefix="/tesoreria")

#: Filas que trae el subdiario como máximo. Con más, se avisa y se pide acotar.
TOPE_SUBDIARIO = 5000

ETIQUETA_TIPO = {
    "movimiento_entre_cuentas": "Entre cuentas",
    "deposito_bancario":        "Depósito bancario",
    "extraccion_bancaria":      "Extracción bancaria",
    "inversiones":              "Inversión",
}
ORIGENES = {"pago": "Pago", "ingreso": "Orden de ingreso", "movimiento": "Entre cuentas",
            "cobranza": "Cobranza"}
TIPOS_ANULABLES = {"pago": "Pagos", "ingreso": "Órdenes de ingreso", "movimiento": "Movimientos entre cuentas"}
#: Un pago importado de AEDA se anula en AEDA: el importador lo trae anulado
#: (importar_aeda_cc_proveedores.py). Anularlo acá dejaría las dos bases distintas.
IMPEDIMENTO_AEDA = "vino de AEDA: se anula allá y el importador trae la anulación"
TIPOS_VALOR = [("cheque", "Cheque"), ("echeq", "E-cheq"), ("pagare", "Pagaré"), ("otro", "Otro")]

#: Las tres operaciones entre cuentas propias. `sale` / `entra`: tipos de
#: cuenta admitidos (None = cualquiera menos inversión, que tiene su pantalla).
OPERACIONES = {
    "transferencia": {"tipo": "movimiento_entre_cuentas", "titulo": "Movimiento entre cuentas",
                      "ayuda": "Plata que pasa de una cuenta propia a otra. No hay tercero.",
                      "sale": None, "entra": None},
    "deposito":      {"tipo": "deposito_bancario", "titulo": "Depósito bancario",
                      "ayuda": "Efectivo de la caja o valores de la cartera que se depositan en un banco. "
                               "Los cheques elegidos pasan a depositados.",
                      "sale": ("R", "C"), "entra": ("B",)},
    "extraccion":    {"tipo": "extraccion_bancaria", "titulo": "Extracción bancaria",
                      "ayuda": "Efectivo del banco para la caja. Sale con cheques propios: el banco los "
                               "informa de a uno, y así se concilian.",
                      "sale": ("B",), "entra": ("C",)},
}

#: A quién se le pagó, según la clase de la orden (las clases del sindicato).
BENEFICIARIO = """
    CASE o.clase
      WHEN 'proveedor' THEN (SELECT GROUP_CONCAT(DISTINCT e.razon_social_emisor SEPARATOR ' / ')
                               FROM pago_ordenes_detalle d JOIN me_expedientes e ON e.id = d.id_expediente
                              WHERE d.id_orden = o.id)
      WHEN 'anticipo'  THEN (SELECT GROUP_CONCAT(DISTINCT pr.razon_social SEPARATOR ' / ')
                               FROM pago_ordenes_anticipo_det ad JOIN c_proveedores pr ON pr.id = ad.id_proveedor
                              WHERE ad.id_orden = o.id)
      WHEN 'reintegro' THEN (SELECT GROUP_CONCAT(DISTINCT rd.nombre SEPARATOR ' / ')
                               FROM pago_ordenes_reintegro_det rd WHERE rd.id_orden = o.id)
      WHEN 'concepto'  THEN (SELECT GROUP_CONCAT(DISTINCT cd.descripcion SEPARATOR ' / ')
                               FROM pago_ordenes_concepto_det cd WHERE cd.id_orden = o.id)
    END"""


# =============================================================================
# Comunes
# =============================================================================

def _uid():
    return session.get("sind_usuario_id")


def _url(endpoint, **kw) -> str:
    return url_for(endpoint, **kw)


def _pantallas() -> list[str]:
    """Las URLs de este módulo que son opciones de menú."""
    return ([_url("tes_mov.subdiario"), _url("tes_mov.orden_ingreso"), _url("tes_mov.anulaciones_lista")]
            + [_url("tes_mov.movimiento_nuevo", operacion=o) for o in OPERACIONES])


def _guardia(urls):
    if not validasesion():
        return redirect(url_for("login"))
    if not any(puede(u) for u in urls):
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


def _fecha_valida(cur, fecha) -> str | None:
    """El error si no se puede registrar con esa fecha."""
    if not fecha:
        return "Falta la fecha (o no es una fecha)."
    if fecha > datetime.date.today():
        return "La fecha no puede ser posterior a hoy."
    fuera = anulaciones._fuera_de_periodo(cur, fecha)
    if fuera:
        return f"No se puede registrar: {fuera}."
    return None


def _cuentas(cur, solo_habilitadas=True) -> list[dict]:
    cur.execute(f"""SELECT id, nombre, tipo_de_cuenta, habilitada FROM c_cuentas_de_fondos
                     {'WHERE habilitada = 1' if solo_habilitadas else ''}
                     ORDER BY habilitada DESC, tipo_de_cuenta, nombre""")
    filas = cur.fetchall()
    for c in filas:
        c["tipo_txt"] = TIPOS_CUENTA_TXT.get(c["tipo_de_cuenta"], c["tipo_de_cuenta"])
        c["texto"] = f"{c['nombre']} · {c['tipo_txt']}" + ("" if c["habilitada"] else " (deshabilitada)")
    return filas


# =============================================================================
# Subdiario de cuentas de fondos
# =============================================================================

def _filtros(args) -> dict:
    """Por defecto el mes en curso. `desde=` vacío en la URL es alguien que borró
    la fecha a propósito: se respeta (se mira si el parámetro viene, no si tiene valor)."""
    hoy = datetime.date.today()
    if "desde" in args or "hasta" in args:
        desde, hasta = _fecha(args.get("desde")), _fecha(args.get("hasta"))
    else:
        desde, hasta = hoy.replace(day=1), hoy
    origen = args.get("origen") or ""
    return {"cuenta": args.get("cuenta", type=int), "origen": origen if origen in ORIGENES else "",
            "desde": desde, "hasta": hasta,
            "imp_desde": leer_importe(args.get("imp_desde")), "imp_hasta": leer_importe(args.get("imp_hasta")),
            "imp_desde_txt": (args.get("imp_desde") or "").strip(),
            "imp_hasta_txt": (args.get("imp_hasta") or "").strip(),
            "anulados": args.get("anulados") == "1"}


@tes_mov_bp.route("/movimientos")
def subdiario():
    salida = _guardia([_url("tes_mov.subdiario")])
    if salida:
        return salida
    f = _filtros(request.args)
    where, params = ["1 = 1"], []
    if f["cuenta"]:
        where.append("mf.c_cuentas_de_fondosId = %s"); params.append(f["cuenta"])
    if f["origen"]:
        # El origen es el comprobante que tiene el renglón: `tipo_origen` no lo
        # completa nadie (movimientos_fondos._sincronizar no lo escribe).
        where.append(f"mf.{mf.COLUMNA_ORIGEN[f['origen']]} IS NOT NULL")
    if f["desde"]:
        where.append("mf.fecha >= %s"); params.append(f["desde"])
    if f["hasta"]:
        where.append("mf.fecha <= %s"); params.append(f["hasta"])
    # Cada renglón es debe o haber: GREATEST da el importe sin preguntar de qué lado cayó.
    if f["imp_desde"] is not None:
        where.append("GREATEST(mf.importe_debe, mf.importe_haber) >= %s"); params.append(f["imp_desde"])
    if f["imp_hasta"] is not None:
        where.append("GREATEST(mf.importe_debe, mf.importe_haber) <= %s"); params.append(f["imp_hasta"])
    if not f["anulados"]:
        where.append("mf.fecha_anulacion IS NULL")
    # El saldo corre solo si la columna es el saldo de una cuenta: una cuenta
    # elegida y ningún filtro que deje renglones afuera.
    con_saldo = bool(f["cuenta"]) and not f["origen"] and f["imp_desde"] is None and f["imp_hasta"] is None

    with get_connection() as conn:
        with conn.cursor() as cur:
            cuentas = _cuentas(cur, solo_habilitadas=False)
            saldo_anterior = 0.0
            if con_saldo and f["desde"]:
                # El arrastre: lo que la cuenta traía antes del corte.
                cur.execute("""SELECT COALESCE(SUM(importe_debe - importe_haber), 0) AS s FROM c_movimientos_de_fondos
                                WHERE c_cuentas_de_fondosId = %s AND fecha < %s AND fecha_anulacion IS NULL""",
                            (f["cuenta"], f["desde"]))
                saldo_anterior = float(cur.fetchone()["s"] or 0)
            cur.execute(f"""
                SELECT mf.id, mf.fecha, mf.tipo_origen, mf.concepto, mf.importe_debe, mf.importe_haber,
                       mf.fecha_anulacion, mf.motivo_anulacion, c.nombre AS cuenta, c.tipo_de_cuenta,
                       mf.pago_pagosId AS id_pago, mf.ingreso_ordenesId AS id_ingreso,
                       mf.c_movimiento_entre_cuentasId AS id_movimiento, mf.c_comprobantes_emitidosId AS id_cobranza,
                       p.id_orden,
                       {sql_nro_visible('p')} AS nro_pago, ({BENEFICIARIO}) AS beneficiario,
                       io.nro_orden AS nro_ingreso
                  FROM c_movimientos_de_fondos mf
                  JOIN c_cuentas_de_fondos c ON c.id = mf.c_cuentas_de_fondosId
                  LEFT JOIN pago_pagos p   ON p.id = mf.pago_pagosId
                  LEFT JOIN pago_ordenes o ON o.id = p.id_orden
                  LEFT JOIN ingreso_ordenes io ON io.id = mf.ingreso_ordenesId
                 WHERE {' AND '.join(where)}
                 ORDER BY mf.fecha, mf.id
                 LIMIT %s
            """, params + [TOPE_SUBDIARIO + 1])
            filas = cur.fetchall()

    excedido = len(filas) > TOPE_SUBDIARIO
    filas = filas[:TOPE_SUBDIARIO]
    saldo, debe, haber = saldo_anterior, 0.0, 0.0
    for m in filas:
        d, h = float(m["importe_debe"] or 0), float(m["importe_haber"] or 0)
        if not m["fecha_anulacion"]:          # anulado: se lista, pero no movió plata
            saldo += d - h
            debe += d
            haber += h
        m["saldo"] = saldo
        origen = ("movimiento" if m["id_movimiento"] else "pago" if m["id_pago"] else "ingreso" if m["id_ingreso"]
                  else "cobranza" if m["id_cobranza"] else m["tipo_origen"])
        m["origen_txt"] = ORIGENES.get(origen, origen or "—")
        if m["id_movimiento"]:
            m["numero"] = f"MOV-{m['id_movimiento']}"
        elif m["id_pago"]:
            m["numero"] = m["nro_pago"]
        elif m["id_ingreso"]:
            m["numero"] = m["nro_ingreso"]
        else:
            m["numero"] = ""
    nuevas = [(o, op["titulo"]) for o, op in OPERACIONES.items()
              if puede(_url("tes_mov.movimiento_nuevo", operacion=o))]
    return render_template("tesoreria/subdiario.html", filas=filas, cuentas=cuentas, f=f, origenes=ORIGENES,
                           con_saldo=con_saldo, saldo_anterior=saldo_anterior, debe=debe, haber=haber,
                           saldo_final=saldo, excedido=excedido, tope=TOPE_SUBDIARIO, nuevas=nuevas,
                           puede_ingreso=puede(_url("tes_mov.orden_ingreso")),
                           puede_ordenes=puede(_url("pagos.ordenes")))


# =============================================================================
# Movimiento entre cuentas, depósito y extracción
# =============================================================================

def _crear_movimiento(cur, tipo, fecha, id_sale, id_entra, importe, comentario, uid) -> int:
    """Cabecera y detalle: la que entrega al haber, la que recibe al debe."""
    cur.execute("""INSERT INTO c_movimiento_entre_cuentas (fecha_emision, tipo_movimiento, importe, comentario,
                                                            id_usuario_emision)
                   VALUES (%s, %s, %s, %s, %s)""", (fecha, tipo, importe, comentario, uid))
    id_mov = cur.lastrowid
    cur.executemany("""INSERT INTO c_movimiento_entre_cuentas_det (id_movimiento, id_cuenta_fondos, debe, haber, comentario)
                       VALUES (%s, %s, %s, %s, %s)""",
                    [(id_mov, id_sale, 0, importe, comentario), (id_mov, id_entra, importe, 0, comentario)])
    mf.registrar_movimiento(cur, id_mov)
    return id_mov


def _cuenta_admitida(c, tipos) -> bool:
    if not c or not c["habilitada"] or c["tipo_de_cuenta"] == "I":
        return False
    return tipos is None or c["tipo_de_cuenta"] in tipos


@tes_mov_bp.route("/movimientos/nuevo/<operacion>", methods=["GET", "POST"])
def movimiento_nuevo(operacion):
    if operacion not in OPERACIONES:
        flash("!Operación desconocida.")
        return redirect(url_for("menu"))
    salida = _guardia([_url("tes_mov.movimiento_nuevo", operacion=operacion)])
    if salida:
        return salida
    op, errores = OPERACIONES[operacion], []
    form = {"fecha": datetime.date.today().isoformat()}

    if request.method == "POST":
        form = request.form.to_dict()
        fecha = _fecha(request.form.get("fecha"))
        comentario = " ".join((request.form.get("comentario") or "").split())[:250] or None
        id_sale = request.form.get("id_cuenta_sale", type=int)
        id_entra = request.form.get("id_cuenta_entra", type=int)
        ids_valor = [int(v) for v in request.form.getlist("valor") if v.isdigit()]
        form["valores"] = set(ids_valor)
        form["cheques"] = list(zip(request.form.getlist("cheque_numero"), request.form.getlist("cheque_importe")))
        conn = get_connection()
        try:
            conn.begin()
            with conn.cursor() as cur:
                e = _fecha_valida(cur, fecha)
                if e:
                    raise ValueError(e)
                cur.execute("SELECT id, nombre, tipo_de_cuenta, habilitada FROM c_cuentas_de_fondos WHERE id IN (%s, %s)",
                            (id_sale or 0, id_entra or 0))
                por_id = {c["id"]: c for c in cur.fetchall()}

                valores = []
                if operacion == "deposito" and ids_valor:
                    # El importe lo definen los valores elegidos.
                    marcas = ",".join(["%s"] * len(ids_valor))
                    cur.execute(f"""SELECT id, importe, id_cuenta_fondos, nro_cheque, fecha_vencimiento
                                      FROM c_valores_de_terceros
                                     WHERE id IN ({marcas}) AND estado = 'en_cartera' FOR UPDATE""", ids_valor)
                    valores = cur.fetchall()
                    if len(valores) != len(ids_valor):
                        raise ValueError("Alguno de los valores dejó de estar en cartera. Volvé a elegirlos.")
                    adelantados = [v for v in valores if v["fecha_vencimiento"] and v["fecha_vencimiento"] > fecha]
                    if adelantados:
                        raise ValueError("Un cheque de pago diferido no se deposita antes de su fecha: "
                                         + ", ".join(f"{v['nro_cheque']} vence {v['fecha_vencimiento']:%d/%m/%Y}"
                                                     for v in adelantados[:4]) + ".")
                    carteras = {v["id_cuenta_fondos"] for v in valores}
                    if len(carteras) > 1:
                        raise ValueError("Los valores están en carteras distintas: hacé un depósito por cada una.")
                    id_sale = carteras.pop()
                    cur.execute("SELECT id, nombre, tipo_de_cuenta, habilitada FROM c_cuentas_de_fondos WHERE id = %s",
                                (id_sale,))
                    por_id[id_sale] = cur.fetchone()
                    importe = round(sum(float(v["importe"]) for v in valores), 2)
                else:
                    importe = leer_importe(request.form.get("importe")) or 0

                if not id_sale or not id_entra:
                    raise ValueError("Elegí las dos cuentas.")
                if id_sale == id_entra:
                    raise ValueError("Origen y destino no pueden ser la misma cuenta.")
                if not _cuenta_admitida(por_id.get(id_sale), op["sale"]):
                    raise ValueError(f"La cuenta de origen no sirve para un {op['titulo'].lower()}.")
                if not _cuenta_admitida(por_id.get(id_entra), op["entra"]):
                    raise ValueError(f"La cuenta de destino no sirve para un {op['titulo'].lower()}.")
                if importe <= 0:
                    raise ValueError("El importe tiene que ser mayor que cero.")

                cheques = []
                if operacion == "extraccion":
                    id_chequera = request.form.get("id_chequera", type=int)
                    cur.execute("SELECT * FROM c_chequeras WHERE id = %s AND c_cuentas_de_fondosId = %s FOR UPDATE",
                                (id_chequera or 0, id_sale))
                    q = cur.fetchone()
                    if not q:
                        raise ValueError("Elegí una chequera de la cuenta de origen.")
                    if not q["habilitada"]:
                        raise ValueError("La chequera está deshabilitada.")
                    vistos = set()
                    for n, im in form["cheques"]:
                        n, val = (n or "").strip(), leer_importe(im) or 0
                        if not n and not val:
                            continue
                        if not n.isdigit() or val <= 0:
                            raise ValueError("Cada cheque lleva número e importe.")
                        numero = int(n)
                        if not (q["numero_desde"] <= numero <= q["numero_hasta"]):
                            raise ValueError(f"El cheque {numero} está fuera de la chequera "
                                             f"({q['numero_desde']}–{q['numero_hasta']}).")
                        if numero in vistos:
                            raise ValueError(f"El cheque {numero} está dos veces.")
                        vistos.add(numero)
                        cur.execute("""SELECT 1 FROM c_debitos_creditos_bancarios
                                        WHERE c_chequerasId = %s AND cheque_numero = %s AND estado <> 'anulado' LIMIT 1""",
                                    (q["id"], numero))
                        if cur.fetchone():
                            raise ValueError(f"El cheque {numero} ya fue emitido.")
                        cheques.append({"numero": numero, "importe": val, "chequera": q["id"],
                                        "a_la_orden": (request.form.get("a_la_orden") or "").strip()[:100] or None,
                                        "fecha": fecha})
                    if not cheques:
                        raise ValueError("Cargá al menos un cheque.")
                    suma = round(sum(c["importe"] for c in cheques), 2)
                    if abs(suma - importe) > 0.01:
                        raise ValueError(f"Los cheques suman {_pesos(suma)} y la extracción es de {_pesos(importe)}.")

                uid = _uid()
                id_mov = _crear_movimiento(cur, op["tipo"], fecha, id_sale, id_entra, importe, comentario, uid)
                if cheques:
                    mf.registrar_cheques(cur, "movimiento", id_mov, id_sale, cheques)
                    proximo = max(c["numero"] for c in cheques) + 1
                    cur.execute("""UPDATE c_chequeras SET proximo_numero = GREATEST(proximo_numero, %s),
                                          habilitada = IF(GREATEST(proximo_numero, %s) > numero_hasta, 0, habilitada)
                                    WHERE id = %s""", (proximo, proximo, cheques[0]["chequera"]))
                for v in valores:
                    cur.execute("UPDATE c_valores_de_terceros SET estado = 'depositado', actualizado = NOW() WHERE id = %s",
                                (v["id"],))
                    cur.execute("""INSERT INTO c_valores_de_terceros_movimientos
                                       (id_valor, estado_anterior, estado_nuevo, motivo, id_movimiento_cuentas, id_usuario)
                                   VALUES (%s, 'en_cartera', 'depositado', %s, %s, %s)""",
                                (v["id"], f"Depósito MOV-{id_mov} del {fecha:%d/%m/%Y}", id_mov, uid))
            conn.commit()
        except ValueError as e:
            conn.rollback()
            errores.append(str(e))
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        if not errores:
            msg = f"MOV-{id_mov} registrado: {op['titulo'].lower()} por {_pesos(importe)}."
            if valores:
                msg += f" {len(valores)} valor(es) pasaron a depositados."
            if cheques:
                msg += " Cheques emitidos: " + ", ".join(str(c["numero"]) for c in cheques) + "."
            flash(msg)
            return redirect(url_for("tes_mov.movimiento", id_movimiento=id_mov))

    with get_connection() as conn:
        with conn.cursor() as cur:
            todas = [c for c in _cuentas(cur) if c["tipo_de_cuenta"] != "I"]
            valores_cartera, chequeras = [], []
            if operacion == "deposito":
                cur.execute("""SELECT v.id, v.tipo_valor, v.nro_cheque, v.importe, v.fecha_vencimiento,
                                      v.razon_social_librador, v.id_cuenta_fondos, c.nombre AS cuenta,
                                      b.nombre AS banco
                                 FROM c_valores_de_terceros v
                                 JOIN c_cuentas_de_fondos c ON c.id = v.id_cuenta_fondos
                                 LEFT JOIN c_codigo_de_banco b ON b.codigo = v.codigo_banco
                                WHERE v.estado = 'en_cartera'
                                ORDER BY v.fecha_vencimiento, v.id""")
                valores_cartera = cur.fetchall()
            if operacion == "extraccion":
                cur.execute("""SELECT q.id, q.c_cuentas_de_fondosId AS id_cuenta, q.descripcion, q.numero_desde,
                                      q.numero_hasta, q.proximo_numero
                                 FROM c_chequeras q
                                WHERE q.habilitada = 1 AND q.proximo_numero <= q.numero_hasta
                                ORDER BY q.numero_desde""")
                chequeras = cur.fetchall()
    return render_template("tesoreria/movimiento_nuevo.html", operacion=operacion, op=op, errores=errores,
                           form=form, hoy=datetime.date.today(),
                           cuentas_sale=[c for c in todas if _cuenta_admitida(c, op["sale"])],
                           cuentas_entra=[c for c in todas if _cuenta_admitida(c, op["entra"])],
                           valores_cartera=valores_cartera, chequeras=chequeras,
                           puede_subdiario=puede(_url("tes_mov.subdiario")))


@tes_mov_bp.route("/movimiento/<int:id_movimiento>")
def movimiento(id_movimiento):
    salida = _guardia(_pantallas())
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT m.*, u.nombre AS usuario_emision, ua.nombre AS usuario_anulacion
                             FROM c_movimiento_entre_cuentas m
                             LEFT JOIN s_usuarios u  ON u.id  = m.id_usuario_emision
                             LEFT JOIN s_usuarios ua ON ua.id = m.id_usuario_anulacion
                            WHERE m.id = %s""", (id_movimiento,))
            mov = cur.fetchone()
            if not mov:
                flash("!No existe ese movimiento.")
                return redirect(url_for("menu"))
            cur.execute("""SELECT d.*, c.nombre AS cuenta, c.tipo_de_cuenta
                             FROM c_movimiento_entre_cuentas_det d JOIN c_cuentas_de_fondos c ON c.id = d.id_cuenta_fondos
                            WHERE d.id_movimiento = %s ORDER BY d.haber DESC, d.id""", (id_movimiento,))
            lineas = cur.fetchall()
            cur.execute("""SELECT dc.cheque_numero, dc.importe_debito, dc.estado, dc.a_la_orden, q.descripcion AS chequera
                             FROM c_debitos_creditos_bancarios dc
                             JOIN c_movimientos_de_fondos m ON m.id = dc.c_movimientos_de_fondosId
                             LEFT JOIN c_chequeras q ON q.id = dc.c_chequerasId
                            WHERE m.c_movimiento_entre_cuentasId = %s AND dc.cheque_numero IS NOT NULL
                            ORDER BY dc.cheque_numero""", (id_movimiento,))
            cheques = cur.fetchall()
            cur.execute("""SELECT DISTINCT v.*, b.nombre AS banco
                             FROM c_valores_de_terceros_movimientos vm
                             JOIN c_valores_de_terceros v ON v.id = vm.id_valor
                             LEFT JOIN c_codigo_de_banco b ON b.codigo = v.codigo_banco
                            WHERE vm.id_movimiento_cuentas = %s ORDER BY v.fecha_vencimiento, v.id""", (id_movimiento,))
            valores = cur.fetchall()
            impedimentos = [] if mov["fecha_anulacion"] else anulaciones.motivos_para_no_anular(
                cur, "movimiento", id_movimiento, mov["fecha_emision"])
    for l in lineas:
        l["tipo_txt"] = TIPOS_CUENTA_TXT.get(l["tipo_de_cuenta"], "")
    return render_template("tesoreria/movimiento.html", mov=mov, lineas=lineas, cheques=cheques, valores=valores,
                           tipo_txt=ETIQUETA_TIPO.get(mov["tipo_movimiento"], mov["tipo_movimiento"]),
                           impedimentos=impedimentos, puede_anular=puede(_url("tes_mov.anulaciones_lista")),
                           puede_subdiario=puede(_url("tes_mov.subdiario")))


# =============================================================================
# Orden de ingreso
# =============================================================================

def _leer_orden(form) -> tuple[dict, list[str]]:
    """Lo que vino del formulario, ordenado, y los errores. No toca la base."""
    errores = []
    o = {"fecha": _fecha(form.get("fecha")), "fecha_txt": form.get("fecha") or "",
         "observaciones": (form.get("observaciones") or "").strip()[:2000] or None,
         "motivos": [], "cuentas": [], "valores": []}
    for i, (mid, desc, per, imp) in enumerate(zip(form.getlist("m_motivo"), form.getlist("m_descripcion"),
                                                   form.getlist("m_periodo"), form.getlist("m_importe")), 1):
        if not (mid or desc.strip() or imp.strip()):
            continue
        val = leer_importe(imp)
        if not mid.isdigit():
            errores.append(f"Motivo {i}: elegí el motivo de ingreso.")
        if not val or val <= 0:
            errores.append(f"Motivo {i}: el importe tiene que ser mayor que cero.")
        periodo = per.replace("-", "") if per else None
        if periodo and not (len(periodo) == 6 and periodo.isdigit()):
            errores.append(f"Motivo {i}: el período no es válido.")
        o["motivos"].append({"id_motivo": int(mid) if mid.isdigit() else None, "descripcion": " ".join(desc.split())[:200],
                             "periodo": periodo, "importe": val or 0, "importe_txt": imp})
    for i, (cid, imp) in enumerate(zip(form.getlist("c_cuenta"), form.getlist("c_importe")), 1):
        if not (cid or imp.strip()):
            continue
        val = leer_importe(imp)
        if not cid.isdigit():
            errores.append(f"Cuenta {i}: elegí la cuenta de fondos.")
        if not val or val <= 0:
            errores.append(f"Cuenta {i}: el importe tiene que ser mayor que cero.")
        o["cuentas"].append({"id_cuenta": int(cid) if cid.isdigit() else None, "importe": val or 0, "importe_txt": imp})
    campos = ("v_cuenta", "v_tipo", "v_numero", "v_banco", "v_cuit", "v_librador", "v_emision", "v_vencimiento", "v_importe")
    for i, fila in enumerate(zip(*(form.getlist(c) for c in campos)), 1):
        cid, tipo, nro, banco, cuit, libr, femi, fven, imp = fila
        if not (nro.strip() or imp.strip()):
            continue
        val = leer_importe(imp)
        cuit = "".join(ch for ch in cuit if ch.isdigit())
        v = {"id_cuenta": int(cid) if cid.isdigit() else None, "tipo_valor": tipo if tipo in dict(TIPOS_VALOR) else "cheque",
             "nro_cheque": nro.strip()[:8], "codigo_banco": banco or None, "cuit_librador": cuit or None,
             "razon_social_librador": " ".join(libr.split())[:200] or None,
             "fecha_emision": _fecha(femi), "fecha_vencimiento": _fecha(fven), "importe": val or 0, "importe_txt": imp}
        if not v["nro_cheque"]:
            errores.append(f"Valor {i}: falta el número.")
        if not val or val <= 0:
            errores.append(f"Valor {i}: el importe tiene que ser mayor que cero.")
        if cuit and not cuit_valido(cuit):
            errores.append(f"Valor {i}: el CUIT del librador {cuit} no verifica.")
        if v["fecha_emision"] and v["fecha_vencimiento"] and v["fecha_vencimiento"] < v["fecha_emision"]:
            errores.append(f"Valor {i}: vence antes de su emisión.")
        o["valores"].append(v)
    return o, errores


@tes_mov_bp.route("/nueva_orden_concepto", methods=["GET", "POST"])
def orden_ingreso():
    """Uno o varios motivos de ingreso; una o varias cuentas. Si entra a una
    cartera, se cargan los valores de terceros que la respaldan."""
    salida = _guardia([_url("tes_mov.orden_ingreso")])
    if salida:
        return salida
    errores = []
    hoy = datetime.date.today()
    o = {"fecha_txt": hoy.isoformat(), "motivos": [], "cuentas": [], "valores": []}

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, descripcion FROM c_motivos_de_ingreso WHERE activo = 1 ORDER BY descripcion")
            motivos = cur.fetchall()
            cuentas = [c for c in _cuentas(cur) if c["tipo_de_cuenta"] != "I"]
            cur.execute("SELECT codigo, nombre FROM c_codigo_de_banco ORDER BY codigo")
            bancos = cur.fetchall()

    if request.method == "POST":
        o, errores = _leer_orden(request.form)
        por_id = {c["id"]: c for c in cuentas}
        motivos_ok = {m["id"] for m in motivos}
        if not o["motivos"]:
            errores.append("Cargá al menos un motivo de ingreso.")
        if not o["cuentas"]:
            errores.append("Cargá al menos una cuenta de fondos.")
        for m in o["motivos"]:
            if m["id_motivo"] and m["id_motivo"] not in motivos_ok:
                errores.append("Hay un motivo que no existe o está inactivo.")
        ids = [c["id_cuenta"] for c in o["cuentas"] if c["id_cuenta"]]
        if len(ids) != len(set(ids)):
            errores.append("La misma cuenta está dos veces: sumá los importes en un renglón.")
        if any(i not in por_id for i in ids):
            errores.append("Hay una cuenta que no existe o está deshabilitada.")
        total_m = round(sum(m["importe"] for m in o["motivos"]), 2)
        total_c = round(sum(c["importe"] for c in o["cuentas"]), 2)
        if o["motivos"] and o["cuentas"] and abs(total_m - total_c) > 0.01:
            errores.append(f"Los motivos suman {_pesos(total_m)} y las cuentas {_pesos(total_c)}: tienen que dar lo mismo.")
        carteras = {c["id_cuenta"]: c["importe"] for c in o["cuentas"]
                    if c["id_cuenta"] in por_id and por_id[c["id_cuenta"]]["tipo_de_cuenta"] == "R"}
        for v in o["valores"]:
            if v["id_cuenta"] not in carteras:
                errores.append(f"El valor {v['nro_cheque'] or ''} va a una cuenta que no es una cartera de esta orden.")
        for cid, imp in carteras.items():
            suma = round(sum(v["importe"] for v in o["valores"] if v["id_cuenta"] == cid), 2)
            if abs(suma - imp) > 0.01:
                errores.append(f"«{por_id[cid]['nombre']}» es una cartera: los valores tienen que sumar "
                               f"{_pesos(imp)} y suman {_pesos(suma)}.")
        if not errores:
            conn = get_connection()
            try:
                conn.begin()
                with conn.cursor() as cur:
                    e = _fecha_valida(cur, o["fecha"])
                    if e:
                        raise ValueError(e)
                    uid = _uid()
                    nro = proximo_numero(cur, "ingreso_ordenes", o["fecha"])
                    cur.execute("""INSERT INTO ingreso_ordenes (nro_orden, clase, anio, fecha, estado, id_cuenta, importe_total,
                                                                 moneda, origen, observaciones, id_usuario_creacion)
                                   VALUES (%s, 'varios', %s, %s, 'confirmado', NULL, %s, 'ARS', 'manual', %s, %s)""",
                                (nro, o["fecha"].year, o["fecha"], total_m, o["observaciones"], uid))
                    id_orden = cur.lastrowid
                    nombres = {m["id"]: m["descripcion"] for m in motivos}
                    for m in o["motivos"]:
                        cur.execute("""INSERT INTO ingreso_ordenes_detalle (id_orden, tipo, id_motivo_ingreso, descripcion,
                                                                            importe, periodo)
                                       VALUES (%s, 'ingreso', %s, %s, %s, %s)""",
                                    (id_orden, m["id_motivo"], m["descripcion"] or nombres.get(m["id_motivo"], "Ingreso"),
                                     m["importe"], m["periodo"]))
                    for c in o["cuentas"]:
                        cur.execute("INSERT INTO ingreso_ordenes_cuentas (id_orden, id_cuenta_fondos, importe) VALUES (%s, %s, %s)",
                                    (id_orden, c["id_cuenta"], c["importe"]))
                    for v in o["valores"]:
                        cur.execute("""INSERT INTO c_valores_de_terceros
                                           (tipo_valor, nro_cheque, codigo_banco, cuit_librador, razon_social_librador,
                                            fecha_emision, fecha_vencimiento, importe, estado, id_cuenta_fondos, id_usuario_carga)
                                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'en_cartera', %s, %s)""",
                                    (v["tipo_valor"], v["nro_cheque"], v["codigo_banco"], v["cuit_librador"],
                                     v["razon_social_librador"], v["fecha_emision"], v["fecha_vencimiento"], v["importe"],
                                     v["id_cuenta"], uid))
                        cur.execute("""INSERT INTO c_valores_de_terceros_movimientos
                                           (id_valor, estado_anterior, estado_nuevo, motivo, id_ingreso, id_usuario)
                                       VALUES (%s, NULL, 'en_cartera', %s, %s, %s)""",
                                    (cur.lastrowid, f"Orden de ingreso {nro}", id_orden, uid))
                    # Al final: el libro saca de las cuentas ya cargadas a dónde entró la plata.
                    mf.registrar_ingreso(cur, id_orden)
                conn.commit()
            except ValueError as e:
                conn.rollback()
                errores.append(str(e))
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            if not errores:
                flash(f"Orden de ingreso {nro} registrada por {_pesos(total_m)}."
                      + (f" {len(o['valores'])} valor(es) en cartera." if o["valores"] else ""))
                return redirect(url_for("tes_mov.ingreso", id_orden=id_orden))

    return render_template("tesoreria/orden_ingreso.html", o=o, errores=errores, motivos=motivos, cuentas=cuentas,
                           bancos=bancos, tipos_valor=TIPOS_VALOR, periodo_actual=hoy.strftime("%Y-%m"),
                           puede_subdiario=puede(_url("tes_mov.subdiario")))


@tes_mov_bp.route("/ingreso/<int:id_orden>")
def ingreso(id_orden):
    salida = _guardia(_pantallas())
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT o.*, u.nombre AS usuario_creacion, ua.nombre AS usuario_anulacion
                             FROM ingreso_ordenes o
                             LEFT JOIN s_usuarios u  ON u.id  = o.id_usuario_creacion
                             LEFT JOIN s_usuarios ua ON ua.id = o.id_usuario_anulacion
                            WHERE o.id = %s""", (id_orden,))
            orden = cur.fetchone()
            if not orden:
                flash("!No existe esa orden de ingreso.")
                return redirect(url_for("menu"))
            cur.execute("""SELECT d.*, mi.descripcion AS motivo FROM ingreso_ordenes_detalle d
                             LEFT JOIN c_motivos_de_ingreso mi ON mi.id = d.id_motivo_ingreso
                            WHERE d.id_orden = %s ORDER BY d.id""", (id_orden,))
            motivos = cur.fetchall()
            cur.execute("""SELECT c.*, cf.nombre AS cuenta, cf.tipo_de_cuenta FROM ingreso_ordenes_cuentas c
                             JOIN c_cuentas_de_fondos cf ON cf.id = c.id_cuenta_fondos
                            WHERE c.id_orden = %s ORDER BY c.id""", (id_orden,))
            cuentas = cur.fetchall()
            # Los valores cuelgan del movimiento de estado, no de la orden: así
            # se sigue un cheque de la cartera al banco sin perder por qué entró.
            cur.execute("""SELECT v.*, cf.nombre AS cuenta, b.nombre AS banco
                             FROM c_valores_de_terceros_movimientos m
                             JOIN c_valores_de_terceros v ON v.id = m.id_valor
                             LEFT JOIN c_cuentas_de_fondos cf ON cf.id = v.id_cuenta_fondos
                             LEFT JOIN c_codigo_de_banco b ON b.codigo = v.codigo_banco
                            WHERE m.id_ingreso = %s AND m.estado_anterior IS NULL
                            ORDER BY v.fecha_vencimiento, v.id""", (id_orden,))
            valores = cur.fetchall()
            impedimentos = [] if orden["estado"] == "anulado" else _impedimentos_ingreso(cur, id_orden, orden["fecha"])
    for c in cuentas:
        c["tipo_txt"] = TIPOS_CUENTA_TXT.get(c["tipo_de_cuenta"], "")
    return render_template("tesoreria/ingreso.html", orden=orden, motivos=motivos, cuentas=cuentas, valores=valores,
                           impedimentos=impedimentos, puede_anular=puede(_url("tes_mov.anulaciones_lista")),
                           puede_subdiario=puede(_url("tes_mov.subdiario")))


# =============================================================================
# Anulaciones
# =============================================================================

def _impedimentos_ingreso(cur, id_orden, fecha) -> list[str]:
    """Los de anulaciones.py más uno propio: un cheque de la orden que ya salió
    de la cartera (se depositó, se rechazó) ata la orden a lo que pasó después."""
    motivos = anulaciones.motivos_para_no_anular(cur, "ingreso", id_orden, fecha)
    cur.execute("""SELECT v.nro_cheque, v.estado FROM c_valores_de_terceros_movimientos m
                     JOIN c_valores_de_terceros v ON v.id = m.id_valor
                    WHERE m.id_ingreso = %s AND m.estado_anterior IS NULL AND v.estado NOT IN ('en_cartera', 'anulado')""",
                (id_orden,))
    for v in cur.fetchall():
        motivos.append(f"el valor {v['nro_cheque']} ya no está en cartera ({v['estado']})")
    return motivos


def _impedimentos_movimiento(cur, id_mov, fecha) -> list[str]:
    motivos = anulaciones.motivos_para_no_anular(cur, "movimiento", id_mov, fecha)
    cur.execute("""SELECT DISTINCT v.nro_cheque, v.estado FROM c_valores_de_terceros_movimientos vm
                     JOIN c_valores_de_terceros v ON v.id = vm.id_valor
                    WHERE vm.id_movimiento_cuentas = %s AND vm.estado_nuevo = 'depositado' AND v.estado <> 'depositado'""",
                (id_mov,))
    for v in cur.fetchall():
        motivos.append(f"el cheque {v['nro_cheque']} ya está {v['estado']}")
    return motivos


def _filtros_anulaciones(args) -> dict:
    """Los últimos 90 días por defecto: el mes en curso y los dos anteriores,
    que es donde cae lo que se corrige (en gestion_adm el día 1 del mes
    escondía justo lo que se venía a anular)."""
    hoy = datetime.date.today()
    if "desde" in args or "hasta" in args:
        desde, hasta = _fecha(args.get("desde")), _fecha(args.get("hasta"))
    else:
        desde, hasta = hoy - datetime.timedelta(days=90), hoy
    tipo = args.get("tipo") or ""
    return {"tipo": tipo if tipo in TIPOS_ANULABLES else "", "desde": desde, "hasta": hasta}


def _anulables(cur, f) -> list[dict]:
    """Lo vigente de los tres circuitos, con la misma forma: origen, número,
    fecha, a quién, cuenta e importe."""
    filas = []
    if f["tipo"] in ("", "pago"):
        where, params = ["p.estado <> 'anulado'"], []
        if f["desde"]: where.append("p.fecha_pago >= %s"); params.append(f["desde"])
        if f["hasta"]: where.append("p.fecha_pago <= %s"); params.append(f["hasta"])
        cur.execute(f"""
            SELECT p.id, {sql_nro_visible('p')} AS numero, p.nro_pago, p.fecha_pago AS fecha, p.importe_total AS importe,
                   p.observaciones, p.id_orden, {sql_nro_orden_visible('o')} AS nro_orden, o.clase,
                   ({BENEFICIARIO}) AS beneficiario,
                   (SELECT GROUP_CONCAT(DISTINCT c.nombre SEPARATOR ' / ') FROM pago_pagos_instrumentos i
                      JOIN c_cuentas_de_fondos c ON c.id = i.id_cuenta_fondos WHERE i.id_pago = p.id) AS cuenta
              FROM pago_pagos p JOIN pago_ordenes o ON o.id = p.id_orden
             WHERE {' AND '.join(where)}
             ORDER BY p.fecha_pago DESC, p.id DESC LIMIT 500""", params)
        for r in cur.fetchall():
            filas.append({"origen": "pago", "tipo_txt": "Pago", "id": r["id"], "numero": r["numero"],
                          "fecha": r["fecha"], "importe": float(r["importe"] or 0), "cuenta": r["cuenta"] or "",
                          "quien": r["beneficiario"] or "", "detalle": r["observaciones"] or "",
                          "sub": f"Orden {r['nro_orden']} · {r['clase']}", "id_orden": r["id_orden"],
                          "de_aeda": (r["nro_pago"] or "").startswith("AEDA-")})
    if f["tipo"] in ("", "ingreso"):
        where, params = ["io.estado <> 'anulado'"], []
        if f["desde"]: where.append("io.fecha >= %s"); params.append(f["desde"])
        if f["hasta"]: where.append("io.fecha <= %s"); params.append(f["hasta"])
        cur.execute(f"""
            SELECT io.id, io.nro_orden AS numero, io.fecha, io.importe_total AS importe, io.observaciones,
                   (SELECT GROUP_CONCAT(DISTINCT COALESCE(mi.descripcion, d.descripcion) SEPARATOR ' / ')
                      FROM ingreso_ordenes_detalle d LEFT JOIN c_motivos_de_ingreso mi ON mi.id = d.id_motivo_ingreso
                     WHERE d.id_orden = io.id) AS motivos,
                   COALESCE((SELECT GROUP_CONCAT(DISTINCT c.nombre SEPARATOR ' / ') FROM ingreso_ordenes_cuentas ioc
                               JOIN c_cuentas_de_fondos c ON c.id = ioc.id_cuenta_fondos WHERE ioc.id_orden = io.id),
                            (SELECT c2.nombre FROM c_cuentas_de_fondos c2 WHERE c2.id = io.id_cuenta)) AS cuenta
              FROM ingreso_ordenes io
             WHERE {' AND '.join(where)}
             ORDER BY io.fecha DESC, io.id DESC LIMIT 500""", params)
        for r in cur.fetchall():
            filas.append({"origen": "ingreso", "tipo_txt": "Orden de ingreso", "id": r["id"], "numero": r["numero"],
                          "fecha": r["fecha"], "importe": float(r["importe"] or 0), "cuenta": r["cuenta"] or "",
                          "quien": r["motivos"] or "", "detalle": r["observaciones"] or "", "sub": ""})
    if f["tipo"] in ("", "movimiento"):
        where, params = ["m.fecha_anulacion IS NULL"], []
        if f["desde"]: where.append("m.fecha_emision >= %s"); params.append(f["desde"])
        if f["hasta"]: where.append("m.fecha_emision <= %s"); params.append(f["hasta"])
        cur.execute(f"""
            SELECT m.id, m.fecha_emision AS fecha, m.tipo_movimiento, m.importe, m.comentario,
                   (SELECT GROUP_CONCAT(c.nombre ORDER BY d.haber DESC SEPARATOR ' → ')
                      FROM c_movimiento_entre_cuentas_det d JOIN c_cuentas_de_fondos c ON c.id = d.id_cuenta_fondos
                     WHERE d.id_movimiento = m.id) AS cuenta
              FROM c_movimiento_entre_cuentas m
             WHERE {' AND '.join(where)}
             ORDER BY m.fecha_emision DESC, m.id DESC LIMIT 500""", params)
        for r in cur.fetchall():
            filas.append({"origen": "movimiento", "tipo_txt": ETIQUETA_TIPO.get(r["tipo_movimiento"], r["tipo_movimiento"]),
                          "id": r["id"], "numero": f"MOV-{r['id']}", "fecha": r["fecha"],
                          "importe": float(r["importe"] or 0), "cuenta": r["cuenta"] or "", "quien": "",
                          "detalle": r["comentario"] or "", "sub": ""})
    filas.sort(key=lambda x: (x["fecha"] or datetime.date.min, x["numero"] or ""), reverse=True)
    return filas


@tes_mov_bp.route("/anulaciones")
def anulaciones_lista():
    salida = _guardia([_url("tes_mov.anulaciones_lista")])
    if salida:
        return salida
    f = _filtros_anulaciones(request.args)
    admin = tiene_rol("Administrador")
    with get_connection() as conn:
        with conn.cursor() as cur:
            filas = _anulables(cur, f)
            # Por qué NO se puede, calculado al dibujar: evita el intento a ciegas.
            # Se vuelve a validar al anular, porque entre una cosa y otra puede cambiar todo.
            for x in filas:
                if x["origen"] == "pago":
                    x["impedimentos"] = anulaciones.motivos_para_no_anular(cur, "pago", x["id"], x["fecha"])
                    if x["de_aeda"]:
                        x["impedimentos"].insert(0, IMPEDIMENTO_AEDA)
                    if not admin:
                        x["impedimentos"].insert(0, "anular un pago es de Administrador")
                elif x["origen"] == "ingreso":
                    x["impedimentos"] = _impedimentos_ingreso(cur, x["id"], x["fecha"])
                else:
                    x["impedimentos"] = _impedimentos_movimiento(cur, x["id"], x["fecha"])
    return render_template("tesoreria/anulaciones.html", filas=filas, f=f, tipos=TIPOS_ANULABLES,
                           anulables=sum(1 for x in filas if not x["impedimentos"]),
                           puede_ordenes=puede(_url("pagos.ordenes")))


@tes_mov_bp.route("/anulaciones/anular", methods=["POST"])
def anular():
    salida = _guardia([_url("tes_mov.anulaciones_lista")])
    if salida:
        return salida
    origen = request.form.get("origen") or ""
    id_ref = request.form.get("id", type=int)
    motivo = " ".join((request.form.get("motivo") or "").split())[:250]
    volver = url_for("tes_mov.anulaciones_lista", tipo=request.form.get("tipo") or None,
                     desde=request.form.get("desde") or "", hasta=request.form.get("hasta") or "")
    if origen not in TIPOS_ANULABLES or not id_ref:
        flash("!No sé qué comprobante anular.")
        return redirect(volver)
    if not motivo:
        flash("!Para anular hay que decir por qué.")
        return redirect(volver)
    if origen == "pago" and not tiene_rol("Administrador"):
        flash("!Anular un pago es una acción de Administrador.")
        return redirect(volver)
    uid = _uid()
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            if origen == "pago":
                cur.execute("SELECT nro_pago FROM pago_pagos WHERE id = %s", (id_ref,))
                if ((cur.fetchone() or {}).get("nro_pago") or "").startswith("AEDA-"):
                    raise ValueError("No se puede anular porque " + IMPEDIMENTO_AEDA + ".")
                r = pago_anulacion.anular(cur, id_ref, motivo, uid)
                msg = f"Pago {r['nro_pago']} anulado."
                if r["expedientes"]:
                    msg += f" {r['expedientes']} comprobante(s) vuelven a impagos."
                if r["orden_reabierta"]:
                    msg += f" La orden {r['nro_orden']} volvió a «aprobada»."
                if r["certificados_en_sire"]:
                    msg = "!" + msg + f" {r['certificados_en_sire']} certificado(s) ya estaban en SIRE: hay que rectificar."
            elif origen == "movimiento":
                cur.execute("""SELECT fecha_emision FROM c_movimiento_entre_cuentas
                                WHERE id = %s AND fecha_anulacion IS NULL FOR UPDATE""", (id_ref,))
                mov = cur.fetchone()
                if not mov:
                    raise ValueError("El movimiento no existe o ya estaba anulado.")
                imp = _impedimentos_movimiento(cur, id_ref, mov["fecha_emision"])
                if imp:
                    raise ValueError("No se puede anular porque " + "; ".join(imp) + ".")
                cur.execute("""SELECT DISTINCT v.id FROM c_valores_de_terceros v
                                 JOIN c_valores_de_terceros_movimientos vm ON vm.id_valor = v.id
                                WHERE vm.id_movimiento_cuentas = %s AND vm.estado_nuevo = 'depositado' FOR UPDATE""",
                            (id_ref,))
                valores = [x["id"] for x in cur.fetchall()]
                cur.execute("""UPDATE c_movimiento_entre_cuentas SET fecha_anulacion = NOW(), motivo_anulacion = %s,
                                      id_usuario_anulacion = %s WHERE id = %s""", (motivo, uid, id_ref))
                mf.anular(cur, "movimiento", id_ref, motivo, uid)
                # Los cheques emitidos de una extracción quedan anulados (se pueden volver a usar los números).
                cur.execute("""UPDATE c_debitos_creditos_bancarios dc
                                 JOIN c_movimientos_de_fondos m ON m.id = dc.c_movimientos_de_fondosId
                                  SET dc.estado = 'anulado' WHERE m.c_movimiento_entre_cuentasId = %s""", (id_ref,))
                for v in valores:   # los cheques del depósito vuelven a cartera
                    cur.execute("UPDATE c_valores_de_terceros SET estado = 'en_cartera', actualizado = NOW() WHERE id = %s", (v,))
                    cur.execute("""INSERT INTO c_valores_de_terceros_movimientos
                                       (id_valor, estado_anterior, estado_nuevo, motivo, id_movimiento_cuentas, id_usuario)
                                   VALUES (%s, 'depositado', 'en_cartera', %s, %s, %s)""",
                                (v, f"Anulación de MOV-{id_ref}: {motivo}"[:200], id_ref, uid))
                msg = f"MOV-{id_ref} anulado." + (f" {len(valores)} valor(es) vuelven a cartera." if valores else "")
            else:
                cur.execute("SELECT fecha, nro_orden FROM ingreso_ordenes WHERE id = %s AND estado <> 'anulado' FOR UPDATE",
                            (id_ref,))
                oi = cur.fetchone()
                if not oi:
                    raise ValueError("La orden no existe o ya estaba anulada.")
                imp = _impedimentos_ingreso(cur, id_ref, oi["fecha"])
                if imp:
                    raise ValueError("No se puede anular porque " + "; ".join(imp) + ".")
                cur.execute("""UPDATE ingreso_ordenes SET estado = 'anulado', fecha_anulacion = NOW(), motivo_anulacion = %s,
                                      id_usuario_anulacion = %s WHERE id = %s""", (motivo, uid, id_ref))
                mf.anular(cur, "ingreso", id_ref, motivo, uid)
                cur.execute("""SELECT v.id FROM c_valores_de_terceros_movimientos m JOIN c_valores_de_terceros v ON v.id = m.id_valor
                                WHERE m.id_ingreso = %s AND m.estado_anterior IS NULL AND v.estado = 'en_cartera' FOR UPDATE""",
                            (id_ref,))
                valores = [x["id"] for x in cur.fetchall()]
                for v in valores:   # entraron con la orden: se van con ella
                    cur.execute("UPDATE c_valores_de_terceros SET estado = 'anulado', actualizado = NOW() WHERE id = %s", (v,))
                    cur.execute("""INSERT INTO c_valores_de_terceros_movimientos
                                       (id_valor, estado_anterior, estado_nuevo, motivo, id_ingreso, id_usuario)
                                   VALUES (%s, 'en_cartera', 'anulado', %s, %s, %s)""",
                                (v, f"Anulación de la orden {oi['nro_orden']}: {motivo}"[:200], id_ref, uid))
                msg = f"Orden de ingreso {oi['nro_orden']} anulada." + (
                    f" {len(valores)} valor(es) salieron de la cartera." if valores else "")
        conn.commit()
        flash(msg)
    except ValueError as e:
        conn.rollback()
        flash("!" + str(e))
    except Exception:
        conn.rollback()
        log.exception("tesoreria.anular %s %s", origen, id_ref)
        raise
    finally:
        conn.close()
    return redirect(volver)
