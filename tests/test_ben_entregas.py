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
r = E.resumen(400, 100)
ok({k: r[k] for k in ("padron", "entregados", "faltan", "porc")} == {"padron": 400, "entregados": 100, "faltan": 300, "porc": 25.0},
   "cuántos retiraron")
ok(E.resumen(0, 0)["porc"] == 0.0, "padrón vacío")
ok(E.solo_digitos("20-28123456-3") == "20281234563", "CUIL con guiones")

print("Stock")
r = E.resumen(400, 120, 500)
ok(r["controla_stock"] and r["queda"] == 380, "500 cargados, 120 entregados: quedan 380")
r = E.resumen(400, 120, 0)
ok(not r["controla_stock"] and r["queda"] is None, "sin cargas: no se controla")
E.control_stock({"controla_stock": False, "queda": None})
ok(True, "sin cargas: se entrega igual")
try:
    E.control_stock({"controla_stock": True, "queda": 0, "stock": 500, "entregados": 500})
    ok(False, "sin stock: no se entrega")
except E.ErrorEntrega as e:
    ok("No queda stock" in str(e), "sin stock: no se entrega")
E.control_stock({"controla_stock": True, "queda": 1, "stock": 500, "entregados": 499})
ok(True, "queda uno: se entrega")
ok(E.leer_stock("500", " compra  remito 12 ", 0, 0) == (500, "compra remito 12"), "carga")
ok(E.leer_stock("-3", "rotas", 100, 500) == (-3, "rotas"), "ajuste")
for args, txt in ((("0", "x", 0, 0), "cero"), (("abc", "x", 0, 0), "no es número"), (("5", "", 0, 0), "sin detalle"),
                  (("-450", "x", 100, 500), "ajuste por debajo de lo entregado"), (("-1", "x", 0, 0), "negativo sin stock")):
    try:
        E.leer_stock(*args)
        ok(False, "se rechaza: " + txt)
    except E.ErrorEntrega:
        ok(True, "se rechaza: " + txt)

print("Retira por la empresa")
import datetime as _dt   # noqa: E402
ok(E.leer_retiro_empresa({"retiro_nombre": " perez  juan ", "retiro_documento": "30.111.222"}) == ("perez juan", "30111222"),
   "nombre y DNI limpios")
for d, txt in (({"retiro_nombre": "PEREZ"}, "sin DNI"), ({"retiro_documento": "30111222"}, "sin nombre"),
               ({"retiro_nombre": "PEREZ", "retiro_documento": "123"}, "DNI corto")):
    try:
        E.leer_retiro_empresa(d)
        ok(False, "se rechaza: " + txt)
    except E.ErrorEntrega:
        ok(True, "se rechaza: " + txt)
ok(E.leer_ids(["3", "1", "3"]) == [3, 1], "ids sin repetir")
for v, txt in (([], "nadie tildado"), (["x"], "id que no es número")):
    try:
        E.leer_ids(v)
        ok(False, "se rechaza: " + txt)
    except E.ErrorEntrega:
        ok(True, "se rechaza: " + txt)
F = lambda i, emp, ent=0: {"id": i, "orden": i, "apellido_nombres": f"AFI {i}", "empleador": emp, "entregado": ent,
                           "fecha_entrega": _dt.datetime(2026, 11, 24, 13, 0) if ent else None}
ok(E.control_empresa([F(1, "CUSTOMS UNION SRL"), F(2, "CUSTOMS UNION SRL")], [1, 2]) == "CUSTOMS UNION SRL", "una empresa")
for filas, ids, txt in (([F(1, "A"), F(2, "B")], [1, 2], "dos empresas"), ([F(1, "A")], [1, 2], "falta una fila"),
                        ([F(1, "A"), F(2, "A", 1)], [1, 2], "uno ya retiró"), ([F(1, None)], [1], "sin empresa")):
    try:
        E.control_empresa(filas, ids)
        ok(False, "se rechaza: " + txt)
    except E.ErrorEntrega:
        ok(True, "se rechaza: " + txt)
E.control_stock_n({"controla_stock": False}, 50)
ok(True, "sin stock cargado: no controla")
try:
    E.control_stock_n({"controla_stock": True, "queda": 2}, 3)
    ok(False, "stock que no alcanza: se rechaza")
except E.ErrorEntrega:
    ok(True, "stock que no alcanza: se rechaza")

print("Constancia por duplicado (PDF)")
try:
    import institucion   # noqa: E402
    institucion.obtener = lambda: {"nombre": "Sindicato de prueba", "sigla": "SP", "cuit": "30657937270"}
    institucion.ruta_logo = lambda d=None: None
    institucion.domicilio_completo = lambda d: "Calle 123"
    from flask import Flask   # noqa: E402
    r = {"id": 7, "empleador": "CUSTOMS UNION SERVICES SRL", "retiro_nombre": "PEREZ JUAN", "retiro_documento": "30111222",
         "cantidad": 3, "fecha": _dt.datetime(2026, 11, 24, 13, 30), "usuario": "Esteban",
         "filas": [{"orden": 1, "apellido_nombres": "ABALSAMO JOSE LUIS", "nro_documento": "22265037",
                    "cuil": "20222650373", "cod_parentesco": 0, "parentesco": None},
                   {"orden": 124, "apellido_nombres": "ARROSPIDE HERNAN MARTIN", "nro_documento": "29462103",
                    "cuil": "20294621033", "cod_parentesco": 0, "parentesco": None}]}
    with Flask(__name__).test_request_context():
        resp = E.constancia_pdf({"titulo": "Caja navideña 2026"}, r)
        resp.direct_passthrough = False
        datos = resp.get_data()
    salida = os.environ.get("PDF_PRUEBA")
    if salida:
        open(salida, "wb").write(datos)
    ok(datos[:4] == b"%PDF" and datos.count(b"/Type /Page") - datos.count(b"/Type /Pages") >= 2,
       "el PDF sale con original y duplicado (2 páginas o más)")
except ImportError as e:
    print("  (sin reportlab o flask: no se prueba el PDF)", e)

if fallos:
    print(f"{len(fallos)} FALLAS")
    sys.exit(1)
print("Todo bien.")
