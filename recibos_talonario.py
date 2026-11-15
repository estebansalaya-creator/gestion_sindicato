"""
recibos_talonario.py — El talonario y el número de cada recibo.

Pedido del 14/11/2026 (sql/fisca_recibos_talonarios_20261114.sql). Un recibo es
una orden de ingreso (`ingreso_ordenes`) de clase «cuota_sindical» o
«fiscalizacion»: es la que va al libro, a la conciliación y a la cuenta
corriente. Lleva además su talonario (`id_talonario`) y su número en él
(`nro_recibo`, único por talonario). Se muestra «X 0001-00000123»; el número de
la orden de ingreso (AAMM-########) queda como dato de tesorería.

    Recibos Cuota Sindical          X 0001   se emite desde acá (Datos del Sindicato)
    Recibos Fiscalización           X 0002   se emite desde acá: a un acta, a las cuotas de su acuerdo
    Recibos Cuota Sindical (AEDA)   X 0091   los cobros de AEDA, con su número (fis_cobros.cobro_id)
    Recibos Fiscalización (AEDA)    X 0092   deshabilitados: no se emite desde ellos

Con qué talonario se emite cada clase lo dicen `s_institucion.talonario_recibo_*`
(se cambia en Datos del Sindicato); los de AEDA, `s_configuracion`
(talonario_recibos_aeda_*), y los usa importar_aeda_fondos.py. Lo de AEDA va
aparte para que lo que se siga importando mientras AEDA cobre no se mezcle con
lo que se emite acá (decidido el 14/11/2026, como OSEDA con sus migrados).

`reservar` toma el próximo número con el talonario bloqueado (FOR UPDATE) y lo
deja como último emitido: dentro de la transacción del recibo, si algo falla el
número no se pierde.
"""

from __future__ import annotations

CLASES = ("cuota_sindical", "fiscalizacion")
NOMBRE_CLASE = {"cuota_sindical": "cuota sindical", "fiscalizacion": "fiscalización"}
SQL_ESQUEMA = "sql/fisca_recibos_talonarios_20261114.sql"
COL_INSTITUCION = {"cuota_sindical": "talonario_recibo_cuota", "fiscalizacion": "talonario_recibo_fisca"}
PARAM_AEDA = {"cuota_sindical": "talonario_recibos_aeda_cuota", "fiscalizacion": "talonario_recibos_aeda_fisca"}

_ESQUEMA_OK = False


class ErrorTalonario(ValueError):
    """Sin talonario, deshabilitado o agotado: el texto va a la pantalla."""


def hay_esquema(cur) -> bool:
    """¿Se corrió el script? Una vez que sí, no se vuelve a preguntar."""
    global _ESQUEMA_OK
    if _ESQUEMA_OK:
        return True
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.columns
                    WHERE table_schema = DATABASE()
                      AND ((table_name = 'ingreso_ordenes' AND column_name IN ('id_talonario', 'nro_recibo', 'id_acta', 'id_acuerdo'))
                        OR (table_name = 's_institucion' AND column_name IN ('talonario_recibo_cuota', 'talonario_recibo_fisca'))
                        OR (table_name = 'fisca_acuerdo_imputacion' AND column_name = 'id_cuota'))""")
    _ESQUEMA_OK = int(cur.fetchone()["n"] or 0) >= 7
    return _ESQUEMA_OK


def texto(letra, punto_de_venta, nro) -> str | None:
    if nro is None or punto_de_venta is None:
        return None
    return f"{letra or 'X'} {int(punto_de_venta):04d}-{int(nro):08d}"


def sql_texto(o: str = "o", t: str = "t") -> str:
    """El número del recibo armado en SQL, con `t` = c_talonario unido a `o`."""
    return (f"CASE WHEN {o}.nro_recibo IS NOT NULL THEN CONCAT({t}.letra, ' ', LPAD({t}.punto_de_venta, 4, '0'), '-', "
            f"LPAD({o}.nro_recibo, 8, '0')) END")


def talonarios(cur) -> list[dict]:
    """Los talonarios de la clasificación de recibos, para elegir en Datos del Sindicato."""
    cur.execute("""SELECT t.id, t.nombre, t.letra, t.punto_de_venta, t.ultimo_emitido, t.habilitado
                     FROM c_talonario t
                     JOIN c_talonario_clasificacion k ON k.id = t.c_talonario_clasificacionId
                     JOIN c_contable_comprobante_tipo ct ON ct.id = k.id_comprobante_tipo
                    WHERE ct.nombre = 'Recibo'
                    ORDER BY t.habilitado DESC, t.punto_de_venta""")
    out = list(cur.fetchall())
    for t in out:
        t["texto"] = f"{t['nombre']} · {t['letra']} {int(t['punto_de_venta']):04d}" + ("" if t["habilitado"] else " (deshabilitado)")
    return out


def id_de_emision(cur, clase: str) -> int | None:
    cur.execute(f"SELECT {COL_INSTITUCION[clase]} AS id FROM s_institucion WHERE id = 1")
    return (cur.fetchone() or {}).get("id")


def id_de_aeda(cur, clase: str) -> int | None:
    cur.execute("SELECT valor FROM s_configuracion WHERE modulo = 'fiscalizacion' AND parametro = %s",
                (PARAM_AEDA[clase],))
    v = ((cur.fetchone() or {}).get("valor") or "").strip()
    return int(v) if v.isdigit() else None


def reservar(cur, clase: str) -> dict:
    """El próximo número del talonario con que se emite `clase`. Corre en la
    transacción del recibo: deja el talonario bloqueado hasta el commit.
    Devuelve id, nro y texto."""
    if clase not in CLASES:
        raise ErrorTalonario(f"No hay talonario para la clase «{clase}».")
    id_tal = id_de_emision(cur, clase)
    if not id_tal:
        raise ErrorTalonario(f"Falta elegir el talonario de los recibos de {NOMBRE_CLASE[clase]} en Datos del Sindicato.")
    cur.execute("""SELECT id, nombre, letra, punto_de_venta, numero_desde, numero_hasta, ultimo_emitido, habilitado
                     FROM c_talonario WHERE id = %s FOR UPDATE""", (id_tal,))
    t = cur.fetchone()
    if not t:
        raise ErrorTalonario("El talonario elegido en Datos del Sindicato ya no existe.")
    if not t["habilitado"]:
        raise ErrorTalonario(f"El talonario «{t['nombre']}» está deshabilitado: se habilita en Talonarios "
                             "o se elige otro en Datos del Sindicato.")
    # Por si alguien cargó a mano un número más alto que el último emitido.
    cur.execute("SELECT MAX(nro_recibo) AS m FROM ingreso_ordenes WHERE id_talonario = %s", (id_tal,))
    usado = int((cur.fetchone() or {}).get("m") or 0)
    nro = max(int(t["ultimo_emitido"] or 0), usado) + 1
    nro = max(nro, int(t["numero_desde"]))
    if nro > int(t["numero_hasta"]):
        raise ErrorTalonario(f"El talonario «{t['nombre']}» agotó su numeración (hasta {t['numero_hasta']}).")
    cur.execute("UPDATE c_talonario SET ultimo_emitido = %s WHERE id = %s", (nro, id_tal))
    return {"id": id_tal, "nro": nro, "texto": texto(t["letra"], t["punto_de_venta"], nro), "nombre": t["nombre"]}


def avanzar(cur, id_talonario: int) -> None:
    """El último emitido, al mayor número usado (lo que se graba con su número, como lo de AEDA)."""
    cur.execute("""UPDATE c_talonario t
                      SET t.ultimo_emitido = GREATEST(t.ultimo_emitido,
                              COALESCE((SELECT MAX(o.nro_recibo) FROM ingreso_ordenes o WHERE o.id_talonario = t.id), 0))
                    WHERE t.id = %s""", (id_talonario,))


def numeros(cur, ids_orden) -> dict:
    """id_orden → «X 0001-00000123». Vacío si el script no se corrió."""
    ids = sorted({int(i) for i in ids_orden if i})
    if not ids or not hay_esquema(cur):
        return {}
    out = {}
    for i in range(0, len(ids), 1000):
        parte = ids[i:i + 1000]
        cur.execute(f"""SELECT o.id, {sql_texto('o', 't')} AS nro
                          FROM ingreso_ordenes o JOIN c_talonario t ON t.id = o.id_talonario
                         WHERE o.id IN ({','.join(['%s'] * len(parte))})""", parte)
        out.update({f["id"]: f["nro"] for f in cur.fetchall() if f["nro"]})
    return out


def completar(cur, filas, campo: str = "id_orden", destino: str = "nro_recibo") -> list:
    """Le pone a cada fila el número de su recibo (o None)."""
    filas = list(filas)
    nros = numeros(cur, [f.get(campo) for f in filas])
    for f in filas:
        f[destino] = nros.get(f.get(campo))
    return filas
