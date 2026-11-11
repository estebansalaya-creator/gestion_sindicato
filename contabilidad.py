"""
contabilidad.py — Módulo de contabilidad (menú 90). Por ahora, el plan de
cuentas (91); ejercicios, asientos, diario y mayor (92-95) vienen después.

Plan de cuentas
---------------
Portado de `gestion_adm/contable.py` (plan de cuentas: listado, árbol, alta,
edición, baja) con el sistema de estilos de este proyecto. El código manda
(las reglas están en plan_cuentas.py, que usan también los importadores):

- Se carga código y nombre. Clase, nivel, cuenta madre, si es imputable
  (último tramo distinto de cero) y si es corriente salen del código y la
  pantalla los muestra mientras se tipea. En gestion_adm la madre se elegía
  de una lista y podía no coincidir con el código.
- Después de cada alta, cambio de código o baja se rearma la jerarquía
  entera: crear una cuenta título que faltaba (AEDA no tiene 5-3-0-00-000)
  hace que las suyas pasen a colgar de ella.
- Monetaria y activa se eligen. Monetaria viene sugerida por el código.
- Una cuenta con cuentas debajo, o que se usa (conceptos, motivos, cuentas
  de fondos, rubros, imputaciones, asientos), no cambia de código ni se
  elimina; si la usa algo vigente, tampoco se desactiva. Dónde se usa cada
  una: plan_cuentas.USOS.
- Sin la importación desde Excel de gestion_adm: el plan viene de AEDA
  (importar_aeda_plan_cuentas.py) y se completa acá.

El permiso es la opción de menú, también en los POST y en la consulta del
código (db.puede).
"""

from __future__ import annotations

import re
from collections import Counter

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

import plan_cuentas as pc
from db import get_connection, puede, validasesion

contabilidad_bp = Blueprint("contabilidad", __name__, url_prefix="/contabilidad")

#: Lo que no impide cambiar el código: un balance ya generado es una foto.
USOS_FOTO = {"balances generados"}


def _guardia(endpoint, api=False):
    """Redirección (o 403 en la consulta del código) si no hay sesión o no
    tiene la opción de menú; None si pasa."""
    if not validasesion():
        return (jsonify(error="La sesión venció: volvé a entrar."), 401) if api else redirect(url_for("login"))
    if not puede(url_for(endpoint)):
        if api:
            return jsonify(error="No tenés permiso para el plan de cuentas."), 403
        flash("!No tenés permiso para esa pantalla.")
        return redirect(url_for("menu"))
    return None


def _texto(nombre, largo):
    return re.sub(r"\s+", " ", (request.form.get(nombre) or "").strip())[:largo]


def _id(nombre):
    v = (request.form.get(nombre) or "").strip()
    return int(v) if v.isdigit() else None


def _leer_plan(cur) -> list[dict]:
    cur.execute("""SELECT p.id_cuenta, p.codigo, p.nombre, p.id_cuenta_padre, p.nivel, p.permite_movimiento,
                          p.activa, p.es_monetario, p.corriente, p.id_clasificacion, cl.clasificacion
                     FROM c_plan_de_cuentas p
                     LEFT JOIN c_clasificacion_plan_cuentas cl ON cl.codigo = p.id_clasificacion
                    ORDER BY p.codigo""")
    return cur.fetchall()


def _clases(cur) -> dict:
    cur.execute("SELECT codigo, clasificacion FROM c_clasificacion_plan_cuentas ORDER BY codigo")
    return {f["codigo"]: f["clasificacion"] for f in cur.fetchall()}


def analizar(texto, filas, clases, id_cuenta=None) -> dict:
    """Lo que dice un código: normalizado, error, clase, nivel, tipo, madre,
    las madres que faltan y cuántas cuentas pasarían a colgar de él. `filas`
    es el plan entero; la cuenta `id_cuenta` (la que se edita) no cuenta."""
    otras = {f["codigo"]: f for f in filas if f["id_cuenta"] != id_cuenta}
    masc = pc.mascara(list(otras) or [f["codigo"] for f in filas])
    codigo = pc.normalizar_codigo(texto, masc)
    r = {"codigo": codigo, "mascara": masc, "error": pc.error_codigo(codigo, masc)}
    if r["error"]:
        return r
    clase = int(pc.tramos(codigo)[0])
    if clase not in clases:
        r["error"] = (f"La clase {clase} no existe: el primer tramo es "
                      + ", ".join(f"{k} {v.lower()}" for k, v in clases.items()) + ".")
        return r
    if codigo in otras:
        r["error"] = f"El código {codigo} ya es de «{otras[codigo]['nombre']}»."
        return r
    m = pc.madre(codigo, otras)
    todos = set(otras) | {codigo}
    imputable = pc.imputable(codigo)
    r.update(clase=clase, clase_texto=f"{clase} · {clases[clase]}", nivel=pc.nivel(codigo), imputable=imputable,
             tipo="Imputable" if imputable else "Título", corriente=pc.corriente(codigo),
             monetaria=pc.monetaria(codigo), madre=f"{m}  {otras[m]['nombre']}" if m else "",
             faltan=pc.faltantes(codigo, otras),
             hijas=0 if imputable else sum(1 for c in otras if pc.madre(c, todos) == codigo))
    r["corriente_texto"] = ("Corriente" if r["corriente"] else "No corriente") if clase in (1, 2) else "—"
    return r


def siguiente_codigo(madre: str, codigos) -> str:
    """El código que sigue debajo de una cuenta título: el siguiente de sus
    hijas en el tramo que usan (con el mismo paso: 010, 020 → 030), o el
    primero del tramo siguiente si no tiene. Vacío si no entra."""
    codigos = set(codigos)
    sep = pc.separador(re.sub(r"\d", "9", madre))
    t = pc.tramos(madre)
    hijas = [c for c in codigos if pc.madre(c, codigos) == madre]
    if hijas:
        pos = Counter(pc.nivel(c) for c in hijas).most_common(1)[0][0] - 1
        valores = sorted(int(pc.tramos(c)[pos]) for c in hijas if pc.nivel(c) == pos + 1)
        paso = valores[-1] - valores[-2] if len(valores) > 1 and valores[-1] > valores[-2] else 1
        prox = valores[-1] + paso
    else:
        pos = pc.nivel(madre)
        if pos >= len(t):
            return ""
        prox = 10 if len(t[pos]) >= 3 else 1
    ancho = len(t[pos])
    while prox < 10 ** ancho:
        nuevo = sep.join(str(prox).zfill(ancho) if i == pos else x for i, x in enumerate(t))
        if nuevo not in codigos:
            return nuevo
        prox += 1
    return ""


def _usos_que_traban(u: dict) -> dict:
    return {k: n for k, n in u.items() if k not in USOS_FOTO}


def _guardar(cur, cid, filas, clases, errores) -> dict:
    """Valida y graba el formulario. Devuelve la cuenta como quedó (o como se
    cargó, si hubo errores)."""
    actual = next((f for f in filas if f["id_cuenta"] == cid), None) if cid else None
    a = analizar(request.form.get("codigo"), filas, clases, cid)
    cuenta = {"id_cuenta": cid, "codigo": a["codigo"], "nombre": _texto("nombre", 150).upper(),
              "es_monetario": 1 if request.form.get("es_monetario") else 0,
              "activa": 1 if request.form.get("activa") else 0}
    if cid and not actual:
        errores.append("La cuenta ya no existe.")
        return cuenta
    if a["error"]:
        errores.append(a["error"])
    if not cuenta["nombre"]:
        errores.append("El nombre es obligatorio.")
    elif not a["error"] and (not actual or cuenta["nombre"] != actual["nombre"] or a["codigo"] != actual["codigo"]):
        # Dos hermanas con el mismo nombre no se distinguen al elegir la cuenta.
        # En lugares distintos sí puede repetirse (CAJA título y CAJA imputable).
        codigos = {f["codigo"] for f in filas if f["id_cuenta"] != cid} | {a["codigo"]}
        m = pc.madre(a["codigo"], codigos)
        gemela = next((f for f in filas if f["id_cuenta"] != cid and f["nombre"] == cuenta["nombre"]
                       and pc.madre(f["codigo"], codigos) == m), None)
        if gemela:
            errores.append(f"Ya hay una cuenta «{cuenta['nombre']}» al mismo nivel: {gemela['codigo']}.")
    u = pc.usos(cur).get(cid, {}) if cid else {}
    hijas = sum(1 for f in filas if f["id_cuenta_padre"] == cid) if cid else 0
    if actual and a["codigo"] != actual["codigo"]:
        if hijas:
            errores.append(f"Tiene {hijas} cuentas debajo: el código no se puede cambiar.")
        elif _usos_que_traban(u):
            errores.append(f"Se usa en {pc.describir_usos(_usos_que_traban(u))}: el código no se puede cambiar. "
                           "Si va en otro lugar del plan, creá la cuenta nueva y pasá las imputaciones.")
    if actual and actual["activa"] and not cuenta["activa"]:
        vivos = {k: n for k, n in u.items() if k in pc.USOS_VIVOS}
        activas = sum(1 for f in filas if f["id_cuenta_padre"] == cid and f["activa"])
        if vivos:
            errores.append(f"Se usa en {pc.describir_usos(vivos)}: no se puede desactivar mientras se use.")
        if activas:
            errores.append(f"Tiene {activas} cuentas activas debajo: desactivalas primero.")
    if errores:
        return cuenta

    valores = {"codigo": a["codigo"], "nombre": cuenta["nombre"], "id_clasificacion": a["clase"],
               "nivel": a["nivel"], "permite_movimiento": 1 if a["imputable"] else 0, "corriente": a["corriente"],
               "es_monetario": cuenta["es_monetario"], "activa": cuenta["activa"]}
    cols = list(valores)
    if cid:
        cur.execute(f"UPDATE c_plan_de_cuentas SET {', '.join(c + ' = %s' for c in cols)} WHERE id_cuenta = %s",
                    [valores[c] for c in cols] + [cid])
    else:
        cur.execute(f"INSERT INTO c_plan_de_cuentas ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                    [valores[c] for c in cols])
        cid = cur.lastrowid
    pc.rearmar_jerarquia(cur)
    cuenta.update(valores, id_cuenta=cid, _hijas=a.get("hijas", 0))
    return cuenta


@contabilidad_bp.route("/plan", methods=["GET", "POST"])
def plan():
    salida = _guardia("contabilidad.plan")
    if salida:
        return salida
    errores, cuenta = [], None

    if request.method == "POST":
        accion, cid = request.form.get("accion", ""), _id("id")
        with get_connection() as conn:
            conn.begin()
            try:
                with conn.cursor() as cur:
                    filas = _leer_plan(cur)
                    if accion in ("borrar", "baja", "reactivar"):
                        f = next((x for x in filas if x["id_cuenta"] == cid), None)
                        if not f:
                            flash("!La cuenta ya no existe.")
                        else:
                            _accion(cur, accion, f, filas)
                        conn.commit()
                        return redirect(url_for("contabilidad.plan"))
                    cuenta = _guardar(cur, cid, filas, _clases(cur), errores)
                    if not errores:
                        conn.commit()
                        texto = f"{cuenta['codigo']} {cuenta['nombre']}"
                        if not cid and cuenta.get("_hijas"):
                            flash(f"Cuenta {texto} agregada; {cuenta['_hijas']} cuentas pasaron a colgar de ella.")
                        else:
                            flash(f"Cuenta {texto} " + ("actualizada." if cid else "agregada."))
                        return redirect(url_for("contabilidad.plan", _anchor=f"c{cuenta['id_cuenta']}"))
                    conn.rollback()
            except Exception:
                conn.rollback()
                raise

    with get_connection() as conn:
        with conn.cursor() as cur:
            filas = _leer_plan(cur)
            clases = _clases(cur)
            usos = pc.usos(cur)
    por_id = {f["id_cuenta"]: f for f in filas}
    codigos = [f["codigo"] for f in filas]
    hijas = Counter(f["id_cuenta_padre"] for f in filas if f["id_cuenta_padre"])
    for f in filas:
        f["usos"] = usos.get(f["id_cuenta"], {})
        f["n_usos"] = sum(f["usos"].values())
        f["usos_texto"] = pc.describir_usos(f["usos"])
        f["hijas"] = hijas.get(f["id_cuenta"], 0)
        f["profundidad"] = _profundidad(f, por_id)
        f["traba_codigo"] = bool(f["hijas"] or _usos_que_traban(f["usos"]))
    hijas_activas = Counter(f["id_cuenta_padre"] for f in filas if f["id_cuenta_padre"] and f["activa"])
    for f in filas:
        vivos = {k: n for k, n in f["usos"].items() if k in pc.USOS_VIVOS}
        activas = hijas_activas.get(f["id_cuenta"], 0)
        f["traba_baja"] = (f"se usa en {pc.describir_usos(vivos)}" if vivos
                           else f"tiene {activas} cuentas activas debajo" if activas else "")

    edit_id = request.args.get("edit", type=int)
    madre_id = request.args.get("madre", type=int)
    madre = None
    if cuenta is None and edit_id:
        cuenta = por_id.get(edit_id)
        if not cuenta:
            flash("!La cuenta no existe.")
            return redirect(url_for("contabilidad.plan"))
    elif cuenta is None and madre_id and por_id.get(madre_id) and not por_id[madre_id]["permite_movimiento"]:
        madre = por_id[madre_id]
        cod = siguiente_codigo(madre["codigo"], codigos)
        cuenta = {"codigo": cod, "nombre": "", "activa": 1, "es_monetario": pc.monetaria(cod) if cod else 0}
    elif cuenta is not None and cuenta.get("id_cuenta"):
        cuenta = {**por_id.get(cuenta["id_cuenta"], {}), **cuenta}
    nuevo = bool(request.args.get("nuevo"))
    if cuenta is None and nuevo:
        cuenta = {"codigo": "", "nombre": "", "activa": 1, "es_monetario": 0}
    info = analizar(cuenta["codigo"], filas, clases, cuenta.get("id_cuenta")) if cuenta and cuenta.get("codigo") else {}

    return render_template("contabilidad/plan.html", filas=filas, cuenta=cuenta, errores=errores, clases=clases,
                           info=info, madre=madre, mascara=pc.mascara(codigos),
                           abrir_ficha=bool(cuenta or errores or nuevo))


def _profundidad(f, por_id) -> int:
    n, actual, vistos = 0, f, set()
    while actual.get("id_cuenta_padre") and actual["id_cuenta_padre"] in por_id and actual["id_cuenta"] not in vistos:
        vistos.add(actual["id_cuenta"])
        actual = por_id[actual["id_cuenta_padre"]]
        n += 1
    return n


def _accion(cur, accion, f, filas):
    texto = f"{f['codigo']} {f['nombre']}"
    u = pc.usos(cur).get(f["id_cuenta"], {})
    hijas = [x for x in filas if x["id_cuenta_padre"] == f["id_cuenta"]]
    if accion == "borrar":
        if hijas:
            flash(f"!{texto} tiene {len(hijas)} cuentas debajo: no se puede eliminar.")
        elif u:
            flash(f"!{texto} se usa en {pc.describir_usos(u)}: no se puede eliminar. "
                  "Desactivala para que no se ofrezca más.")
        else:
            cur.execute("DELETE FROM c_plan_de_cuentas WHERE id_cuenta = %s", (f["id_cuenta"],))
            pc.rearmar_jerarquia(cur)
            flash(f"Cuenta {texto} eliminada.")
        return
    if accion == "baja":
        vivos = {k: n for k, n in u.items() if k in pc.USOS_VIVOS}
        activas = [x for x in hijas if x["activa"]]
        if vivos:
            flash(f"!{texto} se usa en {pc.describir_usos(vivos)}: no se puede desactivar mientras se use.")
        elif activas:
            flash(f"!{texto} tiene {len(activas)} cuentas activas debajo: desactivalas primero.")
        else:
            cur.execute("UPDATE c_plan_de_cuentas SET activa = 0 WHERE id_cuenta = %s", (f["id_cuenta"],))
            flash(f"Cuenta {texto} desactivada: ya no se ofrece para imputar.")
        return
    cur.execute("UPDATE c_plan_de_cuentas SET activa = 1 WHERE id_cuenta = %s", (f["id_cuenta"],))
    madre = next((x for x in filas if x["id_cuenta"] == f["id_cuenta_padre"]), None)
    if madre and not madre["activa"]:
        flash(f"!Cuenta {texto} reactivada, pero su madre {madre['codigo']} {madre['nombre']} sigue inactiva.")
    else:
        flash(f"Cuenta {texto} reactivada.")


@contabilidad_bp.route("/plan/codigo")
def plan_codigo():
    """Lo que dice un código mientras se tipea (la ficha lo muestra debajo)."""
    salida = _guardia("contabilidad.plan", api=True)
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            filas = _leer_plan(cur)
            clases = _clases(cur)
    return jsonify(analizar(request.args.get("codigo", ""), filas, clases, request.args.get("id", type=int)))
