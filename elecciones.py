"""
elecciones.py — Elecciones: configuración, padrón electoral y mesa de votación
(pedido del 18/11/2026: «configurar fecha de elecciones con motivo de elección
y el día de la votación ir marcando el afiliado si vino a votar»).

LA ELECCIÓN (`el_eleccion`)
Motivo, día de la votación, lugar y horario (opcionales), fecha de corte del
padrón y antigüedad mínima en el gremio. Estados: vigente → cerrada (el día
terminó: ya no se marca nada; el Administrador la puede reabrir) o anulada
(con motivo).

EL PADRÓN ELECTORAL (`el_padron`)
Una FOTO del padrón de afiliados al generarlo: los cambios posteriores del
padrón no la tocan. Entra el afiliado (= titular, `cod_parentesco = 0`, como
en las métricas) que a la fecha de corte:
  · tenía el alta hecha (sin fecha de alta entra solo si no se pide antigüedad),
  · no estaba de baja (sin baja y activo, o con la baja posterior al corte),
  · tenía la antigüedad mínima, si se pide (alta hasta el corte − N meses).
Lleva número de orden (alfabético), documento, CUIL, empleador y alta. Se
vuelve a generar mientras nadie votó (se pierden los agregados a mano). Se le
agrega a alguien a mano (un titular, con motivo) o se lo quita (sin voto, con
motivo); todo queda en `el_padron_mov`.

LA MESA DE VOTACIÓN
Se busca al afiliado por documento, CUIL, número de orden o apellido, y se
registra que votó: cuándo y quién lo marcó. Varias mesas a la vez: el UPDATE
solo marca a quien no votó, así dos marcas del mismo no se pisan (la segunda
avisa quién y a qué hora). Quitar un voto pide motivo. Se marca el DÍA de la
votación; fuera de ese día solo el Administrador, con el aviso.

DESDE EL PADRÓN ELECTORAL (pedido del 18/11/2026): la ficha de la elección
tiene en cada fila el botón «Marcar que votó», que anda CUALQUIER DÍA (antes,
el mismo o después de la votación): es la carga posterior de un acta o de una
planilla en papel. Lo usa quien tiene la opción «Elecciones y Padrón»
(Administrador y Supervisor). Pide la elección vigente y el padrón generado:
cerrada, el Administrador la reabre. Fuera del día de la votación el
movimiento lo dice («cargado desde el padrón el …») y la grilla muestra cuándo
se cargó, no una hora de voto que nadie anotó. Quien no está en el padrón electoral sale con el
porqué (familiar, de baja, alta posterior al corte, sin la antigüedad).

OSEDA (pedido del 18/11/2026): el padrón electoral dice de cada afiliado si
tiene OSEDA HOY (titular o familiar vigente en el padrón de OSEDA, en vivo de
contable en Railway, `contable_oseda.padron_oseda_por_cuil`); no es parte de
la foto. Si Railway no responde, la columna sale con «—» y el aviso.

Pantallas (blueprint `elecciones`, /elecciones; sql/elecciones_20261118.sql,
menú 130-132):
  /elecciones                       listado (Administrador y Supervisor)
  /elecciones/nueva                 alta
  /elecciones/<id>                  ficha: datos, padrón, movimientos; POST acciones
  /elecciones/<id>/api_votar        «Marcar que votó» desde el padrón (JSON), cualquier día
  /elecciones/votacion              la mesa (también Operador): elige la elección del día
  /elecciones/votacion/<id>         la mesa de una elección
  /elecciones/votacion/<id>/api_buscar, api_votar, api_quitar_voto, api_estado   (JSON)
"""

from __future__ import annotations

import datetime
import logging
import re

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

import contable_oseda
from db import get_connection, puede, tiene_rol, usuario_actual, validasesion

log = logging.getLogger(__name__)

elecciones_bp = Blueprint("elecciones", __name__, url_prefix="/elecciones")

SQL_ESQUEMA = "sql/elecciones_20261118.sql"
URL_ABM = "/elecciones"
URL_MESA = "/elecciones/votacion"
#: Cuántos resultados devuelve la búsqueda de la mesa.
MAX_RESULTADOS = 25

ESTADOS = {"vigente": ("Vigente", "ok"), "cerrada": ("Cerrada", "neutro"), "anulada": ("Anulada", "danger")}


class ErrorEleccion(ValueError):
    """Un error de validación: el texto va directo a la pantalla."""


# =============================================================================
# Reglas (sin base: lo prueba tests/test_elecciones.py)
# =============================================================================

def restar_meses(fecha: datetime.date, meses: int) -> datetime.date:
    """La misma fecha N meses antes; el 31 cae al último día del mes si no lo tiene."""
    total = fecha.year * 12 + fecha.month - 1 - int(meses or 0)
    anio, mes = divmod(total, 12)
    mes += 1
    sig = datetime.date(anio + (mes == 12), mes % 12 + 1, 1)
    ultimo = (sig - datetime.timedelta(days=1)).day
    return datetime.date(anio, mes, min(fecha.day, ultimo))


def corte_antiguedad(el: dict) -> datetime.date | None:
    """Hasta qué fecha de alta se tiene la antigüedad pedida (None: no se pide)."""
    meses = int(el.get("antiguedad_meses") or 0)
    return restar_meses(el["fecha_padron"], meses) if meses > 0 else None


def puede_marcar(el: dict, hoy: datetime.date, es_admin: bool) -> tuple[bool, str | None]:
    """(se puede registrar votos, aviso o motivo). Fuera del día, solo el Administrador."""
    if el["estado"] == "anulada":
        return False, "La elección está anulada."
    if el["estado"] == "cerrada":
        return False, "La elección está cerrada: ya no se registran votos."
    if not el.get("padron_generado"):
        return False, "Todavía no se generó el padrón electoral."
    if el["fecha_votacion"] == hoy:
        return True, None
    if es_admin:
        cuando = "todavía no llegó" if el["fecha_votacion"] > hoy else "ya pasó"
        return True, (f"El día de la votación ({el['fecha_votacion']:%d/%m/%Y}) {cuando}: "
                      "registrás votos como Administrador (carga posterior o prueba).")
    return False, f"Los votos se registran el día de la votación ({el['fecha_votacion']:%d/%m/%Y})."


def puede_marcar_padron(el: dict) -> tuple[bool, str | None]:
    """(se puede marcar desde el padrón electoral, motivo si no). Cualquier día."""
    if el["estado"] == "anulada":
        return False, "La elección está anulada."
    if el["estado"] == "cerrada":
        return False, "La elección está cerrada: para marcar votos, el Administrador la reabre."
    if not el.get("padron_generado"):
        return False, "Todavía no se generó el padrón electoral."
    return True, None


def detalle_carga(el: dict, hoy: datetime.date) -> str | None:
    """Lo que agrega al movimiento un voto marcado desde el padrón fuera del día."""
    if el["fecha_votacion"] == hoy:
        return None
    return (f"cargado desde el padrón el {hoy:%d/%m/%Y} "
            f"(votación del {el['fecha_votacion']:%d/%m/%Y})")


def partir_busqueda(q: str) -> tuple[str, list[str]]:
    """(dígitos, palabras). «20-12345678-3» → dígitos; «perez juan» → palabras."""
    q = (q or "").strip()
    sin_signos = re.sub(r"[\s.\-/]", "", q)
    if sin_signos.isdigit():
        return sin_signos, []
    return "", [p for p in re.split(r"\s+", q) if len(p) >= 2][:5]


def es_titular(cod_parentesco) -> bool:
    """El parentesco 0 es el titular (llega como número o como texto)."""
    return cod_parentesco is None or str(cod_parentesco).strip() in ("0", "00", "")


def por_que_no_esta(afi: dict, el: dict) -> str:
    """Por qué un afiliado del padrón de afiliados no está en el padrón electoral."""
    if not es_titular(afi.get("cod_parentesco")):
        return "es familiar a cargo: vota el titular"
    corte = el["fecha_padron"]
    if afi.get("fecha_baja") and afi["fecha_baja"] <= corte:
        return f"estaba de baja al corte del padrón (baja {afi['fecha_baja']:%d/%m/%Y})"
    if afi.get("fecha_baja") is None and not afi.get("activo"):
        return "está de baja en el padrón"
    if afi.get("fecha_alta") and afi["fecha_alta"] > corte:
        return f"el alta ({afi['fecha_alta']:%d/%m/%Y}) es posterior al corte del padrón ({corte:%d/%m/%Y})"
    ca = corte_antiguedad(el)
    if ca:
        if not afi.get("fecha_alta"):
            return "no tiene fecha de alta y la elección pide antigüedad"
        if afi["fecha_alta"] > ca:
            return f"no tiene la antigüedad pedida ({el['antiguedad_meses']} meses: alta hasta el {ca:%d/%m/%Y})"
    return "no estaba cuando se generó el padrón: se lo puede agregar a mano"


def resumen(total: int, votaron: int) -> dict:
    return {"padron": total, "votaron": votaron, "faltan": total - votaron,
            "porc": round(votaron * 100 / total, 1) if total else 0.0}


# =============================================================================
# Base
# =============================================================================

def hay_esquema(cur) -> bool:
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_schema = DATABASE()
                     AND table_name IN ('el_eleccion', 'el_padron', 'el_padron_mov')""")
    return int(cur.fetchone()["n"] or 0) == 3


def _hora(v):
    """TIME llega como timedelta: «08:00»."""
    if v is None:
        return None
    if isinstance(v, datetime.timedelta):
        s = int(v.total_seconds())
        return f"{s // 3600:02d}:{s % 3600 // 60:02d}"
    return str(v)[:5]


def eleccion(cur, id_el: int, bloquear=False) -> dict | None:
    cur.execute(f"""SELECT e.*, u.nombre AS usuario, uc.nombre AS usuario_cierre,
                           (SELECT COUNT(*) FROM el_padron p WHERE p.id_eleccion = e.id) AS padron,
                           (SELECT COUNT(*) FROM el_padron p WHERE p.id_eleccion = e.id AND p.voto = 1) AS votaron
                      FROM el_eleccion e
                      LEFT JOIN s_usuarios u ON u.id = e.id_usuario
                      LEFT JOIN s_usuarios uc ON uc.id = e.id_usuario_cierre
                     WHERE e.id = %s {'FOR UPDATE' if bloquear else ''}""", (id_el,))
    el = cur.fetchone()
    if el:
        el["hora_desde_txt"], el["hora_hasta_txt"] = _hora(el["hora_desde"]), _hora(el["hora_hasta"])
        el.update(resumen(int(el["padron"] or 0), int(el["votaron"] or 0)))
    return el


def elecciones(cur) -> list[dict]:
    cur.execute("""SELECT e.*, (SELECT COUNT(*) FROM el_padron p WHERE p.id_eleccion = e.id) AS padron,
                          (SELECT COUNT(*) FROM el_padron p WHERE p.id_eleccion = e.id AND p.voto = 1) AS votaron
                     FROM el_eleccion e ORDER BY e.fecha_votacion DESC, e.id DESC""")
    filas = cur.fetchall()
    for e in filas:
        e["hora_desde_txt"], e["hora_hasta_txt"] = _hora(e["hora_desde"]), _hora(e["hora_hasta"])
        e.update(resumen(int(e["padron"] or 0), int(e["votaron"] or 0)))
    return filas


def padron(cur, id_el: int) -> list[dict]:
    cur.execute("""SELECT p.*, u.nombre AS usuario_voto FROM el_padron p
                     LEFT JOIN s_usuarios u ON u.id = p.id_usuario_voto
                    WHERE p.id_eleccion = %s ORDER BY p.orden""", (id_el,))
    return cur.fetchall()


#: Lo que muestra la columna OSEDA: texto, tipo de estado y valor del filtro.
OSEDA_ESTADOS = {
    "titular": ("Sí", "ok", "si"),
    "familiar": ("Sí, familiar", "ok", "si"),
    "baja": ("De baja", "warn", "no"),
    "no": ("No", "neutro", "no"),
}


def marcar_oseda(filas: list[dict], oseda: dict[str, dict] | None) -> None:
    """Pone en cada fila `oseda` (clave de OSEDA_ESTADOS, None sin consulta) y `oseda_baja`."""
    for f in filas:
        f["oseda_baja"] = None
        if oseda is None:
            f["oseda"] = None
            continue
        o = oseda.get(str(f.get("cuil") or ""))
        if not o:
            f["oseda"] = "no"
        elif o["vigente"]:
            f["oseda"] = "titular" if o["titular"] else "familiar"
        else:
            f["oseda"], f["oseda_baja"] = "baja", o["fecha_baja"]


def con_oseda(filas: list[dict]) -> str | None:
    """Consulta OSEDA para el padrón electoral; devuelve el aviso si Railway no responde."""
    try:
        oseda = contable_oseda.padron_oseda_por_cuil(f["cuil"] for f in filas if f.get("cuil"))
    except contable_oseda.ContableNoDisponible as e:
        log.warning("Elecciones: sin OSEDA: %s", e)
        marcar_oseda(filas, None)
        return f"No se pudo consultar el padrón de OSEDA: la columna OSEDA sale sin datos. ({e})"
    marcar_oseda(filas, oseda)
    return None


def movimientos(cur, id_el: int, limite: int | None = None) -> list[dict]:
    cur.execute(f"""SELECT m.*, u.nombre AS usuario, COALESCE(p.apellido_nombres, a.apellido_nombres) AS apellido_nombres,
                           COALESCE(p.nro_documento, a.nro_documento) AS nro_documento, p.orden
                      FROM el_padron_mov m
                      LEFT JOIN s_usuarios u ON u.id = m.id_usuario
                      LEFT JOIN el_padron p ON p.id_eleccion = m.id_eleccion AND p.id_afiliado = m.id_afiliado
                      LEFT JOIN p_afiliados a ON a.id_afiliado = m.id_afiliado
                     WHERE m.id_eleccion = %s ORDER BY m.fecha DESC, m.id DESC
                     {f'LIMIT {int(limite)}' if limite else ''}""", (id_el,))
    return cur.fetchall()


def _mov(cur, id_el, id_afi, accion, detalle, uid):
    cur.execute("""INSERT INTO el_padron_mov (id_eleccion, id_afiliado, accion, detalle, id_usuario)
                   VALUES (%s, %s, %s, %s, %s)""", (id_el, id_afi, accion, (detalle or None) and detalle[:300], uid))


SQL_EMPLEADOR = """LEFT JOIN p_empresas e ON a.cuit_empleador REGEXP '^[0-9]+$'
                                        AND e.CUIT = CAST(a.cuit_empleador AS UNSIGNED)"""


def _condiciones(el: dict) -> tuple[str, list]:
    """El WHERE del padrón electoral sobre `p_afiliados a` (ver el docstring)."""
    corte = el["fecha_padron"]
    cond = ["a.cod_parentesco = 0",
            "(a.fecha_alta IS NULL OR a.fecha_alta <= %s)",
            "((a.fecha_baja IS NULL AND a.activo = 1) OR a.fecha_baja > %s)"]
    params = [corte, corte]
    ca = corte_antiguedad(el)
    if ca:
        cond.append("a.fecha_alta IS NOT NULL AND a.fecha_alta <= %s")
        params.append(ca)
    return " AND ".join(cond), params


def _reordenar(cur, id_el):
    cur.execute("""UPDATE el_padron p
                     JOIN (SELECT id, ROW_NUMBER() OVER (ORDER BY apellido_nombres, id) AS n
                             FROM el_padron WHERE id_eleccion = %s) x ON x.id = p.id
                      SET p.orden = x.n""", (id_el,))


def generar_padron(cur, el: dict, uid) -> dict:
    """Arma (o rehace) el padrón electoral. Con algún voto registrado, no."""
    if el["estado"] != "vigente":
        raise ErrorEleccion("Solo se genera el padrón de una elección vigente.")
    if el["votaron"]:
        n = el["votaron"]
        raise ErrorEleccion(f"Ya hay {n} {'voto registrado' if n == 1 else 'votos registrados'}: "
                            "el padrón no se vuelve a generar.")
    cur.execute("DELETE FROM el_padron WHERE id_eleccion = %s", (el["id"],))
    where, params = _condiciones(el)
    cur.execute(f"""INSERT INTO el_padron (id_eleccion, id_afiliado, orden, cuil, nro_documento, apellido_nombres,
                                           cuit_empleador, empleador, fecha_alta, origen)
                    SELECT %s, a.id_afiliado, 0, NULLIF(a.cuil, ''), NULLIF(CAST(a.nro_documento AS CHAR), ''),
                           COALESCE(NULLIF(a.apellido_nombres, ''), '(sin nombre)'),
                           NULLIF(CAST(a.cuit_empleador AS CHAR), ''), e.razon_social, a.fecha_alta, 'padron'
                      FROM p_afiliados a {SQL_EMPLEADOR}
                     WHERE {where}""", [el["id"]] + params)
    n = cur.rowcount
    _reordenar(cur, el["id"])
    cur.execute("UPDATE el_eleccion SET padron_generado = NOW() WHERE id = %s", (el["id"],))
    # Lo que quedó afuera por la antigüedad o por no tener alta, para el aviso.
    fuera = {}
    ca = corte_antiguedad(el)
    if ca:
        corte = el["fecha_padron"]
        cur.execute("""SELECT SUM(a.fecha_alta IS NULL) AS sin_alta, SUM(a.fecha_alta > %s) AS sin_antiguedad
                         FROM p_afiliados a
                        WHERE a.cod_parentesco = 0 AND (a.fecha_alta IS NULL OR a.fecha_alta <= %s)
                          AND ((a.fecha_baja IS NULL AND a.activo = 1) OR a.fecha_baja > %s)""", (ca, corte, corte))
        fuera = {k: int(v or 0) for k, v in cur.fetchone().items()}
    return {"n": n, **fuera}


def _afiliado(cur, numero: str) -> dict | None:
    """Del padrón de afiliados por CUIL o documento (el activo primero)."""
    cur.execute("""SELECT a.id_afiliado, a.cuil, a.nro_documento, a.apellido_nombres, a.cod_parentesco, a.activo,
                          a.fecha_alta, a.fecha_baja, a.cuit_empleador, e.razon_social AS empleador
                     FROM p_afiliados a """ + SQL_EMPLEADOR + """
                    WHERE a.cuil = %s OR CAST(a.nro_documento AS CHAR) = %s
                    ORDER BY a.activo DESC, (a.cod_parentesco = 0) DESC, a.id_afiliado LIMIT 1""", (numero, numero))
    return cur.fetchone()


def agregar(cur, el: dict, numero: str, motivo: str, uid) -> dict:
    if el["estado"] != "vigente" or not el.get("padron_generado"):
        raise ErrorEleccion("Se agrega al padrón de una elección vigente, con el padrón ya generado.")
    numero = re.sub(r"\D", "", numero or "")
    motivo = " ".join((motivo or "").split())
    if not numero:
        raise ErrorEleccion("Escribí el CUIL o el documento.")
    if not motivo:
        raise ErrorEleccion("Escribí el motivo: queda en los movimientos del padrón.")
    afi = _afiliado(cur, numero)
    if not afi:
        raise ErrorEleccion(f"{numero} no está en el padrón de afiliados.")
    if not es_titular(afi["cod_parentesco"]):
        raise ErrorEleccion(f"{afi['apellido_nombres']} es familiar a cargo: en el padrón electoral van los afiliados titulares.")
    cur.execute("SELECT orden FROM el_padron WHERE id_eleccion = %s AND id_afiliado = %s", (el["id"], afi["id_afiliado"]))
    ya = cur.fetchone()
    if ya:
        raise ErrorEleccion(f"{afi['apellido_nombres']} ya está en el padrón electoral (orden {ya['orden']}).")
    cur.execute("SELECT COALESCE(MAX(orden), 0) + 1 AS n FROM el_padron WHERE id_eleccion = %s", (el["id"],))
    orden = cur.fetchone()["n"]
    cur.execute("""INSERT INTO el_padron (id_eleccion, id_afiliado, orden, cuil, nro_documento, apellido_nombres,
                                          cuit_empleador, empleador, fecha_alta, origen)
                   VALUES (%s, %s, %s, NULLIF(%s, ''), NULLIF(%s, ''), %s, NULLIF(%s, ''), %s, %s, 'manual')""",
                (el["id"], afi["id_afiliado"], orden, afi["cuil"] or "", str(afi["nro_documento"] or ""),
                 afi["apellido_nombres"] or "(sin nombre)", str(afi["cuit_empleador"] or ""), afi["empleador"],
                 afi["fecha_alta"]))
    _mov(cur, el["id"], afi["id_afiliado"], "agregado", motivo, uid)
    aviso = " Ojo: en el padrón de afiliados está de baja." if not afi["activo"] else ""
    return {"nombre": afi["apellido_nombres"], "orden": orden, "aviso": aviso}


def quitar(cur, el: dict, id_padron: int, motivo: str, uid) -> str:
    if el["estado"] != "vigente":
        raise ErrorEleccion("Solo se quita del padrón de una elección vigente.")
    motivo = " ".join((motivo or "").split())
    if not motivo:
        raise ErrorEleccion("Escribí el motivo.")
    cur.execute("SELECT * FROM el_padron WHERE id = %s AND id_eleccion = %s FOR UPDATE", (id_padron, el["id"]))
    p = cur.fetchone()
    if not p:
        raise ErrorEleccion("No está en el padrón.")
    if p["voto"]:
        raise ErrorEleccion(f"{p['apellido_nombres']} ya votó: primero hay que quitarle el voto.")
    cur.execute("DELETE FROM el_padron WHERE id = %s", (id_padron,))
    _mov(cur, el["id"], p["id_afiliado"], "quitado", f"Orden {p['orden']}: {motivo}", uid)
    return p["apellido_nombres"]


def votar(cur, el: dict, id_padron: int, uid, detalle: str | None = None) -> dict:
    """Marca que votó. Si ya votó (otra mesa), lo dice con la hora y quién."""
    cur.execute("""UPDATE el_padron SET voto = 1, fecha_voto = NOW(), id_usuario_voto = %s
                    WHERE id = %s AND id_eleccion = %s AND voto = 0""", (uid, id_padron, el["id"]))
    marcado = cur.rowcount == 1
    cur.execute("""SELECT p.*, u.nombre AS usuario_voto FROM el_padron p LEFT JOIN s_usuarios u ON u.id = p.id_usuario_voto
                    WHERE p.id = %s AND p.id_eleccion = %s""", (id_padron, el["id"]))
    p = cur.fetchone()
    if not p:
        raise ErrorEleccion("No está en el padrón electoral.")
    if marcado:
        _mov(cur, el["id"], p["id_afiliado"], "voto",
             f"Orden {p['orden']}" + (f": {detalle}" if detalle else ""), uid)
    return {"marcado": marcado, "fila": p}


def quitar_voto(cur, el: dict, id_padron: int, motivo: str, uid) -> dict:
    motivo = " ".join((motivo or "").split())
    if not motivo:
        raise ErrorEleccion("Escribí el motivo para quitar el voto.")
    cur.execute("SELECT * FROM el_padron WHERE id = %s AND id_eleccion = %s FOR UPDATE", (id_padron, el["id"]))
    p = cur.fetchone()
    if not p:
        raise ErrorEleccion("No está en el padrón electoral.")
    if not p["voto"]:
        raise ErrorEleccion(f"{p['apellido_nombres']} no tiene el voto registrado.")
    cur.execute("UPDATE el_padron SET voto = 0, fecha_voto = NULL, id_usuario_voto = NULL WHERE id = %s", (id_padron,))
    _mov(cur, el["id"], p["id_afiliado"], "quita_voto",
         f"Orden {p['orden']}, había votado {p['fecha_voto']:%d/%m/%Y %H:%M}: {motivo}", uid)
    return p


def buscar(cur, el: dict, q: str) -> dict:
    """Los del padrón electoral que coinciden y, si ninguno, por qué no está."""
    digitos, palabras = partir_busqueda(q)
    cond, params = ["p.id_eleccion = %s"], [el["id"]]
    if digitos:
        partes = ["p.nro_documento = %s", "p.cuil = %s"]
        params += [digitos, digitos]
        if len(digitos) >= 6:
            partes.append("p.cuil LIKE %s")
            params.append(f"%{digitos}%")
        if len(digitos) <= 5:
            partes.append("p.orden = %s")
            params.append(int(digitos))
        cond.append("(" + " OR ".join(partes) + ")")
    elif palabras:
        for w in palabras:
            cond.append("p.apellido_nombres LIKE %s")
            params.append(f"%{w}%")
    else:
        return {"filas": [], "fuera": None}
    cur.execute(f"""SELECT p.*, u.nombre AS usuario_voto FROM el_padron p
                      LEFT JOIN s_usuarios u ON u.id = p.id_usuario_voto
                     WHERE {' AND '.join(cond)}
                     ORDER BY (p.nro_documento = %s OR p.cuil = %s) DESC, p.apellido_nombres
                     LIMIT {MAX_RESULTADOS}""", params + [digitos or "-", digitos or "-"])
    filas = cur.fetchall()
    fuera = None
    if not filas and digitos and len(digitos) >= 7:
        afi = _afiliado(cur, digitos)
        if afi:
            fuera = {"nombre": afi["apellido_nombres"], "documento": str(afi["nro_documento"] or ""),
                     "cuil": afi["cuil"], "motivo": por_que_no_esta(afi, el)}
        else:
            fuera = {"nombre": None, "motivo": "no está en el padrón de afiliados"}
    return {"filas": filas, "fuera": fuera}


def ultimos_votos(cur, id_el: int, n: int = 10) -> list[dict]:
    cur.execute("""SELECT p.orden, p.apellido_nombres, p.nro_documento, p.fecha_voto, u.nombre AS usuario_voto
                     FROM el_padron p LEFT JOIN s_usuarios u ON u.id = p.id_usuario_voto
                    WHERE p.id_eleccion = %s AND p.voto = 1 ORDER BY p.fecha_voto DESC, p.id DESC LIMIT %s""",
                (id_el, n))
    return cur.fetchall()


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


def _sin_esquema():
    flash(f"!Falta correr {SQL_ESQUEMA}: sin esas tablas las elecciones no funcionan.")
    return render_template("elecciones/elecciones.html", filas=[], ESTADOS=ESTADOS, puede=puede)


@elecciones_bp.route("")
def listado():
    salida = _guardia(URL_ABM)
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            if not hay_esquema(cur):
                return _sin_esquema()
            filas = elecciones(cur)
    return render_template("elecciones/elecciones.html", filas=filas, ESTADOS=ESTADOS, puede=puede,
                           hoy=datetime.date.today())


def _leer_form(form) -> tuple[dict, list[str]]:
    errores = []
    r = {"motivo": " ".join((form.get("motivo") or "").split())[:200],
         "lugar": " ".join((form.get("lugar") or "").split())[:200] or None,
         "observaciones": (form.get("observaciones") or "").strip()[:500] or None}

    def fecha(campo, rotulo, obligatoria=True):
        t = (form.get(campo) or "").strip()
        if not t:
            if obligatoria:
                errores.append(f"Falta {rotulo}.")
            return None
        try:
            return datetime.date.fromisoformat(t)
        except ValueError:
            errores.append(f"{rotulo[0].upper() + rotulo[1:]} no es válida.")
            return None

    def hora(campo):
        t = (form.get(campo) or "").strip()
        if not t:
            return None
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d(:\d\d)?", t):
            errores.append(f"La hora {t} no es válida.")
            return None
        return t[:5]

    if not r["motivo"]:
        errores.append("Falta el motivo de la elección.")
    r["fecha_votacion"] = fecha("fecha_votacion", "el día de la votación")
    r["fecha_padron"] = fecha("fecha_padron", "la fecha de corte del padrón", obligatoria=False) or r["fecha_votacion"]
    r["hora_desde"], r["hora_hasta"] = hora("hora_desde"), hora("hora_hasta")
    if r["hora_desde"] and r["hora_hasta"] and r["hora_hasta"] <= r["hora_desde"]:
        errores.append("La hora de cierre tiene que ser posterior a la de apertura.")
    try:
        r["antiguedad_meses"] = max(0, int(form.get("antiguedad_meses") or 0))
    except ValueError:
        r["antiguedad_meses"] = 0
        errores.append("La antigüedad mínima es una cantidad de meses.")
    if r["antiguedad_meses"] > 600:
        errores.append("La antigüedad mínima no puede pasar de 600 meses.")
    if r["fecha_votacion"] and r["fecha_padron"] and r["fecha_padron"] > r["fecha_votacion"]:
        errores.append("La fecha de corte del padrón no puede ser posterior al día de la votación.")
    return r, errores


@elecciones_bp.route("/nueva", methods=["GET", "POST"])
def nueva():
    salida = _guardia(URL_ABM)
    if salida:
        return salida
    r, errores = {"antiguedad_meses": 0}, []
    if request.method == "POST":
        r, errores = _leer_form(request.form)
        if not errores:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    if not hay_esquema(cur):
                        return _sin_esquema()
                    cur.execute("""INSERT INTO el_eleccion (motivo, fecha_votacion, hora_desde, hora_hasta, lugar,
                                                            fecha_padron, antiguedad_meses, observaciones, id_usuario)
                                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                                (r["motivo"], r["fecha_votacion"], r["hora_desde"], r["hora_hasta"], r["lugar"],
                                 r["fecha_padron"], r["antiguedad_meses"], r["observaciones"], _uid()))
                    nuevo = cur.lastrowid
                    el = eleccion(cur, nuevo)
                    gen = generar_padron(cur, el, _uid())
                conn.commit()
            flash(f"Elección creada y padrón electoral generado: {gen['n']} afiliados.")
            return redirect(url_for("elecciones.ficha", id_el=nuevo, solapa="padron"))
    return render_template("elecciones/eleccion_form.html", r=r, errores=errores, el=None)


@elecciones_bp.route("/<int:id_el>")
def ficha(id_el):
    salida = _guardia(URL_ABM)
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            if not hay_esquema(cur):
                return _sin_esquema()
            el = eleccion(cur, id_el)
            if not el:
                flash("!No existe esa elección.")
                return redirect(url_for("elecciones.listado"))
            filas = padron(cur, id_el)
            movs = movimientos(cur, id_el, 1000)
    aviso_oseda = con_oseda(filas) if filas else None
    hoy = datetime.date.today()
    marcar, aviso_marcar = puede_marcar(el, hoy, tiene_rol("Administrador"))
    return render_template("elecciones/eleccion.html", el=el, filas=filas, movs=movs, ESTADOS=ESTADOS, puede=puede,
                           marcar_padron=puede_marcar_padron(el)[0],
                           hoy=hoy, marcar=marcar, aviso_marcar=aviso_marcar, es_admin=tiene_rol("Administrador"),
                           solapa=request.args.get("solapa") or "padron", corte=corte_antiguedad(el),
                           editar=request.args.get("editar") == "1", aviso_oseda=aviso_oseda,
                           OSEDA_ESTADOS=OSEDA_ESTADOS)


@elecciones_bp.route("/<int:id_el>", methods=["POST"])
def accion(id_el):
    salida = _guardia(URL_ABM)
    if salida:
        return salida
    acc = request.form.get("accion")
    solapa = "padron"
    with get_connection() as conn:
        with conn.cursor() as cur:
            el = eleccion(cur, id_el, bloquear=True)
            if not el:
                flash("!No existe esa elección.")
                return redirect(url_for("elecciones.listado"))
            try:
                if acc == "guardar":
                    solapa = "datos"
                    if el["estado"] != "vigente":
                        raise ErrorEleccion("Una elección cerrada o anulada no se modifica.")
                    r, errores = _leer_form(request.form)
                    if errores:
                        conn.rollback()
                        hoy = datetime.date.today()
                        marcar, aviso_marcar = puede_marcar(el, hoy, tiene_rol("Administrador"))
                        filas = padron(cur, id_el)
                        aviso_oseda = con_oseda(filas) if filas else None
                        return render_template("elecciones/eleccion.html", el={**el, **r, "hora_desde_txt": r["hora_desde"], "hora_hasta_txt": r["hora_hasta"]},
                                               filas=filas, aviso_oseda=aviso_oseda, OSEDA_ESTADOS=OSEDA_ESTADOS,
                                               movs=movimientos(cur, id_el, 1000), ESTADOS=ESTADOS, puede=puede,
                                               hoy=hoy, marcar=marcar, aviso_marcar=aviso_marcar,
                                               marcar_padron=puede_marcar_padron(el)[0],
                                               es_admin=tiene_rol("Administrador"), solapa="datos",
                                               corte=corte_antiguedad(el), editar=True, errores=errores)
                    cambia_padron = (r["fecha_padron"] != el["fecha_padron"]
                                     or r["antiguedad_meses"] != int(el["antiguedad_meses"] or 0))
                    if el["votaron"] and (cambia_padron or r["fecha_votacion"] != el["fecha_votacion"]):
                        raise ErrorEleccion("Con votos registrados no se cambian el día, el corte ni la antigüedad.")
                    cur.execute("""UPDATE el_eleccion SET motivo = %s, fecha_votacion = %s, hora_desde = %s,
                                          hora_hasta = %s, lugar = %s, fecha_padron = %s, antiguedad_meses = %s,
                                          observaciones = %s WHERE id = %s""",
                                (r["motivo"], r["fecha_votacion"], r["hora_desde"], r["hora_hasta"], r["lugar"],
                                 r["fecha_padron"], r["antiguedad_meses"], r["observaciones"], id_el))
                    msg = "Datos de la elección guardados."
                    if cambia_padron:
                        gen = generar_padron(cur, {**el, **r}, _uid())
                        msg += f" Cambió el corte del padrón: se volvió a generar ({gen['n']} afiliados)."
                    flash(msg)
                elif acc == "generar":
                    gen = generar_padron(cur, el, _uid())
                    msg = f"Padrón electoral generado: {gen['n']} afiliados."
                    if gen.get("sin_antiguedad"):
                        msg += f" Quedaron afuera {gen['sin_antiguedad']} sin la antigüedad pedida"
                        msg += f" y {gen['sin_alta']} sin fecha de alta." if gen.get("sin_alta") else "."
                    elif gen.get("sin_alta"):
                        msg += f" Quedaron afuera {gen['sin_alta']} sin fecha de alta."
                    flash(msg)
                elif acc == "agregar":
                    res = agregar(cur, el, request.form.get("numero"), request.form.get("motivo"), _uid())
                    flash(f"{res['nombre']} agregado al padrón electoral con el número de orden {res['orden']}.{res['aviso']}")
                elif acc == "quitar":
                    nombre = quitar(cur, el, request.form.get("id", type=int), request.form.get("motivo"), _uid())
                    flash(f"{nombre} quitado del padrón electoral.")
                elif acc == "quitar_voto":
                    if el["estado"] != "vigente":
                        raise ErrorEleccion("La elección no está vigente: los votos ya no se tocan.")
                    p = quitar_voto(cur, el, request.form.get("id", type=int), request.form.get("motivo"), _uid())
                    flash(f"Se quitó el voto de {p['apellido_nombres']}.")
                elif acc == "cerrar":
                    if el["estado"] != "vigente":
                        raise ErrorEleccion("Solo se cierra una elección vigente.")
                    cur.execute("""UPDATE el_eleccion SET estado = 'cerrada', fecha_cierre = NOW(),
                                          id_usuario_cierre = %s WHERE id = %s""", (_uid(), id_el))
                    flash(f"Elección cerrada: votaron {el['votaron']} de {el['padron']} ({el['porc']} %).")
                elif acc == "reabrir":
                    if not tiene_rol("Administrador"):
                        raise ErrorEleccion("Solo el Administrador reabre una elección.")
                    if el["estado"] != "cerrada":
                        raise ErrorEleccion("Solo se reabre una elección cerrada.")
                    cur.execute("""UPDATE el_eleccion SET estado = 'vigente', fecha_cierre = NULL,
                                          id_usuario_cierre = NULL WHERE id = %s""", (id_el,))
                    flash("Elección reabierta.")
                elif acc == "anular":
                    motivo = " ".join((request.form.get("motivo") or "").split())[:300]
                    if el["estado"] == "anulada":
                        raise ErrorEleccion("La elección ya está anulada.")
                    if not motivo:
                        raise ErrorEleccion("Escribí el motivo de la anulación.")
                    cur.execute("UPDATE el_eleccion SET estado = 'anulada', motivo_anulacion = %s WHERE id = %s",
                                (motivo, id_el))
                    flash("Elección anulada.")
                else:
                    raise ErrorEleccion("Acción desconocida.")
                conn.commit()
            except ErrorEleccion as e:
                conn.rollback()
                flash("!" + str(e))
            except Exception:
                conn.rollback()
                raise
    if acc in ("guardar",):
        solapa = "datos"
    return redirect(url_for("elecciones.ficha", id_el=id_el, solapa=solapa))


@elecciones_bp.route("/<int:id_el>/api_votar", methods=["POST"])
def api_votar_padron(id_el):
    """«Marcar que votó» desde el padrón electoral: cualquier día (ver el docstring)."""
    if not validasesion():
        return jsonify({"error": "La sesión venció: volvé a ingresar."}), 401
    if not puede(URL_ABM):
        return jsonify({"error": "No tenés permiso para el padrón electoral."}), 403
    datos = request.get_json(silent=True) or {}
    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                el = eleccion(cur, id_el, bloquear=True)
                if not el:
                    raise ErrorEleccion("No existe esa elección.")
                ok, motivo = puede_marcar_padron(el)
                if not ok:
                    raise ErrorEleccion(motivo)
                hoy = datetime.date.today()
                res = votar(cur, el, int(datos.get("id") or 0), _uid(), detalle_carga(el, hoy))
                conn.commit()
            except ErrorEleccion as e:
                conn.rollback()
                return jsonify({"error": str(e)}), 409
            except Exception:
                conn.rollback()
                raise
            el2 = eleccion(cur, id_el)
    fila = _fila_json(res["fila"])
    fila["iso"] = res["fila"]["fecha_voto"].isoformat() if res["fila"]["fecha_voto"] else ""
    fila["fuera_del_dia"] = bool(res["fila"]["fecha_voto"]
                                 and res["fila"]["fecha_voto"].date() != el["fecha_votacion"])
    return jsonify({"marcado": res["marcado"], "fila": fila,
                    "estado": {k: el2[k] for k in ("padron", "votaron", "faltan", "porc")}})


# ── Mesa de votación ─────────────────────────────────────────────────────────

@elecciones_bp.route("/votacion")
def mesa_inicio():
    salida = _guardia(URL_MESA)
    if salida:
        return salida
    hoy = datetime.date.today()
    with get_connection() as conn:
        with conn.cursor() as cur:
            if not hay_esquema(cur):
                flash(f"!Falta correr {SQL_ESQUEMA}: sin esas tablas las elecciones no funcionan.")
                return render_template("elecciones/mesa_inicio.html", del_dia=[], otras=[], hoy=hoy)
            todas = [e for e in elecciones(cur) if e["estado"] == "vigente"]
    del_dia = [e for e in todas if e["fecha_votacion"] == hoy]
    if len(del_dia) == 1 and not request.args.get("elegir"):
        return redirect(url_for("elecciones.mesa", id_el=del_dia[0]["id"]))
    otras = [e for e in todas if e["fecha_votacion"] != hoy]
    return render_template("elecciones/mesa_inicio.html", del_dia=del_dia, otras=otras, hoy=hoy,
                           es_admin=tiene_rol("Administrador"))


def _mesa_el(cur, id_el):
    el = eleccion(cur, id_el)
    if not el:
        raise ErrorEleccion("No existe esa elección.")
    return el


@elecciones_bp.route("/votacion/<int:id_el>")
def mesa(id_el):
    salida = _guardia(URL_MESA)
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            if not hay_esquema(cur):
                return redirect(url_for("elecciones.mesa_inicio"))
            el = eleccion(cur, id_el)
            if not el:
                flash("!No existe esa elección.")
                return redirect(url_for("elecciones.mesa_inicio"))
            ultimos = ultimos_votos(cur, id_el)
    marcar, aviso_marcar = puede_marcar(el, datetime.date.today(), tiene_rol("Administrador"))
    return render_template("elecciones/mesa.html", el=el, ultimos=ultimos, marcar=marcar, aviso_marcar=aviso_marcar,
                           ESTADOS=ESTADOS, puede=puede)


def _fila_json(p: dict) -> dict:
    return {"id": p["id"], "orden": p["orden"], "nombre": p["apellido_nombres"], "documento": p["nro_documento"] or "",
            "cuil": p["cuil"] or "", "empleador": p["empleador"] or "", "voto": bool(p["voto"]),
            "hora": p["fecha_voto"].strftime("%H:%M") if p.get("fecha_voto") else None,
            "fecha": p["fecha_voto"].strftime("%d/%m/%Y") if p.get("fecha_voto") else None,
            "usuario": p.get("usuario_voto") or "", "manual": p.get("origen") == "manual"}


def _estado_json(cur, el):
    el2 = eleccion(cur, el["id"])
    return {"padron": el2["padron"], "votaron": el2["votaron"], "faltan": el2["faltan"], "porc": el2["porc"],
            "ultimos": [{"orden": u["orden"], "nombre": u["apellido_nombres"], "documento": u["nro_documento"] or "",
                         "hora": u["fecha_voto"].strftime("%H:%M"), "usuario": u["usuario_voto"] or ""}
                        for u in ultimos_votos(cur, el["id"])]}


def _guardia_api():
    if not validasesion():
        return jsonify({"error": "La sesión venció: volvé a ingresar."}), 401
    if not puede(URL_MESA):
        return jsonify({"error": "No tenés permiso para la mesa de votación."}), 403
    return None


@elecciones_bp.route("/votacion/<int:id_el>/api_buscar")
def api_buscar(id_el):
    salida = _guardia_api()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                el = _mesa_el(cur, id_el)
            except ErrorEleccion as e:
                return jsonify({"error": str(e)}), 404
            res = buscar(cur, el, request.args.get("q", ""))
    return jsonify({"filas": [_fila_json(p) for p in res["filas"]], "fuera": res["fuera"],
                    "max": MAX_RESULTADOS})


@elecciones_bp.route("/votacion/<int:id_el>/api_estado")
def api_estado(id_el):
    salida = _guardia_api()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                el = _mesa_el(cur, id_el)
            except ErrorEleccion as e:
                return jsonify({"error": str(e)}), 404
            return jsonify(_estado_json(cur, el))


@elecciones_bp.route("/votacion/<int:id_el>/api_votar", methods=["POST"])
def api_votar(id_el):
    salida = _guardia_api()
    if salida:
        return salida
    datos = request.get_json(silent=True) or {}
    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                el = _mesa_el(cur, id_el)
                ok, motivo = puede_marcar(el, datetime.date.today(), tiene_rol("Administrador"))
                if not ok:
                    raise ErrorEleccion(motivo)
                res = votar(cur, el, int(datos.get("id") or 0), _uid())
                conn.commit()
            except ErrorEleccion as e:
                conn.rollback()
                return jsonify({"error": str(e)}), 409
            except Exception:
                conn.rollback()
                raise
            return jsonify({"marcado": res["marcado"], "fila": _fila_json(res["fila"]), "estado": _estado_json(cur, el)})


@elecciones_bp.route("/votacion/<int:id_el>/api_quitar_voto", methods=["POST"])
def api_quitar_voto(id_el):
    salida = _guardia_api()
    if salida:
        return salida
    datos = request.get_json(silent=True) or {}
    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                el = _mesa_el(cur, id_el)
                ok, motivo = puede_marcar(el, datetime.date.today(), tiene_rol("Administrador"))
                if not ok:
                    raise ErrorEleccion(motivo)
                p = quitar_voto(cur, el, int(datos.get("id") or 0), datos.get("motivo"), _uid())
                conn.commit()
            except ErrorEleccion as e:
                conn.rollback()
                return jsonify({"error": str(e)}), 409
            except Exception:
                conn.rollback()
                raise
            cur.execute("SELECT * FROM el_padron WHERE id = %s", (p["id"],))
            return jsonify({"fila": _fila_json(cur.fetchone()), "estado": _estado_json(cur, el)})
