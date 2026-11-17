"""
test_ben_convenio.py — Beneficios › Convenio YMCA (ben_convenio.py), con datos
inventados: sin base ni red. Las cuentas por grupo, el control de la factura y
que las pantallas se dibujen.

    python tests/test_ben_convenio.py
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

import ben_convenio as B   # noqa: E402

fallos = []


def ok(cond, txt):
    print(("  OK   " if cond else "  FALLA ") + txt)
    if not cond:
        fallos.append(txt)


D = Decimal
PRECIOS = [{"periodo_desde": "202604", "precio_proveedor": None, "cuota_afiliado": D("25000")},
           {"periodo_desde": "202609", "precio_proveedor": D("45000"), "cuota_afiliado": D("30000")}]


def adh(i, cuil, tit, desde, hasta=None, nombre=None):
    return {"id": i, "id_afiliado": i, "cuil": cuil, "cuil_titular": tit, "periodo_desde": desde,
            "periodo_hasta": hasta, "apellido_nombres": nombre or f"AFILIADO {i}"}


T1, T2 = "20111111112", "27222222223"
NOMINA = [adh(1, T1, T1, "202609", nombre="PEREZ JUAN"), adh(2, "20333333334", T1, "202610", nombre="PEREZ HIJO"),
          adh(3, T2, T2, "202609", "202610", nombre="GOMEZ ANA")]

print("Vigencias")
ok(B.precio_del_mes(PRECIOS, "202603") is None, "antes de la primera: ninguna")
ok(B.precio_del_mes(PRECIOS, "202608")["cuota_afiliado"] == 25000, "agosto: la de abril")
ok(B.precio_del_mes(PRECIOS, "202612")["cuota_afiliado"] == 30000, "diciembre: la de septiembre")
ok(B.periodo_valido("2026-11") == "202611" and B.periodo_valido("2026-13") is None, "períodos")
ok(B.meses_entre("202611", "202702") == ["202611", "202612", "202701", "202702"], "meses entre (cruza el año)")

print("Nómina")
ok(len(B.adheridos_del_mes(NOMINA, "202609")) == 2, "septiembre: titular y Gómez")
ok(len(B.adheridos_del_mes(NOMINA, "202611")) == 2, "noviembre: Pérez y su hijo (Gómez se fue en octubre)")
ok(B.se_superpone(NOMINA, 1, "202701", None) is not None, "el titular ya está abierto: se superpone")
ok(B.se_superpone(NOMINA, 3, "202611", None) is None, "Gómez puede volver después de su baja")
ok(B.se_superpone(NOMINA, 3, "202610", None) is not None, "pero no pisando su último mes")
ok(B.se_superpone(NOMINA, 1, "202701", None, excepto=1) is None, "al editar, no choca consigo mismo")

print("Cuota del grupo")
c, n = B.cuota_del_grupo(NOMINA, PRECIOS, T1, "202611")
ok((c, n) == (D("60000.00"), 2), f"titular con un hijo: dos cuotas ({c}, {n})")
c, n = B.cuota_del_grupo(NOMINA, PRECIOS, T1, "202609")
ok((c, n) == (D("30000.00"), 1), "en septiembre el hijo todavía no")
c, n = B.cuota_del_grupo(NOMINA, PRECIOS, "20999999990", "202611")
ok((c, n) == (D("30000.00"), 0), "un grupo que no está: la cuota de uno, con 0 adheridos")

print("Cuentas por grupo")
cobros = [{"cuil_titular": T1, "periodo": "202611", "importe": D("60000"), "fecha": datetime.date(2026, 11, 3)},
          {"cuil_titular": T1, "periodo": "202612", "importe": D("30000"), "fecha": datetime.date(2026, 12, 2)},
          {"cuil_titular": T2, "periodo": "202611", "importe": D("30000"), "fecha": datetime.date(2026, 11, 5)}]
cu = B.armar_cuentas(NOMINA, PRECIOS, cobros, "202611", "202612")
g1, g2 = cu[T1], cu[T2]
ok(g1["debe"] == D("120000.00") and g1["pagado"] == D("90000") and g1["saldo"] == D("30000.00"),
   f"Pérez: debe 120.000, pagó 90.000, saldo 30.000 ({g1['debe']}, {g1['pagado']}, {g1['saldo']})")
ok(g1["adeudados"] == 1 and g1["ultimo_pago"] == datetime.date(2026, 12, 2), "un mes adeudado, último pago el 02/12")
ok(g1["titular"] == "PEREZ JUAN" and g1["personas"] == ["PEREZ HIJO", "PEREZ JUAN"], "titular y personas del grupo")
ok(g2["debe"] == 0 and g2["saldo"] == D("-30000") and g2["meses"][0]["adheridos"] == 0,
   "Gómez se fue en octubre y pagó noviembre: saldo a favor, mes sin adheridos")
ok(g2["vigentes"] == 0 and g1["vigentes"] == 2, "adheridos al último mes")
cu = B.armar_cuentas(NOMINA, PRECIOS, cobros, "202612", "202612")
ok(cu[T1]["pagado"] == D("30000"), "un pago fuera del rango no cuenta")

print("Control mensual")
facturas = [{"periodo": "202611", "importe": D("90000")}, {"periodo": "202610", "importe": D("135000")},
            {"periodo": "202610", "importe": D("-45000")}]
filas = B.armar_control(NOMINA, PRECIOS, facturas, {"202611": D("90000"), "202610": D("50000")},
                        ["202608", "202610", "202611"], {"202611": 2})
f8, f10, f11 = filas
ok(f8["precio"] is None and f8["esperado"] is None and f8["diferencia"] is None, "sin precio: no hay esperado")
ok(f10["adheridos"] == 3 and f10["esperado"] == D("135000.00"), "octubre: 3 adheridos × 45.000")
ok(f10["facturado"] == D("90000") and f10["diferencia"] == D("-45000.00"), "la nota de crédito resta")
ok(f10["adheridos_por_factura"] == D("2.00"), "lo facturado son 2 adheridos")
ok(f11["diferencia"] == 0 and f11["a_cargo"] == 0 and f11["pagaron"] == 2, "noviembre cierra justo")
ok(f10["a_cobrar"] == D("90000.00") and f10["a_cargo"] == D("40000"), "a cobrar 3 × 30.000; cubre 90.000 − 50.000")

print("Pantallas (con datos inventados)")
import app as A   # noqa: E402
from flask import render_template   # noqa: E402

conv = {"id": 1, "nombre": "YMCA", "id_proveedor": 23, "id_motivo_ingreso": 29, "cc_desde": "202611",
        "proveedor": "ASOCIACION CRISTIANA", "cuit_proveedor": "30525370190", "observaciones": None}
mes = "202611"
for a in NOMINA:
    a.update({"vigente": B.vigente_en(a, mes), "estado": "vigente" if B.vigente_en(a, mes) else "baja",
              "baja_padron": None, "parentesco": "Hijo", "observaciones": None})
with A.app.test_request_context("/"):
    try:
        h = render_template("beneficios/adheridos.html", conv=conv, puede=lambda u: True, filas=NOMINA, errores=[],
                            registro=None, sin_nomina=[{"cuil": T2, "apellido_nombres": "GOMEZ ANA", "veces": 2,
                                                         "ultima": datetime.date(2026, 11, 3), "total": D("60000"),
                                                         "ultimo_importe": D("30000"), "fecha_baja": None}],
                            mes=mes, totales={"vigentes": 2, "grupos": 1, "titulares": 1, "familiares": 1},
                            abrir_ficha=False)
        ok("PEREZ HIJO" in h and "GOMEZ ANA" in h, "nómina")
        cu = B.armar_cuentas(NOMINA, PRECIOS, cobros, "202611", "202612")
        filas_c = [{"cuil_titular": k, **v} for k, v in cu.items()]
        h = render_template("beneficios/cuotas.html", conv=conv, filas=filas_c, desde="202611", hasta="202612",
                            tot={"grupos": 2, "debe": D("1"), "pagado": D("1"), "saldo": D("0"), "con_deuda": 1})
        ok("PEREZ JUAN" in h, "cuotas")
        h = render_template("beneficios/cuota_grupo.html", conv=conv, cuenta=cu[T1], cuil_titular=T1, nomina=NOMINA[:2],
                            grupo=[], recibos=[{"id": 9, "fecha": datetime.date(2026, 11, 3), "estado": "confirmado",
                                                "numero": "X 0003-00000001", "nro_orden": "2611-1", "afiliado": "PEREZ JUAN",
                                                "meses": ["2026-11"], "cuenta": "BNA", "importe_total": D("60000")}],
                            desde="202611", hasta="202612")
        ok("X 0003-00000001" in h, "cuenta de un grupo")
        facturas[0].update({"numero_completo": "00011-00008168", "fecha_emision": datetime.date(2026, 11, 1),
                            "id_expediente": 1537, "nro_expediente": "000002277/26"})
        for x in facturas[1:]:
            x.update({"numero_completo": "1", "fecha_emision": None, "id_expediente": None, "nro_expediente": None})
        h = render_template("beneficios/control.html", conv=conv, filas=filas, desde="202608", hasta="202611",
                            tot={"facturado": D("1"), "cobrado": D("1"), "a_cargo": D("0"), "diferencias": 1,
                                 "sin_precio": True}, puede_mesa=True)
        ok("00011-00008168" in h, "control mensual")
        h = render_template("beneficios/convenio.html", conv=conv, precios=[dict(p, id=i, hasta=None, vigente=True,
                            observaciones=None) for i, p in enumerate(PRECIOS)], proveedores=[], motivos=[],
                            editar_precio=None, mes=mes)
        ok("Importes por vigencia" in h, "datos del convenio")
        fila = {"id": 5, "fecham": datetime.date(2026, 11, 3), "ref_nro": "1", "concepto": "TRANSF", "cuit": T1,
                "emp": {"nombre": "PEREZ JUAN", "como": "afiliado"}, "adheridos": 2, "cuota_grupo": D("60000"),
                "sugerido": [("202611", D("60000"))], "importe": D("60000"), "estado": "pendiente", "recibo": None,
                "regla": None, "en_lote": True}
        h = render_template("beneficios/recibos.html", conv=conv, cuentas=[{"id": 1, "nombre": "BNA", "numero_de_cuenta": "1",
                            "ultimo": 1}], cuenta={"id": 1, "nombre": "BNA"}, id_cuenta=1, filas=[fila],
                            desde=datetime.date(2026, 11, 1), hasta=datetime.date(2026, 11, 16),
                            res={"cant": 1, "total": D("60000"), "emitido": (0, 0), "ya_tiene": (0, 0),
                                 "lote": (1, D("60000")), "sin_nomina": (0, D("0"))},
                            estados=B.FR.ESTADOS, emitibles=B.FR.EMITIBLES, excedido=False, tope=5000,
                            cfg={"talonario": 1})
        ok("Emitir los recibos tildados" in h, "recibos de adheridos")
    except Exception as e:      # noqa: BLE001
        import traceback
        traceback.print_exc()
        ok(False, f"las pantallas se dibujan: {e}")

print()
print("FALLAS: " + ", ".join(fallos) if fallos else "Todo bien.")
sys.exit(1 if fallos else 0)
