"""
lsd_lector.py — Lectura del archivo de liquidación del Libro de Sueldos Digital.

Es el archivo que el sistema de sueldos de una empresa arma para ARCA:
«Interfaz Usuario / Liquidación de SyJ - DJ F931 (.TXT)», un renglón por
registro:

  01  cabecera: CUIT, envío (SJ / RE), período, tipo y número de liquidación
  02  por trabajador: legajo, dependencia, CBU, fechas de pago y rúbrica
  03  por concepto del recibo: código, cantidad, unidad, importe, débito/crédito
  04  por trabajador, los datos del F931: obra social, remuneración bruta,
      las 10 bases imponibles e importe a detraer (Ley 27.541)
  05  eventuales · 06 observaciones

Las bases imponibles, según la guía N.º 18 de ARCA (Armado de bases
imponibles LSD):
   1 aportes previsionales            6 aportes diferenciales
   2 contribuciones previsionales      7 aportes personal regímenes especiales
   3 contribuciones FNE, AAFF, RENATRE 8 contribuciones obra social y FSR
   4 aportes obra social y FSR         9 Ley de Riesgos del Trabajo
   5 aportes INSSJyP                  10 contribuciones previsionales con la
                                         detracción de la Ley 27.541
La 5 es la «Remuneración imponible 5» del F931, la misma que se toma de la DDJJ
de OSEDA para liquidar la cuota sindical.

Copia del lector de gestion_adm (sueldos_lsd.leer_liquidacion, que además
genera el archivo): esta aplicación no importa nada de aquella. Si se corrige
uno, corregir el otro.
"""

from __future__ import annotations

from decimal import Decimal

ENCODING = "cp1252"          # ANSI, lo que pide ARCA

LARGO_01 = 35
LARGO_02 = 115
LARGO_03 = 51
LARGO_04 = 370
LARGO_05 = 65
LARGO_06 = 108

#: Concepto ARCA «Cuota Sindical» (descuento). Vale cuando la empresa usa los
#: códigos de ARCA como propios; si no, el código del registro 03 es el suyo.
CONCEPTO_CUOTA_SINDICAL = "810004"


class LSDError(Exception):
    """El archivo no tiene el diseño del Libro de Sueldos Digital."""


_CAMPOS_LECTURA = {
    "01": [("tipo_registro", 1, 2, "a"), ("cuit", 3, 13, "a"), ("envio", 14, 15, "a"),
           ("periodo", 16, 21, "n"), ("tipo_liq", 22, 22, "a"),
           ("nro_liquidacion", 23, 27, "n"), ("dias_base", 28, 29, "a"),
           ("cant_trabajadores", 30, 35, "n")],
    "02": [("tipo_registro", 1, 2, "a"), ("cuil", 3, 13, "a"), ("legajo", 14, 23, "a"),
           ("dependencia_revista", 24, 73, "a"), ("cbu", 74, 95, "a"),
           ("dias_tope", 96, 98, "n"), ("fecha_pago", 99, 106, "f"),
           ("fecha_rubrica", 107, 114, "f"), ("forma_pago", 115, 115, "a")],
    "03": [("tipo_registro", 1, 2, "a"), ("cuil", 3, 13, "a"), ("codigo", 14, 23, "a"),
           ("cantidad", 24, 28, "d2"), ("unidad", 29, 29, "a"), ("importe", 30, 44, "d2"),
           ("dc", 45, 45, "a"), ("periodo_ajuste", 46, 51, "n")],
    "04": [("tipo_registro", 1, 2, "a"), ("cuil", 3, 13, "a"), ("conyuge", 14, 14, "a"),
           ("hijos", 15, 16, "n"), ("en_cct", 17, 17, "a"), ("cobertura_scvo", 18, 18, "a"),
           ("corresponde_reduccion", 19, 19, "a"), ("tipo_empleador", 20, 20, "a"),
           ("tipo_operacion", 21, 21, "a"), ("situacion_revista", 22, 23, "a"),
           ("condicion", 24, 25, "a"), ("actividad", 26, 28, "a"),
           ("modalidad_contratacion", 29, 31, "a"), ("siniestrado", 32, 33, "a"),
           ("localidad", 34, 35, "a"), ("sit_revista_2", 36, 37, "a"),
           ("dia_inicio_sr2", 38, 39, "n"), ("sit_revista_3", 40, 41, "a"),
           ("dia_inicio_sr3", 42, 43, "n"), ("sit_revista_4", 44, 45, "a"),
           ("dia_inicio_sr4", 46, 47, "n"), ("dias_trabajados", 48, 49, "n"),
           ("horas_trabajadas", 50, 52, "n"), ("aporte_adic_ss", 53, 57, "d2"),
           ("contrib_tarea_dif", 58, 62, "d2"), ("obra_social", 63, 68, "a"),
           ("adherentes_os", 69, 70, "n"), ("aporte_adic_os", 71, 85, "d2"),
           ("contrib_adic_os", 86, 100, "d2"), ("base_dif_ap_os", 101, 115, "d2"),
           ("base_dif_co_os", 116, 130, "d2"), ("base_dif_lrt", 131, 145, "d2"),
           ("rem_maternidad", 146, 160, "d2"), ("rem_bruta", 161, 175, "d2")]
          + [(f"base_imponible_{i}", 176 + 15 * (i - 1), 190 + 15 * (i - 1), "d2")
             for i in range(1, 10)]
          + [("base_dif_ap_ss", 311, 325, "d2"), ("base_dif_co_ss", 326, 340, "d2"),
             ("base_imponible_10", 341, 355, "d2"), ("importe_detraer", 356, 370, "d2")],
    "05": [("tipo_registro", 1, 2, "a"), ("cuil", 3, 13, "a"), ("categoria", 14, 19, "a"),
           ("puesto", 20, 23, "a"), ("fecha_ingreso", 24, 31, "f"),
           ("fecha_egreso", 32, 39, "f"), ("remuneracion", 40, 54, "d2"),
           ("cuit", 55, 65, "a")],
    "06": [("tipo_registro", 1, 2, "a"), ("id_liquidacion", 3, 17, "n"),
           ("cuil", 18, 28, "a"), ("observaciones", 29, 108, "a")],
}

_LARGOS = {"01": LARGO_01, "02": LARGO_02, "03": LARGO_03, "04": LARGO_04,
           "05": LARGO_05, "06": LARGO_06}

ENVIOS = {"SJ": "Liquidación de SyJ y DJ F931", "RE": "Sólo datos de DJ F931 a rectificar"}
TIPOS_LIQ = {"M": "Mensual", "Q": "Quincenal", "S": "Semanal"}
FORMAS_PAGO = {"1": "Efectivo", "2": "Cheque", "3": "Acreditación en cuenta",
               "4": "Pago externo"}
UNIDADES = {"": "", "$": "Moneda", "%": "Porcentaje", "A": "Año", "M": "Mes",
            "Q": "Quincena", "S": "Semana", "D": "Días", "H": "Horas"}


def _valor(txt: str, tipo: str):
    if tipo == "a":
        return txt.rstrip()
    limpio = txt.strip()
    if not limpio:
        return None
    if not limpio.isdigit():
        raise LSDError(f"«{txt}» no es numérico")
    if tipo == "n":
        return int(limpio)
    if tipo == "d2":
        return (Decimal(limpio) / 100).quantize(Decimal("0.01"))
    if tipo == "f":
        if int(limpio) == 0:
            return None
        from datetime import date
        try:
            return date(int(limpio[:4]), int(limpio[4:6]), int(limpio[6:8]))
        except ValueError:
            raise LSDError(f"«{txt}» no es una fecha AAAAMMDD")
    raise LSDError(f"tipo de campo desconocido: {tipo}")


def leer_registro(linea: str) -> dict:
    """Un renglón del archivo de liquidación → dict con las claves de arriba.

    Levanta LSDError si el tipo de registro no existe, si el largo no es el del
    diseño o si un campo numérico trae otra cosa.
    """
    linea = linea.rstrip("\r\n")
    tipo = linea[:2]
    if tipo not in _CAMPOS_LECTURA:
        raise LSDError(f"tipo de registro «{tipo}» desconocido")
    if len(linea) != _LARGOS[tipo]:
        raise LSDError(f"el registro {tipo} tiene {len(linea)} posiciones y el diseño "
                       f"pide {_LARGOS[tipo]}")
    r = {}
    for clave, desde, hasta, t in _CAMPOS_LECTURA[tipo]:
        try:
            r[clave] = _valor(linea[desde - 1:hasta], t)
        except LSDError as e:
            raise LSDError(f"registro {tipo}, {clave} (pos. {desde}-{hasta}): {e}")
    return r


def leer_liquidacion(contenido) -> dict:
    """Lee el archivo de liquidación (texto o bytes en ANSI).

    Devuelve:
      cabecera      el registro 01;
      trabajadores  uno por CUIL, en el orden del archivo, con
                    `liquidacion` (02), `conceptos` (03), `f931` (04),
                    `eventual` (05) y `observaciones` (06);
      errores       lo que no cierra, con el número de renglón. Un renglón
                    con error se saltea; el resto se lee igual.
    """
    if isinstance(contenido, (bytes, bytearray)):
        contenido = contenido.decode(ENCODING, errors="replace")
    cabecera, errores = None, []
    trabajadores, por_cuil = [], {}

    def _trab(cuil):
        if cuil not in por_cuil:
            por_cuil[cuil] = {"cuil": cuil, "liquidacion": None, "conceptos": [],
                              "f931": None, "eventual": None, "observaciones": []}
            trabajadores.append(por_cuil[cuil])
        return por_cuil[cuil]

    for n, linea in enumerate(contenido.splitlines(), start=1):
        if not linea.strip():
            continue
        try:
            r = leer_registro(linea)
        except LSDError as e:
            errores.append(f"renglón {n}: {e}")
            continue
        tipo = r.pop("tipo_registro")
        if tipo == "01":
            if cabecera:
                errores.append(f"renglón {n}: hay más de un registro 01")
            else:
                cabecera = r
            continue
        if cabecera is None:
            errores.append(f"renglón {n}: el archivo no empieza con el registro 01")
        t = _trab(r["cuil"])
        if tipo == "02":
            if t["liquidacion"]:
                errores.append(f"renglón {n}: CUIL {r['cuil']} con dos registros 02")
            t["liquidacion"] = r
        elif tipo == "03":
            if not t["liquidacion"]:
                errores.append(f"renglón {n}: concepto del CUIL {r['cuil']} antes de su "
                               f"registro 02")
            t["conceptos"].append(r)
        elif tipo == "04":
            if t["f931"]:
                errores.append(f"renglón {n}: CUIL {r['cuil']} con dos registros 04")
            t["f931"] = r
        elif tipo == "05":
            t["eventual"] = r
        elif tipo == "06":
            t["observaciones"].append(r["observaciones"])

    if cabecera is None:
        errores.append("falta el registro 01")
    else:
        n04 = sum(1 for t in trabajadores if t["f931"])
        if cabecera["cant_trabajadores"] != n04:
            errores.append(f"el registro 01 informa {cabecera['cant_trabajadores']} "
                           f"trabajadores y hay {n04} registros 04")
        for t in trabajadores:
            if not t["f931"]:
                errores.append(f"CUIL {t['cuil']}: falta el registro 04")
            if cabecera["envio"] == "SJ" and not t["liquidacion"]:
                errores.append(f"CUIL {t['cuil']}: falta el registro 02")
    return {"cabecera": cabecera, "trabajadores": trabajadores, "errores": errores}
