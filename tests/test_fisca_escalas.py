"""
test_fisca_escalas.py — la lógica de las escalas salariales (fisca_escalas.py),
con datos inventados: sin base ni red.

    python tests/test_fisca_escalas.py
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal as D

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
for k in ("SIND_DB_USER", "SIND_DB_PASS", "SIND_SECRET_KEY"):
    os.environ.setdefault(k, "prueba")

import fisca_escalas as E   # noqa: E402

fallos = []


def ok(cond, txt):
    print(("  OK   " if cond else "  FALLA ") + txt)
    if not cond:
        fallos.append(txt)


print("Importes")
for t, v in [("506,404.46", "506404.46"), ("506.404,46", "506404.46"), ("$ 1.059.434,70", "1059434.70"),
             ("1,224,698.70", "1224698.70"), ("7512", "7512.00"), ("7.512", "7512.00"), ("7512,5", "7512.50"),
             ("  165,264.00 ", "165264.00")]:
    ok(E.numero(t) == D(v), f"{t!r} → {E.numero(t)}")
ok(E.numero("") is None and E.numero("abc") is None, "vacío y texto")

pegado = """Inicial $ 506,404.46
1 año $ 519,138.74
2 años $ 530.519,14
Almuerzo $ 7,512.00"""
ok(E.importes_de(pegado) == [D("506404.46"), D("519138.74"), D("530519.14"), D("7512.00")],
   "pegado: solo importes con centavos, «1 año» no cuenta")

print("Períodos")
ok(E.periodo_de("2026-10") == "202610" and E.periodo_de("202613") is None, "período del formulario")
ok(E.mes_anterior("202601") == "202512" and E.mes_anterior("202610") == "202609", "mes anterior")

print("Controles")
base = [D(100 + i) for i in range(36)]
nueva = [(b * D("1.05")).quantize(D("0.01")) for b in base]
f, raros = E.factor(base, nueva)
ok(abs(f - D("1.05")) < D("0.0001") and not raros, "sube parejo 5 %")
mal = list(nueva)
mal[29] = D("96.05")  # como AEDA 2022-01: un número mal copiado
f, raros = E.factor(base, mal)
ok(raros == [29], f"se despega la antigüedad 29: {raros}")
ok(E.bajan(mal) == [29], "y además baja respecto de 28")
ok(E.bajan(nueva) == [], "una escala bien no baja")
ok(E.conformado(D("506404.46"), D("7512")) == D("671668.46"), "conformado de enero 2025 = la circular")

print()
if fallos:
    print(f"{len(fallos)} FALLAS")
    sys.exit(1)
print("Todo OK")
