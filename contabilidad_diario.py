"""
contabilidad_diario.py — Contabilidad › Asientos (menú 93) y Libro Diario (menú 94).

    /contabilidad/diario                 el libro: ?ejercicio (por defecto el de trabajo), ?periodo, ?estado, ?tipo,
                                         ?desde, ?hasta
    /contabilidad/diario/<id>            un asiento con sus renglones
    /contabilidad/diario/accion          POST accion=confirmar|borrar (id) · confirmar_todos (los borradores del filtro)
    /contabilidad/asientos               carga: ?edit=ID corrige un borrador, ?copiar=ID parte de otro; POST graba
    /contabilidad/diario/exportar        ?formato=xlsx|csv: los asientos confirmados del filtro, con las columnas
                                         del archivo de importación
    /contabilidad/diario/libro           ?formato=xlsx|pdf: el Libro Diario del filtro (sin anulados)
    /contabilidad/diario/externo         ?desde&hasta: los confirmados en el formato del sistema contable externo
    /contabilidad/diario/modelo          ?formato=xlsx|csv: el modelo para importar
    /contabilidad/diario/importar        POST archivo: asientos desde un .xlsx o .csv (quedan en borrador)
    /contabilidad/diario/renumerar       POST: renumera el ejercicio del filtro

Pedido del 18/11/2026: el Libro Diario «con las mismas opciones que OSEDA»
(gestion_adm/contable.py: asientos, exportar_asientos, exportar_diario,
exportar_asientos_externo, descargar_ejemplo_asientos, importar_asientos,
renumerar_asientos), con el sistema de estilos de acá. Las reglas están en
asientos.py. Diferencias con gestion_adm:

- Consulta y carga por separado, como el padrón: el Diario es la opción 94
  (mirar, exportar) y la carga, la 93 «Asientos» (nuevo, corregir, confirmar,
  eliminar un borrador, importar, renumerar). El permiso es la opción de menú.
- El período sale de la fecha y tiene que estar abierto; la numeración es por
  ejercicio también en la carga a mano.
- Lo importado desde un archivo queda en BORRADOR (en gestion_adm el aviso
  decía borrador y lo grababa confirmado); «Confirmar los borradores» confirma
  los del filtro de una vez.
- Anular un asiento confirmado está en Contabilidad › Anulaciones en
  gestion_adm; acá todavía no hay esa pantalla. Tampoco el «Libro de trabajo»
  (los asientos que generarían las operaciones): pendiente.
"""

from __future__ import annotations

import csv
import datetime
import io
from decimal import Decimal

from flask import Blueprint, Response, flash, redirect, render_template, request, send_file, url_for

import asientos as A
import exportar
import exportar_contable_externo as EXT
import institucion
import tesoreria
from db import get_connection, puede, usuario_actual, validasesion

cont_diario_bp = Blueprint("cont_diario", __name__, url_prefix="/contabilidad")

URL_DIARIO = "/contabilidad/diario"
URL_CARGA = "/contabilidad/asientos"
TOPE = 5000
FILTROS = ("ejercicio", "periodo", "estado", "tipo", "desde", "hasta")


def _guardia(url):
    if not validasesion():
        return redirect(url_for("login"))
    if not puede(url):
        flash("!No tenés permiso para esa pantalla.")
        return redirect(url_for("menu"))
    return None


def _usuario() -> str:
    u = usuario_actual() or {}
    return (u.get("email") or u.get("nombre") or "")[:80]


def _num(v) -> str:
    """1234.5 → «1.234,50» (el formato que exportar.xlsx lee como número)."""
    entero, _, dec = f"{float(v or 0):,.2f}".partition(".")
    return f"{entero.replace(',', '.')},{dec}"


def _fecha_arg(v):
    try:
        return datetime.date.fromisoformat((v or "").strip()) if v else None
    except ValueError:
        return None


def filtros(cur, args) -> dict:
    """Los filtros de la URL. Sin ejercicio, el de trabajo; «todos» lo saca."""
    f = {k: (args.get(k) or "").strip() for k in FILTROS}
    if not f["ejercicio"]:
        act = A.ejercicio_activo(cur)
        f["ejercicio"] = str(act["id_ejercicio"]) if act else ""
    elif f["ejercicio"] == "todos":
        f["ejercicio"] = ""
    for k in ("ejercicio", "periodo"):
        f[k] = f[k] if f[k].isdigit() else ""
    f["estado"] = f["estado"] if f["estado"] in A.ESTADOS else ""
    f["tipo"] = f["tipo"] if f["tipo"] in A.TIPOS else ""
    for k in ("desde", "hasta"):
        d = _fecha_arg(f[k])
        f[k] = d.isoformat() if d else ""
    return f


def _args(f: dict) -> dict:
    """Los filtros para url_for (sin vacíos; el ejercicio vacío es «todos»)."""
    d = {k: v for k, v in f.items() if v and k in FILTROS}
    if not f.get("ejercicio"):
        d["ejercicio"] = "todos"
    return d


def _titulo(cur, f: dict) -> str:
    """«Ejercicio 2025 · Marzo 2025 · confirmados» para los encabezados."""
    partes = []
    if f.get("ejercicio"):
        cur.execute("SELECT nombre FROM c_ejercicios WHERE id_ejercicio = %s", (f["ejercicio"],))
        e = cur.fetchone()
        partes.append(e["nombre"] if e else "")
    if f.get("periodo"):
        cur.execute("SELECT nombre FROM c_periodos WHERE id_periodo = %s", (f["periodo"],))
        p = cur.fetchone()
        partes.append(p["nombre"] if p else "")
    if f.get("desde") or f.get("hasta"):
        partes.append(f"{_dmy(f.get('desde')) or '…'} al {_dmy(f.get('hasta')) or '…'}")
    if f.get("estado"):
        partes.append(A.ESTADOS[f["estado"]][0].lower())
    return " · ".join(x for x in partes if x) or "Todos los ejercicios"


def _dmy(iso) -> str:
    d = _fecha_arg(iso)
    return d.strftime("%d/%m/%Y") if d else ""


def _nombre_archivo(base: str, f: dict, ext: str) -> str:
    sufijo = "_".join(x for x in (f.get("desde"), f.get("hasta")) if x)
    return f"{base}{('_' + sufijo) if sufijo else ''}.{ext}"


# =============================================================================
# El libro
# =============================================================================

@cont_diario_bp.route("/diario")
def diario():
    salida = _guardia(URL_DIARIO)
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            f = filtros(cur, request.args)
            filas, excedido = A.listar(cur, f, TOPE)
            ejs = A.ejercicios(cur)
            pers = A.periodos(cur, f["ejercicio"] or None)
            titulo = _titulo(cur, f)
            ej = next((e for e in ejs if str(e["id_ejercicio"]) == f["ejercicio"]), None)
    tot = {"asientos": len(filas),
           "confirmados": sum(1 for a in filas if a["estado"] == "confirmado"),
           "borradores": sum(1 for a in filas if a["estado"] == "borrador"),
           "debe": sum((Decimal(str(a["total_debe"])) for a in filas if a["estado"] == "confirmado"), Decimal("0")),
           "descuadrados": sum(1 for a in filas if a["estado"] != "anulado"
                               and Decimal(str(a["total_debe"])) != Decimal(str(a["total_haber"])))}
    return render_template("contabilidad/diario.html", filas=filas, excedido=excedido, tope=TOPE, f=f,
                           args=_args(f), ejercicios=ejs, periodos=pers, ej=ej, titulo=titulo, tot=tot,
                           estados=A.ESTADOS, tipos=A.TIPOS_TXT, puede_carga=puede(URL_CARGA),
                           puede_ej=puede("/contabilidad/ejercicios"), hoy=datetime.date.today())


@cont_diario_bp.route("/diario/<int:id_asiento>")
def asiento(id_asiento):
    salida = _guardia(URL_DIARIO)
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            a = A.leer_asiento(cur, id_asiento)
    if not a:
        flash("!No existe ese asiento.")
        return redirect(url_for("cont_diario.diario"))
    return render_template("contabilidad/asiento.html", a=a, estados=A.ESTADOS, tipos=A.TIPOS_TXT,
                           puede_carga=puede(URL_CARGA), volver=_volver_seguro(request.args.get("volver")))


def _volver_seguro(v) -> str:
    v = (v or "").strip()
    if v.startswith("/") and not v.startswith("//") and "\\" not in v:
        return v
    return url_for("cont_diario.diario")


@cont_diario_bp.route("/diario/accion", methods=["POST"])
def accion():
    salida = _guardia(URL_CARGA)
    if salida:
        return salida
    acc = request.form.get("accion", "")
    volver = _volver_seguro(request.form.get("volver"))
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            if acc == "confirmar":
                a = A.confirmar(cur, request.form.get("id", type=int))
                msg = f"Asiento N° {a['numero']} confirmado."
            elif acc == "borrar":
                a = A.eliminar_borrador(cur, request.form.get("id", type=int))
                msg = f"Borrador N° {a['numero']} eliminado."
            elif acc == "confirmar_todos":
                f = filtros(cur, request.form)
                f["estado"] = "borrador"
                filas, _ = A.listar(cur, f, TOPE)
                ok, malos = 0, []
                for x in sorted(filas, key=lambda r: (r["fecha"], r["numero"])):
                    cur.execute("SAVEPOINT conf")
                    try:
                        A.confirmar(cur, x["id_asiento"])
                        cur.execute("RELEASE SAVEPOINT conf")
                        ok += 1
                    except A.ErrorContable as e:
                        cur.execute("ROLLBACK TO SAVEPOINT conf")
                        malos.append(str(e))
                msg = f"{ok} asiento(s) confirmado(s)."
                if malos:
                    msg = "!" + msg + f" {len(malos)} no: " + " · ".join(malos[:5]) + (" …" if len(malos) > 5 else "")
            else:
                raise A.ErrorContable("Acción desconocida.")
        conn.commit()
        flash(msg)
    except A.ErrorContable as e:
        conn.rollback()
        flash(f"!{e}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return redirect(volver)


# =============================================================================
# Carga (menú 93)
# =============================================================================

def _renglones_form(form) -> list[dict]:
    ctas, debes, haberes, descs = (form.getlist("r_cuenta"), form.getlist("r_debe"), form.getlist("r_haber"),
                                   form.getlist("r_desc"))
    return [{"id_cuenta": c, "debe": d, "haber": h, "descripcion": x}
            for c, d, h, x in zip(ctas, debes, haberes, descs)]


@cont_diario_bp.route("/asientos", methods=["GET", "POST"])
def carga():
    salida = _guardia(URL_CARGA)
    if salida:
        return salida
    id_edit = request.values.get("edit", type=int)
    errores = []
    with get_connection() as conn:
        with conn.cursor() as cur:
            cuentas = tesoreria.cuentas_imputables(cur)
            ej = A.ejercicio_activo(cur)
            base = None
            if id_edit:
                base = A.leer_asiento(cur, id_edit)
                if not base:
                    flash("!No existe ese asiento.")
                    return redirect(url_for("cont_diario.diario"))
                if base["estado"] != "borrador":
                    flash(f"!El asiento N° {base['numero']} está {base['estado']}: ya no se modifica.")
                    return redirect(url_for("cont_diario.asiento", id_asiento=id_edit))
            elif request.args.get("copiar", type=int):
                base = A.leer_asiento(cur, request.args.get("copiar", type=int))
                if base:
                    base = {**base, "id_asiento": None, "estado": "borrador", "numero": None,
                            "fecha": datetime.date.today(), "referencia": base.get("referencia")}
    cab = {"fecha": (base or {}).get("fecha") or datetime.date.today(),
           "descripcion": (base or {}).get("descripcion") or "", "tipo": (base or {}).get("tipo") or "operacion",
           "referencia": (base or {}).get("referencia") or ""}
    renglones = [{"id_cuenta": r["id_cuenta"], "debe": _num(r["debe"]) if r["debe"] else "",
                  "haber": _num(r["haber"]) if r["haber"] else "", "descripcion": r["descripcion"] or ""}
                 for r in (base or {}).get("renglones", [])]

    if request.method == "POST":
        cab = {k: request.form.get(k, "") for k in ("fecha", "descripcion", "tipo", "referencia")}
        renglones = _renglones_form(request.form)
        confirmar = request.form.get("confirmar") == "1"
        conn = get_connection()
        try:
            conn.begin()
            with conn.cursor() as cur:
                r = A.grabar(cur, cab, renglones, _usuario(), id_asiento=id_edit)
                if confirmar:
                    A.confirmar(cur, r["id_asiento"])
            conn.commit()
            flash(f"Asiento N° {r['numero']} {'confirmado' if confirmar else 'guardado en borrador'} "
                  f"({r['periodo']}).")
            if request.form.get("otro") == "1":
                return redirect(url_for("cont_diario.carga"))
            return redirect(url_for("cont_diario.asiento", id_asiento=r["id_asiento"]))
        except A.ErrorContable as e:
            conn.rollback()
            errores = [str(e)]
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    while len(renglones) < 2:
        renglones.append({"id_cuenta": "", "debe": "", "haber": "", "descripcion": ""})
    return render_template("contabilidad/asiento_carga.html", cab=cab, renglones=renglones, cuentas=cuentas,
                           base=base if id_edit else None, ej=ej, errores=errores, tipos=A.TIPOS_TXT)


# =============================================================================
# Exportaciones
# =============================================================================

@cont_diario_bp.route("/diario/exportar")
def exportar_asientos():
    """Los asientos confirmados del filtro con las columnas del archivo de
    importación (lo que se exporta acá se puede volver a importar)."""
    salida = _guardia(URL_DIARIO)
    if salida:
        return salida
    fmt = (request.args.get("formato") or "xlsx").lower()
    with get_connection() as conn:
        with conn.cursor() as cur:
            f = filtros(cur, request.args)
            f["estado"] = "confirmado"
            filas = A.renglones_libro(cur, f)
    datos = [[a["numero"], a["fecha"], a["tipo"], a["descripcion"], a["referencia"] or "", a["codigo_cuenta"],
              a["detalle"] or "", a["debe"] or 0, a["haber"] or 0] for a in filas]
    nombre = _nombre_archivo("asientos", f, fmt if fmt == "csv" else "xlsx")
    if fmt == "csv":
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(A.COLS_ARCHIVO)
        for d in datos:
            w.writerow([d[0], d[1].isoformat(), *d[2:7], f"{float(d[7]):.2f}" if d[7] else "",
                        f"{float(d[8]):.2f}" if d[8] else ""])
        return Response(out.getvalue().encode("utf-8-sig"), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={nombre}"})
    cols = [{"titulo": t, "tipo": ty} for t, ty in zip(A.TITULOS_ARCHIVO, ("n", "", "t", "t", "t", "t", "t", "n", "n"))]
    contenido = exportar.xlsx("Asientos", cols, [[d[0], d[1].strftime("%d/%m/%Y"), *d[2:7],
                                                  _num(d[7]) if d[7] else "", _num(d[8]) if d[8] else ""]
                                                 for d in datos])
    return send_file(io.BytesIO(contenido), as_attachment=True, download_name=nombre,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@cont_diario_bp.route("/diario/libro")
def libro():
    """El Libro Diario del filtro (sin anulados), en Excel o PDF."""
    salida = _guardia(URL_DIARIO)
    if salida:
        return salida
    fmt = (request.args.get("formato") or "xlsx").lower()
    with get_connection() as conn:
        with conn.cursor() as cur:
            f = filtros(cur, request.args)
            f["sin_anulados"] = True
            filas = A.renglones_libro(cur, f)
            titulo = _titulo(cur, f)
    inst = institucion.obtener()
    nombre = _nombre_archivo("libro_diario", f, "pdf" if fmt == "pdf" else "xlsx")
    if fmt == "pdf":
        return send_file(libro_pdf(filas, titulo), mimetype="application/pdf", as_attachment=False,
                         download_name=nombre)
    cols = [{"titulo": t, "tipo": ty} for t, ty in (("N°", "n"), ("Fecha", ""), ("Tipo", "t"), ("Descripción", "t"),
                                                   ("Referencia", "t"), ("Cuenta", "t"), ("Nombre de la cuenta", "t"),
                                                   ("Detalle", "t"), ("Debe", "n"), ("Haber", "n"), ("Estado", "t"))]
    datos = [[a["numero"], a["fecha"].strftime("%d/%m/%Y"), A.TIPOS_TXT.get(a["tipo"], a["tipo"]), a["descripcion"],
              a["referencia"] or "", a["codigo_cuenta"], a["nombre_cuenta"], a["detalle"] or "",
              _num(a["debe"]) if a["debe"] else "", _num(a["haber"]) if a["haber"] else "",
              A.ESTADOS[a["estado"]][0]] for a in filas]
    enc = [f"LIBRO DIARIO — {inst.get('nombre') or ''}", f"CUIT {inst.get('cuit') or '—'} · {titulo}", ""]
    contenido = exportar.xlsx("Libro Diario", cols, datos, encabezado=enc)
    return send_file(io.BytesIO(contenido), as_attachment=True, download_name=nombre,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def libro_pdf(filas: list[dict], titulo: str) -> io.BytesIO:
    """Un bloque por asiento: la cabecera (número, fecha, descripción) y sus
    renglones, con el total al pie."""
    import pagos_pdf as P
    doc = P._Doc("Libro Diario", titulo)
    tabla, actual = [], None
    td = th = Decimal("0")
    for r in filas:
        if r["id_asiento"] != actual:
            actual = r["id_asiento"]
            ref = f" · {P._txt(r['referencia'])}" if r["referencia"] else ""
            borr = " <font color='#8a6000'>(borrador)</font>" if r["estado"] == "borrador" else ""
            tabla.append([f"<b>{r['numero']}</b>", r["fecha"].strftime("%d/%m/%Y"),
                          f"<b>{P._txt(r['descripcion'])}</b>{ref}{borr}", "", "", ""])
        debe, haber = Decimal(str(r["debe"] or 0)), Decimal(str(r["haber"] or 0))
        td += debe
        th += haber
        sangria = "&nbsp;&nbsp;&nbsp;&nbsp;" if haber else ""
        tabla.append(["", "", f"{sangria}{P._txt(r['codigo_cuenta'])} {P._txt(r['nombre_cuenta'])}",
                      P._txt(r["detalle"]), _num(debe) if debe else "", _num(haber) if haber else ""])
    if not tabla:
        doc.story.append(doc.P("No hay asientos para ese filtro."))
    else:
        doc.tabla(f"{len({r['id_asiento'] for r in filas})} asientos", ["N°", "Fecha", "Cuenta", "Detalle", "Debe",
                                                                         "Haber"],
                  tabla, [1.0, 2.1, 5.8, 4.1, 2.0, 2.0], derecha=(4, 5))
        doc.datos("Totales", [("Debe", P._pesos(td)), ("Haber", P._pesos(th))])
    buf = doc.pdf("Libro Diario")
    buf.seek(0)
    return buf


@cont_diario_bp.route("/diario/externo")
def externo():
    """Los asientos confirmados de un rango en el formato del sistema contable
    externo (exportar_contable_externo.py, el de gestion_adm). Sin rango no
    exporta: mandar un ejercicio entero por error es difícil de deshacer allá."""
    salida = _guardia(URL_DIARIO)
    if salida:
        return salida
    desde, hasta = _fecha_arg(request.args.get("desde")), _fecha_arg(request.args.get("hasta"))
    if not desde or not hasta:
        flash("!Elegí el rango de fechas (desde y hasta) antes de exportar al sistema externo.")
        return redirect(url_for("cont_diario.diario"))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(EXT.SQL_ASIENTOS, (desde, hasta))
            filas = cur.fetchall()
    if not filas:
        flash(f"!No hay asientos confirmados del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}.")
        return redirect(url_for("cont_diario.diario", desde=desde.isoformat(), hasta=hasta.isoformat()))
    sin_codigo = sorted({f["cuenta_codigo"] for f in filas if EXT.cuenta_a_entero(f["cuenta_codigo"]) is None})
    if sin_codigo:
        flash(f"!Hay cuentas sin código numérico: {', '.join(sin_codigo)}. Corregilas en el plan de cuentas.")
        return redirect(url_for("cont_diario.diario"))
    return send_file(EXT.construir_libro(filas), as_attachment=True,
                     download_name=f"asientos_externo_{desde.isoformat()}_{hasta.isoformat()}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# =============================================================================
# Importar y renumerar (carga, menú 93)
# =============================================================================

MODELO = [
    (1, "2026-01-02", "operacion", "Pago de servicios — Proveedor ejemplo", "OP 1234", "5-3-0-00-040",
     "Servicio de enero", "150000,00", ""),
    (1, "2026-01-02", "operacion", "Pago de servicios — Proveedor ejemplo", "OP 1234", "1-1-1-02-020",
     "Transferencia", "", "150000,00"),
    (2, "2026-01-05", "operacion", "Cobro de cuota sindical — Empresa ejemplo", "RC 55", "1-1-1-02-020",
     "Acreditación", "80000,00", ""),
    (2, "2026-01-05", "operacion", "Cobro de cuota sindical — Empresa ejemplo", "RC 55", "4-1-0-01-010",
     "Cuota sindical 2025-12", "", "80000,00"),
]


@cont_diario_bp.route("/diario/modelo")
def modelo():
    salida = _guardia(URL_CARGA)
    if salida:
        return salida
    fmt = (request.args.get("formato") or "xlsx").lower()
    if fmt == "csv":
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(A.COLS_ARCHIVO)
        for r in MODELO:
            w.writerow([*r[:7], r[7].replace(",", "."), r[8].replace(",", ".")])
        return Response(out.getvalue().encode("utf-8-sig"), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=asientos_modelo.csv"})
    cols = [{"titulo": t, "tipo": ty} for t, ty in zip(A.TITULOS_ARCHIVO, ("n", "", "t", "t", "t", "t", "t", "n", "n"))]
    datos = [[r[0], datetime.date.fromisoformat(r[1]).strftime("%d/%m/%Y"), *r[2:]] for r in MODELO]
    enc = [f"Un renglón por imputación; los del mismo N° de asiento forman un asiento (el N° solo agrupa). Tipos: "
           f"{', '.join(A.TIPOS)}. La cuenta es el código del plan (con o sin guiones). Quedan en borrador."]
    contenido = exportar.xlsx("Asientos", cols, datos, encabezado=enc)
    return send_file(io.BytesIO(contenido), as_attachment=True, download_name="asientos_modelo.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@cont_diario_bp.route("/diario/importar", methods=["POST"])
def importar():
    salida = _guardia(URL_CARGA)
    if salida:
        return salida
    volver = _volver_seguro(request.form.get("volver"))
    arch = request.files.get("archivo")
    if not arch or not arch.filename:
        flash("!Elegí el archivo.")
        return redirect(volver)
    conn = get_connection()
    try:
        filas = A.leer_archivo(arch.filename, arch.read())
        conn.begin()
        with conn.cursor() as cur:
            cur.execute("SELECT id_cuenta, codigo FROM c_plan_de_cuentas")
            por_codigo = {"".join(ch for ch in (c["codigo"] or "") if ch.isdigit()): c["id_cuenta"]
                          for c in cur.fetchall()}
            asientos, err = A.agrupar_archivo(filas, por_codigo)
            res = A.importar(cur, asientos, _usuario(), con_origen=A.tiene_origen(cur))
        conn.commit()
    except A.ErrorContable as e:
        conn.rollback()
        flash(f"!{e}")
        return redirect(volver)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    errores = err + res["errores"]
    msg = (f"{res['grabados']} asiento(s) importado(s) en borrador: revisalos y confirmalos."
           + (f" {len(errores)} con problemas: " + " · ".join(errores[:6]) + (" …" if len(errores) > 6 else "")
              if errores else ""))
    flash(("!" if errores else "") + msg)
    return redirect(url_for("cont_diario.diario", estado="borrador"))


@cont_diario_bp.route("/diario/renumerar", methods=["POST"])
def renumerar():
    salida = _guardia(URL_CARGA)
    if salida:
        return salida
    id_ej = request.form.get("ejercicio", type=int)
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            cur.execute("SELECT nombre FROM c_ejercicios WHERE id_ejercicio = %s", (id_ej,))
            ej = cur.fetchone()
            if not ej:
                raise A.ErrorContable("Elegí el ejercicio a renumerar.")
            n = A.renumerar(cur, id_ej)
        conn.commit()
        flash(f"{ej['nombre']}: {n} asientos renumerados (la apertura primero, el resto por fecha).")
    except A.ErrorContable as e:
        conn.rollback()
        flash(f"!{e}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return redirect(url_for("cont_diario.diario", ejercicio=id_ej))
