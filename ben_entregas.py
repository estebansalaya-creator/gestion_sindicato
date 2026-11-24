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

RETIRA POR LA EMPRESA (pedido del 24/11/2026, `ben_entrega_retiro`)
Con la grilla filtrada a una sola empresa (todas las filas que quedan tienen el
mismo empleador), aparece «Retira por la empresa»: muestra los que ya retiraron
de esa empresa (cuándo y quién) y los que faltan, tildados, y pide el nombre y
el DNI de quien viene a buscarlos. Registra de una vez el retiro de los tildados
(todo o nada: si otro puesto marcó a alguno en el medio, no graba nada), con el
mismo control de stock, y deja un `ben_entrega_retiro` cuyo id es el número de
la constancia. La constancia es un PDF con el detalle por duplicado (original y
duplicado, cada uno con las firmas de quien retira y de quien entrega); se
vuelve a imprimir desde la solapa «Retiros por empresa» o desde la fila. Quitar
el retiro de uno de esos afiliados lo saca de la constancia (el PDF lo avisa).

Permiso: el de Campañas (/beneficios/campanias). sql/beneficios_entregas_20261118.sql,
sql/beneficios_entregas_stock_20261118.sql y sql/beneficios_entregas_empresa_20261124.sql.

  /beneficios/campanias/<id>/entrega               el padrón de entrega; POST acciones
  /beneficios/campanias/<id>/entrega/api_entregar  «Marcar que retiró» (JSON)
  /beneficios/campanias/<id>/entrega/retiro/<n>/pdf  la constancia del retiro por la empresa
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
SQL_ESQUEMA_EMPRESA = "sql/beneficios_entregas_empresa_20261124.sql"
#: Tope de afiliados en un retiro por la empresa.
MAX_EMPRESA = 2000
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


def leer_retiro_empresa(datos: dict) -> tuple[str, str]:
    """(nombre, documento) de quien retira por la empresa: los dos obligatorios."""
    nombre = limpio(datos.get("retiro_nombre"), 150)
    doc = solo_digitos(datos.get("retiro_documento"))[:20]
    if not nombre or not doc:
        raise ErrorEntrega("Escribí el nombre y el DNI de quien retira por la empresa: van en la constancia.")
    if not 6 <= len(doc) <= 11:
        raise ErrorEntrega("El DNI de quien retira no parece válido (de 6 a 11 dígitos, sin puntos).")
    return nombre, doc


def leer_ids(valores) -> list[int]:
    """Las filas tildadas, sin repetir; enteros positivos."""
    ids = []
    for v in valores or []:
        try:
            n = int(str(v).strip())
        except ValueError:
            raise ErrorEntrega("Lo tildado no es válido: recargá la página.") from None
        if n > 0 and n not in ids:
            ids.append(n)
    if not ids:
        raise ErrorEntrega("No hay nadie tildado para retirar.")
    if len(ids) > MAX_EMPRESA:
        raise ErrorEntrega(f"Son demasiados de una vez (más de {MAX_EMPRESA}).")
    return ids


def control_empresa(filas: list[dict], ids: list[int]) -> str:
    """Que estén todas, ninguna retirada y de una sola empresa. Devuelve la empresa."""
    por_id = {f["id"]: f for f in filas}
    faltan = [i for i in ids if i not in por_id]
    if faltan:
        raise ErrorEntrega("Alguno ya no está en el padrón de entrega: recargá la página.")
    ya = [por_id[i] for i in ids if por_id[i]["entregado"]]
    if ya:
        nombres = ", ".join(f"{f['apellido_nombres']} ({f['fecha_entrega']:%H:%M})" if f.get("fecha_entrega")
                            else f["apellido_nombres"] for f in ya[:5])
        raise ErrorEntrega(f"Mientras tanto ya {'retiró' if len(ya) == 1 else 'retiraron'} {nombres}"
                           + ("…" if len(ya) > 5 else "") + ". No se registró nada: recargá y volvé a filtrar la empresa.")
    empresas = {(por_id[i].get("empleador") or "").strip() for i in ids}
    if len(empresas) != 1 or "" in empresas:
        raise ErrorEntrega("Lo tildado tiene que ser de una sola empresa.")
    return empresas.pop()


def control_stock_n(camp: dict, n: int) -> None:
    """Con stock cargado, que alcance para `n`."""
    if camp.get("controla_stock") and (camp.get("queda") or 0) < n:
        raise ErrorEntrega(f"No alcanza el stock: quedan {max(camp.get('queda') or 0, 0)} y son {n}. "
                           "Cargá más stock o destildá a algunos.")


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


def hay_empresa(cur) -> bool:
    """sql/beneficios_entregas_empresa_20261124.sql: el retiro por la empresa."""
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.columns WHERE table_schema = DATABASE()
                     AND table_name = 'ben_entrega' AND column_name = 'id_retiro'""")
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
        c["hay_empresa"] = hay_empresa(cur)
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
    cur.execute(f"""UPDATE ben_entrega SET entregado = 0, fecha_entrega = NULL, id_usuario_entrega = NULL,
                                          {"id_retiro = NULL," if camp.get("hay_empresa") else ""}
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


def entregar_empresa(cur, camp: dict, ids, nombre: str, doc: str, uid) -> dict:
    """El retiro por la empresa (ver el docstring). `camp` viene con FOR UPDATE."""
    ids = leer_ids(ids)
    cur.execute(f"""SELECT * FROM ben_entrega WHERE id_campania = %s
                      AND id IN ({', '.join(['%s'] * len(ids))}) FOR UPDATE""", [camp["id"], *ids])
    filas = cur.fetchall()
    empresa = control_empresa(filas, ids)
    control_stock_n(camp, len(ids))
    cur.execute("""INSERT INTO ben_entrega_retiro (id_campania, empleador, retiro_nombre, retiro_documento, cantidad, id_usuario)
                   VALUES (%s, %s, %s, %s, %s, %s)""", (camp["id"], empresa[:200], nombre, doc, len(ids), uid))
    id_retiro = cur.lastrowid
    cur.execute(f"""UPDATE ben_entrega SET entregado = 1, fecha_entrega = NOW(), id_usuario_entrega = %s,
                                           retiro_nombre = %s, retiro_documento = %s, id_retiro = %s
                     WHERE id_campania = %s AND entregado = 0 AND id IN ({', '.join(['%s'] * len(ids))})""",
                [uid, nombre, doc, id_retiro, camp["id"], *ids])
    if cur.rowcount != len(ids):
        raise ErrorEntrega("Otro puesto marcó a alguno en el medio. No se registró nada: recargá la página.")
    for f in sorted(filas, key=lambda x: x["orden"]):
        _mov(cur, camp["id"], f["id_afiliado"], "entrega",
             detalle_retiro(f["orden"], nombre, doc) + f" por la empresa {empresa}, constancia N° {id_retiro}", uid)
    return {"id": id_retiro, "empresa": empresa, "cantidad": len(ids)}


def retiros_empresa(cur, id_camp: int) -> list[dict]:
    if not hay_empresa(cur):
        return []
    cur.execute("""SELECT r.*, u.nombre AS usuario,
                          (SELECT COUNT(*) FROM ben_entrega e WHERE e.id_retiro = r.id) AS vigentes
                     FROM ben_entrega_retiro r LEFT JOIN s_usuarios u ON u.id = r.id_usuario
                    WHERE r.id_campania = %s ORDER BY r.fecha DESC, r.id DESC""", (id_camp,))
    return cur.fetchall()


def retiro_empresa(cur, id_camp: int, id_retiro: int) -> dict | None:
    cur.execute("""SELECT r.*, u.nombre AS usuario FROM ben_entrega_retiro r
                     LEFT JOIN s_usuarios u ON u.id = r.id_usuario
                    WHERE r.id = %s AND r.id_campania = %s""", (id_retiro, id_camp))
    r = cur.fetchone()
    if r:
        cur.execute("""SELECT * FROM ben_entrega WHERE id_retiro = %s ORDER BY apellido_nombres, orden""", (id_retiro,))
        r["filas"] = cur.fetchall()
    return r


def constancia_pdf(camp: dict, r: dict):
    """La constancia del retiro por la empresa: original y duplicado, cada uno con sus firmas."""
    import pagos_pdf as P
    from reportlab.lib.units import cm
    from reportlab.platypus import KeepTogether, PageBreak, Spacer, Table, TableStyle

    numero = f"N° {r['id']:06d}"
    titulo = "Constancia de retiro"
    filas = r["filas"]
    n = len(filas)

    def cuerpo(doc):
        doc.story.append(doc.P(
            f"El {r['fecha']:%d/%m/%Y} a las {r['fecha']:%H:%M}, <b>{P._txt(r['retiro_nombre'])}</b> "
            f"(DNI {P._txt(r['retiro_documento'])}), en representación de <b>{P._txt(r['empleador'])}</b>, retira "
            f"<b>{n} {'beneficio' if n == 1 else 'beneficios'}</b> de la campaña <b>«{P._txt(camp['titulo'])}»</b> "
            f"para {'el afiliado que se detalla' if n == 1 else 'los afiliados que se detallan'}, y se compromete a "
            f"entregárselos.", fontSize=10, leading=15, spaceAfter=10))
        doc.datos("RETIRO", [("Campaña", P._txt(camp["titulo"])), ("Fecha y hora", f"{r['fecha']:%d/%m/%Y %H:%M}"),
                             ("Empresa", P._txt(r["empleador"])), ("Retira", P._txt(r["retiro_nombre"])),
                             ("DNI", P._txt(r["retiro_documento"])), ("Cantidad", str(n)),
                             ("Registró", P._txt(r.get("usuario")))])
        if n != r["cantidad"]:
            doc.story.append(doc.P(
                f"<b>Aviso:</b> al registrarlo fueron {r['cantidad']}; después se quitó el retiro de "
                f"{r['cantidad'] - n}. El detalle muestra los que siguen retirados.",
                fontSize=8.5, textColor=doc.RED, spaceAfter=8))
        doc.tabla("DETALLE", ["#", "Orden", "Apellido y nombres", "Documento", "CUIL", "Parentesco"],
                  [[str(i), str(f["orden"]), P._txt(f["apellido_nombres"]), P._txt(f["nro_documento"]) or "—",
                    P._cuit(f["cuil"]) if f.get("cuil") else "—",
                    "Titular" if f.get("cod_parentesco") == 0 else (P._txt(f.get("parentesco")) or "—")]
                   for i, f in enumerate(filas, 1)],
                  [0.9, 1.3, 6.2, 2.4, 2.8, 2.4], derecha=(0, 1))
        firmas = Table([["", "", ""],
                        [doc.P("Firma de quien retira", alignment=1), "", doc.P("Entregó (por el sindicato)", alignment=1)],
                        [doc.P(f"Aclaración: {P._txt(r['retiro_nombre'])}", alignment=1, fontSize=8), "",
                         doc.P("Aclaración:", alignment=1, fontSize=8)],
                        [doc.P(f"DNI {P._txt(r['retiro_documento'])}", alignment=1, fontSize=8), "", ""]],
                       colWidths=[7 * cm, 2 * cm, 7 * cm], rowHeights=[1.6 * cm, None, None, None])
        firmas.setStyle(TableStyle([("LINEABOVE", (0, 1), (0, 1), 0.6, doc.MUTED),
                                    ("LINEABOVE", (2, 1), (2, 1), 0.6, doc.MUTED)]))
        doc.story.append(KeepTogether([Spacer(1, 0.8 * cm), firmas]))

    doc = P._Doc(titulo, numero, "ORIGINAL")
    cuerpo(doc)
    doc.story.append(PageBreak())
    doc._membrete(titulo, numero, "DUPLICADO")
    cuerpo(doc)
    nombre = f"Constancia de retiro {r['id']:06d}"
    return P.respuesta(doc.pdf(f"{titulo} {numero}"), nombre + ".pdf")


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
            retiros = retiros_empresa(cur, id_camp)
            grupo = _grupo_txt(cur, camp)
    nuevo = next((r for r in retiros if r["id"] == request.args.get("retiro", type=int)), None)
    return render_template("beneficios/entrega.html", camp=camp, filas=filas, movs=movs, grupo=grupo, stock=stock,
                           retiros=retiros, retiro_nuevo=nuevo, solapa=request.args.get("solapa") or "padron")


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
                elif acc == "empresa":
                    if not camp["hay_empresa"]:
                        raise ErrorEntrega(f"Falta correr {SQL_ESQUEMA_EMPRESA}: sin eso no hay retiro por la empresa.")
                    rn, rd = leer_retiro_empresa(request.form)
                    r = entregar_empresa(cur, camp, request.form.getlist("ids"), rn, rd, _uid())
                    conn.commit()
                    flash(f"{r['empresa']}: {rn} retiró {r['cantidad']} "
                          f"{'beneficio' if r['cantidad'] == 1 else 'beneficios'}. Constancia N° {r['id']:06d}: "
                          "imprimila por duplicado para que la firme.")
                    return redirect(url_for("ben_ent.entrega", id_camp=id_camp, retiro=r["id"]))
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


@ben_ent_bp.route("/campanias/<int:id_camp>/entrega/retiro/<int:id_retiro>/pdf")
def retiro_pdf(id_camp, id_retiro):
    salida = _guardia()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            if not hay_esquema(cur) or not hay_empresa(cur):
                flash(f"!Falta correr {SQL_ESQUEMA_EMPRESA}.")
                return redirect(url_for("ben_ent.entrega", id_camp=id_camp))
            camp = campania(cur, id_camp)
            r = retiro_empresa(cur, id_camp, id_retiro) if camp else None
    if not r:
        flash("!No existe esa constancia de retiro.")
        return redirect(url_for("ben_ent.entrega", id_camp=id_camp))
    return constancia_pdf(camp, r)


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
