"""
tesoreria_rg830.py — Escala RG 830 (/tesoreria/rg830, menú 75).

Los regímenes de retención de Ganancias: por cada código (094 locaciones de
servicios, 078 bienes de cambio, 119 profesiones liberales…) la forma de
cálculo —alícuota fija o escala progresiva por tramos—, el mínimo no sujeto,
las alícuotas y la vigencia. Lo leen la ficha del proveedor (`rg830.vigentes`)
y el cálculo de la retención al pagar (`retenciones.regimen_ganancias`): la
fila activa más nueva cuya vigencia cubre la fecha.

Portado de `gestion_adm/tesoreria_routes.py` (rg830_escala), que solo daba de
alta, cerraba vigencias y activaba/desactivaba: no se podía corregir nada sin
crear otra fila. Acá:

- **Una escala ya usada no cambia sus valores.** Usada = hay retenciones de
  Ganancias vigentes de su código dentro de su vigencia. Lo retenido no se
  recalcula (cada retención guarda su base y su alícuota), pero las órdenes
  sin pagar sí, y dos pagos del mismo mes dirían cosas distintas. Para
  cambiar valores: «Nueva vigencia», que copia la escala y cierra la anterior
  el día antes. Lo que sí se edita siempre: descripción, resolución y
  observaciones.
- **Una sin usar se corrige o se elimina.**
- **Las vigencias de un código no se pisan**: al dar de alta una que arranca
  después de otra abierta, la anterior se cierra sola el día antes; una que
  arrancaría antes de otra existente no se acepta.
- **Tramos coherentes**: el primero desde 0, cada uno arranca donde termina
  el anterior, solo el último sin tope (si no, una base por encima del último
  tope retendría cero). El importe fijo de cada tramo se compara con lo que
  acumulan los anteriores y avisa si no da (no bloquea: lo publica ARCA).
- **No se deja sin régimen a un proveedor**: no se desactiva ni se elimina la
  única escala vigente de un código que tienen asignado proveedores.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from db import get_connection, puede, validasesion
from pagos_datos import leer_importe
from rg830 import normalizar_regimen

rg830_bp = Blueprint("rg830", __name__, url_prefix="/tesoreria")

CAMPOS_VALOR = ("tipo_calculo", "alicuota_fija", "monto_no_sujeto_inscripto", "monto_no_sujeto_no_inscripto",
                "alicuota_no_inscripto", "retencion_minima_inscripto", "retencion_minima_no_inscripto")
CODIGO = "LPAD(TRIM({}), 3, '0')"


def _guardia():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede(url_for("rg830.escalas")):
        flash("!No tenés permiso para la escala RG 830.")
        return redirect(url_for("menu"))
    return None


def _fecha(v):
    try:
        return datetime.date.fromisoformat((v or "").strip())
    except ValueError:
        return None


def _num(v):
    """Importe o porcentaje como lo escribe la gente; None si vacío o inválido."""
    n = leer_importe(v)
    return None if n is None else Decimal(str(n))


def _escalas(cur, id_escala=None) -> list[dict]:
    """Las escalas con lo que hace falta para decidir qué se puede hacer con cada una."""
    cur.execute(f"""
        SELECT e.*,
               (SELECT COUNT(*) FROM rg830_escala_tramos t WHERE t.id_escala = e.id) AS tramos,
               (SELECT COUNT(*) FROM c_proveedores p
                 WHERE p.ret_ganancias = 1 AND {CODIGO.format('p.ret_ganancias_codigo_sir')} = {CODIGO.format('e.codigo_regimen')}) AS proveedores,
               (SELECT COUNT(*) FROM pago_retenciones r
                 WHERE r.tipo = 'GANANCIAS' AND COALESCE(r.anulado, 0) = 0
                   AND {CODIGO.format('r.regimen')} = {CODIGO.format('e.codigo_regimen')}
                   AND r.fecha >= e.vigencia_desde AND (e.vigencia_hasta IS NULL OR r.fecha <= e.vigencia_hasta)) AS retenciones,
               (SELECT MAX(r.fecha) FROM pago_retenciones r
                 WHERE r.tipo = 'GANANCIAS' AND COALESCE(r.anulado, 0) = 0
                   AND {CODIGO.format('r.regimen')} = {CODIGO.format('e.codigo_regimen')}
                   AND r.fecha >= e.vigencia_desde AND (e.vigencia_hasta IS NULL OR r.fecha <= e.vigencia_hasta)) AS ultima_retencion
          FROM rg830_escala e
         {'WHERE e.id = %s' if id_escala else ''}
         ORDER BY CAST(e.codigo_regimen AS UNSIGNED), e.vigencia_desde DESC""", (id_escala,) if id_escala else ())
    hoy = datetime.date.today()
    filas = cur.fetchall()
    for e in filas:
        e["codigo"] = normalizar_regimen(e["codigo_regimen"])
        e["estado"] = ("inactiva" if not e["activa"] else "futura" if e["vigencia_desde"] > hoy
                       else "vencida" if e["vigencia_hasta"] and e["vigencia_hasta"] < hoy else "vigente")
        e["usada"] = e["retenciones"] > 0
    return filas


def _unica_vigente_con_proveedores(cur, e) -> bool:
    """¿Es la única escala activa y vigente hoy de un código que tienen proveedores?"""
    if not e["proveedores"] or e["estado"] != "vigente":
        return False
    hoy = datetime.date.today()
    cur.execute(f"""SELECT COUNT(*) AS n FROM rg830_escala
                     WHERE id <> %s AND activa = 1 AND {CODIGO.format('codigo_regimen')} = %s
                       AND vigencia_desde <= %s AND (vigencia_hasta IS NULL OR vigencia_hasta >= %s)""",
                (e["id"], e["codigo"], hoy, hoy))
    return cur.fetchone()["n"] == 0


def _tramos_del_form(form) -> tuple[list[dict], list[str]]:
    tramos, errores = [], []
    filas = zip(form.getlist("t_desde"), form.getlist("t_hasta"), form.getlist("t_fijo"),
                form.getlist("t_alicuota"), form.getlist("t_exc"))
    for i, (d, h, fj, al, ex) in enumerate(filas, 1):
        if not any(x.strip() for x in (d, h, fj, al, ex)):
            continue
        t = {"tramo_desde": _num(d), "tramo_hasta": _num(h), "importe_fijo": _num(fj) or Decimal(0),
             "alicuota": _num(al), "excedente_sobre": _num(ex), "txt": {"d": d, "h": h, "fj": fj, "al": al, "ex": ex}}
        if t["tramo_desde"] is None:
            errores.append(f"Tramo {i}: falta el «desde».")
        if h.strip() and t["tramo_hasta"] is None:
            errores.append(f"Tramo {i}: el «hasta» no es un importe.")
        if t["alicuota"] is None or not 0 < t["alicuota"] <= 100:
            errores.append(f"Tramo {i}: la alícuota va de 0 a 100.")
        if t["importe_fijo"] < 0:
            errores.append(f"Tramo {i}: el importe fijo no puede ser negativo.")
        if t["excedente_sobre"] is None:
            t["excedente_sobre"] = t["tramo_desde"]
        tramos.append(t)
    return tramos, errores


def _validar_tramos(tramos) -> tuple[list[str], list[str]]:
    """Errores (no se guarda) y avisos (se guarda igual)."""
    errores, avisos = [], []
    if not tramos:
        return ["Una escala progresiva lleva al menos un tramo."], []
    if tramos[0]["tramo_desde"] != 0:
        errores.append("El primer tramo arranca en 0.")
    for i, t in enumerate(tramos, 1):
        ultimo = i == len(tramos)
        if t["tramo_hasta"] is None and not ultimo:
            errores.append(f"Tramo {i}: solo el último va sin tope.")
        if t["tramo_hasta"] is not None and ultimo:
            errores.append("El último tramo va sin tope («hasta» vacío): una base mayor no retendría nada.")
        if t["tramo_hasta"] is not None and t["tramo_desde"] is not None and t["tramo_hasta"] <= t["tramo_desde"]:
            errores.append(f"Tramo {i}: el «hasta» tiene que ser mayor que el «desde».")
        if i > 1:
            ant = tramos[i - 2]
            if ant["tramo_hasta"] is not None and t["tramo_desde"] != ant["tramo_hasta"]:
                errores.append(f"Tramo {i}: arranca en {t['tramo_desde']} y el anterior termina en {ant['tramo_hasta']}: "
                               "tienen que coincidir.")
            if not errores and ant["tramo_hasta"] is not None:
                esperado = (ant["importe_fijo"] + (ant["tramo_hasta"] - ant["excedente_sobre"]) * ant["alicuota"] / 100
                            ).quantize(Decimal("0.01"))
                if abs(esperado - t["importe_fijo"]) > Decimal("1"):
                    avisos.append(f"Tramo {i}: el importe fijo es {t['importe_fijo']} y lo que acumulan los anteriores "
                                  f"da {esperado}. Revisalo contra la tabla de ARCA.")
    return errores, avisos


def _leer(form, actual) -> tuple[dict, list[dict], list[str], list[str]]:
    errores, avisos = [], []
    e = {"id": actual["id"] if actual else None,
         "codigo_txt": (form.get("codigo_regimen") or "").strip(),
         "descripcion": " ".join((form.get("descripcion") or "").split())[:200],
         "tipo_calculo": form.get("tipo_calculo") if form.get("tipo_calculo") in ("escala", "fija") else "",
         "alicuota_fija": _num(form.get("alicuota_fija")),
         "monto_no_sujeto_inscripto": _num(form.get("monto_no_sujeto_inscripto")),
         "monto_no_sujeto_no_inscripto": _num(form.get("monto_no_sujeto_no_inscripto")),
         "alicuota_no_inscripto": _num(form.get("alicuota_no_inscripto")),
         "retencion_minima_inscripto": _num(form.get("retencion_minima_inscripto")) or Decimal(0),
         "retencion_minima_no_inscripto": _num(form.get("retencion_minima_no_inscripto")) or Decimal(0),
         "resolucion": " ".join((form.get("resolucion") or "").split())[:50] or None,
         "vigencia_desde": _fecha(form.get("vigencia_desde")), "vigencia_hasta": _fecha(form.get("vigencia_hasta")),
         "observaciones": (form.get("observaciones") or "").strip()[:500] or None,
         "activa": 1 if form.get("activa") else 0}
    tramos, et = _tramos_del_form(form)
    e["codigo"] = normalizar_regimen(e["codigo_txt"])

    if actual and actual["usada"]:
        # Congelada: los valores, el código, los tramos y el inicio quedan como están.
        for c in CAMPOS_VALOR + ("codigo_regimen", "vigencia_desde"):
            e[c] = actual[c]
        e["codigo"], e["codigo_txt"] = actual["codigo"], actual["codigo"]
        e["activa"] = actual["activa"]
        tramos = None
        if form.get("vigencia_hasta") and not e["vigencia_hasta"]:
            errores.append("La vigencia hasta no es una fecha.")
        if e["vigencia_hasta"] and actual["ultima_retencion"] and e["vigencia_hasta"] < actual["ultima_retencion"]:
            errores.append(f"Hay retenciones hasta el {actual['ultima_retencion']:%d/%m/%Y}: la vigencia no puede "
                           "terminar antes.")
        if not e["descripcion"]:
            errores.append("La descripción es obligatoria.")
        return e, tramos, errores, avisos

    errores += et
    if not e["codigo"] or len(e["codigo_txt"].lstrip("0")) > 3 or not e["codigo_txt"].isdigit():
        errores.append("El código de régimen son hasta tres dígitos (094, 78, 119).")
    if not e["descripcion"]:
        errores.append("La descripción es obligatoria.")
    if not e["tipo_calculo"]:
        errores.append("Elegí la forma de cálculo: alícuota fija o escala.")
    if not e["vigencia_desde"]:
        errores.append("La vigencia desde es obligatoria.")
    elif form.get("vigencia_hasta") and not e["vigencia_hasta"]:
        errores.append("La vigencia hasta no es una fecha.")
    elif e["vigencia_hasta"] and e["vigencia_hasta"] < e["vigencia_desde"]:
        errores.append("La vigencia termina antes de empezar.")
    for c, nombre in (("alicuota_no_inscripto", "La alícuota para no inscriptos"),):
        if e[c] is None or not 0 <= e[c] <= 100:
            errores.append(f"{nombre} va de 0 a 100.")
    if e["monto_no_sujeto_inscripto"] is None or e["monto_no_sujeto_inscripto"] < 0:
        errores.append("El mínimo no sujeto es un importe (0 si no hay).")
    if e["tipo_calculo"] == "fija":
        if e["alicuota_fija"] is None or not 0 < e["alicuota_fija"] <= 100:
            errores.append("La alícuota fija va de 0 a 100.")
        tramos = []
    elif e["tipo_calculo"] == "escala":
        e["alicuota_fija"] = None
        if not et:
            er, av = _validar_tramos(tramos)
            errores += er
            avisos += av
    e["codigo_regimen"] = str(int(e["codigo"])) if e["codigo"] else e["codigo_txt"]
    return e, tramos, errores, avisos


def _ordenar_vigencias(cur, e) -> tuple[list[str], list[str]]:
    """Que las vigencias del código no se pisen. Devuelve (errores, cerradas)."""
    if not e["activa"]:
        return [], []
    cur.execute(f"""SELECT id, vigencia_desde, vigencia_hasta FROM rg830_escala
                     WHERE activa = 1 AND {CODIGO.format('codigo_regimen')} = %s AND id <> %s""",
                (e["codigo"], e["id"] or 0))
    errores, cerrar = [], []
    fin = e["vigencia_hasta"] or datetime.date.max
    for o in cur.fetchall():
        o_fin = o["vigencia_hasta"] or datetime.date.max
        if not (o["vigencia_desde"] <= fin and o_fin >= e["vigencia_desde"]):    # no se pisan
            continue
        desde_o = f"{o['vigencia_desde']:%d/%m/%Y}"
        if o["vigencia_desde"] >= e["vigencia_desde"]:
            errores.append(f"Ya hay una escala activa del {e['codigo']} desde el {desde_o}: esta tendría que "
                           "terminar antes, o desactivá aquella.")
        elif e["vigencia_hasta"] and o_fin > e["vigencia_hasta"]:
            # Quedaría en el medio de la otra: cerrarla la acortaría también después de esta.
            errores.append(f"Esta vigencia cae en el medio de la que rige desde el {desde_o}. Una nueva vigencia "
                           "va después de la última y sin fin.")
        else:
            # Se cierra la anterior el día antes, salvo que ya retuvo después de esa fecha.
            cur.execute(f"""SELECT MAX(fecha) AS f FROM pago_retenciones
                             WHERE tipo = 'GANANCIAS' AND COALESCE(anulado, 0) = 0
                               AND {CODIGO.format('regimen')} = %s AND fecha >= %s""",
                        (e["codigo"], e["vigencia_desde"]))
            ult = cur.fetchone()["f"]
            if ult:
                errores.append(f"La escala que rige desde el {desde_o} ya retuvo el {ult:%d/%m/%Y}: la nueva vigencia "
                               "tiene que empezar después.")
            else:
                cerrar.append(o)
    return errores, cerrar


@rg830_bp.route("/rg830", methods=["GET", "POST"])
def escalas():
    salida = _guardia()
    if salida:
        return salida
    errores, avisos, form, tramos_form = [], [], None, None
    hoy = datetime.date.today()

    if request.method == "POST":
        accion = request.form.get("accion", "")
        v = (request.form.get("id") or "").strip()
        eid = int(v) if v.isdigit() else None
        with get_connection() as conn:
            conn.begin()
            with conn.cursor() as cur:
                filas = _escalas(cur, eid) if eid else []
                actual = filas[0] if filas else None
                if eid and not actual:
                    flash("!La escala ya no existe.")
                    return redirect(url_for("rg830.escalas"))

                if accion in ("activar", "desactivar", "borrar", "cerrar") and actual:
                    nombre = f"{actual['codigo']} desde el {actual['vigencia_desde']:%d/%m/%Y}"
                    if accion == "activar":
                        tmp = dict(actual, activa=1, id=actual["id"])
                        err, cerrar = _ordenar_vigencias(cur, dict(tmp, codigo=actual["codigo"]))
                        if err:
                            flash("!" + " ".join(err))
                        else:
                            cur.execute("UPDATE rg830_escala SET activa = 1 WHERE id = %s", (eid,))
                            for o in cerrar:
                                cur.execute("UPDATE rg830_escala SET vigencia_hasta = %s WHERE id = %s",
                                            (actual["vigencia_desde"] - datetime.timedelta(days=1), o["id"]))
                            flash(f"Escala {nombre} activada." + (f" Se cerró la vigencia anterior." if cerrar else ""))
                    elif accion in ("desactivar", "borrar") and _unica_vigente_con_proveedores(cur, actual):
                        flash(f"!Es la única escala vigente del {actual['codigo']} y la tienen {actual['proveedores']} "
                              "proveedor(es): quedarían sin régimen. Cargá antes la nueva vigencia.")
                    elif accion == "desactivar":
                        cur.execute("UPDATE rg830_escala SET activa = 0 WHERE id = %s", (eid,))
                        flash(f"Escala {nombre} desactivada: ya no se usa para calcular.")
                    elif accion == "borrar":
                        if actual["usada"]:
                            flash(f"!La escala {nombre} ya se usó en {actual['retenciones']} retención(es): no se elimina. "
                                  "Cerrá su vigencia.")
                        else:
                            cur.execute("DELETE FROM rg830_escala_tramos WHERE id_escala = %s", (eid,))
                            cur.execute("DELETE FROM rg830_escala WHERE id = %s", (eid,))
                            flash(f"Escala {nombre} eliminada.")
                    else:   # cerrar
                        hasta = _fecha(request.form.get("hasta")) or hoy
                        if hasta < actual["vigencia_desde"]:
                            flash("!La vigencia no puede terminar antes de empezar.")
                        elif actual["ultima_retencion"] and hasta < actual["ultima_retencion"]:
                            flash(f"!Hay retenciones hasta el {actual['ultima_retencion']:%d/%m/%Y}: no puede terminar antes.")
                        else:
                            cur.execute("UPDATE rg830_escala SET vigencia_hasta = %s WHERE id = %s", (hasta, eid))
                            flash(f"Escala {nombre}: vigente hasta el {hasta:%d/%m/%Y}."
                                  + (" Cargá la nueva vigencia: los proveedores con este régimen la necesitan."
                                     if actual["proveedores"] else ""))
                    conn.commit()
                    return redirect(url_for("rg830.escalas"))

                if accion == "guardar":
                    form, tramos_form, errores, avisos = _leer(request.form, actual)
                    if not errores:
                        err, cerrar = _ordenar_vigencias(cur, form)
                        errores += err
                    if not errores:
                        uid = session.get("sind_usuario_id")
                        if actual and actual["usada"]:
                            cur.execute("""UPDATE rg830_escala SET descripcion = %s, resolucion = %s, observaciones = %s,
                                                  vigencia_hasta = %s WHERE id = %s""",
                                        (form["descripcion"], form["resolucion"], form["observaciones"],
                                         form["vigencia_hasta"], eid))
                        else:
                            cols = ("codigo_regimen", "descripcion") + CAMPOS_VALOR + (
                                "resolucion", "vigencia_desde", "vigencia_hasta", "activa", "observaciones")
                            if eid:
                                cur.execute(f"UPDATE rg830_escala SET {', '.join(c + ' = %s' for c in cols)} WHERE id = %s",
                                            [form[c] for c in cols] + [eid])
                            else:
                                cur.execute(f"INSERT INTO rg830_escala ({', '.join(cols)}, id_usuario) "
                                            f"VALUES ({', '.join(['%s'] * len(cols))}, %s)", [form[c] for c in cols] + [uid])
                                eid = cur.lastrowid
                            cur.execute("DELETE FROM rg830_escala_tramos WHERE id_escala = %s", (eid,))
                            for i, t in enumerate(tramos_form or [], 1):
                                cur.execute("""INSERT INTO rg830_escala_tramos
                                                   (id_escala, tramo_desde, tramo_hasta, importe_fijo, alicuota, excedente_sobre, orden)
                                               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                                            (eid, t["tramo_desde"], t["tramo_hasta"], t["importe_fijo"], t["alicuota"],
                                             t["excedente_sobre"], i))
                        for o in cerrar:
                            cur.execute("UPDATE rg830_escala SET vigencia_hasta = %s WHERE id = %s",
                                        (form["vigencia_desde"] - datetime.timedelta(days=1), o["id"]))
                        conn.commit()
                        msg = f"Escala del {form['codigo']} guardada."
                        if cerrar:
                            msg += (f" La vigencia anterior quedó cerrada el "
                                    f"{form['vigencia_desde'] - datetime.timedelta(days=1):%d/%m/%Y}.")
                        flash(msg)
                        for a in avisos:
                            flash("!" + a)
                        return redirect(url_for("rg830.escalas", edit=eid))
                    conn.rollback()

    with get_connection() as conn:
        with conn.cursor() as cur:
            lista = _escalas(cur)
            for e in lista:
                e["unica"] = _unica_vigente_con_proveedores(cur, e)
            if form is None:
                base_id = request.args.get("edit", type=int) or request.args.get("clonar", type=int)
                if base_id:
                    base = next((e for e in lista if e["id"] == base_id), None)
                    if not base:
                        flash("!La escala no existe.")
                        return redirect(url_for("rg830.escalas"))
                    cur.execute("""SELECT tramo_desde, tramo_hasta, importe_fijo, alicuota, excedente_sobre
                                     FROM rg830_escala_tramos WHERE id_escala = %s ORDER BY orden, tramo_desde""", (base_id,))
                    tramos_form = cur.fetchall()
                    form = dict(base, codigo_txt=base["codigo"])
                    if request.args.get("clonar"):
                        # Nueva vigencia: los mismos valores, desde hoy (o desde el día después del fin de la copiada).
                        desde = max(hoy, (base["vigencia_hasta"] + datetime.timedelta(days=1)) if base["vigencia_hasta"] else hoy)
                        form.update(id=None, vigencia_desde=desde, vigencia_hasta=None, activa=1, usada=False,
                                    retenciones=0, observaciones=None, clonada_de=base)
                elif request.args.get("nuevo"):
                    form = {"tipo_calculo": "fija", "alicuota_no_inscripto": Decimal(28), "activa": 1,
                            "vigencia_desde": hoy, "monto_no_sujeto_inscripto": Decimal(0)}
                    tramos_form = []
            base = actual_de(form, lista) if form is not None else None
            if base:
                form["usada"], form["ultima_retencion"] = base["usada"], base["ultima_retencion"]
                form["retenciones"] = base["retenciones"]
                if tramos_form is None:     # una usada que volvió con errores: sus tramos no cambiaron
                    cur.execute("""SELECT tramo_desde, tramo_hasta, importe_fijo, alicuota, excedente_sobre
                                     FROM rg830_escala_tramos WHERE id_escala = %s ORDER BY orden""", (base["id"],))
                    tramos_form = cur.fetchall()
    return render_template("tesoreria/rg830.html", escalas=lista, form=form, tramos=tramos_form or [],
                           errores=errores, avisos=avisos, hoy=hoy)


def actual_de(form, lista):
    return next((e for e in lista if form.get("id") and e["id"] == form["id"]), None)
