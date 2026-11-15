"""
Pruebas de la ayuda (sin base): que los manuales estén bien armados, que cada
sección apunte a pantallas que existen y que toda pantalla tenga su ayuda (o
esté en ayuda.SIN_AYUDA).  python tests/test_ayuda.py

Levanta la aplicación (app.py) para leer sus rutas: necesita el .env (no se
conecta a la base).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ayuda  # noqa: E402
from app import app  # noqa: E402
from werkzeug.exceptions import HTTPException  # noqa: E402

ok = fallos = 0


def v(cond, msg, detalle=None):
    global ok, fallos
    ok, fallos = (ok + 1, fallos) if cond else (ok, fallos + 1)
    print(("  OK   " if cond else "  FALLA ") + msg)
    if not cond and detalle:
        for d in detalle:
            print("         · " + str(d))


import logging
app.logger.setLevel(logging.CRITICAL)   # el encabezado intenta leer la base: sin ella, avisa y sigue

reglas = [(r.rule, r.endpoint, set(r.methods or ())) for r in app.url_map.iter_rules()]
adaptador = app.url_map.bind("localhost")


def url_valida(url):
    try:
        adaptador.match(url, method="GET")
        return True
    except HTTPException:
        return False


print("\nManuales")
mans = ayuda.manuales()
v(len(mans) == len(ayuda.MANUALES), f"se cargan los {len(ayuda.MANUALES)} manuales")
problemas = ayuda.verificar(reglas, url_valida)
v(not problemas, "secciones completas, ids únicos, endpoints y direcciones que existen", problemas)
total = sum(len(m["secciones"]) for m in mans)
print(f"         ({total} secciones)")

print("\nCobertura")
faltan = ayuda.sin_manual(reglas)
v(not faltan, "toda pantalla tiene ayuda o está en SIN_AYUDA", faltan)
v(ayuda.de_endpoint("fisca_acta.acta_nueva") == ("fiscalizacion", "fis_actas"), "el acta nueva abre la sección de actas")
v(ayuda.de_endpoint("afiliados.abm_afiliados")[0] == "padron", "el ABM de afiliados abre el manual del padrón")
v(ayuda.de_endpoint("no.existe") is None, "una pantalla sin ayuda: None (el botón va al índice)")
v(ayuda.sin_ayuda("pagos.api_retenciones") and ayuda.sin_ayuda("fisca_acta.acta_pdf"), "lo que es JSON o PDF no lleva ayuda")

print("\nPantallas")
with app.test_request_context("/"):
    from flask import render_template, session
    session["sind_validausuario"] = True
    session["sind_menu_ids"] = []
    for m in mans:
        try:
            html = render_template("ayuda/manual.html", man=m, seccion=m["secciones"][0]["id"],
                                   otros=[x for x in mans if x is not m], permitidas=set())
            bien = all(f'id="{s["id"]}"' in html for s in m["secciones"])
        except Exception as e:  # noqa: BLE001
            bien, html = False, str(e)
        v(bien, f"se dibuja el manual {m['clave']}", None if bien else [html[:300]])
    html = render_template("ayuda/indice.html", manuales=mans)
    v(html.count('class="card manual-tarjeta"') == len(mans), "el índice tiene una tarjeta por manual")

print(f"\n{ok} bien, {fallos} mal")
sys.exit(1 if fallos else 0)
