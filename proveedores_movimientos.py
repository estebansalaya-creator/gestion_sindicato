"""
proveedores_movimientos.py — Auditoría de cambios sobre c_proveedores.

Portado de gestion_adm: una fila por CAMPO modificado en
`c_proveedores_movimientos` (sql/proveedores_20261107.sql), con el dato
anterior, el actual, quién, cuándo y desde dónde. La ficha lo muestra en la
solapa Movimientos.

POR QUÉ IMPORTA
---------------
En un proveedor se cambian datos que mueven plata: el CBU al que se le
transfiere, el régimen de retención, la cuenta de pasivo contra la que nace la
deuda. Un CBU cambiado sin rastro es exactamente lo que no tiene que poder
pasar.

QUÉ SE REGISTRA
---------------
  · El alta: UN renglón (a quién se dio de alta), no uno por campo.
  · Cada campo que cambió al guardar la ficha. `activo` de 1 a 0 es una BAJA y
    de 0 a 1 una REACTIVACION.
  · Las cuentas contables (rubro de pasivo, concepto de gasto) que se agregan
    o se dan de baja.
  · La eliminación: un renglón con quién era. La tabla NO tiene clave foránea
    a `c_proveedores`: al borrar el proveedor su historia queda.

Las funciones reciben un cursor abierto, para ir en la transacción del que
llama, y nunca lanzan: si la auditoría falla (la tabla todavía no se creó) se
registra en el log y la operación sigue.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal

log = logging.getLogger(__name__)

CAMPO_ALTA = "alta"
CAMPO_ELIMINACION = "eliminacion"

CAMPO_LABEL = {
    CAMPO_ALTA:                 "Alta del proveedor",
    CAMPO_ELIMINACION:          "Eliminación del proveedor",
    "cuit":                     "CUIT",
    "razon_social":             "Razón social",
    "nombre_fantasia":          "Nombre de fantasía",
    "dom_calle":                "Domicilio — calle",
    "dom_cp":                   "Domicilio — código postal",
    "dom_localidad":            "Domicilio — localidad",
    "dom_provincia":            "Domicilio — provincia",
    "condicion_iva":            "Condición IVA",
    "condicion_iibb":           "Condición IIBB",
    "nro_iibb":                 "N° IIBB",
    "jurisdiccion_iibb":        "Jurisdicción IIBB",
    "ret_iva":                  "Aplica retención IVA",
    "ret_iva_alicuota":         "Retención IVA — alícuota %",
    "ret_iva_padron":           "Retención IVA — categoría padrón",
    "ret_ganancias":            "Aplica retención Ganancias",
    "ret_ganancias_codigo_sir": "Retención Ganancias — régimen",
    "ret_iibb":                 "Aplica retención IIBB",
    "ret_iibb_alicuota":        "Retención IIBB — alícuota %",
    "ret_iibb_regimen":         "Retención IIBB — régimen",
    "ret_suss":                 "Aplica retención SUSS",
    "ret_suss_alicuota":        "Retención SUSS — alícuota %",
    "cbu":                      "CBU",
    "cbu_alias":                "Alias",
    "cheque_a_la_orden":        "Cheque a la orden de",
    "moneda":                   "Moneda",
    "condicion_pago_dias":      "Condición de pago (días)",
    "escabecera_grupo":         "Cabecera de grupo",
    "id_grupo":                 "Grupo",
    "activo":                   "Activo",
    "fecha_alta":               "Fecha de alta",
    "observaciones":            "Observaciones",
    "id_area_destino":          "Mesa de entradas — área destino",
    "id_usuario_destino":       "Mesa de entradas — usuario destino",
    # No son columnas de c_proveedores: son sus cuentas contables.
    "cuenta_pasivo":            "Cuenta de pasivo",
    "cuenta_gasto":             "Concepto de gasto",
}

#: `dom_provincia_id` es el código de la provincia que ya se registra por
#: nombre (`dom_provincia`): auditar los dos duplica cada cambio de domicilio.
CAMPOS_IGNORADOS = {"id", "creado", "actualizado", "dom_provincia_id"}

CAMPOS_SI_NO = {"ret_iva", "ret_ganancias", "ret_iibb", "ret_suss",
                "escabecera_grupo", "activo"}

#: Los códigos de la condición de IIBB: no hay tabla, están en el formulario.
CONDICION_IIBB = {"1": "Local", "2": "Convenio Multilateral", "3": "Exento",
                  "4": "No inscripto"}

#: Los campos que son un código de otra tabla: la consulta que da (k, v).
TABLAS_CAMPO = {
    "condicion_iva": "SELECT codigo AS k, descripcion AS v FROM arca_responsable_tipo",
    "id_grupo":      "SELECT id AS k, razon_social AS v FROM c_proveedores",
    "id_area_destino":    "SELECT id AS k, nombre AS v FROM s_areas",
    "id_usuario_destino": "SELECT id AS k, nombre AS v FROM s_usuarios",
}

_MAX_VALOR = 255


def _norm(v):
    """Un valor como texto comparable. None y '' son lo mismo."""
    if v is None:
        return None
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, Decimal):
        v = format(v.normalize(), "f")
    s = str(v).strip()
    return s or None


def _iguales(a, b) -> bool:
    """¿Es el mismo dato? 5 y '5', 2.00 y 2, una fecha y su texto."""
    na, nb = _norm(a), _norm(b)
    if na == nb:
        return True
    try:
        return na is not None and nb is not None and float(na) == float(nb)
    except (TypeError, ValueError):
        return False


def _recortar(v):
    s = _norm(v)
    return s if s is None or len(s) <= _MAX_VALOR else s[:_MAX_VALOR - 1] + "…"


def usuario_actual() -> str | None:
    """El usuario logueado (mail, o nombre). None fuera de un pedido web."""
    try:
        from flask import has_request_context, session
        if not has_request_context():
            return None
        return session.get("sind_usuario_email") or session.get("sind_usuario_nombre") or None
    except Exception:                                        # noqa: BLE001
        return None


def registrar_movimiento(cur, id_proveedor, campo, valor_anterior=None,
                         valor_actual=None, *, tipo_movimiento="MODIFICACION",
                         origen="MANUAL", origen_ref=None, cuit=None,
                         usuario=None, observaciones=None) -> bool:
    """Graba un movimiento. Devuelve True si quedó registrado."""
    if not id_proveedor or not campo:
        return False
    if usuario is None:
        usuario = usuario_actual()
    try:
        cur.execute("""
            INSERT INTO c_proveedores_movimientos
                (id_proveedor, cuit, tipo_movimiento, origen, origen_ref,
                 campo, campo_label, valor_anterior, valor_actual,
                 usuario, observaciones)
            VALUES (%s,%s,%s,%s,%s, %s,%s,%s,%s, %s,%s)
        """, (int(id_proveedor), _norm(cuit), tipo_movimiento, origen,
              _recortar(origen_ref), campo, CAMPO_LABEL.get(campo, campo),
              _recortar(valor_anterior), _recortar(valor_actual),
              _recortar(usuario), _recortar(observaciones)))
        return True
    except Exception as e:                                   # noqa: BLE001
        log.warning("No se pudo auditar el proveedor %s (%s): %s", id_proveedor, campo, e)
        return False


def registrar_cambios(cur, id_proveedor, antes: dict | None, despues: dict, *,
                      tipo_movimiento="MODIFICACION", origen="MANUAL",
                      origen_ref=None, cuit=None, usuario=None,
                      observaciones=None) -> int:
    """
    Compara `antes` con `despues` y graba una fila por campo que cambió. Solo
    se miran los campos que están en los dos: lo que el formulario no mandó no
    cambió. Con `tipo_movimiento="ALTA"` graba un solo renglón.
    """
    if not id_proveedor or not despues:
        return 0
    antes = antes or {}
    cuit = cuit or despues.get("cuit") or antes.get("cuit")

    if tipo_movimiento == "ALTA":
        quien = _norm(despues.get("razon_social")) or _norm(cuit) or ""
        return 1 if registrar_movimiento(
            cur, id_proveedor, CAMPO_ALTA, None, quien, tipo_movimiento="ALTA",
            origen=origen, origen_ref=origen_ref, cuit=cuit, usuario=usuario,
            observaciones=observaciones) else 0

    n = 0
    for campo, nuevo in despues.items():
        if campo in CAMPOS_IGNORADOS or campo not in antes:
            continue
        viejo = antes.get(campo)
        if _iguales(viejo, nuevo):
            continue
        tipo = tipo_movimiento
        if campo == "activo":
            tipo = "BAJA" if _norm(nuevo) in (None, "0") else "REACTIVACION"
        n += registrar_movimiento(
            cur, id_proveedor, campo, viejo, nuevo, tipo_movimiento=tipo,
            origen=origen, origen_ref=origen_ref, cuit=cuit, usuario=usuario,
            observaciones=observaciones)
    return n


def registrar_eliminacion(cur, id_proveedor, antes: dict | None) -> bool:
    """Un renglón con quién era, ANTES del DELETE."""
    antes = antes or {}
    quien = " · ".join(x for x in (_norm(antes.get("razon_social")),
                                   _norm(antes.get("cuit"))) if x)
    return registrar_movimiento(cur, id_proveedor, CAMPO_ELIMINACION,
                                quien or str(id_proveedor), None,
                                tipo_movimiento="ELIMINACION", cuit=antes.get("cuit"))


def snapshot(cur, id_proveedor) -> dict | None:
    """El proveedor como está ahora, para comparar después del UPDATE."""
    if not id_proveedor:
        return None
    try:
        cur.execute("SELECT * FROM c_proveedores WHERE id = %s", (id_proveedor,))
        r = cur.fetchone()
        return dict(r) if r else None
    except Exception as e:                                   # noqa: BLE001
        log.warning("No se pudo leer el proveedor %s: %s", id_proveedor, e)
        return None


def _clave(v) -> str:
    t = str(v).strip() if v is not None else ""
    return t.lstrip("0") or ("0" if t else "")


def descripciones(cur, filas) -> None:
    """Agrega `ant_txt` y `act_txt`: Sí/No, la descripción del código o el valor."""
    mapas = {}
    for campo in {r.get("campo") for r in filas} & set(TABLAS_CAMPO):
        try:
            cur.execute(TABLAS_CAMPO[campo])
            mapas[campo] = {_clave(x["k"]): x["v"] for x in cur.fetchall()}
        except Exception as e:                               # noqa: BLE001
            log.warning("movimientos de proveedores: tabla de %s: %s", campo, e)
    mapas["condicion_iibb"] = CONDICION_IIBB
    for r in filas:
        campo = r.get("campo")
        for col, dest in (("valor_anterior", "ant_txt"), ("valor_actual", "act_txt")):
            v = r.get(col)
            if v in (None, ""):
                r[dest] = v
            elif campo in CAMPOS_SI_NO:
                r[dest] = "Sí" if _norm(v) != "0" else "No"
            elif campo in mapas:
                r[dest] = mapas[campo].get(_clave(v), v)
            else:
                r[dest] = v


def del_proveedor(cur, id_proveedor, limite: int = 500) -> list[dict]:
    """Los movimientos del proveedor, el más reciente primero. [] sin la tabla."""
    try:
        cur.execute("""
            SELECT * FROM c_proveedores_movimientos
             WHERE id_proveedor = %s
             ORDER BY fecha DESC, id_movimiento DESC
             LIMIT %s
        """, (int(id_proveedor), int(limite)))
        filas = [dict(r) for r in cur.fetchall()]
    except Exception as e:                                   # noqa: BLE001
        log.warning("Movimientos del proveedor %s: %s", id_proveedor, e)
        return []
    descripciones(cur, filas)
    return filas
