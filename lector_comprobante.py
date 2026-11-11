# -*- coding: utf-8 -*-
"""
lector_comprobante.py — los datos de un comprobante de ARCA a partir del PDF.

El parser es el de gestion_adm (`_parsear_comprobante_afip` y
`_plantilla_sin_rotulos`), copiado sin tocar la lógica: cada patrón está ahí
por una factura real que no se leía, y los comentarios dicen cuál. Los ejemplos
nombran prestadores de la obra social; los formatos son los mismos para los
proveedores del gremio. Donde dice «la OS», acá es el sindicato.

Lo que agrega este módulo es `leer()`, que arma la secuencia completa:
texto del PDF (o del escaneo, con OCR si está), parser y, si lo leído no
alcanza, el comprobante en Mis Comprobantes por CUIT y número
(`lector_pdf_ocr.buscar_en_mis_comprobantes`).
"""


import lector_pdf_ocr

#: Lo mínimo para identificar el comprobante y constatarlo contra ARCA.
MINIMOS = ("cuit_emisor", "tipo_comprobante", "punto_de_venta", "numero",
           "importe_total", "cae", "fecha_emision")

ROTULOS_MINIMOS = {"cuit_emisor": "CUIT del emisor", "tipo_comprobante": "tipo",
                   "punto_de_venta": "punto de venta", "numero": "número",
                   "importe_total": "importe total", "cae": "CAE",
                   "fecha_emision": "fecha de emisión"}


def leer(contenido: bytes, cur) -> dict:
    """
    Lee el PDF y devuelve
        {"datos": dict | None, "texto": str, "origen": "pdf"|"ocr"|"",
         "aviso": str, "faltan": [rótulos]}

    `datos` trae los campos del formulario como texto (fechas dd/mm/aaaa,
    importes con punto decimal). `faltan` lista los mínimos que no salieron:
    con alguno vacío el comprobante no se puede constatar y la carga sigue a
    mano con lo que se haya leído.
    """
    def _ya_alcanza(t):
        i = lector_pdf_ocr.identificar(t)
        return bool(i["cuits"] and i["numeros"])

    texto, origen, motivo = lector_pdf_ocr.texto_de_pdf(contenido, corta_si=_ya_alcanza)
    if motivo:
        return {"datos": None, "texto": "", "origen": "", "faltan": list(ROTULOS_MINIMOS.values()),
                "aviso": f"No se pudo leer el PDF: {motivo}."}

    cur.execute("SELECT descripcion FROM arca_responsable_tipo ORDER BY LENGTH(descripcion) DESC")
    condiciones = [r["descripcion"] for r in cur.fetchall()]
    datos = _parsear_comprobante_afip(texto, condiciones)
    aviso = ""

    # Lo que dice ARCA le gana a lo que dice la foto: de un escaneo, o de un
    # PDF cuyo membrete es una imagen, alcanza con acertar el CUIT y el número
    # para traer el resto de Mis Comprobantes. Ver gestion_adm.carga_comprobante.
    incompleto = (not (datos.get("cuit_emisor") or "").strip()
                  or not float(datos.get("importe_total") or 0))
    if origen == "ocr" or incompleto:
        de_donde = ("El PDF es un escaneo y se leyó por OCR" if origen == "ocr"
                    else "El PDF no trae todos los datos como texto")
        fila, motivo_mc = lector_pdf_ocr.buscar_en_mis_comprobantes(
            cur, lector_pdf_ocr.identificar(texto))
        if fila:
            datos.update({
                "tipo_comprobante": fila["tipo_comprobante"],
                "punto_de_venta":   str(fila["punto_de_venta"]).zfill(5),
                "numero":           str(fila["numero"]).zfill(8),
                "cuit_emisor":      fila["cuit_emisor"],
                "fecha_emision":    (fila["fecha_emision"].strftime("%d/%m/%Y")
                                     if fila["fecha_emision"] else datos.get("fecha_emision", "")),
                "importe_total":    f"{fila['importe_total']:.2f}",
                "importe_neto_gravado": f"{fila['importe_neto'] or 0:.2f}",
                "importe_iva":      f"{fila['importe_iva'] or 0:.2f}",
                "importe_exento":   f"{fila['importe_exento'] or 0:.2f}",
                "cae":              fila["cae"] or datos.get("cae", ""),
            })
            if fila.get("razon_social"):
                datos["razon_social_emisor"] = fila["razon_social"]
            aviso = (f"{de_donde}: se identificó el comprobante y el resto se trajo de Mis "
                     f"Comprobantes ({fila['punto_de_venta']}-{fila['numero']}). {motivo_mc or ''}").strip()
        else:
            aviso = f"{de_donde}: {motivo_mc}. Revisá los datos antes de guardar."

    if datos.get("tipo_comprobante"):
        datos["tipo_comprobante"] = str(datos["tipo_comprobante"]).zfill(3)
    faltan = [ROTULOS_MINIMOS[k] for k in MINIMOS if not str(datos.get(k) or "").strip()
              or (k == "importe_total" and not float(datos.get(k) or 0))]
    return {"datos": datos, "texto": texto, "origen": origen, "aviso": aviso, "faltan": faltan}


# ═════════════════════════════════════════════════════════════════════════════
# El parser de gestion_adm, sin cambios
# ═════════════════════════════════════════════════════════════════════════════

def _plantilla_sin_rotulos(texto, d, condiciones_iva=None):
    """Facturas cuyo texto trae sólo los VALORES: los rótulos son una imagen.

    Fundación Manantiales (30-67804207-9, FC A 00003-00001320 del 03/11/2026)
    factura con una plantilla de TCPDF. «Punto de Venta», «CUIT», «Fecha de
    emisión», «Importe Total» y hasta la condición de IVA del emisor están
    dibujados; lo que pdfplumber devuelve es esto, en este orden:

        ORIGINAL
        A                                       ← letra
        FACTURA
        1                                       ← código de comprobante
        00003 00001320                          ← punto de venta y número
        FUNDACION MANANTIALES 03/11/2026        ← razón social y emisión
        Irigoin 2501 - (1663) San Miguel
        30678042079                             ← CUIT del emisor, solo
        Av. Entre Ríos 831 (1080ABC)
        121959807                               ← ingresos brutos
        01/01/2010                              ← inicio de actividades
        01/10/2026 31/10/2026 03/12/2026        ← período desde, hasta, vto. pago
        30519651145 OSEDA                       ← CUIT y nombre del receptor
        Exento CALLAO 220 P 6 4372.6667         ← condición IVA del receptor
        ...detalle...
        490.000,00 0,00 490.000,00              ← neto, IVA, total
        CUATROCIENTOS NOVENTA MIL CON 00/100 CENTAVOS
        86440844353682 1 13/11/2026             ← CAE, página, vto. CAE

    Sin esto salía casi todo vacío, la razón social era «00003 00001320» y la
    fecha de emisión el 01/01/2010: la única fecha sola en su renglón es la de
    inicio de actividades.

    Se activa sólo si el encabezado tiene exactamente esa forma ---letra, tipo,
    código, número y nombre con fecha, en renglones seguidos---, y desde ahí
    se lee lo que sigue por posición. Lo que el resto del parser ya encontró
    con rótulo no se pisa, salvo la fecha de emisión y la razón social, que
    en esta plantilla sólo pueden salir del encabezado.
    """
    import re
    m = re.search(
        r"^[ \t]*([ABCEM])[ \t]*\n"
        r"[ \t]*(FACTURA|NOTA\s+DE\s+CR[E\xc9]DITO|NOTA\s+DE\s+D[E\xc9]BITO|RECIBO)[ \t]*\n"
        r"[ \t]*0*(\d{1,3})[ \t]*\n"
        r"[ \t]*(\d{4,5})[ \t]+(\d{8})[ \t]*\n"
        r"[ \t]*(\S.*?)[ \t]+(\d{2}/\d{2}/\d{4})[ \t]*$",
        texto, re.MULTILINE | re.IGNORECASE)
    if not m:
        return
    letra = m.group(1).upper()
    if not d.get("tipo_comprobante"):
        d["tipo_comprobante"] = m.group(3)
    if not d.get("punto_de_venta") or not d.get("numero"):
        d["punto_de_venta"] = m.group(4).zfill(5)
        d["numero"]         = m.group(5).zfill(8)
    d["razon_social_emisor"] = m.group(6).strip()
    d["fecha_emision"]       = m.group(7)

    # Lo que sigue al encabezado, hasta el próximo encabezado (el DUPLICADO
    # repite todo): cada dato se toma de su primera aparición.
    resto = texto[m.end():]
    m_sig = re.search(r"^[ \t]*(?:ORIGINAL|DUPLICADO|TRIPLICADO)[ \t]*$", resto, re.MULTILINE)
    if m_sig:
        resto = resto[:m_sig.start()]

    def _num(v):
        return float(v.replace(".", "").replace(",", "."))

    # CUIT del emisor: el primero solo en su renglón.
    m_ce = re.search(r"^[ \t]*(\d{2}-?\d{8}-?\d)[ \t]*$", resto, re.MULTILINE)
    if m_ce and not d.get("cuit_emisor"):
        d["cuit_emisor"] = m_ce.group(1).replace("-", "")

    # Período facturado desde / hasta y vencimiento del pago: tres fechas solas.
    m_per = re.search(r"^[ \t]*(\d{2}/\d{2}/\d{4})[ \t]+(\d{2}/\d{2}/\d{4})"
                      r"[ \t]+(\d{2}/\d{2}/\d{4})[ \t]*$", resto, re.MULTILINE)
    if m_per:
        if not d.get("periodo_desde") or d.get("_periodo_origen"):
            d["periodo_desde"], d["periodo_hasta"] = m_per.group(1), m_per.group(2)
            d.pop("_periodo_origen", None)
        if not d.get("fecha_vto_pago"):
            d["fecha_vto_pago"] = m_per.group(3)

    # Receptor: CUIT y nombre en el mismo renglón; abajo, su condición de IVA
    # escrita corta («Exento CALLAO 220…»).
    m_rec = re.search(r"^[ \t]*(\d{2}-?\d{8}-?\d)[ \t]+(\S.*?)[ \t]*\n[ \t]*(.*)$",
                      resto, re.MULTILINE)
    if m_rec:
        if not d.get("cuit_receptor"):
            d["cuit_receptor"] = m_rec.group(1).replace("-", "")
        if not d.get("razon_social_receptor"):
            d["razon_social_receptor"] = m_rec.group(2).strip()
        if not d.get("condicion_iva_receptor"):
            _sig = m_rec.group(3).strip().lower()
            for _k, _desc in (("iva sujeto exento", "IVA Sujeto Exento"),
                              ("exento", "IVA Sujeto Exento"),
                              ("iva responsable inscripto", "IVA Responsable Inscripto"),
                              ("responsable inscripto", "IVA Responsable Inscripto"),
                              ("responsable monotributo", "Responsable Monotributo"),
                              ("monotributo", "Responsable Monotributo"),
                              ("consumidor final", "Consumidor Final")):
                if _sig.startswith(_k) and (not condiciones_iva or _desc in condiciones_iva):
                    d["condicion_iva_receptor"] = _desc
                    break

    # La condición del emisor es parte de la imagen. A y B sólo las emite un
    # responsable inscripto, así que la letra alcanza para decirla.
    if letra in ("A", "B", "M") and not d.get("condicion_iva_emisor"):
        if not condiciones_iva or "IVA Responsable Inscripto" in condiciones_iva:
            d["condicion_iva_emisor"] = "IVA Responsable Inscripto"

    # Totales: el renglón de importes solos que va justo antes del importe en
    # letras. Se acepta sólo si cierra: lo de adelante suma el último.
    m_tot = re.search(r"^[ \t]*((?:\d{1,3}(?:\.\d{3})*,\d{2}[ \t]+){1,6}\d{1,3}(?:\.\d{3})*,\d{2})"
                      r"[ \t]*\n[ \t]*[A-Z\xc1\xc9\xcd\xd3\xda\xd1][A-Z\xc1\xc9\xcd\xd3\xda\xd1\d/ ]*CENTAVOS",
                      resto, re.MULTILINE)
    if m_tot and not float(d.get("importe_total") or 0):
        imps = [_num(x) for x in m_tot.group(1).split()]
        neto, total = imps[0], imps[-1]
        iva = sum(imps[1:-1])
        if abs(neto + iva - total) < 0.015:
            d["importe_total"] = f"{total:.2f}"
            if iva:
                d["importe_neto_gravado"] = f"{neto:.2f}"
                d["importe_iva"]          = f"{iva:.2f}"
            else:
                # El papel lo rotula «Importe Neto Gravado» con «IVA 21%: 0,00»,
                # pero ARCA lo tiene como EXENTO: las facturas anteriores de
                # Fundación Manantiales en Mis Comprobantes son exento 490.000,
                # neto 0, IVA 0. Un gravado sin IVA en una factura A no existe;
                # se carga como lo informa ARCA.
                d["importe_exento"] = f"{neto:.2f}"

    # CAE, número de página y vencimiento del CAE en el último renglón.
    m_cae = re.search(r"^[ \t]*(\d{14})[ \t]+\d{1,3}[ \t]+(\d{2}/\d{2}/\d{4})[ \t]*$",
                      resto, re.MULTILINE)
    if m_cae:
        if not d.get("cae"):
            d["cae"] = m_cae.group(1)
        if not d.get("fecha_vto_cae"):
            d["fecha_vto_cae"] = m_cae.group(2)


def _parsear_comprobante_afip(texto, condiciones_iva=None):
    import re

    def buscar(patrones, txt, grupo=1, default=""):
        for pat in patrones:
            m = re.search(pat, txt, re.IGNORECASE | re.MULTILINE)
            if m:
                try:
                    return m.group(grupo).strip()
                except IndexError:
                    pass
        return default

    def importe(patrones, txt):
        """Captura importes con formato AFIP: $ 246000,21"""
        raw = buscar(patrones, txt)
        if not raw:
            return "0.00"
        # Formato AFIP: puede tener $ y espacios, punto como miles, coma como decimal
        raw = raw.replace("$", "").strip()
        # Con los dos separadores, el decimal es el ÚLTIMO: «652.958,24» (AR) y
        # «652,958.24» (el formato de la mitad de los sistemas de facturación
        # que no son el de ARCA: CADAQUES, CEDICAS, EQUS FARMA). Antes la coma
        # se tomaba siempre como decimal y «652,958.24» daba 652,95824: un
        # total distinto de cero y MAL, que no dispara la búsqueda en Mis
        # Comprobantes.
        if "," in raw and "." in raw:
            if raw.rfind(".") > raw.rfind(","):
                raw = raw.replace(",", "")
            else:
                raw = raw.replace(".", "").replace(",", ".")
        # Sólo comas en grupos de tres, sin decimales: «48,000» son miles.
        elif "," in raw and re.fullmatch(r"\d{1,3}(?:,\d{3})+", raw.strip()):
            raw = raw.replace(",", "")
        # Si tiene coma: es separador decimal (formato AR)
        elif "," in raw:
            raw = raw.replace(".", "").replace(",", ".")
        # Si no tiene coma: puede ser entero o con punto decimal (formato US)
        # quitamos puntos de miles solo si hay 3 dígitos después
        else:
            import re as _re
            raw = _re.sub(r"\.(\d{3})", r"\1", raw)
        raw = raw.replace(" ", "")
        try:
            float(raw)
            return raw
        except ValueError:
            return "0.00"

    PAT_IMP = r"\$\s*([\d\.\s,]+)"  # captura el valor después del $

    d = {}
    # ── Tipo de comprobante ───────────────────────────────────────────────────
    # Código explícito (ej: "COD. 011", "COD 11", "Codigo N° 6")
    d["tipo_comprobante"] = buscar([
        r"COD\.\s*0*(\d{1,3})\b",
        r"\bCOD\s+0*(\d{1,3})\b",
        r"C[oó]digo\s*[:\.]?\s*0*(\d{1,3})\b",
        r"Codigo\s+N[°o\xba]\s*0*(\d{1,3})\b",
        # «Cód. N° 06» (EQUS FARMA, C&C Medical's), «COD.Nº001» (APREDIS),
        # «Cod.: 06» (FERTILAB), «Cod.: 011» (CAIPAC): con tilde, con «N°»
        # pegado o con dos puntos. «Cód. Artículo» o «COD.POSTAL» no entran:
        # tienen letras antes del número.
        r"\bC[o\xf3]d(?:igo)?\.?\s*(?:N[°o\xba\xb0]\.?)?\s*:?\s*0*(\d{1,3})\b",
        # «Código» y el número solo en su renglón, uno o dos más abajo
        # (Instituto CREAR).
        r"C[o\xf3]digo[ \t]*\n(?:[^\n]*\n)?[ \t]*0*(\d{1,3})[ \t]*$",
    ], texto)

    # ── Punto de venta y número ───────────────────────────────────────────────
    m_pv = re.search(r"Punto de Venta[:\s]+(\d+)", texto, re.IGNORECASE)
    # «Comp. Nro:» y «Comp. Nº:» (VISITAR).
    m_nu = re.search(r"Comp[\. ]+N(?:ro|[\xba\xb0°º])[\. :]*(\d+)", texto, re.IGNORECASE)
    if m_pv and not m_nu:
        # «Punto de Venta: 00003 Nro:00001526» (Cámara Argentina de
        # Desarrolladores de Software): el número rotulado «Nro» a secas,
        # pegado al punto de venta. Se exige que venga a continuación para no
        # tomar el «Nro» de cualquier otra parte del papel.
        m_nu = re.search(r"Punto de Venta[:\s]+\d+\s+N(?:ro|[\xba\xb0°º])\.?\s*:?\s*(\d+)",
                         texto, re.IGNORECASE)
    if m_pv and m_nu:
        d["punto_de_venta"] = m_pv.group(1).zfill(5)
        d["numero"]         = m_nu.group(1).zfill(8)
    else:
        # Formato "Comprobante Nº : 00003-00006435" / "Comprobante N°: 0003-00001542"
        #
        # Tambien "Factura N°: 00109-00343468", que es como lo escribe OSPOCE.
        # El rotulo cambia con el tipo de comprobante ---Factura, Nota de
        # Credito, Recibo--- y lo que importa es lo que viene despues, asi que
        # se aceptan todos en vez de agregar un patron por cada emisor.
        #
        # El «N°» puede faltar: «FACTURA: 0012-00000523» (CAIPAC), «Factura:
        # 0004-00022185» (CREAR). Sin él se pide el número de ocho dígitos,
        # para no tomar otra cosa con guión.
        m_cbte = re.search(
            r"(?:Comp(?:\.|robante)?|Factura|Nota\s+de\s+(?:Cr[e\xe9]dito|D[e\xe9]bito)|Recibo)"
            r"\s*N[\xba\xb0o°º]\s*[:\.]?\s*(\d{1,5})\s*-\s*(\d+)",
            texto, re.IGNORECASE,
        ) or re.search(
            r"(?:Factura|Comprobante|Nota\s+de\s+(?:Cr[e\xe9]dito|D[e\xe9]bito)|Recibo)"
            r"\s*:\s*(\d{4,5})\s*-\s*(\d{8})\b",
            texto, re.IGNORECASE,
        )
        if m_cbte:
            d["punto_de_venta"] = m_cbte.group(1).zfill(5)
            d["numero"]         = m_cbte.group(2).zfill(8)
        else:
            # Formato impresora fiscal: "N° 0002-00001542"
            # También «N°: 0004-00005281» (DIAGNOSTICO Y TRATAMIENTO), «Nº0002
            # - 00021518» (30712042946) y «N° B00006-00013193» (ORTOPEDIA RP):
            # dos puntos, sin espacio, espacios en el guión, la letra pegada.
            m_fiscal = (re.search(r"N[\xba\xb0o°º]\s+(\d+)-(\d+)", texto, re.IGNORECASE)
                        or re.search(r"(?<![A-Za-z])N[\xba\xb0°º]\s*[:\.]?\s*[ABCEM]?\s*-?\s*"
                                     r"(\d{4,5})\s*-\s*(\d{6,8})\b", texto))
            # «Nro.: A00003-00002620» (APREDIS) o «Número: B-00003-00002315»:
            # rótulo «Nro»/«Número» y la letra del comprobante pegada al punto
            # de venta.
            m_nro = (None if m_fiscal else re.search(
                r"\bN(?:ro|[u\xfa]mero)\.?\s*:?\s*[ABCEM]?\s*-?\s*(\d{4,5})\s*-\s*(\d{6,8})\b",
                texto, re.IGNORECASE))
            if m_fiscal:
                d["punto_de_venta"] = m_fiscal.group(1).zfill(5)
                d["numero"]         = m_fiscal.group(2).zfill(8)
            elif m_nro:
                d["punto_de_venta"] = m_nro.group(1).zfill(5)
                d["numero"]         = m_nro.group(2).zfill(8)
            else:
                # «0003-00026462» solo en su renglón, sin rótulo: Instituto
                # del Niño imprime «ORIGINAL FACTURA», la letra abajo y el
                # número abajo de la letra. Ocho dígitos después del guión,
                # para no confundirlo con un teléfono «4265-4313».
                #
                # Hasta dos ceros de más adelante: el Hospital Posadas
                # imprime «0006 - 0000026728», diez dígitos. ARCA numera con
                # ocho como máximo, así que lo que sobra son ceros de relleno
                # y no otro número.
                m_solo = re.search(r"^\s*[ABCEM]?\s*-?\s*(\d{4,5})\s*-\s*0{0,2}(\d{8})\s*$",
                                   texto, re.MULTILINE)
                # Último recurso: punto de venta y número de ocho dígitos en
                # cualquier lugar del ENCABEZADO (los primeros quince
                # renglones): «Cód. N° 06 0004-00081920» (C&C Medical's).
                # Más abajo puede haber remitos con la misma forma.
                m_enc = None if m_solo else re.search(
                    r"(?<![\d\-])(\d{4,5})\s*-\s*0{0,2}(\d{8})(?![\d\-])",
                    "\n".join(texto.splitlines()[:15]))
                if m_solo or m_enc:
                    _m = m_solo or m_enc
                    d["punto_de_venta"] = _m.group(1).zfill(5)
                    d["numero"]         = _m.group(2).zfill(8)
                else:
                    d["punto_de_venta"] = ""
                    d["numero"]         = ""

    # ── Fecha emisión ─────────────────────────────────────────────────────────
    d["fecha_emision"]  = buscar([
        r"Fecha de Emisi[o\xf3]n[:\s]+(\d{1,2}/\d{1,2}/\d{4})",
        # «Fecha Emisión : 02-11-2026»: sin «de», espacio antes de los dos
        # puntos y con guiones (facturagratis.com.ar, BARGADOS). Los guiones
        # pasan a barras más abajo.
        r"Fecha\s+(?:de\s+)?Emisi[o\xf3]n\s*:?\s*(\d{1,2}-\d{1,2}-\d{4})",
        r"Fecha\s+(\d{2}/\d{2}/\d{4})",
        # «Fecha: 01/10/2026» con dos puntos y sin «de Emisión»: así la
        # escriben los talonarios propios (LIPARINI, RONGO). «Fecha de
        # Vencimiento:» y «Fecha Inicio Actividades:» no entran: llevan
        # palabras entre «Fecha» y los dos puntos.
        # Con día o mes de un dígito, «Fecha: 8/10/2026» (CENTRO CARI): se
        # completa a dos más abajo.
        r"\bFecha\s*:\s*(\d{1,2}/\d{1,2}/\d{4})",
        # Lugar y fecha, solos en su renglón: «Buenos Aires, 08/10/2026»
        # (APREDIS).
        r"^\s*[A-Za-z\xc0-\xff][A-Za-z\xc0-\xff\.\s]{2,40},\s*(\d{1,2}/\d{1,2}/\d{4})\s*$",
        # Sin rotulo, sola en su renglon: asi la escribe OSPOCE, debajo del
        # numero de factura. Va ULTIMA a proposito. En ese PDF hay otras cinco
        # fechas ---el periodo desde y hasta, el vencimiento del pago y el del
        # CAE--- pero todas llevan etiqueta y las agarran los patrones de
        # arriba o los suyos. Una fecha sola en su renglon es la de emision.
        r"^\s*(\d{2}/\d{2}/\d{4})\s*$",
    ], texto)
    d["fecha_vto_pago"] = buscar([
        r"Fecha de Vto\.\s+para el pago[:\s]+(\d{2}/\d{2}/\d{4})",
        r"FECHA\s+VENCIMIENTO\s+DEL\s+PAGO[:\s]+(\d{2}/\d{2}/\d{4})",
        # «Fecha Vto Pago : 02/11/2026» (facturagratis).
        r"Fecha\s+Vto\.?\s+(?:de\s+|para\s+el\s+)?Pago\s*:?\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})",
    ], texto)

    # ── CUITs — quitar guiones ────────────────────────────────────────────────
    # La etiqueta, con los puntos que cada emisor ponga o se olvide:
    #   «C.U.I.T.: 30-71549745-6» y «C.U.I.T: 30519651145»  (FACOEP)
    #   «C.UI.T.: 30-71622997-8»                              (30716229978)
    #   «CUIT.30-71050937-5», punto en vez de dos puntos      (30710509375)
    # Cuando el del emisor no se reconocía, el único rotulado era el nuestro
    # y quedaba la OS como emisor. «C.U.I.L.» no entra: termina en L.
    _cuits_raw = re.findall(r"(?<![A-Z])C\.?U\.?I\.?T\.?[:\s\.]*([\d\-]+)", texto, re.IGNORECASE)
    _cuits = [c.replace("-", "").replace(" ", "") for c in _cuits_raw]
    _cuits = [c for c in _cuits if len(c) == 11 and c.isdigit()]
    # Sin repetir y en orden. Un PDF con ORIGINAL y DUPLICADO trae todo dos
    # veces, y el segundo CUIT de la lista era otra vez el del emisor: quedaba
    # como receptor, no coincidía con el de la OS y la carga descartaba todo
    # lo leído (FACOEP, NC A 0001-00020024).
    _cuits = list(dict.fromkeys(_cuits))
    d["cuit_emisor"]   = _cuits[0] if len(_cuits) > 0 else ""
    d["cuit_receptor"] = _cuits[1] if len(_cuits) > 1 else ""

    # ── Los CUIT que están en el texto SIN la etiqueta «CUIT» ─────────────────
    #
    # El de arriba pide la etiqueta, y hay emisores que no la ponen. La factura
    # de OSPOCE es asi: el CUIT del receptor sale pegado a la condicion frente
    # al IVA ---«EXENTO 30-51965114-5»--- y el unico rotulado es el del emisor,
    # y encima en el bloque de datos bancarios del pie.
    #
    # El efecto no era cosmetico. Sin receptor, la carga manda a ARCA el
    # comprobante sin tipo ni numero de documento del receptor, y ARCA lo
    # RECHAZA con los avisos 115 y 116 ---«el comprobante es de mas de
    # 10.000.000, por lo que se debe informar ... del receptor»---. Justo las
    # facturas grandes, que son las que importan.
    #
    # Se guardan todos los que aparecen, en orden y sin repetir. Quien decide
    # cual es el receptor es el que llama: el unico receptor posible de un
    # comprobante que entra por acá es la obra social, asi que alcanza con
    # preguntar si el CUIT de la OS esta en la lista. Elegir acá seria adivinar;
    # allá es una comprobacion.
    _sueltos = re.findall(r"(?<!\d)(\d{2}-?\d{8}-?\d)(?!\d)", texto)
    _vistos, d["cuits_en_el_texto"] = set(), []
    for c in _sueltos:
        c = c.replace("-", "")
        if len(c) == 11 and c.isdigit() and c not in _vistos:
            _vistos.add(c)
            d["cuits_en_el_texto"].append(c)

    # ── Razón social ─────────────────────────────────────────────────────────
    d["razon_social_emisor"]   = ""
    d["razon_social_receptor"] = ""

    # Estrategia 1: pares directos "CUIT X - Razón Social Y" en la misma línea
    _pairs = re.findall(
        r"CUIT\s*[:\s]+([\d\-]{10,13})\s*[-–]\s*Raz[o\xf3]n\s+Social\s*[:\s]+([^\n]+)",
        texto, re.IGNORECASE,
    )
    _cuit_to_rs = {}
    for _c, _r in _pairs:
        _cc = _c.replace("-", "").replace(" ", "")
        _cuit_to_rs[_cc] = _r.strip().replace("\n", " ")

    if d["cuit_emisor"] and _cuit_to_rs.get(d["cuit_emisor"]):
        d["razon_social_emisor"] = _cuit_to_rs[d["cuit_emisor"]]
    if d["cuit_receptor"] and _cuit_to_rs.get(d["cuit_receptor"]):
        d["razon_social_receptor"] = _cuit_to_rs[d["cuit_receptor"]]

    # Estrategia 2: etiquetas "Razón Social" sueltas — las asignamos a lo que falte
    _pat_rs = r"Raz[o\xf3]n Social[:\s]+(.+?)(?=\n(?:CUIT|Domicilio|Condici[o\xf3]n|\s*$))"
    _razones_sueltas = []
    for _m in re.finditer(_pat_rs, texto, re.IGNORECASE | re.DOTALL):
        _v = _m.group(1).strip().replace("\n", " ").replace("  ", " ")
        if _v and _v not in _cuit_to_rs.values():
            _razones_sueltas.append(_v)

    # Si tenemos 2 razones sueltas y ningún mapeo por CUIT, orden tradicional: emisor=1º, receptor=2º
    if not _cuit_to_rs and len(_razones_sueltas) >= 2:
        if not d["razon_social_emisor"]:
            d["razon_social_emisor"] = _razones_sueltas[0]
        if not d["razon_social_receptor"]:
            d["razon_social_receptor"] = _razones_sueltas[1]
    else:
        # Rellenar sólo lo que falte
        if not d["razon_social_receptor"] and _razones_sueltas:
            d["razon_social_receptor"] = _razones_sueltas.pop(0)
        if not d["razon_social_emisor"] and _razones_sueltas:
            d["razon_social_emisor"] = _razones_sueltas.pop(0)

    # Estrategia 3: para el emisor cuando va en el encabezado sin etiqueta
    # (ej. "ESCUELA ESPECIAL MARIA MONTESSORI SRL Comprobante Nº : 0003-00006435")
    if not d["razon_social_emisor"]:
        _lineas = [l.strip() for l in texto.split("\n") if l.strip()]
        _skip = {"ORIGINAL", "DUPLICADO", "TRIPLICADO", "FACTURA",
                 "NOTA DE CREDITO", "NOTA DE DEBITO", "RECIBO"}
        for _lin in _lineas:
            # Llegar al CUIT o al número solo en su renglón («0003-00026462»)
            # es haber pasado el nombre: en el encabezado va antes. Si no
            # apareció es que es un logo (Instituto del Niño, Cirugía
            # Alemana), y lo que sigue es domicilio, teléfono, ingresos
            # brutos o el nombre del cliente: mejor vacío, que la carga
            # completa con el del proveedor o el de Mis Comprobantes.
            # «00003 00001320», con espacio y sin guión (Fundación
            # Manantiales), también es el número: si no, quedaba de razón
            # social.
            if re.match(r"C\.?\s?U\.?\s?I\.?\s?T\b"
                        r"|[ABCEM]?\s*-?\s*\d{4,5}\s*-\s*\d{6,8}\s*$"
                        r"|\d{4,5}\s+\d{8}\s*$",
                        _lin, re.IGNORECASE):
                break
            # «B FACTURA» (letra delante) y «Código 006» (con tilde) también son
            # encabezado: CENTRO CARI salía con razón social «B FACTURA».
            # «ORIGINAL FACTURA» también: así arranca Instituto del Niño.
            if _lin.upper() in _skip or re.match(
                r"^(Factura|COD[\.\s]|C[o\xf3]digo\b|N[°\xba\xb0o]|Nro\b|N[u\xfa]mero\b|Fecha|IVA|Domicilio|Condici"
                r"|(?:ORIGINAL|DUPLICADO|TRIPLICADO)\b"
                r"|[ABCEM]\s+(?:FACTURA|NOTA\s+DE|RECIBO)\b"
                r"|[ABCEM]\s+N(?:[u\xfa]mero|ro\b|[°\xba\xb0])"
                r"|.*\d{1,2}/\d{1,2}/\d{4}\s*$)",
                _lin, re.IGNORECASE,
            ):
                continue
            if len(_lin) > 5 and not _lin.isdigit():
                # Puede venir pegado con "Comprobante Nº ..." al final — lo recortamos
                _lin = re.split(
                    r"\s+Comp(?:\.|robante)?\s+N[\xba\xb0o°º]",
                    _lin, maxsplit=1, flags=re.IGNORECASE,
                )[0].strip()
                # «de BARGADOS LUIS RICARDO CUIT : 20209761891»
                # (facturagratis): el CUIT en el mismo renglón y un «de»
                # adelante, en minúscula, que no es parte del nombre.
                _lin = re.split(r"\s+C\.?U\.?I\.?T\.?\b", _lin, maxsplit=1)[0].strip()
                _lin = re.sub(r"^de\s+(?=[A-Z\xc0-\xdd])", "", _lin)
                # Y la letra del comprobante pegada al final, que el PDF
                # imprime en el recuadro de al lado: «RONGO, Alejandro Fabián C».
                _lin = re.sub(r"\s+[ABCEM]$", "", _lin)
                if len(_lin) > 5:
                    d["razon_social_emisor"] = _lin
                    break

    # Estrategia 4: receptor vía "SRES:" (impresoras fiscales)
    if not d["razon_social_receptor"]:
        _m_sres = re.search(r"SRES[:\s]+(.+?)(?:\s{2,}|COD\.)", texto, re.IGNORECASE)
        if _m_sres:
            d["razon_social_receptor"] = _m_sres.group(1).strip()
    # Condición IVA: busca ocurrencias de las descripciones de arca_responsable_tipo
    if condiciones_iva:
        _cond_encontradas = []
        for desc in condiciones_iva:
            for m in re.finditer(re.escape(desc), texto, re.IGNORECASE):
                _cond_encontradas.append((m.start(), desc))
        # La condición escrita corta, con su rótulo: «Condición IVA: Exento»
        # (Cámara Argentina de Desarrolladores de Software). Ninguna
        # descripción de ARCA está escrita entera, así que se busca el rótulo
        # y se traduce a la descripción. Sólo cuando las descripciones no
        # encontraron nada: mezclar los dos caminos podría cruzar emisor y
        # receptor.
        if not _cond_encontradas:
            _cortas = {"exento": "IVA Sujeto Exento",
                       "responsable inscripto": "IVA Responsable Inscripto",
                       "monotributo": "Responsable Monotributo",
                       "monotributista": "Responsable Monotributo",
                       "consumidor final": "Consumidor Final",
                       "no alcanzado": "IVA No Alcanzado"}
            for m in re.finditer(r"Condici[o\xf3]n (?:frente al )?IVA\s*:\s*([A-Za-z\xc0-\xff ]+)",
                                 texto, re.IGNORECASE):
                _v = m.group(1).strip().lower()
                for _k, _desc in _cortas.items():
                    if _v.startswith(_k) and _desc in condiciones_iva:
                        _cond_encontradas.append((m.start(), _desc))
                        break
        _cond_encontradas.sort(key=lambda x: x[0])
        d["condicion_iva_emisor"]   = _cond_encontradas[0][1] if len(_cond_encontradas) > 0 else ""
        d["condicion_iva_receptor"] = _cond_encontradas[1][1] if len(_cond_encontradas) > 1 else ""
    else:
        _cond = re.findall(r"Condici[o\xf3]n frente al IVA[:\s]+(.+?)(?:\n)", texto, re.IGNORECASE)
        d["condicion_iva_emisor"]   = _cond[0].strip() if len(_cond) > 0 else ""
        d["condicion_iva_receptor"] = _cond[1].strip() if len(_cond) > 1 else ""

    # Importes — formato: "Etiqueta: $ 246000,21"
    d["importe_neto_gravado"] = importe([
        r"Importe Neto Gravado\s*:\s*\$\s*([\d\.,]+)",
        r"Neto Gravado\s*:\s*\$\s*([\d\.,]+)",
        r"Subtotal:\s*\$\s*([\d\.,]+)",
    ], texto)
    d["importe_neto_no_grav"] = importe([
        r"Importe Neto No Gravado\s*:\s*\$\s*([\d\.,]+)",
        r"Neto No Gravado\s*:\s*\$\s*([\d\.,]+)",
    ], texto)
    d["importe_exento"] = importe([
        r"Importe Exento\s*:\s*\$\s*([\d\.,]+)",
    ], texto)
    d["importe_iva"] = importe([
        r"Impuesto IVA:\s*\$\s*([\d\.,]+)",
        r"IVA\s+\d+\s*%:\s*\$\s*([\d\.,]+)",
        r"(?:Impuesto\s+)?IVA[:\s]+\$\s*([\d\.,]+)",
    ], texto)
    d["importe_otros"] = importe([
        r"Importe Otros Tributos\s*:\s*\$\s*([\d\.,]+)",
        r"Otros Tributos\s*:\s*\$\s*([\d\.,]+)",
        r"Otros Impuestos\s*:\s*\$\s*([\d\.,]+)",
    ], texto)
    d["importe_total"] = importe([
        r"Importe Total\s*:\s*\$\s*([\d\.,]+)",
        r"Importe\s+TOTAL\s*\$\s*[:\s]+\s*([\d\.,]+)",
        r"^Total\s+([\d\.]+,[\d]{2})$",
        # «PRECIO TOTAL: $ 48.000» no: es el precio de lista que el papel
        # escribe en el renglón (ORTOPEDIA RP, cobertura del 50%); el total de
        # la factura va al pie, «TOTAL 24,000.00».
        r"(?<!PRECIO )Total:\s*\$\s*([\d\.,]+)",
        r"^Total\s+([\d\.,]+)",
        r"(?<!PRECIO )\bTOTAL\s+(\d[\d\.,]*[\.,]\d{2})[ \t]*$",
        # «TOTAL A PAGAR: 770043.58», sin $ y con punto decimal (APREDIS).
        r"\bTOTAL\s+A\s+PAGAR\s*:?\s*\$?\s*([\d\.,]+)",
        # «Importe Total 250,757.78» (VISITAR) e «Importe Total : 967.840,47 $»
        # (FERTILAB): sin $ adelante, o con el $ atrás.
        r"Importe\s+Total\s*:?\s*\$?\s*(\d[\d\.,]*\d)",
        # «Total: 46,011.50» sin $ (EQUS FARMA, C&C Medical's). «Subtotal:» no
        # entra: no hay borde de palabra entre «Sub» y «total».
        r"\bTotal\s*:\s*\$?\s*(\d[\d\.,]*\d)",
        # EL ULTIMO importe del documento. Ultimo recurso, y por eso va ultimo:
        # sólo se llega acá cuando el PDF no dice «Total» en ninguna parte, que
        # es el caso de la factura de OSPOCE.
        #
        # Ahi el total esta escrito dos veces ---en el renglon del concepto y
        # otra vez al final del importe en letras--- y despues no viene ningun
        # otro importe: el renglon del CAE no lleva `$`. Se toma el ultimo y no
        # el del concepto porque una factura con varios conceptos tiene varios
        # renglones y uno solo cierra.
        #
        # No se lo puede atar a la palabra «centavos»: en la 343468 el numero
        # cae despues de «centavos.-» y en la 343467, dos renglones antes, sobre
        # el que empieza con «Pesos». El corte de linea del importe en letras lo
        # decide el largo del texto, no el formato.
        r"\$\s*([\d\.,]+)(?![\s\S]*\$\s*[\d])",
    ], texto)
    # Sin rótulo de total: la fila de importes justo antes del importe en
    # letras («Son Pesos: …», «Pesos: …»). El total es el último de la fila
    # (30712042946: «652,958.24 652,958.24 652,958.24»; Instituto Un Lugar:
    # «652,958.24» solo).
    if not float(d["importe_total"] or 0):
        _m_fila = re.search(r"^[ \t]*((?:\d[\d\.,]*\d[ \t]+)*(\d[\d\.,]*[\.,]\d{2}))[ \t]*\n"
                            r"[ \t]*(?:Son[ \t]+)?Pesos\b", texto, re.IGNORECASE | re.MULTILINE)
        if _m_fila:
            d["importe_total"] = importe([r"(.+)"], _m_fila.group(2))

    # dni_afiliado: se resuelve al guardar buscando los documentos
    # de los afiliados vinculados al prestador en sus legajos
    d["dni_afiliado"]     = ""
    d["_candidatos_dni"]  = ""

    # Período facturado desde / hasta
    _RANGO = (r"Per[ií]odo[^\d\n]{0,40}?(\d{2}/\d{2}/\d{4})"
              r"\s*(?:-|–|al|a|hasta:?)\s*(\d{2}/\d{2}/\d{4})")
    d["periodo_desde"] = buscar([
        r"Per[ií]odo\s+Facturado\s*[:\-]?\s*Desde[:\s]+(\d{2}/\d{2}/\d{4})",
        r"Per[ií]odo\s*[:\-]?\s*Desde[:\s]+(\d{2}/\d{2}/\d{4})",
        # El rango sin «Desde» ni «Hasta»: «Período: 01/09/2026 - 30/09/2026»,
        # «Período facturado del 01/09/2026 al 30/09/2026». Va antes del
        # «Desde» suelto, que en una factura así no existe y si aparece es
        # otra cosa. Sin esto el correo tomaba el mes de emisión (LIPARINI
        # 4-19175: emitida el 01/10 por septiembre quedó en 202610).
        _RANGO,
        r"PERIODO\s+desde\s+(\d{2}/\d{2}/\d{4})",
        r"Desde[:\s]+(\d{2}/\d{2}/\d{4})",
    ], texto)
    d["periodo_hasta"] = buscar([
        r"Per[ií]odo\s+Facturado\s*[:\-]?\s*Hasta[:\s]+(\d{2}/\d{2}/\d{4})",
        r"Per[ií]odo\s*[:\-]?\s*Hasta[:\s]+(\d{2}/\d{2}/\d{4})",
        r"hasta\s+(\d{2}/\d{2}/\d{4})",
        r"Hasta[:\s]+(\d{2}/\d{2}/\d{4})",
    ], texto)
    # Si el «desde» salió del rango sin rótulos, el «hasta» es la otra
    # punta de ese rango y no el primer «hasta» suelto del papel, que
    # puede ser el de otra cosa («válido hasta …»).
    _m_rango = re.search(_RANGO, texto, re.IGNORECASE | re.MULTILINE)
    if _m_rango and _m_rango.group(1) == d["periodo_desde"]:
        d["periodo_hasta"] = _m_rango.group(2)

    # Formato abreviado "Período : Marzo/2026" / "PERIODO: Marzo 2026"
    if not d["periodo_desde"]:
        _MESES = {
            "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
            "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
            "septiembre": 9, "setiembre": 9, "octubre": 10,
            "noviembre": 11, "diciembre": 12,
            "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
            "jul": 7, "ago": 8, "sep": 9, "sept": 9, "set": 9, "oct": 10,
            "nov": 11, "dic": 12,
        }
        # Entre «Período» y el mes puede venir «Facturado» o «de prestación»:
        # «PERÍODO FACTURADO: Septiembre 2026» (RONGO). Antes se exigía el mes
        # pegado a «Período», el patrón tomaba «FACTURADO» como mes y el
        # correo terminaba usando el de emisión.
        _m_per = re.search(
            r"Per[ií]odo(?:\s+(?:facturado|de\s+prestaci[oó]n|de\s+servicios?))?"
            r"\s*[:\-]?\s*([A-Za-z\xe1\xe9\xed\xf3\xfa\xc1\xc9\xcd\xd3\xdañÑ]+)\.?"
            r"\s*(?:del?\s+)?[/\-]?\s*(\d{4})(?!\d)",
            texto, re.IGNORECASE,
        )
        if _m_per:
            _mes_raw = _m_per.group(1).lower()
            _mes_raw = _mes_raw.translate(str.maketrans("áéíóú", "aeiou"))
            # Si no es un mes escrito bien, las tres primeras letras: así
            # entra «SEPTIEMRE 2026» (30712042946 2-22736). Ninguna otra
            # palabra que vaya después de «Período» empieza como un mes.
            _mes_num = _MESES.get(_mes_raw) or (
                _MESES.get(_mes_raw[:3]) if len(_mes_raw) >= 4 else None)
            if _mes_num:
                import calendar as _cal
                _anio = int(_m_per.group(2))
                _ult = _cal.monthrange(_anio, _mes_num)[1]
                d["periodo_desde"] = f"01/{_mes_num:02d}/{_anio}"
                if not d.get("periodo_hasta"):
                    d["periodo_hasta"] = f"{_ult:02d}/{_mes_num:02d}/{_anio}"

    # Último recurso: el mes escrito en la descripción del ítem.
    #
    # Los dos intentos de arriba exigen la palabra «Período», que es un campo
    # del formato AFIP que una parte de los prestadores deja vacío: facturan un
    # servicio mensual y el mes queda sólo en el renglón del detalle —«Apoyo a
    # la integración escolar - AGOSTO 2026»—.
    #
    # En Integración eso no es un dato más: el período decide contra qué legajo
    # y contra qué precio se compara el comprobante, y con qué presentación
    # viaja. Sin él no se arma el renglón del DS y el comprobante no se puede
    # presentar, cosa que se descubre cuando ya está cargado.
    #
    # Queda marcado en `_periodo_origen` para que la pantalla pueda decir que
    # ese período se dedujo y conviene mirarlo. Es lo único editable del
    # comprobante cuando ARCA lo validó, así que corregirlo no cuesta nada.
    if not d["periodo_desde"]:
        try:
            from lector_pdf_ocr import periodo_del_texto
            _per_txt, _per_donde = periodo_del_texto(texto, d.get("fecha_emision", ""))
        except Exception:
            _per_txt, _per_donde = "", ""
        if _per_txt:
            import calendar as _cal2
            _a2, _m2 = int(_per_txt[:4]), int(_per_txt[4:])
            d["periodo_desde"]   = f"01/{_m2:02d}/{_a2}"
            d["periodo_hasta"]   = f"{_cal2.monthrange(_a2, _m2)[1]:02d}/{_m2:02d}/{_a2}"
            d["_periodo_origen"] = _per_donde

    # La columna es el código de ARCA, de 3 letras (en la base, todo PES). El PDF
    # puede decir la palabra: «Moneda: Peso» (CENTRO CARI) llegaba tal cual y
    # el guardado fallaba por largo. Lo que no se reconoce queda en PES.
    _mon = (buscar([r"Moneda[:\s]+([^\s\d:]+)"], texto) or "").upper().strip(".")
    if not _mon or _mon.startswith("PES") or _mon in ("ARS", "$"):
        d["moneda"] = "PES"
    elif _mon.startswith(("DOL", "D\xd3L")) or _mon in ("USD", "U$S", "US$"):
        d["moneda"] = "DOL"
    elif _mon.startswith("EUR"):
        d["moneda"] = "060"
    elif len(_mon) == 3 and _mon.isalnum():
        d["moneda"] = _mon
    else:
        d["moneda"] = "PES"
    d["tipo_de_cambio"] = buscar([r"Tipo de Cambio[:\s]+([\d\.,]+)"], texto) or "1.0000"
    d["cae"]            = buscar([
        r"CAE\s*N[\xb0o\xba\.][:\s]*([\d]+)",
        # «CAE Nro : 86440562276651» (facturagratis).
        r"\bCAE\s*Nro\.?\s*:?\s*(\d{14})\b",
        # Catorce dígitos: el CAE siempre los tiene. Con «[\d]+» suelto,
        # «Fecha Vto CAE : 12-11-2026» daba CAE «12».
        r"\bCAE\b[:\s]+(\d{14})\b",
        # «CAE informado: 86405619984781» y cualquier rótulo corto entre
        # «CAE» y el número, siempre que sean los catorce dígitos.
        r"\bCAE\b[^\d\n]{0,20}(\d{14})\b",
        # Con puntos: «C.A.E : 86416752260921» (APREDIS), «C.A.E.: …».
        r"\bC\.A\.E\.?\s*(?:N[\xb0o\xba]\.?\s*)?[:\s]+(\d{14})\b",
    ], texto)
    d["fecha_vto_cae"]  = buscar([
        r"Fecha de Vto\.\s+de CAE[:\s]+(\d{1,2}/\d{1,2}/\d{4})",
        # «Fecha Vto CAE : 12-11-2026» (facturagratis), con guiones.
        r"Fecha\s+(?:de\s+)?Vto\.?\s+(?:del?\s+)?CAE\s*:?\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})",
        r"Vencimiento\s+CAE[:\s]+(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})",
        # «CAE: 86416790084187» y abajo «Vencimiento: 18/10/2026» (CENTRO
        # CARI). Pegado al CAE para no confundirlo con el vencimiento del pago.
        # También «C.A.E : … Fecha Vto : 18/10/2026» (APREDIS).
        r"\bC\.?A\.?E\.?\s*(?:N[\xb0\xbao\.]\s*)?[:\s]*\d{14}\s*(?:Fecha\s+(?:de\s+)?)?"
        r"(?:Vencimiento|Vto\.?)\s*[:\s]+(\d{1,2}/\d{1,2}/\d{4})",
        # «C.A.E. 86261583348173 Página 1 de 1» y en el renglón de abajo
        # «Fecha vto 8/7/2026» (Hospital Posadas). Sólo el renglón que sigue
        # al del CAE: más lejos puede ser el vencimiento del pago.
        r"\bC\.?A\.?E\.?\s*[:\s]*\d{14}[^\n]*\n\s*Fecha\s+(?:de\s+)?Vto\.?\s*:?\s*"
        r"(\d{1,2}/\d{1,2}/\d{4})",
    ], texto)
    # El resto del sistema espera dd/mm/aaaa: «8/10/2026» pasa a «08/10/2026»
    # y «02-11-2026» a «02/11/2026».
    for _k in ("fecha_emision", "fecha_vto_cae", "fecha_vto_pago"):
        _m = re.fullmatch(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", d.get(_k) or "")
        if _m:
            d[_k] = f"{int(_m.group(1)):02d}/{int(_m.group(2)):02d}/{_m.group(3)}"

    # Formato alternativo: "CAE <nro> - Vto. YYYYMMDD"
    if not d["fecha_vto_cae"]:
        _m_vto = re.search(
            r"CAE\s+\d+\s*[-–]?\s*Vto\.\s+(\d{4})(\d{2})(\d{2})",
            texto, re.IGNORECASE,
        )
        if _m_vto:
            d["fecha_vto_cae"] = f"{_m_vto.group(3)}/{_m_vto.group(2)}/{_m_vto.group(1)}"

    _plantilla_sin_rotulos(texto, d, condiciones_iva)

    # ── Inferencia de tipo_comprobante si no apareció como texto ──────────────
    # (muchas facturas electrónicas tienen la letra A/B/C y "COD XX" como imagen/gráfico,
    # por lo que pdfplumber no los ve)
    if not d["tipo_comprobante"]:
        _tt = texto.upper()
        # Tipo de documento
        if re.search(r"\bNOTA\s+DE\s+CR[EÉ]DITO\b", _tt):
            _doc = "NC"
        elif re.search(r"\bNOTA\s+DE\s+D[EÉ]BITO\b", _tt):
            _doc = "ND"
        elif re.search(r"\bRECIBO\b", _tt):
            _doc = "REC"
        elif re.search(r"\bFACTURA\b", _tt):
            _doc = "FC"
        else:
            _doc = None

        # Clase (A/B/C): se detecta leyendo directo del texto del PDF, sin depender
        # del matching contra arca_responsable_tipo (cuyas descripciones no
        # siempre coinciden con la grafía del PDF)
        def _clase_desde_cond(cond_txt):
            cond_txt = (cond_txt or "").upper()
            if "RESPONSABLE INSCRIPTO" in cond_txt or "RESP. INSCRIPTO" in cond_txt \
                    or "RESP.INSCRIPTO" in cond_txt or "IVA INSCRIPTO" in cond_txt:
                return "RI"
            if "EXENTO" in cond_txt:
                return "EX"
            if "MONOTRIBUT" in cond_txt:
                return "MT"
            if "CONSUMIDOR FINAL" in cond_txt or "CONS. FINAL" in cond_txt:
                return "CF"
            return None

        # Extraer las dos primeras ocurrencias de "Condición ... IVA: <X>" del texto
        _cond_matches = re.findall(
            r"Condici[o\xf3]n\s+(?:[Ff]rente\s+al\s+)?I\.?\s*V\.?\s*A\.?\s*[:\s]+([^\n\-\r]+)",
            texto, re.IGNORECASE,
        )
        _c_em = _clase_desde_cond(_cond_matches[0]) if len(_cond_matches) > 0 else None
        _c_re = _clase_desde_cond(_cond_matches[1]) if len(_cond_matches) > 1 else None

        # Como respaldo, usar lo extraído por la ruta de arca_responsable_tipo si ya vino
        if not _c_em:
            _c_em = _clase_desde_cond(d.get("condicion_iva_emisor"))
        if not _c_re:
            _c_re = _clase_desde_cond(d.get("condicion_iva_receptor"))

        if _c_em == "RI":
            # Si el receptor también es RI → A; si no → B
            _clase = "A" if _c_re == "RI" else "B"
        elif _c_em in ("EX", "MT"):
            _clase = "C"
        else:
            _clase = None

        # La letra IMPRESA, si está, manda: es lo que dice el comprobante, y
        # la deducción por la condición de IVA se equivoca cuando el papel
        # escribe mal la del receptor (APREDIS pone «Responsable inscripto» a
        # la obra social, que es exenta). Se busca en el encabezado:
        #   «B» sola en su renglón             (DIAGNOSTICO, CADAQUES, CEDICAS)
        #   «… B FACTURA» o «C FACTURA»        (EQUS FARMA, 30712042946)
        #   el primer renglón terminado en la letra  (RONGO)
        _enc = texto.splitlines()[:15]
        _letra = None
        for _l in _enc:
            _m_l = (re.fullmatch(r"\s*([ABCM])\s*", _l)
                    # La letra en mayúscula siempre: «a FACTURA» en una frase no es una.
                    or re.search(r"(?:^|\s)([ABC])\s+(?i:FACTURA|NOTA\s+DE)\b", _l))
            if _m_l:
                _letra = _m_l.group(1).upper()
                break
        if not _letra and _enc and re.search(r"\S\s+([ABC])\s*$", _enc[0]) \
                and not re.search(r"\d\s+[ABC]\s*$", _enc[0]):
            _letra = re.search(r"\s([ABC])\s*$", _enc[0]).group(1)
        if _letra in ("A", "B", "C"):
            _clase = _letra

        _mapa = {
            ("FC", "A"): "01", ("FC", "B"): "06", ("FC", "C"): "11",
            ("NC", "A"): "03", ("NC", "B"): "08", ("NC", "C"): "13",
            ("ND", "A"): "02", ("ND", "B"): "07", ("ND", "C"): "12",
            ("REC", "A"): "04", ("REC", "B"): "09", ("REC", "C"): "15",
        }
        if _doc and _clase:
            d["tipo_comprobante"] = _mapa.get((_doc, _clase), "")

    return d

