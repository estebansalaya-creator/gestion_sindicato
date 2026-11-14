"""
importar_aeda_fisca_escalas.py — Las escalas salariales del convenio desde AEDA.

    aeda.dbo.fis_escalas  →  fisca_escala_salarial (origen «aeda»)

Una fila por vigencia (desde / hasta, AAAAMM) y antigüedad (0 a 35 años) con el
básico y el adicional por almuerzo. Al 14/11/2026 AEDA tiene 38 vigencias, de
2012-10 a 2023-09.

Uso
---
    python importar_aeda_fisca_escalas.py             simula y escribe el informe en logs/
    python importar_aeda_fisca_escalas.py --aplicar   lo mismo, y lo graba

Requiere sql/fisca_escalas_20261114.sql.

Decisiones
----------
- Clave: período desde + antigüedad (en AEDA no se repite). Se puede volver a
  correr: lo que cambió en AEDA se actualiza, lo igual no se toca.
- Lo cargado acá (origen «manual») no se pisa: si AEDA trae la misma clave,
  sale en el informe y queda lo del sindicato.
- No se borra nada: una vigencia que AEDA ya no tiene queda y se informa.
"""

import argparse
import sys
from collections import Counter
from datetime import datetime
from decimal import Decimal

# importar_aeda carga el .env y trae la conexión a AEDA.
from importar_aeda import CARPETA_LOGS, _filas, conexion_aeda, salir

from db import get_connection

SQL_AEDA = "SELECT desde, hasta, antig, basico, almuerzo FROM aeda.dbo.fis_escalas ORDER BY desde, antig"


def _d(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


def _per(v) -> str:
    return str(int(v)).zfill(6)


def main():
    parser = argparse.ArgumentParser(description="Escalas salariales del convenio desde AEDA (fis_escalas).")
    parser.add_argument("--aplicar", action="store_true", help="grabar en la base (sin esto, solo simula)")
    args = parser.parse_args()
    inicio = datetime.now()

    cn = conexion_aeda()
    try:
        cur_a = cn.cursor()
        aeda = _filas(cur_a, SQL_AEDA)
        cur_a.close()
    finally:
        cn.close()

    cuenta, avisos = Counter(), []
    filas = {}
    for f in aeda:
        if f["desde"] is None or f["antig"] is None:
            cuenta["filas de AEDA sin período o antigüedad (no entran)"] += 1
            continue
        clave = (_per(f["desde"]), int(f["antig"]))
        filas[clave] = {"desde": clave[0], "hasta": _per(f["hasta"] or f["desde"]), "antig": clave[1],
                        "basico": _d(f["basico"]), "almuerzo": _d(f["almuerzo"])}

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT COUNT(*) AS n FROM information_schema.tables
                            WHERE table_schema = DATABASE() AND table_name = 'fisca_escala_salarial'""")
            if not cur.fetchone()["n"]:
                salir("Falta correr sql/fisca_escalas_20261114.sql en esta base.")
            cur.execute("SELECT * FROM fisca_escala_salarial")
            ya = {(r["periodo_desde"], int(r["antiguedad"])): r for r in cur.fetchall()}

        nuevas, cambiadas = [], []
        for clave, f in filas.items():
            r = ya.get(clave)
            if not r:
                nuevas.append(f)
            elif r["origen"] != "aeda":
                cuenta["claves cargadas acá a mano (no se pisan)"] += 1
                avisos.append(f"{clave[0]} antigüedad {clave[1]}: cargada a mano, queda la del sindicato")
            elif (r["periodo_hasta"], _d(r["basico"]), _d(r["almuerzo"])) != (f["hasta"], f["basico"], f["almuerzo"]):
                cambiadas.append(f)
            else:
                cuenta["filas ya importadas sin cambios"] += 1
        for clave, r in ya.items():
            if r["origen"] == "aeda" and clave not in filas:
                cuenta["filas importadas antes que AEDA ya no tiene (quedan)"] += 1
                avisos.append(f"{clave[0]} antigüedad {clave[1]}: ya no está en AEDA")
        cuenta["filas nuevas"] += len(nuevas)
        cuenta["filas que cambiaron en AEDA (se actualizan)"] += len(cambiadas)

        conn.begin()
        try:
            with conn.cursor() as cur:
                cur.executemany("""INSERT INTO fisca_escala_salarial
                                     (periodo_desde, periodo_hasta, antiguedad, basico, almuerzo, origen)
                                   VALUES (%s, %s, %s, %s, %s, 'aeda')""",
                                [(f["desde"], f["hasta"], f["antig"], f["basico"], f["almuerzo"]) for f in nuevas])
                cur.executemany("""UPDATE fisca_escala_salarial SET periodo_hasta = %s, basico = %s, almuerzo = %s
                                    WHERE periodo_desde = %s AND antiguedad = %s AND origen = 'aeda'""",
                                [(f["hasta"], f["basico"], f["almuerzo"], f["desde"], f["antig"]) for f in cambiadas])
                cur.execute("""SELECT periodo_desde, periodo_hasta, COUNT(*) AS n FROM fisca_escala_salarial
                                WHERE origen = 'aeda' GROUP BY periodo_desde, periodo_hasta ORDER BY periodo_desde""")
                control = cur.fetchall()
            if args.aplicar:
                conn.commit()
                estado = "APLICADA"
            else:
                conn.rollback()
                estado = "SIMULACIÓN — no se grabó nada"
        except Exception:
            conn.rollback()
            print("\n  Falló la importación; no se grabó nada.\n")
            raise

    vig = sorted({(f["desde"], f["hasta"]) for f in filas.values()})
    CARPETA_LOGS.mkdir(exist_ok=True)
    informe = CARPETA_LOGS / f"importar_aeda_fisca_escalas_{inicio:%Y%m%d_%H%M%S}.txt"
    lineas = [f"Escalas salariales de AEDA (fis_escalas)  {inicio:%d/%m/%Y %H:%M}", estado,
              f"En AEDA: {len(aeda)} filas, {len(vig)} vigencias"
              + (f", de {vig[0][0]} a {vig[-1][1]}" if vig else ""), ""]
    lineas += [f"  {n:>6}  {k}" for k, n in cuenta.items()]
    lineas += ["", f"  En el sindicato (origen aeda): {sum(c['n'] for c in control)} filas, {len(control)} vigencias"]
    lineas += [f"  {a}" for a in avisos[:30]]
    informe.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print()
    print(informe.read_text(encoding="utf-8"))
    if not args.aplicar:
        print("  Para grabar:  python importar_aeda_fisca_escalas.py --aplicar\n")


if __name__ == "__main__":
    sys.exit(main())
