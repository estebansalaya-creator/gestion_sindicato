# -*- coding: utf-8 -*-
"""
lector_pdf_ocr.py — leer un comprobante que vino escaneado

Copiado de gestion_adm sin cambios de lógica (solo la variable de entorno del
binario de Tesseract). El OCR es opcional: sin PyMuPDF, pytesseract y el
binario, un PDF escaneado se carga a mano, como antes de que existiera.

EL PROBLEMA
-----------
Una parte de los prestadores manda el PDF escaneado: seis páginas de imagen y
ni un carácter de texto adentro. `pdfplumber` devuelve cadena vacía, el parser
no tiene qué parsear y la carga cae a mano. No es un formato raro que haya que
enseñarle al parser —eso sería un problema de layout—: no hay texto que leer.

La factura de WENT SA 0143-00009823 del 30/07/2026 es el caso testigo: 1.095 KB
de JPEG, seis páginas, cero caracteres.

QUÉ HACE
--------
Cuando el PDF no trae texto, se rasteriza y se pasa por Tesseract. El texto que
sale alimenta al mismo parser de siempre, así que el resto del circuito no se
entera de por dónde vino.

POR QUÉ 400 DPI Y NO 300
------------------------
A 300 con segmentación automática, Tesseract leyó «0143-00009825» en un
comprobante que es el 9823. Un dígito. Con ese número el cotejo contra ARCA da
negativo —que al menos es seguro— pero si el error hubiera caído en un dígito
que no se compara, habría pasado por bueno un PDF que no es. A 400 el número
sale bien, y son dos segundos más por página.

400 dpi con segmentación automática y 300 con `--psm 6` leyeron los dos el
número correcto; se usa el primero porque el segundo asume que la página es un
bloque de texto uniforme, y una factura no lo es: tiene encabezado, tabla y
pie.

POR QUÉ SÓLO LAS PRIMERAS PÁGINAS
---------------------------------
Cada página son unos doce segundos. Los datos que se buscan —CUIT, punto de
venta, número, importe— están en la primera; el resto es el detalle de
medicamentos. Se leen de a una y se corta apenas se encontró lo que hacía
falta. Seis páginas completas serían más de un minuto con el navegador
esperando.

SIN TESSERACT NO SE ROMPE NADA
------------------------------
En el servidor propio puede no estar instalado. En ese caso esto devuelve
texto vacío y un motivo legible, que es exactamente lo que pasaba antes de que
este módulo existiera: el comprobante se carga a mano.
"""
import io
import logging
import pathlib
import re
from decimal import Decimal, InvalidOperation

log = logging.getLogger(__name__)

DPI_OCR = 400
#: Más que esto no se lee: los datos del comprobante están en la primera
#: página y cada una cuesta unos doce segundos.
PAGINAS_MAX = 3


def _ruta_tesseract() -> str:
    """Dónde está el binario, si hace falta decirlo.

    `pytesseract` lo busca en el PATH y nada más. Eso alcanza en un contenedor
    Debian, donde apt lo deja en /usr/bin, y no alcanza en Windows: el
    instalador de UB Mannheim lo pone en «Program Files\\Tesseract-OCR» y no
    toca el PATH del servicio.

    `SIND_TESSERACT_CMD` en el .env resuelve los dos casos sin tocar código.
    `TESSERACT_CMD` se acepta también: es el nombre que usa gestion_adm.
    """
    import os
    return (os.getenv("SIND_TESSERACT_CMD") or os.getenv("TESSERACT_CMD") or "").strip()


def _hay_ocr() -> tuple[bool, str]:
    """¿Están las dos piezas que hacen falta? Devuelve (sí/no, qué falta)."""
    try:
        import pymupdf  # noqa: F401
    except ImportError:
        return False, "falta la biblioteca PyMuPDF"
    try:
        import pytesseract
    except ImportError:
        return False, "falta la biblioteca pytesseract"

    ruta = _ruta_tesseract()
    if ruta:
        pytesseract.pytesseract.tesseract_cmd = ruta
    try:
        pytesseract.get_tesseract_version()
    except Exception:
        # La biblioteca está y el binario no aparece. El motivo dice DÓNDE se
        # buscó: «no está instalado» a secas manda a instalar algo que en
        # Railway ya está en la imagen, y el problema real suele ser que el
        # proceso no lo ve.
        import shutil
        donde = ruta or shutil.which("tesseract") or "no está en el PATH"
        return False, (f"no se encontró el binario de Tesseract ({donde}). "
                       "Indicá la ruta en SIND_TESSERACT_CMD")
    return True, ""


def ocr_de_pdf(contenido: bytes, paginas_max: int = PAGINAS_MAX,
               corta_si=None, dpi: int = DPI_OCR,
               config: str = "") -> tuple[str, str]:
    """
    Rasteriza y OCRea el PDF. Devuelve (texto, motivo_si_no_se_pudo).

    `corta_si` es una función que recibe el texto acumulado y devuelve True
    cuando ya alcanza. Sirve para no OCRear seis páginas cuando lo que se
    buscaba estaba en la primera.

    `dpi` y `config` (opciones de Tesseract, p. ej. «--psm 11») son para
    lecturas especiales: la constancia de trazabilidad escaneada se lee mejor
    a la resolución del escáner y como texto disperso (ver `traza_asociar`).
    """
    ok, falta = _hay_ocr()
    if not ok:
        return "", falta

    import pymupdf
    import pytesseract
    from PIL import Image

    try:
        doc = pymupdf.open(stream=contenido, filetype="pdf")
    except Exception as e:                                   # noqa: BLE001
        return "", f"el PDF no se pudo abrir para OCR ({e})"

    partes = []
    try:
        for n, pagina in enumerate(doc):
            if n >= paginas_max:
                break
            pix = pagina.get_pixmap(dpi=dpi)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            partes.append(pytesseract.image_to_string(img, config=config))
            texto = "\n".join(partes)
            if corta_si and corta_si(texto):
                break
    except Exception as e:                                   # noqa: BLE001
        log.warning("OCR interrumpido en la página %s: %s", len(partes) + 1, e)
        if not partes:
            return "", f"el OCR falló ({e})"
    finally:
        doc.close()

    texto = "\n".join(partes)
    log.info("OCR: %s página(s), %s caracteres", len(partes), len(texto))
    return texto, ""


def texto_de_pdf(contenido: bytes, corta_si=None) -> tuple[str, str, str]:
    """
    El texto del comprobante, venga de donde venga.

    Devuelve (texto, origen, motivo). `origen` es "pdf" cuando el archivo
    traía su capa de texto y "ocr" cuando hubo que leer la imagen; el que
    llama lo usa para decir de dónde salió lo que muestra, que no es un
    detalle: un dato leído por OCR es una lectura de una foto y merece que
    alguien lo mire.
    """
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(contenido)) as pdf:
            texto = "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception as e:                                   # noqa: BLE001
        return "", "", f"el PDF no se pudo abrir ({e})"

    if (texto or "").strip():
        return texto, "pdf", ""

    texto, motivo = ocr_de_pdf(contenido, corta_si=corta_si)
    if not (texto or "").strip():
        return "", "", (f"el PDF no tiene texto —es un escaneo— y no se pudo "
                        f"leer la imagen: {motivo}" if motivo else
                        "el PDF no tiene texto y el OCR no encontró nada")
    return texto, "ocr", ""


# =============================================================================
# Identificar el comprobante en lo leído
# =============================================================================

def _digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def identificar(texto: str) -> dict:
    """
    Saca del texto los datos que sirven para ENCONTRAR el comprobante.

    No intenta leer la factura entera: busca el CUIT del emisor y el número
    —punto de venta y correlativo—, que es lo que alcanza para ir a buscar el
    resto a Mis Comprobantes. Todo lo demás —importe, fecha, tipo, CAE— sale
    de ahí, que es el dato de ARCA y no una lectura de una foto.

    Devuelve {"cuits": [...], "numeros": [(pv, nro), ...], "importes": [...]}
    con TODOS los candidatos y no con uno elegido: la elección la hace quien
    puede cruzarlos contra la base, que sabe cuál existe.
    """
    plano = texto or ""

    # CUITs: con guiones o sin ellos. El del emisor y el del receptor están
    # los dos en la página, así que se devuelven ambos y el que busca decide.
    cuits = []
    for m in re.finditer(r"\b(\d{2})[-\s]?(\d{8})[-\s]?(\d)\b", plano):
        c = m.group(1) + m.group(2) + m.group(3)
        if c not in cuits:
            cuits.append(c)

    # Número: «0143 -00009823», «0143-00009823», «Punto de Venta: 0143 Comp.
    # Nro: 00009823». Se aceptan las tres formas porque cada diseño de factura
    # lo escribe distinto, y el OCR además mete espacios donde quiere.
    numeros = []
    # Sin \b adelante: la letra del comprobante puede venir pegada al punto
    # de venta («A00003-00002620», APREDIS) y entre letra y dígito no hay borde.
    # Hasta dos ceros de relleno de más: «0006 - 0000026728» (Hospital
    # Posadas). ARCA numera con ocho dígitos como máximo.
    for pv, nro in re.findall(r"(?<!\d)(\d{4,5})\s*[-–]\s*0{0,2}(\d{7,8})\b", plano):
        par = (pv.zfill(5), nro.zfill(8))
        if par not in numeros:
            numeros.append(par)
    m_pv = re.search(r"[Pp]unto\s+de\s+[Vv]enta\D{0,10}(\d{1,5})", plano)
    # «Comp. Nº:» también (VISITAR).
    m_nr = re.search(r"(?:Comp\.?\s*N(?:ro|º|°)|Nro\.?\s*Comp|N[úu]?mero)\D{0,10}(\d{1,8})", plano)
    if m_pv and not m_nr:
        # «Punto de Venta: 00003 Nro:00001526»: «Nro» a secas, a continuación
        # del punto de venta (Cámara Argentina de Desarrolladores de Software).
        m_nr = re.search(r"[Pp]unto\s+de\s+[Vv]enta\D{0,10}\d{1,5}\s+N(?:ro|°|º)\.?\s*:?\s*(\d{1,8})",
                         plano)
    if m_pv and m_nr:
        par = (m_pv.group(1).zfill(5), m_nr.group(1).zfill(8))
        if par not in numeros:
            numeros.append(par)

    # CAE: 14 dígitos, solos. Sirve para desempatar cuando el PDF nombra más
    # de un comprobante (ver `_desempatar`).
    caes = list(dict.fromkeys(re.findall(r"(?<!\d)(\d{14})(?!\d)", plano)))

    return {"cuits": cuits, "numeros": numeros,
            "importes": importes_del_texto(plano), "caes": caes}


#: Cuántos períodos hacia atrás puede tener un comprobante que se está
#: cargando hoy, contando el mes en curso.
#:
#: La SSS no acepta rendir en Integración una prestación de más de cuatro
#: períodos atrás. Acá se usa como filtro de lo que el detector puede DEDUCIR:
#: un «agosto» leído en un texto de OCR que resuelve a 2021 no es el período
#: del comprobante, es basura. La ventana exacta de presentación se valida
#: aparte, al guardar, y sale del último DR.ENVIO cargado.
MESES_VENTANA = 4

#: Los meses como los escribe un prestador, en nombre completo y abreviados.
#:
#: `setiembre` va al lado de `septiembre` porque las dos se usan y ninguna está
#: mal. Las abreviaturas de tres letras existen porque en la descripción de un
#: ítem el espacio es poco: «Transporte esp. AGO/2026».
_MESES = {
    "enero": 1, "ene": 1, "febrero": 2, "feb": 2, "marzo": 3, "mar": 3,
    "abril": 4, "abr": 4, "mayo": 5, "may": 5, "junio": 6, "jun": 6,
    "julio": 7, "jul": 7, "agosto": 8, "ago": 8,
    "septiembre": 9, "setiembre": 9, "sept": 9, "sep": 9, "set": 9,
    "octubre": 10, "oct": 10, "noviembre": 11, "nov": 11,
    "diciembre": 12, "dic": 12,
}

#: Dónde empieza y dónde termina el detalle de los ítems.
#:
#: El período se busca ahí y no en toda la factura porque el resto del papel
#: está lleno de fechas que no son el período: emisión, vencimiento del pago,
#: vencimiento del CAE. Un mes en letras casi nunca aparece en esas —van en
#: dd/mm/aaaa— pero el `08/2026` suelto sí, y ahí es donde se equivoca.
_ITEMS_DESDE = re.compile(
    r"(Producto\s*/\s*Servicio|Descripci[oó]n|Detalle|Concepto)", re.IGNORECASE)
_ITEMS_HASTA = re.compile(
    r"(Subtotal|Importe\s+Otros\s+Tributos|Importe\s+Total|Otros\s+Tributos)",
    re.IGNORECASE)


def _anio_mes_corriente(fecha_emision: str = "") -> tuple[int, int]:
    """
    El año y el mes contra los que se resuelve un mes escrito sin año.

    Sale de la fecha de emisión y no de la fecha de hoy: un comprobante se
    puede cargar meses después, y ahí «el año corriente» sería el equivocado.
    Sin fecha de emisión legible se cae a hoy, que es lo mejor que hay.
    """
    import datetime as _dt
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", fecha_emision or "")
    if m:
        return int(m.group(3)), int(m.group(2))
    hoy = _dt.date.today()
    return hoy.year, hoy.month


def _zona_items(texto: str) -> tuple[str, str]:
    """El bloque del detalle, o todo el texto si no se lo puede acotar."""
    m1 = _ITEMS_DESDE.search(texto)
    if not m1:
        return texto, "todo el comprobante"
    # El detalle empieza en el renglón SIGUIENTE al encabezado de la grilla.
    # Sin saltearlo, el «Subtotal» que es una columna del encabezado corta la
    # zona en el primer carácter y no queda nada donde buscar.
    fin_encabezado = texto.find("\n", m1.end())
    resto = texto[fin_encabezado + 1:] if fin_encabezado != -1 else texto[m1.end():]
    m2 = _ITEMS_HASTA.search(resto)
    zona = resto[:m2.start()] if m2 else resto
    # Una zona de dos palabras no es el detalle: es un encabezado suelto y hay
    # que volver a mirar todo. Veinte caracteres es menos que cualquier
    # descripción real —«Apoyo a la integración escolar» son treinta— y más que
    # cualquier resto de encabezado.
    return ((zona, "la descripción del ítem") if len(zona.strip()) > 20
            else (texto, "todo el comprobante"))


def periodo_del_texto(texto: str, fecha_emision: str = "") -> tuple[str, str]:
    """
    El período facturado, buscado en la descripción de los ítems.

    POR QUÉ HACE FALTA
    ------------------
    En Integración el período es lo que decide contra qué legajo y contra qué
    precio se compara el comprobante, y con qué presentación viaja. El parser
    lo saca de «Período Facturado Desde/Hasta», que es un campo del formato
    AFIP y que una parte de los prestadores deja vacío: factura un servicio
    mensual y escribe el mes en la descripción del ítem —«Apoyo a la
    integración escolar - AGOSTO 2026»— y en ningún otro lado.

    Sin período el comprobante entra sin renglón de DS y no se puede presentar.
    Que lo complete alguien a mano es posible, pero recién se descubre cuando
    ya está cargado.

    QUE BUSCA, EN ORDEN
    -------------------
        1. Mes en letras y año:  «AGOSTO 2026», «agosto/26», «ago. de 2026»
        2. Rango en prosa:       «del 01/08/2026 al 31/08/2026»
        3. MM/AAAA:              «08/2026», «08-2026»
        4. AAAAMM:               «202608»
        5. Mes solo, sin año:    «AGOSTO»  → el año sale de la emisión

    Sea cual sea el que acierte, el resultado tiene que caer dentro de la
    ventana: no posterior al mes en curso ni al de la emisión, y no anterior a
    `MESES_VENTANA` períodos atrás. Un candidato fuera de eso se descarta y se
    devuelve vacío, que es honesto: mejor sin período que con uno inventado.

    El quinto sólo corre dentro del bloque del detalle, y es el único con esa
    restricción: un mes suelto es lo más fácil de confundir que hay ---«25 de
    Mayo 1234» es un domicilio--- y fuera del detalle no vale el riesgo.

    El mes en letras va primero porque es el que no se confunde con nada. Los
    otros dos son ambiguos —un `08/2026` puede ser el resto de un `31/08/2026`—
    así que se descartan los que vengan pegados a un día.

    COMO ELIGE CUANDO HAY VARIOS
    ----------------------------
    Gana el que más veces aparece: una factura con seis renglones del mismo mes
    lo repite seis veces, y la mención suelta de otro mes —«saldo de julio»— no
    le gana a eso. Si empatan, el primero que aparece.

    Devuelve (AAAAMM, de dónde salió) o ("", motivo por el que no lo encontró).
    """
    if not texto:
        return "", "no hay texto"

    zona, donde = _zona_items(texto)

    # El año de la emisión acota lo aceptable. Sin él igual funciona, pero un
    # «2016» perdido en un texto de OCR pasaría por período válido.
    # La ventana de lo posible, en meses absolutos. El techo es el mes en curso
    # y, si se pudo leer, el de la emisión: lo que sea más chico. El piso son
    # cuatro períodos contando el actual.
    import datetime as _dt
    _hoy = _dt.date.today()
    tope = _hoy.year * 12 + _hoy.month
    m_em = re.search(r"(\d{2})/(\d{2})/(\d{4})", fecha_emision or "")
    if m_em:
        tope = min(tope, int(m_em.group(3)) * 12 + int(m_em.group(2)))
    piso = (_hoy.year * 12 + _hoy.month) - (MESES_VENTANA - 1)

    candidatos: list[tuple[int, int, int]] = []      # (posición, año, mes)

    def _anio(txt: str) -> int:
        n = int(txt)
        return n if n >= 1000 else 2000 + n          # «26» es 2026

    meses_re = "|".join(sorted(_MESES, key=len, reverse=True))
    # Sin `\b` alrededor del mes: pdfplumber pega las palabras cuando el
    # PDF no trae espacios —«...CUIL20556069922Septiembre2026»— y entre un
    # dígito y una letra no hay límite de palabra. Lo que importa es que no
    # sea parte de otra palabra: ni letra antes ni letra después.
    for m in re.finditer(
            rf"(?<![^\W\d_])({meses_re})(?![^\W\d_])\.?\s*(?:de[l]?\s+)?[/\-\s]?\s*((?:20)?\d{{2}})\b",
            zona, re.IGNORECASE):
        candidatos.append((m.start(), _anio(m.group(2)), _MESES[m.group(1).lower()]))

    if not candidatos:
        # El rango escrito en prosa: «del 01/08/2026 al 31/08/2026». No lo
        # agarra el parser de arriba porque no dice «Desde» ni «Hasta», y es
        # como lo escribe media docena de prestadores. Manda el mes de la
        # primera fecha: es donde empieza la prestación.
        for m in re.finditer(
                r"(\d{2})/(\d{2})/(\d{4})\s*(?:al|a|hasta|/|-|–)\s*\d{2}/\d{2}/\d{4}",
                zona, re.IGNORECASE):
            candidatos.append((m.start(), int(m.group(3)), int(m.group(2))))

    if not candidatos:
        # `(?<![\d/\-])` evita quedarse con el «08/2026» que en realidad es la
        # cola de un «31/08/2026».
        for m in re.finditer(r"(?<![\d/\-])(0[1-9]|1[0-2])[/\-](20\d{2})(?![/\-]?\d)",
                             zona):
            candidatos.append((m.start(), int(m.group(2)), int(m.group(1))))

    if not candidatos:
        for m in re.finditer(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(?!\d)", zona):
            candidatos.append((m.start(), int(m.group(1)), int(m.group(2))))

    # Último recurso: el mes SOLO, sin año. «Apoyo a la integración escolar -
    # AGOSTO». Es como factura una parte de los prestadores, y el año lo da por
    # obvio quien lo escribe.
    #
    # SÓLO EN LA ZONA DEL DETALLE
    # Un mes suelto es lo más fácil de confundir que hay: «25 de Mayo 1234» es
    # un domicilio y aparece en el encabezado de medio padrón de prestadores.
    # Si el bloque del detalle no se pudo acotar, esto no corre: prefiero no
    # deducir el período a deducirlo de una calle.
    #
    # Y se descartan los que vienen precedidos de un número y «de» ---«17 de
    # Agosto»---, que es la forma de la fecha patria y de la calle.
    if not candidatos and donde == "la descripción del ítem":
        anio_base, mes_tope = _anio_mes_corriente(fecha_emision)
        for m in re.finditer(rf"(?<!\d)(?<!\d\s)(?<!\d\s\s)\b({meses_re})\b(?!\s*\.?\s*/?\s*\d)",
                             zona, re.IGNORECASE):
            if re.search(r"\d\s*de\s*$", zona[max(0, m.start() - 12):m.start()],
                         re.IGNORECASE):
                continue
            mes = _MESES[m.group(1).lower()]
            # El año corriente, con una salvedad que no es teórica: una factura
            # de enero por «diciembre» es del año anterior. Sin esto el período
            # sale doce meses en el futuro y el filtro de abajo lo tira, con lo
            # cual el comprobante queda sin período igual.
            anio = anio_base if mes <= mes_tope else anio_base - 1
            candidatos.append((m.start(), anio, mes))
        if candidatos:
            donde = "un mes sin año en la descripción del ítem"

    # Un período posterior a la emisión no existe —nadie factura un mes que
    # todavía no pasó— y uno de hace más de cuatro períodos no se puede rendir,
    # así que tampoco es el que se está cargando. Se compara mes contra mes y
    # no año contra año: en una factura de septiembre de 2026, «diciembre 2026»
    # es del mismo año y tampoco puede ser.
    #
    # Esto NO es la validación de la ventana de presentación: es el filtro de
    # lo que se puede deducir sin preguntar. Un período que el operador escribe
    # a mano pasa por acá igual, y lo valida el guardado.
    candidatos = [c for c in candidatos
                  if piso <= c[1] * 12 + c[2] <= tope]

    if not candidatos:
        return "", f"no se encontró un mes en {donde}"

    conteo: dict[tuple[int, int], list[int]] = {}
    for pos, anio, mes in candidatos:
        conteo.setdefault((anio, mes), []).append(pos)
    (anio, mes), posiciones = max(conteo.items(),
                                  key=lambda kv: (len(kv[1]), -min(kv[1])))
    return f"{anio}{mes:02d}", donde


def importes_del_texto(texto: str) -> list[Decimal]:
    """
    Todos los importes del texto, ya convertidos a número.

    POR QUÉ NO SE COMPARAN COMO TEXTO
    ---------------------------------
    Cada emisor escribe el mismo importe distinto: «1.005.286,60»,
    «1,005,286.60», «1005286.60». Armar las variantes del importe buscado y ver
    si alguna aparece en el PDF parecía más simple, y así estaba hecho: fallaba
    con la convención de punto decimal y coma de miles —la que usan WENT y
    varios sistemas de facturación—, porque la variante se construía mal y
    quedaba «1.005.286.60», que no es ningún formato. El comprobante se cargaba
    con el importe correcto y al registrar avisaba que el PDF no coincidía.

    Convertir a número y comparar valores no tiene ese problema, y de paso
    tolera cualquier convención que aparezca mañana.

    EL SEPARADOR DECIMAL ES EL ÚLTIMO
    ---------------------------------
    Con dos decimales siempre, el último punto o coma es el decimal y todo lo
    anterior son miles. No hace falta adivinar la convención del emisor.
    """
    vistos, out = set(), []
    for m in re.finditer(r"(?<![\d.,])\d{1,3}(?:([.,\s])\d{3})+[.,]\d{2}(?![\d.,])"
                         r"|(?<![\d.,])\d+[.,]\d{2}(?![\d.,])", texto or ""):
        crudo = m.group(0)

        # Los separadores de miles tienen que ser TODOS el mismo. Sin este
        # control, «...104010 723,123.12» —una partida seguida del importe—
        # se leía como un solo número de diez millones, tomando el espacio
        # como separador de miles. Un importe fantasma en la lista no rompe
        # nada por sí solo, pero es un importe que el cotejo podría llegar a
        # dar por bueno.
        seps = set(re.findall(r"[.,\s](?=\d{3}(?:[.,\s]|$))", crudo[:-3]))
        if len(seps) > 1:
            continue

        cuerpo = re.sub(r"\D", "", crudo[:-3])
        if not cuerpo:
            continue
        try:
            v = Decimal(f"{cuerpo}.{crudo[-2:]}")
        except InvalidOperation:
            continue
        if v and v not in vistos:
            vistos.add(v)
            out.append(v)
    return out


def buscar_en_mis_comprobantes(cur, ident: dict) -> tuple[dict | None, str]:
    """
    Con lo identificado en el PDF, trae el comprobante de Mis Comprobantes.

    POR QUÉ ACÁ Y NO LEER LA FACTURA ENTERA
    ---------------------------------------
    Del escaneo hace falta acertar sólo dos cosas: el CUIT del emisor y el
    número. El importe, la fecha, el tipo y el CAE salen de `f_mis_comprobantes`,
    que es lo que ARCA informó. Un importe leído de una foto y un importe
    informado por el organismo no son el mismo dato, y para cargar una deuda
    corresponde el segundo.

    Devuelve (fila, motivo). Con más de un candidato devuelve (None, motivo):
    elegir por su cuenta entre dos comprobantes del mismo emisor es
    exactamente lo que no hay que hacer sin que alguien mire.
    """
    cuits = ident.get("cuits") or []
    numeros = ident.get("numeros") or []
    importes = ident.get("importes") or []
    if not numeros:
        return None, "no se pudo leer el número de comprobante en el PDF"

    _COLS = """m.id, m.fecha_emision, m.tipo_comprobante, m.punto_de_venta,
               m.numero, m.cuit_emisor, m.razon_social, m.importe_neto,
               m.importe_no_grav, m.importe_exento, m.importe_iva,
               m.importe_otros, m.importe_total, m.moneda, m.cae,
               m.id_comprobante, m.ignorado"""

    por_numero, par_numero = [], []
    for pv, nro in numeros:
        por_numero.append("(LPAD(m.punto_de_venta,5,'0') = %s "
                          " AND LPAD(m.numero,8,'0') = %s)")
        par_numero += [pv, nro]
    sql_numero = " OR ".join(por_numero)

    # 1) CUIT del emisor + número. Es la más fuerte y la que sirve cuando el
    #    PDF trae el CUIT, sea por texto o por OCR.
    filas = []
    if cuits:
        marc_c = ", ".join(["%s"] * len(cuits))
        cur.execute(f"""SELECT {_COLS} FROM f_mis_comprobantes m
                         WHERE m.cuit_emisor IN ({marc_c}) AND ({sql_numero})""",
                    list(cuits) + par_numero)
        filas = cur.fetchall()

    # 2) Número + importe, cuando el CUIT del emisor no está en el texto.
    #
    #    Hay facturas cuyo membrete es una imagen: el nombre y el CUIT del que
    #    emite están dibujados, y la capa de texto sólo tiene los valores que el
    #    sistema del prestador imprime encima. Ahí el único CUIT que se lee es
    #    el del RECEPTOR —el nuestro— y buscar por emisor no encuentra nada.
    #
    #    El par punto de venta + número no alcanza solo: en Mis Comprobantes hay
    #    217 pares distintos sobre 219 filas, o sea que dos emisores repiten
    #    numeración. Sumando el importe son 219 de 219, únicos. Por eso el
    #    importe no es opcional en esta vía.
    por_importe = "match por número e importe"
    if not filas and importes:
        marc_i = ", ".join(["%s"] * len(importes))
        cur.execute(f"""SELECT {_COLS} FROM f_mis_comprobantes m
                         WHERE ({sql_numero})
                           AND m.importe_total IN ({marc_i})""",
                    par_numero + [str(v) for v in importes])
        filas = cur.fetchall()
        if filas:
            return _unica(_desempatar(filas, ident), por_importe)

    if not filas:
        if not cuits:
            return None, ("no se pudo leer el CUIT del emisor ni encontrar el "
                          "comprobante por número e importe")
        return None, ("el comprobante leído no está en Mis Comprobantes "
                      "(¿falta importar el período?)")
    return _unica(_desempatar(filas, ident), "")


def _desempatar(filas, ident: dict) -> list:
    """Entre varios candidatos, el que el PDF identifica sin dudas.

    Una nota de crédito nombra la factura que ajusta: la NC A 0001-00020024 de
    FACOEP dice «Factura asociada: FACA2 0001-00032162», y las dos están en
    Mis Comprobantes con el mismo emisor. Elegir por cercanía o por orden
    sería adivinar; elegir por el CAE impreso no: es único por comprobante.
    Si el CAE no desempata (no se leyó, o no está), el importe total, siempre
    que coincida con UNO solo. Si nada desempata, vuelven todos y lo decide
    una persona, como hasta ahora.
    """
    if len(filas) < 2:
        return filas
    caes = set(ident.get("caes") or [])
    por_cae = [f for f in filas if str(f.get("cae") or "").strip() in caes]
    if len(por_cae) == 1:
        return por_cae
    importes = set()
    for v in ident.get("importes") or []:
        try:
            importes.add(Decimal(str(v)))
        except (InvalidOperation, ValueError):
            pass
    por_importe = [f for f in filas if f.get("importe_total") is not None
                   and Decimal(str(f["importe_total"])) in importes]
    if len(por_importe) == 1:
        return por_importe
    return filas


def _unica(filas, nota: str):
    """Una sola fila o ninguna: elegir entre dos es lo que no hay que hacer."""
    if len(filas) > 1:
        return None, (f"lo leído coincide con {len(filas)} comprobantes de "
                      "Mis Comprobantes: hay que elegir a mano")
    fila = filas[0]
    if fila["id_comprobante"]:
        return fila, "ese comprobante ya está cargado en el sistema"
    return fila, nota


# =============================================================================
# Cotejo: ¿el PDF dice lo mismo que ARCA?
# =============================================================================

#: Con qué empieza la observación cuando NO SE PUDO leer el archivo.
#:
#: «No coincide» y «no se pudo verificar» son dos cosas distintas y la persona
#: que las lee actúa distinto: la primera es un problema del archivo —subió el
#: que no era— y la segunda es de este servidor —falta Tesseract, el PDF está
#: dañado—. Mezclarlas hace que alguien vuelva a subir el archivo correcto tres
#: veces peleando contra una biblioteca que no está instalada.
#:
#: Se marca con un prefijo y no con un valor de retorno más para no cambiarle
#: la forma a las dos llamadas que ya existen.
ILEGIBLE = "No se pudo verificar el PDF: "
#
# Vivía en `gestion_adm.py`, al lado de la carga. Se mudó acá cuando la pantalla
# del expediente necesitó lo mismo para el PDF que se adjunta después: dos
# copias del criterio de «esto coincide» se separan, y el día que difieran la
# carga y el reemplazo van a marcar `leido_automatico` distinto para el mismo
# archivo.

def cotejar_pdf(ruta, cuit, tipo, punto_venta, numero, importe):
    """
    ¿El PDF dice lo mismo que ARCA? Devuelve (leido_ok, observacion).

    `leido_ok` es lo que va a `f_comprobantes_arca.leido_automatico`, y sólo
    es cierto cuando el archivo se pudo leer Y lo leído coincide con lo que
    informó el organismo. Sin PDF no hay nada que cotejar: no es un error, es
    que todavía no llegó.

    Se comparan CUIT del emisor, punto de venta, número e importe total. El
    tipo no: en el PDF viene como texto —"FACTURA C", "Cod. 011"— y hacerlo
    coincidir con el código de ARCA daría falsos negativos sin agregar nada
    que el número y el CUIT no digan ya.
    """
    if not ruta or not pathlib.Path(ruta).exists():
        return False, ""

    import re as _re

    try:
        _crudo = pathlib.Path(ruta).read_bytes()
    except Exception as e:                                   # noqa: BLE001
        return False, ILEGIBLE + f"{e}."

    # Si el archivo vino escaneado, el texto sale del OCR. Cotejar lo leído de
    # una imagen contra lo que informó ARCA es más flojo que cotejar el texto
    # del PDF —un dígito mal leído da negativo—, pero el negativo manda el
    # comprobante a verificación visual, que es adonde tenía que ir de todos
    # modos: antes ni siquiera se intentaba.
    texto, origen, motivo = texto_de_pdf(_crudo)
    if motivo:
        return False, ILEGIBLE + motivo + "."
    if not (texto or "").strip():
        return False, ILEGIBLE + "el PDF no tiene texto y no se pudo leer la imagen."
    _sufijo = (" El texto se leyó por OCR del escaneo, así que puede tener "
               "errores de lectura.") if origen == "ocr" else ""

    plano = _re.sub(r"[^0-9]", "", texto)
    difs = []

    if cuit and cuit not in plano:
        difs.append(f"el CUIT {cuit} no aparece")

    # El punto de venta y el número van en campos separados del comprobante
    # —"Punto de Venta: 00006   Comp. Nro: 00000412"—, así que se buscan por
    # separado. Y con relleno de ceros o sin él, porque cada diseño de factura
    # los escribe distinto.
    #
    # Antes se busca el par junto, «00003-00002619». Así lo imprimen los que
    # pegan la letra al punto de venta —«Nro.: A00003-00002619», APREDIS—, y
    # entre la letra y el cero no hay borde de palabra: la búsqueda suelta del
    # punto de venta no lo encontraba y el PDF quedaba como que no coincidía.
    try:
        pv  = int(str(punto_venta).lstrip("0") or 0)
        nro = int(str(numero).lstrip("0") or 0)
        limpio = _re.sub(r"[.\s]+", " ", texto)
        if _re.search(rf"(?<!\d)0*{pv}\s*[-\u2013]\s*0*{nro}(?!\d)", texto):
            pass
        elif not _re.search(rf"\b0*{nro}\b", limpio):
            difs.append(f"no aparece el número {nro:08d}")
        elif not _re.search(rf"\b0*{pv}\b", limpio):
            difs.append(f"no aparece el punto de venta {pv:05d}")
    except (TypeError, ValueError):
        pass

    try:
        # El importe se compara COMO NÚMERO y no como texto.
        #
        # Antes se armaban las tres formas de escribirlo y se buscaba alguna en
        # el PDF. Una de las tres estaba mal construida —`1.005.286.60`, que no
        # es ningún formato— así que la convención de coma para miles y punto
        # para decimales, la que usan WENT y varios sistemas de facturación,
        # NUNCA se encontraba: el comprobante se cargaba con el importe
        # correcto y al registrar avisaba que el PDF no coincidía.
        imp = Decimal(str(importe or 0)).quantize(Decimal("0.01"))
        if imp and imp not in importes_del_texto(texto):
            difs.append(f"no aparece el importe {imp}")
    except (InvalidOperation, ValueError):
        pass

    if difs:
        return False, ("El PDF no coincide con lo que informó ARCA: "
                       + ", ".join(difs) + "." + _sufijo)
    return True, ""
