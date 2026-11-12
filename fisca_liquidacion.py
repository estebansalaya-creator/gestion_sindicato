"""
fisca_liquidacion.py — Liquidación de cuota sindical por período.

Fiscalización de Cuotas → Liquidación de Cuota Sindical (`/fiscalizacion/liquidacion`,
menú 6, sql/fisca_liquidacion_20261111.sql). Lo que cada empleador tiene que
pagar en un período: una liquidación por CUIT y período (`fisca_liquidacion`)
con un renglón por afiliado (`fisca_liquidacion_detalle`). Es lo que hacía AEDA
en `fis_deuda` / `fis_deuda_detalle` (su historial lo trae
importar_aeda_fisca_deuda.py, origen «aeda»).

DE DÓNDE SALE LA REMUNERACIÓN (decidido el 12/11/2026)
- De la DDJJ de OSEDA del período: la Remuneración imponible 5 de cada afiliado
  (`f_ddjj_procesada` en contable de Railway, en vivo), y la liquidación es del
  CUIT que lo declaró. Origen «ddjj». La nómina que cargan los empleadores
  (`fisca_cuotarecepcion`, Importar Cuotas) ya no se usa para liquidar.
- Afiliado del período = titular del padrón (los familiares son personas a
  cargo) con alta hasta el último día del período y sin baja o con baja desde
  el primero. Un afiliado con dos empleadores aparece en la liquidación de cada
  uno que lo declaró.

ACTIVOS DEL EMPLEADOR Y PORCENTAJE CON DDJJ (pedido del 12/11/2026)
Cada liquidación lleva TODOS los titulares activos del empleador en el período,
con DDJJ o sin ella: un renglón por CUIL. Activo del empleador = afiliado del
período con una relación laboral (`p_relaciones_laborales`) con ese CUIT
vigente en el período: ingreso hasta el último día (o sin ingreso) y egreso
desde el primero; las de AEDA no traen egreso, así que una relación inactiva
sin egreso termina con la baja del afiliado, y si el afiliado no tiene baja (se
cambió de empleador en algún momento que no se sabe) no cuenta.
- `afiliados_activos` = total de CUIL activos; `activos_con_ddjj` = los que
  están en la DDJJ de ESE empleador en el período; `activos_sin_ddjj` y
  `porc_ddjj` son columnas calculadas en la base.
- Renglones: «ddjj» (declarado, con su cuota; `activo` dice si además es
  activo del empleador según el padrón) y «sin_ddjj» (activo que el empleador
  no declaró: remuneración y cuota en cero).
- Un empleador con activos y ninguno en su DDJJ igual tiene su liquidación, en
  cero y con la nota: es lo que muestra que no declara.

CUOTA = remuneración × alícuota, redondeada al centavo por renglón; vence el día
fijado del mes siguiente (si el mes es más corto, el último). Alícuota y día
están en Datos del Sindicato (`s_institucion.cuota_alicuota`, `cuota_dia_vto`).

LIQUIDAR Y RELIQUIDAR
Se liquida un período o un rango (`generar_rango`: las DDJJ de todo el rango se
leen de Railway de una vez, cada período se graba en su transacción). Volver a
liquidar rehace el detalle de cada empleador con lo que hay hoy y anula la
liquidación de un empleador que se quedó sin base, con la nota.

LO DE AEDA (cambiado el 12/11/2026): se reliquida por DDJJ como lo demás
(pedido: «todos los períodos desde 202401»). La liquidación de AEDA no se pierde
de vista: su importe, sus afiliados y su `fis_deuda` quedan en `aeda_importe`,
`aeda_afiliados` e `id_aeda`, y la marca «[AEDA fis_deuda N]» sale de
observaciones para que importar_aeda_fisca_deuda.py no la vuelva a pisar.

Sin Railway configurado o con Railway caído no se liquida nada: sin la DDJJ no
hay base.
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
#: «nomina» ya no se genera (12/11/2026); queda para leer lo que se haya liquidado así.
ORIGENES = {"ddjj": "DDJJ de OSEDA", "aeda": "AEDA", "nomina": "Nómina del empleador"}
ORIGEN_TIPO = {"ddjj": "info", "aeda": "neutro", "nomina": "ok"}
#: De dónde sale cada renglón del detalle.
FUENTES = {"ddjj": "Con DDJJ", "sin_ddjj": "Sin DDJJ", "aeda": "AEDA", "nomina": "Nómina"}
FUENTE_TIPO = {"ddjj": "ok", "sin_ddjj": "warn", "aeda": "neutro", "nomina": "info"}
#: Tramos del porcentaje de activos con DDJJ (filtro de la grilla).
TRAMOS = {"100": "100 %", "50": "50 % a 99 %", "1": "1 % a 49 %", "0": "0 %", "sin": "Sin activos"}
MAX_PERIODOS = 48
SQL_ESQUEMA = "sql/fisca_liquidacion_ddjj_20261112.sql"
RE_MARCA_AEDA = re.compile(r"^\[AEDA fis_deuda (\d+)\]\s*")


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




def tramo(activos: int, con_ddjj: int) -> str:
    """El tramo del porcentaje de activos con DDJJ (clave de TRAMOS)."""
    if not activos:
        return "sin"
    if con_ddjj >= activos:
        return "100"
    if con_ddjj * 2 >= activos:
        return "50"
    return "1" if con_ddjj else "0"


def periodos_entre(desde: str, hasta: str) -> list[str]:
    """«202401», «202403» → ["202401", "202402", "202403"]."""
    a, m = int(desde[:4]), int(desde[4:])
    fin, salida = (int(hasta[:4]), int(hasta[4:])), []
    while (a, m) <= fin:
        salida.append(f"{a}{m:02d}")
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    return salida


def _digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


# ─────────────────────────────────────────────────────────────────────────────
# Cálculo
# ─────────────────────────────────────────────────────────────────────────────

def leer_padron(cur, desde: datetime.date, hasta: datetime.date) -> dict:
    """Los titulares que pueden ser afiliados de algún período entre las dos
    fechas, con sus relaciones laborales: {"titulares": [..], "relaciones": [..]}."""
    cur.execute("""SELECT id_afiliado, cuil, apellido_nombres, fecha_alta, fecha_baja FROM p_afiliados
                    WHERE cuil REGEXP '^[0-9]{11}$' AND cod_parentesco = 0
                      AND (fecha_alta IS NULL OR fecha_alta <= %s)
                      AND (fecha_baja IS NULL OR fecha_baja >= %s)""", (hasta, desde))
    titulares = cur.fetchall()
    cur.execute("""SELECT r.cuil, r.cuit_empleador, r.estado, r.fecha_inicio, r.fecha_fin
                     FROM p_relaciones_laborales r
                     JOIN p_afiliados a ON a.cuil = r.cuil
                    WHERE a.cod_parentesco = 0
                      AND (a.fecha_alta IS NULL OR a.fecha_alta <= %s)
                      AND (a.fecha_baja IS NULL OR a.fecha_baja >= %s)""", (hasta, desde))
    return {"titulares": titulares, "relaciones": cur.fetchall()}


def armar(periodo: str, padron: dict, ddjj: list[dict], alicuota: Decimal) -> dict:
    """
    Lo que corresponde liquidar en el período, sin base de datos: la función que
    prueban las simulaciones. `ddjj` son las filas de contable_oseda (pueden
    venir de varios períodos: se toman las de este).

    {cuit: {"lineas": [{cuil, id_afiliado, nombre, remuneracion, cuota, fuente,
    activo}], "activos", "con_ddjj", "afiliados", "fuera_nomina", "remuneracion",
    "importe"}}
    """
    desde, hasta = limites(periodo)
    del_periodo = {t["cuil"]: t for t in padron["titulares"]
                   if (t["fecha_alta"] is None or t["fecha_alta"] <= hasta)
                   and (t["fecha_baja"] is None or t["fecha_baja"] >= desde)}

    activos: dict[str, dict] = defaultdict(dict)
    for r in padron["relaciones"]:
        a = del_periodo.get(r["cuil"])
        cuit = _digitos(r["cuit_empleador"])
        if not a or len(cuit) != 11:
            continue
        if r["fecha_inicio"] and r["fecha_inicio"] > hasta:
            continue
        if r["fecha_fin"]:
            if r["fecha_fin"] < desde:
                continue
        elif r["estado"] != "activa" and not a["fecha_baja"]:
            continue                # inactiva sin egreso y el afiliado sigue: no se sabe hasta cuándo
        activos[cuit][r["cuil"]] = a

    empleadores: dict[str, dict] = {}

    def _linea(e, a, fuente, activo):
        return e["lineas"].setdefault(a["cuil"], {
            "cuil": a["cuil"], "id_afiliado": a["id_afiliado"], "nombre": a["apellido_nombres"],
            "remuneracion": Decimal("0"), "fuente": fuente, "activo": activo})

    for f in ddjj:
        if str(f["periodo"]) != periodo or f["cuil"] not in del_periodo:
            continue
        cuit = _digitos(f["cuit"])
        if len(cuit) != 11:
            continue
        e = empleadores.setdefault(cuit, {"lineas": {}})
        l = _linea(e, del_periodo[f["cuil"]], "ddjj", f["cuil"] in activos.get(cuit, {}))
        l["remuneracion"] += Decimal(str(f["rem5"] or 0))

    for cuit, act in activos.items():
        e = empleadores.setdefault(cuit, {"lineas": {}})
        for a in act.values():
            _linea(e, a, "sin_ddjj", True)

    for cuit in list(empleadores):
        e = empleadores[cuit]
        lineas = []
        for l in e["lineas"].values():
            if l["fuente"] == "ddjj" and l["remuneracion"] <= 0 and not l["activo"]:
                continue            # declarado en cero y no es de su nómina: no aporta nada
            l["cuota"] = _cuota(l["remuneracion"], alicuota) if l["remuneracion"] > 0 else Decimal("0.00")
            lineas.append(l)
        if not lineas:
            del empleadores[cuit]
            continue
        e["lineas"] = lineas
        e["activos"] = len(activos.get(cuit, {}))
        e["con_ddjj"] = sum(1 for l in lineas if l["activo"] and l["fuente"] == "ddjj")
        e["fuera_nomina"] = sum(1 for l in lineas if not l["activo"])
        e["afiliados"] = sum(1 for l in lineas if l["cuota"] > 0)
        e["remuneracion"] = sum((l["remuneracion"] for l in lineas), Decimal("0"))
        e["importe"] = sum((l["cuota"] for l in lineas), Decimal("0"))
    return empleadores


def calcular(cur, periodo: str, padron: dict | None = None, ddjj: list | None = None) -> dict:
    """Lo que corresponde liquidar en el período, sin grabar nada.
    Sin DDJJ (Railway caído o sin configurar) levanta ErrorLiquidacion."""
    par = parametros(cur)
    if padron is None:
        padron = leer_padron(cur, *limites(periodo))
    if ddjj is None:
        try:
            ddjj = contable_oseda.ddjj_del_periodo(periodo, {t["cuil"] for t in padron["titulares"]})
        except contable_oseda.ContableNoDisponible as e:
            raise ErrorLiquidacion(f"No se pudieron leer las DDJJ de OSEDA ({e}). No se liquidó nada.") from e
    return {"empleadores": armar(periodo, padron, ddjj, par["alicuota"]), **par}


# ─────────────────────────────────────────────────────────────────────────────
# Grabar
# ─────────────────────────────────────────────────────────────────────────────

def _pesos(v) -> str:
    return f"{Decimal(str(v or 0)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _nota(e: dict, aeda: dict | None) -> str | None:
    partes = []
    if e["activos"] and not e["con_ddjj"]:
        partes.append("Ningún afiliado activo del empleador figura en su DDJJ de OSEDA.")
    if e["fuera_nomina"]:
        partes.append(f"{e['fuera_nomina']} afiliado(s) en su DDJJ sin relación laboral con el empleador en el padrón.")
    if aeda:
        partes.append(aeda["texto"])
    return " ".join(partes)[:500] or None


def _aeda(ya: dict, hoy: datetime.date) -> dict | None:
    """Lo que AEDA había liquidado, la primera vez que se reliquida una suya."""
    if ya["origen"] != "aeda":
        if ya.get("aeda_importe") is None:
            return None
        imp, afi, ida = ya["aeda_importe"], ya["aeda_afiliados"], ya["id_aeda"]
    else:
        m = RE_MARCA_AEDA.match(ya["observaciones"] or "")
        imp, afi, ida = ya["importe"], ya["afiliados"], int(m.group(1)) if m else None
    return {"importe": imp, "afiliados": afi, "id": ida,
            "texto": f"AEDA había liquidado $ {_pesos(imp)} por {afi} afiliado(s)"
                     + (f" (fis_deuda {ida})" if ida else "") + "."}


def generar(cur, periodo: str, id_usuario: int | None, calculo: dict | None = None) -> dict:
    """Liquida (o reliquida) el período. Devuelve los contadores para la pantalla."""
    calculo = calculo or calcular(cur, periodo)
    hoy = datetime.date.today()
    vto = vencimiento(periodo, calculo["dia_vto"])
    r = {"periodo": periodo, "nuevas": 0, "reliquidadas": 0, "iguales": 0, "de_aeda": 0, "anuladas": 0,
         "en_cero": 0, "importe": Decimal("0")}

    cur.execute("""SELECT id, cuit, origen, estado, importe, afiliados, afiliados_activos, activos_con_ddjj,
                          observaciones, aeda_importe, aeda_afiliados, id_aeda
                     FROM fisca_liquidacion WHERE periodo = %s FOR UPDATE""", (periodo,))
    existentes = {f["cuit"]: f for f in cur.fetchall()}

    for cuit, e in sorted(calculo["empleadores"].items()):
        ya = existentes.get(cuit)
        aeda = _aeda(ya, hoy) if ya else None
        nota = _nota(e, aeda)
        if ya:
            iguales = (ya["estado"] == "vigente" and ya["origen"] == "ddjj"
                       and Decimal(str(ya["importe"])) == e["importe"] and ya["afiliados"] == e["afiliados"]
                       and ya["afiliados_activos"] == e["activos"] and ya["activos_con_ddjj"] == e["con_ddjj"])
            if ya["origen"] == "aeda":
                r["de_aeda"] += 1
            else:
                r["iguales" if iguales else "reliquidadas"] += 1
            cur.execute("""UPDATE fisca_liquidacion
                              SET fecha = %s, vencimiento = %s, alicuota = %s, afiliados = %s, remuneracion = %s,
                                  importe = %s, origen = 'ddjj', estado = 'vigente', observaciones = %s,
                                  afiliados_activos = %s, activos_con_ddjj = %s,
                                  aeda_importe = %s, aeda_afiliados = %s, id_aeda = %s, id_usuario = %s
                            WHERE id = %s""",
                        (hoy, vto, calculo["alicuota"], e["afiliados"], e["remuneracion"], e["importe"], nota,
                         e["activos"], e["con_ddjj"], aeda and aeda["importe"], aeda and aeda["afiliados"],
                         aeda and aeda["id"], id_usuario, ya["id"]))
            id_liq = ya["id"]
            cur.execute("DELETE FROM fisca_liquidacion_detalle WHERE id_liquidacion = %s", (id_liq,))
        else:
            cur.execute("""INSERT INTO fisca_liquidacion
                             (cuit, periodo, fecha, vencimiento, alicuota, afiliados, remuneracion, importe, origen,
                              estado, observaciones, afiliados_activos, activos_con_ddjj, id_usuario)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'ddjj', 'vigente', %s, %s, %s, %s)""",
                        (cuit, periodo, hoy, vto, calculo["alicuota"], e["afiliados"], e["remuneracion"],
                         e["importe"], nota, e["activos"], e["con_ddjj"], id_usuario))
            id_liq = cur.lastrowid
            r["nuevas"] += 1
        cur.executemany("""INSERT INTO fisca_liquidacion_detalle
                             (id_liquidacion, cuil, id_afiliado, apellido_nombres, remuneracion, cuota, fuente, activo)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                        [(id_liq, l["cuil"], l["id_afiliado"], (l["nombre"] or None) and l["nombre"][:100],
                          l["remuneracion"], l["cuota"], l["fuente"], 1 if l["activo"] else 0)
                         for l in e["lineas"]])
        r["importe"] += e["importe"]
        if not e["importe"]:
            r["en_cero"] += 1

    # Lo liquidado antes que ya no tiene base (la DDJJ se rectificó, el afiliado
    # dejó de serlo), también lo de AEDA: se anula con la nota y lo de AEDA queda.
    for cuit, ya in existentes.items():
        if cuit in calculo["empleadores"] or ya["estado"] == "anulada":
            continue
        aeda = _aeda(ya, hoy)
        texto = f"Anulada al liquidar por DDJJ el {hoy:%d/%m/%Y}: sin afiliados activos ni DDJJ en el período."
        cur.execute("""UPDATE fisca_liquidacion SET estado = 'anulada', id_usuario = %s, observaciones = %s,
                              aeda_importe = %s, aeda_afiliados = %s, id_aeda = %s WHERE id = %s""",
                    (id_usuario, (texto + (" " + aeda["texto"] if aeda else ""))[:500],
                     aeda and aeda["importe"], aeda and aeda["afiliados"], aeda and aeda["id"], ya["id"]))
        r["anuladas"] += 1
    return r


def generar_rango(desde: str, hasta: str, id_usuario: int | None, simular: bool = False) -> list[dict]:
    """
    Liquida de `desde` a `hasta`. El padrón se lee una vez y las DDJJ de todo el
    rango en una sola pasada por Railway (de a 12 períodos); cada período se
    graba en su propia transacción, así un error deja grabados los anteriores.
    Con `simular` cada período se calcula, se graba y se deshace (rollback).
    """
    periodos = periodos_entre(desde, hasta)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            padron = leer_padron(cur, limites(periodos[0])[0], limites(periodos[-1])[1])
        cuiles = {t["cuil"] for t in padron["titulares"]}
        ddjj = defaultdict(list)
        try:
            for i in range(0, len(periodos), 12):
                for f in contable_oseda.ddjj_de_cuiles(periodos[i:i + 12], cuiles):
                    ddjj[str(f["periodo"])].append(f)
        except contable_oseda.ContableNoDisponible as e:
            raise ErrorLiquidacion(f"No se pudieron leer las DDJJ de OSEDA ({e}). No se liquidó nada.") from e
        resultados = []
        for p in periodos:
            conn.begin()
            try:
                with conn.cursor() as cur:
                    calculo = calcular(cur, p, padron, ddjj.get(p, []))
                    r = generar(cur, p, id_usuario, calculo)
                r["activos"] = sum(e["activos"] for e in calculo["empleadores"].values())
                r["con_ddjj"] = sum(e["con_ddjj"] for e in calculo["empleadores"].values())
                conn.rollback() if simular else conn.commit()
            except Exception:
                conn.rollback()
                raise
            resultados.append(r)
        return resultados
    finally:
        conn.close()


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


def _falta_esquema(cur) -> bool:
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.columns
                    WHERE table_schema = DATABASE() AND table_name = 'fisca_liquidacion'
                      AND column_name = 'afiliados_activos'""")
    return not cur.fetchone()["n"]


def _periodo_sugerido() -> str:
    """El mes anterior: es el que se liquida (vence el mes en curso)."""
    hoy = datetime.date.today().replace(day=1) - datetime.timedelta(days=1)
    return hoy.strftime("%Y%m")


def _porc(con, total):
    return (Decimal(con) * 100 / Decimal(total)).quantize(CENT) if total else None


@fisca_liq_bp.route("/liquidacion")
def liquidacion():
    salida = _guardia()
    if salida:
        return salida
    periodo = periodo_valido(request.args.get("periodo"))
    with get_connection() as conn:
        with conn.cursor() as cur:
            par = parametros(cur)
            if _falta_esquema(cur):
                flash(f"!Falta correr {SQL_ESQUEMA}: hasta entonces no se puede liquidar.")
                return render_template("fisca/liquidacion.html", periodo=None, periodos=[], filas=[], par=par,
                                       sugerido=_periodo_sugerido(), origenes=ORIGENES, origen_tipo=ORIGEN_TIPO,
                                       tramos=TRAMOS, falta_esquema=True)
            cur.execute("""SELECT l.periodo, COUNT(*) AS empleadores, SUM(l.afiliados) AS afiliados,
                                  SUM(l.afiliados_activos) AS activos, SUM(l.activos_con_ddjj) AS con_ddjj,
                                  SUM(l.importe = 0) AS en_cero, SUM(l.origen = 'aeda') AS de_aeda,
                                  SUM(l.remuneracion) AS remuneracion, SUM(l.importe) AS importe,
                                  SUM(COALESCE(l.aeda_importe, IF(l.origen = 'aeda', l.importe, NULL))) AS importe_aeda,
                                  MAX(l.fecha) AS liquidado, MIN(l.vencimiento) AS vto
                             FROM fisca_liquidacion l WHERE l.estado = 'vigente'
                            GROUP BY l.periodo ORDER BY l.periodo DESC""")
            periodos = cur.fetchall()
            for p in periodos:
                p["porc"] = _porc(p["con_ddjj"] or 0, p["activos"] or 0)
            filas = []
            if periodo:
                cur.execute("""SELECT l.*, e.razon_social, u.nombre AS usuario
                                 FROM fisca_liquidacion l
                                 LEFT JOIN p_empresas e ON e.CUIT = CAST(l.cuit AS UNSIGNED)
                                 LEFT JOIN s_usuarios u ON u.id = l.id_usuario
                                WHERE l.periodo = %s
                                ORDER BY l.estado DESC, l.importe DESC, l.afiliados_activos DESC""", (periodo,))
                filas = cur.fetchall()
                for f in filas:
                    f["tramo"] = tramo(f["afiliados_activos"], f["activos_con_ddjj"])
    vigentes = [f for f in filas if f["estado"] == "vigente"]
    tot = {k: sum((f[k] or 0) for f in vigentes) for k in
           ("importe", "remuneracion", "afiliados", "afiliados_activos", "activos_con_ddjj", "activos_sin_ddjj")}
    tot["porc"] = _porc(tot["activos_con_ddjj"], tot["afiliados_activos"])
    tot["aeda"] = sum((f["aeda_importe"] if f["aeda_importe"] is not None else
                       (f["importe"] if f["origen"] == "aeda" else 0)) for f in vigentes)
    return render_template("fisca/liquidacion.html", periodo=periodo, periodos=periodos, filas=filas,
                           tot=tot, n_vigentes=len(vigentes), sugerido=_periodo_sugerido(), par=par,
                           origenes=ORIGENES, origen_tipo=ORIGEN_TIPO, tramos=TRAMOS, falta_esquema=False,
                           con_aeda=any(f["aeda_importe"] is not None or f["origen"] == "aeda" for f in filas))


@fisca_liq_bp.route("/liquidacion/generar", methods=["POST"])
def liquidacion_generar():
    salida = _guardia()
    if salida:
        return salida
    desde = periodo_valido(request.form.get("desde") or request.form.get("periodo"))
    hasta = periodo_valido(request.form.get("hasta")) or desde
    if not desde:
        flash("!Elegí el período a liquidar.")
        return redirect(url_for("fisca_liq.liquidacion"))
    if hasta < desde:
        flash("!El período «hasta» es anterior al «desde».")
        return redirect(url_for("fisca_liq.liquidacion"))
    if limites(hasta)[0] > datetime.date.today():
        flash("!Un período que todavía no empezó no se liquida.")
        return redirect(url_for("fisca_liq.liquidacion", periodo=desde))
    if len(periodos_entre(desde, hasta)) > MAX_PERIODOS:
        flash(f"!Se liquidan hasta {MAX_PERIODOS} períodos de una vez.")
        return redirect(url_for("fisca_liq.liquidacion"))
    with get_connection() as conn:
        with conn.cursor() as cur:
            if _falta_esquema(cur):
                flash(f"!Falta correr {SQL_ESQUEMA}: hasta entonces no se puede liquidar.")
                return redirect(url_for("fisca_liq.liquidacion"))
    usuario = usuario_actual() or {}
    try:
        res = generar_rango(desde, hasta, usuario.get("id"))
    except ErrorLiquidacion as e:
        flash("!" + str(e))
        return redirect(url_for("fisca_liq.liquidacion", periodo=desde))
    suma = {k: sum(r[k] for r in res) for k in ("nuevas", "reliquidadas", "iguales", "de_aeda", "anuladas", "en_cero")}
    partes = [f"{n} {t}" for n, t in ((suma["nuevas"], "nuevas"), (suma["reliquidadas"], "reliquidadas"),
                                       (suma["iguales"], "sin cambios"), (suma["de_aeda"], "de AEDA reliquidadas"),
                                       (suma["anuladas"], "anuladas")) if n]
    rango = f"{desde[:4]}-{desde[4:]}" + (f" a {hasta[:4]}-{hasta[4:]}" if hasta != desde else "")
    flash(f"{'Período' if hasta == desde else 'Períodos'} {rango} liquidado{'s' if hasta != desde else ''}: "
          + (", ".join(partes) or "no hay nada para liquidar")
          + f". Cuota liquidada: $ {_pesos(sum(r['importe'] for r in res))}."
          + (f" {suma['en_cero']} en cero (activos sin DDJJ)." if suma["en_cero"] else ""))
    return redirect(url_for("fisca_liq.liquidacion", periodo=hasta))


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
                            WHERE d.id_liquidacion = %s
                            ORDER BY d.fuente = 'sin_ddjj', nombre, d.cuil""", (id_liq,))
            detalle = cur.fetchall()
    return render_template("fisca/liquidacion_ficha.html", liq=liq, detalle=detalle, origenes=ORIGENES,
                           origen_tipo=ORIGEN_TIPO, fuentes=FUENTES, fuente_tipo=FUENTE_TIPO,
                           tramo=tramo(liq.get("afiliados_activos") or 0, liq.get("activos_con_ddjj") or 0),
                           puede_empleador=puede(url_for("empleadores.abm_empleadores")))


# ─────────────────────────────────────────────────────────────────────────────
# Consola: python fisca_liquidacion.py 202401 202609 [--simular] [--usuario mail@…]
# ─────────────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    """Liquida un rango desde la consola: sin el tope de tiempo de IIS."""
    import argparse
    from pathlib import Path

    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name(".env"))
    ap = argparse.ArgumentParser(description="Liquidación de cuota sindical por DDJJ de OSEDA")
    ap.add_argument("desde"), ap.add_argument("hasta", nargs="?")
    ap.add_argument("--usuario", help="email de quien figura como el que liquidó (por defecto el primer Administrador)")
    ap.add_argument("--simular", action="store_true", help="calcula y muestra, sin grabar nada")
    a = ap.parse_args(argv)
    desde, hasta = periodo_valido(a.desde), periodo_valido(a.hasta or a.desde)
    if not desde or not hasta or hasta < desde:
        ap.error("períodos inválidos (AAAAMM)")
    with get_connection() as conn:
        with conn.cursor() as cur:
            if _falta_esquema(cur):
                print(f"Falta correr {SQL_ESQUEMA}.")
                return 1
            if a.usuario:
                cur.execute("SELECT id FROM s_usuarios WHERE email = %s AND activo = 1", (a.usuario,))
            else:
                cur.execute("""SELECT u.id FROM s_usuarios u JOIN s_usuario_rol ur ON ur.usuario_id = u.id
                                 JOIN s_roles r ON r.id = ur.rol_id WHERE u.activo = 1 AND r.nombre = 'Administrador'
                                ORDER BY u.id LIMIT 1""")
            u = cur.fetchone()
    try:
        res = generar_rango(desde, hasta, u and u["id"], simular=a.simular)
    except ErrorLiquidacion as e:
        print(e)
        return 1
    print("SIMULACIÓN — no se grabó nada" if a.simular else "Liquidado")
    print("período  nuevas  relig.  iguales  de AEDA  anuladas  en cero  activos  c/DDJJ      %            cuota")
    for r in res:
        porc = f"{r['con_ddjj'] * 100 / r['activos']:5.1f}" if r["activos"] else "    —"
        print(f"{r['periodo']}  {r['nuevas']:6}  {r['reliquidadas']:6}  {r['iguales']:7}  {r['de_aeda']:7}  "
              f"{r['anuladas']:8}  {r['en_cero']:7}  {r['activos']:7}  {r['con_ddjj']:6}  {porc}  {_pesos(r['importe']):>15}")
    print(f"Total cuota: $ {_pesos(sum(r['importe'] for r in res))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
