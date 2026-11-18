"""
test_elecciones.py — las reglas de las elecciones (elecciones.py), con datos
inventados: sin base ni red.

    python tests/test_elecciones.py
"""
from __future__ import annotations

import datetime as dt
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
for k in ("SIND_DB_USER", "SIND_DB_PASS", "SIND_SECRET_KEY"):
    os.environ.setdefault(k, "prueba")

import elecciones as E   # noqa: E402

fallos = []


def ok(cond, txt):
    print(("  OK   " if cond else "  FALLA ") + txt)
    if not cond:
        fallos.append(txt)


D = dt.date

print("Restar meses")
ok(E.restar_meses(D(2026, 11, 18), 6) == D(2026, 5, 18), "18/11/2026 − 6 meses = 18/05/2026")
ok(E.restar_meses(D(2026, 3, 31), 1) == D(2026, 2, 28), "31/03 − 1 mes = 28/02 (último día)")
ok(E.restar_meses(D(2024, 3, 31), 1) == D(2024, 2, 29), "31/03/2024 − 1 mes = 29/02 (bisiesto)")
ok(E.restar_meses(D(2026, 1, 15), 13) == D(2024, 12, 15), "15/01/2026 − 13 meses = 15/12/2024")
ok(E.restar_meses(D(2026, 12, 10), 0) == D(2026, 12, 10), "0 meses: la misma fecha")

el = {"id": 1, "estado": "vigente", "padron_generado": dt.datetime(2026, 11, 1), "fecha_votacion": D(2026, 12, 4),
      "fecha_padron": D(2026, 11, 30), "antiguedad_meses": 6}

print("Antigüedad")
ok(E.corte_antiguedad(el) == D(2026, 5, 30), "corte 30/11 con 6 meses: alta hasta el 30/05")
ok(E.corte_antiguedad({**el, "antiguedad_meses": 0}) is None, "sin antigüedad: no hay corte")

print("Cuándo se marca")
ok(E.puede_marcar(el, D(2026, 12, 4), False) == (True, None), "el día de la votación, cualquiera")
ok(not E.puede_marcar(el, D(2026, 12, 3), False)[0], "el día anterior, no")
r = E.puede_marcar(el, D(2026, 12, 5), True)
ok(r[0] and "ya pasó" in r[1], "otro día, el Administrador sí, con el aviso")
ok(not E.puede_marcar({**el, "estado": "cerrada"}, D(2026, 12, 4), True)[0], "cerrada: nadie")
ok(not E.puede_marcar({**el, "estado": "anulada"}, D(2026, 12, 4), True)[0], "anulada: nadie")
ok(not E.puede_marcar({**el, "padron_generado": None}, D(2026, 12, 4), True)[0], "sin padrón: nadie")

print("Búsqueda")
ok(E.partir_busqueda("28.123.456") == ("28123456", []), "documento con puntos")
ok(E.partir_busqueda("20-28123456-3") == ("20281234563", []), "CUIL con guiones")
ok(E.partir_busqueda(" 154 ") == ("154", []), "número de orden")
ok(E.partir_busqueda("perez  juan") == ("", ["perez", "juan"]), "apellido y nombre")
ok(E.partir_busqueda("a") == ("", []), "una letra sola no busca")

print("Por qué no está")
base = {"cod_parentesco": 0, "activo": 1, "fecha_baja": None, "fecha_alta": D(2020, 1, 1)}
ok("familiar" in E.por_que_no_esta({**base, "cod_parentesco": 3}, el), "familiar a cargo")
ok("familiar" in E.por_que_no_esta({**base, "cod_parentesco": "3"}, el), "familiar con el código en texto")
ok("baja al corte" in E.por_que_no_esta({**base, "activo": 0, "fecha_baja": D(2026, 10, 1)}, el), "baja antes del corte")
ok("de baja" in E.por_que_no_esta({**base, "activo": 0}, el), "inactivo sin fecha de baja")
ok("posterior al corte" in E.por_que_no_esta({**base, "fecha_alta": D(2026, 12, 1)}, el), "alta después del corte")
ok("antigüedad" in E.por_que_no_esta({**base, "fecha_alta": D(2026, 8, 1)}, el), "sin la antigüedad")
ok("fecha de alta" in E.por_que_no_esta({**base, "fecha_alta": None}, el), "sin alta y con antigüedad pedida")
ok("agregar" in E.por_que_no_esta(base, el), "cumple todo: no estaba al generarlo")
ok(E.es_titular(0) and E.es_titular("0") and E.es_titular(None) and not E.es_titular(2), "es_titular")

print("Condiciones del padrón")
w, p = E._condiciones(el)
ok("a.cod_parentesco = 0" in w and len(p) == 3 and p[2] == D(2026, 5, 30), "titulares, corte y antigüedad")
w, p = E._condiciones({**el, "antiguedad_meses": 0})
ok(len(p) == 2 and "a.fecha_alta IS NULL OR" in w, "sin antigüedad: sin fecha de alta también entra")

print("Resumen")
ok(E.resumen(200, 37) == {"padron": 200, "votaron": 37, "faltan": 163, "porc": 18.5}, "participación")
ok(E.resumen(0, 0)["porc"] == 0.0, "padrón vacío")

print()
print("OSEDA en el padrón electoral")
fs = [{"cuil": "20111111112"}, {"cuil": "27222222223"}, {"cuil": "20333333334"}, {"cuil": "20444444445"}, {"cuil": None}]
E.marcar_oseda(fs, {"20111111112": {"vigente": True, "titular": True, "fecha_baja": None},
                    "27222222223": {"vigente": True, "titular": False, "fecha_baja": None},
                    "20333333334": {"vigente": False, "titular": True, "fecha_baja": D(2025, 3, 31)}})
ok([f["oseda"] for f in fs] == ["titular", "familiar", "baja", "no", "no"], "titular, familiar, de baja, no está, sin CUIL")
ok(fs[2]["oseda_baja"] == D(2025, 3, 31) and fs[0]["oseda_baja"] is None, "la fecha de baja solo en el de baja")
ok(all(E.OSEDA_ESTADOS[f["oseda"]][2] in ("si", "no") for f in fs), "cada estado tiene su valor de filtro")
E.marcar_oseda(fs, None)
ok(all(f["oseda"] is None for f in fs), "sin consulta (Railway caído): sin dato, no «No»")

if fallos:
    print(f"{len(fallos)} FALLAS")
    sys.exit(1)
print("Todo bien.")
