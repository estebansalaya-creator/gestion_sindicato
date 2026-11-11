"""
afiliados_metricas.py — Métricas del Padrón (/afiliados/metricas, menú 22).

El tablero de gestion_adm (`padron.metricas`, afiliaciones/metricas.html)
pensado para un gremio. Lo de la obra social se fue: cobertura, tipo de
beneficiario, comercializadores y las validaciones del diseño de la SSS. Se
sumaron lo que importa acá: afiliados por empleador (la relación laboral
vigente, la misma regla de la Nómina), antigüedad en el gremio y los controles
del grupo familiar (hijos que cumplieron 21, estudiantes de 26, familiares
cuyo titular está de baja).

QUIÉN ES «AFILIADO»
El titular. Los familiares son personas a cargo: cuentan en el padrón pero no
son afiliados al gremio. Los indicadores de arriba lo distinguen; los repartos
siguen el filtro «Personas».

FILTROS
- Estado: activos (por defecto) o el padrón completo, con las bajas.
- Personas: titulares y familiares, o solo titulares.
- Período (desde / hasta): las altas y bajas por mes, los motivos de baja y la
  columna de altas por empleador. Por defecto, los últimos 24 meses. Las altas
  y bajas se cuentan sobre el padrón completo: una baja del período ya no está
  activa y con el filtro de estado no aparecería nunca.

CONTROLES
Se calculan siempre sobre el padrón de hoy, sin los filtros, y cada uno abre
la lista de afiliados que hay que revisar (?control=<clave>), con enlace a la
ficha. «CUIL que no verifica» se calcula en Python (`cuit_valido`, el mismo
módulo 11 del alta).

Sin Chart.js: los gráficos son HTML y CSS (sindicato.css, 15e). En la
intranet el CDN no siempre responde, y gestion_adm tuvo que copiar la librería
a la aplicación para que el tablero no quedara en blanco.
"""

from __future__ import annotations

from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from db import get_connection, puede, validasesion
from empleadores import cuit_valido

metricas_bp = Blueprint("padron_metricas", __name__)

#: Relación laboral vigente: activa y sin egreso o con egreso de hoy en adelante
#: (afiliados._vigente, empleadores._nomina).
VIGENTE = """EXISTS (SELECT 1 FROM p_relaciones_laborales r
                      WHERE r.cuil = a.cuil AND r.estado = 'activa'
                        AND (r.fecha_fin IS NULL OR r.fecha_fin >= CURDATE()))"""
EDAD = "TIMESTAMPDIFF(YEAR, a.fecha_nacimiento, CURDATE())"
#: AAAAMM sin DATE_FORMAT: el % choca con la sustitución de parámetros de PyMySQL.
def _aaaamm(col):
    return f"CONCAT(YEAR({col}), LPAD(MONTH({col}), 2, '0'))"

RANGOS_EDAD = [("0-17", 0, 17), ("18-25", 18, 25), ("26-35", 26, 35), ("36-45", 36, 45),
               ("46-55", 46, 55), ("56-65", 56, 65), ("66 y más", 66, 200)]
ANTIGUEDAD = [("Menos de 1 año", 0, 1), ("1 a 3 años", 1, 3), ("3 a 5 años", 3, 5),
              ("5 a 10 años", 5, 10), ("10 a 20 años", 10, 20), ("20 años o más", 20, 200)]

#: (clave, qué, qué hacer, universo, condición SQL sobre `a`; None = se calcula en Python)
CONTROLES = [
    ("hijo_21", "Hijos que cumplieron 21 años",
     "Siguen como hijo menor: pasarlos a estudiante con el certificado, o darlos de baja por mayoría de edad.",
     "activos", f"a.cod_parentesco IN (3, 5) AND {EDAD} >= 21"),
    ("estudiante_26", "Hijos estudiantes que cumplieron 26",
     "Ya no pueden seguir a cargo como estudiantes: darlos de baja.",
     "activos", f"a.cod_parentesco IN (4, 6) AND {EDAD} >= 26"),
    ("certificado", "Estudiantes sin certificado del último año",
     "Pedir el certificado de alumno regular y cargar su fecha en la ficha.",
     "activos", "a.cod_parentesco IN (4, 6) AND (a.fecha_certificado_estudios IS NULL "
                "OR a.fecha_certificado_estudios < DATE_SUB(CURDATE(), INTERVAL 1 YEAR))"),
    ("sin_titular", "Familiares sin titular activo",
     "El titular está de baja o no está en el padrón: dar de baja al familiar o corregir el grupo.",
     "activos", "a.cod_parentesco > 0 AND NOT EXISTS (SELECT 1 FROM p_afiliados t WHERE t.cuil = a.cuil_titular "
                "AND t.cod_parentesco = 0 AND t.activo = 1)"),
    ("sin_empleador", "Titulares sin empleador vigente",
     "Cargar la relación laboral en la solapa Empleadores de la ficha.",
     "activos", f"a.cod_parentesco = 0 AND NOT {VIGENTE}"),
    ("sin_cuil", "Sin CUIL", "Cargar el CUIL: sin él no se cruza con las DDJJ ni con la nómina.",
     "activos", "a.cuil IS NULL OR a.cuil = ''"),
    ("cuil_invalido", "CUIL que no verifica",
     "El dígito verificador no da: revisar contra el DNI o la constancia de ARCA.", "activos", None),
    ("sexo_cuil", "Sexo en contra del prefijo del CUIL",
     "Un CUIL 20 es de varón y uno 27 de mujer: corregir el sexo o el CUIL.",
     "activos", "(LEFT(a.cuil, 2) = '20' AND COALESCE(a.sexo, '') <> 'M') "
                "OR (LEFT(a.cuil, 2) = '27' AND COALESCE(a.sexo, '') <> 'F')"),
    ("sin_nacimiento", "Sin fecha de nacimiento",
     "Sin ella no se controla la edad de los hijos ni entra en la pirámide.", "activos", "a.fecha_nacimiento IS NULL"),
    ("sin_domicilio", "Domicilio incompleto", "Falta la calle, la localidad o la provincia.",
     "activos", "a.domicilio_calle IS NULL OR a.domicilio_calle = '' OR a.localidad IS NULL "
                "OR a.localidad = '' OR a.provincia IS NULL"),
    ("alta_futura", "Fecha de alta posterior a hoy", "Seguramente un error de tipeo en el año.",
     "activos", "a.fecha_alta > CURDATE()"),
    ("baja_sin_motivo", "Bajas sin motivo",
     "Las importadas de AEDA vinieron sin motivo; las nuevas lo piden al dar la baja.",
     "bajas", "a.id_motivo_baja IS NULL"),
]
UNIVERSO = {"activos": "a.activo = 1", "bajas": "a.activo = 0"}


def _fecha(nombre, defecto: date) -> tuple[date, str | None]:
    v = (request.args.get(nombre) or "").strip()
    if not v:
        return defecto, None
    try:
        return date.fromisoformat(v), None
    except ValueError:
        return defecto, f"«{v}» no es una fecha."


def _meses(desde: date, hasta: date) -> list[str]:
    salida, a, m = [], desde.year, desde.month
    while (a, m) <= (hasta.year, hasta.month):
        salida.append(f"{a}{m:02d}")
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    return salida


def _cuil_invalidos(cur) -> list[int]:
    cur.execute("SELECT id_afiliado, cuil FROM p_afiliados WHERE activo = 1 AND cuil IS NOT NULL AND cuil <> ''")
    return [f["id_afiliado"] for f in cur.fetchall() if not cuit_valido(f["cuil"])]


def _controles(cur) -> list[dict]:
    cur.execute("SELECT SUM(activo = 1) AS activos, SUM(activo = 0) AS bajas FROM p_afiliados")
    base = {k: int(v or 0) for k, v in cur.fetchone().items()}
    partes = [f"SUM({UNIVERSO[u]} AND ({cond})) AS `{c}`" for c, _, _, u, cond in CONTROLES if cond]
    cur.execute(f"SELECT {', '.join(partes)} FROM p_afiliados a")
    cuentas = {k: int(v or 0) for k, v in cur.fetchone().items()}
    cuentas["cuil_invalido"] = len(_cuil_invalidos(cur))
    salida = []
    for clave, que, hacer, universo, _ in CONTROLES:
        n, sobre = cuentas[clave], base[universo]
        salida.append({"clave": clave, "que": que, "hacer": hacer, "n": n, "sobre": sobre, "universo": universo,
                       "pct": round(100 * n / sobre, 1) if sobre else 0})
    return salida


def _detalle(cur, clave) -> list[dict]:
    control = next((c for c in CONTROLES if c[0] == clave), None)
    if not control:
        return []
    _, _, _, universo, cond = control
    if cond:
        where, args = f"{UNIVERSO[universo]} AND ({cond})", []
    else:
        ids = _cuil_invalidos(cur) or [0]
        where, args = f"a.id_afiliado IN ({','.join(['%s'] * len(ids))})", ids
    cur.execute(f"""
        SELECT a.id_afiliado, a.cuil, a.apellido_nombres, a.cod_parentesco, a.cuil_titular, a.sexo,
               a.fecha_nacimiento, {EDAD} AS edad, a.fecha_alta, a.fecha_baja, a.activo,
               a.fecha_certificado_estudios, a.localidad,
               COALESCE(p.descripcion, CONCAT('Código ', a.cod_parentesco)) AS parentesco,
               t.apellido_nombres AS titular, t.activo AS titular_activo
          FROM p_afiliados a
          LEFT JOIN p_parentesco p ON p.codigo = a.cod_parentesco
          LEFT JOIN p_afiliados t ON t.cuil = a.cuil_titular AND t.cod_parentesco = 0 AND a.cod_parentesco > 0
         WHERE {where}
         ORDER BY a.apellido_nombres
    """, args)
    return cur.fetchall()


@metricas_bp.route("/afiliados/metricas")
def metricas():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede(url_for("padron_metricas.metricas")):
        flash("!No tenés permiso para las métricas del padrón.")
        return redirect(url_for("menu"))

    hoy = date.today()
    errores = []
    estado = "todos" if request.args.get("estado") == "todos" else "activos"
    personas = "titulares" if request.args.get("personas") == "titulares" else "todas"
    defecto_desde = date(hoy.year - 2 + (hoy.month == 12), hoy.month % 12 + 1, 1)   # 24 meses con el actual
    desde, e1 = _fecha("desde", defecto_desde)
    hasta, e2 = _fecha("hasta", hoy)
    errores += [e for e in (e1, e2) if e]
    if desde > hasta:
        errores.append("«Desde» es posterior a «hasta»: se usan los últimos 24 meses.")
        desde, hasta = defecto_desde, hoy
    if len(_meses(desde, hasta)) > 120:
        errores.append("El período tiene más de 10 años: se muestran los últimos 120 meses.")
        desde = date(hasta.year - 10 + (hasta.month == 12), hasta.month % 12 + 1, 1)

    cond = ["a.activo = 1"] if estado == "activos" else []
    W = " AND ".join(cond + (["a.cod_parentesco = 0"] if personas == "titulares" else [])) or "1 = 1"
    W_grupo = " AND ".join(cond) or "1 = 1"                    # el parentesco mira el grupo entero
    W_per = "a.cod_parentesco = 0" if personas == "titulares" else "1 = 1"   # altas y bajas: padrón completo
    m: dict = {}

    with get_connection() as conn:
        with conn.cursor() as cur:
            # ── Indicadores: el padrón de hoy ──
            cur.execute(f"""
                SELECT SUM(activo = 1 AND cod_parentesco = 0) AS titulares,
                       SUM(activo = 1 AND cod_parentesco > 0) AS familiares,
                       SUM(activo = 1) AS personas,
                       SUM(activo = 0) AS bajas,
                       ROUND(AVG(CASE WHEN activo = 1 AND cod_parentesco = 0 THEN {EDAD} END), 1) AS edad_titulares,
                       SUM(activo = 1 AND incapacidad <> 0) AS discapacidad
                  FROM p_afiliados a
            """)
            m["kpi"] = {k: (v if v is not None else 0) for k, v in cur.fetchone().items()}
            cur.execute("""
                SELECT COUNT(DISTINCT COALESCE(CAST(r.id_empleador AS CHAR), r.cuit_empleador)) AS n
                  FROM p_relaciones_laborales r
                  JOIN p_afiliados a ON a.cuil = r.cuil AND a.activo = 1 AND a.cod_parentesco = 0
                 WHERE r.estado = 'activa' AND (r.fecha_fin IS NULL OR r.fecha_fin >= CURDATE())
            """)
            m["kpi"]["empleadores"] = cur.fetchone()["n"] or 0

            # ── Altas y bajas por mes ──
            args = (desde, hasta)
            cur.execute(f"""SELECT {_aaaamm('a.fecha_alta')} AS periodo, COUNT(*) AS n FROM p_afiliados a
                             WHERE {W_per} AND a.fecha_alta BETWEEN %s AND %s GROUP BY periodo""", args)
            altas = {f["periodo"]: f["n"] for f in cur.fetchall()}
            cur.execute(f"""SELECT {_aaaamm('a.fecha_baja')} AS periodo, COUNT(*) AS n FROM p_afiliados a
                             WHERE {W_per} AND a.fecha_baja BETWEEN %s AND %s GROUP BY periodo""", args)
            bajas = {f["periodo"]: f["n"] for f in cur.fetchall()}
            m["evolucion"] = [{"periodo": p, "altas": altas.get(p, 0), "bajas": bajas.get(p, 0),
                               "neto": altas.get(p, 0) - bajas.get(p, 0)} for p in _meses(desde, hasta)]
            m["altas"] = sum(altas.values())
            m["bajas"] = sum(bajas.values())

            # ── Edad y sexo ──
            casos = " ".join(f"WHEN {EDAD} BETWEEN {lo} AND {hi} THEN '{r}'" for r, lo, hi in RANGOS_EDAD)
            cur.execute(f"""
                SELECT CASE WHEN a.fecha_nacimiento IS NULL THEN 'Sin dato' {casos} ELSE 'Sin dato' END AS rango,
                       SUM(a.sexo = 'M') AS varones, SUM(a.sexo = 'F') AS mujeres,
                       SUM(a.sexo IS NULL OR a.sexo NOT IN ('M', 'F')) AS otros
                  FROM p_afiliados a WHERE {W} GROUP BY rango
            """)
            por_rango = {f["rango"]: f for f in cur.fetchall()}
            m["edades"] = [{"rango": r, "varones": int(por_rango.get(r, {}).get("varones") or 0),
                            "mujeres": int(por_rango.get(r, {}).get("mujeres") or 0)}
                           for r, _, _ in reversed(RANGOS_EDAD)]
            sd = por_rango.get("Sin dato", {})
            m["edad_sin_dato"] = sum(int(sd.get(k) or 0) for k in ("varones", "mujeres", "otros"))
            m["sexo_otro"] = sum(int(f.get("otros") or 0) for f in por_rango.values())

            # ── Antigüedad en el gremio (titulares) ──
            casos = " ".join(f"WHEN TIMESTAMPDIFF(YEAR, a.fecha_alta, CURDATE()) >= {lo} "
                             f"AND TIMESTAMPDIFF(YEAR, a.fecha_alta, CURDATE()) < {hi} THEN '{r}'"
                             for r, lo, hi in ANTIGUEDAD)
            cur.execute(f"""
                SELECT CASE WHEN a.fecha_alta IS NULL OR a.fecha_alta > CURDATE() THEN 'Sin dato'
                            {casos} END AS etiqueta, COUNT(*) AS n
                  FROM p_afiliados a WHERE {W} AND a.cod_parentesco = 0 GROUP BY etiqueta
            """)
            ant = {f["etiqueta"]: f["n"] for f in cur.fetchall()}
            m["antiguedad"] = [{"etiqueta": r, "n": ant.get(r, 0)} for r, _, _ in ANTIGUEDAD]
            if ant.get("Sin dato"):
                m["antiguedad"].append({"etiqueta": "Sin fecha de alta", "n": ant["Sin dato"]})

            # ── Afiliados por empleador: titulares activos con relación vigente (no sigue los filtros) ──
            cur.execute(f"""
                SELECT x.id_emp, x.nombre, x.cuit, COUNT(DISTINCT x.cuil) AS n,
                       COUNT(DISTINCT CASE WHEN x.fecha_alta BETWEEN %s AND %s THEN x.cuil END) AS altas
                  FROM (SELECT COALESCE(e.id, e2.id) AS id_emp,
                               COALESCE(e.razon_social, e2.razon_social, CONCAT('CUIT ', r.cuit_empleador)) AS nombre,
                               COALESCE(CAST(e.CUIT AS CHAR), CAST(e2.CUIT AS CHAR), r.cuit_empleador) AS cuit,
                               a.cuil, a.fecha_alta
                          FROM p_afiliados a
                          JOIN p_relaciones_laborales r ON r.cuil = a.cuil AND r.estado = 'activa'
                               AND (r.fecha_fin IS NULL OR r.fecha_fin >= CURDATE())
                          LEFT JOIN p_empresas e ON e.id = r.id_empleador
                          LEFT JOIN p_empresas e2 ON r.id_empleador IS NULL AND r.cuit_empleador REGEXP '^[0-9]+$'
                               AND e2.CUIT = CAST(r.cuit_empleador AS UNSIGNED)
                         WHERE a.activo = 1 AND a.cod_parentesco = 0) x
                 GROUP BY x.id_emp, x.nombre, x.cuit
                 ORDER BY n DESC, x.nombre
            """, args)
            m["empleadores"] = cur.fetchall()
            # Siempre los activos: un dado de baja no tiene empleo vigente que mostrar.
            m["titulares_filtro"] = m["kpi"]["titulares"]
            cur.execute(f"SELECT COUNT(*) AS n FROM p_afiliados a WHERE a.activo = 1 AND a.cod_parentesco = 0 AND NOT {VIGENTE}")
            m["sin_empleador"] = cur.fetchone()["n"] or 0

            # ── Repartos ──
            cur.execute(f"""SELECT COALESCE(p.descripcion, CONCAT('Código ', a.cod_parentesco)) AS etiqueta, COUNT(*) AS n
                              FROM p_afiliados a LEFT JOIN p_parentesco p ON p.codigo = a.cod_parentesco
                             WHERE {W_grupo} GROUP BY a.cod_parentesco, p.descripcion ORDER BY a.cod_parentesco""")
            m["parentesco"] = cur.fetchall()
            cur.execute(f"""SELECT COALESCE(pr.nombre, 'Sin provincia') AS etiqueta, COUNT(*) AS n
                              FROM p_afiliados a LEFT JOIN p_provincia pr ON pr.codigo = a.provincia
                             WHERE {W} GROUP BY a.provincia, pr.nombre ORDER BY n DESC""")
            m["provincias"] = cur.fetchall()
            cur.execute(f"""SELECT COALESCE(NULLIF(TRIM(a.localidad), ''), 'Sin localidad') AS etiqueta, COUNT(*) AS n
                              FROM p_afiliados a WHERE {W} GROUP BY etiqueta ORDER BY n DESC LIMIT 15""")
            m["localidades"] = cur.fetchall()
            cur.execute(f"""SELECT COALESCE(mm.nombre, 'Sin motivo cargado') AS etiqueta, COUNT(*) AS n
                              FROM p_afiliados a LEFT JOIN p_motivo_movimiento mm ON mm.id = a.id_motivo_baja
                             WHERE {W_per} AND a.fecha_baja BETWEEN %s AND %s
                             GROUP BY a.id_motivo_baja, mm.nombre ORDER BY n DESC""", args)
            m["motivos"] = cur.fetchall()
            cur.execute(f"SELECT COUNT(*) AS n FROM p_afiliados a WHERE {W}")
            m["total_filtro"] = cur.fetchone()["n"] or 0

            # ── Controles ──
            m["controles"] = _controles(cur)
            control = request.args.get("control") or ""
            detalle = _detalle(cur, control) if control else []

    if control and not any(c["clave"] == control for c in m["controles"]):
        control = ""
    puede_abm = puede(url_for("afiliados.abm_afiliados"))
    return render_template("afiliados/metricas.html", m=m, errores=errores, estado=estado, personas=personas,
                           desde=desde, hasta=hasta, defecto_desde=defecto_desde, hoy=hoy,
                           control=control, detalle=detalle, puede_abm=puede_abm,
                           puede_empleadores=puede(url_for("empleadores.abm_empleadores")))
