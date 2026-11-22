"""
almacenamiento.py — Los archivos que sube la gente: el disco y el bucket

Todo lo que la aplicación guarda como archivo cuelga de una sola carpeta,
SIND_ADJUNTOS (en IIS y en desarrollo, `adjuntos/` del proyecto; en Railway,
el volumen de /data):

    reintegros/<id>/            comprobantes de los reintegros
    documentacion/<ent>/<id>/   documentación de afiliados (y lo que se sume)
    comprobantes/AAAAMM/        PDF de los comprobantes de proveedores
    tmp_comprobantes/           el PDF entre que se sube y se confirma la carga
    institucion/                el logo
    campanias/                  los flyers de Beneficios › Campañas
    novedades_empresa/          las fichas de afiliación que adjuntan las empresas
    chat/<conv>/                los adjuntos de Mensajes
    arca/                       los tickets de acceso de ARCA (caché, NO va al bucket)

POR QUE HAY UN BUCKET
---------------------
Pedido del 22/11/2026, para poder correr en DigitalOcean App Platform (sin
disco permanente) o con más de una instancia de la app. El disco sigue siendo
la copia de trabajo y el bucket la que sobrevive:

- al guardar, se escribe al disco y se sube la copia (`guardar` o
  `respaldar`);
- al leer, si el archivo no está en este disco se lo trae del bucket y se lo
  deja en su lugar (`local`). El resto del código sigue trabajando con una
  ruta: send_file, el lector de PDF, el adjunto de un mail;
- al borrar, se borran los dos (`borrar`).

La clave en el bucket es la ruta relativa a SIND_ADJUNTOS
(«comprobantes/202611/x.pdf»): el mismo archivo tiene la misma clave lo haya
escrito IIS, Railway o DigitalOcean. Es lo que permite subir lo que ya hay con
`python almacenamiento.py --subir --aplicar` y después cambiar de lugar.

SIN BUCKET
----------
Si no hay SIND_BUCKET (objetos.py) nada de esto hace nada más que el disco:
`respaldar` no sube, `local` devuelve la ruta tal cual. IIS, desarrollo y el
Railway de hoy siguen exactamente igual.

    python almacenamiento.py                     estado y cuánto hay en cada carpeta
    python almacenamiento.py --subir             qué falta subir al bucket (simula)
    python almacenamiento.py --subir --aplicar   lo sube
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import objetos

log = logging.getLogger(__name__)

#: Carpetas que no van al bucket: son caché y se regeneran solas.
NO_VAN = ("arca",)

#: Cuánto se recuerda que un archivo no está en el bucket. El logo se busca en
#: cada pantalla: sin esto, un logo que falta sería un pedido al bucket por request.
_FALTA_SEG = 120
_faltan: dict[str, float] = {}


def base() -> Path:
    """La carpeta de los archivos. Se lee cada vez: el .env puede cargarse después del import."""
    return Path(os.getenv("SIND_ADJUNTOS") or Path(__file__).with_name("adjuntos"))


def hay_bucket() -> bool:
    return objetos.disponible()


def clave_de(ruta) -> str:
    """La clave del archivo en el bucket, o "" si no corresponde (fuera de la base, o caché)."""
    try:
        raiz = os.path.normcase(os.path.abspath(base()))
        p = os.path.normcase(os.path.abspath(ruta))
        if not p.startswith(raiz + os.sep):
            return ""
        rel = Path(os.path.relpath(os.path.abspath(ruta), os.path.abspath(base()))).as_posix()
    except (OSError, ValueError):
        return ""
    if not rel or rel.startswith("../") or rel.split("/", 1)[0] in NO_VAN:
        return ""
    return rel


def respaldar(ruta, contenido: bytes | None = None, tipo_mime: str = "") -> bool:
    """
    Sube la copia de un archivo que ya está en el disco. Nunca lanza.
    Sin bucket no hace nada: se puede poner al lado de cada `save()` sin condicionales.
    """
    if not hay_bucket():
        return False
    clave = clave_de(ruta)
    if not clave:
        return False
    try:
        datos = contenido if contenido is not None else Path(ruta).read_bytes()
    except OSError as e:
        log.warning("No se pudo leer %s para subirlo al bucket: %s", ruta, e)
        return False
    _faltan.pop(clave, None)
    return objetos.guardar(clave, datos, tipo_mime)


def guardar(ruta, contenido: bytes, tipo_mime: str = "") -> Path:
    """Escribe el archivo al disco y sube la copia. Devuelve la ruta. Lanza OSError si no pudo escribir."""
    p = Path(ruta)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(contenido)
    respaldar(p, contenido, tipo_mime)
    return p


def local(ruta) -> Path:
    """
    La ruta del archivo, con el archivo en este disco si está en algún lado.

    Si no está en el disco y sí en el bucket, se lo trae y se lo deja en su
    lugar (lo que hace falta después de un deploy, o en la otra instancia).
    Si no está en ninguno de los dos, devuelve la ruta igual: el que llama
    hace su `is_file()` de siempre y dice que no está.
    """
    p = Path(ruta)
    if p.is_file() or not hay_bucket():
        return p
    clave = clave_de(p)
    if not clave:
        return p
    if time.monotonic() - _faltan.get(clave, -1e9) < _FALTA_SEG:
        return p
    datos = objetos.leer(clave)
    if datos is None:
        _faltan[clave] = time.monotonic()
        return p
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + f".bajando{os.getpid()}")
        tmp.write_bytes(datos)
        os.replace(tmp, p)        # dos pedidos a la vez no dejan un archivo a medias
    except OSError as e:
        log.warning("Se trajo %s del bucket pero no se pudo escribir en el disco: %s", clave, e)
    return p


def existe(ruta) -> bool:
    """¿El archivo está, en el disco o en el bucket? (Si está en el bucket, queda en el disco.)"""
    return local(ruta).is_file()


def leer(ruta) -> bytes | None:
    """El contenido, venga del disco o del bucket; None si no está."""
    p = local(ruta)
    try:
        return p.read_bytes() if p.is_file() else None
    except OSError:
        return None


def borrar(ruta) -> None:
    """Borra el archivo del disco y del bucket. Nunca lanza."""
    try:
        Path(ruta).unlink(missing_ok=True)
    except OSError as e:
        log.warning("No se pudo borrar %s: %s", ruta, e)
    if hay_bucket():
        clave = clave_de(ruta)
        if clave:
            objetos.borrar(clave)
            _faltan.pop(clave, None)


def limpiar_viejos(carpeta: str, dias: float) -> int:
    """
    Borra del bucket lo de una carpeta de paso (tmp_comprobantes) con más de
    `dias`. El disco lo limpia quien la usa; esto es para lo que quedó sólo en
    el bucket, de un contenedor que ya no existe. Devuelve cuántos borró.
    """
    if not hay_bucket():
        return 0
    import datetime as _dt
    limite = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=dias)
    n = 0
    for o in objetos.listar(carpeta.strip("/") + "/"):
        if o.get("modificado") and o["modificado"] < limite and objetos.borrar(o["clave"]):
            n += 1
    return n


# ── Consola: estado y subida de lo que ya hay ────────────────────────────────

def _archivos_locales() -> list[Path]:
    raiz = base()
    if not raiz.is_dir():
        return []
    return [p for p in raiz.rglob("*") if p.is_file() and clave_de(p) and ".bajando" not in p.name]


def _main(argv: list[str]) -> int:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name(".env"))
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    print(f"SIND_ADJUNTOS = {base()}")
    print(f"Bucket        : {objetos.estado()}\n")

    locales = _archivos_locales()
    por_carpeta: dict[str, list[int]] = {}
    for p in locales:
        c = clave_de(p).split("/", 1)[0]
        por_carpeta.setdefault(c, [0, 0])
        por_carpeta[c][0] += 1
        por_carpeta[c][1] += p.stat().st_size
    for c, (n, b) in sorted(por_carpeta.items()):
        print(f"  {c:<22} {n:>7} archivos  {b / 1024 / 1024:>10.1f} MB")
    print(f"  {'total':<22} {len(locales):>7} archivos\n")

    if "--subir" not in argv:
        return 0
    if not hay_bucket():
        print("No hay bucket configurado (SIND_BUCKET): no hay adónde subir.")
        return 1
    en_bucket = {o["clave"]: o["tamanio"] for o in objetos.listar("")}
    faltan = [p for p in locales if en_bucket.get(clave_de(p)) != p.stat().st_size]
    print(f"En el bucket: {len(en_bucket)} objetos. Faltan subir (o difieren): {len(faltan)}.")
    if "--aplicar" not in argv:
        for p in faltan[:20]:
            print("  ", clave_de(p))
        if len(faltan) > 20:
            print(f"   … y {len(faltan) - 20} más")
        print("\nSimulación. Para subirlos: python almacenamiento.py --subir --aplicar")
        return 0
    ok = mal = 0
    for i, p in enumerate(faltan, 1):
        if respaldar(p):
            ok += 1
        else:
            mal += 1
            print("  NO SE SUBIÓ", clave_de(p))
        if i % 100 == 0:
            print(f"  {i}/{len(faltan)}…")
    print(f"\nSubidos: {ok}. Con error: {mal}.")
    return 1 if mal else 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
