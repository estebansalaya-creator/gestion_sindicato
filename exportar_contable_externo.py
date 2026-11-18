# -*- coding: utf-8 -*-
"""
Exportación de asientos al sistema contable externo.

POR QUE NO USA `exportar.py`
----------------------------
`exportar.py` arma reportes para leer: fila de título, encabezados con color,
fuentes, fila de totales, anchos de columna. Todo eso acá sobra y molesta —el
destino lee la fila 1 como encabezado y cualquier adorno le corre los datos—.

Esto no es un reporte, es un archivo de intercambio. La forma la impone el otro
sistema y no se puede negociar:

  · Siete columnas, en este orden, con el encabezado RELLENADO A ANCHO FIJO
    con espacios. `'Id         '` son 11 caracteres, no dos.
  · La fecha va como TEXTO y con un apóstrofo literal adelante:
    `'01/07/2026`. No es el prefijo de Excel para forzar texto —ése no se
    guarda en el valor—: es un carácter más del dato, y sin él el destino la
    lee como número de serie.
  · `Detalle` y `Detitem` también van rellenados con espacios, a 100 y 115.
  · `Cuenta` es el código del plan SIN LOS PUNTOS, como entero:
    `5.3.0.00.040` → `53000040`.
  · `Debe` y `Haber` numéricos, con dos decimales, y el que no corresponde va
    en 0 —no vacío—.

Meterle esto a `exportar.py` como opciones lo convertiría en dos programas
adentro de uno para un solo consumidor. Vive acá, con la forma escrita al lado
del código que la produce.
"""

import io
import re

import openpyxl


# (encabezado, ancho, ¿se rellena el valor?)
#
# El ancho vale para el encabezado siempre. Para el valor sólo en las de texto:
# los números el destino los toma como números y rellenarlos los rompería.
COLUMNAS = [
    ("Id",      11,  False),
    ("Fecha",   11,  False),   # el valor ya mide 11: apóstrofo + dd/mm/aaaa
    ("Detalle", 100, True),
    ("Cuenta",  13,  False),
    ("Detitem", 115, True),
    ("Debe",    20,  False),
    ("Haber",   20,  False),
]

ANCHO_DETALLE = 100
ANCHO_DETITEM = 115


def cuenta_a_entero(codigo: str) -> int | None:
    """`5.3.0.00.040` → 53000040. Devuelve None si no queda nada numérico.

    No se completa con ceros ni se recorta: el código del plan ya tiene la
    cantidad de dígitos que el destino espera. Si alguna cuenta tuviera otra
    máscara, el que la vea acá en None es el que hay que corregir en el plan,
    no acá.
    """
    solo_digitos = re.sub(r"\D", "", codigo or "")
    return int(solo_digitos) if solo_digitos else None


# La Ñ que se perdió en la migración.
#
# Los nombres vinieron del sistema viejo con la Ñ convertida en `?` —uno o dos,
# según si el origen la tenía en latin1 o en UTF-8—: `BRICE?O`, `MU??OZ`. Está
# así grabado en la base (byte 0x3F), en afiliados, comprobantes emitidos,
# expedientes y reintegros, y también en el padrón de la SSS, así que no hay
# de dónde copiar el nombre bien escrito.
#
# Revisados todos los casos (oct. 2026): el `?` entre dos letras es SIEMPRE una
# Ñ. Fuera de ese contexto no aparece, y si apareciera no se toca: no se
# adivina una letra que no está rodeada de otras.
_N_PERDIDA = re.compile(r"(?<=[A-Za-zÁÉÍÓÚÜÑáéíóúüñ])\?+(?=[A-Za-zÁÉÍÓÚÜÑáéíóúüñ])")


def _restituir_enie(m) -> str:
    """Mayúscula si la letra anterior lo es: `MU??OZ` → `MUÑOZ`."""
    anterior = m.string[m.start() - 1]
    return "Ñ" if anterior.isupper() else "ñ"


def _limpiar(s: str) -> str:
    """Lo que el destino no acepta en las columnas de texto.

    · Sin comas. `BARGADOS, LUIS RICARDO` → `BARGADOS LUIS RICARDO`. La coma
      se reemplaza por un espacio y no se borra a secas, para no pegar
      palabras cuando el origen la escribió sin espacio después.
    · La Ñ restituida, ver `_N_PERDIDA`.
    · Los espacios repetidos se colapsan: los dejaba la coma y ya venían en
      algunos nombres (`NU??EZ,  ANGELA  V.`). El relleno a ancho fijo se hace
      después, sobre el texto limpio.
    """
    s = _N_PERDIDA.sub(_restituir_enie, s)
    s = s.replace(",", " ")
    return re.sub(r"\s+", " ", s).strip()


def _texto(valor, ancho: int) -> str:
    """Limpia, rellena con espacios a la derecha y, si no entra, recorta.

    Recortar no es una decisión menor pero es la única posible: el campo es de
    ancho fijo del otro lado. `descripcion` admite 255 en la base y acá entran
    100 o 115, así que puede pasar de verdad. Quien exporta ve el texto
    completo en la pantalla; el que se recorta es el archivo.
    """
    s = "" if valor is None else _limpiar(str(valor))
    return s[:ancho].ljust(ancho)


def _fecha(valor) -> str:
    """date → `'01/07/2026`, con el apóstrofo adelante."""
    if valor is None:
        return "'".ljust(11)
    return "'" + valor.strftime("%d/%m/%Y")


def _importe(valor) -> float:
    """Siempre número, nunca vacío: el destino espera 0 en el lado que no va."""
    return round(float(valor or 0), 2)


def construir_libro(filas) -> io.BytesIO:
    """
    `filas` — dicts con: id, fecha, detalle, cuenta_codigo, detitem, debe, haber.

    Devuelve el xlsx en memoria, listo para `send_file`.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Hoja1"          # el destino busca la hoja por nombre

    for col, (titulo, ancho, _) in enumerate(COLUMNAS, 1):
        ws.cell(row=1, column=col, value=titulo.ljust(ancho))

    for i, f in enumerate(filas, 2):
        ws.cell(row=i, column=1, value=f["id"])
        ws.cell(row=i, column=2, value=_fecha(f["fecha"]))
        ws.cell(row=i, column=3, value=_texto(f["detalle"], ANCHO_DETALLE))
        ws.cell(row=i, column=4, value=cuenta_a_entero(f["cuenta_codigo"]))
        ws.cell(row=i, column=5, value=_texto(f["detitem"], ANCHO_DETITEM))
        ws.cell(row=i, column=6, value=_importe(f["debe"]))
        ws.cell(row=i, column=7, value=_importe(f["haber"]))

    # Los mismos anchos visibles que trae el archivo del destino. Es cosmético
    # —el que lee es un programa— pero hace que abrirlo para controlar no
    # obligue a ensanchar dos columnas a mano cada vez.
    ws.column_dimensions["C"].width = 30.78
    ws.column_dimensions["E"].width = 50.78

    salida = io.BytesIO()
    wb.save(salida)
    salida.seek(0)
    return salida


SQL_ASIENTOS = """
    SELECT a.id_asiento                AS id,
           a.fecha                     AS fecha,
           a.descripcion               AS detalle,
           pc.codigo                   AS cuenta_codigo,
           COALESCE(NULLIF(TRIM(ad.descripcion), ''), pc.nombre) AS detitem,
           ad.debe                     AS debe,
           ad.haber                    AS haber
      FROM c_asientos a
      JOIN c_asiento_detalle ad ON ad.id_asiento = a.id_asiento
      JOIN c_plan_de_cuentas pc ON pc.id_cuenta  = ad.id_cuenta
     WHERE a.estado = 'confirmado'
       AND a.fecha BETWEEN %s AND %s
     ORDER BY a.fecha, a.id_asiento, ad.id_detalle
"""
# El Detitem es la DESCRIPCIÓN DEL RENGLÓN, no el nombre de la cuenta.
#
# Es lo que el destino escribe en esa columna y con lo que se concilia: el
# proveedor en el renglón de pasivo, el afiliado en el de ingresos, el concepto
# imputado en el de gasto, el número de débito en el de fondos. El nombre de la
# cuenta ya va en la columna de al lado.
#
# El COALESCE es para los asientos viejos que quedaron con la descripción
# vacía: ahí se manda el nombre de la cuenta, que repite pero no deja la
# columna en blanco —el destino la usa para identificar el renglón—.
#
# `estado = 'confirmado'` no es un filtro de pantalla: un borrador todavía se
# edita y un anulado dejó de tener efecto. Mandar cualquiera de los dos a un
# sistema contable externo es mandarle algo que acá no es cierto.
#
# El Id es `id_asiento` y no `numero`: sólo tiene que agrupar los renglones de
# un asiento y no repetirse, y `numero` puede reiniciarse por período —dos
# asientos de meses distintos compartirían Id y el destino los uniría—.
