"""
conciliacion.py — Tesorería › Conciliación Bancaria (menú 72) y
Clasificación de Conceptos Bancarios (menú 73).

Portado de `gestion_adm/tesoreria_routes.py` (conc_*) con el sistema de
estilos de acá:

    /tesoreria/conc                              conciliaciones: ?cuenta, ?cerradas=1
    /tesoreria/conc/nueva                        POST
    /tesoreria/conc/saldo_inicial                JSON: con qué saldo arranca (?cuenta, ?desde, ?hasta)
    /tesoreria/conc/<id>                         el detalle: extracto contra libro; ?anteriores=1
    /tesoreria/conc/<id>/vincular                POST  ext=…&dc=…[&observaciones]
    /tesoreria/conc/<id>/sugeridos               POST  par=<ext>:<dc> …
    /tesoreria/conc/<id>/desvincular             POST  grupo
    /tesoreria/conc/<id>/excepcion               POST  ext=…&observaciones
    /tesoreria/conc/<id>/excepcion/quitar        POST  item
    /tesoreria/conc/<id>/generar                 POST  clave=…  (los comprobantes de los conceptos clasificados)
    /tesoreria/conc/<id>/saldo_inicial           POST
    /tesoreria/conc/<id>/cerrar                  POST  saldo_banco
    /tesoreria/conc/<id>/reabrir                 POST  (Administrador)
    /tesoreria/conc/<id>/eliminar                POST  (sin nada conciliado)
    /tesoreria/conc/clasificar                   conceptos del extracto: ?cuenta, ?desde, ?hasta
    /tesoreria/conc/clasificar/guardar           POST JSON
    /tesoreria/conc/clasificar/quitar            POST JSON

LOS DOS LADOS
-------------
Extracto: `c_extractos_bancarios`, lo que informó el banco (extractos.py).
Libro: `c_debitos_creditos_bancarios`, un renglón por instrumento de banco
(cheque, transferencia, depósito) que escribe `movimientos_fondos.py` junto
con el libro de fondos. Va con la óptica del banco —crédito es plata que
entra— para comparar columna contra columna. Un pago con seis cheques es UN
renglón del libro de fondos y SEIS acá: el banco los debita en seis días.

Conciliar es formar un GRUPO (`conciliacion_grupos`): uno o más renglones del
extracto (`conciliacion_items`, estado «conciliado») contra uno o más del libro
(`conciliacion_comprobantes.id_debito_credito`). Uno contra uno es un grupo de
dos. Una excepción es un renglón del extracto que se da por explicado sin
contraparte en el libro (`conciliacion_items` estado «excepcion», con motivo).

QUE CAMBIA RESPECTO DE GESTION_ADM
- El lado libro es el instrumento (`c_debitos_creditos_bancarios`), no el
  renglón del libro de fondos con un `id_instrumento` opcional: gestion_adm
  tuvo que «explotar» los cheques de cada pago en la pantalla para poder
  conciliarlos de a uno, y la regla de unicidad vivía en tres consultas.
  Acá el instrumento ya es un renglón y `conciliacion_comprobantes` tiene un
  índice único sobre él: el mismo cheque no se concilia dos veces.
- La clasificación no se graba de antemano: cada concepto se compara contra
  las reglas al dibujar la pantalla. En gestion_adm «Procesar» creaba ítems
  pendientes que quedaban viejos cuando se cambiaba una regla.
- Ganan las reglas más específicas: a igual orden, la de patrón más largo.
  Antes una regla nueva («COMISION MANT CTA») iba al final y la tapaba la vieja
  («COMISION»).
- Sin Prisma, débito automático, cobranzas por CUIL ni grupos familiares: son
  de la obra social. Las sugerencias quedan por el recibo de cuota sindical
  emitido desde el renglón (fisca_recibos.py), número de cheque, CUIT (el del
  empleador que aparece en la acreditación contra el de la orden de ingreso de
  cuota sindical) y unicidad del importe.
- Desde cuándo se concilia: desde `s_configuracion.conc_fecha_corte`
  (01/11/2026). Todo lo anterior del libro (el historial de AEDA desde 2020) se
  da por conciliado y no se crean conciliaciones de antes; con «Incluir
  anteriores» se ven también los 60 días previos, para el cheque emitido antes
  que el banco debitó después.
- No se cierra con algo pendiente, con un período anterior abierto, ni si el
  saldo final calculado no da el saldo del banco.
- Una conciliación cerrada se reabre (Administrador) si no hay una posterior
  cerrada. En gestion_adm no se podía.
"""

from __future__ import annotations

import calendar
import datetime
import logging
import re
from collections import OrderedDict

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

import anulaciones
import movimientos_fondos as mf
from db import get_connection, puede, tiene_rol, validasesion
from numeracion import proximo_numero, sql_nro_visible
from pagos_datos import leer_importe, max_nivel
from tesoreria_movimientos import BENEFICIARIO, _crear_movimiento

log = logging.getLogger(__name__)

conc_bp = Blueprint("conc", __name__, url_prefix="/tesoreria/conc")

URL_CONC = "/tesoreria/conc"
URL_CLASIF = "/tesoreria/conc/clasificar"

ESTADOS = {"abierto": ("Abierta", "info"), "en_proceso": ("En proceso", "proceso"), "cerrado": ("Cerrada", "ok")}

#: Qué es un concepto del extracto. `orden_pago` y `prisma` quedan en la base
#: por gestion_adm; acá no se usan.
TIPOS_REGLA = OrderedDict([
    ("concepto_gasto",     "Gasto: orden de pago por concepto"),
    ("motivo_ingreso",     "Ingreso: orden de ingreso"),
    ("movimiento_cuentas", "Pase a otra cuenta propia"),
    ("manual",             "Se concilia a mano"),
])

#: Qué dice cada regla de sugerencia, de la más fuerte a la más débil.
REGLAS_SUGERENCIA = {
    "recibo":        ("Recibo del renglón", "El recibo de cuota sindical se emitió desde este renglón del extracto."),
    "cheque":        ("N° de cheque", "El banco debitó el cheque con este número y este importe."),
    "cuit_fecha":    ("CUIT, fecha e importe", "Mismo CUIT, mismo día y mismo importe, y es el único así de los dos lados."),
    "cuit_importe":  ("CUIT e importe", "Mismo CUIT y mismo importe en el período, sin otro igual de ninguno de los dos lados."),
    "fecha_importe": ("Fecha e importe", "El único con ese importe ese día, de los dos lados."),
    "importe":       ("Solo el importe", "El único con ese importe en todo el período, de los dos lados: conviene mirarlo."),
}

#: Con «Incluir anteriores», cuántos días antes del inicio se mira el libro.
DIAS_ANTERIORES = 60

#: El CUIT del empleador en la descripción de las órdenes de ingreso de cuota
#: sindical («CUOTA SINDICAL 2026-10 · RAZON (CUIT 30716707519)»).
_RE_CUIT = re.compile(r"\b(20|23|24|27|30|33|34)\d{9}\b")

TOL = 0.005


# =============================================================================
# Comunes
# =============================================================================

def _uid():
    return session.get("sind_usuario_id")


def _guardia(url=URL_CONC, api=False):
    if not validasesion():
        return (jsonify(error="La sesión venció: volvé a entrar."), 401) if api else redirect(url_for("login"))
    if not puede(url):
        if api:
            return jsonify(error="No tenés permiso."), 403
        flash("!No tenés permiso para esa pantalla.")
        return redirect(url_for("menu"))
    return None


def _pesos(v) -> str:
    v = float(v or 0)
    entero, _, dec = f"{abs(v):,.2f}".partition(".")
    return f"{'-' if v < 0 else ''}$ {entero.replace(',', '.')},{dec}"


def _fecha(texto) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat((texto or "").strip()[:10])
    except ValueError:
        return None


def _periodo_txt(p) -> str:
    p = str(p or "")
    return f"{p[:4]}-{p[4:]}" if len(p) == 6 else p


def fin_de_periodo(periodo) -> datetime.date | None:
    try:
        anio, mes = int(str(periodo)[:4]), int(str(periodo)[4:6])
        return datetime.date(anio, mes, calendar.monthrange(anio, mes)[1])
    except (TypeError, ValueError):
        return None


def _ids(lista) -> list[int]:
    out = []
    for x in lista:
        x = (x or "").strip()
        if x.isdigit() and int(x) not in out:
            out.append(int(x))
    return out


def _cuentas_banco(cur) -> list[dict]:
    cur.execute("""SELECT id, nombre, numero_de_cuenta FROM c_cuentas_de_fondos
                    WHERE tipo_de_cuenta = 'B' AND habilitada = 1 ORDER BY nombre""")
    return cur.fetchall()


def _conc(cur, id_conc, bloquear=False) -> dict | None:
    cur.execute(f"""SELECT ch.*, cf.nombre AS cuenta, cf.numero_de_cuenta
                      FROM conciliacion_header ch JOIN c_cuentas_de_fondos cf ON cf.id = ch.id_cuenta
                     WHERE ch.id = %s{' FOR UPDATE' if bloquear else ''}""", (id_conc,))
    return cur.fetchone()


# =============================================================================
# Saldos del extracto
# =============================================================================

def _saldo_cierre_dia(filas) -> float | None:
    """El saldo al final del día, de los renglones de UN día que traen saldo.

    El orden dentro del día no es el del archivo: ICBC lista del más nuevo al
    más viejo. Se resuelve con la cadena de saldos (copiado de gestion_adm): el
    saldo de cada renglón menos su crédito más su débito es el anterior; el
    último del día es el único cuyo saldo no es el anterior de ningún otro. Si
    la cadena no da un único final (BNA trae el saldo en un solo renglón por
    día), el de mayor id."""
    if not filas:
        return None
    if len(filas) > 1:
        anteriores = {round(float(f["saldo"]) - float(f["credito"]) + float(f["debito"]), 2) for f in filas}
        finales = [f for f in filas if round(float(f["saldo"]), 2) not in anteriores]
        if len(finales) == 1:
            return float(finales[0]["saldo"])
    return float(max(filas, key=lambda f: f["id"])["saldo"])


def saldo_extracto_cierre(cur, id_cuenta, desde, hasta) -> float | None:
    """El saldo de cierre que informa el banco en el rango, o None si el
    extracto de esas fechas no trae saldo. Es el último día con saldo."""
    cur.execute("""
        SELECT id, saldo, COALESCE(credito, 0) AS credito, COALESCE(debito, 0) AS debito
          FROM c_extractos_bancarios
         WHERE c_cuentas_de_fondos_id = %s AND saldo IS NOT NULL
           AND fecham = (SELECT MAX(fecham) FROM c_extractos_bancarios
                          WHERE c_cuentas_de_fondos_id = %s AND fecham BETWEEN %s AND %s AND saldo IS NOT NULL)""",
                (id_cuenta, id_cuenta, desde, hasta))
    return _saldo_cierre_dia(cur.fetchall())


def saldo_extracto_apertura(cur, id_cuenta, desde, hasta) -> float | None:
    """El saldo con que la cuenta arranca el rango, deducido del extracto: el
    cierre del primer día con saldo menos lo que se movió desde el inicio del
    rango hasta ese día. Es una sugerencia para el primer período de la cuenta,
    no un dato del banco: si faltan renglones de esos días, da mal."""
    cur.execute("""SELECT MIN(fecham) AS d FROM c_extractos_bancarios
                    WHERE c_cuentas_de_fondos_id = %s AND fecham BETWEEN %s AND %s AND saldo IS NOT NULL""",
                (id_cuenta, desde, hasta))
    dia = (cur.fetchone() or {}).get("d")
    if not dia:
        return None
    cur.execute("""SELECT id, saldo, COALESCE(credito, 0) AS credito, COALESCE(debito, 0) AS debito
                     FROM c_extractos_bancarios
                    WHERE c_cuentas_de_fondos_id = %s AND fecham = %s AND saldo IS NOT NULL""", (id_cuenta, dia))
    cierre = _saldo_cierre_dia(cur.fetchall())
    cur.execute("""SELECT COALESCE(SUM(COALESCE(credito, 0) - COALESCE(debito, 0)), 0) AS n
                     FROM c_extractos_bancarios
                    WHERE c_cuentas_de_fondos_id = %s AND fecham BETWEEN %s AND %s""", (id_cuenta, desde, dia))
    return round(cierre - float(cur.fetchone()["n"]), 2)


def _anterior_cerrada(cur, id_cuenta, antes_de) -> dict | None:
    """La última conciliación cerrada de la cuenta que termina antes de la
    fecha: de ahí sale el saldo inicial. Una sola consulta para el diálogo y
    para el alta, así la pantalla no promete un saldo distinto del que graba."""
    cur.execute("""SELECT id, periodo, fecha_hasta, saldo_final FROM conciliacion_header
                    WHERE id_cuenta = %s AND estado = 'cerrado' AND fecha_hasta < %s
                    ORDER BY fecha_hasta DESC LIMIT 1""", (id_cuenta, antes_de))
    return cur.fetchone()


# =============================================================================
# Reglas de clasificación
# =============================================================================

def concepto_base(concepto) -> str:
    """El concepto sin lo que agregan los parsers después de « — » (la
    información complementaria del ICBC, el CUIT de quien depositó): es lo
    que se clasifica, porque es lo que se repite."""
    return (concepto or "").split(" — ")[0].strip()


def reglas_activas(cur) -> list[dict]:
    """Ordenadas para matchear: por `orden`, y a igual orden la de patrón más
    largo, que es la más específica."""
    cur.execute("""SELECT r.*, cg.descripcion AS nombre_concepto, mi.descripcion AS nombre_motivo,
                          cd.nombre AS nombre_destino
                     FROM conc_reglas r
                     LEFT JOIN c_concepto_de_gastos cg ON cg.id = r.id_concepto_gasto
                     LEFT JOIN c_motivos_de_ingreso mi ON mi.id = r.id_motivo_ingreso
                     LEFT JOIN c_cuentas_de_fondos cd ON cd.id = r.id_cuenta_destino
                    WHERE r.activa = 1""")
    reglas = cur.fetchall()
    reglas.sort(key=lambda r: (r["orden"] or 0, -len(r["patron_texto"] or ""), r["id"]))
    for r in reglas:
        r["clasif_txt"] = texto_regla(r)
    return reglas


def texto_regla(r) -> str:
    t = r.get("tipo_resultado")
    if t == "concepto_gasto":
        return f"Gasto · {r.get('nombre_concepto') or '¿concepto?'}"
    if t == "motivo_ingreso":
        return f"Ingreso · {r.get('nombre_motivo') or '¿motivo?'}"
    if t == "movimiento_cuentas":
        return f"Pase · {r.get('nombre_destino') or '¿cuenta?'}"
    if t == "manual":
        return "A mano"
    return t or ""


def match_regla(concepto, es_debito: bool, es_credito: bool, reglas: list[dict]) -> dict | None:
    """La primera regla que coincide con el concepto (ya ordenadas)."""
    base = concepto_base(concepto).upper()
    for r in reglas:
        tm = r["tipo_movimiento"]
        if (tm == "debito" and not es_debito) or (tm == "credito" and not es_credito):
            continue
        p, tp = (r["patron_texto"] or "").upper(), r["tipo_patron"]
        if not p:
            continue
        if (tp == "contiene" and p in base) or (tp == "empieza_con" and base.startswith(p)) or (tp == "exacto" and base == p):
            return r
        if tp == "regex":
            try:
                if re.search(r["patron_texto"], concepto or "", re.IGNORECASE):
                    return r
            except re.error:
                continue
    return None


# =============================================================================
# El libro: c_debitos_creditos_bancarios
# =============================================================================

#: Cada renglón del libro con su comprobante. El CUIT del pago es el del
#: beneficiario según la clase de la orden.
SQL_LIBRO = f"""
    SELECT dc.id AS id_dc, dc.tipo_instrumento, dc.importe_debito, dc.importe_credito, dc.cheque_numero,
           COALESCE(dc.fecha_emision, mf.fecha) AS fecha, dc.nro_referencia,
           mf.id AS id_movimiento, mf.concepto, mf.fecha_anulacion,
           mf.pago_pagosId AS id_pago, mf.ingreso_ordenesId AS id_ingreso,
           mf.c_movimiento_entre_cuentasId AS id_mov_cuentas, mf.c_comprobantes_emitidosId AS id_cobranza,
           p.id_orden, o.clase, {sql_nro_visible('p')} AS nro_pago, ({BENEFICIARIO}) AS beneficiario,
           CASE o.clase
             WHEN 'proveedor' THEN (SELECT MIN(e.cuit_emisor) FROM pago_ordenes_detalle d
                                      JOIN me_expedientes e ON e.id = d.id_expediente WHERE d.id_orden = o.id)
             WHEN 'anticipo'  THEN (SELECT MIN(pr.cuit) FROM pago_ordenes_anticipo_det ad
                                      JOIN c_proveedores pr ON pr.id = ad.id_proveedor WHERE ad.id_orden = o.id)
             WHEN 'reintegro' THEN (SELECT MIN(rd.cuil) FROM pago_ordenes_reintegro_det rd WHERE rd.id_orden = o.id)
           END AS cuit_pago,
           io.nro_orden AS nro_ingreso,
           (SELECT MIN(d.id_extracto_origen) FROM ingreso_ordenes_detalle d WHERE d.id_orden = io.id) AS id_extracto_origen,
           (SELECT GROUP_CONCAT(d.descripcion ORDER BY d.id SEPARATOR ' / ')
              FROM ingreso_ordenes_detalle d WHERE d.id_orden = io.id) AS detalle_ingreso,
           mc.tipo_movimiento, mc.comentario AS comentario_mov,
           (SELECT GROUP_CONCAT(c2.nombre SEPARATOR ', ') FROM c_movimiento_entre_cuentas_det d2
              JOIN c_cuentas_de_fondos c2 ON c2.id = d2.id_cuenta_fondos
             WHERE d2.id_movimiento = mc.id AND d2.id_cuenta_fondos <> mf.c_cuentas_de_fondosId) AS otra_cuenta
      FROM c_debitos_creditos_bancarios dc
      JOIN c_movimientos_de_fondos mf ON mf.id = dc.c_movimientos_de_fondosId
      LEFT JOIN pago_pagos p ON p.id = mf.pago_pagosId
      LEFT JOIN pago_ordenes o ON o.id = p.id_orden
      LEFT JOIN ingreso_ordenes io ON io.id = mf.ingreso_ordenesId
      LEFT JOIN c_movimiento_entre_cuentas mc ON mc.id = mf.c_movimiento_entre_cuentasId"""

_INSTRUMENTO = {"cheque": "Cheque", "transferencia": "Transferencia", "deposito": "Depósito",
                "debito_automatico": "Débito automático", "efectivo": "Efectivo", "otro": "Otro"}
_TIPO_MOV = {"movimiento_entre_cuentas": "Entre cuentas", "deposito_bancario": "Depósito",
             "extraccion_bancaria": "Extracción", "inversiones": "Inversión"}


def formatear_libro(r) -> dict:
    """Un renglón del libro listo para mostrar y para emparejar."""
    cred, deb = float(r["importe_credito"] or 0), float(r["importe_debito"] or 0)
    r["tipo"] = "C" if cred > 0 else "D"
    r["importe"] = round(cred if cred > 0 else deb, 2)
    r["credito"], r["debito"] = (cred or None), (deb or None)
    r["neto"] = round(cred - deb, 2)
    r["cheques"] = {int(r["cheque_numero"])} if r.get("cheque_numero") else set()
    r["instrumento_txt"] = _INSTRUMENTO.get(r["tipo_instrumento"], r["tipo_instrumento"] or "")
    if r["cheque_numero"]:
        r["instrumento_txt"] += f" N° {r['cheque_numero']}"
    if r["id_pago"]:
        r["origen"], r["comprobante"] = "pago", f"Pago {r['nro_pago'] or r['id_pago']}"
        r["detalle"] = r["beneficiario"] or r["concepto"] or ""
        r["cuit"] = re.sub(r"\D", "", str(r["cuit_pago"] or "")) or None
        r["url"] = url_for("pagos.orden", id_orden=r["id_orden"]) if r["id_orden"] else None
    elif r["id_ingreso"]:
        r["origen"], r["comprobante"] = "ingreso", f"Ingreso {r['nro_ingreso'] or r['id_ingreso']}"
        r["detalle"] = r["detalle_ingreso"] or r["concepto"] or ""
        m = _RE_CUIT.search(r["detalle"])
        r["cuit"] = m.group(0) if m else None
        r["url"] = url_for("tes_mov.ingreso", id_orden=r["id_ingreso"])
    elif r["id_mov_cuentas"]:
        r["origen"], r["comprobante"] = "movimiento", f"Movimiento MOV-{r['id_mov_cuentas']}"
        r["detalle"] = " · ".join(x for x in (_TIPO_MOV.get(r["tipo_movimiento"], ""),
                                              (("con " + r["otra_cuenta"]) if r["otra_cuenta"] else ""),
                                              r["comentario_mov"] or "") if x)
        r["cuit"] = None
        r["url"] = url_for("tes_mov.movimiento", id_movimiento=r["id_mov_cuentas"])
    else:
        r["origen"], r["comprobante"] = "otro", f"Libro {r['id_movimiento']}"
        r["detalle"], r["cuit"], r["url"] = r["concepto"] or "", None, None
    return r


def fecha_corte(cur) -> datetime.date | None:
    """Desde cuándo se concilia: `s_configuracion.conc_fecha_corte` (01/11/2026,
    decidido el 12/11/2026). Lo anterior del libro —el historial de AEDA desde
    2020— se da por conciliado y no hay conciliaciones de antes. Está en la base
    y no en el código porque es una fecha de puesta en marcha."""
    cur.execute("""SELECT valor FROM s_configuracion
                    WHERE modulo = 'tesoreria' AND parametro = 'conc_fecha_corte' LIMIT 1""")
    return _fecha((cur.fetchone() or {}).get("valor"))


def corte_cuenta(cur, id_cuenta) -> datetime.date | None:
    """Desde dónde se mira el libro de la cuenta: la fecha de corte o, si es
    posterior, el inicio de la primera conciliación de la cuenta (una cuenta que
    se empieza a conciliar después). Sin ninguno de los dos, None.
    Sin un corte, la primera conciliación arrastraría años de renglones de AEDA
    como pendientes."""
    cur.execute("SELECT MIN(fecha_desde) AS d FROM conciliacion_header WHERE id_cuenta = %s", (id_cuenta,))
    primera = (cur.fetchone() or {}).get("d")
    corte = fecha_corte(cur)
    return max(x for x in (corte, primera) if x) if (corte or primera) else None


def libro_pendiente(cur, conc, anteriores=False) -> list[dict]:
    """Lo del libro de la cuenta que todavía no se concilió, hasta el fin del
    período: lo del período y lo que quedó de antes (el cheque emitido en julio
    que el banco debita en agosto), con piso en el corte de la cuenta."""
    corte = corte_cuenta(cur, conc["id_cuenta"]) or conc["fecha_desde"]
    if anteriores:
        corte = corte - datetime.timedelta(days=DIAS_ANTERIORES)
    cur.execute(f"""{SQL_LIBRO}
         WHERE mf.c_cuentas_de_fondosId = %s AND mf.fecha_anulacion IS NULL AND dc.estado <> 'anulado'
           AND COALESCE(dc.fecha_emision, mf.fecha) BETWEEN %s AND %s
           AND NOT EXISTS (SELECT 1 FROM conciliacion_comprobantes cc WHERE cc.id_debito_credito = dc.id)
         ORDER BY fecha, dc.id""", (conc["id_cuenta"], corte, conc["fecha_hasta"]))
    filas = [formatear_libro(r) for r in cur.fetchall()]
    for r in filas:
        r["anterior"] = r["fecha"] < conc["fecha_desde"]
    return filas


def libro_por_ids(cur, ids) -> dict:
    if not ids:
        return {}
    marcas = ",".join(["%s"] * len(ids))
    cur.execute(f"{SQL_LIBRO} WHERE dc.id IN ({marcas})", list(ids))
    return {r["id_dc"]: formatear_libro(r) for r in cur.fetchall()}


# =============================================================================
# El extracto del período
# =============================================================================

def extracto_periodo(cur, conc) -> list[dict]:
    cur.execute("""
        SELECT e.id, e.fecham, e.fechav, e.ref_nro, e.debito, e.credito, e.saldo, e.concepto, e.cuit, e.origen,
               ci.id AS id_item, ci.estado AS estado_item, ci.id_grupo, ci.observaciones AS obs_item,
               ci.origen AS origen_item, ci.id_regla, g.observaciones AS obs_grupo, g.diferencia AS dif_grupo,
               u.nombre AS usuario_item
          FROM c_extractos_bancarios e
          LEFT JOIN conciliacion_items ci ON ci.id_extracto = e.id AND ci.id_conciliacion = %s
          LEFT JOIN conciliacion_grupos g ON g.id = ci.id_grupo
          LEFT JOIN s_usuarios u ON u.id = ci.id_usuario
         WHERE e.c_cuentas_de_fondos_id = %s AND e.fecham BETWEEN %s AND %s
         ORDER BY e.fecham, e.id""", (conc["id"], conc["id_cuenta"], conc["fecha_desde"], conc["fecha_hasta"]))
    filas = cur.fetchall()
    for m in filas:
        cred, deb = float(m["credito"] or 0), float(m["debito"] or 0)
        m["tipo"] = "C" if cred > 0 else "D"
        m["importe"] = round(cred if cred > 0 else deb, 2)
        m["neto"] = round(cred - deb, 2)
        m["pendiente"] = not m["id_item"]
    return filas


def totales(cur, conc, extracto) -> dict:
    creditos = round(sum(float(m["credito"] or 0) for m in extracto), 2)
    debitos = round(sum(float(m["debito"] or 0) for m in extracto), 2)
    inicial = float(conc["saldo_inicial"] or 0)
    final = round(inicial + creditos - debitos, 2)
    if conc["estado"] == "cerrado":
        banco = float(conc["saldo_banco"]) if conc["saldo_banco"] is not None else None
    else:
        banco = saldo_extracto_cierre(cur, conc["id_cuenta"], conc["fecha_desde"], conc["fecha_hasta"])
    pend = [m for m in extracto if m["pendiente"]]
    return {"inicial": inicial, "creditos": creditos, "debitos": debitos, "final": final, "banco": banco,
            "diferencia": round(final - banco, 2) if banco is not None else None,
            "renglones": len(extracto), "pendientes": len(pend),
            "pendiente_importe": round(sum(m["importe"] for m in pend), 2),
            "conciliados": sum(1 for m in extracto if m["estado_item"] == "conciliado"),
            "excepciones": sum(1 for m in extracto if m["estado_item"] == "excepcion")}


# =============================================================================
# Sugerencias
# =============================================================================

def _cuit(v) -> str | None:
    d = re.sub(r"\D", "", str(v or ""))
    return d or None


def sugerencias(extracto: list[dict], libro: list[dict]) -> dict:
    """Empareja extracto y libro de a uno, sin vincular nada: {id_extracto:
    (renglón del libro, regla)}. Vincular es una decisión de la persona.

    Solo lo inequívoco: una clave que aparece dos veces de cualquier lado no se
    sugiere. Las pasadas van de la más fuerte a la más débil y ninguna toca lo
    que ya tomó otra (portado de gestion_adm, sin las pasadas de la obra social).
    En las dos últimas, que no exigen CUIT, se descarta el par contradicho: los
    dos traen CUIT y son distintos, o el banco informa un cheque y el libro dice
    otro.
    """
    sug: dict = {}
    tomados: set = set()
    pend = [m for m in extracto if m["pendiente"]]

    def libres():
        return [c for c in libro if c["id_dc"] not in tomados]

    def pendientes():
        return [m for m in pend if m["id"] not in sug]

    def anotar(m, c, regla):
        sug[m["id"]] = (c, regla)
        tomados.add(c["id_dc"])

    # 0. El recibo de cuota sindical emitido desde el renglón (fisca_recibos.py).
    por_ext: dict = {}
    for c in libro:
        if c.get("id_extracto_origen"):
            por_ext.setdefault(c["id_extracto_origen"], []).append(c)
    for m in pendientes():
        cand = [c for c in por_ext.get(m["id"], ()) if c["id_dc"] not in tomados and abs(c["importe"] - m["importe"]) < TOL]
        if len(cand) == 1:
            anotar(m, cand[0], "recibo")

    # 1. El número de cheque: el banco debitó el cheque N y el libro emitió el cheque N.
    por_cheque: dict = {}
    for c in libro:
        for n in c["cheques"]:
            por_cheque.setdefault(n, []).append(c)
    for m in pendientes():
        ref = re.sub(r"\D", "", str(m["ref_nro"] or ""))
        if m["tipo"] != "D" or not ref:
            continue
        cand = [c for c in por_cheque.get(int(ref), ()) if c["id_dc"] not in tomados and c["tipo"] == "D"
                and abs(c["importe"] - m["importe"]) < TOL]
        if len(cand) == 1:
            anotar(m, cand[0], "cheque")

    def pasada(clave_ext, clave_lib, regla, contradice=None):
        ce: dict = {}
        for m in pendientes():
            k = clave_ext(m)
            if k:
                ce.setdefault(k, []).append(m)
        cl: dict = {}
        for c in libres():
            k = clave_lib(c)
            if k:
                cl.setdefault(k, []).append(c)
        for k, ms in ce.items():
            cs = cl.get(k)
            if len(ms) == 1 and cs and len(cs) == 1 and not (contradice and contradice(ms[0], cs[0])):
                anotar(ms[0], cs[0], regla)

    def se_contradicen(m, c):
        ref = re.sub(r"\D", "", str(m["ref_nro"] or ""))
        if m["tipo"] == "D" and c["cheques"] and ref and int(ref) not in c["cheques"]:
            return True
        a, b = _cuit(m["cuit"]), _cuit(c["cuit"])
        return bool(a and b and a != b)

    # 2. y 3. El CUIT: el de la acreditación contra el del comprobante.
    pasada(lambda m: (_cuit(m["cuit"]), m["fecham"], m["importe"], m["tipo"]) if _cuit(m["cuit"]) else None,
           lambda c: (_cuit(c["cuit"]), c["fecha"], c["importe"], c["tipo"]) if _cuit(c["cuit"]) else None, "cuit_fecha")
    pasada(lambda m: (_cuit(m["cuit"]), m["importe"], m["tipo"]) if _cuit(m["cuit"]) else None,
           lambda c: (_cuit(c["cuit"]), c["importe"], c["tipo"]) if _cuit(c["cuit"]) else None, "cuit_importe")
    # 4. y 5. Lo único de los dos lados: primero con la fecha, después sin ella.
    pasada(lambda m: (m["fecham"], m["importe"], m["tipo"]), lambda c: (c["fecha"], c["importe"], c["tipo"]),
           "fecha_importe", se_contradicen)
    pasada(lambda m: (m["importe"], m["tipo"]), lambda c: (c["importe"], c["tipo"]), "importe", se_contradicen)
    return sug


# =============================================================================
# Comprobantes a generar
# =============================================================================

def grupos_a_generar(extracto: list[dict], reglas: list[dict], sug: dict) -> list[dict]:
    """Los comprobantes que generaría «Generar comprobantes»: los renglones
    pendientes cuyo concepto tiene una regla que genera, agrupados por la
    clasificación y, si la regla agrupa, por fecha. Un gasto sale de los
    débitos y un ingreso de los créditos; un pase, de los dos (uno por sentido).
    Si el libro ya tiene algo que coincide con un renglón (una sugerencia), el
    grupo viene sin tildar: puede que el comprobante ya exista."""
    grupos: "OrderedDict[str, dict]" = OrderedDict()
    for m in extracto:
        if not m["pendiente"]:
            continue
        r = match_regla(m["concepto"], m["tipo"] == "D", m["tipo"] == "C", reglas)
        if not r or not r["genera_op"]:
            continue
        t = r["tipo_resultado"]
        if (t == "concepto_gasto" and m["tipo"] != "D") or (t == "motivo_ingreso" and m["tipo"] != "C"):
            continue
        if t == "concepto_gasto":
            clasif = r["id_concepto_gasto"]
        elif t == "motivo_ingreso":
            clasif = r["id_motivo_ingreso"]
        elif t == "movimiento_cuentas":
            clasif = r["id_cuenta_destino"]
        else:
            continue
        if not clasif:
            continue
        cuando = m["fecham"].isoformat() if r["agrupa_por_fecha"] else f"e{m['id']}"
        clave = f"{t}-{clasif}-{m['tipo']}-{cuando}"
        g = grupos.setdefault(clave, {"clave": clave, "tipo": t, "clasif": clasif, "signo": m["tipo"],
                                      "fecha": m["fecham"], "regla": r, "filas": [], "total": 0.0, "aviso": None})
        g["filas"].append(m)
        g["total"] = round(g["total"] + m["importe"], 2)
        if m["id"] in sug and not g["aviso"]:
            c, _ = sug[m["id"]]
            g["aviso"] = f"El libro ya tiene {c['comprobante']} por {_pesos(c['importe'])} que coincide: puede que ya esté cargado."
    for g in grupos.values():
        r = g["regla"]
        if g["tipo"] == "concepto_gasto":
            g["que"] = f"Orden de pago por concepto · {r['nombre_concepto']}"
        elif g["tipo"] == "motivo_ingreso":
            g["que"] = f"Orden de ingreso · {r['nombre_motivo']}"
        else:
            g["que"] = (f"Movimiento a {r['nombre_destino']}" if g["signo"] == "D"
                        else f"Movimiento desde {r['nombre_destino']}")
        g["nombre"] = concepto_base(g["filas"][0]["concepto"])
    return list(grupos.values())


def _dc_de(cur, origen: str, id_comprobante: int, id_cuenta: int) -> list[dict]:
    """Los renglones del libro bancario que dejó un comprobante en la cuenta."""
    col = mf.COLUMNA_ORIGEN[origen]
    cur.execute(f"""SELECT dc.id, dc.importe_credito, dc.importe_debito, mf.id AS id_movimiento
                      FROM c_debitos_creditos_bancarios dc
                      JOIN c_movimientos_de_fondos mf ON mf.id = dc.c_movimientos_de_fondosId
                     WHERE mf.{col} = %s AND mf.c_cuentas_de_fondosId = %s AND dc.estado <> 'anulado'""",
                (id_comprobante, id_cuenta))
    return cur.fetchall()


def _generar_uno(cur, conc, g, uid) -> str:
    """Crea el comprobante de un grupo y lo concilia con sus renglones. Con el
    cursor de la transacción del grupo: si algo falla, no queda nada."""
    fecha, total, r = g["fecha"], round(g["total"], 2), g["regla"]
    obs = f"Conciliación {_periodo_txt(conc['periodo'])} · {g['nombre']} ({fecha:%d/%m/%Y})"
    id_orden = id_pago = None
    if g["tipo"] == "concepto_gasto":
        # El gasto ya ocurrió: el banco lo debitó. La orden nace aprobada con
        # todos los niveles (pedir aprobación para algo que ya pasó no decide
        # nada) y se paga en el acto con un instrumento de esta cuenta, como en
        # gestion_adm. Sin el pago no hay renglón en el libro y la cuenta no
        # refleja la salida.
        niveles = max_nivel(cur)
        nro = proximo_numero(cur, "pago_ordenes", fecha)
        cur.execute("""INSERT INTO pago_ordenes (nro_orden, clase, anio, periodo, fecha, estado, importe_total, moneda,
                                                 niveles_requeridos, niveles_aprobados, observaciones, id_usuario_creacion)
                       VALUES (%s, 'concepto', %s, %s, %s, 'aprobada', %s, 'ARS', %s, %s, %s, %s)""",
                    (nro, fecha.year, conc["periodo"], fecha, total, niveles, niveles, obs, uid))
        id_orden = cur.lastrowid
        for m in g["filas"]:
            cur.execute("""INSERT INTO pago_ordenes_concepto_det (id_orden, tipo, id_concepto_gasto, descripcion, importe,
                                                                  moneda, periodo, id_extracto_origen)
                           VALUES (%s, 'gasto', %s, %s, %s, 'ARS', %s, %s)""",
                        (id_orden, g["clasif"], (m["concepto"] or g["nombre"])[:200], m["importe"], conc["periodo"], m["id"]))
        nro_pago = proximo_numero(cur, "pago_pagos", fecha)
        cur.execute("""INSERT INTO pago_pagos (nro_pago, id_orden, fecha_pago, estado, importe_total, observaciones,
                                               id_usuario_creacion)
                       VALUES (%s, %s, %s, 'emitido', %s, %s, %s)""", (nro_pago, id_orden, fecha, total, obs, uid))
        id_pago = cur.lastrowid
        # Sin nro_referencia: el libro bancario usa «INST-<id>» como clave del
        # instrumento, y una referencia repetida no le abriría su renglón.
        cur.execute("""INSERT INTO pago_pagos_instrumentos (id_pago, id_cuenta_fondos, tipo_instrumento, importe)
                       VALUES (%s, %s, 'transferencia', %s)""", (id_pago, conc["id_cuenta"], total))
        mf.registrar_pago(cur, id_pago)
        cur.execute("UPDATE pago_ordenes SET estado = 'pagada' WHERE id = %s", (id_orden,))
        origen, id_comp, texto = "pago", id_pago, f"orden {nro} pagada con el pago {nro_pago}"
        tipo_interno = "concepto_gasto"
    elif g["tipo"] == "motivo_ingreso":
        nro = proximo_numero(cur, "ingreso_ordenes", fecha)
        cur.execute("""INSERT INTO ingreso_ordenes (nro_orden, clase, anio, fecha, estado, id_cuenta, importe_total, moneda,
                                                    origen, observaciones, id_usuario_creacion)
                       VALUES (%s, 'bancario', %s, %s, 'confirmado', %s, %s, 'ARS', 'conciliacion', %s, %s)""",
                    (nro, fecha.year, fecha, conc["id_cuenta"], total, obs, uid))
        id_comp = cur.lastrowid
        for m in g["filas"]:
            cur.execute("""INSERT INTO ingreso_ordenes_detalle (id_orden, tipo, id_motivo_ingreso, descripcion, importe,
                                                                periodo, id_extracto_origen)
                           VALUES (%s, 'ingreso', %s, %s, %s, %s, %s)""",
                        (id_comp, g["clasif"], (m["concepto"] or g["nombre"])[:200], m["importe"], conc["periodo"], m["id"]))
        cur.execute("INSERT INTO ingreso_ordenes_cuentas (id_orden, id_cuenta_fondos, importe) VALUES (%s, %s, %s)",
                    (id_comp, conc["id_cuenta"], total))
        mf.registrar_ingreso(cur, id_comp)
        origen, texto, tipo_interno = "ingreso", f"orden de ingreso {nro}", "motivo_ingreso"
    else:
        # El sentido sale del extracto: un débito es plata que se fue de esta
        # cuenta a la otra; un crédito, plata que vino de la otra.
        destino = g["clasif"]
        if destino == conc["id_cuenta"]:
            raise ValueError("la regla manda la plata a la misma cuenta que se concilia")
        sale, entra = (conc["id_cuenta"], destino) if g["signo"] == "D" else (destino, conc["id_cuenta"])
        id_comp = _crear_movimiento(cur, "movimiento_entre_cuentas", fecha, sale, entra, total, obs[:250], uid)
        origen, texto, tipo_interno = "movimiento", f"movimiento MOV-{id_comp}", "movimiento_cuentas"

    dcs = _dc_de(cur, origen, id_comp, conc["id_cuenta"])
    neto_libro = round(sum(float(d["importe_credito"] or 0) - float(d["importe_debito"] or 0) for d in dcs), 2)
    neto_ext = round(sum(m["neto"] for m in g["filas"]), 2)
    if not dcs or abs(neto_libro - neto_ext) > TOL:
        raise ValueError(f"el comprobante no dejó en el libro bancario lo que dice el extracto "
                         f"({_pesos(neto_libro)} contra {_pesos(neto_ext)})")
    _grabar_grupo(cur, conc, g["filas"], [formatear_libro_min(d, origen, id_comp, id_orden) for d in dcs], uid,
                  None, origen="automatico", id_regla=r["id"], tipo_interno=tipo_interno,
                  id_concepto_gasto=g["clasif"] if g["tipo"] == "concepto_gasto" else None,
                  id_motivo_ingreso=g["clasif"] if g["tipo"] == "motivo_ingreso" else None)
    return texto


def formatear_libro_min(d, origen, id_comp, id_orden=None) -> dict:
    """Lo que `_grabar_grupo` necesita de un renglón del libro recién creado."""
    cred, deb = float(d["importe_credito"] or 0), float(d["importe_debito"] or 0)
    return {"id_dc": d["id"], "id_movimiento": d["id_movimiento"], "neto": round(cred - deb, 2),
            "importe": round(cred or deb, 2), "origen": origen,
            "id_pago": id_comp if origen == "pago" else None, "id_orden": id_orden,
            "id_ingreso": id_comp if origen == "ingreso" else None}


# =============================================================================
# Grabar y deshacer vínculos
# =============================================================================

_TIPO_INTERNO = {"pago": "orden_pago", "ingreso": "motivo_ingreso", "movimiento": "movimiento_cuentas"}


def _grabar_grupo(cur, conc, ext: list[dict], lib: list[dict], uid, obs, origen="manual", id_regla=None,
                  tipo_interno=None, id_concepto_gasto=None, id_motivo_ingreso=None) -> int:
    imp_e = round(sum(m["neto"] for m in ext), 2)
    imp_l = round(sum(c["neto"] for c in lib), 2)
    cur.execute("""INSERT INTO conciliacion_grupos (id_conciliacion, importe_extracto, importe_comprobantes, diferencia,
                                                    cant_extractos, cant_comprobantes, observaciones, id_usuario)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (conc["id"], imp_e, imp_l, round(imp_e - imp_l, 2), len(ext), len(lib), obs, uid))
    id_grupo = cur.lastrowid
    unico = lib[0] if len(lib) == 1 else None
    tipo = tipo_interno or (_TIPO_INTERNO.get(lib[0]["origen"], "sin_clasificar") if len({c["origen"] for c in lib}) == 1
                            else "sin_clasificar")
    for m in ext:
        cur.execute("""INSERT INTO conciliacion_items (id_conciliacion, id_grupo, id_extracto, id_debito_credito, id_regla,
                                                       tipo_interno, id_orden_pago, id_pago_pagos, id_concepto_gasto,
                                                       id_motivo_ingreso, estado, origen, id_usuario, observaciones)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'conciliado', %s, %s, %s)""",
                    (conc["id"], id_grupo, m["id"], unico["id_dc"] if unico else None, id_regla, tipo,
                     unico.get("id_orden") if unico else None, unico.get("id_pago") if unico else None,
                     id_concepto_gasto, id_motivo_ingreso, origen, uid, obs))
    for c in lib:
        cur.execute("""INSERT INTO conciliacion_comprobantes (id_grupo, id_debito_credito, id_movimiento, id_pago,
                                                              id_orden_pago, id_ingreso, importe, observaciones)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (id_grupo, c["id_dc"], c["id_movimiento"], c.get("id_pago"), c.get("id_orden"), c.get("id_ingreso"),
                     c["importe"], obs))
    if conc["estado"] == "abierto":
        cur.execute("UPDATE conciliacion_header SET estado = 'en_proceso' WHERE id = %s AND estado = 'abierto'",
                    (conc["id"],))
        conc["estado"] = "en_proceso"
    return id_grupo


def _validar_extracto(cur, conc, ids) -> tuple[list[dict], str | None]:
    if not ids:
        return [], "Elegí al menos un renglón del extracto."
    marcas = ",".join(["%s"] * len(ids))
    cur.execute(f"""SELECT e.id, e.fecham, e.debito, e.credito, e.concepto,
                           (SELECT ci.id FROM conciliacion_items ci WHERE ci.id_extracto = e.id LIMIT 1) AS id_item
                      FROM c_extractos_bancarios e
                     WHERE e.id IN ({marcas}) AND e.c_cuentas_de_fondos_id = %s AND e.fecham BETWEEN %s AND %s""",
                [*ids, conc["id_cuenta"], conc["fecha_desde"], conc["fecha_hasta"]])
    filas = cur.fetchall()
    if len(filas) != len(ids):
        return [], "Hay renglones del extracto que no son de esta cuenta y período."
    if any(f["id_item"] for f in filas):
        return [], "Hay renglones del extracto que ya están conciliados o marcados como excepción."
    for f in filas:
        f["neto"] = round(float(f["credito"] or 0) - float(f["debito"] or 0), 2)
    return filas, None


def _validar_libro(cur, conc, ids) -> tuple[list[dict], str | None]:
    if not ids:
        return [], "Elegí al menos un renglón del libro."
    lib = libro_por_ids(cur, ids)
    if len(lib) != len(ids):
        return [], "Hay renglones del libro que no existen."
    cur.execute(f"""SELECT dc.id FROM c_debitos_creditos_bancarios dc
                      JOIN c_movimientos_de_fondos mf ON mf.id = dc.c_movimientos_de_fondosId
                     WHERE dc.id IN ({','.join(['%s'] * len(ids))})
                       AND (mf.c_cuentas_de_fondosId <> %s OR mf.fecha_anulacion IS NOT NULL OR dc.estado = 'anulado'
                            OR EXISTS (SELECT 1 FROM conciliacion_comprobantes cc WHERE cc.id_debito_credito = dc.id))""",
                [*ids, conc["id_cuenta"]])
    if cur.fetchall():
        return [], "Hay renglones del libro que son de otra cuenta, están anulados o ya se conciliaron."
    return list(lib.values()), None


def _redir(id_conc):
    extra = {"anteriores": 1} if request.form.get("anteriores") == "1" else {}
    return redirect(url_for("conc.detalle", id_conc=id_conc, **extra))


def _transaccion(fn):
    """Corre `fn(cur)` en una transacción; devuelve lo que devuelve fn."""
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            out = fn(cur)
        conn.commit()
        return out
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# =============================================================================
# Lista y alta
# =============================================================================

@conc_bp.route("")
def lista():
    salida = _guardia()
    if salida:
        return salida
    f_cuenta = request.args.get("cuenta", type=int)
    ver_cerradas = request.args.get("cerradas") == "1"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cuentas = _cuentas_banco(cur)
            where, params = ["1 = 1"], []
            if f_cuenta:
                where.append("ch.id_cuenta = %s"); params.append(f_cuenta)
            cur.execute(f"SELECT COUNT(*) AS n FROM conciliacion_header ch WHERE ch.estado = 'cerrado' AND {' AND '.join(where)}",
                        params)
            cerradas = int(cur.fetchone()["n"] or 0)
            if not ver_cerradas:
                where.append("ch.estado <> 'cerrado'")
            cur.execute(f"""
                SELECT ch.*, cf.nombre AS cuenta, u.nombre AS usuario,
                       x.creditos, x.debitos, x.renglones, x.resueltos
                  FROM conciliacion_header ch
                  JOIN c_cuentas_de_fondos cf ON cf.id = ch.id_cuenta
                  LEFT JOIN s_usuarios u ON u.id = ch.id_usuario_creacion
                  LEFT JOIN LATERAL (
                       SELECT COALESCE(SUM(e.credito), 0) AS creditos, COALESCE(SUM(e.debito), 0) AS debitos,
                              COUNT(*) AS renglones, COUNT(ci.id) AS resueltos
                         FROM c_extractos_bancarios e
                         LEFT JOIN conciliacion_items ci ON ci.id_extracto = e.id AND ci.id_conciliacion = ch.id
                        WHERE e.c_cuentas_de_fondos_id = ch.id_cuenta AND e.fecham BETWEEN ch.fecha_desde AND ch.fecha_hasta
                  ) x ON TRUE
                 WHERE {' AND '.join(where)}
                 ORDER BY ch.periodo DESC, cf.nombre""", params)
            filas = cur.fetchall()
            for c in filas:
                if c["estado"] == "cerrado":
                    c["banco"] = float(c["saldo_banco"]) if c["saldo_banco"] is not None else None
                else:
                    c["banco"] = saldo_extracto_cierre(cur, c["id_cuenta"], c["fecha_desde"], c["fecha_hasta"])
                c["final"] = round(float(c["saldo_inicial"] or 0) + float(c["creditos"] or 0) - float(c["debitos"] or 0), 2)
                c["diferencia"] = round(c["final"] - c["banco"], 2) if c["banco"] is not None else None
                c["estado_txt"], c["estado_tipo"] = ESTADOS[c["estado"]]
            corte = fecha_corte(cur)
    # El mes pasado (el que se cierra con el extracto completo), pero nunca antes del corte.
    hoy = datetime.date.today()
    sugerido = (hoy.replace(day=1) - datetime.timedelta(days=1)).replace(day=1)
    if corte and sugerido < corte.replace(day=1):
        sugerido = corte.replace(day=1)
    return render_template("tesoreria/conc_lista.html", filas=filas, cuentas=cuentas, f_cuenta=f_cuenta,
                           ver_cerradas=ver_cerradas, cerradas=cerradas, corte=corte,
                           periodo_sugerido=sugerido.strftime("%Y-%m"))


@conc_bp.route("/saldo_inicial")
def saldo_inicial_json():
    salida = _guardia(api=True)
    if salida:
        return salida
    id_cuenta = request.args.get("cuenta", type=int)
    desde, hasta = _fecha(request.args.get("desde")), _fecha(request.args.get("hasta"))
    if not id_cuenta or not desde or not hasta:
        return jsonify(anterior=None, extracto=None, renglones=0)
    with get_connection() as conn:
        with conn.cursor() as cur:
            ant = _anterior_cerrada(cur, id_cuenta, desde)
            sugerido = saldo_extracto_apertura(cur, id_cuenta, desde, hasta)
            cierre = saldo_extracto_cierre(cur, id_cuenta, desde, hasta)
            cur.execute("""SELECT COUNT(*) AS n FROM c_extractos_bancarios
                            WHERE c_cuentas_de_fondos_id = %s AND fecham BETWEEN %s AND %s""", (id_cuenta, desde, hasta))
            renglones = int(cur.fetchone()["n"] or 0)
    return jsonify(anterior={"periodo": _periodo_txt(ant["periodo"]), "saldo": float(ant["saldo_final"])} if ant else None,
                   extracto=sugerido, cierre=cierre, renglones=renglones)


@conc_bp.route("/nueva", methods=["POST"])
def nueva():
    salida = _guardia()
    if salida:
        return salida
    id_cuenta = request.form.get("id_cuenta", type=int)
    periodo = (request.form.get("periodo") or "").replace("-", "").strip()[:6]
    desde, hasta = _fecha(request.form.get("fecha_desde")), _fecha(request.form.get("fecha_hasta"))
    if not (id_cuenta and len(periodo) == 6 and periodo.isdigit()):
        flash("!Elegí la cuenta y el período.")
        return redirect(url_for("conc.lista"))
    fin = fin_de_periodo(periodo)
    if not fin:
        flash("!El período no es válido.")
        return redirect(url_for("conc.lista"))
    desde = desde or fin.replace(day=1)
    hasta = hasta or fin
    if desde > hasta:
        flash("!La fecha desde es posterior a la fecha hasta.")
        return redirect(url_for("conc.lista"))
    with get_connection() as conn:
        with conn.cursor() as cur:
            corte = fecha_corte(cur)
            if corte and desde < corte:
                flash(f"!Se concilia desde el {corte:%d/%m/%Y}: lo anterior se da por conciliado. "
                      "Elegí un período que empiece ese día o después.")
                return redirect(url_for("conc.lista", cuenta=id_cuenta))
            cur.execute("SELECT id FROM c_cuentas_de_fondos WHERE id = %s AND tipo_de_cuenta = 'B'", (id_cuenta,))
            if not cur.fetchone():
                flash("!Solo se concilian cuentas bancarias.")
                return redirect(url_for("conc.lista"))
            cur.execute("""SELECT periodo FROM conciliacion_header
                            WHERE id_cuenta = %s AND (periodo = %s OR (fecha_desde <= %s AND fecha_hasta >= %s)) LIMIT 1""",
                        (id_cuenta, periodo, hasta, desde))
            choca = cur.fetchone()
            if choca:
                flash(f"!Ya hay una conciliación de esa cuenta que cubre esas fechas ({_periodo_txt(choca['periodo'])}). "
                      "Un renglón del extracto va en una sola conciliación.")
                return redirect(url_for("conc.lista", cuenta=id_cuenta))
            ant = _anterior_cerrada(cur, id_cuenta, desde)
            if ant:
                # El saldo inicial no es una decisión de quien la crea: es el
                # final del período anterior cerrado.
                saldo, manual, id_ant = float(ant["saldo_final"]), 0, ant["id"]
            else:
                saldo = leer_importe(request.form.get("saldo_inicial"))
                if saldo is None:
                    flash("!Es la primera conciliación de la cuenta: escribí el saldo inicial (el del banco al empezar el período).")
                    return redirect(url_for("conc.lista", cuenta=id_cuenta))
                manual, id_ant = 1, None
            banco = saldo_extracto_cierre(cur, id_cuenta, desde, hasta)
            cur.execute("""INSERT INTO conciliacion_header (id_cuenta, periodo, fecha_desde, fecha_hasta, saldo_inicial,
                                                            saldo_inicial_manual, id_conc_anterior, saldo_banco, estado,
                                                            id_usuario_creacion)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'abierto', %s)""",
                        (id_cuenta, periodo, desde, hasta, saldo, manual, id_ant, banco, _uid()))
            id_nuevo = cur.lastrowid
    flash(f"Conciliación {_periodo_txt(periodo)} creada con saldo inicial {_pesos(saldo)}"
          + (f" (el cierre de {_periodo_txt(ant['periodo'])})." if ant else "."))
    return redirect(url_for("conc.detalle", id_conc=id_nuevo))


# =============================================================================
# Detalle
# =============================================================================

@conc_bp.route("/<int:id_conc>")
def detalle(id_conc):
    salida = _guardia()
    if salida:
        return salida
    anteriores = request.args.get("anteriores") == "1"
    with get_connection() as conn:
        with conn.cursor() as cur:
            conc = _conc(cur, id_conc)
            if not conc:
                flash("!Esa conciliación no existe.")
                return redirect(url_for("conc.lista"))
            abierta = conc["estado"] != "cerrado"
            extracto = extracto_periodo(cur, conc)
            reglas = reglas_activas(cur)
            libro = libro_pendiente(cur, conc, anteriores) if abierta else []
            sug = sugerencias(extracto, libro) if abierta else {}
            grupos = grupos_a_generar(extracto, reglas, sug) if abierta else []
            tot = totales(cur, conc, extracto)

            # Con qué se concilió cada grupo.
            ids_grupo = sorted({m["id_grupo"] for m in extracto if m["id_grupo"]})
            por_grupo: dict = {}
            if ids_grupo:
                cur.execute(f"""SELECT id_grupo, id_debito_credito FROM conciliacion_comprobantes
                                 WHERE id_grupo IN ({','.join(['%s'] * len(ids_grupo))}) AND id_debito_credito IS NOT NULL""",
                            ids_grupo)
                filas_cc = cur.fetchall()
                lib = libro_por_ids(cur, sorted({f["id_debito_credito"] for f in filas_cc}))
                for f in filas_cc:
                    if f["id_debito_credito"] in lib:
                        por_grupo.setdefault(f["id_grupo"], []).append(lib[f["id_debito_credito"]])

            # Lo que está antes que este período y sigue abierto: bloquea el cierre.
            cur.execute("""SELECT periodo FROM conciliacion_header
                            WHERE id_cuenta = %s AND fecha_hasta < %s AND estado <> 'cerrado' ORDER BY periodo""",
                        (conc["id_cuenta"], conc["fecha_desde"]))
            previas_abiertas = [r["periodo"] for r in cur.fetchall()]
            cur.execute("""SELECT periodo FROM conciliacion_header
                            WHERE id_cuenta = %s AND fecha_desde > %s AND estado = 'cerrado' LIMIT 1""",
                        (conc["id_cuenta"], conc["fecha_hasta"]))
            posterior_cerrada = cur.fetchone()
            ant = _anterior_cerrada(cur, conc["id_cuenta"], conc["fecha_desde"])
            corte = corte_cuenta(cur, conc["id_cuenta"])
            cur.execute("""SELECT COALESCE(SUM(importe_debe - importe_haber), 0) AS s FROM c_movimientos_de_fondos
                            WHERE c_cuentas_de_fondosId = %s AND fecha <= %s AND fecha_anulacion IS NULL""",
                        (conc["id_cuenta"], conc["fecha_hasta"]))
            saldo_libro = float(cur.fetchone()["s"] or 0)

    for m in extracto:
        m["grupo"] = por_grupo.get(m["id_grupo"], [])
        m["sugerido"] = sug.get(m["id"])
        m["regla"] = (match_regla(m["concepto"], m["tipo"] == "D", m["tipo"] == "C", reglas)
                      if m["pendiente"] else None)
        if m["estado_item"] == "conciliado":
            m["filtro"] = "conciliado"
        elif m["estado_item"] == "excepcion":
            m["filtro"] = "excepcion"
        elif m["sugerido"]:
            m["filtro"] = "sugerido"
        elif m["regla"]:
            m["filtro"] = "clasificado"
        else:
            m["filtro"] = "pendiente"
    sugeridos_dc = {c["id_dc"]: (m_id, regla) for m_id, (c, regla) in sug.items()}
    for c in libro:
        c["sugerido_para"] = sugeridos_dc.get(c["id_dc"])

    # El saldo del libro ajustado por lo que el banco todavía no vio: si da el
    # saldo del banco, el libro y el extracto cuentan lo mismo. AEDA no tiene
    # saldos de apertura, así que hasta que se cargue un ajuste no va a dar:
    # es informativo, no bloquea el cierre.
    pend_cred = round(sum(float(c["credito"] or 0) for c in libro if c["fecha"] <= conc["fecha_hasta"]), 2)
    pend_deb = round(sum(float(c["debito"] or 0) for c in libro if c["fecha"] <= conc["fecha_hasta"]), 2)
    tot["libro"] = round(saldo_libro, 2)
    tot["libro_pend_cred"], tot["libro_pend_deb"] = pend_cred, pend_deb
    tot["libro_ajustado"] = round(saldo_libro - pend_cred + pend_deb, 2)
    conc["estado_txt"], conc["estado_tipo"] = ESTADOS[conc["estado"]]

    motivos_cierre = []
    if tot["pendientes"]:
        motivos_cierre.append(f"faltan {tot['pendientes']} renglones del extracto por conciliar o explicar")
    if previas_abiertas:
        motivos_cierre.append("antes hay que cerrar " + ", ".join(_periodo_txt(p) for p in previas_abiertas))
    if ant and abs(float(ant["saldo_final"]) - tot["inicial"]) > TOL:
        motivos_cierre.append(f"el saldo inicial no es el cierre de {_periodo_txt(ant['periodo'])} "
                              f"({_pesos(ant['saldo_final'])}): actualizalo")

    return render_template("tesoreria/conc_detalle.html", conc=conc, extracto=extracto, libro=libro, grupos=grupos,
                           tot=tot, abierta=abierta, anteriores=anteriores, reglas_sug=REGLAS_SUGERENCIA,
                           n_sugeridos=len(sug), motivos_cierre=motivos_cierre, anterior=ant, corte=corte,
                           posterior_cerrada=posterior_cerrada, es_admin=tiene_rol("Administrador"),
                           dias_anteriores=DIAS_ANTERIORES, puede_clasif=puede(URL_CLASIF),
                           puede_extractos=puede("/tesoreria/extractos"))


# =============================================================================
# Operaciones del detalle
# =============================================================================

def _abierta_o_aviso(cur, id_conc):
    conc = _conc(cur, id_conc, bloquear=True)
    if not conc:
        return None, "Esa conciliación no existe."
    if conc["estado"] == "cerrado":
        return None, "La conciliación está cerrada: para cambiarla hay que reabrirla."
    return conc, None


@conc_bp.route("/<int:id_conc>/vincular", methods=["POST"])
def vincular(id_conc):
    salida = _guardia()
    if salida:
        return salida
    ids_e, ids_l = _ids(request.form.getlist("ext")), _ids(request.form.getlist("dc"))
    obs = (request.form.get("observaciones") or "").strip()[:300] or None

    def hacer(cur):
        conc, error = _abierta_o_aviso(cur, id_conc)
        if error:
            return error
        ext, error = _validar_extracto(cur, conc, ids_e)
        if error:
            return error
        lib, error = _validar_libro(cur, conc, ids_l)
        if error:
            return error
        dif = round(sum(m["neto"] for m in ext) - sum(c["neto"] for c in lib), 2)
        if abs(dif) > TOL and not obs:
            return (f"El extracto suma {_pesos(sum(m['neto'] for m in ext))} y el libro {_pesos(sum(c['neto'] for c in lib))}: "
                    f"para vincular con {_pesos(dif)} de diferencia, escribí por qué.")
        _grabar_grupo(cur, conc, ext, lib, _uid(), obs)
        return None

    error = _transaccion(hacer)
    flash(f"!{error}" if error else f"Vinculados {len(ids_e)} renglón(es) del extracto con {len(ids_l)} del libro.")
    return _redir(id_conc)


@conc_bp.route("/<int:id_conc>/sugeridos", methods=["POST"])
def aceptar_sugeridos(id_conc):
    """Cada par sugerido es un grupo de uno contra uno. Se valida de nuevo
    contra la base: entre que se dibujó la pantalla y el clic, alguien pudo
    haber conciliado alguno."""
    salida = _guardia()
    if salida:
        return salida
    pares = []
    for p in request.form.getlist("par"):
        a, _, b = p.partition(":")
        if a.isdigit() and b.isdigit():
            pares.append((int(a), int(b)))

    def hacer(cur):
        conc, error = _abierta_o_aviso(cur, id_conc)
        if error:
            return 0, [error]
        hechos, saltados = 0, []
        for id_e, id_dc in pares:
            ext, e1 = _validar_extracto(cur, conc, [id_e])
            lib, e2 = _validar_libro(cur, conc, [id_dc])
            if e1 or e2 or abs(ext[0]["neto"] - lib[0]["neto"]) > TOL:
                saltados.append(id_e)
                continue
            _grabar_grupo(cur, conc, ext, lib, _uid(), None)
            hechos += 1
        return hechos, saltados

    hechos, saltados = _transaccion(hacer)
    if hechos:
        flash(f"{hechos} sugerencia(s) conciliadas.")
    if saltados:
        flash(f"!{len(saltados)} no se conciliaron: alguno de los dos lados ya no estaba disponible o no coincide el importe.")
    return _redir(id_conc)


@conc_bp.route("/<int:id_conc>/desvincular", methods=["POST"])
def desvincular(id_conc):
    salida = _guardia()
    if salida:
        return salida
    id_grupo = request.form.get("grupo", type=int)

    def hacer(cur):
        conc, error = _abierta_o_aviso(cur, id_conc)
        if error:
            return error
        cur.execute("SELECT id FROM conciliacion_grupos WHERE id = %s AND id_conciliacion = %s", (id_grupo, id_conc))
        if not cur.fetchone():
            return "Ese vínculo no es de esta conciliación."
        cur.execute("DELETE FROM conciliacion_comprobantes WHERE id_grupo = %s", (id_grupo,))
        cur.execute("DELETE FROM conciliacion_items WHERE id_grupo = %s AND id_conciliacion = %s", (id_grupo, id_conc))
        cur.execute("DELETE FROM conciliacion_grupos WHERE id = %s", (id_grupo,))
        return None

    error = _transaccion(hacer)
    flash(f"!{error}" if error else
          "Vínculo deshecho: los dos lados vuelven a pendientes. Si el comprobante se generó desde acá, sigue existiendo: "
          "se vuelve a conciliar o se anula en Tesorería → Anulaciones.")
    return _redir(id_conc)


@conc_bp.route("/<int:id_conc>/excepcion", methods=["POST"])
def excepcion(id_conc):
    salida = _guardia()
    if salida:
        return salida
    ids_e = _ids(request.form.getlist("ext"))
    obs = (request.form.get("observaciones") or "").strip()[:300]

    def hacer(cur):
        if not obs:
            return "Escribí por qué el renglón no tiene contraparte en el libro."
        conc, error = _abierta_o_aviso(cur, id_conc)
        if error:
            return error
        ext, error = _validar_extracto(cur, conc, ids_e)
        if error:
            return error
        for m in ext:
            cur.execute("""INSERT INTO conciliacion_items (id_conciliacion, id_extracto, tipo_interno, estado, origen,
                                                           id_usuario, observaciones)
                           VALUES (%s, %s, 'excepcion', 'excepcion', 'manual', %s, %s)""", (id_conc, m["id"], _uid(), obs))
        if conc["estado"] == "abierto":
            cur.execute("UPDATE conciliacion_header SET estado = 'en_proceso' WHERE id = %s", (id_conc,))
        return None

    error = _transaccion(hacer)
    flash(f"!{error}" if error else f"{len(ids_e)} renglón(es) marcados como excepción.")
    return _redir(id_conc)


@conc_bp.route("/<int:id_conc>/excepcion/quitar", methods=["POST"])
def excepcion_quitar(id_conc):
    salida = _guardia()
    if salida:
        return salida
    id_item = request.form.get("item", type=int)

    def hacer(cur):
        conc, error = _abierta_o_aviso(cur, id_conc)
        if error:
            return error
        cur.execute("DELETE FROM conciliacion_items WHERE id = %s AND id_conciliacion = %s AND estado = 'excepcion'",
                    (id_item, id_conc))
        return None if cur.rowcount else "Esa excepción no existe."

    error = _transaccion(hacer)
    flash(f"!{error}" if error else "Excepción quitada: el renglón vuelve a pendiente.")
    return _redir(id_conc)


@conc_bp.route("/<int:id_conc>/generar", methods=["POST"])
def generar(id_conc):
    """Los comprobantes de los conceptos clasificados que generan, uno por
    grupo y cada grupo en su transacción: si uno falla (un período contable
    cerrado, una cuenta deshabilitada) los demás se generan igual y el que
    falló se informa."""
    salida = _guardia()
    if salida:
        return salida
    elegidas = set(request.form.getlist("clave"))
    if not elegidas:
        flash("!Tildá al menos un comprobante para generar.")
        return _redir(id_conc)
    with get_connection() as conn:
        with conn.cursor() as cur:
            conc = _conc(cur, id_conc)
            if not conc or conc["estado"] == "cerrado":
                flash("!La conciliación está cerrada o no existe.")
                return _redir(id_conc)
            extracto = extracto_periodo(cur, conc)
            reglas = reglas_activas(cur)
            grupos = [g for g in grupos_a_generar(extracto, reglas, {}) if g["clave"] in elegidas]

    hechos, fallas = [], []
    for g in grupos:
        def hacer(cur, g=g):
            c, error = _abierta_o_aviso(cur, id_conc)
            if error:
                raise ValueError(error)
            fuera = anulaciones._fuera_de_periodo(cur, g["fecha"])
            if fuera:
                raise ValueError(fuera)
            ext, error = _validar_extracto(cur, c, [m["id"] for m in g["filas"]])
            if error:
                raise ValueError(error)
            return _generar_uno(cur, c, g, _uid())
        try:
            hechos.append(_transaccion(hacer))
        except ValueError as e:
            fallas.append(f"{g['nombre']} ({g['fecha']:%d/%m/%Y}): {e}")
        except Exception as e:                               # noqa: BLE001 — se informa por grupo
            log.exception("Conciliación %s: no se pudo generar %s", id_conc, g["clave"])
            fallas.append(f"{g['nombre']} ({g['fecha']:%d/%m/%Y}): {e}")
    if hechos:
        flash(f"{len(hechos)} comprobante(s) generados y conciliados: " + "; ".join(hechos[:8])
              + ("…" if len(hechos) > 8 else "") + ".")
    for f in fallas[:8]:
        flash(f"!No se generó {f}")
    if not hechos and not fallas:
        flash("!No había nada para generar: puede que alguien ya los haya generado.")
    return _redir(id_conc)


@conc_bp.route("/<int:id_conc>/saldo_inicial", methods=["POST"])
def cambiar_saldo_inicial(id_conc):
    salida = _guardia()
    if salida:
        return salida

    def hacer(cur):
        conc, error = _abierta_o_aviso(cur, id_conc)
        if error:
            return error, None
        ant = _anterior_cerrada(cur, conc["id_cuenta"], conc["fecha_desde"])
        if ant:
            saldo, manual, id_ant = float(ant["saldo_final"]), 0, ant["id"]
        else:
            saldo = leer_importe(request.form.get("saldo_inicial"))
            if saldo is None:
                return "Escribí el saldo inicial.", None
            manual, id_ant = 1, None
        cur.execute("""UPDATE conciliacion_header SET saldo_inicial = %s, saldo_inicial_manual = %s, id_conc_anterior = %s
                        WHERE id = %s""", (saldo, manual, id_ant, id_conc))
        return None, (saldo, ant)

    error, res = _transaccion(hacer)
    if error:
        flash(f"!{error}")
    else:
        saldo, ant = res
        flash(f"Saldo inicial: {_pesos(saldo)}" + (f", el cierre de {_periodo_txt(ant['periodo'])}." if ant else "."))
    return _redir(id_conc)


@conc_bp.route("/<int:id_conc>/cerrar", methods=["POST"])
def cerrar(id_conc):
    salida = _guardia()
    if salida:
        return salida
    banco_form = leer_importe(request.form.get("saldo_banco"))

    def hacer(cur):
        conc, error = _abierta_o_aviso(cur, id_conc)
        if error:
            return error
        extracto = extracto_periodo(cur, conc)
        tot = totales(cur, conc, extracto)
        if tot["pendientes"]:
            return f"Faltan {tot['pendientes']} renglones del extracto por conciliar o marcar como excepción."
        cur.execute("""SELECT periodo FROM conciliacion_header WHERE id_cuenta = %s AND fecha_hasta < %s
                         AND estado <> 'cerrado' LIMIT 1""", (conc["id_cuenta"], conc["fecha_desde"]))
        previa = cur.fetchone()
        if previa:
            return f"Antes hay que cerrar la conciliación {_periodo_txt(previa['periodo'])} de la cuenta."
        ant = _anterior_cerrada(cur, conc["id_cuenta"], conc["fecha_desde"])
        if ant and abs(float(ant["saldo_final"]) - tot["inicial"]) > TOL:
            return (f"El saldo inicial ({_pesos(tot['inicial'])}) no es el cierre de {_periodo_txt(ant['periodo'])} "
                    f"({_pesos(ant['saldo_final'])}): actualizalo antes de cerrar.")
        banco = banco_form if banco_form is not None else tot["banco"]
        if banco is None:
            return "Escribí el saldo final que informa el banco: el extracto de estas fechas no lo trae."
        if abs(tot["final"] - banco) > TOL:
            return (f"El saldo final calculado ({_pesos(tot['final'])}) no da el del banco ({_pesos(banco)}): "
                    f"hay {_pesos(tot['final'] - banco)} de diferencia. Falta importar renglones del extracto o el saldo "
                    "inicial no es el del banco.")
        cur.execute("""UPDATE conciliacion_header
                          SET estado = 'cerrado', total_creditos = %s, total_debitos = %s, saldo_final = %s,
                              saldo_banco = %s, fecha_cierre = NOW(), id_usuario_cierre = %s
                        WHERE id = %s""", (tot["creditos"], tot["debitos"], tot["final"], banco, _uid(), id_conc))
        cur.execute("""UPDATE c_extractos_bancarios SET conciliado = 1, id_conciliacion = %s
                        WHERE c_cuentas_de_fondos_id = %s AND fecham BETWEEN %s AND %s""",
                    (id_conc, conc["id_cuenta"], conc["fecha_desde"], conc["fecha_hasta"]))
        return None

    error = _transaccion(hacer)
    flash(f"!{error}" if error else "Conciliación cerrada. Su saldo final es el inicial de la próxima.")
    return _redir(id_conc)


@conc_bp.route("/<int:id_conc>/reabrir", methods=["POST"])
def reabrir(id_conc):
    salida = _guardia()
    if salida:
        return salida
    if not tiene_rol("Administrador"):
        flash("!Reabrir una conciliación cerrada es una acción de Administrador.")
        return _redir(id_conc)
    motivo = (request.form.get("motivo") or "").strip()

    def hacer(cur):
        if not motivo:
            return "Escribí por qué se reabre."
        conc = _conc(cur, id_conc, bloquear=True)
        if not conc or conc["estado"] != "cerrado":
            return "La conciliación no está cerrada."
        cur.execute("""SELECT periodo FROM conciliacion_header WHERE id_cuenta = %s AND fecha_desde > %s
                         AND estado = 'cerrado' LIMIT 1""", (conc["id_cuenta"], conc["fecha_hasta"]))
        post = cur.fetchone()
        if post:
            return f"No se reabre: la conciliación {_periodo_txt(post['periodo'])}, posterior, está cerrada y arranca de este saldo."
        nota = f"[{datetime.datetime.now():%d/%m/%Y %H:%M}] Reabierta: {motivo}"
        cur.execute("""UPDATE conciliacion_header SET estado = 'en_proceso', fecha_cierre = NULL, id_usuario_cierre = NULL,
                              observaciones = CONCAT_WS('\n', observaciones, %s)
                        WHERE id = %s""", (nota, id_conc))
        cur.execute("UPDATE c_extractos_bancarios SET conciliado = 0, id_conciliacion = NULL WHERE id_conciliacion = %s",
                    (id_conc,))
        return None

    error = _transaccion(hacer)
    flash(f"!{error}" if error else "Conciliación reabierta.")
    return _redir(id_conc)


@conc_bp.route("/<int:id_conc>/eliminar", methods=["POST"])
def eliminar(id_conc):
    salida = _guardia()
    if salida:
        return salida

    def hacer(cur):
        conc = _conc(cur, id_conc, bloquear=True)
        if not conc:
            return "Esa conciliación no existe."
        if conc["estado"] == "cerrado":
            return "Una conciliación cerrada no se elimina."
        cur.execute("SELECT COUNT(*) AS n FROM conciliacion_items WHERE id_conciliacion = %s", (id_conc,))
        if cur.fetchone()["n"]:
            return "Tiene renglones conciliados o con excepción: primero hay que deshacerlos."
        cur.execute("DELETE FROM conciliacion_grupos WHERE id_conciliacion = %s", (id_conc,))
        cur.execute("DELETE FROM conciliacion_header WHERE id = %s", (id_conc,))
        return None

    error = _transaccion(hacer)
    if error:
        flash(f"!{error}")
        return _redir(id_conc)
    flash("Conciliación eliminada.")
    return redirect(url_for("conc.lista"))


# =============================================================================
# Clasificación de conceptos (menú 73)
# =============================================================================

@conc_bp.route("/clasificar")
def clasificar():
    salida = _guardia(URL_CLASIF)
    if salida:
        return salida
    id_cuenta = request.args.get("cuenta", type=int)
    desde, hasta = _fecha(request.args.get("desde")), _fecha(request.args.get("hasta"))
    conceptos = []
    with get_connection() as conn:
        with conn.cursor() as cur:
            cuentas = _cuentas_banco(cur)
            if not id_cuenta and cuentas:
                id_cuenta = cuentas[0]["id"]
            if id_cuenta and not (desde and hasta):
                cur.execute("SELECT MAX(fecham) AS f FROM c_extractos_bancarios WHERE c_cuentas_de_fondos_id = %s",
                            (id_cuenta,))
                ultima = (cur.fetchone() or {}).get("f") or datetime.date.today()
                desde, hasta = desde or ultima.replace(day=1), hasta or ultima
            reglas = reglas_activas(cur)
            if id_cuenta:
                cur.execute("""SELECT concepto, debito, credito FROM c_extractos_bancarios
                                WHERE c_cuentas_de_fondos_id = %s AND fecham BETWEEN %s AND %s""",
                            (id_cuenta, desde, hasta))
                agrup: "OrderedDict[str, dict]" = OrderedDict()
                for e in cur.fetchall():
                    base = concepto_base(e["concepto"])
                    c = agrup.setdefault(base.upper(), {"base": base, "debitos": 0, "creditos": 0, "imp_deb": 0.0,
                                                        "imp_cred": 0.0, "ejemplo": e["concepto"]})
                    if e["debito"]:
                        c["debitos"] += 1; c["imp_deb"] += float(e["debito"])
                    if e["credito"]:
                        c["creditos"] += 1; c["imp_cred"] += float(e["credito"])
                for c in agrup.values():
                    c["tipo_mov"] = "M" if c["debitos"] and c["creditos"] else ("D" if c["debitos"] else "C")
                    r = match_regla(c["base"], c["tipo_mov"] != "C", c["tipo_mov"] != "D", reglas)
                    c["regla"] = r
                    # La regla es de este concepto si su patrón es el concepto; si no,
                    # lo está tomando una regla más general (otro concepto que lo contiene).
                    c["propia"] = bool(r and (r["patron_texto"] or "").strip().upper() == c["base"].upper())
                    c["cant"] = c["debitos"] + c["creditos"]
                conceptos = sorted(agrup.values(), key=lambda c: (c["regla"] is not None, -c["cant"], c["base"]))
            cur.execute("SELECT id, descripcion FROM c_concepto_de_gastos WHERE COALESCE(activo, 1) = 1 ORDER BY descripcion")
            gastos = cur.fetchall()
            cur.execute("SELECT id, descripcion FROM c_motivos_de_ingreso WHERE activo = 1 ORDER BY descripcion")
            motivos = cur.fetchall()
            cur.execute("""SELECT id, nombre FROM c_cuentas_de_fondos WHERE habilitada = 1 AND tipo_de_cuenta <> 'I'
                            ORDER BY nombre""")
            destinos = cur.fetchall()
            cur.execute("SELECT id_regla, COUNT(*) AS n FROM conciliacion_items WHERE id_regla IS NOT NULL GROUP BY id_regla")
            usos = {r["id_regla"]: r["n"] for r in cur.fetchall()}
    for r in reglas:
        r["usos"] = usos.get(r["id"], 0)
    return render_template("tesoreria/conc_clasificar.html", cuentas=cuentas, id_cuenta=id_cuenta, desde=desde,
                           hasta=hasta, conceptos=conceptos, reglas=reglas, gastos=gastos, motivos=motivos,
                           destinos=destinos, tipos=TIPOS_REGLA)


@conc_bp.route("/clasificar/guardar", methods=["POST"])
def clasificar_guardar():
    salida = _guardia(URL_CLASIF, api=True)
    if salida:
        return salida
    d = request.get_json(silent=True) or {}
    base = (d.get("concepto") or "").strip()[:200]
    tipo = (d.get("tipo_resultado") or "").strip()
    tipo_mov = {"D": "debito", "C": "credito"}.get(d.get("tipo_mov"), "ambos")

    def _int(v):
        return int(v) if str(v or "").isdigit() else None

    id_cg = _int(d.get("id_concepto_gasto")) if tipo == "concepto_gasto" else None
    id_mi = _int(d.get("id_motivo_ingreso")) if tipo == "motivo_ingreso" else None
    id_cd = _int(d.get("id_cuenta_destino")) if tipo == "movimiento_cuentas" else None
    genera = 1 if d.get("genera_op") and tipo in ("concepto_gasto", "motivo_ingreso", "movimiento_cuentas") else 0
    agrupa = 1 if d.get("agrupa_por_fecha") else 0
    if not base:
        return jsonify(error="Falta el concepto."), 400
    if tipo not in TIPOS_REGLA:
        return jsonify(error="Elegí qué es el concepto."), 400
    if tipo == "concepto_gasto" and not id_cg:
        return jsonify(error="Elegí el concepto de gasto."), 400
    if tipo == "motivo_ingreso" and not id_mi:
        return jsonify(error="Elegí el motivo de ingreso."), 400
    if tipo == "movimiento_cuentas" and not id_cd:
        return jsonify(error="Elegí la otra cuenta."), 400

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Una sola regla por patrón: si ya hubo una (activa o quitada) se
            # actualiza esa. Dos con el mismo patrón se pisarían y ganaría la
            # que nadie eligió.
            cur.execute("""SELECT id FROM conc_reglas WHERE tipo_patron = 'contiene'
                              AND UPPER(TRIM(patron_texto)) = UPPER(TRIM(%s)) ORDER BY activa DESC, id DESC LIMIT 1""",
                        (base,))
            previa = cur.fetchone()
            if previa:
                cur.execute("""UPDATE conc_reglas SET nombre = %s, tipo_movimiento = %s, tipo_resultado = %s,
                                      id_concepto_gasto = %s, id_motivo_ingreso = %s, id_cuenta_destino = %s,
                                      genera_op = %s, agrupa_por_fecha = %s, activa = 1
                                WHERE id = %s""",
                            (base[:100], tipo_mov, tipo, id_cg, id_mi, id_cd, genera, agrupa, previa["id"]))
                id_regla = previa["id"]
            else:
                cur.execute("""INSERT INTO conc_reglas (nombre, patron_texto, tipo_patron, tipo_movimiento, tipo_resultado,
                                                        id_concepto_gasto, id_motivo_ingreso, id_cuenta_destino, genera_op,
                                                        agrupa_por_fecha, orden, activa)
                               VALUES (%s, %s, 'contiene', %s, %s, %s, %s, %s, %s, %s, 10, 1)""",
                            (base[:100], base, tipo_mov, tipo, id_cg, id_mi, id_cd, genera, agrupa))
                id_regla = cur.lastrowid
            cur.execute("""SELECT r.*, cg.descripcion AS nombre_concepto, mi.descripcion AS nombre_motivo,
                                  cd.nombre AS nombre_destino
                             FROM conc_reglas r
                             LEFT JOIN c_concepto_de_gastos cg ON cg.id = r.id_concepto_gasto
                             LEFT JOIN c_motivos_de_ingreso mi ON mi.id = r.id_motivo_ingreso
                             LEFT JOIN c_cuentas_de_fondos cd ON cd.id = r.id_cuenta_destino
                            WHERE r.id = %s""", (id_regla,))
            r = cur.fetchone()
    return jsonify(ok=True, id_regla=id_regla, texto=texto_regla(r))


@conc_bp.route("/clasificar/quitar", methods=["POST"])
def clasificar_quitar():
    """Desactiva, no borra: `conciliacion_items.id_regla` guarda con qué regla
    se generó cada comprobante ya conciliado, y eso es historia."""
    salida = _guardia(URL_CLASIF, api=True)
    if salida:
        return salida
    d = request.get_json(silent=True) or {}
    id_regla = int(d["id_regla"]) if str(d.get("id_regla") or "").isdigit() else None
    if not id_regla:
        return jsonify(error="Falta la regla."), 400
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE conc_reglas SET activa = 0 WHERE id = %s", (id_regla,))
            if not cur.rowcount:
                cur.execute("SELECT id FROM conc_reglas WHERE id = %s", (id_regla,))
                if not cur.fetchone():
                    return jsonify(error="La regla no existe."), 404
    return jsonify(ok=True)
