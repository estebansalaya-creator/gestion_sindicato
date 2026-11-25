"""
afiliado_foto.py — La foto de la ficha del afiliado (`p_afiliados.foto`).

Un retrato 3×4 en JPEG en SIND_ADJUNTOS/fotos/afiliado/<id>/<nombre>.jpg, con
copia en el bucket (almacenamiento.py). La columna guarda la ruta relativa.
Cada foto nueva lleva un nombre nuevo: el navegador no sigue mostrando la
vieja desde su caché.

La graban la carga de DNI (afiliados_dni.py, recortada del frente) y la ficha
(afiliados.py: «Cambiar foto», con una foto cualquiera, y «Quitar foto»).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import almacenamiento

CARPETA_FOTOS = "fotos/afiliado"


def guardar(id_af: int, contenido: bytes) -> Path:
    """Escribe el retrato (disco y bucket) con un nombre nuevo y devuelve la ruta.
    Nombre nuevo cada vez: el navegador no muestra la foto vieja desde su caché."""
    destino = almacenamiento.base() / CARPETA_FOTOS / str(int(id_af)) / f"{uuid.uuid4().hex}.jpg"
    return almacenamiento.guardar(destino, contenido, "image/jpeg")


def relativa(ruta: Path) -> str:
    return Path(ruta).relative_to(almacenamiento.base()).as_posix()


def ruta(rel: str | None) -> Path | None:
    """El archivo de la foto (traído del bucket si hace falta), o None. Nunca afuera de fotos/."""
    if not rel:
        return None
    carpeta = (almacenamiento.base() / CARPETA_FOTOS).resolve()
    real = (almacenamiento.base() / rel).resolve()
    if carpeta not in real.parents:
        return None
    real = almacenamiento.local(real)
    return real if real.is_file() else None


def borrar(rel: str | None):
    if not rel:
        return
    carpeta = (almacenamiento.base() / CARPETA_FOTOS).resolve()
    real = (almacenamiento.base() / rel).resolve()
    if carpeta in real.parents:
        almacenamiento.borrar(real)
