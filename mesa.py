"""
mesa.py — Mesa de entradas: los expedientes de los comprobantes de proveedores.

Portado de gestion_adm (mesa_entradas.py). Cada comprobante cargado abre un
expediente (EXP-AAAA-NNNNNN) que recorre la mesa —derivaciones, observaciones,
aprobación o rechazo— y deja cada paso en `me_expediente_movimientos`.

    ingresado → en revisión → aprobado / rechazado → (auditoría) liquidado → pagado
                                    archivado · anulado

Liquidado y pagado los pone el circuito contable (auditoría de comprobantes,
pagos): desde la mesa ya no se cambian; los movimientos siguen quedando en la
historia (gestion_adm, igual).

Diferencias con gestion_adm:
  · `mover` controla la sesión, el permiso y los datos que exige cada
    movimiento (una derivación sin destino, un rechazo sin motivo). Allá
    cualquier POST pasaba.
  · Anular está acá, con las mismas reglas que en la auditoría de gestion_adm:
    solo con la liquidación abierta y fuera de órdenes de pago.
  · Sin Integración, documentación de la Res. 1743, FACOEP ni trazabilidad.

Permiso: la opción de menú «Mesa de Entradas» (/mesa).
"""
from __future__ import annotations

import io
import json
import logging
from datetime import datetime

import pymysql
from flask import (Blueprint, flash, redirect, render_template, request, send_file,
                   session, url_for)

import comprobantes_datos as cd
import paginar
from exportar import xlsx
from db import get_connection, puede, validasesion

log = logging.getLogger(__name__)

mesa_bp = Blueprint("mesa", __name__, url_prefix="/mesa")


def puede_mesa() -> bool:
    return puede(url_for("mesa.bandeja"))


def _guardia():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede_mesa():
        flash("!No tenés permiso para la mesa de entradas.")
        return redirect(url_for("menu"))
    return None


def _areas_usuarios(cur) -> tuple[list, list]:
    cur.execute("SELECT id, nombre, nivel FROM s_areas WHERE activo = 1 ORDER BY nivel, nombre")
    areas = cur.fetchall()
    cur.execute("""SELECT u.id, u.nombre, u.email, GROUP_CONCAT(au.area_id) AS areas
                     FROM s_usuarios u LEFT JOIN s_area_usuario au ON au.usuario_id = u.id
                    WHERE u.activo = 1 GROUP BY u.id, u.nombre, u.email ORDER BY u.nombre""")
    return areas, cur.fetchall()


# =============================================================================
# Bandeja
#
# La de gestion_adm (mesa_entradas.bandeja, pedido del 11/11/2026): mismas
# columnas, filtros y tarjetas, paginada en el servidor (paginar.py) como allá.
# Antes mandaba todos los expedientes y filtraba en el navegador.
# =============================================================================

#: Una nota de crédito resta en el total: lo decide el tipo, no el signo (la
#: regla de comprobantes_datos.es_credito y de la cuenta corriente).
SQL_ES_CREDITO = "COALESCE(tc.descripcion REGEXP 'nota.*cr[eé]dito', 0)"

SQL_BANDEJA_FROM = """
      FROM me_expedientes e
      LEFT JOIN s_areas a ON a.id = e.id_area_destino
      LEFT JOIN s_usuarios u ON u.id = e.id_usuario_destino
      LEFT JOIN c_proveedores p ON p.id = e.id_proveedor
      LEFT JOIN f_comprobantes_arca c ON c.id = e.id_comprobante
      LEFT JOIN arca_tipo_comprobante tc ON tc.codigo = LPAD(c.tipo_comprobante, 3, '0')
"""

# Columna de la grilla → ORDER BY. ?orden= se busca acá, nunca va al SQL.
ORDEN_BANDEJA = {
    "expediente": "e.id",
    "proveedor":  "e.razon_social_emisor",
    "fecha":      "e.creado",
    "importe":    "e.importe_total",
    "estado":     "e.estado",
}

_DIR_DEFAULT = {"expediente": "desc", "fecha": "desc", "importe": "desc"}


def _fecha_iso(valor) -> str:
    v = (valor or "").strip()
    return v if len(v) == 10 and v[4] == "-" and v[7] == "-" and v.replace("-", "").isdigit() else ""


def _filtros_bandeja(args) -> dict:
    """Los filtros, leídos en un solo lugar: la grilla y la planilla tienen que
    mostrar exactamente lo mismo."""
    estados = {k for k, _ in cd.ESTADOS if k != "reintegro"}
    orden = args.get("orden") if args.get("orden") in ORDEN_BANDEJA else "expediente"
    return {
        "q":       (args.get("q") or "").strip()[:100],
        "estado":  args.get("estado") if args.get("estado") in estados else "",
        "area":    args.get("area_id") if (args.get("area_id") or "").isdigit() else "",
        "usuario": args.get("usuario_id") if (args.get("usuario_id") or "").isdigit() else "",
        "desde":   _fecha_iso(args.get("fecha_desde")),
        "hasta":   _fecha_iso(args.get("fecha_hasta")),
        "orden":   orden,
        # Sin ?dir=, lo más nuevo primero en Expediente y Fecha; el resto, A→Z.
        "dir":     args.get("dir") if args.get("dir") in ("asc", "desc") else _DIR_DEFAULT.get(orden, "asc"),
        "tam":     paginar.tamano(args.get("tam")),
        "pagina":  paginar.pagina(args.get("pagina")),
    }


def _args_bandeja(f: dict) -> dict:
    """Los filtros como van en la URL (los enlaces de página y la exportación)."""
    return {"q": f["q"] or None, "estado": f["estado"] or None,
            "area_id": f["area"] or None, "usuario_id": f["usuario"] or None,
            "fecha_desde": f["desde"] or None, "fecha_hasta": f["hasta"] or None,
            "orden": None if f["orden"] == "expediente" else f["orden"],
            "dir": None if f["dir"] == _DIR_DEFAULT.get(f["orden"], "asc") else f["dir"],
            "tam": None if f["tam"] == paginar.TAMANO_DEFAULT else f["tam"]}


def _hay_filtros(f: dict) -> bool:
    return bool(f["q"] or f["estado"] or f["area"] or f["usuario"] or f["desde"] or f["hasta"])


def _where_bandeja(f: dict) -> tuple[str, list]:
    # Los reintegros de AEDA (estado «reintegro», sin proveedor) no pasan por
    # la mesa: se ven en Reintegros (pedido del 11/11/2026). El expediente se
    # sigue abriendo por su enlace (/mesa/<id>).
    cond, params = ["e.estado <> 'reintegro'"], []
    if f["estado"]:
        cond.append("e.estado = %s"); params.append(f["estado"])
    if f["area"]:
        cond.append("e.id_area_destino = %s"); params.append(int(f["area"]))
    if f["usuario"]:
        cond.append("e.id_usuario_destino = %s"); params.append(int(f["usuario"]))
    if f["q"]:
        like = f"%{f['q']}%"
        cond.append("(e.nro_expediente LIKE %s OR e.razon_social_emisor LIKE %s "
                    "OR e.cuit_emisor LIKE %s OR p.nombre_fantasia LIKE %s "
                    "OR c.numero_completo LIKE %s)")
        params += [like] * 5
    # `creado` es datetime: el «hasta» va hasta el último segundo del día.
    if f["desde"]:
        cond.append("e.creado >= %s"); params.append(f["desde"] + " 00:00:00")
    if f["hasta"]:
        cond.append("e.creado <= %s"); params.append(f["hasta"] + " 23:59:59")
    return "WHERE " + " AND ".join(cond), params


def _consultar_bandeja(cur, f: dict, paginado=True) -> tuple[list, dict]:
    """(expedientes, totales) con los filtros de `f`. Sin `paginado`, todos
    (la exportación)."""
    where, params = _where_bandeja(f)
    cur.execute(f"""
        SELECT COUNT(*) AS n,
               COALESCE(SUM(CASE WHEN {SQL_ES_CREDITO} THEN -1 ELSE 1 END
                            * COALESCE(e.importe_total, 0)), 0) AS importe
        {SQL_BANDEJA_FROM} {where}
    """, params)
    totales = cur.fetchone()

    col = ORDEN_BANDEJA[f["orden"]]
    sentido = "DESC" if f["dir"] == "desc" else "ASC"
    limite = ""
    if paginado:
        paginas = max(1, -(-totales["n"] // f["tam"]))
        offset = (min(f["pagina"], paginas) - 1) * f["tam"]
        limite = f"LIMIT {int(f['tam'])} OFFSET {int(offset)}"
    cur.execute(f"""
        SELECT e.*, a.nombre AS nombre_area, u.nombre AS nombre_usuario,
               p.nombre_fantasia, c.numero_completo, c.fecha_emision,
               c.tipo_comprobante AS cbte_tipo_codigo, tc.descripcion AS cbte_tipo_desc,
               c.constatacion_resultado, c.leido_automatico, c.verificado_visual
        {SQL_BANDEJA_FROM} {where}
        ORDER BY {col} IS NULL, {col} {sentido}, e.id DESC
        {limite}
    """, params)
    return cur.fetchall(), totales


@mesa_bp.route("")
def bandeja():
    g = _guardia()
    if g:
        return g
    f = _filtros_bandeja(request.args)
    with get_connection() as conn:
        with conn.cursor() as cur:
            expedientes, totales = _consultar_bandeja(cur, f)
            areas, usuarios = _areas_usuarios(cur)
    args = _args_bandeja(f)
    return render_template(
        "mesa/bandeja.html", expedientes=expedientes, total=totales, f=f, areas=areas,
        usuarios=usuarios, hay_filtros=_hay_filtros(f), args_export=args,
        pag=paginar.paginador(totales["n"], f["pagina"], f["tam"], "mesa.bandeja", args),
        estados=[e for e in cd.ESTADOS if e[0] != "reintegro"],
        estados_label=cd.ESTADOS_LABEL, estados_tipo=cd.ESTADOS_TIPO,
        puede_cargar=puede(url_for("comprobantes.carga")))


@mesa_bp.route("/exportar")
def exportar():
    """La bandeja en planilla, con los mismos filtros y todo el resultado."""
    g = _guardia()
    if g:
        return g
    f = _filtros_bandeja(request.args)
    with get_connection() as conn:
        with conn.cursor() as cur:
            filas, _tot = _consultar_bandeja(cur, f, paginado=False)

    # El comprobante en dos columnas (tipo y número): en una planilla, junto
    # no se puede filtrar ni ordenar por tipo (lo mismo que gestion_adm).
    columnas = [{"titulo": t, "tipo": tp} for t, tp in [
        ("Expediente", "t"), ("Fecha", ""), ("Tipo comprobante", ""), ("Comprobante", "t"),
        ("Emisión", ""), ("CUIT", "t"), ("Razón social", ""), ("Nombre fantasía", ""),
        ("Importe", "n"), ("Área destino", ""), ("Usuario destino", ""), ("Estado", ""),
        ("Asunto", "")]]
    datos = [[
        r["nro_expediente"] or "",
        r["creado"].strftime("%d/%m/%Y") if r["creado"] else "",
        r["cbte_tipo_desc"] or "", r["numero_completo"] or "",
        r["fecha_emision"].strftime("%d/%m/%Y") if r["fecha_emision"] else "",
        r["cuit_emisor"] or "", r["razon_social_emisor"] or "", r["nombre_fantasia"] or "",
        f"{float(r['importe_total'] or 0):.2f}".replace(".", ","),
        r["nombre_area"] or "", r["nombre_usuario"] or "",
        cd.ESTADOS_LABEL.get(r["estado"], r["estado"] or ""), r["asunto"] or "",
    ] for r in filas]
    nombre = "Mesa de entradas"
    if f["desde"] or f["hasta"]:
        nombre += f" {f['desde'] or 'inicio'} a {f['hasta'] or 'hoy'}"
    return send_file(
        io.BytesIO(xlsx(nombre, columnas, datos)),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True, download_name=f"Mesa_de_entradas_{datetime.now():%Y%m%d_%H%M}.xlsx")


@mesa_bp.route("/<int:exp_id>")
def detalle(exp_id):
    g = _guardia()
    if g:
        return g
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT e.*, a.nombre AS area, u.nombre AS usuario_destino, uc.nombre AS usuario_carga,
                       ua.nombre AS usuario_anulacion
                  FROM me_expedientes e
                  LEFT JOIN s_areas a ON a.id = e.id_area_destino
                  LEFT JOIN s_usuarios u ON u.id = e.id_usuario_destino
                  LEFT JOIN s_usuarios uc ON uc.id = e.usuario_creacion
                  LEFT JOIN s_usuarios ua ON ua.id = e.id_usuario_anulacion
                 WHERE e.id = %s""", (exp_id,))
            exp = cur.fetchone()
            if not exp:
                flash("!El expediente no existe.")
                return redirect(url_for("mesa.bandeja"))
            comp = prov = None
            if exp["id_comprobante"]:
                cur.execute("""SELECT c.*, tc.descripcion AS tipo_desc, u.nombre AS usuario_carga
                                 FROM f_comprobantes_arca c
                                 LEFT JOIN arca_tipo_comprobante tc ON tc.codigo = LPAD(c.tipo_comprobante, 3, '0')
                                 LEFT JOIN s_usuarios u ON u.id = c.usuario_id
                                WHERE c.id = %s""", (exp["id_comprobante"],))
                comp = cur.fetchone()
            if exp["id_proveedor"]:
                cur.execute("""SELECT p.id, p.cuit, p.razon_social, p.nombre_fantasia, p.activo, p.cbu,
                                      p.cbu_alias, rt.descripcion AS condicion_iva
                                 FROM c_proveedores p
                                 LEFT JOIN arca_responsable_tipo rt ON rt.codigo = p.condicion_iva
                                WHERE p.id = %s""", (exp["id_proveedor"],))
                prov = cur.fetchone()
            cur.execute("""
                SELECT l.*, r.nombre AS rubro,
                       (SELECT GROUP_CONCAT(g.descripcion SEPARATOR ', ')
                          FROM c_pasivo_liquidacion_detalle d
                          JOIN c_concepto_de_gastos g ON g.id = d.id_concepto_liquidacion
                         WHERE d.id_pasivo_liquidacion = l.id) AS conceptos
                  FROM c_pasivo_liquidacion l
                  LEFT JOIN c_rubros_de_pasivo r ON r.id = l.id_rubro_pasivo
                 WHERE l.id_expediente = %s ORDER BY l.id""", (exp_id,))
            liquidaciones = cur.fetchall()
            cur.execute("""
                SELECT m.*, u.nombre AS usuario, a.nombre AS area, ud.nombre AS usuario_destino
                  FROM me_expediente_movimientos m
                  LEFT JOIN s_usuarios u ON u.id = m.usuario_id
                  LEFT JOIN s_areas a ON a.id = m.id_area_destino
                  LEFT JOIN s_usuarios ud ON ud.id = m.id_usuario_destino
                 WHERE m.id_expediente = %s ORDER BY m.fecha DESC, m.id DESC""", (exp_id,))
            movimientos = cur.fetchall()
            cambiar_pdf, motivo_pdf = cd.puede_cambiar_pdf(cur, exp_id)
            no_anular = cd.motivos_para_no_anular(cur, exp_id)
            areas, usuarios = _areas_usuarios(cur)
            cst_obs = None
            if comp and comp.get("constatacion_obs"):
                try:
                    o = json.loads(comp["constatacion_obs"])
                    cst_obs = (o.get("detalle") if isinstance(o, dict)
                               else " · ".join(x.get("msg", "") for x in o if isinstance(x, dict)))
                except (ValueError, TypeError):
                    cst_obs = str(comp["constatacion_obs"])
    return render_template("mesa/detalle.html", e=exp, c=comp, prov=prov, liquidaciones=liquidaciones,
                           movimientos=movimientos, cambiar_pdf=cambiar_pdf, motivo_pdf=motivo_pdf,
                           no_anular=no_anular, areas=areas, usuarios=usuarios, cst_obs=cst_obs,
                           tipos_mov=cd.TIPOS_MOV, tipos_mov_label=cd.TIPOS_MOV_LABEL,
                           estados_label=cd.ESTADOS_LABEL, estados_tipo=cd.ESTADOS_TIPO,
                           contables=cd.ESTADOS_CONTABLES)


@mesa_bp.route("/<int:exp_id>/mover", methods=["POST"])
def mover(exp_id):
    g = _guardia()
    if g:
        return g
    f = request.form
    tipo = (f.get("tipo") or "").strip()
    with get_connection() as conn:
        with conn.cursor() as cur:
            conn.begin()
            try:
                err = cd.mover(cur, exp_id, tipo, (f.get("observaciones") or "").strip()[:2000] or None,
                               f.get("id_area", type=int), f.get("id_usuario", type=int),
                               session.get("sind_usuario_id"))
                if err:
                    conn.rollback()
                else:
                    conn.commit()
            except pymysql.MySQLError as e:
                conn.rollback()
                log.exception("Movimiento del expediente %s", exp_id)
                err = f"No se pudo registrar: {e}"
    flash("!" + err if err else f"Movimiento registrado: {cd.TIPOS_MOV_LABEL.get(tipo, tipo)}.")
    return redirect(url_for("mesa.detalle", exp_id=exp_id))


@mesa_bp.route("/<int:exp_id>/anular", methods=["POST"])
def anular(exp_id):
    g = _guardia()
    if g:
        return g
    with get_connection() as conn:
        with conn.cursor() as cur:
            conn.begin()
            err = cd.anular(cur, exp_id, request.form.get("motivo"), session.get("sind_usuario_id"))
            if err:
                conn.rollback()
            else:
                conn.commit()
    flash("!" + err if err else "Expediente anulado. Queda registrado con el motivo: no se borró nada.")
    return redirect(url_for("mesa.detalle", exp_id=exp_id))


@mesa_bp.route("/<int:exp_id>/pdf", methods=["POST"])
def subir_pdf(exp_id):
    """Adjunta el PDF que faltaba o reemplaza el equivocado (mientras la
    liquidación esté abierta y el que hay no se haya confirmado)."""
    g = _guardia()
    if g:
        return g
    archivo = request.files.get("pdf")
    contenido = archivo.read() if archivo and archivo.filename else b""
    if not contenido.startswith(b"%PDF"):
        flash("!Elegí un archivo PDF.")
        return redirect(url_for("mesa.detalle", exp_id=exp_id))
    if len(contenido) > 15 * 1024 * 1024:
        flash("!El PDF pasa de 15 MB.")
        return redirect(url_for("mesa.detalle", exp_id=exp_id))
    with get_connection() as conn:
        with conn.cursor() as cur:
            ok, motivo = cd.puede_cambiar_pdf(cur, exp_id)
            if not ok:
                flash("!No se puede cambiar el PDF: " + motivo)
                return redirect(url_for("mesa.detalle", exp_id=exp_id))
            cur.execute("""SELECT c.* FROM me_expedientes e JOIN f_comprobantes_arca c ON c.id = e.id_comprobante
                            WHERE e.id = %s""", (exp_id,))
            c = cur.fetchone()
            ficha = cd.guardar_tmp(contenido)
            tmp = cd.ruta_tmp(ficha)
            habia = bool(c["ruta_local"])
            try:
                rel = cd.archivar_pdf(tmp, c["fecha_emision"], cd.nombre_pdf(
                    c["cuit_emisor"], c["tipo_comprobante"], c["punto_de_venta"], c["numero"]))
            finally:
                tmp.unlink(missing_ok=True)
            leido, obs = cd.cotejar(cd.ruta_real(rel), c)
            conn.begin()
            cur.execute("""UPDATE f_comprobantes_arca SET nombre_archivo = %s, ruta_local = %s,
                                  leido_automatico = %s, verificado_visual = 0 WHERE id = %s""",
                        (rel.rsplit("/", 1)[-1], rel, 1 if leido else 0, c["id"]))
            cd.movimiento(cur, exp_id, "pdf", _estado(cur, exp_id), session.get("sind_usuario_id"),
                          ("Se reemplazó el PDF del comprobante: " if habia else "Se adjuntó el PDF del comprobante: ")
                          + archivo.filename[:150] + (" (coincide con los datos)" if leido else " (no se pudo cotejar)"))
            conn.commit()
    flash(("PDF reemplazado." if habia else "PDF adjuntado.")
          + (" Coincide con los datos del comprobante." if leido else ""))
    if obs:
        flash("!" + obs)
    return redirect(url_for("mesa.detalle", exp_id=exp_id))


def _estado(cur, exp_id) -> str:
    cur.execute("SELECT estado FROM me_expedientes WHERE id = %s", (exp_id,))
    return cur.fetchone()["estado"]
