"""
documentacion.py — Documentación adjunta de una entidad (`p_documentacion`).

La misma idea que contactos.py: la lógica vive acá una vez y cada pantalla
incluye el parcial `_documentacion.html`. Hoy la usa la ficha del afiliado; la
tabla ya está pensada para cualquier entidad (`entidad_tipo` + `entidad_id`),
y los tipos (`p_tipo_documentacion.aplica_a`) dicen a qué entidad corresponde
cada uno. Los que tienen `aplica_a` vacío sirven para todas.

Los archivos van a SIND_ADJUNTOS/documentacion/<entidad>/<id>/, con un nombre
generado (`nombre_archivo`) y el original guardado aparte (`nombre_original`):
dos «DNI.pdf» del mismo afiliado no se pisan, y un nombre con barras o puntos
no arma una ruta afuera de la carpeta.

Los permisos los controla la pantalla que llama, no este módulo: cada una sabe
quién puede ver y quién puede modificar lo suyo.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

#: Lo mismo que aceptan los reintegros: PDF o imagen.
EXTENSIONES = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
MAX_MB = 10

MIME = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".webp": "image/webp", ".tif": "image/tiff", ".tiff": "image/tiff"}


class DocumentoError(Exception):
    """Un archivo que no se puede guardar, con el motivo para mostrar."""


def base() -> Path:
    return Path(os.getenv("SIND_ADJUNTOS") or Path(__file__).with_name("adjuntos"))


def _carpeta(entidad: str, entidad_id: int) -> Path:
    return base() / "documentacion" / entidad / str(int(entidad_id))


def _aplica(entidad: str) -> str:
    # aplica_a es una lista separada por comas («empresa,empleador»).
    return ("(t.aplica_a IS NULL OR t.aplica_a = '' "
            f"OR FIND_IN_SET('{entidad}', REPLACE(t.aplica_a, ' ', '')))")


def tipos(cur, entidad: str) -> list[dict]:
    """Los tipos que se ofrecen: los de la entidad primero, después los generales."""
    cur.execute(f"""SELECT t.id_tipo_doc, t.codigo, t.descripcion, t.obligatorio
                      FROM p_tipo_documentacion t
                     WHERE t.activo = 1 AND {_aplica(entidad)}
                     ORDER BY t.aplica_a IS NULL OR t.aplica_a = '', t.orden, t.descripcion""")
    return cur.fetchall()


def de(cur, entidad: str, entidad_id: int) -> list[dict]:
    cur.execute("""SELECT d.id_documento, d.id_tipo_doc, t.descripcion AS tipo, d.nombre_original,
                          d.extension, d.tamanio_bytes, d.observaciones, d.subido_por, d.created_at
                     FROM p_documentacion d
                     JOIN p_tipo_documentacion t ON t.id_tipo_doc = d.id_tipo_doc
                    WHERE d.entidad_tipo = %s AND d.entidad_id = %s
                    ORDER BY d.created_at DESC, d.id_documento DESC""", (entidad, entidad_id))
    return cur.fetchall()


def faltantes(cur, entidad: str, entidad_id: int) -> list[str]:
    """Los tipos obligatorios de la entidad que todavía no tienen ningún archivo."""
    cur.execute(f"""SELECT t.descripcion FROM p_tipo_documentacion t
                     WHERE t.activo = 1 AND t.obligatorio = 1
                       AND t.aplica_a IS NOT NULL AND {_aplica(entidad)}
                       AND NOT EXISTS (SELECT 1 FROM p_documentacion d
                                        WHERE d.id_tipo_doc = t.id_tipo_doc
                                          AND d.entidad_tipo = %s AND d.entidad_id = %s)
                     ORDER BY t.orden, t.descripcion""", (entidad, entidad_id))
    return [f["descripcion"] for f in cur.fetchall()]


def guardar(cur, entidad: str, entidad_id: int, id_tipo_doc, archivo, observaciones: str,
            usuario: str) -> dict:
    """
    Guarda el archivo y su fila. Si el INSERT falla se borra el archivo: no
    queda un archivo huérfano en la carpeta. Devuelve la fila, con el tipo.
    """
    if not archivo or not archivo.filename:
        raise DocumentoError("Elegí el archivo.")
    if not str(id_tipo_doc or "").isdigit():
        raise DocumentoError("Elegí el tipo de documento.")
    validos = {t["id_tipo_doc"]: t["descripcion"] for t in tipos(cur, entidad)}
    if int(id_tipo_doc) not in validos:
        raise DocumentoError("Ese tipo de documento no corresponde o está inactivo.")

    original = Path(archivo.filename).name.strip() or "documento"
    ext = Path(original).suffix.lower()
    if ext not in EXTENSIONES:
        raise DocumentoError(f"{original}: solo PDF o imagen (JPG, PNG, WEBP, TIF).")

    carpeta = _carpeta(entidad, entidad_id)
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre = uuid.uuid4().hex + ext
    destino = carpeta / nombre
    archivo.save(destino)
    tam = destino.stat().st_size
    if tam > MAX_MB * 1024 * 1024:
        destino.unlink(missing_ok=True)
        raise DocumentoError(f"{original}: supera los {MAX_MB} MB.")
    if tam == 0:
        destino.unlink(missing_ok=True)
        raise DocumentoError(f"{original}: el archivo está vacío.")
    try:
        cur.execute("""INSERT INTO p_documentacion
                           (entidad_tipo, entidad_id, id_tipo_doc, nombre_original, nombre_archivo,
                            extension, mime_type, tamanio_bytes, observaciones, subido_por)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (entidad, entidad_id, int(id_tipo_doc), original[:255], nombre, ext.lstrip("."),
                     MIME.get(ext), tam, (observaciones or "").strip()[:300] or None, usuario[:80]))
    except Exception:
        destino.unlink(missing_ok=True)
        raise
    # `archivo`: para que quien llama lo borre si después la transacción se deshace.
    return {"id_documento": cur.lastrowid, "tipo": validos[int(id_tipo_doc)],
            "nombre_original": original, "archivo": destino}


def uno(cur, entidad: str, entidad_id: int, id_documento: int) -> dict | None:
    """El documento, solo si es de esa entidad: el id solo no alcanza para servirlo."""
    cur.execute("""SELECT d.*, t.descripcion AS tipo FROM p_documentacion d
                     JOIN p_tipo_documentacion t ON t.id_tipo_doc = d.id_tipo_doc
                    WHERE d.id_documento = %s AND d.entidad_tipo = %s AND d.entidad_id = %s""",
                (id_documento, entidad, entidad_id))
    return cur.fetchone()


def ruta(doc: dict) -> Path | None:
    """El archivo en disco, o None si no está. Nunca afuera de su carpeta."""
    carpeta = _carpeta(doc["entidad_tipo"], doc["entidad_id"]).resolve()
    real = (carpeta / doc["nombre_archivo"]).resolve()
    if carpeta not in real.parents or not real.is_file():
        return None
    return real


def borrar(cur, doc: dict) -> Path | None:
    """
    Borra la fila y devuelve el archivo, que se borra DESPUÉS del commit: si la
    transacción se deshace, el documento sigue entero, fila y archivo.
    """
    cur.execute("DELETE FROM p_documentacion WHERE id_documento = %s", (doc["id_documento"],))
    return ruta(doc)
