"""
test_ben_entregas.py — el padrón de entrega de una campaña (ben_entregas.py),
con datos inventados: sin base ni red.

    python tests/test_ben_entregas.py
"""
from __future__ import annotations

import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
for k in ("SIND_DB_USER", "SIND_DB_PASS", "SIND_SECRET_KEY"):
    os.environ.setdefault(k, "prueba")

import ben_entregas as E   # noqa: E402

fallos = []


def ok(cond, txt):
    print(("  OK   " if cond else "  FALLA ") + txt)
    if not cond:
        fallos.append(txt)


print("Quién retira")
ok(E.leer_retiro({}) == (None, None), "vacío: lo retira el afiliado")
ok(E.leer_retiro({"retiro_nombre": "  gomez   ana ", "retiro_documento": "28.123.456"}) == ("gomez ana", "28123456"),
   "nombre sin espacios de más, documento sin puntos")
ok(E.leer_retiro({"retiro_nombre": "GOMEZ ANA"}) == ("GOMEZ ANA", None), "nombre sin documento: vale")
try:
    E.leer_retiro({"retiro_documento": "28123456"})
    ok(False, "documento sin nombre: se rechaza")
except E.ErrorEntrega:
    ok(True, "documento sin nombre: se rechaza")
ok(len(E.leer_retiro({"retiro_nombre": "x" * 300})[0]) == 150, "el nombre se corta en 150")

print("Detalle del movimiento")
ok(E.detalle_retiro(12, None, None) == "Orden 12", "lo retiró el afiliado")
ok(E.detalle_retiro(12, "GOMEZ ANA", "28123456") == "Orden 12: retiró GOMEZ ANA (DNI 28123456)", "otra persona, con DNI")
ok(E.detalle_retiro(3, "GOMEZ ANA", None) == "Orden 3: retiró GOMEZ ANA", "otra persona, sin DNI")

print("Resumen")
ok(E.resumen(400, 100) == {"padron": 400, "entregados": 100, "faltan": 300, "porc": 25.0}, "cuántos retiraron")
ok(E.resumen(0, 0)["porc"] == 0.0, "padrón vacío")
ok(E.solo_digitos("20-28123456-3") == "20281234563", "CUIL con guiones")

if fallos:
    print(f"{len(fallos)} FALLAS")
    sys.exit(1)
print("Todo bien.")
