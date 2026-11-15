"""
buscador.py — El buscador general de la barra superior (base.html).

El de gestion_adm (`/api/busqueda_rapida`, pedido del 15/11/2026): un solo
cuadro arriba que encuentra afiliados, empleadores y proveedores por CUIL o
CUIT, DNI o nombre, y lleva a su pantalla. Sin la consulta al padrón de ARCA
(acá no hay servicio A13) ni el salto a los aportes de un CUIL que no está en
el padrón (la base del gremio no tiene esa pantalla).

**Cada palabra tiene que estar.** «camila ali» encuentra a ALI CAMILA AILEN:
el apellido y los nombres van juntos en `apellido_nombres` y se tipean en
cualquier orden. Una palabra que es un número (puntos y guiones aparte) se
busca en el CUIL y el documento, o en el CUIT; así «27-41380797-8», «41.380.797»
o «ali 4138» funcionan.

**Solo lo que el usuario puede abrir.** Cada tipo lleva a una pantalla y el
permiso es la opción de menú (`db.puede`): sin ninguna de las dos del padrón no
se buscan afiliados, y así con el resto. El afiliado va a su ficha del ABM (o
de la consulta, si solo tiene esa); el empleador, a su ficha; el proveedor, a
su cuenta corriente (o a la ficha), como en gestion_adm.
"""

import re

from flask import Blueprint, jsonify, request, url_for

from db import get_connection, puede, validasesion

buscador_bp = Blueprint("buscador", __name__)

#: Resultados por tipo: el desplegable es para elegir, no para recorrer.
TOPE = {"afiliado": 12, "empleador": 8, "proveedor": 8}

#: Una palabra numérica: dígitos con puntos o guiones (un CUIL tipeado con su
#: formato). Tres dígitos como mínimo, si no «2» encuentra medio padrón.
_RE_NUMERO = re.compile(r"^[\d.\-]+$")


def palabras(q: str) -> tuple[list[str], list[str]]:
    """El texto en (palabras, números). Los números van sin puntos ni guiones;
    los de menos de tres dígitos se descartan."""
    textos, numeros = [], []
    for p in (q or "").split():
        if _RE_NUMERO.match(p):
            d = re.sub(r"\D", "", p)
            if len(d) >= 3:
                numeros.append(d)
        elif len(p) >= 2:
            textos.append(p)
    return textos, numeros


def _escapar_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _where(textos, numeros, cols_texto, cols_numero) -> tuple[str, list]:
    """Cada palabra en alguna de sus columnas (AND entre palabras)."""
    partes, params = [], []
    for t in textos:
        partes.append("(" + " OR ".join(f"{c} LIKE %s" for c in cols_texto) + ")")
        params += [f"%{_escapar_like(t)}%"] * len(cols_texto)
    for n in numeros:
        partes.append("(" + " OR ".join(f"{c} LIKE %s" for c in cols_numero) + ")")
        params += [f"%{n}%"] * len(cols_numero)
    return " AND ".join(partes), params


def _afiliados(cur, textos, numeros, exacto) -> list[dict]:
    if puede("/afiliados"):
        destino = lambda i: url_for("afiliados.abm_afiliados", edit=i)       # noqa: E731
    elif puede("/afiliados/padron"):
        destino = lambda i: url_for("afiliados.padron", ver=i)               # noqa: E731
    else:
        return []
    where, params = _where(textos, numeros, ["a.apellido_nombres"], ["a.cuil", "a.nro_documento"])
    cur.execute(f"""
        SELECT a.id_afiliado, a.apellido_nombres, a.cuil, a.nro_documento, a.cod_parentesco,
               p.descripcion AS parentesco, a.activo
          FROM p_afiliados a
          LEFT JOIN p_parentesco p ON p.codigo = a.cod_parentesco
         WHERE {where}
         ORDER BY (a.cuil = %s OR a.nro_documento = %s) DESC, a.activo DESC,
                  a.cod_parentesco <> 0, a.apellido_nombres
         LIMIT %s""", params + [exacto, exacto, TOPE["afiliado"]])
    return [{"tipo": "afiliado", "nombre": f["apellido_nombres"] or "(sin nombre)",
             "numero": f["cuil"] or "", "documento": f["nro_documento"] or "",
             "familiar": f["parentesco"] if f["cod_parentesco"] else "",
             "activo": bool(f["activo"]), "url": destino(f["id_afiliado"])}
            for f in cur.fetchall()]


def _empleadores(cur, textos, numeros, exacto) -> list[dict]:
    if not puede("/empleadores"):
        return []
    where, params = _where(textos, numeros, ["e.razon_social", "e.nombre_fantasia"],
                           ["CAST(e.CUIT AS CHAR)"])
    # `Activo` es bit(1): PyMySQL lo devuelve como bytes y b'\x00' es «verdadero».
    cur.execute(f"""
        SELECT e.id, e.CUIT, e.razon_social, e.nombre_fantasia, (e.Activo = 1) AS activo
          FROM p_empresas e
         WHERE {where}
         ORDER BY CAST(e.CUIT AS CHAR) = %s DESC, e.Activo = 1 DESC, e.razon_social
         LIMIT %s""", params + [exacto, TOPE["empleador"]])
    return [{"tipo": "empleador", "nombre": _con_fantasia(f["razon_social"], f["nombre_fantasia"])
             or str(f["CUIT"]),
             "numero": str(f["CUIT"]).zfill(11), "documento": "", "familiar": "",
             "activo": bool(f["activo"]), "url": url_for("empleadores.abm_empleadores", edit=f["id"])}
            for f in cur.fetchall()]


def _proveedores(cur, textos, numeros, exacto) -> list[dict]:
    if puede("/proveedores/cc"):
        destino = lambda i: url_for("cc_prov.estado_cuenta", id_proveedor=i)  # noqa: E731
    elif puede("/proveedores"):
        destino = lambda i: url_for("proveedores.abm", edit=i)                # noqa: E731
    else:
        return []
    where, params = _where(textos, numeros, ["p.razon_social", "p.nombre_fantasia"], ["p.cuit"])
    cur.execute(f"""
        SELECT p.id, p.cuit, p.razon_social, p.nombre_fantasia, p.activo
          FROM c_proveedores p
         WHERE {where}
         ORDER BY p.cuit = %s DESC, p.activo DESC, p.razon_social
         LIMIT %s""", params + [exacto, TOPE["proveedor"]])
    return [{"tipo": "proveedor", "nombre": _con_fantasia(f["razon_social"], f["nombre_fantasia"])
             or f["cuit"],
             "numero": f["cuit"] or "", "documento": "", "familiar": "",
             "activo": bool(f["activo"]), "url": destino(f["id"])}
            for f in cur.fetchall()]


def _con_fantasia(razon, fantasia) -> str:
    """El nombre de fantasía entre paréntesis, solo si dice algo distinto:
    mucha gente conoce a la empresa por ese y no por la razón social."""
    razon, fantasia = (razon or "").strip(), (fantasia or "").strip()
    if fantasia and fantasia.lower() != razon.lower():
        return f"{razon} ({fantasia})" if razon else fantasia
    return razon


@buscador_bp.route("/api/busqueda")
def buscar():
    """JSON para el buscador de la barra: {ok, resultados: [{tipo, nombre,
    numero, documento, familiar, activo, url}]}, afiliados primero."""
    if not validasesion():
        return jsonify({"ok": False, "error": "La sesión venció: volvé a ingresar."}), 401
    textos, numeros = palabras(request.args.get("q", ""))
    if not textos and not numeros:
        return jsonify({"ok": True, "resultados": []})
    # Un número solo y completo (un CUIL o un DNI tal cual): lo que coincide
    # entero va primero, antes que los que solo lo contienen.
    # None si no: comparar contra '' pondría primero a los que no tienen CUIL.
    exacto = numeros[0] if (len(numeros) == 1 and not textos) else None
    resultados = []
    with get_connection() as conn:
        with conn.cursor() as cur:
            resultados += _afiliados(cur, textos, numeros, exacto)
            resultados += _empleadores(cur, textos, numeros, exacto)
            resultados += _proveedores(cur, textos, numeros, exacto)
    return jsonify({"ok": True, "resultados": resultados})
