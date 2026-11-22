"""
objetos.py — El bucket S3 donde viven los archivos del sindicato

Es el objetos.py de gestion_adm (cliente S3, nunca lanza, boto3 importado
tarde), con las variables de acá. Lo usa sólo almacenamiento.py: los módulos
de pantalla no lo llaman directo.

POR QUE
-------
En una plataforma sin disco permanente (DigitalOcean App Platform) o con más
de una instancia de la app, el archivo que subió una persona no puede vivir
sólo en el disco del contenedor que atendió ese pedido: el próximo deploy lo
borra, y la otra instancia no lo ve. El bucket es el lugar común.

QUÉ PASA SI NO HAY BUCKET
-------------------------
Nada: `disponible()` da False, `guardar()` no hace nada y `leer()` devuelve
None. En IIS, en desarrollo y en Railway con el volumen de /data todo sigue
contra el disco, como hasta ahora. Se prende con la variable del nombre del
bucket y nada más.

VARIABLES
---------
Con prefijo `SIND_`, como todas las de esta aplicación:

    SIND_BUCKET              nombre del bucket (prende esto)
    SIND_BUCKET_ENDPOINT     https://<región>.digitaloceanspaces.com, o el de Railway
    SIND_BUCKET_KEY_ID       \\  las credenciales del bucket
    SIND_BUCKET_SECRET       /
    SIND_BUCKET_REGION       nyc3, sfo3… (o «auto»)
    [SIND_BUCKET_CONNECT_TIMEOUT  SIND_BUCKET_READ_TIMEOUT]   segundos, para una carga masiva

También se aceptan las que inyecta un bucket de Railway al vincularlo
(BUCKET, ENDPOINT, ACCESS_KEY_ID, SECRET_ACCESS_KEY, REGION, o las AWS_*).
Van después de las SIND_: si gestion_adm y el sindicato comparten entorno, las
propias ganan.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_cliente = None
_cliente_intentado = False
_aviso_dado = False

#: Dónde se busca cada dato, en orden.
_NOMBRES = {
    "bucket":   ("SIND_BUCKET", "BUCKET", "AWS_S3_BUCKET_NAME", "AWS_BUCKET", "S3_BUCKET"),
    "endpoint": ("SIND_BUCKET_ENDPOINT", "ENDPOINT", "AWS_ENDPOINT_URL_S3", "AWS_ENDPOINT_URL"),
    "key_id":   ("SIND_BUCKET_KEY_ID", "ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID"),
    "secret":   ("SIND_BUCKET_SECRET", "SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY"),
    "region":   ("SIND_BUCKET_REGION", "REGION", "AWS_REGION", "AWS_DEFAULT_REGION"),
}


def _var(dato: str) -> str:
    for clave in _NOMBRES[dato]:
        valor = (os.getenv(clave) or "").strip()
        if valor:
            return valor
    return ""


def _entero(nombre: str, por_defecto: int) -> int:
    """Un timeout mal tipeado no puede apagar el bucket: se usa el de siempre."""
    try:
        n = int(os.getenv(nombre) or "")
        return n if n > 0 else por_defecto
    except ValueError:
        return por_defecto


def bucket() -> str:
    """Nombre del bucket, o "" si esto está apagado."""
    return _var("bucket")


def estado() -> str:
    """Prendido o apagado, y por qué, en una línea (para el log y el diagnóstico)."""
    nombre = bucket()
    if not nombre:
        return "apagado: no hay nombre de bucket (se probó " + ", ".join(_NOMBRES["bucket"]) + ")"
    return f"prendido: bucket {nombre}"


def disponible() -> bool:
    """Si hay bucket configurado. No abre conexión: se llama en cada archivo."""
    global _aviso_dado
    listo = bool(bucket())
    if not _aviso_dado:
        _aviso_dado = True
        if listo:
            log.info("Bucket %s", estado())
        elif os.getenv("SIND_BUCKET_OBLIGATORIO"):
            log.warning("Bucket %s, y SIND_BUCKET_OBLIGATORIO dice que tiene que haberlo: lo que se "
                        "suba no sobrevive al contenedor.", estado())
    return listo


def _s3():
    """El cliente S3, armado una vez; None si no se puede."""
    global _cliente, _cliente_intentado
    if _cliente is not None or _cliente_intentado:
        return _cliente
    _cliente_intentado = True
    if not disponible():
        return None
    try:
        import boto3                                         # noqa: PLC0415  tarde, a propósito
        from botocore.config import Config
        _cliente = boto3.client(
            "s3",
            endpoint_url=_var("endpoint") or None,
            aws_access_key_id=_var("key_id"),
            aws_secret_access_key=_var("secret"),
            region_name=_var("region") or "auto",
            # Esto corre dentro de un pedido web (alguien abrió un PDF): mejor
            # fallar y decirlo que quedarse colgado.
            config=Config(retries={"max_attempts": 3, "mode": "standard"},
                          connect_timeout=_entero("SIND_BUCKET_CONNECT_TIMEOUT", 10),
                          read_timeout=_entero("SIND_BUCKET_READ_TIMEOUT", 60)),
        )
    except Exception as e:                                   # noqa: BLE001
        log.warning("No se pudo armar el cliente del bucket: %s. Se sigue con el disco solo.", e)
        _cliente = None
    return _cliente


def guardar(clave: str, contenido: bytes, tipo_mime: str = "") -> bool:
    """Sube el contenido. Devuelve si se pudo. No lanza nunca."""
    s3 = _s3()
    if s3 is None:
        return False
    try:
        extra = {"ContentType": tipo_mime} if tipo_mime else {}
        s3.put_object(Bucket=bucket(), Key=clave, Body=contenido, **extra)
        return True
    except Exception as e:                                   # noqa: BLE001
        log.warning("No se pudo guardar %s en el bucket: %s", clave, e)
        return False


def leer(clave: str) -> bytes | None:
    """El contenido, o None si no está o no se pudo traer."""
    s3 = _s3()
    if s3 is None:
        return None
    try:
        return s3.get_object(Bucket=bucket(), Key=clave)["Body"].read()
    except Exception as e:                                   # noqa: BLE001
        log.debug("No se pudo leer %s del bucket: %s", clave, e)
        return None


def borrar(clave: str) -> bool:
    s3 = _s3()
    if s3 is None:
        return False
    try:
        s3.delete_object(Bucket=bucket(), Key=clave)
        return True
    except Exception as e:                                   # noqa: BLE001
        log.warning("No se pudo borrar %s del bucket: %s", clave, e)
        return False


def existe(clave: str) -> bool:
    s3 = _s3()
    if s3 is None:
        return False
    try:
        s3.head_object(Bucket=bucket(), Key=clave)
        return True
    except Exception:                                        # noqa: BLE001
        return False


def listar(prefijo: str = "") -> list[dict]:
    """Todos los objetos bajo un prefijo, paginando: [{clave, tamanio, modificado}]."""
    s3 = _s3()
    if s3 is None:
        return []
    salida, token = [], None
    try:
        while True:
            pedido = {"Bucket": bucket(), "Prefix": prefijo, "MaxKeys": 1000}
            if token:
                pedido["ContinuationToken"] = token
            resp = s3.list_objects_v2(**pedido)
            salida += [{"clave": o["Key"], "tamanio": o.get("Size", 0), "modificado": o.get("LastModified")}
                       for o in resp.get("Contents", [])]
            if not resp.get("IsTruncated"):
                return salida
            token = resp.get("NextContinuationToken")
    except Exception as e:                                   # noqa: BLE001
        log.warning("No se pudo listar %s en el bucket: %s", prefijo, e)
        return salida


def _reset_para_pruebas() -> None:
    global _cliente, _cliente_intentado, _aviso_dado
    _cliente, _cliente_intentado, _aviso_dado = None, False, False
