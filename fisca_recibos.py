"""
fisca_recibos.py — Fiscalización de Cuotas › Emisión de Recibos (menú 8).

    /fiscalizacion/recibos                        las acreditaciones de una cuenta: ?cuenta, ?desde, ?hasta
    /fiscalizacion/recibos/emitir/<id_extracto>   GET el formulario (?cuit= elige otro empleador, ?acuerdo= lo
                                                  emite como fiscalización a ese acuerdo de pago); POST emite
    /fiscalizacion/recibos/emitir_lote            POST extracto=… los tildados, con lo que sugiere la pantalla
    /fiscalizacion/recibos/<id_orden>             el recibo (?volver= de Tesorería › Recibos Emitidos)
    /fiscalizacion/recibos/<id_orden>/pdf         el recibo en PDF
    Los dos últimos, también para quien tiene Recibos Emitidos (recibos_emitidos.py).
    /fiscalizacion/recibos/relacion               POST alta de un CUIT que paga por un empleador
    /fiscalizacion/recibos/relacion/<id>/baja     POST
    /fiscalizacion/recibos/asociar                POST de quién es una acreditación: el CUIT a mano (si el banco
                                                  no lo trajo) y la relación del pagador con una empresa o un afiliado
    /fiscalizacion/recibos/afiliado/<id>/baja     POST baja de un CUIT que paga por un afiliado

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
- Nada más (pedido del 15/11/2026). Un afiliado NO se relaciona con su
  empleador: su transferencia es un pago por otro concepto, no la cuota
  sindical de la empresa. Si ese CUIL paga por una empresa, se carga como CUIT
  relacionado y entonces sí se reconoce.
- Salvo el importe (pedido del 18/11/2026, `por_su_empleador`): la cuota social
  es redonda a la medida de la cuota (RA.es_cuota_social: 30.000, 55.000…); lo
  que un afiliado transfiere con centavos o no redondo es la cuota sindical del
  empleador de su ficha (como lo registraba AEDA: 34.304,12 de CERSOSIMO es la
  cuota de CTL INTERNATIONAL). Se sugiere con ese empleador, «Lo pagó el
  afiliado», de a uno (no en lote) y sin «Recordar».

QUIÉN PAGÓ (pedido del 18/11/2026, sql/recibos_pagadores_20261118.sql)
- El banco no siempre trae el CUIT (TRANSF.INT.DIST.TITULAR sin CUIT: tampoco lo
  tiene AEDA). «Asociar» lo carga a mano en el renglón del extracto
  (`cuit_manual` = 1, con quién y cuándo); el que trajo el banco no se pisa.
- Un CUIT que paga por un AFILIADO (el cónyuge, una cuenta de otro):
  `fisca_cuit_afiliado`, el par de fisca_cuit_relacionado. Sus pagos se
  reconocen como del afiliado (`emp["cuil"]` es el CUIL del afiliado, no el del
  banco) y van por Beneficios. Son dos asociaciones, una por concepto: la de
  la empresa vale para la CUOTA SINDICAL y la del afiliado para la CUOTA SOCIAL
  (el importe redondo a la medida de la cuota, RA.es_cuota_social); el mismo
  CUIT puede tener las dos.

EL AFILIADO (recibos_afiliado.py, pedido del 15/11/2026)
Si el CUIT del banco es un CUIL del padrón (y no un pagador relacionado), es la
cuota social YMCA: lleva un RECIBO AL AFILIADO (talonario X 0003, el motivo y el
concepto de Datos del Sindicato), un renglón por mes desde el de la
acreditación. Una transferencia de N cuotas justas se emite en lote; las demás,
de a uno (se puede emitir como cuota sindical de un empleador si no era la
cuota social). Lo que AEDA ya registró en su orden YMCA del mes se ve «Ya tiene
recibo». Sin sql/recibos_afiliados_20261115.sql, queda «Otro ingreso».

TALONARIO (recibos_talonario.py, pedido del 14/11/2026)
Cada recibo lleva su número del talonario de cuota sindical (X 0001, el que diga
Datos del Sindicato): «X 0001-00000123». Los de AEDA están en X 0091 / X 0092 con
el número de cobro de AEDA. El número AAMM-######## es el de la orden de ingreso.

FISCALIZACIÓN (fisca_recibo_acta.py)
Una acreditación de un empleador con un acuerdo de pago vigente se puede emitir
como «Fiscalización»: el recibo es al acta y se imputa a las cuotas del acuerdo
(talonario X 0002). Esas acreditaciones no se emiten en lote como cuota.

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
Saldo = lo liquidado vigente (`fisca_liquidacion`) − lo aplicado a esa cuota
(`fisca_aplicacion`, fisca_aplicaciones.py). Al emitir se puede cambiar todo;
cada renglón del recibo queda aplicado a la cuota de su período, hasta su saldo
(origen «recibo»): lo que sobra queda sin aplicar, a favor del empleador.

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
import fisca_aplicaciones as fa
import fisca_recibo_acta as FRA
import movimientos_fondos as mf
import recibos_afiliado as RA
import recibos_talonario as RT
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
    "afiliado":    ("Afiliado", "info"),
    "por_afiliado": ("Lo pagó el afiliado", "info"),
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
#: Estado de una cuota del acuerdo de pago.
ESTADOS_CUOTA = {"pagada": ("Pagada", "ok"), "parcial": ("Pago parcial", "info"), "vencida": ("Vencida", "danger"),
                 "pendiente": ("Pendiente", "neutro")}


class ErrorRecibo(ValueError):
    """Un error de validación: el texto va directo a la pantalla."""


#: Lo que se muestra tal cual al emitir (validaciones de acá, del talonario y del cobro del acta).
ERRORES = (ErrorRecibo, RT.ErrorTalonario, FRA.ErrorCobro, RA.ErrorReciboAfiliado)


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


#: Tesorería › Recibos Emitidos (recibos_emitidos.py) abre el recibo y su PDF:
#: quien tiene esa pantalla los ve aunque no tenga la de emisión.
URL_EMITIDOS = "/tesoreria/recibos"


#: Beneficios › Recibos de Adheridos (ben_convenio.py) emite el recibo al afiliado y lo abre acá.
URL_BENEFICIOS = "/beneficios/ymca/recibos"


def _guardia_ver():
    if not validasesion():
        return redirect(url_for("login"))
    if not (puede(URL) or puede(URL_EMITIDOS) or puede(URL_BENEFICIOS)):
        flash("!No tenés permiso para ver recibos.")
        return redirect(url_for("menu"))
    return None


def _volver_emitidos() -> str | None:
    """?volver= de Recibos Emitidos, con sus filtros: solo una dirección de esa pantalla."""
    v = request.args.get("volver") or ""
    return v if v == URL_EMITIDOS or v.startswith(URL_EMITIDOS + "?") else None


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
    ("fisca_aplicacion", "id_detalle", "sql/fisca_aplicaciones_20261114.sql"),
    ("ingreso_ordenes", "nro_recibo", RT.SQL_ESQUEMA),
    ("fisca_acuerdo_imputacion", "id_cuota", RT.SQL_ESQUEMA),
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

def resolver_empleador(cuit_banco, empresas: dict, relaciones: dict, afiliados: dict | None = None,
                       pagadores: dict | None = None, social: bool = False) -> dict:
    """De quién es el pago. `empresas`: CUIT → razón social; `relaciones`:
    pagador → [CUIT de empleadores]; `afiliados`: CUIL → apellido y nombres de
    los del padrón. Devuelve cuit, razon, como, las opciones y, si pagó un
    afiliado, su `nombre` y su `cuil`: un afiliado no se relaciona con su
    empleador (ver el encabezado), queda sin empleador. `pagadores`: pagador →
    CUIL del afiliado por el que paga (fisca_cuit_afiliado).

    Dos asociaciones, una por concepto (pedido del 18/11/2026): las relaciones
    con un empleador son de la CUOTA SINDICAL y los pagadores de un afiliado,
    de la CUOTA SOCIAL. `social`: el importe es de la cuota social
    (RA.es_cuota_social); entonces el afiliado (el mismo o por el que paga) va
    antes que las relaciones con un empleador. El mismo CUIT puede tener las dos."""
    c = digitos(cuit_banco)
    sin = {"cuit": None, "razon": None, "como": "sin", "opciones": []}
    if len(c) != 11:
        return sin
    if c in empresas:
        return {"cuit": c, "razon": empresas[c], "como": "mismo", "opciones": []}
    p = (pagadores or {}).get(c)
    if social and afiliados:
        if c in afiliados:
            return {"cuit": None, "razon": None, "como": "afiliado", "opciones": [], "nombre": afiliados[c], "cuil": c}
        if p and p in afiliados:
            return {"cuit": None, "razon": None, "como": "afiliado", "opciones": [], "nombre": afiliados[p],
                    "cuil": p, "por_otro": True}
    cand = sorted({e for e in relaciones.get(c, ()) if e in empresas})
    if len(cand) == 1:
        return {"cuit": cand[0], "razon": empresas[cand[0]], "como": "relacionado", "opciones": []}
    if cand:
        return {"cuit": None, "razon": None, "como": "varios",
                "opciones": [{"cuit": e, "razon": empresas[e], "como": "relacionado"} for e in cand]}
    if afiliados and c in afiliados:
        return {"cuit": None, "razon": None, "como": "afiliado", "opciones": [], "nombre": afiliados[c], "cuil": c}
    if p and afiliados and p in afiliados:
        return {"cuit": None, "razon": None, "como": "afiliado", "opciones": [], "nombre": afiliados[p], "cuil": p,
                "por_otro": True}
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


def esquema_pagadores(cur) -> dict:
    """Qué hay de sql/recibos_pagadores_20261118.sql: el CUIT a mano en el
    extracto («manual») y los pagadores de afiliados («afiliado»)."""
    cur.execute("""SELECT
          (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE()
              AND table_name = 'c_extractos_bancarios' AND column_name = 'cuit_manual') AS manual,
          (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE()
              AND table_name = 'fisca_cuit_afiliado') AS afiliado""")
    f = cur.fetchone()
    return {"manual": bool(f["manual"]), "afiliado": bool(f["afiliado"])}


def pagadores_afiliado(cur, esq: dict | None = None) -> dict:
    """Pagador → CUIL del afiliado por el que paga (activos)."""
    if not (esq or esquema_pagadores(cur))["afiliado"]:
        return {}
    cur.execute("SELECT cuit_pagador, cuil_afiliado FROM fisca_cuit_afiliado WHERE activo = 1")
    return {f["cuit_pagador"]: f["cuil_afiliado"] for f in cur.fetchall()}


def cuil_afiliado_de(cur, pagador: str) -> str:
    """El CUIL del afiliado de un pago: el mismo pagador si está en el padrón;
    si no, el afiliado por el que paga (fisca_cuit_afiliado); si no, el pagador."""
    if RA.afiliado(cur, pagador):
        return pagador
    return pagadores_afiliado(cur).get(pagador, pagador)


def afiliados_de(cur, cuils) -> dict:
    """CUIL → apellido y nombres, de los que están en el padrón (titulares,
    familiares, de baja): una transferencia suya no es la cuota de su empleador."""
    cuils = sorted({c for c in cuils if len(c) == 11})
    if not cuils:
        return {}
    marcas = ",".join(["%s"] * len(cuils))
    cur.execute(f"""SELECT cuil, MAX(apellido_nombres) AS nombre FROM p_afiliados
                     WHERE cuil IN ({marcas}) GROUP BY cuil""", cuils)
    return {f["cuil"]: (f["nombre"] or "").strip() for f in cur.fetchall()}


def saldos_de(cur, cuits) -> dict:
    """CUIT → {período: {liquidado, cobrado, saldo}} de lo liquidado vigente.
    `cobrado` es lo aplicado a la cuota (fisca_aplicaciones.py)."""
    cuits = sorted({c for c in cuits if c})
    if not cuits:
        return {}
    marcas = ",".join(["%s"] * len(cuits))
    cur.execute(f"""SELECT l.cuit, l.periodo, l.importe AS liquidado, l.vencimiento,
                           {fa.sql_aplicado_liq('l')} AS cobrado
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
    return {f["id_ext"]: f for f in RT.completar(cur, cur.fetchall())}


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
    filas = RT.completar(cur, cur.fetchall())
    for r in filas:
        r["importe"] = _d(r["importe"])
        m = _RE_COMPROBANTE.search(r["observaciones"] or "") if (r["nro_orden"] or "").startswith("AEDA-") else None
        r["ref_aeda"] = m.group(1).lstrip("0") if m else None
        r["conciliado"] = bool(r["conciliado"])
    return filas


def cuotas_sociales(cur, cfg: dict | None) -> list[tuple[str, Decimal]]:
    return RA.cuotas_sociales(cur, cfg)


def empleadores_de(cur, cuils) -> dict:
    """CUIL del afiliado → CUIT del empleador de su ficha (el de la relación
    vigente más nueva, `p_afiliados.cuit_empleador`)."""
    cuils = sorted({c for c in cuils if c and len(c) == 11})
    if not cuils:
        return {}
    cur.execute(f"""SELECT cuil, MAX(cuit_empleador) AS cuit FROM p_afiliados
                     WHERE cuil IN ({','.join(['%s'] * len(cuils))}) AND cuit_empleador REGEXP '^[0-9]{{11}}$'
                     GROUP BY cuil""", cuils)
    return {f["cuil"]: f["cuit"] for f in cur.fetchall()}


def por_su_empleador(e: dict, importe, fecha, cuotas, emp_de: dict, empresas: dict) -> dict:
    """La transferencia de un afiliado que NO es un importe de la cuota social
    (con centavos, o no redondo a la medida de la cuota) es la cuota sindical de su empleador (pedido del 18/11/2026: la paga el afiliado
    —monotributista, o la empresa que no transfiere—). Se sugiere con el
    empleador de su ficha, de a uno; si no tiene uno de Empleadores, sigue como
    afiliado (Beneficios)."""
    if e.get("como") != "afiliado" or RA.es_cuota_social(importe, fecha, cuotas):
        return e
    c = emp_de.get(e.get("cuil"))
    if c not in empresas:
        return e
    return {"cuit": c, "razon": empresas[c], "como": "por_afiliado", "opciones": [], "nombre": e.get("nombre"),
            "cuil": e.get("cuil")}


def acreditaciones(cur, id_cuenta, desde, hasta) -> tuple[list[dict], bool]:
    """Los créditos del extracto con su empleador, su estado y lo sugerido."""
    esq = esquema_pagadores(cur)
    manual = "e.cuit_manual" if esq["manual"] else "0"
    cur.execute(f"""SELECT e.id, e.fecham, e.fechav, e.ref_nro, e.credito, e.concepto, e.cuit, e.conciliado,
                          {manual} AS cuit_manual,
                          (SELECT ci.id_conciliacion FROM conciliacion_items ci WHERE ci.id_extracto = e.id LIMIT 1)
                            AS id_conc
                     FROM c_extractos_bancarios e
                    WHERE e.c_cuentas_de_fondos_id = %s AND e.fecham BETWEEN %s AND %s AND e.credito > 0
                    ORDER BY e.fecham, e.id LIMIT %s""", (id_cuenta, desde, hasta, TOPE + 1))
    filas = cur.fetchall()
    excedido = len(filas) > TOPE
    filas = filas[:TOPE]

    emp, rel = empresas(cur), relaciones(cur)
    pag = pagadores_afiliado(cur, esq)
    cuils = ({digitos(f["cuit"]) for f in filas} - set(emp)) | set(pag.values())
    afi = afiliados_de(cur, cuils)
    reglas = conciliacion.reglas_activas(cur)
    try:
        motivo = id_motivo_cuota(cur)
    except ErrorRecibo:
        motivo = None

    cfg = RA.config(cur)
    cuotas = cuotas_sociales(cur, cfg)
    emp_de = empleadores_de(cur, set(afi))
    for f in filas:
        f["importe"] = _d(f["credito"])
        social = RA.es_cuota_social(f["importe"], f["fecham"], cuotas)
        f["emp"] = por_su_empleador(resolver_empleador(f["cuit"], emp, rel, afi, pag, social), f["importe"],
                                    f["fecham"], cuotas, emp_de, emp)
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
    # La transferencia de un afiliado es la cuota social (después de emparejar:
    # si ya tiene recibo, se sigue viendo así). Lo que AEDA registró en su orden
    # agrupada del mes (YMCA), «Ya tiene recibo»; sin el script, «Otro ingreso».
    afis = [f for f in filas if f["estado"] == "pendiente" and f["emp"]["como"] == "afiliado"]
    aeda = RA.ordenes_aeda(cur, id_cuenta, cfg["motivo"], desde, hasta) if cfg and afis else []
    for f in afis:
        o = RA.cubierta(f["fecham"], aeda)
        if not cfg:
            f["estado"] = "otro"
            f["regla"] = (f"Transferencia de un afiliado: es la cuota social, no la de una empresa. Para emitirle "
                          f"el recibo falta correr {RA.SQL_ESQUEMA}.")
        elif o:
            f["estado"] = "ya_tiene"
            f["recibo"] = {"id_orden": o["id_orden"], "nro_orden": o["nro_orden"], "nro_recibo": None,
                           "clase": "varios", "fecha": o["fecha"], "importe": o["importe_total"]}
            f["regla"] = (f"AEDA la registró en su orden {cfg['motivo_txt'] or ''} {o['nro_orden']} "
                          f"del {o['fecha']:%d/%m/%Y}, junto con las demás del mes.")

    # Un importe sin pagador identificado que es de la cuota social (redondo a
    # la medida de la cuota: 30.000, 55.000…, RA.es_cuota_social) es un afiliado
    # que pagó desde una cuenta que no lo nombra, no una empresa (pedido del
    # 18/11/2026): no se sugiere como cuota sindical. Queda «Otro ingreso» y se
    # puede emitir igual de a uno.
    sin_pagador = [f for f in filas if f["estado"] == "pendiente" and f["emp"]["como"] == "sin"]
    if sin_pagador:
        for f in sin_pagador:
            if RA.es_cuota_social(f["importe"], f["fecham"], cuotas):
                f["estado"] = "otro"
                f["regla"] = ("Es un importe de la cuota social del convenio (redondo, a la medida de la cuota) y el "
                              "banco no dice quién pagó: no se sugiere como cuota sindical. Si sabés de quién es, "
                              "«Asociar» lo identifica.")

    sal = saldos_de(cur, {f["emp"]["cuit"] for f in filas if f["estado"] == "pendiente"})
    # Un empleador con un acuerdo de pago: su pago puede ser una cuota del acuerdo. Se emite de a uno.
    acuerdo = FRA.con_acuerdo(cur, {f["emp"]["cuit"] for f in filas if f["estado"] in EMITIBLES}) \
        if RT.hay_esquema(cur) else set()
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
        f["con_acuerdo"] = f["emp"]["cuit"] in acuerdo
        f["en_lote"] = f["estado"] == "pendiente" and f["emp"]["como"] in COMO_SEGURO and not f["con_acuerdo"]
        # El recibo al afiliado: los meses desde el de la acreditación; en lote, solo N cuotas justas.
        if cfg and f["estado"] in EMITIBLES and f["emp"]["como"] == "afiliado":
            f["sugerido"] = RA.periodos(f["importe"], f["fecham"], cfg["cuota"])
            f["en_lote"] = (f["estado"] == "pendiente" and bool(cfg.get("talonario"))
                            and bool(RA.meses_justos(f["importe"], cfg["cuota"])))
            f["al_afiliado"] = True
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

    talon = RT.reservar(cur, "cuota_sindical")
    nro_orden = proximo_numero(cur, "ingreso_ordenes", e["fecham"])
    nro = talon["texto"]
    obs = " · ".join(x for x in (
        f"Recibo de cuota sindical desde el extracto de {e['cuenta']}",
        f"acreditación del {e['fecham']:%d/%m/%Y}", f"ref. {e['ref_nro']}" if e["ref_nro"] else None,
        (e["concepto"] or "").strip() or None,
        f"pagó {digitos(e['cuit'])}" if digitos(e["cuit"]) and digitos(e["cuit"]) != cuit_emp else None,
        observaciones) if x)[:2000]
    cur.execute("""INSERT INTO ingreso_ordenes (nro_orden, id_talonario, nro_recibo, clase, anio, fecha, estado, id_cuenta,
                                                importe_total, moneda, origen, observaciones, id_usuario_creacion)
                   VALUES (%s, %s, %s, 'cuota_sindical', %s, %s, 'confirmado', %s, %s, 'ARS', 'extracto', %s, %s)""",
                (nro_orden, talon["id"], talon["nro"], e["fecham"].year, e["fecham"], e["c_cuentas_de_fondos_id"], total,
                 obs, uid))
    id_orden = cur.lastrowid
    ids_detalle = []
    for p, imp in sorted(renglones):
        cur.execute("""INSERT INTO ingreso_ordenes_detalle (id_orden, tipo, id_motivo_ingreso, descripcion, importe,
                                                            moneda, periodo, cuit, id_extracto_origen)
                       VALUES (%s, 'ingreso', %s, %s, %s, 'ARS', %s, %s, %s)""",
                    (id_orden, motivo, f"CUOTA SINDICAL {periodo_txt(p)} · {razon} (CUIT {cuit_emp})"[:200],
                     imp, p, cuit_emp, e["id"]))
        ids_detalle.append(cur.lastrowid)
    # Cada renglón, a la cuota de su período (hasta su saldo): lo que sobra queda sin aplicar.
    fa.aplicar_automatico(cur, cuits=[cuit_emp], ids_detalle=ids_detalle, origen_periodo="recibo", id_usuario=uid)
    cur.execute("INSERT INTO ingreso_ordenes_cuentas (id_orden, id_cuenta_fondos, importe) VALUES (%s, %s, %s)",
                (id_orden, e["c_cuentas_de_fondos_id"], total))
    mf.registrar_ingreso(cur, id_orden)

    pagador = digitos(e["cuit"])
    if recordar and len(pagador) == 11 and pagador != cuit_emp:
        cur.execute("""INSERT INTO fisca_cuit_relacionado (cuit_pagador, cuit_empleador, observaciones, id_usuario)
                       VALUES (%s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE activo = 1""",
                    (pagador, cuit_emp, f"Al emitir el recibo {nro}"[:250], uid))

    # Con una conciliación abierta que incluye la fecha, queda conciliado ya.
    conciliado = FRA.conciliar_en_el_acto(cur, e["c_cuentas_de_fondos_id"], e["fecham"], id_orden, total, e["id"],
                                          motivo, uid)
    return {"id_orden": id_orden, "nro": nro, "nro_orden": nro_orden, "conciliado": conciliado, "razon": razon}


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
            # Las transferencias de afiliados (cuota social del convenio) van aparte, por
            # Beneficios › Recibos de Adheridos (pedido del 17/11/2026): acá solo se cuentan.
            de_afiliados = [f for f in filas if f["emp"]["como"] == "afiliado"]
            filas = [f for f in filas if f["emp"]["como"] != "afiliado"]
            cur.execute("""SELECT r.*, e.razon_social, u.nombre AS usuario,
                                  (SELECT p.razon_social FROM p_empresas p WHERE p.CUIT = CAST(r.cuit_pagador AS UNSIGNED))
                                    AS razon_pagador
                             FROM fisca_cuit_relacionado r
                             LEFT JOIN p_empresas e ON e.CUIT = CAST(r.cuit_empleador AS UNSIGNED)
                             LEFT JOIN s_usuarios u ON u.id = r.id_usuario
                            WHERE r.activo = 1
                            ORDER BY e.razon_social, r.cuit_pagador""")
            rels = cur.fetchall()
            esq = esquema_pagadores(cur)
            rels_afi = []
            if esq["afiliado"]:
                cur.execute("""SELECT r.*, a.apellido_nombres, a.activo AS afiliado_activo, u.nombre AS usuario
                                 FROM fisca_cuit_afiliado r
                                 LEFT JOIN p_afiliados a ON a.id_afiliado = (SELECT MIN(x.id_afiliado) FROM p_afiliados x
                                                                              WHERE x.cuil = r.cuil_afiliado)
                                 LEFT JOIN s_usuarios u ON u.id = r.id_usuario
                                WHERE r.activo = 1
                                ORDER BY a.apellido_nombres, r.cuit_pagador""")
                rels_afi = cur.fetchall()
    res = {"cant": len(filas), "total": sum((f["importe"] for f in filas), Decimal("0"))}
    for k in ESTADOS:
        sel = [f for f in filas if f["estado"] == k]
        res[k] = (len(sel), sum((f["importe"] for f in sel), Decimal("0")))
    sel = [f for f in filas if f["en_lote"]]
    res["lote"] = (len(sel), sum((f["importe"] for f in sel), Decimal("0")))
    sel = [f for f in filas if f["estado"] == "pendiente" and not f["en_lote"]]
    res["a_mano"] = (len(sel), sum((f["importe"] for f in sel), Decimal("0")))
    return render_template("fisca/recibos.html", cuentas=cuentas, cuenta=cuenta, id_cuenta=id_cuenta, filas=filas,
                           relaciones=rels, relaciones_afi=rels_afi, esq=esq,
                           desde=desde, hasta=hasta, res=res, estados=ESTADOS, como=COMO,
                           de_afiliados=(len(de_afiliados), sum((f["importe"] for f in de_afiliados), Decimal("0"))),
                           puede_beneficios=puede(URL_BENEFICIOS),
                           emitibles=EMITIBLES, excedido=excedido, tope=TOPE, falta_esquema=False,
                           puede_extractos=puede("/tesoreria/extractos"), puede_conc=puede("/tesoreria/conc"),
                           puede_ingreso=puede("/tesoreria/nueva_orden_concepto") or puede("/tesoreria/movimientos"))


def _volver_lista(id_cuenta=None, desde=None, hasta=None):
    f = request.form
    return redirect(url_for("fisca_rec.lista", cuenta=id_cuenta or f.get("cuenta") or None,
                            desde=desde or f.get("desde") or None, hasta=hasta or f.get("hasta") or None))


def leer_imputaciones(form) -> list[tuple[int, Decimal]]:
    """Las cuotas tildadas del acuerdo con su importe (c_id / c_importe / c_sel_<id>)."""
    out = []
    for id_txt, imp in zip(form.getlist("c_id"), form.getlist("c_importe")):
        if not id_txt.isdigit() or not form.get(f"c_sel_{id_txt}"):
            continue
        v = leer_importe(imp)
        if v and v > 0:
            out.append((int(id_txt), _d(v)))
    return out


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
                flash(f"!Esa acreditación ya tiene el recibo {ya['nro_recibo'] or ya['nro_orden']}.")
                return redirect(url_for("fisca_rec.recibo", id_orden=ya["id_orden"]))
            emp_todas, rel = empresas(cur), relaciones(cur)
            pagador = digitos(e["cuit"])
            pag = pagadores_afiliado(cur)
            cuotas = cuotas_sociales(cur, RA.config(cur))
            social = RA.es_cuota_social(e["credito"], e["fecham"], cuotas)
            sugerido = resolver_empleador(pagador, emp_todas, rel,
                                          afiliados_de(cur, ({pagador} - set(emp_todas)) | set(pag.values())), pag,
                                          social)
            sugerido = por_su_empleador(sugerido, _d(e["credito"]), e["fecham"], cuotas,
                                        empleadores_de(cur, {sugerido.get("cuil")}), emp_todas)
            # El recibo al afiliado (la cuota social), salvo que se elija un empleador.
            cfg = RA.config(cur)
            modo_afiliado = bool(cfg) and sugerido["como"] == "afiliado" and request.values.get("para") != "empleador" \
                and not request.values.get("cuit")
            if modo_afiliado:
                # El recibo al afiliado se emite en Beneficios (con la cuota de su grupo, 17/11/2026).
                return redirect(url_for("ben_conv.emitir_uno", id_extracto=id_extracto,
                                        cuenta=e["c_cuentas_de_fondos_id"], desde=request.values.get("desde") or None,
                                        hasta=request.values.get("hasta") or None))
            afi = RA.afiliado(cur, sugerido.get("cuil") or pagador) if modo_afiliado else None
            cubierta = (RA.cubierta(e["fecham"], RA.ordenes_aeda(cur, e["c_cuentas_de_fondos_id"], cfg["motivo"],
                                                                  e["fecham"], e["fecham"])) if modo_afiliado else None)
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
            # Fiscalización: los acuerdos de pago del empleador que deben algo.
            acuerdos = FRA.acuerdos_cobrables(cur, elegido) if razon else []
            id_acuerdo = request.values.get("acuerdo", type=int)
            acuerdo = next((x for x in acuerdos if x["id"] == id_acuerdo), None)
            if id_acuerdo and not acuerdo:
                errores.append("Ese acuerdo de pago no es de este empleador o ya no debe nada.")
            est = FRA.estado_cobro(cur, acuerdo) if acuerdo else None

    renglones = [(p, imp) for p, imp in distribuir(e["credito"], e["fecham"],
                                                     {p: v["saldo"] for p, v in saldos.items()})] if razon else []
    if modo_afiliado:
        renglones = RA.periodos(e["credito"], e["fecham"], cfg["cuota"])
    # Lo que pagó un afiliado por el empleador de su ficha se reconoce solo
    # (por_su_empleador): recordarlo no hace falta. Si eligió otro empleador, sí:
    # la relación es de la cuota sindical y no se lleva su cuota social.
    recordar = (pagador != elegido and len(pagador) == 11 and elegido not in rel.get(pagador, ())
                and not (sugerido["como"] == "por_afiliado" and elegido == sugerido["cuit"]))
    obs = ""
    imput = dict(FRA.sugerir(est["cuotas"], e["credito"])) if est else {}
    accion = request.form.get("accion") if request.method == "POST" else None

    if accion == "emitir_afiliado" and modo_afiliado:
        obs = " ".join((request.form.get("observaciones") or "").split())[:250]
        renglones, errores = RA.leer_renglones(request.form)
        if cubierta:
            errores.append(f"AEDA ya registró esta acreditación en su orden {cubierta['nro_orden']}.")
        if not errores:
            conn = get_connection()
            try:
                conn.begin()
                with conn.cursor() as cur:
                    r = RA.emitir(cur, _extracto_bloqueado(cur, id_extracto), pagador, renglones, _uid(), cfg,
                                  obs or None, fecha_valida=_fecha_valida)
                conn.commit()
            except ERRORES as ex:
                conn.rollback()
                errores.append(str(ex))
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            if not errores:
                flash(f"Recibo {r['nro']} emitido a {r['razon']} por {pesos(r['total'])} ({cfg['concepto']})."
                      + (f" Quedó conciliado en la conciliación {periodo_txt(r['conciliado'])}." if r["conciliado"] else ""))
                return redirect(url_for("fisca_rec.recibo", id_orden=r["id_orden"]))

    if accion in ("emitir", "emitir_fisca"):
        recordar = bool(request.form.get("recordar"))
        obs = " ".join((request.form.get("observaciones") or "").split())[:250]
        if accion == "emitir":
            renglones, errores = leer_renglones(request.form)
        else:
            imput = dict(leer_imputaciones(request.form))
            errores = [] if acuerdo else ["Elegí el acuerdo de pago."]
        if not razon:
            errores.append("Elegí el empleador.")
        if not errores:
            conn = get_connection()
            try:
                conn.begin()
                with conn.cursor() as cur:
                    if accion == "emitir":
                        r = emitir(cur, id_extracto, elegido, renglones, _uid(), obs or None, recordar)
                    else:
                        r = FRA.emitir(cur, id_acuerdo=acuerdo["id"], imputaciones=list(imput.items()), uid=_uid(),
                                       extracto=_extracto_bloqueado(cur, id_extracto), observaciones=obs or None,
                                       fecha_valida=_fecha_valida)
                        if recordar:
                            _recordar(cur, pagador, elegido, r["nro"], _uid())
                conn.commit()
            except ERRORES as ex:
                conn.rollback()
                errores.append(str(ex))
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            if not errores:
                if accion == "emitir":
                    texto = f"Recibo {r['nro']} emitido a {r['razon']} por {pesos(e['credito'])}."
                else:
                    texto = (f"Recibo de fiscalización {r['nro']} emitido a {r['razon']} por {pesos(r['total'])}: "
                             f"{pesos(r['capital'])} de cuota sindical del acta y {pesos(r['interes'])} de intereses."
                             + (f" El acuerdo {r['nro_acuerdo']} quedó pagado." if r["acuerdo_cancelado"] else ""))
                flash(texto
                      + (f" Quedó conciliado en la conciliación {periodo_txt(r['conciliado'])}." if r["conciliado"] else "")
                      + (" Los próximos pagos de ese CUIT se reconocen solos." if recordar else ""))
                return redirect(url_for("fisca_rec.recibo", id_orden=r["id_orden"]))

    capital = interes = None
    if est:
        capital, interes = FRA.partir(_d(e["credito"]), est["falta_capital"], est["falta_acuerdo"])
    periodos = sorted(set(saldos) | set(sin_liq), reverse=True)
    return render_template("fisca/recibo_emitir.html", e=e, errores=errores, sugerido=sugerido, elegido=elegido,
                           razon=razon, saldos=saldos, sin_liq=sin_liq, periodos=periodos, renglones=renglones,
                           recordar=recordar, obs=obs, fila=fila, conciliado=conciliado, pagador=pagador,
                           como=COMO, estados=ESTADOS, periodo_mes=periodo_anterior(e["fecham"]),
                           hoy=datetime.date.today().strftime("%Y-%m"),
                           acuerdos=acuerdos, acuerdo=acuerdo, est=est, imput=imput, capital=capital, interes=interes,
                           estados_cuota=ESTADOS_CUOTA,
                           modo_afiliado=modo_afiliado, afi=afi, cfg=cfg, cubierta=cubierta,
                           mes_max=RA.periodo_txt(RA.sumar_meses(e["fecham"].strftime("%Y%m"), RA.MAX_MESES - 1)),
                           volver=url_for("fisca_rec.lista", cuenta=e["c_cuentas_de_fondos_id"],
                                          desde=request.values.get("desde") or None,
                                          hasta=request.values.get("hasta") or None))


def _recordar(cur, pagador, cuit_emp, nro, uid) -> None:
    if len(pagador) == 11 and pagador != cuit_emp:
        cur.execute("""INSERT INTO fisca_cuit_relacionado (cuit_pagador, cuit_empleador, observaciones, id_usuario)
                       VALUES (%s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE activo = 1""",
                    (pagador, cuit_emp, f"Al emitir el recibo {nro}"[:250], uid))


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
            cfg = RA.config(cur)
    elegidas = [f for f in filas if f["id"] in ids]
    uid = _uid()
    hechos, total, saltados, fallados = 0, Decimal("0"), 0, []
    for f in elegidas:
        if not f["en_lote"] or not f["sugerido"] or f.get("al_afiliado"):
            saltados += 1
            continue
        conn = get_connection()
        try:
            conn.begin()
            with conn.cursor() as cur:
                if f.get("al_afiliado"):
                    RA.emitir(cur, _extracto_bloqueado(cur, f["id"]), f["emp"].get("cuil") or digitos(f["cuit"]),
                              f["sugerido"], uid, cfg,
                              fecha_valida=_fecha_valida)
                else:
                    emitir(cur, f["id"], f["emp"]["cuit"], f["sugerido"], uid)
            conn.commit()
            hechos += 1
            total += f["importe"]
        except ERRORES as ex:
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
        flash(f"!{saltados} no se emitieron: ya tienen recibo, el empleador no es seguro o el pago del afiliado no es "
              "un número justo de cuotas. Se emiten de a uno.")
    for t in fallados[:10]:
        flash("!" + t)
    if len(fallados) > 10:
        flash(f"!…y {len(fallados) - 10} más.")
    return _volver_lista(id_cuenta)


def leer_recibo(cur, id_orden) -> dict | None:
    cur.execute("""SELECT o.*, u.nombre AS usuario_creacion, ua.nombre AS usuario_anulacion, cf.nombre AS cuenta,
                          cf.numero_de_cuenta, cf.tipo_de_cuenta
                     FROM ingreso_ordenes o
                     LEFT JOIN s_usuarios u  ON u.id  = o.id_usuario_creacion
                     LEFT JOIN s_usuarios ua ON ua.id = o.id_usuario_anulacion
                     LEFT JOIN c_cuentas_de_fondos cf ON cf.id = o.id_cuenta
                    WHERE o.id = %s""", (id_orden,))
    o = cur.fetchone()
    if not o:
        return None
    o["nro_recibo"] = RT.numeros(cur, [o["id"]]).get(o["id"])
    o["numero"] = o["nro_recibo"] or o["nro_orden"]
    cur.execute("""SELECT d.*, m.descripcion AS motivo FROM ingreso_ordenes_detalle d
                     LEFT JOIN c_motivos_de_ingreso m ON m.id = d.id_motivo_ingreso
                    WHERE d.id_orden = %s ORDER BY d.periodo IS NULL, d.periodo, d.id""", (id_orden,))
    o["detalle"] = cur.fetchall()
    for d in o["detalle"]:
        d["es_interes"] = (d["motivo"] or "").upper() == FRA.MOTIVO_INTERES
    cuit = next((d["cuit"] for d in o["detalle"] if d["cuit"]), None)
    o["cuit"] = cuit
    o["empresa"] = None
    o["afiliado"], o["concepto"] = None, None
    if o["clase"] == "afiliado":
        o["afiliado"] = RA.afiliado(cur, o.get("cuil_afiliado")) or {"cuil": o.get("cuil_afiliado"), "apellido_nombres": None}
        o["cuit"] = cuit = None
        o["concepto"] = RA.concepto_de(o["detalle"])
    if cuit:
        cur.execute("SELECT id, razon_social FROM p_empresas WHERE CUIT = %s", (int(cuit),))
        o["empresa"] = cur.fetchone()
    ext = next((d["id_extracto_origen"] for d in o["detalle"] if d["id_extracto_origen"]), None)
    o["extracto"] = None
    if ext:
        cur.execute("SELECT * FROM c_extractos_bancarios WHERE id = %s", (ext,))
        o["extracto"] = cur.fetchone()
    o["en_letras"] = en_letras(o["importe_total"])
    o["acuerdo"], o["imputaciones"] = None, []
    if o.get("id_acuerdo"):
        cur.execute("""SELECT x.id, x.nro_acuerdo, x.estado, x.id_acta, a.nro_acta, x.cantidad_cuotas
                         FROM fisca_acuerdo x JOIN fisca_acta a ON a.id = x.id_acta WHERE x.id = %s""", (o["id_acuerdo"],))
        o["acuerdo"] = cur.fetchone()
        cur.execute("""SELECT c.nro_cuota, c.vencimiento, c.importe AS importe_cuota, i.importe
                         FROM fisca_acuerdo_imputacion i JOIN fisca_acuerdo_cuota c ON c.id = i.id_cuota
                        WHERE i.id_orden = %s ORDER BY c.nro_cuota""", (id_orden,))
        o["imputaciones"] = cur.fetchall()
    o["capital"] = sum((_d(d["importe"]) for d in o["detalle"] if not d["es_interes"]), Decimal("0"))
    o["interes"] = sum((_d(d["importe"]) for d in o["detalle"] if d["es_interes"]), Decimal("0"))
    return o


def _recibo_o_volver(cur, id_orden):
    o = leer_recibo(cur, id_orden)
    if not o or o["clase"] not in RT.CLASES:
        return None
    return o


@fisca_rec_bp.route("/recibos/<int:id_orden>")
def recibo(id_orden):
    salida = _guardia_ver()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            o = _recibo_o_volver(cur, id_orden)
    if not o:
        flash("!No existe ese recibo.")
        return redirect(url_for("fisca_rec.lista") if puede(URL) else URL_EMITIDOS)
    return render_template("fisca/recibo.html", o=o, puede_ingreso=puede("/tesoreria/movimientos")
                           or puede("/tesoreria/nueva_orden_concepto"),
                           puede_emision=puede(URL), volver_emitidos=_volver_emitidos(),
                           puede_anular=puede("/tesoreria/anulaciones"),
                           puede_acuerdo=puede("/fiscalizacion/acuerdos"),
                           puede_empleador=puede(url_for("empleadores.abm_empleadores")),
                           puede_afiliado=puede(url_for("afiliados.abm_afiliados")))


def recibo_pdf(o: dict):
    """El recibo en PDF, con el membrete de Datos del Sindicato (pagos_pdf)."""
    import pagos_pdf as P
    fisca = o["clase"] == "fiscalizacion"
    if o["clase"] == "afiliado":
        return _recibo_afiliado_pdf(o)
    doc = P._Doc("Recibo de fiscalización" if fisca else "Recibo", o["numero"],
                 "ANULADO" if o["estado"] == "anulado" else None)
    razon = escape((o["empresa"] or {}).get("razon_social") or "—")
    x = o["acuerdo"] or {}
    if fisca:
        concepto = (f"en concepto de pago del acuerdo de pago {escape(x.get('nro_acuerdo') or '—')} del acta de fiscalización "
                    f"{escape(x.get('nro_acta') or '—')}")
    else:
        concepto = "en concepto de cuota sindical"
    doc.story.append(doc.P(
        f"Recibimos de <b>{razon}</b> (CUIT {P._cuit(o['cuit'])}) la suma de <b>PESOS {escape(o['en_letras'])}</b> "
        f"(<b>{P._pesos(o['importe_total'])}</b>) {concepto}.", fontSize=10, leading=15, spaceAfter=10))
    datos = [("Número", escape(o["numero"])), ("Fecha", P._fecha(o["fecha"])), ("Empleador", razon),
             ("CUIT", P._cuit(o["cuit"])), ("Importe", P._pesos(o["importe_total"]))]
    if fisca:
        datos += [("Acta", escape(x.get("nro_acta") or "—")), ("Acuerdo de pago", escape(x.get("nro_acuerdo") or "—"))]
    doc.datos("RECIBO", datos)
    if fisca:
        doc.tabla("CUOTAS DEL ACUERDO", ["Cuota", "Vencimiento", "Importe de la cuota", "Pagado con este recibo"],
                  [[f"{c['nro_cuota']} de {x.get('cantidad_cuotas') or '—'}", P._fecha(c["vencimiento"]),
                    P._pesos(c["importe_cuota"]), P._pesos(c["importe"])] for c in o["imputaciones"]],
                  [3.0, 3.5, 4.5, 5.0], derecha=(2, 3), total=("Total", P._pesos(o["importe_total"])))
        filas = [[periodo_txt(d["periodo"]), "Cuota sindical del período", P._pesos(d["importe"])]
                 for d in o["detalle"] if not d["es_interes"]]
        filas += [["—", "Intereses resarcitorios y de financiación", P._pesos(d["importe"])]
                  for d in o["detalle"] if d["es_interes"]]
        doc.tabla("IMPUTACIÓN", ["Período", "Concepto", "Importe"], filas, [3.0, 10.0, 3.0], derecha=(2,),
                  total=("Total", P._pesos(o["importe_total"])))
    else:
        doc.tabla("PERÍODOS", ["Período", "Concepto", "Importe"],
                  [[periodo_txt(d["periodo"]), "Cuota sindical", P._pesos(d["importe"])] for d in o["detalle"]],
                  [3.0, 10.0, 3.0], derecha=(2,), total=("Total", P._pesos(o["importe_total"])))
    _pie_pdf(doc, o, o["cuit"])
    return P.respuesta(doc.pdf(f"Recibo {o['numero']}"), f"Recibo {o['numero']}.pdf")


def _pie_pdf(doc, o, cuit_receptor) -> None:
    """La forma de pago y la firma, iguales en todos los recibos."""
    import pagos_pdf as P
    from reportlab.lib.units import cm
    from reportlab.platypus import Spacer, Table, TableStyle
    e = o["extracto"] or {}
    if e:
        pago = [("Medio", "Acreditación bancaria"),
                ("Cuenta", P._txt(o.get("cuenta")) + (f" N° {P._txt(o['numero_de_cuenta'])}" if o.get("numero_de_cuenta") else "")),
                ("Acreditada el", P._fecha(e.get("fecham"))), ("Referencia", P._txt(e.get("ref_nro"))),
                ("Concepto del banco", P._txt(e.get("concepto"))),
                ("Pagó", P._cuit(e.get("cuit")) if digitos(e.get("cuit")) and digitos(e.get("cuit")) != cuit_receptor else "")]
    else:
        pago = [("Medio", "Efectivo" if o.get("tipo_de_cuenta") == "C" else "Depósito o transferencia bancaria"),
                ("Cuenta", P._txt(o.get("cuenta")) + (f" N° {P._txt(o['numero_de_cuenta'])}" if o.get("numero_de_cuenta") else "")),
                ("Fecha", P._fecha(o["fecha"]))]
    doc.datos("FORMA DE PAGO", pago)
    doc.story.append(Spacer(1, 1.8 * cm))
    f = Table([[""], [doc.P("Firma y aclaración", alignment=1)]], colWidths=[6 * cm], rowHeights=[1.2 * cm, None],
              hAlign="RIGHT")
    f.setStyle(TableStyle([("LINEABOVE", (0, 1), (0, 1), 0.6, doc.MUTED)]))
    doc.story.append(f)


def _recibo_afiliado_pdf(o: dict):
    """El recibo al afiliado: la cuota social de los meses que paga."""
    import pagos_pdf as P
    a = o["afiliado"] or {}
    nombre = escape(a.get("apellido_nombres") or "—")
    cuil = a.get("cuil") or o.get("cuil_afiliado")
    concepto = escape(o["concepto"] or "cuota social")
    doc = P._Doc("Recibo", o["numero"], "ANULADO" if o["estado"] == "anulado" else None)
    meses = ", ".join(periodo_txt(d["periodo"]) for d in o["detalle"] if d["periodo"])
    doc.story.append(doc.P(
        f"Recibimos de <b>{nombre}</b> (CUIL {P._cuit(cuil)}) la suma de <b>PESOS {escape(o['en_letras'])}</b> "
        f"(<b>{P._pesos(o['importe_total'])}</b>) en concepto de {concepto[:1].lower() + concepto[1:]}"
        f"{' de ' + meses if meses else ''}.", fontSize=10, leading=15, spaceAfter=10))
    doc.datos("RECIBO", [("Número", escape(o["numero"])), ("Fecha", P._fecha(o["fecha"])), ("Afiliado", nombre),
                         ("CUIL", P._cuit(cuil)), ("Importe", P._pesos(o["importe_total"]))])
    doc.tabla("MESES", ["Mes", "Concepto", "Importe"],
              [[periodo_txt(d["periodo"]), concepto, P._pesos(d["importe"])] for d in o["detalle"]],
              [3.0, 10.0, 3.0], derecha=(2,), total=("Total", P._pesos(o["importe_total"])))
    _pie_pdf(doc, o, digitos(cuil))
    return P.respuesta(doc.pdf(f"Recibo {o['numero']}"), f"Recibo {o['numero']}.pdf")


@fisca_rec_bp.route("/recibos/<int:id_orden>/pdf")
def recibo_pdf_ruta(id_orden):
    salida = _guardia_ver()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            o = _recibo_o_volver(cur, id_orden)
    if not o:
        flash("!No existe ese recibo.")
        return redirect(url_for("fisca_rec.lista") if puede(URL) else URL_EMITIDOS)
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


@fisca_rec_bp.route("/recibos/asociar", methods=["POST"])
def asociar():
    """De quién es una acreditación (pedido del 18/11/2026). Si el banco no trajo
    el CUIT, se carga en el renglón (`cuit_manual`). Después, si el que pagó no
    es la misma empresa o el mismo afiliado, se lo relaciona: con una empresa
    (fisca_cuit_relacionado) o con un afiliado (fisca_cuit_afiliado)."""
    salida = _guardia()
    if salida:
        return salida
    id_ext = request.form.get("id_extracto", type=int)
    tipo = request.form.get("tipo")
    destino = digitos(request.form.get("destino"))
    escrito = digitos(request.form.get("cuit_pagador"))
    obs = " ".join((request.form.get("observaciones") or "").split())[:250] or None
    if tipo not in ("empresa", "afiliado"):
        flash("!Elegí si el pago es de una empresa o de un afiliado.")
        return _volver_asociar()
    msgs = []
    with get_connection() as conn:
        with conn.cursor() as cur:
            esq = esquema_pagadores(cur)
            cur.execute("SELECT * FROM c_extractos_bancarios WHERE id = %s FOR UPDATE", (id_ext,))
            e = cur.fetchone()
            if not e or _d(e["credito"]) <= 0:
                flash("!No existe esa acreditación.")
                return _volver_asociar()
            del_banco = digitos(e["cuit"]) if not e.get("cuit_manual") else ""
            pagador = del_banco or escrito or ""
            # Sin CUIT del banco ni escrito: el destino es el que pagó (lo más común:
            # el afiliado o la empresa transfirieron desde una cuenta propia).
            if not pagador and not del_banco:
                pagador = destino
            if not cuit_valido(pagador):
                flash(f"!El CUIT/CUIL de quien pagó ({pagador or 'vacío'}) no verifica.")
                return _volver_asociar()
            if not cuit_valido(destino):
                flash(f"!El {'CUIT de la empresa' if tipo == 'empresa' else 'CUIL del afiliado'} "
                      f"({destino or 'vacío'}) no verifica.")
                return _volver_asociar()
            if tipo == "empresa":
                cur.execute("SELECT razon_social FROM p_empresas WHERE CUIT = %s", (int(destino),))
                d = cur.fetchone()
                if not d:
                    flash(f"!El CUIT {destino} no está en Empleadores.")
                    return _volver_asociar()
                nombre = d["razon_social"]
            else:
                a = RA.afiliado(cur, destino)
                if not a:
                    flash(f"!El CUIL {destino} no está en el padrón.")
                    return _volver_asociar()
                nombre = a["apellido_nombres"]
            # Las dos asociaciones conviven (una de cada concepto): el mismo CUIT
            # puede pagar la cuota sindical de una empresa y la cuota social de un
            # afiliado. Solo una empresa no paga la cuota social de nadie: sus
            # pagos son siempre de ella.
            if pagador != destino and tipo == "afiliado":
                cur.execute("SELECT razon_social FROM p_empresas WHERE CUIT = %s", (int(pagador),))
                otra = cur.fetchone()
                if otra:
                    flash(f"!{pagador} es la empresa {otra['razon_social']}: sus pagos son de ella.")
                    return _volver_asociar()
                if not esq["afiliado"]:
                    flash("!Falta correr sql/recibos_pagadores_20261118.sql para asociar la cuota social a un afiliado.")
                    return _volver_asociar()
            if not del_banco:
                if not esq["manual"]:
                    flash("!El banco no trajo el CUIT y falta correr sql/recibos_pagadores_20261118.sql para cargarlo.")
                    return _volver_asociar()
                cur.execute("""UPDATE c_extractos_bancarios SET cuit = %s, cuit_manual = 1, cuit_manual_usuario = %s,
                                      cuit_manual_fecha = NOW() WHERE id = %s""", (pagador, _uid(), id_ext))
                msgs.append(f"La acreditación quedó con el CUIT {pagador} (cargado a mano).")
            if pagador != destino:
                if tipo == "empresa":
                    cur.execute("""INSERT INTO fisca_cuit_relacionado (cuit_pagador, cuit_empleador, observaciones, id_usuario)
                                   VALUES (%s, %s, %s, %s)
                                   ON DUPLICATE KEY UPDATE activo = 1,
                                       observaciones = COALESCE(VALUES(observaciones), observaciones)""",
                                (pagador, destino, obs, _uid()))
                else:
                    cur.execute("""INSERT INTO fisca_cuit_afiliado (cuit_pagador, cuil_afiliado, observaciones, id_usuario)
                                   VALUES (%s, %s, %s, %s)
                                   ON DUPLICATE KEY UPDATE cuil_afiliado = VALUES(cuil_afiliado), activo = 1,
                                       observaciones = COALESCE(VALUES(observaciones), observaciones),
                                       id_usuario = VALUES(id_usuario)""",
                                (pagador, destino, obs, _uid()))
                msgs.append(f"Los pagos de {pagador} de la {'cuota sindical' if tipo == 'empresa' else 'cuota social'} "
                            f"se reconocen como de {nombre}.")
            else:
                msgs.append(f"Es de {nombre}.")
        conn.commit()
    if tipo == "afiliado":
        msgs.append("El recibo al afiliado se emite en Beneficios › Convenio YMCA › Recibos.")
    flash(" ".join(msgs))
    return _volver_asociar()


def _volver_asociar():
    """A la pantalla de la que vino (Emisión de Recibos o Beneficios), solo rutas internas."""
    volver = (request.form.get("volver") or "").strip()
    if volver.startswith("/") and not volver.startswith("//") and "\\" not in volver:
        return redirect(volver)
    return _volver_lista()


@fisca_rec_bp.route("/recibos/afiliado/<int:id_rel>/baja", methods=["POST"])
def relacion_afiliado_baja(id_rel):
    salida = _guardia()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE fisca_cuit_afiliado SET activo = 0 WHERE id = %s", (id_rel,))
        conn.commit()
    flash("Relación dada de baja: los recibos ya emitidos no cambian.")
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
