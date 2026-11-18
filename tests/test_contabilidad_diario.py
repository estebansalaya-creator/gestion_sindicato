"""
Pruebas del Libro Diario y los ejercicios (sin base): reglas de asientos.py,
lectura del archivo de importación, el formato externo y que las pantallas se
dibujen.  python tests/test_contabilidad_diario.py
"""
import datetime
import io
import logging
import os
import sys
from decimal import Decimal as D

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asientos as A  # noqa: E402
import contabilidad_ejercicios as CE  # noqa: E402
import exportar_contable_externo as EXT  # noqa: E402

fallos = []


def ok(cond, txt):
    print(("  OK   " if cond else "  FALLA ") + txt)
    if not cond:
        fallos.append(txt)


print("Períodos de un ejercicio")
m = A.meses(datetime.date(2026, 1, 1), datetime.date(2026, 12, 31))
ok(len(m) == 12 and m[0]["nombre"] == "Enero 2026" and m[-1]["fecha_fin"] == datetime.date(2026, 12, 31), "doce meses")
ok(m[1]["fecha_fin"] == datetime.date(2026, 2, 28), "febrero termina el 28")
m = A.meses(datetime.date(2025, 7, 1), datetime.date(2026, 6, 30))
ok(len(m) == 12 and m[0]["nombre"] == "Julio 2025" and m[-1]["nombre"] == "Junio 2026", "ejercicio de julio a junio")
m = A.meses(datetime.date(2026, 3, 15), datetime.date(2026, 5, 10))
ok([x["fecha_inicio"].day for x in m] == [15, 1, 1] and m[-1]["fecha_fin"] == datetime.date(2026, 5, 10),
   "primero y último parciales")
p = CE.propuesta(datetime.date(2026, 11, 18), [])
ok(p["fecha_inicio"] == datetime.date(2026, 1, 1) and p["fecha_fin"] == datetime.date(2026, 12, 31)
   and p["nombre"] == "Ejercicio 2026", "sin ejercicios: el año en curso")
p = CE.propuesta(datetime.date(2026, 11, 18), [{"fecha_fin": datetime.date(2026, 6, 30)}])
ok(p["fecha_inicio"] == datetime.date(2026, 7, 1) and p["fecha_fin"] == datetime.date(2027, 6, 30)
   and p["nombre"] == "Ejercicio 2026/2027", "el siguiente al último")

print("Importes")
for t, esp in (("1.234,56", "1234.56"), ("1234.56", "1234.56"), ("1.234", "1234"), ("", "0"), (1500.0, "1500"),
               ("$ 10", "10"), ("12.5", "12.5")):
    ok(A.leer_importe(t) == D(esp), f"{t!r} → {esp}")
ok(A.leer_importe("abc") is None, "lo que no es número: None")

print("Renglones")
cuentas = {1: {"id_cuenta": 1, "codigo": "1-1-1-02-020", "nombre": "BANCO", "permite_movimiento": 1, "activa": 1},
           2: {"id_cuenta": 2, "codigo": "5-3-0-00-040", "nombre": "SERVICIOS", "permite_movimiento": 1, "activa": 1},
           3: {"id_cuenta": 3, "codigo": "5-0-0-00-000", "nombre": "EGRESOS", "permite_movimiento": 0, "activa": 1},
           4: {"id_cuenta": 4, "codigo": "5-3-0-00-099", "nombre": "VIEJA", "permite_movimiento": 1, "activa": 0}}
b, e, td, th = A.validar_renglones([{"id_cuenta": "2", "debe": "1.000,00", "haber": ""},
                                    {"id_cuenta": "1", "debe": "", "haber": "1000"},
                                    {"id_cuenta": "", "debe": "", "haber": ""}], cuentas)
ok(not e and len(b) == 2 and td == th == D("1000"), "balancea; la fila vacía no cuenta")
_, e, _, _ = A.validar_renglones([{"id_cuenta": "2", "debe": "100"}, {"id_cuenta": "1", "haber": "99,99"}], cuentas)
ok(any("No balancea" in x for x in e), "no balancea")
_, e, _, _ = A.validar_renglones([{"id_cuenta": "2", "debe": "100", "haber": "100"}, {"id_cuenta": "1", "haber": "100"}],
                                 cuentas)
ok(any("no a los dos" in x for x in e), "debe y haber en el mismo renglón")
_, e, _, _ = A.validar_renglones([{"id_cuenta": "3", "debe": "100"}, {"id_cuenta": "1", "haber": "100"}], cuentas)
ok(any("título" in x for x in e), "un título no es imputable")
_, e, _, _ = A.validar_renglones([{"id_cuenta": "4", "debe": "100"}, {"id_cuenta": "1", "haber": "100"}], cuentas)
ok(any("inactiva" in x for x in e), "una cuenta inactiva no")
_, e, _, _ = A.validar_renglones([{"id_cuenta": "2", "debe": "100"}], cuentas)
ok(any("dos renglones" in x for x in e), "al menos dos renglones")
_, e, _, _ = A.validar_renglones([{"id_cuenta": "2", "debe": "-100"}, {"id_cuenta": "1", "haber": "-100"}], cuentas)
ok(any("positivo" in x for x in e), "sin negativos")

print("Archivo de importación")
csv_txt = ("nro_asiento,fecha,tipo,descripcion,referencia,codigo_cuenta,descripcion_item,debe,haber\n"
           "7,2026-01-02,operacion,Pago,OP 1,5-3-0-00-040,Servicio,150000.00,\n"
           "7,2026-01-02,operacion,Pago,OP 1,1-1-1-02-020,Transferencia,,150000.00\n"
           "8,02/01/2026,ajuste,Otro,,9-9-9-99-999,X,10,\n"
           "8,02/01/2026,ajuste,Otro,,1.1.1.02.020,Y,,10\n").encode("utf-8-sig")
filas = A.leer_archivo("a.csv", csv_txt)
ok(len(filas) == 4 and filas[0]["codigo_cuenta"] == "5-3-0-00-040", "lee el CSV")
asientos, err = A.agrupar_archivo(filas, {"53000040": 2, "11102020": 1})
ok(len(asientos) == 2 and not err, "agrupa por N°")
a7 = next(x for x in asientos if x["nro"] == "7")
ok(a7["fecha"] == datetime.date(2026, 1, 2) and a7["referencia"] == "OP 1" and not a7["error"]
   and [r["id_cuenta"] for r in a7["renglones"]] == [2, 1], "cabecera y cuentas por código sin guiones")
a8 = next(x for x in asientos if x["nro"] == "8")
ok(a8["error"] and "9-9-9-99-999" in a8["error"], "una cuenta que no está en el plan se informa")
ok(A.leer_archivo("b.csv", "N° Asiento;Fecha;Tipo;Descripción;Referencia;Código cuenta;Debe;Haber\n1;02/01/2026;operacion;X;;1;10;\n"
                  .encode())[0]["debe"] == "10", "CSV con punto y coma y los títulos del modelo")
try:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Instrucciones de ejemplo"])
    ws.append(A.TITULOS_ARCHIVO)
    ws.append([1, datetime.datetime(2026, 3, 5), "operacion", "X", None, "5-3-0-00-040", "d", 12.5, None])
    ws.append([1, datetime.datetime(2026, 3, 5), "operacion", "X", None, "1-1-1-02-020", "h", None, 12.5])
    buf = io.BytesIO()
    wb.save(buf)
    filas = A.leer_archivo("m.xlsx", buf.getvalue())
    asientos, _ = A.agrupar_archivo(filas, {"53000040": 2, "11102020": 1})
    b, e, td, _ = A.validar_renglones(asientos[0]["renglones"], cuentas)
    ok(len(filas) == 2 and asientos[0]["fecha"] == datetime.date(2026, 3, 5) and not e and td == D("12.50"),
       "lee el .xlsx con la fila de instrucciones arriba")
except ImportError:
    print("  (sin openpyxl: no se prueba el .xlsx)")
try:
    A.leer_archivo("x.txt", b"")
    ok(False, "otra extensión no")
except A.ErrorContable:
    ok(True, "otra extensión no")

print("Formato externo")
ok(EXT.cuenta_a_entero("5-3-0-00-040") == 53000040, "la cuenta sin guiones")
buf = EXT.construir_libro([{"id": 1, "fecha": datetime.date(2026, 1, 2), "detalle": "MU??OZ, JUAN",
                            "cuenta_codigo": "1-1-1-02-020", "detitem": "x", "debe": 10, "haber": 0}])
ws = openpyxl.load_workbook(buf).active
ok(ws["B2"].value == "'02/01/2026" and ws["C2"].value.startswith("MUÑOZ JUAN") and len(ws["C2"].value) == 100,
   "fecha con apóstrofo, Ñ restituida, sin coma, ancho fijo")

print("Pantallas")
import app as aplicacion  # noqa: E402
app = aplicacion.app
app.logger.setLevel(logging.CRITICAL)
hoy = datetime.date(2026, 11, 18)
ej = {"id_ejercicio": 1, "nombre": "Ejercicio 2026", "fecha_inicio": datetime.date(2026, 1, 1),
      "fecha_fin": datetime.date(2026, 12, 31), "estado": "abierto", "activo": 1, "periodos": 12, "abiertos": 12,
      "asientos": 3, "borradores": 1, "observaciones": None, "usuario_cierre": None, "fecha_cierre_real": None}
pers = [{"id_periodo": 10 + i, "id_ejercicio": 1, "nombre": x["nombre"], "fecha_inicio": x["fecha_inicio"],
         "fecha_fin": x["fecha_fin"], "estado": "cerrado" if i == 0 else "abierto", "confirmados": 1 if i == 1 else 0,
         "borradores": 0} for i, x in enumerate(A.meses(ej["fecha_inicio"], ej["fecha_fin"]))]
asiento = {"id_asiento": 5, "numero": 12, "fecha": hoy, "descripcion": "Pago Nro: 00004475", "tipo": "operacion",
           "referencia": "OP 4475", "estado": "borrador", "usuario": "ROMINA", "periodo": "Noviembre 2026",
           "estado_periodo": "abierto", "total_debe": D("100"), "total_haber": D("90"), "renglones": 2}
with app.test_request_context("/contabilidad/diario"):
    from flask import render_template, session
    session["sind_validausuario"] = True
    session["sind_menu_ids"] = []
    html = render_template("contabilidad/ejercicios.html", ejercicios=[ej], ficha=ej, periodos=pers, nuevo=True,
                           propuesta=CE.propuesta(hoy, [ej]), inst={"nombre": "AEDA", "cuit": "30657937270"},
                           estados=A.ESTADOS_PERIODO, puede_diario=True)
    ok("Enero 2026" in html and "Abrir el ejercicio" in html and "Ejercicio 2027" in html, "Ejercicios con su ficha")
    tot = {"asientos": 1, "confirmados": 0, "borradores": 1, "debe": D("0"), "descuadrados": 1}
    f = {"ejercicio": "1", "periodo": "", "estado": "", "tipo": "", "desde": "", "hasta": ""}
    html = render_template("contabilidad/diario.html", filas=[asiento], excedido=False, tope=5000, f=f,
                           args={"ejercicio": "1"}, ejercicios=[ej], periodos=pers, ej=ej, titulo="Ejercicio 2026",
                           tot=tot, estados=A.ESTADOS, tipos=A.TIPOS_TXT, puede_carga=True, puede_ej=True, hoy=hoy)
    ok("Pago Nro: 00004475" in html and "no balancea" in html and "modal-importar" in html
       and "Confirmar los borradores" in html and "/contabilidad/diario/externo" in html, "Libro Diario")
    a = dict(asiento, ejercicio="Ejercicio 2026", created_at=None, origen="aeda", id_origen=14486,
             renglones=[{"codigo": "5-3-0-00-040", "cuenta": "SERVICIOS", "descripcion": None, "debe": D("100"),
                         "haber": D("0")},
                        {"codigo": "1-1-1-02-020", "cuenta": "BANCO", "descripcion": "x", "debe": D("0"),
                         "haber": D("90")}], total_debe=D("100"), total_haber=D("90"))
    html = render_template("contabilidad/asiento.html", a=a, estados=A.ESTADOS, tipos=A.TIPOS_TXT, puede_carga=True,
                           volver="/contabilidad/diario")
    ok("No balancea" in html and "AEDA 14486" in html and "Corregir" in html, "la ficha del asiento")
    html = render_template("contabilidad/asiento_carga.html", cab={"fecha": hoy, "descripcion": "", "tipo": "operacion",
                                                                   "referencia": ""},
                           renglones=[{"id_cuenta": "", "debe": "", "haber": "", "descripcion": ""}] * 2,
                           cuentas=[{"id": 1, "texto": "1-1-1-02-020  BANCO", "grupo": "1 · ACTIVO"}], base=None,
                           ej=ej, errores=[], tipos=A.TIPOS_TXT)
    ok(html.count('name="r_cuenta"') == 3 and "Guardar y confirmar" in html, "la carga (dos renglones y el modelo)")

print()
if fallos:
    print(f"{len(fallos)} FALLAS")
    sys.exit(1)
print("Todo OK")
