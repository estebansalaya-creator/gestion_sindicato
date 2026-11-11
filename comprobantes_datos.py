"""
comprobantes_datos.py — Capa de datos de los comprobantes de proveedores y de
la mesa de entradas.

El circuito, igual que en gestion_adm:

    carga del comprobante (f_comprobantes_arca)
      → expediente en la mesa de entradas (me_expedientes + movimientos)
      → liquidación ABIERTA (c_pasivo_liquidacion sin fecha de cierre)
      → auditoría de comprobantes: la cierra y nace la deuda   [paso siguiente]
      → orden de pago → pago

Mientras la liquidación no tenga fecha de cierre no es deuda: no entra en la
cuenta corriente (v_cc_proveedores_movimientos pide fecha_cierre) ni en una
orden de pago (v_expedientes_liquidados_impagos pide estado 'liquidado').

DIFERENCIA CON GESTION_ADM
--------------------------
Allá el comprobante, el expediente y la liquidación se graban en tres
conexiones distintas, y cuando la segunda o la tercera fallaban quedaba un
comprobante sin expediente —«cargado» para la base, fuera de todo circuito—
que hubo que arreglar con un botón aparte. Acá van en UNA transacción
(`registrar_comprobante`): o queda todo o no queda nada.

Y se exige que el emisor sea un proveedor dado de alta: la liquidación necesita
su rubro de pasivo y su concepto de gasto, que salen de la ficha.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import secrets
import shutil
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

import lector_pdf_ocr

# ─────────────────────────────────────────────────────────────────────────────
# Mesa de entradas: estados y movimientos
# ─────────────────────────────────────────────────────────────────────────────

ESTADOS = [
    ("ingresado",   "Ingresado"),
    ("en_revision", "En revisión"),
    ("aprobado",    "Aprobado"),
    ("rechazado",   "Rechazado"),
    ("liquidado",   "Liquidado"),
    ("pagado",      "Pagado"),
    ("reintegro",   "Reintegro"),
    ("archivado",   "Archivado"),
    ("anulado",     "Anulado"),
]
ESTADOS_LABEL = dict(ESTADOS)
ESTADOS_TIPO = {"ingresado": "info", "en_revision": "warn", "aprobado": "ok",
                "rechazado": "danger", "liquidado": "ok", "pagado": "ok", "reintegro": "ok",
                "archivado": "neutro", "anulado": "danger"}
#: Lo que todavía está en la mesa: lo que la bandeja muestra por defecto.
ESTADOS_ABIERTOS = ("ingresado", "en_revision", "aprobado", "rechazado")
#: Ya pasó a la parte contable: su estado lo maneja el circuito de pagos.
#: `reintegro`: un reintegro o subsidio de AEDA (importar_aeda_cc_afiliados.py),
#: sin comprobante; se paga desde el circuito de reintegros.
ESTADOS_CONTABLES = ("liquidado", "pagado", "reintegro")

TIPOS_MOV = [
    ("derivacion",  "Derivación"),
    ("observacion", "Observación"),
    ("aprobacion",  "Aprobación"),
    ("rechazo",     "Rechazo"),
    ("archivo",     "Archivo"),
    ("nota",        "Nota"),
]
TIPOS_MOV_LABEL = dict(TIPOS_MOV) | {"ingreso": "Ingreso", "anulacion": "Anulación",
                                     "pdf": "Comprobante PDF"}
#: El estado al que lleva cada movimiento. None: no lo cambia.
ESTADO_RESULTANTE = {"derivacion": "en_revision", "observacion": None,
                     "aprobacion": "aprobado", "rechazo": "rechazado",
                     "archivo": "archivado", "nota": None}
#: Movimientos que exigen escribir algo: sin el motivo no se entiende después.
CON_TEXTO = ("observacion", "rechazo", "nota")

AMBITO_EXPEDIENTE = "me_expedientes"
PREFIJO_EXPEDIENTE = "EXP"


# ─────────────────────────────────────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────────────────────────────────────

def solo_digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def fecha(v) -> datetime.date | None:
    """dd/mm/aaaa, aaaa-mm-dd o un date → date. Lo demás → None."""
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    s = (v or "").strip()[:10]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def importe(v) -> Decimal | None:
    """'1.234,56', '1234.56', '1234,5' → Decimal. Vacío → 0. Basura → None."""
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v)).quantize(Decimal("0.01"))
    s = str(v or "").strip().replace("$", "").replace(" ", "")
    if not s:
        return Decimal("0.00")
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def institucion(cur) -> dict:
    cur.execute("SELECT nombre, cuit FROM s_institucion ORDER BY id LIMIT 1")
    f = cur.fetchone() or {}
    return {"nombre": (f.get("nombre") or "").strip(), "cuit": solo_digitos(f.get("cuit"))}


def proveedor_por_cuit(cur, cuit) -> dict | None:
    cur.execute("""SELECT p.id, p.cuit, p.razon_social, p.nombre_fantasia, p.activo,
                          p.condicion_iva, rt.descripcion AS condicion_iva_txt,
                          p.id_area_destino, p.id_usuario_destino
                     FROM c_proveedores p
                     LEFT JOIN arca_responsable_tipo rt ON rt.codigo = p.condicion_iva
                    WHERE p.cuit = %s LIMIT 1""", (solo_digitos(cuit),))
    return cur.fetchone()


def tipos_comprobante(cur) -> list[dict]:
    cur.execute("SELECT codigo, descripcion FROM arca_tipo_comprobante WHERE activo = 1 ORDER BY codigo")
    return cur.fetchall()


def es_credito(cur, tipo) -> bool:
    """¿Nota de crédito? El TIPO manda el signo, no quien carga (ver
    gestion_adm/comprobante_signo.py). Se clasifica por el nombre oficial."""
    if not tipo:
        return False
    cur.execute("SELECT descripcion FROM arca_tipo_comprobante WHERE codigo = LPAD(%s, 3, '0')",
                (str(tipo),))
    f = cur.fetchone()
    return bool(f and re.search(r"cr[eé]dito", f["descripcion"] or "", re.I)
                and re.search(r"nota", f["descripcion"] or "", re.I))


def nombre_pdf(cuit, tipo, punto_venta, numero) -> str:
    """`CUIT_tipo_pv_nro.pdf` sin ceros a la izquierda: el nombre de ARCA."""
    n = lambda v: int(str(v).lstrip("0") or 0)                   # noqa: E731
    return f"{solo_digitos(cuit)}_{n(tipo)}_{n(punto_venta)}_{n(numero)}.pdf"


# ─────────────────────────────────────────────────────────────────────────────
# Imputación (de gestion_adm/auditoria_comprobantes.py)
# ─────────────────────────────────────────────────────────────────────────────

def opciones_de_imputacion(cur, id_proveedor) -> dict:
    """Rubros de pasivo y conceptos de gasto activos de la ficha del proveedor."""
    if not id_proveedor:
        return {"rubros": [], "conceptos": []}
    cur.execute("""SELECT cp.id_rubro_pasivo AS id, r.nombre, cp.predeterminada
                     FROM c_proveedores_cuentas_pasivo cp
                     JOIN c_rubros_de_pasivo r ON r.id = cp.id_rubro_pasivo
                    WHERE cp.id_proveedor = %s AND cp.activa = 1
                    ORDER BY cp.predeterminada DESC, r.nombre""", (id_proveedor,))
    rubros = cur.fetchall()
    cur.execute("""SELECT cg.id_concepto_gasto AS id, g.descripcion, cg.predeterminada
                     FROM c_proveedores_cuentas_gasto cg
                     JOIN c_concepto_de_gastos g ON g.id = cg.id_concepto_gasto
                    WHERE cg.id_proveedor = %s AND cg.activa = 1
                    ORDER BY cg.predeterminada DESC, g.descripcion""", (id_proveedor,))
    return {"rubros": rubros, "conceptos": cur.fetchall()}


def _elegida(opciones: list[dict], elegido):
    """La elegida si es una de las opciones; si no, la única o la predeterminada."""
    ids = {o["id"] for o in opciones}
    if elegido and int(elegido) in ids:
        return int(elegido)
    if len(opciones) == 1:
        return opciones[0]["id"]
    pred = [o["id"] for o in opciones if o.get("predeterminada")]
    return pred[0] if len(pred) == 1 else None


def errores_de_imputacion(cur, id_proveedor, id_rubro, id_concepto) -> list[str]:
    """
    Con más de un rubro o concepto activo hay que elegir: la predeterminada es
    una sugerencia y cuál es cada factura lo sabe el que la carga. Lo elegido
    tiene que ser una de las opciones activas (el formulario se toca con F12).
    Sin ninguna, la liquidación no se puede imputar.
    """
    op = opciones_de_imputacion(cur, id_proveedor)
    err = []
    for clave, elegido, rotulo, art in (("rubros", id_rubro, "rubro de pasivo", "un"),
                                        ("conceptos", id_concepto, "concepto de gasto", "un")):
        lista = op[clave]
        ids = {o["id"] for o in lista}
        if not lista:
            err.append(f"El proveedor no tiene ningún {rotulo} activo: agregalo en su ficha "
                       "(Proveedores → Cuentas contables).")
        elif len(lista) > 1 and not elegido:
            err.append(f"El proveedor tiene más de {art} {rotulo}: elegí a cuál corresponde la factura.")
        elif elegido and int(elegido) not in ids:
            err.append(f"El {rotulo} elegido no es uno de los del proveedor.")
    return err


# ─────────────────────────────────────────────────────────────────────────────
# Duplicados
# ─────────────────────────────────────────────────────────────────────────────

def duplicado(cur, cuit, tipo, punto_venta, numero, cae=None) -> str | None:
    """El mensaje si el comprobante ya está cargado; None si no."""
    if cae:
        cur.execute("SELECT id, numero_completo, cuit_emisor FROM f_comprobantes_arca WHERE cae = %s LIMIT 1",
                    (solo_digitos(cae),))
        f = cur.fetchone()
        if f:
            return (f"Ese comprobante ya está cargado: el CAE {solo_digitos(cae)} es del "
                    f"{f['numero_completo']} del CUIT {f['cuit_emisor']}.")
    try:
        pv, nro = int(solo_digitos(punto_venta) or 0), int(solo_digitos(numero) or 0)
    except ValueError:
        return None
    cur.execute("""SELECT c.id, c.numero_completo, e.nro_expediente
                     FROM f_comprobantes_arca c
                     LEFT JOIN me_expedientes e ON e.id_comprobante = c.id
                    WHERE c.cuit_emisor = %s AND c.tipo_comprobante = LPAD(%s, 3, '0')
                      AND CAST(c.punto_de_venta AS UNSIGNED) = %s
                      AND CAST(c.numero AS UNSIGNED) = %s LIMIT 1""",
                (solo_digitos(cuit), str(tipo or ""), pv, nro))
    f = cur.fetchone()
    if f:
        return (f"Ese comprobante ya está cargado: {f['numero_completo']} del CUIT "
                f"{solo_digitos(cuit)}" + (f", expediente {f['nro_expediente']}." if f["nro_expediente"] else "."))
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Validación del formulario de confirmación
# ─────────────────────────────────────────────────────────────────────────────

CAMPOS_IMPORTE = ("importe_neto_gravado", "importe_neto_no_grav", "importe_exento",
                  "importe_iva", "importe_otros", "importe_total")


def validar(cur, d: dict) -> tuple[dict, list[str]]:
    """
    Normaliza el comprobante que llega del formulario y devuelve
    (valores para la base, errores). `d` trae los campos como texto.
    """
    err = []
    v = {
        "cuit_emisor":    solo_digitos(d.get("cuit_emisor")),
        "tipo_comprobante": solo_digitos(d.get("tipo_comprobante")).zfill(3) if solo_digitos(d.get("tipo_comprobante")) else "",
        "punto_de_venta": solo_digitos(d.get("punto_de_venta")).zfill(5) if solo_digitos(d.get("punto_de_venta")) else "",
        "numero":         solo_digitos(d.get("numero")).zfill(8) if solo_digitos(d.get("numero")) else "",
        "fecha_emision":  fecha(d.get("fecha_emision")),
        "fecha_vto_pago": fecha(d.get("fecha_vto_pago")),
        "periodo_desde":  fecha(d.get("periodo_desde")),
        "periodo_hasta":  fecha(d.get("periodo_hasta")),
        "cae":            solo_digitos(d.get("cae")) or None,
        "fecha_vto_cae":  fecha(d.get("fecha_vto_cae")),
        "moneda":         (d.get("moneda") or "PES").strip().upper()[:3] or "PES",
        "tipo_de_cambio": importe(d.get("tipo_de_cambio") or "1") or Decimal("1"),
        "condicion_iva_emisor":   (d.get("condicion_iva_emisor") or "").strip()[:50] or None,
        "condicion_iva_receptor": (d.get("condicion_iva_receptor") or "").strip()[:50] or None,
    }
    for c in CAMPOS_IMPORTE:
        v[c] = importe(d.get(c))
        if v[c] is None:
            err.append(f"El importe «{c.replace('importe_', '').replace('_', ' ')}» no es un número.")
            v[c] = Decimal("0")

    if len(v["cuit_emisor"]) != 11:
        err.append("El CUIT del emisor tiene que tener 11 dígitos.")
    if not v["tipo_comprobante"]:
        err.append("Falta el tipo de comprobante.")
    else:
        cur.execute("SELECT 1 FROM arca_tipo_comprobante WHERE codigo = %s", (v["tipo_comprobante"],))
        if not cur.fetchone():
            err.append(f"El tipo de comprobante {v['tipo_comprobante']} no es un código de ARCA.")
    if not v["punto_de_venta"] or not v["numero"]:
        err.append("Faltan el punto de venta o el número.")
    elif len(v["punto_de_venta"]) > 5 or len(v["numero"]) > 8:
        err.append("El punto de venta va hasta 5 dígitos y el número hasta 8.")
    if not v["fecha_emision"]:
        err.append("La fecha de emisión no es válida.")
    elif v["fecha_emision"] > datetime.date.today():
        err.append("La fecha de emisión es posterior a hoy.")
    if v["importe_total"] <= 0:
        err.append("El importe total tiene que ser mayor que cero. Una nota de crédito se carga "
                   "en positivo: el tipo dice que resta.")
    if v["cae"] and len(v["cae"]) != 14:
        err.append("El CAE tiene 14 dígitos.")

    # Los componentes, si se cargaron, tienen que cerrar con el total: es la
    # misma cuenta que exige ARCA para autorizar el comprobante.
    partes = sum(v[c] for c in CAMPOS_IMPORTE[:-1])
    if partes and abs(partes - v["importe_total"]) > Decimal("0.05"):
        err.append(f"Los importes no cierran: neto, no gravado, exento, IVA y otros suman "
                   f"{partes:,.2f} y el total es {v['importe_total']:,.2f}.".replace(",", "X")
                   .replace(".", ",").replace("X", "."))

    # El período decide a qué mes va el gasto: es obligatorio y no puede ser
    # de un mes posterior al de la factura (gestion_adm, mismas reglas).
    pd, ph, fe = v["periodo_desde"], v["periodo_hasta"], v["fecha_emision"]
    mes = lambda x: x.year * 12 + x.month                          # noqa: E731
    if not pd:
        err.append("El período facturado es obligatorio. Si el comprobante no lo declara —porque "
                   "no es un servicio— corresponde el mes de la fecha de emisión.")
    elif fe and mes(pd) > mes(fe):
        err.append(f"El período facturado ({pd:%m/%Y}) es posterior al del comprobante ({fe:%m/%Y}).")
    if pd and ph and ph < pd:
        err.append("El período facturado termina antes de empezar.")
    if ph and fe and mes(ph) > mes(fe):
        err.append(f"El período facturado hasta ({ph:%m/%Y}) es de un mes posterior al del comprobante.")
    return v, err


# ─────────────────────────────────────────────────────────────────────────────
# Grabación: comprobante + expediente + liquidación abierta, en una transacción
# ─────────────────────────────────────────────────────────────────────────────

def _proximo(cur, ambito: str, periodo: str, minimo: int = 0) -> int:
    cur.execute("""INSERT INTO c_numeradores (ambito, periodo, ultimo)
                   VALUES (%s, %s, LAST_INSERT_ID(%s))
                   ON DUPLICATE KEY UPDATE ultimo = LAST_INSERT_ID(ultimo + 1)""",
                (ambito, periodo, minimo + 1))
    cur.execute("SELECT LAST_INSERT_ID() AS n")
    return int(cur.fetchone()["n"])


def nuevo_nro_expediente(cur, anio: int) -> str:
    """EXP-AAAA-NNNNNN desde c_numeradores; el mínimo cubre lo cargado antes."""
    cur.execute("""SELECT COALESCE(MAX(CAST(SUBSTRING_INDEX(nro_expediente, '-', -1) AS UNSIGNED)), 0) AS m
                     FROM me_expedientes WHERE anio = %s""", (anio,))
    minimo = int(cur.fetchone()["m"] or 0)
    return f"{PREFIJO_EXPEDIENTE}-{anio}-{_proximo(cur, AMBITO_EXPEDIENTE, str(anio), minimo):06d}"


def movimiento(cur, id_expediente, tipo, estado, usuario_id, obs=None,
               id_area=None, id_usuario_destino=None) -> None:
    cur.execute("""INSERT INTO me_expediente_movimientos
                     (id_expediente, tipo, estado_resultante, usuario_id,
                      id_area_destino, id_usuario_destino, observaciones)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (id_expediente, tipo, estado, usuario_id or None, id_area or None,
                 id_usuario_destino or None, obs))


def marcar_verificacion_mis(cur, ids=None) -> int:
    """
    Lo vinculado con Mis Comprobantes y que coincide en CUIT, tipo, punto de
    venta, número, importe y CAE queda con constatación 'A': ARCA lo informa
    como recibido (gestion_adm/verificacion_arca.py). No pisa un rechazo.
    """
    sql = """UPDATE f_comprobantes_arca c
               JOIN f_mis_comprobantes mc ON mc.id_comprobante = c.id
                SET c.constatacion_resultado = 'A', c.constatacion_fch = NOW(),
                    c.constatacion_obs = JSON_OBJECT('origen', 'mis_comprobantes', 'detalle',
                        'Informado por ARCA en Mis Comprobantes: mismo CUIT, tipo, punto de venta, número, importe y CAE.')
              WHERE COALESCE(c.constatacion_resultado, '') NOT IN ('A', 'R')
                AND mc.cuit_emisor = c.cuit_emisor
                AND CAST(mc.tipo_comprobante AS UNSIGNED) = CAST(c.tipo_comprobante AS UNSIGNED)
                AND CAST(mc.punto_de_venta AS UNSIGNED) = CAST(c.punto_de_venta AS UNSIGNED)
                AND CAST(mc.numero AS UNSIGNED) = CAST(c.numero AS UNSIGNED)
                AND ABS(mc.importe_total - c.importe_total) <= 0.01
                AND (COALESCE(mc.cae, '') = '' OR COALESCE(c.cae, '') = '' OR mc.cae = c.cae)"""
    params = []
    if ids is not None:
        ids = [int(i) for i in ids if i]
        if not ids:
            return 0
        sql += f" AND c.id IN ({', '.join(['%s'] * len(ids))})"
        params = ids
    cur.execute(sql, params)
    return cur.rowcount or 0


def vincular_mis(cur) -> int:
    """Une cada fila de Mis Comprobantes con su comprobante cargado."""
    cur.execute("""UPDATE f_mis_comprobantes m
                     JOIN f_comprobantes_arca f
                       ON f.cuit_emisor = m.cuit_emisor
                      AND CAST(f.tipo_comprobante AS UNSIGNED) = CAST(m.tipo_comprobante AS UNSIGNED)
                      AND CAST(f.punto_de_venta AS UNSIGNED) = CAST(m.punto_de_venta AS UNSIGNED)
                      AND CAST(f.numero AS UNSIGNED) = CAST(m.numero AS UNSIGNED)
                      SET m.id_comprobante = f.id
                    WHERE m.id_comprobante IS NULL""")
    return cur.rowcount or 0


def vincular_mis_por_numero(cur) -> list[dict]:
    """
    Segunda vuelta de `vincular_mis`, para el comprobante que entró con otro
    punto de venta: `adm_pasivo.prefijo` de AEDA es varchar(4) y un punto de
    venta tipeado con cinco dígitos perdió el último («00011» → «0001»), y así lo
    trajo `importar_aeda_cc_proveedores.py`. Sin esto, ARCA lo informa, no
    vincula y figura pendiente de cargar estando cargado.

    Mismo CUIT, tipo, número e importe; otro punto de venta; un único candidato
    que no esté vinculado a otra fila; CAE igual si los dos lo tienen. No toca el
    comprobante (y `marcar_verificacion_mis`, que pide el punto de venta igual,
    no lo marca). Devuelve los vínculos hechos.
    """
    cur.execute("""
        SELECT m.id AS id_mis, MIN(f.id) AS id_comprobante, m.cuit_emisor, m.tipo_comprobante,
               m.punto_de_venta AS pv_arca, MIN(f.punto_de_venta) AS pv_cargado, m.numero, m.importe_total
          FROM f_mis_comprobantes m
          JOIN f_comprobantes_arca f
            ON f.cuit_emisor = m.cuit_emisor
           AND CAST(f.tipo_comprobante AS UNSIGNED) = CAST(m.tipo_comprobante AS UNSIGNED)
           AND CAST(f.numero AS UNSIGNED) = CAST(m.numero AS UNSIGNED)
           AND CAST(f.punto_de_venta AS UNSIGNED) <> CAST(m.punto_de_venta AS UNSIGNED)
           AND ABS(f.importe_total - m.importe_total) <= 0.01
           AND (COALESCE(f.cae, '') = '' OR COALESCE(m.cae, '') = '' OR f.cae = m.cae)
         WHERE m.id_comprobante IS NULL
           AND NOT EXISTS (SELECT 1 FROM f_mis_comprobantes otro WHERE otro.id_comprobante = f.id)
         GROUP BY m.id, m.cuit_emisor, m.tipo_comprobante, m.punto_de_venta, m.numero, m.importe_total
        HAVING COUNT(*) = 1""")
    # Dos filas de ARCA que apunten al mismo comprobante no se vinculan: no se
    # sabe cuál es.
    usos = {}
    for p in cur.fetchall():
        usos.setdefault(p["id_comprobante"], []).append(p)
    hechos = []
    for grupo in usos.values():
        if len(grupo) == 1:
            p = grupo[0]
            cur.execute("UPDATE f_mis_comprobantes SET id_comprobante = %s WHERE id = %s AND id_comprobante IS NULL",
                        (p["id_comprobante"], p["id_mis"]))
            hechos.append(p)
    return hechos


def registrar_comprobante(cur, v: dict, prov: dict, inst: dict, usuario_id,
                          id_rubro, id_concepto, constatacion: dict | None,
                          asunto: str | None = None) -> dict:
    """
    Graba el comprobante, su expediente con el movimiento de ingreso y la
    liquidación abierta. El que llama abre y confirma la transacción.
    Devuelve {"id_comprobante", "id_expediente", "nro_expediente"}.
    """
    cst = constatacion or {}
    cur.execute("""
        INSERT INTO f_comprobantes_arca
          (id_proveedor, cuit_emisor, razon_social_emisor, condicion_iva_emisor,
           cuit_receptor, razon_social_receptor, condicion_iva_receptor,
           tipo_comprobante, punto_de_venta, numero, fecha_emision, fecha_vto_pago,
           periodo_desde, periodo_hasta,
           importe_neto_gravado, importe_neto_no_grav, importe_exento,
           importe_iva, importe_otros, importe_total, moneda, tipo_de_cambio,
           cae, fecha_vto_cae, constatacion_resultado, constatacion_fch, constatacion_obs,
           estado, usuario_id)
        VALUES (%s,%s,%s,%s, %s,%s,%s, %s,%s,%s,%s,%s, %s,%s, %s,%s,%s, %s,%s,%s,%s,%s,
                %s,%s,%s,IF(%s IS NULL, NULL, NOW()),%s, 'ingresado', %s)
    """, (prov["id"], v["cuit_emisor"], prov["razon_social"][:200],
          v["condicion_iva_emisor"] or prov.get("condicion_iva_txt"),
          inst["cuit"] or None, inst["nombre"][:200] or None, v["condicion_iva_receptor"],
          v["tipo_comprobante"], v["punto_de_venta"], v["numero"], v["fecha_emision"], v["fecha_vto_pago"],
          v["periodo_desde"], v["periodo_hasta"],
          v["importe_neto_gravado"], v["importe_neto_no_grav"], v["importe_exento"],
          v["importe_iva"], v["importe_otros"], v["importe_total"], v["moneda"], v["tipo_de_cambio"],
          v["cae"], v["fecha_vto_cae"], cst.get("resultado") or None, cst.get("resultado") or None,
          json.dumps(cst.get("obs"), ensure_ascii=False) if cst.get("obs") else None,
          usuario_id or None))
    id_cmp = cur.lastrowid

    anio = datetime.date.today().year
    nro = nuevo_nro_expediente(cur, anio)
    cur.execute("SELECT descripcion FROM arca_tipo_comprobante WHERE codigo = %s", (v["tipo_comprobante"],))
    tipo_txt = (cur.fetchone() or {}).get("descripcion") or f"Comprobante {v['tipo_comprobante']}"
    asunto = asunto or f"{tipo_txt} {v['punto_de_venta']}-{v['numero']}"
    cur.execute("""
        INSERT INTO me_expedientes
          (nro_expediente, anio, id_comprobante, id_proveedor, cuit_emisor, razon_social_emisor,
           importe_total, moneda, id_area_destino, id_usuario_destino, estado, asunto, usuario_creacion)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ingresado',%s,%s)
    """, (nro, anio, id_cmp, prov["id"], v["cuit_emisor"], prov["razon_social"][:200],
          v["importe_total"], v["moneda"], prov.get("id_area_destino"), prov.get("id_usuario_destino"),
          asunto[:500], usuario_id or None))
    id_exp = cur.lastrowid
    movimiento(cur, id_exp, "ingreso", "ingresado", usuario_id, "Ingreso por carga del comprobante.",
               prov.get("id_area_destino"), prov.get("id_usuario_destino"))

    preliquidar(cur, id_exp, v, prov["id"], usuario_id, id_rubro, id_concepto)

    vincular_mis(cur)
    marcar_verificacion_mis(cur, [id_cmp])
    return {"id_comprobante": id_cmp, "id_expediente": id_exp, "nro_expediente": nro}


def preliquidar(cur, id_expediente, v, id_proveedor, usuario_id, id_rubro, id_concepto) -> int:
    """
    La liquidación abierta del expediente (gestion_adm/auditoria_comprobantes.
    preliquidar): sin fecha de cierre y con el expediente en «ingresado», así
    que todavía no es deuda. El signo lo da el tipo: una nota de crédito resta.
    """
    op = opciones_de_imputacion(cur, id_proveedor)
    rubro = _elegida(op["rubros"], id_rubro)
    concepto = _elegida(op["conceptos"], id_concepto)
    if not rubro or not concepto:
        raise ValueError("El proveedor no tiene imputación: falta el rubro de pasivo o el concepto de gasto.")
    total = Decimal(str(v["importe_total"]))
    total = -abs(total) if es_credito(cur, v["tipo_comprobante"]) else abs(total)
    periodo = (v["periodo_desde"] or v["fecha_emision"]).strftime("%Y%m")
    cur.execute("""INSERT INTO c_pasivo_liquidacion
                     (fecha_cierre, periodo, importe_liquidado, importe_debitado, comentario,
                      id_expediente, id_usuario, id_rubro_pasivo)
                   VALUES (NULL, %s, %s, 0, %s, %s, %s, %s)""",
                (periodo, total, "Propuesta automática al cargar el comprobante. Pendiente de auditoría.",
                 id_expediente, usuario_id or 0, rubro))
    id_liq = cur.lastrowid
    cur.execute("""INSERT INTO c_pasivo_liquidacion_detalle
                     (id_pasivo_liquidacion, id_rubro_pasivo, id_concepto_liquidacion,
                      importe_liquidado, importe_debitado, fecha_devengado, comentario, id_usuario)
                   VALUES (%s, %s, %s, %s, 0, NOW(), 'Propuesta automática.', %s)""",
                (id_liq, rubro, concepto, total, usuario_id or 0))
    movimiento(cur, id_expediente, "nota", "ingresado", usuario_id,
               "Se armó la liquidación pendiente de auditoría.")
    return id_liq


# ─────────────────────────────────────────────────────────────────────────────
# PDFs: temporal mientras se confirma, definitivo al grabar
# ─────────────────────────────────────────────────────────────────────────────

RE_TOKEN = re.compile(r"^[0-9a-f]{32}$")


def base_adjuntos() -> Path:
    return Path(os.getenv("SIND_ADJUNTOS") or Path(__file__).with_name("adjuntos"))


def _tmp() -> Path:
    d = base_adjuntos() / "tmp_comprobantes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def guardar_tmp(contenido: bytes) -> str:
    """Guarda el PDF hasta que se confirme la carga. Devuelve su ficha (32 hex):
    al formulario viaja la ficha, nunca una ruta."""
    d = _tmp()
    limite = time.time() - 2 * 86400
    for viejo in d.glob("*.pdf"):          # los que quedaron de cargas abandonadas
        try:
            if viejo.stat().st_mtime < limite:
                viejo.unlink()
        except OSError:
            pass
    ficha = secrets.token_hex(16)
    (d / f"{ficha}.pdf").write_bytes(contenido)
    return ficha


def ruta_tmp(ficha: str) -> Path | None:
    if not ficha or not RE_TOKEN.match(ficha):
        return None
    p = _tmp() / f"{ficha}.pdf"
    return p if p.is_file() else None


def archivar_pdf(origen: Path, fecha_emision: datetime.date, nombre: str) -> str:
    """Copia el PDF a comprobantes/AAAAMM/ y devuelve la ruta RELATIVA a la base."""
    rel = Path("comprobantes") / fecha_emision.strftime("%Y%m") / nombre
    destino = base_adjuntos() / rel
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(origen, destino)
    return rel.as_posix()


def ruta_real(ruta: str | None) -> Path | None:
    """El archivo de un comprobante. Relativa a la base; una que se escape con
    `..` no se sirve."""
    if not ruta:
        return None
    p = Path(ruta)
    if not p.is_absolute():
        base = base_adjuntos().resolve()
        p = (base / p).resolve()
        if base not in p.parents:
            return None
    return p if p.is_file() else None


def cotejar(ruta: Path | None, v: dict) -> tuple[bool, str]:
    """¿El PDF dice lo mismo que los datos? (gestion_adm: leido_automatico)."""
    if not ruta:
        return False, ""
    return lector_pdf_ocr.cotejar_pdf(str(ruta), v["cuit_emisor"], v["tipo_comprobante"],
                                      v["punto_de_venta"], v["numero"], v["importe_total"])


# ─────────────────────────────────────────────────────────────────────────────
# Mesa: movimientos y anulación
# ─────────────────────────────────────────────────────────────────────────────

def mover(cur, id_expediente, tipo, obs, id_area, id_usuario_destino, usuario_id) -> str | None:
    """Registra un movimiento. Devuelve el error, o None."""
    if tipo not in ESTADO_RESULTANTE:
        return "Elegí el tipo de movimiento."
    if tipo in CON_TEXTO and not obs:
        return f"La {TIPOS_MOV_LABEL[tipo].lower()} necesita un texto: es lo que va a explicar el movimiento."
    if tipo == "derivacion" and not (id_area or id_usuario_destino):
        return "Elegí a qué área o a qué persona se deriva."
    cur.execute("SELECT estado FROM me_expedientes WHERE id = %s FOR UPDATE", (id_expediente,))
    e = cur.fetchone()
    if not e:
        return "El expediente no existe."
    actual = e["estado"]
    if actual == "anulado" and tipo not in ("nota", "observacion"):
        return "El expediente está anulado: solo admite notas."
    if tipo != "derivacion":
        id_area = id_usuario_destino = None      # el formulario manda el destino actual igual
    nuevo = ESTADO_RESULTANTE[tipo]
    # Liquidado o pagado ya pasó a la parte contable: el movimiento queda en la
    # historia pero el estado no retrocede.
    resultante = actual if (actual in ESTADOS_CONTABLES or not nuevo) else nuevo
    movimiento(cur, id_expediente, tipo, resultante, usuario_id, obs, id_area, id_usuario_destino)
    sets, params = ["estado = %s", "actualizado = NOW()"], [resultante]
    if tipo == "derivacion":
        sets += ["id_area_destino = %s", "id_usuario_destino = %s"]
        params += [id_area or None, id_usuario_destino or None]
    cur.execute(f"UPDATE me_expedientes SET {', '.join(sets)} WHERE id = %s", params + [id_expediente])
    return None


def motivos_para_no_anular(cur, id_expediente) -> list[str]:
    cur.execute("""SELECT e.estado, e.id_orden_pago, e.id_pago,
                          (SELECT COUNT(*) FROM c_pasivo_liquidacion l
                            WHERE l.id_expediente = e.id AND l.fecha_cierre IS NOT NULL) AS cerradas,
                          (SELECT COUNT(*) FROM pago_ordenes_detalle d
                            WHERE d.id_expediente = e.id) AS en_ordenes
                     FROM me_expedientes e WHERE e.id = %s""", (id_expediente,))
    x = cur.fetchone()
    if not x:
        return ["El expediente no existe."]
    m = []
    if x["estado"] == "anulado":
        m.append("Ya está anulado.")
    if x["cerradas"] or x["estado"] in ESTADOS_CONTABLES:
        m.append("La liquidación ya fue aprobada: es deuda exigible. Lo que corresponde es una nota de crédito.")
    if x["en_ordenes"] or x["id_orden_pago"] or x["id_pago"]:
        m.append("Está en una orden de pago.")
    return m


def anular(cur, id_expediente, motivo, usuario_id) -> str | None:
    """
    Anula el expediente y su comprobante. No borra la historia: el expediente
    queda «anulado» con motivo, fecha y usuario, y el comprobante también, para
    que no vuelva a aparecer como pendiente. Lo único que se saca es la
    liquidación abierta, que es un estado de trabajo (gestion_adm, anular).
    """
    motivo = (motivo or "").strip()
    if len(motivo) < 5:
        return "Hace falta un motivo: es lo único que va a explicar la anulación dentro de seis meses."
    imp = motivos_para_no_anular(cur, id_expediente)
    if imp:
        return " ".join(imp)
    cur.execute("SELECT id_comprobante FROM me_expedientes WHERE id = %s FOR UPDATE", (id_expediente,))
    x = cur.fetchone()
    cur.execute("""DELETE d FROM c_pasivo_liquidacion_detalle d
                     JOIN c_pasivo_liquidacion l ON l.id = d.id_pasivo_liquidacion
                    WHERE l.id_expediente = %s AND l.fecha_cierre IS NULL""", (id_expediente,))
    cur.execute("DELETE FROM c_pasivo_liquidacion WHERE id_expediente = %s AND fecha_cierre IS NULL",
                (id_expediente,))
    cur.execute("""UPDATE me_expedientes SET estado = 'anulado', motivo_anulacion = %s,
                          fecha_anulacion = NOW(), id_usuario_anulacion = %s, actualizado = NOW()
                    WHERE id = %s""", (motivo[:400], usuario_id or None, id_expediente))
    if x and x["id_comprobante"]:
        cur.execute("UPDATE f_comprobantes_arca SET estado = 'anulado' WHERE id = %s", (x["id_comprobante"],))
    movimiento(cur, id_expediente, "anulacion", "anulado", usuario_id, motivo)
    return None


def puede_cambiar_pdf(cur, id_expediente) -> tuple[bool, str]:
    """El PDF se reemplaza mientras la liquidación esté abierta y el que hay no
    se haya confirmado como el del comprobante (gestion_adm)."""
    cur.execute("""SELECT e.estado, e.id_comprobante, c.leido_automatico, c.verificado_visual, c.ruta_local,
                          (SELECT COUNT(*) FROM c_pasivo_liquidacion l
                            WHERE l.id_expediente = e.id AND l.fecha_cierre IS NOT NULL) AS cerradas
                     FROM me_expedientes e
                     LEFT JOIN f_comprobantes_arca c ON c.id = e.id_comprobante
                    WHERE e.id = %s""", (id_expediente,))
    x = cur.fetchone()
    if not x or not x["id_comprobante"]:
        return False, "El expediente no tiene comprobante."
    if x["estado"] == "anulado":
        return False, "El expediente está anulado."
    if x["leido_automatico"] and x["ruta_local"]:
        return False, "El PDF coincide con los datos del comprobante: es el que corresponde."
    if x["verificado_visual"] and x["ruta_local"]:
        return False, "Una persona verificó que el PDF es el del comprobante."
    if x["cerradas"]:
        return False, "La liquidación ya fue aprobada: el PDF es el respaldo de lo aprobado."
    return True, ""
