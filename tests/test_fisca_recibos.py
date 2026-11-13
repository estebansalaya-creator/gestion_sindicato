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
afi = {"27000000006": {"30711111118"}, "20000000001": {"30711111118", "30709404047"}}
r = R.resolver_empleador("30709404047", emp, rel, afi)
ok(r["como"] == "mismo" and r["cuit"] == "30709404047", "mismo CUIT")
r = R.resolver_empleador("20081898201", emp, rel, afi)
ok(r["como"] == "relacionado" and r["cuit"] == "30696906420", "CUIT relacionado")
r = R.resolver_empleador("20123456786", emp, rel, afi)
ok(r["como"] == "varios" and not r["cuit"] and len(r["opciones"]) == 2, "paga por dos empleadores: se elige")
r = R.resolver_empleador("27000000006", emp, rel, afi)
ok(r["como"] == "afiliado" and r["cuit"] == "30711111118", "afiliado con un empleador: sugerencia")
r = R.resolver_empleador("20000000001", emp, rel, afi)
ok(r["como"] == "varios", "afiliado con dos empleadores")
ok(R.resolver_empleador("", emp, rel, afi)["como"] == "sin", "sin CUIT")
ok(R.resolver_empleador("33707651259", emp, rel, afi)["como"] == "sin", "CUIT desconocido")
ok(R.resolver_empleador("20081898201", emp, {"20081898201": ["30999999990"]}, afi)["como"] == "sin",
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

print()
if fallos:
    print(f"{len(fallos)} FALLAS")
    sys.exit(1)
print("Todo OK")
