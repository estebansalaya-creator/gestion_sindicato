"""
transferencias_lote.py — Lotes de transferencias: a quién y a qué CBU, y el
registro de cada archivo que salió.

Portado de `gestion_adm/transferencias_lote.py`. La pregunta «¿este pago ya
salió en un archivo?» es `anulaciones.ya_transferido`, la misma que impide
anularlo.

EL ARCHIVO NO SE GUARDA, EL HECHO SÍ
El archivo se descarga y se puede volver a armar desde el detalle del lote. Lo
que se persiste es que salió, con qué formato, desde qué cuenta y a qué CBU.

EL CBU SE CONGELA
Al generar, el destino usado queda en el detalle del lote (aunque el proveedor
cambie su CBU después, el lote dice a dónde fue la plata) y en el instrumento
del pago si estaba vacío (`cbu_destino` o `alias_destino`, según qué sea).

DE DÓNDE SALE EL DESTINO, EN ORDEN
1. el instrumento del pago (lo que se escribió al emitir: manda sobre todo);
2. proveedor y anticipo: la ficha del proveedor (CBU, si no alias);
3. reintegro: el renglón de la orden, la solicitud y la ficha del afiliado
   (`p_afiliados.cbu_pago`), y en cada nivel el CBU antes que el alias: el CBU
   no cambia, un alias se puede reasignar a otra cuenta sin aviso.
Concepto y sueldos no se transfieren desde acá.
"""

from __future__ import annotations

import datetime

import anulaciones
import transferencias_formatos as tf

#: Las clases de orden que salen por esta pantalla. Lista de lo que ENTRA: una
#: clase nueva no aparece sola en la pantalla que le manda archivos al banco.
CLASES = ("proveedor", "anticipo", "reintegro")


def _limpio(v) -> str:
    return (v or "").strip()


def _primero(*valores) -> str:
    return next((_limpio(v) for v in valores if _limpio(v)), "")


def resolver_beneficiario(cur, id_pago: int, id_instrumento: int | None = None) -> dict:
    """Quién cobra y a qué destino. Devuelve `nombre`, `cuit`, `cbu` (CBU o
    alias), `cbu_origen` («instrumento» o «beneficiario») y `motivo` (por qué
    no se puede transferir, o None). Nunca levanta excepción: un beneficiario
    que no se resuelve es un renglón excluido, no un archivo que no sale."""
    cur.execute("""SELECT o.clase, o.id AS id_orden FROM pago_pagos p JOIN pago_ordenes o ON o.id = p.id_orden
                    WHERE p.id = %s""", (id_pago,))
    fila = cur.fetchone()
    if not fila:
        return {"nombre": None, "cuit": None, "cbu": None, "cbu_origen": None,
                "motivo": "el pago no tiene orden"}
    clase, id_orden = fila["clase"], fila["id_orden"]

    if clase in ("proveedor", "anticipo"):
        cur.execute("""SELECT DISTINCT pr.id, pr.razon_social AS nombre, pr.cuit, pr.cbu, pr.cbu_alias AS alias
                         FROM c_proveedores pr
                        WHERE pr.id IN (SELECT e.id_proveedor FROM pago_ordenes_detalle od
                                          JOIN me_expedientes e ON e.id = od.id_expediente
                                         WHERE od.id_orden = %s
                                        UNION
                                        SELECT ad.id_proveedor FROM pago_ordenes_anticipo_det ad
                                         WHERE ad.id_orden = %s)""", (id_orden, id_orden))
        provs = cur.fetchall()
        if len(provs) > 1:
            return {"nombre": provs[0]["nombre"], "cuit": None, "cbu": None, "cbu_origen": None,
                    "motivo": "la orden es de más de un proveedor: no se sabe a cuál transferir"}
        b = provs[0] if provs else {}
        destino_ficha = _primero(b.get("cbu"), b.get("alias"))
    elif clase == "reintegro":
        cur.execute("""SELECT rd.nombre, rd.cuil AS cuit,
                              rd.cbu_destino AS cbu_rd, rd.alias_destino AS alias_rd,
                              r.cbu_destino AS cbu_r, r.alias_destino AS alias_r, a.cbu_pago AS cbu_af
                         FROM pago_ordenes_reintegro_det rd
                         LEFT JOIN c_reintegro_afiliados r ON r.id = rd.id_reintegro
                         LEFT JOIN p_afiliados a ON a.id_afiliado = rd.id_afiliado
                        WHERE rd.id_orden = %s ORDER BY rd.id LIMIT 1""", (id_orden,))
        b = cur.fetchone() or {}
        destino_ficha = _primero(b.get("cbu_rd"), b.get("alias_rd"), b.get("cbu_r"),
                                 b.get("alias_r"), b.get("cbu_af"))
    else:
        return {"nombre": None, "cuit": None, "cbu": None, "cbu_origen": None,
                "motivo": f"las órdenes de clase «{clase}» no se transfieren desde acá"}

    destino_instr = ""
    if id_instrumento:
        cur.execute("SELECT cbu_destino, alias_destino FROM pago_pagos_instrumentos WHERE id = %s",
                    (id_instrumento,))
        i = cur.fetchone() or {}
        destino_instr = _primero(i.get("cbu_destino"), i.get("alias_destino"))

    destino = destino_instr or destino_ficha
    # «instrumento» solo si el del pago es OTRO que el de la ficha: es lo que
    # hay que mirar para saber dónde corregirlo. El que congeló un archivo
    # anterior es el mismo de la ficha.
    origen = ("instrumento" if destino_instr and destino_instr != destino_ficha
              else "beneficiario" if destino else None)
    motivo = None
    if not b:
        motivo = "no se pudo identificar al beneficiario"
    elif not destino:
        motivo = "el beneficiario no tiene CBU ni alias cargado"
    elif not (tf.es_cbu(destino) or tf.es_alias(destino)):
        donde = "cargado en el pago" if destino_instr else "de la ficha del beneficiario"
        motivo = f"el destino {donde} no es un CBU ni un alias válido: «{destino[:30]}»"
    return {"nombre": b.get("nombre"), "cuit": b.get("cuit"), "cbu": destino or None,
            "cbu_origen": origen, "motivo": motivo}


def pagos_transferibles(cur, *, desde=None, hasta=None, id_cuenta=None, ids=None, limite=1000) -> list[dict]:
    """Instrumentos de transferencia de pagos vivos, no conciliados y que no
    salieron en otro archivo, con su beneficiario resuelto. La usan la grilla
    y la generación: lo que se ofrece y lo que se acepta es lo mismo."""
    where = ["p.estado <> 'anulado'", "i.tipo_instrumento = 'transferencia'",
             f"o.clase IN ({', '.join(['%s'] * len(CLASES))})",
             """NOT EXISTS (SELECT 1 FROM pago_transferencias_lote_det d
                              JOIN pago_transferencias_lote l ON l.id = d.id_lote
                             WHERE d.incluida = 1 AND l.fecha_anulacion IS NULL
                               AND (d.id_instrumento = i.id OR (d.id_instrumento IS NULL AND d.id_pago = p.id)))""",
             f"NOT {anulaciones.sql_pago_conciliado('p')}"]
    params: list = list(CLASES)
    if ids is not None:
        if not ids:
            return []
        where.append(f"i.id IN ({', '.join(['%s'] * len(ids))})")
        params += list(ids)
    else:
        if desde:
            where.append("p.fecha_pago >= %s"); params.append(desde)
        if hasta:
            where.append("p.fecha_pago <= %s"); params.append(hasta)
    if id_cuenta:
        where.append("i.id_cuenta_fondos = %s"); params.append(id_cuenta)
    cur.execute(f"""SELECT p.id, p.nro_pago, p.nro_origen, p.fecha_pago, p.id_orden,
                           i.id AS id_instrumento, i.importe, i.id_cuenta_fondos,
                           o.clase, o.nro_orden, cf.nombre AS cuenta
                      FROM pago_pagos p
                      JOIN pago_pagos_instrumentos i ON i.id_pago = p.id
                      JOIN pago_ordenes o ON o.id = p.id_orden
                      LEFT JOIN c_cuentas_de_fondos cf ON cf.id = i.id_cuenta_fondos
                     WHERE {' AND '.join(where)}
                     ORDER BY p.fecha_pago DESC, p.id DESC, i.id
                     LIMIT {int(limite) + 1}""", params)
    filas = cur.fetchall()
    for x in filas:
        b = resolver_beneficiario(cur, x["id"], x["id_instrumento"])
        x.update(beneficiario=b["nombre"], cuit=b["cuit"], cbu=b["cbu"],
                 cbu_origen=b["cbu_origen"], motivo=b["motivo"])
    return filas


def registrar_lote(cur, *, formato: str, nombre_archivo: str, renglones: list[dict], id_cuenta_fondos: int,
                   cbu_ordenante: str, concepto: str, id_usuario=None, fecha=None, origen: str = "masivo") -> int:
    """Asienta el archivo generado. `renglones` es la lista completa, incluidos
    y excluidos (el excluido por falta de CBU es información: mañana alguien
    pregunta por qué no cobró). Va dentro de la transacción del que genera."""
    fecha = fecha or datetime.date.today()
    incluidos = [r for r in renglones if r["incluida"]]
    cur.execute("""INSERT INTO pago_transferencias_lote
                         (origen, formato, nombre_archivo, fecha, periodo, id_cuenta_fondos, cbu_ordenante,
                          concepto, cantidad, importe_total, excluidas, id_usuario)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (origen, formato, nombre_archivo, fecha, f"{fecha:%Y%m}", id_cuenta_fondos, cbu_ordenante,
                 concepto, len(incluidos), round(sum(float(r["importe"] or 0) for r in incluidos), 2),
                 len(renglones) - len(incluidos), id_usuario))
    id_lote = cur.lastrowid
    for r in renglones:
        cur.execute("""INSERT INTO pago_transferencias_lote_det
                             (id_lote, id_pago, id_instrumento, cbu_destino, cuit_destino, beneficiario,
                              importe, incluida, motivo_exclusion)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (id_lote, r["id_pago"], r["id_instrumento"], (r.get("cbu") or None) and r["cbu"][:22],
                     (r.get("cuit") or None) and str(r["cuit"])[:11], (r.get("nombre") or "")[:200] or None,
                     r["importe"] or 0, 1 if r["incluida"] else 0, (r.get("motivo") or "")[:150] or None))
        if r["incluida"] and r.get("cbu"):
            columna = "cbu_destino" if tf.es_cbu(r["cbu"]) else "alias_destino"
            cur.execute(f"""UPDATE pago_pagos_instrumentos SET {columna} = %s
                             WHERE id = %s AND COALESCE(cbu_destino, '') = '' AND COALESCE(alias_destino, '') = ''""",
                        (r["cbu"], r["id_instrumento"]))
    return id_lote


# ── Deshacer un archivo que no se transmitió ────────────────────────────────
# Generar el archivo traba los pagos (ya_transferido). Si el archivo nunca se
# subió, o se armó con un pago equivocado, estas dos salidas los liberan. Lo
# único que el sistema puede verificar es el extracto: si un pago ya está
# conciliado, el banco lo debitó y no se libera. Lo demás —si el archivo se
# subió al home banking— no se sabe: por eso se pide motivo.

def _lote_abierto(cur, id_lote: int) -> dict:
    cur.execute("SELECT id, nombre_archivo, fecha_anulacion FROM pago_transferencias_lote WHERE id = %s FOR UPDATE",
                (id_lote,))
    lote = cur.fetchone()
    if not lote:
        raise ValueError("El archivo no existe.")
    if lote["fecha_anulacion"]:
        raise ValueError("El archivo ya está anulado.")
    return lote


def _recalcular(cur, id_lote: int) -> int:
    """Totales desde el detalle, no sumando y restando sobre lo guardado."""
    cur.execute("""SELECT COALESCE(SUM(incluida = 1), 0) AS cantidad,
                          COALESCE(SUM(CASE WHEN incluida = 1 THEN importe END), 0) AS importe,
                          COALESCE(SUM(incluida = 0), 0) AS excluidas
                     FROM pago_transferencias_lote_det WHERE id_lote = %s""", (id_lote,))
    t = cur.fetchone()
    cur.execute("UPDATE pago_transferencias_lote SET cantidad = %s, importe_total = %s, excluidas = %s WHERE id = %s",
                (int(t["cantidad"]), t["importe"], int(t["excluidas"]), id_lote))
    return int(t["cantidad"])


def excluir_de_lote(cur, id_lote: int, id_detalle: int, motivo: str, usuario: str | None = None) -> dict:
    """Saca un renglón del archivo. Si era el último incluido, el archivo se
    anula solo. Devuelve {nro_pago, quedan, lote_anulado}."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValueError("Hace falta un motivo para sacar el pago del archivo.")
    _lote_abierto(cur, id_lote)
    cur.execute("""SELECT d.id, d.id_pago, COALESCE(CAST(p.nro_origen AS CHAR), p.nro_pago) AS nro_pago
                     FROM pago_transferencias_lote_det d LEFT JOIN pago_pagos p ON p.id = d.id_pago
                    WHERE d.id = %s AND d.id_lote = %s AND d.incluida = 1 FOR UPDATE""", (id_detalle, id_lote))
    det = cur.fetchone()
    if not det:
        raise ValueError("Ese renglón no está incluido en el archivo.")
    if anulaciones._conciliado_pago(cur, det["id_pago"]):
        raise ValueError("El pago ya está conciliado con el extracto: el banco lo debitó, la transferencia salió.")
    quien = f" por {usuario}" if usuario else ""
    texto = f"Excluido el {datetime.date.today():%d/%m/%Y}{quien}: {motivo}"
    cur.execute("UPDATE pago_transferencias_lote_det SET incluida = 0, motivo_exclusion = %s WHERE id = %s",
                (texto[:150], det["id"]))
    quedan = _recalcular(cur, id_lote)
    if not quedan:
        cur.execute("""UPDATE pago_transferencias_lote SET fecha_anulacion = NOW(), motivo_anulacion = %s
                        WHERE id = %s""", ("Se excluyeron todos sus pagos", id_lote))
    return {"nro_pago": det["nro_pago"], "quedan": quedan, "lote_anulado": not quedan}


def anular_lote(cur, id_lote: int, motivo: str, usuario: str | None = None) -> int:
    """El archivo entero no viajó: sus pagos quedan libres. No se anula si
    alguno ya está conciliado (eso prueba que se transmitió). Devuelve cuántos
    pagos libera."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValueError("Hace falta un motivo para anular el archivo.")
    _lote_abierto(cur, id_lote)
    cur.execute("""SELECT DISTINCT d.id_pago, COALESCE(CAST(p.nro_origen AS CHAR), p.nro_pago) AS nro_pago
                     FROM pago_transferencias_lote_det d LEFT JOIN pago_pagos p ON p.id = d.id_pago
                    WHERE d.id_lote = %s AND d.incluida = 1""", (id_lote,))
    incluidos = cur.fetchall()
    conciliados = [r["nro_pago"] for r in incluidos if anulaciones._conciliado_pago(cur, r["id_pago"])]
    if conciliados:
        raise ValueError("No se puede anular: el extracto ya muestra "
                         + ("el pago " if len(conciliados) == 1 else "los pagos ")
                         + ", ".join(conciliados[:5]) + (" y otros" if len(conciliados) > 5 else "")
                         + ". El archivo se transmitió.")
    quien = f" ({usuario})" if usuario else ""
    cur.execute("""UPDATE pago_transferencias_lote SET fecha_anulacion = NOW(), motivo_anulacion = %s
                    WHERE id = %s AND fecha_anulacion IS NULL""", ((motivo + quien)[:250], id_lote))
    return len(incluidos)


def lotes_de(cur, id_pago: int) -> list[dict]:
    """Los archivos en los que figura un pago (incluido o excluido)."""
    cur.execute("""SELECT l.id, l.nombre_archivo, l.fecha, l.formato, l.fecha_anulacion,
                          d.cbu_destino, d.importe, d.incluida, d.motivo_exclusion
                     FROM pago_transferencias_lote_det d JOIN pago_transferencias_lote l ON l.id = d.id_lote
                    WHERE d.id_pago = %s ORDER BY l.fecha DESC, l.id DESC""", (id_pago,))
    return cur.fetchall()
