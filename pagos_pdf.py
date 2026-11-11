"""
pagos_pdf.py — PDF de la orden de pago y del certificado de retención.

Portado de `gestion_adm/pagos_routes.py` (pdf_orden, pdf_certificado) con el
membrete de «Datos del sindicato» (`s_institucion`) y los colores de la marca.
La orden lleva lo que se paga según la clase, los pagos con sus instrumentos y
las retenciones; el certificado imita el F.2005 / F.2004 de ARCA y se dice
provisorio hasta que se presente en SIRE.
"""

from __future__ import annotations

import io
from xml.sax.saxutils import escape

from flask import send_file

import institucion

TIPO_COMPROBANTE = {1: "Factura", 2: "Recibo", 3: "Nota de crédito", 4: "Nota de débito", 5: "Otro comprobante",
                    6: "Orden de pago"}
IMPUESTO = {"GANANCIAS": ("216", "Impuesto a las Ganancias", "2005"), "IVA": ("216", "Impuesto al Valor Agregado", "2005"),
            "SUSS": ("353", "Seguridad Social", "2004"), "IIBB": ("—", "Ingresos Brutos", "—")}
CLASES = {"proveedor": "Pago a proveedor", "anticipo": "Anticipo a proveedor", "concepto": "Pago por concepto",
          "reintegro": "Reintegro a afiliado", "sueldos": "Pago de sueldos"}
ESTADOS = {"borrador": "BORRADOR", "pendiente_aprobacion": "PENDIENTE DE APROBACIÓN", "aprobada": "APROBADA",
           "rechazada": "RECHAZADA", "pagada": "PAGADA", "anulada": "ANULADA"}


def respuesta(buf: io.BytesIO, nombre: str):
    buf.seek(0)
    return send_file(buf, mimetype="application/pdf", as_attachment=False, download_name=nombre.replace("/", "-"))


def _pesos(v) -> str:
    entero, _, dec = f"{float(v or 0):,.2f}".partition(".")
    return f"$ {entero.replace(',', '.')},{dec}"


def _txt(v) -> str:
    s = "" if v is None else str(v).strip()
    return "" if s.lower() in ("none", "null") else escape(s)


def _fecha(v) -> str:
    return v.strftime("%d/%m/%Y") if hasattr(v, "strftime") else "—"


def _cuit(v) -> str:
    d = "".join(c for c in _txt(v) if c.isdigit())
    return f"{d[:2]}-{d[2:10]}-{d[10]}" if len(d) == 11 else _txt(v)


class _Doc:
    """Estilos y membrete comunes."""

    def __init__(self, titulo: str, numero: str, aviso: str | None = None):
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        self.c = colors
        self.NAVY, self.MUTED, self.BORDER = (colors.HexColor("#1c5a8f"), colors.HexColor("#6b7a99"),
                                              colors.HexColor("#dde4ef"))
        self.GRAY, self.RED = colors.HexColor("#f2f5fa"), colors.HexColor("#b42318")
        self.base = getSampleStyleSheet()["Normal"]
        self.story = []
        self._membrete(titulo, numero, aviso)

    def sty(self, nombre, **kw):
        from reportlab.lib.styles import ParagraphStyle
        kw.setdefault("fontName", "Helvetica")
        kw.setdefault("fontSize", 9)
        kw.setdefault("leading", kw["fontSize"] + 3)
        return ParagraphStyle(nombre, parent=self.base, **kw)

    def P(self, texto, **kw):
        from reportlab.platypus import Paragraph
        return Paragraph(texto, self.sty("p", **kw))

    def _membrete(self, titulo, numero, aviso):
        from reportlab.lib.enums import TA_RIGHT
        from reportlab.lib.units import cm
        from reportlab.platypus import HRFlowable, Image, Table, TableStyle
        d = institucion.obtener()
        nombre = _txt(d.get("nombre")) + (f" ({_txt(d.get('sigla'))})" if d.get("sigla") else "")
        marca = self.P(f"<b>{nombre}</b>", fontSize=11, textColor=self.NAVY, fontName="Helvetica-Bold")
        logo = institucion.ruta_logo(d)
        if logo and logo.suffix.lower() in (".png", ".jpg", ".jpeg"):
            try:
                img = Image(str(logo))
                esc = min(1.4 * cm / img.imageHeight, 3.5 * cm / img.imageWidth)
                img.drawHeight, img.drawWidth = img.imageHeight * esc, img.imageWidth * esc
                marca = Table([[img, marca]], colWidths=[img.drawWidth + 0.3 * cm, None])
                marca.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                           ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
            except Exception:                            # noqa: BLE001 — un logo dañado no impide imprimir
                pass
        derecha = f"<b>{titulo}</b><br/><font size=10 face='Courier-Bold'>{_txt(numero)}</font>"
        if aviso:
            derecha += f"<br/><font size=8 color='#b42318'>{aviso}</font>"
        t = Table([[marca, self.P(derecha, fontSize=12, leading=15, textColor=self.NAVY, fontName="Helvetica-Bold",
                                  alignment=TA_RIGHT)]], colWidths=["58%", "42%"])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        self.story.append(t)
        linea = "  —  ".join(x for x in ((f"CUIT: {_cuit(d.get('cuit'))}" if d.get("cuit") else ""),
                                         escape(institucion.domicilio_completo(d))) if x)
        if linea:
            self.story.append(self.P(linea, fontSize=8, textColor=self.MUTED, spaceAfter=4))
        self.story.append(HRFlowable(width="100%", thickness=2, color=self.NAVY, spaceAfter=8))

    def datos(self, titulo, filas):
        from reportlab.platypus import Spacer, Table, TableStyle
        filas = [(k, v) for k, v in filas if v not in (None, "", "—")]
        if not filas:
            return
        self.story.append(self.P(titulo, fontSize=8, textColor=self.MUTED, fontName="Helvetica-Bold", spaceAfter=3))
        t = Table([[self.P(f"<font color='#6b7a99'>{k}</font>"), self.P(f"<b>{v}</b>")] for k, v in filas],
                  colWidths=["28%", "72%"])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 1),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 1), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        self.story.append(t)
        self.story.append(Spacer(1, 8))

    def tabla(self, titulo, cabeza, filas, anchos, derecha=(), total=None):
        """Una grilla con cabecera navy; `derecha`: índices de columnas
        numéricas; `total`: (texto, importe) al pie."""
        from reportlab.lib.enums import TA_RIGHT
        from reportlab.lib.units import cm
        from reportlab.platypus import Spacer, Table, TableStyle
        if not filas:
            return
        self.story.append(self.P(titulo, fontSize=8, textColor=self.MUTED, fontName="Helvetica-Bold", spaceAfter=3))
        st_c = self.sty("c", fontSize=7.5, leading=9.5, textColor=self.c.white, fontName="Helvetica-Bold")
        st_cr = self.sty("cr", fontSize=7.5, leading=9.5, textColor=self.c.white, fontName="Helvetica-Bold",
                         alignment=TA_RIGHT)
        st_d, st_dr = self.sty("d", fontSize=8, leading=10), self.sty("dr", fontSize=8, leading=10, alignment=TA_RIGHT)
        from reportlab.platypus import Paragraph
        data = [[Paragraph(h, st_cr if i in derecha else st_c) for i, h in enumerate(cabeza)]]
        for f in filas:
            data.append([Paragraph(str(v), st_dr if i in derecha else st_d) for i, v in enumerate(f)])
        if total:
            fila = [""] * len(cabeza)
            fila[-2], fila[-1] = Paragraph(f"<b>{total[0]}</b>", st_dr), Paragraph(f"<b>{total[1]}</b>", st_dr)
            data.append(fila)
        t = Table(data, colWidths=[a * cm for a in anchos], repeatRows=1)
        estilo = [("BACKGROUND", (0, 0), (-1, 0), self.NAVY), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                  ("LINEBELOW", (0, 1), (-1, -1), 0.4, self.BORDER), ("TOPPADDING", (0, 0), (-1, -1), 3),
                  ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        if total:
            estilo += [("LINEABOVE", (0, -1), (-1, -1), 1, self.NAVY), ("BACKGROUND", (0, -1), (-1, -1), self.GRAY)]
        t.setStyle(TableStyle(estilo))
        self.story.append(t)
        self.story.append(Spacer(1, 10))

    def pdf(self, titulo: str) -> io.BytesIO:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate

        def pie(canvas, doc):
            canvas.saveState()
            canvas.setFont("Helvetica", 7)
            canvas.setFillColor(self.MUTED)
            canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"{titulo} · página {doc.page}")
            canvas.restoreState()

        buf = io.BytesIO()
        SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm,
                          bottomMargin=1.8 * cm, title=titulo).build(self.story, onFirstPage=pie, onLaterPages=pie)
        return buf


# ─────────────────────────────────────────────────────────────────────────────
# Orden de pago
# ─────────────────────────────────────────────────────────────────────────────

def orden(o: dict) -> io.BytesIO:
    from reportlab.lib.units import cm
    from reportlab.platypus import Spacer, Table, TableStyle
    aviso = None if o["estado"] == "pagada" else ESTADOS.get(o["estado"], o["estado"])
    doc = _Doc("Orden de pago", o["nro_vis"], aviso)
    benef = o.get("emisor_unico") or {}
    cuentas = o.get("beneficiarios") or []
    cbu = (_txt(cuentas[0]["cbu"] or cuentas[0]["alias"])) if len(cuentas) == 1 else ""
    doc.datos("ORDEN", [("Fecha", _fecha(o.get("fecha"))), ("Clase", CLASES.get(o["clase"], o["clase"])),
                        ("Beneficiario", _txt(benef.get("razon_social"))),
                        ("CUIT", _cuit(benef.get("cuit"))), ("Importe", _pesos(o.get("importe_total"))),
                        ("Observaciones", _txt(o.get("observaciones"))), ("CBU", cbu)])
    if o["detalle"]:
        doc.tabla("COMPROBANTES QUE SE PAGAN",
                  ["Comprobante", "Número", "Fecha", "Expediente", "Importe", "Se paga"],
                  [[_txt(d.get("tipo_desc")) or "—", _txt(d.get("numero_completo")), _fecha(d.get("fecha_emision")),
                    _txt(d.get("nro_expediente")), _pesos(d.get("comp_importe")), _pesos(d.get("importe"))]
                   for d in o["detalle"]],
                  [3.6, 3.0, 2.0, 2.6, 2.4, 2.4], derecha=(4, 5), total=("Total", _pesos(o.get("importe_total"))))
    if o["detalle_anticipo"]:
        doc.tabla("ANTICIPO", ["Proveedor", "CUIT", "Cuenta", "Descripción", "Importe"],
                  [[_txt(a.get("razon_social")), _cuit(a.get("cuit")), _txt(a.get("rubro")), _txt(a.get("descripcion")),
                    _pesos(a.get("importe"))] for a in o["detalle_anticipo"]],
                  [4.4, 2.6, 3.0, 3.6, 2.4], derecha=(4,), total=("Total", _pesos(o.get("importe_total"))))
    if o["detalle_concepto"]:
        doc.tabla("CONCEPTOS", ["Concepto / motivo", "Descripción", "Período", "Importe"],
                  [[_txt(c.get("nombre_concepto") or c.get("nombre_motivo")), _txt(c.get("descripcion")),
                    (c["periodo"][4:] + "/" + c["periodo"][:4]) if c.get("periodo") and len(c["periodo"]) == 6 else "",
                    _pesos(c.get("importe"))] for c in o["detalle_concepto"]],
                  [4.6, 6.4, 2.0, 3.0], derecha=(3,), total=("Total", _pesos(o.get("importe_total"))))
    if o["detalle_reintegro"]:
        doc.tabla("REINTEGROS", ["Solicitud", "Titular", "CUIL", "CBU / alias", "Importe"],
                  [[_txt(r.get("nro_solicitud")), _txt(r.get("nombre")), _cuit(r.get("cuil")),
                    _txt(r.get("cbu_destino") or r.get("alias_destino")), _pesos(r.get("importe"))]
                   for r in o["detalle_reintegro"]],
                  [2.8, 4.6, 2.6, 4.0, 2.4], derecha=(4,), total=("Total", _pesos(o.get("importe_total"))))

    vivos = [p for p in o["pagos"] if p["estado"] != "anulado"]
    instrumentos = [(p, i) for p in vivos for i in p["instrumentos"]]
    if instrumentos:
        nombres = {"cheque": "Cheque", "transferencia": "Transferencia", "efectivo": "Efectivo"}
        doc.tabla("PAGO", ["Pago", "Fecha", "Instrumento", "Cuenta", "Importe"],
                  [[_txt(p.get("nro_origen") or p.get("nro_pago")), _fecha(p.get("fecha_pago")),
                    nombres.get(i["tipo_instrumento"], _txt(i["tipo_instrumento"]))
                    + (f" N° {_txt(i['nro_cheque'])}" if i.get("nro_cheque") else "")
                    + (f" vence {_fecha(i['fecha_cheque'])}" if i.get("fecha_cheque") else "")
                    + (f" → {_txt(i['cbu_destino'])}" if i.get("cbu_destino") else ""),
                    _txt(i.get("cuenta")) + (f" ({_txt(i['banco'])})" if i.get("banco") else ""), _pesos(i.get("importe"))]
                   for p, i in instrumentos],
                  [2.6, 2.0, 5.4, 3.6, 2.4], derecha=(4,))
    elif vivos:
        doc.datos("PAGO", [("Pago", _txt(vivos[0].get("nro_origen") or vivos[0].get("nro_pago"))),
                           ("Fecha", _fecha(vivos[0].get("fecha_pago")))])
    rets = [r for r in o["retenciones"] if not r.get("anulado")]
    if rets:
        doc.tabla("RETENCIONES PRACTICADAS", ["Impuesto", "Régimen", "Certificado", "Base", "Alícuota", "Importe"],
                  [[_txt(r["tipo"]), _txt(r["regimen"]), _txt(r.get("nro_certificado")), _pesos(r["base_calculo"]),
                    f"{float(r['alicuota']):.2f} %".replace(".", ","), _pesos(r["importe"])] for r in rets],
                  [2.6, 1.8, 3.6, 3.0, 2.0, 2.8], derecha=(3, 4, 5))
        retenido = sum(float(r["importe"]) for r in rets)
        t = Table([[doc.P("Importe de la orden"), doc.P(f"<b>{_pesos(o['importe_total'])}</b>")],
                   [doc.P("Retenciones"), doc.P(f"<b>− {_pesos(retenido)}</b>")],
                   [doc.P("<b>Neto pagado</b>"), doc.P(f"<b>{_pesos(float(o['importe_total']) - retenido)}</b>")]],
                  colWidths=[12 * cm, 4 * cm])
        t.setStyle(TableStyle([("ALIGN", (1, 0), (1, -1), "RIGHT"), ("LINEABOVE", (0, -1), (-1, -1), 1, doc.NAVY)]))
        doc.story.append(t)
    # Firmas
    doc.story.append(Spacer(1, 1.6 * cm))
    f = Table([["", "", ""], [doc.P("Confeccionó", alignment=1), doc.P("Autorizó", alignment=1),
                              doc.P("Recibí conforme", alignment=1)]], colWidths=[5.3 * cm] * 3, rowHeights=[1.2 * cm, None])
    f.setStyle(TableStyle([("LINEABOVE", (0, 1), (0, 1), 0.6, doc.MUTED), ("LINEABOVE", (1, 1), (1, 1), 0.6, doc.MUTED),
                           ("LINEABOVE", (2, 1), (2, 1), 0.6, doc.MUTED), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 10)]))
    doc.story.append(f)
    return doc.pdf(f"Orden de pago {o['nro_vis']}")


# ─────────────────────────────────────────────────────────────────────────────
# Certificado de retención
# ─────────────────────────────────────────────────────────────────────────────

def certificado(c: dict) -> io.BytesIO:
    from reportlab.lib.units import cm
    from reportlab.platypus import Spacer, Table, TableStyle
    num, nombre_imp, formulario = IMPUESTO.get(c["tipo"], ("—", c["tipo"], "—"))
    aviso = "ANULADO" if c.get("estado") == "anulado" else None
    doc = _Doc(f"Certificado de retención · F.{formulario}", c["nro_certificado"], aviso)
    inst = institucion.obtener()
    doc.datos("AGENTE DE RETENCIÓN", [("Razón social", _txt(inst.get("nombre"))), ("CUIT", _cuit(inst.get("cuit"))),
                                      ("Domicilio", escape(institucion.domicilio_completo(inst))),
                                      ("Resolución", _txt(inst.get("nro_resolucion_ret")))])
    p = c.get("proveedor") or {}
    doc.datos("SUJETO RETENIDO", [("Razón social", _txt(c.get("razon_social_proveedor"))),
                                  ("CUIT", _cuit(c.get("cuit_proveedor"))),
                                  ("Condición frente al IVA", _txt(c.get("condicion_fiscal") or p.get("condicion_txt"))),
                                  ("Domicilio", _txt(p.get("domicilio")))])
    per = c.get("periodo_fiscal") or ""
    doc.datos("RETENCIÓN", [("Impuesto", f"{num} — {nombre_imp}"), ("Régimen", _txt(c.get("codigo_regimen"))),
                            ("Fecha", _fecha(c.get("fecha_emision"))),
                            ("Período fiscal", f"{per[4:]}/{per[:4]}" if len(per) == 6 else "—"),
                            ("Base de cálculo", _pesos(c.get("base_calculo"))),
                            ("Alícuota", f"{float(c.get('alicuota') or 0):.2f} %".replace(".", ",")),
                            ("Exclusión", "Con certificado de exclusión" if c.get("tiene_exclusion") else "")])
    nro_comp = ((f"{_txt(c['comprobante_pv'])}-" if c.get("comprobante_pv") else "") + _txt(c.get("comprobante_nro")))
    doc.datos("COMPROBANTE QUE ORIGINA LA RETENCIÓN",
              [("Tipo", TIPO_COMPROBANTE.get(c.get("comprobante_tipo"), "—")), ("Número", nro_comp),
               ("Fecha", _fecha(c.get("comprobante_fecha"))),
               ("Importe", _pesos(c.get("comprobante_importe")) if c.get("comprobante_importe") else ""),
               ("Orden de pago", _txt(c.get("nro_orden"))), ("Pago", _txt(c.get("nro_pago")))])
    t = Table([[doc.P("IMPORTE RETENIDO", fontSize=8, textColor=doc.MUTED, fontName="Helvetica-Bold", alignment=1)],
               [doc.P(f"<b>{_pesos(c.get('importe_retenido'))}</b>", fontSize=18, leading=22, textColor=doc.NAVY,
                      alignment=1)]], colWidths=[16 * cm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), doc.GRAY), ("BOX", (0, 0), (-1, -1), 1, doc.NAVY),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    doc.story.append(t)
    doc.story.append(Spacer(1, 1.6 * cm))
    f = Table([["", ""], [doc.P("Firma y sello del agente de retención", alignment=1), doc.P("Recibí conforme", alignment=1)]],
              colWidths=[8 * cm] * 2, rowHeights=[1.2 * cm, None])
    f.setStyle(TableStyle([("LINEABOVE", (0, 1), (0, 1), 0.6, doc.MUTED), ("LINEABOVE", (1, 1), (1, 1), 0.6, doc.MUTED),
                           ("LEFTPADDING", (0, 0), (-1, -1), 16), ("RIGHTPADDING", (0, 0), (-1, -1), 16)]))
    doc.story.append(f)
    doc.story.append(Spacer(1, 0.6 * cm))
    doc.story.append(doc.P("Certificado emitido por el sistema del agente de retención. La retención se informa a ARCA "
                           "en la declaración jurada del período (SIRE / SICORE).", fontSize=7, textColor=doc.MUTED))
    return doc.pdf(f"Certificado {c['nro_certificado']}")
