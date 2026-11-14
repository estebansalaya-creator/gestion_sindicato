"""
Pruebas de fisca_intereses.py (sin base): tramos de tasa, interés resarcitorio
y vencimiento del F.931 por la regla.  python tests/test_fisca_intereses.py
"""
import datetime
import os
import sys
from decimal import Decimal as D

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fisca_intereses as FI  # noqa: E402

ok = fallos = 0


def v(cond, msg):
    global ok, fallos
    ok, fallos = (ok + 1, fallos) if cond else (ok, fallos + 1)
    print(("  OK   " if cond else "  FALLA ") + msg)


d = datetime.date
TASAS = [{"id": 1, "vigencia_desde": d(2025, 3, 1), "vigencia_hasta": d(2025, 6, 30), "resarcitorio": D("4"), "resolucion": "199/25"},
         {"id": 2, "vigencia_desde": d(2025, 7, 1), "vigencia_hasta": None, "resarcitorio": D("2.75"), "resolucion": "823/25"}]

print("\nInterés")
v(FI.interes(TASAS, 1000, d(2025, 6, 20), d(2025, 7, 10)) == D("22.50"), "10 días al 4 % y 10 al 2,75 %: 22,50")
v(FI.interes(TASAS, 1000, d(2025, 7, 9), d(2025, 7, 19)) == D("9.17"), "10 días al 2,75 %: 9,17")
v(FI.interes(TASAS, 1000, d(2025, 7, 9), d(2025, 7, 9)) == D("0.00"), "pagado el día del vencimiento: sin interés")
v(FI.interes(TASAS, 0, d(2025, 7, 9), d(2026, 7, 9)) == D("0.00"), "sin capital: sin interés")
t = FI.tramos(TASAS, d(2025, 6, 20), d(2025, 7, 10))
v(sum(x["dias"] for x in t) == 20 and [x["dias"] for x in t] == [10, 10], "los días se reparten sin perder el del cambio de tasa")
try:
    FI.tramos(TASAS, d(2025, 1, 1), d(2025, 3, 10))
    v(False, "sin tasa cargada avisa")
except ValueError:
    v(True, "sin tasa cargada avisa")

print("\nVencimiento del F.931 (regla)")


class Cal(FI.Calendario):
    def __init__(self, feriados=()):
        self.oficiales, self.feriados = {}, set(feriados)


c = Cal()
v(c.vencimiento("30111111110", "202609") == d(2026, 10, 9), "terminación 0: día 9")
v(c.vencimiento("30111111115", "202609") == d(2026, 10, 12), "terminación 5: día 10 (sábado) → lunes 12")
v(Cal([d(2026, 10, 12)]).vencimiento("30111111118", "202609") == d(2026, 10, 13), "terminación 8: 11 domingo, 12 feriado → 13")
v(c.vencimiento("30111111117", "202612") == d(2027, 1, 11), "diciembre vence en enero del año siguiente")
c.oficiales[("202609", "5")] = d(2026, 10, 13)
v(c.vencimiento("30111111115", "202609") == d(2026, 10, 13) and c.es_oficial("30111111115", "202609"), "la tabla manda sobre la regla")

print(f"\n{'Todo OK' if not fallos else f'{fallos} FALLA(S)'} ({ok} pruebas)")
sys.exit(1 if fallos else 0)
