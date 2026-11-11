"""
pagos_datos.py — Capa de datos del circuito de pagos (sin Flask).

Portado de `gestion_adm/pagos_routes.py` (las consultas y las reglas; las
pantallas están en pagos.py). Lo que cambia:

- Sin Integración: ni el filtro de rubro/marca, ni sus órdenes, ni la firma
  digital de sus comprobantes. Sin visibilidad por áreas.
- Crédito sin aplicar: UNA consulta (`creditos`), de la que salen el detalle y
  el total. En gestion_adm eran dos que tenían que decir lo mismo.
- Pago parcial: el expediente queda «pagado» solo si el saldo llega a cero;
  si no, sigue «liquidado» y vuelve a la lista por lo que falta (la vista de
  impagos exige `liquidado`: en gestion_adm el parcial desaparecía).
- Certificados de retención: número de `c_numeradores` (no COUNT(*)), y el
  comprobante que informa es la factura si la orden paga una sola, si no la
  orden (tipo 6) — como el importador de AEDA. gestion_adm guardaba el código
  ARCA en una columna que SIRE lee como 1 FAC / 3 NC / 4 ND / 6 OP.
- Todas las clases piden los niveles de aprobación configurados (en
  gestion_adm anticipo y concepto pedían uno fijo).
"""

from __future__ import annotations

import datetime
import logging

import movimientos_fondos as mf
from numeracion import nro_orden_visible, proximo_certificado, proximo_numero, sql_nro_orden_visible
from retenciones import calcular_retenciones_orden, total_retenciones

log = logging.getLogger(__name__)

ESTADOS_ORDEN = [("borrador", "Borrador"), ("pendiente_aprobacion", "Pendiente de aprobación"),
                 ("aprobada", "Aprobada"), ("rechazada", "Rechazada"), ("pagada", "Pagada"),
                 ("anulada", "Anulada")]
ESTADOS_TXT = dict(ESTADOS_ORDEN)
ESTADO_TIPO = {"borrador": "neutro", "pendiente_aprobacion": "warn", "aprobada": "info", "rechazada": "danger",
               "pagada": "ok", "anulada": "neutro"}
CLASES_ORDEN = [("proveedor", "Pago a proveedor"), ("anticipo", "Anticipo a proveedor"),
                ("concepto", "Pago por concepto"), ("reintegro", "Reintegro a afiliado"),
                ("sueldos", "Pago de sueldos")]
CLASES_TXT = dict(CLASES_ORDEN)
TIPOS_INSTRUMENTO = [("transferencia", "Transferencia bancaria"), ("cheque", "Cheque"), ("efectivo", "Efectivo")]

#: Una orden viva reserva sus expedientes: no pueden entrar en otra. Pagada ya
#: no (manda el saldo: así se paga en cuotas); anulada tampoco; rechazada sí.
SQL_ORDEN_RESERVA = "o2.estado NOT IN ('anulada', 'pagada')"

#: comprobante_tipo del certificado (lo que lee SIRE): 1 FAC 2 REC 3 NC 4 ND 5 OTRO 6 OP.
_FORMULARIO_SIRE = {"GANANCIAS": "2005", "IVA": "2005", "SUSS": "2004", "IIBB": None}

#: El proveedor de una orden: por los expedientes, o el del anticipo.
SQL_PROVEEDOR_ORDEN = """
    LEFT JOIN (SELECT id_orden, MIN(id_proveedor) AS id_proveedor FROM (
                 SELECT od.id_orden, e.id_proveedor FROM pago_ordenes_detalle od
                   JOIN me_expedientes e ON e.id = od.id_expediente WHERE e.id_proveedor IS NOT NULL
                 UNION
                 SELECT ad.id_orden, ad.id_proveedor FROM pago_ordenes_anticipo_det ad
                  WHERE ad.id_proveedor IS NOT NULL) x
                GROUP BY id_orden) op ON op.id_orden = o.id
    LEFT JOIN c_proveedores pr ON pr.id = op.id_proveedor"""

#: A quién se le paga, según la clase.
SQL_BENEFICIARIO = """CASE o.clase
      WHEN 'proveedor' THEN (SELECT GROUP_CONCAT(DISTINCT e.razon_social_emisor SEPARATOR ' / ')
                               FROM pago_ordenes_detalle d JOIN me_expedientes e ON e.id = d.id_expediente
                              WHERE d.id_orden = o.id)
      WHEN 'anticipo' THEN (SELECT GROUP_CONCAT(DISTINCT p.razon_social SEPARATOR ' / ')
                              FROM pago_ordenes_anticipo_det ad JOIN c_proveedores p ON p.id = ad.id_proveedor
                             WHERE ad.id_orden = o.id)
      WHEN 'reintegro' THEN (SELECT GROUP_CONCAT(DISTINCT rd.nombre SEPARATOR ' / ')
                               FROM pago_ordenes_reintegro_det rd WHERE rd.id_orden = o.id)
      WHEN 'concepto' THEN (SELECT GROUP_CONCAT(DISTINCT cd.descripcion SEPARATOR ' / ')
                              FROM pago_ordenes_concepto_det cd WHERE cd.id_orden = o.id)
      WHEN 'sueldos' THEN (SELECT CONCAT(COUNT(*), ' empleado(s)')
                             FROM pago_ordenes_sueldos_det sd WHERE sd.id_orden = o.id)
    END"""

#: Lo retenido y vigente de una orden (las retenciones de un pago anulado no).
SQL_RETENIDO_ORDEN = """(SELECT COALESCE(SUM(r.importe), 0) FROM pago_retenciones r
                          LEFT JOIN pago_pagos pr2 ON pr2.id = r.id_pago
                         WHERE r.id_orden = o.id AND COALESCE(r.anulado, 0) = 0
                           AND COALESCE(pr2.estado, 'emitido') <> 'anulado')"""
SQL_PAGADO_ORDEN = """(SELECT COALESCE(SUM(pp.importe_total), 0) FROM pago_pagos pp
                        WHERE pp.id_orden = o.id AND pp.estado <> 'anulado')"""


class ErrorPago(ValueError):
    """Un error de validación: el texto va directo a la pantalla."""


# ─────────────────────────────────────────────────────────────────────────────
# Importes
# ─────────────────────────────────────────────────────────────────────────────

def leer_importe(texto) -> float | None:
    """«1.234.567,89», «1234567.89» o «1.234» (miles) → número. None si no es
    un importe. Con coma: puntos de miles y coma decimal. Sin coma, el punto es
    de miles solo si todos los grupos que siguen tienen tres dígitos."""
    t = (texto or "").strip().replace(" ", "").replace("$", "")
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif "." in t:
        grupos = t.split(".")
        if all(len(g) == 3 and g.isdigit() for g in grupos[1:]):
            t = "".join(grupos)
    try:
        return round(float(t), 2)
    except ValueError:
        return None


def importe_a_pagar(texto, saldo) -> tuple[float | None, str | None]:
    """El importe de un renglón de la orden contra el saldo. Vacío = todo el
    saldo. El tope es el saldo (para adelantar plata están los anticipos)."""
    saldo = round(float(saldo or 0), 2)
    if not (texto or "").strip():
        return saldo, None
    importe = leer_importe(texto)
    if importe is None:
        return None, f"«{texto}» no es un importe"
    if importe <= 0:
        return None, "el importe tiene que ser mayor que cero"
    if importe > saldo + 0.01:
        return None, f"{importe:,.2f} supera el saldo de {saldo:,.2f}"
    return min(importe, saldo), None


# ─────────────────────────────────────────────────────────────────────────────
# Qué se puede pagar
# ─────────────────────────────────────────────────────────────────────────────

def expedientes_disponibles(cur, id_proveedor: int | None = None) -> list[dict]:
    """Expedientes liquidados con saldo que no están en una orden viva. La misma
    consulta para la lista de proveedores y para la pantalla del proveedor."""
    filtro = "AND v.id_proveedor = %s" if id_proveedor else ""
    cur.execute(f"""
        SELECT v.*, me.id_comprobante, fa.numero_completo AS comp_numero, fa.fecha_emision AS comp_fecha,
               COALESCE(tc.descripcion, fa.tipo_comprobante) AS comp_tipo,
               IF(COALESCE(TRIM(fa.ruta_local), '') = '', 0, 1) AS comp_pdf,
               fa.constatacion_resultado, fa.leido_automatico, fa.verificado_visual,
               (SELECT COUNT(*) FROM pago_ordenes_detalle d3 JOIN pago_ordenes o3 ON o3.id = d3.id_orden
                 WHERE d3.id_expediente = v.id AND o3.estado = 'pagada') AS pagos_previos_n,
               (SELECT ROUND(SUM(d3.importe), 2) FROM pago_ordenes_detalle d3
                  JOIN pago_ordenes o3 ON o3.id = d3.id_orden
                 WHERE d3.id_expediente = v.id AND o3.estado = 'pagada') AS pagos_previos_importe
          FROM v_expedientes_liquidados_impagos v
          LEFT JOIN me_expedientes me ON me.id = v.id
          LEFT JOIN f_comprobantes_arca fa ON fa.id = me.id_comprobante
          LEFT JOIN arca_tipo_comprobante tc ON tc.codigo = fa.tipo_comprobante
         WHERE NOT EXISTS (SELECT 1 FROM pago_ordenes_detalle d2 JOIN pago_ordenes o2 ON o2.id = d2.id_orden
                            WHERE d2.id_expediente = v.id AND {SQL_ORDEN_RESERVA})
           {filtro}
         ORDER BY v.cuit_emisor, comp_fecha IS NULL, comp_fecha, comp_numero, v.nro_expediente""",
                (id_proveedor,) if id_proveedor else ())
    return list(cur.fetchall())


def creditos(cur, ids_proveedor) -> dict:
    """{id_proveedor: [crédito, …]}: plata que ya es del proveedor y no se
    descontó de ninguna factura. Notas de crédito con saldo, y pagos (de
    órdenes de comprobantes o anticipos) con saldo sin imputar. Emitir la orden
    sin aplicarlos es pagar de más."""
    ids = sorted({int(i) for i in ids_proveedor if i})
    if not ids:
        return {}
    m = ",".join(["%s"] * len(ids))
    cur.execute(f"""
        SELECT e.id_proveedor, 'nota' AS clase, l.id, e.nro_expediente AS referencia,
               COALESCE(tc.descripcion, 'Nota de crédito') AS descripcion, fa.numero_completo,
               COALESCE(fa.fecha_emision, l.fecha_cierre) AS fecha,
               ROUND(ABS(l.importe_liquidado) - COALESCE((SELECT SUM(a.importe_aplicado) FROM c_pasivo_aplicacion a
                                                           WHERE a.id_liq_credito = l.id), 0), 2) AS saldo
          FROM c_pasivo_liquidacion l
          JOIN me_expedientes e ON e.id = l.id_expediente
          LEFT JOIN f_comprobantes_arca fa ON fa.id = e.id_comprobante
          LEFT JOIN arca_tipo_comprobante tc ON tc.codigo = fa.tipo_comprobante
         WHERE l.importe_liquidado < -0.01 AND e.estado NOT IN ('anulado', 'reintegro')
           AND e.id_proveedor IN ({m})
        HAVING saldo > 0.01""", ids)
    filas = list(cur.fetchall())
    cur.execute(f"""
        SELECT op.id_proveedor, 'pago' AS clase, p.id, {sql_nro_orden_visible('o')} AS referencia,
               IF(o.clase = 'anticipo', 'Anticipo', 'Pago a cuenta') AS descripcion,
               p.nro_pago AS numero_completo, p.fecha_pago AS fecha,
               ROUND(p.importe_total
                     - COALESCE((SELECT SUM(l.importe_liquidado) FROM c_pasivo_liquidacion l
                                   JOIN me_expedientes e ON e.id = l.id_expediente AND e.estado <> 'anulado'
                                  WHERE l.id_pago = p.id), 0)
                     - COALESCE((SELECT SUM(a.importe_aplicado) FROM c_pasivo_aplicacion a
                                  WHERE a.id_pago = p.id), 0), 2) AS saldo
          FROM pago_pagos p
          JOIN pago_ordenes o ON o.id = p.id_orden
          JOIN (SELECT id_orden, MIN(id_proveedor) AS id_proveedor FROM (
                  SELECT od.id_orden, e.id_proveedor FROM pago_ordenes_detalle od
                    JOIN me_expedientes e ON e.id = od.id_expediente
                   WHERE e.id_proveedor IS NOT NULL AND e.estado NOT IN ('anulado', 'reintegro')
                  UNION
                  SELECT ad.id_orden, ad.id_proveedor FROM pago_ordenes_anticipo_det ad
                   WHERE ad.id_proveedor IS NOT NULL) u GROUP BY id_orden) op ON op.id_orden = o.id
         WHERE p.estado <> 'anulado' AND op.id_proveedor IN ({m})
        HAVING saldo > 0.01""", ids)
    filas += list(cur.fetchall())
    out: dict = {}
    for f in sorted(filas, key=lambda x: (x["fecha"] or datetime.date.min)):
        out.setdefault(f["id_proveedor"], []).append(f)
    return out


def ops_sin_pago(cur, ids_proveedor) -> dict:
    """{id_proveedor: [orden, …]}: órdenes no anuladas y sin pago vivo. Se
    avisa al armar otra (regla de gestion_adm del 02/11/2026): una OP olvidada
    es la que después se paga dos veces."""
    ids = sorted({int(i) for i in ids_proveedor if i})
    if not ids:
        return {}
    m = ",".join(["%s"] * len(ids))
    cur.execute(f"""
        SELECT x.id_proveedor, o.id, o.clase, o.estado, o.fecha, o.importe_total,
               {sql_nro_orden_visible('o')} AS nro_vis,
               EXISTS (SELECT 1 FROM pago_pagos pa WHERE pa.id_orden = o.id AND pa.estado = 'anulado') AS pago_anulado
          FROM pago_ordenes o
          JOIN (SELECT od.id_orden, e.id_proveedor FROM pago_ordenes_detalle od
                  JOIN me_expedientes e ON e.id = od.id_expediente WHERE e.id_proveedor IN ({m})
                UNION
                SELECT ad.id_orden, ad.id_proveedor FROM pago_ordenes_anticipo_det ad
                 WHERE ad.id_proveedor IN ({m})) x ON x.id_orden = o.id
         WHERE o.estado <> 'anulada'
           AND NOT EXISTS (SELECT 1 FROM pago_pagos p WHERE p.id_orden = o.id AND p.estado <> 'anulado')
         ORDER BY o.fecha, o.id""", ids * 2)
    textos = {"borrador": "en borrador", "pendiente_aprobacion": "esperando aprobación",
              "aprobada": "aprobada, sin pagar", "rechazada": "rechazada por un aprobador"}
    out: dict = {}
    for r in cur.fetchall():
        r["estado_txt"] = "con el pago anulado" if r["pago_anulado"] else textos.get(r["estado"], r["estado"])
        r["clase_txt"] = "Anticipo" if r["clase"] == "anticipo" else "OP"
        out.setdefault(r["id_proveedor"], []).append(r)
    return out


def agrupar_por_proveedor(expedientes, creds: dict, ops: dict) -> list[dict]:
    """La grilla de «a quién se le paga»: por proveedor, el saldo (no el
    importe del comprobante), el crédito sin aplicar y las OP sin pago."""
    provs: dict = {}
    for e in expedientes:
        clave = e.get("id_proveedor") or 0
        p = provs.get(clave)
        if p is None:
            c = creds.get(e.get("id_proveedor")) or []
            p = provs[clave] = {"id_proveedor": e.get("id_proveedor"),
                                "proveedor": e.get("proveedor") or e.get("razon_social_emisor") or "Sin proveedor",
                                "cuit": e.get("cuit_emisor"), "n": 0, "importe": 0.0, "rubros": set(),
                                "credito_n": len(c), "credito_importe": sum(float(x["saldo"]) for x in c),
                                "ops_sin_pago": ops.get(e.get("id_proveedor")) or []}
        p["n"] += 1
        p["importe"] += float(e.get("saldo_pendiente") or 0)
        if e.get("rubro"):
            p["rubros"].add(e["rubro"])
    for p in provs.values():
        p["rubros"] = sorted(p["rubros"])
    return sorted(provs.values(), key=lambda p: -p["importe"])


# ─────────────────────────────────────────────────────────────────────────────
# Para el pago
# ─────────────────────────────────────────────────────────────────────────────

def cbu_beneficiarios(cur, orden) -> list[dict]:
    """A qué CBU se transfiere: de la ficha del proveedor (proveedor y
    anticipo) o del reintegro (detalle, solicitud y por último la ficha del
    afiliado). Concepto y sueldos no tienen uno."""
    clase, id_orden = orden.get("clase"), orden.get("id")
    if clase == "proveedor":
        cur.execute("""SELECT DISTINCT p.razon_social AS nombre, p.cbu, p.cbu_alias AS alias
                         FROM pago_ordenes_detalle d JOIN me_expedientes e ON e.id = d.id_expediente
                         JOIN c_proveedores p ON p.id = e.id_proveedor
                        WHERE d.id_orden = %s AND (COALESCE(p.cbu, '') <> '' OR COALESCE(p.cbu_alias, '') <> '')
                        ORDER BY p.razon_social""", (id_orden,))
    elif clase == "anticipo":
        cur.execute("""SELECT DISTINCT p.razon_social AS nombre, p.cbu, p.cbu_alias AS alias
                         FROM pago_ordenes_anticipo_det ad JOIN c_proveedores p ON p.id = ad.id_proveedor
                        WHERE ad.id_orden = %s AND (COALESCE(p.cbu, '') <> '' OR COALESCE(p.cbu_alias, '') <> '')
                        ORDER BY p.razon_social""", (id_orden,))
    elif clase == "reintegro":
        cur.execute("""SELECT DISTINCT rd.nombre,
                              COALESCE(NULLIF(TRIM(rd.cbu_destino), ''), NULLIF(TRIM(r.cbu_destino), ''),
                                       NULLIF(TRIM(a.cbu_pago), '')) AS cbu,
                              COALESCE(NULLIF(TRIM(rd.alias_destino), ''), NULLIF(TRIM(r.alias_destino), '')) AS alias
                         FROM pago_ordenes_reintegro_det rd
                         LEFT JOIN c_reintegro_afiliados r ON r.id = rd.id_reintegro
                         LEFT JOIN p_afiliados a ON a.id_afiliado = rd.id_afiliado
                        WHERE rd.id_orden = %s
                       HAVING cbu IS NOT NULL OR alias IS NOT NULL
                        ORDER BY rd.nombre""", (id_orden,))
    else:
        return []
    return [{"nombre": (r["nombre"] or "").strip(), "cbu": (r["cbu"] or "").strip(),
             "alias": (r["alias"] or "").strip()} for r in cur.fetchall()]


def cuentas_pago(cur) -> list[dict]:
    cur.execute("""SELECT cf.id, cf.nombre, cf.tipo_de_cuenta, cf.numero_de_cuenta, cf.cbu, cf.alias,
                          cf.predeterminada, b.nombre AS banco_nombre, e.simbolo AS moneda_simbolo
                     FROM c_cuentas_de_fondos cf
                     LEFT JOIN c_codigo_de_banco b ON b.id = cf.c_codigo_de_bancoId
                     LEFT JOIN c_especies e ON e.id = cf.c_especiesId
                    WHERE cf.esdepago = 1 AND cf.habilitada = 1
                    ORDER BY cf.predeterminada DESC, cf.nombre""")
    return list(cur.fetchall())


def chequeras_habilitadas(cur) -> list[dict]:
    """Chequeras con números por usar (una habilitada pero agotada no se ofrece)."""
    cur.execute("""SELECT q.id, q.c_cuentas_de_fondosId AS id_cuenta, q.descripcion, q.tipo_cheque,
                          q.numero_desde, q.numero_hasta, q.proximo_numero
                     FROM c_chequeras q JOIN c_cuentas_de_fondos cf ON cf.id = q.c_cuentas_de_fondosId
                    WHERE q.habilitada = 1 AND cf.esdepago = 1 AND cf.habilitada = 1
                      AND q.proximo_numero <= q.numero_hasta
                    ORDER BY q.c_cuentas_de_fondosId, q.proximo_numero""")
    return [{"id": r["id"], "id_cuenta": r["id_cuenta"], "descripcion": r["descripcion"] or f"Chequera {r['id']}",
             "tipo_cheque": r["tipo_cheque"], "desde": int(r["numero_desde"]), "hasta": int(r["numero_hasta"]),
             "proximo": int(r["proximo_numero"]),
             "disponibles": int(r["numero_hasta"]) - int(r["proximo_numero"]) + 1} for r in cur.fetchall()]


def consumir_chequeras(cur, id_pago: int) -> None:
    """Adelanta la chequera hasta pasar el último cheque del pago, y rechaza
    un número que no es número, fuera de la chequera o ya emitido en otro pago
    vivo. Dentro de la transacción del pago, con FOR UPDATE."""
    cur.execute("""SELECT id_chequera, nro_cheque FROM pago_pagos_instrumentos
                    WHERE id_pago = %s AND tipo_instrumento = 'cheque'
                      AND id_chequera IS NOT NULL AND nro_cheque IS NOT NULL""", (id_pago,))
    usados: dict[int, list[int]] = {}
    for r in cur.fetchall():
        crudo = (r["nro_cheque"] or "").strip()
        if not crudo.isdigit():
            raise ErrorPago(f"El número de cheque «{crudo}» no es un número.")
        usados.setdefault(int(r["id_chequera"]), []).append(int(crudo))
    for id_chequera, numeros in usados.items():
        cur.execute("SELECT id, descripcion, numero_desde, numero_hasta, proximo_numero FROM c_chequeras "
                    "WHERE id = %s FOR UPDATE", (id_chequera,))
        q = cur.fetchone()
        if not q:
            raise ErrorPago("La chequera elegida ya no existe.")
        nombre = q["descripcion"] or f"chequera {id_chequera}"
        fuera = [n for n in numeros if n < q["numero_desde"] or n > q["numero_hasta"]]
        if fuera:
            raise ErrorPago(f"El cheque {fuera[0]} está fuera de la {nombre} "
                            f"(va del {q['numero_desde']} al {q['numero_hasta']}).")
        if len(set(numeros)) != len(numeros):
            raise ErrorPago(f"Hay números de cheque repetidos en el pago ({nombre}).")
        cur.execute(f"""SELECT i.nro_cheque, p.nro_pago FROM pago_pagos_instrumentos i
                          JOIN pago_pagos p ON p.id = i.id_pago
                         WHERE i.id_chequera = %s AND i.id_pago <> %s AND p.estado <> 'anulado'
                           AND CAST(i.nro_cheque AS UNSIGNED) IN ({', '.join(['%s'] * len(numeros))}) LIMIT 1""",
                    [id_chequera, id_pago] + numeros)
        rep = cur.fetchone()
        if rep:
            raise ErrorPago(f"El cheque {rep['nro_cheque']} de la {nombre} ya se emitió en el pago {rep['nro_pago']}.")
        cur.execute("UPDATE c_chequeras SET proximo_numero = %s WHERE id = %s AND proximo_numero < %s",
                    (max(numeros) + 1, id_chequera, max(numeros) + 1))


# ─────────────────────────────────────────────────────────────────────────────
# Aprobación
# ─────────────────────────────────────────────────────────────────────────────

def niveles(cur) -> list[int]:
    cur.execute("SELECT DISTINCT nivel FROM pago_config_aprobadores WHERE activo = 1 ORDER BY nivel")
    return [int(r["nivel"]) for r in cur.fetchall()]


def max_nivel(cur) -> int:
    n = niveles(cur)
    return max(n) if n else 1


def nivel_usuario(cur, id_usuario) -> int | None:
    """El nivel más bajo que tiene asignado el usuario (None si no aprueba)."""
    cur.execute("SELECT MIN(nivel) AS n FROM pago_config_aprobadores WHERE id_usuario = %s AND activo = 1",
                (id_usuario or 0,))
    r = cur.fetchone()
    return int(r["n"]) if r and r["n"] is not None else None


def niveles_pendientes_de(cur, id_orden: int, id_usuario) -> list[int]:
    """Los niveles de la orden todavía pendientes que este usuario puede firmar."""
    cur.execute("""SELECT a.nivel FROM pago_ordenes_aprobacion a
                    WHERE a.id_orden = %s AND a.estado = 'pendiente'
                      AND a.nivel IN (SELECT nivel FROM pago_config_aprobadores
                                       WHERE id_usuario = %s AND activo = 1)
                    ORDER BY a.nivel""", (id_orden, id_usuario or 0))
    return [int(r["nivel"]) for r in cur.fetchall()]


def enviar_a_aprobacion(cur, id_orden: int, obs: str | None) -> str:
    cur.execute("SELECT estado FROM pago_ordenes WHERE id = %s FOR UPDATE", (id_orden,))
    o = cur.fetchone()
    if not o:
        raise ErrorPago("La orden no existe.")
    if o["estado"] != "borrador":
        raise ErrorPago("Solo se envía a aprobación una orden en borrador.")
    lista = niveles(cur)
    if not lista:
        # En gestion_adm la orden quedaba «pendiente» sin ningún nivel que la
        # pudiera aprobar, para siempre.
        raise ErrorPago("No hay aprobadores configurados. Cargalos en Tesorería → Pagos → Config. Aprobadores "
                        "(un usuario por nivel) y volvé a enviar.")
    cur.execute("""UPDATE pago_ordenes SET estado = 'pendiente_aprobacion', niveles_requeridos = %s,
                          niveles_aprobados = 0,
                          observaciones = CONCAT_WS('\n', NULLIF(observaciones, ''), %s)
                    WHERE id = %s""", (len(lista), obs, id_orden))
    cur.execute("DELETE FROM pago_ordenes_aprobacion WHERE id_orden = %s", (id_orden,))
    for n in lista:
        cur.execute("INSERT INTO pago_ordenes_aprobacion (id_orden, nivel, estado) VALUES (%s, %s, 'pendiente')",
                    (id_orden, n))
    return f"Orden enviada a aprobación ({len(lista)} nivel{'es' if len(lista) > 1 else ''})."


def aprobar(cur, id_orden: int, id_usuario, obs: str | None) -> str:
    cur.execute("SELECT estado FROM pago_ordenes WHERE id = %s FOR UPDATE", (id_orden,))
    o = cur.fetchone()
    if not o or o["estado"] != "pendiente_aprobacion":
        raise ErrorPago("La orden no está esperando aprobación.")
    mios = niveles_pendientes_de(cur, id_orden, id_usuario)
    if not mios:
        raise ErrorPago("No tenés un nivel de aprobación pendiente en esta orden.")
    nivel = mios[0]
    cur.execute("""UPDATE pago_ordenes_aprobacion SET estado = 'aprobado', id_usuario = %s, fecha = NOW(),
                          observaciones = %s
                    WHERE id_orden = %s AND nivel = %s AND estado = 'pendiente'""", (id_usuario, obs, id_orden, nivel))
    cur.execute("SELECT COUNT(*) AS n FROM pago_ordenes_aprobacion WHERE id_orden = %s AND estado = 'pendiente'",
                (id_orden,))
    pendientes = cur.fetchone()["n"]
    if pendientes == 0:
        cur.execute("UPDATE pago_ordenes SET estado = 'aprobada', niveles_aprobados = niveles_requeridos "
                    "WHERE id = %s", (id_orden,))
        return "Orden aprobada en todos los niveles: ya se puede pagar."
    cur.execute("UPDATE pago_ordenes SET niveles_aprobados = niveles_aprobados + 1 WHERE id = %s", (id_orden,))
    return f"Nivel {nivel} aprobado. Falta{'n' if pendientes > 1 else ''} {pendientes} nivel{'es' if pendientes > 1 else ''}."


def rechazar(cur, id_orden: int, id_usuario, obs: str | None) -> str:
    cur.execute("SELECT estado FROM pago_ordenes WHERE id = %s FOR UPDATE", (id_orden,))
    o = cur.fetchone()
    if not o or o["estado"] != "pendiente_aprobacion":
        raise ErrorPago("La orden no está esperando aprobación.")
    mios = niveles_pendientes_de(cur, id_orden, id_usuario)
    if not mios:
        raise ErrorPago("No tenés un nivel de aprobación pendiente en esta orden.")
    if not (obs or "").strip():
        raise ErrorPago("Para rechazar, escribí el motivo en observaciones.")
    cur.execute("""UPDATE pago_ordenes_aprobacion SET estado = 'rechazado', id_usuario = %s, fecha = NOW(),
                          observaciones = %s
                    WHERE id_orden = %s AND nivel = %s AND estado = 'pendiente'""",
                (id_usuario, obs, id_orden, mios[0]))
    cur.execute("UPDATE pago_ordenes SET estado = 'rechazada' WHERE id = %s", (id_orden,))
    return "Orden rechazada. Para rehacerla, anulala: eso libera los comprobantes."


# ─────────────────────────────────────────────────────────────────────────────
# Alta de órdenes
# ─────────────────────────────────────────────────────────────────────────────

def _insertar_orden(cur, clase: str, total: float, obs: str | None, id_usuario) -> tuple[int, str]:
    nro = proximo_numero(cur, "pago_ordenes")
    cur.execute("""INSERT INTO pago_ordenes (nro_orden, clase, anio, fecha, estado, importe_total, moneda,
                                             niveles_requeridos, niveles_aprobados, observaciones,
                                             id_usuario_creacion)
                   VALUES (%s, %s, YEAR(CURDATE()), CURDATE(), 'borrador', %s, 'ARS', %s, 0, %s, %s)""",
                (nro, clase, round(total, 2), max_nivel(cur), obs, id_usuario))
    return cur.lastrowid, nro


def crear_orden_proveedor(cur, ids_expediente: list[int], importes: dict, obs, id_usuario) -> dict:
    """La orden de un proveedor con sus expedientes. `importes`: {id_exp: texto}.
    Se valida contra lo que dice la base ahora, no contra lo que mostraba la
    grilla."""
    if not ids_expediente:
        raise ErrorPago("Elegí al menos un comprobante.")
    m = ",".join(["%s"] * len(ids_expediente))
    cur.execute(f"""
        SELECT e.id, e.nro_expediente, e.estado, e.id_proveedor, e.moneda,
               COALESCE(p.razon_social, e.razon_social_emisor) AS proveedor, l.id AS id_liquidacion, l.id_pago,
               ROUND(l.importe_liquidado - IF(l.id_pago IS NOT NULL, l.importe_liquidado, 0)
                     - COALESCE((SELECT SUM(a.importe_aplicado) FROM c_pasivo_aplicacion a
                                  WHERE a.id_liq_debito = l.id), 0), 2) AS saldo_pendiente,
               (SELECT GROUP_CONCAT(DISTINCT {sql_nro_orden_visible('o2')} ORDER BY o2.id SEPARATOR ', ')
                  FROM pago_ordenes_detalle d2 JOIN pago_ordenes o2 ON o2.id = d2.id_orden
                 WHERE d2.id_expediente = e.id AND {SQL_ORDEN_RESERVA}) AS ordenes_previas
          FROM me_expedientes e
          JOIN c_pasivo_liquidacion l ON l.id_expediente = e.id
          LEFT JOIN c_proveedores p ON p.id = e.id_proveedor
         WHERE e.id IN ({m})
           FOR UPDATE""", ids_expediente)
    rows = list(cur.fetchall())
    if len({r["id"] for r in rows}) != len(set(ids_expediente)):
        raise ErrorPago("Algún comprobante ya no existe o no tiene liquidación.")
    invalidos = [r for r in rows if r["estado"] != "liquidado" or r["id_pago"] is not None
                 or float(r["saldo_pendiente"] or 0) <= 0.01]
    if invalidos:
        raise ErrorPago("No están disponibles (ya pagados o sin liquidar): "
                        + ", ".join(r["nro_expediente"] for r in invalidos[:6]) + ".")
    provs = {r["id_proveedor"] for r in rows}
    if None in provs:
        raise ErrorPago("Hay comprobantes sin proveedor asignado: asignáselo en el expediente.")
    if len(provs) > 1:
        nombres = sorted({r["proveedor"] or "" for r in rows})
        raise ErrorPago(f"Una orden de pago es de un solo proveedor y la selección tiene {len(provs)}: "
                        f"{', '.join(nombres[:4])}. Armá una orden por cada uno.")
    repetidos = [r for r in rows if r["ordenes_previas"]]
    if repetidos:
        raise ErrorPago("Ya tienen orden de pago emitida: "
                        + "; ".join(f"{r['nro_expediente']} en {r['ordenes_previas']}" for r in repetidos[:8])
                        + ". Si esa orden no va, anulala primero.")
    errores = []
    for r in rows:
        r["a_pagar"], err = importe_a_pagar(importes.get(r["id"]), r["saldo_pendiente"])
        if err:
            errores.append(f"{r['nro_expediente']}: {err}")
    if errores:
        raise ErrorPago("Revisá los importes: " + "; ".join(errores[:6]) + ".")
    total = sum(r["a_pagar"] for r in rows)
    id_orden, nro = _insertar_orden(cur, "proveedor", total, obs, id_usuario)
    for r in rows:
        cur.execute("""INSERT INTO pago_ordenes_detalle (id_orden, id_expediente, id_liquidacion, importe, moneda)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (id_orden, r["id"], r["id_liquidacion"], r["a_pagar"], r["moneda"] or "ARS"))
    cur.execute(f"UPDATE me_expedientes SET id_orden_pago = %s WHERE id IN ({m})", [id_orden] + ids_expediente)
    parciales = sum(1 for r in rows if r["a_pagar"] < float(r["saldo_pendiente"]) - 0.01)
    return {"id_orden": id_orden, "nro": nro, "n": len(rows), "parciales": parciales}


def rubros_de_proveedor(cur, id_proveedor) -> list[dict]:
    cur.execute("""SELECT r.id, r.nombre, cp.predeterminada FROM c_proveedores_cuentas_pasivo cp
                     JOIN c_rubros_de_pasivo r ON r.id = cp.id_rubro_pasivo
                    WHERE cp.id_proveedor = %s AND cp.activa = 1
                    ORDER BY cp.predeterminada DESC, r.nombre""", (id_proveedor,))
    return list(cur.fetchall())


def imputaciones(cur, clase: str) -> list[dict]:
    cur.execute("""SELECT i.id, i.nombre, cd.codigo AS codigo_debe, cd.nombre AS cuenta_debe,
                          ch.codigo AS codigo_haber, ch.nombre AS cuenta_haber
                     FROM pago_imputaciones_config i
                     LEFT JOIN c_plan_de_cuentas cd ON cd.id_cuenta = i.id_cuenta_debe
                     LEFT JOIN c_plan_de_cuentas ch ON ch.id_cuenta = i.id_cuenta_haber
                    WHERE i.clase = %s AND i.activo = 1 ORDER BY i.nombre""", (clase,))
    return list(cur.fetchall())


def crear_orden_anticipo(cur, id_proveedor, id_imputacion, id_rubro, descripcion, importe, obs, id_usuario) -> dict:
    if not id_proveedor:
        raise ErrorPago("El proveedor es obligatorio.")
    cur.execute("SELECT id, razon_social, activo FROM c_proveedores WHERE id = %s", (id_proveedor,))
    prov = cur.fetchone()
    if not prov or not prov["activo"]:
        raise ErrorPago("El proveedor no existe o está dado de baja.")
    if not id_imputacion or not any(i["id"] == id_imputacion for i in imputaciones(cur, "anticipo")):
        raise ErrorPago("Elegí la imputación contable del anticipo.")
    if importe is None or importe <= 0:
        raise ErrorPago("El importe tiene que ser mayor que cero.")
    rubros = rubros_de_proveedor(cur, id_proveedor)
    if not id_rubro:
        if len(rubros) > 1:
            raise ErrorPago("El proveedor tiene más de una cuenta de pasivo: elegí a cuál se imputa el anticipo.")
        id_rubro = rubros[0]["id"] if rubros else None
    elif id_rubro not in [r["id"] for r in rubros]:
        raise ErrorPago("La cuenta de pasivo elegida no está configurada para ese proveedor.")
    id_orden, nro = _insertar_orden(cur, "anticipo", importe, obs, id_usuario)
    cur.execute("""INSERT INTO pago_ordenes_anticipo_det (id_orden, id_proveedor, id_imputacion, id_rubro_pasivo,
                                                          descripcion, importe, moneda)
                   VALUES (%s, %s, %s, %s, %s, %s, 'ARS')""",
                (id_orden, id_proveedor, id_imputacion, id_rubro, descripcion, round(importe, 2)))
    return {"id_orden": id_orden, "nro": nro}


def crear_orden_concepto(cur, lineas: list[dict], obs, id_usuario) -> dict:
    """`lineas`: [{tipo gasto|ingreso, id (concepto o motivo), descripcion, importe, periodo AAAAMM}]."""
    if not lineas:
        raise ErrorPago("Agregá al menos un concepto a la orden.")
    errores = []
    for i, l in enumerate(lineas, 1):
        if l["tipo"] not in ("gasto", "ingreso"):
            errores.append(f"Renglón {i}: tipo inválido.")
        if not l.get("id"):
            errores.append(f"Renglón {i}: elegí el {'concepto de gasto' if l['tipo'] == 'gasto' else 'motivo de ingreso'}.")
        if not (l.get("descripcion") or "").strip():
            errores.append(f"Renglón {i}: la descripción es obligatoria.")
        if l.get("importe") is None or l["importe"] <= 0:
            errores.append(f"Renglón {i}: el importe tiene que ser mayor que cero.")
    if errores:
        raise ErrorPago(" ".join(errores[:8]))
    total = sum(l["importe"] for l in lineas)
    id_orden, nro = _insertar_orden(cur, "concepto", total, obs, id_usuario)
    for l in lineas:
        cur.execute("""INSERT INTO pago_ordenes_concepto_det (id_orden, tipo, id_concepto_gasto, id_motivo_ingreso,
                                                              descripcion, importe, moneda, periodo)
                       VALUES (%s, %s, %s, %s, %s, %s, 'ARS', %s)""",
                    (id_orden, l["tipo"], l["id"] if l["tipo"] == "gasto" else None,
                     l["id"] if l["tipo"] == "ingreso" else None, l["descripcion"].strip()[:200],
                     round(l["importe"], 2), l.get("periodo") or None))
    return {"id_orden": id_orden, "nro": nro}


# ─────────────────────────────────────────────────────────────────────────────
# Pago
# ─────────────────────────────────────────────────────────────────────────────

def instrumentos_del_form(form) -> list[dict]:
    """Las listas paralelas del formulario de pago, un dict por instrumento."""
    campos = ["id_cuenta_fondos", "tipo_instrumento", "importe_instrumento", "nro_cheque", "fecha_cheque",
              "cbu_destino", "nro_referencia", "id_chequera", "cruzado"]
    listas = {c: form.getlist(c) for c in campos}
    out = []
    for i in range(len(listas["id_cuenta_fondos"])):
        v = {c: ((listas[c][i] if i < len(listas[c]) else "") or "").strip() for c in campos}
        out.append({"id_cuenta": int(v["id_cuenta_fondos"]) if v["id_cuenta_fondos"].isdigit() else None,
                    "tipo": v["tipo_instrumento"], "importe": leer_importe(v["importe_instrumento"]),
                    "nro_cheque": v["nro_cheque"] or None, "fecha_cheque": v["fecha_cheque"] or None,
                    "cbu": v["cbu_destino"] or None, "referencia": v["nro_referencia"] or None,
                    "id_chequera": int(v["id_chequera"]) if v["id_chequera"].isdigit() else None,
                    "cruzado": 1 if v["cruzado"] == "1" else 0})
    return out


def _comprobante_certificado(cur, id_orden: int, fecha_pago, importe_orden) -> tuple:
    """(tipo, pv, nro, fecha, importe, cae) que informa el certificado: la
    factura si la orden paga una sola; si no, la orden (6)."""
    cur.execute("""SELECT fa.punto_de_venta, fa.numero, fa.fecha_emision, fa.importe_total, fa.cae,
                          tc.descripcion
                     FROM pago_ordenes_detalle d JOIN me_expedientes e ON e.id = d.id_expediente
                     LEFT JOIN f_comprobantes_arca fa ON fa.id = e.id_comprobante
                     LEFT JOIN arca_tipo_comprobante tc ON tc.codigo = fa.tipo_comprobante
                    WHERE d.id_orden = %s""", (id_orden,))
    filas = cur.fetchall()
    if len(filas) == 1 and filas[0]["numero"]:
        f = filas[0]
        desc = (f["descripcion"] or "").lower()
        tipo = 3 if "crédito" in desc or "credito" in desc else 4 if "débito" in desc or "debito" in desc \
            else 2 if "recibo" in desc else 1
        return tipo, f["punto_de_venta"], f["numero"], f["fecha_emision"], f["importe_total"], f["cae"]
    cur.execute("SELECT nro_orden FROM pago_ordenes WHERE id = %s", (id_orden,))
    nro = "".join(c for c in cur.fetchone()["nro_orden"] if c.isdigit())
    return 6, None, int(nro[-8:]) if nro else id_orden, fecha_pago, importe_orden, None


def ejecutar_pago(conn, id_orden: int, fecha_pago: str, instrumentos: list[dict], obs, id_usuario) -> dict:
    """Emite el pago de una orden aprobada: pago, instrumentos, chequeras,
    libro de fondos, retenciones y certificados, aplicación contra las
    liquidaciones, estado de expedientes y orden. TODO EN UNA TRANSACCIÓN: lo
    abre y lo confirma acá; si algo falla, no queda nada escrito."""
    try:
        fecha = datetime.date.fromisoformat(fecha_pago)
    except (TypeError, ValueError):
        raise ErrorPago("La fecha de pago no es válida.")
    if not instrumentos:
        raise ErrorPago("Agregá al menos un instrumento de pago.")
    conn.begin()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM pago_ordenes WHERE id = %s FOR UPDATE", (id_orden,))
            orden = cur.fetchone()
            if not orden or orden["estado"] != "aprobada":
                raise ErrorPago("La orden tiene que estar aprobada para pagarla.")
            if orden["clase"] == "sueldos":
                raise ErrorPago("Las órdenes de sueldos se pagan por empleado.")
            cuentas = {c["id"]: c for c in cuentas_pago(cur)}
            for n, i in enumerate(instrumentos, 1):
                if i["id_cuenta"] not in cuentas:
                    raise ErrorPago(f"Instrumento {n}: la cuenta no está habilitada para pagar.")
                if i["tipo"] not in dict(TIPOS_INSTRUMENTO):
                    raise ErrorPago(f"Instrumento {n}: tipo inválido.")
                if not i["importe"] or i["importe"] <= 0:
                    raise ErrorPago(f"Instrumento {n}: el importe tiene que ser mayor que cero.")
                if i["tipo"] == "cheque" and not (i["nro_cheque"] and i["id_chequera"] and i["fecha_cheque"]):
                    raise ErrorPago(f"Instrumento {n}: al cheque le falta la chequera, el número o la fecha.")
                if i["tipo"] != "cheque":
                    i.update(nro_cheque=None, fecha_cheque=None, id_chequera=None, cruzado=0)
                if i["tipo"] == "efectivo" and cuentas[i["id_cuenta"]]["tipo_de_cuenta"] == "B":
                    raise ErrorPago(f"Instrumento {n}: el efectivo sale de una caja, no de un banco.")

        retenciones = calcular_retenciones_orden(conn, id_orden, fecha)
        bruto = float(orden["importe_total"])
        retenido = total_retenciones(retenciones)
        neto = round(bruto - retenido, 2)
        total = round(sum(i["importe"] for i in instrumentos), 2)
        if abs(total - neto) > 0.01:
            raise ErrorPago(f"Los instrumentos suman $ {total:,.2f} y el neto a pagar es $ {neto:,.2f} "
                            f"(orden $ {bruto:,.2f} − retenciones $ {retenido:,.2f}). Puede que las retenciones "
                            "hayan cambiado: revisá la fecha y volvé a armar el pago.")

        with conn.cursor() as cur:
            nro_pago = proximo_numero(cur, "pago_pagos", fecha)
            cur.execute("""INSERT INTO pago_pagos (nro_pago, id_orden, fecha_pago, estado, importe_total, observaciones,
                                                   id_usuario_creacion)
                           VALUES (%s, %s, %s, 'emitido', %s, %s, %s)""",
                        (nro_pago, id_orden, fecha, bruto, obs, id_usuario))
            id_pago = cur.lastrowid
            for i in instrumentos:
                cur.execute("""INSERT INTO pago_pagos_instrumentos
                                 (id_pago, id_cuenta_fondos, tipo_instrumento, importe, nro_cheque, fecha_cheque,
                                  cruzado, id_chequera, cbu_destino, nro_referencia)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            (id_pago, i["id_cuenta"], i["tipo"], i["importe"], i["nro_cheque"], i["fecha_cheque"],
                             i["cruzado"], i["id_chequera"], (i["cbu"] or "")[:22] or None,
                             (i["referencia"] or "")[:100] or None))
            consumir_chequeras(cur, id_pago)
            mf.registrar_pago(cur, id_pago)
            certificados = _registrar_retenciones(cur, id_orden, id_pago, retenciones, fecha, bruto, id_usuario)
            cur.execute(f"""INSERT INTO c_pasivo_aplicacion (id_pago, id_liq_debito, importe_aplicado, fecha, origen,
                                                             observaciones, id_usuario)
                            SELECT %s, d.id_liquidacion, d.importe, %s, 'pago',
                                   CONCAT('Orden ', {sql_nro_orden_visible('o')}), %s
                              FROM pago_ordenes_detalle d JOIN pago_ordenes o ON o.id = d.id_orden
                             WHERE d.id_orden = %s AND d.importe > 0""", (id_pago, fecha, id_usuario, id_orden))
            # «pagado» solo si quedó en cero: con saldo sigue liquidado y vuelve a
            # la lista de impagos por lo que falta.
            cur.execute("""UPDATE me_expedientes e JOIN pago_ordenes_detalle d ON d.id_expediente = e.id
                             JOIN c_pasivo_liquidacion l ON l.id = d.id_liquidacion
                              SET e.estado = 'pagado', e.id_pago = %s
                            WHERE d.id_orden = %s
                              AND l.importe_liquidado - COALESCE((SELECT SUM(a.importe_aplicado)
                                                                   FROM c_pasivo_aplicacion a
                                                                  WHERE a.id_liq_debito = l.id), 0) <= 0.01""",
                        (id_pago, id_orden))
            cur.execute("UPDATE pago_ordenes SET estado = 'pagada' WHERE id = %s", (id_orden,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"id_pago": id_pago, "nro_pago": nro_pago, "retenciones": len(retenciones), "retenido": retenido,
            "neto": neto, "certificados": certificados}


def _registrar_retenciones(cur, id_orden, id_pago, retenciones, fecha, bruto, id_usuario) -> int:
    """Las retenciones del pago y un certificado por proveedor e impuesto."""
    grupos: dict = {}
    for r in retenciones:
        cur.execute("""INSERT INTO pago_retenciones (id_pago, id_orden, id_expediente, id_proveedor, tipo, regimen,
                                                     base_calculo, alicuota, importe, origen_alicuota,
                                                     id_certificado, fecha, id_usuario)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (id_pago, id_orden, r.get("id_expediente"), r["id_proveedor"], r["tipo"], r["regimen"],
                     r["base_calculo"], r["alicuota"], r["importe"], r["origen_alicuota"], r.get("id_certificado"),
                     fecha, id_usuario))
        g = grupos.setdefault((r["id_proveedor"], r["tipo"]), {"regimen": r["regimen"],
                                                              "exencion": r.get("id_certificado"), "lineas": []})
        g["lineas"].append((cur.lastrowid, r))
    if not grupos:
        return 0
    comp = _comprobante_certificado(cur, id_orden, fecha, bruto)
    for (id_prov, tipo), g in grupos.items():
        cur.execute("""SELECT p.cuit, p.razon_social, rt.descripcion AS condicion
                         FROM c_proveedores p LEFT JOIN arca_responsable_tipo rt ON rt.codigo = p.condicion_iva
                        WHERE p.id = %s""", (id_prov,))
        prov = cur.fetchone() or {}
        base = sum(float(r["base_calculo"]) for _, r in g["lineas"])
        monto = sum(float(r["importe"]) for _, r in g["lineas"])
        alic = (sum(float(r["alicuota"]) * float(r["base_calculo"]) for _, r in g["lineas"]) / base) if base else 0
        nro = proximo_certificado(cur, fecha)
        cur.execute("""INSERT INTO pago_retenciones_certificado
                         (nro_certificado, tipo, codigo_regimen, formulario_sire, id_pago, id_orden, id_proveedor,
                          cuit_proveedor, razon_social_proveedor, condicion_fiscal, fecha_emision, periodo_fiscal,
                          base_calculo, alicuota, importe_retenido, comprobante_tipo, comprobante_pv, comprobante_nro,
                          comprobante_fecha, comprobante_importe, comprobante_cae, tiene_exclusion,
                          id_certificado_exencion, id_usuario_creacion)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                               %s, %s, %s)""",
                    (nro, tipo, g["regimen"], _FORMULARIO_SIRE.get(tipo), id_pago, id_orden, id_prov,
                     (prov.get("cuit") or "")[:13] or None, (prov.get("razon_social") or "")[:200],
                     (prov.get("condicion") or "")[:30] or None, fecha, fecha.strftime("%Y%m"),
                     round(base, 2), round(alic, 4), round(monto, 2), *comp,
                     1 if g["exencion"] else 0, g["exencion"], id_usuario))
        id_cert = cur.lastrowid
        ids = [i for i, _ in g["lineas"]]
        cur.execute(f"UPDATE pago_retenciones SET id_certificado_emitido = %s WHERE id IN ({', '.join(['%s'] * len(ids))})",
                    [id_cert] + ids)
    return len(grupos)


# ─────────────────────────────────────────────────────────────────────────────
# La orden entera, para la ficha y el PDF
# ─────────────────────────────────────────────────────────────────────────────

def orden_completa(cur, id_orden: int) -> dict | None:
    cur.execute("""SELECT o.*, u.nombre AS nombre_usuario, ua.nombre AS usuario_anulacion
                     FROM pago_ordenes o
                     LEFT JOIN s_usuarios u ON u.id = o.id_usuario_creacion
                     LEFT JOIN s_usuarios ua ON ua.id = o.id_usuario_anulacion
                    WHERE o.id = %s""", (id_orden,))
    orden = cur.fetchone()
    if not orden:
        return None
    orden["nro_vis"] = nro_orden_visible(orden)
    cur.execute("""SELECT d.*, e.nro_expediente, e.razon_social_emisor, e.cuit_emisor, e.id_proveedor,
                          fa.id AS id_comprobante, fa.numero_completo, fa.fecha_emision, fa.importe_total AS comp_importe,
                          IF(COALESCE(TRIM(fa.ruta_local), '') = '', 0, 1) AS comp_pdf,
                          COALESCE(tc.descripcion, fa.tipo_comprobante) AS tipo_desc,
                          fa.constatacion_resultado, fa.leido_automatico, fa.verificado_visual
                     FROM pago_ordenes_detalle d
                     JOIN me_expedientes e ON e.id = d.id_expediente
                     LEFT JOIN f_comprobantes_arca fa ON fa.id = e.id_comprobante
                     LEFT JOIN arca_tipo_comprobante tc ON tc.codigo = fa.tipo_comprobante
                    WHERE d.id_orden = %s ORDER BY fa.fecha_emision, e.nro_expediente""", (id_orden,))
    orden["detalle"] = list(cur.fetchall())
    emisores = {(d["cuit_emisor"] or "", d["razon_social_emisor"] or "") for d in orden["detalle"]}
    orden["emisor_unico"] = ({"cuit": next(iter(emisores))[0], "razon_social": next(iter(emisores))[1]}
                             if len(emisores) == 1 else None)
    cur.execute("""SELECT ad.*, p.razon_social, p.cuit, r.nombre AS rubro, i.nombre AS imputacion
                     FROM pago_ordenes_anticipo_det ad
                     LEFT JOIN c_proveedores p ON p.id = ad.id_proveedor
                     LEFT JOIN c_rubros_de_pasivo r ON r.id = ad.id_rubro_pasivo
                     LEFT JOIN pago_imputaciones_config i ON i.id = ad.id_imputacion
                    WHERE ad.id_orden = %s ORDER BY ad.id""", (id_orden,))
    orden["detalle_anticipo"] = list(cur.fetchall())
    if not orden["emisor_unico"] and orden["detalle_anticipo"]:
        a = orden["detalle_anticipo"][0]
        orden["emisor_unico"] = {"cuit": a["cuit"], "razon_social": a["razon_social"]}
    cur.execute("""SELECT cd.*, cg.descripcion AS nombre_concepto, mi.descripcion AS nombre_motivo
                     FROM pago_ordenes_concepto_det cd
                     LEFT JOIN c_concepto_de_gastos cg ON cg.id = cd.id_concepto_gasto
                     LEFT JOIN c_motivos_de_ingreso mi ON mi.id = cd.id_motivo_ingreso
                    WHERE cd.id_orden = %s ORDER BY cd.id""", (id_orden,))
    orden["detalle_concepto"] = list(cur.fetchall())
    cur.execute("""SELECT rd.*, r.nro_solicitud, r.fecha_solicitud, r.importe_aprobado
                     FROM pago_ordenes_reintegro_det rd
                     JOIN c_reintegro_afiliados r ON r.id = rd.id_reintegro
                    WHERE rd.id_orden = %s ORDER BY r.nro_solicitud""", (id_orden,))
    orden["detalle_reintegro"] = list(cur.fetchall())
    cur.execute("""SELECT a.*, u.nombre AS nombre_usuario FROM pago_ordenes_aprobacion a
                     LEFT JOIN s_usuarios u ON u.id = a.id_usuario
                    WHERE a.id_orden = %s ORDER BY a.nivel, a.id""", (id_orden,))
    orden["aprobaciones"] = list(cur.fetchall())
    cur.execute("""SELECT p.*, u.nombre AS nombre_usuario,
                          (SELECT COALESCE(SUM(r.importe), 0) FROM pago_retenciones r
                            WHERE r.id_pago = p.id AND COALESCE(r.anulado, 0) = 0) AS retenido
                     FROM pago_pagos p LEFT JOIN s_usuarios u ON u.id = p.id_usuario_creacion
                    WHERE p.id_orden = %s ORDER BY p.id DESC""", (id_orden,))
    orden["pagos"] = list(cur.fetchall())
    for p in orden["pagos"]:
        cur.execute("""SELECT i.*, cf.nombre AS cuenta, b.nombre AS banco
                         FROM pago_pagos_instrumentos i
                         JOIN c_cuentas_de_fondos cf ON cf.id = i.id_cuenta_fondos
                         LEFT JOIN c_codigo_de_banco b ON b.id = cf.c_codigo_de_bancoId
                        WHERE i.id_pago = %s ORDER BY i.id""", (p["id"],))
        p["instrumentos"] = list(cur.fetchall())
    cur.execute("""SELECT r.*, c.nro_certificado, c.id AS id_cert, pr.razon_social AS proveedor
                     FROM pago_retenciones r
                     LEFT JOIN pago_retenciones_certificado c ON c.id = r.id_certificado_emitido
                     LEFT JOIN c_proveedores pr ON pr.id = r.id_proveedor
                    WHERE r.id_orden = %s ORDER BY r.id_pago, r.tipo, r.id""", (id_orden,))
    orden["retenciones"] = list(cur.fetchall())
    orden["pago_vivo"] = next((p for p in orden["pagos"] if p["estado"] != "anulado"), None)
    orden["beneficiarios"] = cbu_beneficiarios(cur, orden)
    return orden
