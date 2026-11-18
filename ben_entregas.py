"""
ben_entregas.py — Beneficios › Campañas › padrón de entrega (pedido del 18/11/2026).

«Dentro de campañas, con el filtro que selecciono de a quién se envía, un botón
crea padrón para entrega de beneficio; por ejemplo si la campaña es cajas
navideñas, cuando vengan a retirar marcar al afiliado como que retiró.»

EL PADRÓN DE ENTREGA (`ben_entrega`)
«Crear padrón de entrega», en la ficha de la campaña, arma la lista con el
MISMO GRUPO de «A quién va» (los filtros del padrón, titulares, titulares y
familiares, adheridos de un convenio: `ben_campanias.personas`), TENGAN O NO
CORREO: el beneficio es de la persona, no de su dirección. Es una FOTO del
padrón de afiliados al crearlo: lo que cambie después no lo toca. Lleva número
de orden (alfabético), documento, CUIL, parentesco y empleador. Se vuelve a
crear mientras nadie retiró (se pierden los agregados a mano). Se le agrega a
alguien a mano (con motivo) o se lo quita (sin retiro, con motivo). Es
independiente del envío del mail: se crea con la campaña en borrador o ya
enviada.

EL RETIRO
En la grilla se busca al afiliado (documento, CUIL, apellido: el filtro de la
grilla) y «Marcar que retiró» registra cuándo y quién lo marcó, y, si no vino
el afiliado, quién retiró (nombre y documento, opcionales). Marca sin recargar
la página. Dos puestos a la vez no se pisan: el UPDATE solo marca a quien no
retiró y el segundo ve quién y a qué hora. Quitar un retiro pide motivo. Todo
queda en `ben_entrega_mov`.

EL STOCK (pedido del 18/11/2026, `ben_entrega_stock`)
Cuántos beneficios hay para entregar: cada carga suma (la compra de las cajas,
con el remito en el detalle) y un ajuste resta (rotas, devueltas), con motivo.
Lo que queda es lo cargado menos lo retirado. Con stock cargado, un retiro que
lo dejaría en negativo no se registra: la campaña se bloquea al marcar
(FOR UPDATE), así dos puestos no entregan la última caja dos veces. Sin ninguna
carga de stock, no se controla (y la pantalla lo avisa). Un ajuste no puede
dejar lo cargado por debajo de lo ya retirado.

FUERA DEL PADRÓN (pedido del 18/11/2026)
«Entregar a alguien fuera del padrón» registra el retiro de quien no está en el
padrón de entrega, con motivo: si el documento o CUIL es de un afiliado, entra
al padrón como agregado a mano y ya con el retiro; si no es afiliado (un
invitado, un no afiliado), entra con su nombre y documento, sin afiliado
(`id_afiliado` NULL, origen «externo»). Descuenta stock igual. Quitarle el
retiro a uno de afuera lo saca de la lista (no tiene padrón al que volver).

Permiso: el de Campañas (/beneficios/campanias). sql/beneficios_entregas_20261118.sql
y sql/beneficios_entregas_stock_20261118.sql.

  /beneficios/campanias/<id>/entrega               el padrón de entrega; POST acciones
  /beneficios/campanias/<id>/entrega/api_entregar  «Marcar que retiró» (JSON)
La grilla exporta a Excel con los filtros puestos, como todas.
"""

from __future__ import annotations

import logging
import re

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

import ben_campanias as camp_mod
from db import get_connection, puede, usuario_actual, validasesion

log = logging.getLogger(__name__)

ben_ent_bp = Blueprint("ben_ent", __name__, url_prefix="/beneficios")

URL = camp_mod.URL
SQL_ESQUEMA = "sql/beneficios_entregas_20261118.sql"
SQL_ESQUEMA_STOCK = "sql/beneficios_entregas_stock_20261118.sql"
#: Las personas se piden de a tantas al armar el padrón.
TANDA = 500


class ErrorEntrega(ValueError):
    """Un error de validación: el texto va directo a la pantalla."""


# =============================================================================
# Reglas (sin base: lo prueba tests/test_ben_entregas.py)
# =============================================================================

def limpio(texto, largo: int) -> str:
    return " ".join((texto or "").split())[:largo]


def solo_digitos(texto) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def leer_retiro(datos: dict) -> tuple[str | None, str | None]:
    """(nombre, documento) de quien retiró, si no fue el afiliado. Documento sin
    puntos; un documento sin nombre no dice nada y se rechaza."""
    nombre = limpio(datos.get("retiro_nombre"), 150) or None
    doc = solo_digitos(datos.get("retiro_documento"))[:20] or None
    if doc and not nombre:
        raise ErrorEntrega("Escribí también el nombre de quien retira.")
    return nombre, doc


def detalle_retiro(orden, nombre: str | None, doc: str | None) -> str:
    d = f"Orden {orden}"
    if nombre:
        d += f": retiró {nombre}" + (f" (DNI {doc})" if doc else "")
    return d


def resumen(total: int, entregados: int, stock: int | None = None) -> dict:
    """`stock`: lo cargado (None o 0 sin cargas: no se controla)."""
    r = {"padron": total, "entregados": entregados, "faltan": total - entregados,
         "porc": round(entregados * 100 / total, 1) if total else 0.0,
         "stock": int(stock or 0), "controla_stock": bool(stock)}
    r["queda"] = r["stock"] - entregados if r["controla_stock"] else None
    return r


def control_stock(camp: dict) -> None:
    """Antes de un retiro: con stock cargado, que quede al menos uno."""
    if camp.get("controla_stock") and (camp.get("queda") or 0) <= 0:
        raise ErrorEntrega(f"No queda stock: se cargaron {camp['stock']} y ya se entregaron {camp['entregados']}. "
                           "Cargá más stock para seguir entregando.")


def leer_stock(cantidad, detalle, entregados: int, stock: int) -> tuple[int, str]:
    """(cantidad, detalle) de una carga (+) o un ajuste (−) de stock."""
    try:
        n = int(str(cantidad or "").strip())
    except ValueError:
        raise ErrorEntrega("La cantidad es un número entero: positivo carga, negativo ajusta.") from None
    detalle = limpio(detalle, 250)
    if n == 0:
        raise ErrorEntrega("La cantidad no puede ser cero.")
    if abs(n) > 1_000_000:
        raise ErrorEntrega("La cantidad es demasiado grande.")
    if not detalle:
        raise ErrorEntrega("Escribí el detalle (la compra, el remito, el motivo del ajuste).")
    if stock + n < entregados:
        raise ErrorEntrega(f"Con ese ajuste quedarían {stock + n} cargados y ya se entregaron {entregados}.")
    if stock + n < 0:
        raise ErrorEntrega("El stock cargado no puede quedar en negativo.")
    return n, detalle


# =============================================================================
# Base
# =============================================================================

def hay_stock(cur) -> bool:
    """sql/beneficios_entregas_stock_20261118.sql: el stock y los de fuera del padrón."""
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_schema = DATABASE()
                     AND table_name = 'ben_entrega_stock'""")
    return bool(cur.fetchone()["n"])


def hay_esquema(cur) -> bool:
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_schema = DATABASE()
                     AND table_name IN ('ben_entrega', 'ben_entrega_mov')""")
    if int(cur.fetchone()["n"] or 0) != 2:
        return False
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.columns WHERE table_schema = DATABASE()
                     AND table_name = 'ben_campania' AND column_name = 'entrega_generada'""")
    return bool(cur.fetchone()["n"])


def campania(cur, id_camp: int, bloquear=False) -> dict | None:
    con_stock = hay_stock(cur)
    stock = ("(SELECT COALESCE(SUM(s.cantidad), 0) FROM ben_entrega_stock s WHERE s.id_campania = c.id)"
             if con_stock else "0")
    # «padron»: los del padrón de entrega, sin los de afuera (esos no estaban en la lista).
    cur.execute(f"""SELECT c.*, v.nombre AS convenio,
                           (SELECT COUNT(*) FROM ben_entrega e WHERE e.id_campania = c.id
                               {"AND e.origen <> 'externo'" if con_stock else ""}) AS padron,
                           (SELECT COUNT(*) FROM ben_entrega e WHERE e.id_campania = c.id AND e.entregado = 1) AS entregados,
                           (SELECT COUNT(*) FROM ben_entrega e WHERE e.id_campania = c.id
                               AND e.entregado = 1 {"AND e.origen <> 'externo'" if con_stock else ""}) AS entregados_padron,
                           {stock} AS stock_cargado
                      FROM ben_campania c LEFT JOIN ben_convenio v ON v.id = c.id_convenio
                     WHERE c.id = %s {'FOR UPDATE' if bloquear else ''}""", (id_camp,))
    c = cur.fetchone()
    if c:
        c.update(resumen(int(c["padron"] or 0), int(c["entregados"] or 0), int(c["stock_cargado"] or 0)))
        # Del padrón faltan los que no retiraron; los de afuera no cuentan para eso.
        c["faltan"] = c["padron"] - int(c["entregados_padron"] or 0)
        c["porc"] = round(int(c["entregados_padron"] or 0) * 100 / c["padron"], 1) if c["padron"] else 0.0
        c["externos"] = c["entregados"] - int(c["entregados_padron"] or 0)
        c["hay_stock"] = con_stock
    return c


def stock_movs(cur, id_camp: int) -> list[dict]:
    if not hay_stock(cur):
        return []
    cur.execute("""SELECT s.*, u.nombre AS usuario FROM ben_entrega_stock s
                     LEFT JOIN s_usuarios u ON u.id = s.id_usuario
                    WHERE s.id_campania = %s ORDER BY s.fecha DESC, s.id DESC""", (id_camp,))
    return cur.fetchall()


def cargar_stock(cur, camp: dict, cantidad, detalle, uid) -> int:
    n, detalle = leer_stock(cantidad, detalle, camp["entregados"], camp["stock"])
    cur.execute("""INSERT INTO ben_entrega_stock (id_campania, cantidad, detalle, id_usuario)
                   VALUES (%s, %s, %s, %s)""", (camp["id"], n, detalle, uid))
    _mov(cur, camp["id"], None, "stock", f"{'+' if n > 0 else ''}{n}: {detalle}", uid)
    return n


def padron(cur, id_camp: int) -> list[dict]:
    cur.execute("""SELECT e.*, u.nombre AS usuario_entrega FROM ben_entrega e
                     LEFT JOIN s_usuarios u ON u.id = e.id_usuario_entrega
                    WHERE e.id_campania = %s ORDER BY e.orden""", (id_camp,))
    return cur.fetchall()


def movimientos(cur, id_camp: int, limite: int = 1000) -> list[dict]:
    cur.execute(f"""SELECT m.*, u.nombre AS usuario, COALESCE(e.apellido_nombres, a.apellido_nombres) AS apellido_nombres,
                           COALESCE(e.nro_documento, CAST(a.nro_documento AS CHAR)) AS nro_documento
                      FROM ben_entrega_mov m
                      LEFT JOIN s_usuarios u ON u.id = m.id_usuario
                      LEFT JOIN ben_entrega e ON e.id_campania = m.id_campania AND e.id_afiliado = m.id_afiliado
                      LEFT JOIN p_afiliados a ON a.id_afiliado = m.id_afiliado
                     WHERE m.id_campania = %s ORDER BY m.fecha DESC, m.id DESC LIMIT {int(limite)}""", (id_camp,))
    return cur.fetchall()


def _mov(cur, id_camp, id_afi, accion, detalle, uid):
    cur.execute("""INSERT INTO ben_entrega_mov (id_campania, id_afiliado, accion, detalle, id_usuario)
                   VALUES (%s, %s, %s, %s, %s)""", (id_camp, id_afi, accion, (detalle or None) and detalle[:300], uid))


SQL_DATOS = """SELECT a.id_afiliado, NULLIF(a.cuil, '') AS cuil, NULLIF(CAST(a.nro_documento AS CHAR), '') AS nro_documento,
                      COALESCE(NULLIF(a.apellido_nombres, ''), '(sin nombre)') AS apellido_nombres,
                      a.cod_parentesco, p.descripcion AS parentesco, NULLIF(a.cuil_titular, '') AS cuil_titular,
                      COALESCE(e.razon_social, NULLIF(CAST(a.cuit_empleador AS CHAR), '')) AS empleador, a.activo
                 FROM p_afiliados a
                 LEFT JOIN p_parentesco p ON p.codigo = a.cod_parentesco
                 LEFT JOIN p_empresas e ON a.cuit_empleador REGEXP '^[0-9]+$'
                                       AND e.CUIT = CAST(a.cuit_empleador AS UNSIGNED)"""


def _reordenar(cur, id_camp):
    cur.execute("""UPDATE ben_entrega x
                     JOIN (SELECT id, ROW_NUMBER() OVER (ORDER BY apellido_nombres, id) AS n
                             FROM ben_entrega WHERE id_campania = %s) o ON o.id = x.id
                      SET x.orden = o.n""", (id_camp,))


def generar(cur, camp: dict, uid) -> int:
    """Arma (o rehace) el padrón de entrega con el grupo de «A quién va». Con algún retiro, no."""
    if camp["entregados"]:
        n = camp["entregados"]
        raise ErrorEntrega(f"Ya {'retiró uno' if n == 1 else f'retiraron {n}'}: el padrón de entrega no se vuelve a crear.")
    try:
        grupo = camp_mod.personas(cur, camp["destino"], camp["id_convenio"], camp_mod._filtro_guardado(camp))
    except camp_mod.ErrorCampania as e:
        raise ErrorEntrega(str(e)) from e
    ids = sorted({p["id_afiliado"] for p in grupo})
    if not ids:
        raise ErrorEntrega("El grupo de «A quién va» no tiene a nadie: no hay padrón que crear.")
    cur.execute("DELETE FROM ben_entrega WHERE id_campania = %s", (camp["id"],))
    filas = []
    for i in range(0, len(ids), TANDA):
        tanda = ids[i:i + TANDA]
        cur.execute(SQL_DATOS + f" WHERE a.id_afiliado IN ({', '.join(['%s'] * len(tanda))})", tanda)
        filas += cur.fetchall()
    cur.executemany("""INSERT INTO ben_entrega (id_campania, id_afiliado, orden, cuil, nro_documento, apellido_nombres,
                                                cod_parentesco, parentesco, cuil_titular, empleador, origen)
                       VALUES (%s, %s, 0, %s, %s, %s, %s, %s, %s, %s, 'padron')""",
                    [(camp["id"], f["id_afiliado"], f["cuil"], f["nro_documento"], f["apellido_nombres"],
                      f["cod_parentesco"], f["parentesco"], f["cuil_titular"], (f["empleador"] or None) and f["empleador"][:200])
                     for f in filas])
    _reordenar(cur, camp["id"])
    cur.execute("UPDATE ben_campania SET entrega_generada = NOW() WHERE id = %s", (camp["id"],))
    _mov(cur, camp["id"], None, "generado", f"{len(filas)} personas", uid)
    return len(filas)


def _afiliado(cur, numero: str) -> dict | None:
    cur.execute(SQL_DATOS + """ WHERE a.cuil = %s OR CAST(a.nro_documento AS CHAR) = %s
                               ORDER BY a.activo DESC, (a.cod_parentesco = 0) DESC, a.id_afiliado LIMIT 1""",
                (numero, numero))
    return cur.fetchone()


def agregar(cur, camp: dict, numero: str, motivo: str, uid) -> dict:
    if not camp.get("entrega_generada"):
        raise ErrorEntrega("Primero creá el padrón de entrega.")
    numero, motivo = solo_digitos(numero), limpio(motivo, 250)
    if not numero:
        raise ErrorEntrega("Escribí el CUIL o el documento.")
    if not motivo:
        raise ErrorEntrega("Escribí el motivo: queda en los movimientos.")
    afi = _afiliado(cur, numero)
    if not afi:
        raise ErrorEntrega(f"{numero} no está en el padrón de afiliados.")
    cur.execute("SELECT orden FROM ben_entrega WHERE id_campania = %s AND id_afiliado = %s", (camp["id"], afi["id_afiliado"]))
    ya = cur.fetchone()
    if ya:
        raise ErrorEntrega(f"{afi['apellido_nombres']} ya está en el padrón de entrega (orden {ya['orden']}).")
    cur.execute("SELECT COALESCE(MAX(orden), 0) + 1 AS n FROM ben_entrega WHERE id_campania = %s", (camp["id"],))
    orden = cur.fetchone()["n"]
    cur.execute("""INSERT INTO ben_entrega (id_campania, id_afiliado, orden, cuil, nro_documento, apellido_nombres,
                                            cod_parentesco, parentesco, cuil_titular, empleador, origen)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'manual')""",
                (camp["id"], afi["id_afiliado"], orden, afi["cuil"], afi["nro_documento"], afi["apellido_nombres"],
                 afi["cod_parentesco"], afi["parentesco"], afi["cuil_titular"],
                 (afi["empleador"] or None) and afi["empleador"][:200]))
    _mov(cur, camp["id"], afi["id_afiliado"], "agregado", motivo, uid)
    aviso = " Ojo: en el padrón de afiliados está de baja." if not afi["activo"] else ""
    return {"nombre": afi["apellido_nombres"], "orden": orden, "aviso": aviso}


def quitar(cur, camp: dict, id_fila: int, motivo: str, uid) -> str:
    motivo = limpio(motivo, 250)
    if not motivo:
        raise ErrorEntrega("Escribí el motivo.")
    cur.execute("SELECT * FROM ben_entrega WHERE id = %s AND id_campania = %s FOR UPDATE", (id_fila, camp["id"]))
    f = cur.fetchone()
    if not f:
        raise ErrorEntrega("No está en el padrón de entrega.")
    if f["entregado"]:
        raise ErrorEntrega(f"{f['apellido_nombres']} ya retiró: primero hay que quitarle el retiro.")
    cur.execute("DELETE FROM ben_entrega WHERE id = %s", (id_fila,))
    _mov(cur, camp["id"], f["id_afiliado"], "quitado", f"Orden {f['orden']}: {motivo}", uid)
    return f["apellido_nombres"]


def entregar(cur, camp: dict, id_fila: int, nombre: str | None, doc: str | None, uid) -> dict:
    """Marca que retiró. Si ya retiró (otro puesto), lo dice con la hora y quién.
    `camp` viene leída con FOR UPDATE: el control de stock no se cruza con otro puesto."""
    cur.execute("SELECT entregado FROM ben_entrega WHERE id = %s AND id_campania = %s", (id_fila, camp["id"]))
    ya = cur.fetchone()
    if ya and not ya["entregado"]:
        control_stock(camp)
    cur.execute("""UPDATE ben_entrega SET entregado = 1, fecha_entrega = NOW(), id_usuario_entrega = %s,
                                          retiro_nombre = %s, retiro_documento = %s
                    WHERE id = %s AND id_campania = %s AND entregado = 0""", (uid, nombre, doc, id_fila, camp["id"]))
    marcado = cur.rowcount == 1
    cur.execute("""SELECT e.*, u.nombre AS usuario_entrega FROM ben_entrega e
                     LEFT JOIN s_usuarios u ON u.id = e.id_usuario_entrega
                    WHERE e.id = %s AND e.id_campania = %s""", (id_fila, camp["id"]))
    f = cur.fetchone()
    if not f:
        raise ErrorEntrega("No está en el padrón de entrega.")
    if marcado:
        _mov(cur, camp["id"], f["id_afiliado"], "entrega", detalle_retiro(f["orden"], nombre, doc), uid)
    return {"marcado": marcado, "fila": f}


def quitar_entrega(cur, camp: dict, id_fila: int, motivo: str, uid) -> str:
    motivo = limpio(motivo, 250)
    if not motivo:
        raise ErrorEntrega("Escribí el motivo para quitar el retiro.")
    cur.execute("SELECT * FROM ben_entrega WHERE id = %s AND id_campania = %s FOR UPDATE", (id_fila, camp["id"]))
    f = cur.fetchone()
    if not f:
        raise ErrorEntrega("No está en el padrón de entrega.")
    if not f["entregado"]:
        raise ErrorEntrega(f"{f['apellido_nombres']} no tiene el retiro registrado.")
    if f["origen"] == "externo":
        # No estaba en el padrón: sin el retiro no hay nada que dejar en la lista.
        cur.execute("DELETE FROM ben_entrega WHERE id = %s", (id_fila,))
        _mov(cur, camp["id"], None, "quita_entrega",
             f"Fuera del padrón, {f['apellido_nombres']}" + (f" (DNI {f['nro_documento']})" if f["nro_documento"] else "")
             + f", había retirado {f['fecha_entrega']:%d/%m/%Y %H:%M}: {motivo}", uid)
        return f["apellido_nombres"]
    cur.execute("""UPDATE ben_entrega SET entregado = 0, fecha_entrega = NULL, id_usuario_entrega = NULL,
                                          retiro_nombre = NULL, retiro_documento = NULL WHERE id = %s""", (id_fila,))
    _mov(cur, camp["id"], f["id_afiliado"], "quita_entrega",
         f"Orden {f['orden']}, había retirado {f['fecha_entrega']:%d/%m/%Y %H:%M}: {motivo}", uid)
    return f["apellido_nombres"]


def entregar_fuera(cur, camp: dict, numero, nombre, motivo, retiro_nombre, retiro_doc, uid) -> dict:
    """El retiro de alguien que no está en el padrón de entrega (ver el docstring)."""
    if not camp.get("entrega_generada"):
        raise ErrorEntrega("Primero creá el padrón de entrega.")
    numero, nombre, motivo = solo_digitos(numero)[:20], limpio(nombre, 100), limpio(motivo, 250)
    if not numero:
        raise ErrorEntrega("Escribí el documento o el CUIL de quien recibe.")
    if not motivo:
        raise ErrorEntrega("Escribí el motivo: por qué se le entrega estando fuera del padrón.")
    afi = _afiliado(cur, numero)
    if afi:
        cur.execute("SELECT orden, entregado FROM ben_entrega WHERE id_campania = %s AND id_afiliado = %s",
                    (camp["id"], afi["id_afiliado"]))
        ya = cur.fetchone()
        if ya:
            raise ErrorEntrega(f"{afi['apellido_nombres']} está en el padrón de entrega (orden {ya['orden']}): "
                               + ("ya retiró." if ya["entregado"] else "marcalo desde la grilla."))
    else:
        if not nombre:
            raise ErrorEntrega(f"{numero} no es afiliado: escribí su apellido y nombre.")
        cur.execute("""SELECT fecha_entrega FROM ben_entrega WHERE id_campania = %s AND origen = 'externo'
                          AND nro_documento = %s""", (camp["id"], numero))
        ya = cur.fetchone()
        if ya:
            raise ErrorEntrega(f"{numero} ya retiró fuera del padrón el {ya['fecha_entrega']:%d/%m/%Y %H:%M}.")
    control_stock(camp)
    cur.execute("SELECT COALESCE(MAX(orden), 0) + 1 AS n FROM ben_entrega WHERE id_campania = %s", (camp["id"],))
    orden = cur.fetchone()["n"]
    if afi:
        cur.execute("""INSERT INTO ben_entrega (id_campania, id_afiliado, orden, cuil, nro_documento, apellido_nombres,
                                                cod_parentesco, parentesco, cuil_titular, empleador, origen,
                                                entregado, fecha_entrega, id_usuario_entrega, retiro_nombre,
                                                retiro_documento, observaciones)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'manual', 1, NOW(), %s, %s, %s, %s)""",
                    (camp["id"], afi["id_afiliado"], orden, afi["cuil"], afi["nro_documento"], afi["apellido_nombres"],
                     afi["cod_parentesco"], afi["parentesco"], afi["cuil_titular"],
                     (afi["empleador"] or None) and afi["empleador"][:200], uid, retiro_nombre, retiro_doc, motivo))
        _mov(cur, camp["id"], afi["id_afiliado"], "agregado", f"Fuera del padrón: {motivo}", uid)
        _mov(cur, camp["id"], afi["id_afiliado"], "entrega", detalle_retiro(orden, retiro_nombre, retiro_doc), uid)
        quien = afi["apellido_nombres"]
    else:
        cur.execute("""INSERT INTO ben_entrega (id_campania, id_afiliado, orden, nro_documento, apellido_nombres, origen,
                                                entregado, fecha_entrega, id_usuario_entrega, retiro_nombre,
                                                retiro_documento, observaciones)
                       VALUES (%s, NULL, %s, %s, %s, 'externo', 1, NOW(), %s, %s, %s, %s)""",
                    (camp["id"], orden, numero, nombre, uid, retiro_nombre, retiro_doc, motivo))
        _mov(cur, camp["id"], None, "externo",
             f"{nombre} (DNI {numero}), no afiliado: {motivo}"
             + (f"; retiró {retiro_nombre}" + (f" (DNI {retiro_doc})" if retiro_doc else "") if retiro_nombre else ""), uid)
        quien = nombre
    return {"nombre": quien, "afiliado": bool(afi), "orden": orden}


# =============================================================================
# Pantallas
# =============================================================================

def _uid():
    return (usuario_actual() or {}).get("id")


def _guardia():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede(URL):
        flash("!No tenés permiso para las campañas.")
        return redirect(url_for("menu"))
    return None


def _grupo_txt(cur, camp: dict) -> str:
    if camp["destino"] == "padron":
        atributos = {a["id"]: a["rotulo"] for a in camp_mod.atributos_activos(cur)}
        return "Padrón: " + camp_mod.describir_filtro(camp_mod._filtro_guardado(camp), atributos)
    if camp["destino"] == "adheridos":
        return "Adheridos " + (camp.get("convenio") or "")
    return camp_mod.DESTINOS.get(camp["destino"], camp["destino"])


@ben_ent_bp.route("/campanias/<int:id_camp>/entrega")
def entrega(id_camp):
    salida = _guardia()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            if not hay_esquema(cur):
                flash(f"!Falta correr {SQL_ESQUEMA}: sin esas tablas no hay padrón de entrega.")
                return redirect(url_for("ben_camp.ficha", id_camp=id_camp))
            camp = campania(cur, id_camp)
            if not camp:
                flash("!No existe esa campaña.")
                return redirect(url_for("ben_camp.lista"))
            filas = padron(cur, id_camp)
            movs = movimientos(cur, id_camp)
            stock = stock_movs(cur, id_camp)
            grupo = _grupo_txt(cur, camp)
    return render_template("beneficios/entrega.html", camp=camp, filas=filas, movs=movs, grupo=grupo, stock=stock,
                           solapa=request.args.get("solapa") or "padron")


@ben_ent_bp.route("/campanias/<int:id_camp>/entrega", methods=["POST"])
def accion(id_camp):
    salida = _guardia()
    if salida:
        return salida
    acc = request.form.get("accion")
    with get_connection() as conn:
        with conn.cursor() as cur:
            if not hay_esquema(cur):
                flash(f"!Falta correr {SQL_ESQUEMA}: sin esas tablas no hay padrón de entrega.")
                return redirect(url_for("ben_camp.ficha", id_camp=id_camp))
            camp = campania(cur, id_camp, bloquear=True)
            if not camp:
                flash("!No existe esa campaña.")
                return redirect(url_for("ben_camp.lista"))
            try:
                if acc == "generar":
                    n = generar(cur, camp, _uid())
                    flash(f"Padrón de entrega creado: {n} {'persona' if n == 1 else 'personas'}.")
                elif acc == "agregar":
                    r = agregar(cur, camp, request.form.get("numero"), request.form.get("motivo"), _uid())
                    flash(f"{r['nombre']} agregado al padrón de entrega con el número de orden {r['orden']}.{r['aviso']}")
                elif acc == "quitar":
                    nombre = quitar(cur, camp, request.form.get("id", type=int), request.form.get("motivo"), _uid())
                    flash(f"{nombre} quitado del padrón de entrega.")
                elif acc in ("stock", "fuera") and not camp["hay_stock"]:
                    raise ErrorEntrega(f"Falta correr {SQL_ESQUEMA_STOCK}: sin eso no hay stock ni entregas fuera del padrón.")
                elif acc == "stock":
                    n = cargar_stock(cur, camp, request.form.get("cantidad"), request.form.get("detalle"), _uid())
                    flash(f"Stock {'cargado' if n > 0 else 'ajustado'}: {'+' if n > 0 else ''}{n}. "
                          f"Quedan {camp['stock'] + n - camp['entregados']} para entregar.")
                elif acc == "fuera":
                    rn, rd = leer_retiro(request.form)
                    r = entregar_fuera(cur, camp, request.form.get("numero"), request.form.get("nombre"),
                                       request.form.get("motivo"), rn, rd, _uid())
                    flash(f"{r['nombre']}: retiro registrado fuera del padrón"
                          + (" (es afiliado: quedó agregado al padrón de entrega)." if r["afiliado"] else " (no afiliado)."))
                elif acc == "quitar_entrega":
                    nombre = quitar_entrega(cur, camp, request.form.get("id", type=int), request.form.get("motivo"), _uid())
                    flash(f"Se quitó el retiro de {nombre}.")
                else:
                    raise ErrorEntrega("Acción desconocida.")
                conn.commit()
            except ErrorEntrega as e:
                conn.rollback()
                flash("!" + str(e))
            except Exception:
                conn.rollback()
                raise
    return redirect(url_for("ben_ent.entrega", id_camp=id_camp))


def _fila_json(f: dict) -> dict:
    return {"id": f["id"], "orden": f["orden"], "nombre": f["apellido_nombres"], "entregado": bool(f["entregado"]),
            "fecha": f["fecha_entrega"].strftime("%d/%m/%Y %H:%M") if f.get("fecha_entrega") else None,
            "iso": f["fecha_entrega"].isoformat() if f.get("fecha_entrega") else "",
            "usuario": f.get("usuario_entrega") or "", "retiro_nombre": f.get("retiro_nombre") or "",
            "retiro_documento": f.get("retiro_documento") or ""}


@ben_ent_bp.route("/campanias/<int:id_camp>/entrega/api_entregar", methods=["POST"])
def api_entregar(id_camp):
    if not validasesion():
        return jsonify({"error": "La sesión venció: volvé a ingresar."}), 401
    if not puede(URL):
        return jsonify({"error": "No tenés permiso para las campañas."}), 403
    datos = request.get_json(silent=True) or {}
    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                camp = campania(cur, id_camp, bloquear=True)     # el stock: ver entregar()
                if not camp:
                    raise ErrorEntrega("No existe esa campaña.")
                nombre, doc = leer_retiro(datos)
                res = entregar(cur, camp, int(datos.get("id") or 0), nombre, doc, _uid())
                conn.commit()
            except ErrorEntrega as e:
                conn.rollback()
                return jsonify({"error": str(e)}), 409
            except Exception:
                conn.rollback()
                raise
            c2 = campania(cur, id_camp)
    return jsonify({"marcado": res["marcado"], "fila": _fila_json(res["fila"]),
                    "estado": {k: c2[k] for k in ("padron", "entregados", "faltan", "porc", "stock", "queda",
                                                  "controla_stock")}})
