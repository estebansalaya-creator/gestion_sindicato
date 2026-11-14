"""
importar_arca_tablas.py — Vencimientos del F.931, tasas de interés y feriados de ARCA, desde contable.

gestion_adm las mantiene (arca_vencimientos, arca_intereses, arca_feriados en
`contable` de Railway) y acá se copian: es una importación explícita, de solo
lectura sobre contable (contable_oseda._conexion), como pide la regla de oro.

    arca_vencimientos   solo la obligación F931; por (período, dígito)
    arca_intereses      por vigencia_desde
    arca_feriados       por fecha

Con --aplicar, además, las liquidaciones de cuota sindical pasan al
vencimiento del F.931 de su CUIT (fisca_intereses.Calendario), por si cambió
alguna fecha. Lo que ya está en un acta no cambia: el acta guarda lo suyo.

Uso
---
    python importar_arca_tablas.py              simula: compara y no graba
    python importar_arca_tablas.py --aplicar    graba
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

import contable_oseda                  # noqa: E402
import fisca_intereses as FI           # noqa: E402
from db import get_connection          # noqa: E402

COLS_INT = ["vigencia_desde", "vigencia_hasta", "resarcitorio", "punitorio", "devolucion", "resarcitorio_usd",
            "punitorio_usd", "devolucion_usd", "resolucion", "tipo", "origen", "observaciones"]


def leer_contable() -> dict:
    cn = contable_oseda._conexion()
    try:
        with cn.cursor() as cur:
            cur.execute("""SELECT periodo, digito_verificador, fecha_vencimiento, origen, rg_referencia, observaciones
                             FROM arca_vencimientos WHERE obligacion = 'F931'""")
            venc = list(cur.fetchall())
            cur.execute(f"SELECT {', '.join(COLS_INT)} FROM arca_intereses WHERE vigencia_desde IS NOT NULL")
            ints = list(cur.fetchall())
            cur.execute("SELECT fecha, descripcion, tipo, origen, activo FROM arca_feriados")
            fer = list(cur.fetchall())
    finally:
        cn.close()
    return {"venc": venc, "int": ints, "fer": fer}


def aplicar(cur, datos: dict) -> dict:
    r = {}
    cur.execute("SELECT periodo, digito_verificador AS d, fecha_vencimiento AS f FROM arca_vencimientos WHERE obligacion = 'F931'")
    ya = {(x["periodo"], x["d"]): x["f"] for x in cur.fetchall()}
    nuevos = [v for v in datos["venc"] if ya.get((v["periodo"], v["digito_verificador"])) != v["fecha_vencimiento"]]
    cur.executemany("""INSERT INTO arca_vencimientos (periodo, digito_verificador, obligacion, fecha_vencimiento, origen,
                                                      rg_referencia, observaciones)
                       VALUES (%s, %s, 'F931', %s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE fecha_vencimiento = VALUES(fecha_vencimiento), origen = VALUES(origen),
                                               rg_referencia = VALUES(rg_referencia), observaciones = VALUES(observaciones)""",
                    [(v["periodo"], v["digito_verificador"], v["fecha_vencimiento"], v["origen"], v["rg_referencia"],
                      v["observaciones"]) for v in nuevos])
    r["vencimientos"] = (len(datos["venc"]), len(nuevos))

    cur.execute(f"SELECT {', '.join(COLS_INT)} FROM arca_intereses")
    ya = {x["vigencia_desde"]: x for x in cur.fetchall()}
    nuevos = [t for t in datos["int"] if {k: ya.get(t["vigencia_desde"], {}).get(k) for k in COLS_INT} != t]
    cur.executemany(f"""INSERT INTO arca_intereses ({', '.join(COLS_INT)}) VALUES ({', '.join(['%s'] * len(COLS_INT))})
                        ON DUPLICATE KEY UPDATE {', '.join(f'{c} = VALUES({c})' for c in COLS_INT[1:])}""",
                    [[t[c] for c in COLS_INT] for t in nuevos])
    r["tasas"] = (len(datos["int"]), len(nuevos))

    cur.execute("SELECT fecha, descripcion, tipo, origen, activo FROM arca_feriados")
    ya = {x["fecha"]: x for x in cur.fetchall()}
    nuevos = [f for f in datos["fer"] if ya.get(f["fecha"]) != f]
    cur.executemany("""INSERT INTO arca_feriados (fecha, descripcion, tipo, origen, activo) VALUES (%s, %s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE descripcion = VALUES(descripcion), tipo = VALUES(tipo),
                                               origen = VALUES(origen), activo = VALUES(activo)""",
                    [(f["fecha"], f["descripcion"], f["tipo"], f["origen"], f["activo"]) for f in nuevos])
    r["feriados"] = (len(datos["fer"]), len(nuevos))

    # Las liquidaciones, al vencimiento del F.931 de su CUIT.
    cal = FI.Calendario(cur)
    cur.execute("SELECT id, cuit, periodo, vencimiento FROM fisca_liquidacion")
    cambios = [(cal.vencimiento(l["cuit"], l["periodo"]), l["id"]) for l in cur.fetchall()]
    cambios = [c for c in cambios if c[0]]
    cur.execute("SELECT id, vencimiento FROM fisca_liquidacion")
    antes = {x["id"]: x["vencimiento"] for x in cur.fetchall()}
    cambios = [c for c in cambios if antes.get(c[1]) != c[0]]
    cur.executemany("UPDATE fisca_liquidacion SET vencimiento = %s WHERE id = %s", cambios)
    r["liquidaciones"] = len(cambios)
    return r


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Tablas de ARCA (vencimientos F.931, tasas, feriados) desde contable.")
    p.add_argument("--aplicar", action="store_true", help="grabar (sin esto, simula)")
    a = p.parse_args(argv)
    try:
        datos = leer_contable()
    except contable_oseda.ContableNoDisponible as e:
        print(f"\n  {e}\n")
        return 1
    with get_connection() as conn:
        conn.begin()
        try:
            with conn.cursor() as cur:
                r = aplicar(cur, datos)
            conn.commit() if a.aplicar else conn.rollback()
        except Exception:
            conn.rollback()
            raise
    print()
    for k in ("vencimientos", "tasas", "feriados"):
        print(f"  {k:<14} {r[k][0]:>5} en contable, {r[k][1]:>5} nuevos o cambiados")
    print(f"  liquidaciones  {r['liquidaciones']:>5} con otro vencimiento")
    print("  GRABADO." if a.aplicar else "  SIMULACIÓN: no se grabó nada (--aplicar graba).")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
