"""
db.py — Conexión MySQL y helpers de sesión del proyecto `sindicato`.

Este archivo es deliberadamente independiente del `db.py` de `gestion_adm`.
No lo importa, no comparte variables de entorno y no comparte claves de sesión.
Esa separación es el punto: las dos aplicaciones pueden convivir en el mismo
servidor —incluso en el mismo proceso, mientras dure el desacople— sin que un
cambio de configuración de una toque a la otra.

Las tres formas concretas en que están separadas:

1. Variables de entorno con prefijo `SIND_`. Si mañana `gestion_adm` cambia su
   `DB_HOST` o su `DB_USER`, esta aplicación no se entera.
2. La base es `sindicato`, siempre. No hay variable para cambiarla, porque no
   hay caso legítimo en el que este código deba escribir en `contable`.
3. Las claves de sesión llevan prefijo `sind_`. Si las dos aplicaciones quedan
   bajo el mismo dominio y comparten cookie, iniciar sesión en una no da acceso
   a la otra.
"""

import os

import pymysql
import pymysql.cursors
from flask import g, has_request_context, session

#: Nombre de la base. Fijo a propósito, no configurable por entorno.
#:
#: La regla de oro del proyecto es que este conector apunta sólo a `sindicato`.
#: Dejarlo como variable de entorno haría que un `.env` mal armado —o copiado
#: de `gestion_adm`— pudiera hacer que este código escriba en `contable` sin
#: que nada falle. Que sea una constante es lo que convierte esa regla en algo
#: que el código garantiza en vez de algo que hay que acordarse.
DB_NAME = "sindicato"

#: Zona horaria de la sesión de MySQL.
#:
#: `NOW()` devuelve la hora del servidor de base, no una hora universal. Con la
#: base local coincide con la del negocio y no se nota; el día que la base esté
#: en la nube arrancando en UTC, `NOW()` queda 3 horas adelante de todas las
#: fechas ya guardadas, sin que falle nada —que es lo peor que puede pasar—.
#:
#: Fijarla por sesión y no en el servidor hace que el resultado no dependa de
#: dónde esté hoy la base. Va el desplazamiento y no
#: `America/Argentina/Buenos_Aires` porque el nombre exige las tablas de zonas
#: horarias cargadas en el esquema `mysql`, que las imágenes de MySQL no traen
#: pobladas. Argentina no tiene horario de verano: -03:00 es exacto todo el año.
TIME_ZONE = os.getenv("SIND_DB_TIME_ZONE", "-03:00")


def _usuario() -> str:
    """
    El usuario de MySQL de la aplicación, sin default a root.

    Un default es una decisión que nadie toma: con `root` como fallback, una
    variable mal escrita o un `.env` que no se cargó dejaban a la aplicación
    conectada como root sin que nada lo dijera. Faltando la variable, es mejor
    que no conecte y lo diga.
    """
    usuario = os.getenv("SIND_DB_USER", "").strip()
    if not usuario:
        raise RuntimeError(
            "Falta SIND_DB_USER. La aplicación del sindicato no se conecta a "
            "MySQL sin un usuario declarado. Ojo: es SIND_DB_USER, no DB_USER "
            "— esa última es la de gestion_adm y apunta a otra base."
        )
    return usuario


def _credenciales() -> tuple[str, str]:
    """
    Con qué usuario de MySQL se conecta esta llamada.

    Si hay una sesión web cuyo rol tiene usuario propio de base, se usa ése:
    los permisos del rol dejan de depender sólo de que la aplicación se acuerde
    de chequearlos y pasan a estar también del lado de MySQL. El nombre sale de
    `s_roles.db_usuario` y lo guarda el login; la contraseña, de una variable
    de entorno, nunca de la base.

    Si no hay sesión —scripts de importación, tareas programadas, migraciones—
    se usa el usuario del proceso.

    Un rol con `db_usuario` en NULL también cae en el usuario del proceso. Es a
    propósito: permite ir prendiendo esto de a un rol por vez en lugar de tener
    que dejar todo listo antes de que alguien pueda entrar.
    """
    base_usuario = _usuario()
    base_clave = os.getenv("SIND_DB_PASS", "")

    if not has_request_context():
        return base_usuario, base_clave

    db_usuario = (session.get("sind_db_usuario") or "").strip()
    if not db_usuario:
        return base_usuario, base_clave

    # La convención evita mantener un mapa aparte: el usuario `sind_operador`
    # busca su contraseña en SIND_DB_PASS_SIND_OPERADOR.
    variable = f"SIND_DB_PASS_{db_usuario.upper()}"
    clave = os.getenv(variable, "")
    if not clave:
        # No se cae al usuario del proceso: ése tiene más permisos, y una
        # variable faltante terminaría dando MÁS acceso del que corresponde sin
        # que nadie se entere. Es exactamente al revés de lo que tiene que
        # pasar cuando algo de permisos está mal configurado.
        raise RuntimeError(
            f"El rol de esta sesión conecta como '{db_usuario}' pero falta la "
            f"variable {variable}. No se usa el usuario de la aplicación en su "
            f"lugar porque tiene más permisos."
        )
    return db_usuario, clave


def get_connection():
    """
    Conexión a la base `sindicato`, con `DictCursor` y autocommit.

    `DictCursor` devuelve diccionarios: los resultados se leen por nombre de
    columna (`row["cuit"]`), nunca por posición ni desempaquetando la fila.
    """
    usuario, clave = _credenciales()
    return pymysql.connect(
        host         = os.getenv("SIND_DB_HOST", "localhost"),
        port         = int(os.getenv("SIND_DB_PORT", "3306")),
        user         = usuario,
        password     = clave,
        database     = DB_NAME,
        charset      = "utf8mb4",
        cursorclass  = pymysql.cursors.DictCursor,
        autocommit   = True,
        init_command = f"SET time_zone = '{TIME_ZONE}'",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Sesión
#
# Las claves llevan prefijo `sind_` para no pisarse con las de gestion_adm si
# las dos aplicaciones terminan compartiendo cookie de sesión. El login propio
# —contra `s_usuarios` de esta base— las puebla con `roles_y_menu`.
# ─────────────────────────────────────────────────────────────────────────────

def validasesion() -> bool:
    """Si la sesión actual corresponde a un usuario autenticado del sindicato."""
    return bool(session.get("sind_validausuario"))


def usuario_actual() -> dict | None:
    """
    Los datos del usuario logueado que el login dejó en la sesión, o None.

    Devuelve lo que hay en la sesión y no consulta la base: esto se llama en
    cada request y no justifica un viaje a MySQL. Para datos frescos de
    `s_usuarios`, consultarla directamente por `id`.
    """
    if not validasesion():
        return None
    return {
        "id":     session.get("sind_usuario_id"),
        "email":  session.get("sind_usuario_email"),
        "nombre": session.get("sind_usuario_nombre"),
    }


def tiene_rol(rol_nombre: str) -> bool:
    """Si el usuario logueado tiene el rol indicado (por `s_roles.nombre`)."""
    return rol_nombre in session.get("sind_roles", [])


def puede(url: str) -> bool:
    """
    Si el usuario logueado tiene la opción de menú con esa URL.

    El permiso ES la opción de menú: lo que se asigna en `s_menu_rol` o
    `s_menu_usuario`, que el login deja en `sind_menu_ids`. Así no hay una
    segunda tabla de permisos que se desincronice de lo que la persona ve en
    el menú. Para dar o quitar el ABM de afiliados a un rol, se le da o se le
    quita la opción «ABM de Afiliados».

    Como sale de la sesión, un cambio de permisos rige desde el próximo login.

    Una consulta por URL y por request (se guarda en `flask.g`): una pantalla
    pregunta lo mismo varias veces mientras se arma.
    """
    ids = set(session.get("sind_menu_ids") or [])
    if not ids:
        return False
    cache = g.setdefault("_sind_permisos", {})
    if url not in cache:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM s_menu WHERE url = %s AND activo = 1", (url,))
                cache[url] = any(f["id"] in ids for f in cur.fetchall())
    return cache[url]


def roles_y_menu(id_usuario: int) -> tuple[list[str], list[int]]:
    """
    Los roles del usuario y los ids de menú que tiene permitidos.

    Los permisos salen de dos lados y se suman:

    - `s_menu_rol`, lo que corresponde a cada rol. Es el caso normal.
    - `s_menu_usuario`, excepciones para una persona puntual.

    `gestion_adm` mira solo `s_menu_usuario` y copia ahí lo del rol desde su
    ABM de permisos. Acá se toma la unión: alcanza con asignar un rol para que
    la persona vea su menú, y «Permisos por Usuario» (admin.permisos) suma
    opciones sueltas a una persona. Una excepción solo agrega, no quita.

    Vive acá y no en app.py porque la usan el login y las pantallas de
    administración (refrescan la sesión de quien cambia sus propios permisos).

    Devuelve listas vacías si no hay nada asignado, que es correcto y no
    impide entrar: se ve la aplicación sin menú lateral.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.nombre
                FROM s_usuario_rol ur
                JOIN s_roles r ON r.id = ur.rol_id
                WHERE ur.usuario_id = %s AND r.activo = 1
                ORDER BY r.prioridad DESC
            """, (id_usuario,))
            roles = [fila["nombre"] for fila in cur.fetchall()]

            cur.execute("""
                SELECT DISTINCT m.id
                FROM s_menu m
                WHERE m.activo = 1
                  AND (
                        m.id IN (SELECT mr.menu_id
                                 FROM s_menu_rol mr
                                 JOIN s_usuario_rol ur ON ur.rol_id = mr.rol_id
                                 JOIN s_roles r        ON r.id = ur.rol_id AND r.activo = 1
                                 WHERE ur.usuario_id = %s)
                     OR m.id IN (SELECT mu.menu_id
                                 FROM s_menu_usuario mu
                                 WHERE mu.usuario_id = %s)
                  )
            """, (id_usuario, id_usuario))
            menu_ids = [fila["id"] for fila in cur.fetchall()]

    return roles, menu_ids
