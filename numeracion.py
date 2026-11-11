"""
numeracion.py — Números de órdenes, pagos y certificados.

Portado de `gestion_adm/numeracion.py`.

Órdenes de pago, pagos y órdenes de ingreso: AAMM-######## que arranca en 1
cada mes (la primera orden de noviembre de 2026 es 2611-00000001). El ámbito
del contador es la tabla, así que cada circuito numera por separado. La clase
no va en el número: es una columna.

El contador es `c_numeradores` y no un COUNT(*): borrar un comprobante haría
que el próximo repitiera un número. El INSERT … ON DUPLICATE KEY UPDATE con
LAST_INSERT_ID lo incrementa y lo devuelve en una sentencia atómica.

Lo que vino de AEDA no tiene este formato (AEDA-OP-123, AEDA-PG-123,
AEDA-CRT-45) y no puede chocar. Su número conocido —el de AEDA— está en
`nro_origen`, y es el que se muestra (`nro_visible`).
"""

from __future__ import annotations

import datetime


def _proximo(cur, ambito: str, periodo: str, minimo: int = 0) -> int:
    cur.execute("""INSERT INTO c_numeradores (ambito, periodo, ultimo)
                   VALUES (%s, %s, LAST_INSERT_ID(%s + 1))
                   ON DUPLICATE KEY UPDATE ultimo = LAST_INSERT_ID(GREATEST(ultimo, %s) + 1)""",
                (ambito, periodo, minimo, minimo))
    cur.execute("SELECT LAST_INSERT_ID() AS n")
    return int(cur.fetchone()["n"])


def proximo_numero(cur, ambito: str, fecha: datetime.date | None = None) -> str:
    """AAMM-######## del ámbito (la tabla) para el mes de `fecha`."""
    periodo = (fecha or datetime.date.today()).strftime("%y%m")
    return f"{periodo}-{_proximo(cur, ambito, periodo):08d}"


def proximo_certificado(cur, fecha: datetime.date | None = None) -> str:
    """CRT-AAAA-NNNNNN, correlativo por año. En gestion_adm salía de contar
    los certificados del año: anular uno y emitir otro repetía el número."""
    anio = (fecha or datetime.date.today()).year
    cur.execute("""SELECT COALESCE(MAX(CAST(SUBSTRING_INDEX(nro_certificado, '-', -1) AS UNSIGNED)), 0) AS m
                     FROM pago_retenciones_certificado WHERE nro_certificado LIKE %s""", (f"CRT-{anio}-%",))
    minimo = int(cur.fetchone()["m"] or 0)
    return f"CRT-{anio}-{_proximo(cur, 'pago_retenciones_certificado', str(anio), minimo):06d}"


# ─────────────────────────────────────────────────────────────────────────────
# El número que se muestra
# ─────────────────────────────────────────────────────────────────────────────

def _campo(fila, nombre):
    return fila.get(nombre) if hasattr(fila, "get") else getattr(fila, nombre, None)


def nro_visible(fila, clave: str = "nro_pago") -> str:
    """El número de un pago como se lo nombra: el de origen si lo tiene."""
    if not fila:
        return ""
    origen = _campo(fila, "nro_origen")
    if origen not in (None, "", 0):
        return str(origen)
    return str(_campo(fila, clave) or "")


def nro_orden_visible(fila) -> str:
    return nro_visible(fila, "nro_orden")


def sql_nro_visible(alias: str = "p", clave: str = "nro_pago") -> str:
    return f"COALESCE(NULLIF(NULLIF({alias}.nro_origen, ''), '0'), {alias}.{clave})"


def sql_nro_orden_visible(alias: str = "o") -> str:
    return sql_nro_visible(alias, "nro_orden")
