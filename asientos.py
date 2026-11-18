"""
asientos.py — Ejercicios, períodos y asientos: las reglas, sin Flask.

Lo usan la pantalla de Ejercicios (contabilidad_ejercicios.py), las de Asientos y
Libro Diario (contabilidad_diario.py) y los importadores (Excel desde la pantalla
y importar_aeda_asientos.py). Portado de gestion_adm/contable.py (asientos,
ejercicios, periodos, importar_asientos, renumerar_asientos) sin los stored
procedures (sp_abrir_ejercicio, sp_cerrar_ejercicio), que esta base no tiene.

EJERCICIO Y PERÍODOS
- Un ejercicio tiene fechas desde/hasta y, al abrirlo, un período por mes
  («Enero 2026», como gestion_adm). A lo sumo uno es el EJERCICIO DE TRABAJO
  (c_ejercicios.activo): el que muestran el Diario y la carga por defecto.
- Los ejercicios no se superponen: una fecha es de un solo período.
- Un período cerrado o bloqueado no admite asientos nuevos, ni editar,
  confirmar o eliminar los suyos. Ojo: Tesorería también lo mira
  (anulaciones._fuera_de_periodo): cerrar un período impide anular pagos,
  ingresos y movimientos de esas fechas.

EL ASIENTO
- Borrador → confirmado; anulado (en gestion_adm, Contabilidad › Anulaciones;
  acá todavía no). El borrador se edita y se elimina; el confirmado ya no.
- Partida doble: al menos dos renglones, cada uno con debe o haber (no los
  dos), cuentas imputables y activas, y debe = haber al centavo.
- El período sale de la FECHA (no se elige aparte, como en gestion_adm, donde
  se podía cargar un asiento de julio en el período de agosto).
- Número correlativo POR EJERCICIO (el siguiente al mayor del ejercicio). En
  gestion_adm la carga manual numeraba por período y la importación por
  ejercicio. «Renumerar» los ordena: la apertura primero, el resto por fecha.
"""

from __future__ import annotations

import calendar
import csv
import datetime
import io
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

TIPOS = ("apertura", "operacion", "ajuste", "cierre", "rectificacion")
TIPOS_TXT = {"apertura": "Apertura", "operacion": "Operación", "ajuste": "Ajuste", "cierre": "Cierre",
             "rectificacion": "Rectificación"}
ESTADOS = {"borrador": ("Borrador", "warn"), "confirmado": ("Confirmado", "ok"), "anulado": ("Anulado", "neutro")}
ESTADOS_PERIODO = {"abierto": ("Abierto", "ok"), "cerrado": ("Cerrado", "neutro"), "bloqueado": ("Bloqueado", "danger")}
MESES = ("Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre",
         "Noviembre", "Diciembre")
CENT = Decimal("0.01")

#: Columnas del archivo de importación y de «Exportar asientos» (las de gestion_adm).
COLS_ARCHIVO = ["nro_asiento", "fecha", "tipo", "descripcion", "referencia", "codigo_cuenta", "descripcion_item",
                "debe", "haber"]
TITULOS_ARCHIVO = ["N° Asiento", "Fecha", "Tipo", "Descripción", "Referencia", "Código cuenta", "Descripción ítem",
                   "Debe", "Haber"]
_ALIAS_COL = {
    "n° asiento": "nro_asiento", "nº asiento": "nro_asiento", "nro asiento": "nro_asiento", "nro_asiento": "nro_asiento",
    "numero": "nro_asiento", "número": "nro_asiento", "fecha": "fecha", "tipo": "tipo",
    "descripción": "descripcion", "descripcion": "descripcion", "referencia": "referencia",
    "código cuenta": "codigo_cuenta", "codigo cuenta": "codigo_cuenta", "codigo_cuenta": "codigo_cuenta",
    "cuenta": "codigo_cuenta", "descripción ítem": "descripcion_item", "descripcion item": "descripcion_item",
    "descripcion_item": "descripcion_item", "detalle": "descripcion_item", "debe": "debe", "haber": "haber",
}


class ErrorContable(Exception):
    """Lo que la pantalla le muestra a quien carga."""


def _d(v) -> Decimal:
    try:
        return Decimal(str(v if v is not None else 0)).quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return Decimal("0.00")


def leer_importe(texto) -> Decimal | None:
    """«1.234,56», «1234.56», «1.234» (miles) o vacío (cero). None si no es un importe."""
    t = str(texto if texto is not None else "").strip().replace(" ", "").replace("$", "")
    if not t:
        return Decimal("0.00")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif "." in t and not isinstance(texto, (int, float, Decimal)):
        # Sin coma, el punto es de miles solo si todos los grupos que siguen
        # tienen tres dígitos (la regla de pagos_datos.leer_importe).
        grupos = t.split(".")
        if all(len(g) == 3 and g.isdigit() for g in grupos[1:]):
            t = "".join(grupos)
    try:
        return Decimal(t).quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


def pesos(v) -> str:
    entero, _, dec = f"{float(v or 0):,.2f}".partition(".")
    return f"$ {entero.replace(',', '.')},{dec}"


def fecha_de(texto) -> datetime.date | None:
    """AAAA-MM-DD, DD/MM/AAAA o un date/datetime."""
    if isinstance(texto, datetime.datetime):
        return texto.date()
    if isinstance(texto, datetime.date):
        return texto
    t = str(texto or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.datetime.strptime(t, fmt).date()
        except ValueError:
            pass
    return None


# =============================================================================
# Ejercicios y períodos
# =============================================================================

def meses(desde: datetime.date, hasta: datetime.date) -> list[dict]:
    """Los períodos mensuales de un ejercicio: el primero y el último pueden
    ser parciales si el ejercicio no empieza el 1.° o no termina a fin de mes."""
    out, d = [], desde
    while d <= hasta:
        fin_mes = d.replace(day=calendar.monthrange(d.year, d.month)[1])
        fin = min(fin_mes, hasta)
        out.append({"nombre": f"{MESES[d.month - 1]} {d.year}", "fecha_inicio": d, "fecha_fin": fin})
        d = fin_mes + datetime.timedelta(days=1)
    return out


def ejercicio_activo(cur) -> dict | None:
    cur.execute("SELECT * FROM c_ejercicios WHERE activo = 1 ORDER BY id_ejercicio DESC LIMIT 1")
    return cur.fetchone()


def ejercicios(cur) -> list[dict]:
    cur.execute("""SELECT e.*,
                          (SELECT COUNT(*) FROM c_periodos p WHERE p.id_ejercicio = e.id_ejercicio) AS periodos,
                          (SELECT COUNT(*) FROM c_periodos p WHERE p.id_ejercicio = e.id_ejercicio
                              AND p.estado = 'abierto') AS abiertos,
                          (SELECT COUNT(*) FROM c_asientos a JOIN c_periodos p ON p.id_periodo = a.id_periodo
                            WHERE p.id_ejercicio = e.id_ejercicio AND a.estado <> 'anulado') AS asientos,
                          (SELECT COUNT(*) FROM c_asientos a JOIN c_periodos p ON p.id_periodo = a.id_periodo
                            WHERE p.id_ejercicio = e.id_ejercicio AND a.estado = 'borrador') AS borradores
                     FROM c_ejercicios e ORDER BY e.fecha_inicio DESC""")
    return cur.fetchall()


def periodos(cur, id_ejercicio=None) -> list[dict]:
    """Los períodos (de un ejercicio, o todos), con sus asientos."""
    where, params = ("WHERE p.id_ejercicio = %s", [id_ejercicio]) if id_ejercicio else ("", [])
    cur.execute(f"""SELECT p.*, e.nombre AS ejercicio,
                           (SELECT COUNT(*) FROM c_asientos a WHERE a.id_periodo = p.id_periodo
                               AND a.estado = 'confirmado') AS confirmados,
                           (SELECT COUNT(*) FROM c_asientos a WHERE a.id_periodo = p.id_periodo
                               AND a.estado = 'borrador') AS borradores
                      FROM c_periodos p LEFT JOIN c_ejercicios e ON e.id_ejercicio = p.id_ejercicio
                      {where} ORDER BY p.fecha_inicio""", params)
    return cur.fetchall()


def periodo_de_fecha(cur, fecha: datetime.date) -> dict | None:
    cur.execute("""SELECT p.*, e.nombre AS ejercicio, e.estado AS estado_ejercicio FROM c_periodos p
                     LEFT JOIN c_ejercicios e ON e.id_ejercicio = p.id_ejercicio
                    WHERE %s BETWEEN p.fecha_inicio AND p.fecha_fin ORDER BY p.id_periodo DESC LIMIT 1""", (fecha,))
    return cur.fetchone()


def validar_ejercicio(cur, nombre, desde, hasta, id_ejercicio=None) -> list[str]:
    errores = []
    if not nombre:
        errores.append("El nombre es obligatorio.")
    if not desde or not hasta:
        errores.append("Las fechas de inicio y de cierre son obligatorias.")
    elif hasta < desde:
        errores.append("La fecha de cierre tiene que ser posterior a la de inicio.")
    elif (hasta - desde).days > 550:
        errores.append("Un ejercicio no puede durar más de 18 meses.")
    if errores:
        return errores
    cur.execute("""SELECT nombre, fecha_inicio, fecha_fin FROM c_ejercicios
                    WHERE fecha_inicio <= %s AND fecha_fin >= %s AND id_ejercicio <> %s LIMIT 1""",
                (hasta, desde, id_ejercicio or 0))
    otro = cur.fetchone()
    if otro:
        errores.append(f"Se superpone con el ejercicio «{otro['nombre']}» "
                       f"({otro['fecha_inicio']:%d/%m/%Y} al {otro['fecha_fin']:%d/%m/%Y}).")
    return errores


def abrir_ejercicio(cur, nombre, desde, hasta, cuit, razon, usuario, observaciones=None, activar=False) -> int:
    """Crea el ejercicio con un período por mes (lo que hacía sp_abrir_ejercicio)."""
    errores = validar_ejercicio(cur, nombre, desde, hasta)
    if errores:
        raise ErrorContable(" ".join(errores))
    cur.execute("""INSERT INTO c_ejercicios (nombre, cuit, razon_social, fecha_inicio, fecha_fin, estado, activo,
                                            observaciones, usuario_apertura)
                   VALUES (%s, %s, %s, %s, %s, 'abierto', 0, %s, %s)""",
                (nombre, cuit, razon, desde, hasta, observaciones, usuario))
    id_ej = cur.lastrowid
    cur.executemany("""INSERT INTO c_periodos (id_ejercicio, nombre, fecha_inicio, fecha_fin, estado)
                       VALUES (%s, %s, %s, %s, 'abierto')""",
                    [(id_ej, m["nombre"], m["fecha_inicio"], m["fecha_fin"]) for m in meses(desde, hasta)])
    cur.execute("SELECT COUNT(*) AS n FROM c_ejercicios WHERE activo = 1")
    if activar or not cur.fetchone()["n"]:
        activar_ejercicio(cur, id_ej)
    return id_ej


def activar_ejercicio(cur, id_ejercicio) -> None:
    cur.execute("UPDATE c_ejercicios SET activo = (id_ejercicio = %s)", (id_ejercicio,))


def modificar_ejercicio(cur, id_ej, nombre, observaciones) -> None:
    """Nombre y observaciones. Las fechas no: los períodos ya están armados."""
    if not nombre:
        raise ErrorContable("El nombre es obligatorio.")
    cur.execute("UPDATE c_ejercicios SET nombre = %s, observaciones = %s WHERE id_ejercicio = %s",
                (nombre, observaciones, id_ej))


def borrar_ejercicio(cur, id_ej) -> None:
    cur.execute("""SELECT COUNT(*) AS n FROM c_asientos a JOIN c_periodos p ON p.id_periodo = a.id_periodo
                    WHERE p.id_ejercicio = %s""", (id_ej,))
    if cur.fetchone()["n"]:
        raise ErrorContable("Tiene asientos: no se elimina. Si no se usa más, cerralo.")
    cur.execute("DELETE FROM c_periodos WHERE id_ejercicio = %s", (id_ej,))
    cur.execute("DELETE FROM c_ejercicios WHERE id_ejercicio = %s", (id_ej,))


def cerrar_ejercicio(cur, id_ej, usuario) -> int:
    """Cierra el ejercicio y todos sus períodos. No genera el asiento de cierre
    (refundición de resultados): eso lo hacía sp_cerrar_ejercicio de gestion_adm
    y acá queda para después. Devuelve cuántos períodos cerró."""
    cur.execute("""SELECT COUNT(*) AS n FROM c_asientos a JOIN c_periodos p ON p.id_periodo = a.id_periodo
                    WHERE p.id_ejercicio = %s AND a.estado = 'borrador'""", (id_ej,))
    n = cur.fetchone()["n"]
    if n:
        raise ErrorContable(f"Tiene {n} asiento(s) en borrador: confirmalos o eliminalos antes de cerrar.")
    cur.execute("UPDATE c_periodos SET estado = 'cerrado' WHERE id_ejercicio = %s AND estado = 'abierto'", (id_ej,))
    cerrados = cur.rowcount
    cur.execute("""UPDATE c_ejercicios SET estado = 'cerrado', usuario_cierre = %s, fecha_cierre_real = NOW()
                    WHERE id_ejercicio = %s""", (usuario, id_ej))
    return cerrados


def reabrir_ejercicio(cur, id_ej) -> None:
    """Vuelve a abrir el ejercicio (sus períodos quedan como estaban: se abren de a uno)."""
    cur.execute("""UPDATE c_ejercicios SET estado = 'abierto', usuario_cierre = NULL, fecha_cierre_real = NULL
                    WHERE id_ejercicio = %s""", (id_ej,))


def cambiar_periodo(cur, id_periodo, estado) -> dict:
    if estado not in ESTADOS_PERIODO:
        raise ErrorContable("Estado inválido.")
    cur.execute("""SELECT p.*, e.estado AS estado_ejercicio FROM c_periodos p
                     JOIN c_ejercicios e ON e.id_ejercicio = p.id_ejercicio WHERE p.id_periodo = %s""", (id_periodo,))
    p = cur.fetchone()
    if not p:
        raise ErrorContable("No existe ese período.")
    if estado == "abierto" and p["estado_ejercicio"] != "abierto":
        raise ErrorContable("El ejercicio está cerrado: para abrir un período, primero reabrí el ejercicio.")
    if estado != "abierto":
        cur.execute("SELECT COUNT(*) AS n FROM c_asientos WHERE id_periodo = %s AND estado = 'borrador'", (id_periodo,))
        n = cur.fetchone()["n"]
        if n:
            raise ErrorContable(f"{p['nombre']} tiene {n} asiento(s) en borrador: confirmalos o eliminalos antes.")
    cur.execute("UPDATE c_periodos SET estado = %s WHERE id_periodo = %s", (estado, id_periodo))
    return p


# =============================================================================
# Asientos
# =============================================================================

def cuentas_por_id(cur) -> dict:
    cur.execute("""SELECT id_cuenta, codigo, nombre, permite_movimiento, activa FROM c_plan_de_cuentas""")
    return {f["id_cuenta"]: f for f in cur.fetchall()}


def validar_renglones(renglones: list[dict], cuentas: dict) -> tuple[list[dict], list[str], Decimal, Decimal]:
    """`renglones`: dicts con id_cuenta, debe, haber (Decimal o texto) y
    descripcion. Devuelve (los válidos, errores, total debe, total haber). Un
    renglón sin cuenta ni importes se ignora (una fila vacía del formulario)."""
    errores, buenos = [], []
    td = th = Decimal("0.00")
    for i, r in enumerate(renglones, 1):
        debe = r["debe"] if isinstance(r.get("debe"), Decimal) else leer_importe(r.get("debe"))
        haber = r["haber"] if isinstance(r.get("haber"), Decimal) else leer_importe(r.get("haber"))
        cta = r.get("id_cuenta")
        if not cta and not debe and not haber:
            continue
        if debe is None or haber is None:
            errores.append(f"Renglón {i}: importe inválido.")
            continue
        if debe < 0 or haber < 0:
            errores.append(f"Renglón {i}: los importes van en positivo (el lado lo da la columna).")
            continue
        if debe and haber:
            errores.append(f"Renglón {i}: va al debe o al haber, no a los dos.")
            continue
        if not debe and not haber:
            errores.append(f"Renglón {i}: falta el importe.")
            continue
        c = cuentas.get(int(cta)) if str(cta or "").isdigit() else None
        if not c:
            errores.append(f"Renglón {i}: elegí la cuenta.")
            continue
        if not c["permite_movimiento"]:
            errores.append(f"Renglón {i}: {c['codigo']} {c['nombre']} es un título, no es imputable.")
            continue
        if not c["activa"]:
            errores.append(f"Renglón {i}: {c['codigo']} {c['nombre']} está inactiva.")
            continue
        td += debe
        th += haber
        buenos.append({"id_cuenta": c["id_cuenta"], "debe": debe, "haber": haber,
                       "descripcion": (str(r.get("descripcion") or "").strip()[:255] or None)})
    if len(buenos) < 2 and not errores:
        errores.append("El asiento necesita al menos dos renglones.")
    if buenos and td != th:
        errores.append(f"No balancea: debe {pesos(td)} y haber {pesos(th)} (diferencia {pesos(td - th)}).")
    return buenos, errores, td, th


def proximo_numero(cur, id_ejercicio) -> int:
    """El siguiente número del ejercicio. Bloquea la fila del ejercicio para que
    dos cargas a la vez no tomen el mismo."""
    cur.execute("SELECT id_ejercicio FROM c_ejercicios WHERE id_ejercicio = %s FOR UPDATE", (id_ejercicio,))
    cur.execute("""SELECT COALESCE(MAX(a.numero), 0) + 1 AS n FROM c_asientos a
                     JOIN c_periodos p ON p.id_periodo = a.id_periodo WHERE p.id_ejercicio = %s""", (id_ejercicio,))
    return int(cur.fetchone()["n"])


def periodo_para(cur, fecha: datetime.date) -> dict:
    """El período abierto de la fecha, o el error."""
    per = periodo_de_fecha(cur, fecha)
    if not per:
        raise ErrorContable(f"El {fecha:%d/%m/%Y} no es de ningún ejercicio: abrí el ejercicio en Contabilidad › "
                            "Ejercicios.")
    if per["estado"] != "abierto":
        raise ErrorContable(f"El período {per['nombre']} está {per['estado']}: no admite asientos.")
    return per


def leer_asiento(cur, id_asiento) -> dict | None:
    cur.execute("""SELECT a.*, p.nombre AS periodo, p.estado AS estado_periodo, p.id_ejercicio, e.nombre AS ejercicio
                     FROM c_asientos a JOIN c_periodos p ON p.id_periodo = a.id_periodo
                     LEFT JOIN c_ejercicios e ON e.id_ejercicio = p.id_ejercicio
                    WHERE a.id_asiento = %s""", (id_asiento,))
    a = cur.fetchone()
    if not a:
        return None
    cur.execute("""SELECT d.*, c.codigo, c.nombre AS cuenta FROM c_asiento_detalle d
                     JOIN c_plan_de_cuentas c ON c.id_cuenta = d.id_cuenta
                    WHERE d.id_asiento = %s ORDER BY d.id_detalle""", (id_asiento,))
    a["renglones"] = cur.fetchall()
    a["total_debe"] = sum((_d(r["debe"]) for r in a["renglones"]), Decimal("0.00"))
    a["total_haber"] = sum((_d(r["haber"]) for r in a["renglones"]), Decimal("0.00"))
    return a


def grabar(cur, cab: dict, renglones: list[dict], usuario, id_asiento=None, estado="borrador",
           origen=None, id_origen=None, cuentas=None, numero=None, con_origen=False) -> dict:
    """Alta o edición de un asiento (en borrador, o confirmado si lo pide quien
    importa). `cab`: fecha, descripcion, tipo, referencia. Devuelve
    {id_asiento, numero, periodo}. Con el cursor de una transacción."""
    fecha = fecha_de(cab.get("fecha"))
    descripcion = re.sub(r"\s+", " ", str(cab.get("descripcion") or "")).strip()[:255]
    tipo = (cab.get("tipo") or "operacion").strip().lower()
    referencia = (str(cab.get("referencia") or "").strip()[:80] or None)
    errores = []
    if not fecha:
        errores.append("La fecha es obligatoria (dd/mm/aaaa).")
    if not descripcion:
        errores.append("La descripción es obligatoria.")
    if tipo not in TIPOS:
        errores.append(f"El tipo «{tipo}» no existe: {', '.join(TIPOS)}.")
    buenos, err_r, _, _ = validar_renglones(renglones, cuentas or cuentas_por_id(cur))
    errores += err_r
    if errores:
        raise ErrorContable(" ".join(errores))
    per = periodo_para(cur, fecha)
    if id_asiento:
        cur.execute("""SELECT a.estado, a.numero, p.id_ejercicio, p.estado AS estado_periodo, p.nombre
                         FROM c_asientos a JOIN c_periodos p ON p.id_periodo = a.id_periodo
                        WHERE a.id_asiento = %s FOR UPDATE""", (id_asiento,))
        viejo = cur.fetchone()
        if not viejo:
            raise ErrorContable("No existe ese asiento.")
        if viejo["estado"] != "borrador":
            raise ErrorContable(f"El asiento N° {viejo['numero']} está {viejo['estado']}: ya no se modifica.")
        if viejo["estado_periodo"] != "abierto":
            raise ErrorContable(f"El período {viejo['nombre']} está {viejo['estado_periodo']}.")
        num = viejo["numero"] if viejo["id_ejercicio"] == per["id_ejercicio"] else proximo_numero(cur, per["id_ejercicio"])
        cur.execute("""UPDATE c_asientos SET id_periodo = %s, numero = %s, fecha = %s, descripcion = %s, tipo = %s,
                              referencia = %s WHERE id_asiento = %s""",
                    (per["id_periodo"], num, fecha, descripcion, tipo, referencia, id_asiento))
        cur.execute("DELETE FROM c_asiento_detalle WHERE id_asiento = %s", (id_asiento,))
    else:
        num = numero or proximo_numero(cur, per["id_ejercicio"])
        if con_origen:
            cur.execute("""INSERT INTO c_asientos (id_periodo, numero, fecha, descripcion, tipo, referencia, estado,
                                                   usuario, origen, id_origen)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (per["id_periodo"], num, fecha, descripcion, tipo, referencia, estado, usuario,
                         origen, id_origen))
        else:
            cur.execute("""INSERT INTO c_asientos (id_periodo, numero, fecha, descripcion, tipo, referencia, estado,
                                                   usuario)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                        (per["id_periodo"], num, fecha, descripcion, tipo, referencia, estado, usuario))
        id_asiento = cur.lastrowid
    cur.executemany("""INSERT INTO c_asiento_detalle (id_asiento, id_cuenta, debe, haber, descripcion)
                       VALUES (%s, %s, %s, %s, %s)""",
                    [(id_asiento, r["id_cuenta"], r["debe"], r["haber"], r["descripcion"]) for r in buenos])
    return {"id_asiento": id_asiento, "numero": num, "periodo": per["nombre"]}


def _bloquear_borrador(cur, id_asiento) -> dict:
    cur.execute("""SELECT a.*, p.estado AS estado_periodo, p.nombre AS periodo FROM c_asientos a
                     JOIN c_periodos p ON p.id_periodo = a.id_periodo WHERE a.id_asiento = %s FOR UPDATE""",
                (id_asiento,))
    a = cur.fetchone()
    if not a:
        raise ErrorContable("No existe ese asiento.")
    if a["estado"] != "borrador":
        raise ErrorContable(f"El asiento N° {a['numero']} ya está {a['estado']}.")
    if a["estado_periodo"] != "abierto":
        raise ErrorContable(f"El período {a['periodo']} está {a['estado_periodo']}.")
    return a


def confirmar(cur, id_asiento) -> dict:
    """Pasa un borrador a confirmado, si balancea."""
    a = _bloquear_borrador(cur, id_asiento)
    cur.execute("""SELECT COUNT(*) AS n, COALESCE(SUM(debe), 0) AS d, COALESCE(SUM(haber), 0) AS h
                     FROM c_asiento_detalle WHERE id_asiento = %s""", (id_asiento,))
    t = cur.fetchone()
    if t["n"] < 2:
        raise ErrorContable(f"El asiento N° {a['numero']} tiene menos de dos renglones.")
    if _d(t["d"]) != _d(t["h"]):
        raise ErrorContable(f"El asiento N° {a['numero']} no balancea: debe {pesos(t['d'])}, haber {pesos(t['h'])}.")
    cur.execute("UPDATE c_asientos SET estado = 'confirmado' WHERE id_asiento = %s", (id_asiento,))
    return a


def eliminar_borrador(cur, id_asiento) -> dict:
    a = _bloquear_borrador(cur, id_asiento)
    cur.execute("DELETE FROM c_asientos WHERE id_asiento = %s", (id_asiento,))   # el detalle va en cascada
    return a


def renumerar(cur, id_ejercicio) -> int:
    """Renumera el ejercicio: la apertura primero, el resto por fecha y carga
    (los anulados también: conservan su lugar). Devuelve cuántos."""
    cur.execute("SELECT id_ejercicio FROM c_ejercicios WHERE id_ejercicio = %s FOR UPDATE", (id_ejercicio,))
    cur.execute("""SELECT a.id_asiento FROM c_asientos a JOIN c_periodos p ON p.id_periodo = a.id_periodo
                    WHERE p.id_ejercicio = %s
                    ORDER BY a.tipo = 'apertura' DESC, a.fecha, a.tipo = 'cierre', a.id_asiento""", (id_ejercicio,))
    ids = [f["id_asiento"] for f in cur.fetchall()]
    # Primero a negativos: el índice único (período, número) no admite el cruce.
    cur.executemany("UPDATE c_asientos SET numero = %s WHERE id_asiento = %s", [(-i, x) for i, x in enumerate(ids, 1)])
    cur.executemany("UPDATE c_asientos SET numero = %s WHERE id_asiento = %s", [(i, x) for i, x in enumerate(ids, 1)])
    return len(ids)


# =============================================================================
# Listado y libro
# =============================================================================

def filtro_sql(f: dict) -> tuple[str, list]:
    """WHERE del Diario: ejercicio, período, estado, desde, hasta, cuenta, q."""
    w, p = ["1 = 1"], []
    if f.get("ejercicio"):
        w.append("p.id_ejercicio = %s"); p.append(f["ejercicio"])
    if f.get("periodo"):
        w.append("a.id_periodo = %s"); p.append(f["periodo"])
    if f.get("estado"):
        w.append("a.estado = %s"); p.append(f["estado"])
    elif f.get("sin_anulados"):
        w.append("a.estado <> 'anulado'")
    if f.get("desde"):
        w.append("a.fecha >= %s"); p.append(f["desde"])
    if f.get("hasta"):
        w.append("a.fecha <= %s"); p.append(f["hasta"])
    if f.get("cuenta"):
        w.append("EXISTS (SELECT 1 FROM c_asiento_detalle dx WHERE dx.id_asiento = a.id_asiento AND dx.id_cuenta = %s)")
        p.append(f["cuenta"])
    if f.get("tipo"):
        w.append("a.tipo = %s"); p.append(f["tipo"])
    return " AND ".join(w), p


def listar(cur, f: dict, tope: int = 5000) -> tuple[list[dict], bool]:
    where, params = filtro_sql(f)
    cur.execute(f"""SELECT a.id_asiento, a.numero, a.fecha, a.descripcion, a.tipo, a.referencia, a.estado, a.usuario,
                           p.nombre AS periodo, p.estado AS estado_periodo,
                           COALESCE(SUM(d.debe), 0) AS total_debe, COALESCE(SUM(d.haber), 0) AS total_haber,
                           COUNT(d.id_detalle) AS renglones
                      FROM c_asientos a
                      JOIN c_periodos p ON p.id_periodo = a.id_periodo
                      LEFT JOIN c_asiento_detalle d ON d.id_asiento = a.id_asiento
                     WHERE {where}
                     GROUP BY a.id_asiento
                     ORDER BY a.fecha DESC, a.numero DESC
                     LIMIT %s""", params + [tope + 1])
    filas = cur.fetchall()
    return filas[:tope], len(filas) > tope


def renglones_libro(cur, f: dict) -> list[dict]:
    """Un renglón por imputación, en el orden del libro."""
    where, params = filtro_sql(f)
    cur.execute(f"""SELECT a.id_asiento, a.numero, a.fecha, a.tipo, a.descripcion, a.referencia, a.estado,
                           p.nombre AS periodo, c.codigo AS codigo_cuenta, c.nombre AS nombre_cuenta,
                           d.descripcion AS detalle, d.debe, d.haber
                      FROM c_asientos a
                      JOIN c_periodos p ON p.id_periodo = a.id_periodo
                      JOIN c_asiento_detalle d ON d.id_asiento = a.id_asiento
                      JOIN c_plan_de_cuentas c ON c.id_cuenta = d.id_cuenta
                     WHERE {where}
                     ORDER BY a.fecha, a.numero, a.id_asiento, d.haber > 0, d.id_detalle""", params)
    return cur.fetchall()


# =============================================================================
# Importar desde un archivo (el modelo de gestion_adm)
# =============================================================================

def leer_archivo(nombre: str, contenido: bytes) -> list[dict]:
    """Las filas del CSV o XLSX como dicts con las claves de COLS_ARCHIVO.
    Saltea una fila de instrucciones arriba del encabezado (la del modelo)."""
    ext = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
    if ext == "csv":
        texto = contenido.decode("utf-8-sig", errors="replace")
        muestra = texto[:2000]
        sep = ";" if muestra.count(";") > muestra.count(",") else ","
        filas = list(csv.reader(io.StringIO(texto), delimiter=sep))
    elif ext == "xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(contenido), data_only=True, read_only=True)
        filas = [list(r) for r in wb.active.iter_rows(values_only=True)]
    else:
        raise ErrorContable("El archivo tiene que ser .xlsx o .csv.")
    cab_i = next((i for i, r in enumerate(filas[:5])
                  if sum(1 for v in r if _ALIAS_COL.get(str(v or "").strip().lower())) >= 4), None)
    if cab_i is None:
        raise ErrorContable("No encuentro el encabezado (N° Asiento, Fecha, Tipo, Descripción, Código cuenta, Debe, Haber). "
                            "Bajá el modelo.")
    claves = [_ALIAS_COL.get(str(v or "").strip().lower()) for v in filas[cab_i]]
    out = []
    for n, r in enumerate(filas[cab_i + 1:], start=cab_i + 2):
        if not any(v not in (None, "") for v in r):
            continue
        d = {"_fila": n}
        for k, v in zip(claves, r):
            if k:
                d[k] = v
        out.append(d)
    return out


def agrupar_archivo(filas: list[dict], cuentas_codigo: dict) -> tuple[list[dict], list[str]]:
    """Agrupa por N° de asiento (del archivo: solo agrupa, no es el número que
    queda) y arma la cabecera y los renglones. `cuentas_codigo`: código → id
    (se acepta con o sin guiones/puntos)."""
    errores, grupos = [], defaultdict(list)
    for f in filas:
        nro = str(f.get("nro_asiento") or "").strip()
        if nro.endswith(".0"):
            nro = nro[:-2]
        if not nro:
            errores.append(f"Fila {f['_fila']}: falta el N° de asiento.")
            continue
        grupos[nro].append(f)
    asientos = []
    for nro, lineas in grupos.items():
        p = lineas[0]
        renglones = []
        for f in lineas:
            cod = re.sub(r"\D", "", str(f.get("codigo_cuenta") or ""))
            renglones.append({"id_cuenta": cuentas_codigo.get(cod), "codigo": f.get("codigo_cuenta"),
                              "debe": f.get("debe"), "haber": f.get("haber"),
                              "descripcion": f.get("descripcion_item"), "_fila": f["_fila"]})
        sin_cta = [r for r in renglones if not r["id_cuenta"]]
        asientos.append({"nro": nro, "fecha": fecha_de(p.get("fecha")),
                         "tipo": (str(p.get("tipo") or "operacion").strip().lower() or "operacion"),
                         "descripcion": p.get("descripcion"), "referencia": p.get("referencia"),
                         "renglones": renglones,
                         "error": (f"la cuenta {sin_cta[0]['codigo'] or '(vacía)'} (fila {sin_cta[0]['_fila']}) "
                                   "no está en el plan") if sin_cta else None})
    asientos.sort(key=lambda a: (a["fecha"] or datetime.date.max, a["nro"]))
    return asientos, errores


def importar(cur, asientos: list[dict], usuario, con_origen=False) -> dict:
    """Graba cada asiento del archivo en BORRADOR (para revisarlo y confirmarlo
    en el Diario), con su número correlativo del ejercicio. Uno que falla no
    frena a los demás: se informa. Con el cursor de una transacción (un
    SAVEPOINT por asiento)."""
    cuentas = cuentas_por_id(cur)
    res = {"grabados": 0, "errores": []}
    for a in asientos:
        if a.get("error"):
            res["errores"].append(f"Asiento {a['nro']}: {a['error']}.")
            continue
        cur.execute("SAVEPOINT imp")
        try:
            grabar(cur, a, a["renglones"], usuario, cuentas=cuentas, origen="excel", con_origen=con_origen)
            cur.execute("RELEASE SAVEPOINT imp")
            res["grabados"] += 1
        except ErrorContable as e:
            cur.execute("ROLLBACK TO SAVEPOINT imp")
            res["errores"].append(f"Asiento {a['nro']}: {e}")
    return res


def tiene_origen(cur) -> bool:
    """¿Se corrió sql/contabilidad_diario_20261118.sql?"""
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.columns WHERE table_schema = DATABASE()
                    AND table_name = 'c_asientos' AND column_name = 'origen'""")
    return bool(cur.fetchone()["n"])
