"""
institucion.py — Datos del sindicato (/admin/institucion).

El equivalente de «Parámetros de la Obra Social» de gestion_adm
(`os_parametros`), para un gremio: identificación gremial, datos fiscales,
condición de agente de retención, domicilio, autoridades y logo. Una sola
fila en `s_institucion` (sql/institucion_20261107.sql).

De acá sale el membrete de los documentos (la constancia de reintegro) y el
nombre y el logo del encabezado de todas las pantallas. Y lo que ven las
empresas en su enlace y en su instructivo (instructivo_empresa.py): la cuenta
donde se paga la cuota sindical —una de Tesorería → Cuentas de Fondos— y el
correo y el teléfono para consultas (`pago_cuota`,
sql/institucion_cuota_pago_20261115.sql). `encabezado()` se
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


def cuentas_cuota(cur, actual: int | None = None) -> list[dict]:
    """Las cuentas bancarias habilitadas de Tesorería, para elegir dónde se paga
    la cuota. La elegida entra aunque la hayan deshabilitado después."""
    cur.execute("""
        SELECT f.id, f.nombre, f.numero_de_cuenta AS numero, f.cbu, f.alias, b.nombre AS banco,
               CAST(f.habilitada AS UNSIGNED) AS habilitada
          FROM c_cuentas_de_fondos f
          LEFT JOIN c_codigo_de_banco b ON b.id = f.c_codigo_de_bancoId
         WHERE (f.tipo_de_cuenta = 'B' AND f.habilitada = 1) OR f.id = %s
         ORDER BY f.nombre
    """, (actual or 0,))
    return cur.fetchall()


def pago_cuota(d: dict | None = None) -> dict:
    """Dónde se paga la cuota y a quién consultar, para el portal de las
    empresas y su instructivo:
        cuenta       {nombre, banco, numero, cbu, alias} o None si no se eligió
        titular/cuit los del sindicato
        indicaciones lo que tiene que hacer la empresa al pagar
        email/telefono los de consultas o, si no hay, los generales
        domicilio/web los del sindicato"""
    d = obtener() if d is None else d
    cuenta = None
    if d.get("cuota_cuenta_fondos"):
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cuenta = next((c for c in cuentas_cuota(cur, d["cuota_cuenta_fondos"])
                                   if c["id"] == d["cuota_cuenta_fondos"]), None)
        except pymysql.err.Error:
            cuenta = None
    return {"cuenta": cuenta, "titular": d.get("nombre"), "cuit": d.get("cuit"),
            "indicaciones": d.get("cuota_pago_indicaciones"),
            "email": d.get("cuota_consultas_email") or d.get("email"),
            "telefono": d.get("cuota_consultas_telefono") or d.get("telefono"),
            "domicilio": domicilio_completo(d), "web": d.get("web")}


def domicilio_completo(d: dict) -> str:
    partes = [d.get("domicilio"), d.get("localidad"),
              (f"CP {d['cp']}" if d.get("cp") else None), d.get("provincia_txt")]
    return ", ".join(p for p in partes if p)


# =============================================================================
# Pantalla
# =============================================================================

def _catalogos(actual: int | None = None) -> dict:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT codigo, descripcion FROM arca_responsable_tipo ORDER BY codigo")
            condiciones = cur.fetchall()
            cur.execute("SELECT id, descripcion, alicuota FROM arca_tasa_iva ORDER BY alicuota, codigo")
            tasas = cur.fetchall()
            cur.execute("SELECT codigo, nombre FROM p_provincia ORDER BY nombre")
            provincias = cur.fetchall()
            import recibos_talonario as RT
            talonarios = RT.talonarios(cur) if RT.hay_esquema(cur) else []
            cuentas = cuentas_cuota(cur, actual)
            cur.execute("SELECT id, descripcion FROM c_motivos_de_ingreso WHERE activo = 1 ORDER BY descripcion")
            motivos = cur.fetchall()
    return {"condiciones_iva": condiciones, "tasas_iva": tasas, "provincias": provincias,
            "regimenes_iibb": REGIMENES_IIBB, "talonarios_recibo": talonarios, "cuentas_cuota": cuentas,
            "motivos_ingreso": motivos}


def _leer_form(form, actual_cuenta: int | None = None) -> tuple[dict, list[str]]:
    """Los valores del formulario, validados. Devuelve (valores, errores).
    `actual_cuenta`: la cuenta de la cuota ya guardada, que vale aunque se haya
    deshabilitado en Tesorería."""
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
        # El vencimiento ya no se configura: es el del F.931 del CUIT (fisca_intereses.py).
    if "acta_plazo_dias" in form:
        plazo = (form.get("acta_plazo_dias") or "").strip()
        if plazo and not (plazo.isdigit() and 0 < int(plazo) <= 365):
            errores.append("El plazo para pagar el acta va de 1 a 365 días.")
        v["acta_plazo_dias"] = int(plazo) if plazo.isdigit() else None
        v["acta_lugar_pago"] = (form.get("acta_lugar_pago") or "").strip()[:300] or None
    # Talonarios de los recibos (sql/fisca_recibos_talonarios_20261114.sql).
    if "talonario_recibo_cuota" in form:
        import recibos_talonario as RT
        with get_connection() as conn:
            with conn.cursor() as cur:
                validos = {t["id"]: t for t in RT.talonarios(cur)}
        for campo, rotulo in (("talonario_recibo_cuota", "cuota sindical"), ("talonario_recibo_fisca", "fiscalización")):
            texto = (form.get(campo) or "").strip()
            v[campo] = int(texto) if texto.isdigit() else None
            if v[campo] is None:
                errores.append(f"Elegí el talonario de los recibos de {rotulo}.")
            elif v[campo] not in validos:
                errores.append(f"El talonario de los recibos de {rotulo} no es un talonario de recibos.")
            elif not validos[v[campo]]["habilitado"]:
                errores.append(f"El talonario de los recibos de {rotulo} está deshabilitado.")
        if v.get("talonario_recibo_cuota") and v.get("talonario_recibo_cuota") == v.get("talonario_recibo_fisca"):
            errores.append("Los recibos de cuota sindical y los de fiscalización van en talonarios distintos.")
    # Pago de la cuota y consultas (sql/institucion_cuota_pago_20261115.sql).
    if "cuota_cuenta_fondos" in form:
        errores += _leer_pago_cuota(form, v, actual_cuenta)
    # Recibos a afiliados: la cuota social YMCA (sql/recibos_afiliados_20261115.sql, recibos_afiliado.py).
    if "talonario_recibo_afiliado" in form:
        errores += _leer_recibos_afiliado(form, v)
    return v, errores


def _leer_recibos_afiliado(form, v: dict) -> list[str]:
    """Talonario, motivo, concepto y cuota por mes de los recibos a afiliados."""
    import recibos_talonario as RT
    errores = []
    with get_connection() as conn:
        with conn.cursor() as cur:
            talonarios = {t["id"]: t for t in RT.talonarios(cur)}
            cur.execute("SELECT id FROM c_motivos_de_ingreso WHERE activo = 1")
            motivos = {f["id"] for f in cur.fetchall()}
    texto = (form.get("talonario_recibo_afiliado") or "").strip()
    v["talonario_recibo_afiliado"] = int(texto) if texto.isdigit() else None
    t = talonarios.get(v["talonario_recibo_afiliado"])
    if v["talonario_recibo_afiliado"] is None:
        errores.append("Elegí el talonario de los recibos a afiliados.")
    elif not t:
        errores.append("El talonario de los recibos a afiliados no es un talonario de recibos.")
    elif not t["habilitado"]:
        errores.append("El talonario de los recibos a afiliados está deshabilitado.")
    elif v["talonario_recibo_afiliado"] in (v.get("talonario_recibo_cuota"), v.get("talonario_recibo_fisca")):
        errores.append("Los recibos a afiliados van en un talonario propio, no en el de cuota sindical ni en el de fiscalización.")
    texto = (form.get("recibo_afiliado_motivo") or "").strip()
    v["recibo_afiliado_motivo"] = int(texto) if texto.isdigit() else None
    if v["recibo_afiliado_motivo"] not in motivos:
        errores.append("Elegí el motivo de ingreso de los recibos a afiliados.")
    concepto = re.sub(r"\s+", " ", form.get("recibo_afiliado_concepto") or "").strip()
    if len(concepto) > 100:
        errores.append("El concepto de los recibos a afiliados va hasta 100 caracteres.")
    v["recibo_afiliado_concepto"] = concepto or None
    from pagos_datos import leer_importe
    texto = (form.get("recibo_afiliado_cuota") or "").strip()
    valor = leer_importe(texto) if texto else None
    cuota = Decimal(str(valor)) if valor is not None else None
    if texto and (cuota is None or cuota <= 0):
        errores.append("La cuota por mes de los recibos a afiliados tiene que ser un importe mayor que cero.")
    v["recibo_afiliado_cuota"] = cuota
    return errores


def _leer_pago_cuota(form, v: dict, actual: int | None) -> list[str]:
    """La cuenta donde se paga la cuota y el contacto para consultas. Valida en `v`."""
    errores = []
    texto = (form.get("cuota_cuenta_fondos") or "").strip()
    v["cuota_cuenta_fondos"] = int(texto) if texto.isdigit() else None
    if v["cuota_cuenta_fondos"]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                validas = {c["id"] for c in cuentas_cuota(cur, actual)}
        if v["cuota_cuenta_fondos"] not in validas:
            errores.append("La cuenta para pagar la cuota tiene que ser una cuenta bancaria habilitada de Tesorería.")
    lineas = [re.sub(r"[ \t]+", " ", l).strip() for l in (form.get("cuota_pago_indicaciones") or "").splitlines()]
    indicaciones = "\n".join(l for l in lineas if l)
    if len(indicaciones) > 500:
        errores.append("Las indicaciones para el pago van hasta 500 caracteres.")
    v["cuota_pago_indicaciones"] = indicaciones or None
    email = (form.get("cuota_consultas_email") or "").strip()
    if email and (len(email) > 100 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)):
        errores.append(f"El correo para consultas «{email}» no es válido.")
    v["cuota_consultas_email"] = email or None
    telefono = re.sub(r"\s+", " ", form.get("cuota_consultas_telefono") or "").strip()
    if len(telefono) > 50:
        errores.append("El teléfono para consultas va hasta 50 caracteres.")
    v["cuota_consultas_telefono"] = telefono or None
    return errores


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
        valores, errores = _leer_form(request.form, actual.get("cuota_cuenta_fondos"))
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
                           max_mb=LOGO_MAX_MB, **_catalogos(actual.get("cuota_cuenta_fondos")))


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
