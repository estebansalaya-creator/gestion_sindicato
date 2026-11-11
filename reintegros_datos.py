"""
reintegros_datos.py — Circuito de reintegros a afiliados (capa de datos).

Portado de `gestion_adm/reintegros.py`. Mismo circuito, mismas reglas y las
mismas tablas —las de reintegros vinieron de `contable` con la estructura
idéntica—; cambia lo que en el gremio es distinto de la obra social:

- Los conceptos son los de AEDA (subsidios de nacimiento, educación inicial,
  casamiento, movilidad…), marcados con `c_concepto_de_gastos.es_reintegro`.
  No hay concepto predeterminado: en la obra social casi todo era «Reintegros
  a afiliados»; acá cada solicitud es de un subsidio distinto.
- El padrón no tiene cobertura ni tipo de beneficiario: esos filtros no están.
- El nombre del afiliado es `apellido_nombres`, un solo campo como en AEDA;
  con la coma de gestion_adm (apellido, nombre) salía «LUCERO RUDY,».
- El estado `pagada`: lo que se pagó fuera de este sistema. Hoy son los
  reintegros importados de AEDA, que ya se cobraron allá.
- El número de solicitud sale de `c_numeradores` y no de un COUNT(*): con el
  COUNT, borrar un borrador hacía que el siguiente repitiera un número.

Circuito:
    borrador -> en_auditoria -> aprobada -> pago_parcial -> con_orden
                     |              |
                     +-> rechazada  +-> anulada

- AUDITORÍA: el auditor resuelve el importe reconocido de cada renglón. Al
  cerrarla, la solicitud queda APROBADA con el importe autorizado, lista para
  la orden de pago.
- La orden de pago se crea en `pago_ordenes` (clase 'reintegro'), una por
  titular. Aprobarla y pagarla es del circuito de pagos.
"""

from __future__ import annotations

import datetime
import unicodedata
from decimal import Decimal, InvalidOperation

import pymysql

import tesoreria
from db import get_connection

ESTADOS = [
    ("borrador",     "Borrador"),
    ("en_auditoria", "En auditoría"),
    ("aprobada",     "Aprobada"),
    ("rechazada",    "Rechazada"),
    ("anulada",      "Anulada"),
    # Cobró una parte y espera el resto. Sin este estado no se distingue al
    # que nunca se pagó del que se pagó a medias.
    ("pago_parcial", "Pago parcial"),
    ("con_orden",    "Con orden de pago"),
    # Pagada fuera de este sistema: el historial importado de AEDA.
    ("pagada",       "Pagada"),
]
ESTADOS_LABEL = dict(ESTADOS)

#: El color de cada estado en pantalla (ui.estado).
ESTADOS_TIPO = {
    "borrador": "neutro", "en_auditoria": "warn", "aprobada": "info",
    "pago_parcial": "proceso", "con_orden": "ok", "pagada": "ok",
    "rechazada": "danger", "anulada": "neutro",
}

# Los que todavía tienen algo por cobrar.
ESTADOS_PAGABLES = ("aprobada", "pago_parcial")

#: Desde estos ya no se toca la solicitud, tenga orden o no. Una rechazada o
#: anulada se corrige cargando otra: el papel que se le dio al afiliado dice lo
#: que decía.
ESTADOS_CERRADOS = ("rechazada", "anulada", "pagada")

PREFIJO_SOLICITUD = "RA"
CLASE_ORDEN       = "reintegro"      # enum pago_ordenes.clase

#: Apellido y nombres como en el padrón: una sola columna desde
#: sql/afiliados_apellido_nombres_20261110.sql.
NOMBRE = "a.apellido_nombres"


def _plano(texto) -> str:
    base = unicodedata.normalize("NFKD", str(texto).strip().lower())
    base = "".join(c for c in base if not unicodedata.combining(c))
    return base.replace(" ", "_")


#: `estado` se guarda por clave y el código la compara con `==`. Una fila con
#: la etiqueta en la columna («Borrador») pasa los filtros de MySQL, que no
#: distingue mayúsculas, pero falla en cada `if` de Python, y el botón de
#: editar directamente no se dibuja. Se normaliza al leer.
_ESTADO_POR_TEXTO = {}
for _clave, _etiqueta in ESTADOS:
    _ESTADO_POR_TEXTO[_plano(_clave)]    = _clave
    _ESTADO_POR_TEXTO[_plano(_etiqueta)] = _clave


def estado_clave(valor):
    """La clave canónica del estado; lo que no reconoce, tal cual."""
    if valor is None:
        return None
    return _ESTADO_POR_TEXTO.get(_plano(valor), str(valor).strip())


def estado_label(valor) -> str:
    clave = estado_clave(valor)
    return ESTADOS_LABEL.get(clave, clave or "")


class ReintegroError(Exception):
    """Error de negocio del circuito de reintegros."""


# =============================================================================
# Helpers
# =============================================================================

def _dec(valor, campo: str = "importe") -> Decimal:
    """
    Decimal desde formato argentino (1.234,56) o con punto (1234.56).

    Con coma, la coma es decimal y los puntos de miles. Sin coma, el último
    punto es decimal solo si lo siguen 1 o 2 dígitos: «1.000» son mil.
    """
    if valor is None or valor == "":
        return Decimal("0.00")
    if isinstance(valor, (Decimal, int, float)):
        return Decimal(str(valor)).quantize(Decimal("0.01"))

    txt = str(valor).strip().replace(" ", "").replace("$", "")
    if "," in txt:
        txt = txt.replace(".", "").replace(",", ".")
    elif "." in txt:
        ultimo = txt.rfind(".")
        if len(txt) - ultimo - 1 in (1, 2):
            txt = txt[:ultimo].replace(".", "") + "." + txt[ultimo + 1:]
        else:
            txt = txt.replace(".", "")
    try:
        return Decimal(txt).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ReintegroError(f"El {campo} «{valor}» no es un número válido.")


def _proximo(cur, ambito: str, periodo: str, minimo: int = 0) -> int:
    """
    El próximo número de `c_numeradores`, en una sola sentencia atómica: dos
    sesiones a la vez no pueden sacar el mismo.

    `minimo` arranca el contador por encima de lo que ya existe la primera vez
    que se usa el ámbito en el período.
    """
    cur.execute("""
        INSERT INTO c_numeradores (ambito, periodo, ultimo)
        VALUES (%s, %s, LAST_INSERT_ID(%s))
        ON DUPLICATE KEY UPDATE ultimo = LAST_INSERT_ID(ultimo + 1)
    """, (ambito, periodo, minimo + 1))
    cur.execute("SELECT LAST_INSERT_ID() AS n")
    return int(cur.fetchone()["n"])


def _nuevo_nro_solicitud(cur, anio: int) -> str:
    """RA-AAAA-NNNNNN. El mínimo cubre las solicitudes cargadas antes del contador."""
    cur.execute("""
        SELECT COALESCE(MAX(CAST(SUBSTRING_INDEX(nro_solicitud, '-', -1) AS UNSIGNED)), 0) AS m
          FROM c_reintegro_afiliados
         WHERE nro_solicitud LIKE %s
    """, (f"{PREFIJO_SOLICITUD}-{anio}-%",))
    minimo = int(cur.fetchone()["m"] or 0)
    n = _proximo(cur, "c_reintegro_afiliados", f"{anio:04d}", minimo)
    return f"{PREFIJO_SOLICITUD}-{anio}-{n:06d}"


def _nuevo_nro_orden(cur) -> str:
    """AAMM-######## del mismo contador que el resto de las órdenes de pago."""
    periodo = datetime.date.today().strftime("%y%m")
    return f"{periodo}-{_proximo(cur, 'pago_ordenes', periodo):08d}"


def max_nivel(cur) -> int:
    cur.execute("SELECT MAX(nivel) AS m FROM pago_config_aprobadores WHERE activo = 1")
    r = cur.fetchone()
    return int(r["m"]) if r and r["m"] else 1


# =============================================================================
# Catálogos / búsquedas
# =============================================================================

def conceptos_de_gasto(incluir: list[int] | None = None) -> list[dict]:
    """
    Los conceptos que se ofrecen en la solicitud: los marcados `es_reintegro`.

    `incluir` suma conceptos que no están marcados pero que ya usa la solicitud
    que se edita —una del historial, o un concepto que se desmarcó después—:
    sin eso, el select no lo tendría y al guardar cambiaría solo.

    Sin la columna (falta correr sql/reintegros_20261107.sql) ofrece el catálogo
    entero, que es como funcionaba en gestion_adm.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                conceptos = list(tesoreria.conceptos_activos(cur, solo_reintegro=True))
            except pymysql.err.OperationalError:
                cur.execute("SELECT id, descripcion FROM c_concepto_de_gastos "
                            "ORDER BY descripcion")
                conceptos = list(cur.fetchall())
            faltan = [int(i) for i in (incluir or [])
                      if int(i) not in {c["id"] for c in conceptos}]
            if faltan:
                cur.execute(
                    f"SELECT id, descripcion FROM c_concepto_de_gastos "
                    f"WHERE id IN ({','.join(['%s'] * len(faltan))})", faltan)
                conceptos += cur.fetchall()
    return sorted(conceptos, key=lambda c: c["descripcion"])


def atributos_activos() -> list[dict]:
    """Atributos del afiliado para el filtro de la grilla (Judicializado, Amparo…)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, rotulo FROM p_afiliado_atributo "
                        "WHERE activo = 1 ORDER BY rotulo")
            return cur.fetchall()


#: Un afiliado cuenta como activo si lo está, o si tiene un atributo que fuerza
#: el estado activo (judicializado, amparo). Escrito una vez y usado en las
#: tres consultas: a mano en cada una, dentro de un año una quedaría vieja y el
#: síntoma sería «a este no le puedo cargar el reintegro», sin pista de por qué.
#: `a` es el alias de `p_afiliados`.
_VIGENTE = """(
    a.activo = 1
    OR EXISTS (SELECT 1
                 FROM p_atributos_por_afiliado x
                 JOIN p_afiliado_atributo at ON at.id = x.id_atributo
                WHERE x.id_afiliado = a.id_afiliado
                  AND at.activo = 1 AND at.fuerza_activo = 1)
)"""

#: Dado de baja dentro del mes en curso: se le puede cargar un reintegro, pero
#: solo por gastos del mes anterior (ver `_validar_bajas_del_mes`). Sin `%`: la
#: consulta lleva parámetros y PyMySQL tomaría un `%Y` como marcador.
_BAJA_EN_EL_MES = "(a.fecha_baja >= CURDATE() - INTERVAL (DAY(CURDATE()) - 1) DAY)"

_ACTIVO_O_PROTEGIDO = f"({_VIGENTE} OR {_BAJA_EN_EL_MES})"

_COLS_BAJA = f"""CASE WHEN {_VIGENTE} THEN 0 ELSE 1 END AS baja_mes,
                 DATE_FORMAT(a.fecha_baja, '%%d/%%m/%%Y') AS fecha_baja_txt"""


def buscar_titulares(texto: str, limite: int = 25) -> list[dict]:
    """Titulares vigentes (cod_parentesco = 0) por apellido y nombres, CUIL o documento."""
    texto = (texto or "").strip()
    if len(texto) < 3:
        return []
    like = f"%{texto}%"
    digitos = "".join(c for c in texto if c.isdigit())
    like_num = f"%{digitos}%" if digitos else like
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT a.id_afiliado, a.cuil, a.nro_documento,
                       a.cbu_pago, {NOMBRE} AS nombre_completo,
                       {_COLS_BAJA}
                FROM   p_afiliados a
                WHERE  {_ACTIVO_O_PROTEGIDO}
                  AND  a.cod_parentesco = 0
                  AND (a.apellido_nombres LIKE %s
                       OR a.cuil LIKE %s OR a.nro_documento LIKE %s)
                ORDER BY a.apellido_nombres
                LIMIT %s
            """, (like, like_num, like_num, limite))
            return cur.fetchall()


def grupo_familiar(id_titular) -> list[dict]:
    """Titular y familiares vigentes que comparten cuil_titular."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT cuil FROM p_afiliados WHERE id_afiliado = %s", (id_titular,))
            row = cur.fetchone()
            if not row:
                return []
            cur.execute(f"""
                SELECT a.id_afiliado, a.cuil, a.nro_documento, a.cod_parentesco,
                       COALESCE(p.descripcion, 'Titular') AS parentesco,
                       {NOMBRE} AS nombre_completo,
                       {_COLS_BAJA}
                FROM   p_afiliados a
                LEFT JOIN p_parentesco p ON p.codigo = a.cod_parentesco
                WHERE  {_ACTIVO_O_PROTEGIDO}
                  AND (a.id_afiliado = %s OR (a.cuil_titular = %s AND %s <> ''))
                ORDER BY a.cod_parentesco, a.apellido_nombres
            """, (id_titular, row["cuil"] or "", row["cuil"] or ""))
            return cur.fetchall()


def _mes_anterior(hoy: datetime.date | None = None) -> tuple[datetime.date, datetime.date]:
    hoy = hoy or datetime.date.today()
    fin = hoy.replace(day=1) - datetime.timedelta(days=1)
    return fin.replace(day=1), fin


def _validar_bajas_del_mes(cur, renglones: list[dict]) -> None:
    """
    El dado de baja en el mes solo cobra gastos del mes anterior: lo que gastó
    con cobertura le corresponde; lo de este mes es posterior a la baja.
    """
    ids = {int(r["id_afiliado"]) for r in renglones}
    if not ids:
        return
    cur.execute(f"""
        SELECT a.id_afiliado, a.fecha_baja, {NOMBRE} AS nombre
          FROM p_afiliados a
         WHERE a.id_afiliado IN ({",".join(["%s"] * len(ids))})
           AND NOT {_VIGENTE}
    """, list(ids))
    bajas = {f["id_afiliado"]: f for f in cur.fetchall()}
    if not bajas:
        return
    desde, hasta = _mes_anterior()
    for r in renglones:
        b = bajas.get(int(r["id_afiliado"]))
        if not b:
            continue
        f = r.get("fecha_gasto")
        if isinstance(f, str) and f:
            f = datetime.datetime.strptime(f, "%Y-%m-%d").date()
        fb_txt = b["fecha_baja"].strftime("%d/%m/%Y") if b["fecha_baja"] else "este mes"
        if not f or not (desde <= f <= hasta):
            raise ReintegroError(
                f"{b['nombre']} tiene la baja del {fb_txt}: solo se le pueden "
                f"reintegrar gastos del mes anterior ({desde:%d/%m/%Y} al {hasta:%d/%m/%Y}). "
                + ("Cargá la fecha del gasto." if not f else
                   f"El renglón tiene fecha {f:%d/%m/%Y}."))


def _ids_grupo_familiar(cur, id_titular) -> set:
    cur.execute("SELECT cuil FROM p_afiliados WHERE id_afiliado = %s", (id_titular,))
    row = cur.fetchone()
    if not row:
        raise ReintegroError("El titular no existe en el padrón.")
    cur.execute(
        f"SELECT a.id_afiliado FROM p_afiliados a "
        f"WHERE {_ACTIVO_O_PROTEGIDO} AND (a.id_afiliado = %s OR (a.cuil_titular = %s AND %s <> ''))",
        (id_titular, row["cuil"] or "", row["cuil"] or ""))
    return {r["id_afiliado"] for r in cur.fetchall()}


# =============================================================================
# Consultas
# =============================================================================

#: Subsidio o reintegro: sale de la clase de los conceptos de sus renglones
#: (`c_concepto_de_gastos.clase_reintegro`, sql/reintegros_clase_20261111.sql).
#: Un concepto sin clase cuenta como reintegro; renglones de las dos, «mixta».
CLASES = {"subsidio": "Subsidio", "reintegro": "Reintegro", "mixta": "Mixta"}


def _clases(cur) -> dict:
    """id del reintegro → 'subsidio' | 'reintegro' | 'mixta'. Sin la columna
    (falta el script), todo es reintegro."""
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.columns
                    WHERE table_schema = DATABASE() AND table_name = 'c_concepto_de_gastos'
                      AND column_name = 'clase_reintegro'""")
    if not cur.fetchone()["n"]:
        return {}
    cur.execute("""SELECT d.id_reintegro,
                          IF(COUNT(DISTINCT COALESCE(g.clase_reintegro, 'reintegro')) > 1, 'mixta',
                             MIN(COALESCE(g.clase_reintegro, 'reintegro'))) AS clase
                     FROM c_reintegro_afiliados_detalle d
                     JOIN c_concepto_de_gastos g ON g.id = d.id_concepto_gasto
                    GROUP BY d.id_reintegro""")
    return {f["id_reintegro"]: f["clase"] for f in cur.fetchall()}


def _poner_clase(filas, clases) -> None:
    for r in filas:
        r["clase"] = clases.get(r["id"], "reintegro")
        r["clase_txt"] = CLASES[r["clase"]]


def listar(estado: str | None = None) -> list[dict]:
    """
    Las solicitudes, de la más nueva a la más vieja, con lo que la grilla
    necesita para filtrar sin volver al servidor:

    - `busqueda`: nombre, CUIL y documento de los afiliados de los renglones.
      Un reintegro del hijo se carga a nombre del padre; buscar el CUIL del
      hijo tiene que encontrar la solicitud.
    - `conceptos` y `atributos`: ids, separados por espacios, para los filtros
      de concepto y de atributo (del titular o de cualquier afiliado de un
      renglón: el atributo que interesa puede ser del hijo).

    Se filtra en el navegador como el resto de las grillas: son cientos de
    filas, no miles.
    """
    where, params = "", []
    if estado:
        where, params = "WHERE v.estado = %s", [estado_clave(estado)]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM v_reintegros_afiliados v {where} "
                        "ORDER BY v.fecha_solicitud DESC, v.id DESC", params)
            filas = cur.fetchall()
            if not filas:
                return []
            cur.execute(f"""
                SELECT d.id_reintegro,
                       GROUP_CONCAT(DISTINCT CONCAT_WS(' ', {NOMBRE}, a.cuil, a.nro_documento)
                                    SEPARATOR ' · ') AS busqueda,
                       GROUP_CONCAT(DISTINCT d.id_concepto_gasto SEPARATOR ' ') AS conceptos,
                       GROUP_CONCAT(DISTINCT cg.descripcion ORDER BY cg.descripcion
                                    SEPARATOR ', ') AS conceptos_txt
                  FROM c_reintegro_afiliados_detalle d
                  JOIN p_afiliados a           ON a.id_afiliado = d.id_afiliado
                  JOIN c_concepto_de_gastos cg ON cg.id = d.id_concepto_gasto
                 GROUP BY d.id_reintegro
            """)
            extra = {f["id_reintegro"]: f for f in cur.fetchall()}
            cur.execute("""
                SELECT r.id AS id_reintegro,
                       GROUP_CONCAT(DISTINCT x.id_atributo SEPARATOR ' ') AS atributos
                  FROM c_reintegro_afiliados r
                  JOIN p_atributos_por_afiliado x
                    ON x.id_afiliado = r.id_afiliado
                    OR x.id_afiliado IN (SELECT d.id_afiliado FROM c_reintegro_afiliados_detalle d
                                          WHERE d.id_reintegro = r.id)
                 GROUP BY r.id
            """)
            atrib = {f["id_reintegro"]: f["atributos"] for f in cur.fetchall()}
            _poner_clase(filas, _clases(cur))

    for r in filas:
        r["estado"] = estado_clave(r.get("estado"))
        e = extra.get(r["id"], {})
        r["busqueda"] = e.get("busqueda") or ""
        r["conceptos"] = e.get("conceptos") or ""
        r["conceptos_txt"] = e.get("conceptos_txt") or ""
        r["atributos"] = atrib.get(r["id"]) or ""
    return filas


def obtener(id_reintegro) -> dict | None:
    """La solicitud entera: cabecera, renglones con sus adjuntos y sus órdenes de pago."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM v_reintegros_afiliados WHERE id = %s", (id_reintegro,))
            cab = cur.fetchone()
            if not cab:
                return None
            cab["estado"] = estado_clave(cab.get("estado"))

            cur.execute("""
                SELECT observaciones, fecha_anulacion, importado_csv, creado
                FROM   c_reintegro_afiliados WHERE id = %s
            """, (id_reintegro,))
            cab.update(cur.fetchone() or {})

            cur.execute(f"""
                SELECT d.*, cg.descripcion AS concepto,
                       {NOMBRE} AS afiliado, a.cuil, a.cod_parentesco,
                       COALESCE(p.descripcion, 'Titular') AS parentesco
                FROM   c_reintegro_afiliados_detalle d
                JOIN   c_concepto_de_gastos cg ON cg.id = d.id_concepto_gasto
                JOIN   p_afiliados a           ON a.id_afiliado = d.id_afiliado
                LEFT JOIN p_parentesco p       ON p.codigo = a.cod_parentesco
                WHERE  d.id_reintegro = %s
                ORDER BY d.id
            """, (id_reintegro,))
            cab["detalle"] = cur.fetchall()

            ids = [d["id"] for d in cab["detalle"]]
            adjuntos = {i: [] for i in ids}
            if ids:
                cur.execute(f"""
                    SELECT ad.*, u.nombre AS usuario
                    FROM   c_reintegro_afiliados_detalle_adjunto ad
                    LEFT JOIN s_usuarios u ON u.id = ad.id_usuario
                    WHERE  ad.id_detalle IN ({",".join(["%s"] * len(ids))})
                    ORDER BY ad.id
                """, ids)
                for a in cur.fetchall():
                    adjuntos[a["id_detalle"]].append(a)
            for d in cab["detalle"]:
                d["adjuntos"] = adjuntos.get(d["id"], [])

            # Con pago parcial, un reintegro puede estar en varias órdenes: la
            # relación real es el detalle, no `id_orden_pago`, que apunta a la
            # última.
            cur.execute("""
                SELECT o.id, o.nro_orden, o.fecha, o.estado, det.importe
                  FROM pago_ordenes_reintegro_det det
                  JOIN pago_ordenes o ON o.id = det.id_orden
                 WHERE det.id_reintegro = %s
                 ORDER BY o.fecha, o.id
            """, (id_reintegro,))
            cab["ordenes"] = cur.fetchall()

            cur.execute("SELECT aprobado, en_ordenes, saldo FROM v_reintegro_saldo "
                        "WHERE id_reintegro = %s", (id_reintegro,))
            cab.update(cur.fetchone() or {})
            return cab


def adjunto(id_adjunto) -> dict | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM c_reintegro_afiliados_detalle_adjunto WHERE id = %s",
                        (id_adjunto,))
            return cur.fetchone()


# =============================================================================
# Alta / edición
# =============================================================================

def editable(reintegro: dict) -> tuple:
    """
    `(se_puede, motivo)`: si la solicitud todavía se puede corregir.

    Lo que cierra la puerta es la orden de pago, no la auditoría. Hasta que hay
    orden, todo es interno y corregible; con la orden emitida hay un importe
    comprometido, y cambiar el detalle dejaría a la orden pagando algo distinto
    de lo que la respalda. Una auditada que se edita pierde su aprobación (ver
    `guardar`): editarla no es una forma de cambiar lo aprobado sin que nadie
    lo mire.
    """
    if not reintegro:
        return False, "La solicitud no existe."
    if reintegro.get("id_orden_pago") or reintegro.get("nro_orden_pago"):
        return False, ("La solicitud ya tiene orden de pago "
                       f"{reintegro.get('nro_orden_pago') or ''}".strip()
                       + " y no se puede editar.")
    if estado_clave(reintegro.get("estado")) in ESTADOS_CERRADOS:
        return False, (f"La solicitud está {estado_label(reintegro.get('estado')).lower()} "
                       "y no se puede editar.")
    return True, ""


def guardar(datos: dict, renglones: list[dict], id_usuario, id_reintegro=None):
    """
    Alta o edición de la solicitud.

    renglones: dicts con uid (el del formulario, para los adjuntos), id_detalle
    (o None), id_concepto_gasto, id_afiliado, fecha_gasto, nro_comprobante,
    importe_solicitado, comentario_solicitud.

    Devuelve (id_reintegro, {uid: id_detalle}) para guardar los archivos.
    """
    if not datos.get("id_afiliado"):
        raise ReintegroError("Seleccioná el afiliado titular.")
    if not renglones:
        raise ReintegroError("La solicitud tiene que tener al menos un renglón.")

    total = sum(_dec(r.get("importe_solicitado"), "importe solicitado") for r in renglones)
    if total <= 0:
        raise ReintegroError("El importe total solicitado tiene que ser mayor a cero.")
    if any(_dec(r.get("importe_solicitado")) < 0 for r in renglones):
        raise ReintegroError("Hay un renglón con importe negativo.")

    cbu = "".join(c for c in (datos.get("cbu_destino") or "") if c.isdigit())
    if cbu and len(cbu) != 22:
        raise ReintegroError(f"El CBU tiene {len(cbu)} dígitos: tienen que ser 22.")

    fecha = datos.get("fecha_solicitud") or datetime.date.today()
    if isinstance(fecha, str):
        fecha = datetime.datetime.strptime(fecha, "%Y-%m-%d").date()

    mapa_uid = {}
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            ids_grupo = _ids_grupo_familiar(cur, datos["id_afiliado"])
            for r in renglones:
                if int(r["id_afiliado"]) not in ids_grupo:
                    raise ReintegroError("Hay un renglón con un afiliado que no es del grupo "
                                         "familiar vigente del titular.")
            _validar_bajas_del_mes(cur, renglones)

            if id_reintegro:
                cur.execute("SELECT estado, id_orden_pago FROM c_reintegro_afiliados "
                            "WHERE id = %s FOR UPDATE", (id_reintegro,))
                actual = cur.fetchone()
                se_puede, motivo = editable(actual)
                if not se_puede:
                    raise ReintegroError(motivo)

                # Editar una ya auditada le saca la aprobación y la devuelve a
                # auditoría con los importes en blanco: lo autorizado se
                # resolvió sobre renglones que ya no son estos. Sin esto,
                # corregir un renglón de $10.000 a $200.000 dejaría aprobados
                # $200.000 que nadie miró.
                vuelve = estado_clave(actual["estado"]) not in ("borrador", "en_auditoria")
                if vuelve:
                    cur.execute("""
                        UPDATE c_reintegro_afiliados_detalle
                           SET importe_aprobado = NULL, comentario_autorizacion = NULL
                         WHERE id_reintegro = %s
                    """, (id_reintegro,))

                cur.execute(f"""
                    UPDATE c_reintegro_afiliados
                    SET    id_afiliado = %s, fecha_solicitud = %s, cbu_destino = %s,
                           alias_destino = %s, observaciones = %s, importe_solicitado = %s
                           {", estado = 'en_auditoria', importe_aprobado = NULL,"
                            " fecha_auditoria = NULL, id_usuario_auditoria = NULL,"
                            " fecha_aprobacion = NULL, id_usuario_aprobacion = NULL"
                            if vuelve else ""}
                    WHERE  id = %s
                """, (datos["id_afiliado"], fecha, cbu or None,
                      datos.get("alias_destino") or None, datos.get("observaciones") or None,
                      total, id_reintegro))
            else:
                anio = fecha.year
                cur.execute("""
                    INSERT INTO c_reintegro_afiliados
                        (nro_solicitud, anio, id_afiliado, fecha_solicitud,
                         id_usuario_solicitud, estado, niveles_requeridos,
                         niveles_aprobados, importe_solicitado, moneda,
                         cbu_destino, alias_destino, importado_csv, observaciones)
                    VALUES (%s, %s, %s, %s, %s, 'borrador', %s, 0, %s, 'ARS',
                            %s, %s, 0, %s)
                """, (_nuevo_nro_solicitud(cur, anio), anio, datos["id_afiliado"], fecha,
                      id_usuario, max_nivel(cur), total, cbu or None,
                      datos.get("alias_destino") or None, datos.get("observaciones") or None))
                id_reintegro = cur.lastrowid

            # Detalle: upsert. Borrar todo y volver a insertar perdería los
            # adjuntos, que cuelgan del renglón.
            conservados = []
            for r in renglones:
                id_det = r.get("id_detalle") or None
                valores = (r["id_concepto_gasto"], r["id_afiliado"], r.get("fecha_gasto") or None,
                           r.get("nro_comprobante") or None, _dec(r.get("importe_solicitado")),
                           r.get("comentario_solicitud") or None)
                if id_det:
                    cur.execute("""
                        UPDATE c_reintegro_afiliados_detalle
                        SET    id_concepto_gasto = %s, id_afiliado = %s, fecha_gasto = %s,
                               nro_comprobante = %s, importe_solicitado = %s,
                               comentario_solicitud = %s
                        WHERE  id = %s AND id_reintegro = %s
                    """, valores + (id_det, id_reintegro))
                else:
                    cur.execute("""
                        INSERT INTO c_reintegro_afiliados_detalle
                            (id_concepto_gasto, id_afiliado, fecha_gasto, nro_comprobante,
                             importe_solicitado, comentario_solicitud, id_reintegro)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, valores + (id_reintegro,))
                    id_det = cur.lastrowid
                conservados.append(id_det)
                if r.get("uid"):
                    mapa_uid[r["uid"]] = id_det

            # Los renglones que se quitaron del formulario.
            cur.execute(
                f"DELETE FROM c_reintegro_afiliados_detalle "
                f"WHERE id_reintegro = %s AND id NOT IN ({','.join(['%s'] * len(conservados))})",
                [id_reintegro] + conservados)
        conn.commit()
        return id_reintegro, mapa_uid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def eliminar(id_reintegro) -> list[str]:
    """Borra una solicitud en borrador. Devuelve las rutas de sus adjuntos."""
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            cur.execute("SELECT estado FROM c_reintegro_afiliados WHERE id = %s FOR UPDATE",
                        (id_reintegro,))
            row = cur.fetchone()
            if not row:
                raise ReintegroError("La solicitud no existe.")
            if estado_clave(row["estado"]) != "borrador":
                raise ReintegroError("Solo se eliminan solicitudes en borrador.")
            cur.execute("""
                SELECT ad.ruta_archivo
                  FROM c_reintegro_afiliados_detalle_adjunto ad
                  JOIN c_reintegro_afiliados_detalle d ON d.id = ad.id_detalle
                 WHERE d.id_reintegro = %s
            """, (id_reintegro,))
            rutas = [f["ruta_archivo"] for f in cur.fetchall()]
            cur.execute("DELETE FROM c_reintegro_afiliados WHERE id = %s", (id_reintegro,))
        conn.commit()
        return rutas
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# =============================================================================
# Adjuntos
# =============================================================================

ESTADOS_CON_ADJUNTOS = ("borrador", "en_auditoria")


def registrar_adjunto(id_detalle, ruta: str, nombre: str, id_usuario):
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.estado
                FROM   c_reintegro_afiliados_detalle d
                JOIN   c_reintegro_afiliados r ON r.id = d.id_reintegro
                WHERE  d.id = %s
            """, (id_detalle,))
            row = cur.fetchone()
            if not row:
                raise ReintegroError("El renglón no existe.")
            # Una aprobada que se edita vuelve a auditoría en el mismo guardado,
            # antes de que lleguen los archivos: por eso basta con estos dos.
            if estado_clave(row["estado"]) not in ESTADOS_CON_ADJUNTOS:
                raise ReintegroError(f"No se pueden agregar comprobantes a una solicitud "
                                     f"{estado_label(row['estado']).lower()}.")
            cur.execute("""
                INSERT INTO c_reintegro_afiliados_detalle_adjunto
                    (id_detalle, ruta_archivo, nombre_archivo, creado, id_usuario)
                VALUES (%s, %s, %s, NOW(), %s)
            """, (id_detalle, ruta, nombre, id_usuario))
            nuevo = cur.lastrowid
        conn.commit()
        return nuevo
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def eliminar_adjunto(id_adjunto) -> tuple[str, int]:
    """Borra el registro. Devuelve (ruta del archivo, id de la solicitud)."""
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ad.ruta_archivo, r.estado, r.id AS id_reintegro
                FROM   c_reintegro_afiliados_detalle_adjunto ad
                JOIN   c_reintegro_afiliados_detalle d ON d.id = ad.id_detalle
                JOIN   c_reintegro_afiliados r         ON r.id = d.id_reintegro
                WHERE  ad.id = %s
            """, (id_adjunto,))
            row = cur.fetchone()
            if not row:
                raise ReintegroError("El comprobante no existe.")
            if estado_clave(row["estado"]) not in ESTADOS_CON_ADJUNTOS:
                raise ReintegroError("En este estado ya no se borran comprobantes.")
            cur.execute("DELETE FROM c_reintegro_afiliados_detalle_adjunto WHERE id = %s",
                        (id_adjunto,))
        conn.commit()
        return row["ruta_archivo"], row["id_reintegro"]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# =============================================================================
# Auditoría
# =============================================================================

def _sin_documentacion(cur, id_reintegro) -> bool:
    """Si la solicitud no tiene ni un comprobante adjunto (al enviar y al auditar)."""
    cur.execute("""
        SELECT COUNT(*) AS n
        FROM   c_reintegro_afiliados_detalle d
        JOIN   c_reintegro_afiliados_detalle_adjunto ad ON ad.id_detalle = d.id
        WHERE  d.id_reintegro = %s
    """, (id_reintegro,))
    return not cur.fetchone()["n"]


def enviar_a_auditoria(id_reintegro) -> bool:
    """
    borrador → en_auditoria. Devuelve True si va sin comprobantes.

    La falta de documentación no frena el envío: hay reintegros que se
    resuelven con el papel o que la reciben después. Quien decide si alcanza
    es la auditoría, que ve renglón por renglón cuáles no tienen comprobante.
    """
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            cur.execute("SELECT estado FROM c_reintegro_afiliados WHERE id = %s FOR UPDATE",
                        (id_reintegro,))
            row = cur.fetchone()
            if not row:
                raise ReintegroError("La solicitud no existe.")
            if estado_clave(row["estado"]) != "borrador":
                raise ReintegroError("Solo se envían a auditoría las solicitudes en borrador.")
            cur.execute("SELECT COUNT(*) AS n FROM c_reintegro_afiliados_detalle "
                        "WHERE id_reintegro = %s", (id_reintegro,))
            if not cur.fetchone()["n"]:
                raise ReintegroError("La solicitud no tiene renglones.")
            sin_respaldo = _sin_documentacion(cur, id_reintegro)
            cur.execute("UPDATE c_reintegro_afiliados SET estado = 'en_auditoria' WHERE id = %s",
                        (id_reintegro,))
        conn.commit()
        return sin_respaldo
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def auditar(id_reintegro, id_usuario, importes: dict, comentarios: dict | None = None,
            observaciones: str | None = None) -> Decimal:
    """
    Cierra la auditoría: fija el importe reconocido de cada renglón y deja la
    solicitud APROBADA, lista para la orden de pago.

    importes:    {id_detalle: importe}. Lo que no venga se reconoce entero; en 0
                 el renglón queda rechazado.
    comentarios: {id_detalle: comentario}
    Devuelve el total autorizado.
    """
    comentarios = comentarios or {}
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            cur.execute("SELECT estado FROM c_reintegro_afiliados WHERE id = %s FOR UPDATE",
                        (id_reintegro,))
            r = cur.fetchone()
            if not r:
                raise ReintegroError("La solicitud no existe.")
            if estado_clave(r["estado"]) != "en_auditoria":
                raise ReintegroError(f"La solicitud está «{estado_label(r['estado'])}» "
                                     "y no en auditoría.")

            cur.execute("SELECT id, importe_solicitado FROM c_reintegro_afiliados_detalle "
                        "WHERE id_reintegro = %s", (id_reintegro,))
            renglones = cur.fetchall()
            if not renglones:
                raise ReintegroError("La solicitud no tiene renglones.")

            total = Decimal("0.00")
            for d in renglones:
                aprobado = _dec(importes.get(d["id"], d["importe_solicitado"]), "importe reconocido")
                if aprobado < 0:
                    raise ReintegroError("El importe reconocido no puede ser negativo.")
                if aprobado > _dec(d["importe_solicitado"]):
                    raise ReintegroError("El importe reconocido no puede superar al solicitado "
                                         f"({_dec(d['importe_solicitado'])}).")
                cur.execute("""
                    UPDATE c_reintegro_afiliados_detalle
                    SET    importe_aprobado = %s, comentario_autorizacion = %s
                    WHERE  id = %s
                """, (aprobado, (comentarios.get(d["id"]) or "").strip()[:250] or None, d["id"]))
                total += aprobado

            if total <= 0:
                raise ReintegroError("El total reconocido es cero. Si no corresponde "
                                     "reintegro, usá «Rechazar solicitud».")

            # Aprobar sin comprobantes se permite, pero queda escrito: es lo que
            # se lee cuando alguien pregunta por qué se pagó.
            if _sin_documentacion(cur, id_reintegro):
                aviso = "Auditada sin documentación de respaldo adjunta."
                observaciones = (f"{aviso} {observaciones.strip()}"
                                 if (observaciones or "").strip() else aviso)

            cur.execute("""
                UPDATE c_reintegro_afiliados
                SET    estado = 'aprobada', importe_aprobado = %s,
                       fecha_auditoria = CURDATE(), id_usuario_auditoria = %s,
                       fecha_aprobacion = CURDATE(), id_usuario_aprobacion = %s,
                       observaciones = CASE WHEN %s IS NULL OR %s = '' THEN observaciones
                            ELSE LEFT(CONCAT_WS(' | ', NULLIF(TRIM(observaciones), ''),
                                                CONCAT('Auditoría: ', %s)), 500) END
                WHERE  id = %s
            """, (total, id_usuario, id_usuario,
                  observaciones, observaciones, observaciones, id_reintegro))
        conn.commit()
        return total
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rechazar(id_reintegro, id_usuario, motivo: str) -> None:
    """Rechazo total en auditoría. Cierra el trámite."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise ReintegroError("Indicá el motivo del rechazo.")
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            cur.execute("SELECT estado FROM c_reintegro_afiliados WHERE id = %s FOR UPDATE",
                        (id_reintegro,))
            r = cur.fetchone()
            if not r:
                raise ReintegroError("La solicitud no existe.")
            if estado_clave(r["estado"]) != "en_auditoria":
                raise ReintegroError("Solo se rechazan solicitudes en auditoría.")
            cur.execute("""
                UPDATE c_reintegro_afiliados_detalle
                SET    importe_aprobado = 0, comentario_autorizacion = %s
                WHERE  id_reintegro = %s
            """, (motivo[:250], id_reintegro))
            cur.execute("""
                UPDATE c_reintegro_afiliados
                SET    estado = 'rechazada', motivo_rechazo = %s, importe_aprobado = 0,
                       fecha_auditoria = CURDATE(), id_usuario_auditoria = %s
                WHERE  id = %s
            """, (motivo[:250], id_usuario, id_reintegro))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def anular(id_reintegro, id_usuario, motivo: str) -> None:
    """
    Anula una solicitud enviada o aprobada que todavía no tiene orden.

    En gestion_adm la función existía pero ninguna pantalla la llamaba: una
    aprobada por error quedaba esperando la orden de pago para siempre.
    """
    motivo = (motivo or "").strip()
    if not motivo:
        raise ReintegroError("Indicá el motivo de la anulación.")
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            cur.execute("SELECT estado, id_orden_pago FROM c_reintegro_afiliados "
                        "WHERE id = %s FOR UPDATE", (id_reintegro,))
            r = cur.fetchone()
            if not r:
                raise ReintegroError("La solicitud no existe.")
            if r["id_orden_pago"]:
                raise ReintegroError("La solicitud ya generó una orden de pago: "
                                     "primero hay que anular la orden.")
            estado = estado_clave(r["estado"])
            if estado in ESTADOS_CERRADOS:
                raise ReintegroError(f"La solicitud ya está {estado_label(estado).lower()}.")
            if estado in ("con_orden", "pago_parcial"):
                raise ReintegroError("La solicitud ya tiene orden de pago.")
            if estado == "borrador":
                raise ReintegroError("Un borrador no se anula: se elimina.")
            cur.execute("""
                UPDATE c_reintegro_afiliados
                SET    estado = 'anulada', fecha_anulacion = CURDATE(),
                       id_usuario_anulacion = %s,
                       observaciones = LEFT(CONCAT_WS(' | ', NULLIF(TRIM(observaciones), ''),
                                                      CONCAT('Anulación: ', %s)), 500)
                WHERE  id = %s
            """, (id_usuario, motivo, id_reintegro))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# =============================================================================
# Órdenes de pago
# =============================================================================

def listar_con_saldo() -> list[dict]:
    """
    Lo que queda por pagar: aprobadas sin orden y las que cobraron una parte.

    El criterio es «tiene saldo», no «no tiene orden»: con el pago parcial un
    reintegro puede tener orden y seguir debiéndose.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT v.*, s.aprobado, s.en_ordenes, s.saldo
                  FROM v_reintegros_afiliados v
                  JOIN v_reintegro_saldo s ON s.id_reintegro = v.id
                 WHERE v.estado IN ({",".join(["%s"] * len(ESTADOS_PAGABLES))})
                   AND s.saldo > 0
                 ORDER BY v.titular, v.nro_solicitud
            """, ESTADOS_PAGABLES)
            filas = cur.fetchall()
            _poner_clase(filas, _clases(cur))
    for r in filas:
        r["estado"] = estado_clave(r["estado"])
    return filas


def generar_ordenes_pago(ids_reintegro: list, id_usuario,
                         importes: dict | None = None) -> list[dict]:
    """
    Genera las órdenes de pago: UNA por titular, con todos los reintegros de la
    selección que son suyos.

    `importes` es {id_reintegro: importe}; lo que no venga se paga por su saldo.
    El importe se valida contra el saldo —lo aprobado menos lo que ya está en
    órdenes vigentes—, no contra lo aprobado: si no, el segundo pago de uno ya
    cobrado a medias se pagaría dos veces.

    El reintegro queda en `pago_parcial` mientras le sobre saldo y en
    `con_orden` cuando queda en cero.

    Devuelve [{id_orden, nro_orden, titular, cuil, reintegros, importe}, ...]
    """
    ids = sorted({int(i) for i in (ids_reintegro or [])})
    if not ids:
        raise ReintegroError("No seleccionaste ningún reintegro.")
    importes = {int(k): _dec(v) for k, v in (importes or {}).items()}

    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            # `FOR UPDATE OF r`: bloquear solo los reintegros, no la vista de
            # saldos ni las tablas de las que sale. Alcanza para que dos
            # personas no generen órdenes sobre el mismo reintegro a la vez.
            cur.execute(f"""
                SELECT r.id, r.nro_solicitud, r.estado, r.moneda,
                       r.cbu_destino, r.alias_destino, r.id_afiliado,
                       a.cuil, {NOMBRE} AS titular,
                       s.aprobado, s.en_ordenes, s.saldo
                FROM   c_reintegro_afiliados r
                JOIN   p_afiliados a ON a.id_afiliado = r.id_afiliado
                JOIN   v_reintegro_saldo s ON s.id_reintegro = r.id
                WHERE  r.id IN ({",".join(["%s"] * len(ids))})
                ORDER BY r.id_afiliado, r.id
                FOR UPDATE OF r
            """, ids)
            filas = cur.fetchall()
            if len(filas) != len(ids):
                raise ReintegroError("Alguno de los reintegros elegidos no existe.")

            grupos: dict = {}
            for r in filas:
                if estado_clave(r["estado"]) not in ESTADOS_PAGABLES:
                    raise ReintegroError(f"{r['nro_solicitud']}: está «{estado_label(r['estado'])}» "
                                         "y no se puede pagar.")
                saldo = _dec(r["saldo"])
                if saldo <= 0:
                    raise ReintegroError(f"{r['nro_solicitud']}: ya está pagado entero.")
                pedido = importes.get(r["id"], saldo)
                if pedido <= 0:
                    raise ReintegroError(f"{r['nro_solicitud']}: el importe a pagar tiene que "
                                         "ser mayor a cero.")
                if pedido > saldo:
                    raise ReintegroError(f"{r['nro_solicitud']}: se quiere pagar "
                                         f"$ {_pesos(pedido)} y el saldo es $ {_pesos(saldo)}.")
                r["a_pagar"] = pedido
                grupos.setdefault(r["id_afiliado"], []).append(r)

            anio = datetime.date.today().year
            niveles = max_nivel(cur)
            generadas = []
            for renglones in grupos.values():
                cabeza = renglones[0]
                total = sum(r["a_pagar"] for r in renglones)
                # «(parcial)» en el número: el que mira la orden tiene que ver
                # que quedó saldo sin abrir el reintegro.
                nros = ", ".join(r["nro_solicitud"]
                                 + (" (parcial)" if r["a_pagar"] < _dec(r["saldo"]) else "")
                                 for r in renglones)
                cbu   = next((r["cbu_destino"] for r in reversed(renglones) if r["cbu_destino"]), None)
                alias = next((r["alias_destino"] for r in reversed(renglones) if r["alias_destino"]), None)

                nro_orden = _nuevo_nro_orden(cur)
                cur.execute("""
                    INSERT INTO pago_ordenes
                        (nro_orden, clase, anio, fecha, estado, importe_total, moneda,
                         niveles_requeridos, niveles_aprobados, observaciones,
                         id_usuario_creacion, creado, actualizado)
                    VALUES (%s, %s, %s, CURDATE(), 'borrador', %s, %s, %s, 0, %s, %s, NOW(), NOW())
                """, (nro_orden, CLASE_ORDEN, anio, total, cabeza["moneda"], niveles,
                      f"Reintegro a afiliado {cabeza['titular']} "
                      f"(CUIL {cabeza['cuil'] or '-'}) — solicitudes {nros}",
                      id_usuario))
                id_orden = cur.lastrowid

                for r in renglones:
                    queda = _dec(r["saldo"]) - r["a_pagar"]
                    cur.execute("""
                        INSERT INTO pago_ordenes_reintegro_det
                            (id_orden, id_reintegro, cuil, nombre, id_afiliado,
                             descripcion, importe, moneda, cbu_destino, alias_destino)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (id_orden, r["id"], r["cuil"] or "", r["titular"], r["id_afiliado"],
                          f"Reintegro {r['nro_solicitud']}"
                          + (f" — pago parcial, queda $ {_pesos(queda)}" if queda > 0 else ""),
                          r["a_pagar"], r["moneda"],
                          r["cbu_destino"] or cbu, r["alias_destino"] or alias))
                    # `importe_aprobado` no se toca: es lo autorizado, no cambia
                    # porque se pague en cuotas. `id_orden_pago` apunta a la
                    # última orden; la relación entera vive en el detalle.
                    cur.execute("UPDATE c_reintegro_afiliados SET id_orden_pago = %s, estado = %s "
                                "WHERE id = %s",
                                (id_orden, "pago_parcial" if queda > 0 else "con_orden", r["id"]))

                generadas.append({"id_orden": id_orden, "nro_orden": nro_orden,
                                  "titular": cabeza["titular"], "cuil": cabeza["cuil"],
                                  "reintegros": len(renglones), "importe": total})
        conn.commit()
        return generadas
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _pesos(valor) -> str:
    entero, _, dec = f"{float(valor or 0):,.2f}".partition(".")
    return f"{entero.replace(',', '.')},{dec}"


ESTADOS_ORDEN = [
    ("borrador",             "Borrador"),
    ("pendiente_aprobacion", "Pendiente de aprobación"),
    ("aprobada",             "Aprobada"),
    ("rechazada",            "Rechazada"),
    ("pagada",               "Pagada"),
    ("anulada",              "Anulada"),
]
ESTADOS_ORDEN_LABEL = dict(ESTADOS_ORDEN)
ESTADOS_ORDEN_TIPO = {"borrador": "neutro", "pendiente_aprobacion": "warn", "aprobada": "info",
                      "rechazada": "danger", "pagada": "ok", "anulada": "neutro"}


def listar_ordenes() -> list[dict]:
    """
    Las órdenes de pago de reintegros, con beneficiario, solicitudes y lo pagado.
    Todas: se filtran en la grilla, como el resto.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT o.id, o.nro_orden, o.fecha, o.estado, o.importe_total,
                       o.niveles_requeridos, o.niveles_aprobados,
                       u.nombre AS nombre_usuario,
                       (SELECT GROUP_CONCAT(DISTINCT rd.nombre SEPARATOR ' / ')
                          FROM pago_ordenes_reintegro_det rd WHERE rd.id_orden = o.id) AS beneficiario,
                       (SELECT GROUP_CONCAT(DISTINCT rd.cuil SEPARATOR ' / ')
                          FROM pago_ordenes_reintegro_det rd WHERE rd.id_orden = o.id) AS cuil,
                       (SELECT GROUP_CONCAT(DISTINCT rd.cbu_destino SEPARATOR ' / ')
                          FROM pago_ordenes_reintegro_det rd WHERE rd.id_orden = o.id) AS cbu,
                       (SELECT GROUP_CONCAT(CONCAT(r2.id, ':', r2.nro_solicitud)
                                            ORDER BY r2.nro_solicitud SEPARATOR ',')
                          FROM pago_ordenes_reintegro_det rd
                          JOIN c_reintegro_afiliados r2 ON r2.id = rd.id_reintegro
                         WHERE rd.id_orden = o.id) AS solicitudes,
                       (SELECT COALESCE(SUM(pp.importe_total), 0)
                          FROM pago_pagos pp
                         WHERE pp.id_orden = o.id AND pp.estado <> 'anulado') AS pagado
                FROM   pago_ordenes o
                LEFT JOIN s_usuarios u ON u.id = o.id_usuario_creacion
                WHERE  o.clase = %s
                ORDER BY o.fecha DESC, o.id DESC
            """, (CLASE_ORDEN,))
            filas = cur.fetchall()
    for o in filas:
        o["solicitudes"] = [dict(zip(("id", "nro"), s.split(":", 1)))
                            for s in (o["solicitudes"] or "").split(",") if ":" in s]
    return filas
