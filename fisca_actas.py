"""
fisca_actas.py — Actas de fiscalización y acuerdos de pago de cuota sindical.

    /fiscalizacion/actas                     lista (menú 14): ?q, ?estado
    /fiscalizacion/actas/nueva?cuit=         el acta nueva del CUIT (o la abierta que ya tiene)
    /fiscalizacion/actas/guardar             POST: alta, o guardar y recalcular una abierta
    /fiscalizacion/actas/<id>                ficha (editable mientras está abierta)
    /fiscalizacion/actas/<id>/cerrar         POST: la deuda queda firme
    /fiscalizacion/actas/<id>/anular         POST, con motivo
    /fiscalizacion/actas/<id>/pdf
    /fiscalizacion/acuerdos                  lista (menú 15)
    /fiscalizacion/actas/<id>/acuerdo        el acuerdo de un acta cerrada (nuevo o el vigente)
    /fiscalizacion/actas/<id>/acuerdo/guardar   POST
    /fiscalizacion/acuerdos/<id>/estado      POST: anular, cancelar o judicializar, con motivo
    /fiscalizacion/acuerdos/<id>/pdf
    /fiscalizacion/fiscalizadores            ABM (menú 16): ?edit=ID, ?nuevo=1; POST guardar, borrar, baja, reactivar

Portado de gestion_adm (fiscalizacion_routes.acta_* y acuerdo_*), sobre la
cuenta corriente de empleadores de acá (fisca_aplicaciones.py).

QUÉ RECLAMA EL ACTA (`calcular`)
  Las liquidaciones vigentes del CUIT del rango de períodos, ya vencidas a la
  fecha de cálculo y que no estén en otra acta cerrada. Por cada una:
    saldo            liquidado − lo aplicado con cobros de hasta la fecha de cálculo
    interés saldo    resarcitorio ARCA del saldo, del vencimiento a la fecha de cálculo
    interés pagos    (si se pide) resarcitorio de cada cobro aplicado después del
                     vencimiento, del vencimiento a la fecha del cobro
  Entra el período con saldo o con interés de pagos tarde. El vencimiento es el
  de la liquidación: el del F.931 del CUIT (fisca_intereses.py). El interés es
  simple, con la tasa de arca_intereses vigente cada día.

FISCALIZADORES (`fisca_fiscalizador`, sql/fisca_fiscalizadores_20261114.sql)
  El acta se labra con uno del catálogo (activo). Guarda el id y, además, el
  nombre y el DNI como quedaron impresos (`inspector`, `inspector_dni`): corregir
  la ficha después no cambia un acta ya labrada. Uno que figura en un acta no se
  elimina: se desactiva.

ESTADOS
  abierta   se edita y se recalcula (un acta abierta por CUIT, como gestion_adm)
  cerrada   la deuda queda firme: no se recalcula; admite el acuerdo de pago
  anulada   con motivo; no si tiene un acuerdo vigente. Sus períodos vuelven a
            poder reclamarse.

EL ACUERDO (`guardar_acuerdo`)
  Sobre un acta cerrada, uno vigente por acta. La deuda es el total del acta;
  el interés de financiación se carga a mano (decidido el 14/11/2026) y el
  cronograma lo propone en cuotas iguales, editables. El total financiado es la
  suma de las cuotas y el interés, lo que esa suma tiene por encima de la deuda
  (la regla de gestion_adm): un cronograma que no cubre la deuda no se graba.
  Los cobros de las cuotas todavía no se siguen acá.
"""

from __future__ import annotations

import datetime
import logging
import re
from decimal import Decimal
from xml.sax.saxutils import escape

from flask import Blueprint, flash, redirect, render_template, request, url_for

import fisca_aplicaciones as fa
import fisca_intereses as FI
from db import get_connection, puede, usuario_actual, validasesion
from numeracion import _proximo
from pagos_datos import leer_importe

log = logging.getLogger(__name__)

fisca_acta_bp = Blueprint("fisca_acta", __name__, url_prefix="/fiscalizacion")

URL_ACTAS = "/fiscalizacion/actas"
URL_ACUERDOS = "/fiscalizacion/acuerdos"
URL_FISCALIZADORES = "/fiscalizacion/fiscalizadores"
SQL_ESQUEMA = "sql/fisca_actas_20261114.sql"
SQL_FISCALIZADORES = "sql/fisca_fiscalizadores_20261114.sql"
CENT = Decimal("0.01")
ESTADOS_ACTA = {"abierta": ("Abierta", "warn"), "cerrada": ("Cerrada", "ok"), "anulada": ("Anulada", "danger")}
ESTADOS_ACUERDO = {"vigente": ("Vigente", "ok"), "anulado": ("Anulado", "danger"), "cancelado": ("Cancelado", "info"),
                   "judicializado": ("Judicializado", "warn")}
ACCIONES_ACUERDO = {"anular": "anulado", "cancelar": "cancelado", "judicializar": "judicializado"}

#: Los textos del documento. Revisarlos con el asesor legal del sindicato.
TEXTO_DETERMINACION = (
    "En ejercicio de las facultades de fiscalización de la cuota sindical que el empleador debe retener y depositar "
    "como agente de retención (art. 38 de la Ley 23.551), se determina la deuda que surge de la cuenta corriente del "
    "empleador, por los períodos y con los importes que se detallan, con más los intereses resarcitorios calculados a "
    "la tasa que fija ARCA (art. 37 de la Ley 11.683), desde el vencimiento de cada período —el de la declaración "
    "jurada de la seguridad social (F.931) según la terminación del CUIT— hasta la fecha de cálculo.")
TEXTO_INTIMACION = (
    "Se intima al empleador a abonar la suma total determinada{hasta}{lugar}, bajo apercibimiento de iniciar el cobro "
    "por la vía de apremio prevista por la Ley 24.642, con más los intereses que se devenguen hasta el efectivo pago.")
TEXTO_ACUERDO = (
    "Las partes acuerdan la cancelación de la deuda determinada en el acta {acta} en las cuotas y fechas que se "
    "detallan. La falta de pago en término de cualquiera de las cuotas habilita al sindicato a dar por caído el "
    "acuerdo y a reclamar el saldo impago con más los intereses resarcitorios que correspondan, sin necesidad de "
    "intimación previa. El presente no implica novación de la deuda.")


class ErrorActa(Exception):
    """Lo que impide guardar, cerrar o anular: se muestra tal cual."""


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


def _uid():
    return (usuario_actual() or {}).get("id")


def _cuit(v) -> str | None:
    t = re.sub(r"\D", "", v or "")
    return t if len(t) == 11 else None


def periodo_de(texto) -> str | None:
    t = re.sub(r"\D", "", texto or "")
    return t if len(t) == 6 and 1 <= int(t[4:]) <= 12 else None


def _fecha(texto) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat((texto or "").strip()[:10])
    except ValueError:
        return None


def _pesos(v) -> str:
    entero, _, dec = f"{float(v or 0):,.2f}".partition(".")
    return f"$ {entero.replace(',', '.')},{dec}"


def _guardia(url):
    if not validasesion():
        return redirect(url_for("login"))
    if not puede(url):
        flash("!No tenés permiso para esa pantalla.")
        return redirect(url_for("menu"))
    return None


def falta_esquema(cur) -> bool:
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_schema = DATABASE()
                    AND table_name IN ('fisca_acta', 'fisca_acta_periodo', 'fisca_acta_pago', 'fisca_acuerdo',
                                       'fisca_acuerdo_cuota', 'arca_intereses')""")
    if cur.fetchone()["n"] < 6 or fa.falta_esquema(cur):
        return True
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.columns WHERE table_schema = DATABASE()
                    AND table_name = 'fisca_acta' AND column_name = 'id_fiscalizador'""")
    return not cur.fetchone()["n"]


def _aviso_esquema():
    flash(f"!Faltan correr en la base, desde DBeaver como root: sql/fisca_aplicaciones_20261114.sql, {SQL_ESQUEMA} "
          f"y {SQL_FISCALIZADORES} (los que no se hayan corrido).")


def numero(cur, prefijo: str, ambito: str, fecha: datetime.date) -> str:
    return f"{prefijo}-{fecha.year}-{_proximo(cur, ambito, str(fecha.year)):06d}"


def empresa(cur, cuit: str) -> dict:
    cur.execute("SELECT * FROM p_empresas WHERE CUIT = %s", (int(cuit),))
    return cur.fetchone() or {}


def domicilio(e: dict) -> str:
    """El domicilio legal de la ficha (y si falta, el fiscal), en una línea."""
    def armar(p):
        calle = " ".join(x for x in ((e.get(f"{p}_calle") or "").strip(), (e.get(f"{p}_numero") or "").strip()) if x)
        if (e.get(f"{p}_piso") or "").strip():
            calle += f", piso {e[p + '_piso'].strip()}"
        if (e.get(f"{p}_depto") or "").strip():
            calle += f" dto. {e[p + '_depto'].strip()}"
        loc = (e.get(f"{p}_localidad_nombre") or "").strip()
        cp = str(e.get(f"{p}_cp") or "").strip()
        return ", ".join(x for x in (calle, f"({cp}) {loc}" if cp and loc else loc,
                                     (e.get(f"{p}_provincia_nombre") or "").strip()) if x)
    return armar("dom") or armar("fdom")


def parametros(cur) -> dict:
    try:
        cur.execute("SELECT acta_plazo_dias, acta_lugar_pago FROM s_institucion WHERE id = 1")
        f = cur.fetchone() or {}
    except Exception:                                    # noqa: BLE001 — sin la columna, sin valores por defecto
        f = {}
    return {"plazo": f.get("acta_plazo_dias"), "lugar": f.get("acta_lugar_pago") or ""}


# ─────────────────────────────────────────────────────────────────────────────
# El cálculo
# ─────────────────────────────────────────────────────────────────────────────

def periodos_en_actas(cur, cuit: str, excluir: int | None = None) -> dict:
    """período → {nro_acta, id, estado} de las actas no anuladas del CUIT."""
    cur.execute("""SELECT p.periodo, a.id, a.nro_acta, a.estado
                     FROM fisca_acta_periodo p JOIN fisca_acta a ON a.id = p.id_acta
                    WHERE a.cuit = %s AND a.estado <> 'anulada'""", (cuit,))
    return {f["periodo"]: f for f in cur.fetchall() if f["id"] != excluir}


def actas_por_periodo(cur, cuit: str) -> dict:
    """Para la cuenta corriente: período → acta no anulada que lo reclama ({} sin el esquema)."""
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.tables
                    WHERE table_schema = DATABASE() AND table_name IN ('fisca_acta', 'fisca_acta_periodo')""")
    return periodos_en_actas(cur, cuit) if cur.fetchone()["n"] == 2 else {}


def calcular(cur, cuit: str, fecha_calculo: datetime.date, desde: str | None = None, hasta: str | None = None,
             con_pagos_tarde: bool = True, excluir_acta: int | None = None) -> dict:
    """Ver el encabezado del módulo. Devuelve períodos (con sus pagos tarde),
    totales y los períodos que quedaron afuera por estar en otra acta."""
    tasas = FI.tasas(cur)
    liqs = [l for l in fa.liquidaciones_de(cur, cuit)
            if (not desde or l["periodo"] >= desde) and (not hasta or l["periodo"] <= hasta)]
    por_liq = {}
    for a in fa.aplicaciones_de(cur, cuit):
        if not a["muerta"]:
            por_liq.setdefault(a["id_liquidacion"], []).append(a)
    en_actas = periodos_en_actas(cur, cuit, excluir_acta)
    out, afuera = [], []
    for l in liqs:
        venc = l["vencimiento"]
        if not venc or venc >= fecha_calculo:
            continue
        otra = en_actas.get(l["periodo"])
        if otra and otra["estado"] == "cerrada":
            afuera.append({"periodo": l["periodo"], "nro_acta": otra["nro_acta"], "id_acta": otra["id"]})
            continue
        termino, tarde, pagos = Decimal("0"), Decimal("0"), []
        for a in sorted(por_liq.get(l["id"], []), key=lambda x: (x["fecha_cobro"] or datetime.date.min, x["id"])):
            f = a["fecha_cobro"]
            if not f or f > fecha_calculo:
                continue                              # cobrado después de la fecha de cálculo: a esa fecha era deuda
            if f <= venc:
                termino += a["importe"]
                continue
            tarde += a["importe"]
            if con_pagos_tarde:
                pagos.append({"id_detalle": a["id_detalle"], "id_orden": a["id_orden"], "nro_orden": a["nro_orden"],
                              "fecha_cobro": f, "importe": a["importe"], "dias": (f - venc).days,
                              "interes": FI.interes(tasas, a["importe"], venc, f)})
        saldo = max(l["importe"] - termino - tarde, Decimal("0"))
        int_saldo = FI.interes(tasas, saldo, venc, fecha_calculo)
        int_pagos = sum((p["interes"] for p in pagos), Decimal("0"))
        if saldo <= Decimal("0.005") and int_pagos <= Decimal("0.005"):
            continue
        out.append({"id_liquidacion": l["id"], "periodo": l["periodo"], "vencimiento": venc,
                    "liquidado": l["importe"], "pagado_termino": termino, "pagado_tarde": tarde, "saldo": saldo,
                    "dias_mora": (fecha_calculo - venc).days, "interes_saldo": int_saldo, "interes_pagos": int_pagos,
                    "total": saldo + int_saldo + int_pagos, "pagos": pagos,
                    "abierta": otra["nro_acta"] if otra else None})
    tot = {k: sum((p[k] for p in out), Decimal("0")) for k in ("saldo", "interes_saldo", "interes_pagos", "total")}
    tasa = FI.tasa_vigente(tasas, fecha_calculo)
    return {"periodos": out, "totales": tot, "afuera": afuera, "tasa_hoy": tasa}


def _grabar_detalle(cur, id_acta: int, calc: dict) -> None:
    cur.execute("DELETE FROM fisca_acta_periodo WHERE id_acta = %s", (id_acta,))
    for p in calc["periodos"]:
        cur.execute("""INSERT INTO fisca_acta_periodo (id_acta, id_liquidacion, periodo, vencimiento, liquidado,
                                                       pagado_termino, pagado_tarde, saldo, dias_mora, interes_saldo,
                                                       interes_pagos, total)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (id_acta, p["id_liquidacion"], p["periodo"], p["vencimiento"], p["liquidado"], p["pagado_termino"],
                     p["pagado_tarde"], p["saldo"], p["dias_mora"], p["interes_saldo"], p["interes_pagos"], p["total"]))
        id_per = cur.lastrowid
        if p["pagos"]:
            cur.executemany("""INSERT INTO fisca_acta_pago (id_acta_periodo, id_detalle, id_orden, nro_orden, fecha_cobro,
                                                            importe, dias, interes)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                            [(id_per, x["id_detalle"], x["id_orden"], x["nro_orden"], x["fecha_cobro"], x["importe"],
                              x["dias"], x["interes"]) for x in p["pagos"]])
    t = calc["totales"]
    cur.execute("""UPDATE fisca_acta SET deuda = %s, interes_saldo = %s, interes_pagos = %s, total = %s
                    WHERE id = %s""", (t["saldo"], t["interes_saldo"], t["interes_pagos"], t["total"], id_acta))


# ─────────────────────────────────────────────────────────────────────────────
# Lectura
# ─────────────────────────────────────────────────────────────────────────────

SQL_ACTA = """SELECT a.*, uc.nombre AS usuario_creacion, ui.nombre AS usuario_cierre, ua.nombre AS usuario_anulacion
                FROM fisca_acta a
                LEFT JOIN s_usuarios uc ON uc.id = a.id_usuario_creacion
                LEFT JOIN s_usuarios ui ON ui.id = a.id_usuario_cierre
                LEFT JOIN s_usuarios ua ON ua.id = a.id_usuario_anulacion"""


def leer_acta(cur, id_acta: int, bloquear: bool = False) -> dict | None:
    cur.execute(SQL_ACTA + " WHERE a.id = %s" + (" FOR UPDATE" if bloquear else ""), (id_acta,))
    a = cur.fetchone()
    if not a:
        return None
    cur.execute("SELECT * FROM fisca_acta_periodo WHERE id_acta = %s ORDER BY periodo", (id_acta,))
    a["periodos"] = list(cur.fetchall())
    cur.execute("""SELECT g.*, p.periodo FROM fisca_acta_pago g JOIN fisca_acta_periodo p ON p.id = g.id_acta_periodo
                    WHERE p.id_acta = %s ORDER BY p.periodo, g.fecha_cobro, g.id""", (id_acta,))
    pagos = list(cur.fetchall())
    for p in a["periodos"]:
        p["pagos"] = [g for g in pagos if g["id_acta_periodo"] == p["id"]]
    a["pagos"] = pagos
    cur.execute("""SELECT id, nro_acuerdo, estado, monto_total, cantidad_cuotas FROM fisca_acuerdo
                    WHERE id_acta = %s ORDER BY id DESC""", (id_acta,))
    a["acuerdos"] = list(cur.fetchall())
    a["acuerdo_vigente"] = next((x for x in a["acuerdos"] if x["estado"] == "vigente"), None)
    return a


def acta_abierta(cur, cuit: str) -> dict | None:
    cur.execute("SELECT id FROM fisca_acta WHERE cuit = %s AND estado = 'abierta' ORDER BY id DESC LIMIT 1", (cuit,))
    return cur.fetchone()


# ─────────────────────────────────────────────────────────────────────────────
# Actas: pantallas
# ─────────────────────────────────────────────────────────────────────────────

@fisca_acta_bp.route("/actas")
def actas():
    salida = _guardia(URL_ACTAS)
    if salida:
        return salida
    estado = request.args.get("estado", "")
    q = (request.args.get("q") or "").strip()
    with get_connection() as conn:
        with conn.cursor() as cur:
            if falta_esquema(cur):
                _aviso_esquema()
                return render_template("fisca/actas.html", filas=[], estado=estado, q=q, estados=ESTADOS_ACTA)
            where, params = ["1 = 1"], []
            if estado in ESTADOS_ACTA:
                where.append("a.estado = %s")
                params.append(estado)
            if q:
                dig = re.sub(r"\D", "", q)
                where.append("(a.razon_social LIKE %s OR a.nro_acta LIKE %s" + (" OR a.cuit LIKE %s)" if dig else ")"))
                params += [f"%{q}%", f"%{q}%"] + ([f"%{dig}%"] if dig else [])
            cur.execute(f"""SELECT a.id, a.nro_acta, a.cuit, a.razon_social, a.fecha_acta, a.fecha_calculo,
                                   a.periodo_desde, a.periodo_hasta, a.deuda, a.interes_saldo + a.interes_pagos AS interes,
                                   a.total, a.estado, a.inspector,
                                   (SELECT COUNT(*) FROM fisca_acta_periodo p WHERE p.id_acta = a.id) AS periodos,
                                   (SELECT MIN(p.periodo) FROM fisca_acta_periodo p WHERE p.id_acta = a.id) AS per_min,
                                   (SELECT MAX(p.periodo) FROM fisca_acta_periodo p WHERE p.id_acta = a.id) AS per_max,
                                   (SELECT x.nro_acuerdo FROM fisca_acuerdo x WHERE x.id_acta = a.id AND x.estado <> 'anulado'
                                     ORDER BY x.id DESC LIMIT 1) AS acuerdo,
                                   (SELECT x.estado FROM fisca_acuerdo x WHERE x.id_acta = a.id AND x.estado <> 'anulado'
                                     ORDER BY x.id DESC LIMIT 1) AS estado_acuerdo
                              FROM fisca_acta a WHERE {' AND '.join(where)}
                             ORDER BY a.id DESC LIMIT 2000""", params)
            filas = list(cur.fetchall())
    return render_template("fisca/actas.html", filas=filas, estado=estado, q=q, estados=ESTADOS_ACTA,
                           estados_acuerdo=ESTADOS_ACUERDO)


def _vista_nueva(cur, cuit: str, args) -> dict:
    """El acta todavía sin guardar, con los datos por defecto y el cálculo."""
    e = empresa(cur, cuit)
    par = parametros(cur)
    hoy = datetime.date.today()
    fecha_calc = _fecha(args.get("fecha_calculo")) or hoy
    con_pagos = args.get("con_pagos_tarde", "1") == "1"
    a = {"id": None, "estado": "abierta", "nro_acta": "(se numera al guardar)", "cuit": cuit,
         "razon_social": e.get("razon_social") or "", "domicilio": domicilio(e), "actividad": "",
         "telefono": (e.get("telefonos") or "")[:100], "email": (e.get("email") or "")[:150],
         "fecha_acta": hoy, "hora_acta": datetime.datetime.now().strftime("%H:%M"), "fecha_calculo": fecha_calc,
         "periodo_desde": periodo_de(args.get("periodo_desde") or args.get("desde")),
         "periodo_hasta": periodo_de(args.get("periodo_hasta") or args.get("hasta")),
         "con_pagos_tarde": 1 if con_pagos else 0, "id_fiscalizador": None, "inspector": "", "inspector_dni": "",
         "representante": "",
         "representante_dni": "", "representante_cargo": "",
         "fecha_pago": hoy + datetime.timedelta(days=int(par["plazo"])) if par["plazo"] else None,
         "lugar_pago": par["lugar"], "observaciones": "", "acuerdos": [], "acuerdo_vigente": None}
    return a


def fiscalizadores_para(cur, actual: int | None = None) -> list[dict]:
    """Los activos, más el del acta aunque ya no lo esté (si no, el select lo perdería)."""
    cur.execute("""SELECT id, apellido_nombres, dni, cargo, activo FROM fisca_fiscalizador
                    WHERE activo = 1 OR id = %s ORDER BY apellido_nombres""", (actual or 0,))
    return list(cur.fetchall())


def _render_acta(cur, a: dict, calc: dict | None, error: str | None = None):
    return render_template("fisca/acta.html", a=a, calc=calc, error=error, estados=ESTADOS_ACTA,
                           estados_acuerdo=ESTADOS_ACUERDO, fiscalizadores=fiscalizadores_para(cur, a.get("id_fiscalizador")),
                           puede_fiscalizadores=puede(URL_FISCALIZADORES),
                           editable=a["estado"] == "abierta", puede_acuerdo=puede(URL_ACUERDOS),
                           puede_cc=puede("/empleadores/cc"))


@fisca_acta_bp.route("/actas/nueva")
def acta_nueva():
    salida = _guardia(URL_ACTAS)
    if salida:
        return salida
    cuit = _cuit(request.args.get("cuit"))
    if not cuit:
        flash("!Indicá el CUIT del empleador (11 dígitos).")
        return redirect(url_for("fisca_acta.actas"))
    with get_connection() as conn:
        with conn.cursor() as cur:
            if falta_esquema(cur):
                _aviso_esquema()
                return redirect(url_for("fisca_acta.actas"))
            abierta = acta_abierta(cur, cuit)
            if abierta:
                flash("!El empleador ya tiene un acta abierta: se abre esa.")
                return redirect(url_for("fisca_acta.acta", id_acta=abierta["id"]))
            a = _vista_nueva(cur, cuit, request.args)
            calc, error = None, None
            try:
                calc = calcular(cur, cuit, a["fecha_calculo"], a["periodo_desde"], a["periodo_hasta"],
                                bool(a["con_pagos_tarde"]))
            except ValueError as e:
                error = str(e)
            return _render_acta(cur, a, calc, error)


@fisca_acta_bp.route("/actas/<int:id_acta>")
def acta(id_acta):
    salida = _guardia(URL_ACTAS)
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            if falta_esquema(cur):
                _aviso_esquema()
                return redirect(url_for("fisca_acta.actas"))
            a = leer_acta(cur, id_acta)
            if not a:
                flash("!No existe esa acta.")
                return redirect(url_for("fisca_acta.actas"))
            # Lo grabado es lo que dice el acta; abierta, se muestra además lo que daría recalcular hoy con sus datos.
            calc = {"periodos": a["periodos"], "afuera": [],
                    "totales": {"saldo": a["deuda"], "interes_saldo": a["interes_saldo"],
                                "interes_pagos": a["interes_pagos"], "total": a["total"]},
                    "tasa_hoy": FI.tasa_vigente(FI.tasas(cur), a["fecha_calculo"])}
            return _render_acta(cur, a, calc)


def _datos_form(form) -> dict:
    t = lambda k, n: (form.get(k) or "").strip()[:n] or None          # noqa: E731
    return {"domicilio": t("domicilio", 300), "actividad": t("actividad", 200), "telefono": t("telefono", 100),
            "email": t("email", 150), "fecha_acta": _fecha(form.get("fecha_acta")), "hora_acta": t("hora_acta", 5),
            "id_fiscalizador": form.get("id_fiscalizador", type=int),
            "representante": t("representante", 200), "representante_dni": t("representante_dni", 20),
            "representante_cargo": t("representante_cargo", 100), "fecha_pago": _fecha(form.get("fecha_pago")),
            "lugar_pago": t("lugar_pago", 300), "observaciones": t("observaciones", 1000)}


@fisca_acta_bp.route("/actas/guardar", methods=["POST"])
def acta_guardar():
    salida = _guardia(URL_ACTAS)
    if salida:
        return salida
    f = request.form
    id_acta = f.get("id", type=int)
    cuit = _cuit(f.get("cuit"))
    datos = _datos_form(f)
    fecha_calc = _fecha(f.get("fecha_calculo"))
    desde, hasta = periodo_de(f.get("periodo_desde")), periodo_de(f.get("periodo_hasta"))
    con_pagos = f.get("con_pagos_tarde") == "1"
    errores = []
    if not cuit:
        errores.append("Falta el CUIT del empleador.")
    if not datos["fecha_acta"]:
        errores.append("Falta la fecha del acta.")
    if not fecha_calc:
        errores.append("Falta la fecha de cálculo de los intereses.")
    elif fecha_calc > datetime.date.today() + datetime.timedelta(days=366):
        errores.append("La fecha de cálculo está a más de un año.")
    if desde and hasta and desde > hasta:
        errores.append("El período desde es posterior al período hasta.")
    if not datos["id_fiscalizador"]:
        errores.append("Elegí el fiscalizador.")
    volver = (url_for("fisca_acta.acta", id_acta=id_acta) if id_acta
              else url_for("fisca_acta.acta_nueva", cuit=cuit, fecha_calculo=f.get("fecha_calculo"),
                           desde=desde, hasta=hasta, con_pagos_tarde="1" if con_pagos else "0"))
    if errores:
        for e in errores:
            flash("!" + e)
        return redirect(volver)
    with get_connection() as conn:
        try:
            with conn.cursor() as cur:
                if id_acta:
                    a = leer_acta(cur, id_acta, bloquear=True)
                    if not a:
                        raise ErrorActa("No existe esa acta.")
                    if a["estado"] != "abierta":
                        raise ErrorActa("El acta ya no está abierta: no se modifica.")
                    cuit = a["cuit"]
                cur.execute("SELECT id, apellido_nombres, dni, activo FROM fisca_fiscalizador WHERE id = %s",
                            (datos["id_fiscalizador"],))
                fz = cur.fetchone()
                if not fz or (not fz["activo"] and not (id_acta and a["id_fiscalizador"] == fz["id"])):
                    raise ErrorActa("Ese fiscalizador no existe o está inactivo.")
                datos.update(inspector=fz["apellido_nombres"][:150], inspector_dni=fz["dni"])
                if not id_acta:
                    cur.execute("SELECT id FROM fisca_acta WHERE cuit = %s AND estado = 'abierta' FOR UPDATE", (cuit,))
                    ya = cur.fetchone()
                    if ya:                                   # el mismo formulario mandado dos veces
                        id_acta = ya["id"]
                calc = calcular(cur, cuit, fecha_calc, desde, hasta, con_pagos, excluir_acta=id_acta)
                if not calc["periodos"]:
                    raise ErrorActa("Con esos datos no hay nada que reclamar: ningún período vencido con saldo"
                                    + (" ni pagado fuera de término" if con_pagos else "") + ".")
                campos = {**datos, "fecha_calculo": fecha_calc, "periodo_desde": desde, "periodo_hasta": hasta,
                          "con_pagos_tarde": 1 if con_pagos else 0}
                if id_acta:
                    cur.execute(f"UPDATE fisca_acta SET {', '.join(k + ' = %s' for k in campos)} WHERE id = %s",
                                list(campos.values()) + [id_acta])
                else:
                    e = empresa(cur, cuit)
                    campos.update(cuit=cuit, razon_social=(e.get("razon_social") or "")[:200] or None,
                                  nro_acta=numero(cur, "ACTA", "fisca_acta", datos["fecha_acta"]),
                                  id_usuario_creacion=_uid(), estado="abierta")
                    cur.execute(f"INSERT INTO fisca_acta ({', '.join(campos)}) VALUES ({', '.join(['%s'] * len(campos))})",
                                list(campos.values()))
                    id_acta = cur.lastrowid
                _grabar_detalle(cur, id_acta, calc)
            conn.commit()
            flash(f"Acta guardada: {len(calc['periodos'])} período(s), total {_pesos(calc['totales']['total'])}.")
            return redirect(url_for("fisca_acta.acta", id_acta=id_acta))
        except (ErrorActa, ValueError) as e:
            conn.rollback()
            flash("!" + str(e))
            return redirect(volver)
        except Exception:
            conn.rollback()
            raise


@fisca_acta_bp.route("/actas/<int:id_acta>/cerrar", methods=["POST"])
def acta_cerrar(id_acta):
    salida = _guardia(URL_ACTAS)
    if salida:
        return salida
    with get_connection() as conn:
        try:
            with conn.cursor() as cur:
                a = leer_acta(cur, id_acta, bloquear=True)
                if not a or a["estado"] != "abierta":
                    raise ErrorActa("Solo se cierra un acta abierta.")
                if not a["periodos"]:
                    raise ErrorActa("El acta no tiene períodos.")
                if not a["inspector"]:
                    raise ErrorActa("Falta el fiscalizador.")
                cur.execute("""UPDATE fisca_acta SET estado = 'cerrada', cerrado = NOW(), id_usuario_cierre = %s
                                WHERE id = %s AND estado = 'abierta'""", (_uid(), id_acta))
            conn.commit()
            flash(f"Acta {a['nro_acta']} cerrada: la deuda queda firme. Ya se puede cargar el acuerdo de pago.")
        except ErrorActa as e:
            conn.rollback()
            flash("!" + str(e))
    return redirect(url_for("fisca_acta.acta", id_acta=id_acta))


@fisca_acta_bp.route("/actas/<int:id_acta>/anular", methods=["POST"])
def acta_anular(id_acta):
    salida = _guardia(URL_ACTAS)
    if salida:
        return salida
    motivo = (request.form.get("motivo") or "").strip()
    with get_connection() as conn:
        try:
            with conn.cursor() as cur:
                if not motivo:
                    raise ErrorActa("Escribí el motivo de la anulación.")
                a = leer_acta(cur, id_acta, bloquear=True)
                if not a or a["estado"] == "anulada":
                    raise ErrorActa("Esa acta no existe o ya está anulada.")
                if a["acuerdo_vigente"]:
                    raise ErrorActa(f"El acta tiene el acuerdo de pago {a['acuerdo_vigente']['nro_acuerdo']} vigente: "
                                    "primero hay que anularlo.")
                cur.execute("""UPDATE fisca_acta SET estado = 'anulada', anulado = NOW(), id_usuario_anulacion = %s,
                                      motivo_anulacion = %s WHERE id = %s""", (_uid(), motivo[:255], id_acta))
            conn.commit()
            flash(f"Acta {a['nro_acta']} anulada: sus períodos se pueden volver a reclamar.")
        except ErrorActa as e:
            conn.rollback()
            flash("!" + str(e))
    return redirect(url_for("fisca_acta.acta", id_acta=id_acta))


@fisca_acta_bp.route("/actas/<int:id_acta>/pdf")
def acta_pdf(id_acta):
    salida = _guardia(URL_ACTAS)
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            a = leer_acta(cur, id_acta)
            tasas = FI.tasas(cur) if a else []
    if not a:
        flash("!No existe esa acta.")
        return redirect(url_for("fisca_acta.actas"))
    if a["estado"] == "anulada":
        flash("!El acta está anulada: no se imprime.")
        return redirect(url_for("fisca_acta.acta", id_acta=id_acta))
    return _pdf_acta(a, tasas)


def _pdf_acta(a: dict, tasas: list):
    import pagos_pdf as P
    from reportlab.lib.units import cm
    from reportlab.platypus import Spacer, Table, TableStyle
    doc = P._Doc("Acta de fiscalización", a["nro_acta"], "BORRADOR — acta abierta" if a["estado"] == "abierta" else None)
    doc.datos("1. IDENTIFICACIÓN", [
        ("Acta N°", escape(a["nro_acta"])), ("Fecha y hora", P._fecha(a["fecha_acta"]) + (f" · {a['hora_acta']} h" if a["hora_acta"] else "")),
        ("Fiscalizador", escape(a["inspector"] or "") + (f" · DNI {escape(a['inspector_dni'])}" if a["inspector_dni"] else ""))])
    doc.datos("2. EMPLEADOR", [
        ("Razón social", escape(a["razon_social"] or "")), ("CUIT", P._cuit(a["cuit"])), ("Domicilio", escape(a["domicilio"] or "")),
        ("Actividad", escape(a["actividad"] or "")), ("Teléfono", escape(a["telefono"] or "")), ("Correo", escape(a["email"] or "")),
        ("Atiende", escape(a["representante"] or "") + (f" · DNI {escape(a['representante_dni'])}" if a["representante_dni"] else "")
         + (f" · {escape(a['representante_cargo'])}" if a["representante_cargo"] else ""))])
    doc.story.append(doc.P("3. DETERMINACIÓN DE LA DEUDA", fontSize=8, textColor=doc.MUTED, fontName="Helvetica-Bold", spaceAfter=3))
    doc.story.append(doc.P(escape(TEXTO_DETERMINACION), fontSize=8.5, leading=11.5, spaceAfter=6))
    per = lambda p: f"{p[4:]}/{p[:4]}"                                     # noqa: E731
    doc.tabla("DEUDA POR PERÍODO (intereses al " + P._fecha(a["fecha_calculo"]) + ")",
              ["Período", "Vence", "Liquidado", "Pagado", "Saldo", "Días", "Int. saldo", "Int. pagos tarde", "Total"],
              [[per(p["periodo"]), P._fecha(p["vencimiento"]), P._pesos(p["liquidado"]),
                P._pesos(_d(p["pagado_termino"]) + _d(p["pagado_tarde"])), P._pesos(p["saldo"]), str(p["dias_mora"]),
                P._pesos(p["interes_saldo"]), P._pesos(p["interes_pagos"]), P._pesos(p["total"])] for p in a["periodos"]],
              [1.5, 1.9, 2.0, 2.0, 2.0, 1.0, 1.9, 1.9, 2.3], derecha=(2, 3, 4, 5, 6, 7, 8),
              total=("Total", P._pesos(a["total"])))
    doc.datos("TOTALES", [("Deuda (saldo de las cuotas)", P._pesos(a["deuda"])),
                          ("Intereses resarcitorios del saldo", P._pesos(a["interes_saldo"])),
                          ("Intereses de pagos fuera de término", P._pesos(a["interes_pagos"]) if a["interes_pagos"] else ""),
                          ("TOTAL DETERMINADO", f"{P._pesos(a['total'])}")])
    if a["pagos"]:
        doc.tabla("4. PAGOS FUERA DE TÉRMINO",
                  ["Período", "Cobro", "Fecha", "Importe", "Días", "Interés"],
                  [[per(g["periodo"]), escape(g["nro_orden"] or str(g["id_orden"])), P._fecha(g["fecha_cobro"]),
                    P._pesos(g["importe"]), str(g["dias"]), P._pesos(g["interes"])] for g in a["pagos"]],
                  [2.0, 4.0, 2.2, 3.0, 1.3, 2.5], derecha=(3, 4, 5), total=("Total", P._pesos(a["interes_pagos"])))
    usadas = [t for t in tasas if a["periodos"] and t["vigencia_desde"] <= a["fecha_calculo"]
              and (t["vigencia_hasta"] is None or t["vigencia_hasta"] >= min(p["vencimiento"] for p in a["periodos"]))]
    if usadas:
        doc.story.append(doc.P(
            "Interés resarcitorio simple, del día siguiente al vencimiento hasta el pago o la fecha de cálculo, a la tasa "
            "mensual de ARCA vigente cada día (÷ 30): " + "; ".join(
                f"{P._fecha(t['vigencia_desde'])} a {P._fecha(t['vigencia_hasta']) if t['vigencia_hasta'] else 'la fecha'}: "
                f"{str(t['resarcitorio']).rstrip('0').rstrip('.').replace('.', ',')} % ({escape(t['resolucion'] or '')})"
                for t in usadas) + ".", fontSize=7, leading=9, textColor=doc.MUTED, spaceAfter=8))
    hasta = f" hasta el {P._fecha(a['fecha_pago'])}" if a["fecha_pago"] else ""
    lugar = f", en {escape(a['lugar_pago'])}" if a["lugar_pago"] else ""
    doc.story.append(doc.P("5. INTIMACIÓN", fontSize=8, textColor=doc.MUTED, fontName="Helvetica-Bold", spaceAfter=3))
    doc.story.append(doc.P(escape(TEXTO_INTIMACION).format(hasta=hasta, lugar=lugar), fontSize=8.5, leading=11.5, spaceAfter=6))
    if a["observaciones"]:
        doc.datos("OBSERVACIONES", [("", escape(a["observaciones"]))])
    doc.story.append(Spacer(1, 2.2 * cm))
    f = Table([["", "", ""], [doc.P("Firma del fiscalizador", alignment=1), "", doc.P("Firma y aclaración por el empleador", alignment=1)]],
              colWidths=[6.5 * cm, 3 * cm, 6.5 * cm], rowHeights=[1.2 * cm, None])
    f.setStyle(TableStyle([("LINEABOVE", (0, 1), (0, 1), 0.6, doc.MUTED), ("LINEABOVE", (2, 1), (2, 1), 0.6, doc.MUTED)]))
    doc.story.append(f)
    return P.respuesta(doc.pdf(f"Acta {a['nro_acta']}"), f"Acta {a['nro_acta']} CUIT {a['cuit']}.pdf")


# ─────────────────────────────────────────────────────────────────────────────
# Acuerdos de pago
# ─────────────────────────────────────────────────────────────────────────────

SQL_ACUERDO = """SELECT x.*, a.nro_acta, a.total AS total_acta, a.estado AS estado_acta, uc.nombre AS usuario_creacion,
                        ue.nombre AS usuario_estado
                   FROM fisca_acuerdo x JOIN fisca_acta a ON a.id = x.id_acta
                   LEFT JOIN s_usuarios uc ON uc.id = x.id_usuario_creacion
                   LEFT JOIN s_usuarios ue ON ue.id = x.id_usuario_estado"""


def leer_acuerdo(cur, id_acuerdo: int) -> dict | None:
    cur.execute(SQL_ACUERDO + " WHERE x.id = %s", (id_acuerdo,))
    x = cur.fetchone()
    if x:
        cur.execute("SELECT * FROM fisca_acuerdo_cuota WHERE id_acuerdo = %s ORDER BY nro_cuota", (id_acuerdo,))
        x["cuotas"] = list(cur.fetchall())
    return x


@fisca_acta_bp.route("/acuerdos")
def acuerdos():
    salida = _guardia(URL_ACUERDOS)
    if salida:
        return salida
    estado = request.args.get("estado", "")
    with get_connection() as conn:
        with conn.cursor() as cur:
            if falta_esquema(cur):
                _aviso_esquema()
                return render_template("fisca/acuerdos.html", filas=[], estado=estado, estados=ESTADOS_ACUERDO)
            cur.execute(f"""SELECT x.id, x.nro_acuerdo, x.cuit, x.razon_social, x.fecha_acuerdo, x.monto_deuda,
                                   x.interes_financiacion, x.monto_total, x.cantidad_cuotas, x.estado, x.id_acta, a.nro_acta,
                                   (SELECT MIN(c.vencimiento) FROM fisca_acuerdo_cuota c WHERE c.id_acuerdo = x.id) AS primera,
                                   (SELECT MAX(c.vencimiento) FROM fisca_acuerdo_cuota c WHERE c.id_acuerdo = x.id) AS ultima
                              FROM fisca_acuerdo x JOIN fisca_acta a ON a.id = x.id_acta
                             {'WHERE x.estado = %s' if estado in ESTADOS_ACUERDO else ''}
                             ORDER BY x.id DESC LIMIT 2000""", (estado,) if estado in ESTADOS_ACUERDO else ())
            filas = list(cur.fetchall())
    return render_template("fisca/acuerdos.html", filas=filas, estado=estado, estados=ESTADOS_ACUERDO)


@fisca_acta_bp.route("/actas/<int:id_acta>/acuerdo")
def acuerdo(id_acta):
    salida = _guardia(URL_ACUERDOS)
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            if falta_esquema(cur):
                _aviso_esquema()
                return redirect(url_for("fisca_acta.acuerdos"))
            a = leer_acta(cur, id_acta)
            if not a:
                flash("!No existe esa acta.")
                return redirect(url_for("fisca_acta.acuerdos"))
            id_x = request.args.get("id", type=int)
            x = None
            if id_x:
                x = leer_acuerdo(cur, id_x)
                if x and x["id_acta"] != id_acta:
                    x = None
            if not x:
                vivo = a["acuerdo_vigente"] or next((y for y in a["acuerdos"] if y["estado"] != "anulado"), None)
                x = leer_acuerdo(cur, vivo["id"]) if vivo else None
            if not x and a["estado"] != "cerrada":
                flash("!El acuerdo de pago se carga sobre un acta cerrada: primero cerrá el acta.")
                return redirect(url_for("fisca_acta.acta", id_acta=id_acta))
            par = parametros(cur)
    if not x:
        hoy = datetime.date.today()
        x = {"id": None, "nro_acuerdo": "(se numera al guardar)", "estado": "vigente", "fecha_acuerdo": hoy,
             "monto_deuda": a["total"], "interes_financiacion": Decimal("0"), "monto_total": a["total"],
             "cantidad_cuotas": 1, "forma_pago": "", "lugar_pago": a["lugar_pago"] or par["lugar"],
             "representante": a["representante"] or "", "representante_dni": a["representante_dni"] or "",
             "representante_cargo": a["representante_cargo"] or "", "observaciones": "", "cuotas": []}
    return render_template("fisca/acuerdo.html", a=a, x=x, estados=ESTADOS_ACUERDO,
                           editable=x["estado"] == "vigente", texto=TEXTO_ACUERDO.format(acta=a["nro_acta"]))


def leer_cronograma(form) -> tuple[list[tuple[int, datetime.date, Decimal]], list[str]]:
    errores, out = [], []
    for nro, fecha, importe in zip(form.getlist("cuota_nro"), form.getlist("cuota_fecha"), form.getlist("cuota_importe")):
        if not (fecha or "").strip() and not (importe or "").strip():
            continue
        f, imp = _fecha(fecha), leer_importe(importe)
        if not f or imp is None or imp <= 0:
            errores.append(f"La cuota {nro or '?'} no tiene fecha o importe válidos.")
            continue
        out.append((0, f, Decimal(str(imp)).quantize(CENT)))
    out.sort(key=lambda c: c[1])
    out = [(i + 1, f, imp) for i, (_, f, imp) in enumerate(out)]
    if not out and not errores:
        errores.append("Cargá al menos una cuota con fecha e importe.")
    return out, errores


@fisca_acta_bp.route("/actas/<int:id_acta>/acuerdo/guardar", methods=["POST"])
def acuerdo_guardar(id_acta):
    salida = _guardia(URL_ACUERDOS)
    if salida:
        return salida
    f = request.form
    id_x = f.get("id", type=int)
    cuotas, errores = leer_cronograma(f)
    fecha_acuerdo = _fecha(f.get("fecha_acuerdo"))
    if not fecha_acuerdo:
        errores.append("Falta la fecha del acuerdo.")
    if cuotas and fecha_acuerdo and cuotas[0][1] < fecha_acuerdo:
        errores.append("La primera cuota vence antes de la fecha del acuerdo.")
    volver = url_for("fisca_acta.acuerdo", id_acta=id_acta, id=id_x)
    if errores:
        for e in errores:
            flash("!" + e)
        return redirect(volver)
    t = lambda k, n: (f.get(k) or "").strip()[:n] or None             # noqa: E731
    with get_connection() as conn:
        try:
            with conn.cursor() as cur:
                a = leer_acta(cur, id_acta, bloquear=True)
                if not a or a["estado"] != "cerrada":
                    raise ErrorActa("El acuerdo de pago se carga sobre un acta cerrada.")
                deuda = _d(a["total"])
                total = sum((c[2] for c in cuotas), Decimal("0"))
                if total + Decimal("0.005") < deuda:
                    raise ErrorActa(f"El cronograma suma {_pesos(total)} y no cubre la deuda del acta ({_pesos(deuda)}): "
                                    "falta una cuota o un importe.")
                interes = total - deuda
                datos = {"fecha_acuerdo": fecha_acuerdo, "monto_deuda": deuda, "interes_financiacion": interes,
                         "monto_total": total, "cantidad_cuotas": len(cuotas), "forma_pago": t("forma_pago", 150),
                         "lugar_pago": t("lugar_pago", 300), "representante": t("representante", 200),
                         "representante_dni": t("representante_dni", 20), "representante_cargo": t("representante_cargo", 100),
                         "observaciones": t("observaciones", 1000)}
                if id_x:
                    cur.execute("SELECT * FROM fisca_acuerdo WHERE id = %s FOR UPDATE", (id_x,))
                    x = cur.fetchone()
                    if not x or x["id_acta"] != id_acta:
                        raise ErrorActa("Ese acuerdo no es de esta acta.")
                    if x["estado"] != "vigente":
                        raise ErrorActa("El acuerdo ya no está vigente: no se modifica.")
                    cur.execute(f"UPDATE fisca_acuerdo SET {', '.join(k + ' = %s' for k in datos)} WHERE id = %s",
                                list(datos.values()) + [id_x])
                    cur.execute("DELETE FROM fisca_acuerdo_cuota WHERE id_acuerdo = %s", (id_x,))
                else:
                    if a["acuerdo_vigente"]:
                        raise ErrorActa(f"El acta ya tiene el acuerdo {a['acuerdo_vigente']['nro_acuerdo']} vigente.")
                    if any(y["estado"] == "cancelado" for y in a["acuerdos"]):
                        raise ErrorActa("El acta tiene un acuerdo cancelado: la deuda quedó saldada.")
                    datos.update(nro_acuerdo=numero(cur, "AP", "fisca_acuerdo", fecha_acuerdo), id_acta=id_acta,
                                 cuit=a["cuit"], razon_social=a["razon_social"], id_usuario_creacion=_uid(), estado="vigente")
                    cur.execute(f"INSERT INTO fisca_acuerdo ({', '.join(datos)}) VALUES ({', '.join(['%s'] * len(datos))})",
                                list(datos.values()))
                    id_x = cur.lastrowid
                cur.executemany("INSERT INTO fisca_acuerdo_cuota (id_acuerdo, nro_cuota, vencimiento, importe) "
                                "VALUES (%s, %s, %s, %s)", [(id_x, n, fe, imp) for n, fe, imp in cuotas])
            conn.commit()
            flash(f"Acuerdo guardado: {len(cuotas)} cuota(s) por {_pesos(total)}"
                  + (f" (interés de financiación {_pesos(interes)})." if interes > 0 else ", sin interés de financiación."))
            return redirect(url_for("fisca_acta.acuerdo", id_acta=id_acta, id=id_x))
        except ErrorActa as e:
            conn.rollback()
            flash("!" + str(e))
            return redirect(volver)
        except Exception:
            conn.rollback()
            raise


@fisca_acta_bp.route("/acuerdos/<int:id_acuerdo>/estado", methods=["POST"])
def acuerdo_estado(id_acuerdo):
    salida = _guardia(URL_ACUERDOS)
    if salida:
        return salida
    accion = request.form.get("accion")
    motivo = (request.form.get("motivo") or "").strip()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM fisca_acuerdo WHERE id = %s FOR UPDATE", (id_acuerdo,))
            x = cur.fetchone()
            if not x:
                flash("!No existe ese acuerdo.")
                return redirect(url_for("fisca_acta.acuerdos"))
            nuevo = ACCIONES_ACUERDO.get(accion)
            if not nuevo:
                flash("!Acción desconocida.")
            elif x["estado"] != "vigente":
                flash("!El acuerdo ya no está vigente.")
            elif not motivo:
                flash("!Escribí el motivo.")
            else:
                cur.execute("""UPDATE fisca_acuerdo SET estado = %s, fecha_estado = NOW(), id_usuario_estado = %s,
                                      motivo_estado = %s WHERE id = %s AND estado = 'vigente'""",
                            (nuevo, _uid(), motivo[:255], id_acuerdo))
                conn.commit()
                flash(f"Acuerdo {x['nro_acuerdo']}: {ESTADOS_ACUERDO[nuevo][0].lower()}.")
    return redirect(url_for("fisca_acta.acuerdo", id_acta=x["id_acta"], id=id_acuerdo))


@fisca_acta_bp.route("/acuerdos/<int:id_acuerdo>/pdf")
def acuerdo_pdf(id_acuerdo):
    salida = _guardia(URL_ACUERDOS)
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            x = leer_acuerdo(cur, id_acuerdo)
            a = leer_acta(cur, x["id_acta"]) if x else None
    if not x:
        flash("!No existe ese acuerdo.")
        return redirect(url_for("fisca_acta.acuerdos"))
    if x["estado"] == "anulado":
        flash("!El acuerdo está anulado: no se imprime.")
        return redirect(url_for("fisca_acta.acuerdo", id_acta=x["id_acta"], id=id_acuerdo))
    import pagos_pdf as P
    import institucion
    from reportlab.lib.units import cm
    from reportlab.platypus import Spacer, Table, TableStyle
    doc = P._Doc("Acuerdo de pago", x["nro_acuerdo"],
                 None if x["estado"] == "vigente" else ESTADOS_ACUERDO[x["estado"]][0].upper())
    inst = institucion.obtener()
    doc.datos("PARTES", [
        ("Sindicato", escape(P._txt(inst.get("nombre")))),
        ("Empleador", escape(x["razon_social"] or "") + f" · CUIT {P._cuit(x['cuit'])}"),
        ("En representación", escape(x["representante"] or "") + (f" · DNI {escape(x['representante_dni'])}" if x["representante_dni"] else "")
         + (f" · {escape(x['representante_cargo'])}" if x["representante_cargo"] else "")),
        ("Fecha", P._fecha(x["fecha_acuerdo"])), ("Acta de fiscalización", escape(x["nro_acta"]))])
    doc.datos("DEUDA", [("Deuda determinada en el acta", P._pesos(x["monto_deuda"])),
                        ("Interés de financiación", P._pesos(x["interes_financiacion"])),
                        ("Total a pagar", P._pesos(x["monto_total"])), ("Cuotas", str(x["cantidad_cuotas"]))])
    if a and a["periodos"]:
        doc.story.append(doc.P("Períodos: " + ", ".join(f"{p['periodo'][4:]}/{p['periodo'][:4]}" for p in a["periodos"]) + ".",
                               fontSize=8, textColor=doc.MUTED, spaceAfter=6))
    doc.tabla("CRONOGRAMA", ["Cuota", "Vencimiento", "Importe"],
              [[str(c["nro_cuota"]), P._fecha(c["vencimiento"]), P._pesos(c["importe"])] for c in x["cuotas"]],
              [3.0, 5.0, 5.0], derecha=(2,), total=("Total", P._pesos(x["monto_total"])))
    doc.datos("PAGO", [("Forma de pago", escape(x["forma_pago"] or "")), ("Lugar de pago", escape(x["lugar_pago"] or ""))])
    doc.story.append(doc.P(escape(TEXTO_ACUERDO.format(acta=x["nro_acta"])), fontSize=8.5, leading=11.5, spaceAfter=6))
    if x["observaciones"]:
        doc.datos("OBSERVACIONES", [("", escape(x["observaciones"]))])
    doc.story.append(Spacer(1, 2.2 * cm))
    f = Table([["", "", ""], [doc.P("Por el sindicato", alignment=1), "", doc.P("Por el empleador", alignment=1)]],
              colWidths=[6.5 * cm, 3 * cm, 6.5 * cm], rowHeights=[1.2 * cm, None])
    f.setStyle(TableStyle([("LINEABOVE", (0, 1), (0, 1), 0.6, doc.MUTED), ("LINEABOVE", (2, 1), (2, 1), 0.6, doc.MUTED)]))
    doc.story.append(f)
    return P.respuesta(doc.pdf(f"Acuerdo {x['nro_acuerdo']}"), f"Acuerdo {x['nro_acuerdo']} CUIT {x['cuit']}.pdf")


# ─────────────────────────────────────────────────────────────────────────────
# Fiscalizadores
# ─────────────────────────────────────────────────────────────────────────────

CAMPOS_FISCALIZADOR = {"apellido_nombres": 150, "dni": 20, "cargo": 100, "telefono": 50, "email": 150,
                       "observaciones": 500}


def _fiscalizador_form(cur, form, id_fz) -> tuple[dict, list[str]]:
    v = {k: (form.get(k) or "").strip()[:n] or None for k, n in CAMPOS_FISCALIZADOR.items()}
    errores = []
    if v["apellido_nombres"]:
        v["apellido_nombres"] = v["apellido_nombres"].upper()
    else:
        errores.append("Falta el apellido y nombre.")
    if v["dni"]:
        v["dni"] = re.sub(r"\D", "", v["dni"]) or None
        if v["dni"] and not 6 <= len(v["dni"]) <= 9:
            errores.append("El DNI tiene que tener entre 6 y 9 dígitos.")
        elif v["dni"]:
            cur.execute("SELECT apellido_nombres FROM fisca_fiscalizador WHERE dni = %s AND id <> %s", (v["dni"], id_fz or 0))
            otro = cur.fetchone()
            if otro:
                errores.append(f"El DNI {v['dni']} ya es de {otro['apellido_nombres']}.")
    if v["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v["email"]):
        errores.append("El correo no es válido.")
    v["id_usuario"] = form.get("id_usuario", type=int) or None
    v["activo"] = 1 if form.get("activo") == "1" else 0
    return v, errores


@fisca_acta_bp.route("/fiscalizadores", methods=["GET", "POST"])
def fiscalizadores():
    salida = _guardia(URL_FISCALIZADORES)
    if salida:
        return salida
    errores, registro = [], None
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT COUNT(*) AS n FROM information_schema.tables
                            WHERE table_schema = DATABASE() AND table_name = 'fisca_fiscalizador'""")
            if not cur.fetchone()["n"] or falta_esquema(cur):
                _aviso_esquema()
                return render_template("fisca/fiscalizadores.html", filas=[], registro=None, usuarios=[],
                                       errores=[], abrir_ficha=False)
            if request.method == "POST":
                accion = request.form.get("accion")
                id_fz = request.form.get("id", type=int)
                try:
                    if accion == "guardar":
                        v, errores = _fiscalizador_form(cur, request.form, id_fz)
                        if not errores:
                            if id_fz:
                                cur.execute(f"UPDATE fisca_fiscalizador SET {', '.join(k + ' = %s' for k in v)} WHERE id = %s",
                                            list(v.values()) + [id_fz])
                                flash(f"Fiscalizador {v['apellido_nombres']} actualizado. Las actas ya labradas conservan "
                                      "el nombre y el DNI con que se imprimieron.")
                            else:
                                cur.execute(f"INSERT INTO fisca_fiscalizador ({', '.join(v)}) VALUES ({', '.join(['%s'] * len(v))})",
                                            list(v.values()))
                                flash(f"Fiscalizador {v['apellido_nombres']} agregado.")
                            conn.commit()
                            return redirect(url_for("fisca_acta.fiscalizadores"))
                        registro = {**v, "id": id_fz}
                    elif accion in ("baja", "reactivar"):
                        cur.execute("UPDATE fisca_fiscalizador SET activo = %s WHERE id = %s",
                                    (1 if accion == "reactivar" else 0, id_fz))
                        conn.commit()
                        flash("Fiscalizador " + ("reactivado." if accion == "reactivar" else "desactivado: deja de ofrecerse en las actas."))
                        return redirect(url_for("fisca_acta.fiscalizadores"))
                    elif accion == "borrar":
                        cur.execute("SELECT COUNT(*) AS n FROM fisca_acta WHERE id_fiscalizador = %s", (id_fz,))
                        if cur.fetchone()["n"]:
                            flash("!Figura en actas: no se elimina, se desactiva.")
                        else:
                            cur.execute("DELETE FROM fisca_fiscalizador WHERE id = %s", (id_fz,))
                            conn.commit()
                            flash("Fiscalizador eliminado.")
                        return redirect(url_for("fisca_acta.fiscalizadores"))
                except Exception:
                    conn.rollback()
                    raise
            cur.execute("""SELECT f.*, u.nombre AS usuario,
                                  (SELECT COUNT(*) FROM fisca_acta a WHERE a.id_fiscalizador = f.id) AS actas,
                                  (SELECT COUNT(*) FROM fisca_acta a WHERE a.id_fiscalizador = f.id AND a.estado = 'abierta') AS abiertas,
                                  (SELECT MAX(a.fecha_acta) FROM fisca_acta a WHERE a.id_fiscalizador = f.id) AS ultima
                             FROM fisca_fiscalizador f LEFT JOIN s_usuarios u ON u.id = f.id_usuario
                            ORDER BY f.apellido_nombres""")
            filas = list(cur.fetchall())
            if registro is None:
                if request.args.get("edit", type=int):
                    registro = next((f for f in filas if f["id"] == request.args.get("edit", type=int)), None)
                    if not registro:
                        flash("!No existe ese fiscalizador.")
                elif request.args.get("nuevo"):
                    registro = {"activo": 1}
            cur.execute("SELECT id, nombre, email FROM s_usuarios WHERE activo = 1 OR id = %s ORDER BY nombre",
                        ((registro or {}).get("id_usuario") or 0,))
            usuarios = list(cur.fetchall())
    return render_template("fisca/fiscalizadores.html", filas=filas, registro=registro, usuarios=usuarios,
                           errores=errores, abrir_ficha=registro is not None)
