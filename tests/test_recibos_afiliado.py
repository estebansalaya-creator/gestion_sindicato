"""
test_recibos_afiliado.py — el recibo al afiliado por la cuota social
(recibos_afiliado.py): los meses que paga una transferencia, lo que AEDA ya
registró y el concepto. Sin base ni red.

    python tests/test_recibos_afiliado.py
"""
from __future__ import annotations

import datetime
import os
import sys
from decimal import Decimal

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
for k in ("SIND_DB_USER", "SIND_DB_PASS", "SIND_SECRET_KEY"):
    os.environ.setdefault(k, "prueba")

import recibos_afiliado as RA   # noqa: E402

fallos = []


def ok(cond, txt):
    print(("  OK   " if cond else "  FALLA ") + txt)
    if not cond:
        fallos.append(txt)


D = Decimal
d = datetime.date

print("Los meses")
ok(RA.sumar_meses("202611", 1) == "202612" and RA.sumar_meses("202612", 1) == "202701", "sumar meses (cambio de año)")
ok(RA.meses_justos(30000, 30000) == 1 and RA.meses_justos(60000, 30000) == 2 and RA.meses_justos("90000.00", D("30000")) == 3,
   "cuotas justas")
ok(RA.meses_justos(85000, 30000) == 0 and RA.meses_justos(25000, 30000) == 0, "no justas")
ok(RA.meses_justos(30000, None) == 0 and RA.meses_justos(0, 30000) == 0, "sin cuota o sin importe")
ok(RA.meses_justos(30000 * 13, 30000) == 0, "más de un año no es una transferencia de cuotas")
ok(RA.periodos(60000, d(2026, 11, 2), D("30000")) == [("202611", D("30000.00")), ("202612", D("30000.00"))],
   "dos cuotas: el mes de la acreditación y el siguiente")
ok(RA.periodos(85000, d(2026, 11, 2), D("30000")) == [("202611", D("85000.00"))], "no justas: un renglón por todo")
ok(RA.periodos(30000, d(2026, 12, 30), None) == [("202612", D("30000.00"))], "sin cuota definida: un renglón")

print("Lo que AEDA ya registró")
ordenes = [{"id_orden": 1, "nro_orden": "AEDA-OI-1", "fecha": d(2026, 10, 15)},
           {"id_orden": 2, "nro_orden": "AEDA-OI-2", "fecha": d(2026, 10, 31)}]
ok(RA.cubierta(d(2026, 10, 3), ordenes)["id_orden"] == 1, "la primera orden del mes que la incluye")
ok(RA.cubierta(d(2026, 10, 20), ordenes)["id_orden"] == 2, "una posterior del mismo mes")
ok(RA.cubierta(d(2026, 11, 2), ordenes) is None, "otro mes: sin orden")
ok(RA.cubierta(d(2026, 10, 31), ordenes[:1]) is None, "después de la última orden del mes: no está registrada")

print("El concepto")
det = [{"periodo": "202611", "descripcion": "Cuota social YMCA 2026-11 · PEREZ JUAN (CUIL 20111111112)"}]
ok(RA.concepto_de(det) == "Cuota social YMCA", "lo que va antes del mes")
ok(RA.concepto_de([{"periodo": None, "descripcion": "x"}]) is None, "sin mes, nada")

print()
print(f"{len(fallos)} falla(s)" if fallos else "Todo OK")
sys.exit(1 if fallos else 0)
