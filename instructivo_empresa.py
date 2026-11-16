"""
instructivo_empresa.py — El instructivo en PDF del enlace de las empresas.

La empresa lo abre desde su enlace (botón «Instructivo»,
/empresas/<token>/instructivo.pdf) y el mail del enlace trae la dirección. El
sindicato lo ve desde la solapa Cuota sindical del empleador, la bandeja de
Presentaciones LSD y Datos del sindicato (/fiscalizacion/lsd/instructivo.pdf),
para mirarlo o adjuntarlo a mano.

El texto está en docs/instructivo_empresa.md, en Markdown simple —títulos
#/##, párrafos, listas con «- » y «1. », tablas con «|», **negrita** y
`código`— para corregirlo sin tocar código. Es el mismo texto del documento
«Instructivo para el empleador». Lo que depende de Datos del sindicato se
completa al armar el PDF, así que sale siempre con los datos del día:

  {sigla}       la sigla (o el nombre) del sindicato
  {alicuota}    la alícuota de la cuota sindical, «2,50 %»
  [[pago]]      la cuenta donde se paga la cuota (institucion.pago_cuota)
  [[contacto]]  el correo, el teléfono y el domicilio para consultas

Sin cuenta configurada, el instructivo dice que pidan los datos al sindicato:
nunca muestra un «pendiente» a la empresa.
"""

from __future__ import annotations

import datetime
import io
import re
from pathlib import Path
from xml.sax.saxutils import escape

import institucion
import pagos_pdf

TEXTO = Path(__file__).with_name("docs") / "instructivo_empresa.md"
TITULO = "Instructivo de la cuota sindical"
RE_OL = re.compile(r"^\d+\.\s+")
RE_MARCA = re.compile(r"^\[\[(\w+)\]\]$")
RE_SEPARADOR = re.compile(r"^:?-{3,}:?$")


# ─────────────────────────────────────────────────────────────────────────────
# El Markdown
# ─────────────────────────────────────────────────────────────────────────────

def leer_bloques(md: str) -> list[tuple]:
    """El Markdown en bloques: ("h1"|"h2"|"p", texto), ("ul"|"ol", [ítems]),
    ("tabla", [filas]) con la cabecera primero, ("marca", nombre)."""
    bloques, parrafo = [], []
    lineas = [l.strip() for l in md.splitlines()]

    def cerrar():
        if parrafo:
            bloques.append(("p", " ".join(parrafo)))
            parrafo.clear()

    i = 0
    while i < len(lineas):
        s = lineas[i]
        if not s:
            cerrar()
        elif s.startswith("# "):
            cerrar()
            bloques.append(("h1", s[2:].strip()))
        elif s.startswith("## "):
            cerrar()
            bloques.append(("h2", s[3:].strip()))
        elif RE_MARCA.match(s):
            cerrar()
            bloques.append(("marca", RE_MARCA.match(s).group(1)))
        elif s.startswith("- ") or RE_OL.match(s) or s.startswith("|"):
            cerrar()
            tipo = "ul" if s.startswith("- ") else "ol" if RE_OL.match(s) else "tabla"
            items = []
            while i < len(lineas) and lineas[i] and _mismo_tipo(lineas[i], tipo):
                t = lineas[i]
                if tipo == "ul":
                    items.append(t[2:].strip())
                elif tipo == "ol":
                    items.append(RE_OL.sub("", t, count=1).strip())
                else:
                    celdas = [c.strip() for c in t.strip().strip("|").split("|")]
                    if not all(RE_SEPARADOR.match(c) for c in celdas):
                        items.append(celdas)
                i += 1
            bloques.append((tipo, items))
            continue
        else:
            parrafo.append(s)
        i += 1
    cerrar()
    return bloques


def _mismo_tipo(linea: str, tipo: str) -> bool:
    return {"ul": linea.startswith("- "), "ol": bool(RE_OL.match(linea)), "tabla": linea.startswith("|")}[tipo]


def en_linea(texto: str) -> str:
    """El texto de un bloque, como lo lee Paragraph: escapado, con **negrita** y `código`."""
    t = escape(texto)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return re.sub(r"`(.+?)`", r"<font face='Courier'>\1</font>", t)


def reemplazos(md: str, datos: dict) -> str:
    sigla = datos.get("sigla") or datos.get("nombre") or "el sindicato"
    alic = datos.get("cuota_alicuota")
    if alic is None:
        md = md.replace(" (hoy {alicuota})", "")
    else:
        md = md.replace("{alicuota}", f"{float(alic):.2f}".replace(".", ",") + " %")
    return md.replace("{sigla}", sigla)


# ─────────────────────────────────────────────────────────────────────────────
# El PDF
# ─────────────────────────────────────────────────────────────────────────────

def nombre_archivo(datos: dict) -> str:
    sigla = re.sub(r"[^\w -]", "", datos.get("sigla") or "").strip()
    return f"Instructivo cuota sindical{' ' + sigla if sigla else ''}.pdf"


def armar(datos: dict, pago: dict, empresa: dict | None = None, texto: str | None = None) -> io.BytesIO:
    """El PDF. `datos`: los de Datos del sindicato; `pago`: institucion.pago_cuota;
    `empresa`: {razon_social, cuit} cuando se arma para una empresa."""
    from reportlab.lib.units import cm
    from reportlab.platypus import KeepTogether, ListFlowable, ListItem, Spacer

    cuit_emp = pagos_pdf._cuit((empresa or {}).get("cuit")) if empresa else ""
    doc = pagos_pdf._Doc(TITULO, f"CUIT {cuit_emp}" if cuit_emp else "")
    md = reemplazos(texto if texto is not None else TEXTO.read_text(encoding="utf-8"), datos)
    st_p = dict(fontSize=9.5, leading=13.5, spaceAfter=5)

    for tipo, valor in leer_bloques(md):
        if tipo == "h1":
            doc.story.append(doc.P(en_linea(valor), fontSize=15, leading=19, textColor=doc.NAVY,
                                   fontName="Helvetica-Bold", spaceAfter=3))
            pie = f"Actualizado al {datetime.date.today().strftime('%d/%m/%Y')}"
            if empresa and empresa.get("razon_social"):
                pie = f"Para {escape(empresa['razon_social'])} · " + pie
            doc.story.append(doc.P(pie, fontSize=8.5, textColor=doc.MUTED, spaceAfter=8))
        elif tipo == "h2":
            doc.story.append(doc.P(en_linea(valor), fontSize=11.5, leading=15, textColor=doc.NAVY,
                                   fontName="Helvetica-Bold", spaceBefore=9, spaceAfter=4, keepWithNext=1))
        elif tipo == "p":
            doc.story.append(doc.P(en_linea(valor), **st_p))
        elif tipo in ("ul", "ol"):
            items = [ListItem(doc.P(en_linea(t), fontSize=9.5, leading=13.5), leftIndent=16) for t in valor]
            opciones = dict(bulletType="1", bulletFormat="%s.", bulletFontName="Helvetica-Bold",
                            bulletColor=doc.NAVY) if tipo == "ol" else dict(bulletType="bullet", start="•",
                                                                             bulletColor=doc.NAVY)
            doc.story.append(ListFlowable(items, leftIndent=16, bulletFontSize=9, spaceAfter=0, **opciones))
            doc.story.append(Spacer(1, 6))
        elif tipo == "tabla":
            doc.story.append(_tabla(doc, valor, cm))
        elif tipo == "marca" and valor == "pago":
            doc.story.append(KeepTogether(_pago(doc, pago, cm)))
        elif tipo == "marca" and valor == "contacto":
            doc.story.append(KeepTogether(_contacto(doc, pago, cm)))
    return doc.pdf(TITULO)


def _tabla(doc, filas: list[list[str]], cm):
    from reportlab.platypus import Table, TableStyle
    n = max(len(f) for f in filas)
    anchos = {2: [4.6, 12.4], 3: [3.0, 7.0, 7.0]}.get(n, [17.0 / n] * n)
    st_c = doc.sty("tc", fontSize=8.5, leading=11, textColor=doc.c.white, fontName="Helvetica-Bold")
    st_d = doc.sty("td", fontSize=8.8, leading=11.5)
    from reportlab.platypus import Paragraph
    data = [[Paragraph(en_linea(c), st_c if i == 0 else st_d) for c in (f + [""] * (n - len(f)))]
            for i, f in enumerate(filas)]
    t = Table(data, colWidths=[a * cm for a in anchos], repeatRows=1, spaceAfter=8)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), doc.NAVY), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LINEBELOW", (0, 1), (-1, -1), 0.4, doc.BORDER),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return t


def _recuadro(doc, filas: list[tuple[str, str]], cm):
    """Rótulo y dato en un recuadro gris con la franja navy: lo que hay que copiar."""
    from reportlab.platypus import Table, TableStyle
    data = [[doc.P(f"<font color='#6b7a99'>{k}</font>", fontSize=9.5, leading=13),
             doc.P(v, fontSize=10, leading=13.5, fontName="Helvetica-Bold", textColor=doc.NAVY)] for k, v in filas]
    t = Table(data, colWidths=[4.0 * cm, 13.0 * cm], spaceAfter=8)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), doc.GRAY), ("LINEBEFORE", (0, 0), (0, -1), 3, doc.NAVY),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (0, -1), 10),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


def _mono(v: str) -> str:
    return f"<font face='Courier-Bold'>{escape(v)}</font>"


def filas_cuenta(pago: dict) -> list[tuple[str, str]]:
    """Los datos de la cuenta, en el orden en que se copian para transferir.
    Vacía si no hay cuenta configurada."""
    c = pago.get("cuenta")
    if not c:
        return []
    filas = [("Titular", escape(pago.get("titular") or "")),
             ("CUIT", pagos_pdf._cuit(pago.get("cuit")) if pago.get("cuit") else ""),
             ("Banco", escape(c.get("banco") or "")),
             ("Cuenta N°", _mono(c["numero"]) if c.get("numero") else ""),
             ("CBU", _mono(c["cbu"]) if c.get("cbu") else ""),
             ("Alias", _mono(c["alias"]) if c.get("alias") else "")]
    return [(k, v) for k, v in filas if v]


def _pago(doc, pago: dict, cm) -> list:
    filas = filas_cuenta(pago)
    if not filas:
        return [doc.P("Pidan al sindicato los datos de la cuenta para pagar la cuota (ver «Contacto»).",
                      fontSize=9.5, leading=13.5, spaceAfter=5)]
    salida = [_recuadro(doc, filas, cm)]
    for linea in (pago.get("indicaciones") or "").splitlines():
        if linea.strip():
            salida.append(doc.P(escape(linea.strip()), fontSize=9.5, leading=13.5, spaceAfter=4))
    return salida


def filas_contacto(pago: dict) -> list[tuple[str, str]]:
    filas = [("Correo", escape(pago.get("email") or "")), ("Teléfono", escape(pago.get("telefono") or "")),
             ("Domicilio", escape(pago.get("domicilio") or "")), ("Sitio web", escape(pago.get("web") or ""))]
    return [(k, v) for k, v in filas if v]


def _contacto(doc, pago: dict, cm) -> list:
    filas = filas_contacto(pago)
    if not filas:
        return [doc.P("Por consultas sobre el enlace, la presentación o el pago de la cuota, comuníquense con el "
                      "sindicato.", fontSize=9.5, leading=13.5)]
    return [doc.P("Por consultas sobre el enlace, la presentación o el pago de la cuota:", fontSize=9.5, leading=13.5,
                  spaceAfter=5), _recuadro(doc, filas, cm)]


def pdf(empresa: dict | None = None) -> tuple[io.BytesIO, str]:
    """El instructivo con los datos de hoy. Devuelve (PDF, nombre del archivo)."""
    datos = institucion.obtener()
    return armar(datos, institucion.pago_cuota(datos), empresa), nombre_archivo(datos)
