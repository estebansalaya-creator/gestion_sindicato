"""
contabilidad_ejercicios.py — Contabilidad › Ejercicios (menú 92).

    /contabilidad/ejercicios           listado; ?ver=ID la ficha con sus períodos; ?nuevo=1 el alta
    /contabilidad/ejercicios           POST accion=nuevo|guardar|activar|cerrar|reabrir|borrar
                                       |periodo (id_periodo, estado = abierto|cerrado|bloqueado)

Portado de gestion_adm/contable.py (ejercicios, periodos, seleccionar_ejercicio)
en una sola pantalla (pedido del 18/11/2026, junto con el Libro Diario):

- Abrir un ejercicio crea sus períodos, uno por mes (asientos.abrir_ejercicio;
  en gestion_adm lo hacía sp_abrir_ejercicio). CUIT y razón social son los de
  Datos del Sindicato. Los ejercicios no se superponen.
- El ejercicio de trabajo («Activar») es el que muestran el Diario y la carga
  por defecto; el primero que se abre queda activo.
- Cerrar un ejercicio cierra sus períodos abiertos y pide que no queden
  borradores. No genera el asiento de cierre (sp_cerrar_ejercicio): pendiente.
- Los períodos se cierran, bloquean y reabren de a uno desde la ficha. Cerrado
  no admite asientos; Tesorería tampoco anula comprobantes de esas fechas.
- Eliminar: solo sin asientos.
"""

from __future__ import annotations

import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

import asientos as A
import institucion
from db import get_connection, puede, usuario_actual, validasesion

cont_ej_bp = Blueprint("cont_ej", __name__, url_prefix="/contabilidad")

URL = "/contabilidad/ejercicios"


def _guardia():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede(URL):
        flash("!No tenés permiso para esa pantalla.")
        return redirect(url_for("menu"))
    return None


def _usuario() -> str:
    u = usuario_actual() or {}
    return (u.get("email") or u.get("nombre") or "")[:80]


def _fecha(nombre):
    try:
        return datetime.date.fromisoformat((request.form.get(nombre) or "").strip())
    except ValueError:
        return None


def propuesta(hoy: datetime.date, existentes: list[dict]) -> dict:
    """Lo que el alta trae cargado: el año siguiente al último ejercicio (o el
    año en curso si no hay ninguno), del 1/1 al 31/12."""
    if existentes:
        ultimo = max(e["fecha_fin"] for e in existentes)
        desde = ultimo + datetime.timedelta(days=1)
    else:
        desde = datetime.date(hoy.year, 1, 1)
    try:
        hasta = desde.replace(year=desde.year + 1) - datetime.timedelta(days=1)
    except ValueError:                                   # 29/02
        hasta = desde.replace(year=desde.year + 1, day=28)
    nombre = f"Ejercicio {desde.year}" if (desde.month, desde.day) == (1, 1) else f"Ejercicio {desde.year}/{hasta.year}"
    return {"nombre": nombre, "fecha_inicio": desde, "fecha_fin": hasta}


@cont_ej_bp.route("/ejercicios", methods=["GET", "POST"])
def ejercicios():
    salida = _guardia()
    if salida:
        return salida
    if request.method == "POST":
        return _post()
    ver = request.args.get("ver", type=int)
    with get_connection() as conn:
        with conn.cursor() as cur:
            lista = A.ejercicios(cur)
            ficha = next((e for e in lista if e["id_ejercicio"] == ver), None) if ver else None
            pers = A.periodos(cur, ver) if ficha else []
    inst = institucion.obtener()
    return render_template("contabilidad/ejercicios.html", ejercicios=lista, ficha=ficha, periodos=pers,
                           nuevo=request.args.get("nuevo") == "1" or not lista,
                           propuesta=propuesta(datetime.date.today(), lista),
                           inst=inst, estados=A.ESTADOS_PERIODO, puede_diario=puede("/contabilidad/diario"))


def _post():
    accion = request.form.get("accion", "")
    id_ej = request.form.get("id", type=int)
    volver = url_for("cont_ej.ejercicios", ver=id_ej) if id_ej else url_for("cont_ej.ejercicios")
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            if accion == "nuevo":
                inst = institucion.obtener()
                desde, hasta = _fecha("fecha_inicio"), _fecha("fecha_fin")
                nombre = " ".join((request.form.get("nombre") or "").split())[:100]
                obs = (request.form.get("observaciones") or "").strip() or None
                id_ej = A.abrir_ejercicio(cur, nombre, desde, hasta, inst.get("cuit"), inst.get("nombre"),
                                          _usuario(), obs, activar=bool(request.form.get("activar")))
                n = len(A.meses(desde, hasta))
                msg = f"Ejercicio «{nombre}» abierto con {n} períodos."
                volver = url_for("cont_ej.ejercicios", ver=id_ej)
            elif accion == "guardar" and id_ej:
                A.modificar_ejercicio(cur, id_ej, " ".join((request.form.get("nombre") or "").split())[:100],
                                      (request.form.get("observaciones") or "").strip() or None)
                msg = "Ejercicio actualizado."
            elif accion == "activar" and id_ej:
                A.activar_ejercicio(cur, id_ej)
                msg = "Es el ejercicio de trabajo: el Diario y la carga de asientos lo muestran por defecto."
            elif accion == "cerrar" and id_ej:
                n = A.cerrar_ejercicio(cur, id_ej, _usuario())
                msg = f"Ejercicio cerrado ({n} período(s) que estaban abiertos)."
            elif accion == "reabrir" and id_ej:
                A.reabrir_ejercicio(cur, id_ej)
                msg = "Ejercicio reabierto. Los períodos siguen cerrados: se abren de a uno."
            elif accion == "borrar" and id_ej:
                A.borrar_ejercicio(cur, id_ej)
                msg = "Ejercicio eliminado."
                volver = url_for("cont_ej.ejercicios")
            elif accion == "periodo":
                estado = request.form.get("estado", "")
                p = A.cambiar_periodo(cur, request.form.get("id_periodo", type=int), estado)
                msg = f"{p['nombre']}: {A.ESTADOS_PERIODO[estado][0].lower()}."
                volver = url_for("cont_ej.ejercicios", ver=p["id_ejercicio"])
            else:
                raise A.ErrorContable("Acción desconocida.")
        conn.commit()
        flash(msg)
    except A.ErrorContable as e:
        conn.rollback()
        flash(f"!{e}")
        if accion == "nuevo":
            return redirect(url_for("cont_ej.ejercicios", nuevo=1))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return redirect(volver)
