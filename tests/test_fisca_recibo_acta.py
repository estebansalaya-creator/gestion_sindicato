"""
test_fisca_recibo_acta.py — el recibo de fiscalización (fisca_recibo_acta.py) y
el número del talonario (recibos_talonario.py), con datos inventados: sin base ni red.

    python tests/test_fisca_recibo_acta.py
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

import fisca_recibo_acta as F   # noqa: E402
import recibos_talonario as RT  # noqa: E402

fallos = []
D = Decimal


def ok(cond, txt):
    print(("  OK   " if cond else "  FALLA ") + txt)
    if not cond:
        fallos.append(txt)


print("Número del recibo")
ok(RT.texto("X", 2, 1) == "X 0002-00000001", "X 0002-00000001")
ok(RT.texto("X", 91, 17835) == "X 0091-00017835", "el de AEDA, con el cobro_id")
ok(RT.texto("X", 1, None) is None, "sin número, nada")

print("Capital e interés")
# Acta: deuda 1.600 + intereses 300 = 1.900; acuerdo de 3 cuotas de 700 (financiación 200).
cap, inte = F.partir(D("700"), D("1600"), D("2100"))
ok((cap, inte) == (D("533.33"), D("166.67")), f"primera cuota: 533,33 + 166,67 ({cap} + {inte})")
cap, inte = F.partir(D("1400"), D("1066.67"), D("1400"))
ok((cap, inte) == (D("1066.67"), D("333.33")), "la que termina el acuerdo se lleva todo el capital que falta")
cap, inte = F.partir(D("700"), D("0"), D("1400"))
ok((cap, inte) == (D("0"), D("700")), "sin capital que falte (el empleador pagó los períodos), todo es interés")
cap, inte = F.partir(D("700"), D("900"), D("700"))
ok(cap == D("700") and inte == 0, "el capital nunca pasa el importe")

print("Capital a los períodos")
periodos = [{"periodo": "202506", "saldo": D("1000")}, {"periodo": "202507", "saldo": D("600")},
            {"periodo": "202508", "saldo": D("0")}]
ok(F.repartir_capital(D("533.33"), periodos) == [("202506", D("533.33"))], "al más viejo primero")
ok(F.repartir_capital(D("1200"), periodos) == [("202506", D("1000")), ("202507", D("200"))], "hasta el saldo de cada uno")
ok(F.repartir_capital(D("5000"), periodos) == [("202506", D("1000")), ("202507", D("600"))], "lo que sobra no se inventa")

print("Imputación a las cuotas")
hoy = datetime.date.today()
cuotas = [{"id": 1, "saldo": D("0")}, {"id": 2, "saldo": D("700")}, {"id": 3, "saldo": D("700")}]
ok(F.sugerir(cuotas, D("700")) == [(2, D("700"))], "la primera con saldo")
ok(F.sugerir(cuotas, D("1000")) == [(2, D("700")), (3, D("300"))], "lo que sobra, a la siguiente")

print()
print("Todo OK" if not fallos else f"{len(fallos)} FALLA(N)")
sys.exit(1 if fallos else 0)
