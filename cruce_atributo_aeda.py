"""
cruce_atributo_aeda.py — ¿Todos los afiliados activos de AEDA tienen la marca «AEDA» en el padrón de OSEDA?

Cruza por CUIL los titulares del padrón del sindicato (lo que se importó de
AEDA) con el padrón de OSEDA (`p_afiliados` de contable en Railway, en vivo y
solo lectura) y su atributo «AEDA — Afiliado al Gremio»
(`p_atributos_por_afiliado`). El resultado de cada persona:

    Correcto                         activo en AEDA, vigente en OSEDA y con la marca
    Falta la marca                   activo en AEDA, vigente en OSEDA, sin la marca
    De baja en OSEDA                 activo en AEDA, con la baja dada en OSEDA
    Familiar en OSEDA                activo en AEDA, pero en OSEDA figura como familiar
    No está en OSEDA                 activo en AEDA y no figura en OSEDA (otra obra social)
    Sobra la marca: baja en AEDA     con la marca en OSEDA y de baja en el sindicato
    Sobra la marca: no está en AEDA  con la marca en OSEDA y no está en el padrón del sindicato
    Sobra la marca: familiar         la marca puesta a un familiar en OSEDA

Vigente en OSEDA = sin fecha de baja o con baja de hoy en adelante (también se
muestra la columna `activo` de OSEDA, que no siempre coincide).

Uso
---
    python cruce_atributo_aeda.py

No escribe en ninguna base (contable es de solo lectura para esta app). Deja en
logs/ el resumen (.txt), la planilla con una fila por persona y un .txt con los
CUIL a los que les falta la marca, para cargarla en gestion_adm.
"""

import sys
from collections import Counter
from datetime import date, datetime

# importar_aeda carga el .env.
from importar_aeda import CARPETA_LOGS, salir

import contable_oseda
from db import get_connection
from exportar import xlsx

ORDEN = ["Falta la marca", "Sobra la marca: baja en AEDA", "Sobra la marca: no está en AEDA",
         "Sobra la marca: familiar", "De baja en OSEDA", "Familiar en OSEDA", "No está en OSEDA", "Correcto"]


def _fecha(v) -> str:
    return v.strftime("%d/%m/%Y") if isinstance(v, date) else ""


def _vigente_oseda(o, hoy) -> bool:
    fb = o["fecha_baja"]
    if isinstance(fb, datetime):
        fb = fb.date()
    return fb is None or fb >= hoy


def cruzar(sind: dict, oseda: list[dict], hoy: date) -> list[dict]:
    """`sind`: cuil → titular del sindicato (activo o de baja)."""
    os_tit, os_fam = {}, {}
    for o in oseda:
        (os_tit if o["cod_parentesco"] == 0 else os_fam)[o["cuil"]] = o
    filas = []
    for cuil in sorted(set(sind) | set(os_tit) | {c for c, o in os_fam.items() if o["marca_aeda"]}):
        s, t, f = sind.get(cuil), os_tit.get(cuil), os_fam.get(cuil)
        o = t or f
        activo_aeda = bool(s) and s["fecha_baja"] is None
        marca = bool(o and o["marca_aeda"])
        if activo_aeda:
            if t and _vigente_oseda(t, hoy):
                res = "Correcto" if t["marca_aeda"] else "Falta la marca"
            elif t:
                res = "De baja en OSEDA"
            elif f:
                res = "Familiar en OSEDA"
            else:
                res = "No está en OSEDA"
        elif f and f["marca_aeda"]:
            res = "Sobra la marca: familiar"
        elif marca:
            res = "Sobra la marca: baja en AEDA" if s else "Sobra la marca: no está en AEDA"
        else:
            continue                         # de baja en AEDA o no está, y sin marca: nada que ver
        filas.append({"cuil": cuil, "s": s, "o": o, "marca": marca, "res": res})
    return filas


def main():
    inicio = datetime.now()
    hoy = inicio.date()
    try:
        oseda = contable_oseda.padron_oseda_aeda()
    except contable_oseda.ContableNoDisponible as e:
        salir(str(e))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT a.cuil, a.apellido_nombres, a.fecha_alta, a.fecha_baja, a.cuit_empleador,
                                  e.razon_social
                             FROM p_afiliados a
                             LEFT JOIN p_empresas e ON a.cuit_empleador REGEXP '^[0-9]{11}$'
                                                   AND e.CUIT = CAST(a.cuit_empleador AS UNSIGNED)
                            WHERE a.cod_parentesco = 0 AND a.cuil REGEXP '^[0-9]{11}$'""")
            sind = {}
            for f in cur.fetchall():
                ya = sind.get(f["cuil"])
                if not ya or (ya["fecha_baja"] is not None and f["fecha_baja"] is None):
                    sind[f["cuil"]] = f              # con el CUIL repetido, manda el activo

    filas = cruzar(sind, oseda, hoy)
    cuenta = Counter(f["res"] for f in filas)
    filas.sort(key=lambda f: (ORDEN.index(f["res"]), f["cuil"]))

    CARPETA_LOGS.mkdir(exist_ok=True)
    base = CARPETA_LOGS / f"cruce_atributo_aeda_{inicio:%Y%m%d_%H%M%S}"
    columnas = [{"titulo": "Resultado"}, {"titulo": "CUIL", "tipo": "t"},
                {"titulo": "Apellido y nombres (AEDA)"}, {"titulo": "Estado en AEDA"}, {"titulo": "Baja en AEDA"},
                {"titulo": "Empleador en AEDA", "tipo": "t"}, {"titulo": "Razón social"},
                {"titulo": "Apellido y nombre (OSEDA)"}, {"titulo": "En OSEDA"}, {"titulo": "Baja en OSEDA"},
                {"titulo": "Activo en OSEDA"}, {"titulo": "Empleador en OSEDA", "tipo": "t"},
                {"titulo": "Marca AEDA en OSEDA"}]
    datos = []
    for f in filas:
        s, o = f["s"] or {}, f["o"] or {}
        datos.append([
            f["res"], f["cuil"], s.get("apellido_nombres") or "",
            ("Activo" if s.get("fecha_baja") is None else "De baja") if s else "No está",
            _fecha(s.get("fecha_baja")), s.get("cuit_empleador") or "", s.get("razon_social") or "",
            " ".join(x for x in (o.get("apellido"), o.get("nombre")) if x) if o else "",
            ("Titular" if o.get("cod_parentesco") == 0 else "Familiar") if o else "No está",
            _fecha(o.get("fecha_baja")), ("Sí" if o.get("activo") else "No") if o else "",
            o.get("cuit_empleador") or "", "Sí" if f["marca"] else "No"])
    planilla = base.with_name(base.name + ".xlsx")
    planilla.write_bytes(xlsx("Marca AEDA en OSEDA", columnas, datos))
    faltan = base.with_name(base.name + "_falta_la_marca.txt")
    faltan.write_text("\n".join(f["cuil"] for f in filas if f["res"] == "Falta la marca") + "\n", encoding="utf-8")

    activos = sum(1 for s in sind.values() if s["fecha_baja"] is None)
    vigentes = cuenta["Correcto"] + cuenta["Falta la marca"]
    lineas = [f"Marca AEDA en el padrón de OSEDA  {inicio:%d/%m/%Y %H:%M}", "",
              f"  Titulares activos en AEDA                         {activos:>6}",
              f"  De ellos, titulares vigentes en OSEDA             {vigentes:>6}",
              f"    con la marca AEDA                               {cuenta['Correcto']:>6}"
              + (f"  ({100 * cuenta['Correcto'] / vigentes:.1f} %)" if vigentes else ""),
              f"    sin la marca                                    {cuenta['Falta la marca']:>6}",
              f"  ¿Todos tienen la marca?  {'SÍ' if not cuenta['Falta la marca'] else 'NO'}", "",
              "  Por resultado:"]
    lineas += [f"    {k:<34} {cuenta[k]:>6}" for k in ORDEN if cuenta[k]]
    lineas += ["", f"Planilla: {planilla.name}", f"CUIL sin la marca: {faltan.name}"]
    resumen = base.with_suffix(".txt")
    resumen.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print()
    print(resumen.read_text(encoding="utf-8"))


if __name__ == "__main__":
    sys.exit(main())
