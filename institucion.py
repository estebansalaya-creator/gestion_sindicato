"""
institucion.py — Datos del sindicato (/admin/institucion).

El equivalente de «Parámetros de la Obra Social» de gestion_adm
(`os_parametros`), para un gremio: identificación gremial, datos fiscales,
condición de agente de retención, domicilio, autoridades y logo. Una sola
fila en `s_institucion` (sql/institucion_20261107.sql).

De acá sale el membrete de los documentos (la constancia de reintegro) y el
nombre y el logo del encabezado de todas las pantallas. `encabezado()` se
guarda un minuto en memoria: se consulta en cada request y cambia una vez por
año; al guardar se descarta, así el cambio se ve en la pantalla siguiente.

Los campos de retención se llaman como en `os_parametros`: el motor de
retenciones de gestion_adm se podrá traer cambiando solo el nombre de la tabla.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pymysql
from flask import (Blueprint, flash, redirect, render_template, request, send_file,
                   session, url_for)

from db import get_connection, puede, validasesion
from empleadores import cuit_valido

institucion_bp = Blueprint("institucion", __name__)

TEXTO = {
    # campo: (rótulo, largo máximo)
    "nombre": ("Denominación", 150), "sigla": ("Sigla", 20),
    "personeria_gremial": ("Personería gremial", 60),
    "inscripcion_gremial": ("Inscripción gremial", 60), "ambito": ("Ámbito", 250),
    "nro_iibb": ("N° de Ingresos Brutos", 30),
    "exencion_ganancias": ("Exención en Ganancias", 100),
    "ret_iibb_regimen": ("Régimen de IIBB", 20),
    "nro_resolucion_ret": ("Resolución de designación", 100),
    "domicilio": ("Domicilio", 200), "localidad": ("Localidad", 100), "cp": ("Código postal", 8),
    "telefono": ("Teléfono", 50), "email": ("Email", 100), "web": ("Sitio web", 100),
    "secretario_general": ("Secretario general", 150),
    "secretario_adjunto": ("Secretario adjunto", 150), "tesorero": ("Tesorero", 150),
}
FECHAS = {"inicio_actividades": "Inicio de actividades",
          "exencion_ganancias_vto": "Vencimiento de la exención"}
ENTEROS = {"condicion_iva": "Condición frente al IVA", "provincia": "Provincia",
           "ret_arca_tasa_ivaid": "Tasa de IVA para la base"}
IMPUESTOS = ["iva", "ganancias", "iibb", "suss"]          # ret_<x> y ret_<x>_alicuota
REGIMENES_IIBB = ["SIRCAR", "SIRCREB", "ARBA", "AGIP", "OTRO"]
LOGO_EXT = {".png", ".jpg", ".jpeg", ".svg"}
LOGO_MAX_MB = 2


def _base_archivos() -> Path:
    """La misma carpeta escribible que los comprobantes de reintegros."""
    return Path(os.getenv("SIND_ADJUNTOS") or Path(__file__).with_name("adjuntos"))


# =============================================================================
# Lectura (la usan otras pantallas)
# =============================================================================

def obtener() -> dict:
    """Los datos del sindicato, o {} si todavía no se cargaron o falta la tabla."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT i.*, rt.descripcion AS condicion_iva_txt, pv.nombre AS provincia_txt
                      FROM s_institucion i
                      LEFT JOIN arca_responsable_tipo rt ON rt.codigo = i.condicion_iva
                      LEFT JOIN p_provincia pv ON pv.codigo = i.provincia
                     WHERE i.id = 1
                """)
                return cur.fetchone() or {}
    except pymysql.err.ProgrammingError:
        return {}       # falta sql/institucion_20261107.sql


def ruta_logo(datos: dict | None = None) -> Path | None:
    datos = obtener() if datos is None else datos
    rel = datos.get("logo_path")
    if not rel:
        return None
    base = _base_archivos().resolve()
    real = (base / rel).resolve()
    return real if base in real.parents and real.exists() else None


_CACHE = {"hasta": 0.0, "valor": None}


def encabezado() -> dict:
    """Nombre, sigla y si hay logo, para el encabezado de base.html. Un minuto en memoria."""
    if _CACHE["valor"] is None or time.monotonic() > _CACHE["hasta"]:
        d = obtener()
        _CACHE["valor"] = {"nombre": d.get("nombre"), "sigla": d.get("sigla"),
                           "logo": bool(ruta_logo(d)),
                           "version": int(d["actualizado_at"].timestamp()) if d.get("actualizado_at") else 0}
        _CACHE["hasta"] = time.monotonic() + 60
    return _CACHE["valor"]


def domicilio_completo(d: dict) -> str:
    partes = [d.get("domicilio"), d.get("localidad"),
              (f"CP {d['cp']}" if d.get("cp") else None), d.get("provincia_txt")]
    return ", ".join(p for p in partes if p)


# =============================================================================
# Pantalla
# =============================================================================

def _catalogos() -> dict:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT codigo, descripcion FROM arca_responsable_tipo ORDER BY codigo")
            condiciones = cur.fetchall()
            cur.execute("SELECT id, descripcion, alicuota FROM arca_tasa_iva ORDER BY alicuota, codigo")
            tasas = cur.fetchall()
            cur.execute("SELECT codigo, nombre FROM p_provincia ORDER BY nombre")
            provincias = cur.fetchall()
    return {"condiciones_iva": condiciones, "tasas_iva": tasas, "provincias": provincias,
            "regimenes_iibb": REGIMENES_IIBB}


def _leer_form(form) -> tuple[dict, list[str]]:
    """Los valores del formulario, validados. Devuelve (valores, errores)."""
    v, errores = {}, []
    for campo, (rotulo, largo) in TEXTO.items():
        texto = re.sub(r"\s+", " ", form.get(campo) or "").strip()
        if len(texto) > largo:
            errores.append(f"{rotulo}: hasta {largo} caracteres.")
        v[campo] = texto or None
    if not v["nombre"]:
        errores.append("La denominación es obligatoria.")

    cuit = re.sub(r"\D", "", form.get("cuit") or "")
    if cuit and not cuit_valido(cuit):
        errores.append(f"El CUIT {cuit} no es válido: no verifica el dígito de control.")
    v["cuit"] = cuit or None

    if v["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v["email"]):
        errores.append(f"El email «{v['email']}» no es válido.")
    if v["ret_iibb_regimen"] and v["ret_iibb_regimen"] not in REGIMENES_IIBB:
        errores.append("Elegí el régimen de Ingresos Brutos de la lista.")

    for campo, rotulo in FECHAS.items():
        texto = (form.get(campo) or "").strip()
        try:
            v[campo] = datetime.strptime(texto, "%Y-%m-%d").date() if texto else None
        except ValueError:
            errores.append(f"{rotulo}: la fecha no es válida.")
            v[campo] = None

    for campo, rotulo in ENTEROS.items():
        texto = (form.get(campo) or "").strip()
        v[campo] = int(texto) if texto.isdigit() else None

    for imp in IMPUESTOS:
        v[f"ret_{imp}"] = 1 if form.get(f"ret_{imp}") else 0
        texto = (form.get(f"ret_{imp}_alicuota") or "").strip().replace(",", ".")
        try:
            alic = Decimal(texto) if texto else None
        except InvalidOperation:
            alic, texto = None, "x"
        if texto and (alic is None or not (0 <= alic <= 100)):
            errores.append(f"La alícuota de {imp.upper()} tiene que ser un porcentaje entre 0 y 100.")
        v[f"ret_{imp}_alicuota"] = alic

    # Cuota sindical (sql/fisca_liquidacion_20261111.sql): solo viaja si la
    # columna existe, porque la pantalla dibuja el bloque solo entonces.
    if "cuota_alicuota" in form:
        texto = (form.get("cuota_alicuota") or "").strip().replace(",", ".")
        try:
            alic = Decimal(texto)
        except InvalidOperation:
            alic = None
        if alic is None or not (0 < alic <= 100):
            errores.append("La alícuota de la cuota sindical tiene que ser un porcentaje mayor que 0 y hasta 100.")
        v["cuota_alicuota"] = alic
        dia = (form.get("cuota_dia_vto") or "").strip()
        if not dia.isdigit() or not (1 <= int(dia) <= 31):
            errores.append("El día de vencimiento de la cuota sindical va de 1 a 31.")
        v["cuota_dia_vto"] = int(dia) if dia.isdigit() else None
    return v, errores


def _guardar_logo(archivo) -> tuple[str | None, str | None]:
    """Guarda el logo nuevo. Devuelve (ruta relativa, error)."""
    ext = Path(archivo.filename).suffix.lower()
    if ext not in LOGO_EXT:
        return None, "El logo tiene que ser PNG, JPG o SVG."
    carpeta = _base_archivos() / "institucion"
    carpeta.mkdir(parents=True, exist_ok=True)
    for viejo in carpeta.glob("logo.*"):
        viejo.unlink(missing_ok=True)
    destino = carpeta / f"logo{ext}"
    archivo.save(destino)
    if destino.stat().st_size > LOGO_MAX_MB * 1024 * 1024:
        destino.unlink()
        return None, f"El logo supera los {LOGO_MAX_MB} MB."
    return f"institucion/logo{ext}", None


@institucion_bp.route("/admin/institucion", methods=["GET", "POST"])
def datos():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede(url_for("institucion.datos")):
        flash("!No tenés permiso para los datos del sindicato.")
        return redirect(url_for("menu"))

    actual = obtener()
    falta_tabla = not actual and not _hay_tabla()
    errores = []

    if request.method == "POST" and not falta_tabla:
        valores, errores = _leer_form(request.form)
        logo = request.files.get("logo")
        if not errores:
            if request.form.get("borrar_logo"):
                for viejo in (_base_archivos() / "institucion").glob("logo.*"):
                    viejo.unlink(missing_ok=True)
                valores["logo_path"] = None
            elif logo and logo.filename:
                ruta, error = _guardar_logo(logo)
                if error:
                    errores.append(error)
                else:
                    valores["logo_path"] = ruta
        if not errores:
            valores["actualizado_por"] = (session.get("sind_usuario_email")
                                          or session.get("sind_usuario_nombre") or "")[:100]
            columnas = list(valores)
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"INSERT INTO s_institucion (id, {', '.join(columnas)}) "
                        f"VALUES (1, {', '.join(['%s'] * len(columnas))}) "
                        f"ON DUPLICATE KEY UPDATE "
                        + ", ".join(f"{c} = VALUES({c})" for c in columnas),
                        [valores[c] for c in columnas])
            _CACHE["valor"] = None
            flash("Datos del sindicato guardados.")
            return redirect(url_for("institucion.datos"))
        # Con errores se vuelve a dibujar lo que se escribió, no lo guardado.
        actual = {**actual, **valores}

    return render_template("admin/institucion.html", d=actual, errores=errores,
                           falta_tabla=falta_tabla, tiene_logo=bool(ruta_logo(actual)),
                           max_mb=LOGO_MAX_MB, **_catalogos())


def _hay_tabla() -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM information_schema.tables "
                        "WHERE table_schema = DATABASE() AND table_name = 's_institucion'")
            return bool(cur.fetchone()["n"])


@institucion_bp.route("/admin/institucion/logo")
def logo():
    """El logo, para el encabezado y la pantalla. Cualquiera con sesión lo ve."""
    if not validasesion():
        return redirect(url_for("login"))
    real = ruta_logo()
    if not real:
        return "", 404
    respuesta = send_file(real)
    respuesta.headers["Cache-Control"] = "private, max-age=3600"
    return respuesta
