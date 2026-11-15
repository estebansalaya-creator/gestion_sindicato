"""
Pruebas de afiliado_aportes.py (sin base ni Railway): la diferencia por la
situación del empleador, el armado por período y la solapa del grupo.
python tests/test_afiliado_aportes.py
"""
import os
import sys
from decimal import Decimal as D

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import afiliado_aportes as AA  # noqa: E402
import contable_oseda  # noqa: E402

ok = fallos = 0


def v(cond, msg):
    global ok, fallos
    ok, fallos = (ok + 1, fallos) if cond else (ok, fallos + 1)
    print(("  OK   " if cond else "  FALLA ") + msg)


print("\nDiferencia (padron._fila_diferencia de gestion_adm)")
r = AA.fila_diferencia({"aporte_decl": D("100"), "contrib_decl": D("200"), "emp_decl": D("1000"), "emp_deuda": D("0.45")})
v(r["total_a_pagar"] == D("300") and r["diferencia"] == 0 and r["total_pagado"] == D("300"),
  "el empleador debe menos de $ 1,50: no hay diferencia y pagó todo")
r = AA.fila_diferencia({"aporte_decl": D("100"), "contrib_decl": D("200"), "emp_decl": D("1000"), "emp_deuda": D("250")})
v(r["diferencia"] == D("75.00") and r["total_pagado"] == D("225.00"), "debe el 25 % de su nómina: al afiliado le toca el 25 %")
r = AA.fila_diferencia({"aporte_decl": D("100"), "contrib_decl": D("200"), "emp_decl": D("1000"), "emp_deuda": D("5000")})
v(r["diferencia"] == D("300.00") and r["total_pagado"] == 0, "deuda mayor que lo declarado: tope en lo del afiliado")
r = AA.fila_diferencia({"aporte_decl": D("100"), "contrib_decl": D("200"), "total_percibido": D("290")})
v(r["diferencia"] == D("10") and r["total_pagado"] == D("290"), "sin el empleador en f_deuda_empresa: contra lo prorrateado")
r = AA.fila_diferencia({"aporte_decl": D("100"), "contrib_decl": D("200"), "total_percibido": D("299")})
v(r["diferencia"] == 0, "contra lo prorrateado, $ 1 es redondeo")
r = AA.fila_diferencia({"monotributo": D("5000"), "total_percibido": D("5000")})
v(r["total_a_pagar"] == 0 and r["diferencia"] == D("-5000"), "monotributo sin DDJJ: lo pagado sin nada declarado (como OSEDA)")

print("\nPor período")
CUIL, CONY = "20111111112", "27222222223"
datos = {
    "ddjj": [
        {"cuil": CUIL, "cuit": "30000000001", "periodo": "202609", "remosimp": D("1000"), "rem5": D("900"), "aporte_decl": D("30"), "contrib_decl": D("60")},
        {"cuil": CUIL, "cuit": "30000000002", "periodo": "202609", "remosimp": D("500"), "rem5": D("500"), "aporte_decl": D("15"), "contrib_decl": D("30")},
        {"cuil": CUIL, "cuit": "30000000001", "periodo": "202608", "remosimp": D("1000"), "rem5": D("900"), "aporte_decl": D("30"), "contrib_decl": D("60")},
        {"cuil": CUIL, "cuit": "30000000001", "periodo": "201901", "remosimp": D("10"), "rem5": D("10"), "aporte_decl": D("1"), "contrib_decl": D("2")},
    ],
    "transferencias": [
        {"cuil": CUIL, "cuit": "30000000001", "periodo": "202609", "aporte_perc": D("30"), "contrib_perc": D("60"), "total_percibido": D("90"), "monotributo": D("0")},
        {"cuil": CONY, "cuit": CONY, "periodo": "202609", "aporte_perc": D("0"), "contrib_perc": D("0"), "total_percibido": D("4000"), "monotributo": D("4000")},
    ],
    "deuda_empresa": {("30000000002", "202609"): {"emp_decl": D("4500"), "emp_deuda": D("4500")}},
    "empresas": {"30000000001": "UNO SA", "30000000002": "DOS SA"},
}
cuotas = {(CUIL, "30000000001", "202609"): D("22.50")}
ap = AA.aportes(CUIL, datos, cuotas, datos["empresas"])
p = ap["detalle"][0]
v([r["periodo"] for r in ap["detalle"]] == ["202609", "202608", "201901"], "del período más nuevo al más viejo")
v(p["remuneracion"] == D("1500") and p["rem5"] == D("1400") and p["total_a_pagar"] == D("135"),
  "dos empleadores en el período: se suman")
v(p["diferencia"] == D("45.00") and p["total_pagado"] == D("90"), "debe solo el que no pagó (su parte entera)")
v([e["cuit"] for e in p["empleadores_det"]] == ["30000000002", "30000000001"]
  and [e["liquidada"] for e in p["empleadores_det"]] == [False, True], "empleadores del período, con la cuota liquidada marcada")
v(p["cuota"] == D("22.50") and ap["totales"]["cuota"] == D("22.50"), "la cuota sindical del período y el total")
v(ap["totales"]["ddjj_desde"] == "201901" and ap["totales"]["ddjj_hasta"] == "202609", "declarado desde/hasta: toda la historia")
v(ap["totales"]["tipo"] == "Relación de dependencia", "con DDJJ: relación de dependencia")
ap2 = AA.aportes(CUIL, datos, {}, {}, limite=2)
v(ap2["totales"]["periodos"] == 2 and ap2["totales"]["primero"] == "202608" and ap2["totales"]["ddjj_desde"] == "201901",
  "los últimos N períodos en la grilla; el «desde» sigue siendo el de toda la historia")
apc = AA.aportes(CONY, datos, {}, {})
v(apc["totales"]["tipo"] == "Monotributo" and apc["totales"]["ddjj_desde"] is None, "monotributista sin DDJJ propia")

print("\nSolapa")


class Cur:
    def execute(self, sql, params=()):
        self.sql = sql

    def fetchall(self):
        return []


contable_oseda.aportes_de_cuiles = lambda cuiles: datos if CUIL in cuiles else {
    "ddjj": [], "transferencias": [], "deuda_empresa": {}, "empresas": {}}
tit = {"id_afiliado": 1, "cuil": CUIL, "cuil_titular": CUIL, "apellido_nombres": "TITULAR", "activo": 1}
cony = {"id_afiliado": 2, "cuil": CONY, "cuil_titular": CUIL, "apellido_nombres": "CONYUGE", "activo": 1, "parentesco": "Cónyuge"}
s = AA.solapa(Cur(), tit, [tit, cony])
v(s["es_titular"] and s["titular"]["cuil"] == CUIL and [o["cuil"] for o in s["otros"]] == [CONY] and s["propio"] is None,
  "titular: su grilla y la del familiar que aporta a su nombre")
v(s["conteo"] == 3 + 1, "el número de la solapa cuenta los períodos de todas las grillas")
s = AA.solapa(Cur(), cony, [tit, cony])
v(not s["es_titular"] and s["propio"]["cuil"] == CONY and s["otros"] == [], "familiar: primero lo propio, después el titular")
v(AA.solapa(Cur(), {"id_afiliado": 3, "cuil": "20333333334", "cuil_titular": "20333333334"}, []) is None,
  "sin DDJJ en el grupo: no hay solapa")

print(f"\n{ok} bien, {fallos} mal")
sys.exit(1 if fallos else 0)
