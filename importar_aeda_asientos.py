"""
importar_aeda_asientos.py — Los asientos contables de AEDA al Libro Diario.

    aeda.dbo.adm_asientos + adm_asienpase + adm_asienref  →  c_asientos + c_asiento_detalle
                                                              (origen «aeda», id_origen = asto_id)

AEDA arma un asiento por cada pago (OP), pase entre cuentas (PF), orden de
ingreso (OI), depósito (DB) y algunos ajustes (AP, AI): 4.584 al 17/11/2026,
de octubre de 2023 en adelante, todos en su ejercicio 1 (Adm_Ejercicios está
vacía). Pedido del 18/11/2026, junto con el Libro Diario.

Uso
---
    python importar_aeda_asientos.py                     simula y escribe el informe en logs/
    python importar_aeda_asientos.py --aplicar           lo mismo, y lo graba
    python importar_aeda_asientos.py --crear-ejercicios  abre los ejercicios que falten (por año
                                                         calendario, «Ejercicio AAAA») antes de importar
    --desde AAAA-MM-DD / --hasta AAAA-MM-DD              solo ese rango de fechas

Requiere sql/contabilidad_diario_20261118.sql (c_asientos.origen / id_origen) y
que haya ejercicios con períodos que cubran las fechas (Contabilidad ›
Ejercicios, o --crear-ejercicios).

Decisiones
----------
- La cuenta: `pcont_id` de AEDA es `id_cuenta` del plan del sindicato (lo trajo
  importar_aeda_plan_cuentas.py con el mismo id).
- AEDA deja SIN CUENTA (pcont_id 0) el renglón del afiliado en los pagos de
  reintegros y subsidios (664 renglones al 17/11/2026). Acá se imputa al gasto,
  como registra el sindicato los reintegros: el pago → lo que cancela
  (adm_pasivoAplic) → el reintegro (afi_reintegros) → su concepto
  (adm_cptogasto.pcont_id), un renglón por concepto con lo aplicado. Lo que no
  se puede rastrear (un pago a un afiliado que no cancela ningún reintegro) va
  a la cuenta de --cuenta-sin-imputar (por defecto 5-3-0-00-150 GASTOS
  GENERALES, la que usó importar_aeda_cc_afiliados.py) y sale en el informe.
- Confirmado si balancea y todas sus cuentas son imputables; si no, entra en
  BORRADOR para corregirlo en el Diario (al 17/11/2026, 12 de AEDA no
  balancean) y sale en el informe.
- Número: el de AEDA (asto_nro, único en AEDA). «Renumerar» en el Diario los
  ordena por fecha, si se quiere.
- Referencia: lo que AEDA ata al asiento (adm_asienref), «OP 4475» = el pago
  AEDA-PG-4475 de acá (pago_id), «OI», «PF», «DB»...
- Se puede volver a correr: lo que ya está (origen aeda + asto_id) no se toca.
  Un asiento cuya fecha cae en un período cerrado no entra (sale en el informe).
"""

import argparse
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal

from importar_aeda import CARPETA_LOGS, conexion_aeda, salir

import asientos as A
from db import get_connection

CUENTA_SIN_IMPUTAR = "5-3-0-00-150"

SQL_ASIENTOS = """
    SELECT a.asto_id, a.asto_nro, a.fecha, a.descrip, a.usr
      FROM aeda.dbo.adm_asientos a
     WHERE a.fecha BETWEEN ? AND ?
     ORDER BY a.fecha, a.asto_nro"""
SQL_PASES = """
    SELECT p.asto_id, p.asto_pase, p.pcont_id, p.debe, p.haber, CAST(p.descrip AS varchar(255)) AS descrip
      FROM aeda.dbo.adm_asienpase p JOIN aeda.dbo.adm_asientos a ON a.asto_id = p.asto_id
     WHERE a.fecha BETWEEN ? AND ?
     ORDER BY p.asto_id, p.asto_pase"""
SQL_REFS = """
    SELECT r.asto_id, r.ref_id, r.ref_nro
      FROM aeda.dbo.adm_asienref r JOIN aeda.dbo.adm_asientos a ON a.asto_id = r.asto_id
     WHERE a.fecha BETWEEN ? AND ?"""
# El gasto de los pagos a afiliados: lo que cada pago cancela, por concepto.
SQL_REINTEGROS = """
    SELECT r.asto_id, cg.pcont_id, MAX(cg.descrip) AS concepto, SUM(ap.aplicado) AS aplicado,
           COUNT(DISTINCT ri.reintegro_id) AS reintegros
      FROM aeda.dbo.adm_asienref r
      JOIN aeda.dbo.adm_asientos a ON a.asto_id = r.asto_id
      JOIN aeda.dbo.adm_pasivoAplic ap ON ap.aplica_id = r.ref_nro AND ap.tipo_aplic = 'P' AND ap.estado <> 'X'
      JOIN aeda.dbo.adm_pasivo pv ON pv.comp_id = ap.comp_id
      JOIN aeda.dbo.afi_reintegros ri ON ri.reintegro_id = pv.numero
      JOIN aeda.dbo.adm_cptogasto cg ON cg.conc_id = ri.conc_id
     WHERE r.ref_id = 'OP' AND a.fecha BETWEEN ? AND ?
       AND EXISTS (SELECT 1 FROM aeda.dbo.adm_asienpase p WHERE p.asto_id = r.asto_id AND p.pcont_id = 0)
     GROUP BY r.asto_id, cg.pcont_id"""


def _filas(cur, sql: str, params=()) -> list[dict]:
    cur.execute(sql, params)
    columnas = [d[0] for d in cur.description]
    return [dict(zip(columnas, fila)) for fila in cur.fetchall()]


def _d(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


def _fecha(v):
    return v.date() if isinstance(v, datetime) else v


def leer_aeda(desde, hasta) -> dict:
    cn = conexion_aeda()
    try:
        cur = cn.cursor()
        datos = {"asientos": _filas(cur, SQL_ASIENTOS, (desde, hasta)), "pases": _filas(cur, SQL_PASES, (desde, hasta)),
                 "refs": _filas(cur, SQL_REFS, (desde, hasta)), "reint": _filas(cur, SQL_REINTEGROS, (desde, hasta))}
        cur.close()
    finally:
        cn.close()
    return datos


def armar(datos: dict, cuentas: dict, id_sin_imputar: int) -> tuple[list[dict], Counter, list[str]]:
    """Los asientos a grabar, sin tocar la base. `cuentas`: id → fila del plan."""
    cuenta, avisos = Counter(), []
    pases, refs, reint = defaultdict(list), defaultdict(list), defaultdict(list)
    for p in datos["pases"]:
        pases[p["asto_id"]].append(p)
    for r in datos["refs"]:
        refs[r["asto_id"]].append(f"{(r['ref_id'] or '').strip()} {r['ref_nro']}")
    for r in datos["reint"]:
        reint[r["asto_id"]].append(r)
    out = []
    for a in datos["asientos"]:
        aid = a["asto_id"]
        renglones, notas = [], []
        for p in pases.get(aid, []):
            debe, haber = _d(p["debe"]), _d(p["haber"])
            if not debe and not haber:
                continue
            desc = (p["descrip"] or "").strip() or None
            if int(p["pcont_id"] or 0) == 0:
                # El renglón del afiliado: al gasto de lo que el pago canceló.
                rs = [r for r in reint.get(aid, []) if int(r["pcont_id"] or 0)]
                if rs and abs(sum(_d(r["aplicado"]) for r in rs) - (debe or haber)) < Decimal("0.01"):
                    for r in rs:
                        imp = _d(r["aplicado"])
                        renglones.append({"id_cuenta": int(r["pcont_id"]), "debe": imp if debe else Decimal("0"),
                                          "haber": imp if haber else Decimal("0"),
                                          "descripcion": (desc or (r["concepto"] or "").strip() or None)})
                    cuenta["renglones sin cuenta en AEDA, imputados al concepto del reintegro"] += 1
                else:
                    renglones.append({"id_cuenta": id_sin_imputar, "debe": debe, "haber": haber,
                                      "descripcion": desc or "Sin cuenta en AEDA"})
                    cuenta["renglones sin cuenta en AEDA, a la cuenta sin imputar"] += 1
                    notas.append("renglón sin cuenta en AEDA, a la cuenta sin imputar")
                continue
            renglones.append({"id_cuenta": int(p["pcont_id"]), "debe": debe, "haber": haber, "descripcion": desc})
        td = sum((r["debe"] for r in renglones), Decimal("0"))
        th = sum((r["haber"] for r in renglones), Decimal("0"))
        malas = [r["id_cuenta"] for r in renglones if r["id_cuenta"] not in cuentas]
        titulos = [r["id_cuenta"] for r in renglones if r["id_cuenta"] in cuentas
                   and not cuentas[r["id_cuenta"]]["permite_movimiento"]]
        if malas:
            notas.append(f"cuenta(s) {', '.join(map(str, sorted(set(malas))))} que no están en el plan")
        if titulos:
            notas.append(f"cuenta(s) título {', '.join(cuentas[c]['codigo'] for c in sorted(set(titulos)))}")
        if td != th:
            notas.append(f"no balancea: debe {A.pesos(td)}, haber {A.pesos(th)}")
        if len(renglones) < 2:
            notas.append("menos de dos renglones")
        out.append({"asto_id": aid, "numero": int(a["asto_nro"]), "fecha": _fecha(a["fecha"]),
                    "descripcion": (a["descrip"] or "").strip() or f"Asiento AEDA {a['asto_nro']}",
                    "referencia": ", ".join(sorted(refs.get(aid, [])))[:80] or None,
                    "usuario": f"AEDA {(a['usr'] or '').strip()}".strip()[:80], "renglones": renglones,
                    "notas": notas, "valido": not malas, "confirmar": not notas or notas == [
                        "renglón sin cuenta en AEDA, a la cuenta sin imputar"]})
        if notas:
            avisos.append(f"N° {a['asto_nro']} del {_fecha(a['fecha']):%d/%m/%Y} ({a['descrip']}): " + "; ".join(notas))
    return out, cuenta, avisos


def crear_ejercicios(cur, fechas, cuenta: Counter) -> None:
    """Abre por año calendario los ejercicios que falten para cubrir las fechas."""
    import institucion
    inst = institucion.obtener()
    for anio in sorted({f.year for f in fechas}):
        if A.periodo_de_fecha(cur, date(anio, 1, 1)) and A.periodo_de_fecha(cur, date(anio, 12, 31)):
            continue
        try:
            A.abrir_ejercicio(cur, f"Ejercicio {anio}", date(anio, 1, 1), date(anio, 12, 31), inst.get("cuit"),
                              inst.get("nombre"), "importar_aeda_asientos")
            cuenta[f"ejercicio {anio} abierto"] += 1
        except A.ErrorContable as e:
            # Ya hay un ejercicio que cubre parte del año (no calendario): ese manda.
            cuenta[f"ejercicio {anio} no se abrió: {e}"] += 1


def main():
    ap = argparse.ArgumentParser(description="Asientos contables de AEDA al Libro Diario.")
    ap.add_argument("--aplicar", action="store_true", help="grabar (sin esto, solo simula)")
    ap.add_argument("--crear-ejercicios", action="store_true", help="abrir por año los ejercicios que falten")
    ap.add_argument("--desde", default="2000-01-01")
    ap.add_argument("--hasta", default="2100-12-31")
    ap.add_argument("--cuenta-sin-imputar", default=CUENTA_SIN_IMPUTAR,
                    help=f"código de la cuenta para lo que AEDA deja sin cuenta y no se rastrea (por defecto "
                         f"{CUENTA_SIN_IMPUTAR})")
    args = ap.parse_args()
    inicio = datetime.now()
    desde, hasta = date.fromisoformat(args.desde), date.fromisoformat(args.hasta)

    with get_connection() as conn:
        with conn.cursor() as cur:
            if not A.tiene_origen(cur):
                salir("Falta correr sql/contabilidad_diario_20261118.sql (c_asientos.origen / id_origen).")
            cuentas = A.cuentas_por_id(cur)
            sin_imp = next((c for c in cuentas.values() if c["codigo"] == args.cuenta_sin_imputar), None)
            if not sin_imp or not sin_imp["permite_movimiento"]:
                salir(f"La cuenta {args.cuenta_sin_imputar} no está en el plan o no es imputable.")

    datos = leer_aeda(desde, hasta)
    asientos, cuenta, avisos = armar(datos, cuentas, sin_imp["id_cuenta"])
    cuenta["asientos en AEDA (en el rango)"] = len(datos["asientos"])

    with get_connection() as conn:
        conn.begin()
        try:
            with conn.cursor() as cur:
                if args.crear_ejercicios:
                    crear_ejercicios(cur, [a["fecha"] for a in asientos], cuenta)
                cur.execute("SELECT id_origen FROM c_asientos WHERE origen = 'aeda'")
                ya = {r["id_origen"] for r in cur.fetchall()}
                per_cache = {}
                for a in asientos:
                    if a["asto_id"] in ya:
                        cuenta["ya importados (no se tocan)"] += 1
                        continue
                    if not a["valido"]:
                        cuenta["con cuentas que no están en el plan (no entran)"] += 1
                        continue
                    clave = (a["fecha"].year, a["fecha"].month, a["fecha"].day)
                    per = per_cache.get(clave)
                    if per is None:
                        per = per_cache[clave] = A.periodo_de_fecha(cur, a["fecha"]) or {}
                    if not per:
                        cuenta["sin ejercicio para la fecha (no entran)"] += 1
                        avisos.append(f"N° {a['numero']} del {a['fecha']:%d/%m/%Y}: no hay ejercicio para esa fecha")
                        continue
                    if per["estado"] != "abierto":
                        cuenta["en un período cerrado (no entran)"] += 1
                        avisos.append(f"N° {a['numero']} del {a['fecha']:%d/%m/%Y}: el período {per['nombre']} está "
                                      f"{per['estado']}")
                        continue
                    estado = "confirmado" if a["confirmar"] else "borrador"
                    cur.execute("""INSERT INTO c_asientos (id_periodo, numero, fecha, descripcion, tipo, referencia,
                                                           estado, usuario, origen, id_origen)
                                   VALUES (%s, %s, %s, %s, 'operacion', %s, %s, %s, 'aeda', %s)""",
                                (per["id_periodo"], a["numero"], a["fecha"], a["descripcion"][:255], a["referencia"],
                                 estado, a["usuario"], a["asto_id"]))
                    nid = cur.lastrowid
                    cur.executemany("""INSERT INTO c_asiento_detalle (id_asiento, id_cuenta, debe, haber, descripcion)
                                       VALUES (%s, %s, %s, %s, %s)""",
                                    [(nid, r["id_cuenta"], r["debe"], r["haber"], (r["descripcion"] or None) and
                                      r["descripcion"][:255]) for r in a["renglones"]])
                    cuenta["importados confirmados" if estado == "confirmado" else "importados en borrador"] += 1
                # Control: lo importado suma lo mismo que AEDA.
                cur.execute("""SELECT COUNT(DISTINCT a.id_asiento) AS n, COALESCE(SUM(d.debe), 0) AS debe,
                                      COALESCE(SUM(d.haber), 0) AS haber
                                 FROM c_asientos a JOIN c_asiento_detalle d ON d.id_asiento = a.id_asiento
                                WHERE a.origen = 'aeda' AND a.fecha BETWEEN %s AND %s""", (desde, hasta))
                ctrl = cur.fetchone()
            if args.aplicar:
                conn.commit()
                estado_txt = "APLICADA"
            else:
                conn.rollback()
                estado_txt = "SIMULACIÓN — no se grabó nada"
        except Exception:
            conn.rollback()
            print("\n  Falló la importación; no se grabó nada.\n")
            raise

    aeda_debe = sum(_d(p["debe"]) for p in datos["pases"])
    aeda_haber = sum(_d(p["haber"]) for p in datos["pases"])
    CARPETA_LOGS.mkdir(exist_ok=True)
    informe = CARPETA_LOGS / f"importar_aeda_asientos_{inicio:%Y%m%d_%H%M%S}.txt"
    lineas = [f"Asientos de AEDA al Libro Diario  {inicio:%d/%m/%Y %H:%M}", estado_txt,
              f"Rango: {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}", ""]
    lineas += [f"  {n:>6}  {k}" for k, n in cuenta.items()]
    lineas += ["", f"  AEDA:      debe {A.pesos(aeda_debe)}  haber {A.pesos(aeda_haber)}",
               f"  Sindicato: {ctrl['n']} asientos de AEDA, debe {A.pesos(ctrl['debe'])}  haber {A.pesos(ctrl['haber'])}"
               + ("  (todo lo de AEDA)" if ctrl["n"] == len(datos["asientos"]) else ""), ""]
    lineas += [f"  {x}" for x in avisos[:200]]
    if len(avisos) > 200:
        lineas.append(f"  … y {len(avisos) - 200} más")
    informe.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print()
    print(informe.read_text(encoding="utf-8"))
    if not args.aplicar:
        print("  Para grabar:  python importar_aeda_asientos.py --aplicar"
              + ("" if args.crear_ejercicios else "  (--crear-ejercicios abre los que falten)") + "\n")


if __name__ == "__main__":
    sys.exit(main())
