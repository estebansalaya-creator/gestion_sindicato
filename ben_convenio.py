"""
ben_convenio.py — Beneficios › Convenio YMCA (pedido del 17/11/2026).

El sindicato tiene un convenio con un gimnasio (la YMCA, proveedor de
Proveedores). Los afiliados que se adhieren pagan una cuota fija por mes y el
gimnasio le factura al sindicato todos los meses; la diferencia entre lo que
factura y lo que pagan los afiliados la cubre el sindicato. Decidido el
17/11/2026:

  · La NÓMINA de adheridos se carga en el sistema (`ben_adherido`): titular o
    familiar del padrón, con el mes desde y el mes hasta (vacío = sigue).
  · La CUOTA es un importe fijo para todos, por vigencia (`ben_convenio_precio`,
    con el PRECIO que factura el gimnasio por adherido). Hoy $ 30.000.
  · El ingreso va APARTE de la cuota sindical: las transferencias de los
    afiliados se emiten desde Beneficios › Recibos de Adheridos y ya no salen en
    Fiscalización › Emisión de Recibos. El recibo es el mismo recibo al afiliado
    de recibos_afiliado.py (talonario X 0003, un renglón por mes).
  · CONTROLES: la factura del gimnasio contra la cantidad de la nómina por el
    precio (Control Mensual), y qué grupos familiares pagaron su cuota (Cuotas
    de Adheridos).

LA CUOTA ES DEL GRUPO FAMILIAR
Un adherido puede ser titular o familiar, y quien transfiere suele ser el
titular por todos. Por eso la cuenta se lleva por grupo (`cuil_titular`): cada
mes el grupo debe la cuota × sus adheridos de ese mes, y le cuentan los recibos
de cualquiera del grupo. La transferencia sugiere tantos meses como cuotas
JUSTAS del grupo entra (dos adheridos a $ 30.000: $ 60.000 es un mes).

DESDE CUÁNDO
Hasta octubre de 2026 AEDA registró lo cobrado en una orden por mes, sin
detalle por afiliado: la cuenta de cada grupo empieza en `ben_convenio.cc_desde`
(202611). El control mensual sí usa todo lo cobrado (por mes), también lo de AEDA.

Pantallas (blueprint `ben_conv`, /beneficios/ymca; menú 122-126 en
sql/beneficios_correo_20261117.sql, Administrador y Supervisor):
  /adheridos  /recibos (+ /emitir/<id>, /emitir_lote)  /cuotas (+ /<cuil_titular>)
  /control    /convenio
"""

from __future__ import annotations

import datetime
import logging
from collections import defaultdict
from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for

import fisca_recibos as FR
import recibos_afiliado as RA
from db import get_connection, puede, usuario_actual, validasesion

log = logging.getLogger(__name__)

ben_conv_bp = Blueprint("ben_conv", __name__, url_prefix="/beneficios/ymca")

SQL_ESQUEMA = "sql/beneficios_correo_20261117.sql"
CENT = Decimal("0.01")
URL_ADHERIDOS = "/beneficios/ymca/adheridos"
URL_RECIBOS = "/beneficios/ymca/recibos"
URL_CUOTAS = "/beneficios/ymca/cuotas"
URL_CONTROL = "/beneficios/ymca/control"
URL_CONVENIO = "/beneficios/ymca/convenio"
#: Cuántos meses mira la lista de «transfirieron y no están en la nómina».
MESES_SIN_NOMINA = 3


class ErrorConvenio(ValueError):
    """Un error de validación: el texto va directo a la pantalla."""


# =============================================================================
# Períodos e importes (sin base: lo prueba tests/test_ben_convenio.py)
# =============================================================================

def _d(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(CENT)


def mes_actual(hoy: datetime.date | None = None) -> str:
    return (hoy or datetime.date.today()).strftime("%Y%m")


def sumar(periodo: str, n: int) -> str:
    return RA.sumar_meses(periodo, n)


def meses_entre(desde: str, hasta: str) -> list[str]:
    out, p = [], desde
    while p <= hasta and len(out) < 600:
        out.append(p)
        p = sumar(p, 1)
    return out


def periodo_valido(texto) -> str | None:
    """«2026-11» o «202611» → «202611»."""
    t = (texto or "").strip().replace("-", "").replace("/", "")
    if len(t) == 6 and t.isdigit() and 1 <= int(t[4:]) <= 12 and t[:2] in ("19", "20"):
        return t
    return None


def precio_del_mes(precios: list[dict], periodo: str) -> dict | None:
    """La vigencia que rige el mes: la de `periodo_desde` más nuevo que no lo pasa."""
    vig = [p for p in precios if str(p["periodo_desde"]) <= periodo]
    return max(vig, key=lambda p: str(p["periodo_desde"])) if vig else None


def vigente_en(a: dict, periodo: str) -> bool:
    return str(a["periodo_desde"]) <= periodo and (not a["periodo_hasta"] or str(a["periodo_hasta"]) >= periodo)


def adheridos_del_mes(adheridos: list[dict], periodo: str) -> list[dict]:
    return [a for a in adheridos if vigente_en(a, periodo)]


def se_superpone(adheridos: list[dict], id_afiliado: int, desde: str, hasta: str | None, excepto=None) -> dict | None:
    """Otro período del mismo afiliado que pisa [desde, hasta]."""
    fin = hasta or "999912"
    for a in adheridos:
        if a["id_afiliado"] != id_afiliado or a["id"] == excepto:
            continue
        if str(a["periodo_desde"]) <= fin and (not a["periodo_hasta"] or str(a["periodo_hasta"]) >= desde):
            return a
    return None


def cuota_del_grupo(adheridos: list[dict], precios: list[dict], cuil_titular: str, periodo: str) -> tuple[Decimal, int]:
    """(cuota del mes × adheridos del grupo en el mes, adheridos). Sin adheridos, la de uno."""
    p = precio_del_mes(precios, periodo)
    cuota = _d(p["cuota_afiliado"]) if p else Decimal("0")
    n = sum(1 for a in adheridos_del_mes(adheridos, periodo) if a["cuil_titular"] == cuil_titular)
    return (cuota * (n or 1)).quantize(CENT), n


def armar_cuentas(adheridos: list[dict], precios: list[dict], cobros: list[dict], desde: str, hasta: str) -> dict:
    """
    La cuenta de cada grupo familiar de `desde` a `hasta`:
    {cuil_titular: {"meses": [{periodo, adheridos, debe, pagado, saldo}], "debe", "pagado", "saldo",
                    "adeudados", "ultimo_pago", "personas": [nombres]}}
    `cobros`: [{cuil_titular, periodo, importe, fecha}] (los renglones de los recibos).
    Lo pagado a un mes en que el grupo no tenía adheridos cuenta igual (saldo a favor).
    """
    grupos: dict[str, dict] = {}
    for a in adheridos:
        g = grupos.setdefault(a["cuil_titular"], {"personas": {}, "titular": None})
        g["personas"][a["id_afiliado"]] = a["apellido_nombres"]
        if a["cuil"] == a["cuil_titular"]:
            g["titular"] = a["apellido_nombres"]
    pagos: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    ultimo: dict[str, datetime.date] = {}
    for c in cobros:
        if not c["periodo"] or not (desde <= str(c["periodo"]) <= hasta):
            continue
        pagos[c["cuil_titular"]][str(c["periodo"])] += _d(c["importe"])
        if c.get("fecha") and (c["cuil_titular"] not in ultimo or c["fecha"] > ultimo[c["cuil_titular"]]):
            ultimo[c["cuil_titular"]] = c["fecha"]
    out = {}
    for tit, g in grupos.items():
        meses, debe_t, pag_t, adeudados = [], Decimal("0"), Decimal("0"), 0
        for p in meses_entre(desde, hasta):
            pr = precio_del_mes(precios, p)
            n = sum(1 for a in adheridos_del_mes(adheridos, p) if a["cuil_titular"] == tit)
            debe = (_d(pr["cuota_afiliado"]) * n).quantize(CENT) if pr and n else Decimal("0")
            pagado = pagos[tit].get(p, Decimal("0"))
            if not n and not pagado:
                continue
            saldo = debe - pagado
            if saldo > 0:
                adeudados += 1
            meses.append({"periodo": p, "adheridos": n, "debe": debe, "pagado": pagado, "saldo": saldo})
            debe_t += debe
            pag_t += pagado
        out[tit] = {"meses": meses, "debe": debe_t, "pagado": pag_t, "saldo": debe_t - pag_t,
                    "adeudados": adeudados, "ultimo_pago": ultimo.get(tit),
                    "personas": sorted(g["personas"].values()), "titular": g["titular"],
                    "vigentes": sum(1 for a in adheridos_del_mes(adheridos, hasta) if a["cuil_titular"] == tit)}
    return out


def armar_control(adheridos: list[dict], precios: list[dict], facturas: list[dict], cobrado: dict,
                  meses: list[str], pagaron: dict | None = None) -> list[dict]:
    """
    Un renglón por mes: adheridos de la nómina, precio del gimnasio, lo esperado
    (adheridos × precio), lo facturado y la diferencia, lo cobrado a los afiliados
    y lo que cubre el sindicato (facturado − cobrado).
    `facturas`: [{periodo, importe (con signo), …}]; `cobrado`: {periodo: importe};
    `pagaron`: {periodo: grupos que pagaron algo}.
    """
    fact = defaultdict(list)
    for f in facturas:
        fact[str(f["periodo"])].append(f)
    filas = []
    for p in meses:
        ad = adheridos_del_mes(adheridos, p)
        pr = precio_del_mes(precios, p)
        precio = _d(pr["precio_proveedor"]) if pr and pr.get("precio_proveedor") is not None else None
        esperado = (precio * len(ad)).quantize(CENT) if precio is not None else None
        facturado = sum((_d(f["importe"]) for f in fact[p]), Decimal("0"))
        cob = _d(cobrado.get(p))
        grupos = {a["cuil_titular"] for a in ad}
        filas.append({
            "periodo": p, "adheridos": len(ad), "grupos": len(grupos), "precio": precio,
            "cuota": _d(pr["cuota_afiliado"]) if pr else None,
            "esperado": esperado, "facturas": fact[p], "facturado": facturado,
            "diferencia": (facturado - esperado) if esperado is not None and fact[p] else None,
            "adheridos_por_factura": (facturado / precio).quantize(Decimal("0.01")) if precio and fact[p] else None,
            "cobrado": cob, "a_cargo": facturado - cob,
            "a_cobrar": (_d(pr["cuota_afiliado"]) * len(ad)).quantize(CENT) if pr else None,
            "pagaron": (pagaron or {}).get(p),
        })
    return filas


# =============================================================================
# Base
# =============================================================================

def hay_esquema(cur) -> bool:
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_schema = DATABASE()
                     AND table_name IN ('ben_convenio', 'ben_convenio_precio', 'ben_adherido')""")
    return int(cur.fetchone()["n"] or 0) == 3


def convenio(cur, id_convenio: int | None = None) -> dict | None:
    """El convenio (el primero activo si no se dice cuál), con su proveedor y motivo."""
    cur.execute(f"""SELECT c.*, p.razon_social AS proveedor, p.cuit AS cuit_proveedor, m.descripcion AS motivo
                      FROM ben_convenio c
                      LEFT JOIN c_proveedores p ON p.id = c.id_proveedor
                      LEFT JOIN c_motivos_de_ingreso m ON m.id = c.id_motivo_ingreso
                     WHERE {'c.id = %s' if id_convenio else 'c.activo = 1'}
                     ORDER BY c.id LIMIT 1""", (id_convenio,) if id_convenio else ())
    return cur.fetchone()


def precios(cur, id_convenio: int) -> list[dict]:
    cur.execute("""SELECT p.*, u.nombre AS usuario FROM ben_convenio_precio p
                     LEFT JOIN s_usuarios u ON u.id = p.id_usuario
                    WHERE p.id_convenio = %s ORDER BY p.periodo_desde""", (id_convenio,))
    return cur.fetchall()


def adheridos(cur, id_convenio: int) -> list[dict]:
    """La nómina entera, con los datos del padrón. `cuil_titular`: el grupo
    (un titular es su propio grupo; sin CUIL, el id del afiliado)."""
    cur.execute("""SELECT b.*, a.cuil, a.apellido_nombres, a.cod_parentesco, a.fecha_baja AS baja_padron,
                          COALESCE(NULLIF(a.cuil_titular, ''), a.cuil, CONCAT('ID', a.id_afiliado)) AS cuil_titular,
                          pa.descripcion AS parentesco, ua.nombre AS usuario_alta
                     FROM ben_adherido b
                     JOIN p_afiliados a ON a.id_afiliado = b.id_afiliado
                     LEFT JOIN p_parentesco pa ON pa.codigo = a.cod_parentesco
                     LEFT JOIN s_usuarios ua ON ua.id = b.id_usuario_alta
                    WHERE b.id_convenio = %s
                    ORDER BY a.apellido_nombres, b.periodo_desde""", (id_convenio,))
    return cur.fetchall()


def cobros_por_grupo(cur, motivo: int | None, desde: str) -> list[dict]:
    """Los renglones de los recibos a afiliados (no anulados) del motivo del
    convenio, desde un mes, con el grupo de quien pagó."""
    if not motivo:
        return []
    cur.execute("""SELECT COALESCE(NULLIF(a.cuil_titular, ''), o.cuil_afiliado) AS cuil_titular, d.periodo,
                          d.importe, o.fecha, o.id AS id_orden
                     FROM ingreso_ordenes o
                     JOIN ingreso_ordenes_detalle d ON d.id_orden = o.id
                     LEFT JOIN p_afiliados a ON a.id_afiliado = (SELECT x.id_afiliado FROM p_afiliados x
                                                                  WHERE x.cuil = o.cuil_afiliado
                                                                  ORDER BY x.activo DESC, x.id_afiliado LIMIT 1)
                    WHERE o.clase = 'afiliado' AND o.estado <> 'anulado' AND d.id_motivo_ingreso = %s
                      AND d.periodo >= %s""", (motivo, desde))
    return cur.fetchall()


def cobrado_por_mes(cur, motivo: int | None, desde: str, hasta: str) -> dict:
    """Todo lo cobrado con el motivo del convenio, por mes (también las órdenes
    agrupadas de AEDA, que no tienen período: el de su fecha)."""
    if not motivo:
        return {}
    cur.execute("""SELECT COALESCE(d.periodo, CONCAT(YEAR(o.fecha), LPAD(MONTH(o.fecha), 2, '0'))) AS periodo,
                          SUM(d.importe) AS importe
                     FROM ingreso_ordenes o JOIN ingreso_ordenes_detalle d ON d.id_orden = o.id
                    WHERE o.estado <> 'anulado' AND d.id_motivo_ingreso = %s
                    GROUP BY 1 HAVING periodo BETWEEN %s AND %s""", (motivo, desde, hasta))
    return {str(f["periodo"]): f["importe"] for f in cur.fetchall()}


def facturas(cur, conv: dict, desde: str, hasta: str) -> list[dict]:
    """Las facturas (y notas de crédito, en negativo) del gimnasio por período,
    con su expediente."""
    if not conv.get("id_proveedor"):
        return []
    cur.execute("""SELECT c.id, c.periodo, c.numero_completo, c.fecha_emision, c.estado, tc.descripcion AS tipo,
                          c.importe_total * IF(COALESCE(tc.descripcion REGEXP 'nota.*cr[eé]dito', 0), -1, 1) AS importe,
                          x.id AS id_expediente, x.nro_expediente
                     FROM f_comprobantes_arca c
                     LEFT JOIN arca_tipo_comprobante tc ON tc.codigo = LPAD(c.tipo_comprobante, 3, '0')
                     LEFT JOIN me_expedientes x ON x.id_comprobante = c.id
                    WHERE (c.id_proveedor = %s OR REPLACE(c.cuit_emisor, '-', '') = %s)
                      AND COALESCE(c.estado, '') <> 'anulado' AND c.periodo BETWEEN %s AND %s
                    ORDER BY c.periodo, c.fecha_emision""",
                (conv["id_proveedor"], conv.get("cuit_proveedor") or "", desde, hasta))
    return cur.fetchall()


def config_recibo(cur, conv: dict) -> dict | None:
    """Lo de recibos_afiliado (talonario, concepto) con el motivo del convenio."""
    cfg = RA.config(cur)
    if cfg is None:
        return None
    if conv.get("id_motivo_ingreso"):
        cfg["motivo"] = conv["id_motivo_ingreso"]
    return cfg


# =============================================================================
# Pantallas
# =============================================================================

def _guardia(url):
    if not validasesion():
        return redirect(url_for("login"))
    if not puede(url):
        flash("!No tenés permiso para esa pantalla.")
        return redirect(url_for("menu"))
    return None


def _uid():
    return (usuario_actual() or {}).get("id")


def _base(cur):
    """El convenio, o None con el aviso (falta el script o no hay convenio)."""
    if not hay_esquema(cur):
        flash(f"!Falta correr {SQL_ESQUEMA}: sin esas tablas el convenio no funciona.")
        return None
    conv = convenio(cur)
    if not conv:
        flash("!No hay ningún convenio activo: cargalo en Datos del Convenio.")
    return conv


def _ctx(conv, **kw):
    return {"conv": conv, "puede": puede, **kw}


# ── Nómina de adheridos ──────────────────────────────────────────────────────

@ben_conv_bp.route("/adheridos", methods=["GET", "POST"])
def adheridos_abm():
    salida = _guardia(URL_ADHERIDOS)
    if salida:
        return salida
    errores, registro = [], None
    with get_connection() as conn:
        with conn.cursor() as cur:
            conv = _base(cur)
            if not conv:
                return render_template("beneficios/adheridos.html", **_ctx(None, filas=[], errores=[], registro=None,
                                                                            sin_nomina=[], mes=mes_actual(), totales={}))
            nomina = adheridos(cur, conv["id"])
            if request.method == "POST":
                accion = request.form.get("accion")
                try:
                    if accion == "guardar":
                        registro, errores = _guardar_adherido(cur, conv, nomina, request.form)
                        if not errores:
                            conn.commit()
                            return redirect(url_for("ben_conv.adheridos_abm"))
                    elif accion == "baja":
                        _baja_adherido(cur, conv, request.form)
                        conn.commit()
                        return redirect(url_for("ben_conv.adheridos_abm"))
                    elif accion == "borrar":
                        _borrar_adherido(cur, conv, request.form.get("id", type=int))
                        conn.commit()
                        return redirect(url_for("ben_conv.adheridos_abm"))
                except ErrorConvenio as e:
                    conn.rollback()
                    flash("!" + str(e))
                    return redirect(url_for("ben_conv.adheridos_abm"))
                except Exception:
                    conn.rollback()
                    raise
            if registro is None and request.args.get("edit", type=int):
                registro = next((a for a in nomina if a["id"] == request.args.get("edit", type=int)), None)
            if registro is None and "cuil" in request.args:
                registro = {"cuil": request.args.get("cuil"), "periodo_desde": request.args.get("desde") or mes_actual()}
            sin_nomina = _transfirieron_sin_nomina(cur, nomina)
    mes = mes_actual()
    vig = adheridos_del_mes(nomina, mes)
    for a in nomina:
        a["vigente"] = vigente_en(a, mes)
        a["estado"] = "vigente" if a["vigente"] else ("futuro" if str(a["periodo_desde"]) > mes else "baja")
    totales = {"vigentes": len(vig), "grupos": len({a["cuil_titular"] for a in vig}),
               "titulares": sum(1 for a in vig if a["cuil"] == a["cuil_titular"]),
               "familiares": sum(1 for a in vig if a["cuil"] != a["cuil_titular"])}
    return render_template("beneficios/adheridos.html", **_ctx(conv, filas=nomina, errores=errores, registro=registro,
                                                                sin_nomina=sin_nomina, mes=mes, totales=totales,
                                                                abrir_ficha=bool(registro or errores)))


def _afiliado_por_cuil(cur, cuil: str) -> dict | None:
    cur.execute("""SELECT id_afiliado, cuil, apellido_nombres, fecha_baja, cod_parentesco, cuil_titular FROM p_afiliados
                    WHERE cuil = %s ORDER BY (fecha_baja IS NULL) DESC, id_afiliado LIMIT 1""", (cuil,))
    return cur.fetchone()


def _guardar_adherido(cur, conv, nomina, form) -> tuple[dict, list[str]]:
    id_reg = form.get("id", type=int)
    cuil = "".join(ch for ch in (form.get("cuil") or "") if ch.isdigit())
    desde = periodo_valido(form.get("periodo_desde"))
    hasta = periodo_valido(form.get("periodo_hasta")) if (form.get("periodo_hasta") or "").strip() else None
    obs = " ".join((form.get("observaciones") or "").split())[:300] or None
    registro = {"id": id_reg, "cuil": cuil, "periodo_desde": desde or form.get("periodo_desde"),
                "periodo_hasta": hasta, "observaciones": obs}
    errores = []
    afi = _afiliado_por_cuil(cur, cuil) if len(cuil) == 11 else None
    if not afi:
        errores.append(f"El CUIL {cuil or '—'} no está en el padrón.")
    if not desde:
        errores.append("El mes desde no es válido.")
    if (form.get("periodo_hasta") or "").strip() and not hasta:
        errores.append("El mes hasta no es válido.")
    if desde and hasta and hasta < desde:
        errores.append("El mes hasta es anterior al mes desde.")
    if afi and desde:
        otro = se_superpone(nomina, afi["id_afiliado"], desde, hasta, excepto=id_reg)
        if otro:
            errores.append(f"{afi['apellido_nombres']} ya está en la nómina de {RA.periodo_txt(otro['periodo_desde'])}"
                           + (f" a {RA.periodo_txt(otro['periodo_hasta'])}" if otro["periodo_hasta"] else " en adelante")
                           + ": corregí ese período en lugar de cargar otro.")
    if errores:
        return registro, errores
    if id_reg:
        cur.execute("""UPDATE ben_adherido SET id_afiliado = %s, periodo_desde = %s, periodo_hasta = %s,
                              observaciones = %s, id_usuario_baja = IF(%s IS NULL, NULL, COALESCE(id_usuario_baja, %s))
                        WHERE id = %s AND id_convenio = %s""",
                    (afi["id_afiliado"], desde, hasta, obs, hasta, _uid(), id_reg, conv["id"]))
        flash(f"{afi['apellido_nombres']}: adhesión actualizada.")
    else:
        cur.execute("""INSERT INTO ben_adherido (id_convenio, id_afiliado, periodo_desde, periodo_hasta, observaciones,
                                                 id_usuario_alta)
                       VALUES (%s, %s, %s, %s, %s, %s)""", (conv["id"], afi["id_afiliado"], desde, hasta, obs, _uid()))
        aviso = " Ojo: en el padrón está dado de baja." if afi["fecha_baja"] else ""
        flash(f"{afi['apellido_nombres']} agregado a la nómina desde {RA.periodo_txt(desde)}.{aviso}")
    return registro, []


def _baja_adherido(cur, conv, form) -> None:
    id_reg = form.get("id", type=int)
    hasta = periodo_valido(form.get("periodo_hasta"))
    if not hasta:
        raise ErrorConvenio("Elegí el último mes que paga.")
    cur.execute("SELECT * FROM ben_adherido WHERE id = %s AND id_convenio = %s FOR UPDATE", (id_reg, conv["id"]))
    a = cur.fetchone()
    if not a:
        raise ErrorConvenio("No existe esa adhesión.")
    if hasta < str(a["periodo_desde"]):
        raise ErrorConvenio(f"El último mes no puede ser anterior al primero ({RA.periodo_txt(a['periodo_desde'])}).")
    obs = " ".join((form.get("motivo") or "").split())[:200]
    cur.execute("""UPDATE ben_adherido SET periodo_hasta = %s, id_usuario_baja = %s,
                          observaciones = TRIM(CONCAT_WS(' · ', NULLIF(observaciones, ''), %s))
                    WHERE id = %s""", (hasta, _uid(), f"Baja: {obs}" if obs else None, id_reg))
    flash(f"Baja registrada: el último mes que paga es {RA.periodo_txt(hasta)}.")


def _borrar_adherido(cur, conv, id_reg) -> None:
    """Solo una carga equivocada: si ya debía algún mes de la cuenta, se da de baja."""
    cur.execute("SELECT * FROM ben_adherido WHERE id = %s AND id_convenio = %s", (id_reg, conv["id"]))
    a = cur.fetchone()
    if not a:
        raise ErrorConvenio("No existe esa adhesión.")
    if conv.get("cc_desde") and str(a["periodo_desde"]) <= mes_actual() and \
            (not a["periodo_hasta"] or str(a["periodo_hasta"]) >= str(conv["cc_desde"])):
        raise ErrorConvenio("Esa adhesión ya generó cuotas: no se elimina, se da de baja con el último mes que paga.")
    cur.execute("DELETE FROM ben_adherido WHERE id = %s", (id_reg,))
    flash("Adhesión eliminada.")


def _transfirieron_sin_nomina(cur, nomina) -> list[dict]:
    """Afiliados que transfirieron (extracto) o tienen recibo de la cuota social en
    los últimos meses y cuyo grupo no tiene adheridos ese mes: para armar la nómina."""
    desde = (datetime.date.today().replace(day=1) - datetime.timedelta(days=31 * (MESES_SIN_NOMINA - 1))).replace(day=1)
    cur.execute("""SELECT e.cuit AS cuil, COUNT(*) AS veces, MAX(e.fecham) AS ultima, SUM(e.credito) AS total,
                          SUBSTRING_INDEX(GROUP_CONCAT(e.credito ORDER BY e.fecham DESC), ',', 1) AS ultimo_importe
                     FROM c_extractos_bancarios e
                    WHERE e.credito > 0 AND e.fecham >= %s AND e.cuit REGEXP '^(20|23|24|27)[0-9]{9}$'
                      AND NOT EXISTS (SELECT 1 FROM p_empresas p WHERE p.CUIT = CAST(e.cuit AS UNSIGNED))
                    GROUP BY e.cuit""", (desde,))
    transf = {f["cuil"]: f for f in cur.fetchall()}
    if not transf:
        return []
    cuils = list(transf)
    cur.execute(f"""SELECT id_afiliado, cuil, apellido_nombres, fecha_baja,
                           COALESCE(NULLIF(cuil_titular, ''), cuil) AS cuil_titular
                      FROM p_afiliados WHERE cuil IN ({','.join(['%s'] * len(cuils))})""", cuils)
    afis = {}
    for a in cur.fetchall():
        afis.setdefault(a["cuil"], a)
    grupos_en_nomina = {a["cuil_titular"] for a in nomina if not a["periodo_hasta"] or str(a["periodo_hasta"]) >= desde.strftime("%Y%m")}
    out = []
    for cuil, t in transf.items():
        a = afis.get(cuil)
        if not a or a["cuil_titular"] in grupos_en_nomina:
            continue
        out.append({**t, **a, "ultimo_importe": _d(t["ultimo_importe"])})
    return sorted(out, key=lambda x: x["ultima"], reverse=True)


# ── Datos del convenio y precios ────────────────────────────────────────────

@ben_conv_bp.route("/convenio", methods=["GET", "POST"])
def convenio_ficha():
    salida = _guardia(URL_CONVENIO)
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            if not hay_esquema(cur):
                flash(f"!Falta correr {SQL_ESQUEMA}.")
                return render_template("beneficios/convenio.html", conv=None, precios=[], proveedores=[], motivos=[],
                                       editar_precio=None)
            conv = convenio(cur)
            if request.method == "POST":
                try:
                    _post_convenio(cur, conv, request.form)
                    conn.commit()
                except ErrorConvenio as e:
                    conn.rollback()
                    flash("!" + str(e))
                except Exception:
                    conn.rollback()
                    raise
                return redirect(url_for("ben_conv.convenio_ficha"))
            pre = precios(cur, conv["id"]) if conv else []
            cur.execute("SELECT id, razon_social, cuit FROM c_proveedores WHERE activo = 1 OR id = %s ORDER BY razon_social",
                        ((conv or {}).get("id_proveedor") or 0,))
            proveedores = cur.fetchall()
            cur.execute("SELECT id, descripcion FROM c_motivos_de_ingreso ORDER BY descripcion")
            motivos = cur.fetchall()
    editar = next((p for p in pre if p["id"] == request.args.get("precio", type=int)), None)
    mes = mes_actual()
    for p in pre:
        sig = [x for x in pre if str(x["periodo_desde"]) > str(p["periodo_desde"])]
        p["hasta"] = sumar(min(str(x["periodo_desde"]) for x in sig), -1) if sig else None
        p["vigente"] = str(p["periodo_desde"]) <= mes and (not p["hasta"] or p["hasta"] >= mes)
    return render_template("beneficios/convenio.html", conv=conv, precios=pre, proveedores=proveedores,
                           motivos=motivos, editar_precio=editar, mes=mes)


def _post_convenio(cur, conv, form) -> None:
    from pagos_datos import leer_importe
    accion = form.get("accion")
    if accion == "datos":
        nombre = " ".join((form.get("nombre") or "").split())[:100]
        if not nombre:
            raise ErrorConvenio("El nombre es obligatorio.")
        cc = periodo_valido(form.get("cc_desde")) if (form.get("cc_desde") or "").strip() else None
        if (form.get("cc_desde") or "").strip() and not cc:
            raise ErrorConvenio("El mes desde el que se lleva la cuota no es válido.")
        valores = (nombre, form.get("id_proveedor", type=int), form.get("id_motivo_ingreso", type=int), cc,
                   " ".join((form.get("observaciones") or "").split())[:500] or None)
        if conv:
            cur.execute("""UPDATE ben_convenio SET nombre = %s, id_proveedor = %s, id_motivo_ingreso = %s, cc_desde = %s,
                                  observaciones = %s WHERE id = %s""", (*valores, conv["id"]))
        else:
            cur.execute("""INSERT INTO ben_convenio (nombre, id_proveedor, id_motivo_ingreso, cc_desde, observaciones)
                           VALUES (%s, %s, %s, %s, %s)""", valores)
        flash("Datos del convenio guardados.")
        return
    if not conv:
        raise ErrorConvenio("Primero cargá los datos del convenio.")
    if accion == "precio":
        id_p = form.get("id", type=int)
        desde = periodo_valido(form.get("periodo_desde"))
        cuota = leer_importe(form.get("cuota_afiliado") or "")
        precio_txt = (form.get("precio_proveedor") or "").strip()
        precio = leer_importe(precio_txt) if precio_txt else None
        if not desde:
            raise ErrorConvenio("El mes desde no es válido.")
        if not cuota or cuota <= 0:
            raise ErrorConvenio("La cuota del afiliado tiene que ser mayor que cero.")
        if precio_txt and (precio is None or precio <= 0):
            raise ErrorConvenio("El precio del gimnasio no es válido.")
        cur.execute("SELECT id FROM ben_convenio_precio WHERE id_convenio = %s AND periodo_desde = %s AND id <> %s",
                    (conv["id"], desde, id_p or 0))
        if cur.fetchone():
            raise ErrorConvenio(f"Ya hay una vigencia desde {RA.periodo_txt(desde)}: corregí esa.")
        obs = " ".join((form.get("observaciones") or "").split())[:300] or None
        if id_p:
            cur.execute("""UPDATE ben_convenio_precio SET periodo_desde = %s, precio_proveedor = %s, cuota_afiliado = %s,
                                  observaciones = %s, id_usuario = %s WHERE id = %s AND id_convenio = %s""",
                        (desde, precio, cuota, obs, _uid(), id_p, conv["id"]))
        else:
            cur.execute("""INSERT INTO ben_convenio_precio (id_convenio, periodo_desde, precio_proveedor, cuota_afiliado,
                                                            observaciones, id_usuario)
                           VALUES (%s, %s, %s, %s, %s, %s)""", (conv["id"], desde, precio, cuota, obs, _uid()))
        flash(f"Vigencia desde {RA.periodo_txt(desde)} guardada.")
    elif accion == "borrar_precio":
        cur.execute("DELETE FROM ben_convenio_precio WHERE id = %s AND id_convenio = %s",
                    (form.get("id", type=int), conv["id"]))
        flash("Vigencia eliminada: los meses que cubría pasan a la anterior.")


# ── Cuotas de adheridos (por grupo familiar) ────────────────────────────────

def _rango_cuenta(conv, args) -> tuple[str, str]:
    hasta = periodo_valido(args.get("hasta")) or mes_actual()
    desde = periodo_valido(args.get("desde")) or str(conv.get("cc_desde") or sumar(hasta, -11))
    if conv.get("cc_desde") and desde < str(conv["cc_desde"]):
        desde = str(conv["cc_desde"])
    return desde, max(desde, hasta)


@ben_conv_bp.route("/cuotas")
def cuotas():
    salida = _guardia(URL_CUOTAS)
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            conv = _base(cur)
            if not conv:
                return render_template("beneficios/cuotas.html", conv=None, filas=[], desde=None, hasta=None, tot={})
            desde, hasta = _rango_cuenta(conv, request.args)
            nomina, pre = adheridos(cur, conv["id"]), precios(cur, conv["id"])
            cob = cobros_por_grupo(cur, conv.get("id_motivo_ingreso"), desde)
    cuentas = armar_cuentas(nomina, pre, cob, desde, hasta)
    filas = sorted(({"cuil_titular": k, **v} for k, v in cuentas.items()), key=lambda f: (f["titular"] or f["personas"][0]))
    tot = {"grupos": len(filas), "debe": sum((f["debe"] for f in filas), Decimal("0")),
           "pagado": sum((f["pagado"] for f in filas), Decimal("0")),
           "con_deuda": sum(1 for f in filas if f["saldo"] > 0)}
    tot["saldo"] = tot["debe"] - tot["pagado"]
    return render_template("beneficios/cuotas.html", conv=conv, filas=filas, desde=desde, hasta=hasta, tot=tot)


@ben_conv_bp.route("/cuotas/<cuil_titular>")
def cuota_grupo(cuil_titular):
    salida = _guardia(URL_CUOTAS)
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            conv = _base(cur)
            if not conv:
                return redirect(url_for("ben_conv.cuotas"))
            desde, hasta = _rango_cuenta(conv, request.args)
            nomina = [a for a in adheridos(cur, conv["id"]) if a["cuil_titular"] == cuil_titular]
            pre = precios(cur, conv["id"])
            cob = [c for c in cobros_por_grupo(cur, conv.get("id_motivo_ingreso"), desde) if c["cuil_titular"] == cuil_titular]
            cur.execute("""SELECT id_afiliado, cuil, apellido_nombres FROM p_afiliados
                            WHERE cuil = %s OR cuil_titular = %s ORDER BY cod_parentesco, apellido_nombres""",
                        (cuil_titular, cuil_titular))
            grupo = cur.fetchall()
            recibos = []
            for a in grupo:
                recibos += [dict(r, afiliado=a["apellido_nombres"]) for r in RA.del_afiliado(cur, a["cuil"])]
    cuenta = armar_cuentas(nomina, pre, cob, desde, hasta).get(cuil_titular)
    if not cuenta:
        flash("!Ese grupo no tiene adheridos en la nómina.")
        return redirect(url_for("ben_conv.cuotas"))
    recibos.sort(key=lambda r: (r["fecha"], r["id"]), reverse=True)
    return render_template("beneficios/cuota_grupo.html", conv=conv, cuenta=cuenta, cuil_titular=cuil_titular,
                           nomina=nomina, grupo=grupo, recibos=recibos, desde=desde, hasta=hasta)


# ── Control mensual de la factura del gimnasio ──────────────────────────────

@ben_conv_bp.route("/control")
def control():
    salida = _guardia(URL_CONTROL)
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            conv = _base(cur)
            if not conv:
                return render_template("beneficios/control.html", conv=None, filas=[], desde=None, hasta=None, tot={})
            hasta = periodo_valido(request.args.get("hasta")) or mes_actual()
            desde = periodo_valido(request.args.get("desde")) or sumar(hasta, -11)
            desde = min(desde, hasta)
            nomina, pre = adheridos(cur, conv["id"]), precios(cur, conv["id"])
            fact = facturas(cur, conv, desde, hasta)
            cobrado = cobrado_por_mes(cur, conv.get("id_motivo_ingreso"), desde, hasta)
            cob = cobros_por_grupo(cur, conv.get("id_motivo_ingreso"), desde)
    pagaron = defaultdict(set)
    for c in cob:
        pagaron[str(c["periodo"])].add(c["cuil_titular"])
    filas = armar_control(nomina, pre, fact, cobrado, meses_entre(desde, hasta),
                          {p: len(v) for p, v in pagaron.items()})
    tot = {k: sum((f[k] or Decimal("0") for f in filas), Decimal("0")) for k in ("facturado", "cobrado", "a_cargo")}
    tot["diferencias"] = sum(1 for f in filas if f["diferencia"] and abs(f["diferencia"]) >= 1)
    tot["sin_precio"] = any(f["precio"] is None for f in filas)
    return render_template("beneficios/control.html", conv=conv, filas=filas, desde=desde, hasta=hasta, tot=tot,
                           puede_mesa=puede("/mesa"))


# ── Recibos de adheridos (aparte de la cuota sindical) ──────────────────────

def es_de_beneficios(f: dict) -> bool:
    """La acreditación es de un afiliado (no de un empleador): va por Beneficios."""
    return f.get("emp", {}).get("como") == "afiliado"


def acreditaciones(cur, conv, id_cuenta, desde, hasta) -> tuple[list[dict], bool, dict | None]:
    """Las acreditaciones de afiliados de la cuenta, con lo sugerido por la cuota
    del grupo: N cuotas justas del grupo pagan N meses (en lote); si no, de a una."""
    filas, excedido = FR.acreditaciones(cur, id_cuenta, desde, hasta)
    filas = [f for f in filas if es_de_beneficios(f)]
    cfg = config_recibo(cur, conv)
    nomina, pre = adheridos(cur, conv["id"]), precios(cur, conv["id"])
    if filas:
        cuils = list({FR.digitos(f["cuit"]) for f in filas})
        cur.execute(f"""SELECT cuil, COALESCE(NULLIF(cuil_titular, ''), cuil) AS cuil_titular FROM p_afiliados
                         WHERE cuil IN ({','.join(['%s'] * len(cuils))})""", cuils)
        grupo_de = {r["cuil"]: r["cuil_titular"] for r in cur.fetchall()}
    for f in filas:
        mes = f["fecham"].strftime("%Y%m")
        tit = grupo_de.get(FR.digitos(f["cuit"]))
        f["cuil_titular"] = tit
        f["cuota_grupo"], f["adheridos"] = cuota_del_grupo(nomina, pre, tit, mes)
        f["al_afiliado"] = True
        if cfg and f["estado"] in FR.EMITIBLES:
            f["sugerido"] = RA.periodos(f["importe"], f["fecham"], f["cuota_grupo"])
            f["en_lote"] = (f["estado"] == "pendiente" and bool(cfg.get("talonario")) and f["adheridos"] > 0
                            and bool(RA.meses_justos(f["importe"], f["cuota_grupo"])))
        else:
            f["sugerido"], f["en_lote"] = [], False
    return filas, excedido, cfg


@ben_conv_bp.route("/recibos")
def recibos():
    salida = _guardia(URL_RECIBOS)
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            conv = _base(cur)
            faltan = FR.falta_esquema(cur) if conv else []
            if not conv or faltan:
                if faltan:
                    FR._aviso_esquema(faltan)
                return render_template("beneficios/recibos.html", conv=None, cuentas=[], cuenta=None, filas=[],
                                       desde=None, hasta=None, id_cuenta=None, res={}, estados=FR.ESTADOS,
                                       excedido=False, tope=FR.TOPE, cfg=None)
            cuentas = FR._cuentas_banco(cur)
            id_cuenta = request.args.get("cuenta", type=int) or (cuentas[0]["id"] if cuentas else None)
            cuenta = next((c for c in cuentas if c["id"] == id_cuenta), None)
            desde, hasta = FR._rango(cur, request.args)
            filas, excedido, cfg = acreditaciones(cur, conv, id_cuenta, desde, hasta) if cuenta else ([], False, None)
    res = {"cant": len(filas), "total": sum((f["importe"] for f in filas), Decimal("0"))}
    for k in FR.ESTADOS:
        sel = [f for f in filas if f["estado"] == k]
        res[k] = (len(sel), sum((f["importe"] for f in sel), Decimal("0")))
    sel = [f for f in filas if f["en_lote"]]
    res["lote"] = (len(sel), sum((f["importe"] for f in sel), Decimal("0")))
    sel = [f for f in filas if f["estado"] in FR.EMITIBLES and not f["adheridos"]]
    res["sin_nomina"] = (len(sel), sum((f["importe"] for f in sel), Decimal("0")))
    return render_template("beneficios/recibos.html", conv=conv, cuentas=cuentas, cuenta=cuenta, id_cuenta=id_cuenta,
                           filas=filas, desde=desde, hasta=hasta, res=res, estados=FR.ESTADOS, emitibles=FR.EMITIBLES,
                           excedido=excedido, tope=FR.TOPE, cfg=cfg)


@ben_conv_bp.route("/recibos/emitir/<int:id_extracto>", methods=["GET", "POST"])
def emitir_uno(id_extracto):
    salida = _guardia(URL_RECIBOS)
    if salida:
        return salida
    errores: list[str] = []
    volver = url_for("ben_conv.recibos", cuenta=request.values.get("cuenta") or None,
                     desde=request.values.get("desde") or None, hasta=request.values.get("hasta") or None)
    with get_connection() as conn:
        with conn.cursor() as cur:
            conv = _base(cur)
            if not conv:
                return redirect(url_for("ben_conv.recibos"))
            cur.execute("""SELECT e.*, c.nombre AS cuenta, c.numero_de_cuenta
                             FROM c_extractos_bancarios e JOIN c_cuentas_de_fondos c ON c.id = e.c_cuentas_de_fondos_id
                            WHERE e.id = %s""", (id_extracto,))
            e = cur.fetchone()
            if not e:
                flash("!No existe ese renglón del extracto.")
                return redirect(volver)
            ya = FR.emitidos_de(cur, [e["id"]]).get(e["id"])
            if ya:
                flash(f"!Esa acreditación ya tiene el recibo {ya['nro_recibo'] or ya['nro_orden']}.")
                return redirect(url_for("fisca_rec.recibo", id_orden=ya["id_orden"]))
            pagador = FR.digitos(e["cuit"])
            afi = RA.afiliado(cur, pagador)
            if not afi:
                flash(f"!El CUIT {pagador or '—'} no es de un afiliado del padrón: se emite en Fiscalización › Emisión de Recibos.")
                return redirect(volver)
            cfg = config_recibo(cur, conv)
            if not cfg:
                flash(f"!Falta correr {RA.SQL_ESQUEMA}.")
                return redirect(volver)
            cur.execute("SELECT COALESCE(NULLIF(cuil_titular, ''), cuil) AS t FROM p_afiliados WHERE id_afiliado = %s",
                        (afi["id_afiliado"],))
            tit = cur.fetchone()["t"]
            nomina, pre = adheridos(cur, conv["id"]), precios(cur, conv["id"])
            mes = e["fecham"].strftime("%Y%m")
            cuota_g, n_adh = cuota_del_grupo(nomina, pre, tit, mes)
            cfg["cuota"] = cuota_g
            cubierta = RA.cubierta(e["fecham"], RA.ordenes_aeda(cur, e["c_cuentas_de_fondos_id"], cfg["motivo"],
                                                                e["fecham"], e["fecham"]))
            fila = {"id": e["id"], "ref_nro": e["ref_nro"], "fecham": e["fecham"], "importe": FR._d(e["credito"]),
                    "cuits": {pagador}, "estado": "pendiente", "recibo": None}
            FR.emparejar([fila], {}, FR.libro_ingresos(cur, e["c_cuentas_de_fondos_id"], e["fecham"], e["fecham"]))
            cur.execute("SELECT 1 FROM conciliacion_items WHERE id_extracto = %s LIMIT 1", (e["id"],))
            conciliado = bool(e["conciliado"] or cur.fetchone())
    renglones = RA.periodos(e["credito"], e["fecham"], cuota_g)
    obs = ""
    if request.method == "POST" and request.form.get("accion") == "emitir_afiliado":
        obs = " ".join((request.form.get("observaciones") or "").split())[:250]
        renglones, errores = RA.leer_renglones(request.form)
        if cubierta:
            errores.append(f"AEDA ya registró esta acreditación en su orden {cubierta['nro_orden']}.")
        if not errores:
            conn = get_connection()
            try:
                conn.begin()
                with conn.cursor() as cur:
                    r = RA.emitir(cur, FR._extracto_bloqueado(cur, id_extracto), pagador, renglones, _uid(), cfg,
                                  obs or None, fecha_valida=FR._fecha_valida)
                conn.commit()
            except FR.ERRORES as ex:
                conn.rollback()
                errores.append(str(ex))
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            if not errores:
                flash(f"Recibo {r['nro']} emitido a {r['razon']} por {FR.pesos(r['total'])} ({cfg['concepto']})."
                      + (f" Quedó conciliado en la conciliación {FR.periodo_txt(r['conciliado'])}." if r["conciliado"] else ""))
                return redirect(url_for("fisca_rec.recibo", id_orden=r["id_orden"]))
    if not n_adh:
        errores = errores or []
        flash(f"!Nadie del grupo de {afi['apellido_nombres']} está en la nómina de {RA.periodo_txt(mes)}: revisá si "
              "corresponde agregarlo antes de emitir.")
    return render_template("fisca/recibo_emitir.html", e=e, errores=errores, modo_afiliado=True, afi=afi, cfg=cfg,
                           cubierta=cubierta, renglones=renglones, obs=obs, fila=fila, conciliado=conciliado,
                           pagador=pagador, mes_max=RA.periodo_txt(RA.sumar_meses(mes, RA.MAX_MESES - 1)),
                           hoy=datetime.date.today().strftime("%Y-%m"), volver=volver, como=FR.COMO,
                           estados=FR.ESTADOS, sugerido={}, elegido="", razon=None, saldos={}, sin_liq={},
                           periodos=[], recordar=False, acuerdos=[], acuerdo=None, est=None, imput={},
                           capital=None, interes=None, estados_cuota=FR.ESTADOS_CUOTA,
                           periodo_mes=FR.periodo_anterior(e["fecham"]), beneficios=True, n_adheridos=n_adh)


@ben_conv_bp.route("/recibos/emitir_lote", methods=["POST"])
def emitir_lote():
    """Los tildados, con lo sugerido; se vuelve a calcular todo en el servidor.
    Solo entran los que siguen sin recibo, con adheridos en la nómina y N cuotas justas."""
    salida = _guardia(URL_RECIBOS)
    if salida:
        return salida
    id_cuenta = request.form.get("cuenta", type=int)
    volver = redirect(url_for("ben_conv.recibos", cuenta=id_cuenta, desde=request.form.get("desde") or None,
                              hasta=request.form.get("hasta") or None))
    ids = {int(x) for x in request.form.getlist("extracto") if x.isdigit()}
    if not ids:
        flash("!Tildá al menos una acreditación.")
        return volver
    if len(ids) > FR.MAX_LOTE:
        flash(f"!Se emiten hasta {FR.MAX_LOTE} recibos de una vez.")
        return volver
    with get_connection() as conn:
        with conn.cursor() as cur:
            conv = _base(cur)
            if not conv:
                return volver
            cur.execute("SELECT MIN(fecham) AS d, MAX(fecham) AS h FROM c_extractos_bancarios "
                        f"WHERE c_cuentas_de_fondos_id = %s AND id IN ({','.join(['%s'] * len(ids))})", [id_cuenta, *ids])
            r = cur.fetchone() or {}
            if not r.get("d"):
                flash("!Esas acreditaciones no son de la cuenta elegida.")
                return volver
            filas, _, cfg = acreditaciones(cur, conv, id_cuenta, r["d"], r["h"])
    uid = _uid()
    hechos, total, saltados, fallados = 0, Decimal("0"), 0, []
    for f in [f for f in filas if f["id"] in ids]:
        if not f["en_lote"] or not f["sugerido"]:
            saltados += 1
            continue
        conn = get_connection()
        try:
            conn.begin()
            with conn.cursor() as cur:
                RA.emitir(cur, FR._extracto_bloqueado(cur, f["id"]), FR.digitos(f["cuit"]), f["sugerido"], uid, cfg,
                          fecha_valida=FR._fecha_valida)
            conn.commit()
            hechos += 1
            total += f["importe"]
        except FR.ERRORES as ex:
            conn.rollback()
            fallados.append(f"{f['fecham']:%d/%m} {FR.pesos(f['importe'])}: {ex}")
        except Exception:
            conn.rollback()
            log.exception("Recibo de adherido del extracto %s", f["id"])
            fallados.append(f"{f['fecham']:%d/%m} {FR.pesos(f['importe'])}: no se pudo emitir")
        finally:
            conn.close()
    if hechos:
        flash(f"{hechos} recibo(s) emitidos por {FR.pesos(total)}.")
    if saltados:
        flash(f"!{saltados} no se emitieron: ya tienen recibo, el grupo no está en la nómina o el importe no es un número "
              "justo de cuotas. Se emiten de a uno.")
    for t in fallados[:10]:
        flash("!" + t)
    return volver
