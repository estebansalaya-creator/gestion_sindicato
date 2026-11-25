"""
Pruebas de lector_dni.py y de la comparación de afiliados_dni.py (sin base ni
fotos reales: los datos son inventados).   python tests/test_lector_dni.py

El código se arma con zxing-cpp y se lee de vuelta de una imagen: prueba la
lectura y la clasificación frente/dorso. La cara no se puede probar sin una
foto: para eso, `python lector_dni.py foto.jpg` deja el recorte al lado.
"""
import io
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lector_dni as L  # noqa: E402

ok = fallos = 0


def v(cond, msg):
    global ok, fallos
    ok, fallos = (ok + 1, fallos) if cond else (ok, fallos + 1)
    print(("  OK   " if cond else "  FALLA ") + msg)


TARJETA = "00512345678@GOMEZ PEREZ@MARIA LAURA@F@30123456@B@02/05/1984@10/08/2015@200"
LIBRETA = ("@25111222    @A@1@RODRIGUEZ@JUAN CARLOS@ARGENTINA@15/03/1976@M@20/06/2010"
           "@00098765432@7003 @20/06/2025@123@0@ILR:2.01 C:110128.01 (GM/EXE-MOVE-HM)@UNIDAD #20")

print("\nCódigo del DNI tarjeta")
d = L.parsear_codigo(TARJETA)
v(d and d["formato"] == "tarjeta", "formato tarjeta")
v(d["dni"] == "30123456" and d["tramite"] == "00512345678", "documento y trámite")
v(d["apellido"] == "GOMEZ PEREZ" and d["nombres"] == "MARIA LAURA", "apellido compuesto y nombres")
v(d["apellido_nombres"] == "GOMEZ PEREZ MARIA LAURA", "apellido_nombres como el padrón")
v(d["sexo"] == "F" and d["ejemplar"] == "B", "sexo y ejemplar")
v(d["fecha_nacimiento"] == date(1984, 5, 2) and d["fecha_emision"] == date(2015, 8, 10), "fechas dd/mm/aaaa")
v(d["fecha_vencimiento"] is None, "la tarjeta no trae vencimiento")

for cod, letra in (("1", "M"), ("2", "F"), ("3", "X")):
    d = L.parsear_codigo(TARJETA.replace("@F@", f"@{cod}@"))
    v(d["sexo"] == letra and d["sexo_codigo"] == cod, f"sexo «{cod}» (tabla de ARCA / ANSES) = {letra}")
d = L.parsear_codigo(TARJETA.replace("@F@", "@9@"))
v(d["sexo"] is None and d["sexo_codigo"] == "9", "sexo «9»: no se adivina, queda el código")

print("\nCódigo del DNI libreta")
d = L.parsear_codigo(LIBRETA)
v(d and d["formato"] == "libreta", "formato libreta (empieza con @)")
v(d["dni"] == "25111222", "documento sin los espacios de relleno")
v(d["apellido"] == "RODRIGUEZ" and d["sexo"] == "M", "apellido y sexo")
v(d["fecha_vencimiento"] == date(2025, 6, 20), "la libreta trae vencimiento")
v(d["tramite"] == "00098765432", "trámite")

print("\nLo que no es un DNI")
v(L.parsear_codigo("") is None, "vacío")
v(L.parsear_codigo("https://ejemplo.com") is None, "sin @")
v(L.parsear_codigo("a@b@c") is None, "pocos campos")
v(L.parsear_codigo("1@@X@F@12@A@01/01/2000@01/01/2010") is None, "sin apellido ni un documento válido")

faltan = L.disponible()
if faltan:
    print(f"\n(sin {', '.join(faltan)}: no se prueba la lectura de imágenes)")
else:
    import zxingcpp
    from PIL import Image

    print("\nLectura de una imagen")
    codigo = zxingcpp.create_barcode(TARJETA, zxingcpp.BarcodeFormat.PDF417)
    img = Image.fromarray(codigo.to_image(scale=3)).convert("RGB")
    lienzo = Image.new("RGB", (img.width + 200, img.height + 300), "white")
    lienzo.paste(img, (100, 150))

    def jpeg(im):
        b = io.BytesIO()
        im.save(b, "JPEG", quality=92)
        return b.getvalue()

    r = L.leer(jpeg(lienzo))
    v(r["lado"] == "frente" and r["datos"] and r["datos"]["dni"] == "30123456", "con código: frente, y lo lee")
    v(r["foto"] is None and any("cara" in a for a in r["avisos"]), "sin cara: lo avisa")
    r = L.leer(jpeg(lienzo.rotate(90, expand=True)))
    v(r["datos"] and r["datos"]["dni"] == "30123456", "girado 90°: lo lee igual")
    r = L.leer(jpeg(Image.new("RGB", (800, 500), (230, 235, 230))))
    v(r["lado"] == "dorso" and r["datos"] is None, "sin código ni cara: dorso")
    try:
        L.leer(b"esto no es una imagen")
        v(False, "un archivo que no es imagen lanza LectorError")
    except L.LectorError:
        v(True, "un archivo que no es imagen lanza LectorError")
    foto = L.retrato(jpeg(Image.new("RGB", (900, 600), (200, 180, 160))))
    v(Image.open(io.BytesIO(foto)).size == (L.FOTO_ANCHO, L.FOTO_ALTO), "retrato sin cara: el centro en 3×4")

print("\nComparación con la ficha (afiliados_dni.comparar)")
try:
    import afiliados_dni as A
except ImportError as e:          # sin Flask o sin PyMySQL instalados
    print(f"  (no se importa afiliados_dni: {e})")
else:
    d = L.parsear_codigo(TARJETA)
    ficha = {"nro_documento": "30123456", "apellido_nombres": "GÓMEZ PÉREZ MARÍA", "sexo": "F",
             "fecha_nacimiento": date(1984, 5, 2)}
    c = {f["campo"]: f["ok"] for f in A.comparar(d, ficha)}
    v(all(c.values()), "todo coincide (sin acentos, con un solo nombre en la ficha)")
    c = {f["campo"]: f["ok"] for f in A.comparar(d, dict(ficha, apellido_nombres="GOMEZ ANA", sexo="M"))}
    v(c["Apellido"] is False and c["Nombres"] is False and c["Sexo"] is False, "otro apellido, nombre y sexo")
    v(c["Documento"] and c["Nacimiento"], "documento y nacimiento siguen bien")
    c = {f["campo"]: f["ok"] for f in A.comparar(d, dict(ficha, fecha_nacimiento=None))}
    v(c["Nacimiento"] is None, "sin nacimiento en la ficha: no se compara")
    d2 = L.parsear_codigo(TARJETA.replace("@F@", "@2@"))
    v({f["campo"]: f["ok"] for f in A.comparar(d2, ficha)}["Sexo"] is True, "sexo «2» = F: coincide")
    d2 = L.parsear_codigo(TARJETA.replace("@F@", "@9@"))
    v({f["campo"]: f["ok"] for f in A.comparar(d2, ficha)}["Sexo"] is None, "sexo desconocido: no se compara")
    v(A.comparar(None, ficha) == [], "sin código: nada que comparar")

print(f"\n{ok} bien, {fallos} mal")
sys.exit(1 if fallos else 0)
