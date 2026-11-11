"""
pagos.py — Circuito de pagos: Tesorería → Pagos.

Portado de `gestion_adm/pagos_routes.py` y `pago_imputaciones_routes.py` con
el sistema de estilos de este proyecto; las consultas y reglas están en
pagos_datos.py y el motor de retenciones en retenciones.py.

    /pagos/ordenes                        órdenes de proveedores y anticipos (41)
    /pagos/ordenes/nueva                  a qué proveedor se le paga (41)
    /pagos/ordenes/nueva/<id_proveedor>   sus comprobantes, y emitir la orden (41)
    /pagos/ordenes/anticipo/nueva         orden de anticipo (43)
    /pagos/ordenes/concepto/nueva         orden por concepto (44)
    /pagos/ordenes/<id>                   ficha: aprobación, pago, anulación
    /pagos/emision                        órdenes por estado, todas las clases (45)
    /pagos/emitidos                       pagos emitidos (42)
    /pagos/certificados                   certificados de retención (47)
    /pagos/imputaciones                   imputaciones contables (48)
    /pagos/config_aprobadores             niveles de aprobación (49)

Permisos (la opción de menú, controlada en el servidor también en los POST):
ver una orden, quien tenga alguna opción de pagos o la de órdenes de
reintegros; enviarla a aprobación, quien pueda crear esa clase; aprobar o
rechazar, quien tenga el nivel en Config. Aprobadores; pagar, Emisión de
Pagos; anular una orden o un pago, rol Administrador (como gestion_adm).

Fuera, por ser de la obra social: Integración (órdenes, emisión y
transferencias), visibilidad por áreas. Pendiente: envío del comprobante por
mail (necesita el servidor de correo), exportación SIRE / SICORE,
transferencias masivas y sueldos (etapas siguientes).
"""

from __future__ import annotations

import datetime
import logging

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

import pagos_datos as pd
import pago_anulacion
import retenciones as ret
from db import get_connection, puede, tiene_rol, validasesion
from numeracion import nro_orden_visible, sql_nro_orden_visible, sql_nro_visible

log = logging.getLogger(__name__)

pagos_bp = Blueprint("pagos", __name__, url_prefix="/pagos")

#: Las pantallas desde las que se puede llegar a una orden.
VEN_ORDENES = ("pagos.ordenes", "pagos.anticipo_nueva", "pagos.concepto_nueva", "pagos.emision",
               "pagos.emitidos", "pagos.certificados", "reintegros.ordenes")
#: Quién arma (y manda a aprobar) cada clase.
CREA_CLASE = {"proveedor": "pagos.ordenes", "anticipo": "pagos.anticipo_nueva",
              "concepto": "pagos.concepto_nueva", "reintegro": "reintegros.ordenes",
              "sueldos": "pagos.ordenes"}


def _uid():
    return session.get("sind_usuario_id")


def _puede(endpoint) -> bool:
    try:
        return puede(url_for(endpoint))
    except Exception:                                    # noqa: BLE001 — un endpoint que no está registrado
        return False


def _guardia(*endpoints, api=False):
    """Redirección (o 401/403 en una API) si no hay sesión o no tiene ninguna
    de esas opciones de menú; None si pasa."""
    if not validasesion():
        return (jsonify(error="La sesión venció."), 401) if api else redirect(url_for("login"))
    if not any(_puede(e) for e in endpoints):
        if api:
            return jsonify(error="No tenés permiso."), 403
        flash("!No tenés permiso para esa pantalla.")
        return redirect(url_for("menu"))
    return None


def _flash_error(e: Exception):
    flash("!" + str(e))


def _pesos(v) -> str:
    entero, _, dec = f"{float(v or 0):,.2f}".partition(".")
    return f"{entero.replace(',', '.')},{dec}"


def _cuenta_de_clase(cur, id_cuenta, clase: int, nombre_clase: str) -> str | None:
    """El error si la cuenta no sirve para imputar o no es de esa clase."""
    import tesoreria
    e = tesoreria._cuenta_valida(cur, id_cuenta)
    if e:
        return e
    cur.execute("SELECT codigo, nombre, id_clasificacion FROM c_plan_de_cuentas WHERE id_cuenta = %s", (id_cuenta,))
    c = cur.fetchone()
    if c["id_clasificacion"] != clase:
        return f"La cuenta {c['codigo']} {c['nombre']} no es de {nombre_clase}."
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Órdenes de pago a proveedores
# ─────────────────────────────────────────────────────────────────────────────

@pagos_bp.route("/ordenes")
def ordenes():
    salida = _guardia("pagos.ordenes")
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT o.id, o.nro_orden, o.nro_origen, {sql_nro_orden_visible('o')} AS nro_vis, o.fecha, o.clase,
                       o.estado, o.importe_total, u.nombre AS usuario, pr.id AS id_proveedor, pr.cuit,
                       pr.razon_social, (SELECT COUNT(*) FROM pago_ordenes_detalle d WHERE d.id_orden = o.id) AS n_comp,
                       (SELECT {sql_nro_visible('pp')} FROM pago_pagos pp
                         WHERE pp.id_orden = o.id AND pp.estado <> 'anulado' ORDER BY pp.id DESC LIMIT 1) AS nro_pago
                  FROM pago_ordenes o
                  LEFT JOIN s_usuarios u ON u.id = o.id_usuario_creacion
                  {pd.SQL_PROVEEDOR_ORDEN}
                 WHERE o.clase IN ('proveedor', 'anticipo')
                 ORDER BY o.fecha DESC, o.id DESC""")
            filas = cur.fetchall()
    return render_template("pagos/ordenes.html", ordenes=filas, estados=pd.ESTADOS_ORDEN,
                           estados_txt=pd.ESTADOS_TXT, estado_tipo=pd.ESTADO_TIPO, clases_txt=pd.CLASES_TXT)


@pagos_bp.route("/ordenes/nueva", methods=["GET", "POST"])
def nueva():
    salida = _guardia("pagos.ordenes")
    if salida:
        return salida
    if request.method == "POST":
        id_prov = request.form.get("id_proveedor", type=int)
        ids = [int(x) for x in request.form.getlist("id_expediente") if x.isdigit()]
        importes = {i: request.form.get(f"importe_{i}") for i in ids}
        obs = (request.form.get("observaciones") or "").strip() or None
        with get_connection() as conn:
            conn.begin()
            try:
                with conn.cursor() as cur:
                    r = pd.crear_orden_proveedor(cur, ids, importes, obs, _uid())
                conn.commit()
            except pd.ErrorPago as e:
                conn.rollback()
                _flash_error(e)
                return redirect(url_for("pagos.nueva_proveedor", id_proveedor=id_prov) if id_prov
                                else url_for("pagos.nueva"))
            except Exception:
                conn.rollback()
                raise
        aviso = f"Orden {r['nro']} creada con {r['n']} comprobante{'s' if r['n'] > 1 else ''}."
        if r["parciales"]:
            aviso += (f" {r['parciales']} va{'n' if r['parciales'] > 1 else ''} por menos del saldo: el resto vuelve "
                      "a la lista cuando esta orden se pague.")
        flash(aviso)
        return redirect(url_for("pagos.orden", id_orden=r["id_orden"]))

    with get_connection() as conn:
        with conn.cursor() as cur:
            exps = pd.expedientes_disponibles(cur)
            ids = [e["id_proveedor"] for e in exps]
            proveedores = pd.agrupar_por_proveedor(exps, pd.creditos(cur, ids), pd.ops_sin_pago(cur, ids))
    return render_template("pagos/nueva_orden.html", proveedores=proveedores)


@pagos_bp.route("/ordenes/nueva/<int:id_proveedor>")
def nueva_proveedor(id_proveedor):
    salida = _guardia("pagos.ordenes")
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, cuit, razon_social, nombre_fantasia, cbu, cbu_alias FROM c_proveedores "
                        "WHERE id = %s", (id_proveedor,))
            proveedor = cur.fetchone()
            if not proveedor:
                flash("!El proveedor no existe.")
                return redirect(url_for("pagos.nueva"))
            exps = pd.expedientes_disponibles(cur, id_proveedor)
            if not exps:
                flash("!Este proveedor ya no tiene comprobantes para pagar: puede que ya se le haya emitido la orden.")
                return redirect(url_for("pagos.nueva"))
            creditos = pd.creditos(cur, [id_proveedor]).get(id_proveedor) or []
            ops = pd.ops_sin_pago(cur, [id_proveedor]).get(id_proveedor) or []
    return render_template("pagos/nueva_orden_proveedor.html", proveedor=proveedor, expedientes=exps,
                           creditos=creditos, credito_total=sum(float(c["saldo"]) for c in creditos),
                           ops_sin_pago=ops)


# ─────────────────────────────────────────────────────────────────────────────
# Anticipo y concepto
# ─────────────────────────────────────────────────────────────────────────────

@pagos_bp.route("/ordenes/anticipo/nueva", methods=["GET", "POST"])
def anticipo_nueva():
    salida = _guardia("pagos.anticipo_nueva")
    if salida:
        return salida
    datos = {}
    with get_connection() as conn:
        with conn.cursor() as cur:
            imputaciones = pd.imputaciones(cur, "anticipo")
        if request.method == "POST":
            datos = {"id_proveedor": request.form.get("id_proveedor", type=int),
                     "id_imputacion": request.form.get("id_imputacion", type=int),
                     "id_rubro_pasivo": request.form.get("id_rubro_pasivo", type=int),
                     "descripcion": (request.form.get("descripcion") or "").strip()[:200] or None,
                     "importe": request.form.get("importe") or "",
                     "observaciones": (request.form.get("observaciones") or "").strip() or None}
            conn.begin()
            try:
                with conn.cursor() as cur:
                    r = pd.crear_orden_anticipo(cur, datos["id_proveedor"], datos["id_imputacion"],
                                                datos["id_rubro_pasivo"], datos["descripcion"],
                                                pd.leer_importe(datos["importe"]), datos["observaciones"], _uid())
                conn.commit()
                flash(f"Orden de anticipo {r['nro']} creada.")
                return redirect(url_for("pagos.orden", id_orden=r["id_orden"]))
            except pd.ErrorPago as e:
                conn.rollback()
                _flash_error(e)
            except Exception:
                conn.rollback()
                raise
        proveedor = None
        if datos.get("id_proveedor"):
            with conn.cursor() as cur:
                cur.execute("SELECT id, cuit, razon_social, cbu, cbu_alias FROM c_proveedores WHERE id = %s",
                            (datos["id_proveedor"],))
                proveedor = cur.fetchone()
                if proveedor:
                    proveedor["rubros"] = pd.rubros_de_proveedor(cur, proveedor["id"])
    return render_template("pagos/nueva_anticipo.html", imputaciones=imputaciones, datos=datos,
                           proveedor=proveedor, puede_imputaciones=_puede("pagos.imputaciones"))


@pagos_bp.route("/api/proveedores")
def api_proveedores():
    """Búsqueda para el anticipo: con sus cuentas de pasivo y sus OP sin pago."""
    salida = _guardia("pagos.anticipo_nueva", api=True)
    if salida:
        return salida
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify([])
    like, dig = f"%{q}%", "".join(c for c in q if c.isdigit())
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, razon_social, nombre_fantasia, cuit, cbu, cbu_alias FROM c_proveedores
                            WHERE activo = 1 AND (razon_social LIKE %s OR nombre_fantasia LIKE %s OR cuit LIKE %s)
                            ORDER BY razon_social LIMIT 15""", (like, like, f"%{dig}%" if dig else like))
            filas = cur.fetchall()
            ops = pd.ops_sin_pago(cur, [f["id"] for f in filas])
            for f in filas:
                f["rubros"] = pd.rubros_de_proveedor(cur, f["id"])
                f["ops_sin_pago"] = [{"id": o["id"], "nro": o["nro_vis"], "clase": o["clase_txt"],
                                      "estado": o["estado_txt"], "importe": float(o["importe_total"] or 0),
                                      "url": url_for("pagos.orden", id_orden=o["id"])}
                                     for o in ops.get(f["id"]) or []]
    return jsonify(filas)


@pagos_bp.route("/ordenes/concepto/nueva", methods=["GET", "POST"])
def concepto_nueva():
    salida = _guardia("pagos.concepto_nueva")
    if salida:
        return salida
    lineas, obs = [], None
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, descripcion FROM c_concepto_de_gastos WHERE activo = 1 ORDER BY descripcion")
            conceptos = cur.fetchall()
            cur.execute("SELECT id, descripcion FROM c_motivos_de_ingreso WHERE activo = 1 ORDER BY descripcion")
            motivos = cur.fetchall()
        if request.method == "POST":
            f = request.form
            for tipo, cid, desc, imp, per in zip(f.getlist("tipo"), f.getlist("id_concepto"), f.getlist("descripcion"),
                                                 f.getlist("importe"), f.getlist("periodo")):
                per = per.replace("-", "")
                lineas.append({"tipo": tipo, "id": int(cid) if cid.isdigit() else None, "descripcion": desc,
                               "importe": pd.leer_importe(imp), "importe_txt": imp,
                               "periodo": per if len(per) == 6 and per.isdigit() else None})
            obs = (f.get("observaciones") or "").strip() or None
            conn.begin()
            try:
                with conn.cursor() as cur:
                    r = pd.crear_orden_concepto(cur, lineas, obs, _uid())
                conn.commit()
                flash(f"Orden de pago {r['nro']} creada.")
                return redirect(url_for("pagos.orden", id_orden=r["id_orden"]))
            except pd.ErrorPago as e:
                conn.rollback()
                _flash_error(e)
            except Exception:
                conn.rollback()
                raise
    return render_template("pagos/nueva_concepto.html", conceptos=conceptos, motivos=motivos, lineas=lineas,
                           observaciones=obs, periodo_actual=datetime.date.today().strftime("%Y-%m"))


# ─────────────────────────────────────────────────────────────────────────────
# La orden
# ─────────────────────────────────────────────────────────────────────────────

@pagos_bp.route("/ordenes/<int:id_orden>")
def orden(id_orden):
    salida = _guardia(*VEN_ORDENES)
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            o = pd.orden_completa(cur, id_orden)
            if not o:
                flash("!La orden no existe.")
                return redirect(url_for("pagos.emision") if _puede("pagos.emision") else url_for("menu"))
            mis_niveles = pd.niveles_pendientes_de(cur, id_orden, _uid())
            beneficiarios = o["beneficiarios"]
            cuentas = pd.cuentas_pago(cur)
            chequeras = pd.chequeras_habilitadas(cur)
            hay_aprobadores = bool(pd.niveles(cur))
    return render_template(
        "pagos/orden.html", o=o, estados_txt=pd.ESTADOS_TXT, estado_tipo=pd.ESTADO_TIPO, clases_txt=pd.CLASES_TXT,
        tipos_instrumento=pd.TIPOS_INSTRUMENTO, beneficiarios=beneficiarios, cuentas=cuentas, chequeras=chequeras,
        cuenta_predeterminada=next((c["id"] for c in cuentas if c["predeterminada"]), None),
        mis_niveles=mis_niveles, hay_aprobadores=hay_aprobadores,
        puede_enviar=_puede(CREA_CLASE.get(o["clase"], "pagos.ordenes")),
        puede_pagar=_puede("pagos.emision"), es_admin=tiene_rol("Administrador"),
        hoy=datetime.date.today().isoformat())


@pagos_bp.route("/ordenes/<int:id_orden>/aprobacion", methods=["POST"])
def aprobacion(id_orden):
    salida = _guardia(*VEN_ORDENES)
    if salida:
        return salida
    accion = request.form.get("accion", "")
    obs = (request.form.get("observaciones") or "").strip() or None
    with get_connection() as conn:
        conn.begin()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT clase FROM pago_ordenes WHERE id = %s", (id_orden,))
                o = cur.fetchone()
                if not o:
                    raise pd.ErrorPago("La orden no existe.")
                if accion == "enviar":
                    if not _puede(CREA_CLASE.get(o["clase"], "pagos.ordenes")):
                        raise pd.ErrorPago("No tenés permiso para mandar a aprobar esta clase de orden.")
                    msg = pd.enviar_a_aprobacion(cur, id_orden, obs)
                elif accion == "aprobar":
                    msg = pd.aprobar(cur, id_orden, _uid(), obs)
                elif accion == "rechazar":
                    msg = pd.rechazar(cur, id_orden, _uid(), obs)
                else:
                    raise pd.ErrorPago("Acción desconocida.")
            conn.commit()
            flash(msg)
        except pd.ErrorPago as e:
            conn.rollback()
            _flash_error(e)
        except Exception:
            conn.rollback()
            raise
    return redirect(url_for("pagos.orden", id_orden=id_orden))


@pagos_bp.route("/ordenes/<int:id_orden>/pagar", methods=["POST"])
def pagar(id_orden):
    salida = _guardia("pagos.emision")
    if salida:
        return salida
    instrumentos = pd.instrumentos_del_form(request.form)
    try:
        with get_connection() as conn:
            r = pd.ejecutar_pago(conn, id_orden, request.form.get("fecha_pago") or datetime.date.today().isoformat(),
                                 instrumentos, (request.form.get("observaciones") or "").strip() or None, _uid())
    except pd.ErrorPago as e:
        _flash_error(e)
        return redirect(url_for("pagos.orden", id_orden=id_orden))
    msg = f"Pago {r['nro_pago']} emitido."
    if r["retenciones"]:
        msg += (f" Se retuvo $ {_pesos(r['retenido'])} ({r['certificados']} certificado"
                f"{'s' if r['certificados'] > 1 else ''}); neto pagado $ {_pesos(r['neto'])}.")
    flash(msg)
    return redirect(url_for("pagos.orden", id_orden=id_orden))


@pagos_bp.route("/api/orden/<int:id_orden>/retenciones")
def api_retenciones(id_orden):
    """Lo que se va a retener si se paga en esa fecha, y por qué (o por qué no)."""
    salida = _guardia("pagos.emision", api=True)
    if salida:
        return salida
    try:
        fecha = datetime.date.fromisoformat(request.args.get("fecha_pago") or datetime.date.today().isoformat())
    except ValueError:
        return jsonify(error="Fecha inválida."), 400
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT importe_total, clase FROM pago_ordenes WHERE id = %s", (id_orden,))
            o = cur.fetchone()
            if not o:
                return jsonify(error="La orden no existe."), 404
        avisos: list = []
        lista = ret.calcular_retenciones_orden(conn, id_orden, fecha, avisos=avisos)
        conf = ret.configuracion(conn)
        motivos = []
        if o["clase"] in ("proveedor", "anticipo"):
            if not conf.get("ret_ganancias"):
                motivos.append("El sindicato no figura como agente de retención de Ganancias (Datos del Sindicato).")
            with conn.cursor() as cur:
                tabla = "pago_ordenes_detalle d JOIN me_expedientes e ON e.id = d.id_expediente" \
                    if o["clase"] == "proveedor" else "pago_ordenes_anticipo_det e"
                cur.execute(f"""SELECT DISTINCT p.razon_social, p.ret_ganancias FROM {tabla}
                                  JOIN c_proveedores p ON p.id = e.id_proveedor
                                 WHERE {'d' if o['clase'] == 'proveedor' else 'e'}.id_orden = %s""", (id_orden,))
                for p in cur.fetchall():
                    if not p["ret_ganancias"]:
                        motivos.append(f"{p['razon_social']} no tiene tildada la retención de Ganancias en su ficha.")
        motivos += avisos
        divisor = float(ret.divisor_iva(conf))
    bruto = float(o["importe_total"] or 0)
    total = ret.total_retenciones(lista)
    return jsonify(bruto=bruto, total_retenciones=total, neto=round(bruto - total, 2), retenciones=lista,
                   motivos=motivos, base_orden=round(bruto / divisor, 2) if divisor else bruto, divisor=divisor)


@pagos_bp.route("/ordenes/<int:id_orden>/anular", methods=["POST"])
def anular_orden(id_orden):
    salida = _guardia(*VEN_ORDENES)
    if salida:
        return salida
    if not tiene_rol("Administrador"):
        flash("!Anular órdenes de pago es una acción de Administrador.")
        return redirect(url_for("pagos.orden", id_orden=id_orden))
    with get_connection() as conn:
        conn.begin()
        try:
            with conn.cursor() as cur:
                r = pago_anulacion.anular_orden(cur, id_orden, request.form.get("motivo"), _uid())
            conn.commit()
        except ValueError as e:
            conn.rollback()
            _flash_error(e)
            return redirect(url_for("pagos.orden", id_orden=id_orden))
        except Exception:
            conn.rollback()
            raise
    partes = [f"Orden {r['nro_orden']} anulada."]
    if r["expedientes_liberados"]:
        partes.append(f"{r['expedientes_liberados']} comprobante(s) vuelven a estar disponibles para pagar.")
    if r["reintegros_liberados"]:
        partes.append(f"{r['reintegros_liberados']} reintegro(s) vuelven a poder pagarse.")
    flash(" ".join(partes))
    return redirect(url_for("pagos.orden", id_orden=id_orden))


@pagos_bp.route("/pagos/<int:id_pago>/anular", methods=["POST"])
def anular_pago(id_pago):
    salida = _guardia(*VEN_ORDENES)
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id_orden FROM pago_pagos WHERE id = %s", (id_pago,))
            p = cur.fetchone()
    if not p:
        flash("!El pago no existe.")
        return redirect(url_for("menu"))
    if not tiene_rol("Administrador"):
        flash("!Anular pagos es una acción de Administrador.")
        return redirect(url_for("pagos.orden", id_orden=p["id_orden"]))
    with get_connection() as conn:
        conn.begin()
        try:
            with conn.cursor() as cur:
                r = pago_anulacion.anular(cur, id_pago, request.form.get("motivo"), _uid())
            conn.commit()
        except ValueError as e:
            conn.rollback()
            _flash_error(e)
            return redirect(url_for("pagos.orden", id_orden=p["id_orden"]))
        except Exception:
            conn.rollback()
            raise
    msg = f"Pago {r['nro_pago']} anulado."
    if r["orden_reabierta"]:
        msg += " La orden volvió a «aprobada»: se puede volver a pagar o anular."
    if r["certificados_en_sire"]:
        msg = "!" + msg + f" {r['certificados_en_sire']} certificado(s) ya se habían informado en SIRE: hay que rectificar."
    flash(msg)
    return redirect(url_for("pagos.orden", id_orden=p["id_orden"]))


# ─────────────────────────────────────────────────────────────────────────────
# Emisión y emitidos
# ─────────────────────────────────────────────────────────────────────────────

@pagos_bp.route("/emision")
def emision():
    salida = _guardia("pagos.emision")
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT o.id, {sql_nro_orden_visible('o')} AS nro_vis, o.fecha, o.clase, o.estado, o.importe_total,
                       u.nombre AS usuario, {pd.SQL_BENEFICIARIO} AS beneficiario,
                       {pd.SQL_PAGADO_ORDEN} AS pagado_bruto, {pd.SQL_RETENIDO_ORDEN} AS retenido
                  FROM pago_ordenes o
                  LEFT JOIN s_usuarios u ON u.id = o.id_usuario_creacion
                 ORDER BY o.estado = 'aprobada' DESC, o.fecha DESC, o.id DESC""")
            filas = cur.fetchall()
    for o in filas:
        o["pagado"] = round(float(o["pagado_bruto"] or 0) - float(o["retenido"] or 0), 2)
    return render_template("pagos/emision.html", ordenes=filas, estados=pd.ESTADOS_ORDEN, estados_txt=pd.ESTADOS_TXT,
                           estado_tipo=pd.ESTADO_TIPO, clases=pd.CLASES_ORDEN, clases_txt=pd.CLASES_TXT)


@pagos_bp.route("/emitidos")
def emitidos():
    salida = _guardia("pagos.emitidos")
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT p.id, {sql_nro_visible('p')} AS nro_vis, p.fecha_pago, p.importe_total AS bruto, p.estado,
                       o.id AS id_orden, {sql_nro_orden_visible('o')} AS nro_orden_vis, o.clase,
                       u.nombre AS usuario, {pd.SQL_BENEFICIARIO} AS beneficiario,
                       (SELECT COALESCE(SUM(r.importe), 0) FROM pago_retenciones r
                         WHERE r.id_pago = p.id AND COALESCE(r.anulado, 0) = 0) AS retenido,
                       (SELECT GROUP_CONCAT(DISTINCT i.tipo_instrumento SEPARATOR ', ')
                          FROM pago_pagos_instrumentos i WHERE i.id_pago = p.id) AS instrumentos
                  FROM pago_pagos p
                  JOIN pago_ordenes o ON o.id = p.id_orden
                  LEFT JOIN s_usuarios u ON u.id = p.id_usuario_creacion
                 ORDER BY p.fecha_pago DESC, p.id DESC""")
            filas = cur.fetchall()
    for p in filas:
        p["neto"] = round(float(p["bruto"] or 0) - float(p["retenido"] or 0), 2)
    return render_template("pagos/emitidos.html", pagos=filas, clases=pd.CLASES_ORDEN, clases_txt=pd.CLASES_TXT)


# ─────────────────────────────────────────────────────────────────────────────
# Certificados de retención
# ─────────────────────────────────────────────────────────────────────────────

@pagos_bp.route("/certificados")
def certificados():
    salida = _guardia("pagos.certificados")
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT c.id, c.nro_certificado, c.tipo, c.codigo_regimen, c.fecha_emision, c.periodo_fiscal,
                       c.cuit_proveedor, c.razon_social_proveedor, c.base_calculo, c.alicuota, c.importe_retenido,
                       c.estado, c.exportado_sire, c.id_orden, c.id_pago,
                       {sql_nro_visible('p')} AS nro_pago, {sql_nro_orden_visible('o')} AS nro_orden
                  FROM pago_retenciones_certificado c
                  LEFT JOIN pago_pagos p ON p.id = c.id_pago
                  LEFT JOIN pago_ordenes o ON o.id = c.id_orden
                 ORDER BY c.fecha_emision DESC, c.id DESC""")
            filas = cur.fetchall()
    return render_template("pagos/certificados.html", certificados=filas)


@pagos_bp.route("/certificados/<int:id_cert>")
def certificado(id_cert):
    salida = _guardia("pagos.certificados", *VEN_ORDENES)
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT c.*, {sql_nro_visible('p')} AS nro_pago, p.fecha_pago, p.estado AS estado_pago,
                       {sql_nro_orden_visible('o')} AS nro_orden, u.nombre AS usuario, ua.nombre AS usuario_anulacion
                  FROM pago_retenciones_certificado c
                  LEFT JOIN pago_pagos p ON p.id = c.id_pago
                  LEFT JOIN pago_ordenes o ON o.id = c.id_orden
                  LEFT JOIN s_usuarios u ON u.id = c.id_usuario_creacion
                  LEFT JOIN s_usuarios ua ON ua.id = c.id_usuario_anulacion
                 WHERE c.id = %s""", (id_cert,))
            c = cur.fetchone()
            if not c:
                flash("!El certificado no existe.")
                return redirect(url_for("pagos.certificados"))
            cur.execute("""SELECT r.*, e.nro_expediente FROM pago_retenciones r
                             LEFT JOIN me_expedientes e ON e.id = r.id_expediente
                            WHERE r.id_certificado_emitido = %s ORDER BY r.id""", (id_cert,))
            lineas = cur.fetchall()
    return render_template("pagos/certificado.html", c=c, lineas=lineas)


# ─────────────────────────────────────────────────────────────────────────────
# PDF
# ─────────────────────────────────────────────────────────────────────────────

@pagos_bp.route("/ordenes/<int:id_orden>/pdf")
def orden_pdf(id_orden):
    salida = _guardia(*VEN_ORDENES)
    if salida:
        return salida
    import pagos_pdf
    with get_connection() as conn:
        with conn.cursor() as cur:
            o = pd.orden_completa(cur, id_orden)
    if not o:
        flash("!La orden no existe.")
        return redirect(url_for("menu"))
    return pagos_pdf.respuesta(pagos_pdf.orden(o), f"OP_{nro_orden_visible(o)}.pdf")


@pagos_bp.route("/certificados/<int:id_cert>/pdf")
def certificado_pdf(id_cert):
    salida = _guardia("pagos.certificados", *VEN_ORDENES)
    if salida:
        return salida
    import pagos_pdf
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM pago_retenciones_certificado WHERE id = %s", (id_cert,))
            c = cur.fetchone()
            if c:
                cur.execute(f"""SELECT {sql_nro_visible('p')} AS nro_pago, p.fecha_pago,
                                       {sql_nro_orden_visible('o')} AS nro_orden
                                  FROM pago_pagos p JOIN pago_ordenes o ON o.id = p.id_orden WHERE p.id = %s""",
                            (c["id_pago"],))
                c.update(cur.fetchone() or {})
                cur.execute("""SELECT p.*, rt.descripcion AS condicion_txt FROM c_proveedores p
                                 LEFT JOIN arca_responsable_tipo rt ON rt.codigo = p.condicion_iva
                                WHERE p.id = %s""", (c["id_proveedor"],))
                c["proveedor"] = cur.fetchone() or {}
    if not c:
        flash("!El certificado no existe.")
        return redirect(url_for("pagos.certificados"))
    return pagos_pdf.respuesta(pagos_pdf.certificado(c), f"Certificado_{c['nro_certificado']}.pdf")


# ─────────────────────────────────────────────────────────────────────────────
# Tablas del circuito
# ─────────────────────────────────────────────────────────────────────────────

@pagos_bp.route("/config_aprobadores", methods=["GET", "POST"])
def aprobadores():
    salida = _guardia("pagos.aprobadores")
    if salida:
        return salida
    errores, registro = [], None
    if request.method == "POST":
        accion, rid = request.form.get("accion", ""), request.form.get("id", type=int)
        with get_connection() as conn:
            with conn.cursor() as cur:
                if accion == "borrar" and rid:
                    cur.execute("DELETE FROM pago_config_aprobadores WHERE id = %s", (rid,))
                    flash("Aprobador eliminado.")
                    return redirect(url_for("pagos.aprobadores"))
                registro = {"id": rid, "nivel": request.form.get("nivel", type=int),
                            "id_usuario": request.form.get("id_usuario", type=int),
                            "activo": 1 if request.form.get("activo") else 0,
                            "observaciones": (request.form.get("observaciones") or "").strip()[:200] or None}
                if not registro["nivel"] or not 1 <= registro["nivel"] <= 9:
                    errores.append("El nivel es un número del 1 al 9.")
                if not registro["id_usuario"]:
                    errores.append("Elegí el usuario.")
                if not errores:
                    cur.execute("""SELECT id FROM pago_config_aprobadores WHERE nivel = %s AND id_usuario = %s
                                     AND id <> %s""", (registro["nivel"], registro["id_usuario"], rid or 0))
                    if cur.fetchone():
                        errores.append("Ese usuario ya está en ese nivel.")
                if not errores:
                    if rid:
                        cur.execute("""UPDATE pago_config_aprobadores SET nivel = %s, id_usuario = %s, activo = %s,
                                              observaciones = %s WHERE id = %s""",
                                    (registro["nivel"], registro["id_usuario"], registro["activo"],
                                     registro["observaciones"], rid))
                        flash("Aprobador actualizado.")
                    else:
                        cur.execute("""INSERT INTO pago_config_aprobadores (nivel, id_usuario, activo, observaciones)
                                       VALUES (%s, %s, %s, %s)""",
                                    (registro["nivel"], registro["id_usuario"], registro["activo"],
                                     registro["observaciones"]))
                        flash("Aprobador agregado.")
                    return redirect(url_for("pagos.aprobadores"))
    with get_connection() as conn:
        with conn.cursor() as cur:
            edit = request.args.get("edit", type=int)
            if edit and registro is None:
                cur.execute("SELECT * FROM pago_config_aprobadores WHERE id = %s", (edit,))
                registro = cur.fetchone()
            cur.execute("""SELECT a.*, u.nombre AS usuario, u.email, u.activo AS usuario_activo
                             FROM pago_config_aprobadores a JOIN s_usuarios u ON u.id = a.id_usuario
                            ORDER BY a.nivel, u.nombre""")
            lista = cur.fetchall()
            cur.execute("SELECT id, CONCAT(nombre, ' · ', email) AS nombre FROM s_usuarios WHERE activo = 1 "
                        "ORDER BY nombre")
            usuarios = cur.fetchall()
            cur.execute("SELECT COUNT(*) AS n FROM pago_ordenes WHERE estado = 'pendiente_aprobacion'")
            esperando = cur.fetchone()["n"]
    return render_template("pagos/aprobadores.html", aprobadores=lista, usuarios=usuarios, registro=registro,
                           errores=errores, esperando=esperando,
                           abrir_ficha=bool(registro or errores or request.args.get("nuevo")))


#: Qué se configura en Imputaciones Contables (de gestion_adm, sin acuerdos de
#: pago ni recibos de fiscalización, que son de la obra social).
CLASES_IMPUTACION = [("anticipo", "Anticipo a proveedor"), ("retencion", "Retención impositiva")]
SUBTIPOS_RETENCION = [("IVA", "IVA — RG 2854"), ("GANANCIAS", "Ganancias — RG 830"), ("IIBB", "Ingresos Brutos"),
                      ("SUSS", "SUSS")]


@pagos_bp.route("/imputaciones", methods=["GET", "POST"])
def imputaciones():
    """Contra qué cuenta va cada operación que no la tiene en otro lado: el
    anticipo (debe, activo) y cada retención (haber, pasivo a depositar)."""
    salida = _guardia("pagos.imputaciones")
    if salida:
        return salida
    import tesoreria
    errores, registro = [], None
    if request.method == "POST":
        accion, rid = request.form.get("accion", ""), request.form.get("id", type=int)
        with get_connection() as conn:
            with conn.cursor() as cur:
                if accion in ("borrar", "baja", "reactivar") and rid:
                    if accion == "borrar":
                        cur.execute("SELECT COUNT(*) AS n FROM pago_ordenes_anticipo_det WHERE id_imputacion = %s",
                                    (rid,))
                        if cur.fetchone()["n"]:
                            flash("!La usan órdenes de anticipo: no se elimina, se desactiva.")
                        else:
                            cur.execute("DELETE FROM pago_imputaciones_config WHERE id = %s", (rid,))
                            flash("Imputación eliminada.")
                    else:
                        cur.execute("UPDATE pago_imputaciones_config SET activo = %s WHERE id = %s",
                                    (1 if accion == "reactivar" else 0, rid))
                        flash("Imputación " + ("reactivada." if accion == "reactivar" else "desactivada."))
                    return redirect(url_for("pagos.imputaciones"))
                f = request.form
                registro = {"id": rid, "clase": f.get("clase", ""), "subtipo": f.get("subtipo") or None,
                            "nombre": (f.get("nombre") or "").strip()[:100],
                            "id_cuenta_debe": f.get("id_cuenta_debe", type=int),
                            "id_cuenta_haber": f.get("id_cuenta_haber", type=int),
                            "activo": 1 if f.get("activo") else 0,
                            "observaciones": (f.get("observaciones") or "").strip()[:255] or None}
                if registro["clase"] not in dict(CLASES_IMPUTACION):
                    errores.append("Elegí la clase.")
                if registro["clase"] == "retencion":
                    if registro["subtipo"] not in dict(SUBTIPOS_RETENCION):
                        errores.append("Para una retención, el impuesto es obligatorio.")
                    registro["id_cuenta_debe"] = None
                    e = _cuenta_de_clase(cur, registro["id_cuenta_haber"], 2, "pasivo (la retención se deposita)")
                    if e:
                        errores.append("Cuenta haber: " + e)
                elif registro["clase"] == "anticipo":
                    registro["subtipo"], registro["id_cuenta_haber"] = None, None
                    e = _cuenta_de_clase(cur, registro["id_cuenta_debe"], 1, "activo (el anticipo es un crédito)")
                    if e:
                        errores.append("Cuenta debe: " + e)
                if not registro["nombre"]:
                    errores.append("El nombre es obligatorio.")
                if not errores:
                    cols = ["clase", "subtipo", "nombre", "id_cuenta_debe", "id_cuenta_haber", "activo", "observaciones"]
                    if rid:
                        cur.execute(f"UPDATE pago_imputaciones_config SET {', '.join(c + ' = %s' for c in cols)} "
                                    "WHERE id = %s", [registro[c] for c in cols] + [rid])
                        flash("Imputación actualizada.")
                    else:
                        cur.execute(f"INSERT INTO pago_imputaciones_config ({', '.join(cols)}) "
                                    f"VALUES ({', '.join(['%s'] * len(cols))})", [registro[c] for c in cols])
                        flash("Imputación agregada.")
                    return redirect(url_for("pagos.imputaciones"))
    with get_connection() as conn:
        with conn.cursor() as cur:
            edit = request.args.get("edit", type=int)
            if edit and registro is None:
                cur.execute("SELECT * FROM pago_imputaciones_config WHERE id = %s", (edit,))
                registro = cur.fetchone()
            cur.execute("""SELECT i.*, cd.codigo AS codigo_debe, cd.nombre AS cuenta_debe,
                                  ch.codigo AS codigo_haber, ch.nombre AS cuenta_haber,
                                  (SELECT COUNT(*) FROM pago_ordenes_anticipo_det a WHERE a.id_imputacion = i.id) AS usos
                             FROM pago_imputaciones_config i
                             LEFT JOIN c_plan_de_cuentas cd ON cd.id_cuenta = i.id_cuenta_debe
                             LEFT JOIN c_plan_de_cuentas ch ON ch.id_cuenta = i.id_cuenta_haber
                            ORDER BY i.clase, i.subtipo, i.nombre""")
            lista = cur.fetchall()
            activo = tesoreria.cuentas_imputables(cur, clases=[1])
            pasivo = tesoreria.cuentas_imputables(cur, clases=[2])
    return render_template("pagos/imputaciones.html", imputaciones=lista, registro=registro, errores=errores,
                           clases=CLASES_IMPUTACION, subtipos=SUBTIPOS_RETENCION, clases_txt=dict(CLASES_IMPUTACION),
                           subtipos_txt=dict(SUBTIPOS_RETENCION), cuentas_activo=activo,
                           cuentas_pasivo=pasivo, abrir_ficha=bool(registro or errores or request.args.get("nuevo")))
