"""
importar_aeda_extractos.py — Los extractos del Banco Nación que AEDA ya cargó.

    adm_bna24   →  c_extractos_bancarios (origen «BNA»)

AEDA guarda en `adm_bna24` los movimientos de las cuentas del Nación que
descarga de BNA24 (cajabanco_id = la cuenta de `adm_ctasfondos`). Sirve para
probar la emisión de recibos y la conciliación sin volver a bajar los archivos
del banco; después se sigue importando el archivo en Extractos Bancarios, y lo
que ya entró por acá se reconoce como duplicado.

Uso
---
    python importar_aeda_extractos.py                       simula desde el corte de la conciliación
    python importar_aeda_extractos.py --aplicar             lo mismo, y lo graba
    python importar_aeda_extractos.py --desde 2026-10-01 [--hasta 2026-11-30]

Decisiones
----------
- Desde el corte de la conciliación (`s_configuracion` conc_fecha_corte,
  01/11/2026) si no se dice otra cosa: lo anterior se da por conciliado.
- La cuenta: la de `c_cuentas_de_fondos` con la marca «[AEDA adm_ctasfondos N]»
  (importar_aeda_tesoreria.py). Una cuenta de AEDA sin su par acá no entra.
- AEDA graba los débitos en negativo: acá van en positivo, como los deja el
  lector del archivo.
- El CUIT: el que AEDA sacó del archivo, en las acreditaciones; en los débitos
  solo si está en el concepto (en `adm_bna24` los débitos traen el CUIT propio
  de la cuenta, y marcarlo como contraparte arruinaría la conciliación).
- Duplicado = la regla de Extractos Bancarios: misma cuenta, número de
  operación, fecha e importe; los renglones idénticos se cuentan. Se puede
  volver a correr.
- Sin saldo: `adm_bna24` no lo guarda. El saldo de cierre se escribe al cerrar
  la conciliación.
"""

import argparse
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal

# importar_aeda carga el .env y trae la conexión a AEDA.
from importar_aeda import CARPETA_LOGS, conexion_aeda, limpio, salir, solo_digitos

from db import get_connection
from extractos_bancarios import _extraer_cuit

SQL_AEDA = """SELECT bna_id, cajabanco_id, fecham, fechav, ref_nro, debito, credito, concepto, cuit
                FROM aeda.dbo.adm_bna24
               WHERE fecham >= ? AND fecham < DATEADD(day, 1, ?)
               ORDER BY cajabanco_id, fecham, bna_id"""


def _d(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


def _dia(v):
    if v is None:
        return None
    return v.date() if isinstance(v, datetime) else v


def _pesos(v) -> str:
    return f"$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fecha(texto) -> date | None:
    try:
        return date.fromisoformat(texto)
    except (TypeError, ValueError):
        return None


def renglon(m: dict) -> dict:
    """Un renglón de adm_bna24 como lo grabaría el lector del archivo."""
    debito, credito = abs(_d(m["debito"])), abs(_d(m["credito"]))
    concepto = limpio(m["concepto"])[:100]
    cuit = _extraer_cuit(concepto)
    if not cuit and credito > 0:
        c = solo_digitos(limpio(m["cuit"]))
        cuit = c if len(c) == 11 else None
    # Como el lector del archivo: sin ceros a la izquierda, «0» si no hay número.
    ref = str(int(m["ref_nro"] or 0))
    return {"fecham": _dia(m["fecham"]), "fechav": _dia(m["fechav"]) or _dia(m["fecham"]), "ref_nro": ref,
            "debito": debito or None, "credito": credito or None, "concepto": concepto, "cuit": cuit,
            "aeda": m["bna_id"], "caja": m["cajabanco_id"]}


def _clave(r) -> tuple:
    return (r["ref_nro"] or "", r["fecham"], r["debito"] or Decimal("0"), r["credito"] or Decimal("0"),
            "" if r["ref_nro"] else r["concepto"])


def main():
    parser = argparse.ArgumentParser(description="Extractos del Nación de AEDA (adm_bna24).")
    parser.add_argument("--aplicar", action="store_true", help="grabar en la base (sin esto, solo simula)")
    parser.add_argument("--desde", help="AAAA-MM-DD (por defecto, el corte de la conciliación)")
    parser.add_argument("--hasta", help="AAAA-MM-DD (por defecto, hoy)")
    args = parser.parse_args()
    inicio = datetime.now()
    hasta = _fecha(args.hasta) or date.today()

    with get_connection() as conn:
        with conn.cursor() as cur:
            desde = _fecha(args.desde)
            if not desde:
                cur.execute("""SELECT valor FROM s_configuracion
                                WHERE modulo = 'tesoreria' AND parametro = 'conc_fecha_corte' LIMIT 1""")
                desde = _fecha(((cur.fetchone() or {}).get("valor") or "")[:10])
            if not desde:
                salir("No hay fecha de corte de la conciliación: pasá --desde AAAA-MM-DD.")
            cur.execute("SELECT id, nombre, tipo_de_cuenta, comentario FROM c_cuentas_de_fondos")
            cuentas, nombres = {}, {}
            for f in cur.fetchall():
                mm = re.match(r"^\[AEDA adm_ctasfondos (\d+)\]", f["comentario"] or "")
                if mm and f["tipo_de_cuenta"] == "B":
                    cuentas[int(mm.group(1))] = f["id"]
                nombres[f["id"]] = f["nombre"]
            if not cuentas:
                salir("No están las cuentas de fondos de AEDA. Correr antes importar_aeda_tesoreria.py --aplicar.")

    cn = conexion_aeda()
    try:
        c = cn.cursor()
        c.execute(SQL_AEDA, desde, hasta)
        columnas = [d[0] for d in c.description]
        aeda = [dict(zip(columnas, fila)) for fila in c.fetchall()]
        c.close()
    finally:
        cn.close()

    cuenta_txt, insertar, avisos = Counter(), [], []
    por_cuenta = defaultdict(list)
    for m in aeda:
        r = renglon(m)
        id_cuenta = cuentas.get(int(m["cajabanco_id"] or 0))
        if not id_cuenta:
            cuenta_txt["renglones de una cuenta de AEDA sin su cuenta acá (no entran)"] += 1
            avisos.append(f"bna_id {m['bna_id']}: cajabanco_id {m['cajabanco_id']} sin cuenta")
            continue
        if not (r["debito"] or r["credito"]):
            cuenta_txt["renglones en cero (no entran)"] += 1
            continue
        r["id_cuenta"] = id_cuenta
        por_cuenta[id_cuenta].append(r)

    ahora = inicio.replace(microsecond=0)
    resumen = defaultdict(lambda: [0, 0, Decimal("0"), Decimal("0")])   # nuevos, ya estaban, créditos, débitos
    with get_connection() as conn:
        conn.begin()
        try:
            with conn.cursor() as cur:
                for id_cuenta, filas in por_cuenta.items():
                    cur.execute("""SELECT COALESCE(ref_nro, '') AS ref, fecham, COALESCE(debito, 0) AS d,
                                          COALESCE(credito, 0) AS c, concepto
                                     FROM c_extractos_bancarios
                                    WHERE c_cuentas_de_fondos_id = %s AND fecham BETWEEN %s AND %s""",
                                (id_cuenta, desde, hasta))
                    previos = Counter((x["ref"], x["fecham"], _d(x["d"]), _d(x["c"]), "" if x["ref"] else x["concepto"])
                                      for x in cur.fetchall())
                    vistos = Counter()
                    for r in filas:
                        k = _clave({**r, "debito": r["debito"] or Decimal("0.00"), "credito": r["credito"] or Decimal("0.00")})
                        vistos[k] += 1
                        if vistos[k] <= previos[k]:
                            resumen[id_cuenta][1] += 1
                            continue
                        insertar.append(r)
                        resumen[id_cuenta][0] += 1
                        resumen[id_cuenta][2] += r["credito"] or 0
                        resumen[id_cuenta][3] += r["debito"] or 0
                cur.executemany("""INSERT INTO c_extractos_bancarios
                                     (c_cuentas_de_fondos_id, fecham, fechav, ref_nro, debito, credito, saldo,
                                      concepto, cuit, origen, importado)
                                   VALUES (%s, %s, %s, %s, %s, %s, NULL, %s, %s, 'BNA', %s)""",
                                [(r["id_cuenta"], r["fecham"], r["fechav"], r["ref_nro"], r["debito"], r["credito"],
                                  r["concepto"], r["cuit"], ahora) for r in insertar])
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

    CARPETA_LOGS.mkdir(exist_ok=True)
    informe = CARPETA_LOGS / f"importar_aeda_extractos_{inicio:%Y%m%d_%H%M%S}.txt"
    lineas = [f"Extractos del Nación de AEDA (adm_bna24)  {inicio:%d/%m/%Y %H:%M}", estado,
              f"Del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}: {len(aeda)} renglones en AEDA", ""]
    for id_cuenta, (n, ya, cr, db) in sorted(resumen.items()):
        lineas.append(f"  {nombres[id_cuenta]}: {n} nuevos ({ya} ya estaban) · créditos {_pesos(cr)} · débitos {_pesos(db)}")
    lineas += [f"  {n:>6}  {k}" for k, n in cuenta_txt.items()]
    lineas += [f"  {a}" for a in avisos[:20]]
    informe.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print()
    print(informe.read_text(encoding="utf-8"))
    if not args.aplicar:
        print("  Para grabar:  python importar_aeda_extractos.py --aplicar\n")


if __name__ == "__main__":
    sys.exit(main())
