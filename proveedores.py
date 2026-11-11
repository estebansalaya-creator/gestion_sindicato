"""
proveedores.py — ABM de proveedores (c_proveedores).

Portado de `gestion_adm/proveedores_routes.py`: la misma ficha y las mismas
reglas, con el sistema de estilos de este proyecto y sin lo que es de la obra
social:

- Sin la solapa Hospital / Integración (prestadores de la SSS) ni la de
  Mesa de entradas (área y usuario destino de los expedientes, que acá todavía
  no existen). Las columnas quedan en la tabla, sin tocar.
- De qué impuestos el sindicato es agente de retención sale de «Datos del
  sindicato» (`s_institucion.ret_*`), no de `s_configuracion`. Los bloques de
  los impuestos en los que no es agente se muestran deshabilitados y sus
  campos no se pisan al guardar.
- Sin la importación por CSV: los proveedores vienen de AEDA
  (importar_aeda_proveedores.py).

Reglas que vienen de gestion_adm:
- Un proveedor por CUIT; se avisa mientras se tipea y se controla al guardar.
  Al editar, solo si el CUIT cambió: uno viejo que ya comparte CUIT no puede
  quedar imposible de guardar.
- En el alta, rubro de pasivo y concepto de gasto obligatorios: sin ellos la
  deuda del proveedor no se puede imputar. Y no se puede dar de baja la única
  cuenta activa de cada clase.
- Ganancias: con la retención tildada, el régimen tiene que tener escala
  vigente en `rg830_escala`; a un monotributista no se le retiene.
- Todo cambio queda en `c_proveedores_movimientos`, una fila por campo.

Permiso: la opción de menú «ABM de Proveedores» (/proveedores), en el servidor.
"""

from __future__ import annotations

import re
from datetime import datetime

import pymysql
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

import contactos
import institucion
import proveedores_movimientos as movs
import rg830
import tesoreria
from afiliados import cbu_valido
from db import get_connection, puede, validasesion
from empleadores import cuit_valido

proveedores_bp = Blueprint("proveedores", __name__, url_prefix="/proveedores")

IMPUESTOS = ("iva", "ganancias", "iibb", "suss")

#: Las columnas de cada impuesto en la ficha. De Ganancias se guarda si aplica
#: y el régimen: el cálculo sale de la tabla RG 830.
CAMPOS_RETENCION = {
    "iva":       ("ret_iva", "ret_iva_alicuota", "ret_iva_padron"),
    "ganancias": ("ret_ganancias", "ret_ganancias_codigo_sir"),
    "iibb":      ("ret_iibb", "ret_iibb_alicuota", "ret_iibb_regimen"),
    "suss":      ("ret_suss", "ret_suss_alicuota"),
}
CONDICIONES_IIBB = [(1, "Local"), (2, "Convenio Multilateral"), (3, "Exento"), (4, "No inscripto")]
PADRON_IVA = ["A", "B", "C", "D"]
REGIMENES_IIBB = ["SIRCAR", "SIRCREB", "ARBA", "AGIP", "OTRO"]
MONEDAS = ["ARS", "USD"]


def puede_abm() -> bool:
    return puede(url_for("proveedores.abm"))


def _entero(valor):
    s = re.sub(r"\D", "", str(valor or ""))
    return int(s) if s else None


def _alicuota(valor, rotulo, errores):
    s = str(valor or "").strip().replace(",", ".")
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        v = -1
    if not 0 <= v <= 100:
        errores.append(f"{rotulo}: tiene que ser un porcentaje entre 0 y 100.")
        return None
    return v


def agentes_retencion() -> dict:
    """De qué impuestos el sindicato es agente, según «Datos del sindicato»."""
    d = institucion.obtener()
    return {imp: bool(d.get(f"ret_{imp}")) for imp in IMPUESTOS}


def _por_cuit(cur, cuit, excepto=None):
    """El proveedor que ya tiene ese CUIT, o None. Una sola definición para el
    aviso del campo y la validación al guardar. No filtra por activo: uno dado
    de baja con ese CUIT es el que menos se encuentra y más confunde."""
    cuit = re.sub(r"\D", "", cuit or "")
    if len(cuit) != 11:
        return None
    sql = "SELECT id, razon_social, cuit, activo FROM c_proveedores WHERE cuit = %s"
    params = [cuit]
    if excepto:
        sql += " AND id <> %s"
        params.append(excepto)
    cur.execute(sql + " ORDER BY activo DESC, id LIMIT 1", params)
    r = cur.fetchone()
    if not r:
        return None
    return {"id": r["id"], "razon_social": r["razon_social"] or "(sin razón social)",
            "activo": int(r["activo"] or 0),
            "url": url_for("proveedores.abm", edit=r["id"])}


# =============================================================================
# Lectura
# =============================================================================

def _catalogos(cur) -> dict:
    cur.execute("SELECT codigo, descripcion FROM arca_responsable_tipo ORDER BY codigo")
    condiciones_iva = cur.fetchall()
    cur.execute("SELECT id, nombre FROM c_rubros_de_pasivo ORDER BY nombre")
    rubros = cur.fetchall()
    # Los activos: uno desactivado en Conceptos de Gasto no se ofrece para una
    # cuenta nueva (las que ya lo tienen lo siguen mostrando).
    conceptos = tesoreria.conceptos_activos(cur)
    cur.execute("SELECT codigo, nombre FROM p_provincia ORDER BY nombre")
    provincias = cur.fetchall()
    cur.execute("SELECT id, razon_social FROM c_proveedores "
                "WHERE escabecera_grupo = 1 AND activo = 1 ORDER BY razon_social")
    grupos = cur.fetchall()
    return {"condiciones_iva": condiciones_iva, "rubros_pasivo": rubros,
            "conceptos_gasto": conceptos, "provincias": provincias, "grupos": grupos,
            "regimenes_rg830": rg830.vigentes(cur), "condiciones_iibb": CONDICIONES_IIBB,
            "padron_iva": PADRON_IVA, "regimenes_iibb": REGIMENES_IIBB, "monedas": MONEDAS,
            "areas_contacto": contactos.areas(cur)}


def _listado(cur) -> list[dict]:
    """Todos los proveedores, con lo que la grilla necesita para filtrar."""
    cur.execute("""
        SELECT p.id, p.cuit, p.razon_social, p.nombre_fantasia, p.activo, p.cbu, p.cbu_alias,
               p.condicion_iva, rt.descripcion AS condicion_iva_txt,
               p.ret_iva, p.ret_ganancias, p.ret_ganancias_codigo_sir, p.ret_iibb, p.ret_suss,
               p.escabecera_grupo, p.dom_localidad,
               (SELECT GROUP_CONCAT(DISTINCT r.nombre ORDER BY r.nombre SEPARATOR ', ')
                  FROM c_proveedores_cuentas_pasivo cp
                  JOIN c_rubros_de_pasivo r ON r.id = cp.id_rubro_pasivo
                 WHERE cp.id_proveedor = p.id AND cp.activa = 1) AS rubros,
               (SELECT GROUP_CONCAT(DISTINCT cp.id_rubro_pasivo SEPARATOR ' ')
                  FROM c_proveedores_cuentas_pasivo cp
                 WHERE cp.id_proveedor = p.id AND cp.activa = 1) AS rubros_ids,
               (SELECT GROUP_CONCAT(DISTINCT c.descripcion ORDER BY c.descripcion SEPARATOR ', ')
                  FROM c_proveedores_cuentas_gasto cg
                  JOIN c_concepto_de_gastos c ON c.id = cg.id_concepto_gasto
                 WHERE cg.id_proveedor = p.id AND cg.activa = 1) AS conceptos
          FROM c_proveedores p
          LEFT JOIN arca_responsable_tipo rt ON rt.codigo = p.condicion_iva
         ORDER BY p.razon_social
    """)
    return cur.fetchall()


def _ficha(cur, pid) -> tuple:
    cur.execute("SELECT * FROM c_proveedores WHERE id = %s", (pid,))
    prov = cur.fetchone()
    if not prov:
        return None, [], [], [], []
    cur.execute("""
        SELECT cp.*, r.nombre AS rubro FROM c_proveedores_cuentas_pasivo cp
          JOIN c_rubros_de_pasivo r ON r.id = cp.id_rubro_pasivo
         WHERE cp.id_proveedor = %s AND cp.activa = 1
         ORDER BY cp.predeterminada DESC, r.nombre
    """, (pid,))
    pasivo = cur.fetchall()
    cur.execute("""
        SELECT cg.*, c.descripcion AS concepto FROM c_proveedores_cuentas_gasto cg
          JOIN c_concepto_de_gastos c ON c.id = cg.id_concepto_gasto
         WHERE cg.id_proveedor = %s AND cg.activa = 1
         ORDER BY cg.predeterminada DESC, c.descripcion
    """, (pid,))
    gasto = cur.fetchall()
    return prov, pasivo, gasto, contactos.de(cur, "proveedor", pid), movs.del_proveedor(cur, pid)


# =============================================================================
# Pantalla
# =============================================================================

@proveedores_bp.route("", methods=["GET", "POST"])
def abm():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede_abm():
        flash("!No tenés permiso para el ABM de proveedores.")
        return redirect(url_for("menu"))

    agentes = agentes_retencion()
    errores, proveedor = [], None

    if request.method == "POST":
        accion = request.form.get("accion", "")
        pid = request.form.get("id", type=int)
        if accion == "borrar" and pid:
            return _borrar(pid)
        proveedor, errores, pid = _guardar(pid, agentes)
        if not errores:
            return redirect(url_for("proveedores.abm", edit=pid))

    edit_id = request.args.get("edit", type=int)
    pasivo, gasto, ctos, movimientos = [], [], [], []
    with get_connection() as conn:
        with conn.cursor() as cur:
            if edit_id and proveedor is None:
                proveedor, pasivo, gasto, ctos, movimientos = _ficha(cur, edit_id)
                if not proveedor:
                    flash("!El proveedor no existe.")
                    return redirect(url_for("proveedores.abm"))
            elif proveedor and proveedor.get("id"):
                _, pasivo, gasto, ctos, movimientos = _ficha(cur, proveedor["id"])
            elif proveedor is None and request.args.get("nuevo") and request.args.get("cuit"):
                # Desde la carga de comprobantes o Comprobantes ARCA: el CUIT y
                # la razón social que informó ARCA, para no tipearlos.
                proveedor = {"cuit": re.sub(r"\D", "", request.args["cuit"])[:11],
                             "razon_social": (request.args.get("razon") or "").strip().upper()[:200],
                             "activo": 1}
            listado = _listado(cur)
            cat = _catalogos(cur)

    return render_template(
        "proveedores/abm_proveedores.html",
        proveedor=proveedor, errores=errores, proveedores=listado,
        ctas_pasivo=pasivo, ctas_gasto=gasto, contactos=ctos, movimientos=movimientos,
        agentes=agentes, nuevo=bool(request.args.get("nuevo")) or (proveedor is not None
                                                                  and not proveedor.get("id")),
        **cat)


def _leer_form(f, agentes: dict) -> tuple[dict, list[str]]:
    errores = []
    cuit = re.sub(r"\D", "", f.get("cuit") or "")
    prov_cod = (f.get("dom_provincia_id") or "").strip()
    campos = {
        "cuit":              cuit or None,
        "razon_social":      re.sub(r"\s+", " ", f.get("razon_social") or "").strip().upper(),
        "nombre_fantasia":   (f.get("nombre_fantasia") or "").strip() or None,
        "dom_calle":         (f.get("dom_calle") or "").strip().upper() or None,
        "dom_cp":            (f.get("dom_cp") or "").strip().upper() or None,
        "dom_localidad":     (f.get("dom_localidad") or "").strip().upper() or None,
        "dom_provincia_id":  prov_cod or None,
        "condicion_iva":     _entero(f.get("condicion_iva")),
        "condicion_iibb":    _entero(f.get("condicion_iibb")),
        "nro_iibb":          (f.get("nro_iibb") or "").strip() or None,
        "jurisdiccion_iibb": (f.get("jurisdiccion_iibb") or "").strip().upper()[:2] or None,
        "ret_iva":           1 if f.get("ret_iva") else 0,
        "ret_iva_alicuota":  _alicuota(f.get("ret_iva_alicuota"), "Alícuota de IVA", errores),
        "ret_iva_padron":    (f.get("ret_iva_padron") or "").strip() or None,
        "ret_ganancias":     1 if f.get("ret_ganancias") else 0,
        "ret_ganancias_codigo_sir": rg830.normalizar_regimen(f.get("ret_ganancias_codigo_sir")) or None,
        "ret_iibb":          1 if f.get("ret_iibb") else 0,
        "ret_iibb_alicuota": _alicuota(f.get("ret_iibb_alicuota"), "Alícuota de IIBB", errores),
        "ret_iibb_regimen":  (f.get("ret_iibb_regimen") or "").strip() or None,
        "ret_suss":          1 if f.get("ret_suss") else 0,
        "ret_suss_alicuota": _alicuota(f.get("ret_suss_alicuota"), "Alícuota de SUSS", errores),
        "cbu":               re.sub(r"\D", "", f.get("cbu") or "") or None,
        "cbu_alias":         (f.get("cbu_alias") or "").strip() or None,
        "cheque_a_la_orden": (f.get("cheque_a_la_orden") or "").strip() or None,
        "moneda":            (f.get("moneda") or "ARS").strip() if (f.get("moneda") or "ARS") in MONEDAS else "ARS",
        "condicion_pago_dias": _entero(f.get("condicion_pago_dias")) or 0,
        "escabecera_grupo":  1 if f.get("escabecera_grupo") else 0,
        "id_grupo":          _entero(f.get("id_grupo")),
        "activo":            1 if f.get("activo") else 0,
        "fecha_alta":        (f.get("fecha_alta") or "").strip() or None,
        "observaciones":     (f.get("observaciones") or "").strip() or None,
    }
    # Los impuestos en los que el sindicato no es agente: el formulario los
    # manda deshabilitados (no viajan) y no se pisa lo que hubiera guardado.
    for imp, cols in CAMPOS_RETENCION.items():
        if not agentes.get(imp):
            for col in cols:
                campos.pop(col, None)

    if not campos["razon_social"]:
        errores.append("La razón social es obligatoria.")
    if not campos["cuit"]:
        errores.append("El CUIT es obligatorio.")
    elif len(campos["cuit"]) != 11 or not cuit_valido(campos["cuit"]):
        errores.append(f"El CUIT {campos['cuit']} no es válido: no verifica el dígito de control.")
    if campos["cbu"] and not cbu_valido(campos["cbu"]):
        errores.append(f"El CBU {campos['cbu']} no es válido: no cierran los dígitos verificadores.")
    if campos["fecha_alta"]:
        try:
            datetime.strptime(campos["fecha_alta"], "%Y-%m-%d")
        except ValueError:
            errores.append("La fecha de alta no es válida.")
    if campos["escabecera_grupo"]:
        campos["id_grupo"] = None       # una cabecera no pertenece a otro grupo
    for largo, campo, rotulo in ((200, "razon_social", "Razón social"),
                                 (200, "nombre_fantasia", "Nombre de fantasía"),
                                 (150, "dom_calle", "Calle"), (10, "dom_cp", "Código postal"),
                                 (100, "dom_localidad", "Localidad"), (30, "nro_iibb", "N° de IIBB"),
                                 (50, "cbu_alias", "Alias"), (100, "cheque_a_la_orden", "Cheque a la orden de")):
        if campos.get(campo) and len(campos[campo]) > largo:
            errores.append(f"{rotulo}: hasta {largo} caracteres.")

    if campos.get("ret_ganancias"):
        if rg830.es_monotributista(campos.get("condicion_iva")):
            errores.append("Es monotributista: no corresponde retenerle Ganancias. "
                           "Destildá «Aplica retención de Ganancias».")
        elif not campos.get("ret_ganancias_codigo_sir"):
            errores.append("Elegí el régimen de Ganancias: con la retención tildada, el "
                           "cálculo sale de la tabla RG 830 de ese régimen.")
    return campos, errores


def _guardar(pid, agentes) -> tuple[dict, list[str], int | None]:
    """Alta o modificación. Devuelve (proveedor para redibujar, errores, id)."""
    campos, errores = _leer_form(request.form, agentes)
    nuevo = not pid
    rubro_ini = _entero(request.form.get("id_rubro_pasivo_inicial"))
    gasto_ini = _entero(request.form.get("id_concepto_gasto_inicial"))
    if nuevo:
        if not rubro_ini:
            errores.append("Elegí el rubro de pasivo: define contra qué cuenta corriente nace "
                           "la deuda del proveedor.")
        if not gasto_ini:
            errores.append("Elegí el concepto de gasto: es la imputación de lo que se le compra.")

    with get_connection() as conn:
        with conn.cursor() as cur:
            # El nombre de la provincia se guarda junto al código, como en
            # gestion_adm: los listados viejos leen el texto.
            if campos.get("dom_provincia_id"):
                cur.execute("SELECT nombre FROM p_provincia WHERE codigo = %s",
                            (campos["dom_provincia_id"],))
                fila = cur.fetchone()
                campos["dom_provincia"] = fila["nombre"].upper() if fila else None
            else:
                campos["dom_provincia"] = None

            antes = movs.snapshot(cur, pid) if pid else None
            if pid and not antes:
                errores.append("El proveedor ya no existe.")
            if campos["cuit"] and (nuevo or (antes or {}).get("cuit") != campos["cuit"]):
                dup = _por_cuit(cur, campos["cuit"], pid)
                if dup:
                    errores.append(f"El CUIT {campos['cuit']} ya es de {dup['razon_social']}"
                                   + ("" if dup["activo"] else " (dado de baja)")
                                   + ". Un proveedor por CUIT: editá esa ficha en lugar de crear otra.")
            if campos.get("ret_ganancias") and campos.get("ret_ganancias_codigo_sir") and not any(
                    r["codigo"] == campos["ret_ganancias_codigo_sir"] for r in rg830.vigentes(cur)):
                errores.append(f"El régimen {campos['ret_ganancias_codigo_sir']} no tiene una escala "
                               "vigente en la tabla RG 830: con él no se puede retener. Elegí otro.")
            if campos.get("id_grupo") and campos["id_grupo"] == pid:
                errores.append("Un proveedor no puede ser de su propio grupo.")

            if errores:
                return {**(antes or {}), **campos, "id": pid}, errores, pid

            conn.begin()
            try:
                if nuevo:
                    cols = list(campos)
                    cur.execute(f"INSERT INTO c_proveedores ({', '.join(cols)}) "
                                f"VALUES ({', '.join(['%s'] * len(cols))})",
                                [campos[c] for c in cols])
                    pid = cur.lastrowid
                    movs.registrar_cambios(cur, pid, None, campos, tipo_movimiento="ALTA",
                                           origen_ref="Proveedores")
                    # En la misma transacción: si algo falla no queda un
                    # proveedor sin imputación, que es lo que se quiere evitar.
                    cur.execute("INSERT INTO c_proveedores_cuentas_pasivo (id_proveedor, "
                                "id_rubro_pasivo, descripcion, moneda, predeterminada, activa) "
                                "VALUES (%s, %s, 'Cuenta principal', 'ARS', 1, 1)", (pid, rubro_ini))
                    cur.execute("INSERT INTO c_proveedores_cuentas_gasto (id_proveedor, "
                                "id_concepto_gasto, descripcion, predeterminada, activa) "
                                "VALUES (%s, %s, 'Concepto principal', 1, 1)", (pid, gasto_ini))
                else:
                    cur.execute(f"UPDATE c_proveedores SET {', '.join(f'{c} = %s' for c in campos)} "
                                f"WHERE id = %s", [campos[c] for c in campos] + [pid])
                    movs.registrar_cambios(cur, pid, antes, campos, origen_ref="Proveedores")
                conn.commit()
            except pymysql.err.IntegrityError as e:
                conn.rollback()
                return {**(antes or {}), **campos, "id": pid if not nuevo else None}, \
                    [f"La base rechazó el guardado: {e.args[1] if len(e.args) > 1 else e}"], pid
    flash("Proveedor creado." if nuevo else "Proveedor actualizado.")
    return campos, [], pid


def _borrar(pid):
    with get_connection() as conn:
        with conn.cursor() as cur:
            antes = movs.snapshot(cur, pid)
            if not antes:
                flash("!El proveedor ya no existe.")
                return redirect(url_for("proveedores.abm"))
            conn.begin()
            try:
                # Antes del DELETE: el registro no tiene clave foránea y queda.
                movs.registrar_eliminacion(cur, pid, antes)
                cur.execute("DELETE FROM c_proveedores WHERE id = %s", (pid,))
                conn.commit()
            except pymysql.err.IntegrityError:
                conn.rollback()
                flash("!No se puede eliminar: tiene comprobantes, retenciones o certificados "
                      "cargados. Dalo de baja destildando «Activo».")
                return redirect(url_for("proveedores.abm", edit=pid))
    flash(f"Proveedor {antes['razon_social']} eliminado.")
    return redirect(url_for("proveedores.abm"))


# =============================================================================
# Cuentas contables
# =============================================================================

def _cuenta_txt(cur, clase: str, id_cuenta) -> str | None:
    """«Rubro (descripción)» de una cuenta, para el registro de cambios."""
    if clase == "pasivo":
        cur.execute("SELECT r.nombre AS cuenta, cp.descripcion, cp.predeterminada "
                    "FROM c_proveedores_cuentas_pasivo cp JOIN c_rubros_de_pasivo r "
                    "ON r.id = cp.id_rubro_pasivo WHERE cp.id = %s", (id_cuenta,))
    else:
        cur.execute("SELECT c.descripcion AS cuenta, cg.descripcion, cg.predeterminada "
                    "FROM c_proveedores_cuentas_gasto cg JOIN c_concepto_de_gastos c "
                    "ON c.id = cg.id_concepto_gasto WHERE cg.id = %s", (id_cuenta,))
    r = cur.fetchone()
    if not r:
        return None
    txt = str(r["cuenta"] or "")
    if r.get("descripcion") and r["descripcion"] != r["cuenta"]:
        txt += f" ({r['descripcion']})"
    return txt + (" — predeterminada" if r.get("predeterminada") else "")


TABLAS_CUENTA = {
    "pasivo": ("c_proveedores_cuentas_pasivo", "id_rubro_pasivo", "cuenta_pasivo",
               "es la única cuenta de pasivo activa del proveedor"),
    "gasto":  ("c_proveedores_cuentas_gasto", "id_concepto_gasto", "cuenta_gasto",
               "es el único concepto de gasto activo del proveedor"),
}


@proveedores_bp.route("/<int:pid>/cuenta/<clase>", methods=["POST"])
def cuenta(pid, clase):
    if not validasesion():
        return redirect(url_for("login"))
    if not puede_abm() or clase not in TABLAS_CUENTA:
        flash("!No tenés permiso para el ABM de proveedores.")
        return redirect(url_for("menu"))
    tabla, col, campo_mov, unica = TABLAS_CUENTA[clase]
    volver = url_for("proveedores.abm", edit=pid, solapa="cuentas")
    accion = request.form.get("accion")
    with get_connection() as conn:
        with conn.cursor() as cur:
            conn.begin()
            if accion == "nuevo":
                id_ref = _entero(request.form.get(col))
                if not id_ref:
                    flash("!Elegí la cuenta.")
                    return redirect(volver)
                predet = 1 if request.form.get("predeterminada") else 0
                if predet:
                    # Una sola predeterminada por clase: es la que propone la
                    # carga del comprobante.
                    cur.execute(f"UPDATE {tabla} SET predeterminada = 0 WHERE id_proveedor = %s", (pid,))
                extra_col, extra_val = ("moneda, ", [request.form.get("moneda") or "ARS"]) \
                    if clase == "pasivo" else ("", [])
                cur.execute(f"INSERT INTO {tabla} (id_proveedor, {col}, descripcion, {extra_col}"
                            f"predeterminada, activa) VALUES (%s, %s, %s, "
                            f"{'%s, ' if extra_col else ''}%s, 1)",
                            [pid, id_ref, (request.form.get("descripcion") or "").strip()[:100] or None]
                            + extra_val + [predet])
                movs.registrar_movimiento(cur, pid, campo_mov, None, _cuenta_txt(cur, clase, cur.lastrowid),
                                          origen_ref="Proveedores — Cuentas contables")
                flash("Cuenta agregada.")
            elif accion == "borrar":
                id_cuenta = request.form.get("id", type=int)
                # La regla del alta, también al borrar: sin cuenta la deuda del
                # proveedor no se puede imputar.
                cur.execute(f"SELECT COUNT(*) AS n FROM {tabla} WHERE id_proveedor = %s AND activa = 1",
                            (pid,))
                if cur.fetchone()["n"] <= 1:
                    conn.rollback()
                    flash(f"!No se puede dar de baja: {unica}. Cargá la nueva antes.")
                    return redirect(volver)
                txt = _cuenta_txt(cur, clase, id_cuenta)
                cur.execute(f"UPDATE {tabla} SET activa = 0, predeterminada = 0 "
                            f"WHERE id = %s AND id_proveedor = %s", (id_cuenta, pid))
                if cur.rowcount:
                    movs.registrar_movimiento(cur, pid, campo_mov, txt, None,
                                              origen_ref="Proveedores — Cuentas contables")
                flash("Cuenta dada de baja.")
            conn.commit()
    return redirect(volver)


# =============================================================================
# APIs
# =============================================================================

@proveedores_bp.route("/api/cuit/<cuit>")
def api_cuit(cuit):
    """¿El CUIT es válido y está libre? Para avisar mientras se tipea."""
    if not validasesion():
        return jsonify({"ok": False}), 401
    cuit = re.sub(r"\D", "", cuit)
    if len(cuit) != 11 or not cuit_valido(cuit):
        return jsonify({"ok": True, "valido": False})
    with get_connection() as conn:
        with conn.cursor() as cur:
            dup = _por_cuit(cur, cuit, request.args.get("excepto", type=int))
    return jsonify({"ok": True, "valido": True, "existe": bool(dup), **(dup or {})})


@proveedores_bp.route("/api/buscar")
def api_buscar():
    """Proveedores activos por razón social, fantasía o CUIT (para otros formularios)."""
    if not validasesion():
        return jsonify([]), 401
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify([])
    like = f"%{q}%"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, cuit, razon_social, nombre_fantasia FROM c_proveedores "
                        "WHERE activo = 1 AND (razon_social LIKE %s OR cuit LIKE %s "
                        "OR nombre_fantasia LIKE %s) ORDER BY razon_social LIMIT 20",
                        (like, like, like))
            return jsonify(cur.fetchall())
