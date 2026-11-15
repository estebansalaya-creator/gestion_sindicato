"""
ayuda_pantallas.py — Las pantallas de la ayuda: el índice de los manuales
(/ayuda) y cada manual (/ayuda/<clave>, ?s=<sección> la resalta). El contenido
y el registro están en ayuda.py y en los ayuda_<módulo>.py.

Los ve cualquiera que haya iniciado sesión: un manual explica también las
pantallas que esa persona no tiene, para que sepa a quién pedírselas. «Ir a la
pantalla» sale solo si la tiene (`db.puede`).
"""

from flask import Blueprint, abort, redirect, render_template, request, url_for

import ayuda
from db import puede, validasesion

ayuda_bp = Blueprint("ayuda", __name__)


def url_ayuda(endpoint: str | None) -> str:
    """El enlace del botón Ayuda (abajo a la derecha) para la pantalla actual."""
    par = ayuda.de_endpoint(endpoint)
    if not par:
        return url_for("ayuda.indice")
    clave, seccion = par
    return url_for("ayuda.manual", clave=clave, s=seccion) + "#" + seccion


@ayuda_bp.app_context_processor
def _inyectar():
    return {"url_ayuda": url_ayuda}


def _permitidas(secciones) -> set[str]:
    return {s["url"] for s in secciones if s.get("url") and puede(s["url"])}


@ayuda_bp.route("/ayuda")
def indice():
    if not validasesion():
        return redirect(url_for("login"))
    mans = ayuda.manuales()
    return render_template("ayuda/indice.html", manuales=mans)


@ayuda_bp.route("/ayuda/<clave>")
def manual(clave):
    if not validasesion():
        return redirect(url_for("login"))
    man = ayuda.manual(clave)
    if not man:
        abort(404)
    seccion = (request.args.get("s") or "").strip()
    if seccion not in {s["id"] for s in man["secciones"]}:
        seccion = ""
    return render_template("ayuda/manual.html", man=man, seccion=seccion,
                           otros=[m for m in ayuda.manuales() if m["clave"] != clave],
                           permitidas=_permitidas(man["secciones"]))
