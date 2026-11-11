"""
transferencias.py — Transferencias masivas por archivo (Tesorería → Pagos, menú 46).

Portado de `gestion_adm/transferencias_routes.py`:

    /pagos/transferencias                    pagos para transferir y archivos generados
    /pagos/transferencias/generar            POST: registra el lote y lleva a su ficha
    /pagos/transferencias/lote/<id>          ficha del archivo
    /pagos/transferencias/lote/<id>/descargar  el archivo, armado con lo registrado
    /pagos/transferencias/lote/<id>/excluir  POST: saca un renglón (no se transmitió)
    /pagos/transferencias/lote/<id>/anular   POST: el archivo entero no viajó

La grilla es por instrumento de transferencia (un pago abierto en dos cuentas
son dos transferencias) de pagos vivos, no conciliados y que no salieron en otro
archivo. La cuenta de origen del filtro ES la ordenante: no hay un segundo
selector (permitía filtrar por una y ordenar desde otra). El formato no se elige:
es el habitual de la cuenta (Cuentas de Fondos), y si no tiene, el primero de su
banco.

QUÉ CAMBIA RESPECTO DE GESTION_ADM
- El permiso es la opción de menú, controlado en cada GET y POST.
- Un destino que el formato no toma (alias en un archivo del BNA, CBU que no
  verifica) se ve apagado con el motivo y queda excluido del lote. En gestion_adm
  el generador lo salteaba en silencio y el lote lo daba por transferido.
- Generar registra el lote y lleva a su ficha, que descarga el archivo armado
  con lo registrado: lo que se baja es exactamente lo asentado, y la grilla no
  queda mostrando pagos que ya salieron.
- Sin visibilidad por áreas ni los circuitos de Integración y sueldos.
"""

from __future__ import annotations

import datetime
import io

from flask import Blueprint, flash, redirect, render_template, request, send_file, session, url_for

import transferencias_formatos as tf
import transferencias_lote as tl
from db import get_connection, puede, validasesion

transferencias_bp = Blueprint("transferencias", __name__, url_prefix="/pagos/transferencias")

#: Instrumentos que trae la grilla como máximo.
TOPE = 1000
CLASES_TXT = {"proveedor": "Proveedor", "anticipo": "Anticipo", "reintegro": "Reintegro"}


def _guardia():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede(url_for("transferencias.index")):
        flash("!No tenés permiso para esa pantalla.")
        return redirect(url_for("menu"))
    return None


def _fecha(txt):
    try:
        return datetime.date.fromisoformat((txt or "").strip())
    except ValueError:
        return None


def _cuentas(cur) -> list[dict]:
    """Las cuentas de banco habilitadas: son las únicas que ordenan transferencias."""
    cur.execute("""SELECT cf.id, cf.nombre, cf.cbu, cf.formato_transferencia, cf.predeterminada,
                          b.codigo AS banco_codigo, b.nombre AS banco_nombre
                     FROM c_cuentas_de_fondos cf
                     LEFT JOIN c_codigo_de_banco b ON b.id = cf.c_codigo_de_bancoId
                    WHERE cf.habilitada = 1 AND cf.tipo_de_cuenta = 'B'
                    ORDER BY cf.predeterminada DESC, cf.nombre""")
    cuentas = cur.fetchall()
    for c in cuentas:
        c["formato"] = tf.formato_de_cuenta(c)
    return cuentas


def _motivo(p: dict, formato: str | None) -> str | None:
    """Por qué ese renglón no puede ir en el archivo de esa cuenta, o None."""
    if p["motivo"]:
        return p["motivo"]
    if formato:
        return tf.motivo_destino(formato, p["cbu"])
    return None


def _lotes(cur, limite=100) -> list[dict]:
    cur.execute("""SELECT l.*, cf.nombre AS cuenta FROM pago_transferencias_lote l
                     LEFT JOIN c_cuentas_de_fondos cf ON cf.id = l.id_cuenta_fondos
                    WHERE l.origen = 'masivo' ORDER BY l.creado DESC, l.id DESC LIMIT %s""", (limite,))
    lotes = cur.fetchall()
    for x in lotes:
        x["formato_txt"] = (tf.FORMATOS.get(x["formato"]) or {}).get("nombre") or x["formato"]
    return lotes


@transferencias_bp.route("")
def index():
    salida = _guardia()
    if salida:
        return salida
    hoy = datetime.date.today()
    # Por defecto el día: las transferencias se arman con los pagos de hoy. Se
    # mira si el parámetro VIENE, no si tiene valor, para poder vaciarlo.
    if "desde" in request.args or "hasta" in request.args:
        desde, hasta = _fecha(request.args.get("desde")), _fecha(request.args.get("hasta"))
    else:
        desde = hasta = hoy
    with get_connection() as conn:
        with conn.cursor() as cur:
            cuentas = _cuentas(cur)
            if "cuenta" in request.args:
                id_cuenta = request.args.get("cuenta", type=int)
            else:
                id_cuenta = next((c["id"] for c in cuentas if c["predeterminada"]), None) \
                    or (cuentas[0]["id"] if len(cuentas) == 1 else None)
            cuenta = next((c for c in cuentas if c["id"] == id_cuenta), None)
            pagos = tl.pagos_transferibles(cur, desde=desde, hasta=hasta, id_cuenta=id_cuenta, limite=TOPE)
            lotes = _lotes(cur)
    excedido = len(pagos) > TOPE
    pagos = pagos[:TOPE]
    formato = cuenta["formato"] if cuenta else None
    for p in pagos:
        p["motivo_final"] = _motivo(p, formato)
        p["clase_txt"] = CLASES_TXT.get(p["clase"], p["clase"])
        p["numero"] = str(p["nro_origen"]) if p["nro_origen"] else p["nro_pago"]
    listos = [p for p in pagos if not p["motivo_final"]]
    return render_template(
        "pagos/transferencias.html", pagos=pagos, cuentas=cuentas, cuenta=cuenta, lotes=lotes,
        formato=tf.FORMATOS.get(formato) if formato else None, clave_formato=formato,
        formatos_banco=tf.formatos_del_banco(tf.banco_de_cuenta(cuenta)) if cuenta else {},
        f={"desde": desde, "hasta": hasta, "cuenta": id_cuenta},
        cant_listos=len(listos), total_listos=sum(float(p["importe"] or 0) for p in listos),
        excedido=excedido, tope=TOPE, puede_cuentas=puede(url_for("tesoreria.cuentas_fondos")),
        puede_ordenes=puede(url_for("pagos.ordenes")))


@transferencias_bp.route("/generar", methods=["POST"])
def generar():
    salida = _guardia()
    if salida:
        return salida
    ids = sorted({int(x) for x in request.form.getlist("instrumento") if x.isdigit()})
    id_cuenta = request.form.get("cuenta", type=int)
    concepto = "".join(ch for ch in (request.form.get("concepto") or "FAC").upper() if ch.isalnum())[:3] or "FAC"
    volver = url_for("transferencias.index", desde=request.form.get("desde", ""),
                     hasta=request.form.get("hasta", ""), cuenta=id_cuenta or "")
    if not ids:
        flash("!No elegiste ninguna transferencia.")
        return redirect(volver)
    if not id_cuenta:
        flash("!Elegí la cuenta de origen: es la que ordena la transferencia.")
        return redirect(volver)

    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            cuenta = next((c for c in _cuentas(cur) if c["id"] == id_cuenta), None)
            if not cuenta:
                raise ValueError("La cuenta de origen no es una cuenta de banco habilitada.")
            if not tf.es_cbu(cuenta["cbu"] or ""):
                raise ValueError(f"La cuenta {cuenta['nombre']} no tiene CBU cargado.")
            formato = cuenta["formato"]
            if not formato:
                raise ValueError(f"No hay formato de transferencias para {cuenta['banco_nombre'] or 'el banco'} "
                                 f"de la cuenta {cuenta['nombre']}.")
            # Se vuelven a traer con los mismos descartes: entre que se dibujó la
            # grilla y se apretó Generar, alguno pudo salir en otro archivo. Y
            # todos de la cuenta ordenante: el id viaja en el form y la cuenta
            # aparte, un form armado a mano podría mezclarlas.
            filas = tl.pagos_transferibles(cur, ids=ids, limite=len(ids))
            if not filas:
                raise ValueError("Ninguna de las transferencias elegidas sigue disponible: ya salieron en otro "
                                 "archivo, se conciliaron o se anuló el pago.")
            ajenas = [x for x in filas if x["id_cuenta_fondos"] != id_cuenta]
            if ajenas:
                raise ValueError(f"{len(ajenas)} de las transferencias elegidas no son de {cuenta['nombre']}: "
                                 "el archivo se ordena desde una sola cuenta.")
            renglones = []
            for x in filas:
                motivo = _motivo(x, formato)
                renglones.append({"id_pago": x["id"], "id_instrumento": x["id_instrumento"], "cbu": x["cbu"],
                                  "cuit": x["cuit"], "nombre": x["beneficiario"], "importe": x["importe"],
                                  "incluida": not motivo, "motivo": motivo})
            n = sum(1 for r in renglones if r["incluida"])
            if not n:
                raise ValueError("Ninguna de las elegidas tiene un destino que sirva para el formato "
                                 f"{tf.FORMATOS[formato]['nombre']}.")
            hoy = datetime.date.today()
            nombre = f"transferencias_{formato}_{hoy:%Y%m%d}_{datetime.datetime.now():%H%M%S}_{n}." \
                     f"{tf.FORMATOS[formato]['extension']}"
            id_lote = tl.registrar_lote(cur, formato=formato, nombre_archivo=nombre, renglones=renglones,
                                        id_cuenta_fondos=id_cuenta, cbu_ordenante=cuenta["cbu"], concepto=concepto,
                                        id_usuario=session.get("sind_usuario_id"), fecha=hoy)
        conn.commit()
    except ValueError as e:
        conn.rollback()
        flash(f"!{e}")
        return redirect(volver)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    excluidas = len(renglones) - n
    flash(f"Archivo generado: {n} transferencia{'s' if n != 1 else ''}."
          + (f" {excluidas} quedaron afuera, con el motivo en el detalle." if excluidas else "")
          + " Subilo al home banking; si no lo subís, anulalo para liberar los pagos.")
    return redirect(url_for("transferencias.lote_ver", id_lote=id_lote, descargar=1))


def _lote(cur, id_lote):
    cur.execute("""SELECT l.*, cf.nombre AS cuenta, u.nombre AS usuario
                     FROM pago_transferencias_lote l
                     LEFT JOIN c_cuentas_de_fondos cf ON cf.id = l.id_cuenta_fondos
                     LEFT JOIN s_usuarios u ON u.id = l.id_usuario
                    WHERE l.id = %s""", (id_lote,))
    lote = cur.fetchone()
    if not lote:
        return None, []
    cur.execute("""SELECT d.*, p.nro_pago, p.nro_origen, p.fecha_pago, p.estado AS estado_pago, p.id_orden,
                          o.clase
                     FROM pago_transferencias_lote_det d
                     LEFT JOIN pago_pagos p ON p.id = d.id_pago
                     LEFT JOIN pago_ordenes o ON o.id = p.id_orden
                    WHERE d.id_lote = %s ORDER BY d.incluida DESC, d.id""", (id_lote,))
    detalle = cur.fetchall()
    for d in detalle:
        d["numero"] = str(d["nro_origen"]) if d["nro_origen"] else d["nro_pago"]
        d["clase_txt"] = CLASES_TXT.get(d["clase"], d["clase"] or "")
    return lote, detalle


@transferencias_bp.route("/lote/<int:id_lote>")
def lote_ver(id_lote):
    salida = _guardia()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            lote, detalle = _lote(cur, id_lote)
    if not lote:
        flash("!No se encontró el archivo.")
        return redirect(url_for("transferencias.index"))
    fmt = tf.FORMATOS.get(lote["formato"]) or {}
    return render_template("pagos/transferencias_lote.html", lote=lote, detalle=detalle,
                           formato_txt=fmt.get("nombre") or lote["formato"],
                           descargar=bool(request.args.get("descargar")) and not lote["fecha_anulacion"],
                           puede_ordenes=puede(url_for("pagos.ordenes")))


@transferencias_bp.route("/lote/<int:id_lote>/descargar")
def lote_descargar(id_lote):
    """El archivo armado con los renglones registrados, no con lo que dice hoy
    la ficha: si después se corrigió un CBU, el archivo que se mandó fue con el
    viejo. Volver a bajarlo no registra otro lote."""
    salida = _guardia()
    if salida:
        return salida
    volver = url_for("transferencias.lote_ver", id_lote=id_lote)
    with get_connection() as conn:
        with conn.cursor() as cur:
            lote, detalle = _lote(cur, id_lote)
    if not lote:
        flash("!No se encontró el archivo.")
        return redirect(url_for("transferencias.index"))
    if lote["formato"] not in tf.FORMATOS:
        flash(f"!El formato {lote['formato']} ya no está disponible.")
        return redirect(volver)
    para_archivo = [{"cbu_ordenante": lote["cbu_ordenante"], "cbu_destino": d["cbu_destino"],
                     "importe": d["importe"], "nro_pago": d["numero"], "cuit": d["cuit_destino"],
                     "nombre": d["beneficiario"]} for d in detalle if d["incluida"]]
    if not para_archivo:
        flash("!El archivo no tiene transferencias incluidas.")
        return redirect(volver)
    contenido, _ext, mimetype = tf.generar(lote["formato"], para_archivo, lote["concepto"] or "FAC")
    return send_file(io.BytesIO(contenido), as_attachment=True, download_name=lote["nombre_archivo"],
                     mimetype=mimetype)


@transferencias_bp.route("/lote/<int:id_lote>/excluir", methods=["POST"])
def lote_excluir(id_lote):
    salida = _guardia()
    if salida:
        return salida
    volver = url_for("transferencias.lote_ver", id_lote=id_lote)
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            res = tl.excluir_de_lote(cur, id_lote, request.form.get("id_detalle", type=int) or 0,
                                     request.form.get("motivo"), usuario=session.get("sind_usuario_nombre"))
        conn.commit()
    except ValueError as e:
        conn.rollback()
        flash(f"!{e}")
        return redirect(volver)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if res["lote_anulado"]:
        flash(f"Pago {res['nro_pago']} fuera del archivo. No le quedaban otros: el archivo quedó anulado.")
    else:
        flash(f"Pago {res['nro_pago']} fuera del archivo: ya se puede anular o mandar en otro. "
              f"Quedan {res['quedan']}. Si ya lo habías descargado, bajalo de nuevo: el anterior todavía lo trae.")
    return redirect(volver)


@transferencias_bp.route("/lote/<int:id_lote>/anular", methods=["POST"])
def lote_anular(id_lote):
    salida = _guardia()
    if salida:
        return salida
    volver = url_for("transferencias.lote_ver", id_lote=id_lote)
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            n = tl.anular_lote(cur, id_lote, request.form.get("motivo"), usuario=session.get("sind_usuario_nombre"))
        conn.commit()
    except ValueError as e:
        conn.rollback()
        flash(f"!{e}")
        return redirect(volver)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    flash(f"Archivo anulado. {'Su pago queda' if n == 1 else f'Sus {n} pagos quedan'} como no transferido"
          f"{'' if n == 1 else 's'}: se puede{'' if n == 1 else 'n'} anular o mandar en otro archivo.")
    return redirect(volver)
