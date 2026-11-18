"""
test_fisca_recibos.py — la lógica de la emisión de recibos (fisca_recibos.py)
con datos inventados: sin base ni red.

    python tests/test_fisca_recibos.py
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

import fisca_recibos as R   # noqa: E402

fallos = []


def ok(cond, txt):
    print(("  OK   " if cond else "  FALLA ") + txt)
    if not cond:
        fallos.append(txt)


D = Decimal
F = datetime.date(2026, 11, 5)

print("El importe en letras")
for v, esperado in [
    (1, "UNO CON 00/100"), (21, "VEINTIUNO CON 00/100"), (100, "CIEN CON 00/100"), (101, "CIENTO UNO CON 00/100"),
    (1000, "MIL CON 00/100"), (21000, "VEINTIÚN MIL CON 00/100"), (31000, "TREINTA Y UN MIL CON 00/100"),
    (100000, "CIEN MIL CON 00/100"), (1000000, "UN MILLÓN CON 00/100"),
    (2500000.5, "DOS MILLONES QUINIENTOS MIL CON 50/100"),
    (448156.31, "CUATROCIENTOS CUARENTA Y OCHO MIL CIENTO CINCUENTA Y SEIS CON 31/100"),
    (1166700, "UN MILLÓN CIENTO SESENTA Y SEIS MIL SETECIENTOS CON 00/100"),
    (21001001, "VEINTIÚN MILLONES MIL UNO CON 00/100"), (0.07, "CERO CON 07/100"),
    (15, "QUINCE CON 00/100"), (16, "DIECISÉIS CON 00/100"), (222, "DOSCIENTOS VEINTIDÓS CON 00/100"),
]:
    ok(R.en_letras(v) == esperado, f"{v} → {R.en_letras(v)}")

print("El empleador")
emp = {"30709404047": "NELIDA SA", "30696906420": "RMO SA", "30652980623": "UNO SRL", "30710216319": "DOS SA",
       "30711111118": "TRES SA"}
rel = {"20081898201": ["30696906420"], "20123456786": ["30652980623", "30710216319"]}
afi = {"27000000006": "PEREZ JUAN", "20000000001": "GOMEZ ANA", "20081898201": "RELACIONADO TAMBIEN AFILIADO"}
r = R.resolver_empleador("30709404047", emp, rel, afi)
ok(r["como"] == "mismo" and r["cuit"] == "30709404047", "mismo CUIT")
r = R.resolver_empleador("20081898201", emp, rel, afi)
ok(r["como"] == "relacionado" and r["cuit"] == "30696906420", "CUIT relacionado")
r = R.resolver_empleador("20123456786", emp, rel, afi)
ok(r["como"] == "varios" and not r["cuit"] and len(r["opciones"]) == 2, "paga por dos empleadores: se elige")
r = R.resolver_empleador("27000000006", emp, rel, afi)
ok(r["como"] == "afiliado" and r["cuit"] is None and r["nombre"] == "PEREZ JUAN",
   "afiliado: no se relaciona con su empleador (otro concepto)")
r = R.resolver_empleador("20081898201", emp, rel, afi)
ok(r["como"] == "relacionado" and r["cuit"] == "30696906420", "un afiliado cargado como relacionado sí paga por la empresa")
ok(R.resolver_empleador("27000000006", emp, rel)["como"] == "sin", "sin padrón, sin identificar")
ok(R.resolver_empleador("", emp, rel, afi)["como"] == "sin", "sin CUIT")
ok(R.resolver_empleador("33707651259", emp, rel, afi)["como"] == "sin", "CUIT desconocido")
pag = {"23238151694": "27000000006", "30709404047": "20000000001", "20999999995": "20888888886"}
r = R.resolver_empleador("23238151694", emp, rel, afi, pag)
ok(r["como"] == "afiliado" and r["cuil"] == "27000000006" and r["nombre"] == "PEREZ JUAN" and r.get("por_otro"),
   "paga por un afiliado (fisca_cuit_afiliado): el CUIL es el del afiliado")
ok(R.resolver_empleador("27000000006", emp, rel, afi, pag)["cuil"] == "27000000006", "el afiliado mismo: su CUIL")
ok(R.resolver_empleador("30709404047", emp, rel, afi, pag)["como"] == "mismo", "una empresa no pasa a ser de un afiliado")
ok(R.resolver_empleador("20999999995", emp, rel, afi, pag)["como"] == "sin", "paga por alguien que no está en el padrón: sin identificar")
# Dos asociaciones, una por concepto: 20081898201 es afiliado y además paga la cuota sindical de RMO SA.
r = R.resolver_empleador("20081898201", emp, rel, afi, pag, social=True)
ok(r["como"] == "afiliado" and r["cuil"] == "20081898201", "cuota social: la del afiliado, aunque pague la sindical de una empresa")
ok(R.resolver_empleador("20081898201", emp, rel, afi, pag, social=False)["cuit"] == "30696906420",
   "cuota sindical: la de la empresa con la que está asociado")
rel2 = {**rel, "23238151694": ["30709404047"]}
ok(R.resolver_empleador("23238151694", emp, rel2, afi, pag, social=True)["cuil"] == "27000000006",
   "el mismo CUIT con las dos asociaciones: lo redondo va al afiliado")
ok(R.resolver_empleador("23238151694", emp, rel2, afi, pag, social=False)["cuit"] == "30709404047",
   "… y lo demás a la empresa")
import datetime as _dt
from decimal import Decimal as _D
cuotas = [("202609", _D("30000")), ("202604", _D("25000"))]
emp_de = {"27000000006": "30711111118"}
a_ = R.resolver_empleador("27000000006", emp, rel, afi)
r = R.por_su_empleador(a_, _D("34304.12"), _dt.date(2026, 10, 14), cuotas, emp_de, emp)
ok(r["como"] == "por_afiliado" and r["cuit"] == "30711111118" and r["cuil"] == "27000000006",
   "afiliado con un importe que no es cuota social: la cuota sindical de su empleador")
ok(R.por_su_empleador(a_, _D("60000"), _dt.date(2026, 10, 14), cuotas, emp_de, emp)["como"] == "afiliado",
   "dos cuotas sociales: sigue siendo del afiliado (Beneficios)")
ok(R.por_su_empleador(a_, _D("25000"), _dt.date(2026, 10, 14), cuotas, emp_de, emp)["como"] == "afiliado",
   "la cuota anterior (25.000) también es cuota social")
for imp in ("55000", "5000", "85000"):
    ok(R.por_su_empleador(a_, _D(imp), _dt.date(2026, 10, 14), cuotas, emp_de, emp)["como"] == "afiliado",
       f"{imp}: redondo a la medida de la cuota (5.000), cuota social")
for imp in ("23872.10", "137836.08", "32610"):
    ok(R.por_su_empleador(a_, _D(imp), _dt.date(2026, 10, 14), cuotas, emp_de, emp)["como"] == "por_afiliado",
       f"{imp}: no es redondo, cuota sindical de su empleador")
ok(R.por_su_empleador(a_, _D("400000"), _dt.date(2026, 10, 14), cuotas, emp_de, emp)["como"] == "por_afiliado",
   "más de 12 cuotas: no es la cuota social")
ok(R.por_su_empleador(a_, _D("25000"), _dt.date(2026, 3, 14), cuotas, emp_de, emp)["como"] == "por_afiliado",
   "antes del convenio no hay cuota social: es cuota sindical")
ok(R.por_su_empleador(a_, _D("34304.12"), _dt.date(2026, 10, 14), cuotas, {}, emp)["como"] == "afiliado",
   "sin empleador en Empleadores: sigue como afiliado")
ok(R.resolver_empleador("20081898201", emp, {"20081898201": ["30999999990"]}, {})["como"] == "sin",
   "relacionado con un CUIT que no está en Empleadores")

print("Los períodos")
ok(R.periodo_anterior(F) == "202610", "el mes anterior a la acreditación")
ok(R.periodo_anterior(datetime.date(2026, 1, 3)) == "202512", "enero paga diciembre")
ok(R.distribuir(D("1000"), F, {}) == [("202610", D("1000.00"))], "sin liquidaciones: al mes anterior (sin liquidar)")
ok(R.distribuir(D("1000"), F, {"202610": D("1000")}) == [("202610", D("1000.00"))], "exacto al mes anterior")
ok(R.distribuir(D("700"), F, {"202610": D("1000"), "202605": D("700")}) == [("202605", D("700.00"))],
   "exacto a otro período")
ok(R.distribuir(D("700"), F, {"202609": D("700"), "202605": D("700")}) == [("202609", D("700.00"))],
   "dos exactos: el más cercano al mes anterior")
ok(R.distribuir(D("1500"), F, {"202610": D("1000"), "202605": D("300"), "202601": D("100")})
   == [("202601", D("100.00")), ("202605", D("300.00")), ("202610", D("1100.00"))],
   "el mes anterior hasta su saldo, lo que sobra a lo más viejo y el resto al mes")
ok(R.distribuir(D("500"), F, {"202610": D("1000")}) == [("202610", D("500.00"))], "pago parcial del mes")
ok(R.distribuir(D("500"), F, {"202610": D("0"), "202603": D("200")})
   == [("202603", D("200.00")), ("202610", D("300.00"))], "el mes ya pagado: a la deuda vieja")
ok(R.distribuir(D("500"), F, {"202609": D("800")}) == [("202610", D("500.00"))],
   "el mes anterior sin liquidar: va entero ahí, no a la deuda vieja")
ok(R.distribuir(D("500"), F, {"202610": D("100"), "202611": D("900")}) == [("202610", D("500.00"))],
   "nunca a un período posterior")
s = R.distribuir(D("1234.56"), F, {"202610": D("1000.10"), "202602": D("50.05")})
ok(sum(i for _, i in s) == D("1234.56"), "siempre suma el importe")

print("¿Ya tiene recibo?")


def cred(i, fecha, imp, ref="1", cuits=()):
    return {"id": i, "fecham": fecha, "importe": D(imp), "ref_nro": ref, "cuits": set(cuits), "estado": "pendiente",
            "recibo": None}


def lib(i, fecha, imp, cuit=None, ref=None, orden=None, conc=False):
    return {"id_dc": i, "id_orden": orden or i, "nro_orden": f"AEDA-RC-{i}", "fecha": fecha, "importe": D(imp),
            "cuit": cuit, "ref_aeda": ref, "conciliado": conc}


c = [cred(1, F, "100", "4315666", ["33710892399"]), cred(2, F, "100", "999", ["30000000001"]),
     cred(3, F, "250", "5"), cred(4, F, "77", "6"), cred(5, F, "500", "7", ["30709404047"])]
l = [lib(10, F, "100", ref="4315666"), lib(11, F - datetime.timedelta(days=2), "100", cuit="30000000001"),
     lib(12, F, "250"), lib(13, F, "77", conc=True), lib(14, F, "500", cuit="30709404047", orden=99)]
R.emparejar(c, {5: {"id_orden": 99, "nro_orden": "2611-00000001"}}, l)
ok(c[0]["estado"] == "ya_tiene" and c[0]["recibo"]["id_dc"] == 10, "por el comprobante de AEDA")
ok(c[1]["estado"] == "ya_tiene" and c[1]["recibo"]["id_dc"] == 11, "por CUIT e importe, dos días antes")
ok(c[2]["estado"] == "posible", "único con esa fecha e importe: a revisar")
ok(c[3]["estado"] == "pendiente", "lo del libro ya conciliado no cuenta")
ok(c[4]["estado"] == "emitido", "emitido desde el renglón")

c = [cred(1, F, "100", "1", ["30000000001"]), cred(2, F, "100", "2", ["30000000001"])]
l = [lib(10, F, "100", cuit="30000000001")]
R.emparejar(c, {}, l)
ok([x["estado"] for x in c].count("ya_tiene") == 1, "un renglón del libro sirve a una sola acreditación")

c = [cred(1, F, "100", "1", ["30000000001"])]
l = [lib(10, F - datetime.timedelta(days=3), "100", cuit="30000000001"),
     lib(11, F + datetime.timedelta(days=3), "100", cuit="30000000001")]
R.emparejar(c, {}, l)
ok(c[0]["estado"] == "pendiente", "dos igual de cerca: no se elige")

c = [cred(1, F, "100", "1", ["30000000001"])]
R.emparejar(c, {}, [lib(10, F - datetime.timedelta(days=40), "100", cuit="30000000001")])
ok(c[0]["estado"] == "pendiente", "fuera de la ventana de días")

c = [cred(1, F, "100"), cred(2, F, "100")]
R.emparejar(c, {}, [lib(10, F, "100")])
ok(all(x["estado"] == "pendiente" for x in c), "fecha e importe repetidos: no se sugiere")

print("Formulario")


class Form(dict):
    def getlist(self, k):
        return self.get(k, [])


r, e = R.leer_renglones(Form(r_periodo=["2026-10", "2026-09", ""], r_importe=["1.234,56", "100", ""]))
ok(not e and r == [("202610", D("1234.56")), ("202609", D("100.00"))], "períodos e importes")
r, e = R.leer_renglones(Form(r_periodo=["2026-10", "2026-10"], r_importe=["1", "2"]))
ok(any("dos veces" in x for x in e), "período repetido")
r, e = R.leer_renglones(Form(r_periodo=["2026-13"], r_importe=["0"]))
ok(len(e) == 2, "período e importe inválidos")


print("Cuotas impagas por importe (pago sin empleador)")
import datetime as _dt2
from decimal import Decimal as _D2
ok(R.periodos_atras(_dt2.date(2026, 11, 3)) == ["202610", "202609", "202608"], "los 3 períodos anteriores")
ok(R.periodos_atras(_dt2.date(2026, 1, 5), 2) == ["202512", "202511"], "cruza el año")
per = ["202610", "202609", "202608"]
sal = {"202610": _D2("85403.72"), "202609": _D2("40000"), "202608": _D2("45403.72")}
ok(R.coincidencias(_D2("85403.72"), sal, per) == [["202610"], ["202608", "202609"]], "una cuota sola o dos seguidas")
ok(R.coincidencias(_D2("85403.73"), sal, per) == [], "al centavo")
ok(R.coincidencias(_D2("125403.72"), {"202610": _D2("85403.72"), "202608": _D2("40000")}, per) == [],
   "salteando un período sin saldo no suma")
ok(R.coincidencias(_D2("100"), {"202610": _D2("0"), "202609": _D2("100")}, per) == [["202609"]], "lo pagado no cuenta")

print()
if fallos:
    print(f"{len(fallos)} FALLAS")
    sys.exit(1)
print("Todo OK")
