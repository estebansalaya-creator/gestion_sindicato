"""
reintegros.py — Pantallas del circuito de reintegros a afiliados.

Las mismas pantallas que gestion_adm (`reintegros_routes.py`), armadas con el
sistema de estilos de este proyecto:

  /reintegros/solicitud              listado de solicitudes y carga (?edit=ID, ?nuevo=1)
  /reintegros/solicitud/<id>         ficha de consulta, en cualquier estado
  /reintegros/solicitud/<id>/pdf     constancia para el afiliado
  /reintegros/auditoria              bandeja de solicitudes en auditoría
  /reintegros/auditoria/<id>         auditoría: importe reconocido por renglón
  /reintegros/ordenes                reintegros con saldo → órdenes de pago

Lo que cambia respecto de gestion_adm:

- Permisos: cada pantalla es una opción de menú y se controla en el servidor
  con `db.puede`, no solo escondiendo botones (en gestion_adm, cualquiera con
  sesión podía postear una auditoría). Cargar = «Solicitudes de Reintegro»;
  auditar, corregir una auditada y anular = «Auditoría de Reintegros»;
  generar órdenes = «Órdenes de Pago de Reintegros». La ficha la ve quien
  tenga cualquiera de las tres.
- La ficha de consulta existe: en gestion_adm el botón «ver» de una aprobada
  llevaba a la pantalla de auditoría, que la rechazaba por no estar en
  auditoría.
- Anular: la función estaba y ninguna pantalla la usaba.
- Las grillas filtran en el navegador, con la barra de todas las pantallas.
- Los adjuntos se guardan con la ruta relativa a SIND_ADJUNTOS, no absoluta:
  mover la carpeta no deja a todos los comprobantes apuntando a la nada.
"""

from __future__ import annotations

import datetime
import io
import os
from pathlib import Path

from flask import (Blueprint, flash, jsonify, redirect, render_template, request,
                   send_file, session, url_for)
from werkzeug.utils import secure_filename

import institucion
import reintegros_datos as svc
from db import puede, validasesion
from reintegros_datos import ReintegroError

reintegros_bp = Blueprint("reintegros", __name__, url_prefix="/reintegros")

EXTENSIONES_OK = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
MAX_ADJUNTO_MB = 10


# =============================================================================
# Permisos y helpers
# =============================================================================

def puede_cargar() -> bool:
    return puede(url_for("reintegros.solicitud"))


def puede_auditar() -> bool:
    return puede(url_for("reintegros.auditoria"))


def puede_ordenes() -> bool:
    return puede(url_for("reintegros.ordenes"))


def puede_ver() -> bool:
    return puede_cargar() or puede_auditar() or puede_ordenes()


def _sin_permiso(texto: str):
    flash("!" + texto)
    return redirect(url_for("menu"))


def _usuario_id():
    return session.get("sind_usuario_id")


def _pesos(valor) -> str:
    entero, _, dec = f"{float(valor or 0):,.2f}".partition(".")
    return f"{entero.replace(',', '.')},{dec}"


def base_adjuntos() -> Path:
    """
    Dónde se guardan los comprobantes. SIND_ADJUNTOS en el .env, o la carpeta
    `adjuntos` del proyecto. El pool de IIS necesita permiso de escritura ahí.
    """
    return Path(os.getenv("SIND_ADJUNTOS") or Path(__file__).with_name("adjuntos"))


def _ruta_real(ruta: str) -> Path | None:
    """
    El archivo de un adjunto. Las rutas se guardan relativas a base_adjuntos();
    una absoluta (cargada a mano o de otro sistema) se respeta. Una relativa que
    se escape de la base con `..` no se sirve.
    """
    p = Path(ruta)
    if p.is_absolute():
        return p
    base = base_adjuntos().resolve()
    real = (base / p).resolve()
    return real if base in real.parents else None


def _volver_local(destino: str | None, defecto: str) -> str:
    """Solo rutas de este sitio: un `volver` armado afuera no redirige a otro dominio."""
    if destino and destino.startswith("/") and not destino.startswith("//"):
        return destino
    return defecto


def _renglones_del_form(form) -> list[dict]:
    """
    Cada renglón viaja con un uid propio (det_uid) y sus campos se leen por uid:
    agregar o quitar filas en el navegador no descoloca los datos.
    """
    renglones = []
    for uid in form.getlist("det_uid"):
        concepto = (form.get(f"det_concepto_{uid}") or "").strip()
        afiliado = (form.get(f"det_afiliado_{uid}") or "").strip()
        importe  = (form.get(f"det_importe_{uid}") or "").strip()
        if not concepto and not afiliado and not importe:
            continue
        if not concepto or not afiliado or not importe:
            raise ReintegroError("Cada renglón necesita afiliado, concepto e importe.")
        renglones.append({
            "uid":                  uid,
            "id_detalle":           form.get(f"det_id_{uid}", type=int),
            "id_concepto_gasto":    int(concepto),
            "id_afiliado":          int(afiliado),
            "fecha_gasto":          (form.get(f"det_fecha_{uid}") or "").strip() or None,
            "nro_comprobante":      (form.get(f"det_comprobante_{uid}") or "").strip()[:30] or None,
            "importe_solicitado":   importe,
            "comentario_solicitud": (form.get(f"det_comentario_{uid}") or "").strip()[:250] or None,
        })
    return renglones


def _guardar_archivos(id_reintegro, mapa_uid: dict, archivos) -> tuple[int, list]:
    """Guarda los adjuntos que vinieron en cada renglón. Devuelve (guardados, errores)."""
    relativa = Path("reintegros") / str(id_reintegro)
    carpeta = base_adjuntos() / relativa
    guardados, errores = 0, []
    for uid, id_detalle in mapa_uid.items():
        for f in archivos.getlist(f"det_archivos_{uid}"):
            if not f or not f.filename:
                continue
            nombre = secure_filename(f.filename) or "comprobante"
            if os.path.splitext(nombre)[1].lower() not in EXTENSIONES_OK:
                errores.append(f"{f.filename}: solo PDF o imagen.")
                continue
            carpeta.mkdir(parents=True, exist_ok=True)
            sello = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")
            archivo = f"{id_detalle}_{sello}_{nombre}"
            destino = carpeta / archivo
            f.save(destino)
            if destino.stat().st_size > MAX_ADJUNTO_MB * 1024 * 1024:
                destino.unlink()
                errores.append(f"{f.filename}: supera los {MAX_ADJUNTO_MB} MB.")
                continue
            try:
                svc.registrar_adjunto(id_detalle, (relativa / archivo).as_posix(),
                                      f.filename[:500], _usuario_id())
            except Exception:
                destino.unlink(missing_ok=True)
                raise
            guardados += 1
    return guardados, errores


def _borrar_archivo(ruta: str | None) -> None:
    real = _ruta_real(ruta) if ruta else None
    if real and real.exists():
        try:
            real.unlink()
        except OSError:
            pass    # el registro ya no está; un archivo huérfano no rompe nada


# =============================================================================
# 1. Solicitudes: listado y carga
# =============================================================================

@reintegros_bp.route("")
@reintegros_bp.route("/")
def inicio():
    # La URL que tenía el menú antes de que el módulo existiera.
    return redirect(url_for("reintegros.solicitud"))


@reintegros_bp.route("/solicitud", methods=["GET", "POST"])
def solicitud():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede_cargar():
        if puede_ver():
            return redirect(url_for("reintegros.auditoria") if puede_auditar()
                            else url_for("reintegros.ordenes"))
        return _sin_permiso("No tenés permiso para la carga de reintegros.")

    if request.method == "POST":
        return _guardar_solicitud()

    edit_id = request.args.get("edit", type=int)
    reintegro, familia = None, []
    if edit_id:
        reintegro = svc.obtener(edit_id)
        if not reintegro:
            flash("!La solicitud no existe.")
            return redirect(url_for("reintegros.solicitud"))
        se_puede, motivo = svc.editable(reintegro)
        if not se_puede:
            flash("!" + motivo)
            return redirect(url_for("reintegros.ficha", id_reintegro=edit_id))
        # Corregir una enviada le saca la aprobación, así que la abre solo
        # quien puede volver a darla. Para el resto, una solicitud enviada
        # dejó de ser suya.
        if reintegro["estado"] != "borrador" and not puede_auditar():
            flash("!La solicitud ya fue enviada a auditoría y no se puede editar desde acá.")
            return redirect(url_for("reintegros.ficha", id_reintegro=edit_id))
        familia = svc.grupo_familiar(reintegro["id_afiliado"])

    usados = [d["id_concepto_gasto"] for d in (reintegro or {}).get("detalle", [])]
    conceptos = svc.conceptos_de_gasto(incluir=usados)
    return render_template(
        "reintegros/solicitud.html",
        reintegro      = reintegro,
        familia        = familia,
        conceptos      = conceptos,
        solicitudes    = svc.listar(),
        clases         = svc.CLASES,
        atributos      = svc.atributos_activos(),
        estados        = svc.ESTADOS,
        estados_label  = svc.ESTADOS_LABEL,
        estados_tipo   = svc.ESTADOS_TIPO,
        hoy            = datetime.date.today().isoformat(),
        max_mb         = MAX_ADJUNTO_MB,
        puede_auditar  = puede_auditar(),
        nuevo          = bool(request.args.get("nuevo")),
    )


def _guardar_solicitud():
    id_reintegro = request.form.get("id_reintegro", type=int)
    datos = {
        "id_afiliado":     request.form.get("id_afiliado", type=int),
        "fecha_solicitud": request.form.get("fecha_solicitud") or None,
        "cbu_destino":     (request.form.get("cbu_destino") or "").strip() or None,
        "alias_destino":   (request.form.get("alias_destino") or "").strip()[:50] or None,
        "observaciones":   (request.form.get("observaciones") or "").strip()[:500] or None,
    }
    accion = request.form.get("accion") or "guardar"
    volver = (url_for("reintegros.solicitud", edit=id_reintegro) if id_reintegro
              else url_for("reintegros.solicitud", nuevo=1))

    if id_reintegro and not puede_auditar():
        actual = svc.obtener(id_reintegro) or {}
        if actual.get("estado") != "borrador":
            flash("!La solicitud ya fue enviada a auditoría y no se puede editar desde acá.")
            return redirect(url_for("reintegros.ficha", id_reintegro=id_reintegro))
    if accion == "enviar_y_auditar" and not puede_auditar():
        flash("!No tenés permiso para auditar reintegros.")
        return redirect(volver)

    try:
        renglones = _renglones_del_form(request.form)
        id_reintegro, mapa_uid = svc.guardar(datos, renglones, _usuario_id(), id_reintegro)
    except ReintegroError as e:
        flash(f"!{e}")
        return redirect(volver)

    volver = url_for("reintegros.solicitud", edit=id_reintegro)
    try:
        n, errores = _guardar_archivos(id_reintegro, mapa_uid, request.files)
    except ReintegroError as e:
        n, errores = 0, [str(e)]
    nro = (svc.obtener(id_reintegro) or {}).get("nro_solicitud", "")
    msg = f"Solicitud {nro} guardada."
    if n:
        msg += f" {n} comprobante{'s' if n != 1 else ''} adjuntado{'s' if n != 1 else ''}."
    flash(msg)
    if errores:
        flash("!No se adjuntaron: " + " ".join(errores))

    try:
        if accion == "enviar_y_auditar":
            # Cargar y auditar en un paso, para quien tiene las dos pantallas:
            # en la ventanilla la misma persona recibe los comprobantes, los
            # mira y resuelve. Aprueba por lo solicitado; reconocer menos se
            # hace en la pantalla de auditoría. Quedan registrados quién cargó
            # y quién auditó, así que se ve que fue la misma persona.
            estado = (svc.obtener(id_reintegro) or {}).get("estado")
            sin_respaldo = (svc.enviar_a_auditoria(id_reintegro)
                            if estado == "borrador" else False)
            total = svc.auditar(id_reintegro, _usuario_id(), {})
            flash(f"Solicitud {nro} auditada y aprobada por $ {_pesos(total)}.")
            if sin_respaldo:
                flash("!Se aprobó sin documentación de respaldo: quedó escrito en la "
                      "observación de la solicitud.")
            return redirect(url_for("reintegros.solicitud"))

        if accion == "enviar":
            sin_respaldo = svc.enviar_a_auditoria(id_reintegro)
            flash(f"Solicitud {nro} enviada a auditoría.")
            if sin_respaldo:
                flash("!Va sin documentación de respaldo. Si la conseguís, adjuntala antes "
                      "de que se audite; si se aprueba sin comprobantes queda constancia.")
            return redirect(url_for("reintegros.solicitud"))
    except ReintegroError as e:
        flash(f"!{e}")

    return redirect(volver)


@reintegros_bp.route("/solicitud/<int:id_reintegro>/eliminar", methods=["POST"])
def eliminar_solicitud(id_reintegro):
    if not validasesion():
        return redirect(url_for("login"))
    if not puede_cargar():
        return _sin_permiso("No tenés permiso para la carga de reintegros.")
    try:
        for ruta in svc.eliminar(id_reintegro):
            _borrar_archivo(ruta)
        flash("Solicitud eliminada.")
    except ReintegroError as e:
        flash(f"!{e}")
    return redirect(url_for("reintegros.solicitud"))


@reintegros_bp.route("/solicitud/<int:id_reintegro>/anular", methods=["POST"])
def anular_solicitud(id_reintegro):
    if not validasesion():
        return redirect(url_for("login"))
    if not puede_auditar():
        return _sin_permiso("Anular una solicitud es de la auditoría de reintegros.")
    try:
        svc.anular(id_reintegro, _usuario_id(), request.form.get("motivo"))
        flash("Solicitud anulada.")
    except ReintegroError as e:
        flash(f"!{e}")
    return redirect(url_for("reintegros.ficha", id_reintegro=id_reintegro))


# =============================================================================
# 2. Ficha de consulta
# =============================================================================

@reintegros_bp.route("/solicitud/<int:id_reintegro>")
def ficha(id_reintegro):
    if not validasesion():
        return redirect(url_for("login"))
    if not puede_ver():
        return _sin_permiso("No tenés permiso para los reintegros.")
    r = svc.obtener(id_reintegro)
    if not r:
        flash("!La solicitud no existe.")
        return redirect(url_for("reintegros.solicitud"))
    return _ficha(r, "ver")


def _ficha(r: dict, modo: str):
    se_puede, _ = svc.editable(r)
    return render_template(
        "reintegros/ficha.html",
        r             = r,
        modo          = modo,
        estados_label = svc.ESTADOS_LABEL,
        estados_tipo  = svc.ESTADOS_TIPO,
        orden_label   = svc.ESTADOS_ORDEN_LABEL,
        orden_tipo    = svc.ESTADOS_ORDEN_TIPO,
        puede_auditar = puede_auditar(),
        puede_editar  = se_puede and puede_cargar()
                        and (r["estado"] == "borrador" or puede_auditar()),
        puede_anular  = puede_auditar() and not r.get("id_orden_pago")
                        and r["estado"] in ("en_auditoria", "aprobada"),
    )


# =============================================================================
# 3. Constancia en PDF
# =============================================================================

@reintegros_bp.route("/solicitud/<int:id_reintegro>/pdf")
def constancia(id_reintegro):
    """
    El papel que se lleva el que vino a presentar los comprobantes: qué
    presentó, cuándo, por cuánto, y con qué número reclamarlo. No es una
    aprobación, y lo dice al pie. Se imprime en cualquier estado, también en
    borrador —cuando el afiliado está en el mostrador—, marcado como tal. Lo
    aprobado y la orden aparecen recién cuando existen.
    """
    if not validasesion():
        return redirect(url_for("login"))
    if not puede_ver():
        return _sin_permiso("No tenés permiso para los reintegros.")
    r = svc.obtener(id_reintegro)
    if not r:
        flash("!La solicitud no existe.")
        return redirect(url_for("reintegros.solicitud"))
    buf = _pdf_constancia(r)
    nombre = "reintegro_" + ((r.get("nro_solicitud") or "").replace("/", "-")
                             or f"borrador_{id_reintegro}")
    # inline: se abre en el visor del navegador, que es de donde se imprime.
    return send_file(buf, mimetype="application/pdf", as_attachment=False,
                     download_name=f"{nombre}.pdf")


def _pdf_constancia(r: dict) -> io.BytesIO:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (HRFlowable, Image, Paragraph, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)
    from xml.sax.saxutils import escape

    # Los colores de la marca, los de sindicato.css.
    NAVY, MUTED, BORDER = (colors.HexColor("#1c5a8f"), colors.HexColor("#6b7a99"),
                           colors.HexColor("#dde4ef"))
    base = getSampleStyleSheet()["Normal"]

    def sty(nombre, **kw):
        kw.setdefault("fontName", "Helvetica")
        kw.setdefault("fontSize", 9)
        kw.setdefault("leading", kw["fontSize"] + 3)
        return ParagraphStyle(nombre, parent=base, **kw)

    def txt(v) -> str:
        s = "" if v is None else str(v).strip()
        return "" if s.lower() in ("none", "null") else escape(s)

    def pesos(v) -> str:
        return "$ " + _pesos(v)

    def fecha(v) -> str:
        return v.strftime("%d/%m/%Y") if hasattr(v, "strftime") else "—"

    def cuil(v) -> str:
        d = "".join(c for c in txt(v) if c.isdigit())
        return f"{d[:2]}-{d[2:10]}-{d[10]}" if len(d) == 11 else txt(v)

    # El membrete, de «Datos del sindicato».
    datos_inst = institucion.obtener()
    inst = {"nombre": datos_inst.get("nombre") or "", "sigla": datos_inst.get("sigla") or "",
            "cuit": datos_inst.get("cuit") or "", "domicilio": institucion.domicilio_completo(datos_inst)}
    logo = institucion.ruta_logo(datos_inst)
    borrador = r.get("estado") == "borrador"
    auditada = any(d.get("importe_aprobado") is not None for d in r["detalle"])
    numero = txt(r.get("nro_solicitud")) or "sin número"
    story = []

    # ── Membrete ──
    linea2 = "  —  ".join(x for x in ((f"CUIT: {cuil(inst['cuit'])}" if inst["cuit"] else ""),
                                      escape(inst["domicilio"])) if x)
    nombre_inst = escape(inst["nombre"]) + (f" ({escape(inst['sigla'])})" if inst["sigla"] else "")
    marca = Paragraph(f"<b>{nombre_inst}</b>",
                      sty("os", fontSize=11, textColor=NAVY, fontName="Helvetica-Bold"))
    # El logo, si es una imagen que reportlab sabe dibujar (no SVG).
    if logo and logo.suffix.lower() in (".png", ".jpg", ".jpeg"):
        try:
            img = Image(str(logo))
            escala = min(1.4 * cm / img.imageHeight, 3.5 * cm / img.imageWidth)
            img.drawHeight, img.drawWidth = img.imageHeight * escala, img.imageWidth * escala
            marca = Table([[img, marca]], colWidths=[img.drawWidth + 0.3 * cm, None])
            marca.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                       ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        except Exception:
            pass        # un logo dañado no impide imprimir la constancia
    enc = Table([[
        marca,
        Paragraph("<b>Constancia de solicitud<br/>de reintegro</b><br/>"
                  + (f"<font size=9>{numero}</font>" if not borrador
                     else "<font size=9 color='#b42318'>BORRADOR</font>"),
                  sty("tit", fontSize=12, textColor=NAVY, fontName="Helvetica-Bold",
                      alignment=TA_RIGHT)),
    ]], colWidths=["58%", "42%"])
    enc.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story.append(enc)
    if linea2:
        story.append(Paragraph(linea2, sty("os2", fontSize=8, textColor=MUTED, spaceAfter=4)))
    story.append(HRFlowable(width="100%", thickness=2, color=NAVY, spaceAfter=8))

    def bloque(titulo, filas):
        filas = [(k, v) for k, v in filas if v not in (None, "", "—")]
        if not filas:
            return
        story.append(Paragraph(titulo, sty("h", fontSize=8, textColor=MUTED,
                                           fontName="Helvetica-Bold", spaceAfter=3)))
        t = Table([[Paragraph(f"<font color='#6b7a99'>{k}</font>", sty("k")),
                    Paragraph(f"<b>{v}</b>", sty("v"))] for k, v in filas],
                  colWidths=["28%", "72%"])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("TOPPADDING", (0, 0), (-1, -1), 1),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                               ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        story.append(t)
        story.append(Spacer(1, 8))

    bloque("AFILIADO TITULAR", [("Apellido y nombre", txt(r.get("titular"))),
                                ("CUIL", cuil(r.get("cuil_titular"))),
                                ("Documento", txt(r.get("doc_titular")))])
    bloque("PRESENTACIÓN", [
        ("Fecha de solicitud", fecha(r.get("fecha_solicitud"))),
        ("Estado", svc.estado_label(r.get("estado"))),
        ("Recibida por", txt(r.get("usuario_solicitud"))),
        ("Comprobantes adjuntos", str(sum(len(d.get("adjuntos") or []) for d in r["detalle"]))),
    ])
    bloque("DESTINO DEL PAGO", [("CBU", txt(r.get("cbu_destino"))),
                                ("Alias", txt(r.get("alias_destino")))])

    # ── Detalle ──
    cabeza = ["Fecha", "Beneficiario", "Concepto", "Comprobante", "Adj.", "Solicitado"]
    anchos = [2.0, 4.6, 3.7, 2.9, 1.0, 2.6]
    if auditada:
        cabeza.append("Reconocido")
        anchos.append(2.6)
    filas = [[Paragraph(f"<b>{c}</b>", sty("th", fontSize=8, textColor=colors.white,
                                           alignment=(TA_RIGHT if c in ("Solicitado", "Reconocido")
                                                      else TA_LEFT)))
              for c in cabeza]]
    for d in r["detalle"]:
        par = txt(d.get("parentesco"))
        fila = [
            Paragraph(fecha(d.get("fecha_gasto")), sty("c", fontSize=8)),
            Paragraph(txt(d.get("afiliado")) + (f"<br/><font size=7 color='#6b7a99'>{par}</font>"
                                                 if par else ""), sty("c", fontSize=8)),
            Paragraph(txt(d.get("concepto")), sty("c", fontSize=8)),
            Paragraph(txt(d.get("nro_comprobante")) or "—", sty("c", fontSize=8)),
            Paragraph(str(len(d.get("adjuntos") or [])), sty("c", fontSize=8, alignment=TA_CENTER)),
            Paragraph(pesos(d.get("importe_solicitado")), sty("c", fontSize=8, alignment=TA_RIGHT)),
        ]
        if auditada:
            fila.append(Paragraph(pesos(d["importe_aprobado"]) if d.get("importe_aprobado") is not None
                                  else "—", sty("c", fontSize=8, alignment=TA_RIGHT)))
        filas.append(fila)
    total = [Paragraph("<b>Total</b>", sty("t", fontSize=9)), "", "", "", "",
             Paragraph(f"<b>{pesos(r.get('importe_solicitado'))}</b>",
                       sty("t", fontSize=9, alignment=TA_RIGHT))]
    if auditada:
        total.append(Paragraph(f"<b>{pesos(r.get('importe_aprobado'))}</b>",
                               sty("t", fontSize=9, alignment=TA_RIGHT)))
    filas.append(total)
    t = Table(filas, colWidths=[a * cm for a in anchos], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#fafbfd")]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eaf4fc")),
        ("SPAN", (0, -1), (4, -1)),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    resuelto = []
    if r.get("fecha_auditoria"):
        resuelto += [("Auditada el", fecha(r.get("fecha_auditoria"))),
                     ("Auditó", txt(r.get("usuario_auditoria")))]
    for o in r.get("ordenes") or []:
        resuelto.append(("Orden de pago", f"{txt(o['nro_orden'])} del {fecha(o['fecha'])} "
                                          f"por {pesos(o['importe'])}"))
    if txt(r.get("motivo_rechazo")):
        resuelto.append(("Motivo del rechazo", txt(r.get("motivo_rechazo"))))
    bloque("RESOLUCIÓN", resuelto)

    if txt(r.get("observaciones")):
        story.append(Paragraph("OBSERVACIONES", sty("h", fontSize=8, textColor=MUTED,
                                                    fontName="Helvetica-Bold", spaceAfter=3)))
        story.append(Paragraph(txt(r.get("observaciones")), sty("obs", spaceAfter=8)))

    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=6))
    aclaracion = ("Esta constancia acredita la presentación de la solicitud y no implica su "
                  "aprobación. El reintegro queda sujeto a la auditoría de la documentación "
                  "presentada.")
    if borrador:
        aclaracion = ("BORRADOR: la solicitud todavía no fue presentada y puede cambiar. "
                      "Esta hoja no sirve como constancia.")
    story.append(Paragraph(aclaracion, sty("pie", fontSize=7.5, textColor=MUTED)))
    story.append(Paragraph(
        f"Emitida el {datetime.datetime.now():%d/%m/%Y a las %H:%M} por "
        f"{escape(session.get('sind_usuario_nombre') or '')}.",
        sty("pie2", fontSize=7.5, textColor=MUTED, spaceBefore=2)))

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                      topMargin=1.8 * cm, bottomMargin=1.8 * cm,
                      title=f"Solicitud de reintegro {numero}").build(story)
    buf.seek(0)
    return buf


# =============================================================================
# 4. Auditoría
# =============================================================================

def _importes_del_form(form, prefijo: str) -> dict:
    """Los campos <prefijo>_<id_detalle> como {id_detalle: valor}."""
    salida = {}
    for clave, valor in form.items():
        if clave.startswith(prefijo + "_"):
            sufijo = clave[len(prefijo) + 1:]
            if sufijo.isdigit():
                salida[int(sufijo)] = valor
    return salida


@reintegros_bp.route("/auditoria")
def auditoria():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede_auditar():
        return _sin_permiso("No tenés permiso para la auditoría de reintegros.")
    return render_template("reintegros/auditoria.html",
                           reintegros=svc.listar("en_auditoria"), clases=svc.CLASES)


@reintegros_bp.route("/auditoria/<int:id_reintegro>")
def auditoria_ficha(id_reintegro):
    if not validasesion():
        return redirect(url_for("login"))
    if not puede_auditar():
        return _sin_permiso("No tenés permiso para la auditoría de reintegros.")
    r = svc.obtener(id_reintegro)
    if not r:
        flash("!La solicitud no existe.")
        return redirect(url_for("reintegros.auditoria"))
    if r["estado"] != "en_auditoria":
        # A la ficha de consulta, no a la bandeja: el que llegó hasta acá
        # quería ver esta solicitud.
        flash(f"!La solicitud está «{svc.estado_label(r['estado'])}»: no hay nada que auditar.")
        return redirect(url_for("reintegros.ficha", id_reintegro=id_reintegro))
    return _ficha(r, "auditar")


@reintegros_bp.route("/auditoria/<int:id_reintegro>/resolver", methods=["POST"])
def auditoria_resolver(id_reintegro):
    if not validasesion():
        return redirect(url_for("login"))
    if not puede_auditar():
        return _sin_permiso("No tenés permiso para la auditoría de reintegros.")
    try:
        if request.form.get("accion") == "rechazar":
            svc.rechazar(id_reintegro, _usuario_id(), request.form.get("motivo"))
            flash("Solicitud rechazada.")
            return redirect(url_for("reintegros.auditoria"))
        total = svc.auditar(
            id_reintegro, _usuario_id(),
            importes      = _importes_del_form(request.form, "aprobado"),
            comentarios   = _importes_del_form(request.form, "comentario"),
            observaciones = (request.form.get("observaciones") or "").strip() or None,
        )
        flash(f"Auditoría cerrada: $ {_pesos(total)} autorizados. La solicitud queda "
              "aprobada y lista para la orden de pago.")
        return redirect(url_for("reintegros.auditoria"))
    except ReintegroError as e:
        flash(f"!{e}")
    return redirect(url_for("reintegros.auditoria_ficha", id_reintegro=id_reintegro))


# =============================================================================
# 5. Órdenes de pago
# =============================================================================

@reintegros_bp.route("/ordenes")
def ordenes():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede_ordenes():
        return _sin_permiso("No tenés permiso para las órdenes de pago de reintegros.")
    return render_template("reintegros/ordenes.html",
                           solapa       = "ordenes" if request.args.get("solapa") == "ordenes"
                                          else "pendientes",
                           reintegros   = svc.listar_con_saldo(),
                           clases       = svc.CLASES,
                           ordenes      = svc.listar_ordenes(),
                           estados_orden = svc.ESTADOS_ORDEN,
                           orden_label  = svc.ESTADOS_ORDEN_LABEL,
                           orden_tipo   = svc.ESTADOS_ORDEN_TIPO)


@reintegros_bp.route("/ordenes/generar", methods=["POST"])
def ordenes_generar():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede_ordenes():
        return _sin_permiso("No tenés permiso para las órdenes de pago de reintegros.")
    ids = request.form.getlist("seleccion", type=int)
    importes = {}
    for i in ids:
        crudo = (request.form.get(f"importe_{i}") or "").strip()
        if not crudo:
            continue
        try:
            importes[i] = svc._dec(crudo)
        except ReintegroError:
            flash(f"!El importe a pagar «{crudo}» no se entiende.")
            return redirect(url_for("reintegros.ordenes"))
    try:
        for g in svc.generar_ordenes_pago(ids, _usuario_id(), importes):
            flash(f"Orden {g['nro_orden']} — {g['titular']} · {g['reintegros']} "
                  f"reintegro{'s' if g['reintegros'] != 1 else ''} · $ {_pesos(g['importe'])}")
    except ReintegroError as e:
        flash(f"!{e}")
        return redirect(url_for("reintegros.ordenes"))
    # A las generadas: es lo que se quiere ver después de generar.
    return redirect(url_for("reintegros.ordenes", solapa="ordenes"))


# =============================================================================
# Adjuntos
# =============================================================================

@reintegros_bp.route("/adjunto/<int:id_adjunto>")
def ver_adjunto(id_adjunto):
    if not validasesion():
        return redirect(url_for("login"))
    if not puede_ver():
        return _sin_permiso("No tenés permiso para los reintegros.")
    a = svc.adjunto(id_adjunto)
    real = _ruta_real(a["ruta_archivo"]) if a else None
    if not real or not real.exists():
        flash("!El archivo no está en el servidor.")
        return redirect(request.referrer or url_for("reintegros.solicitud"))
    return send_file(real, download_name=a["nombre_archivo"])


@reintegros_bp.route("/adjunto/<int:id_adjunto>/eliminar", methods=["POST"])
def borrar_adjunto(id_adjunto):
    if not validasesion():
        return redirect(url_for("login"))
    if not (puede_cargar() or puede_auditar()):
        return _sin_permiso("No tenés permiso para la carga de reintegros.")
    volver = _volver_local(request.form.get("volver"), url_for("reintegros.solicitud"))
    try:
        ruta, _ = svc.eliminar_adjunto(id_adjunto)
        _borrar_archivo(ruta)
        flash("Comprobante eliminado.")
    except ReintegroError as e:
        flash(f"!{e}")
    return redirect(volver)


# =============================================================================
# API del formulario
# =============================================================================

@reintegros_bp.route("/api/titulares")
def api_titulares():
    if not validasesion() or not puede_cargar():
        return jsonify([])
    return jsonify(svc.buscar_titulares(request.args.get("q", "")))


@reintegros_bp.route("/api/grupo_familiar/<int:id_titular>")
def api_grupo_familiar(id_titular):
    if not validasesion() or not puede_cargar():
        return jsonify([])
    return jsonify(svc.grupo_familiar(id_titular))
