"""
extractos_bancarios.py — Lectura e importación de extractos bancarios.

Copiado de `gestion_adm/extractos_bancarios.py` (los parsers y el control de
cuenta, sin cambios de lógica; sin la conciliación de Prisma, que es del débito
automático de la obra social). Los bancos del sindicato son los mismos: Nación
(cuenta corriente 2049118 y recaudadora) e ICBC (recaudadora).

  BNA   CSV ';' clásico (Fecha Mvto;Fecha Valor;Monto;Referencia;Concepto;Saldo)
        o de Banca Empresas (BEE_Reporte_*.csv: Cuenta;CUIT Cuenta;Fecha;Monto;…)
  ICBC  extracto de cuenta corriente (Fecha contable;…;Debito en $;Credito en $;Saldo en $)
        o reporte de recaudaciones (sin fecha en las filas: va en el nombre del archivo)

QUE CAMBIA RESPECTO DE GESTION_ADM
- El número de cuenta del archivo se compara también contra el CBU de la cuenta
  (la parte de la cuenta, del dígito 9 al 21): en Banca Empresas el BNA puede
  escribir la cuenta como sucursal + número, que no termina igual que el número
  cargado en el maestro pero sí está dentro del CBU.
- Un error al insertar un renglón se cuenta y se informa (antes se contaba y el
  motivo se perdía).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, date
from decimal import Decimal, InvalidOperation


# ── Helpers ───────────────────────────────────────────────────────────────────

log = logging.getLogger(__name__)


def _parse_monto_ar(s: str) -> Decimal | None:
    """
    Convierte importe en formato argentino a Decimal.
    Ejemplos: '8.000,00' → 8000.00 | '-1.044.540,00' → -1044540.00
    """
    s = (s or "").strip()
    if not s:
        return None
    try:
        return Decimal(s.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None


def _parse_fecha_ar(s: str) -> date | None:
    """DD/MM/YYYY → date"""
    s = (s or "").strip()
    try:
        return datetime.strptime(s, "%d/%m/%Y").date()
    except ValueError:
        return None


def _extraer_cuit(concepto: str) -> str | None:
    """
    Intenta extraer un CUIT/CUIL del campo concepto.
    BNA suele incluirlo como 11 dígitos dentro del texto.
    Ej: 'TRANSF. FAC 20222970866' → '20222970866'
    """
    m = re.search(r'\b(20|23|24|27|30|33|34)\d{9}\b', concepto or "")
    return m.group(0) if m else None


# ── Parser BNA ────────────────────────────────────────────────────────────────
#
# BNA exporta en dos formatos distintos y los dos siguen siendo BNA, así que
# comparten parser y sólo cambia de qué columna sale cada dato.
#
#   Clásico:         Fecha Mvto;Fecha Valor;Monto;Referencia;Concepto;Saldo
#   Banca Empresas:  Cuenta;CUIT Cuenta;Fecha;Monto;N° de Comprobante;
#                    Descripción;Saldo   ← archivos `BEE_Reporte_*.csv`
#
# En Banca Empresas `fechav` apunta a la misma columna que `fecham` porque el
# archivo trae una sola fecha. Y las dos primeras columnas —cuenta y CUIT del
# titular— no se mapean a propósito: ese CUIT es el de la cuenta propia, no el
# de la contraparte, y guardarlo como `cuit` marcaría todos los movimientos
# contra uno mismo y arruinaría la conciliación. El de la contraparte se sigue
# sacando del texto del concepto, como en el otro formato.

_COLS_BNA_CLASICO = {
    "fecham": 0, "fechav": 1, "monto": 2, "ref_nro": 3, "concepto": 4,
    "saldo": 5, "minimo": 5,
}

_COLS_BNA_EMPRESAS = {
    "fecham": 2, "fechav": 2, "monto": 3, "ref_nro": 4, "concepto": 5,
    "saldo": 6, "minimo": 6,
}


def _es_cabecera_bna_empresas(linea: str) -> bool:
    """
    ¿Es el encabezado del export de Banca Empresas?

    Se piden dos marcas y no una: `CUIT Cuenta` sola podría aparecer en otro
    reporte del mismo banco, y confundirse de formato no falla ruidosamente
    —falla leyendo el importe de la columna equivocada—, que es mucho peor.

    La comparación ignora acentos y mayúsculas porque el archivo llega en
    Latin-1 y, según quién lo abra y lo vuelva a guardar, `Descripción` puede
    venir con el acento roto.
    """
    l = linea.lower()
    return "cuit cuenta" in l and ("comprobante" in l and "monto" in l)

def parsear_bna(contenido: str) -> list[dict]:
    """
    Parsea el CSV de Banco Nación (Empresas).

    Formato:
      Fecha Mvto;Fecha Valor;Monto;Referencia;Concepto;Saldo
      01/09/2023;01/09/2023;8.000,00;0000000406107;TRANSF. VAR ...;
      ...
      (el Saldo solo aparece en el último renglón de cada día)

    Retorna lista de dicts listos para insertar en c_extractos_bancarios.
    """
    # Quitar BOM si existe
    contenido = contenido.lstrip("\ufeff")

    lineas = contenido.splitlines()
    if not lineas:
        return []

    # Saltar el encabezado, y de paso reconocer cuál de los dos formatos de BNA
    # es. La variante se elige por el ENCABEZADO y no por el nombre del
    # archivo: el nombre lo pone quien lo descarga y cambia, el encabezado lo
    # pone el banco.
    inicio, col = 0, _COLS_BNA_CLASICO
    for i, l in enumerate(lineas):
        if _es_cabecera_bna_empresas(l):
            inicio, col = i + 1, _COLS_BNA_EMPRESAS
            break
        if "Fecha Mvto" in l or "fecham" in l.lower():
            inicio = i + 1
            break

    resultados = []
    for linea in lineas[inicio:]:
        linea = linea.strip()
        if not linea:
            continue

        partes = linea.split(";")
        if len(partes) < col["minimo"]:
            continue

        def _campo(cual: str) -> str:
            i = col.get(cual)
            return partes[i] if i is not None and i < len(partes) else ""

        fecham  = _parse_fecha_ar(_campo("fecham"))
        # En Banca Empresas hay una sola fecha; ahí `fechav` apunta a la misma
        # columna y queda igual a `fecham`, que es lo correcto: inventar una
        # fecha de valor distinta sería peor que repetir la que el banco dio.
        fechav  = _parse_fecha_ar(_campo("fechav"))
        monto   = _parse_monto_ar(_campo("monto"))
        ref_nro = _campo("ref_nro").strip().lstrip("0") or "0"
        concepto = _campo("concepto").strip()
        # Saldo. Viene en una sola fila por día —la última en el formato
        # clásico, la primera en Banca Empresas— así que la mayoría de las
        # filas lo dejan vacío y eso está bien: lo que importa es el último
        # valor del período, que es el saldo de cierre del extracto.
        saldo   = _parse_monto_ar(_campo("saldo"))

        if fecham is None or monto is None:
            continue

        # Separar débito / crédito según signo del monto
        debito  = abs(monto) if monto < 0 else None
        credito = monto       if monto > 0 else None

        cuit = _extraer_cuit(concepto)

        resultados.append({
            "fecham":   fecham,
            "fechav":   fechav,
            "ref_nro":  ref_nro,
            "debito":   float(debito)  if debito  is not None else None,
            "credito":  float(credito) if credito is not None else None,
            "saldo":    float(saldo)   if saldo   is not None else None,
            "concepto": concepto[:100],
            "cuit":     cuit,
            "origen":   "BNA",
        })

    return resultados


# ── Parser ICBC ───────────────────────────────────────────────────────────────

def parsear_icbc(contenido: str, nombre_archivo: str = "") -> list[dict]:
    """
    Parser ICBC — Extracto de Cuenta Corriente.

    Formato real (separador ';', sin BOM):

      Línea 1:  Movimientos de CC $ NNNN/NNNNNNN/NN   ← info cuenta, ignorar
      Línea 2:  Fecha contable;Cod de Concepto;Concepto;Debito en $;
                Credito en $;Saldo en $;Informacion Complementaria;
                Nro de cheque;Sucursal Origen;Canal
      Datos:    DD/MM/YYYY;COD;CONCEPTO;-debito_o_vacio;credito_o_vacio;
                saldo;info_comp;nro_cheque;sucursal;canal

    Particularidades:
      - Fecha contable presente en cada fila (DD/MM/YYYY).
      - Débito y Crédito en columnas separadas.
      - Débito viene con signo negativo (ej: -182044,00); se almacena positivo.
      - ref_nro: Nro de cheque si tiene valor, sino Informacion Complementaria.
      - CUIT: se intenta extraer de Info Complementaria o Concepto.
      - Concepto enriquecido con Info Complementaria si no está vacía.
    """
    contenido = contenido.lstrip("\ufeff")
    lineas    = contenido.splitlines()
    if not lineas:
        return []

    # Encontrar la línea de encabezado (contiene "Fecha contable")
    inicio = 0
    for i, l in enumerate(lineas):
        if "Fecha contable" in l or "Fecha Contable" in l:
            inicio = i + 1
            break

    resultados = []
    for linea in lineas[inicio:]:
        linea = linea.strip()
        if not linea:
            continue

        partes = linea.split(";")
        if len(partes) < 5:
            continue

        # Col 0: Fecha contable
        fecham = _parse_fecha_ar(partes[0])
        if fecham is None:
            continue

        # Col 2: Concepto
        concepto    = partes[2].strip() if len(partes) > 2 else ""
        # Col 3: Debito en $ (negativo o vacío)
        debito_raw  = partes[3].strip() if len(partes) > 3 else ""
        # Col 4: Credito en $ (positivo o vacío)
        credito_raw = partes[4].strip() if len(partes) > 4 else ""
        # Col 5: Saldo en $ — el saldo del banco después de este movimiento.
        # Se guardaba nada y era el dato que después había que tipear a mano al
        # abrir la conciliación. El del último movimiento del período ES el
        # saldo de cierre del extracto.
        saldo_raw   = partes[5].strip() if len(partes) > 5 else ""
        # Col 6: Informacion Complementaria
        info_comp   = partes[6].strip() if len(partes) > 6 else ""
        # Col 7: Nro de cheque
        nro_cheque  = partes[7].strip() if len(partes) > 7 else ""

        debito  = None
        credito = None

        if debito_raw:
            d = _parse_monto_ar(debito_raw)
            if d is not None:
                debito = float(abs(d))   # guardar siempre positivo

        if credito_raw:
            c = _parse_monto_ar(credito_raw)
            if c is not None and c > 0:
                credito = float(c)

        # Saltear filas sin movimiento real
        if debito is None and credito is None:
            continue

        # ref_nro: cheque tiene prioridad, luego info complementaria
        ref_nro = (nro_cheque or info_comp or "").strip() or None

        # CUIT desde info complementaria o concepto
        cuit = _extraer_cuit(info_comp) or _extraer_cuit(concepto)

        # Enriquecer concepto con info complementaria
        concepto_full = concepto
        if info_comp and info_comp not in concepto:
            concepto_full = f"{concepto} — {info_comp}"

        saldo = _parse_monto_ar(saldo_raw) if saldo_raw else None

        resultados.append({
            "fecham":   fecham,
            "fechav":   fecham,      # ICBC no distingue fecha valor
            "ref_nro":  ref_nro,
            "debito":   debito,
            "credito":  credito,
            "saldo":    float(saldo) if saldo is not None else None,
            "concepto": concepto_full[:100],
            "cuit":     cuit,
            "origen":   "ICBC",
        })

    return resultados


def _fecha_del_nombre(nombre_archivo: str) -> date | None:
    """
    Fecha del movimiento tomada del nombre del archivo.

    El reporte de recaudaciones no trae fecha en sus filas: viene al principio
    del nombre, como «30.07.26  2026...». Se admite dd.mm.aa y dd.mm.aaaa.
    """
    m = re.match(r"\s*(\d{2})[.\-/](\d{2})[.\-/](\d{2,4})", nombre_archivo or "")
    if not m:
        return None
    d, mes, a = m.groups()
    anio = int(a) + (2000 if len(a) == 2 else 0)
    try:
        return date(anio, int(mes), int(d))
    except ValueError:
        return None


def parsear_icbc_recaudaciones(contenido: str, nombre_archivo: str = "") -> list[dict]:
    """
    Parser ICBC — reporte de Recaudaciones de la cuenta recaudadora.

    Formato (separador ';'):
      CUENTA;NOMBRE;MONEDA;COMPROBANTE;IMPORTE MOVTO.;CONCEPTO;SUC;CHEQUE;
      DATOS COMPLEMENTARIOS DE LA OPERACION

    Particularidades que lo distinguen del extracto de cuenta corriente:
      · No hay fecha en las filas: sale del nombre del archivo.
      · Un solo importe; el signo lo define el concepto (DEB… es débito).
      · «Datos complementarios» trae el CUIL y el nombre de quien depositó,
        que es justamente lo que permite identificar al afiliado después.
    """
    lineas = (contenido or "").lstrip("﻿").splitlines()
    if not lineas:
        return []

    fecham = _fecha_del_nombre(nombre_archivo) or date.today()

    inicio = 0
    for i, l in enumerate(lineas):
        if "IMPORTE MOVTO" in l.upper():
            inicio = i + 1
            break

    resultados = []
    for linea in lineas[inicio:]:
        linea = linea.strip()
        if not linea or linea.count(";") < 5:
            continue

        p = [x.strip() for x in linea.split(";")]
        comprobante = p[3] if len(p) > 3 else ""
        importe_raw = p[4] if len(p) > 4 else ""
        concepto    = p[5] if len(p) > 5 else ""
        cheque      = p[7] if len(p) > 7 else ""
        datos_comp  = p[8] if len(p) > 8 else ""

        importe = _parse_monto_ar(importe_raw)
        if importe is None or importe == 0:
            continue

        # El concepto define el signo: DEB.TRANSF.REC es el barrido a la cuenta
        # operativa, el resto son acreditaciones de terceros.
        es_debito = concepto.upper().startswith("DEB")
        debito  = float(abs(importe)) if es_debito else None
        credito = float(abs(importe)) if not es_debito else None

        cuit = _extraer_cuit(datos_comp) or _extraer_cuit(concepto)

        concepto_full = concepto
        if datos_comp and datos_comp not in concepto:
            concepto_full = f"{concepto} — {datos_comp}"

        resultados.append({
            "fecham":   fecham,
            "fechav":   fecham,
            "ref_nro":  (comprobante or cheque or "").strip() or None,
            "debito":   debito,
            "credito":  credito,
            "concepto": concepto_full[:100],
            "cuit":     cuit,
            "origen":   "ICBC",
        })

    return resultados


# ── Detección automática de banco ─────────────────────────────────────────────

def detectar_banco(nombre_archivo: str, contenido: str) -> str | None:
    """Intenta detectar el banco por nombre de archivo o contenido."""
    nombre = nombre_archivo.upper()
    # `BEE_` es el prefijo que le pone Banca Empresas de BNA a sus reportes.
    if ("BNA" in nombre or "NACION" in nombre or "CONFORMADOS" in nombre
            or nombre.startswith("BEE_")):
        return "BNA"
    if "ICBC" in nombre or "RECAUDACIONES" in nombre:
        return "ICBC"
    # Por contenido
    contenido_norm = contenido.lstrip("\ufeff")[:500]
    if "Fecha Mvto" in contenido_norm and "Referencia" in contenido_norm:
        return "BNA"
    # El otro formato de BNA, el de Banca Empresas.
    if _es_cabecera_bna_empresas(contenido_norm):
        return "BNA"
    # Nuevo formato ICBC: tiene "Fecha contable" y "Debito en $"
    if "Fecha contable" in contenido_norm and "Debito en $" in contenido_norm:
        return "ICBC"
    # Formato ICBC legacy (por si acaso)
    if "DATOS COMPLEMENTARIOS" in contenido_norm.upper():
        return "ICBC"
    return None


def parsear(banco: str, contenido: str, nombre_archivo: str = "") -> list[dict]:
    """Despacha al parser correcto según banco.

    El ICBC entrega dos archivos distintos: el extracto de cuenta corriente y
    el reporte de recaudaciones. Se distinguen por el encabezado, no por el
    nombre, porque el nombre lo cambia el operador al bajarlo.
    """
    if banco == "BNA":
        return parsear_bna(contenido)
    if banco == "ICBC":
        cabecera = (contenido or "").lstrip("﻿")[:400].upper()
        if "IMPORTE MOVTO" in cabecera and "DATOS COMPLEMENTARIOS" in cabecera:
            return parsear_icbc_recaudaciones(contenido, nombre_archivo)
        return parsear_icbc(contenido, nombre_archivo)
    raise ValueError(f"Banco no soportado: {banco}")


# ── Persistencia ──────────────────────────────────────────────────────────────

# =============================================================================
# De qué cuenta es el archivo
#
# EL PROBLEMA QUE RESUELVE
# ------------------------
# La cuenta la elegía la persona en un combo y nadie la comparaba contra el
# archivo. Equivocarse de opción metía el extracto entero en otra cuenta, sin
# un solo aviso: los parsers LEEN el número de cuenta ---está en la primera
# línea del ICBC y en la primera columna del BNA de Banca Empresas--- y lo
# descartaban a propósito.
#
# Pasó el 12/09/2026 a las 16:27: 39 movimientos de Plaza de Mayo, entre ellos
# nueve SS-AFIP DISTR.DIARIA de millones, entraron en Congreso ---una cuenta
# cuyo saldo se mueve en miles--- y la llevaron a un saldo de $ 133.537.444,17.
# La conciliación en proceso de Congreso ya los había levantado como 34 ítems
# pendientes.
#
# QUE SE COMPARA
# --------------
# Los ÚLTIMOS CINCO DÍGITOS del número, nada más. El mismo número se escribe
# `CC $ 00010003978039` en el archivo, `00010003978039` en el maestro y
# `0501/02146774/97` en el ICBC; separadores, prefijos y ceros de relleno
# cambian, el final no. Con cinco dígitos las cinco cuentas bancarias
# configuradas no se pisan entre sí (78039, 68672, 67497, 99063, 15489).
#
# Y se mira CADA FILA que declara cuenta, no sólo la primera: el BNA de Banca
# Empresas y el reporte de recaudaciones del ICBC la repiten en todas, así
# que un archivo con movimientos de dos cuentas mezcladas también se corta.
#
# QUE HACE ANTE UN DESACUERDO
# ---------------------------
# Corta. Siempre que el archivo declare una cuenta y no sea la elegida, no se
# importa nada, coincida o no con otra cuenta del maestro.
#
# Hasta el 29/09/2026 sólo cortaba cuando el número era el de OTRA cuenta
# configurada, y si no coincidía con ninguna avisaba y dejaba pasar; el aviso
# además nunca llegaba a la pantalla. Se había dejado así porque el maestro
# tenía números mal cargados (la cuenta 4 tenía `0501/0214665/59`); eso ya se
# corrigió y el hueco quedaba abierto para nada.
#
# También corta si la cuenta elegida no tiene número cargado en el maestro:
# sin número no hay contra qué comparar, y dejar pasar es exactamente el
# hueco que se cierra.
#
# Lo único que pasa sin validar es el BNA «clásico», que no trae número de
# cuenta. Pasa con un aviso visible.
# =============================================================================

_DIGITOS_COMPARADOS = 5


class CuentaEquivocada(Exception):
    """El archivo es de una cuenta distinta de la elegida."""


def _solo_digitos(s) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def _cola(s) -> str:
    """Los últimos dígitos del número, o '' si no alcanzan."""
    d = _solo_digitos(s)
    return d[-_DIGITOS_COMPARADOS:] if len(d) >= _DIGITOS_COMPARADOS else ""


def _mismo_numero(a: str, b: str) -> bool:
    """¿Son el mismo número de cuenta, escrito de dos formas?"""
    ca, cb = _cola(a), _cola(b)
    return bool(ca) and ca == cb


def cuentas_del_archivo(banco: str, contenido: str,
                        nombre_archivo: str = "") -> list[str]:
    """Todos los números de cuenta distintos que declara el archivo, en el
    orden en que aparecen. Lista vacía si el formato no los trae.

    El BNA «clásico» ---Fecha Mvto;Fecha Valor;Monto;…--- es el único de los
    cuatro formatos que no lo incluye.
    """
    lineas = [l for l in (contenido or "").lstrip("\ufeff").splitlines() if l.strip()]
    if not lineas:
        return []
    banco = (banco or "").upper()
    vistos: list[str] = []

    def _agregar(cand: str):
        cand = cand.strip()
        if _cola(cand) and cand not in vistos:
            vistos.append(cand)

    if banco == "ICBC":
        # Extracto de cuenta corriente: «Movimientos de CC $ 0501/02146686/72»
        # en la primera línea, antes del encabezado.
        for l in lineas[:5]:
            if "fecha contable" in l.lower():
                break
            m = re.search(r"(\d{3,5}\s*/\s*\d{5,10}\s*/\s*\d{1,3})", l)
            if m:
                return [m.group(1)]
        # Reporte de recaudaciones: la cuenta es la primera columna de cada
        # fila de datos.
        encabezado = False
        for l in lineas:
            if "IMPORTE MOVTO" in l.upper():
                encabezado = True
                continue
            if encabezado and ";" in l:
                _agregar(l.split(";")[0])
        return vistos

    if banco == "BNA":
        # Sólo Banca Empresas trae la cuenta, en la columna 0 de cada fila.
        for i, l in enumerate(lineas):
            if not _es_cabecera_bna_empresas(l):
                continue
            for fila in lineas[i + 1:]:
                if ";" in fila:
                    _agregar(fila.split(";")[0])
            return vistos
    return vistos


def cuenta_del_archivo(banco: str, contenido: str, nombre_archivo: str = "") -> str | None:
    """El primer número de cuenta que declara el archivo, o None si no lo trae."""
    todas = cuentas_del_archivo(banco, contenido, nombre_archivo)
    return todas[0] if todas else None


def _validar_cuenta(cur, id_cuenta: int, banco: str, contenido: str,
                    nombre_archivo: str) -> str:
    """Corta (CuentaEquivocada) si el archivo no es de la cuenta elegida.

    Devuelve un aviso sólo cuando el formato no trae número de cuenta y no se
    pudo validar; '' si validó bien.
    """
    del_archivo = cuentas_del_archivo(banco, contenido, nombre_archivo)
    if not del_archivo:
        return "el archivo no declara número de cuenta: no se pudo validar"

    cur.execute("SELECT id, nombre, numero_de_cuenta, cbu FROM c_cuentas_de_fondos")
    cuentas = list(cur.fetchall())
    elegida = next((c for c in cuentas if c["id"] == id_cuenta), None)
    nombre_elegida = elegida["nombre"] if elegida else f"la cuenta {id_cuenta}"
    numero_elegida = (elegida or {}).get("numero_de_cuenta")

    def _es_de(n, c) -> bool:
        """¿El número del archivo es el de la cuenta `c`? Por el número del
        maestro o por la parte de la cuenta del CBU (dígitos 9 a 21, con y sin
        el verificador): el BNA de Banca Empresas puede escribir la cuenta con
        la sucursal adelante, y eso no termina igual que el número cargado."""
        cbu = _solo_digitos((c or {}).get("cbu"))
        candidatos = [(c or {}).get("numero_de_cuenta")]
        if len(cbu) == 22:
            candidatos += [cbu[8:21], cbu[8:22]]
        return any(_mismo_numero(n, x) for x in candidatos)

    if not _cola(numero_elegida) and len(_solo_digitos((elegida or {}).get("cbu"))) != 22:
        raise CuentaEquivocada(
            f"{nombre_elegida} no tiene número de cuenta cargado en el maestro "
            f"y el archivo es de la cuenta {del_archivo[0]}: cargá el número "
            f"de cuenta antes de importar. No se importó nada."
        )

    ajenas = [n for n in del_archivo if not _es_de(n, elegida)]
    if not ajenas:
        return ""

    def _de_quien(n):
        o = next((c for c in cuentas if _es_de(n, c)), None)
        return f"{n} ({o['nombre']})" if o else f"{n} (no configurada)"

    if len(ajenas) < len(del_archivo):
        detalle = (f"el archivo mezcla movimientos de la cuenta elegida con "
                   f"otras: {', '.join(_de_quien(n) for n in ajenas)}")
    else:
        detalle = (f"el archivo es de la cuenta "
                   f"{', '.join(_de_quien(n) for n in ajenas)}")
    raise CuentaEquivocada(
        f"{detalle} y se eligió {nombre_elegida} "
        f"(…{_cola(numero_elegida)}). No se importó nada."
    )


def importar_extracto(conn, id_cuenta: int, banco: str, contenido: str,
                      nombre_archivo: str) -> dict:
    """
    Parsea el archivo e inserta los movimientos en c_extractos_bancarios.

    Validación por fecha:
      - Se descarta el movimiento que ya está cargado en la cuenta, comparando
        por número de operación, fecha e importe (no por saldo). Los renglones
        idénticos se cuentan: entran los que superan a los ya cargados.
      - No se filtra por fecha: se puede reimportar un período viejo o cargar
        archivos en cualquier orden sin perder movimientos.

    Retorna resumen:
      {insertados, descartados_por_duplicado, errores,
       total_credito, total_debito, ultima_fecha_previa, ultima_fecha_nueva}
    """
    # ANTES de parsear nada: si el archivo es de otra cuenta, no hay nada que
    # importar acá y meterlo igual es el bug que esto viene a cerrar.
    with conn.cursor() as cur:
        aviso_cuenta = _validar_cuenta(cur, id_cuenta, banco, contenido,
                                       nombre_archivo)

    movimientos = parsear(banco, contenido, nombre_archivo)

    resumen = {
        "insertados":               0,
        "descartados_por_duplicado": 0,
        "errores":                  0,
        "aviso_cuenta":             "",
        "detalle_errores":          [],
        "total_credito":            0.0,
        "total_debito":             0.0,
        "ultima_fecha_previa":      None,
        "ultima_fecha_nueva":       None,
    }

    resumen["aviso_cuenta"] = aviso_cuenta
    if aviso_cuenta:
        log.warning("Extracto %s: %s", nombre_archivo, aviso_cuenta)

    if not movimientos:
        return resumen

    # Sin microsegundos: `importado` es DATETIME y se compara contra esto
    # para no contar lo insertado en esta misma importación.
    ahora = datetime.now().replace(microsecond=0)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT MAX(fecham) AS ultima
            FROM   c_extractos_bancarios
            WHERE  c_cuentas_de_fondos_id = %s
        """, (id_cuenta,))
        row = cur.fetchone()
        resumen["ultima_fecha_previa"] = row["ultima"] if row else None

        # Cuántas veces apareció cada movimiento en ESTE archivo hasta ahora.
        vistos: dict = {}

        for m in movimientos:
            try:
                # Duplicado = mismo número de operación, mismo día y mismo
                # importe (sin número de operación, mismo concepto).
                #
                # NO SE COMPARA EL SALDO
                # ----------------------
                # BNA no trae el saldo en todos los renglones: va en uno solo
                # por día —el último en el formato clásico, el primero en
                # Banca Empresas— y depende de cómo se descargó el archivo.
                # Comparándolo, un extracto mensual reimportado no reconocía
                # los movimientos ya cargados día por día y los duplicaba
                # (cuenta 3, 28/10/2026: 31 movimientos del 01 al 23/10).
                #
                # MOVIMIENTOS IGUALES LEGÍTIMOS: SE CUENTAN
                # -----------------------------------------
                # Puede haber varios renglones idénticos que son movimientos
                # distintos (siete acreditaciones de $52.000 el mismo día, con
                # la misma referencia). Por eso no alcanza con «ya existe»: si
                # el archivo trae N y la cuenta ya tiene M de importaciones
                # anteriores, entran N - M. Lo insertado en esta misma
                # importación no cuenta como previo (`importado <> ahora`).
                ref = (m.get("ref_nro") or "").strip()
                clave = (ref, m["fecham"], m["debito"] or 0, m["credito"] or 0,
                         "" if ref else m["concepto"])
                vistos[clave] = vistos.get(clave, 0) + 1

                if ref:
                    cur.execute("""
                        SELECT COUNT(*) AS n FROM c_extractos_bancarios
                         WHERE c_cuentas_de_fondos_id = %s
                           AND COALESCE(ref_nro, '') = %s
                           AND fecham = %s
                           AND COALESCE(debito,  0) = %s
                           AND COALESCE(credito, 0) = %s
                           AND (importado IS NULL OR importado <> %s)
                    """, (id_cuenta, ref, m["fecham"],
                          m["debito"] or 0, m["credito"] or 0, ahora))
                else:
                    cur.execute("""
                        SELECT COUNT(*) AS n FROM c_extractos_bancarios
                         WHERE c_cuentas_de_fondos_id = %s
                           AND fecham   = %s
                           AND concepto = %s
                           AND COALESCE(ref_nro, '') = ''
                           AND COALESCE(debito,  0) = %s
                           AND COALESCE(credito, 0) = %s
                           AND (importado IS NULL OR importado <> %s)
                    """, (id_cuenta, m["fecham"], m["concepto"],
                          m["debito"] or 0, m["credito"] or 0, ahora))

                if vistos[clave] <= cur.fetchone()["n"]:
                    resumen["descartados_por_duplicado"] += 1
                    continue

                cur.execute("""
                    INSERT INTO c_extractos_bancarios
                      (c_cuentas_de_fondos_id, fecham, fechav, ref_nro,
                       debito, credito, saldo, concepto, cuit, origen, importado)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    id_cuenta,
                    m["fecham"],
                    m["fechav"],
                    m["ref_nro"],
                    m["debito"],
                    m["credito"],
                    m.get("saldo"),
                    m["concepto"],
                    m["cuit"],
                    m["origen"],
                    ahora,
                ))
                resumen["insertados"] += 1
                resumen["total_credito"] += m["credito"] or 0
                resumen["total_debito"]  += m["debito"]  or 0

            except Exception as e:                       # noqa: BLE001 — se cuenta y se informa
                resumen["errores"] += 1
                if len(resumen["detalle_errores"]) < 5:
                    resumen["detalle_errores"].append(
                        f"{m.get('fecham')} {m.get('concepto') or ''}: {e}")
                log.exception("Extracto %s: no se pudo grabar un renglón", nombre_archivo)

        # Registrar la nueva fecha máxima importada
        if resumen["insertados"] > 0:
            cur.execute("""
                SELECT MAX(fecham) AS ultima
                FROM   c_extractos_bancarios
                WHERE  c_cuentas_de_fondos_id = %s
            """, (id_cuenta,))
            row = cur.fetchone()
            resumen["ultima_fecha_nueva"] = row["ultima"] if row else None

    return resumen


# ── Consultas ─────────────────────────────────────────────────────────────────

def get_cuentas(conn) -> list[dict]:
    """Devuelve las cuentas de fondos habilitadas (tipo Banco)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, nombre, numero_de_cuenta, tipo_de_cuenta
              FROM c_cuentas_de_fondos
             WHERE habilitada = 1
               AND tipo_de_cuenta = 'B'
             ORDER BY nombre
        """)
        return cur.fetchall()
