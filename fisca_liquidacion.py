"""
fisca_liquidacion.py — Liquidación de cuota sindical por período.

Fiscalización de Cuotas → Liquidación de Cuota Sindical (`/fiscalizacion/liquidacion`,
menú 6, sql/fisca_liquidacion_20261111.sql). Lo que cada empleador tiene que
pagar en un período: una liquidación por CUIT y período (`fisca_liquidacion`)
con un renglón por afiliado (`fisca_liquidacion_detalle`). Es lo que hacía AEDA
en `fis_deuda` / `fis_deuda_detalle` (su historial lo trae
importar_aeda_fisca_deuda.py, origen «aeda»).

DE DÓNDE SALE LA REMUNERACIÓN (decidido el 11/11/2026)
- Si el empleador cargó la nómina del período (`fisca_cuotarecepcion`, Importar
  Cuotas), la remuneración que declaró, renglón por renglón. Origen «nomina».
- Si no, sus afiliados con la Remuneración imponible 5 de la DDJJ de OSEDA de
  ese período (`f_ddjj_procesada` en contable de Railway, en vivo, la regla de
  Fiscalización). Origen «ddjj». Es lo que hacía AEDA, que solo veía a los
  afiliados con OSEDA.
- La nómina manda: si el empleador la cargó, no se mira su DDJJ. Un afiliado
  con dos empleadores aparece en la liquidación de cada uno.
- Afiliado del período = titular del padrón (los familiares son personas a
  cargo, no afiliados) con alta hasta el último día del período y sin baja o
  con baja desde el primero. La nómina no se filtra: un renglón que no está en
  el padrón entra igual y la liquidación lo avisa.

CUOTA = remuneración × alícuota, redondeada al centavo por renglón; vence el día
fijado del mes siguiente (si el mes es más corto, el último). Alícuota y día
están en Datos del Sindicato (`s_institucion.cuota_alicuota`, `cuota_dia_vto`).

LIQUIDAR Y RELIQUIDAR
Liquidar un período lo calcula entero y graba en una transacción. Reliquidar
(volver a liquidarlo) rehace el detalle de cada empleador con lo que hay hoy
(una nómina cargada después, una DDJJ rectificada) y anula la liquidación de un
empleador que ya no tiene base, con la nota. Lo que vino de AEDA no se toca: es
la deuda que AEDA emitió.

Sin Railway configurado o con Railway caído se liquida igual lo que tiene
nómina; la pantalla lo avisa y el informe dice cuántos empleadores no se
pudieron mirar.
"""

from __future__ import annotations

import calendar
import datetime
import re
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

import pymysql
from flask import Blueprint, flash, redirect, render_template, request, url_for

import contable_oseda
from db import get_connection, puede, usuario_actual, validasesion

fisca_liq_bp = Blueprint("fisca_liq", __name__, url_prefix="/fiscalizacion")

CENT = Decimal("0.01")
ALICUOTA_DEFECTO = Decimal("2.50")
DIA_VTO_DEFECTO = 20
ORIGENES = {"nomina": "Nómina del empleador", "ddjj": "DDJJ de OSEDA", "aeda": "AEDA"}
ORIGEN_TIPO = {"nomina": "ok", "ddjj": "info", "aeda": "neutro"}


class ErrorLiquidacion(ValueError):
    """Un error de validación: el texto va directo a la pantalla."""


# ─────────────────────────────────────────────────────────────────────────────
# Período y parámetros
# ─────────────────────────────────────────────────────────────────────────────

def periodo_valido(texto) -> str | None:
    """«2026-04», «202604» o «04/2026» → «202604»; None si no es un período."""
    t = (texto or "").strip()
    m = re.fullmatch(r"(\d{4})-?(\d{2})", t) or re.fullmatch(r"(\d{2})/(\d{4})", t)
    if not m:
        return None
    anio, mes = (m.group(1), m.group(2)) if len(m.group(1)) == 4 else (m.group(2), m.group(1))
    return f"{anio}{mes}" if 1 <= int(mes) <= 12 and 2000 <= int(anio) <= 2100 else None


def limites(periodo: str) -> tuple[datetime.date, datetime.date]:
    anio, mes = int(periodo[:4]), int(periodo[4:])
    return datetime.date(anio, mes, 1), datetime.date(anio, mes, calendar.monthrange(anio, mes)[1])


def vencimiento(periodo: str, dia: int) -> datetime.date:
    anio, mes = int(periodo[:4]), int(periodo[4:])
    anio, mes = (anio + 1, 1) if mes == 12 else (anio, mes + 1)
    return datetime.date(anio, mes, min(dia, calendar.monthrange(anio, mes)[1]))


def parametros(cur) -> dict:
    """Alícuota y día de vencimiento de Datos del Sindicato (o los de siempre)."""
    try:
        cur.execute("SELECT cuota_alicuota, cuota_dia_vto FROM s_institucion WHERE id = 1")
        f = cur.fetchone() or {}
    except pymysql.err.OperationalError as e:  # falta sql/fisca_liquidacion_20261111.sql
        if "cuota_alicuota" not in str(e):
            raise
        f = {}
    return {"alicuota": Decimal(str(f.get("cuota_alicuota") or ALICUOTA_DEFECTO)),
            "dia_vto": int(f.get("cuota_dia_vto") or DIA_VTO_DEFECTO)}


def _cuota(remuneracion, alicuota: Decimal) -> Decimal:
    return (Decimal(str(remuneracion or 0)) * alicuota / 100).quantize(CENT, rounding=ROUND_HALF_UP)


# ─────────────────────────────────────────────────────────────────────────────
# Cálculo
# ─────────────────────────────────────────────────────────────────────────────

def calcular(cur, periodo: str) -> dict:
    """Lo que corresponde liquidar en el período, sin grabar nada.

    {"empleadores": {cuit: {"origen", "lineas": [{cuil, id_afiliado, nombre,
    remuneracion, cuota, fuente}]}}, "alicuota", "dia_vto", "ddjj_ok", "avisos"}.
    """
    par = parametros(cur)
    desde, hasta = limites(periodo)
    avisos = []

    cur.execute("""SELECT id_afiliado, cuil, apellido_nombres FROM p_afiliados
                    WHERE cuil REGEXP '^[0-9]{11}$' AND cod_parentesco = 0
                      AND (fecha_alta IS NULL OR fecha_alta <= %s)
                      AND (fecha_baja IS NULL OR fecha_baja >= %s)""", (hasta, desde))
    padron = {f["cuil"]: f for f in cur.fetchall()}
    cur.execute("SELECT cuil, id_afiliado, apellido_nombres FROM p_afiliados WHERE cuil REGEXP '^[0-9]{11}$'")
    todos = {f["cuil"]: f for f in cur.fetchall()}

    empleadores: dict[str, dict] = {}

    # 1) Nóminas cargadas por los empleadores.
    cur.execute("""SELECT cuit, cuil, remuneracion FROM fisca_cuotarecepcion
                    WHERE periodo = %s ORDER BY cuit, cuil""", (int(periodo),))
    for f in cur.fetchall():
        cuit = re.sub(r"\D", "", f["cuit"] or "")
        cuil = re.sub(r"\D", "", f["cuil"] or "")
        if len(cuit) != 11 or len(cuil) != 11:
            continue
        e = empleadores.setdefault(cuit, {"origen": "nomina", "lineas": {}})
        a = todos.get(cuil) or {}
        linea = e["lineas"].setdefault(cuil, {"cuil": cuil, "id_afiliado": a.get("id_afiliado"),
                                              "nombre": a.get("apellido_nombres"),
                                              "remuneracion": Decimal("0"), "fuente": "nomina"})
        linea["remuneracion"] += Decimal(str(f["remuneracion"] or 0))   # dos renglones del mismo CUIL se suman

    # 2) DDJJ de OSEDA de los afiliados, para los empleadores sin nómina.
    ddjj_ok = True
    try:
        filas = contable_oseda.ddjj_del_periodo(periodo, padron.keys())
    except contable_oseda.ContableNoDisponible as e:
        ddjj_ok, filas = False, []
        avisos.append(f"No se pudieron leer las DDJJ de OSEDA ({e}). Se liquidó solo lo que tiene nómina.")
    sin_nomina = set()
    for f in filas:
        cuit = re.sub(r"\D", "", f["cuit"] or "")
        if len(cuit) != 11:
            continue
        e = empleadores.get(cuit)
        if e and e["origen"] == "nomina":
            continue                            # la nómina manda
        a = padron[f["cuil"]]
        e = empleadores.setdefault(cuit, {"origen": "ddjj", "lineas": {}})
        sin_nomina.add(cuit)
        linea = e["lineas"].setdefault(f["cuil"], {"cuil": f["cuil"], "id_afiliado": a["id_afiliado"],
                                                   "nombre": a["apellido_nombres"],
                                                   "remuneracion": Decimal("0"), "fuente": "ddjj"})
        linea["remuneracion"] += Decimal(str(f["rem5"] or 0))

    # Cuota por renglón; sin remuneración no hay cuota (y el renglón no va).
    for cuit in list(empleadores):
        e = empleadores[cuit]
        lineas = []
        for l in e["lineas"].values():
            if l["remuneracion"] <= 0:
                continue
            l["cuota"] = _cuota(l["remuneracion"], par["alicuota"])
            lineas.append(l)
        if not lineas:
            del empleadores[cuit]
            continue
        e["lineas"] = lineas
        e["remuneracion"] = sum(l["remuneracion"] for l in lineas)
        e["importe"] = sum(l["cuota"] for l in lineas)
        e["fuera_padron"] = sum(1 for l in lineas if not l["id_afiliado"])
    return {"empleadores": empleadores, "ddjj_ok": ddjj_ok, "avisos": avisos, **par}


# ─────────────────────────────────────────────────────────────────────────────
# Grabar
# ─────────────────────────────────────────────────────────────────────────────

def generar(cur, periodo: str, id_usuario: int | None, calculo: dict | None = None) -> dict:
    """Liquida (o reliquida) el período. Devuelve el resumen para la pantalla."""
    calculo = calculo or calcular(cur, periodo)
    hoy = datetime.date.today()
    vto = vencimiento(periodo, calculo["dia_vto"])
    r = {"nuevas": 0, "reliquidadas": 0, "iguales": 0, "de_aeda": 0, "anuladas": 0,
         "importe": Decimal("0"), "avisos": list(calculo["avisos"])}

    cur.execute("""SELECT id, cuit, origen, estado, importe, afiliados FROM fisca_liquidacion
                    WHERE periodo = %s FOR UPDATE""", (periodo,))
    existentes = {f["cuit"]: f for f in cur.fetchall()}

    for cuit, e in sorted(calculo["empleadores"].items()):
        ya = existentes.get(cuit)
        if ya and ya["origen"] == "aeda":
            r["de_aeda"] += 1
            continue
        nota = (f"{e['fuera_padron']} renglón(es) de la nómina no están en el padrón."
                if e["fuera_padron"] else None)
        if ya:
            iguales = (ya["estado"] == "vigente" and ya["origen"] == e["origen"]
                       and Decimal(str(ya["importe"])) == e["importe"] and ya["afiliados"] == len(e["lineas"]))
            cur.execute("""UPDATE fisca_liquidacion
                              SET fecha = %s, vencimiento = %s, alicuota = %s, afiliados = %s, remuneracion = %s,
                                  importe = %s, origen = %s, estado = 'vigente', observaciones = %s, id_usuario = %s
                            WHERE id = %s""",
                        (hoy, vto, calculo["alicuota"], len(e["lineas"]), e["remuneracion"], e["importe"],
                         e["origen"], nota, id_usuario, ya["id"]))
            id_liq = ya["id"]
            cur.execute("DELETE FROM fisca_liquidacion_detalle WHERE id_liquidacion = %s", (id_liq,))
            r["iguales" if iguales else "reliquidadas"] += 1
        else:
            cur.execute("""INSERT INTO fisca_liquidacion
                             (cuit, periodo, fecha, vencimiento, alicuota, afiliados, remuneracion, importe, origen,
                              estado, observaciones, id_usuario)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'vigente', %s, %s)""",
                        (cuit, periodo, hoy, vto, calculo["alicuota"], len(e["lineas"]), e["remuneracion"],
                         e["importe"], e["origen"], nota, id_usuario))
            id_liq = cur.lastrowid
            r["nuevas"] += 1
        cur.executemany("""INSERT INTO fisca_liquidacion_detalle
                             (id_liquidacion, cuil, id_afiliado, apellido_nombres, remuneracion, cuota, fuente)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        [(id_liq, l["cuil"], l["id_afiliado"], (l["nombre"] or None) and l["nombre"][:100],
                          l["remuneracion"], l["cuota"], l["fuente"]) for l in e["lineas"]])
        r["importe"] += e["importe"]

    # Lo liquidado antes que hoy ya no tiene base (la nómina se borró, la DDJJ se
    # rectificó en cero). Si Railway no respondió no se anula nada de la DDJJ:
    # no saber no es lo mismo que no tener.
    for cuit, ya in existentes.items():
        if cuit in calculo["empleadores"] or ya["origen"] == "aeda" or ya["estado"] == "anulada":
            continue
        if ya["origen"] == "ddjj" and not calculo["ddjj_ok"]:
            continue
        cur.execute("""UPDATE fisca_liquidacion SET estado = 'anulada', id_usuario = %s,
                              observaciones = %s WHERE id = %s""",
                    (id_usuario, f"Anulada al reliquidar el {hoy:%d/%m/%Y}: sin nómina ni DDJJ en el período.",
                     ya["id"]))
        r["anuladas"] += 1
    return r


# ─────────────────────────────────────────────────────────────────────────────
# Pantallas
# ─────────────────────────────────────────────────────────────────────────────

def _guardia():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede(url_for("fisca_liq.liquidacion")):
        flash("!No tenés permiso para la liquidación de cuota sindical.")
        return redirect(url_for("menu"))
    return None


def _periodo_sugerido() -> str:
    """El mes anterior: es el que se liquida (vence el mes en curso)."""
    hoy = datetime.date.today().replace(day=1) - datetime.timedelta(days=1)
    return hoy.strftime("%Y%m")


@fisca_liq_bp.route("/liquidacion")
def liquidacion():
    salida = _guardia()
    if salida:
        return salida
    periodo = periodo_valido(request.args.get("periodo"))
    with get_connection() as conn:
        with conn.cursor() as cur:
            par = parametros(cur)
            cur.execute("""SELECT l.periodo, COUNT(*) AS empleadores, SUM(l.afiliados) AS afiliados,
                                  SUM(l.remuneracion) AS remuneracion, SUM(l.importe) AS importe,
                                  SUM(l.origen = 'nomina') AS por_nomina, SUM(l.origen = 'ddjj') AS por_ddjj,
                                  SUM(l.origen = 'aeda') AS de_aeda, MAX(l.fecha) AS liquidado, MIN(l.vencimiento) AS vto
                             FROM fisca_liquidacion l WHERE l.estado = 'vigente'
                            GROUP BY l.periodo ORDER BY l.periodo DESC""")
            periodos = cur.fetchall()
            filas = []
            if periodo:
                cur.execute("""SELECT l.*, e.razon_social, u.nombre AS usuario
                                 FROM fisca_liquidacion l
                                 LEFT JOIN p_empresas e ON e.CUIT = CAST(l.cuit AS UNSIGNED)
                                 LEFT JOIN s_usuarios u ON u.id = l.id_usuario
                                WHERE l.periodo = %s
                                ORDER BY l.estado DESC, l.importe DESC""", (periodo,))
                filas = cur.fetchall()
    vigentes = [f for f in filas if f["estado"] == "vigente"]
    return render_template("fisca/liquidacion.html", periodo=periodo, periodos=periodos, filas=filas,
                           total=sum((f["importe"] for f in vigentes), Decimal("0")),
                           total_remu=sum((f["remuneracion"] for f in vigentes), Decimal("0")),
                           total_afil=sum(f["afiliados"] for f in vigentes), n_vigentes=len(vigentes),
                           sugerido=_periodo_sugerido(), par=par, origenes=ORIGENES, origen_tipo=ORIGEN_TIPO,
                           de_aeda=any(f["origen"] == "aeda" for f in filas))


@fisca_liq_bp.route("/liquidacion/generar", methods=["POST"])
def liquidacion_generar():
    salida = _guardia()
    if salida:
        return salida
    periodo = periodo_valido(request.form.get("periodo"))
    if not periodo:
        flash("!Elegí el período a liquidar.")
        return redirect(url_for("fisca_liq.liquidacion"))
    if limites(periodo)[0] > datetime.date.today():
        flash("!Un período que todavía no empezó no se liquida.")
        return redirect(url_for("fisca_liq.liquidacion", periodo=periodo))
    usuario = usuario_actual() or {}
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            r = generar(cur, periodo, usuario.get("id"))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    partes = [f"{n} {t}" for n, t in ((r["nuevas"], "nuevas"), (r["reliquidadas"], "reliquidadas"),
                                       (r["iguales"], "sin cambios"), (r["anuladas"], "anuladas"),
                                       (r["de_aeda"], "de AEDA sin tocar")) if n]
    per = f"{periodo[:4]}-{periodo[4:]}"
    total = f"{r['importe']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    flash(f"Período {per} liquidado: " + (", ".join(partes) or "no hay nada para liquidar")
          + f". Cuota liquidada: $ {total}.")
    for a in r["avisos"]:
        flash("!" + a)
    return redirect(url_for("fisca_liq.liquidacion", periodo=periodo))


@fisca_liq_bp.route("/liquidacion/<int:id_liq>")
def liquidacion_ficha(id_liq):
    salida = _guardia()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT l.*, e.razon_social, e.id AS id_empresa, u.nombre AS usuario
                             FROM fisca_liquidacion l
                             LEFT JOIN p_empresas e ON e.CUIT = CAST(l.cuit AS UNSIGNED)
                             LEFT JOIN s_usuarios u ON u.id = l.id_usuario
                            WHERE l.id = %s""", (id_liq,))
            liq = cur.fetchone()
            if not liq:
                flash("!No existe esa liquidación.")
                return redirect(url_for("fisca_liq.liquidacion"))
            cur.execute("""SELECT d.*, COALESCE(d.apellido_nombres, a.apellido_nombres) AS nombre
                             FROM fisca_liquidacion_detalle d
                             LEFT JOIN p_afiliados a ON a.id_afiliado = d.id_afiliado
                            WHERE d.id_liquidacion = %s ORDER BY nombre, d.cuil""", (id_liq,))
            detalle = cur.fetchall()
    return render_template("fisca/liquidacion_ficha.html", liq=liq, detalle=detalle, origenes=ORIGENES,
                           origen_tipo=ORIGEN_TIPO, puede_empleador=puede(url_for("empleadores.abm_empleadores")))
