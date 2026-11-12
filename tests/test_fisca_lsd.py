"""
test_fisca_lsd.py — la planilla de cuota sindical que sale del Libro de
Sueldos Digital (fisca_lsd.py), con datos inventados: sin base ni red.

    python tests/test_fisca_lsd.py
"""
from __future__ import annotations

import datetime
import io
import os
import re
import sys
import zipfile
from decimal import Decimal

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
for k in ("SIND_DB_USER", "SIND_DB_PASS", "SIND_SECRET_KEY"):
    os.environ.setdefault(k, "prueba")

import fisca_liquidacion as FL   # noqa: E402
import fisca_lsd as L            # noqa: E402
import lsd_lector                # noqa: E402

fallos = []


def ok(cond, txt):
    print(("  OK   " if cond else "  FALLA ") + txt)
    if not cond:
        fallos.append(txt)


def n(v, largo, dec=0):
    return str(int(round(Decimal(str(v)) * (10 ** dec)))).zfill(largo)


CUIT = "30000000007"


def r01(cant, periodo=202610, cuit=CUIT, envio="SJ"):
    return f"01{cuit}{envio}{periodo}M{n(1, 5)}30{n(cant, 6)}"


def r02(cuil):
    return f"02{cuil}{'1'.ljust(10)}{'CABA'.ljust(50)}{''.ljust(22)}{n(0, 3)}2026103120261103" + "1"


def r03(cuil, codigo, cant, unidad, importe, dc):
    return f"03{cuil}{codigo.ljust(10)}{n(cant, 5, 2)}{unidad}{n(importe, 15, 2)}{dc}{' ' * 6}"


def r04(cuil, base5, bruta=None):
    bruta = bruta if bruta is not None else base5
    cab = f"04{cuil}0000101101010490080001010100000000" + "30000" + "0000000000" + "106104" + "00"
    imp = [0, 0, 0, 0, 0, 0, bruta] + [base5] * 9 + [0, 0, base5, 0]
    return cab + "".join(n(v, 15, 2) for v in imp)


def archivo(trabajadores, **kw):
    lineas = [r01(len(trabajadores), **kw)]
    for cuil, base, cuota in trabajadores:
        lineas += [r02(cuil), r03(cuil, "110000", 30, "$", base, "C")]
        if cuota is not None:
            lineas.append(r03(cuil, "810004", 2.5, "%", cuota, "D"))
        lineas.append(r04(cuil, base))
    return ("\r\n".join(lineas) + "\r\n").encode("cp1252")


A, B, C, D, E = "20111111112", "27222222223", "20333333334", "20444444445", "20555555556"
d = datetime.date
padron = {
    "titulares": [
        {"id_afiliado": 1, "cuil": A, "apellido_nombres": "AFILIADO ACTIVO", "fecha_alta": d(2015, 1, 1), "fecha_baja": None},
        {"id_afiliado": 2, "cuil": B, "apellido_nombres": "SIN RELACION", "fecha_alta": d(2015, 1, 1), "fecha_baja": None},
        {"id_afiliado": 3, "cuil": C, "apellido_nombres": "ACTIVO SIN ARCHIVO", "fecha_alta": d(2015, 1, 1), "fecha_baja": None},
        {"id_afiliado": 4, "cuil": D, "apellido_nombres": "DE BAJA", "fecha_alta": d(2015, 1, 1), "fecha_baja": d(2026, 9, 30)},
    ],
    "relaciones": [
        {"cuil": A, "cuit_empleador": CUIT, "estado": "activa", "fecha_inicio": d(2020, 1, 1), "fecha_fin": None},
        {"cuil": C, "cuit_empleador": CUIT, "estado": "activa", "fecha_inicio": None, "fecha_fin": None},
        {"cuil": D, "cuit_empleador": CUIT, "estado": "activa", "fecha_inicio": None, "fecha_fin": None},
    ],
}
contenido = archivo([(A, "1000000.00", "25000.00"), (B, "400000.00", None), (D, "500000.00", None),
                     (E, "800000.00", None)])

print("Lectura y validación")
lec = lsd_lector.leer_liquidacion(contenido)
ok(lec["errores"] == [], f"el archivo de prueba respeta el diseño ({lec['errores']})")
ok(L.validar(lec, CUIT) == [], "con el CUIT del enlace no hay errores")
ok(any("este enlace es del CUIT" in e for e in L.validar(lec, "30999999990")), "otro CUIT: se rechaza")
futuro = lsd_lector.leer_liquidacion(archivo([(A, "1", None)], periodo=209912))
ok(any("todavía no empezó" in e for e in L.validar(futuro)), "un período futuro: se rechaza")
try:
    L._leer(contenido[:-5], CUIT)
    ok(False, "un archivo roto levanta ErrorPresentacion")
except L.ErrorPresentacion as e:
    ok(e.detalle and "posiciones" in " ".join(e.detalle), "un archivo roto levanta ErrorPresentacion con los renglones")

print("\nLa planilla")
plan = L.armar_planilla(lec, padron, Decimal("2.50"))
por = {l["cuil"]: l for l in plan["lineas"]}
ok(set(por) == {A, B, C}, "afiliados del período: los del archivo y el activo que no está (no el de baja ni el no afiliado)")
ok(por[A]["fuente"] == "lsd" and por[A]["activo"] and por[A]["cuota"] == Decimal("25000.00"),
   "afiliado activo: base 5 × 2,50 %")
ok(por[A]["retenido"] == Decimal("25000.00"), "lo retenido en el recibo (810004) se muestra al lado")
ok(por[B]["fuente"] == "lsd" and not por[B]["activo"] and por[B]["cuota"] == Decimal("10000.00"),
   "en el archivo sin relación laboral: se liquida y se marca")
ok(por[C]["fuente"] == "sin_lsd" and por[C]["cuota"] == 0, "activo de la empresa que no está en el archivo: en cero")
ok((plan["trabajadores"], plan["no_afiliados"], plan["activos"], plan["en_archivo"], plan["fuera_nomina"], plan["afiliados"])
   == (4, 2, 2, 1, 1, 2), "contadores: trabajadores, no afiliados, activos, en el archivo, fuera de nómina, con cuota")
ok(plan["importe"] == Decimal("35000.00") and plan["remuneracion"] == Decimal("1400000.00"), "totales")
ok(plan["lineas"][-1]["fuente"] == "sin_lsd", "los que no están en el archivo van al final")

print("\nControl contra la DDJJ de OSEDA")
real = L.contable_oseda.ddjj_del_periodo
L.contable_oseda.ddjj_del_periodo = lambda periodo, cuiles: [
    {"cuit": CUIT, "cuil": A, "periodo": 202610, "rem5": Decimal("1200000.00")},
    {"cuit": "30999999990", "cuil": B, "periodo": 202610, "rem5": Decimal("400000.00")}]
c = L.control_ddjj(dict(plan, alicuota=Decimal("2.50")))
L.contable_oseda.ddjj_del_periodo = real
ok(c["con_ddjj"] == 1 and c["con_diferencia"] == 1, "solo cuenta la DDJJ de ESE CUIT")
ok(por[A]["dif"] == Decimal("-200000.00") and c["cuota_diferencia"] == Decimal("-5000.00"),
   "la diferencia del archivo contra la DDJJ, y su cuota")

print("\nLa planilla en Excel")
plan.update(alicuota=Decimal("2.50"), dia_vto=20, vencimiento=FL.vencimiento(plan["periodo"], 20))
x = L.planilla_xlsx({"cuit": CUIT, "periodo": "202610", "nro_liquidacion": 1, "razon_social": "EMPRESA SA"}, plan,
                    {"sigla": "AEDA"})
hoja = zipfile.ZipFile(io.BytesIO(x)).read("xl/worksheets/sheet1.xml").decode()
filas = {r: re.sub(r"<[^>]+>", "|", c) for r, c in re.findall(r'<row r="(\d+)">(.*?)</row>', hoja)}
f3 = re.sub(r"\|+", "", filas["3"])
ok(re.search(r"Cuit[:\s]+(\d{11})", f3).group(1) == CUIT and re.search(r"Per[ií]odo\s*:?\s*(\d{6})", f3).group(1) == "202610"
   and re.search(r"Empresa[:\s]+(.+?)\s{3,}", f3).group(1) == "EMPRESA SA",
   "fila 3: CUIT, período y empresa como los lee Importar Cuotas")
ok("CUIL" in filas["4"] and A in filas["5"], "encabezado en la fila 4 y renglones desde la 5")
ok("Total" in list(filas.values())[-1], "última fila: el total")

print("\nEl mail del enlace")
m = L.mailto({"razon_social": "EMPRESA SA"}, ["a@b.com"], "https://x/empresas/t", {"sigla": "AEDA"})
ok(m.startswith("mailto:a@b.com?subject=") and "Ley%2025.326" in m, "lleva el texto de confidencialidad")

print()
print("Todo bien." if not fallos else f"{len(fallos)} FALLAS.")
sys.exit(1 if fallos else 0)
