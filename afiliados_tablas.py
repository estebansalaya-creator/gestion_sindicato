"""
afiliados_tablas.py — Tablas auxiliares del padrón de afiliados.

Las de «Tablas Auxiliares Padrón SSS» de gestion_adm que usa la ficha del
afiliado —estado civil, nacionalidad, parentesco, provincia y tipo de
documento—, sin situación de revista. Más las tres que la ficha también
consulta: motivos de alta y baja, atributos del afiliado y tipos de
documentación. Tipo de beneficiario queda afuera: el padrón del gremio no tiene
ese dato, y un catálogo que nada usa solo confunde.

Una pantalla, una solapa por tabla y una sola regla para todas, declarada en
TABLAS:

- En las tablas de la SSS el código lo elige quien carga (es el del padrón y
  el que se informa); en las demás lo pone la base.
- Lo que se usa no se borra. Si la tabla tiene `activo`, se desactiva: deja de
  ofrecerse y lo ya cargado sigue apuntando a él. Si no tiene, queda.
- Hay filas que el sistema usa por su código (parentesco 0 = Titular, DU): se
  pueden editar pero no borrar.
- Con un error de validación la pantalla vuelve con lo tipeado y el diálogo
  abierto, no con un cartel y el formulario vacío.

Permiso: la opción de menú «Tablas Auxiliares» (sql/afiliados_tablas_20261110.sql),
también en el POST.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from flask import Blueprint, flash, redirect, render_template, request, url_for

from db import get_connection, puede, validasesion

log = logging.getLogger(__name__)

tablas_bp = Blueprint("afiliados_tablas", __name__)


@dataclass
class Campo:
    col: str
    etiqueta: str
    tipo: str = "texto"            # texto | entero | check | opcion
    largo: int = 0                 # texto: máximo de caracteres
    obligatorio: bool = False
    unico: bool = False            # no puede repetirse en la tabla
    mayusculas: bool = False
    opciones: tuple = ()           # opcion: ((valor, texto), …)
    minimo: int = 0                # entero
    maximo: int = 0                # entero
    ayuda: str = ""
    span: int = 6                  # ancho en la grilla de 12 del formulario
    defecto: object = None         # vacío → esto (columnas NOT NULL que no son obligatorias)


@dataclass
class Tabla:
    clave: str
    tabla: str
    titulo: str
    singular: str
    pk: str
    #: manual_entero / manual_texto: lo escribe quien carga (códigos de la SSS).
    #: auto: AUTO_INCREMENT. siguiente: la tabla no es AUTO_INCREMENT y se
    #: toma el máximo + 1.
    pk_modo: str
    campos: list
    nombre: str                    # la columna que nombra la fila en los mensajes
    usos: tuple = ()               # (tabla, columna) que apuntan a esta
    pk_max: int = 0                # manual_entero: el tope del tipo de la columna que la usa
    pk_largo: int = 0              # manual_texto
    fijos: dict = field(default_factory=dict)      # pk → por qué no se borra
    filtro: str = ""               # condición extra para listar (sin WHERE)
    al_crear: dict = field(default_factory=dict)   # columnas fijas del INSERT
    orden: str = ""
    ayuda: str = ""

    @property
    def tiene_activo(self) -> bool:
        return any(c.col == "activo" for c in self.campos)

    @property
    def pk_manual(self) -> bool:
        return self.pk_modo.startswith("manual")


_ACTIVO = Campo("activo", "Activo", "check", span=3,
                ayuda="Si no, no se ofrece al cargar.")

TABLAS: dict[str, Tabla] = {t.clave: t for t in [
    Tabla("estado_civil", "p_estado_civil", "Estado civil", "estado civil",
          pk="codigo", pk_modo="manual_entero", pk_max=127, nombre="descripcion",
          campos=[Campo("descripcion", "Descripción", largo=40, obligatorio=True, unico=True, span=9)],
          usos=(("p_afiliados", "estado_civil"),),
          ayuda="Códigos del padrón de la SSS."),
    Tabla("nacionalidad", "p_nacionalidad", "Nacionalidades", "nacionalidad",
          pk="codigo", pk_modo="manual_entero", pk_max=32767, nombre="descripcion",
          campos=[Campo("descripcion", "Descripción", largo=60, obligatorio=True, unico=True, span=9)],
          usos=(("p_afiliados", "nacionalidad"),),
          ayuda="Códigos de país del padrón de la SSS (12 = Argentina)."),
    Tabla("parentesco", "p_parentesco", "Parentescos", "parentesco",
          pk="codigo", pk_modo="manual_entero", pk_max=127, nombre="descripcion",
          campos=[Campo("descripcion", "Descripción", largo=80, obligatorio=True, unico=True, span=9)],
          usos=(("p_afiliados", "cod_parentesco"),),
          fijos={"0": "Titular: con el código 0 el sistema arma los grupos familiares."},
          ayuda="Códigos del padrón de la SSS. El 0 es el titular."),
    Tabla("provincia", "p_provincia", "Provincias", "provincia",
          pk="codigo", pk_modo="manual_entero", pk_max=127, nombre="nombre",
          campos=[Campo("nombre", "Nombre", largo=40, obligatorio=True, unico=True, span=6),
                  Campo("codigo_arca", "Código ARCA", "entero", minimo=0, maximo=999, span=3,
                        ayuda="El de la provincia en ARCA.")],
          usos=(("p_afiliados", "provincia"), ("s_institucion", "provincia"),
                ("p_domicilios_explotacion", "provincia")),
          ayuda="Códigos del padrón de la SSS, con su equivalente de ARCA."),
    Tabla("tipo_documento", "p_tipo_documento", "Tipos de documento", "tipo de documento",
          pk="codigo", pk_modo="manual_texto", pk_largo=2, nombre="descripcion",
          campos=[Campo("descripcion", "Descripción", largo=40, obligatorio=True, unico=True, span=6),
                  Campo("codigo_arca", "Código ARCA", largo=15, span=3,
                        ayuda="El tipo de documento en ARCA.")],
          usos=(("p_afiliados", "tipo_documento"),),
          fijos={"DU": "Documento Único: es el que se toma del CUIL cuando falta el documento."},
          ayuda="Códigos de dos letras del padrón de la SSS."),
    Tabla("motivos", "p_motivo_movimiento", "Motivos de alta y baja", "motivo",
          pk="id", pk_modo="siguiente", nombre="nombre",
          campos=[Campo("nombre", "Nombre", largo=120, obligatorio=True, span=7),
                  Campo("es_alta", "Tipo", "opcion", obligatorio=True,
                        opciones=(("0", "Baja"), ("1", "Alta")), span=2),
                  _ACTIVO],
          usos=(("p_afiliados", "id_motivo_baja"),),
          orden="es_alta, nombre",
          ayuda="Los de baja se eligen al dar de baja a un afiliado."),
    Tabla("atributos", "p_afiliado_atributo", "Atributos", "atributo",
          pk="id", pk_modo="auto", nombre="rotulo",
          campos=[Campo("rotulo", "Rótulo", largo=20, obligatorio=True, unico=True, span=3),
                  Campo("descripcion", "Descripción", largo=100, span=9),
                  Campo("fuerza_activo", "Lo mantiene vigente aunque esté de baja", "check", span=9,
                        ayuda="Para los reintegros: un judicializado o con amparo sigue cubierto."),
                  _ACTIVO],
          usos=(("p_atributos_por_afiliado", "id_atributo"),),
          orden="id",
          ayuda="Las marcas que se tildan en la ficha del afiliado y por las que se filtra el padrón."),
    Tabla("tipos_documentacion", "p_tipo_documentacion", "Tipos de documentación", "tipo de documentación",
          pk="id_tipo_doc", pk_modo="auto", nombre="descripcion",
          campos=[Campo("codigo", "Código", largo=30, obligatorio=True, unico=True, span=3,
                        ayuda="Interno, sin espacios."),
                  Campo("descripcion", "Descripción", largo=100, obligatorio=True, span=6),
                  Campo("orden", "Orden", "entero", minimo=0, maximo=9999, span=3, defecto=0,
                        ayuda="En ese orden se ofrecen."),
                  Campo("obligatorio", "Obligatorio", "check", span=6,
                        ayuda="La ficha avisa si al afiliado le falta."),
                  _ACTIVO],
          usos=(("p_documentacion", "id_tipo_doc"),),
          # La tabla es de todas las entidades (proveedores, empresas…): acá
          # solo las del afiliado, y lo nuevo nace del afiliado.
          filtro="FIND_IN_SET('afiliado', REPLACE(COALESCE(aplica_a, ''), ' ', ''))",
          al_crear={"aplica_a": "afiliado"},
          orden="orden, descripcion",
          ayuda="Lo que se puede adjuntar en la solapa Documentación de la ficha."),
]}


def puede_tablas() -> bool:
    return puede(url_for("afiliados_tablas.tablas"))


def _usos(cur, t: Tabla) -> dict[str, int]:
    """pk (como texto) → en cuántas filas se usa, sumando todas las tablas que la apuntan."""
    n: dict[str, int] = {}
    for tabla, col in t.usos:
        cur.execute(f"SELECT {col} AS v, COUNT(*) AS n FROM {tabla} "
                    f"WHERE {col} IS NOT NULL GROUP BY {col}")
        for f in cur.fetchall():
            k = str(f["v"])
            n[k] = n.get(k, 0) + f["n"]
    return n


def _filas(cur, t: Tabla) -> list[dict]:
    cols = ", ".join(c.col for c in t.campos)
    where = f"WHERE {t.filtro}" if t.filtro else ""
    cur.execute(f"SELECT {t.pk} AS _pk, {cols} FROM {t.tabla} {where} "
                f"ORDER BY {t.orden or t.pk}")
    filas = cur.fetchall()
    usos = _usos(cur, t)
    for f in filas:
        f["_usos"] = usos.get(str(f["_pk"]), 0)
        f["_fijo"] = t.fijos.get(str(f["_pk"]))
        # Lo que el botón de editar lleva en data-*, para llenar el diálogo.
        f["_datos"] = {"t": t.clave, "pk": f["_pk"], **{f"c_{c.col}": f[c.col] for c in t.campos}}
    return filas


def _siguiente(cur, t: Tabla) -> int:
    cur.execute(f"SELECT COALESCE(MAX({t.pk}), 0) + 1 AS n FROM {t.tabla}")
    return cur.fetchone()["n"]


def _leer(form, t: Tabla, errores: list[str]) -> dict:
    """Los valores del formulario, limpios y validados en forma; la unicidad va aparte."""
    v: dict = {}
    for c in t.campos:
        crudo = (form.get(c.col) or "").strip()
        if c.tipo == "check":
            v[c.col] = 1 if crudo else 0
        elif c.tipo == "entero":
            if not crudo:
                v[c.col] = None
            elif not re.fullmatch(r"\d+", crudo) or not (c.minimo <= int(crudo) <= c.maximo):
                errores.append(f"{c.etiqueta}: tiene que ser un número entre {c.minimo} y {c.maximo}.")
                v[c.col] = crudo
            else:
                v[c.col] = int(crudo)
        elif c.tipo == "opcion":
            validos = {o[0] for o in c.opciones}
            v[c.col] = crudo if crudo in validos else None
            if v[c.col] is not None and crudo.isdigit():
                v[c.col] = int(crudo)
        else:
            txt = re.sub(r"\s+", " ", crudo)
            if c.largo and len(txt) > c.largo:
                errores.append(f"{c.etiqueta}: hasta {c.largo} caracteres.")
                txt = txt[:c.largo]
            v[c.col] = (txt.upper() if c.mayusculas else txt) or None
        if v[c.col] is None and c.defecto is not None:
            v[c.col] = c.defecto
        if c.obligatorio and v[c.col] in (None, ""):
            errores.append(f"Falta {c.etiqueta.lower()}.")
    return v


def _leer_pk(form, t: Tabla, errores: list[str]):
    crudo = (form.get("pk") or "").strip()
    if t.pk_modo == "manual_entero":
        if not re.fullmatch(r"\d+", crudo) or int(crudo) > t.pk_max:
            errores.append(f"El código tiene que ser un número entre 0 y {t.pk_max}.")
            return crudo
        return int(crudo)
    if t.pk_modo == "manual_texto":
        crudo = crudo.upper()
        if not re.fullmatch(r"[A-Z0-9]{1,%d}" % t.pk_largo, crudo):
            errores.append(f"El código son hasta {t.pk_largo} letras o números.")
        return crudo
    return None


def _guardar(t: Tabla) -> tuple[list[str], dict]:
    """Alta o modificación. Devuelve (errores, lo tipeado para volver a mostrarlo)."""
    errores: list[str] = []
    original = (request.form.get("pk_original") or "").strip()
    valores = _leer(request.form, t, errores)
    pk = _leer_pk(request.form, t, errores) if (t.pk_manual and not original) else None
    tipeado = {"clave": t.clave, "pk_original": original, "pk": request.form.get("pk", ""),
               "valores": valores}

    with get_connection() as conn:
        conn.begin()
        try:
            with conn.cursor() as cur:
                if original:
                    cur.execute(f"SELECT {t.pk} AS _pk FROM {t.tabla} WHERE {t.pk} = %s", (original,))
                    if not cur.fetchone():
                        conn.rollback()
                        return [f"Ese {t.singular} ya no existe."], {}
                elif t.pk_manual and not errores:
                    cur.execute(f"SELECT {t.nombre} AS n FROM {t.tabla} WHERE {t.pk} = %s", (pk,))
                    otro = cur.fetchone()
                    if otro:
                        errores.append(f"El código {pk} ya es de «{otro['n']}».")

                # La unicidad se mira en toda la tabla, no solo en lo que
                # muestra la solapa: la base la exige así.
                for c in t.campos:
                    if c.unico and valores.get(c.col):
                        cur.execute(f"SELECT {t.pk} AS _pk FROM {t.tabla} "
                                    f"WHERE {c.col} = %s AND {t.pk} <> %s",
                                    (valores[c.col], original if original else (pk if pk is not None else "")))
                        if cur.fetchone():
                            errores.append(f"Ya hay un {t.singular} con {c.etiqueta.lower()} «{valores[c.col]}».")

                if errores:
                    conn.rollback()
                    return errores, tipeado

                cols = [c.col for c in t.campos]
                if original:
                    cur.execute(f"UPDATE {t.tabla} SET {', '.join(c + ' = %s' for c in cols)} "
                                f"WHERE {t.pk} = %s", [valores[c] for c in cols] + [original])
                    flash(f"«{valores[t.nombre]}» actualizado.")
                else:
                    extra = dict(t.al_crear)
                    if t.pk_manual:
                        extra[t.pk] = pk
                    elif t.pk_modo == "siguiente":
                        extra[t.pk] = _siguiente(cur, t)
                    todas = cols + list(extra)
                    cur.execute(f"INSERT INTO {t.tabla} ({', '.join(todas)}) "
                                f"VALUES ({', '.join(['%s'] * len(todas))})",
                                [valores[c] for c in cols] + list(extra.values()))
                    flash(f"«{valores[t.nombre]}» agregado.")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return [], {}


def _cambiar(t: Tabla, accion: str):
    """Borrar (si no se usa ni es fijo), desactivar o reactivar."""
    pk = (request.form.get("pk_original") or "").strip()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {t.nombre} AS n FROM {t.tabla} WHERE {t.pk} = %s", (pk,))
            f = cur.fetchone()
            if not f:
                flash(f"!Ese {t.singular} ya no existe.")
                return
            nombre = f["n"]
            if accion == "borrar":
                if t.fijos.get(pk):
                    flash(f"!«{nombre}» no se puede eliminar. {t.fijos[pk]}")
                    return
                n = _usos(cur, t).get(pk, 0)
                if n:
                    flash(f"!«{nombre}» se usa en {n} registro(s): no se puede eliminar."
                          + (" Desactivalo para que no se ofrezca más." if t.tiene_activo else ""))
                    return
                cur.execute(f"DELETE FROM {t.tabla} WHERE {t.pk} = %s", (pk,))
                flash(f"«{nombre}» eliminado.")
            elif t.tiene_activo:
                cur.execute(f"UPDATE {t.tabla} SET activo = %s WHERE {t.pk} = %s",
                            (1 if accion == "reactivar" else 0, pk))
                flash(f"«{nombre}» " + ("reactivado." if accion == "reactivar"
                                         else "desactivado: ya no se ofrece al cargar."))


@tablas_bp.route("/afiliados/tablas", methods=["GET", "POST"])
def tablas():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede_tablas():
        flash("!No tenés permiso para las tablas del padrón.")
        return redirect(url_for("menu"))

    clave = request.values.get("t") or next(iter(TABLAS))
    if clave not in TABLAS:
        clave = next(iter(TABLAS))
    errores, reabrir = [], {}

    if request.method == "POST":
        t = TABLAS[clave]
        accion = request.form.get("accion", "")
        if accion == "guardar":
            errores, reabrir = _guardar(t)
            if not errores:
                return redirect(url_for("afiliados_tablas.tablas", t=clave))
        elif accion in ("borrar", "baja", "reactivar"):
            _cambiar(t, accion)
            return redirect(url_for("afiliados_tablas.tablas", t=clave))

    with get_connection() as conn:
        with conn.cursor() as cur:
            datos = []
            for t in TABLAS.values():
                datos.append({"t": t, "filas": _filas(cur, t),
                              "siguiente": _siguiente(cur, t) if t.pk_modo == "manual_entero" else ""})
    return render_template("afiliados/tablas.html", datos=datos, actual=clave,
                           errores=errores, reabrir=reabrir)
