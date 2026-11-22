"""
fisca_novedades.py — Altas y bajas de afiliados que informa la empresa por su
enlace (pedido del 15/11/2026).

La empresa entra con su enlace personal (fisca_lsd.py, /empresas/<token>), ve
su NÓMINA —los afiliados que según el padrón trabajan ahí— y puede informar:

  · el ALTA de un CUIL que corresponde cuota, con la fecha de alta en la
    empresa y, si quiere, la ficha de afiliación firmada (PDF o imagen). Si el
    CUIL no está en el padrón, con apellido y nombre;
  · la BAJA de un CUIL que el padrón tiene activo en la empresa, con la fecha.

Las dos quedan PENDIENTES (decidido el 15/11/2026): el sindicato las aprueba o
las rechaza en Fiscalización de Cuotas → Presentaciones LSD, y recién al
aprobar cambia el padrón:

  · alta aprobada: si el CUIL no está en el padrón se crea el afiliado (titular,
    con la fecha de alta); se abre la relación laboral con el empleador; la
    ficha adjunta pasa a la documentación del afiliado («Ficha de afiliación»).
    Un afiliado del padrón dado de baja no se reactiva solo: se avisa.
  · baja aprobada: se cierra la relación laboral con esa fecha. La afiliación
    no se toca (puede seguir afiliado con otro empleador).

Todo con su renglón en la auditoría del afiliado (p_afiliados_movimientos).

LA CUOTA DEL MES ya toma el alta pendiente: la planilla de la presentación (por
archivo o cargada a mano) la incluye desde su fecha de alta, con fuente «alta».
La baja pendiente no cambia la cuota hasta que se apruebe.

La ficha de afiliación se guarda en SIND_ADJUNTOS/novedades_empresa/ con un
nombre generado; al aprobar se copia a la documentación del afiliado.
"""

from __future__ import annotations

import datetime
import re
import uuid
from pathlib import Path

import almacenamiento
import documentacion as DOC

SQL_ESQUEMA = "sql/fisca_novedades_empresa_20261115.sql"
TIPOS = {"alta": "Alta", "baja": "Baja"}
ESTADOS = {"pendiente": ("Pendiente", "warn"), "aprobada": ("Aprobada", "ok"),
           "rechazada": ("Rechazada", "danger"), "retirada": ("Retirada", "neutro")}
#: Hasta cuántos días adelante se acepta una fecha de alta o de baja.
DIAS_FUTURO = 31
PREFIJOS_PERSONA = ("20", "23", "24", "27")


class ErrorNovedad(ValueError):
    """Lo que impide informar o resolver una novedad: se muestra tal cual."""


def _digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def cuil_valido(c: str) -> bool:
    c = _digitos(c)
    if len(c) != 11:
        return False
    resto = sum(int(c[i]) * p for i, p in enumerate((5, 4, 3, 2, 7, 6, 5, 4, 3, 2))) % 11
    dv = 0 if resto == 0 else (9 if resto == 1 else 11 - resto)
    return dv == int(c[10])


def fecha_de(texto) -> datetime.date | None:
    """'2026-11-15' o '15/11/2026' → date."""
    t = (texto or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(t, fmt).date()
        except ValueError:
            pass
    return None


def falta_esquema(cur) -> bool:
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.tables
                    WHERE table_schema = DATABASE() AND table_name = 'fisca_novedad_empresa'""")
    return not (cur.fetchone() or {}).get("n")


# ─────────────────────────────────────────────────────────────────────────────
# Lecturas
# ─────────────────────────────────────────────────────────────────────────────

def nomina(cur, cuit: str, hoy: datetime.date | None = None) -> list[dict]:
    """
    Los afiliados (titulares) que según el padrón trabajan hoy en la empresa: una
    relación laboral con el CUIT que ya empezó y no terminó (la regla de
    fisca_liquidacion.activos_por_empleador), y la afiliación vigente. Con la
    novedad pendiente de cada uno, si la hay.
    """
    hoy = hoy or datetime.date.today()
    cur.execute("""SELECT a.id_afiliado, a.cuil, a.apellido_nombres, a.fecha_alta AS alta_afiliacion,
                          r.id_relacion, r.fecha_inicio, r.fecha_fin, r.estado
                     FROM p_relaciones_laborales r
                     JOIN p_afiliados a ON a.cuil = r.cuil AND a.cod_parentesco = 0
                    WHERE r.cuit_empleador = %s
                      AND (a.fecha_alta IS NULL OR a.fecha_alta <= %s)
                      AND (a.fecha_baja IS NULL OR a.fecha_baja >= %s)
                      AND (r.fecha_inicio IS NULL OR r.fecha_inicio <= %s)
                      AND (r.fecha_fin >= %s OR (r.fecha_fin IS NULL AND r.estado = 'activa'))
                    ORDER BY a.apellido_nombres, r.fecha_inicio DESC""", (cuit, hoy, hoy, hoy, hoy))
    filas, vistos = [], set()
    for f in cur.fetchall():
        if f["cuil"] in vistos:
            continue
        vistos.add(f["cuil"])
        filas.append(f)
    try:
        pend = pendientes(cur, cuit)
    except Exception as e:                                   # noqa: BLE001
        if "1146" not in str(e):                             # sin la tabla: la nómina igual
            raise
        pend = []
    for f in filas:
        f["baja_pendiente"] = next((n for n in pend if n["tipo"] == "baja" and n["cuil"] == f["cuil"]), None)
    return filas


def novedades(cur, cuit: str | None = None, estado: str | None = None, limite: int = 300) -> list[dict]:
    cond, args = ["1 = 1"], []
    if cuit:
        cond.append("n.cuit = %s"); args.append(cuit)
    if estado:
        cond.append("n.estado = %s"); args.append(estado)
    cur.execute(f"""SELECT n.*, e.id AS id_empresa, e.razon_social, u.nombre AS usuario,
                           a.apellido_nombres AS nombre_padron
                      FROM fisca_novedad_empresa n
                      LEFT JOIN p_empresas e ON e.CUIT = CAST(n.cuit AS UNSIGNED)
                      LEFT JOIN s_usuarios u ON u.id = n.id_usuario
                      LEFT JOIN p_afiliados a ON a.cuil = n.cuil AND a.cod_parentesco = 0
                     WHERE {' AND '.join(cond)}
                     ORDER BY n.estado = 'pendiente' DESC, n.creado DESC, n.id DESC
                     LIMIT {int(limite)}""", args)
    filas = cur.fetchall()
    for f in filas:
        f["nombre"] = f["nombre_padron"] or f["apellido_nombres"] or ""
    return filas


def pendientes(cur, cuit: str) -> list[dict]:
    return [n for n in novedades(cur, cuit=cuit, estado="pendiente")]


def altas_pendientes(cur, cuit: str) -> dict:
    """{cuil: {apellido_nombres, fecha, id}}: las altas pendientes del CUIT, para
    que la cuota del mes las tome. Sin la tabla, ninguna."""
    try:
        cur.execute("""SELECT n.id, n.cuil, n.fecha, COALESCE(a.apellido_nombres, n.apellido_nombres) AS apellido_nombres,
                              a.id_afiliado
                         FROM fisca_novedad_empresa n
                         LEFT JOIN p_afiliados a ON a.cuil = n.cuil AND a.cod_parentesco = 0
                        WHERE n.cuit = %s AND n.tipo = 'alta' AND n.estado = 'pendiente'""", (cuit,))
    except Exception as e:                                   # noqa: BLE001
        if "1146" in str(e):
            return {}
        raise
    return {f["cuil"]: f for f in cur.fetchall()}


def una(cur, id_nov: int, cuit: str | None = None, bloquear: bool = False) -> dict | None:
    cur.execute(f"""SELECT * FROM fisca_novedad_empresa WHERE id = %s {'AND cuit = %s' if cuit else ''}
                    {'FOR UPDATE' if bloquear else ''}""", (id_nov, cuit) if cuit else (id_nov,))
    return cur.fetchone()


def contar_pendientes(cur) -> int:
    try:
        cur.execute("SELECT COUNT(*) AS n FROM fisca_novedad_empresa WHERE estado = 'pendiente'")
    except Exception as e:                                   # noqa: BLE001
        if "1146" in str(e):
            return 0
        raise
    return int((cur.fetchone() or {}).get("n") or 0)


# ─────────────────────────────────────────────────────────────────────────────
# La ficha de afiliación adjunta
# ─────────────────────────────────────────────────────────────────────────────

def _carpeta() -> Path:
    return DOC.base() / "novedades_empresa"


def guardar_ficha(archivo) -> dict | None:
    """Guarda el archivo subido (FileStorage) y devuelve {ficha_nombre,
    ficha_archivo, ficha_bytes, ruta}; None si no se adjuntó nada."""
    if not archivo or not archivo.filename:
        return None
    original = Path(archivo.filename).name.strip() or "ficha"
    ext = Path(original).suffix.lower()
    if ext not in DOC.EXTENSIONES:
        raise ErrorNovedad(f"La ficha de afiliación tiene que ser un PDF o una imagen (JPG, PNG); «{original}» no lo es.")
    carpeta = _carpeta()
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre = uuid.uuid4().hex + ext
    destino = carpeta / nombre
    archivo.save(destino)
    tam = destino.stat().st_size
    if tam == 0 or tam > DOC.MAX_MB * 1024 * 1024:
        destino.unlink(missing_ok=True)
        raise ErrorNovedad(f"La ficha de afiliación {'está vacía' if tam == 0 else f'pesa más de {DOC.MAX_MB} MB'}.")
    # Al bucket: la empresa la sube desde su enlace y alguien del sindicato la
    # abre días después, en otro contenedor. Si la novedad no se graba, quien
    # llama la borra con almacenamiento.borrar().
    almacenamiento.respaldar(destino, tipo_mime=DOC.MIME.get(ext, ""))
    return {"ficha_nombre": original[:255], "ficha_archivo": nombre, "ficha_bytes": tam, "ruta": destino}


def ruta_ficha(nov: dict) -> Path | None:
    if not nov or not nov.get("ficha_archivo") or "/" in nov["ficha_archivo"] or "\\" in nov["ficha_archivo"]:
        return None
    p = almacenamiento.local(_carpeta() / nov["ficha_archivo"])
    return p if p.is_file() else None


# ─────────────────────────────────────────────────────────────────────────────
# Lo que informa la empresa
# ─────────────────────────────────────────────────────────────────────────────

def _validar_fecha(fecha: datetime.date | None, rotulo: str, hoy: datetime.date) -> datetime.date:
    if not fecha:
        raise ErrorNovedad(f"Falta la fecha de {rotulo}, o no es una fecha.")
    if fecha.year < 1950 or fecha > hoy + datetime.timedelta(days=DIAS_FUTURO):
        raise ErrorNovedad(f"La fecha de {rotulo} ({fecha:%d/%m/%Y}) no puede ser de más de {DIAS_FUTURO} días adelante.")
    return fecha


def informar_alta(cur, cuit: str, cuil, apellido_nombres: str, fecha, observaciones: str = "",
                  ficha: dict | None = None, origen: str = "empresa", id_enlace=None, ip=None,
                  hoy: datetime.date | None = None) -> int:
    """Guarda el alta pendiente. `ficha` es lo que devolvió guardar_ficha."""
    hoy = hoy or datetime.date.today()
    cuil = _digitos(cuil)
    if not cuil_valido(cuil):
        raise ErrorNovedad("El CUIL tiene que tener 11 dígitos y verificar el dígito de control.")
    fecha = _validar_fecha(fecha if isinstance(fecha, datetime.date) else fecha_de(fecha), "alta", hoy)
    if any(f["cuil"] == cuil for f in nomina(cur, cuit, hoy)):
        raise ErrorNovedad(f"El CUIL {cuil} ya figura en su nómina: no hace falta informar el alta.")
    if any(n["tipo"] == "alta" and n["cuil"] == cuil for n in pendientes(cur, cuit)):
        raise ErrorNovedad(f"Ya informaron el alta del CUIL {cuil}: está pendiente de revisión del sindicato.")
    cur.execute("SELECT apellido_nombres, cod_parentesco FROM p_afiliados WHERE cuil = %s", (cuil,))
    af = cur.fetchone()
    nombre = " ".join((apellido_nombres or "").split()).upper()[:100]
    if not af and not nombre:
        raise ErrorNovedad(f"El CUIL {cuil} no está en el padrón del sindicato: escriban el apellido y el nombre.")
    cur.execute("""INSERT INTO fisca_novedad_empresa
                     (cuit, tipo, cuil, apellido_nombres, fecha, observaciones, ficha_nombre, ficha_archivo,
                      ficha_bytes, origen, id_enlace, ip)
                   VALUES (%s, 'alta', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (cuit, cuil, nombre or None, fecha, (observaciones or "").strip()[:300] or None,
                 ficha and ficha["ficha_nombre"], ficha and ficha["ficha_archivo"], ficha and ficha["ficha_bytes"],
                 origen, id_enlace, (ip or "")[:45] or None))
    return cur.lastrowid


def informar_baja(cur, cuit: str, cuil, fecha, observaciones: str = "", origen: str = "empresa",
                  id_enlace=None, ip=None, hoy: datetime.date | None = None) -> int:
    hoy = hoy or datetime.date.today()
    cuil = _digitos(cuil)
    fila = next((f for f in nomina(cur, cuit, hoy) if f["cuil"] == cuil), None)
    if not fila:
        raise ErrorNovedad(f"El CUIL {cuil} no figura activo en su nómina.")
    if fila["baja_pendiente"]:
        raise ErrorNovedad(f"Ya informaron la baja del CUIL {cuil}: está pendiente de revisión del sindicato.")
    fecha = _validar_fecha(fecha if isinstance(fecha, datetime.date) else fecha_de(fecha), "baja", hoy)
    if fila["fecha_inicio"] and fecha < fila["fecha_inicio"]:
        raise ErrorNovedad(f"La fecha de baja no puede ser anterior al alta en la empresa ({fila['fecha_inicio']:%d/%m/%Y}).")
    cur.execute("""INSERT INTO fisca_novedad_empresa
                     (cuit, tipo, cuil, fecha, observaciones, origen, id_enlace, ip, id_afiliado, id_relacion)
                   VALUES (%s, 'baja', %s, %s, %s, %s, %s, %s, %s, %s)""",
                (cuit, cuil, fecha, (observaciones or "").strip()[:300] or None, origen, id_enlace,
                 (ip or "")[:45] or None, fila["id_afiliado"], fila["id_relacion"]))
    return cur.lastrowid


def retirar(cur, id_nov: int, cuit: str) -> bool:
    """La empresa retira una novedad que todavía no se revisó."""
    cur.execute("""UPDATE fisca_novedad_empresa SET estado = 'retirada', resuelto = NOW()
                    WHERE id = %s AND cuit = %s AND estado = 'pendiente'""", (id_nov, cuit))
    return cur.rowcount > 0


# ─────────────────────────────────────────────────────────────────────────────
# Lo que resuelve el sindicato
# ─────────────────────────────────────────────────────────────────────────────

def _empresa(cur, cuit: str) -> dict:
    cur.execute("SELECT id, razon_social FROM p_empresas WHERE CUIT = %s", (int(cuit),))
    return cur.fetchone() or {}


def aprobar(cur, id_nov: int, id_usuario: int | None) -> str:
    """Aplica la novedad al padrón. Devuelve qué hizo, para mostrar."""
    import afiliados as AF                   # acá: afiliados no depende de este módulo
    nov = una(cur, id_nov, bloquear=True)
    if not nov or nov["estado"] != "pendiente":
        raise ErrorNovedad("Esa novedad ya no está pendiente.")
    emp = _empresa(cur, nov["cuit"])
    quien = f"{emp.get('razon_social') or nov['cuit']} ({nov['cuit']})"
    obs = f"Novedad {nov['id']} informada por la empresa {quien}"[:300]
    cat = AF._catalogos(cur)
    hechos = []

    if nov["tipo"] == "alta":
        cur.execute("SELECT * FROM p_afiliados WHERE cuil = %s", (nov["cuil"],))
        af = cur.fetchone()
        if af and af["cod_parentesco"] != 0:
            raise ErrorNovedad(f"El CUIL {nov['cuil']} está en el padrón como familiar: resolvelo desde su ficha "
                               "y después rechazá esta novedad.")
        if not af:
            cuil = nov["cuil"]
            persona = cuil[:2] in PREFIJOS_PERSONA
            cur.execute("""INSERT INTO p_afiliados
                             (cod_obra_social, cuit_empleador, cuil_titular, cod_parentesco, cuil, tipo_documento,
                              nro_documento, apellido_nombres, sexo, fecha_alta, activo, observaciones)
                           VALUES ('', %s, %s, 0, %s, 'DU', %s, %s, %s, %s, 1, %s)""",
                        (nov["cuit"], cuil, cuil, cuil[2:10].lstrip("0") if persona else "",
                         (nov["apellido_nombres"] or cuil)[:100], {"20": "M", "27": "F"}.get(cuil[:2]),
                         nov["fecha"], f"Alta informada por la empresa {quien} (novedad {nov['id']})."))
            id_af = cur.lastrowid
            AF._registrar(cur, id_af, cuil, {"activo": None}, {"activo": 1}, {"activo": "Activo"}, "ALTA", cat,
                          vigencia=nov["fecha"], observaciones=obs)
            cur.execute("SELECT * FROM p_afiliados WHERE id_afiliado = %s", (id_af,))
            af = cur.fetchone()
            hechos.append("se dio de alta al afiliado")
        elif af["fecha_baja"] and af["fecha_baja"] < datetime.date.today():
            hechos.append(f"OJO: el afiliado está dado de baja desde el {af['fecha_baja']:%d/%m/%Y}; "
                          "si corresponde, reactivalo desde su ficha")

        cur.execute("""SELECT id_relacion FROM p_relaciones_laborales
                        WHERE cuil = %s AND cuit_empleador = %s
                          AND (fecha_fin IS NULL OR fecha_fin >= %s) AND estado = 'activa' LIMIT 1""",
                    (nov["cuil"], nov["cuit"], nov["fecha"]))
        ya = cur.fetchone()
        if ya:
            id_rel = ya["id_relacion"]
            hechos.append("la relación laboral ya estaba abierta")
        else:
            cur.execute("""INSERT INTO p_relaciones_laborales
                             (cuil, cuit_empleador, id_empleador, fecha_inicio, estado, observaciones)
                           VALUES (%s, %s, %s, %s, 'activa', %s)""",
                        (nov["cuil"], nov["cuit"], emp.get("id"), nov["fecha"],
                         f"Informada por la empresa (novedad {nov['id']})"))
            id_rel = cur.lastrowid
            rel = {"cuit_empleador": nov["cuit"], "razon_social": emp.get("razon_social"),
                   "fecha_inicio": nov["fecha"], "fecha_fin": None}
            AF._registrar(cur, af["id_afiliado"], af["cuil"], {"relacion_laboral": None},
                          {"relacion_laboral": AF._texto_relacion(rel)}, {"relacion_laboral": "Relación laboral"},
                          "MODIFICACION", cat, vigencia=nov["fecha"], observaciones=obs)
            hechos.append(f"se abrió la relación laboral desde el {nov['fecha']:%d/%m/%Y}")
        AF._sincronizar_empleador(cur, af, cat)

        ruta = ruta_ficha(nov)
        if ruta:
            cur.execute("SELECT id_tipo_doc FROM p_tipo_documentacion WHERE codigo = 'ficha_afiliacion' AND activo = 1")
            t = cur.fetchone()
            if t:
                DOC.guardar_copia(cur, "afiliado", af["id_afiliado"], t["id_tipo_doc"], ruta,
                                  nov["ficha_nombre"] or ruta.name, obs, AF._usuario())
                hechos.append("la ficha de afiliación pasó a su documentación")
        cur.execute("""UPDATE fisca_novedad_empresa SET estado = 'aprobada', resuelto = NOW(), id_usuario = %s,
                              id_afiliado = %s, id_relacion = %s, resultado = %s WHERE id = %s""",
                    (id_usuario, af["id_afiliado"], id_rel, "; ".join(hechos)[:300], id_nov))
    else:
        cur.execute("SELECT * FROM p_relaciones_laborales WHERE id_relacion = %s FOR UPDATE", (nov["id_relacion"],))
        rel = cur.fetchone()
        if not rel or rel["cuit_empleador"] != nov["cuit"]:
            cur.execute("""SELECT * FROM p_relaciones_laborales WHERE cuil = %s AND cuit_empleador = %s
                             AND (fecha_fin IS NULL OR fecha_fin >= %s) ORDER BY fecha_inicio DESC LIMIT 1""",
                        (nov["cuil"], nov["cuit"], nov["fecha"]))
            rel = cur.fetchone()
        if not rel:
            raise ErrorNovedad("En el padrón ya no hay una relación laboral abierta de ese CUIL con la empresa.")
        if rel["fecha_inicio"] and nov["fecha"] < rel["fecha_inicio"]:
            raise ErrorNovedad("La fecha de baja es anterior al inicio de la relación laboral.")
        estado = "activa" if nov["fecha"] >= datetime.date.today() else "inactiva"
        cur.execute("UPDATE p_relaciones_laborales SET fecha_fin = %s, estado = %s WHERE id_relacion = %s",
                    (nov["fecha"], estado, rel["id_relacion"]))
        cur.execute("SELECT * FROM p_afiliados WHERE cuil = %s AND cod_parentesco = 0", (nov["cuil"],))
        af = cur.fetchone()
        if af:
            antes = dict(rel, razon_social=emp.get("razon_social"))
            AF._registrar(cur, af["id_afiliado"], af["cuil"], {"relacion_laboral": AF._texto_relacion(antes)},
                          {"relacion_laboral": AF._texto_relacion(dict(antes, fecha_fin=nov["fecha"]))},
                          {"relacion_laboral": "Relación laboral"}, "MODIFICACION", cat, observaciones=obs)
            AF._sincronizar_empleador(cur, af, cat)
        hechos.append(f"se cerró la relación laboral el {nov['fecha']:%d/%m/%Y}")
        cur.execute("""UPDATE fisca_novedad_empresa SET estado = 'aprobada', resuelto = NOW(), id_usuario = %s,
                              id_afiliado = %s, id_relacion = %s, resultado = %s WHERE id = %s""",
                    (id_usuario, af and af["id_afiliado"], rel["id_relacion"], "; ".join(hechos)[:300], id_nov))
    return "; ".join(hechos)


def rechazar(cur, id_nov: int, motivo: str, id_usuario: int | None) -> None:
    motivo = " ".join((motivo or "").split())
    if not motivo:
        raise ErrorNovedad("Escribí el motivo del rechazo: la empresa lo ve.")
    cur.execute("""UPDATE fisca_novedad_empresa SET estado = 'rechazada', motivo = %s, resuelto = NOW(),
                          id_usuario = %s WHERE id = %s AND estado = 'pendiente'""", (motivo[:300], id_usuario, id_nov))
    if not cur.rowcount:
        raise ErrorNovedad("Esa novedad ya no está pendiente.")
