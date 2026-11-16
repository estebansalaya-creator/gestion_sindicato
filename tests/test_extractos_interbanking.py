"""
test_extractos_interbanking.py — el «Extracto de Cuenta» de Interbanking en
Excel (extractos_bancarios.py): se reconoce, se lee la cuenta, los movimientos,
el CUIT propio y los saldos de cierre. Arma un .xlsx de prueba con la forma del
real (datos inventados). Sin base ni red.

    python tests/test_extractos_interbanking.py
"""
from __future__ import annotations

import datetime
import io
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
for k in ("SIND_DB_USER", "SIND_DB_PASS", "SIND_SECRET_KEY"):
    os.environ.setdefault(k, "prueba")

import openpyxl                  # noqa: E402

import extractos_bancarios as EB  # noqa: E402

fallos = []


def ok(cond, txt):
    print(("  OK   " if cond else "  FALLA ") + txt)
    if not cond:
        fallos.append(txt)


PROPIO = "30111111118"
CABECERA = ["Concepto/Cod.Op.", "Fecha", "Comprobante", "Sucursal", "Importe", "Descripción",
            "Cod.Op.Bco.", "CUIT", "Denominación", "Saldo"]


def reporte(movs, inicial=1000.0, final=None, cuenta="CC $ 00.020.491/18") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "principal"
    for fila in (["Extracto de Cuenta"], [], ["Banco", "NACION"], [], [],
                 ["Tipo y Nro. de Cuenta", cuenta], ["Denominación", "UN SINDICATO"], [],
                 ["Fecha desde", "11/11/2026"], ["Fecha hasta", "12/11/2026"], [],
                 ["Saldo Inicial al 11/11/2026", inicial], [], CABECERA,
                 ["", "", "", "", "", "", "", "", "", inicial]):
        ws.append(fila)
    for m in movs:
        ws.append(m)
    if final is not None:
        ws.append(["", "", "", "", "", "", "", "", "Saldo Final: ", final])
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


MOVS = [
    ["CAJ.AUTOM", "11/11/2026", "434632", "7777 ", 300.0, "TRANSF.INT.DIST.TITULAR  ", "6231 ",
     "20342154191", "UNO/AFILIADO   ", ""],
    ["IMPUESTO AL CREDITO", "11/11/2026", "434676", "0085 ", -1.8, "GRAVAMEN LEY 25413 S/CRED",
     "6600 ", PROPIO, "UN SINDICATO", ""],
    ["CR.TR.", "12/11/2026", "000390552", "0085 ", 500.5, "CR.TR. CUOTAS-CUO", "", "30-71162419-4",
     "UNA EMPRESA SA", ""],
    ["DEB.TRAN", "12/11/2026", "434700", "0085 ", -100.0, "DEB.TRAN.INTERBMISMO TIT", "", PROPIO,
     "UN SINDICATO", ""],
]

print("Se reconoce")
texto = EB.interbanking_a_texto(reporte(MOVS, final=1698.7))
ok(texto is not None and EB.es_interbanking(texto), "el .xlsx de Interbanking")
ok(EB.detectar_banco("reporte_-_2026-11-13.xlsx", texto) == "IBK", "detectar_banco → IBK")
wb = openpyxl.Workbook()
wb.active.append(["Otra cosa", 1])
b = io.BytesIO()
wb.save(b)
ok(EB.interbanking_a_texto(b.getvalue()) is None, "otro Excel no")
ok(EB.interbanking_a_texto(b"no es un zip") is None, "un archivo roto no")

print("La cuenta")
ok(EB.cuentas_del_archivo("IBK", texto) == ["CC $ 00.020.491/18"], "Tipo y Nro. de Cuenta")

print("Los movimientos")
m = EB.parsear("IBK", texto, "r.xlsx")
ok(len(m) == 4, f"4 movimientos, sin las filas de saldo ({len(m)})")
ok(m[0]["fecham"] == datetime.date(2026, 11, 11) == m[0]["fechav"], "fecha")
ok(m[0]["credito"] == 300.0 and m[0]["debito"] is None, "importe positivo = crédito")
ok(m[1]["debito"] == 1.8 and m[1]["credito"] is None, "importe negativo = débito")
ok(m[2]["ref_nro"] == "390552", "comprobante sin ceros a la izquierda")
ok(m[0]["concepto"] == "TRANSF.INT.DIST.TITULAR", "la Descripción, recortada")
ok(m[0]["cuit"] == "20342154191" and m[2]["cuit"] == "30711624194", "CUIT de la contraparte (con o sin guiones)")
ok(m[1]["cuit"] is None and m[3]["cuit"] is None, "el CUIT propio (el del renglón Ley 25.413) se saca")
ok(all(x["origen"] is None for x in m), "el origen lo pone importar_extracto")

print("Los saldos")
ok(m[1]["saldo"] == 1298.2 and m[3]["saldo"] == 1698.7, "cierre de cada día en su último renglón")
ok(m[0]["saldo"] is None and m[2]["saldo"] is None, "los demás sin saldo")
m = EB.parsear("IBK", EB.interbanking_a_texto(reporte(MOVS, final=9999.0)), "r.xlsx")
ok([x["saldo"] for x in m] == [None, None, None, 9999.0], "si no cierra con el Saldo Final, solo el último")

print("Sin encabezado")
try:
    EB.parsear_interbanking("Extracto de Cuenta\nnada")
    ok(False, "tenía que avisar")
except EB.ErrorInterbanking:
    ok(True, "ErrorInterbanking")

print()
print("FALLAS:", len(fallos))
sys.exit(1 if fallos else 0)
