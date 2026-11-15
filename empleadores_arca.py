"""
empleadores_arca.py — actualizar los empleadores desde ARCA, a pedido
=====================================================================

El botón «Actualizar desde ARCA» de Empleadores (pedido del 15/11/2026, el de
gestion_adm). Consulta la constancia de inscripción (arca_constancia.py, con el
certificado del sindicato) de los empleadores del alcance y, por cada uno:

  1. guarda la constancia —impuestos, actividades, condición de IVA— por CUIT
     (`arca_constancia`, la solapa ARCA de la ficha);
  2. actualiza el **domicilio fiscal** de la ficha (`fdom_*`) si ARCA informa
     otro. El domicilio legal (`dom_*`, el que usan las actas) y la razón
     social no se tocan.

Lo que cambia en `p_empresas` queda campo por campo, con el valor de antes, en
`arca_constancia_cambios` (sql/arca_constancia_20261115.sql); la solapa ARCA lo
muestra. Sin esa tabla no se corre: un cambio de domicilio sin rastro no vale.

EL ALCANCE
----------
gestion_adm consulta a los que presentaron DDJJ en los últimos 12 meses. Acá,
a los que tienen afiliados con relación laboral vigente (la regla de la
solapa Nómina) o cuota sindical recibida en los últimos `MESES` meses
(`fisca_cuotarecepcion`): los ~3.100 de la tabla son casi todos «activos» y
la mayoría no aporta.

EL DOMICILIO
------------
ARCA da la dirección en un texto («AV CORRIENTES 1234 Piso:5 Dpto:B») y se
parte en calle, número, piso y depto como en el botón de la ficha
(`arca_constancia.partir_direccion`). Calle, número, piso y depto se comparan y
se reescriben juntos; el CP y la localidad, cada uno. Si cambia la localidad se
vacían los id de localidad y departamento: ARCA no los da y los viejos
apuntarían a otro lado. Si ARCA no trae domicilio, no se borra el que hay.

EL ORDEN Y LA CORRIDA
---------------------
Del que hace más tiempo que no se consulta (o nunca) al más reciente: si la
corrida se corta —un despliegue reinicia la web— la siguiente sigue por donde
quedó. Corre en un hilo; el estado vive en memoria, que alcanza porque la web
es un solo proceso (Procfile: gunicorn con un worker; IIS: maxInstances=1).

Desde la consola (con el .env de la carpeta):

    python empleadores_arca.py --dry-run --limite 20   # consulta y muestra, no guarda
    python empleadores_arca.py --cuits 30682342907
    python empleadores_arca.py                          # todos los del alcance
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import re
import sys
import threading
import time
import unicodedata

import arca_constancia as C

log = logging.getLogger(__name__)

MESES = 12
#: Entre consulta y consulta, para no apurar al web service de ARCA.
PAUSA_SEGUNDOS = 0.2
#: Tantos errores seguidos con el mismo motivo es que ARCA (o el certificado)
#: no anda: se corta en vez de anotar trescientas veces lo mismo.
ERRORES_SEGUIDOS_MAX = 15
SQL_TABLAS = "sql/arca_constancia_20261115.sql"

#: Rótulos de las columnas, para la pantalla y la solapa ARCA.
CAMPOS = {"fdom_calle": "Calle", "fdom_numero": "Número", "fdom_piso": "Piso", "fdom_depto": "Depto",
          "fdom_cp": "Código postal", "fdom_localidad_nombre": "Localidad", "fdom_localidad_id": "Localidad (id)",
          "fdom_departamento_id": "Departamento (id)", "fdom_departamento_nombre": "Departamento",
          "fdom_provincia_id": "Provincia (código)", "fdom_provincia_nombre": "Provincia"}

_LOCK = threading.Lock()
_TRABAJO: dict | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Quiénes
# ─────────────────────────────────────────────────────────────────────────────

def periodo_desde(hoy: dt.date | None = None) -> int:
    """El primer período (AAAAMM) que cuenta como cuota reciente."""
    hoy = hoy or dt.date.today()
    mes = hoy.year * 12 + hoy.month - 1 - MESES
    return (mes // 12) * 100 + mes % 12 + 1


_ALCANCE = """
      FROM p_empresas e
      LEFT JOIN arca_constancia ac ON ac.cuit = LPAD(e.CUIT, 11, '0') COLLATE utf8mb4_0900_ai_ci
     WHERE (EXISTS (SELECT 1 FROM fisca_cuotarecepcion c
                     WHERE c.cuit = LPAD(e.CUIT, 11, '0') AND c.periodo >= %s)
         OR EXISTS (SELECT 1 FROM p_relaciones_laborales r
                     WHERE r.estado = 'activa' AND (r.fecha_fin IS NULL OR r.fecha_fin >= CURDATE())
                       AND (r.id_empleador = e.id
                            OR (r.id_empleador IS NULL AND r.cuit_empleador = LPAD(e.CUIT, 11, '0')))))
"""


def empleadores(cur, cuits=None, limite=None) -> list[dict]:
    """Los del alcance, del menos reciente al más reciente en ARCA."""
    params: list = [periodo_desde()]
    extra = ""
    if cuits:
        lista = [int(re.sub(r"\D", "", c)) for c in cuits if re.sub(r"\D", "", c)]
        extra = " AND e.CUIT IN (%s)" % ",".join(["%s"] * len(lista))
        params += lista
    sql = ("SELECT e.id, e.CUIT, e.razon_social, "
           + ", ".join(f"e.{c}" for c in CAMPOS) + ", ac.consultado" + _ALCANCE + extra
           + " ORDER BY ac.consultado IS NOT NULL, ac.consultado, e.id")
    if limite:
        sql += f" LIMIT {int(limite)}"
    cur.execute(sql, params)
    return cur.fetchall()


def resumen_alcance(cur) -> dict:
    """{total, nunca, mas_vieja, desde} para el cartel del botón, o {falta_tabla}."""
    try:
        cur.execute("SELECT COUNT(*) AS total, SUM(ac.cuit IS NULL) AS nunca, MIN(ac.consultado) AS mas_vieja"
                    + _ALCANCE, (periodo_desde(),))
        r = cur.fetchone() or {}
        cur.execute("SELECT 1 FROM arca_constancia_cambios LIMIT 1")
    except Exception as e:                                   # noqa: BLE001
        if "1146" in str(e):
            return {"falta_tabla": True, "sql": SQL_TABLAS}
        raise
    p = str(periodo_desde())
    return {"total": int(r.get("total") or 0), "nunca": int(r.get("nunca") or 0),
            "mas_vieja": r["mas_vieja"].strftime("%d/%m/%Y") if r.get("mas_vieja") else None,
            "desde": f"{p[:4]}-{p[4:]}"}


# ─────────────────────────────────────────────────────────────────────────────
# El domicilio fiscal
# ─────────────────────────────────────────────────────────────────────────────

def _n(v) -> str:
    """Para comparar: mayúsculas, sin acentos, sin signos ni espacios de más."""
    t = unicodedata.normalize("NFD", str(v or "").upper())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", t).split())


def _txt(v, largo) -> str | None:
    return " ".join(str(v or "").split()).upper()[:largo] or None


def domicilio_cambios(emp: dict, dom: dict, provincia: tuple | None = None) -> dict:
    """{columna: valor nuevo} con lo que hay que cambiar del domicilio fiscal.
    `provincia`: (codigo, nombre) de p_provincia que corresponde a la de ARCA."""
    if not dom or not (dom.get("calle") or "").strip():
        return {}
    cambios = {}
    nuevo = {"fdom_calle": _txt(dom.get("calle"), 150), "fdom_numero": _txt(dom.get("numero"), 10),
             "fdom_piso": _txt(dom.get("piso"), 5), "fdom_depto": _txt(dom.get("depto"), 10)}
    if any(_n(emp.get(k)) != _n(v) for k, v in nuevo.items()):
        cambios.update(nuevo)
    cp = _txt(dom.get("cp"), 8)
    if cp and _n(cp).lstrip("0") != _n(emp.get("fdom_cp")).lstrip("0"):
        cambios["fdom_cp"] = cp
    loc = _txt(dom.get("localidad"), 100)
    if loc and _n(loc) != _n(emp.get("fdom_localidad_nombre")):
        cambios.update({"fdom_localidad_nombre": loc, "fdom_localidad_id": None,
                        "fdom_departamento_id": None, "fdom_departamento_nombre": None})
    if provincia and str(provincia[0]) != str(emp.get("fdom_provincia_id") or ""):
        cambios.update({"fdom_provincia_id": str(provincia[0]), "fdom_provincia_nombre": provincia[1]})

    # Lo que no cambia de verdad no es un cambio: vacío que sigue vacío, o lo
    # mismo con otras mayúsculas o signos («Av. Corrientes» y «AV CORRIENTES»).
    def igual(k, v):
        if k.endswith("_id"):
            return str(v or "") == str(emp.get(k) or "")
        return _n(v) == _n(emp.get(k))
    return {k: v for k, v in cambios.items() if not igual(k, v)}


def _provincias(cur) -> list[dict]:
    cur.execute("SELECT codigo, nombre FROM p_provincia")
    return cur.fetchall()


def _provincia(provincias: list[dict], descripcion: str) -> tuple | None:
    cod = C.P.provincia_codigo(descripcion, provincias) if descripcion else None
    if cod is None:
        return None
    return cod, next(f["nombre"] for f in provincias if f["codigo"] == cod)


# ─────────────────────────────────────────────────────────────────────────────
# Uno
# ─────────────────────────────────────────────────────────────────────────────

def actualizar_uno(conn, emp: dict, provincias: list[dict], usuario=None, guardar=True,
                   consultar=None) -> dict:
    """Consulta ARCA y guarda. {id, cuit, razon_social, cambios, error}."""
    consultar = consultar or C.consultar
    cuit = "%011d" % int(emp["CUIT"])
    out = {"id": emp.get("id"), "cuit": cuit, "razon_social": emp.get("razon_social") or "",
           "cambios": [], "error": None}
    try:
        d = consultar(cuit)
    except (C.ErrorARCA, C.NoEncontrado, ValueError) as e:
        out["error"] = str(e)[:300]
        return out
    dom = d.get("domicilio") or {}
    cambios = domicilio_cambios(emp, dom, _provincia(provincias, dom.get("provincia")))
    out["cambios"] = [{"campo": k, "rotulo": CAMPOS.get(k, k), "antes": emp.get(k), "despues": v}
                      for k, v in cambios.items()]
    if d.get("sin_constancia"):
        out["aviso"] = "; ".join(d.get("avisos") or [])[:300]
    if not guardar:
        return out
    with conn.cursor() as cur:
        conn.begin()
        try:
            # Lo del A13 o una constancia que ARCA no emite no pisa lo guardado.
            if d.get("fuente") == "constancia" and not d.get("sin_constancia"):
                C.guardar(cur, d, usuario)
            if cambios:
                cur.execute("UPDATE p_empresas SET " + ", ".join(f"`{k}` = %s" for k in cambios)
                            + " WHERE id = %s", list(cambios.values()) + [emp["id"]])
                for c in out["cambios"]:
                    cur.execute("""INSERT INTO arca_constancia_cambios
                                          (fecha, cuit, id_empresa, campo, antes, despues, id_usuario)
                                   VALUES (NOW(), %s, %s, %s, %s, %s, %s)""",
                                (cuit, emp["id"], c["campo"],
                                 None if c["antes"] is None else str(c["antes"])[:200],
                                 None if c["despues"] is None else str(c["despues"])[:200], usuario))
            conn.commit()
        except Exception as e:                               # noqa: BLE001
            conn.rollback()
            out["error"] = f"no se pudo guardar: {e}"[:300]
    return out


# ─────────────────────────────────────────────────────────────────────────────
# La tanda, en segundo plano
# ─────────────────────────────────────────────────────────────────────────────

def estado() -> dict | None:
    """La corrida en curso o la última (mientras la web no se reinicie)."""
    with _LOCK:
        if _TRABAJO is None:
            return None
        return dict(_TRABAJO, actualizados=list(_TRABAJO["actualizados"]),
                    errores=list(_TRABAJO["errores"]))


def empezar(get_connection, usuario=None) -> dict:
    """Arranca la corrida en un hilo. Si ya hay una en curso, devuelve ésa."""
    global _TRABAJO
    with _LOCK:
        if _TRABAJO and not _TRABAJO["terminado"]:
            return dict(estado_sin_lock(), ya_en_curso=True)
    ok, motivo = C.configurado()
    if not ok:
        return {"error": f"No se puede consultar ARCA: {motivo}."}
    with get_connection() as conn:
        with conn.cursor() as cur:
            alcance = resumen_alcance(cur)
            if alcance.get("falta_tabla"):
                return {"error": f"Falta correr {SQL_TABLAS}: sin esas tablas no se puede actualizar."}
            filas = empleadores(cur)
            provincias = _provincias(cur)
    with _LOCK:
        _TRABAJO = {"total": len(filas), "hechos": 0, "consultados": 0, "actualizados": [], "errores": [],
                    "terminado": False, "cortado": None, "actual": "",
                    "inicio": dt.datetime.now().strftime("%d/%m/%Y %H:%M"), "fin": None}
    threading.Thread(target=tanda, args=(get_connection, filas, provincias, usuario),
                     daemon=True, name="empleadores-arca").start()
    return estado()


def estado_sin_lock() -> dict:
    return dict(_TRABAJO, actualizados=list(_TRABAJO["actualizados"]), errores=list(_TRABAJO["errores"]))


def _anotar(**cambios):
    with _LOCK:
        if _TRABAJO is not None:
            _TRABAJO.update(cambios)


def tanda(get_connection, filas, provincias, usuario=None, consultar=None, pausa=PAUSA_SEGUNDOS):
    """Corre con conexión propia. Un empleador que falla no corta a los demás;
    `ERRORES_SEGUIDOS_MAX` con el mismo motivo, sí."""
    seguidos, ultimo = 0, None
    try:
        with get_connection() as conn:
            for i, emp in enumerate(filas):
                _anotar(actual=f"{emp.get('razon_social') or ''} ({'%011d' % int(emp['CUIT'])})")
                r = actualizar_uno(conn, emp, provincias, usuario, consultar=consultar)
                with _LOCK:
                    t = _TRABAJO
                    t["hechos"] = i + 1
                    if r["error"]:
                        t["errores"].append({k: r[k] for k in ("id", "cuit", "razon_social", "error")})
                    else:
                        t["consultados"] += 1
                        if r["cambios"]:
                            t["actualizados"].append(r)
                if r["error"]:
                    motivo = r["error"][:80]
                    seguidos = seguidos + 1 if motivo == ultimo else 1
                    ultimo = motivo
                    if seguidos >= ERRORES_SEGUIDOS_MAX:
                        _anotar(cortado=f"{seguidos} errores seguidos: {r['error']}")
                        break
                else:
                    seguidos, ultimo = 0, None
                if pausa:
                    time.sleep(pausa)
    except Exception as e:                                   # noqa: BLE001
        log.exception("Actualización de empleadores desde ARCA")
        _anotar(cortado=str(e))
    finally:
        _anotar(terminado=True, actual="", fin=dt.datetime.now().strftime("%d/%m/%Y %H:%M"))


# ─────────────────────────────────────────────────────────────────────────────
# Consola
# ─────────────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name(".env"))
    ap = argparse.ArgumentParser(description="Actualiza los empleadores desde ARCA.")
    ap.add_argument("--dry-run", action="store_true", help="consulta y muestra, no guarda")
    ap.add_argument("--limite", type=int, help="como máximo N empleadores")
    ap.add_argument("--cuits", help="solo estos CUIT, separados por coma")
    a = ap.parse_args(argv)

    from db import get_connection
    with get_connection() as conn:
        with conn.cursor() as cur:
            filas = empleadores(cur, a.cuits.split(",") if a.cuits else None, a.limite)
            provincias = _provincias(cur)
        print(f"{len(filas)} empleador(es) con afiliados activos o cuota desde {periodo_desde()}"
              + (" — DRY RUN, no se guarda nada" if a.dry_run else ""))
        errores = cambiados = 0
        for i, emp in enumerate(filas, 1):
            r = actualizar_uno(conn, emp, provincias, guardar=not a.dry_run)
            if r["error"]:
                errores += 1
                print(f"[{i}/{len(filas)}] {r['cuit']} {r['razon_social']}: ERROR {r['error']}")
            elif r["cambios"]:
                cambiados += 1
                print(f"[{i}/{len(filas)}] {r['cuit']} {r['razon_social']}:")
                for c in r["cambios"]:
                    print(f"      {c['rotulo']}: {c['antes']!r} → {c['despues']!r}")
            time.sleep(PAUSA_SEGUNDOS)
    print(f"\nListo: {len(filas) - errores} consultados, {cambiados} con domicilio fiscal "
          f"{'a cambiar' if a.dry_run else 'actualizado'}, {errores} con error.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
