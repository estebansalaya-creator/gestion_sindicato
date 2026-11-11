# =============================================================================
# gestion_sindicato.py
# Fiscalización de cuotas sindicales — blueprint de la aplicación `sindicato`.
#
# Esta aplicación es autónoma: proceso propio, sitio propio en IIS, base propia.
# No importa nada de `gestion_adm` y no toca la base `contable`.
#
#   gestion_sindicato/
#     app.py                  ← entrypoint, registra este blueprint
#     db.py                   ← conexión a la base `sindicato`
#     gestion_sindicato.py    ← este archivo
#     templates/
#       base.html
#       fisca/
#         fisca_dashboard.html
#         fisca_importar_cuotas.html
#         fisca_importaciones_log.html
# =============================================================================

import datetime
import decimal
import json

from flask import (Blueprint, render_template, request,
                   redirect, url_for, session, jsonify)

# `db` resuelve al db.py de esta carpeta: no hay ningún sys.path apuntando a
# gestion_adm, y al correr en su propio proceso tampoco hay un módulo `db`
# ajeno ya cargado en sys.modules que pueda ganarle por nombre.
from db import get_connection, validasesion

# El `url_prefix` se define en app.py al registrar; las rutas de acá no lo
# repiten. `template_folder` apunta a la carpeta templates/ de este proyecto.
sindicato_bp = Blueprint("sindicato", __name__, template_folder="templates")


# Las cuotas guardan el CUIT como varchar(11) y `p_empresas` como bigint, así
# que la comparación necesita un CAST. El REGEXP va primero y no es decorativo:
# `CAST('30-12345678-9' AS UNSIGNED)` no falla, devuelve 30 — y ese 30 puede
# llegar a matchear una fila equivocada. Filtrando antes, las cuotas con CUIT
# mal formado no matchean con nada, que es lo correcto.
JOIN_EMPRESAS = """
    LEFT JOIN p_empresas e
           ON r.cuit REGEXP '^[0-9]+$'
          AND e.CUIT = CAST(r.cuit AS UNSIGNED)
"""


def _fix_types(obj):
    """Convierte Decimal y datetime a tipos que `tojson` sepa serializar."""
    if isinstance(obj, dict):
        return {k: _fix_types(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_fix_types(i) for i in obj]
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return str(obj)
    return obj


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD principal
# ─────────────────────────────────────────────────────────────────────────────

@sindicato_bp.route("/")
@sindicato_bp.route("/dashboard")
def fisca_dashboard():
    if not validasesion():
        return redirect(url_for("login"))

    dash = {}
    evol = []
    top10 = []
    ultimas_importaciones = []

    # Sin try/except: si la base falla, que se vea. Acá había un
    # `except Exception: pass` y lo que tapaba era un JOIN a `a_empresas`, una
    # tabla que no existe en esta base ni en `contable`. El dashboard venía
    # mostrando todo en cero y nadie se enteraba, porque un dashboard vacío se
    # parece bastante a un dashboard sin datos.
    with get_connection() as conn:
        with conn.cursor() as cur:

            # ── KPIs globales ────────────────────────────────────────────────
            cur.execute("""
                SELECT COUNT(DISTINCT cuit)    AS total_empresas,
                       COUNT(DISTINCT cuil)    AS total_cuiles,
                       COUNT(DISTINCT periodo) AS total_periodos,
                       MAX(periodo)            AS ultimo_periodo,
                       MIN(periodo)            AS primer_periodo
                FROM fisca_cuotarecepcion
            """)
            dash = cur.fetchone() or {}

            # ── Totales del período más reciente ─────────────────────────────
            if dash.get("ultimo_periodo"):
                cur.execute("""
                    SELECT COUNT(DISTINCT cuit) AS empresas,
                           COUNT(*)             AS empleados,
                           SUM(remuneracion)    AS total_remu,
                           SUM(cuota)           AS total_cuota
                    FROM fisca_cuotarecepcion
                    WHERE periodo = %s
                """, (dash["ultimo_periodo"],))
                dash["ultimo"] = cur.fetchone() or {}

            # ── Evolución de los últimos 12 períodos ─────────────────────────
            cur.execute("""
                SELECT periodo,
                       COUNT(DISTINCT cuit) AS empresas,
                       COUNT(*)             AS empleados,
                       SUM(remuneracion)    AS total_remu,
                       SUM(cuota)           AS total_cuota
                FROM fisca_cuotarecepcion
                GROUP BY periodo
                ORDER BY periodo DESC
                LIMIT 12
            """)
            evol = list(reversed(cur.fetchall()))

            # ── Top 10 empresas del período más reciente ─────────────────────
            if dash.get("ultimo_periodo"):
                cur.execute(f"""
                    SELECT r.cuit,
                           COALESCE(e.razon_social, r.cuit) AS empresa,
                           COUNT(*)             AS empleados,
                           SUM(r.remuneracion)  AS total_remu,
                           SUM(r.cuota)         AS total_cuota
                    FROM fisca_cuotarecepcion r
                    {JOIN_EMPRESAS}
                    WHERE r.periodo = %s
                    GROUP BY r.cuit, e.razon_social
                    ORDER BY total_cuota DESC
                    LIMIT 10
                """, (dash["ultimo_periodo"],))
                top10 = cur.fetchall()

            # ── Últimas importaciones ────────────────────────────────────────
            cur.execute("""
                SELECT l.id, l.nombre_archivo, l.cuit, l.empresa, l.periodo,
                       l.insertados, l.actualizados, l.ignorados, l.errores,
                       l.estado, l.fecha_importacion, l.detalle_errores,
                       u.nombre AS usuario_nombre
                FROM fisca_importacion_log l
                LEFT JOIN s_usuarios u ON u.id = l.id_usuario
                ORDER BY l.fecha_importacion DESC
                LIMIT 200
            """)
            ultimas_importaciones = cur.fetchall()

    return render_template(
        "fisca/fisca_dashboard.html",
        dash=_fix_types(dash),
        evol=_fix_types(evol),
        top10=_fix_types(top10),
        ultimas_importaciones=ultimas_importaciones,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Importar cuotas sindicales
# ─────────────────────────────────────────────────────────────────────────────

@sindicato_bp.route("/importar_cuotas")
def fisca_importar_cuotas():
    if not validasesion():
        return redirect(url_for("login"))
    return render_template("fisca/fisca_importar_cuotas.html")


@sindicato_bp.route("/importar_cuotas", methods=["POST"])
def fisca_importar_cuotas_post():
    if not validasesion():
        return jsonify(ok=False, error="Sin sesión activa."), 401

    data = request.get_json(force=True) or {}

    nombre_archivo = data.get("nombre_archivo", "")
    cuit           = data.get("cuit", "").strip()
    empresa        = data.get("empresa", "")
    periodo        = data.get("periodo")
    total_filas    = data.get("total_filas", 0)
    modo_dup       = data.get("modo_dup", "skip")   # skip | update | error
    obs_global     = data.get("observaciones", "") or ""
    registros      = data.get("registros", [])
    id_usuario     = session.get("sind_usuario_id", 0)

    if not cuit or not registros:
        return jsonify(ok=False, error="Payload incompleto: falta CUIT o registros.")

    insertados   = 0
    actualizados = 0
    ignorados    = 0
    errores      = 0
    detalle_err  = []

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:

                for rec in registros:
                    cuil         = rec.get("cuil", "")
                    per          = rec.get("periodo")
                    remuneracion = rec.get("remuneracion", 0)
                    cuota        = rec.get("cuota", 0)
                    alta         = rec.get("alta")
                    baja         = rec.get("baja")
                    obs_rec      = rec.get("observaciones") or obs_global or None

                    # El try es por registro y a propósito: una fila mala no
                    # tiene que abortar una importación de miles. El error no
                    # se pierde — se cuenta y viaja en `detalle_errores`.
                    try:
                        cur.execute(
                            "SELECT id FROM fisca_cuotarecepcion "
                            "WHERE cuit=%s AND cuil=%s AND periodo=%s LIMIT 1",
                            (cuit, cuil, per)
                        )
                        existente = cur.fetchone()

                        if existente:
                            if modo_dup == "skip":
                                ignorados += 1

                            elif modo_dup == "update":
                                cur.execute(
                                    "UPDATE fisca_cuotarecepcion "
                                    "SET remuneracion=%s, cuota=%s, alta=%s, "
                                    "    baja=%s, observaciones=%s "
                                    "WHERE id=%s",
                                    (remuneracion, cuota, alta, baja,
                                     obs_rec, existente["id"])
                                )
                                actualizados += 1

                            else:   # "error"
                                detalle_err.append(
                                    f"CUIL {cuil} / período {per}: "
                                    f"ya existe (modo: detener)."
                                )
                                errores += 1

                        else:
                            cur.execute(
                                "INSERT INTO fisca_cuotarecepcion "
                                "(cuit, cuil, periodo, remuneracion, cuota, "
                                " alta, baja, observaciones, id_usuario) "
                                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                                (cuit, cuil, per, remuneracion, cuota,
                                 alta, baja, obs_rec, id_usuario)
                            )
                            insertados += 1

                    except Exception as e:
                        detalle_err.append(f"CUIL {cuil}: {e}")
                        errores += 1

            # ── Log de importación ───────────────────────────────────────────
            estado_log = (
                "ok"      if errores == 0 else
                "parcial" if (insertados + actualizados) > 0 else
                "error"
            )
            aviso_log = None
            with conn.cursor() as cur_log:
                try:
                    cur_log.execute(
                        "INSERT INTO fisca_importacion_log "
                        "(nombre_archivo, cuit, empresa, periodo, total_filas, "
                        " insertados, actualizados, ignorados, errores, "
                        " modo_dup, observaciones, detalle_errores, estado, id_usuario) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            nombre_archivo, cuit, empresa, periodo, total_filas,
                            insertados, actualizados, ignorados, errores,
                            modo_dup, obs_global or None,
                            json.dumps(detalle_err, ensure_ascii=False) if detalle_err else None,
                            estado_log, id_usuario
                        )
                    )
                except Exception as e:
                    # Que falle el log no justifica tirar abajo una importación
                    # que ya se guardó, pero tampoco se traga: viaja en la
                    # respuesta para que se vea que el historial quedó
                    # incompleto. Antes esto era un `except Exception: pass`.
                    aviso_log = f"Los datos se importaron, pero no se pudo registrar en el historial: {e}"

    except Exception as e:
        return jsonify(ok=False, error=f"Error de base de datos: {e}")

    return jsonify(
        ok=True,
        insertados=insertados,
        actualizados=actualizados,
        ignorados=ignorados,
        errores=errores,
        detalle_errores=detalle_err,
        aviso=aviso_log,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Historial de importaciones
# ─────────────────────────────────────────────────────────────────────────────

@sindicato_bp.route("/importaciones_log")
def fisca_importaciones_log():
    if not validasesion():
        return redirect(url_for("login"))

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT l.*,
                       u.nombre AS usuario_nombre
                FROM fisca_importacion_log l
                LEFT JOIN s_usuarios u ON u.id = l.id_usuario
                ORDER BY l.fecha_importacion DESC
                LIMIT 500
            """)
            registros = cur.fetchall()

    return render_template("fisca/fisca_importaciones_log.html", registros=registros)


# ─────────────────────────────────────────────────────────────────────────────
# API — Cuotas por período (AJAX desde el tab)
# ─────────────────────────────────────────────────────────────────────────────

@sindicato_bp.route("/api/cuotas")
def api_cuotas():
    if not validasesion():
        return jsonify(ok=False, error="Sin sesión"), 401

    periodo  = request.args.get("periodo", "").strip()
    cuit_flt = request.args.get("cuit", "").strip()

    if not periodo:
        return jsonify(ok=False, error="Falta período.")

    totales = {"empresas": 0, "empleados": 0, "remuneracion": 0.0, "cuota": 0.0}

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:

                where  = "WHERE r.periodo = %s"
                params = [periodo]
                if cuit_flt:
                    where  += " AND r.cuit LIKE %s"
                    params.append(f"%{cuit_flt}%")

                cur.execute(
                    f"""SELECT r.id, r.cuit, r.cuil, r.periodo,
                               r.remuneracion, r.cuota, r.alta, r.baja,
                               r.observaciones, r.creado,
                               COALESCE(e.razon_social, '') AS empresa_nombre
                        FROM fisca_cuotarecepcion r
                        {JOIN_EMPRESAS}
                        {where}
                        ORDER BY r.cuit, r.cuil""",
                    params
                )
                rows = cur.fetchall()

                cur.execute(
                    f"""SELECT COUNT(DISTINCT r.cuit) AS empresas,
                               COUNT(*)               AS empleados,
                               SUM(r.remuneracion)    AS total_remu,
                               SUM(r.cuota)           AS total_cuota
                        FROM fisca_cuotarecepcion r
                        {where}""",
                    params
                )
                tot = cur.fetchone()
                if tot:
                    totales = {
                        "empresas":     int(tot["empresas"]  or 0),
                        "empleados":    int(tot["empleados"] or 0),
                        "remuneracion": float(tot["total_remu"]  or 0),
                        "cuota":        float(tot["total_cuota"] or 0),
                    }

        registros = [_fix_types(dict(r)) for r in rows]

    except Exception as e:
        return jsonify(ok=False, error=str(e))

    return jsonify(ok=True, periodo=int(periodo), registros=registros, totales=totales)
