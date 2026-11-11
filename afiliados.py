"""
afiliados.py — ABM del padrón de afiliados (`p_afiliados`).

Sigue al ABM de empleadores en estructura y en pantalla: solapas Listado y
Datos, edición por `?edit=<id>`, formulario en grilla de 12 columnas. Lo que
agrega es lo que un afiliado tiene y una empresa no:

- **Grupo familiar.** Titular y familiares comparten `cuil_titular`. La ficha
  muestra el grupo entero y permite agregar un familiar con el titular y el
  domicilio ya cargados (`?familiar_de=<CUIL del titular>`).
- **Baja lógica, nunca DELETE.** De `p_afiliados` cuelgan por FK reintegros,
  comprobantes y la auditoría, y la baja de una persona es un dato del padrón,
  no un error que se borra. Lleva fecha y motivo (`p_motivo_movimiento`); la
  de un titular ofrece arrastrar a su grupo.
- **Auditoría.** Cada cambio deja una fila por campo en
  `p_afiliados_movimientos`, con usuario y fecha. Es la solapa «Movimientos».
- **Atributos.** Las marcas activas de `p_afiliado_atributo` se tildan en la
  ficha. La «AEDA — Afiliado al Gremio» que vino de la obra social está
  desactivada: en la base del gremio todos lo son.
- **Contactos**, con el mismo parcial que empleadores (entidad `afiliado`).
- **Empleadores.** El historial de `p_relaciones_laborales`, con período desde
  y hasta. El empleador de la ficha es el de la relación vigente: se cambia en
  la solapa, no en el formulario, para que no haya dos lugares que digan cosas
  distintas. En el alta sí se carga, y nace la primera relación.
- **Documentación** adjunta, con el parcial de documentacion.py.

**Dos opciones de menú, una pantalla.** «Consulta del padrón»
(`/afiliados/padron?ver=ID`) es de solo lectura; «ABM de afiliados»
(`/afiliados?edit=ID`) modifica. El permiso es la opción de menú (`db.puede`):
quien tiene el ABM ve en la consulta los botones para editar, y quien no lo
tiene y entra a /afiliados por URL termina en la consulta. El control está en
el servidor, en cada GET y POST del ABM; esconder los botones es solo la parte
visible.

Los datos vienen de AEDA por `importar_aeda_afiliados.py`. Apellido y nombres
van juntos en un solo campo, `apellido_nombres`, como los guarda AEDA: no hay
regla que los separe bien (falla con los apellidos compuestos), y dos campos
que nadie separaba solo confundían (`sql/afiliados_apellido_nombres_20261110.sql`).
"""

import logging
from datetime import date

from flask import (Blueprint, render_template, request, redirect, url_for,
                   session, flash, jsonify, send_file)

import contactos as _contactos
import documentacion as _doc
from db import get_connection, puede, validasesion
from empleadores import cuit_valido     # CUIL y CUIT comparten el dígito verificador

log = logging.getLogger(__name__)

afiliados_bp = Blueprint("afiliados", __name__, template_folder="templates")

TITULAR = 0
ARGENTINA = 12

#: Columna → etiqueta, en el orden del formulario. Es a la vez lo que el
#: formulario edita y lo que la auditoría compara: si una columna se agrega al
#: formulario y no acá, se guarda sin dejar rastro.
CAMPOS = {
    "cuil":                       "CUIL",
    "cod_parentesco":             "Parentesco",
    "cuil_titular":               "CUIL del titular",
    "tipo_documento":             "Tipo de documento",
    "nro_documento":              "Documento",
    "apellido_nombres":           "Apellido y nombres",
    "sexo":                       "Sexo",
    "fecha_nacimiento":           "Fecha de nacimiento",
    "estado_civil":               "Estado civil",
    "nacionalidad":               "Nacionalidad",
    "cuit_empleador":             "Empleador",
    "domicilio_calle":            "Calle",
    "domicilio_numero":           "Número",
    "domicilio_piso":             "Piso",
    "domicilio_depto":            "Depto",
    "localidad":                  "Localidad",
    "codigo_postal":              "Código postal",
    "provincia":                  "Provincia",
    "cbu_pago":                   "CBU",
    "incapacidad":                "Discapacidad",
    "fecha_alta":                 "Fecha de alta",
    "fecha_certificado_estudios": "Certificado de estudios",
    "observaciones":              "Observaciones",
}

#: Los cambia la baja o la reactivación, nunca el formulario.
CAMPOS_ESTADO = {
    "activo":         "Activo",
    "fecha_baja":     "Fecha de baja",
    "id_motivo_baja": "Motivo de baja",
}

#: Al cargar un familiar se copia el domicilio del titular: casi siempre es el
#: mismo, y reescribirlo es donde aparecen las diferencias de tipeo.
CAMPOS_DOMICILIO = ["domicilio_calle", "domicilio_numero", "domicilio_piso",
                    "domicilio_depto", "localidad", "codigo_postal", "provincia"]


# ─────────────────────────────────────────────────────────────────────────────
# Validaciones
# ─────────────────────────────────────────────────────────────────────────────

def digitos(valor) -> str:
    return "".join(c for c in (valor or "") if c.isdigit())


def cbu_valido(cbu: str) -> bool:
    """
    Los dos dígitos verificadores del CBU: uno cierra el bloque de banco y
    sucursal (8 dígitos), el otro el de la cuenta (14). Igual que con el CUIT,
    no prueba que la cuenta exista, pero frena el error de tipeo, que en un CBU
    se descubre recién cuando rebota la transferencia.
    """
    if len(cbu) != 22 or not cbu.isdigit():
        return False

    def cierra(bloque: str, pesos) -> bool:
        suma = sum(int(d) * p for d, p in zip(bloque[:-1], pesos))
        return (10 - suma % 10) % 10 == int(bloque[-1])

    return (cierra(cbu[:8], (7, 1, 3, 9, 7, 1, 3))
            and cierra(cbu[8:], (3, 9, 7, 1, 3, 9, 7, 1, 3, 9, 7, 1, 3)))


def _fecha_form(valor, etiqueta, errores) -> date | None:
    valor = (valor or "").strip()
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        errores.append(f"{etiqueta}: «{valor}» no es una fecha.")
        return None


def _datos_del_form(form, errores) -> dict:
    def txt(nombre, largo):
        return (form.get(nombre) or "").strip()[:largo] or None

    def num(nombre):
        v = (form.get(nombre) or "").strip()
        return int(v) if v.isdigit() else None

    sexo = form.get("sexo")
    return {
        # Se aceptan guiones y puntos al pegar desde una constancia de CUIL.
        "cuil":                       digitos(form.get("cuil")) or None,
        "cod_parentesco":             num("cod_parentesco"),
        "cuil_titular":               digitos(form.get("cuil_titular")) or None,
        "tipo_documento":             txt("tipo_documento", 2),
        "nro_documento":              digitos(form.get("nro_documento")),
        # Sin espacios de más: «PEREZ  JUAN» y «PEREZ JUAN» son la misma
        # persona al buscar.
        "apellido_nombres":           " ".join((form.get("apellido_nombres") or "").split())[:100]
                                      or None,
        "sexo":                       sexo if sexo in ("M", "F", "X") else None,
        "fecha_nacimiento":           _fecha_form(form.get("fecha_nacimiento"),
                                                  "Fecha de nacimiento", errores),
        "estado_civil":               num("estado_civil"),
        "nacionalidad":               num("nacionalidad"),
        "cuit_empleador":             digitos(form.get("cuit_empleador")) or None,
        "domicilio_calle":            txt("domicilio_calle", 100),
        "domicilio_numero":           txt("domicilio_numero", 5),
        "domicilio_piso":             txt("domicilio_piso", 4),
        "domicilio_depto":            txt("domicilio_depto", 4),
        "localidad":                  txt("localidad", 20),
        "codigo_postal":              txt("codigo_postal", 8),
        "provincia":                  num("provincia"),
        "cbu_pago":                   digitos(form.get("cbu_pago")) or None,
        "incapacidad":                1 if form.get("incapacidad") else 0,
        "fecha_alta":                 _fecha_form(form.get("fecha_alta"),
                                                  "Fecha de alta", errores),
        "fecha_certificado_estudios": _fecha_form(form.get("fecha_certificado_estudios"),
                                                  "Certificado de estudios", errores),
        "observaciones":              (form.get("observaciones") or "").strip() or None,
    }


def _validar(cur, d: dict, antes: dict | None, cat: dict, errores: list[str]):
    """Valida y completa `d` en el lugar. `antes` es la ficha guardada, o None en el alta."""
    id_actual = antes["id_afiliado"] if antes else 0

    if not d["apellido_nombres"]:
        errores.append("Falta el apellido y nombres.")
    if d["cod_parentesco"] not in cat["codigos_parentesco"]:
        errores.append("Elegí el parentesco.")

    if d["cuil"]:
        if len(d["cuil"]) != 11 or not cuit_valido(d["cuil"]):
            errores.append(f"El CUIL {d['cuil']} no es válido: no verifica el dígito de "
                           "control. Revisá que no falte ni sobre un número.")
        else:
            cur.execute("SELECT apellido_nombres FROM p_afiliados "
                        "WHERE cuil = %s AND id_afiliado <> %s", (d["cuil"], id_actual))
            otro = cur.fetchone()
            if otro:
                errores.append(f"El CUIL {d['cuil']} ya es de «{otro['apellido_nombres']}».")

    if d["cod_parentesco"] == TITULAR:
        if not d["cuil"]:
            errores.append("El titular necesita CUIL: es lo que agrupa a su familia.")
        d["cuil_titular"] = d["cuil"]
    else:
        ct = d["cuil_titular"]
        if not ct:
            errores.append("Falta el CUIL del titular del grupo.")
        elif len(ct) != 11 or not cuit_valido(ct):
            errores.append(f"El CUIL del titular {ct} no es válido.")
        elif ct == d["cuil"]:
            errores.append("Un familiar no puede ser su propio titular. Si es titular, "
                           "elegí el parentesco «Titular».")
        elif antes is None or antes["cuil_titular"] != ct:
            # Solo cuando cambia: hay familiares importados de AEDA cuyo titular
            # no está, y exigirlo siempre impediría corregirles un teléfono.
            cur.execute("SELECT 1 FROM p_afiliados WHERE cuil = %s AND cod_parentesco = 0",
                        (ct,))
            if not cur.fetchone():
                errores.append(f"No hay un titular con CUIL {ct}. Cargá primero al titular.")

    # Dejar de ser titular con familiares colgados deja al grupo sin cabeza.
    if antes and antes["cod_parentesco"] == TITULAR and d["cod_parentesco"] != TITULAR:
        cur.execute("SELECT COUNT(*) AS n FROM p_afiliados "
                    "WHERE cuil_titular = %s AND id_afiliado <> %s", (antes["cuil"], id_actual))
        n = cur.fetchone()["n"]
        if n:
            errores.append(f"Es titular de un grupo con {n} familiar(es). Para que pase "
                           "a ser familiar, primero hay que mover a su grupo.")

    if not d["nro_documento"] and d["cuil"] and len(d["cuil"]) == 11:
        d["nro_documento"] = d["cuil"][2:10]
    if len(d["nro_documento"]) > 8:
        errores.append("El documento tiene más de 8 dígitos.")
    if d["cbu_pago"] and not cbu_valido(d["cbu_pago"]):
        errores.append(f"El CBU {d['cbu_pago']} no es válido: no cierran sus dígitos "
                       "verificadores.")
    if d["cuit_empleador"] and (len(d["cuit_empleador"]) != 11
                                or not cuit_valido(d["cuit_empleador"])):
        errores.append(f"El CUIT del empleador {d['cuit_empleador']} no es válido.")
    elif d["cuit_empleador"] and antes is None:
        # En el alta el empleador abre el historial: tiene que estar en el
        # padrón de empleadores y la relación se ata al CUIL.
        cur.execute("SELECT 1 FROM p_empresas WHERE CUIT = %s", (d["cuit_empleador"],))
        if not cur.fetchone():
            errores.append(f"El CUIT {d['cuit_empleador']} no está en el padrón de empleadores: "
                           "cargalo primero en Empleadores.")
        if not d["cuil"]:
            errores.append("Para registrar el empleador hace falta el CUIL del afiliado.")
    if d["fecha_nacimiento"] and d["fecha_nacimiento"] > date.today():
        errores.append("La fecha de nacimiento es posterior a hoy.")


# ─────────────────────────────────────────────────────────────────────────────
# Auditoría
# ─────────────────────────────────────────────────────────────────────────────

def _usuario() -> str:
    return (session.get("sind_usuario_email") or session.get("sind_usuario_nombre")
            or "desconocido")[:80]


def _texto(valor) -> str | None:
    """Forma comparable de un valor: dos None, '' y 0 de un checkbox no son lo mismo."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, date):
        return valor.isoformat()
    return str(valor)


def _legible(campo: str, valor, cat: dict) -> str | None:
    """
    El valor como lo entiende una persona: «3 · Hijo soltero…» y no «3».

    Se guarda así y no el código pelado porque el catálogo puede cambiar de
    descripción mañana, y la auditoría tiene que decir lo que se vio hoy.
    """
    if valor is None or valor == "":
        return None
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    if campo in ("incapacidad", "activo"):
        return "sí" if int(valor) else "no"
    mapa = cat["etiquetas"].get(campo)
    if mapa is not None:
        desc = mapa.get(str(valor))
        return f"{valor} · {desc}" if desc else str(valor)
    return str(valor)[:255]


def _registrar(cur, id_afiliado, cuil, antes: dict, despues: dict, campos: dict,
               tipo: str, cat: dict, vigencia=None, observaciones=None) -> int:
    """Una fila de `p_afiliados_movimientos` por cada campo de `campos` que cambió."""
    filas = []
    for col, etiqueta in campos.items():
        if _texto(antes.get(col)) == _texto(despues.get(col)):
            continue
        filas.append((
            id_afiliado, cuil, vigencia,
            "CAMBIO_CUIL" if (col == "cuil" and tipo == "MODIFICACION") else tipo,
            col, etiqueta,
            _legible(col, antes.get(col), cat), _legible(col, despues.get(col), cat),
            _usuario(), observaciones,
        ))
    if filas:
        cur.executemany("""
            INSERT INTO p_afiliados_movimientos
                (id_afiliado, cuil, fecha_vigencia, tipo_movimiento, origen, origen_ref,
                 campo, campo_label, valor_anterior, valor_actual, usuario, observaciones)
            VALUES (%s, %s, %s, %s, 'MANUAL', 'ABM de afiliados', %s, %s, %s, %s, %s, %s)
        """, filas)
    return len(filas)


# ─────────────────────────────────────────────────────────────────────────────
# Lecturas
# ─────────────────────────────────────────────────────────────────────────────

def _catalogos(cur) -> dict:
    cat = {}
    cur.execute("SELECT codigo, descripcion FROM p_parentesco ORDER BY codigo")
    cat["parentescos"] = cur.fetchall()
    cur.execute("SELECT codigo, descripcion FROM p_tipo_documento "
                "ORDER BY codigo = 'DU' DESC, descripcion")
    cat["tipos_doc"] = cur.fetchall()
    cur.execute("SELECT codigo, descripcion FROM p_estado_civil ORDER BY codigo")
    cat["estados_civiles"] = cur.fetchall()
    cur.execute("SELECT codigo, descripcion FROM p_nacionalidad "
                "ORDER BY codigo = 12 DESC, descripcion")
    cat["nacionalidades"] = cur.fetchall()
    cur.execute("SELECT codigo, nombre FROM p_provincia ORDER BY nombre")
    cat["provincias"] = cur.fetchall()
    cur.execute("SELECT id, nombre FROM p_motivo_movimiento "
                "WHERE activo = 1 AND es_alta = 0 ORDER BY nombre")
    cat["motivos_baja"] = cur.fetchall()
    cur.execute("SELECT id, nombre FROM p_motivo_movimiento")
    motivos_todos = cur.fetchall()
    cur.execute("SELECT id, rotulo, descripcion FROM p_afiliado_atributo "
                "WHERE activo = 1 ORDER BY id")
    cat["atributos"] = cur.fetchall()

    cat["codigos_parentesco"] = {p["codigo"] for p in cat["parentescos"]}
    cat["etiquetas"] = {
        "cod_parentesco": {str(p["codigo"]): p["descripcion"] for p in cat["parentescos"]},
        "tipo_documento": {p["codigo"]: p["descripcion"] for p in cat["tipos_doc"]},
        "estado_civil":   {str(p["codigo"]): p["descripcion"] for p in cat["estados_civiles"]},
        "nacionalidad":   {str(p["codigo"]): p["descripcion"] for p in cat["nacionalidades"]},
        "provincia":      {str(p["codigo"]): p["nombre"] for p in cat["provincias"]},
        "id_motivo_baja": {str(m["id"]): m["nombre"] for m in motivos_todos},
    }
    return cat


def _afiliado(cur, id_afiliado) -> dict | None:
    columnas = ", ".join(["id_afiliado"] + list(CAMPOS) + list(CAMPOS_ESTADO))
    cur.execute(f"SELECT {columnas} FROM p_afiliados WHERE id_afiliado = %s", (id_afiliado,))
    return cur.fetchone()


def _atributos_de(cur, id_afiliado) -> set[int]:
    cur.execute("SELECT id_atributo FROM p_atributos_por_afiliado WHERE id_afiliado = %s",
                (id_afiliado,))
    return {f["id_atributo"] for f in cur.fetchall()}


def _guardar_atributos(cur, id_afiliado, cuil, elegidos: set[int], cat: dict) -> int:
    """Sincroniza las marcas tildadas y deja cada cambio en la auditoría."""
    actuales = _atributos_de(cur, id_afiliado)
    rotulos = {a["id"]: a["rotulo"] for a in cat["atributos"]}
    elegidos &= set(rotulos)    # un id inventado en el POST no entra
    cambios = 0
    for id_atr in elegidos - actuales:
        cur.execute("INSERT INTO p_atributos_por_afiliado (id_atributo, id_afiliado, usuario) "
                    "VALUES (%s, %s, %s)", (id_atr, id_afiliado, _usuario()[:60]))
        cambios += _registrar(cur, id_afiliado, cuil, {"a": "no"}, {"a": "sí"},
                              {"a": f"Atributo {rotulos[id_atr]}"}, "MODIFICACION", cat)
    for id_atr in (actuales - elegidos) & set(rotulos):
        cur.execute("DELETE FROM p_atributos_por_afiliado "
                    "WHERE id_atributo = %s AND id_afiliado = %s", (id_atr, id_afiliado))
        cambios += _registrar(cur, id_afiliado, cuil, {"a": "sí"}, {"a": "no"},
                              {"a": f"Atributo {rotulos[id_atr]}"}, "MODIFICACION", cat)
    return cambios


# ─────────────────────────────────────────────────────────────────────────────
# Historial de empleadores (p_relaciones_laborales)
# ─────────────────────────────────────────────────────────────────────────────

def _vigente(r: dict, hoy: date | None = None) -> bool:
    """
    Vigente: activa y sin egreso, o con egreso de hoy en adelante. Se mira la
    fecha y no solo `estado`: una relación cargada con egreso futuro deja de
    estar vigente sola cuando llega el día.
    """
    hoy = hoy or date.today()
    return r["estado"] == "activa" and (r["fecha_fin"] is None or r["fecha_fin"] >= hoy)


def _relaciones(cur, cuil) -> list[dict]:
    """El historial de una persona: las vigentes primero, después de la más nueva a la más vieja."""
    if not cuil:
        return []
    # La razón social por id y, si la relación vino de AEDA sin id (una
    # empresa que todavía no estaba en el padrón), por CUIT.
    cur.execute("""
        SELECT r.id_relacion, r.cuit_empleador, r.fecha_inicio, r.fecha_fin, r.categoria,
               r.estado, r.observaciones,
               COALESCE(e1.razon_social, e2.razon_social) AS razon_social,
               COALESCE(e1.id, e2.id) AS id_empresa
          FROM p_relaciones_laborales r
          LEFT JOIN p_empresas e1 ON e1.id = r.id_empleador
          LEFT JOIN p_empresas e2 ON r.id_empleador IS NULL
                                 AND r.cuit_empleador REGEXP '^[0-9]+$'
                                 AND e2.CUIT = CAST(r.cuit_empleador AS UNSIGNED)
         WHERE r.cuil = %s
    """, (cuil,))
    hoy = date.today()
    # list(): sin filas, PyMySQL devuelve una tupla vacía, que no se ordena.
    filas = list(cur.fetchall())
    for f in filas:
        f["vigente"] = _vigente(f, hoy)
    filas.sort(key=lambda f: (not f["vigente"], -(f["fecha_inicio"] or date.min).toordinal(),
                              -f["id_relacion"]))
    return filas


def _texto_relacion(r: dict) -> str:
    """Una relación como la lee una persona: así queda en la auditoría."""
    partes = [f"{r['cuit_empleador']} {r.get('razon_social') or '(no está en el padrón)'}",
              "desde " + (r["fecha_inicio"].strftime("%d/%m/%Y") if r["fecha_inicio"] else "?")]
    if r["fecha_fin"]:
        partes.append("hasta " + r["fecha_fin"].strftime("%d/%m/%Y"))
    if r.get("categoria"):
        partes.append(r["categoria"])
    return " · ".join(partes)[:255]


def _se_superponen(d1, h1, d2, h2) -> bool:
    """Dos períodos se pisan. Sin desde es «desde siempre»; sin hasta, «hasta hoy y después»."""
    return (d1 or date.min) <= (h2 or date.max) and (d2 or date.min) <= (h1 or date.max)


def _relacion_del_form(cur, form, antes: dict | None, otras: list[dict],
                       errores: list[str]) -> dict:
    cuit = digitos(form.get("rel_cuit"))
    empresa = None
    if not cuit:
        errores.append("Falta el CUIT del empleador.")
    elif len(cuit) != 11 or not cuit_valido(cuit):
        errores.append(f"El CUIT {cuit} no es válido.")
    else:
        cur.execute("SELECT id, razon_social FROM p_empresas WHERE CUIT = %s", (cuit,))
        empresa = cur.fetchone()
        if not empresa:
            errores.append(f"El CUIT {cuit} no está en el padrón de empleadores: "
                           "cargalo primero en Empleadores.")

    desde = _fecha_form(form.get("rel_desde"), "Desde", errores)
    hasta = _fecha_form(form.get("rel_hasta"), "Hasta", errores)
    # Las de AEDA sin fecha de ingreso (411) se pueden seguir editando sin
    # inventarles una; una nueva, no.
    if not desde and not (antes and antes["fecha_inicio"] is None):
        errores.append("Falta la fecha desde.")
    if desde and desde > date.today():
        errores.append("La fecha desde es posterior a hoy.")
    if desde and hasta and hasta < desde:
        errores.append("La fecha hasta es anterior a la fecha desde.")
    for o in otras:
        if empresa and o["cuit_empleador"] == cuit and _se_superponen(
                desde, hasta, o["fecha_inicio"], o["fecha_fin"]):
            errores.append(f"Ya hay una relación con {empresa['razon_social']} en ese período "
                           f"({_texto_relacion(o)}).")
            break

    hoy = date.today()
    if hasta:
        estado = "activa" if hasta >= hoy else "inactiva"
    else:
        # Sin egreso: las que vinieron inactivas de AEDA siguen así hasta que
        # alguien les ponga la fecha; una nueva sin egreso está vigente.
        estado = "inactiva" if (antes and antes["estado"] == "inactiva") else "activa"
    return {"cuit_empleador": cuit, "id_empleador": empresa["id"] if empresa else None,
            "razon_social": empresa["razon_social"] if empresa else None,
            "fecha_inicio": desde, "fecha_fin": hasta, "estado": estado,
            "categoria": (form.get("rel_categoria") or "").strip()[:60] or None,
            "observaciones": (form.get("rel_observaciones") or "").strip()[:255] or None}


def _sincronizar_empleador(cur, af: dict, cat: dict):
    """El empleador de la ficha pasa a ser el de la relación vigente más nueva, o ninguno."""
    cur.execute("""SELECT cuit_empleador FROM p_relaciones_laborales
                    WHERE cuil = %s AND estado = 'activa'
                      AND (fecha_fin IS NULL OR fecha_fin >= CURDATE())
                    ORDER BY fecha_inicio IS NULL, fecha_inicio DESC, id_relacion DESC
                    LIMIT 1""", (af["cuil"],))
    f = cur.fetchone()
    nuevo = f["cuit_empleador"] if f else None
    if (af["cuit_empleador"] or None) != nuevo:
        cur.execute("UPDATE p_afiliados SET cuit_empleador = %s WHERE id_afiliado = %s",
                    (nuevo, af["id_afiliado"]))
        _registrar(cur, af["id_afiliado"], af["cuil"], {"cuit_empleador": af["cuit_empleador"]},
                   {"cuit_empleador": nuevo}, {"cuit_empleador": "Empleador"}, "MODIFICACION", cat,
                   observaciones="El empleador vigente del historial")


# ─────────────────────────────────────────────────────────────────────────────
# Rutas
# ─────────────────────────────────────────────────────────────────────────────

@afiliados_bp.route("/afiliados/empleador")
def buscar_empleador():
    """Razón social de un CUIT, para mostrarla debajo del campo mientras se tipea."""
    if not validasesion():
        return jsonify({"error": "sesión vencida"}), 401
    cuit = digitos(request.args.get("cuit"))
    if len(cuit) != 11:
        return jsonify({})
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, razon_social FROM p_empresas WHERE CUIT = %s", (cuit,))
            return jsonify(cur.fetchone() or {})


def puede_abm() -> bool:
    return puede(url_for("afiliados.abm_afiliados"))


def puede_consulta() -> bool:
    # El ABM incluye la consulta: quien puede modificar el padrón puede verlo.
    return puede(url_for("afiliados.padron")) or puede_abm()


@afiliados_bp.route("/afiliados/padron")
def padron():
    """Consulta del padrón: listado y ficha, sin modificar nada."""
    if not validasesion():
        return redirect(url_for("login"))
    if not puede_consulta():
        flash("!No tenés permiso para consultar el padrón.")
        return redirect(url_for("menu"))
    return _pantalla(None, set(), [], modo="consulta")


@afiliados_bp.route("/afiliados", methods=["GET", "POST"])
def abm_afiliados():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede_abm():
        # A la consulta y no a un error: quien llegó con un link del ABM igual
        # puede ver la ficha que buscaba.
        id_af = request.args.get("edit") or request.form.get("id") or None
        if not puede_consulta():
            flash("!No tenés permiso para el padrón de afiliados.")
            return redirect(url_for("menu"))
        flash("!No tenés permiso para modificar el padrón: se abrió la consulta.")
        return redirect(url_for("afiliados.padron", ver=id_af))

    errores: list[str] = []
    afiliado = None
    atributos_sel: set[int] = set()

    if request.method == "POST":
        accion = request.form.get("accion", "")
        id_af = int(request.form.get("id") or 0)

        if accion in ("baja", "reactivar") and id_af:
            return _cambiar_estado(accion, id_af)

        if accion in ("nuevo", "guardar"):
            with get_connection() as conn:
                conn.begin()        # todo o nada: ficha, grupo, atributos y auditoría
                try:
                    with conn.cursor() as cur:
                        cat = _catalogos(cur)
                        antes = _afiliado(cur, id_af) if accion == "guardar" else None
                        if accion == "guardar" and antes is None:
                            conn.rollback()
                            flash("Ese afiliado no existe.")
                            return redirect(url_for("afiliados.abm_afiliados"))

                        d = _datos_del_form(request.form, errores)
                        if antes is not None:
                            # El empleador de una ficha existente lo maneja
                            # la solapa Empleadores, no el formulario.
                            d["cuit_empleador"] = antes["cuit_empleador"]
                        _validar(cur, d, antes, cat, errores)
                        elegidos = {int(x) for x in request.form.getlist("atributos")
                                    if x.isdigit()}

                        if not errores:
                            if antes is None:
                                id_af = _insertar(cur, d, cat)
                                flash(f"Afiliado «{d['apellido_nombres']}» creado.")
                            else:
                                _actualizar(cur, antes, d, cat)
                                flash("Cambios guardados.")
                            _guardar_atributos(cur, id_af, d["cuil"], elegidos, cat)
                            conn.commit()
                            return redirect(url_for("afiliados.abm_afiliados", edit=id_af))
                        conn.rollback()
                except Exception:
                    conn.rollback()
                    raise

            # Con errores se devuelve lo tipeado, no lo guardado: perder una
            # ficha entera por un CUIL mal escrito es peor que el error.
            afiliado = dict(d, id_afiliado=id_af or None,
                            activo=antes["activo"] if antes else 1,
                            fecha_baja=antes["fecha_baja"] if antes else None,
                            id_motivo_baja=antes["id_motivo_baja"] if antes else None)
            atributos_sel = elegidos

    return _pantalla(afiliado, atributos_sel, errores, modo="abm")


def _guardia_abm(id_af):
    """None si puede modificar el padrón; si no, a dónde mandarlo."""
    if not validasesion():
        return redirect(url_for("login"))
    if not puede_abm():
        flash("!No tenés permiso para modificar el padrón.")
        return redirect(url_for("afiliados.padron", ver=id_af))
    return None


@afiliados_bp.route("/afiliados/<int:id_af>/empleadores", methods=["POST"])
def empleadores(id_af):
    """Alta, edición y eliminación de una relación del historial de empleadores."""
    salida = _guardia_abm(id_af)
    if salida:
        return salida
    volver = url_for("afiliados.abm_afiliados", edit=id_af, solapa="empleadores")
    accion = request.form.get("accion", "")
    id_rel = int(request.form.get("id_relacion") or 0)

    with get_connection() as conn:
        conn.begin()        # relación, empleador de la ficha y auditoría: todo o nada
        try:
            with conn.cursor() as cur:
                cat = _catalogos(cur)
                af = _afiliado(cur, id_af)
                if af is None:
                    conn.rollback()
                    flash("!Ese afiliado no existe.")
                    return redirect(url_for("afiliados.abm_afiliados"))
                if not af["cuil"]:
                    conn.rollback()
                    flash("!Sin CUIL no se puede registrar el historial de empleadores: "
                          "cargá primero el CUIL en la ficha.")
                    return redirect(volver)

                todas = _relaciones(cur, af["cuil"])
                antes = next((r for r in todas if r["id_relacion"] == id_rel), None)
                if id_rel and antes is None:
                    conn.rollback()
                    flash("!Esa relación laboral ya no existe.")
                    return redirect(volver)

                campo = {"relacion_laboral": "Relación laboral"}
                if accion == "borrar" and antes:
                    cur.execute("DELETE FROM p_relaciones_laborales WHERE id_relacion = %s", (id_rel,))
                    _registrar(cur, id_af, af["cuil"], {"relacion_laboral": _texto_relacion(antes)},
                               {"relacion_laboral": None}, campo, "MODIFICACION", cat,
                               observaciones="Eliminada del historial de empleadores")
                    flash("Relación laboral eliminada.")
                else:
                    errores: list[str] = []
                    otras = [r for r in todas if r["id_relacion"] != id_rel]
                    r = _relacion_del_form(cur, request.form, antes, otras, errores)
                    if errores:
                        conn.rollback()
                        for e in errores:
                            flash("!" + e)
                        return redirect(volver)
                    cols = ["cuit_empleador", "id_empleador", "fecha_inicio", "fecha_fin",
                            "estado", "categoria", "observaciones"]
                    if antes:
                        cur.execute(f"UPDATE p_relaciones_laborales SET "
                                    f"{', '.join(c + ' = %s' for c in cols)} WHERE id_relacion = %s",
                                    [r[c] for c in cols] + [id_rel])
                        flash("Relación laboral actualizada.")
                    else:
                        cur.execute(f"INSERT INTO p_relaciones_laborales (cuil, {', '.join(cols)}) "
                                    f"VALUES (%s, {', '.join(['%s'] * len(cols))})",
                                    [af["cuil"]] + [r[c] for c in cols])
                        flash("Relación laboral agregada.")
                    _registrar(cur, id_af, af["cuil"],
                               {"relacion_laboral": _texto_relacion(antes) if antes else None},
                               {"relacion_laboral": _texto_relacion(r)}, campo, "MODIFICACION", cat,
                               vigencia=r["fecha_inicio"] if not antes else None)
                _sincronizar_empleador(cur, af, cat)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return redirect(volver)


@afiliados_bp.route("/afiliados/<int:id_af>/documentacion", methods=["POST"])
def documentacion(id_af):
    """Subir o eliminar un documento del afiliado."""
    salida = _guardia_abm(id_af)
    if salida:
        return salida
    volver = url_for("afiliados.abm_afiliados", edit=id_af, solapa="documentacion")
    accion = request.form.get("accion", "")
    campo = {"documentacion": "Documentación"}
    nuevo_archivo, a_borrar = None, None

    with get_connection() as conn:
        conn.begin()
        try:
            with conn.cursor() as cur:
                cat = _catalogos(cur)
                af = _afiliado(cur, id_af)
                if af is None:
                    conn.rollback()
                    flash("!Ese afiliado no existe.")
                    return redirect(url_for("afiliados.abm_afiliados"))
                if accion == "borrar":
                    doc = _doc.uno(cur, "afiliado", id_af, int(request.form.get("id_documento") or 0))
                    if not doc:
                        conn.rollback()
                        flash("!Ese documento ya no existe.")
                        return redirect(volver)
                    a_borrar = _doc.borrar(cur, doc)
                    _registrar(cur, id_af, af["cuil"],
                               {"documentacion": f"{doc['tipo']} · {doc['nombre_original']}"},
                               {"documentacion": None}, campo, "MODIFICACION", cat,
                               observaciones="Documento eliminado")
                    flash(f"«{doc['nombre_original']}» eliminado.")
                else:
                    try:
                        nuevo = _doc.guardar(cur, "afiliado", id_af, request.form.get("id_tipo_doc"),
                                             request.files.get("archivo"),
                                             request.form.get("observaciones"), _usuario())
                    except _doc.DocumentoError as e:
                        conn.rollback()
                        flash(f"!{e}")
                        return redirect(volver)
                    nuevo_archivo = nuevo["archivo"]
                    _registrar(cur, id_af, af["cuil"], {"documentacion": None},
                               {"documentacion": f"{nuevo['tipo']} · {nuevo['nombre_original']}"},
                               campo, "MODIFICACION", cat, observaciones="Documento agregado")
                    flash(f"«{nuevo['nombre_original']}» agregado como {nuevo['tipo']}.")
            conn.commit()
        except Exception:
            conn.rollback()
            if nuevo_archivo:
                nuevo_archivo.unlink(missing_ok=True)
            raise
    # Recién con la fila borrada de verdad se borra el archivo.
    if a_borrar:
        a_borrar.unlink(missing_ok=True)
    return redirect(volver)


@afiliados_bp.route("/afiliados/<int:id_af>/documentacion/<int:id_documento>")
def ver_documento(id_af, id_documento):
    """El archivo, en el navegador: lo puede ver quien puede consultar el padrón."""
    if not validasesion():
        return redirect(url_for("login"))
    if not puede_consulta():
        flash("!No tenés permiso para consultar el padrón.")
        return redirect(url_for("menu"))
    with get_connection() as conn:
        with conn.cursor() as cur:
            doc = _doc.uno(cur, "afiliado", id_af, id_documento)
    real = _doc.ruta(doc) if doc else None
    if not real:
        flash("!El archivo no está en el servidor.")
        return redirect(request.referrer or url_for("afiliados.padron", ver=id_af))
    return send_file(real, mimetype=doc["mime_type"] or None, as_attachment=False,
                     download_name=doc["nombre_original"])


def _insertar(cur, d: dict, cat: dict) -> int:
    columnas = list(CAMPOS) + ["activo", "cod_obra_social"]
    valores = [d[c] for c in CAMPOS] + [1, ""]
    cur.execute(f"INSERT INTO p_afiliados ({', '.join(columnas)}) "
                f"VALUES ({', '.join(['%s'] * len(columnas))})", valores)
    id_af = cur.lastrowid
    _registrar(cur, id_af, d["cuil"], {"activo": None}, {"activo": 1},
               {"activo": "Activo"}, "ALTA", cat, vigencia=d["fecha_alta"] or date.today())
    if d["cuit_empleador"] and d["cuil"]:
        cur.execute("SELECT id, razon_social FROM p_empresas WHERE CUIT = %s", (d["cuit_empleador"],))
        emp = cur.fetchone() or {}
        rel = {"cuit_empleador": d["cuit_empleador"], "razon_social": emp.get("razon_social"),
               "fecha_inicio": d["fecha_alta"] or date.today(), "fecha_fin": None, "categoria": None}
        cur.execute("INSERT INTO p_relaciones_laborales "
                    "(cuil, cuit_empleador, id_empleador, fecha_inicio, estado, observaciones) "
                    "VALUES (%s, %s, %s, %s, 'activa', 'Cargada con el alta del afiliado')",
                    (d["cuil"], d["cuit_empleador"], emp.get("id"), rel["fecha_inicio"]))
        _registrar(cur, id_af, d["cuil"], {"relacion_laboral": None},
                   {"relacion_laboral": _texto_relacion(rel)},
                   {"relacion_laboral": "Relación laboral"}, "ALTA", cat)
    return id_af


def _actualizar(cur, antes: dict, d: dict, cat: dict):
    asignaciones = ", ".join(f"{c} = %s" for c in CAMPOS)
    cur.execute(f"UPDATE p_afiliados SET {asignaciones} WHERE id_afiliado = %s",
                [d[c] for c in CAMPOS] + [antes["id_afiliado"]])
    _registrar(cur, antes["id_afiliado"], d["cuil"], antes, d, CAMPOS, "MODIFICACION", cat)

    # Un titular que cambia de CUIL arrastra a su grupo y a sus relaciones
    # laborales, que lo referencian por CUIL y no por id. Sin esto, corregir un
    # CUIL mal cargado dejaría a la familia apuntando a un titular que ya no
    # existe.
    viejo, nuevo = antes["cuil"], d["cuil"]
    if viejo and nuevo and viejo != nuevo:
        if antes["cod_parentesco"] == TITULAR:
            cur.execute("SELECT id_afiliado, cuil, cuil_titular FROM p_afiliados "
                        "WHERE cuil_titular = %s AND id_afiliado <> %s",
                        (viejo, antes["id_afiliado"]))
            for f in cur.fetchall():
                cur.execute("UPDATE p_afiliados SET cuil_titular = %s WHERE id_afiliado = %s",
                            (nuevo, f["id_afiliado"]))
                _registrar(cur, f["id_afiliado"], f["cuil"], f, {"cuil_titular": nuevo},
                           {"cuil_titular": "CUIL del titular"}, "MODIFICACION", cat,
                           observaciones="Cambió el CUIL del titular")
        cur.execute("UPDATE p_relaciones_laborales SET cuil = %s WHERE cuil = %s",
                    (nuevo, viejo))


def _cambiar_estado(accion: str, id_af: int):
    """Baja o reactivación. La baja de un titular puede arrastrar a su grupo."""
    with get_connection() as conn:
        conn.begin()
        try:
            with conn.cursor() as cur:
                cat = _catalogos(cur)
                antes = _afiliado(cur, id_af)
                if antes is None:
                    conn.rollback()
                    flash("Ese afiliado no existe.")
                    return redirect(url_for("afiliados.abm_afiliados"))

                if accion == "reactivar":
                    despues = {"activo": 1, "fecha_baja": None, "id_motivo_baja": None}
                    cur.execute("UPDATE p_afiliados SET activo = 1, fecha_baja = NULL, "
                                "id_motivo_baja = NULL WHERE id_afiliado = %s", (id_af,))
                    _registrar(cur, id_af, antes["cuil"], antes, despues, CAMPOS_ESTADO,
                               "REACTIVACION", cat, vigencia=date.today())
                    conn.commit()
                    flash("Afiliado reactivado.")
                    return redirect(url_for("afiliados.abm_afiliados", edit=id_af))

                errores = []
                fecha_baja = _fecha_form(request.form.get("fecha_baja"), "Fecha de baja",
                                         errores) or date.today()
                motivo = request.form.get("id_motivo_baja", "")
                id_motivo = int(motivo) if motivo.isdigit() else None
                if id_motivo is None:
                    errores.append("Elegí el motivo de la baja.")
                if errores:
                    conn.rollback()
                    for e in errores:
                        flash(e)
                    return redirect(url_for("afiliados.abm_afiliados", edit=id_af))

                ids = [id_af]
                if antes["cod_parentesco"] == TITULAR and request.form.get("con_grupo"):
                    cur.execute("SELECT id_afiliado FROM p_afiliados "
                                "WHERE cuil_titular = %s AND id_afiliado <> %s AND activo = 1",
                                (antes["cuil"], id_af))
                    ids += [f["id_afiliado"] for f in cur.fetchall()]

                despues = {"activo": 0, "fecha_baja": fecha_baja, "id_motivo_baja": id_motivo}
                for i in ids:
                    previo = antes if i == id_af else _afiliado(cur, i)
                    cur.execute("UPDATE p_afiliados SET activo = 0, fecha_baja = %s, "
                                "id_motivo_baja = %s WHERE id_afiliado = %s",
                                (fecha_baja, id_motivo, i))
                    _registrar(cur, i, previo["cuil"], previo, despues, CAMPOS_ESTADO, "BAJA",
                               cat, vigencia=fecha_baja,
                               observaciones=None if i == id_af else "Baja del grupo con el titular")
                conn.commit()
                flash("Afiliado dado de baja." if len(ids) == 1 else
                      f"Baja del titular y de {len(ids) - 1} familiar(es).")
        except Exception:
            conn.rollback()
            raise
    return redirect(url_for("afiliados.abm_afiliados", edit=id_af))


def _pantalla(afiliado, atributos_sel, errores, modo: str):
    """
    Arma la pantalla en sus dos modos. La consulta abre la ficha con ?ver=ID;
    el ABM, con ?edit=ID o ?familiar_de=CUIL.
    """
    consulta = modo == "consulta"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cat = _catalogos(cur)
            edit_id = (request.args.get("ver" if consulta else "edit") or "").strip()
            familiar_de = "" if consulta else digitos(request.args.get("familiar_de"))

            if afiliado is None and edit_id.isdigit():
                afiliado = _afiliado(cur, int(edit_id))
                if afiliado is None:
                    flash("Ese afiliado no existe.")
                else:
                    atributos_sel = _atributos_de(cur, afiliado["id_afiliado"])

            # Alta de un familiar desde la ficha del titular: grupo y domicilio
            # ya puestos, el parentesco por elegir.
            if afiliado is None and familiar_de:
                cur.execute("SELECT * FROM p_afiliados WHERE cuil = %s AND cod_parentesco = 0",
                            (familiar_de,))
                titular = cur.fetchone()
                if titular:
                    afiliado = {c: titular[c] for c in CAMPOS_DOMICILIO}
                    afiliado.update(cuil_titular=familiar_de, cod_parentesco=None,
                                    nacionalidad=ARGENTINA, tipo_documento="DU",
                                    fecha_alta=date.today())

            editando = bool(afiliado and afiliado.get("id_afiliado"))
            grupo, contactos_af, movimientos, empleador = [], [], [], None
            relaciones, documentos, tipos_doc_adj, doc_faltantes = [], [], [], []
            areas = _contactos.areas(cur)
            ref = afiliado or {}
            if ref.get("cuil_titular"):
                cur.execute("""
                    SELECT a.id_afiliado, a.cuil, a.apellido_nombres, a.cod_parentesco,
                           p.descripcion AS parentesco, a.activo, a.fecha_baja,
                           TIMESTAMPDIFF(YEAR, a.fecha_nacimiento, CURDATE()) AS edad
                      FROM p_afiliados a
                      LEFT JOIN p_parentesco p ON p.codigo = a.cod_parentesco
                     WHERE a.cuil_titular = %s
                     ORDER BY a.cod_parentesco, a.fecha_nacimiento
                """, (ref["cuil_titular"],))
                grupo = cur.fetchall()
            if ref.get("cuit_empleador"):
                cur.execute("SELECT id, razon_social FROM p_empresas WHERE CUIT = %s",
                            (ref["cuit_empleador"],))
                empleador = cur.fetchone()
            if editando:
                relaciones = _relaciones(cur, afiliado.get("cuil"))
                documentos = _doc.de(cur, "afiliado", afiliado["id_afiliado"])
                tipos_doc_adj = _doc.tipos(cur, "afiliado")
                doc_faltantes = _doc.faltantes(cur, "afiliado", afiliado["id_afiliado"])
                contactos_af = _contactos.de(cur, "afiliado", afiliado["id_afiliado"])
                cur.execute("""
                    SELECT fecha, fecha_vigencia, tipo_movimiento, origen, campo_label,
                           valor_anterior, valor_actual, usuario, observaciones
                      FROM p_afiliados_movimientos
                     WHERE id_afiliado = %s
                     ORDER BY fecha DESC, id_movimiento DESC
                     LIMIT 300
                """, (afiliado["id_afiliado"],))
                movimientos = cur.fetchall()

            # Todo el padrón de una vez, como empleadores: el JS de base.html
            # filtra, ordena y pagina en el navegador sin volver a la base.
            cur.execute("""
                SELECT a.id_afiliado, a.cuil, a.cuil_titular, a.cod_parentesco,
                       p.descripcion AS parentesco,
                       a.apellido_nombres AS nombre_completo,
                       a.nro_documento, a.localidad, a.activo, a.fecha_baja,
                       TIMESTAMPDIFF(YEAR, a.fecha_nacimiento, CURDATE()) AS edad,
                       a.sexo, x.atributos,
                       e.razon_social AS empleador
                  FROM p_afiliados a
                  LEFT JOIN p_parentesco p ON p.codigo = a.cod_parentesco
                  LEFT JOIN p_empresas e
                         ON a.cuit_empleador REGEXP '^[0-9]+$'
                        AND e.CUIT = CAST(a.cuit_empleador AS UNSIGNED)
                  -- CAST: GROUP_CONCAT de enteros vuelve binario y pymysql lo
                  -- entrega como bytes.
                  LEFT JOIN (SELECT id_afiliado,
                                    GROUP_CONCAT(CAST(id_atributo AS CHAR)) AS atributos
                               FROM p_atributos_por_afiliado
                              GROUP BY id_afiliado) x ON x.id_afiliado = a.id_afiliado
                 ORDER BY a.apellido_nombres
            """)
            afiliados = cur.fetchall()

            # Las marcas de cada uno, en el orden del catálogo y solo las
            # activas: una desactivada (la «AEDA» de la obra social) ni se
            # muestra ni se ofrece en el filtro.
            activos = [atr["id"] for atr in cat["atributos"]]
            por_id = {atr["id"]: atr for atr in cat["atributos"]}
            for f in afiliados:
                tiene = {int(i) for i in (f["atributos"] or "").split(",") if i.isdigit()}
                f["atributos"] = [por_id[i] for i in activos if i in tiene]

    return render_template(
        "afiliados/abm_afiliados.html",
        modo=modo, puede_abm=puede_abm(),
        afiliados=afiliados, afiliado=afiliado, editando=editando,
        atributos_sel=atributos_sel, grupo=grupo, empleador=empleador,
        contactos=contactos_af, areas_contacto=areas, movimientos=movimientos,
        relaciones=relaciones, documentos=documentos, tipos_doc_adj=tipos_doc_adj,
        doc_faltantes=doc_faltantes, doc_extensiones=sorted(_doc.EXTENSIONES), doc_max_mb=_doc.MAX_MB,
        errores=errores, hoy=date.today(),
        motivo_baja=cat["etiquetas"]["id_motivo_baja"].get(str((afiliado or {}).get("id_motivo_baja"))),
        **cat,
    )
