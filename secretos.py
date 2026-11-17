"""
Cifrado simétrico de credenciales de terceros (copia de gestion_adm, 17/11/2026).

En el sindicato la clave es `SIND_FERNET_KEY` (el prefijo de todas las variables
de esta app). El IIS local y Railway usan la MISMA base: la clave tiene que ser
la misma en los dos, o lo que cifra uno el otro no lo puede leer.

==============================================

POR QUÉ ESTE MÓDULO EXISTE
--------------------------
Estas cuatro funciones vivían dentro de `firma_digital.py`, que es el módulo
del circuito de firma de la SSS y arrastra pyHanko, asn1crypto y requests.
Cualquier pantalla que quisiera guardar una contraseña tenía que importar todo
eso para usar veinte líneas de cifrado. Acá no dependen de nada más que de
`cryptography`, así que las puede usar cualquiera.

`firma_digital.py` las sigue exponiendo con el mismo nombre para no romper lo
que ya las importa de ahí.

QUÉ PROTEGE Y QUÉ NO
--------------------
Fernet es AES-128-CBC con HMAC-SHA256: cifra y además detecta si el texto
cifrado fue alterado. Protege la contraseña frente a quien lea la BASE —un
backup que se copia a un pendrive, un dump que se manda por mail, un SELECT de
alguien que tiene acceso de lectura—.

NO protege frente a quien tenga el servidor completo: la clave está en el
entorno del proceso, así que quien puede leer las variables de entorno puede
descifrar. Eso es inherente a cualquier esquema donde la aplicación necesite la
contraseña en claro para usarla; la alternativa sería pedírsela a una persona
cada vez, y entonces nada puede correr solo de noche.

LA CLAVE SE PIERDE, LOS SECRETOS SE PIERDEN
-------------------------------------------
Si `SIND_FERNET_KEY` cambia o se pierde, todo lo cifrado con la anterior queda
ilegible y hay que volver a cargar cada contraseña a mano. No es una catástrofe
—son un par de campos— pero tiene que estar dicho: la clave va en el backup de
configuración, no en el repositorio.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

__all__ = ["cifrar_secret", "descifrar_secret", "hay_clave", "InvalidToken"]


# La clave se busca en el entorno del proceso y, si no está, en el .env de al
# lado de ESTE archivo, resuelto por __file__ (IIS arranca donde quiere).
_ENV_LOCAL = Path(__file__).with_name(".env")
_VARIABLE = "SIND_FERNET_KEY"


def _leer_env_local(nombre: str) -> str:
    """
    Busca una variable en el .env que acompaña a este archivo.

    Se parsea a mano en vez de usar python-dotenv para no depender de que esté
    instalado ni de que alguien lo haya llamado antes: son cuatro líneas y esto
    tiene que funcionar igual desde la web, desde un scheduler y desde un
    `python -c` suelto.
    """
    try:
        with _ENV_LOCAL.open(encoding="utf-8") as fh:
            for linea in fh:
                linea = linea.strip()
                if not linea or linea.startswith("#") or "=" not in linea:
                    continue
                clave, _, valor = linea.partition("=")
                if clave.strip() == nombre:
                    return valor.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _clave_configurada() -> str:
    """El entorno manda; el .env es el respaldo para desarrollo."""
    return (os.getenv(_VARIABLE) or "").strip() or _leer_env_local(_VARIABLE)


def _get_fernet() -> Fernet:
    key = _clave_configurada()
    if not key:
        raise RuntimeError(
            f"Falta {_VARIABLE}. Generá una clave con:\n"
            "  python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"\n"
            f"y cargala como variable de entorno, en web.config o en {_ENV_LOCAL}."
        )
    return Fernet(key.encode())


def hay_clave() -> bool:
    """
    ¿Está configurado el cifrado?

    Sirve para que las pantallas avisen antes y no después: sin esto, el
    usuario escribe la contraseña, aprieta guardar y recién ahí se entera de
    que el servidor no puede cifrarla.
    """
    return bool(_clave_configurada())


def cifrar_secret(texto_plano: str) -> bytes:
    """Cifra un secreto; devuelve bytes aptos para VARBINARY."""
    return _get_fernet().encrypt(texto_plano.encode("utf-8"))


def descifrar_secret(token_cifrado: bytes) -> str:
    """Descifra un secreto. Lanza InvalidToken si la SIND_FERNET_KEY cambió."""
    return _get_fernet().decrypt(bytes(token_cifrado)).decode("utf-8")
