"""
exportar.py — Exportación a Excel de cualquier grilla.

El botón «Exportar a Excel» de la barra de filtros (macro `ui.barra_filtros`)
manda acá las filas que pasaron el filtro —todas, no solo la página que se ve—
y recibe un .xlsx. Un solo endpoint para todas las grillas: así el archivo sale
igual desde cualquier pantalla, con el mismo encabezado y los mismos formatos.

POR QUÉ .XLSX ARMADO A MANO Y NO CSV
Un CSV abierto en Excel convierte un CUIL en 2,04195E+10 y un código postal
«0123» en 123, y no hay forma de evitarlo desde el archivo. En un .xlsx cada
celda dice su tipo: el CUIL va como texto y sigue siendo un CUIL.

Y a mano y no con openpyxl porque un .xlsx es un zip con cinco XML, y escribir
solo lo que hace falta evita una dependencia más en el Python del IIS.

Tipos de columna (los decide el navegador por la cabecera, ver base.html):
  'n'  número — "1.234,56" → 1234.56, alineado a la derecha
  't'  texto forzado — CUIL, CUIT, documentos, códigos (td-mono)
  ''   automático — fecha si es dd/mm/aaaa, texto si no
"""

import io
import re
import zipfile
from datetime import date, datetime
from xml.sax.saxutils import escape

from flask import Blueprint, request, send_file, jsonify

from db import validasesion

exportar_bp = Blueprint("exportar", __name__)

RE_FECHA = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
RE_NUMERO = re.compile(r"^-?[\d.]*\d(,\d+)?$")
# Caracteres de control que el XML no admite: si se cuelan en un dato, Excel
# declara el archivo dañado en vez de abrirlo.
RE_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
EPOCA_EXCEL = date(1899, 12, 30)

# Estilos (índices de cellXfs en styles.xml).
S_TEXTO, S_ENCABEZADO, S_DECIMAL, S_FECHA, S_ENTERO = 0, 1, 2, 3, 4


def _numero(texto: str):
    """«1.234,56» → 1234.56 · «$ 12» → 12 · lo que no es número → None."""
    t = texto.replace("$", "").replace("%", "").replace(" ", "")
    if not t or not RE_NUMERO.match(t):
        return None
    t = t.replace(".", "").replace(",", ".")
    try:
        n = float(t)
    except ValueError:
        return None
    return int(n) if n.is_integer() and "." not in t else n


def _columna(i: int) -> str:
    letras = ""
    i += 1
    while i:
        i, resto = divmod(i - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


def _celda(ref: str, valor, tipo: str) -> str:
    texto = RE_CONTROL.sub("", "" if valor is None else str(valor)).strip()
    if texto == "":
        return ""
    if tipo == "n":
        n = _numero(texto)
        if n is not None:
            estilo = S_ENTERO if isinstance(n, int) else S_DECIMAL
            return f'<c r="{ref}" s="{estilo}"><v>{n}</v></c>'
    # Una columna numérica puede traer fechas (las fechas también van a la
    # derecha): lo que no es número se prueba como fecha antes de ir a texto.
    if tipo != "t":
        m = RE_FECHA.match(texto)
        if m:
            try:
                d = date(int(m[3]), int(m[2]), int(m[1]))
                return f'<c r="{ref}" s="{S_FECHA}"><v>{(d - EPOCA_EXCEL).days}</v></c>'
            except ValueError:
                pass
    return (f'<c r="{ref}" s="{S_TEXTO}" t="inlineStr"><is><t xml:space="preserve">'
            f'{escape(texto)}</t></is></c>')


def xlsx(nombre: str, columnas: list[dict], filas: list[list]) -> bytes:
    """Un libro de una hoja: encabezado fijo con autofiltro, anchos según el contenido."""
    n_cols = len(columnas)
    ultima = _columna(max(n_cols - 1, 0))
    anchos = [len(c.get("titulo") or "") for c in columnas]
    for f in filas:
        for i, v in enumerate(f[:n_cols]):
            anchos[i] = max(anchos[i], len(str(v or "")))

    filas_xml = ['<row r="1">' + "".join(
        f'<c r="{_columna(i)}1" s="{S_ENCABEZADO}" t="inlineStr"><is><t>'
        f'{escape(RE_CONTROL.sub("", c.get("titulo") or ""))}</t></is></c>'
        for i, c in enumerate(columnas)) + "</row>"]
    for r, f in enumerate(filas, start=2):
        celdas = "".join(_celda(f"{_columna(i)}{r}", v, columnas[i].get("tipo", ""))
                         for i, v in enumerate(f[:n_cols]))
        filas_xml.append(f'<row r="{r}">{celdas}</row>')

    cols_xml = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{min(a, 60) + 3}" customWidth="1"/>'
                       for i, a in enumerate(anchos))
    hoja = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f'<cols>{cols_xml}</cols>'
        f'<sheetData>{"".join(filas_xml)}</sheetData>'
        f'<autoFilter ref="A1:{ultima}{max(len(filas) + 1, 1)}"/>'
        '</worksheet>'
    )
    # El nombre de hoja no admite estos caracteres y tiene un tope de 31.
    nombre_hoja = re.sub(r"[\[\]:*?/\\]", " ", nombre).strip()[:31] or "Hoja1"

    estilos = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<numFmts count="2"><numFmt numFmtId="164" formatCode="#,##0.00"/>'
        '<numFmt numFmtId="165" formatCode="dd/mm/yyyy"/></numFmts>'
        '<fonts count="2"><font><sz val="10"/><name val="Calibri"/></font>'
        '<font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts>'
        # El azul de la cabecera de grilla (--navy), para que el archivo se
        # reconozca como salido del sistema.
        '<fills count="3"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF1C5A8F"/></patternFill></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="5">'
        '<xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
        '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '<xf numFmtId="3" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   '</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   '</Relationships>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   f'<sheets><sheet name="{escape(nombre_hoja)}" sheetId="1" r:id="rId1"/></sheets>'
                   '<definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">'
                   f"'{escape(nombre_hoja)}'!$A$1:${ultima}${max(len(filas) + 1, 1)}</definedName></definedNames>"
                   '</workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                   '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   '</Relationships>')
        z.writestr("xl/styles.xml", estilos)
        z.writestr("xl/worksheets/sheet1.xml", hoja)
    return buffer.getvalue()


@exportar_bp.route("/exportar/excel", methods=["POST"])
def excel():
    """
    Recibe {nombre, columnas: [{titulo, tipo}], filas: [[...]]} como JSON y
    devuelve el .xlsx. JSON en el cuerpo y no un formulario: una grilla de
    5.000 filas pasa holgado el tope de 500 KB que Werkzeug pone a un campo
    de formulario, y el error que da no dice nada de eso.
    """
    if not validasesion():
        return jsonify({"error": "La sesión venció. Volvé a entrar."}), 401
    datos = request.get_json(silent=True) or {}
    columnas = datos.get("columnas") or []
    filas = datos.get("filas") or []
    if not columnas:
        return jsonify({"error": "La grilla no tiene columnas para exportar."}), 400

    nombre = re.sub(r"[^\w\- ]", "", str(datos.get("nombre") or "grilla"), flags=re.UNICODE).strip() or "grilla"
    archivo = f"{nombre.replace(' ', '_')}_{datetime.now():%Y%m%d_%H%M}.xlsx"
    return send_file(
        io.BytesIO(xlsx(nombre, columnas, filas)),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True, download_name=archivo,
    )
