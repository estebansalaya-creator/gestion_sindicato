"""
test_instructivo_empresa.py — el instructivo en PDF del enlace de las empresas
(instructivo_empresa.py), con datos inventados: sin base ni red.

    python tests/test_instructivo_empresa.py
"""
from __future__ import annotations

import io
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
for k in ("SIND_DB_USER", "SIND_DB_PASS", "SIND_SECRET_KEY"):
    os.environ.setdefault(k, "prueba")

import institucion                  # noqa: E402
import instructivo_empresa as IE    # noqa: E402

fallos = []


def ok(cond, txt):
    print(("  OK   " if cond else "  FALLA ") + txt)
    if not cond:
        fallos.append(txt)


DATOS = {"nombre": "Asociacion Empleados de Despachantes de Aduana", "sigla": "AEDA", "cuit": "30657937270",
         "cuota_alicuota": 2.5, "domicilio": "Av. Siempreviva 742", "localidad": "CABA"}
PAGO = {"cuenta": {"nombre": "BANCO NACION RECAUDADORA", "banco": "BANCO DE LA NACION ARGENTINA", "numero": "5743801",
                   "cbu": "0110599520000057438014", "alias": "AEDA.CUOTA"},
        "titular": DATOS["nombre"], "cuit": "30657937270",
        "indicaciones": "Pongan el CUIT y el mes.\nManden el comprobante a cuotas@aeda.org.ar",
        "email": "cuotas@aeda.org.ar", "telefono": "4300-0000", "domicilio": "Av. Siempreviva 742, CABA", "web": None}
SIN_CUENTA = dict(PAGO, cuenta=None, indicaciones=None)
# El membrete lee Datos del sindicato: sin base, los de prueba.
institucion.obtener = lambda: DATOS
institucion.ruta_logo = lambda d=None: None


def texto_pdf(buf) -> str:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(buf.getvalue())) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


print("El Markdown")
b = IE.leer_bloques("# Título\n\nUn párrafo\nen dos renglones.\n\n- uno\n- **dos**\n\n1. primero\n2. segundo\n\n"
                    "| A | B |\n| --- | --- |\n| x | y |\n\n[[pago]]\n\n## Sub")
ok(b[0] == ("h1", "Título") and b[1] == ("p", "Un párrafo en dos renglones."), "título y párrafo de dos renglones")
ok(b[2] == ("ul", ["uno", "**dos**"]) and b[3] == ("ol", ["primero", "segundo"]), "listas")
ok(b[4] == ("tabla", [["A", "B"], ["x", "y"]]), "tabla sin el renglón separador")
ok(b[5] == ("marca", "pago") and b[6] == ("h2", "Sub"), "marca y subtítulo")
ok(IE.en_linea("**a** <b> `c` & d") == "<b>a</b> &lt;b&gt; <font face='Courier'>c</font> &amp; d",
   "negrita, código y escape de lo demás")
ok(IE.reemplazos("de {sigla} (hoy {alicuota})", DATOS) == "de AEDA (hoy 2,50 %)", "sigla y alícuota")
ok(IE.reemplazos("cuota (hoy {alicuota}).", {"nombre": "X"}) == "cuota.", "sin alícuota se saca el paréntesis")

print("El texto del repositorio")
md = IE.TEXTO.read_text(encoding="utf-8")
bloques = IE.leer_bloques(md)
marcas = [v for t, v in bloques if t == "marca"]
ok(marcas == ["pago", "contacto"], "tiene [[pago]] y [[contacto]]")
ok("Pendiente" not in md, "nada «pendiente» para la empresa")
titulos = [v for t, v in bloques if t == "h2"]
ok("Cómo pagar la cuota" in titulos and titulos[-1] == "Contacto", f"secciones: {len(titulos)}")

print("Los datos de la cuenta y el contacto")
f = dict(IE.filas_cuenta(PAGO))
ok(list(f) == ["Titular", "CUIT", "Banco", "Cuenta N°", "CBU", "Alias"], "en el orden en que se copian")
ok(f["CUIT"] == "30-65793727-0" and "0110599520000057438014" in f["CBU"], "CUIT con guiones y CBU")
ok(IE.filas_cuenta(SIN_CUENTA) == [], "sin cuenta, nada")
ok("Alias" not in dict(IE.filas_cuenta(dict(PAGO, cuenta=dict(PAGO["cuenta"], alias=None)))), "sin alias, sin renglón")
ok([k for k, _ in IE.filas_contacto(PAGO)] == ["Correo", "Teléfono", "Domicilio"], "contacto sin lo vacío")
ok(IE.nombre_archivo(DATOS) == "Instructivo cuota sindical AEDA.pdf", "nombre del archivo")

print("El PDF")
t = texto_pdf(IE.armar(DATOS, PAGO, {"razon_social": "EMPRESA SA", "cuit": "30712345678"}))
for frag in ("Instructivo para la empresa", "Para EMPRESA SA", "30-71234567-8", "Cómo pagar la cuota",
             "0110599520000057438014", "AEDA.CUOTA", "Manden el comprobante", "cuotas@aeda.org.ar", "2,50 %"):
    ok(frag in t, f"con «{frag}»")
ok("{" not in t and "[[" not in t, "sin marcas sin reemplazar")
t = texto_pdf(IE.armar(DATOS, SIN_CUENTA))
ok("Pidan al sindicato los datos de la cuenta" in t and "CBU" not in t, "sin cuenta: pide los datos")
t = texto_pdf(IE.armar(DATOS, dict(SIN_CUENTA, email=None, telefono=None, domicilio="")))
ok("comuníquense con el sindicato" in t, "sin contacto: que se comuniquen")

print()
print(f"{len(fallos)} falla(s)" if fallos else "Todo OK")
sys.exit(1 if fallos else 0)
