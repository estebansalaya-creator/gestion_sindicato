"""
importar_aeda_plan_cuentas.py — El plan de cuentas de AEDA a `c_plan_de_cuentas`.

Origen: `aeda.dbo.adm_planctas` (151 cuentas, código 1-1-1-02-020). El plan de
AEDA es el del sindicato: cada concepto de gasto, motivo de ingreso y cuenta de
fondos de AEDA ya apunta a una de sus cuentas.

Uso
---
    python importar_aeda_plan_cuentas.py             simula y escribe el informe en logs/
    python importar_aeda_plan_cuentas.py --aplicar   lo mismo, y lo graba

importar_aeda_tesoreria.py hace lo mismo antes de las tablas de tesorería (usa
estas funciones), así que da igual cuál se corra primero.

Decisiones
----------
- El código se conserva tal cual y el número de AEDA (pcont_id) es el
  id_cuenta: las imputaciones de AEDA se resuelven sin tabla de equivalencias.
- Clase, nivel, madre, imputable y corriente salen del código, con las reglas
  de plan_cuentas.py (las mismas de la pantalla). AEDA marca «4-2-0-00-000
  INGRESOS DIVERSOS» como imputable aunque es un título con cinco cuentas
  debajo y sin asientos: entra como título, y el informe lo dice.
- AEDA no tiene las cuentas título 5-2-0-00-000 ni 5-3-0-00-000 (ni algunas
  más): las que irían debajo cuelgan de la más cercana que existe. Si después
  se crean en la pantalla, las cuentas se acomodan solas.
- Monetaria: disponibilidades, inversiones y créditos (1-1 salvo bienes de
  cambio) y todo el pasivo. Revisarlo con el contador antes del primer ajuste
  por inflación; se cambia en la ficha.
- AEDA repite un código (5-3-0-00-105 CAJA DE SEGURIDAD, 122 y 161): entra
  uno; lo que apunte al otro va a ese.
- Se puede correr más de una vez: una cuenta cuyo código ya está no se toca
  (puede haberse corregido en la pantalla).
"""

import argparse
import csv
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

# importar_aeda carga el .env y trae la conexión a AEDA.
from importar_aeda import CARPETA_LOGS, _filas, conexion_aeda, limpio, salir

import plan_cuentas as pc
from db import get_connection

SQL_PLAN = "SELECT pcont_id, codigo, titulo, imputable FROM aeda.dbo.adm_planctas"
#: AEDA rellena el título a 40 y en una cuenta quedó una letra suelta al final
#: («SUELDOS                                 N»).
RE_LETRA_SUELTA = re.compile(r"\s{5,}\S$")


def leer_destino(cur) -> dict:
    cur.execute("SELECT id_cuenta, codigo FROM c_plan_de_cuentas")
    filas = cur.fetchall()
    cur.execute("SELECT codigo FROM c_clasificacion_plan_cuentas")
    clases = {f["codigo"] for f in cur.fetchall()}
    if not clases:
        salir("c_clasificacion_plan_cuentas está vacía: faltan las clases 1 a 5 (activo … egresos).")
    return {"plan_por_codigo": {f["codigo"]: f["id_cuenta"] for f in filas},
            "plan_ids": {f["id_cuenta"] for f in filas}, "clasificaciones": clases}


@dataclass
class Plan:
    cuentas_plan: list[dict] = field(default_factory=list)
    mapa: dict = field(default_factory=dict)          # pcont_id → código
    titulos: dict = field(default_factory=dict)       # código → nombre en AEDA
    informe: list[dict] = field(default_factory=list)
    cuenta: dict = field(default_factory=dict)

    def contar(self, clave, n=1):
        self.cuenta[clave] = self.cuenta.get(clave, 0) + n

    def anotar(self, accion, **datos):
        self.informe.append({"accion": accion, **datos})


def _titulo(texto) -> str:
    t = str(texto or "").rstrip()
    return limpio(RE_LETRA_SUELTA.sub("", t))


def armar_plan_cuentas(filas_aeda, destino, plan):
    """Llena plan.cuentas_plan (las nuevas), plan.mapa y plan.titulos. `plan`
    puede ser el de este script o el de importar_aeda_tesoreria."""
    por_codigo = {}
    for f in sorted(filas_aeda, key=lambda x: (limpio(x["codigo"]), x["pcont_id"])):
        cod = limpio(f["codigo"])
        if not re.fullmatch(r"\d+(-\d+)+", cod):
            plan.contar("cuentas de AEDA con un código que no se entiende (no se importan)")
            plan.anotar("omitida", aeda=f"adm_planctas {f['pcont_id']}", codigo=cod, nombre=_titulo(f["titulo"]))
            continue
        if cod in por_codigo:
            plan.contar("cuentas de AEDA con el código repetido (entra una)")
            plan.anotar("repetida", aeda=f"adm_planctas {f['pcont_id']}", codigo=cod, nombre=_titulo(f["titulo"]),
                        nota=f"queda la {por_codigo[cod]['pcont_id']}; lo que apunte a esta va a esa")
            plan.mapa[f["pcont_id"]] = cod
            continue
        por_codigo[cod] = f
        plan.mapa[f["pcont_id"]] = cod
        plan.titulos[cod] = _titulo(f["titulo"])

    todos = set(por_codigo) | set(destino["plan_por_codigo"])
    hijos = defaultdict(int)
    for cod in todos:
        m = pc.madre(cod, todos)
        if m:
            hijos[m] += 1
    nuevas = []
    for cod, f in por_codigo.items():
        if cod in destino["plan_por_codigo"]:
            plan.contar("cuentas que ya estaban en el plan")
            continue
        clase = int(pc.tramos(cod)[0])
        notas = []
        if clase not in destino["clasificaciones"]:
            notas.append(f"la clase {clase} no está en c_clasificacion_plan_cuentas")
            clase = None
        imp = pc.imputable(cod)
        if bool(f["imputable"]) != imp:
            notas.append(("imputable" if f["imputable"] else "título") + " en AEDA; por el código es "
                         + ("imputable" if imp else "título") + (f" ({hijos[cod]} cuentas debajo)" if hijos[cod] else ""))
            plan.contar("cuentas con la marca de imputable de AEDA corregida por el código")
        falta = pc.faltantes(cod, todos)
        if falta:
            m = pc.madre(cod, todos)
            notas.append(f"AEDA no tiene {falta[0]}: cuelga de {m or 'la raíz'}")
            plan.contar("cuentas sin su madre en AEDA (cuelgan de la más cercana)")
        nuevas.append({"codigo": cod, "nombre": plan.titulos[cod][:150], "nivel": pc.nivel(cod),
                       "id_clasificacion": clase, "permite_movimiento": 1 if imp else 0,
                       "corriente": pc.corriente(cod), "es_monetario": pc.monetaria(cod),
                       "_id": f["pcont_id"] if f["pcont_id"] not in destino["plan_ids"] else None,
                       "_pcont": f["pcont_id"]})
        plan.anotar("crear cuenta", aeda=f"adm_planctas {f['pcont_id']}", codigo=cod, nombre=plan.titulos[cod],
                    tipo="imputable" if imp else "título", nota="; ".join(notas))
    plan.cuentas_plan = sorted(nuevas, key=lambda c: c["codigo"])
    plan.contar("cuentas a crear en el plan", len(nuevas))


def aplicar_plan_cuentas(cur, plan, destino) -> dict:
    """Graba las cuentas nuevas y arma la jerarquía. Devuelve código → id_cuenta."""
    ids = dict(destino["plan_por_codigo"])
    for c in plan.cuentas_plan:
        cols = ["codigo", "nombre", "nivel", "permite_movimiento", "activa", "es_monetario", "corriente",
                "id_clasificacion"]
        vals = [c["codigo"], c["nombre"], c["nivel"], c["permite_movimiento"], 1, c["es_monetario"],
                c["corriente"], c["id_clasificacion"]]
        if c["_id"]:
            cols.insert(0, "id_cuenta")
            vals.insert(0, c["_id"])
        cur.execute(f"INSERT INTO c_plan_de_cuentas ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                    vals)
        ids[c["codigo"]] = c["_id"] or cur.lastrowid
    if plan.cuentas_plan:
        pc.rearmar_jerarquia(cur)
    return ids


CAMPOS_INFORME = ["accion", "aeda", "codigo", "nombre", "tipo", "nota"]


def escribir_informe(plan: Plan, estado: str, inicio: datetime):
    CARPETA_LOGS.mkdir(exist_ok=True)
    base = CARPETA_LOGS / f"importar_aeda_plan_cuentas_{inicio:%Y%m%d_%H%M%S}"
    detalle, resumen = base.with_suffix(".csv"), base.with_suffix(".txt")
    with open(detalle, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_INFORME, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(plan.informe)
    lineas = [f"Plan de cuentas AEDA → sindicato  {inicio:%d/%m/%Y %H:%M}", estado, ""]
    lineas += [f"  {n:>6}  {k}" for k, n in plan.cuenta.items()]
    lineas += ["", f"Detalle: {detalle.name}"]
    resumen.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return resumen


def main():
    parser = argparse.ArgumentParser(description="Plan de cuentas desde AEDA.")
    parser.add_argument("--aplicar", action="store_true", help="grabar en la base (sin esto, solo simula)")
    args = parser.parse_args()
    inicio = datetime.now()

    cn = conexion_aeda()
    try:
        cur_a = cn.cursor()
        filas = _filas(cur_a, SQL_PLAN)
        cur_a.close()
    finally:
        cn.close()

    with get_connection() as conn:
        with conn.cursor() as cur:
            destino = leer_destino(cur)
        plan = Plan()
        armar_plan_cuentas(filas, destino, plan)
        estado = "SIMULACIÓN — no se grabó nada"
        if args.aplicar:
            conn.begin()
            try:
                with conn.cursor() as cur:
                    aplicar_plan_cuentas(cur, plan, destino)
                conn.commit()
                estado = "APLICADA"
            except Exception:
                conn.rollback()
                resumen = escribir_informe(plan, "FALLÓ — no se grabó nada", inicio)
                print(f"\n  Falló la importación; no se grabó nada. Plan en {resumen}\n")
                raise

    resumen = escribir_informe(plan, estado, inicio)
    print()
    print(resumen.read_text(encoding="utf-8"))
    if not args.aplicar:
        print("  Para grabar:  python importar_aeda_plan_cuentas.py --aplicar\n")


if __name__ == "__main__":
    sys.exit(main())
