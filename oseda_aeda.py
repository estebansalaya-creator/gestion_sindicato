"""
oseda_aeda.py — El atributo AEDA de OSEDA sigue al padrón del gremio.

Cuando el sindicato da un alta, una baja o una reactivación de un TITULAR, el
afiliado con el mismo CUIL en la obra social (base `contable`) gana o pierde el
atributo «AEDA — Afiliado al Gremio». Solo titulares: en OSEDA el atributo es
del titular y en un familiar no significa nada, así que los familiares no se
anotan acá y el procedimiento tampoco los toca si en OSEDA figuran como
familiar (NO_TITULAR). Si el CUIL no está en OSEDA, no se hace nada: acá no se
dan altas en el padrón de la obra social.

Es la única excepción a la regla de oro (este código no escribe en
`contable`), decidida el 27/11/2026, y está acotada en tres lugares:

1. **MySQL.** Se conecta con `sind_oseda`, un usuario sin permisos sobre
   ninguna tabla: solo puede ejecutar `sp_sindicato_atributo_aeda`, que solo
   pone o saca ese atributo y deja el movimiento en la auditoría de OSEDA
   (`sql/oseda_atributo_aeda_20261127.sql`, se corre en contable).
2. **Usuario aparte.** El servidor es el mismo que lee las DDJJ
   (`SIND_CONTABLE_HOST/PORT/DB`, ver contable_oseda.py), pero el usuario es
   otro: `SIND_OSEDA_AEDA_USER` / `SIND_OSEDA_AEDA_PASS`. La conexión de
   lectura sigue siendo READ ONLY y `get_connection()` sigue apuntando solo a
   `sindicato`.
3. **Este archivo.** Es el único que escribe (por el procedimiento) en OSEDA.

Bandeja de pendientes
---------------------
Las bases están en servidores distintos: no hay transacción que abarque a las
dos. El cambio de estado se graba en `sindicato` junto con su fila en
`p_afiliados_oseda_aeda` (`anotar`, dentro de la transacción del ABM), y
después de confirmar se aplica en OSEDA (`procesar`). Si OSEDA no responde, la
fila queda PENDIENTE; `sincronizar_oseda_aeda.py` la reintenta. El
procedimiento es idempotente (YA_ESTABA / NO_ESTABA), así que reintentar nunca
duplica nada.

Sin `SIND_CONTABLE_HOST` o `SIND_OSEDA_AEDA_USER`, todo queda en la bandeja: la app local
con datos de demo no toca la obra social.
"""

import logging
import os

import pymysql
import pymysql.cursors

from db import get_connection

log = logging.getLogger(__name__)

PROCEDIMIENTO = "sp_sindicato_atributo_aeda"
TITULAR = 0

#: Qué le pasa al atributo en OSEDA con cada movimiento del gremio.
ACCION_POR_MOTIVO = {"ALTA": "AGREGAR", "REACTIVACION": "AGREGAR", "BAJA": "QUITAR"}

#: Se espera poco: esto corre en el request del ABM, y si OSEDA tarda la fila
#: queda pendiente en vez de colgar la pantalla.
TIMEOUT = 8


def configurado() -> bool:
    return bool(os.getenv("SIND_CONTABLE_HOST", "").strip()
                and os.getenv("SIND_OSEDA_AEDA_USER", "").strip())


def _conexion_oseda():
    return pymysql.connect(
        host            = os.getenv("SIND_CONTABLE_HOST", "").strip(),
        port            = int(os.getenv("SIND_CONTABLE_PORT", "3306")),
        user            = os.getenv("SIND_OSEDA_AEDA_USER", "").strip(),
        password        = os.getenv("SIND_OSEDA_AEDA_PASS", ""),
        # En Railway la base de OSEDA se llama `railway`; en local, `contable`.
        database        = os.getenv("SIND_CONTABLE_DB", "").strip() or "railway",
        charset         = "utf8mb4",
        cursorclass     = pymysql.cursors.DictCursor,
        autocommit      = True,
        connect_timeout = TIMEOUT,
        read_timeout    = TIMEOUT,
        write_timeout   = TIMEOUT,
    )


def anotar(cur, personas, motivo: str, usuario: str) -> list[int]:
    """
    Deja en la bandeja una fila por cada titular de `personas`, que son fichas
    con `id_afiliado`, `cuil` y `cod_parentesco`. Los familiares se saltean.
    Va con el cursor del ABM, dentro de su transacción: si el cambio de estado
    no se confirma, la fila tampoco existe.
    """
    accion = ACCION_POR_MOTIVO[motivo]
    ids = []
    for p in personas:
        if p.get("cod_parentesco") != TITULAR:
            continue
        id_afiliado, cuil = p["id_afiliado"], p.get("cuil")
        cur.execute("""
            INSERT INTO p_afiliados_oseda_aeda (id_afiliado, cuil, motivo, accion, usuario)
            VALUES (%s, %s, %s, %s, %s)
        """, (id_afiliado, cuil or None, motivo, accion, (usuario or "")[:80] or None))
        ids.append(cur.lastrowid)
    return ids


def procesar(id_afiliados=None) -> dict:
    """
    Aplica en OSEDA lo pendiente, en orden. Con `id_afiliados`, solo lo de
    esas personas (lo que acaba de hacer la pantalla); sin él, toda la bandeja.

    Si una fila de una persona falla, las siguientes de esa misma persona se
    dejan para otra vuelta: aplicar una reactivación antes que la baja que la
    precede dejaría el atributo al revés.

    Devuelve un conteo por resultado, más «PENDIENTE» (lo que no se pudo),
    «error» (el último mensaje, para mostrarlo) y «sin_configurar».
    """
    conteo: dict = {}
    with get_connection() as conn:
        with conn.cursor() as cur:
            sql = ("SELECT id, id_afiliado, cuil, motivo, accion, usuario "
                   "FROM p_afiliados_oseda_aeda WHERE estado = 'PENDIENTE'")
            args: tuple = ()
            if id_afiliados:
                ids = sorted({int(i) for i in id_afiliados})
                sql += f" AND id_afiliado IN ({', '.join(['%s'] * len(ids))})"
                args = tuple(ids)
            cur.execute(sql + " ORDER BY id", args)
            filas = cur.fetchall()
            if not filas:
                return conteo

            # Lo que no necesita a OSEDA se cierra igual, configurada o no.
            con_cuil = []
            for f in filas:
                if f["cuil"]:
                    con_cuil.append(f)
                else:
                    _cerrar(cur, f["id"], "SIN_CUIL", None)
                    conteo["SIN_CUIL"] = conteo.get("SIN_CUIL", 0) + 1
            if not con_cuil:
                return conteo
            if not configurado():
                # La app local con datos de demo: queda en la bandeja sin avisar.
                conteo["PENDIENTE"] = len(con_cuil)
                conteo["sin_configurar"] = True
                return conteo

            try:
                oseda = _conexion_oseda()
            except Exception as e:
                log.warning("OSEDA no responde: %s", e)
                for f in con_cuil:
                    _fallo(cur, f["id"], e)
                conteo["PENDIENTE"] = len(con_cuil)
                conteo["error"] = str(e)
                return conteo

            trabadas: set[int] = set()
            with oseda:
                with oseda.cursor() as oc:
                    for f in con_cuil:
                        if f["id_afiliado"] in trabadas:
                            conteo["PENDIENTE"] = conteo.get("PENDIENTE", 0) + 1
                            continue
                        try:
                            oc.execute(f"CALL {PROCEDIMIENTO}(%s, %s, %s, %s)",
                                       (f["cuil"], f["accion"],
                                        _usuario_oseda(f["usuario"]), f["motivo"]))
                            r = oc.fetchone() or {}
                            while oc.nextset():     # el CALL deja un resultado vacío al final
                                pass
                            res = r.get("resultado") or "SIN_RESULTADO"
                            _cerrar(cur, f["id"], res, r.get("id_afiliado_oseda"))
                            conteo[res] = conteo.get(res, 0) + 1
                        except Exception as e:
                            log.warning("OSEDA: fila %s (CUIL %s) falló: %s", f["id"], f["cuil"], e)
                            _fallo(cur, f["id"], e)
                            trabadas.add(f["id_afiliado"])
                            conteo["PENDIENTE"] = conteo.get("PENDIENTE", 0) + 1
                            conteo["error"] = str(e)
    return conteo


def resumen(conteo: dict) -> str | None:
    """El conteo de `procesar` como una línea para la pantalla, o None si no hubo nada que contar."""
    partes = []
    if conteo.get("AGREGADO"):
        partes.append(f"se asignó el atributo AEDA a {conteo['AGREGADO']}")
    if conteo.get("QUITADO"):
        partes.append(f"se quitó el atributo AEDA a {conteo['QUITADO']}")
    ya = conteo.get("YA_ESTABA", 0) + conteo.get("NO_ESTABA", 0)
    if ya:
        partes.append(f"{ya} ya estaba(n) así")
    if conteo.get("NO_TITULAR"):
        partes.append(f"{conteo['NO_TITULAR']} figura(n) como familiar en OSEDA y no se tocó")
    if conteo.get("SIN_AFILIADO"):
        partes.append(f"{conteo['SIN_AFILIADO']} no está(n) en el padrón de OSEDA")
    if not partes:
        return None
    return "OSEDA: " + "; ".join(partes) + "."


def _usuario_oseda(usuario: str | None) -> str:
    # En OSEDA el usuario es una persona de la obra social; el sufijo dice que
    # el cambio vino del gremio.
    return f"{usuario or 'gestion_sindicato'} (AEDA)"[:60]


def _cerrar(cur, id_fila, resultado, id_oseda):
    cur.execute("""
        UPDATE p_afiliados_oseda_aeda
           SET estado = 'APLICADO', resultado = %s, id_afiliado_oseda = %s,
               ultimo_error = NULL, intentos = intentos + 1, procesado = NOW()
         WHERE id = %s
    """, (resultado, id_oseda, id_fila))


def _fallo(cur, id_fila, error):
    cur.execute("""
        UPDATE p_afiliados_oseda_aeda
           SET ultimo_error = %s, intentos = intentos + 1
         WHERE id = %s
    """, (str(error)[:500], id_fila))
