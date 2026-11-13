"""
fisca_recibos.py — Fiscalización de Cuotas › Emisión de Recibos (menú 8).

    /fiscalizacion/recibos                        las acreditaciones de una cuenta: ?cuenta, ?desde, ?hasta
    /fiscalizacion/recibos/emitir/<id_extracto>   GET el formulario (?cuit= elige otro empleador); POST emite
    /fiscalizacion/recibos/emitir_lote            POST extracto=… los tildados, con lo que sugiere la pantalla
    /fiscalizacion/recibos/<id_orden>             el recibo
    /fiscalizacion/recibos/<id_orden>/pdf         el recibo en PDF
    /fiscalizacion/recibos/relacion               POST alta de un CUIT que paga por un empleador
    /fiscalizacion/recibos/relacion/<id>/baja     POST

Pedido del 12/11/2026: los recibos de cuota sindical salen del extracto
bancario. Se elige la cuenta del banco y cada acreditación se relaciona con su
empleador por el CUIT que informa el banco.

EL EMPLEADOR (`resolver_empleador`)
- El mismo CUIT: el que pagó es un empleador de Empleadores.
- Un CUIT relacionado (`fisca_cuit_relacionado`): el estudio contable, el dueño
  o la otra empresa del grupo que paga por él. Se cargan en la misma pantalla
  —o al emitir, con «Recordar»— y las de AEDA (afi_empresas_rel) vinieron con
  sql/fisca_recibos_20261112.sql. Un pagador puede pagar por varios empleadores:
  entonces se elige al emitir.
- Un afiliado con relación laboral vigente con un solo empleador: queda como
  sugerencia y no se emite en lote. Muchas transferencias de CUIL son la cuota
  de la persona, no la de su empleador.

EL RECIBO
Es una orden de ingreso (`ingreso_ordenes`) de clase «cuota_sindical» y origen
«extracto», con la fecha de la acreditación, a la cuenta del extracto, y un
renglón por período (`ingreso_ordenes_detalle`, motivo CUOTA SINDICAL, con el
CUIT del empleador y `id_extracto_origen`). La descripción repite el formato de
los cobros de AEDA («CUOTA SINDICAL 2026-10 · RAZÓN (CUIT …)»), que es el que lee
la conciliación. Deja su renglón en el libro (`movimientos_fondos`), y si la
cuenta tiene una conciliación abierta que incluye la fecha, queda conciliado con
la acreditación en el acto, como lo que genera la conciliación. Se anula en
Tesorería → Anulaciones; anulado, la acreditación vuelve a quedar sin recibo.

LOS PERÍODOS (`distribuir`)
El pago es del mes anterior a la acreditación (la cuota vence el 20 del mes
siguiente). Si el importe es exactamente el saldo de un período, va a ese. Si
no, al mes anterior hasta su saldo y lo que sobra a la deuda más vieja (lo
decidido para aplicar cobros); lo que todavía sobra, o todo si el mes anterior
no está liquidado, queda en ese mes («pago sin liquidar»), sin saldo a favor.
Saldo = lo liquidado vigente (`fisca_liquidacion`) − lo cobrado del CUIT y el
período (`ingreso_ordenes_detalle.cuit`). Al emitir se puede cambiar todo.

¿YA TIENE RECIBO? (`emparejar`)
Mientras AEDA siga cobrando, lo que AEDA ya registró entra por
importar_aeda_fondos.py como «AEDA-RC-…»: esa acreditación ya tiene su recibo y
no se emite otro. Se reconoce, de la más segura a la menos: el recibo emitido
desde el renglón; el número de comprobante de AEDA («comprobante 4315666» es la
referencia del banco) con el importe; el CUIT (el del banco o el del empleador)
con el importe a 15 días o menos; y como «¿ya tiene?», el único con esa fecha e
importe de los dos lados. Un renglón del libro sirve a una sola acreditación.
"""

from __future__ import annotations

import datetime
import logging
import re
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from flask import Blueprint, flash, redirect, render_template, request, url_for
from xml.sax.saxutils import escape

import conciliacion
import movimientos_fondos as mf
from db import get_connection, puede, usuario_actual, validasesion
from empleadores import cuit_valido
from numeracion import proximo_numero
from pagos_datos import leer_importe
from tesoreria_movimientos import _fecha_valida

log = logging.getLogger(__name__)

fisca_rec_bp = Blueprint("fisca_rec", __name__, url_prefix="/fiscalizacion")

URL = "/fiscalizacion/recibos"
SQL_ESQUEMA = "sql/fisca_recibos_20261112.sql"
MOTIVO_CUOTA = "CUOTA SINDICAL"
CENT = Decimal("0.01")
#: Cuántos días se busca, alrededor de la acreditación, el recibo ya registrado por CUIT e importe.
DIAS_VENTANA = 15
#: Acreditaciones que trae la grilla como máximo.
TOPE = 5000
#: Recibos de una sola vez desde la grilla.
MAX_LOTE = 500

COMO = {
    "mismo":       ("Mismo CUIT", "ok"),
    "relacionado": ("CUIT relacionado", "info"),
    "afiliado":    ("Afiliado del empleador", "warn"),
    "varios":      ("Varios posibles", "warn"),
    "sin":         ("Sin identificar", "danger"),
}
#: Con estos el empleador es seguro: se emite en lote.
COMO_SEGURO = ("mismo", "relacionado")

ESTADOS = {
    "pendiente":  ("Sin recibo", "warn"),
    "emitido":    ("Recibo emitido", "ok"),
    "ya_tiene":   ("Ya tiene recibo", "info"),
    "posible":    ("¿Ya tiene recibo?", "warn"),
    "conciliado": ("Conciliado", "neutro"),
    "otro":       ("Otro ingreso", "neutro"),
}
#: Estados desde los que se puede emitir (a mano).
EMITIBLES = ("pendiente", "posible", "otro")


class ErrorRecibo(ValueError):
    """Un error de validación: el texto va directo a la pantalla."""


# =============================================================================
# Comunes
# =============================================================================

def _d(v) -> Decimal:
    try:
        return Decimal(str(v if v is not None else 0)).quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return Decimal("0.00")


def digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def pesos(v) -> str:
    entero, _, dec = f"{float(v or 0):,.2f}".partition(".")
    return f"$ {entero.replace(',', '.')},{dec}"


def periodo_txt(p) -> str:
    p = str(p or "")
    return f"{p[:4]}-{p[4:]}" if len(p) == 6 else p


def periodo_anterior(fecha: datetime.date) -> str:
    """El período que se paga con una acreditación de esa fecha: el mes anterior."""
    return (fecha.replace(day=1) - datetime.timedelta(days=1)).strftime("%Y%m")


def periodo_de_form(texto) -> str | None:
    """«2026-10» (input month) o «202610» → «202610»."""
    t = digitos(texto)
    if len(t) == 6 and 1 <= int(t[4:]) <= 12 and 2000 <= int(t[:4]) <= 2100:
        return t
    return None


def _meses(p: str) -> int:
    return int(p[:4]) * 12 + int(p[4:]) - 1


def _fecha(texto) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat((texto or "").strip())
    except ValueError:
        return None


def _uid():
    return (usuario_actual() or {}).get("id")


def _guardia():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede(URL):
        flash("!No tenés permiso para la emisión de recibos.")
        return redirect(url_for("menu"))
    return None


#: Lo que la pantalla necesita de la base, y el script que lo crea. En Railway
#: los scripts se corren a mano: sin esto, uno que falta es un 500 sin explicación.
ESQUEMA = [
    ("c_extractos_bancarios", "id", "sql/conciliacion_bancaria_20261111.sql"),
    ("conc_reglas", "id_cuenta_destino", "sql/conciliacion_bancaria_20261111.sql"),
    ("conciliacion_comprobantes", "id_debito_credito", "sql/conciliacion_bancaria_20261111.sql"),
    ("conciliacion_items", "id_grupo", "sql/conciliacion_bancaria_20261111.sql"),
    ("fisca_liquidacion", "afiliados_activos", "sql/fisca_liquidacion_ddjj_20261112.sql"),
    ("ingreso_ordenes_detalle", "cuit", SQL_ESQUEMA),
    ("fisca_cuit_relacionado", "cuit_pagador", SQL_ESQUEMA),
]


def falta_esquema(cur) -> list[str]:
    """Los scripts que faltan correr en esta base (vacío si está todo)."""
    cur.execute("""SELECT CONCAT(table_name, '.', column_name) AS c FROM information_schema.columns
                    WHERE table_schema = DATABASE()""")
    hay = {f["c"].lower() for f in cur.fetchall()}
    faltan = []
    for tabla, columna, script in ESQUEMA:
        if f"{tabla}.{columna}".lower() not in hay and script not in faltan:
            faltan.append(script)
    cur.execute("""SELECT column_type AS column_type FROM information_schema.columns WHERE table_schema = DATABASE()
                    AND table_name = 'ingreso_ordenes' AND column_name = 'clase'""")
    r = cur.fetchone()
    if (not r or "cuota_sindical" not in (r["column_type"] or "")) and SQL_ESQUEMA not in faltan:
        faltan.append(SQL_ESQUEMA)
    return faltan


def _aviso_esquema(faltan) -> None:
    flash("!Faltan correr en esta base: " + ", ".join(faltan) + ". Hasta entonces no se emiten recibos.")


# =============================================================================
# El importe en letras
# =============================================================================

_UNIDADES = ["", "UNO", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE", "DIEZ", "ONCE",
             "DOCE", "TRECE", "CATORCE", "QUINCE", "DIECISÉIS", "DIECISIETE", "DIECIOCHO", "DIECINUEVE", "VEINTE",
             "VEINTIUNO", "VEINTIDÓS", "VEINTITRÉS", "VEINTICUATRO", "VEINTICINCO", "VEINTISÉIS", "VEINTISIETE",
             "VEINTIOCHO", "VEINTINUEVE"]
_DECENAS = {3: "TREINTA", 4: "CUARENTA", 5: "CINCUENTA", 6: "SESENTA", 7: "SETENTA", 8: "OCHENTA", 9: "NOVENTA"}
_CENTENAS = ["", "CIENTO", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS", "SEISCIENTOS",
             "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS"]


def _hasta_999(n: int, apocope: bool) -> str:
    """1 a 999. Con `apocope` (antes de MIL o MILLONES): UN, VEINTIÚN, Y UN."""
    if n == 100:
        return "CIEN"
    c, r = divmod(n, 100)
    partes = [_CENTENAS[c]] if c else []
    if r:
        if r < 30:
            t = _UNIDADES[r]
        else:
            d, u = divmod(r, 10)
            t = _DECENAS[d] + (f" Y {_UNIDADES[u]}" if u else "")
        if apocope and r % 10 == 1 and r != 11:
            t = "VEINTIÚN" if r == 21 else t[:-1]
        partes.append(t)
    return " ".join(partes)


def _hasta_999999(n: int, apocope: bool) -> str:
    miles, resto = divmod(n, 1000)
    partes = []
    if miles:
        partes.append("MIL" if miles == 1 else _hasta_999(miles, True) + " MIL")
    if resto:
        partes.append(_hasta_999(resto, apocope))
    return " ".join(partes)


def en_letras(importe) -> str:
    """«CUATROCIENTOS CUARENTA Y OCHO MIL CIENTO CINCUENTA Y SEIS CON 31/100»."""
    v = _d(importe)
    entero = int(v)
    centavos = int((v - entero) * 100)
    if entero == 0:
        texto = "CERO"
    else:
        millones, resto = divmod(entero, 1_000_000)
        partes = []
        if millones:
            partes.append("UN MILLÓN" if millones == 1 else _hasta_999999(millones, True) + " MILLONES")
        if resto:
            partes.append(_hasta_999999(resto, False))
        texto = " ".join(partes)
    return f"{texto} CON {centavos:02d}/100"


# =============================================================================
# Lógica (sin base): empleador, períodos, recibos ya registrados
# =============================================================================

def resolver_empleador(cuit_banco, empresas: dict, relaciones: dict, afiliados: dict) -> dict:
    """De quién es el pago. `empresas`: CUIT → razón social; `relaciones`:
    pagador → [CUIT de empleadores]; `afiliados`: CUIL → [CUIT de empleadores
    con relación vigente]. Devuelve cuit, razon, como y las opciones."""
    c = digitos(cuit_banco)
    sin = {"cuit": None, "razon": None, "como": "sin", "opciones": []}
    if len(c) != 11:
        return sin
    if c in empresas:
        return {"cuit": c, "razon": empresas[c], "como": "mismo", "opciones": []}
    for clave, fuente in (("relacionado", relaciones), ("afiliado", afiliados)):
        cand = sorted({e for e in fuente.get(c, ()) if e in empresas})
        if len(cand) == 1:
            return {"cuit": cand[0], "razon": empresas[cand[0]], "como": clave, "opciones": []}
        if cand:
            return {"cuit": None, "razon": None, "como": "varios",
                    "opciones": [{"cuit": e, "razon": empresas[e], "como": clave} for e in cand]}
    return sin


def distribuir(importe, fecha: datetime.date, saldos: dict) -> list[tuple[str, Decimal]]:
    """En qué períodos va el pago. `saldos`: período → saldo de los
    liquidados (puede ser cero o negativo). Ver el encabezado del módulo."""
    imp = _d(importe)
    p_mes = periodo_anterior(fecha)
    if imp <= 0:
        return []
    exactos = [p for p, s in saldos.items() if _d(s) > 0 and abs(_d(s) - imp) < CENT]
    if exactos:
        exactos.sort(key=lambda p: (abs(_meses(p) - _meses(p_mes)), p))
        return [(exactos[0], imp)]
    if p_mes not in saldos:
        return [(p_mes, imp)]
    resto, out = imp, defaultdict(Decimal)
    a = min(resto, max(_d(saldos[p_mes]), Decimal("0")))
    if a > 0:
        out[p_mes] += a
        resto -= a
    for p in sorted(saldos):
        if resto <= 0:
            break
        if p >= p_mes or _d(saldos[p]) <= 0:
            continue
        a = min(resto, _d(saldos[p]))
        out[p] += a
        resto -= a
    if resto > 0:
        out[p_mes] += resto
    return sorted(out.items())


def emparejar(creditos: list[dict], emitidos: dict, libro: list[dict]) -> None:
    """Marca en cada acreditación (`estado`, `recibo`) si ya tiene su recibo.

    `creditos`: los renglones del extracto con id, ref_nro, fecham, importe
    (Decimal), cuits (los CUIT con que se la puede reconocer) y estado (los que
    no son «pendiente» no se emparejan). `emitidos`: id_extracto → el recibo
    emitido desde ese renglón. `libro`: los ingresos de la cuenta con id_dc,
    id_orden, nro_orden, fecha, importe, cuit, ref_aeda, conciliado.
    """
    usados_orden = {r["id_orden"] for r in emitidos.values()}
    libres = [r for r in libro if not r["conciliado"] and r["id_orden"] not in usados_orden]
    tomados: set = set()

    def pend():
        return [c for c in creditos if c["estado"] == "pendiente"]

    def tomar(c, r, estado):
        c["estado"], c["recibo"] = estado, r
        tomados.add(r["id_dc"])

    for c in creditos:
        if c["id"] in emitidos:
            c["estado"], c["recibo"] = "emitido", emitidos[c["id"]]

    # El número de comprobante de AEDA es la referencia del banco.
    por_ref = defaultdict(list)
    for r in libres:
        if r.get("ref_aeda"):
            por_ref[r["ref_aeda"]].append(r)
    for c in pend():
        ref = digitos(c["ref_nro"]).lstrip("0")
        cand = [r for r in por_ref.get(ref, ()) if r["id_dc"] not in tomados and abs(r["importe"] - c["importe"]) < CENT]
        if cand:
            cand.sort(key=lambda r: abs((r["fecha"] - c["fecham"]).days))
            tomar(c, cand[0], "ya_tiene")

    # El CUIT con el importe, cerca de la fecha. Dos igual de cerca: no se elige.
    for c in pend():
        cand = [r for r in libres if r["id_dc"] not in tomados and r.get("cuit") in c["cuits"]
                and abs(r["importe"] - c["importe"]) < CENT and abs((r["fecha"] - c["fecham"]).days) <= DIAS_VENTANA]
        if not cand:
            continue
        cand.sort(key=lambda r: abs((r["fecha"] - c["fecham"]).days))
        if len(cand) > 1 and abs((cand[0]["fecha"] - c["fecham"]).days) == abs((cand[1]["fecha"] - c["fecham"]).days):
            continue
        tomar(c, cand[0], "ya_tiene")

    # Lo único con esa fecha e importe de los dos lados: a mirar.
    ext, lib = defaultdict(list), defaultdict(list)
    for c in pend():
        ext[(c["fecham"], c["importe"])].append(c)
    for r in libres:
        if r["id_dc"] not in tomados:
            lib[(r["fecha"], r["importe"])].append(r)
    for k, cs in ext.items():
        rs = lib.get(k)
        if len(cs) == 1 and rs and len(rs) == 1:
            tomar(cs[0], rs[0], "posible")


# =============================================================================
# Lectura
# =============================================================================

def _cuentas_banco(cur) -> list[dict]:
    cur.execute("""SELECT c.id, c.nombre, c.numero_de_cuenta,
                          (SELECT MAX(e.fecham) FROM c_extractos_bancarios e WHERE e.c_cuentas_de_fondos_id = c.id) AS ultimo
                     FROM c_cuentas_de_fondos c
                    WHERE c.tipo_de_cuenta = 'B' AND c.habilitada = 1
                    ORDER BY (ultimo IS NULL), c.nombre""")
    return cur.fetchall()


def id_motivo_cuota(cur) -> int:
    cur.execute("SELECT id FROM c_motivos_de_ingreso WHERE UPPER(descripcion) = %s ORDER BY activo DESC, id LIMIT 1",
                (MOTIVO_CUOTA,))
    r = cur.fetchone()
    if not r:
        raise ErrorRecibo(f"No existe el motivo de ingreso «{MOTIVO_CUOTA}»: se carga en Tesorería → Tablas.")
    return r["id"]


def empresas(cur) -> dict:
    cur.execute("SELECT CUIT, razon_social FROM p_empresas")
    return {str(f["CUIT"]).zfill(11): (f["razon_social"] or "").strip() for f in cur.fetchall() if f["CUIT"]}


def relaciones(cur) -> dict:
    cur.execute("SELECT cuit_pagador, cuit_empleador FROM fisca_cuit_relacionado WHERE activo = 1")
    rel = defaultdict(list)
    for f in cur.fetchall():
        rel[f["cuit_pagador"]].append(f["cuit_empleador"])
    return rel


def afiliados_de(cur, cuils) -> dict:
    """CUIL → empleadores con relación laboral vigente (la regla de la nómina)."""
    cuils = sorted({c for c in cuils if len(c) == 11})
    if not cuils:
        return {}
    marcas = ",".join(["%s"] * len(cuils))
    cur.execute(f"""SELECT r.cuil, COALESCE(LPAD(e.CUIT, 11, '0'), r.cuit_empleador) AS cuit
                      FROM p_relaciones_laborales r
                      LEFT JOIN p_empresas e ON e.id = r.id_empleador
                     WHERE r.estado = 'activa' AND (r.fecha_fin IS NULL OR r.fecha_fin >= CURDATE())
                       AND r.cuil IN ({marcas})""", cuils)
    out = defaultdict(set)
    for f in cur.fetchall():
        if f["cuit"]:
            out[f["cuil"]].add(digitos(f["cuit"]))
    return out


def saldos_de(cur, cuits) -> dict:
    """CUIT → {período: {liquidado, cobrado, saldo}} de lo liquidado vigente."""
    cuits = sorted({c for c in cuits if c})
    if not cuits:
        return {}
    marcas = ",".join(["%s"] * len(cuits))
    cur.execute(f"""SELECT l.cuit, l.periodo, l.importe AS liquidado, l.vencimiento,
                           (SELECT COALESCE(SUM(d.importe), 0) FROM ingreso_ordenes_detalle d
                              JOIN ingreso_ordenes o ON o.id = d.id_orden
                             WHERE o.estado <> 'anulado' AND d.cuit = l.cuit AND d.periodo = l.periodo) AS cobrado
                      FROM fisca_liquidacion l
                     WHERE l.estado = 'vigente' AND l.cuit IN ({marcas})""", cuits)
    out = defaultdict(dict)
    for f in cur.fetchall():
        liq, cob = _d(f["liquidado"]), _d(f["cobrado"])
        out[f["cuit"]][f["periodo"]] = {"liquidado": liq, "cobrado": cob, "saldo": liq - cob,
                                        "vencimiento": f["vencimiento"]}
    return out


def cobrado_sin_liquidar(cur, cuit) -> dict:
    """Lo cobrado de períodos sin liquidación vigente: período → importe."""
    cur.execute("""SELECT d.periodo, SUM(d.importe) AS cobrado
                     FROM ingreso_ordenes_detalle d JOIN ingreso_ordenes o ON o.id = d.id_orden
                    WHERE o.estado <> 'anulado' AND d.cuit = %s AND d.periodo IS NOT NULL
                      AND NOT EXISTS (SELECT 1 FROM fisca_liquidacion l
                                       WHERE l.cuit = d.cuit AND l.periodo = d.periodo AND l.estado = 'vigente')
                    GROUP BY d.periodo""", (cuit,))
    return {f["periodo"]: _d(f["cobrado"]) for f in cur.fetchall()}


def emitidos_de(cur, ids) -> dict:
    """id_extracto → el recibo vigente emitido desde ese renglón."""
    if not ids:
        return {}
    marcas = ",".join(["%s"] * len(ids))
    cur.execute(f"""SELECT d.id_extracto_origen AS id_ext, o.id AS id_orden, o.nro_orden, o.fecha, o.clase,
                           GROUP_CONCAT(DISTINCT d.cuit) AS cuit,
                           GROUP_CONCAT(d.periodo ORDER BY d.periodo SEPARATOR ',') AS periodos
                      FROM ingreso_ordenes_detalle d JOIN ingreso_ordenes o ON o.id = d.id_orden
                     WHERE o.estado <> 'anulado' AND d.id_extracto_origen IN ({marcas})
                     GROUP BY d.id_extracto_origen, o.id""", list(ids))
    return {f["id_ext"]: f for f in cur.fetchall()}


_RE_COMPROBANTE = re.compile(r"comprobante (\d+)", re.IGNORECASE)


def libro_ingresos(cur, id_cuenta, desde, hasta) -> list[dict]:
    """Los ingresos vigentes de la cuenta en el libro bancario, con un margen."""
    cur.execute("""SELECT dc.id AS id_dc, io.id AS id_orden, io.nro_orden, io.clase, io.observaciones,
                          COALESCE(dc.fecha_emision, mf.fecha) AS fecha, dc.importe_credito AS importe,
                          (SELECT MIN(d.cuit) FROM ingreso_ordenes_detalle d WHERE d.id_orden = io.id) AS cuit,
                          (SELECT GROUP_CONCAT(d.descripcion ORDER BY d.id SEPARATOR ' / ')
                             FROM ingreso_ordenes_detalle d WHERE d.id_orden = io.id) AS detalle,
                          EXISTS (SELECT 1 FROM conciliacion_comprobantes cc WHERE cc.id_debito_credito = dc.id) AS conciliado
                     FROM c_debitos_creditos_bancarios dc
                     JOIN c_movimientos_de_fondos mf ON mf.id = dc.c_movimientos_de_fondosId
                     JOIN ingreso_ordenes io ON io.id = mf.ingreso_ordenesId
                    WHERE mf.c_cuentas_de_fondosId = %s AND mf.fecha_anulacion IS NULL AND dc.estado <> 'anulado'
                      AND io.estado <> 'anulado' AND dc.importe_credito > 0
                      AND COALESCE(dc.fecha_emision, mf.fecha) BETWEEN %s AND %s""",
                (id_cuenta, desde - datetime.timedelta(days=DIAS_VENTANA), hasta + datetime.timedelta(days=DIAS_VENTANA)))
    filas = cur.fetchall()
    for r in filas:
        r["importe"] = _d(r["importe"])
        m = _RE_COMPROBANTE.search(r["observaciones"] or "") if (r["nro_orden"] or "").startswith("AEDA-") else None
        r["ref_aeda"] = m.group(1).lstrip("0") if m else None
        r["conciliado"] = bool(r["conciliado"])
    return filas


def acreditaciones(cur, id_cuenta, desde, hasta) -> tuple[list[dict], bool]:
    """Los créditos del extracto con su empleador, su estado y lo sugerido."""
    cur.execute("""SELECT e.id, e.fecham, e.fechav, e.ref_nro, e.credito, e.concepto, e.cuit, e.conciliado,
                          (SELECT ci.id_conciliacion FROM conciliacion_items ci WHERE ci.id_extracto = e.id LIMIT 1)
                            AS id_conc
                     FROM c_extractos_bancarios e
                    WHERE e.c_cuentas_de_fondos_id = %s AND e.fecham BETWEEN %s AND %s AND e.credito > 0
                    ORDER BY e.fecham, e.id LIMIT %s""", (id_cuenta, desde, hasta, TOPE + 1))
    filas = cur.fetchall()
    excedido = len(filas) > TOPE
    filas = filas[:TOPE]

    emp, rel = empresas(cur), relaciones(cur)
    cuils = {digitos(f["cuit"]) for f in filas} - set(emp)
    afi = afiliados_de(cur, cuils)
    reglas = conciliacion.reglas_activas(cur)
    try:
        motivo = id_motivo_cuota(cur)
    except ErrorRecibo:
        motivo = None

    for f in filas:
        f["importe"] = _d(f["credito"])
        f["emp"] = resolver_empleador(f["cuit"], emp, rel, afi)
        f["cuits"] = {x for x in (digitos(f["cuit"]), f["emp"]["cuit"]) if x}
        f["recibo"], f["regla"] = None, None
        if f["conciliado"] or f["id_conc"]:
            f["estado"] = "conciliado"
            continue
        r = conciliacion.match_regla(f["concepto"], False, True, reglas)
        if r and r["tipo_resultado"] in ("movimiento_cuentas", "concepto_gasto") or (
                r and r["tipo_resultado"] == "motivo_ingreso" and r["id_motivo_ingreso"] != motivo):
            f["estado"], f["regla"] = "otro", r["clasif_txt"]
        else:
            f["estado"] = "pendiente"

    # Lo emitido desde un renglón gana sobre «conciliado»: el recibo concilia en el acto.
    emparejar(filas, emitidos_de(cur, [f["id"] for f in filas]), libro_ingresos(cur, id_cuenta, desde, hasta))

    sal =saldos_de(cur, {f["emp"]["cuit"] for f in filas if f["estado"] == "pendiente"})
    vivos = {c: {p: v["saldo"] for p, v in ps.items()} for c, ps in sal.items()}
    for f in filas:
        f["sugerido"] = []
        if f["estado"] in EMITIBLES and f["emp"]["cuit"]:
            saldos = vivos.setdefault(f["emp"]["cuit"], {})
            f["sugerido"] = distribuir(f["importe"], f["fecham"], saldos)
            # Lo que se sugiere para uno ya no está para el siguiente del mismo empleador.
            if f["estado"] == "pendiente":
                for p, imp in f["sugerido"]:
                    if p in saldos:
                        saldos[p] -= imp
        f["en_lote"] = f["estado"] == "pendiente" and f["emp"]["como"] in COMO_SEGURO
    return filas, excedido


# =============================================================================
# Emitir
# =============================================================================

def _extracto_bloqueado(cur, id_extracto) -> dict:
    cur.execute("""SELECT e.*, c.nombre AS cuenta, c.tipo_de_cuenta
                     FROM c_extractos_bancarios e JOIN c_cuentas_de_fondos c ON c.id = e.c_cuentas_de_fondos_id
                    WHERE e.id = %s FOR UPDATE""", (id_extracto,))
    e = cur.fetchone()
    if not e:
        raise ErrorRecibo("No existe ese renglón del extracto.")
    if e["tipo_de_cuenta"] != "B" or _d(e["credito"]) <= 0:
        raise ErrorRecibo("El recibo sale de una acreditación de una cuenta bancaria.")
    if emitidos_de(cur, [e["id"]]):
        raise ErrorRecibo("Esa acreditación ya tiene su recibo.")
    cur.execute("SELECT 1 FROM conciliacion_items WHERE id_extracto = %s LIMIT 1", (e["id"],))
    if e["conciliado"] or cur.fetchone():
        raise ErrorRecibo("Esa acreditación ya está conciliada: si le falta el recibo, primero se desvincula.")
    return e


def leer_renglones(form) -> tuple[list[tuple[str, Decimal]], list[str]]:
    errores, out, vistos = [], [], set()
    for i, (per, imp) in enumerate(zip(form.getlist("r_periodo"), form.getlist("r_importe")), 1):
        if not (per.strip() or imp.strip()):
            continue
        p, v = periodo_de_form(per), leer_importe(imp)
        if not p:
            errores.append(f"Renglón {i}: el período no es válido.")
        if not v or v <= 0:
            errores.append(f"Renglón {i}: el importe tiene que ser mayor que cero.")
        if p and p in vistos:
            errores.append(f"El período {periodo_txt(p)} está dos veces: sumá los importes en un renglón.")
        if p:
            vistos.add(p)
        out.append((p, _d(v)))
    if not out:
        errores.append("Cargá al menos un período.")
    return out, errores


def emitir(cur, id_extracto: int, cuit_emp: str, renglones: list[tuple[str, Decimal]], uid,
           observaciones: str | None = None, recordar: bool = False) -> dict:
    """Emite el recibo de una acreditación. Con el cursor de una transacción:
    si algo falla, no queda nada. Devuelve id_orden, nro y si se concilió."""
    e = _extracto_bloqueado(cur, id_extracto)
    cuit_emp = digitos(cuit_emp)
    cur.execute("SELECT id, razon_social FROM p_empresas WHERE CUIT = %s", (int(cuit_emp) if cuit_emp else 0,))
    empresa = cur.fetchone()
    if not empresa:
        raise ErrorRecibo(f"El CUIT {cuit_emp or '—'} no está en Empleadores.")
    total = _d(e["credito"])
    hoy = datetime.date.today().strftime("%Y%m")
    for p, imp in renglones:
        if not p:
            raise ErrorRecibo("Hay un período que no es válido.")
        if p > hoy:
            raise ErrorRecibo(f"El período {periodo_txt(p)} todavía no empezó.")
        if imp <= 0:
            raise ErrorRecibo("Hay un importe en cero.")
    if len({p for p, _ in renglones}) != len(renglones):
        raise ErrorRecibo("Hay un período repetido.")
    suma = sum((imp for _, imp in renglones), Decimal("0"))
    if abs(suma - total) >= CENT:
        raise ErrorRecibo(f"Los períodos suman {pesos(suma)} y la acreditación es de {pesos(total)}: tienen que dar lo mismo.")
    error = _fecha_valida(cur, e["fecham"])
    if error:
        raise ErrorRecibo(error)
    motivo = id_motivo_cuota(cur)
    razon = (empresa["razon_social"] or "").strip()

    nro = proximo_numero(cur, "ingreso_ordenes", e["fecham"])
    obs = " · ".join(x for x in (
        f"Recibo de cuota sindical desde el extracto de {e['cuenta']}",
        f"acreditación del {e['fecham']:%d/%m/%Y}", f"ref. {e['ref_nro']}" if e["ref_nro"] else None,
        (e["concepto"] or "").strip() or None,
        f"pagó {digitos(e['cuit'])}" if digitos(e["cuit"]) and digitos(e["cuit"]) != cuit_emp else None,
        observaciones) if x)[:2000]
    cur.execute("""INSERT INTO ingreso_ordenes (nro_orden, clase, anio, fecha, estado, id_cuenta, importe_total, moneda,
                                                origen, observaciones, id_usuario_creacion)
                   VALUES (%s, 'cuota_sindical', %s, %s, 'confirmado', %s, %s, 'ARS', 'extracto', %s, %s)""",
                (nro, e["fecham"].year, e["fecham"], e["c_cuentas_de_fondos_id"], total, obs, uid))
    id_orden = cur.lastrowid
    for p, imp in sorted(renglones):
        cur.execute("""INSERT INTO ingreso_ordenes_detalle (id_orden, tipo, id_motivo_ingreso, descripcion, importe,
                                                            moneda, periodo, cuit, id_extracto_origen)
                       VALUES (%s, 'ingreso', %s, %s, %s, 'ARS', %s, %s, %s)""",
                    (id_orden, motivo, f"CUOTA SINDICAL {periodo_txt(p)} · {razon} (CUIT {cuit_emp})"[:200],
                     imp, p, cuit_emp, e["id"]))
    cur.execute("INSERT INTO ingreso_ordenes_cuentas (id_orden, id_cuenta_fondos, importe) VALUES (%s, %s, %s)",
                (id_orden, e["c_cuentas_de_fondos_id"], total))
    mf.registrar_ingreso(cur, id_orden)

    pagador = digitos(e["cuit"])
    if recordar and len(pagador) == 11 and pagador != cuit_emp:
        cur.execute("""INSERT INTO fisca_cuit_relacionado (cuit_pagador, cuit_empleador, observaciones, id_usuario)
                       VALUES (%s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE activo = 1""",
                    (pagador, cuit_emp, f"Al emitir el recibo {nro}", uid))

    # Con una conciliación abierta que incluye la fecha, queda conciliado ya.
    conciliado = None
    cur.execute("""SELECT * FROM conciliacion_header
                    WHERE id_cuenta = %s AND estado IN ('abierto', 'en_proceso') AND %s BETWEEN fecha_desde AND fecha_hasta
                    ORDER BY fecha_desde DESC LIMIT 1""", (e["c_cuentas_de_fondos_id"], e["fecham"]))
    conc = cur.fetchone()
    if conc:
        dcs = conciliacion._dc_de(cur, "ingreso", id_orden, e["c_cuentas_de_fondos_id"])
        neto = sum((_d(d["importe_credito"]) - _d(d["importe_debito"]) for d in dcs), Decimal("0"))
        if dcs and abs(neto - total) < CENT:
            conciliacion._grabar_grupo(
                cur, conc, [{"id": e["id"], "neto": float(total)}],
                [conciliacion.formatear_libro_min(d, "ingreso", id_orden) for d in dcs], uid, None,
                origen="automatico", tipo_interno="motivo_ingreso", id_motivo_ingreso=motivo)
            conciliado = conc["periodo"]
    return {"id_orden": id_orden, "nro": nro, "conciliado": conciliado, "razon": razon}


# =============================================================================
# Pantallas
# =============================================================================

def _rango(cur, args) -> tuple[datetime.date, datetime.date]:
    """Por defecto, desde el 1° del mes anterior (nunca antes del corte de la
    conciliación) hasta hoy."""
    hoy = datetime.date.today()
    hasta = _fecha(args.get("hasta")) or hoy
    desde = _fecha(args.get("desde"))
    if not desde:
        desde = (hoy.replace(day=1) - datetime.timedelta(days=1)).replace(day=1)
        corte = conciliacion.fecha_corte(cur)
        if corte and desde < corte:
            desde = corte
    return desde, hasta


@fisca_rec_bp.route("/recibos")
def lista():
    salida = _guardia()
    if salida:
        return salida
    try:
        return _lista()
    except Exception as e:                       # noqa: BLE001 — se informa en pantalla y en el log
        # Mientras la pantalla es nueva: el error en el aviso, con dónde pasó, en
        # lugar de un 500 mudo (en Railway el traceback queda en Deploy Logs).
        log.exception("Emisión de recibos")
        import traceback
        donde = traceback.extract_tb(e.__traceback__)[-1]
        flash(f"!Error al armar la pantalla: {type(e).__name__}: {e} "
              f"({donde.filename.rsplit('/', 1)[-1].rsplit(chr(92), 1)[-1]}, línea {donde.lineno}: {donde.line})")
        return render_template("fisca/recibos.html", cuentas=[], cuenta=None, filas=[], relaciones=[],
                               desde=None, hasta=None, id_cuenta=None, res={}, falta_esquema=True,
                               estados=ESTADOS, como=COMO, excedido=False, tope=TOPE)


def _lista():
    with get_connection() as conn:
        with conn.cursor() as cur:
            faltan = falta_esquema(cur)
            if faltan:
                _aviso_esquema(faltan)
                return render_template("fisca/recibos.html", cuentas=[], cuenta=None, filas=[], relaciones=[],
                                       desde=None, hasta=None, id_cuenta=None, res={}, falta_esquema=True,
                                       estados=ESTADOS, como=COMO, excedido=False, tope=TOPE)
            cuentas = _cuentas_banco(cur)
            id_cuenta = request.args.get("cuenta", type=int) or (cuentas[0]["id"] if cuentas else None)
            cuenta = next((c for c in cuentas if c["id"] == id_cuenta), None)
            desde, hasta = _rango(cur, request.args)
            filas, excedido = acreditaciones(cur, id_cuenta, desde, hasta) if cuenta else ([], False)
            cur.execute("""SELECT r.*, e.razon_social, u.nombre AS usuario,
                                  (SELECT p.razon_social FROM p_empresas p WHERE p.CUIT = CAST(r.cuit_pagador AS UNSIGNED))
                                    AS razon_pagador
                             FROM fisca_cuit_relacionado r
                             LEFT JOIN p_empresas e ON e.CUIT = CAST(r.cuit_empleador AS UNSIGNED)
                             LEFT JOIN s_usuarios u ON u.id = r.id_usuario
                            WHERE r.activo = 1
                            ORDER BY e.razon_social, r.cuit_pagador""")
            rels = cur.fetchall()
    res = {"cant": len(filas), "total": sum((f["importe"] for f in filas), Decimal("0"))}
    for k in ESTADOS:
        sel = [f for f in filas if f["estado"] == k]
        res[k] = (len(sel), sum((f["importe"] for f in sel), Decimal("0")))
    sel = [f for f in filas if f["en_lote"]]
    res["lote"] = (len(sel), sum((f["importe"] for f in sel), Decimal("0")))
    sel = [f for f in filas if f["estado"] == "pendiente" and not f["en_lote"]]
    res["a_mano"] = (len(sel), sum((f["importe"] for f in sel), Decimal("0")))
    return render_template("fisca/recibos.html", cuentas=cuentas, cuenta=cuenta, id_cuenta=id_cuenta, filas=filas,
                           relaciones=rels, desde=desde, hasta=hasta, res=res, estados=ESTADOS, como=COMO,
                           emitibles=EMITIBLES, excedido=excedido, tope=TOPE, falta_esquema=False,
                           puede_extractos=puede("/tesoreria/extractos"), puede_conc=puede("/tesoreria/conc"),
                           puede_ingreso=puede("/tesoreria/nueva_orden_concepto") or puede("/tesoreria/movimientos"))


def _volver_lista(id_cuenta=None, desde=None, hasta=None):
    f = request.form
    return redirect(url_for("fisca_rec.lista", cuenta=id_cuenta or f.get("cuenta") or None,
                            desde=desde or f.get("desde") or None, hasta=hasta or f.get("hasta") or None))


@fisca_rec_bp.route("/recibos/emitir/<int:id_extracto>", methods=["GET", "POST"])
def emitir_uno(id_extracto):
    salida = _guardia()
    if salida:
        return salida
    errores: list[str] = []
    with get_connection() as conn:
        with conn.cursor() as cur:
            faltan = falta_esquema(cur)
            if faltan:
                _aviso_esquema(faltan)
                return redirect(url_for("fisca_rec.lista"))
            cur.execute("""SELECT e.*, c.nombre AS cuenta, c.numero_de_cuenta
                             FROM c_extractos_bancarios e JOIN c_cuentas_de_fondos c ON c.id = e.c_cuentas_de_fondos_id
                            WHERE e.id = %s""", (id_extracto,))
            e = cur.fetchone()
            if not e:
                flash("!No existe ese renglón del extracto.")
                return redirect(url_for("fisca_rec.lista"))
            ya = emitidos_de(cur, [e["id"]]).get(e["id"])
            if ya:
                flash(f"!Esa acreditación ya tiene el recibo {ya['nro_orden']}.")
                return redirect(url_for("fisca_rec.recibo", id_orden=ya["id_orden"]))
            emp_todas, rel = empresas(cur), relaciones(cur)
            pagador = digitos(e["cuit"])
            sugerido = resolver_empleador(pagador, emp_todas, rel, afiliados_de(cur, {pagador} - set(emp_todas)))
            elegido = digitos(request.values.get("cuit")) or sugerido["cuit"] or ""
            razon = emp_todas.get(elegido)
            if elegido and not razon:
                errores.append(f"El CUIT {elegido} no está en Empleadores.")
            saldos = saldos_de(cur, [elegido]).get(elegido, {}) if razon else {}
            sin_liq = cobrado_sin_liquidar(cur, elegido) if razon else {}
            # El mismo libro que la grilla: si ya tiene un recibo de AEDA, se avisa.
            fila = {"id": e["id"], "ref_nro": e["ref_nro"], "fecham": e["fecham"], "importe": _d(e["credito"]),
                    "cuits": {x for x in (pagador, elegido) if x}, "estado": "pendiente", "recibo": None}
            emparejar([fila], {}, libro_ingresos(cur, e["c_cuentas_de_fondos_id"], e["fecham"], e["fecham"]))
            cur.execute("SELECT 1 FROM conciliacion_items WHERE id_extracto = %s LIMIT 1", (e["id"],))
            conciliado = bool(e["conciliado"] or cur.fetchone())

    renglones = [(p, imp) for p, imp in distribuir(e["credito"], e["fecham"],
                                                     {p: v["saldo"] for p, v in saldos.items()})] if razon else []
    recordar = pagador != elegido and len(pagador) == 11 and elegido not in rel.get(pagador, ())
    obs = ""

    if request.method == "POST" and request.form.get("accion") == "emitir":
        renglones, errores = leer_renglones(request.form)
        recordar = bool(request.form.get("recordar"))
        obs = " ".join((request.form.get("observaciones") or "").split())[:250]
        if not razon:
            errores.append("Elegí el empleador.")
        if not errores:
            conn = get_connection()
            try:
                conn.begin()
                with conn.cursor() as cur:
                    r = emitir(cur, id_extracto, elegido, renglones, _uid(), obs or None, recordar)
                conn.commit()
            except ErrorRecibo as ex:
                conn.rollback()
                errores.append(str(ex))
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            if not errores:
                flash(f"Recibo {r['nro']} emitido a {r['razon']} por {pesos(e['credito'])}."
                      + (f" Quedó conciliado en la conciliación {periodo_txt(r['conciliado'])}." if r["conciliado"] else "")
                      + (" Los próximos pagos de ese CUIT se reconocen solos." if recordar else ""))
                return redirect(url_for("fisca_rec.recibo", id_orden=r["id_orden"]))

    periodos = sorted(set(saldos) | set(sin_liq), reverse=True)
    return render_template("fisca/recibo_emitir.html", e=e, errores=errores, sugerido=sugerido, elegido=elegido,
                           razon=razon, saldos=saldos, sin_liq=sin_liq, periodos=periodos, renglones=renglones,
                           recordar=recordar, obs=obs, fila=fila, conciliado=conciliado, pagador=pagador,
                           como=COMO, estados=ESTADOS, periodo_mes=periodo_anterior(e["fecham"]),
                           hoy=datetime.date.today().strftime("%Y-%m"),
                           volver=url_for("fisca_rec.lista", cuenta=e["c_cuentas_de_fondos_id"],
                                          desde=request.values.get("desde") or None,
                                          hasta=request.values.get("hasta") or None))


@fisca_rec_bp.route("/recibos/emitir_lote", methods=["POST"])
def emitir_lote():
    """Los tildados, con lo que sugiere la pantalla. Se vuelve a calcular todo
    en el servidor: solo entran los que siguen sin recibo y con el empleador
    seguro. Cada recibo en su transacción."""
    salida = _guardia()
    if salida:
        return salida
    id_cuenta = request.form.get("cuenta", type=int)
    ids = {int(x) for x in request.form.getlist("extracto") if x.isdigit()}
    if not ids:
        flash("!Tildá al menos una acreditación.")
        return _volver_lista()
    if len(ids) > MAX_LOTE:
        flash(f"!Se emiten hasta {MAX_LOTE} recibos de una vez.")
        return _volver_lista()
    with get_connection() as conn:
        with conn.cursor() as cur:
            faltan = falta_esquema(cur)
            if faltan:
                _aviso_esquema(faltan)
                return _volver_lista()
            cur.execute("SELECT MIN(fecham) AS d, MAX(fecham) AS h FROM c_extractos_bancarios "
                        f"WHERE c_cuentas_de_fondos_id = %s AND id IN ({','.join(['%s'] * len(ids))})",
                        [id_cuenta, *ids])
            r = cur.fetchone() or {}
            if not r.get("d"):
                flash("!Esas acreditaciones no son de la cuenta elegida.")
                return _volver_lista()
            # Desde el comienzo del rango de la pantalla, para que lo sugerido sea lo mismo que se vio.
            desde = min(r["d"], _fecha(request.form.get("desde")) or r["d"])
            filas, _ = acreditaciones(cur, id_cuenta, desde, r["h"])
    elegidas = [f for f in filas if f["id"] in ids]
    uid = _uid()
    hechos, total, saltados, fallados = 0, Decimal("0"), 0, []
    for f in elegidas:
        if not f["en_lote"] or not f["sugerido"]:
            saltados += 1
            continue
        conn = get_connection()
        try:
            conn.begin()
            with conn.cursor() as cur:
                emitir(cur, f["id"], f["emp"]["cuit"], f["sugerido"], uid)
            conn.commit()
            hechos += 1
            total += f["importe"]
        except ErrorRecibo as ex:
            conn.rollback()
            fallados.append(f"{f['fecham']:%d/%m} {pesos(f['importe'])}: {ex}")
        except Exception:
            conn.rollback()
            log.exception("Recibo del extracto %s", f["id"])
            fallados.append(f"{f['fecham']:%d/%m} {pesos(f['importe'])}: no se pudo emitir")
        finally:
            conn.close()
    if hechos:
        flash(f"{hechos} recibo(s) emitidos por {pesos(total)}.")
    if saltados:
        flash(f"!{saltados} no se emitieron: ya tienen recibo o el empleador no es seguro. Se emiten de a uno.")
    for t in fallados[:10]:
        flash("!" + t)
    if len(fallados) > 10:
        flash(f"!…y {len(fallados) - 10} más.")
    return _volver_lista(id_cuenta)


def leer_recibo(cur, id_orden) -> dict | None:
    cur.execute("""SELECT o.*, u.nombre AS usuario_creacion, ua.nombre AS usuario_anulacion, cf.nombre AS cuenta,
                          cf.numero_de_cuenta
                     FROM ingreso_ordenes o
                     LEFT JOIN s_usuarios u  ON u.id  = o.id_usuario_creacion
                     LEFT JOIN s_usuarios ua ON ua.id = o.id_usuario_anulacion
                     LEFT JOIN c_cuentas_de_fondos cf ON cf.id = o.id_cuenta
                    WHERE o.id = %s""", (id_orden,))
    o = cur.fetchone()
    if not o:
        return None
    cur.execute("""SELECT d.* FROM ingreso_ordenes_detalle d WHERE d.id_orden = %s ORDER BY d.periodo, d.id""",
                (id_orden,))
    o["detalle"] = cur.fetchall()
    cuit = next((d["cuit"] for d in o["detalle"] if d["cuit"]), None)
    o["cuit"] = cuit
    o["empresa"] = None
    if cuit:
        cur.execute("SELECT id, razon_social FROM p_empresas WHERE CUIT = %s", (int(cuit),))
        o["empresa"] = cur.fetchone()
    ext = next((d["id_extracto_origen"] for d in o["detalle"] if d["id_extracto_origen"]), None)
    o["extracto"] = None
    if ext:
        cur.execute("SELECT * FROM c_extractos_bancarios WHERE id = %s", (ext,))
        o["extracto"] = cur.fetchone()
    o["en_letras"] = en_letras(o["importe_total"])
    return o


@fisca_rec_bp.route("/recibos/<int:id_orden>")
def recibo(id_orden):
    salida = _guardia()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            o = leer_recibo(cur, id_orden)
    if not o or o["clase"] != "cuota_sindical":
        flash("!No existe ese recibo de cuota sindical.")
        return redirect(url_for("fisca_rec.lista"))
    return render_template("fisca/recibo.html", o=o, puede_ingreso=puede("/tesoreria/movimientos")
                           or puede("/tesoreria/nueva_orden_concepto"),
                           puede_anular=puede("/tesoreria/anulaciones"),
                           puede_empleador=puede(url_for("empleadores.abm_empleadores")))


def recibo_pdf(o: dict):
    """El recibo en PDF, con el membrete de Datos del Sindicato (pagos_pdf)."""
    import pagos_pdf as P
    from reportlab.lib.units import cm
    from reportlab.platypus import Spacer, Table, TableStyle
    doc = P._Doc("Recibo", o["nro_orden"], "ANULADO" if o["estado"] == "anulado" else None)
    razon = escape((o["empresa"] or {}).get("razon_social") or "—")
    doc.story.append(doc.P(
        f"Recibimos de <b>{razon}</b> (CUIT {P._cuit(o['cuit'])}) la suma de <b>PESOS {escape(o['en_letras'])}</b> "
        f"(<b>{P._pesos(o['importe_total'])}</b>) en concepto de cuota sindical.", fontSize=10, leading=15, spaceAfter=10))
    doc.datos("RECIBO", [("Fecha", P._fecha(o["fecha"])), ("Empleador", razon), ("CUIT", P._cuit(o["cuit"])),
                         ("Importe", P._pesos(o["importe_total"]))])
    doc.tabla("PERÍODOS", ["Período", "Concepto", "Importe"],
              [[periodo_txt(d["periodo"]), "Cuota sindical", P._pesos(d["importe"])] for d in o["detalle"]],
              [3.0, 10.0, 3.0], derecha=(2,), total=("Total", P._pesos(o["importe_total"])))
    e = o["extracto"] or {}
    doc.datos("FORMA DE PAGO", [
        ("Medio", "Acreditación bancaria"),
        ("Cuenta", P._txt(o.get("cuenta")) + (f" N° {P._txt(o['numero_de_cuenta'])}" if o.get("numero_de_cuenta") else "")),
        ("Acreditada el", P._fecha(e.get("fecham"))), ("Referencia", P._txt(e.get("ref_nro"))),
        ("Concepto del banco", P._txt(e.get("concepto"))),
        ("Pagó", P._cuit(e.get("cuit")) if digitos(e.get("cuit")) and digitos(e.get("cuit")) != o["cuit"] else "")])
    doc.story.append(Spacer(1, 1.8 * cm))
    f = Table([[""], [doc.P("Firma y aclaración", alignment=1)]], colWidths=[6 * cm], rowHeights=[1.2 * cm, None],
              hAlign="RIGHT")
    f.setStyle(TableStyle([("LINEABOVE", (0, 1), (0, 1), 0.6, doc.MUTED)]))
    doc.story.append(f)
    return P.respuesta(doc.pdf(f"Recibo {o['nro_orden']}"), f"Recibo {o['nro_orden']}.pdf")


@fisca_rec_bp.route("/recibos/<int:id_orden>/pdf")
def recibo_pdf_ruta(id_orden):
    salida = _guardia()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            o = leer_recibo(cur, id_orden)
    if not o or o["clase"] != "cuota_sindical":
        flash("!No existe ese recibo de cuota sindical.")
        return redirect(url_for("fisca_rec.lista"))
    return recibo_pdf(o)


# =============================================================================
# CUIT relacionados
# =============================================================================

@fisca_rec_bp.route("/recibos/relacion", methods=["POST"])
def relacion_alta():
    salida = _guardia()
    if salida:
        return salida
    pagador = digitos(request.form.get("cuit_pagador"))
    empleador = digitos(request.form.get("cuit_empleador"))
    obs = " ".join((request.form.get("observaciones") or "").split())[:250] or None
    if not cuit_valido(pagador):
        flash(f"!El CUIT/CUIL que paga ({pagador or 'vacío'}) no verifica.")
        return _volver_lista()
    if pagador == empleador:
        flash("!El que paga y el empleador son el mismo CUIT: no hace falta relacionarlos.")
        return _volver_lista()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT razon_social FROM p_empresas WHERE CUIT = %s", (int(empleador or 0),))
            emp = cur.fetchone()
            if not emp:
                flash(f"!El CUIT {empleador or '—'} no está en Empleadores.")
                return _volver_lista()
            cur.execute("""INSERT INTO fisca_cuit_relacionado (cuit_pagador, cuit_empleador, observaciones, id_usuario)
                           VALUES (%s, %s, %s, %s)
                           ON DUPLICATE KEY UPDATE activo = 1, observaciones = COALESCE(VALUES(observaciones), observaciones)""",
                        (pagador, empleador, obs, _uid()))
        conn.commit()
    flash(f"Los pagos de {pagador} se reconocen como de {emp['razon_social']}.")
    return _volver_lista()


@fisca_rec_bp.route("/recibos/relacion/<int:id_rel>/baja", methods=["POST"])
def relacion_baja(id_rel):
    salida = _guardia()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE fisca_cuit_relacionado SET activo = 0 WHERE id = %s", (id_rel,))
        conn.commit()
    flash("Relación dada de baja: los recibos ya emitidos no cambian.")
    return _volver_lista()
