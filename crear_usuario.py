"""
crear_usuario.py — Alta de usuarios de la aplicación `sindicato` desde la consola.

Existe porque el primer usuario no se puede crear desde la pantalla de alta de
usuarios: para llegar a esa pantalla hay que estar logueado. Después del
primero sigue siendo útil para desbloquear una cuenta o resetear una
contraseña sin entrar a la base a mano.

Uso: completar el .env de esta carpeta y correr

    python crear_usuario.py

Pide los datos y no toma la contraseña por argumento a propósito: lo que se
escribe en la línea de comandos queda en el historial de la terminal.
"""

import getpass
import sys
from pathlib import Path

from dotenv import load_dotenv

# Contra `__file__` y no contra el directorio de trabajo: este script se corre
# a mano desde cualquier lado, y el .env tiene que ser siempre el de al lado.
load_dotenv(Path(__file__).with_name(".env"))

from werkzeug.security import generate_password_hash   # noqa: E402

from db import get_connection                          # noqa: E402


LARGO_MINIMO = 8


def _pedir_email() -> str:
    email = input("Correo: ").strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        salir("Ese correo no tiene forma de correo.")
    if len(email) > 150:
        salir("El correo no puede pasar de 150 caracteres.")
    return email


def _pedir_clave() -> str:
    clave = getpass.getpass("Contraseña: ")
    if len(clave) < LARGO_MINIMO:
        salir(f"La contraseña necesita al menos {LARGO_MINIMO} caracteres.")
    if clave != getpass.getpass("Repetir contraseña: "):
        salir("Las contraseñas no coinciden.")
    return clave


def salir(mensaje: str):
    print(f"\n  {mensaje}\n")
    sys.exit(1)


def main():
    print("\n  Alta de usuario — base `sindicato`\n")

    email = _pedir_email()

    nombre = input("Nombre y apellido: ").strip()
    if not nombre:
        salir("El nombre no puede quedar vacío.")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, nombre, activo FROM s_usuarios WHERE email = %s",
                (email,)
            )
            existente = cur.fetchone()

    # Si el correo ya está, se ofrece pisar la contraseña en vez de fallar:
    # "ya existe" a secas obliga a ir a la base a mano, que es justo lo que
    # este script viene a evitar. Pero se pregunta, porque cambiarle la
    # contraseña a otro sin querer es peor que un error.
    if existente:
        estado = "activo" if existente["activo"] else "INACTIVO"
        print(f"\n  Ya existe: {existente['nombre']} ({estado}).")
        if input("  ¿Reemplazar su contraseña? [s/N]: ").strip().lower() != "s":
            salir("No se cambió nada.")

    clave = _pedir_clave()
    # `generate_password_hash` usa scrypt y guarda el salt y los parámetros
    # dentro del propio string, que es lo que `check_password_hash` lee al
    # verificar. Por eso no hay ninguna columna de salt en la tabla.
    hash_clave = generate_password_hash(clave)

    with get_connection() as conn:
        with conn.cursor() as cur:
            if existente:
                cur.execute(
                    "UPDATE s_usuarios "
                    "SET nombre = %s, password_hash = %s, activo = 1 "
                    "WHERE id = %s",
                    (nombre, hash_clave, existente["id"])
                )
                id_usuario = existente["id"]
                accion = "actualizado"
            else:
                cur.execute(
                    "INSERT INTO s_usuarios (email, nombre, password_hash, activo) "
                    "VALUES (%s, %s, %s, 1)",
                    (email, nombre, hash_clave)
                )
                # `lastrowid` se lee acá adentro: fuera del context manager el
                # cursor ya está cerrado.
                id_usuario = cur.lastrowid
                accion = "creado"

    print(f"\n  Usuario {accion}: {nombre} <{email}> (id {id_usuario})")

    # Los roles todavía no están armados, así que no hay nada que asignar. Se
    # avisa una vez y no se pregunta: un menú vacío no ayuda a nadie.
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM s_roles WHERE activo = 1")
            if cur.fetchone()["n"] == 0:
                print("  Sin roles definidos todavía: entra, pero `tiene_rol()` "
                      "va a dar False para todo.")

    print("  Ya podés entrar en /login\n")


if __name__ == "__main__":
    main()
