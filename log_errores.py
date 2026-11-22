# -*- coding: utf-8 -*-
"""
log_errores.py — El registro de los errores que se producen en el sistema
Prefijo: /admin  (comparte el de admin.py; la pantalla es /admin/errores)

Es el log de errores de gestion_adm (22/11/2026), con la sesión, el permiso y
la grilla de acá. Se registra en app.py lo más arriba posible, antes que los
blueprints, así los errores de cualquier pantalla quedan anotados:

    import log_errores
    log_errores.instalar(app)
    app.register_blueprint(log_errores.errores_bp)

POR QUE
-------
Hasta ahora un error sólo quedaba en el log de Railway (o en el de wfastcgi):
para saber qué pasó había que entrar ahí, buscar por hora y adivinar quién era.
Y los errores que el código ataja (`except Exception as e: flash(f"!No se
pudo: {e}")`) no quedaban en ningún lado: el usuario veía el cartel y nadie
más se enteraba.

QUE SE REGISTRA (s_log_errores, sql/s_log_errores_20261122.sql)
---------------------------------------------------------------
Una fila con la fecha y hora, el usuario, el método y la URL, el error (tipo
y mensaje) y el traceback, para tres casos:

  excepcion  Una excepción que nadie atajó: la que termina en el 500
             («La pantalla no se pudo abrir», templates/500.html, que muestra
             el número de la fila).
  respuesta  Una respuesta 500 o más que el código armó a mano, sin que se
             escapara una excepción (las API que hacen
             `return jsonify(error=str(e)), 500`). El mensaje es el «error»
             del JSON, o el principio del texto.
  aviso      Un `flash()` dentro de un `except`: el error que la pantalla
             atajó y le mostró al usuario. Se reconoce porque al momento del
             flash hay una excepción en curso (sys.exc_info()); los flash de
             validación («Ingresá el CUIT») no la tienen y no se anotan.
             Tampoco se anotan los que vienen de un ValueError (el
             `float(importe)` de una validación) ni de una excepción propia
             de una regla de negocio (las de reintegros_datos, pagos_datos,
             asientos…): le explican algo al usuario, no son fallas. Sí se
             anotan las propias que envuelven un servicio de afuera que no
             respondió (correo, ARCA, contable de OSEDA): ver _SERVICIOS.

Los 404 y los «no tenés permiso» no son errores del sistema: no se anotan.

Lo que NO llega acá: los errores de los procesos sin pantalla (importadores,
el envío de campañas en segundo plano) —no tienen URL ni usuario; siguen en
sus propios logs—, y los `except` que devuelven `{"ok": false}` con 200 sin
hacer flash.

REPETICIONES
------------
El mismo error (misma «firma»: tipo + el lugar del código donde saltó, o la
pantalla y el mensaje) del mismo usuario dentro de 5 minutos no abre otra
fila: suma `veces` y corre `ultima`. Una pantalla que se recarga sola o el
contador de Mensajes que consulta cada 20 segundos no llenan la tabla.

Se guarda 180 días: de vez en cuando (1 de cada 500 anotaciones) se borra lo
más viejo.

NUNCA ROMPE NADA
----------------
Anotar un error no puede producir otro: todo va envuelto, y si no se puede
escribir en la base (la base es lo que falló, falta la tabla) queda el aviso
en el log de la aplicación y la pantalla sigue como hubiera seguido.

LO QUE NO SE GUARDA
-------------------
El cuerpo del formulario: puede traer contraseñas, claves fiscales o datos
de afiliados. De la URL se tapan los parámetros que parecen secretos
(clave, password, token…).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import io
import json
import logging
import os
import random
import re
import sys
import traceback

from flask import (Blueprint, flash, g, has_request_context, redirect,
                   render_template, request, send_file, session, url_for)
from flask.signals import got_request_exception, message_flashed

import paginar
from db import get_connection, puede, validasesion

log = logging.getLogger(__name__)

errores_bp = Blueprint("errores", __name__, url_prefix="/admin")

#: Ventana en la que el mismo error del mismo usuario suma en vez de abrir fila.
VENTANA_MIN = 5
#: Cuánto se guarda.
RETENCION_DIAS = 180

_RAIZ = os.path.dirname(os.path.abspath(__file__))
_SECRETO = re.compile(r"(pass|clave|token|secret|key|pwd|contrase)", re.I)
#: La hora del negocio (el contenedor de Railway corre en UTC).
_ART = _dt.timezone(_dt.timedelta(hours=-3))


# ── Armado de la fila ────────────────────────────────────────────────────────

def _url_sin_secretos() -> str:
    """La URL pedida, con los parámetros que parecen secretos tapados."""
    if not request.args:
        return request.path
    partes = []
    for k, v in request.args.items(multi=True):
        partes.append(f"{k}={'***' if _SECRETO.search(k) else v}")
    return (request.path + "?" + "&".join(partes))[:1000]


def _lugar(tb) -> str:
    """El último renglón del traceback que es código nuestro (no de Flask ni de pymysql)."""
    lugar = ""
    for f in traceback.extract_tb(tb):
        if f.filename.startswith(_RAIZ) and "site-packages" not in f.filename:
            lugar = f"{os.path.relpath(f.filename, _RAIZ)}:{f.lineno} {f.name}"
    return lugar


def _firma(*partes) -> str:
    return hashlib.sha1("|".join(str(p) for p in partes).encode("utf-8", "replace")).hexdigest()


def registrar(origen: str, exc: BaseException | None = None, mensaje: str | None = None,
              status: int | None = None) -> int | None:
    """
    Anota un error del request en curso. Devuelve el id de la fila, o None.
    Nunca lanza. Se puede llamar a mano desde una ruta:
        except Exception as e:
            log_errores.registrar("aviso", e)
    """
    if not has_request_context():
        return None
    try:
        tipo, detalle, lugar = "", "", ""
        if exc is not None:
            tipo = type(exc).__name__
            if not mensaje:
                mensaje = str(exc)
            tb = exc.__traceback__
            detalle = "".join(traceback.format_exception(type(exc), exc, tb))
            lugar = _lugar(tb)
        mensaje = (mensaje or "").strip() or "(sin mensaje)"
        endpoint = request.endpoint or ""
        firma = _firma(origen, tipo, lugar or endpoint, "" if lugar else mensaje[:120])
        id_usuario = session.get("sind_usuario_id") if session else None
        usuario = (session.get("sind_usuario_nombre") or session.get("sind_usuario_email") or "") if session else ""
        fila = {
            "origen": origen, "status": status, "tipo": tipo[:150], "mensaje": mensaje[:4000],
            "detalle": detalle[:60000] or None, "lugar": lugar[:300] or None, "firma": firma,
            "id_usuario": id_usuario, "usuario": usuario[:150] or None,
            "metodo": request.method[:10], "url": _url_sin_secretos(), "endpoint": endpoint[:150] or None,
            "referer": (request.referrer or "")[:500] or None,
            "ip": (request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip())[:64] or None,
            "navegador": (request.user_agent.string or "")[:300] or None,
        }
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""SELECT id FROM s_log_errores
                                 WHERE firma = %s AND id_usuario <=> %s
                                   AND ultima >= NOW() - INTERVAL {VENTANA_MIN} MINUTE
                                 ORDER BY id DESC LIMIT 1""", (firma, id_usuario))
                previa = cur.fetchone()
                if previa:
                    cur.execute("UPDATE s_log_errores SET veces = veces + 1, ultima = NOW(), url = %s "
                                "WHERE id = %s", (fila["url"], previa["id"]))
                    id_fila = int(previa["id"])
                else:
                    cols = ", ".join(fila)
                    cur.execute(f"INSERT INTO s_log_errores ({cols}) VALUES ({', '.join(['%s'] * len(fila))})",
                                list(fila.values()))
                    id_fila = int(cur.lastrowid)
                if random.random() < 0.002:
                    cur.execute(f"DELETE FROM s_log_errores WHERE ultima < NOW() - INTERVAL {RETENCION_DIAS} DAY "
                                "LIMIT 5000")
        g.log_error_id = id_fila
        return id_fila
    except Exception as e:                                   # noqa: BLE001
        log.warning("No se pudo anotar el error en s_log_errores: %s: %s", type(e).__name__, e)
        return None


# ── Los ganchos ──────────────────────────────────────────────────────────────

def _al_excepcion(sender, exception, **_):
    """Una excepción que se escapó de la ruta (Flask manda la señal antes del handler del 500)."""
    from werkzeug.exceptions import HTTPException
    if isinstance(exception, HTTPException) and (exception.code or 500) < 500:
        return
    registrar("excepcion", exception, status=500)


#: Módulos propios cuyas excepciones son un servicio de afuera que falló, no
#: una regla de negocio: ésas sí van al log aunque las defina nuestro código.
_SERVICIOS = ("mailer", "correo", "arca_wscdc", "arca_padron", "arca_constancia", "empleadores_arca",
              "contable_oseda", "lector_pdf_ocr", "pagos_pdf", "instructivo_empresa")


def _es_aviso_de_negocio(exc: BaseException) -> bool:
    """¿La excepción es una validación o una regla de negocio, y no una falla?"""
    if type(exc) is ValueError:
        return True
    modulo = type(exc).__module__ or ""
    archivo = getattr(sys.modules.get(modulo), "__file__", "") or ""
    # Las de Python (KeyError, OSError…) no tienen archivo: no son propias. Ojo
    # que abspath("") da la carpeta actual, que es la de la aplicación.
    propia = bool(archivo) and os.path.abspath(archivo).startswith(_RAIZ) and "site-packages" not in archivo
    return propia and modulo.split(".")[0] not in _SERVICIOS


def _al_flash(sender, message, category, **_):
    """Un flash dentro de un except: el error que la pantalla atajó y mostró."""
    exc = sys.exc_info()[1]
    if exc is None or g.get("_flash_registrado") is exc or _es_aviso_de_negocio(exc):
        return
    g._flash_registrado = exc
    texto = str(message)
    registrar("aviso", exc, mensaje=texto[1:] if texto.startswith("!") else texto)


def _despues(respuesta):
    """Una respuesta 500 o más que no vino de una excepción ya anotada."""
    try:
        if respuesta.status_code >= 500 and "log_error_id" not in g \
                and request.endpoint not in ("static",):
            mensaje = ""
            if respuesta.is_json:
                datos = respuesta.get_json(silent=True) or {}
                if isinstance(datos, dict):
                    mensaje = str(datos.get("error") or datos.get("mensaje") or datos.get("detalle") or "")
                if not mensaje:
                    mensaje = json.dumps(datos, ensure_ascii=False)[:500]
            elif not respuesta.direct_passthrough and respuesta.mimetype in ("text/plain", "text/html"):
                texto = respuesta.get_data(as_text=True)
                mensaje = re.sub(r"<[^>]+>|\s+", " ", texto).strip()[:500] if len(texto) < 200000 else ""
            registrar("respuesta", mensaje=mensaje or f"Respuesta {respuesta.status_code}",
                      status=respuesta.status_code)
    except Exception as e:                                   # noqa: BLE001
        log.warning("log_errores: no se pudo revisar la respuesta: %s", e)
    return respuesta


def instalar(app) -> None:
    """Engancha el registro. Una vez, al arrancar."""
    got_request_exception.connect(_al_excepcion, app, weak=False)
    message_flashed.connect(_al_flash, app, weak=False)
    app.after_request(_despues)


# ── La pantalla ──────────────────────────────────────────────────────────────

ORIGENES = {"excepcion": ("Excepción", "danger"), "respuesta": ("Respuesta 500", "warn"),
            "aviso": ("Atajado", "info")}

_RE_FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")

#: Las columnas que ordenan: clave del th[data-col] → expresión SQL.
ORDENES = {"fecha": "e.ultima", "usuario": "e.usuario", "url": "e.url", "error": "e.tipo",
           "estado": "e.revisado"}


def _filtros(args):
    f = {"q": (args.get("q") or "").strip(), "usuario": (args.get("usuario") or "").strip(),
         "origen": args.get("origen") or "", "desde": args.get("desde") or "",
         "hasta": args.get("hasta") or "", "estado": args.get("estado") or "pendientes",
         "orden": args.get("orden") if args.get("orden") in ORDENES else "",
         "dir": "asc" if args.get("dir") == "asc" else "desc"}
    where, params = ["1=1"], []
    if f["q"]:
        where.append("(e.mensaje LIKE %s OR e.tipo LIKE %s OR e.url LIKE %s OR e.lugar LIKE %s)")
        params += [f"%{f['q']}%"] * 4
    if f["usuario"].isdigit():
        where.append("e.id_usuario = %s")
        params.append(int(f["usuario"]))
    if f["origen"] in ORIGENES:
        where.append("e.origen = %s")
        params.append(f["origen"])
    if _RE_FECHA.fullmatch(f["desde"]):
        where.append("e.ultima >= %s")
        params.append(f["desde"])
    if _RE_FECHA.fullmatch(f["hasta"]):
        where.append("e.fecha < %s + INTERVAL 1 DAY")
        params.append(f["hasta"])
    if f["estado"] == "pendientes":
        where.append("e.revisado = 0")
    elif f["estado"] == "revisados":
        where.append("e.revisado = 1")
    return " AND ".join(where), params, f


def _order_by(f) -> str:
    """Lo más reciente primero, salvo que se ordene por una columna."""
    if not f["orden"]:
        return "e.ultima DESC, e.id DESC"
    return f"{ORDENES[f['orden']]} {f['dir'].upper()}, e.ultima DESC, e.id DESC"


def _guardia():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede(url_for("errores.errores")):
        flash("!No tenés permiso para esa pantalla.")
        return redirect(url_for("menu"))
    return None


def _volver_ok(url: str) -> bool:
    return bool(url) and url.startswith("/admin/errores") and not url.startswith("//")


@errores_bp.route("/errores", methods=["GET", "POST"])
def errores():
    """El log de errores: qué falló, dónde, a quién y cuándo."""
    corte = _guardia()
    if corte:
        return corte

    if request.method == "POST":
        ids = [int(x) for x in request.form.getlist("id") if x.isdigit()]
        revisado = 1 if request.form.get("revisado", "1") == "1" else 0
        if ids:
            marcas = ",".join(["%s"] * len(ids))
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""UPDATE s_log_errores
                                       SET revisado = %s, revisado_por = %s, revisado_el = IF(%s, NOW(), NULL)
                                     WHERE id IN ({marcas})""",
                                [revisado, session.get("sind_usuario_nombre") if revisado else None, revisado] + ids)
            flash(f"{len(ids)} error(es) marcados como revisados." if revisado else "El error vuelve a pendientes.")
        else:
            flash("!Tildá los errores a marcar.")
        volver = request.form.get("volver") or ""
        return redirect(volver if _volver_ok(volver) else url_for("errores.errores"))

    tam = paginar.tamano(request.args.get("tam"))
    pag = paginar.pagina(request.args.get("pagina"))
    where, params, f = _filtros(request.args)
    filas, total, resumen, usuarios, error = [], 0, {}, [], None
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) AS n FROM s_log_errores e WHERE {where}", params)
                total = int(cur.fetchone()["n"])
                paginas = max(1, -(-total // tam))
                pag = min(pag, paginas)
                cur.execute(f"""SELECT e.id, e.fecha, e.ultima, e.veces, e.origen, e.status, e.tipo, e.mensaje,
                                       e.lugar, e.usuario, e.id_usuario, e.metodo, e.url, e.endpoint, e.referer,
                                       e.ip, e.navegador, e.detalle, e.revisado, e.revisado_por, e.revisado_el
                                  FROM s_log_errores e WHERE {where}
                                 ORDER BY {_order_by(f)}
                                 LIMIT {tam} OFFSET {(pag - 1) * tam}""", params)
                filas = cur.fetchall()
                cur.execute("""SELECT SUM(revisado = 0) AS pendientes,
                                      SUM(ultima >= CURDATE()) AS hoy,
                                      SUM(ultima >= CURDATE() - INTERVAL 6 DAY) AS semana,
                                      COUNT(DISTINCT CASE WHEN revisado = 0 THEN firma END) AS distintos
                                 FROM s_log_errores""")
                resumen = cur.fetchone() or {}
                cur.execute("""SELECT DISTINCT id_usuario, usuario FROM s_log_errores
                                WHERE id_usuario IS NOT NULL ORDER BY usuario""")
                usuarios = cur.fetchall()
    except Exception as e:                                   # noqa: BLE001
        error = ("Falta la tabla del log: correr sql/s_log_errores_20261122.sql."
                 if "1146" in str(e) else f"No se pudo leer el log: {e}")
    args = dict(f, tam=tam if tam != paginar.TAMANO_DEFAULT else "")
    return render_template("admin/errores.html", filas=filas, f=f, resumen=resumen, usuarios=usuarios,
                           origenes=ORIGENES, error=error, tam=tam,
                           pag=paginar.paginador(total, pag, tam, "errores.errores", args),
                           hoy_iso=_dt.datetime.now(_ART).strftime("%Y-%m-%d"))


@errores_bp.route("/errores/exportar")
def exportar():
    """El log a Excel con los filtros de la pantalla: todas las filas, no sólo la página."""
    corte = _guardia()
    if corte:
        return corte
    from exportar import xlsx
    where, params, f = _filtros(request.args)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""SELECT e.id, e.fecha, e.ultima, e.veces, e.origen, e.tipo, e.mensaje, e.lugar,
                                   e.usuario, e.metodo, e.url, e.revisado, e.revisado_por
                              FROM s_log_errores e WHERE {where}
                             ORDER BY {_order_by(f)} LIMIT 20000""", params)
            filas = cur.fetchall()
    columnas = [{"titulo": t, "tipo": tp} for t, tp in (
        ("Código", "n"), ("Primera vez", ""), ("Última vez", ""), ("Veces", "n"), ("Tipo", ""),
        ("Error", ""), ("Mensaje", ""), ("Lugar", ""), ("Usuario", ""), ("Método", ""), ("Dirección", ""),
        ("Estado", ""), ("Revisó", ""))]
    datos = [[str(r["id"]), r["fecha"].strftime("%d/%m/%Y %H:%M:%S"), r["ultima"].strftime("%d/%m/%Y %H:%M:%S"),
              str(r["veces"]), ORIGENES.get(r["origen"], (r["origen"],))[0], r["tipo"] or "", r["mensaje"] or "",
              r["lugar"] or "", r["usuario"] or "", r["metodo"] or "", r["url"] or "",
              "Revisado" if r["revisado"] else "Pendiente", r["revisado_por"] or ""] for r in filas]
    return send_file(io.BytesIO(xlsx("Log de errores", columnas, datos)),
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     as_attachment=True,
                     download_name=f"Log_de_errores_{_dt.datetime.now(_ART):%Y%m%d_%H%M}.xlsx")
