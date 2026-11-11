"""
mis_comprobantes.py — Comprobantes recibidos que informa ARCA («Mis Comprobantes»).

Portado de gestion_adm (mis_comprobantes.py). ARCA no tiene un web service
que liste los comprobantes RECIBIDOS: el WSCDC constata uno que ya se conoce,
no enumera. La vía es el export del portal Mis Comprobantes (Recibidos →
período → Exportar), que esta pantalla importa a `f_mis_comprobantes` y cruza
con lo cargado para saber qué falta.

    pendiente   ARCA lo informa y no tiene expediente
    cargado     tiene comprobante y expediente en la mesa
    ignorado    alguien dijo que no corresponde cargarlo (se puede restaurar)

El parser del archivo es el de gestion_adm, sin cambios: acepta el CSV, el
XLSX o el ZIP tal como lo baja ARCA, con los rótulos de las distintas
versiones del portal.

Lo que no se trajo: la descarga automática desde el portal (con requests da
403: ARCA exige un token que el portal arma con JavaScript) y la visibilidad
por áreas. Se importa el archivo a mano.

Permiso: la opción de menú «Comprobantes ARCA» (/comprobantes/arca).
"""
from __future__ import annotations

import csv
import datetime
import io
import logging
import re

from flask import Blueprint, flash, redirect, render_template, request, url_for

import comprobantes_datos as cd
from db import get_connection, puede, validasesion

log = logging.getLogger(__name__)

mis_comp_bp = Blueprint("mis_comp", __name__, url_prefix="/comprobantes/arca")

#: Cargado = con comprobante Y con expediente: sin expediente no entró a
#: ningún circuito (gestion_adm). Una sola definición para grilla y totales.
SQL_CARGADO = ("m.id_comprobante IS NOT NULL"
               " AND EXISTS (SELECT 1 FROM me_expedientes x WHERE x.id_comprobante = m.id_comprobante)")
SQL_PENDIENTE = f"NOT ({SQL_CARGADO}) AND m.ignorado = 0"
#: Una nota de crédito resta: el TIPO manda el signo (alias `t` = arca_tipo_comprobante).
SQL_CREDITO = "(t.descripcion LIKE 'Nota de Cr%dito%')"


def puede_ver() -> bool:
    return puede(url_for("mis_comp.listado"))


# ─────────────────────────────────────────────────────────────────────────────
# Parseo del export (gestion_adm, sin cambios)
# ─────────────────────────────────────────────────────────────────────────────

# El portal cambia rótulos según la versión y el navegador; se aceptan
# variantes y se normaliza sin acentos ni mayúsculas.
COLUMNAS = {
    "fecha":      ("fecha de emision", "fecha", "fecha emision"),
    "tipo":       ("tipo de comprobante", "tipo", "tipo comp", "tipo comprobante"),
    "pto_vta":    ("punto de venta", "pto venta", "punto venta", "pto de venta"),
    "numero":     ("numero desde", "numero", "nro", "numero de comprobante",
                   "nro comprobante", "comprobante desde"),
    "cuit":       ("nro doc emisor", "cuit emisor", "nro documento emisor",
                   "documento emisor", "nro doc vendedor", "cuit"),
    "razon":      ("denominacion emisor", "razon social emisor", "denominacion",
                   "razon social", "denominacion vendedor"),
    # Ojo: el export trae una columna de neto por alícuota ("Imp. Neto
    # Gravado IVA 21%", etc.) además del total. Acá se busca el TOTAL —
    # el match es por nombre exacto, así que las parciales no interfieren.
    "neto":       ("imp neto gravado total", "imp neto gravado",
                   "neto gravado", "importe neto gravado"),
    "no_grav":    ("imp neto no gravado", "neto no gravado", "importe neto no gravado"),
    "exento":     ("imp op exentas", "op exentas", "importe exento", "exento"),
    "iva":        ("total iva", "iva", "imp iva", "importe iva"),
    "otros":      ("otros tributos", "imp trib", "importe otros tributos", "otros trib"),
    "total":      ("imp total", "importe total", "total"),
    "moneda":     ("moneda",),
    "tipo_cambio":("tipo cambio", "tipo de cambio"),
    "cae":        ("cod autorizacion", "codigo de autorizacion", "cae", "cae/caea"),
}

_ACENTOS = str.maketrans("áéíóúÁÉÍÓÚñÑ", "aeiouAEIOUnN")


def _norm(s):
    s = (s or "").strip().translate(_ACENTOS).lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _mapear_encabezado(fila):
    """Devuelve {clave_interna: indice_columna} a partir del encabezado."""
    encabezado = [_norm(c) for c in fila]
    mapa = {}
    for clave, alias in COLUMNAS.items():
        for i, col in enumerate(encabezado):
            if col in alias:
                mapa[clave] = i
                break
    return mapa


def _dec(v):
    """'1.234,56' o '1234.56' → float. Vacío → 0."""
    s = (v or "").strip().replace("$", "").replace(" ", "")
    if not s:
        return 0.0
    if "," in s:                       # formato AR: el punto es de miles
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _fecha(v):
    s = (v or "").strip()[:10]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


_MONEDAS = {"$": "PES", "ARS": "PES", "PESOS": "PES",
            "US$": "DOL", "USD": "DOL", "U$S": "DOL"}


def _moneda(v):
    s = (v or "").strip().upper()
    if not s:
        return "PES"
    return _MONEDAS.get(s, s[:3])


def _cod_tipo(v):
    """'1 - Factura A' o '001' o '1' → '001'."""
    s = (v or "").strip()
    m = re.match(r"\s*(\d{1,3})", s)
    return m.group(1).zfill(3) if m else None


def _filas_del_archivo(archivo):
    """Itera las filas del CSV o XLSX subido, o del ZIP que los contiene."""
    nombre = (archivo.filename or "").lower()
    contenido = archivo.read()

    # ARCA entrega la exportación comprimida: el ZIP trae un único CSV con
    # el nombre largo de la consulta. Se acepta el .zip tal como se baja.
    if nombre.endswith(".zip") or contenido[:2] == b"PK":
        import zipfile
        with zipfile.ZipFile(io.BytesIO(contenido)) as z:
            internos = [n for n in z.namelist()
                        if n.lower().endswith((".csv", ".txt", ".xlsx", ".xlsm"))]
            if not internos:
                raise ValueError(
                    "El ZIP no contiene ningún CSV ni XLSX. "
                    f"Trae: {', '.join(z.namelist()) or '(vacío)'}"
                )
            nombre = internos[0].lower()
            contenido = z.read(internos[0])

    if nombre.endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
        hoja = wb[wb.sheetnames[0]]
        for fila in hoja.iter_rows(values_only=True):
            yield ["" if c is None else str(c) for c in fila]
        wb.close()
        return

    # CSV: el portal exporta en latin-1 y a veces con ';'
    for enc in ("utf-8-sig", "latin-1"):
        try:
            texto = contenido.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        texto = contenido.decode("latin-1", errors="replace")

    muestra = texto[:4096]
    sep = ";" if muestra.count(";") > muestra.count(",") else ","
    for fila in csv.reader(io.StringIO(texto), delimiter=sep):
        yield fila


def parsear_export(archivo):
    """
    Devuelve (registros, errores). Cada registro es un dict listo para
    insertar en f_mis_comprobantes.
    """
    registros, errores = [], []
    mapa = None
    nro_fila = 0

    for fila in _filas_del_archivo(archivo):
        nro_fila += 1
        if not any((c or "").strip() for c in fila):
            continue

        if mapa is None:
            posible = _mapear_encabezado(fila)
            # Encabezado válido: al menos la clave natural y el total
            if all(k in posible for k in ("fecha", "tipo", "pto_vta", "numero",
                                          "cuit", "total")):
                mapa = posible
            continue

        def col(clave):
            i = mapa.get(clave)
            return fila[i] if i is not None and i < len(fila) else ""

        cuit = re.sub(r"\D", "", col("cuit"))
        tipo = _cod_tipo(col("tipo"))
        pv   = re.sub(r"\D", "", col("pto_vta"))
        nro  = re.sub(r"\D", "", col("numero"))
        fch  = _fecha(col("fecha"))

        if not (cuit and tipo and pv and nro and fch):
            errores.append(f"Fila {nro_fila}: datos incompletos, se omite.")
            continue
        if len(cuit) != 11:
            errores.append(f"Fila {nro_fila}: CUIT inválido ({cuit}), se omite.")
            continue

        registros.append({
            "fecha_emision":    fch,
            "tipo_comprobante": tipo,
            "punto_de_venta":   pv.zfill(5),
            "numero":           nro.zfill(8),
            "cuit_emisor":      cuit,
            "razon_social":     (col("razon") or "").strip()[:200] or None,
            "importe_neto":     _dec(col("neto")),
            "importe_no_grav":  _dec(col("no_grav")),
            "importe_exento":   _dec(col("exento")),
            "importe_iva":      _dec(col("iva")),
            "importe_otros":    _dec(col("otros")),
            "importe_total":    _dec(col("total")),
            # El export usa el símbolo ($) donde el resto del sistema usa el
            # código ISO de ARCA (PES).
            "moneda":           _moneda(col("moneda")),
            "tipo_de_cambio":   _dec(col("tipo_cambio")) or 1,
            "cae":              re.sub(r"\D", "", col("cae"))[:14] or None,
            "nombre_archivo":   (archivo.filename or "")[:200],
        })

    if mapa is None:
        errores.append(
            "No se reconoció el encabezado del archivo. Verificá que sea el "
            "export de Mis Comprobantes (CSV o XLSX) sin filas agregadas arriba."
        )
    return registros, errores


# ─────────────────────────────────────────────────────────────────────────────
# Pantalla
# ─────────────────────────────────────────────────────────────────────────────

def _guardar_registros(cur, registros) -> tuple[int, int]:
    """Alta o actualización en f_mis_comprobantes y vínculo con lo cargado.
    Devuelve (nuevos, actualizados)."""
    nuevos = actualizados = 0
    for r in registros:
        cur.execute("""
            INSERT INTO f_mis_comprobantes
              (fecha_emision, tipo_comprobante, punto_de_venta, numero, cuit_emisor, razon_social,
               importe_neto, importe_no_grav, importe_exento, importe_iva, importe_otros,
               importe_total, moneda, tipo_de_cambio, cae, nombre_archivo)
            VALUES (%(fecha_emision)s, %(tipo_comprobante)s, %(punto_de_venta)s, %(numero)s,
                    %(cuit_emisor)s, %(razon_social)s, %(importe_neto)s, %(importe_no_grav)s,
                    %(importe_exento)s, %(importe_iva)s, %(importe_otros)s, %(importe_total)s,
                    %(moneda)s, %(tipo_de_cambio)s, %(cae)s, %(nombre_archivo)s)
            ON DUPLICATE KEY UPDATE
               fecha_emision = VALUES(fecha_emision), razon_social = VALUES(razon_social),
               importe_neto = VALUES(importe_neto), importe_no_grav = VALUES(importe_no_grav),
               importe_exento = VALUES(importe_exento), importe_iva = VALUES(importe_iva),
               importe_otros = VALUES(importe_otros), importe_total = VALUES(importe_total),
               cae = VALUES(cae), nombre_archivo = VALUES(nombre_archivo)
        """, r)
        # 1 = fila nueva, 2 = actualizada con cambios, 0 = igual.
        if cur.rowcount == 1:
            nuevos += 1
        elif cur.rowcount == 2:
            actualizados += 1
    cd.vincular_mis(cur)
    cd.vincular_mis_por_numero(cur)
    # Lo vinculado —por la carga o por esta importación— queda con la
    # verificación ARCA: ARCA lo informa como recibido.
    cd.marcar_verificacion_mis(cur)
    return nuevos, actualizados


@mis_comp_bp.route("", methods=["GET", "POST"])
def listado():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede_ver():
        flash("!No tenés permiso para Comprobantes ARCA.")
        return redirect(url_for("menu"))

    errores = []
    if request.method == "POST":
        archivo = request.files.get("archivo")
        if not archivo or not archivo.filename:
            errores.append("Elegí el archivo exportado de Mis Comprobantes.")
        elif not archivo.filename.lower().endswith((".csv", ".txt", ".xlsx", ".xlsm", ".zip")):
            errores.append("El archivo tiene que ser el .zip que baja ARCA, o el .csv o .xlsx de adentro.")
        else:
            try:
                registros, avisos = parsear_export(archivo)
            except ImportError:
                registros, avisos = [], ["Para leer un .xlsx hace falta openpyxl (pip install openpyxl). "
                                         "El .zip o el .csv que baja ARCA no lo necesitan."]
            except Exception as e:                           # noqa: BLE001
                log.exception("Mis Comprobantes: %s", archivo.filename)
                registros, avisos = [], [f"No se pudo leer el archivo: {e}"]
            errores += avisos[:12] + ([f"…y {len(avisos) - 12} avisos más."] if len(avisos) > 12 else [])
            if registros:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        conn.begin()
                        nuevos, act = _guardar_registros(cur, registros)
                        conn.commit()
                flash(f"Se procesaron {len(registros)} comprobantes de {archivo.filename}: "
                      f"{nuevos} nuevos, {act} actualizados y {len(registros) - nuevos - act} que ya estaban.")
                for a in avisos[:5]:
                    flash("!" + a)
                return redirect(url_for("mis_comp.listado"))

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT m.*, t.descripcion AS tipo_desc,
                       p.id AS id_proveedor, p.razon_social AS proveedor, p.nombre_fantasia, p.activo AS prov_activo,
                       e.id AS id_expediente, e.nro_expediente, e.estado AS estado_exp,
                       ({SQL_CARGADO}) AS cargado,
                       c.constatacion_resultado, c.leido_automatico
                  FROM f_mis_comprobantes m
                  LEFT JOIN arca_tipo_comprobante t ON t.codigo = m.tipo_comprobante
                  LEFT JOIN c_proveedores p ON p.cuit = m.cuit_emisor
                  LEFT JOIN me_expedientes e ON e.id_comprobante = m.id_comprobante
                  LEFT JOIN f_comprobantes_arca c ON c.id = m.id_comprobante
                 ORDER BY m.fecha_emision DESC, m.cuit_emisor, m.numero
            """)
            filas = cur.fetchall()
            cur.execute(f"""
                SELECT COUNT(*) AS total, COALESCE(SUM({SQL_CARGADO}), 0) AS cargados,
                       COALESCE(SUM({SQL_PENDIENTE}), 0) AS pendientes,
                       COALESCE(SUM(m.ignorado = 1 AND NOT ({SQL_CARGADO})), 0) AS ignorados,
                       COALESCE(SUM(CASE WHEN {SQL_PENDIENTE} THEN
                                CASE WHEN {SQL_CREDITO} THEN -m.importe_total ELSE m.importe_total END
                                END), 0) AS importe_pendiente,
                       COALESCE(SUM(CASE WHEN {SQL_PENDIENTE} AND NOT EXISTS
                                     (SELECT 1 FROM c_proveedores pp WHERE pp.cuit = m.cuit_emisor)
                                THEN 1 END), 0) AS sin_alta,
                       MAX(m.importado) AS ultima, MIN(m.fecha_emision) AS desde, MAX(m.fecha_emision) AS hasta
                  FROM f_mis_comprobantes m
                  LEFT JOIN arca_tipo_comprobante t ON t.codigo = m.tipo_comprobante
            """)
            resumen = cur.fetchone()
            tipos = sorted({(f["tipo_comprobante"], f["tipo_desc"] or f["tipo_comprobante"]) for f in filas})
    for f in filas:
        f["estado_mis"] = "cargado" if f["cargado"] else ("ignorado" if f["ignorado"] else "pendiente")
    return render_template("comprobantes/mis_comprobantes.html", filas=filas, resumen=resumen,
                           tipos=tipos, errores=errores, puede_cargar=puede(url_for("comprobantes.carga")),
                           puede_mesa=puede(url_for("mesa.bandeja")),
                           puede_alta_prov=puede(url_for("proveedores.abm")))


@mis_comp_bp.route("/<int:id_mis>/ignorar", methods=["POST"])
def ignorar(id_mis):
    """Descarta un pendiente (no corresponde cargarlo) o lo restaura."""
    if not validasesion():
        return redirect(url_for("login"))
    if not puede_ver():
        flash("!No tenés permiso para Comprobantes ARCA.")
        return redirect(url_for("menu"))
    restaurar = bool(request.form.get("restaurar"))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE f_mis_comprobantes SET ignorado = %s WHERE id = %s AND id_comprobante IS NULL",
                        (0 if restaurar else 1, id_mis))
            hecho = cur.rowcount
        conn.commit()
    if hecho:
        flash("Comprobante restaurado: vuelve a figurar como pendiente." if restaurar
              else "Comprobante descartado: no figura más como pendiente. Se puede restaurar.")
    else:
        flash("!No se cambió nada: el comprobante no existe o ya está cargado.")
    return redirect(url_for("mis_comp.listado"))
