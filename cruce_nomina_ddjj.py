"""
cruce_nomina_ddjj.py — Qué empleadores tienen toda su nómina de AEDA en la DDJJ de OSEDA.

La nómina de AEDA es lo que se importó al padrón: afiliados titulares activos
con relación laboral vigente (`p_relaciones_laborales` activa, sin egreso o con
egreso de hoy en adelante). Cada uno se busca en la DDJJ de OSEDA
(`f_ddjj_procesada` en contable de Railway, en vivo y solo lectura):

    en la DDJJ               el empleador lo declaró en el período
    en otro período          lo declaró en la ventana, pero no en el período
    con otro empleador       está en la DDJJ, pero declarado por otro CUIT
    no está                  no figura en ninguna DDJJ de OSEDA de la ventana

Un empleador está «al 100 %» cuando todos sus afiliados están en su DDJJ del
período. También se informa si lo está en la ventana (alguno de los últimos N
períodos) y cuántos empleados declaró en total (afiliados al gremio o no).

Uso
---
    python cruce_nomina_ddjj.py                       el último período completo y los 6 anteriores
    python cruce_nomina_ddjj.py --periodo 202608      ese período
    python cruce_nomina_ddjj.py --meses 3             ventana de 3 períodos

No escribe en ninguna base. Deja en logs/ el resumen (.txt) y dos planillas:
empleadores y afiliados.

El período por defecto es el último completo: el más nuevo cuyo número de filas
llega al 80 % del anterior (el mes en curso viene a medio presentar).
"""

import argparse
import sys
from collections import defaultdict
from datetime import date, datetime

# importar_aeda carga el .env.
from importar_aeda import CARPETA_LOGS, salir

import contable_oseda
from db import get_connection
from exportar import xlsx

ESTADOS = {"ok": "En la DDJJ", "otro_periodo": "En otro período", "otro_cuit": "Con otro empleador",
           "no": "No está"}


def _num(v, dec=2) -> str:
    """Para exportar.xlsx, que lee el número en formato argentino."""
    return f"{v:.{dec}f}".replace(".", ",") if dec else str(int(v))


def _per(p: str) -> str:
    return f"{p[:4]}-{p[4:]}"


def elegir_periodos(periodo: str | None, meses: int) -> tuple[str, list[str]]:
    lista = contable_oseda.periodos_ddjj(meses + 12)
    if not lista:
        salir("No hay DDJJ de OSEDA en contable.")
    pers = [f["periodo"] for f in lista]
    if not periodo:
        periodo = pers[0]
        for i in range(len(lista) - 1):
            if lista[i]["filas"] >= 0.8 * lista[i + 1]["filas"]:
                periodo = pers[i]
                break
            periodo = pers[i + 1]
    if periodo not in pers:
        salir(f"No hay DDJJ de OSEDA del período {periodo}.")
    i = pers.index(periodo)
    return periodo, pers[i:i + meses]


def leer_nomina(cur) -> list[dict]:
    cur.execute("""SELECT r.cuit_empleador AS cuit, a.cuil, a.apellido_nombres, a.id_afiliado,
                          r.fecha_inicio, e.razon_social
                     FROM p_relaciones_laborales r
                     JOIN p_afiliados a ON a.cuil = r.cuil
                     LEFT JOIN p_empresas e ON e.CUIT = CAST(r.cuit_empleador AS UNSIGNED)
                    WHERE r.estado = 'activa' AND (r.fecha_fin IS NULL OR r.fecha_fin >= CURDATE())
                      AND a.fecha_baja IS NULL AND a.cod_parentesco = 0
                      AND r.cuit_empleador REGEXP '^[0-9]{11}$' AND a.cuil REGEXP '^[0-9]{11}$'
                    ORDER BY r.cuit_empleador, a.apellido_nombres""")
    return cur.fetchall()


def cruzar(nomina, ddjj, periodo, empleados):
    por_cuil = defaultdict(list)                      # cuil → [(cuit, periodo)]
    for f in ddjj:
        por_cuil[f["cuil"]].append((f["cuit"], f["periodo"]))
    afiliados, empleadores = [], {}
    for n in nomina:
        decl = por_cuil.get(n["cuil"], [])
        del_cuit = sorted({p for c, p in decl if c == n["cuit"]}, reverse=True)
        otros = sorted({c for c, p in decl if c != n["cuit"]})
        if periodo in del_cuit:
            estado = "ok"
        elif del_cuit:
            estado = "otro_periodo"
        elif otros:
            estado = "otro_cuit"
        else:
            estado = "no"
        afiliados.append({**n, "estado": estado, "ultimo": del_cuit[0] if del_cuit else None, "otros": otros})
        e = empleadores.setdefault(n["cuit"], {"cuit": n["cuit"], "razon": n["razon_social"],
                                               "n": 0, "ok": 0, "otro_periodo": 0, "otro_cuit": 0, "no": 0})
        e["n"] += 1
        e[estado] += 1
    for e in empleadores.values():
        e["pct"] = 100 * e["ok"] / e["n"]
        e["pct_ventana"] = 100 * (e["ok"] + e["otro_periodo"]) / e["n"]
        e["empleados_ddjj"] = empleados.get(e["cuit"], 0)
    return afiliados, sorted(empleadores.values(), key=lambda e: (-e["pct"], -e["n"], e["cuit"]))


def main():
    parser = argparse.ArgumentParser(description="Empleadores con toda su nómina de AEDA en la DDJJ de OSEDA.")
    parser.add_argument("--periodo", help="AAAAMM (por defecto, el último completo)")
    parser.add_argument("--meses", type=int, default=6, help="períodos de la ventana, contando el elegido")
    args = parser.parse_args()
    inicio = datetime.now()

    try:
        periodo, ventana = elegir_periodos(args.periodo, max(args.meses, 1))
        with get_connection() as conn:
            with conn.cursor() as cur:
                nomina = leer_nomina(cur)
        if not nomina:
            salir("No hay afiliados titulares activos con relación laboral vigente.")
        ddjj = contable_oseda.ddjj_de_cuiles(ventana, {n["cuil"] for n in nomina})
        empleados = contable_oseda.empleados_por_cuit(periodo, {n["cuit"] for n in nomina})
    except contable_oseda.ContableNoDisponible as e:
        salir(str(e))

    afiliados, empleadores = cruzar(nomina, ddjj, periodo, empleados)
    al_100 = [e for e in empleadores if e["ok"] == e["n"]]
    al_100_v = [e for e in empleadores if e["ok"] + e["otro_periodo"] == e["n"]]
    sin_nadie = [e for e in empleadores if e["ok"] + e["otro_periodo"] == 0]
    cuenta = defaultdict(int)
    for a in afiliados:
        cuenta[a["estado"]] += 1

    CARPETA_LOGS.mkdir(exist_ok=True)
    base = CARPETA_LOGS / f"cruce_nomina_ddjj_{inicio:%Y%m%d_%H%M%S}"
    col_e = [{"titulo": "CUIT", "tipo": "t"}, {"titulo": "Empleador"}, {"titulo": "Afiliados (AEDA)", "tipo": "n"},
             {"titulo": f"En la DDJJ {_per(periodo)}", "tipo": "n"}, {"titulo": "En otro período", "tipo": "n"},
             {"titulo": "Con otro empleador", "tipo": "n"}, {"titulo": "No están", "tipo": "n"},
             {"titulo": f"% en la DDJJ {_per(periodo)}", "tipo": "n"}, {"titulo": "% en la ventana", "tipo": "n"},
             {"titulo": f"100 % en {_per(periodo)}"}, {"titulo": "Empleados en la DDJJ (todos)", "tipo": "n"}]
    filas_e = [[e["cuit"], e["razon"] or "— no está en Empleadores —", _num(e["n"], 0), _num(e["ok"], 0),
                _num(e["otro_periodo"], 0), _num(e["otro_cuit"], 0), _num(e["no"], 0), _num(e["pct"]),
                _num(e["pct_ventana"]), "Sí" if e["ok"] == e["n"] else "No", _num(e["empleados_ddjj"], 0)]
               for e in empleadores]
    col_a = [{"titulo": "CUIT", "tipo": "t"}, {"titulo": "Empleador"}, {"titulo": "CUIL", "tipo": "t"},
             {"titulo": "Apellido y nombres"}, {"titulo": "Ingreso"}, {"titulo": "Estado"},
             {"titulo": "Último período en su DDJJ", "tipo": "t"}, {"titulo": "Declarado por (otros CUIT)", "tipo": "t"}]
    filas_a = [[a["cuit"], a["razon_social"] or "", a["cuil"], a["apellido_nombres"] or "",
                a["fecha_inicio"].strftime("%d/%m/%Y") if isinstance(a["fecha_inicio"], date) else "",
                ESTADOS[a["estado"]], _per(a["ultimo"]) if a["ultimo"] else "", ", ".join(a["otros"])]
               for a in afiliados]
    arch_e = base.with_name(base.name + "_empleadores.xlsx")
    arch_a = base.with_name(base.name + "_afiliados.xlsx")
    arch_e.write_bytes(xlsx("Empleadores", col_e, filas_e))
    arch_a.write_bytes(xlsx("Afiliados", col_a, filas_a))

    total = len(afiliados)
    lineas = [f"Nómina de AEDA contra la DDJJ de OSEDA  {inicio:%d/%m/%Y %H:%M}",
              f"Período {_per(periodo)}; ventana {_per(ventana[-1])} a {_per(ventana[0])} ({len(ventana)} períodos)", "",
              f"  Empleadores con afiliados                      {len(empleadores):>6}",
              f"  Con el 100 % de su nómina en la DDJJ {_per(periodo)}  {len(al_100):>6}"
              f"   ({sum(e['n'] for e in al_100)} afiliados)",
              f"  Con el 100 % en la ventana                     {len(al_100_v):>6}",
              f"  Sin ningún afiliado en su DDJJ                 {len(sin_nadie):>6}", "",
              f"  Afiliados titulares con relación vigente       {total:>6}"]
    lineas += [f"    {ESTADOS[k]:<44} {cuenta[k]:>6}  ({100 * cuenta[k] / total:.1f} %)" for k in ESTADOS]
    lineas += ["", f"  Empleadores al 100 % en {_per(periodo)} (los de más afiliados primero):"]
    lineas += [f"    {e['cuit']}  {(e['razon'] or '—')[:50]:<50} {e['n']:>4} afiliados, "
               f"{e['empleados_ddjj']:>4} empleados en la DDJJ"
               for e in sorted(al_100, key=lambda e: -e["n"])[:40]]
    if len(al_100) > 40:
        lineas.append(f"    … y {len(al_100) - 40} más (ver la planilla)")
    lineas += ["", f"Planillas: {arch_e.name}  {arch_a.name}"]
    resumen = base.with_suffix(".txt")
    resumen.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print()
    print(resumen.read_text(encoding="utf-8"))


if __name__ == "__main__":
    sys.exit(main())
