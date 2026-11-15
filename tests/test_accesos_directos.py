"""
Pruebas de accesos_directos.py (sin base): el módulo de cada acceso y el
armado de las cajas del panel de inicio.  python tests/test_accesos_directos.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import accesos_directos as A  # noqa: E402

ok = fallos = 0


def v(cond, msg):
    global ok, fallos
    ok, fallos = (ok + 1, fallos) if cond else (ok, fallos + 1)
    print(("  OK   " if cond else "  FALLA ") + msg)


RAMAS = {1: {"id": 1, "padre_id": None, "nombre": "Fiscalización de Cuotas", "icono_svg": "<svg/>"},
         17: {"id": 17, "padre_id": 1, "nombre": "Fiscalización", "icono_svg": None},
         60: {"id": 60, "padre_id": None, "nombre": "Tesorería", "icono_svg": None},
         40: {"id": 40, "padre_id": 60, "nombre": "Pagos", "icono_svg": None},
         80: {"id": 80, "padre_id": 40, "nombre": "Reintegros", "icono_svg": None},
         7: {"id": 7, "padre_id": 8, "nombre": "A"}, 8: {"id": 8, "padre_id": 7, "nombre": "B"}}

print("\nMódulo de cada acceso")
filas = A.con_modulo([{"menu_id": 14, "padre_id": 17}, {"menu_id": 81, "padre_id": 80},
                      {"menu_id": 8, "padre_id": 1}, {"menu_id": 99, "padre_id": None},
                      {"menu_id": 5, "padre_id": 7}], RAMAS)
v(filas[0]["modulo"] == "Fiscalización de Cuotas" and filas[0]["modulo_icono"] == "<svg/>",
  "un nieto (Actas) cuelga del módulo de arriba, con su ícono")
v(filas[1]["modulo"] == "Tesorería", "un bisnieto (Solicitudes de Reintegro) también")
v(filas[2]["modulo_id"] == 1, "un hijo directo")
v(filas[3]["modulo"] == "General" and filas[3]["modulo_id"] == 0, "sin padre: General")
v(filas[4]["modulo"] in ("A", "B"), "un padre_id circular no se cuelga")

print("\nCajas del panel")
g = A.agrupar([{"menu_id": 81, "modulo_id": 60, "modulo": "Tesorería"},
               {"menu_id": 14, "modulo_id": 1, "modulo": "Fiscalización de Cuotas"},
               {"menu_id": 41, "modulo_id": 60, "modulo": "Tesorería"}])
v([x["modulo"] for x in g] == ["Tesorería", "Fiscalización de Cuotas"], "los módulos en el orden de su primera tarjeta")
v([a["menu_id"] for a in g[0]["items"]] == [81, 41], "las tarjetas de un módulo, en su orden")
v(A.agrupar([]) == [], "sin accesos, sin cajas")

print(f"\n{ok} bien, {fallos} mal")
sys.exit(1 if fallos else 0)
