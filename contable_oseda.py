"""
contable_oseda.py — Lectura de las DDJJ de OSEDA en `contable` (Railway).

Es la ÚNICA conexión de esta app a otra base y es de solo lectura: la sesión se
abre con `SET SESSION TRANSACTION READ ONLY`, así que aunque alguien agregue un
UPDATE acá, MySQL lo rechaza. Conviene además que el usuario de Railway tenga
solo SELECT. Escribir en `contable` sigue prohibido.

No hay JOIN entre bases (son dos servidores): se consulta por CUIT y el cruce
con el padrón del sindicato se hace en Python.

Variables (.env): SIND_CONTABLE_HOST  SIND_CONTABLE_PORT  SIND_CONTABLE_USER
                  SIND_CONTABLE_PASS  [SIND_CONTABLE_DB, por defecto `railway`]
"""

import os

import pymysql
import pymysql.cursors

#: Código RNOS de OSEDA en el F.931. Hoy f_ddjj_procesada solo tiene este,
#: pero el filtro deja explícito que la DDJJ que se muestra es la de OSEDA.
CODOSOC_OSEDA = "106104"


class ContableNoDisponible(Exception):
    """Falta configuración o Railway no responde: la pantalla sigue sin la DDJJ."""


def _conexion():
    host = os.getenv("SIND_CONTABLE_HOST", "").strip()
    user = os.getenv("SIND_CONTABLE_USER", "").strip()
    if not host or not user:
        raise ContableNoDisponible("Falta SIND_CONTABLE_HOST / SIND_CONTABLE_USER en el .env.")
    try:
        return pymysql.connect(
            host            = host,
            port            = int(os.getenv("SIND_CONTABLE_PORT", "3306")),
            user            = user,
            password        = os.getenv("SIND_CONTABLE_PASS", ""),
            database        = os.getenv("SIND_CONTABLE_DB", "").strip() or "railway",
            charset         = "utf8mb4",
            cursorclass     = pymysql.cursors.DictCursor,
            connect_timeout = 5,
            read_timeout    = 30,
            init_command    = "SET SESSION TRANSACTION READ ONLY",
        )
    except pymysql.MySQLError as e:
        raise ContableNoDisponible(f"No se pudo conectar a contable (Railway): {e}") from e


def ultima_ddjj_por_cuil(cuit: str) -> dict[str, dict]:
    """
    Última DDJJ de OSEDA de cada empleado declarado por `cuit`:
    {cuil: {"ultimo_periodo": "AAAAMM", "rem5": Decimal}}.

    `f_ddjj_procesada` ya tiene una sola fila por CUIT + CUIL + período (la
    DDJJ vigente, la de mayor secuencia), así que el último período da una fila.
    """
    sql = """
        SELECT d.cuil, d.periodo AS ultimo_periodo, d.rem5
          FROM (SELECT cuil, MAX(periodo) AS periodo
                  FROM f_ddjj_procesada
                 WHERE cuit = %s AND codosoc = %s
                 GROUP BY cuil) x
          JOIN f_ddjj_procesada d
            ON d.cuit = %s AND d.codosoc = %s AND d.cuil = x.cuil AND d.periodo = x.periodo
    """
    cn = _conexion()
    try:
        with cn.cursor() as cur:
            cur.execute(sql, (cuit, CODOSOC_OSEDA, cuit, CODOSOC_OSEDA))
            return {f["cuil"]: f for f in cur.fetchall()}
    except pymysql.MySQLError as e:
        raise ContableNoDisponible(f"Error al leer las DDJJ en contable: {e}") from e
    finally:
        cn.close()



def ddjj_de_cuiles(periodos, cuiles) -> list[dict]:
    """
    Las DDJJ de OSEDA de esos CUIL en esos períodos (AAAAMM), con el empleador
    que las presentó: [{"cuit", "cuil", "periodo", "rem5"}]. Un CUIL con dos
    empleos da dos filas por período.

    Se consulta de a 500 CUIL: el padrón entero en un IN es una sentencia de
    decenas de KB y Railway corta las que tardan.
    """
    periodos = sorted({str(p) for p in periodos if p})
    cuiles = sorted({str(c) for c in cuiles if c})
    if not periodos or not cuiles:
        return []
    marcas_p = ",".join(["%s"] * len(periodos))
    cn = _conexion()
    filas = []
    try:
        with cn.cursor() as cur:
            for i in range(0, len(cuiles), 500):
                tanda = cuiles[i:i + 500]
                marcas = ",".join(["%s"] * len(tanda))
                cur.execute(f"""SELECT cuit, cuil, periodo, rem5 FROM f_ddjj_procesada
                                 WHERE codosoc = %s AND periodo IN ({marcas_p}) AND cuil IN ({marcas})""",
                            [CODOSOC_OSEDA, *periodos, *tanda])
                filas += cur.fetchall()
        return filas
    except pymysql.MySQLError as e:
        raise ContableNoDisponible(f"Error al leer las DDJJ en contable: {e}") from e
    finally:
        cn.close()


def declarantes_por_cuil(cuiles) -> dict[str, dict[str, str]]:
    """
    Quién declaró a cada CUIL en la DDJJ de OSEDA y hasta cuándo, en toda la
    historia: {cuil: {cuit: último período AAAAMM}}. El último declarante es el
    CUIT del período más nuevo (dos si en ese período lo declararon dos).

    De a 500 CUIL, por el índice (cuil, periodo): el padrón entero en un IN es
    una sentencia de decenas de KB y Railway corta las que tardan.
    """
    cuiles = sorted({str(c) for c in cuiles if c})
    salida: dict[str, dict[str, str]] = {}
    if not cuiles:
        return salida
    cn = _conexion()
    try:
        with cn.cursor() as cur:
            for i in range(0, len(cuiles), 500):
                tanda = cuiles[i:i + 500]
                marcas = ",".join(["%s"] * len(tanda))
                cur.execute(f"""SELECT cuil, cuit, MAX(periodo) AS periodo FROM f_ddjj_procesada
                                 WHERE codosoc = %s AND cuil IN ({marcas})
                                 GROUP BY cuil, cuit""", [CODOSOC_OSEDA, *tanda])
                for f in cur.fetchall():
                    salida.setdefault(f["cuil"], {})[f["cuit"]] = f["periodo"]
        return salida
    except pymysql.MySQLError as e:
        raise ContableNoDisponible(f"Error al leer las DDJJ en contable: {e}") from e
    finally:
        cn.close()


def ddjj_del_periodo(periodo: str, cuiles) -> list[dict]:
    """Las DDJJ de OSEDA de un período: la usa la liquidación de cuota sindical."""
    return ddjj_de_cuiles([periodo], cuiles)


def periodos_ddjj(cuantos: int = 13) -> list[dict]:
    """Los últimos períodos con DDJJ de OSEDA y cuántas filas tiene cada uno,
    del más nuevo al más viejo: [{"periodo", "filas"}]."""
    cn = _conexion()
    try:
        with cn.cursor() as cur:
            cur.execute("""SELECT periodo, COUNT(*) AS filas FROM f_ddjj_procesada
                            WHERE codosoc = %s GROUP BY periodo ORDER BY periodo DESC LIMIT %s""",
                        (CODOSOC_OSEDA, cuantos))
            return cur.fetchall()
    except pymysql.MySQLError as e:
        raise ContableNoDisponible(f"Error al leer las DDJJ en contable: {e}") from e
    finally:
        cn.close()


def empleados_por_cuit(periodo: str, cuits) -> dict[str, int]:
    """Cuántos empleados declaró cada CUIT en la DDJJ de OSEDA del período
    (afiliados al gremio o no): {cuit: n}."""
    cuits = sorted({str(c) for c in cuits if c})
    if not cuits:
        return {}
    cn = _conexion()
    res = {}
    try:
        with cn.cursor() as cur:
            for i in range(0, len(cuits), 500):
                tanda = cuits[i:i + 500]
                marcas = ",".join(["%s"] * len(tanda))
                cur.execute(f"""SELECT cuit, COUNT(*) AS n FROM f_ddjj_procesada
                                 WHERE codosoc = %s AND periodo = %s AND cuit IN ({marcas})
                                 GROUP BY cuit""", [CODOSOC_OSEDA, periodo, *tanda])
                res.update({f["cuit"]: f["n"] for f in cur.fetchall()})
        return res
    except pymysql.MySQLError as e:
        raise ContableNoDisponible(f"Error al leer las DDJJ en contable: {e}") from e
    finally:
        cn.close()


def padron_oseda_aeda(rotulo: str = "AEDA") -> list[dict]:
    """
    El padrón de OSEDA que importa para la marca de afiliado al gremio: todos
    los titulares y, además, los familiares que tienen la marca. Con
    `marca_aeda` = 1 si tienen el atributo de ese rótulo
    (`p_atributos_por_afiliado` → `p_afiliado_atributo`).
    """
    cn = _conexion()
    try:
        with cn.cursor() as cur:
            cur.execute("SELECT id FROM p_afiliado_atributo WHERE rotulo = %s", (rotulo,))
            fila = cur.fetchone()
            if not fila:
                raise ContableNoDisponible(f"No hay un atributo «{rotulo}» en el padrón de OSEDA.")
            cur.execute("""SELECT p.id_afiliado, p.cuil, p.cod_parentesco, p.cuil_titular, p.apellido, p.nombre,
                                  p.cuit_empleador, p.fecha_baja, p.activo,
                                  EXISTS (SELECT 1 FROM p_atributos_por_afiliado x
                                           WHERE x.id_afiliado = p.id_afiliado AND x.id_atributo = %s) AS marca_aeda
                             FROM p_afiliados p
                            WHERE p.cod_parentesco = 0
                               OR EXISTS (SELECT 1 FROM p_atributos_por_afiliado x
                                           WHERE x.id_afiliado = p.id_afiliado AND x.id_atributo = %s)""",
                        (fila["id"], fila["id"]))
            return cur.fetchall()
    except pymysql.MySQLError as e:
        raise ContableNoDisponible(f"Error al leer el padrón de OSEDA en contable: {e}") from e
    finally:
        cn.close()
