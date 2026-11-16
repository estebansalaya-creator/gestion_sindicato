"""
recibos_emitidos.py — Tesorería › Recibos Emitidos (/tesoreria/recibos).

Pedido del 15/11/2026: «en tesorería agregar recibos emitidos», como en
gestion_adm (recibos_emitidos.py: la consulta de lo cobrado, al lado de la
emisión). Acá son los recibos del sindicato: las órdenes de ingreso con número
de talonario (recibos_talonario.py), de cuota sindical y de fiscalización, los
emitidos en el sistema y los que vinieron de AEDA (talonarios X 0091 y X 0092), y
los recibos a afiliados por la cuota social YMCA (X 0003, recibos_afiliado.py).

Se emiten en Fiscalización de Cuotas › Emisión de Recibos (fisca_recibos.py) y
se anulan en Tesorería › Anulaciones. Esta pantalla mira para atrás: buscar un
recibo, verlo, imprimirlo y bajar la lista a Excel. A diferencia de gestion_adm
no manda el recibo por mail: el sistema no envía correo.

    /tesoreria/recibos            la grilla, paginada en el servidor (son más de 10.000)
    /tesoreria/recibos/exportar   la planilla, con los mismos filtros y todo el resultado

El recibo se abre en su ficha (fisca_rec.recibo, con su PDF), que también
acepta a quien tiene esta pantalla aunque no tenga la de emisión.

APLICADO: lo que el recibo ya canceló de deuda. Uno de cuota sindical, lo
aplicado a las cuotas liquidadas (`fisca_aplicacion`, por sus renglones); uno
de fiscalización, lo imputado a las cuotas de su acuerdo de pago
(`fisca_acuerdo_imputacion`). Lo que falta queda a favor del empleador. Uno al
afiliado no se aplica a nada: cuenta como aplicado del todo.

Sin sql/recibos_afiliados_20261115.sql no hay `cuil_afiliado`: la consulta usa
NULL en su lugar (`_sql_from`).
"""

from __future__ import annotations

import io
import re
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for

import paginar
from db import get_connection, puede, validasesion
from exportar import xlsx

rec_emi_bp = Blueprint("rec_emi", __name__, url_prefix="/tesoreria")

URL = "/tesoreria/recibos"
CLASES = {"cuota_sindical": "Cuota sindical", "fiscalizacion": "Fiscalización", "afiliado": "Afiliado (cuota social)"}
ESTADOS = {"vigente": "Vigentes", "anulado": "Anulados", "todos": "Todos"}
APLICACION = {"sin_aplicar": "Sin aplicar", "con_saldo": "Con saldo sin aplicar", "aplicado": "Aplicados del todo"}

#: Un renglón por recibo. Los renglones del recibo se resumen en `d` (el CUIT
#: del empleador y los períodos) y lo aplicado en `ap` / `ai`: agrupados una
#: vez por consulta y no una subconsulta por renglón.
SQL_FROM = """
      FROM ingreso_ordenes o
      JOIN c_talonario t ON t.id = o.id_talonario
      LEFT JOIN p_afiliados af ON af.cuil = {cuil_afiliado} AND af.cuil IS NOT NULL
      LEFT JOIN (SELECT id_orden, MIN(cuit) AS cuit, MIN(periodo) AS p_desde, MAX(periodo) AS p_hasta,
                        COUNT(DISTINCT periodo) AS n_per
                   FROM ingreso_ordenes_detalle GROUP BY id_orden) d ON d.id_orden = o.id
      LEFT JOIN p_empresas e ON e.CUIT = CAST(d.cuit AS UNSIGNED)
      LEFT JOIN fisca_acta ac ON ac.id = o.id_acta
      LEFT JOIN c_cuentas_de_fondos cf ON cf.id = o.id_cuenta
      LEFT JOIN (SELECT dd.id_orden, SUM(a.importe) AS aplicado
                   FROM fisca_aplicacion a JOIN ingreso_ordenes_detalle dd ON dd.id = a.id_detalle
                  GROUP BY dd.id_orden) ap ON ap.id_orden = o.id
      LEFT JOIN (SELECT id_orden, SUM(importe) AS aplicado
                   FROM fisca_acuerdo_imputacion GROUP BY id_orden) ai ON ai.id_orden = o.id
"""
SQL_APLICADO = ("(CASE WHEN o.clase = 'fiscalizacion' THEN COALESCE(ai.aplicado, 0) "
                "WHEN o.clase = 'afiliado' THEN o.importe_total ELSE COALESCE(ap.aplicado, 0) END)")
SQL_RAZON = "COALESCE(e.razon_social, ac.razon_social, af.apellido_nombres)"
_TIENE_CUIL: dict = {}


def _sql_from(cur) -> str:
    """SQL_FROM con el CUIL del afiliado, o NULL si falta el script."""
    if not _TIENE_CUIL.get("v"):         # una vez que está, no se vuelve a preguntar
        cur.execute("""SELECT COUNT(*) AS n FROM information_schema.columns WHERE table_schema = DATABASE()
                         AND table_name = 'ingreso_ordenes' AND column_name = 'cuil_afiliado'""")
        _TIENE_CUIL["v"] = bool(cur.fetchone()["n"])
    return SQL_FROM.replace("{cuil_afiliado}", "o.cuil_afiliado" if _TIENE_CUIL["v"] else "NULL")

# Columna de la grilla → ORDER BY. ?orden= se busca acá, nunca va al SQL.
ORDEN = {
    "fecha":    "o.fecha",
    "recibo":   "t.punto_de_venta {dir}, o.nro_recibo",
    "empleador": SQL_RAZON,
    "importe":  "o.importe_total",
}
_DIR_DEFAULT = {"fecha": "desc", "recibo": "desc", "importe": "desc"}


def _fecha_iso(valor) -> str:
    v = (valor or "").strip()
    return v if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) else ""


def leer_filtros(args) -> dict:
    """Los filtros, leídos en un solo lugar: la grilla y la planilla muestran lo mismo."""
    orden = args.get("orden") if args.get("orden") in ORDEN else "fecha"
    return {
        "q":          (args.get("q") or "").strip()[:100],
        # Número de recibo exacto: «123», «0091-00000123» o «X 0091-00000123».
        "nro":        (args.get("nro") or "").strip()[:30],
        "desde":      _fecha_iso(args.get("desde")),
        "hasta":      _fecha_iso(args.get("hasta")),
        "clase":      args.get("clase") if args.get("clase") in CLASES else "",
        "talonario":  args.get("talonario") if (args.get("talonario") or "").isdigit() else "",
        "cuenta":     args.get("cuenta") if (args.get("cuenta") or "").isdigit() else "",
        "aplicacion": args.get("aplicacion") if args.get("aplicacion") in APLICACION else "",
        "estado":     args.get("estado") if args.get("estado") in ESTADOS else "vigente",
        "orden":      orden,
        "dir":        args.get("dir") if args.get("dir") in ("asc", "desc") else _DIR_DEFAULT.get(orden, "asc"),
        "tam":        paginar.tamano(args.get("tam")),
        "pagina":     paginar.pagina(args.get("pagina")),
    }


def args_url(f: dict) -> dict:
    """Los filtros como van en la URL (los enlaces de página y la exportación)."""
    return {"q": f["q"] or None, "nro": f["nro"] or None, "desde": f["desde"] or None, "hasta": f["hasta"] or None,
            "clase": f["clase"] or None, "talonario": f["talonario"] or None, "cuenta": f["cuenta"] or None,
            "aplicacion": f["aplicacion"] or None, "estado": None if f["estado"] == "vigente" else f["estado"],
            "orden": None if f["orden"] == "fecha" else f["orden"],
            "dir": None if f["dir"] == _DIR_DEFAULT.get(f["orden"], "asc") else f["dir"],
            "tam": None if f["tam"] == paginar.TAMANO_DEFAULT else f["tam"]}


def hay_filtros(f: dict) -> bool:
    return bool(f["q"] or f["nro"] or f["desde"] or f["hasta"] or f["clase"] or f["talonario"] or f["cuenta"]
                or f["aplicacion"] or f["estado"] != "vigente")


def where(f: dict) -> tuple[str, list]:
    """El WHERE, compartido por la grilla, los totales y la planilla."""
    cond, params = ["o.id_talonario IS NOT NULL"], []
    # Con número de recibo se busca ESE recibo: los demás filtros no cuentan
    # (ni vigente/anulado), para que aparezca esté como esté.
    if f["nro"]:
        partes = re.findall(r"\d+", f["nro"])
        if not partes:
            cond.append("1 = 0")
        else:
            cond.append("o.nro_recibo = %s"); params.append(int(partes[-1]))
            if len(partes) >= 2:
                cond.append("t.punto_de_venta = %s"); params.append(int(partes[-2]))
        return "WHERE " + " AND ".join(cond), params
    if f["estado"] == "vigente":
        cond.append("o.estado <> 'anulado'")
    elif f["estado"] == "anulado":
        cond.append("o.estado = 'anulado'")
    if f["desde"]:
        cond.append("o.fecha >= %s"); params.append(f["desde"])
    if f["hasta"]:
        cond.append("o.fecha <= %s"); params.append(f["hasta"])
    if f["clase"]:
        cond.append("o.clase = %s"); params.append(f["clase"])
    if f["talonario"]:
        cond.append("o.id_talonario = %s"); params.append(int(f["talonario"]))
    if f["cuenta"]:
        cond.append("o.id_cuenta = %s"); params.append(int(f["cuenta"]))
    # Medio centavo de tolerancia: un recibo aplicado de a centavos no queda «con saldo» por redondeo.
    if f["aplicacion"] == "sin_aplicar":
        cond.append(f"{SQL_APLICADO} < 0.005")
    elif f["aplicacion"] == "con_saldo":
        cond.append(f"o.importe_total - {SQL_APLICADO} > 0.005")
    elif f["aplicacion"] == "aplicado":
        cond.append(f"o.importe_total - {SQL_APLICADO} <= 0.005")
    if f["q"]:
        like = f"%{f['q']}%"
        cuit = re.sub(r"\D", "", f["q"])
        partes = [f"{SQL_RAZON} LIKE %s", "e.nombre_fantasia LIKE %s", "o.nro_orden LIKE %s"]
        params += [like, like, like]
        if len(cuit) >= 4:
            partes.append("(d.cuit LIKE %s OR af.cuil LIKE %s)"); params += [f"%{cuit}%", f"%{cuit}%"]
        cond.append("(" + " OR ".join(partes) + ")")
    return "WHERE " + " AND ".join(cond), params


def consultar(cur, f: dict, paginado: bool = True) -> tuple[list, dict]:
    """(recibos, totales) con los filtros de `f`. Sin `paginado`, todos (la planilla)."""
    w, params = where(f)
    desde_sql = _sql_from(cur)
    cur.execute(f"""
        SELECT COUNT(*) AS n, COALESCE(SUM(o.importe_total), 0) AS importe,
               COALESCE(SUM({SQL_APLICADO}), 0) AS aplicado,
               COALESCE(SUM(o.importe_total - {SQL_APLICADO} > 0.005), 0) AS con_saldo
        {desde_sql} {w}""", params)
    tot = cur.fetchone()
    tot["sin_aplicar"] = (tot["importe"] or 0) - (tot["aplicado"] or 0)

    sentido = "DESC" if f["dir"] == "desc" else "ASC"
    col = ORDEN[f["orden"]].format(dir=sentido)
    limite = ""
    if paginado:
        paginas = max(1, -(-int(tot["n"]) // f["tam"]))
        limite = f"LIMIT {int(f['tam'])} OFFSET {(min(f['pagina'], paginas) - 1) * int(f['tam'])}"
    cur.execute(f"""
        SELECT o.id, o.fecha, o.clase, o.estado, o.importe_total, o.nro_orden, o.origen, o.observaciones,
               o.fecha_anulacion, o.motivo_anulacion,
               CONCAT(t.letra, ' ', LPAD(t.punto_de_venta, 4, '0'), '-', LPAD(o.nro_recibo, 8, '0')) AS numero,
               t.nombre AS talonario, COALESCE(d.cuit, af.cuil) AS cuit, d.p_desde, d.p_hasta, d.n_per,
               {SQL_RAZON} AS razon_social, e.id AS id_empresa, cf.nombre AS cuenta,
               {SQL_APLICADO} AS aplicado, ac.nro_acta
        {desde_sql} {w}
        ORDER BY {col} {sentido}, o.id {sentido}
        {limite}""", params)
    return cur.fetchall(), tot


def _catalogos(cur) -> dict:
    """Los talonarios y las cuentas que tienen recibos, para los filtros."""
    cur.execute("""SELECT t.id, t.nombre, t.letra, t.punto_de_venta FROM c_talonario t
                    WHERE EXISTS (SELECT 1 FROM ingreso_ordenes o WHERE o.id_talonario = t.id)
                    ORDER BY t.punto_de_venta""")
    talonarios = cur.fetchall()
    cur.execute("""SELECT cf.id, cf.nombre FROM c_cuentas_de_fondos cf
                    WHERE EXISTS (SELECT 1 FROM ingreso_ordenes o WHERE o.id_cuenta = cf.id AND o.id_talonario IS NOT NULL)
                    ORDER BY cf.nombre""")
    return {"talonarios": talonarios, "cuentas": cur.fetchall()}


def periodos_txt(r: dict) -> str:
    """«2026-10», o «2026-08 a 2026-10 (3)» si el recibo paga varios meses."""
    def p(v):
        return f"{v[:4]}-{v[4:]}" if v and len(v) == 6 else ""
    if not r.get("p_desde"):
        return ""
    if r["p_desde"] == r["p_hasta"]:
        return p(r["p_desde"])
    return f"{p(r['p_desde'])} a {p(r['p_hasta'])} ({r['n_per']})"


def _guardia():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede(URL):
        flash("!No tenés permiso para los recibos emitidos.")
        return redirect(url_for("menu"))
    return None


@rec_emi_bp.route("/recibos")
def lista():
    salida = _guardia()
    if salida:
        return salida
    f = leer_filtros(request.args)
    with get_connection() as conn:
        with conn.cursor() as cur:
            recibos, tot = consultar(cur, f)
            cat = _catalogos(cur)
    for r in recibos:
        r["periodos"] = periodos_txt(r)
    args = args_url(f)
    return render_template("tesoreria/recibos_emitidos.html", recibos=recibos, tot=tot, f=f, args_export=args,
                           hay_filtros=hay_filtros(f), clases=CLASES, estados=ESTADOS, aplicacion=APLICACION,
                           pag=paginar.paginador(int(tot["n"]), f["pagina"], f["tam"], "rec_emi.lista", args),
                           volver=request.full_path.rstrip("?"),
                           puede_emision=puede("/fiscalizacion/recibos"), puede_anular=puede("/tesoreria/anulaciones"),
                           **cat)


@rec_emi_bp.route("/recibos/exportar")
def exportar():
    """La grilla en planilla, con los mismos filtros y todo el resultado."""
    salida = _guardia()
    if salida:
        return salida
    f = leer_filtros(request.args)
    with get_connection() as conn:
        with conn.cursor() as cur:
            filas, _tot = consultar(cur, f, paginado=False)
    columnas = [{"titulo": t, "tipo": tp} for t, tp in [
        ("Fecha", ""), ("Recibo", "t"), ("Talonario", ""), ("Orden de ingreso", "t"), ("Clase", ""), ("CUIT", "t"),
        ("Empleador", ""), ("Períodos", ""), ("Acta", "t"), ("Cuenta", ""), ("Importe", "n"), ("Aplicado", "n"),
        ("Sin aplicar", "n"), ("Estado", ""), ("Anulado el", ""), ("Motivo de la anulación", "")]]

    def num(v):
        return f"{float(v or 0):.2f}".replace(".", ",")
    datos = [[
        r["fecha"].strftime("%d/%m/%Y") if r["fecha"] else "", r["numero"] or "", r["talonario"] or "",
        r["nro_orden"] or "", CLASES.get(r["clase"], r["clase"] or ""), r["cuit"] or "", r["razon_social"] or "",
        periodos_txt(r), r["nro_acta"] or "", r["cuenta"] or "", num(r["importe_total"]), num(r["aplicado"]),
        num((r["importe_total"] or 0) - (r["aplicado"] or 0)), "Anulado" if r["estado"] == "anulado" else "Vigente",
        r["fecha_anulacion"].strftime("%d/%m/%Y") if r["fecha_anulacion"] else "", r["motivo_anulacion"] or "",
    ] for r in filas]
    nombre = "Recibos emitidos"
    if f["desde"] or f["hasta"]:
        nombre += f" {f['desde'] or 'inicio'} a {f['hasta'] or 'hoy'}"
    return send_file(io.BytesIO(xlsx(nombre, columnas, datos)),
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     as_attachment=True, download_name=f"Recibos_emitidos_{datetime.now():%Y%m%d_%H%M}.xlsx")
