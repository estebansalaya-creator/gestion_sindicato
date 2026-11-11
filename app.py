"""
app.py — Entrypoint de la aplicación `sindicato`.

Corre en su propio proceso y su propio sitio de IIS. No comparte nada con
`gestion_adm`: ni módulos, ni base, ni cookie de sesión.

Para levantar en desarrollo: completar el .env de esta carpeta y correr

    python app.py
"""

import itertools
import os
import re
from pathlib import Path

from dotenv import load_dotenv

# El .env se resuelve contra este archivo y no contra el directorio de trabajo.
# `load_dotenv()` sin argumentos busca desde el cwd hacia arriba, y el cwd no
# es algo que uno controle: IIS arranca el proceso donde quiere y una tarea
# programada usa lo que diga «Iniciar en». Con la ruta explícita es siempre el
# mismo archivo, se lance desde donde se lance.
load_dotenv(Path(__file__).with_name(".env"))

from flask import (Flask, render_template, request, redirect,   # noqa: E402
                   url_for, session, flash)
from markupsafe import Markup                                   # noqa: E402
from werkzeug.security import check_password_hash               # noqa: E402

from db import get_connection, validasesion, puede, roles_y_menu  # noqa: E402
from gestion_sindicato import sindicato_bp                      # noqa: E402
from empleadores import empleadores_bp                          # noqa: E402
from contactos import contactos_bp                              # noqa: E402
from afiliados import afiliados_bp                              # noqa: E402
from afiliados_tablas import tablas_bp as afiliados_tablas_bp   # noqa: E402
from afiliados_metricas import metricas_bp                      # noqa: E402
from exportar import exportar_bp                                # noqa: E402
from reintegros import reintegros_bp                            # noqa: E402
from institucion import institucion_bp, encabezado as encabezado_institucion  # noqa: E402
from proveedores import proveedores_bp                          # noqa: E402
from comprobantes import comprobantes_bp                        # noqa: E402
from mis_comprobantes import mis_comp_bp                        # noqa: E402
from mesa import mesa_bp                                        # noqa: E402
from tesoreria import tesoreria_bp                              # noqa: E402
from tesoreria_movimientos import tes_mov_bp                    # noqa: E402
from tesoreria_panel import tes_panel_bp                         # noqa: E402
from transferencias import transferencias_bp                    # noqa: E402
from tesoreria_rg830 import rg830_bp                            # noqa: E402
from contabilidad import contabilidad_bp                        # noqa: E402
from pagos import pagos_bp                                      # noqa: E402
from admin import admin_bp                                      # noqa: E402
from talonarios import talonarios_bp                            # noqa: E402
from fisca_liquidacion import fisca_liq_bp                      # noqa: E402
from cc_proveedores import cc_prov_bp                           # noqa: E402


def _secret_key() -> str:
    """
    La clave que firma la cookie de sesión.

    Sin default y sin generarla al vuelo: una clave aleatoria por arranque
    parece funcionar en desarrollo —y de hecho funciona— pero invalida todas
    las sesiones en cada reinicio, y con varios workers de IIS cada uno firma
    con una clave distinta, así que la sesión se cae según qué worker atienda.
    Es un problema que aparece recién en producción y cuesta de encontrar.
    """
    clave = os.getenv("SIND_SECRET_KEY", "").strip()
    if not clave:
        raise RuntimeError(
            "Falta SIND_SECRET_KEY. Es la clave que firma la cookie de sesión: "
            "sin un valor fijo y compartido, los workers de IIS firman distinto "
            "y las sesiones se caen solas."
        )
    return clave


app = Flask(__name__)
app.secret_key = _secret_key()

# Railway termina el HTTPS en su proxy y le pasa la request a Flask por http:
# sin ProxyFix, url_for(_external) y los redirects salen como http y el host
# como el interno. Lo mismo que gestion_adm.py. En IIS no llega el encabezado
# X-Forwarded-* y ProxyFix no cambia nada.
from werkzeug.middleware.proxy_fix import ProxyFix              # noqa: E402
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# En Railway todo es HTTPS (aeda.seggestion.com.ar): la cookie de sesión no
# viaja por http. En IIS (http://servidor:5001) no se puede exigir, por eso
# depende de la variable que Railway define en todos sus servicios.
if os.getenv("RAILWAY_ENVIRONMENT"):
    app.config["SESSION_COOKIE_SECURE"] = True

# Nombre de cookie propio. Si esta aplicación y gestion_adm terminan bajo el
# mismo dominio, cookies con el mismo nombre se pisan entre sí y entrar a una
# desloguea de la otra.
app.config["SESSION_COOKIE_NAME"] = "sindicato_session"


# ── Filtros de plantilla ─────────────────────────────────────────────────────

# `puede(url)` en las plantillas: un enlace a otra pantalla se dibuja solo si
# el usuario la tiene en el menú (ui.expediente). Es la misma función que usan
# las guardias de las vistas.
app.jinja_env.globals["puede"] = puede

@app.template_filter("periodo")
def _periodo(valor):
    """
    AAAAMM → «2026-08»: el formato del período de ARCA en contable/gestion_adm
    (filtro `periodo` de gestion_adm.py). Se guarda con los seis dígitos que pide
    ARCA y se muestra así; además ordena bien como texto en las grillas.
    """
    d = "".join(c for c in str(valor or "") if c.isdigit())
    return f"{d[:4]}-{d[4:]}" if len(d) == 6 else (valor or "")


_SVG_SEQ = itertools.count(1)
_RE_SVG_ID = re.compile(r'\bid="([^"]+)"')


@app.template_filter("svg_unico")
def _svg_unico(svg):
    """
    El ícono de una opción del menú, con los `id` de sus degradados renombrados
    cada vez que se dibuja (el `svg_unico` de gestion_adm).

    Los íconos en colores (Fluent Color, sql/menu_iconos_color_20261111.sql)
    pintan con `url(#id)`, que apunta al PRIMER elemento de la página con ese
    id. El mismo ícono sale dos veces (el menú y el ABM del menú, o «Tablas» en
    dos módulos), y si el primero quedó en un submenú cerrado (display:none)
    Chrome no dibuja el degradado: el visible sale vacío. Un SVG de trazo, sin
    id, pasa igual que con `|safe`. Lo que llega acá ya lo validó el ABM del
    menú (sin script ni `on…=`).
    """
    if not svg:
        return Markup("")
    s = str(svg)
    ids = set(_RE_SVG_ID.findall(s))
    if ids:
        n = next(_SVG_SEQ)
        for i in ids:
            nuevo = f"{i}-u{n}"
            s = (s.replace(f'id="{i}"', f'id="{nuevo}"').replace(f"url(#{i})", f"url(#{nuevo})")
                  .replace(f'href="#{i}"', f'href="#{nuevo}"'))
    return Markup(s)


@app.template_filter("miles")
def _miles(valor):
    """
    Formatea un importe al estilo argentino: 1.234.567,89

    Se usa siempre como `{{ (valor or 0) | miles }}`. Los paréntesis importan:
    `valor or 0 | miles` aplica el filtro al 0 y no al valor, por precedencia.
    """
    try:
        numero = float(valor or 0)
    except (TypeError, ValueError):
        return valor
    entero, _, decimales = f"{numero:,.2f}".partition(".")
    return f"{entero.replace(',', '.')},{decimales}"


# ── Sesión ───────────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    email = (request.form.get("email") or "").strip().lower()
    clave = request.form.get("password") or ""

    if not email or not clave:
        flash("Ingresá tu correo y tu contraseña.")
        return render_template("login.html"), 401

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, nombre, password_hash, activo "
                "FROM s_usuarios WHERE email = %s LIMIT 1",
                (email,)
            )
            usuario = cur.fetchone()

    # Un solo mensaje para usuario inexistente, inactivo y contraseña
    # equivocada. Distinguirlos le confirma a cualquiera que pruebe direcciones
    # cuáles están dadas de alta.
    if (not usuario
            or not usuario["activo"]
            or not usuario["password_hash"]
            or not check_password_hash(usuario["password_hash"], clave)):
        flash("Correo o contraseña incorrectos.")
        return render_template("login.html"), 401

    roles, menu_ids = roles_y_menu(usuario["id"])

    session.clear()
    session["sind_validausuario"]  = True
    session["sind_usuario_id"]     = usuario["id"]
    session["sind_usuario_email"]  = usuario["email"]
    session["sind_usuario_nombre"] = usuario["nombre"]
    session["sind_roles"]          = roles
    # Solo los ids. El árbol lo arma `inject_menu` en cada request, contra la
    # base: si a alguien le cambian los permisos, el menú se acomoda al
    # siguiente request y no hay que hacerlo salir y entrar. Guardar el árbol
    # entero acá lo dejaría congelado en la cookie hasta el próximo login.
    session["sind_menu_ids"]       = menu_ids

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE s_usuarios SET ultimo_acceso = NOW() WHERE id = %s",
                (usuario["id"],)
            )

    return redirect(url_for("sindicato.fisca_dashboard"))


def _armar_arbol(items: list[dict]) -> list[dict]:
    """
    Convierte la lista plana de `s_menu` en el árbol que espera `base.html`.

    Un ítem cuyo padre no está en `items` se descarta en silencio, y eso es
    deliberado: pasa cuando alguien tiene permiso sobre una opción pero no
    sobre la rama que la contiene. Promoverla a raíz la mostraría al mismo
    nivel que los módulos, como si «Importar Cuotas» fuera una sección entera.
    El script sql/menu_y_roles_20260826.sql tiene una consulta al final que
    lista estos casos, para que se arreglen en los datos y no acá.
    """
    por_id  = {i["id"]: dict(i, hijos=[]) for i in items}
    raices  = []
    for item in por_id.values():
        if item["padre_id"] is None:
            raices.append(item)
        elif item["padre_id"] in por_id:
            por_id[item["padre_id"]]["hijos"].append(item)
    return raices


@app.context_processor
def inject_estaticos():
    """
    `v_css`: la fecha de modificación de la hoja de estilos, para el `?v=` del
    <link> de base.html. Sin eso el navegador sigue usando la versión que ya
    tenía y un cambio de estilos «no anda» hasta que alguien fuerza la recarga.
    """
    try:
        return {"v_css": int(os.path.getmtime(CSS))}
    except OSError:
        return {"v_css": 0}


CSS = Path(__file__).with_name("static") / "css" / "sindicato.css"


@app.context_processor
def inject_institucion():
    """
    `inst`: sigla, nombre y si hay logo, para el encabezado de base.html. Sale
    de «Datos del sindicato» (s_institucion), con un minuto de memoria. Si la
    tabla todavía no existe o la base no responde, el encabezado dice
    «Sindicato» como antes: no vale romper todas las pantallas por esto.
    """
    if not validasesion():
        return {"inst": {}}
    try:
        return {"inst": encabezado_institucion()}
    except Exception:
        app.logger.exception("No se pudieron leer los datos del sindicato")
        return {"inst": {}}


@app.context_processor
def inject_menu():
    """
    Pone `menu_tree` —y `menu_error` si algo falló— a disposición de todas las
    plantillas. `base.html` dibuja el menú lateral solo.
    """
    if not validasesion():
        return {"menu_tree": [], "menu_error": None}

    menu_ids = session.get("sind_menu_ids") or []
    if not menu_ids:
        return {"menu_tree": [], "menu_error": None}

    try:
        marcadores = ",".join(["%s"] * len(menu_ids))
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""SELECT id, padre_id, nombre, url, icono_svg, orden, nivel
                        FROM s_menu
                        WHERE id IN ({marcadores}) AND activo = 1
                        ORDER BY nivel, orden, nombre""",
                    menu_ids,
                )
                items = cur.fetchall()
        return {"menu_tree": _armar_arbol(items), "menu_error": None}

    except Exception as e:
        # Un menú vacío es ambiguo de la peor manera: se ve igual si la persona
        # no tiene permisos que si la base no respondió. Por eso el error viaja
        # a la plantilla en vez de tragarse.
        #
        # Va como variable de contexto y no como `flash`: flashear desde un
        # context processor es poco confiable, porque el mensaje se agrega
        # cuando la plantilla ya se está renderizando y termina apareciendo
        # —si aparece— en la página siguiente. El error del menú tiene que
        # verse en la pantalla donde el menú faltó.
        app.logger.exception("No se pudo cargar el menú")
        return {"menu_tree": [], "menu_error": f"{type(e).__name__}: {e}"}


@app.errorhandler(404)
def pantalla_no_encontrada(_e):
    """
    Distingue «esta pantalla todavía no está hecha» de «esta URL no existe».

    El menú carga la estructura completa prevista, así que hay opciones que
    apuntan a pantallas sin escribir. Sin esto todas darían el 404 de IIS, que
    no dice si falta el código o si el link está mal.
    """
    destino = request.path
    opcion = None
    if validasesion():
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT nombre FROM s_menu WHERE url = %s AND activo = 1 LIMIT 1",
                        (destino,)
                    )
                    opcion = cur.fetchone()
        except Exception:
            # Si la base no responde, se muestra el 404 común. El error de
            # conexión ya se va a ver en el menú, que corre en el mismo request.
            app.logger.exception("No se pudo consultar s_menu para el 404 de %s", destino)

    return render_template("404.html", destino=destino, opcion=opcion), 404


@app.route("/estilos")
def estilos():
    """
    Guía visual: cada componente de sindicato.css dibujado, con la línea para
    copiarlo. Es la referencia al armar una pantalla nueva y, a la vez, la
    prueba de que un cambio en la hoja de estilos no rompió nada.
    """
    if not validasesion():
        return redirect(url_for("login"))
    return render_template("estilos.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/menu")
def menu():
    """
    El botón de inicio de base.html apunta acá.

    En gestion_adm `menu` es una pantalla propia; acá la portada es el
    dashboard de fiscalización, así que redirige. Cuando el sindicato tenga
    varios módulos, este endpoint pasa a ser su menú de verdad y base.html no
    necesita cambiar.
    """
    if not validasesion():
        return redirect(url_for("login"))
    return redirect(url_for("sindicato.fisca_dashboard"))


# El blueprint queda montado en la raíz: este sitio es el del sindicato, así
# que un prefijo /sindicato repetiría en la URL lo que ya dice el dominio.
app.register_blueprint(sindicato_bp)
app.register_blueprint(empleadores_bp)
# `url_prefix` viene declarado en el propio blueprint (/contactos), así que acá
# no se repite.
app.register_blueprint(contactos_bp)
app.register_blueprint(afiliados_bp)
app.register_blueprint(afiliados_tablas_bp)
app.register_blueprint(metricas_bp)
app.register_blueprint(exportar_bp)
app.register_blueprint(reintegros_bp)
app.register_blueprint(institucion_bp)
app.register_blueprint(proveedores_bp)
app.register_blueprint(comprobantes_bp)
app.register_blueprint(mis_comp_bp)
app.register_blueprint(mesa_bp)
app.register_blueprint(tesoreria_bp)
app.register_blueprint(tes_mov_bp)
app.register_blueprint(tes_panel_bp)
app.register_blueprint(transferencias_bp)
app.register_blueprint(rg830_bp)
app.register_blueprint(contabilidad_bp)
app.register_blueprint(pagos_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(talonarios_bp)
app.register_blueprint(fisca_liq_bp)
app.register_blueprint(cc_prov_bp)


if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("SIND_PORT", "5001")))
