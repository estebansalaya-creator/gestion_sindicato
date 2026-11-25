"""
lector_dni.py — Lee la foto de un DNI argentino: el código PDF417 del frente
y la cara, para la foto de la ficha del afiliado.

Lo usa la pantalla «Carga de DNI» (afiliados_dni.py). No toca la base: recibe
los bytes de una imagen y devuelve lo que pudo leer.

**El código del frente** trae los datos separados por «@». Hay dos formatos:

- DNI tarjeta (desde 2012):
  ``trámite@APELLIDO@NOMBRES@sexo@DNI@ejemplar@nacimiento@emisión[@…]``.
  No trae vencimiento, domicilio ni CUIL.
- DNI libreta nuevo (2009-2011) y algunas tarjetas viejas: empieza con «@»,
  ``@DNI@ejemplar@…@APELLIDO@NOMBRES@nacionalidad@nacimiento@sexo@emisión@trámite@…@vencimiento@…``.

El sexo viene como letra (M/F/X) o como el código de ARCA / ANSES: 1 masculino,
2 femenino, 3 otro (X). Cualquier otra cosa queda vacía y se dice.

**Frente o dorso.** La imagen con el código es el frente. Sin código, si tiene
una cara es un frente que no se pudo leer (foto movida, reflejo); si no, se
trata como dorso. El dorso no tiene código en el DNI tarjeta: el domicilio sale
del OCR si está tesseract (lector_pdf_ocr), y si no, no sale.

**La foto.** OpenCV (detector de caras de Haar, que viene en el wheel) busca la
cara más grande, probando la imagen girada si el celular la sacó de costado, y
recorta un retrato 3×4 alrededor. Devuelve un JPEG de 300×400.

Las librerías (zxing-cpp, opencv-python-headless, Pillow) se importan recién al
leer: la aplicación arranca sin ellas y la pantalla avisa qué falta.
"""

from __future__ import annotations

import io
import re
from datetime import date, datetime

#: Tamaño del retrato que se guarda (3×4).
FOTO_ANCHO, FOTO_ALTO = 300, 400


class LectorError(Exception):
    """Algo que impide leer (falta una librería, el archivo no es una imagen)."""


# ─────────────────────────────────────────────────────────────────────────────
# El texto del código
# ─────────────────────────────────────────────────────────────────────────────

def _fecha(txt: str) -> date | None:
    txt = (txt or "").strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(txt, fmt).date()
        except ValueError:
            pass
    return None


#: El sexo con el código de la tabla de ARCA / ANSES (1 masculino, 2 femenino, 3 otro).
SEXO_CODIGO = {"1": "M", "2": "F", "3": "X"}


def _sexo(txt: str) -> str | None:
    s = (txt or "").strip().upper()
    s = SEXO_CODIGO.get(s, s)
    return s if s in ("M", "F", "X") else None


def _dni(txt: str) -> str:
    return re.sub(r"\D", "", txt or "")


def parsear_codigo(texto: str) -> dict | None:
    """
    Los datos del texto del PDF417, o None si no es el de un DNI.

    Devuelve: formato ('tarjeta' / 'libreta'), tramite, apellido, nombres,
    sexo (M/F/X o None), sexo_codigo (lo que venía), dni, ejemplar,
    fecha_nacimiento, fecha_emision, fecha_vencimiento (solo libreta).
    """
    if not texto or "@" not in texto:
        return None
    c = [x.strip() for x in texto.split("@")]

    if c[0] == "" and len(c) >= 11:
        # Libreta: @DNI@ejemplar@?@APELLIDO@NOMBRES@nacionalidad@nacimiento@sexo@emisión@trámite@?@vencimiento
        d = {"formato": "libreta", "dni": _dni(c[1]), "ejemplar": c[2] or None,
             "apellido": c[4], "nombres": c[5], "nacionalidad": c[6] or None,
             "fecha_nacimiento": _fecha(c[7]), "sexo_codigo": c[8], "sexo": _sexo(c[8]),
             "fecha_emision": _fecha(c[9]), "tramite": _dni(c[10]) or None,
             "fecha_vencimiento": _fecha(c[12]) if len(c) > 12 else None}
    elif len(c) >= 8:
        d = {"formato": "tarjeta", "tramite": _dni(c[0]) or None, "apellido": c[1], "nombres": c[2],
             "sexo_codigo": c[3], "sexo": _sexo(c[3]), "dni": _dni(c[4]), "ejemplar": c[5] or None,
             "fecha_nacimiento": _fecha(c[6]), "fecha_emision": _fecha(c[7]),
             "nacionalidad": None, "fecha_vencimiento": None}
    else:
        return None

    # Un código cualquiera con «@» no es un DNI: tiene que haber número y apellido.
    if not (6 <= len(d["dni"]) <= 9) or not d["apellido"]:
        return None
    d["apellido_nombres"] = " ".join(x for x in (d["apellido"].upper(), d["nombres"].upper()) if x)
    return d


# ─────────────────────────────────────────────────────────────────────────────
# La imagen
# ─────────────────────────────────────────────────────────────────────────────

def _libs():
    faltan = []
    try:
        import zxingcpp  # noqa: F401
    except ImportError:
        faltan.append("zxing-cpp")
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        faltan.append("opencv-python-headless")
    try:
        import PIL  # noqa: F401
    except ImportError:
        faltan.append("Pillow")
    return faltan


def disponible() -> list[str]:
    """Las librerías que faltan (vacío: se puede leer)."""
    return _libs()


def _abrir(contenido: bytes):
    """La imagen como PIL RGB, enderezada según el EXIF del celular."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        img = Image.open(io.BytesIO(contenido))
        img = ImageOps.exif_transpose(img)
        return img.convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        raise LectorError("El archivo no es una imagen que se pueda abrir (JPG, PNG o WEBP).") from e


def _leer_codigo(img) -> tuple[str | None, int]:
    """
    El texto del PDF417. Una foto de celular rara vez sale a la primera: con
    reflejos y el código chico, en grises solo falla, y binarizada (Otsu o
    umbral adaptativo) y a otra escala sale. Se prueba hasta que una lea.
    Devuelve el texto y cuánto hay que girar la imagen (para PIL, antihorario)
    para que el código quede derecho: con eso se busca la cara primero.
    """
    import cv2
    import numpy as np
    import zxingcpp
    gris = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    # Las fotos enormes se achican primero: el código ya tiene píxeles de sobra.
    if max(gris.shape) > 2400:
        f = 2400 / max(gris.shape)
        gris = cv2.resize(gris, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    for escala in (1, 0.75, 1.5, 2):
        g = gris if escala == 1 else cv2.resize(
            gris, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA if escala < 1 else cv2.INTER_CUBIC)
        for im in (g,
                   cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
                   cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10)):
            for r in zxingcpp.read_barcodes(im, formats=zxingcpp.BarcodeFormat.PDF417):
                if r.text:
                    rot = getattr(r, "rotation", None)
                    rot = r.orientation if rot is None else rot
                    return r.text, (-int(rot)) % 360
    return None, 0


def _cara_derecha(gris_np):
    """
    La cara más grande, solo si está derecha: el detector de caras a veces
    «ve» una cara cabeza abajo, así que se pide además al menos un ojo en la
    mitad de arriba del recuadro. (x, y, w, h) o None.
    """
    import cv2
    caras_det = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    ojos_det = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
    if caras_det.empty() or ojos_det.empty():
        raise LectorError("La instalación de OpenCV no trae los detectores de caras: "
                          "instalar opencv-python-headless anterior a la 5.")
    lado = min(gris_np.shape[:2])
    minimo = max(40, int(lado * 0.12))
    caras = caras_det.detectMultiScale(gris_np, scaleFactor=1.1, minNeighbors=6, minSize=(minimo, minimo))
    for x, y, w, h in sorted(caras, key=lambda c: -c[2] * c[3]):
        arriba = gris_np[y:y + h // 2, x:x + w]
        ojos = ojos_det.detectMultiScale(arriba, scaleFactor=1.1, minNeighbors=5,
                                         minSize=(max(8, w // 10), max(8, w // 10)))
        if len(ojos):
            return x, y, w, h
    return None


def _recortar_foto(img, giro_primero: int = 0) -> bytes | None:
    """
    El retrato 3×4 alrededor de la cara, en JPEG; None si no hay cara.
    `giro_primero`: el giro que conviene probar primero (el que dio el código).
    """
    import numpy as np
    from PIL import Image

    # La imagen se achica para buscar (más rápido) y se recorta del original.
    escala = min(1.0, 1400 / max(img.size))
    giros = [giro_primero] + [g for g in (0, 90, 270, 180) if g != giro_primero]
    for giro in giros:
        im = img.rotate(giro, expand=True) if giro else img
        chica = im.resize((int(im.width * escala), int(im.height * escala))) if escala < 1 else im
        cara = _cara_derecha(np.array(chica.convert("L")))
        if cara is None:
            continue
        x, y, w, h = (v / escala for v in cara)
        # Retrato: la cara ocupa algo más de la mitad del ancho, con frente y
        # pelo arriba y el cuello abajo, como la foto impresa del DNI.
        ancho = w * 1.5
        alto = ancho * FOTO_ALTO / FOTO_ANCHO
        cx = x + w / 2
        arriba = y - h * 0.4
        izq = cx - ancho / 2
        # Sin salirse de la imagen: se corre el recuadro y, si no entra, se achica.
        ancho = min(ancho, im.width)
        alto = min(alto, im.height)
        izq = min(max(0, izq), im.width - ancho)
        arriba = min(max(0, arriba), im.height - alto)
        foto = im.crop((int(izq), int(arriba), int(izq + ancho), int(arriba + alto)))
        foto = foto.resize((FOTO_ANCHO, FOTO_ALTO), Image.LANCZOS)
        salida = io.BytesIO()
        foto.save(salida, "JPEG", quality=88)
        return salida.getvalue()
    return None


def retrato(contenido: bytes) -> bytes:
    """
    La foto de la ficha a partir de cualquier imagen (una foto carnet, una
    selfie): la cara recortada si se encuentra; si no, el centro de la imagen
    en 3×4. Lanza LectorError si no es una imagen o falta una librería.
    """
    from PIL import Image, ImageOps
    faltan = [x for x in _libs() if x != "zxing-cpp"]
    if faltan:
        raise LectorError("Falta instalar en el servidor: " + ", ".join(faltan) + ".")
    img = _abrir(contenido)
    foto = _recortar_foto(img)
    if foto:
        return foto
    centro = ImageOps.fit(img, (FOTO_ANCHO, FOTO_ALTO), Image.LANCZOS, centering=(0.5, 0.4))
    salida = io.BytesIO()
    centro.save(salida, "JPEG", quality=88)
    return salida.getvalue()


def _domicilio_ocr(img) -> str | None:
    """El renglón «DOMICILIO …» del dorso, si hay tesseract. None si no se pudo."""
    try:
        import pytesseract
        from PIL import ImageOps
        texto = pytesseract.image_to_string(ImageOps.grayscale(img), lang="spa")
    except Exception:       # sin tesseract (o sin el idioma) el dorso se guarda igual, sin domicilio
        return None
    m = re.search(r"DOMICILIO[:\s]+(.+)", texto, re.IGNORECASE)
    return re.sub(r"\s+", " ", m.group(1)).strip(" .,") if m else None


def leer(contenido: bytes) -> dict:
    """
    Lo que se pudo sacar de una imagen:

        lado      'frente' (con código o con cara) o 'dorso'
        codigo    el texto del PDF417, o None
        datos     parsear_codigo(codigo), o None
        foto      JPEG 300×400 de la cara (solo del frente), o None
        domicilio el renglón del dorso por OCR, o None
        avisos    lista de textos para mostrar

    Lanza LectorError si faltan librerías o no es una imagen.
    """
    faltan = _libs()
    if faltan:
        raise LectorError("Falta instalar en el servidor: " + ", ".join(faltan) + ".")
    img = _abrir(contenido)
    avisos: list[str] = []
    codigo, giro = _leer_codigo(img)
    datos = parsear_codigo(codigo) if codigo else None
    if codigo and not datos:
        avisos.append("Tiene un código PDF417, pero no es el de un DNI.")
    foto = _recortar_foto(img, giro)

    if datos or foto:
        lado = "frente"
        if not datos:
            avisos.append("Parece el frente, pero el código no se pudo leer: probá con una foto más nítida, "
                          "sin reflejos sobre el código.")
        if not foto:
            avisos.append("No se encontró la cara para la foto de la ficha.")
        if datos and datos["sexo"] is None and datos.get("sexo_codigo"):
            avisos.append(f"El código trae el sexo como «{datos['sexo_codigo']}», que no es M, F, X ni 1, 2, 3: "
                          "no se toma, vale lo de la ficha.")
        domicilio = None
    else:
        lado = "dorso"
        domicilio = _domicilio_ocr(img)
    return {"lado": lado, "codigo": codigo, "datos": datos, "foto": foto,
            "domicilio": domicilio, "avisos": avisos}


def _main(argv: list[str]) -> int:
    """python lector_dni.py imagen.jpg [otra.jpg]: lo que lee, sin la base."""
    from pathlib import Path
    for ruta in argv:
        r = leer(Path(ruta).read_bytes())
        print(f"{ruta}: {r['lado']}")
        for k, v in (r["datos"] or {}).items():
            print(f"   {k:18} {v}")
        if r["domicilio"]:
            print(f"   domicilio          {r['domicilio']}")
        if r["foto"]:
            salida = Path(ruta).with_suffix(".foto.jpg")
            salida.write_bytes(r["foto"])
            print(f"   foto               {salida}")
        for a in r["avisos"]:
            print(f"   ! {a}")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
