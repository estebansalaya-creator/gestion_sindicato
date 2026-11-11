"""
transferencias_formatos.py — Los archivos que se suben al home banking.

Portado de `gestion_adm` (integracion_transferencias.py y
pago_transferencias_icbc.py). Las cuentas pagadoras del sindicato son del
Banco Nación y del ICBC, así que vienen los tres diseños de esos bancos:

    bna24        Banco Nación, 216 posiciones con CBU ordenante y registro de pie
    bna_empresa  Banco Nación, 99 posiciones, sin ordenante ni pie
    icbc_xlsx    ICBC, planilla de seis columnas (todo como texto)

Interbanking no se portó: en gestion_adm depende del circuito de sueldos.

Cada formato dice su banco (código BCRA, los tres primeros dígitos del CBU) y
si el banco acepta alias. Cada transferencia es un dict con `cbu_ordenante`,
`cbu_destino`, `importe`, `nro_pago`, `cuit` y `nombre`.

QUÉ CAMBIA RESPECTO DE GESTION_ADM
- `motivo_destino()` dice ANTES de generar si un destino sirve para ese
  formato. En gestion_adm el generador del BNA salteaba en silencio los CBU
  que no verificaban (o los alias, que el BNA no toma) pero el lote los
  registraba como incluidos: el pago figuraba transferido y nunca había
  viajado. Acá un destino que el formato no toma queda excluido del lote con
  su motivo, a la vista.
- Los generadores ya no omiten nada: reciben solo lo que pasó `motivo_destino`.
"""

from __future__ import annotations

import io
import re
from decimal import Decimal, ROUND_HALF_UP

from afiliados import cbu_valido

BANCO_BNA = "011"
BANCO_ICBC = "015"

_CENT = Decimal("0.01")
#: Alias de CBU: 6 a 20 caracteres, letras, números, punto y guion, y no
#: todo números (eso es un CBU mal copiado).
_RE_ALIAS = re.compile(r"^[A-Za-z0-9.\-]{6,20}$")


def _digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def es_cbu(valor) -> bool:
    v = (valor or "").strip()
    return len(v) == 22 and v.isdigit()


def es_alias(valor) -> bool:
    v = (valor or "").strip()
    return bool(_RE_ALIAS.match(v)) and not v.isdigit()


def _centavos(importe) -> int:
    d = Decimal(str(importe or 0)).quantize(_CENT, rounding=ROUND_HALF_UP)
    return int(d * 100)


def _referencia(texto) -> str:
    """Alfanumérico puro: los diseños del banco no dicen qué separadores admiten."""
    return "".join(ch for ch in str(texto or "") if ch.isalnum())


def motivo_destino(clave: str, destino) -> str | None:
    """Por qué ese destino no puede ir en un archivo de ese formato, o None."""
    fmt = FORMATOS.get(clave)
    v = (destino or "").strip()
    if not v:
        return "no tiene CBU ni alias"
    if es_cbu(v):
        return None if cbu_valido(v) else f"el CBU {v} no verifica (dígitos verificadores)"
    if es_alias(v):
        if fmt and not fmt["acepta_alias"]:
            return f"tiene alias ({v}) y el formato {fmt['nombre']} solo toma CBU"
        return None
    return f"«{v[:30]}» no es un CBU ni un alias válido"


# ── Banco Nación ─────────────────────────────────────────────────────────────

def _linea_bna24(t: dict, concepto: str) -> str:
    return (_digitos(t["cbu_ordenante"]).ljust(22)[:22]
            + _digitos(t["cbu_destino"]).ljust(22)[:22]
            + " " * 44
            + str(_centavos(t["importe"])).rjust(12, "0")[-12:]
            + " " * 50
            + (concepto or "FAC").ljust(3)[:3]
            + _referencia(t.get("nro_pago")).ljust(12)[:12]
            + " " * 51)


def generar_bna24(transferencias: list[dict], concepto: str = "FAC") -> dict:
    """Un registro de 216 por transferencia y el pie: cantidad + 1 (cuenta el
    propio pie) y total en centavos. CRLF: se sube desde Windows."""
    lineas = [_linea_bna24(t, concepto) for t in transferencias]
    total = sum(Decimal(str(t["importe"])) for t in transferencias)
    lineas.append(str(len(lineas) + 1).rjust(5, "0")[-5:]
                  + str(_centavos(total)).rjust(17, "0")[-17:] + " " * 194)
    return {"contenido": "\r\n".join(lineas) + "\r\n"}


def generar_bna_empresa(transferencias: list[dict], concepto: str = "FAC") -> dict:
    """99 posiciones: CBU destino, importe en centavos, concepto, referencia.
    La cuenta débito se elige en el home banking al subirlo."""
    lineas = [_digitos(t["cbu_destino"]).ljust(22)[:22]
              + str(_centavos(t["importe"])).rjust(12, "0")[-12:]
              + (concepto or "FAC").ljust(3)[:3]
              + _referencia(t.get("nro_pago")).ljust(12)[:12]
              + " " * 50
              for t in transferencias]
    return {"contenido": "\r\n".join(lineas) + "\r\n"}


# ── ICBC ─────────────────────────────────────────────────────────────────────
# Encabezados exactos de la plantilla del banco: los compara y rechaza la
# planilla si no coinciden. CUIT, CBU y monto van como texto con quotePrefix
# (el apóstrofo de Excel): como número, el CBU pasa a notación científica y el
# CUIT pierde el cero, cuando alguien abre la planilla y la guarda.

ICBC_ENCABEZADOS = [
    "CUIL/CUIT/CDI",
    "CBU/CVU/ALIAS",
    "DESCRIPCION DEL CONTACTO (MAXIMO 50 CARACTERES)",
    "MONTO (SIN SEPARADORES DE MILES, CON SEPARADOR DECIMAL)",
    "COMENTARIOS (OPCIONAL, MAXIMO 100 CARACTERES)",
    "COMPROBANTE DE TRANSFERENCIA (OPCIONAL, INGRESE HASTA CINCO EMAILS A NOTIFICAR)",
]
_ICBC_ANCHOS = {"A": 30.7109375, "B": 30.7109375, "C": 50.7109375,
                "D": 20.7109375, "E": 50.7109375, "F": 150.7109375}
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def generar_icbc_xlsx(transferencias: list[dict], concepto: str = "") -> dict:
    """Hoja `Hoja1`, encabezado en la fila 1 y una fila por transferencia.
    Comentarios y emails vacíos, como en la planilla que el banco aceptó."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Hoja1"
    for letra, ancho in _ICBC_ANCHOS.items():
        ws.column_dimensions[letra].width = ancho
    for col, titulo in enumerate(ICBC_ENCABEZADOS, start=1):
        ws.cell(row=1, column=col, value=titulo)
    for fila, t in enumerate(transferencias, start=2):
        destino = (t["cbu_destino"] or "").strip()
        valores = [(_digitos(t.get("cuit")).zfill(11) if _digitos(t.get("cuit")) else "", True),
                   (destino, True),
                   (str(t.get("nombre") or "").strip()[:50], False),
                   (f"{Decimal(str(t['importe'])).quantize(_CENT, rounding=ROUND_HALF_UP):.2f}", True)]
        for col, (valor, texto) in enumerate(valores, start=1):
            celda = ws.cell(row=fila, column=col, value=valor)
            if texto and valor:
                celda.quotePrefix = True
    buf = io.BytesIO()
    wb.save(buf)
    return {"contenido": buf.getvalue()}


FORMATOS = {
    "bna24": {"nombre": "Banco Nación — BNA24", "banco": BANCO_BNA, "acepta_alias": False,
              "descripcion": "216 posiciones, con CBU ordenante y registro de pie",
              "generar": generar_bna24, "extension": "txt", "mimetype": "text/plain"},
    "bna_empresa": {"nombre": "Banco Nación — BNA Empresa", "banco": BANCO_BNA, "acepta_alias": False,
                    "descripcion": "99 posiciones, sin CBU ordenante ni registro de pie",
                    "generar": generar_bna_empresa, "extension": "txt", "mimetype": "text/plain"},
    "icbc_xlsx": {"nombre": "ICBC — transferencias masivas (Excel)", "banco": BANCO_ICBC, "acepta_alias": True,
                  "descripcion": "Planilla de seis columnas: CUIT, CBU o alias, nombre y monto, todo como texto",
                  "generar": generar_icbc_xlsx, "extension": "xlsx", "mimetype": XLSX},
}


def banco_de_cuenta(cuenta) -> str | None:
    """Código BCRA de la cuenta: el del banco cargado o los tres primeros
    dígitos del CBU, que son el mismo."""
    if not cuenta:
        return None
    codigo = (cuenta.get("banco_codigo") or "").strip()
    if codigo:
        return codigo.zfill(3)
    cbu = _digitos(cuenta.get("cbu"))
    return cbu[:3] if len(cbu) >= 3 else None


def formatos_del_banco(banco: str | None) -> dict:
    """Los formatos que sirven para ese banco (todos si no se sabe el banco)."""
    if not banco:
        return dict(FORMATOS)
    return {k: v for k, v in FORMATOS.items() if v["banco"] == banco}


def formato_de_cuenta(cuenta) -> str | None:
    """El formato habitual de la cuenta (`formato_transferencia`); si no tiene,
    o el guardado no es de su banco, el primero que sí lo es."""
    if not cuenta:
        return None
    permitidos = formatos_del_banco(banco_de_cuenta(cuenta))
    guardado = (cuenta.get("formato_transferencia") or "").strip()
    if guardado in permitidos:
        return guardado
    return next(iter(permitidos), None)


def generar(clave: str, transferencias: list[dict], concepto: str) -> tuple[bytes, str, str]:
    """(contenido en bytes, extensión, mimetype). Los .txt van en latin-1."""
    fmt = FORMATOS[clave]
    contenido = fmt["generar"](transferencias, concepto)["contenido"]
    if isinstance(contenido, str):
        contenido = contenido.encode("latin-1", errors="replace")
    return contenido, fmt["extension"], fmt["mimetype"]
