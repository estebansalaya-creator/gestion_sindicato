"""
empleadores.py — ABM de empleadores (`p_empresas`).

Sigue el ABM de empresas de `gestion_adm` en estructura y en pantalla, con dos
diferencias obligadas y una de convención:

1. **Sin validación contra ARCA.** El original exige consultar el CUIT en el
   padrón de ARCA antes de guardar, contra `/api/consultar_cuit/`. Ese servicio
   vive en `gestion_adm` con sus credenciales, y la nómina ARCA está fuera del
   alcance de este proyecto. Acá el CUIT se valida por dígito verificador, que
   no depende de ningún servicio: no confirma que la empresa exista, pero
   descarta los CUIT mal tipeados, que es la mayoría de los errores de carga.
2. **Contactos en su propia solapa**, con el parcial `_contactos.html` y la
   lógica de `contactos.py` —los mismos que usa afiliados—.
3. La edición entra por `?edit=<id>` y no por `?id=<id>`, que es la convención
   escrita de este proyecto.
"""

from datetime import date

from flask import (Blueprint, render_template, request,
                   redirect, url_for, session, flash)

import contactos as _contactos
import contable_oseda
from db import get_connection, puede, validasesion

empleadores_bp = Blueprint("empleadores", __name__, template_folder="templates")


# Los once campos que se repiten en el domicilio legal (`dom_`) y en el fiscal
# (`fdom_`). Se listan una vez y se recorren con el prefijo: son 22 columnas y
# escribirlas a mano es garantía de que alguna quede afuera.
DOM_CAMPOS = [
    "provincia_id", "provincia_nombre",
    "departamento_id", "departamento_nombre",
    "localidad_id", "localidad_nombre",
    "calle", "numero", "piso", "depto", "cp",
]


def cuit_valido(cuit: str) -> bool:
    """
    Verifica el dígito verificador del CUIT (módulo 11).

    El último dígito se calcula desde los otros diez, así que un CUIT con un
    número cambiado o dos transpuestos casi siempre falla la cuenta. No prueba
    que la empresa exista —para eso hace falta ARCA— pero corta los errores de
    tipeo antes de que entren a la base.
    """
    if len(cuit) != 11 or not cuit.isdigit():
        return False
    pesos = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    suma = sum(int(d) * p for d, p in zip(cuit[:10], pesos))
    resto = suma % 11
    verificador = 0 if resto == 0 else (9 if resto == 1 else 11 - resto)
    return verificador == int(cuit[10])


def _provincias(cur) -> list[dict]:
    cur.execute("SELECT codigo, nombre FROM p_provincia ORDER BY nombre")
    return cur.fetchall()


def _empleador(cur, emp_id) -> dict | None:
    """
    Un empleador por id, con `Activo` ya convertido a entero.

    El CAST no es cosmético: `Activo` es `bit(1)` y PyMySQL lo devuelve como
    `b'\\x00'` o `b'\\x01'`. Los dos son bytes de longitud 1, y en Python
    cualquier bytes no vacío es verdadero — así que `{% if e.Activo %}` da
    verdadero también para los inactivos. Resolverlo en el SELECT evita tener
    que acordarse en cada plantilla.
    """
    cur.execute("""
        SELECT id, CUIT, razon_social, nombre_fantasia, telefonos, email,
               observaciones, CAST(Activo AS UNSIGNED) AS Activo,
               dom_provincia_id, dom_provincia_nombre,
               dom_departamento_id, dom_departamento_nombre,
               dom_localidad_id, dom_localidad_nombre,
               dom_calle, dom_numero, dom_piso, dom_depto, dom_cp,
               fdom_provincia_id, fdom_provincia_nombre,
               fdom_departamento_id, fdom_departamento_nombre,
               fdom_localidad_id, fdom_localidad_nombre,
               fdom_calle, fdom_numero, fdom_piso, fdom_depto, fdom_cp
        FROM p_empresas WHERE id = %s
    """, (emp_id,))
    return cur.fetchone()


def _anios(desde: date | None, hasta: date) -> int | None:
    """Años cumplidos entre dos fechas: la antigüedad que se cuenta, no la redondeada."""
    if not desde:
        return None
    return hasta.year - desde.year - ((hasta.month, hasta.day) < (desde.month, desde.day))


def _nomina(cur, empleador: dict) -> tuple[list[dict], str | None]:
    """
    Nómina del empleador: sus relaciones laborales (`p_relaciones_laborales`)
    con la última DDJJ de OSEDA de cada empleado para ESTE CUIT.

    Activo = relación `activa` sin egreso o con egreso de hoy en adelante, la
    misma regla de «vigente» de la solapa Empleadores del afiliado. La relación
    importada de AEDA no trae egreso: si está inactiva y no tiene `fecha_fin`,
    la fecha de baja que se muestra es la del afiliado, que es de donde salió
    el estado (se marca `baja_del_afiliado` para decirlo en pantalla).

    La DDJJ se consulta en vivo en `contable` de Railway (contable_oseda.py,
    conexión de solo lectura) y se cruza acá por CUIL. Si Railway no está
    disponible la nómina se muestra igual, sin DDJJ, y `aviso` dice por qué.
    Devuelve (filas, aviso).
    """
    hoy = date.today()
    cur.execute("""
        SELECT r.id_relacion, r.cuil, r.fecha_inicio, r.fecha_fin, r.estado,
               a.id_afiliado, a.apellido_nombres, a.fecha_baja AS afiliado_baja
          FROM p_relaciones_laborales r
          LEFT JOIN p_afiliados a ON a.cuil = r.cuil
         WHERE r.id_empleador = %s
            OR (r.id_empleador IS NULL AND r.cuit_empleador = %s)
         ORDER BY a.apellido_nombres, r.fecha_inicio
    """, (empleador["id"], str(empleador["CUIT"])))
    filas = cur.fetchall()

    ddjj, aviso = {}, None
    if filas:
        try:
            ddjj = contable_oseda.ultima_ddjj_por_cuil(str(empleador["CUIT"]))
        except contable_oseda.ContableNoDisponible as e:
            aviso = f"No se muestran las DDJJ de OSEDA. {e}"

    for f in filas:
        d = ddjj.get(f["cuil"]) or {}
        f["ultimo_periodo"] = d.get("ultimo_periodo")
        f["rem5_ultimo"] = d.get("rem5")
        f["activo"] = f["estado"] == "activa" and (f["fecha_fin"] is None or f["fecha_fin"] >= hoy)
        f["baja_del_afiliado"] = False
        f["fecha_baja"] = f["fecha_fin"]
        if not f["activo"] and f["fecha_baja"] is None and f["afiliado_baja"]:
            f["fecha_baja"] = f["afiliado_baja"]
            f["baja_del_afiliado"] = True
        hasta = f["fecha_baja"] if (not f["activo"] and f["fecha_baja"]) else hoy
        f["antiguedad"] = _anios(f["fecha_inicio"], hasta)
    return filas, aviso


@empleadores_bp.route("/empleadores", methods=["GET", "POST"])
def abm_empleadores():
    if not validasesion():
        return redirect(url_for("login"))

    errores = []
    empleador = None

    if request.method == "POST":
        accion = request.form.get("accion", "")
        emp_id = (request.form.get("id") or "").strip()

        if accion == "borrar" and emp_id:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM p_empresas WHERE id = %s", (emp_id,))
            flash("Empleador eliminado.")
            return redirect(url_for("empleadores.abm_empleadores"))

        if accion in ("guardar", "nuevo"):
            def campo(nombre):
                return request.form.get(nombre, "").strip() or None

            # Se aceptan guiones y puntos al pegar desde una constancia y se
            # limpian acá: rechazar «30-71188440-4» por el formato obliga a
            # reescribir a mano un dato que ya está bien.
            cuit = "".join(c for c in request.form.get("CUIT", "") if c.isdigit())
            razon_social    = request.form.get("razon_social", "").strip()
            nombre_fantasia = request.form.get("nombre_fantasia", "").strip()
            activo          = 1 if request.form.get("Activo") else 0

            if not cuit:
                errores.append("El CUIT es obligatorio.")
            elif not cuit_valido(cuit):
                errores.append(
                    f"El CUIT {cuit} no es válido: no verifica el dígito de control. "
                    "Revisá que no falte ni sobre un número."
                )
            if not razon_social:
                errores.append("La razón social es obligatoria.")

            if cuit and not errores:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        if accion == "nuevo":
                            cur.execute(
                                "SELECT id, razon_social FROM p_empresas WHERE CUIT = %s",
                                (cuit,)
                            )
                        else:
                            cur.execute(
                                "SELECT id, razon_social FROM p_empresas "
                                "WHERE CUIT = %s AND id <> %s",
                                (cuit, emp_id)
                            )
                        duplicado = cur.fetchone()
                if duplicado:
                    errores.append(
                        f"El CUIT ya está cargado como «{duplicado['razon_social']}»."
                    )

            if not errores:
                valores = {
                    "CUIT":            cuit,
                    "razon_social":    razon_social,
                    # NOT NULL en la tabla: va cadena vacía, nunca None.
                    "nombre_fantasia": nombre_fantasia,
                    "telefonos":       campo("telefonos"),
                    "email":           campo("email"),
                    "observaciones":   campo("observaciones"),
                    "Activo":          activo,
                }
                for prefijo in ("dom", "fdom"):
                    for c in DOM_CAMPOS:
                        valores[f"{prefijo}_{c}"] = campo(f"{prefijo}_{c}")

                columnas = ", ".join(f"`{k}`" for k in valores)
                marcadores = ", ".join(["%s"] * len(valores))

                with get_connection() as conn:
                    with conn.cursor() as cur:
                        if accion == "nuevo":
                            cur.execute(
                                f"INSERT INTO p_empresas ({columnas}) VALUES ({marcadores})",
                                list(valores.values())
                            )
                            flash(f"Empleador «{razon_social}» creado.")
                        else:
                            asignaciones = ", ".join(f"`{k}` = %s" for k in valores)
                            cur.execute(
                                f"UPDATE p_empresas SET {asignaciones} WHERE id = %s",
                                list(valores.values()) + [emp_id]
                            )
                            flash(f"Empleador «{razon_social}» actualizado.")
                return redirect(url_for("empleadores.abm_empleadores"))

            # Con errores se devuelve lo tipeado, no lo que hay en la base: si
            # alguien cargó veinte campos y erró el CUIT, perder los otros
            # diecinueve es peor que el error.
            empleador = {
                "id": emp_id, "CUIT": cuit, "razon_social": razon_social,
                "nombre_fantasia": nombre_fantasia, "Activo": activo,
                "telefonos": request.form.get("telefonos", ""),
                "email": request.form.get("email", ""),
                "observaciones": request.form.get("observaciones", ""),
            }
            for prefijo in ("dom", "fdom"):
                for c in DOM_CAMPOS:
                    empleador[f"{prefijo}_{c}"] = request.form.get(f"{prefijo}_{c}", "")

    with get_connection() as conn:
        with conn.cursor() as cur:
            edit_id = (request.args.get("edit") or "").strip()
            if edit_id and empleador is None:
                empleador = _empleador(cur, edit_id)
                if empleador is None:
                    flash("Ese empleador no existe.")

            provincias = _provincias(cur)
            aviso_ddjj = None

            # Los contactos solo tienen sentido con el empleador ya creado: se
            # cuelgan de su id, y en el alta todavía no hay id del cual colgar.
            # El parcial se dibuja únicamente en edición.
            contactos_emp = []
            nomina = []
            # Solapa «Cuota sindical»: el enlace de la empresa para presentar su
            # Libro de Sueldos Digital y lo que presentó (fisca_lsd.py). Solo
            # para quien tiene Presentaciones LSD en el menú.
            cuota = None
            enlace_nuevo = None
            areas_contacto = _contactos.areas(cur)
            if empleador and empleador.get("id"):
                contactos_emp = _contactos.de(cur, "empresa", empleador["id"])
                if empleador.get("CUIT"):
                    nomina, aviso_ddjj = _nomina(cur, empleador)
                    if puede(url_for("fisca_lsd.lista")):
                        import fisca_lsd
                        cuota = fisca_lsd.datos_empleador(cur, empleador)
                        nuevo = session.pop("sind_enlace_nuevo", None)
                        if nuevo and str(nuevo.get("id_empresa")) == str(empleador["id"]):
                            enlace_nuevo = {"url": nuevo["url"],
                                            "mailto": fisca_lsd.mailto(empleador, cuota.get("emails", []),
                                                                       nuevo["url"], fisca_lsd._institucion())}

            # Sin paginación del lado del servidor: son 2.854 filas y el JS de
            # base.html ya pagina, filtra y ordena en el navegador. Traer todo
            # de una es lo que hace que el filtro responda sin ir a la base.
            cur.execute("""
                SELECT e.id, e.CUIT, e.razon_social, e.nombre_fantasia,
                       e.dom_localidad_nombre, e.dom_provincia_nombre,
                       CAST(e.Activo AS UNSIGNED) AS Activo,
                       COALESCE(MAX(ra.activos), 0) AS activos,
                       COUNT(DISTINCT c.cuil) AS empleados
                FROM p_empresas e
                LEFT JOIN fisca_cuotarecepcion c
                       ON c.cuit REGEXP '^[0-9]+$'
                      AND CAST(c.cuit AS UNSIGNED) = e.CUIT
                -- Empleados activos: afiliados con relación laboral vigente
                -- (`activa`, sin egreso o con egreso de hoy en adelante), la
                -- misma regla que la solapa Nómina. Las relaciones sin
                -- id_empleador se atan por CUIT, como en afiliados.py.
                LEFT JOIN (
                    SELECT COALESCE(r.id_empleador, e2.id) AS id_emp,
                           COUNT(DISTINCT r.cuil) AS activos
                      FROM p_relaciones_laborales r
                      LEFT JOIN p_empresas e2
                             ON r.id_empleador IS NULL
                            AND r.cuit_empleador REGEXP '^[0-9]+$'
                            AND e2.CUIT = CAST(r.cuit_empleador AS UNSIGNED)
                     WHERE r.estado = 'activa'
                       AND (r.fecha_fin IS NULL OR r.fecha_fin >= CURDATE())
                     GROUP BY id_emp
                ) ra ON ra.id_emp = e.id
                GROUP BY e.id
                ORDER BY activos DESC, e.razon_social
            """)
            empleadores = cur.fetchall()

    return render_template(
        "empleadores/abm_empleadores.html",
        empleadores=empleadores,
        empleador=empleador,
        provincias=provincias,
        contactos=contactos_emp,
        nomina=nomina,
        aviso_ddjj=aviso_ddjj,
        cuota=cuota,
        enlace_nuevo=enlace_nuevo,
        solapa=request.args.get("solapa"),
        areas_contacto=areas_contacto,
        errores=errores,
    )
