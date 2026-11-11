"""
comprobantes.py — Carga de comprobantes de proveedores (ARCA).

Portado de gestion_adm (`carga_comprobante` en gestion_adm.py). Tres entradas
y un solo formulario de confirmación:

    PDF               se lee (texto, OCR si es un escaneo, Mis Comprobantes si
                      lo leído no alcanza) y se constata contra ARCA
    a mano            el formulario vacío, con el proveedor buscado por nombre
    Mis Comprobantes  ?mis=<id>: los datos los dio ARCA, no hay nada que leer

Al guardar se vuelve a validar TODO en el servidor —lo que viene del
formulario se toca con F12—: duplicados, período, importes, imputación y la
constatación con los valores que llegaron (o, si vino de Mis Comprobantes, la
fila de ARCA). Después se graban el comprobante, el expediente y la
liquidación abierta en una transacción (comprobantes_datos.registrar_comprobante)
y el PDF queda en SIND_ADJUNTOS/comprobantes/AAAAMM/.

Lo que se sacó por ser de la obra social: Integración, hospitales y
liquidaciones sin CAE, hojas del legajo, correo de comprobantes y visibilidad
por áreas.

Permiso: la opción de menú «Carga de Comprobantes» (/comprobantes/carga).
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from decimal import Decimal

import pymysql
from flask import (Blueprint, abort, flash, jsonify, redirect, render_template, request,
                   send_file, session, url_for)

import arca_wscdc
import comprobantes_datos as cd
import lector_comprobante
from db import get_connection, puede, validasesion

log = logging.getLogger(__name__)

comprobantes_bp = Blueprint("comprobantes", __name__, url_prefix="/comprobantes")

#: Los campos del formulario de confirmación.
CAMPOS = ("cuit_emisor", "tipo_comprobante", "punto_de_venta", "numero", "fecha_emision",
          "fecha_vto_pago", "periodo_desde", "periodo_hasta", "cae", "fecha_vto_cae",
          "moneda", "tipo_de_cambio", "condicion_iva_emisor", "condicion_iva_receptor",
          *cd.CAMPOS_IMPORTE)


def puede_cargar() -> bool:
    return puede(url_for("comprobantes.carga"))


def puede_ver_pdf() -> bool:
    return (puede_cargar() or puede(url_for("mesa.bandeja"))
            or puede(url_for("mis_comp.listado")))


def _usuario_id():
    return session.get("sind_usuario_id")


def _fmt_fecha(v) -> str:
    """aaaa-mm-dd, lo que espera un <input type="date">. Lo ilegible, vacío."""
    f = cd.fecha(v)
    return f.isoformat() if f else ""


def _fmt_imp(v) -> str:
    d = cd.importe(v)
    return f"{d:.2f}" if d is not None else ""


def _mes_de(fe) -> tuple[str, str]:
    """El primer y el último día del mes de una fecha, aaaa-mm-dd."""
    f = cd.fecha(fe)
    if not f:
        return "", ""
    ult = (f.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return f.replace(day=1).isoformat(), ult.isoformat()


def _completar(d: dict) -> dict:
    """Formato del formulario: fechas ISO, importes con punto, período por defecto."""
    d = {k: ("" if d.get(k) is None else d.get(k)) for k in CAMPOS} | \
        {k: v for k, v in d.items() if k not in CAMPOS}
    for k in ("fecha_emision", "fecha_vto_pago", "periodo_desde", "periodo_hasta", "fecha_vto_cae"):
        d[k] = _fmt_fecha(d.get(k))
    for k in cd.CAMPOS_IMPORTE:
        d[k] = _fmt_imp(d.get(k)) if str(d.get(k) or "").strip() else ""
    d["moneda"] = d.get("moneda") or "PES"
    d["tipo_de_cambio"] = d.get("tipo_de_cambio") or "1"
    for k, n in (("tipo_comprobante", 3), ("punto_de_venta", 5), ("numero", 8)):
        if cd.solo_digitos(d.get(k)):
            d[k] = cd.solo_digitos(d[k]).zfill(n)
    # El período: lo que declara el comprobante, o el mes de emisión.
    if not d["periodo_desde"] and d["fecha_emision"]:
        d["periodo_desde"], ph = _mes_de(d["fecha_emision"])
        d["periodo_hasta"] = d["periodo_hasta"] or ph
        d["_periodo_sugerido"] = True
    return d


def _constatar_datos(d: dict, cuit_receptor: str) -> dict | None:
    """Constatación WSCDC de lo leído/tipeado, si está configurada y alcanzan los datos."""
    ok, _ = arca_wscdc.configurado()
    if not ok:
        return None
    imp = cd.importe(d.get("importe_total"))
    fe = cd.fecha(d.get("fecha_emision"))
    if not (len(cd.solo_digitos(d.get("cuit_emisor"))) == 11 and d.get("tipo_comprobante")
            and d.get("punto_de_venta") and d.get("numero") and fe and imp and d.get("cae")):
        return None
    r = arca_wscdc.constatar(d["cuit_emisor"], d["tipo_comprobante"], d["punto_de_venta"],
                             d["numero"], fe, imp, d["cae"], cuit_receptor or None)
    obs = (r.get("errores") or []) + (r.get("observaciones") or [])
    if r["resultado"] == "A":
        obs = [{"code": "0", "msg": "Autorizado por ARCA (WSCDC)"
                + (f", proceso {r['fch_proceso']}" if r.get("fch_proceso") else "")}] + obs
    return {"resultado": r["resultado"], "origen": "wscdc", "fecha": r["fch_proceso"] or date.today().isoformat(),
            "obs": obs,
            "texto": arca_wscdc.texto_resultado(r)}


def _contexto(cur, d: dict | None, **extra) -> dict:
    """Lo que la plantilla necesita alrededor del formulario."""
    inst = cd.institucion(cur)
    prov = cd.proveedor_por_cuit(cur, d.get("cuit_emisor")) if d and d.get("cuit_emisor") else None
    cst_ok, cst_motivo = arca_wscdc.configurado()
    cur.execute("""SELECT COUNT(*) AS n FROM f_mis_comprobantes m
                    WHERE m.ignorado = 0 AND (m.id_comprobante IS NULL OR NOT EXISTS
                          (SELECT 1 FROM me_expedientes x WHERE x.id_comprobante = m.id_comprobante))""")
    pendientes = cur.fetchone()["n"]
    # ¿Lo informa ARCA en Mis Comprobantes? Al guardar queda verificado si
    # coinciden el importe y el CAE (comprobantes_datos.marcar_verificacion_mis).
    en_mis = None
    if d and len(cd.solo_digitos(d.get("cuit_emisor"))) == 11 and cd.solo_digitos(d.get("numero")):
        cur.execute("""SELECT id, importe_total, cae FROM f_mis_comprobantes
                        WHERE cuit_emisor = %s AND CAST(tipo_comprobante AS UNSIGNED) = %s
                          AND CAST(punto_de_venta AS UNSIGNED) = %s AND CAST(numero AS UNSIGNED) = %s""",
                    (cd.solo_digitos(d["cuit_emisor"]), int(cd.solo_digitos(d.get("tipo_comprobante")) or 0),
                     int(cd.solo_digitos(d.get("punto_de_venta")) or 0), int(cd.solo_digitos(d["numero"]))))
        en_mis = cur.fetchone()
        if en_mis:
            imp = cd.importe(d.get("importe_total"))
            en_mis["coincide"] = imp is not None and abs(en_mis["importe_total"] - imp) <= Decimal("0.01")
    return {"datos": d, "prov": prov, "inst": inst, "en_mis": en_mis,
            "imputacion": cd.opciones_de_imputacion(cur, prov["id"]) if prov else None,
            "tipos": cd.tipos_comprobante(cur), "wscdc_ok": cst_ok, "wscdc_motivo": cst_motivo,
            "pendientes_arca": pendientes, "puede_mis": puede(url_for("mis_comp.listado")),
            "puede_alta_prov": puede(url_for("proveedores.abm"))} | extra


# =============================================================================
# Pantalla
# =============================================================================

@comprobantes_bp.route("/carga", methods=["GET", "POST"])
def carga():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede_cargar():
        flash("!No tenés permiso para cargar comprobantes.")
        return redirect(url_for("menu"))

    accion = request.form.get("accion") if request.method == "POST" else None
    if accion == "leer":
        return _leer()
    if accion == "guardar":
        return _guardar()

    with get_connection() as conn:
        with conn.cursor() as cur:
            id_mis = request.args.get("mis", type=int)
            if id_mis:
                return _desde_mis(cur, id_mis)
            if request.args.get("manual"):
                return render_template("comprobantes/carga.html", paso="confirmar", modo="manual",
                                       **_contexto(cur, _completar({})))
            return render_template("comprobantes/carga.html", paso="subir", modo=None,
                                   **_contexto(cur, None))


def _leer():
    archivo = request.files.get("pdf")
    if not archivo or not archivo.filename:
        flash("!Elegí el PDF del comprobante.")
        return redirect(url_for("comprobantes.carga"))
    contenido = archivo.read()
    if not contenido.startswith(b"%PDF"):
        flash("!El archivo no es un PDF.")
        return redirect(url_for("comprobantes.carga"))
    if len(contenido) > 15 * 1024 * 1024:
        flash("!El PDF pasa de 15 MB.")
        return redirect(url_for("comprobantes.carga"))

    ficha = cd.guardar_tmp(contenido)
    errores, avisos = [], []
    with get_connection() as conn:
        with conn.cursor() as cur:
            inst = cd.institucion(cur)
            lect = lector_comprobante.leer(contenido, cur)
            d = lect["datos"] or {}
            if lect["aviso"]:
                avisos.append(lect["aviso"])

            # El receptor tiene que ser el sindicato. Un CUIT nuestro sin
            # rótulo en el texto también vale (gestion_adm).
            rec = cd.solo_digitos(d.get("cuit_receptor"))
            if inst["cuit"] and not rec and inst["cuit"] in (d.get("cuits_en_el_texto") or []):
                rec = inst["cuit"]
            if inst["cuit"] and rec and rec != inst["cuit"]:
                errores.append(f"El comprobante está emitido al CUIT {rec}, que no es el del sindicato "
                               f"({inst['cuit']}). Verificá que sea un comprobante para nosotros.")
                return render_template("comprobantes/carga.html", paso="subir", modo=None,
                                       errores=errores, texto=lect["texto"], **_contexto(cur, None))
            if inst["cuit"] and not rec:
                avisos.append(f"No se encontró el CUIT receptor en el PDF: verificá que el comprobante "
                              f"sea para el sindicato ({inst['cuit']}).")

            if d.get("cae"):
                dup = cd.duplicado(cur, d.get("cuit_emisor"), d.get("tipo_comprobante"),
                                   d.get("punto_de_venta"), d.get("numero"), d.get("cae"))
                if dup:
                    errores.append(dup)
                    return render_template("comprobantes/carga.html", paso="subir", modo=None,
                                           errores=errores, texto=lect["texto"], **_contexto(cur, None))

            datos = _completar(d)
            # La razón social: la de la ficha si es un proveedor nuestro.
            modo = "pdf"
            cst = None
            if lect["faltan"]:
                modo = "manual"
                errores.append("El PDF no se pudo leer por completo. Faltan: " + ", ".join(lect["faltan"])
                               + ". Completalos mirando el PDF; se validan al guardar.")
            else:
                cst = _constatar_datos(datos, inst["cuit"])
                if cst and cst["resultado"] == "R":
                    errores.append("ARCA no reconoce el comprobante con estos datos"
                                   + (f" — {cst['texto']}" if cst.get("texto") else "")
                                   + ". Si el PDF se leyó mal, corregí los datos; si no, pedile al proveedor "
                                     "el comprobante correcto.")
            for a in avisos:
                flash("!" + a)
            return render_template("comprobantes/carga.html", paso="confirmar", modo=modo,
                                   errores=errores, texto=lect["texto"], pdf_ficha=ficha,
                                   pdf_nombre=archivo.filename, cst=cst,
                                   **_contexto(cur, datos))


def _desde_mis(cur, id_mis: int):
    cur.execute("SELECT * FROM f_mis_comprobantes WHERE id = %s", (id_mis,))
    m = cur.fetchone()
    if not m:
        flash("!Ese comprobante de ARCA no existe.")
        return redirect(url_for("comprobantes.carga"))
    if m["id_comprobante"]:
        cur.execute("SELECT id FROM me_expedientes WHERE id_comprobante = %s", (m["id_comprobante"],))
        e = cur.fetchone()
        flash("!Ese comprobante ya está cargado.")
        if e and puede(url_for("mesa.bandeja")):
            return redirect(url_for("mesa.detalle", exp_id=e["id"]))
        return redirect(url_for("comprobantes.carga"))
    datos = _completar({
        "cuit_emisor": m["cuit_emisor"], "tipo_comprobante": m["tipo_comprobante"],
        "punto_de_venta": m["punto_de_venta"], "numero": m["numero"],
        "fecha_emision": m["fecha_emision"], "cae": m["cae"] or "",
        # El CAE vence a los 10 días corridos de la emisión (gestion_adm).
        "fecha_vto_cae": m["fecha_emision"] + timedelta(days=10) if m["cae"] else "",
        "importe_neto_gravado": m["importe_neto"], "importe_neto_no_grav": m["importe_no_grav"],
        "importe_exento": m["importe_exento"], "importe_iva": m["importe_iva"],
        "importe_otros": m["importe_otros"], "importe_total": m["importe_total"],
        "moneda": m["moneda"], "tipo_de_cambio": m["tipo_de_cambio"],
        "_razon_arca": m["razon_social"] or ""})
    cst = {"resultado": "A", "origen": "mis", "fecha": date.today().isoformat(),
           "obs": [{"code": "0", "msg": "Informado por ARCA en Mis Comprobantes"
                    + (f" — {m['nombre_archivo']}" if m.get("nombre_archivo") else "")}],
           "texto": "Informado por ARCA en Mis Comprobantes."}
    return render_template("comprobantes/carga.html", paso="confirmar", modo="mis", id_mis=id_mis,
                           cst=cst, **_contexto(cur, datos))


def _guardar():
    f = request.form
    d = {k: (f.get(k) or "").strip() for k in CAMPOS}
    d["_razon_arca"] = (f.get("_razon_arca") or "").strip()
    modo = f.get("modo") or "manual"
    id_mis = f.get("id_mis", type=int)
    id_rubro = f.get("id_rubro_pasivo", type=int)
    id_concepto = f.get("id_concepto_gasto", type=int)
    nota = (f.get("nota") or "").strip()[:400] or None
    ficha = (f.get("pdf_ficha") or "").strip()
    pdf_nombre = (f.get("pdf_nombre") or "").strip()

    # Un PDF adjuntado en este paso (desde Mis Comprobantes o a mano).
    adj = request.files.get("pdf_adjunto")
    errores = []
    if adj and adj.filename:
        contenido = adj.read()
        if not contenido.startswith(b"%PDF"):
            errores.append("El archivo adjunto no es un PDF.")
        elif len(contenido) > 15 * 1024 * 1024:
            errores.append("El PDF pasa de 15 MB.")
        else:
            ficha, pdf_nombre = cd.guardar_tmp(contenido), adj.filename
    ruta_pdf = cd.ruta_tmp(ficha)
    if ficha and not ruta_pdf:
        ficha = ""

    cst = None
    with get_connection() as conn:
        with conn.cursor() as cur:
            inst = cd.institucion(cur)
            v, err_val = cd.validar(cur, d)
            errores += err_val
            prov = cd.proveedor_por_cuit(cur, v["cuit_emisor"]) if len(v["cuit_emisor"]) == 11 else None
            if len(v["cuit_emisor"]) == 11:
                if not prov:
                    errores.append(f"El CUIT {v['cuit_emisor']} no es un proveedor dado de alta. "
                                   "Dalo de alta (con su rubro de pasivo y su concepto de gasto) y volvé a cargar.")
                elif not prov["activo"]:
                    errores.append(f"{prov['razon_social']} está dado de baja: reactivalo en su ficha "
                                   "para cargarle comprobantes.")
                else:
                    errores += cd.errores_de_imputacion(cur, prov["id"], id_rubro, id_concepto)
            if not errores:
                dup = cd.duplicado(cur, v["cuit_emisor"], v["tipo_comprobante"], v["punto_de_venta"],
                                   v["numero"], v["cae"])
                if dup:
                    errores.append(dup)

            # La constatación, otra vez y con lo que llegó: lo de la pantalla
            # es una cortesía, no un control.
            if not errores:
                if modo == "mis":
                    cst, err = _verificar_mis(cur, id_mis, v)
                    if err:
                        errores.append(err)
                else:
                    cst = _constatar_datos(d, inst["cuit"])
                    if cst and cst["resultado"] == "R":
                        errores.append("ARCA no reconoce el comprobante con estos datos"
                                       + (f" — {cst['texto']}" if cst.get("texto") else "")
                                       + ". No se puede dar ingreso: verificá los datos o pedile al "
                                         "proveedor el comprobante correcto.")
                    elif cst and cst["resultado"] == "E":
                        flash("!No se pudo constatar con ARCA (" + (cst.get("texto") or "sin detalle")
                              + "). El comprobante queda cargado sin constatar.")

            if errores:
                cst_vista = None
                if modo == "mis":
                    cst_vista = {"resultado": "A", "origen": "mis", "texto": "Informado por ARCA en Mis Comprobantes."}
                return render_template("comprobantes/carga.html", paso="confirmar", modo=modo,
                                       id_mis=id_mis, errores=errores, cst=cst or cst_vista,
                                       pdf_ficha=ficha, pdf_nombre=pdf_nombre, nota=nota,
                                       elegido_rubro=id_rubro, elegido_concepto=id_concepto,
                                       **_contexto(cur, _completar(d)))

            conn.begin()
            archivo_nuevo = None
            try:
                res = cd.registrar_comprobante(cur, v, prov, inst, _usuario_id(), id_rubro, id_concepto,
                                               cst and {"resultado": cst["resultado"], "fecha": cst.get("fecha"),
                                                        "obs": cst.get("obs")})
                if nota:
                    cd.movimiento(cur, res["id_expediente"], "nota", "ingresado", _usuario_id(), nota)
                if ruta_pdf:
                    rel = cd.archivar_pdf(ruta_pdf, v["fecha_emision"],
                                          cd.nombre_pdf(v["cuit_emisor"], v["tipo_comprobante"],
                                                        v["punto_de_venta"], v["numero"]))
                    archivo_nuevo = cd.ruta_real(rel)
                    leido, obs = cd.cotejar(archivo_nuevo, v)
                    cur.execute("""UPDATE f_comprobantes_arca SET nombre_archivo = %s, ruta_local = %s,
                                          leido_automatico = %s WHERE id = %s""",
                                (rel.rsplit("/", 1)[-1], rel, 1 if leido else 0, res["id_comprobante"]))
                    if obs:
                        flash("!" + obs + " El PDF queda pendiente de verificación visual.")
                conn.commit()
            except (pymysql.MySQLError, ValueError, OSError) as e:
                conn.rollback()
                if archivo_nuevo:
                    try:
                        archivo_nuevo.unlink()
                    except OSError:
                        pass
                log.exception("Guardando el comprobante %s", v)
                return render_template("comprobantes/carga.html", paso="confirmar", modo=modo,
                                       id_mis=id_mis, cst=cst, pdf_ficha=ficha, pdf_nombre=pdf_nombre,
                                       nota=nota, errores=[f"No se pudo guardar: {e}"],
                                       elegido_rubro=id_rubro, elegido_concepto=id_concepto,
                                       **_contexto(cur, _completar(d)))
    if ruta_pdf:
        try:
            ruta_pdf.unlink()
        except OSError:
            pass

    est = {"A": " Constatado en ARCA.", "E": " Sin constatar (ARCA no respondió).",
           None: " Sin constatar."}.get(cst["resultado"] if cst else None, "")
    flash(f"Comprobante cargado: expediente {res['nro_expediente']}, con la liquidación pendiente de auditoría."
          + est + ("" if ruta_pdf else " Sin PDF: se puede adjuntar desde el expediente."))
    if puede(url_for("mesa.bandeja")):
        return redirect(url_for("mesa.detalle", exp_id=res["id_expediente"]))
    return redirect(url_for("comprobantes.carga"))


def _verificar_mis(cur, id_mis, v) -> tuple[dict | None, str | None]:
    """El comprobante que vino de Mis Comprobantes tiene que seguir siendo el de ARCA."""
    if not id_mis:
        return None, "Falta la referencia al comprobante de Mis Comprobantes."
    cur.execute("SELECT * FROM f_mis_comprobantes WHERE id = %s", (id_mis,))
    m = cur.fetchone()
    if not m:
        return None, "El comprobante de Mis Comprobantes ya no existe."
    iguales = (m["cuit_emisor"] == v["cuit_emisor"]
               and int(m["tipo_comprobante"]) == int(v["tipo_comprobante"])
               and int(m["punto_de_venta"]) == int(v["punto_de_venta"])
               and int(m["numero"]) == int(v["numero"])
               and abs(m["importe_total"] - v["importe_total"]) <= 0.01
               and m["fecha_emision"] == v["fecha_emision"]
               and (not m["cae"] or not v["cae"] or m["cae"] == v["cae"]))
    if not iguales:
        return None, ("Los datos no coinciden con los que informó ARCA en Mis Comprobantes "
                      "(CUIT, tipo, número, fecha, importe o CAE). No se modifican: volvé a "
                      "entrar desde Comprobantes ARCA.")
    return {"resultado": "A", "origen": "mis", "fecha": date.today().isoformat(),
            "obs": [{"code": "0", "msg": "Informado por ARCA en Mis Comprobantes"
                     + (f" — {m['nombre_archivo']}" if m.get("nombre_archivo") else "")}]}, None


# =============================================================================
# PDFs y APIs
# =============================================================================

@comprobantes_bp.route("/tmp/<ficha>")
def pdf_tmp(ficha):
    """El PDF subido que todavía no se guardó, para verlo al confirmar."""
    if not validasesion() or not puede_cargar():
        abort(403)
    p = cd.ruta_tmp(ficha)
    if not p:
        abort(404)
    return send_file(p, mimetype="application/pdf")


@comprobantes_bp.route("/<int:id_comprobante>/pdf")
def pdf(id_comprobante):
    if not validasesion() or not puede_ver_pdf():
        abort(403)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT ruta_local, nombre_archivo FROM f_comprobantes_arca WHERE id = %s",
                        (id_comprobante,))
            c = cur.fetchone()
    p = cd.ruta_real(c and c["ruta_local"])
    if not p:
        abort(404)
    return send_file(p, mimetype="application/pdf", download_name=c["nombre_archivo"] or p.name)


@comprobantes_bp.route("/api/proveedor/<cuit>")
def api_proveedor(cuit):
    """El proveedor por CUIT, su imputación y lo que ARCA informa sin cargar."""
    if not validasesion() or not puede_cargar():
        return jsonify({"error": "Sin permiso"}), 403
    cuit = re.sub(r"\D", "", cuit)
    with get_connection() as conn:
        with conn.cursor() as cur:
            prov = cd.proveedor_por_cuit(cur, cuit)
            if not prov:
                return jsonify({"existe": False})
            op = cd.opciones_de_imputacion(cur, prov["id"])
            cur.execute("""SELECT m.id, m.fecha_emision, m.tipo_comprobante, m.punto_de_venta, m.numero,
                                  m.importe_total, t.descripcion AS tipo
                             FROM f_mis_comprobantes m
                             LEFT JOIN arca_tipo_comprobante t ON t.codigo = m.tipo_comprobante
                            WHERE m.cuit_emisor = %s AND m.ignorado = 0 AND m.id_comprobante IS NULL
                            ORDER BY m.fecha_emision DESC LIMIT 30""", (cuit,))
            pend = cur.fetchall()
    return jsonify({
        "existe": True, "id": prov["id"], "razon_social": prov["razon_social"], "activo": prov["activo"],
        "condicion_iva": prov["condicion_iva_txt"] or "",
        "rubros": [{"id": r["id"], "nombre": r["nombre"], "pred": r["predeterminada"]} for r in op["rubros"]],
        "conceptos": [{"id": c["id"], "nombre": c["descripcion"], "pred": c["predeterminada"]}
                      for c in op["conceptos"]],
        "pendientes": [{"id": p["id"], "fecha": p["fecha_emision"].strftime("%d/%m/%Y"),
                        "tipo": p["tipo"] or p["tipo_comprobante"],
                        "numero": f"{p['punto_de_venta']}-{p['numero']}",
                        "total": float(p["importe_total"])} for p in pend],
    })

