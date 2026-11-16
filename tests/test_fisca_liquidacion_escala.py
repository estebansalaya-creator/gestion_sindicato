"""
test_fisca_liquidacion_escala.py — el activo sin DDJJ se liquida con el conformado
de la escala salarial (fisca_liquidacion.armar, pedido del 16/11/2026), con datos
inventados: sin base ni red.

    python tests/test_fisca_liquidacion_escala.py
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

import fisca_liquidacion as FL   # noqa: E402

fallos = []


def ok(cond, txt):
    print(("  OK   " if cond else "  FALLA ") + txt)
    if not cond:
        fallos.append(txt)


D = Decimal
d = datetime.date
CUIT = "30000000007"
OTRO = "30500000005"


def titular(i, cuil, alta=d(2010, 1, 1), baja=None):
    return {"id_afiliado": i, "cuil": cuil, "apellido_nombres": f"AFILIADO {i}", "fecha_alta": alta, "fecha_baja": baja}


def rel(cuil, cuit, inicio, antig=None, fin=None, estado="activa"):
    return {"cuil": cuil, "cuit_empleador": cuit, "estado": estado, "fecha_inicio": inicio, "fecha_fin": fin,
            "fecha_antiguedad": antig}


def escala(desde, hasta, basicos, almuerzo):
    return [{"periodo_desde": desde, "periodo_hasta": hasta, "antiguedad": i, "basico": D(b), "almuerzo": D(almuerzo)}
            for i, b in enumerate(basicos)]


BAS = [str(1000 + 10 * i) for i in range(36)]
ESCALAS = escala("202404", "202404", BAS, "100") + escala("202412", None, [str(D(b) * 2) for b in BAS], "200")

padron = {"titulares": [titular(1, "20111111112"), titular(2, "20222222223"), titular(3, "20333333334"),
                        titular(4, "20444444445"), titular(5, "20555555556")],
          "relaciones": [
              rel("20111111112", CUIT, d(2015, 3, 1)),                  # en la DDJJ
              rel("20222222223", CUIT, d(2020, 5, 1), antig=d(2014, 4, 30)),  # sin DDJJ, antigüedad por DDJJ
              rel("20333333334", CUIT, None),                           # sin DDJJ, sin fecha → Inicial
              rel("20444444445", CUIT, d(1980, 1, 1)),                  # sin DDJJ, 44 años → tope 35
              rel("20555555556", CUIT, d(2023, 6, 1)),                  # en la DDJJ en cero
          ]}
ddjj = [{"periodo": "202404", "cuil": "20111111112", "cuit": CUIT, "rem5": D("500000")},
        {"periodo": "202404", "cuil": "20555555556", "cuit": CUIT, "rem5": D("0")}]
alic = D("2.50")

print("Abril 2024, con escala")
e = FL.armar("202404", padron, ddjj, alic, ESCALAS)[CUIT]
L = {l["cuil"]: l for l in e["lineas"]}
ok(L["20111111112"]["fuente"] == "ddjj" and L["20111111112"]["remuneracion"] == D("500000"), "el de la DDJJ no cambia")
ok(L["20555555556"]["fuente"] == "ddjj" and L["20555555556"]["cuota"] == 0, "lo declarado en cero en la DDJJ queda en cero")
l2 = L["20222222223"]
ok(l2["fuente"] == "escala" and l2["antiguedad"] == 10, f"antigüedad desde fecha_antiguedad, años cumplidos al 30/04: {l2.get('antiguedad')}")
ok(l2["remuneracion"] == D("1100") + D("100") * 22, f"conformado = básico + almuerzo × 22: {l2['remuneracion']}")
ok(l2["cuota"] == D("82.50"), f"cuota al 2,5 %: {l2['cuota']}")
ok(L["20333333334"]["fuente"] == "escala" and L["20333333334"]["antiguedad"] == 0, "sin fecha: Inicial")
ok(L["20444444445"]["antiguedad"] == 35, "tope de 35 años")
ok(e["con_ddjj"] == 2 and e["por_escala"] == 3, f"con DDJJ 2, por escala 3: {e['con_ddjj']}, {e['por_escala']}")
ok(e["afiliados"] == 4, f"liquidados = con cuota: {e['afiliados']}")
ok(e["importe"] == sum(l["cuota"] for l in e["lineas"]), "el importe suma los renglones")
ok("escala salarial" in (FL._nota(e, None) or ""), "la nota lo dice")

print("Antigüedad al último día del período")
ok(FL.anios_cumplidos(d(2014, 4, 30), d(2024, 4, 30)) == 10, "cumple el último día: cuenta")
ok(FL.anios_cumplidos(d(2014, 5, 1), d(2024, 4, 30)) == 9, "cumple al mes siguiente: no")
ok(FL.anios_cumplidos(d(2025, 1, 1), d(2024, 4, 30)) == 0, "fecha posterior: 0")

print("Sin escala en el período")
e = FL.armar("202405", padron, [dict(f, periodo="202405") for f in ddjj], alic, ESCALAS)[CUIT]
L = {l["cuil"]: l for l in e["lineas"]}
ok(L["20222222223"]["fuente"] == "sin_ddjj" and L["20222222223"]["cuota"] == 0, "queda sin_ddjj en cero")
ok(e["por_escala"] == 0, "nadie por escala")

print("Escala abierta (desde 202412)")
e = FL.armar("202603", padron, [], alic, ESCALAS)[CUIT]
L = {l["cuil"]: l for l in e["lineas"]}
ok(L["20222222223"]["remuneracion"] == D("2220") + D("200") * 22,
   f"la vigente abierta, 11 años: {L['20222222223']['remuneracion']}")
ok(e["con_ddjj"] == 0 and e["por_escala"] == 5, "ninguno en la DDJJ: todos por escala")

print("Antigüedad con otro empleador no cuenta")
padron2 = {"titulares": [titular(9, "20999999990")],
           "relaciones": [rel("20999999990", OTRO, d(2000, 1, 1), estado="inactiva", fin=d(2019, 12, 31)),
                          rel("20999999990", CUIT, d(2022, 1, 1))]}
e = FL.armar("202404", padron2, [], alic, ESCALAS)[CUIT]
ok(e["lineas"][0]["antiguedad"] == 2, f"solo la de ESE empleador: {e['lineas'][0]['antiguedad']}")

print("Sin escalas (como antes)")
e = FL.armar("202404", padron, ddjj, alic)[CUIT]
ok(all(l["fuente"] != "escala" for l in e["lineas"]), "sin escalas no cambia nada")

print()
print("FALLAS: " + ", ".join(fallos) if fallos else "Todo bien.")
sys.exit(1 if fallos else 0)
