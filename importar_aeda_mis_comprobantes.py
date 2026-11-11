"""
importar_aeda_mis_comprobantes.py — La copia de Mis Comprobantes que tiene AEDA,
a `f_mis_comprobantes`.

Origen: `aeda.dbo.adm_comprobafip`, donde AEDA guarda lo que ARCA informa como
recibido por el sindicato (Mis Comprobantes → Recibidos). Es lo mismo que la
pantalla Comprobantes ARCA importa del archivo del portal: con esto, la pantalla
arranca con la historia (desde septiembre de 2023) en vez de vacía, y cruza ya
contra los comprobantes que trajo `importar_aeda_cc_proveedores.py`.

Uso
---
    python importar_aeda_mis_comprobantes.py             simula y escribe el informe en logs/
    python importar_aeda_mis_comprobantes.py --aplicar   lo mismo, y lo graba

Cómo viene AEDA y qué se hace
-----------------------------
- `fecha` es texto «DD/MM/AAAA»; `tipo`, «11 - Factura C» (el código va a tres
  dígitos: 011); `prefijo` y `numero` van con ceros a 5 y 8, como el parser del
  archivo del portal.
- Importes: total, IVA, no gravado, exento y otros tal cual. El neto gravado
  AEDA lo tiene en cero casi siempre (solo 43 de 1.734 lo traen): queda en cero.
  El total es lo que se usa para cruzar y para el importe pendiente.
- Un comprobante repetido (misma clave CUIT + tipo + punto de venta + número)
  entra una vez: el que tiene CAE. Caso real: BALACTICO 0002-00000112, tres
  veces, una sola con CAE.
- Lo que no tiene fecha, CUIT de 11 dígitos, tipo o número no entra: va al
  informe con el motivo. Un tipo que no está en `arca_tipo_comprobante` entra
  igual y se avisa (la pantalla lo muestra con el código).

Qué pisa y qué no
-----------------
Lo importado se reconoce por `nombre_archivo` = «[AEDA adm_comprobafip]».
- Una clave que no está: se agrega.
- Una que vino de AEDA en una corrida anterior: se actualiza si cambió.
- Una que vino del archivo del portal (importado en la pantalla): no se toca. El
  archivo de ARCA es la fuente; AEDA es una copia, y además trae el neto por
  alícuota que AEDA no tiene.
- Nada se borra: un comprobante que AEDA dejó de tener sigue acá.

Después vincula con lo cargado (`comprobantes_datos.vincular_mis`) y marca la
verificación ARCA de lo que coincide en importe y CAE
(`comprobantes_datos.marcar_verificacion_mis`), igual que la pantalla al
importar el archivo. El informe dice cuántos quedan pendientes de cargar y
cuántos de esos son de emisores que no están dados de alta como proveedores.

EL PUNTO DE VENTA QUE AEDA CORTÓ
`adm_pasivo.prefijo` es varchar(4): un punto de venta tipeado con cinco dígitos
perdió el último («00011» quedó «0001», «00109» quedó «0010»), y así entró a
`f_comprobantes_arca`. Contra Mis Comprobantes, que tiene el bueno, no vincula
y el comprobante aparecería como pendiente de cargar cuando ya está cargado
(29 casos al 11/11/2026). Por eso hay una segunda vuelta
(`comprobantes_datos.vincular_mis_por_numero`, que usa también la pantalla): mismo CUIT, tipo, número e importe, otro punto de
venta, un único candidato que no esté vinculado a otra fila y CAE igual si los
dos lo tienen. Se vinculan y van al informe; el comprobante no se toca (no se
le marca la verificación ARCA, que pide el punto de venta igual).

La simulación hace todo dentro de una transacción y la deshace: los números del
informe son los que van a quedar.

Se puede correr todas las veces que haga falta mientras AEDA siga en uso.
"""

import argparse
import csv
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

# importar_aeda carga el .env y trae la conexión a AEDA.
from importar_aeda import CARPETA_LOGS, _filas, conexion_aeda, limpio, salir

import comprobantes_datos as cd
from db import get_connection

MARCA = "[AEDA adm_comprobafip]"
RE_TIPO = re.compile(r"^\s*(\d{1,3})")
CAMPOS = ("fecha_emision", "tipo_comprobante", "punto_de_venta", "numero", "cuit_emisor", "razon_social",
          "importe_neto", "importe_no_grav", "importe_exento", "importe_iva", "importe_otros",
          "importe_total", "moneda", "tipo_de_cambio", "cae", "nombre_archivo")
#: Lo que se compara para decidir si un comprobante de AEDA cambió.
COMPARAR = ("fecha_emision", "razon_social", "importe_neto", "importe_no_grav", "importe_exento",
            "importe_iva", "importe_otros", "importe_total", "cae")


# ─────────────────────────────────────────────────────────────────────────────
# Lectura y armado
# ─────────────────────────────────────────────────────────────────────────────

def leer_aeda(cn) -> list[dict]:
    cur = cn.cursor()
    filas = _filas(cur, """
        SELECT fecha, cuit, prefijo, numero, cae, tipo, netogra, nogra, exento, otro, iva, importe,
               nombre, orden
          FROM aeda.dbo.adm_comprobafip
         ORDER BY orden
    """)
    cur.close()
    return filas


def _fecha(texto):
    try:
        return datetime.strptime(limpio(texto)[:10], "%d/%m/%Y").date()
    except ValueError:
        return None


def _digitos(valor) -> str:
    return re.sub(r"\D", "", limpio(valor))


def _importe(valor) -> float:
    return round(float(valor or 0), 2)


@dataclass
class Plan:
    leidos: int = 0
    registros: list = field(default_factory=list)        # uno por clave, listo para grabar
    omitidos: list = field(default_factory=list)         # (fila de AEDA, motivo)
    repetidos: list = field(default_factory=list)        # (clave, cuántas, cuál quedó)
    tipos_desconocidos: Counter = field(default_factory=Counter)
    nuevos: list = field(default_factory=list)
    actualizar: list = field(default_factory=list)       # (id, registro)
    iguales: int = 0
    del_portal: int = 0                                  # ya estaban, cargados del archivo de ARCA
    # Después de aplicar (o simulado):
    vinculados: int = 0
    por_numero: list = field(default_factory=list)       # vinculados con otro punto de venta
    verificados: int = 0
    pendientes: int | None = None
    pendientes_sin_alta: int | None = None


def armar_registro(f: dict) -> tuple[dict | None, str | None]:
    """El registro de f_mis_comprobantes, o (None, motivo)."""
    fecha = _fecha(f["fecha"])
    cuit = _digitos(f["cuit"])
    m = RE_TIPO.match(limpio(f["tipo"]))
    pv, nro = _digitos(f["prefijo"]), _digitos(f["numero"])
    if not fecha:
        return None, f"fecha ilegible «{limpio(f['fecha'])}»"
    if len(cuit) != 11:
        return None, f"CUIT de {len(cuit)} dígitos «{limpio(f['cuit'])}»"
    if not m:
        return None, f"tipo ilegible «{limpio(f['tipo'])}»"
    if not pv or not nro:
        return None, "sin punto de venta o número"
    return {
        "fecha_emision":    fecha,
        "tipo_comprobante": m.group(1).zfill(3),
        "punto_de_venta":   pv.zfill(5)[-5:],
        "numero":           nro.zfill(8)[-8:],
        "cuit_emisor":      cuit,
        "razon_social":     limpio(f["nombre"])[:200] or None,
        "importe_neto":     _importe(f["netogra"]),
        "importe_no_grav":  _importe(f["nogra"]),
        "importe_exento":   _importe(f["exento"]),
        "importe_iva":      _importe(f["iva"]),
        "importe_otros":    _importe(f["otro"]),
        "importe_total":    _importe(f["importe"]),
        "moneda":           "PES",
        "tipo_de_cambio":   1,
        "cae":              _digitos(f["cae"])[:14] or None,
        "nombre_archivo":   MARCA,
        "_orden":           f["orden"] or 0,
    }, None


def _clave(r: dict) -> tuple:
    return (r["cuit_emisor"], r["tipo_comprobante"], r["punto_de_venta"], r["numero"])


def armar_plan(filas: list[dict], destino: dict) -> Plan:
    plan = Plan(leidos=len(filas))
    por_clave: dict = {}
    for f in filas:
        r, motivo = armar_registro(f)
        if not r:
            plan.omitidos.append((f, motivo))
            continue
        por_clave.setdefault(_clave(r), []).append(r)

    for clave, grupo in por_clave.items():
        # El que tiene CAE y, entre esos, el último que cargó AEDA.
        elegido = max(grupo, key=lambda r: (bool(r["cae"]), r["_orden"]))
        if len(grupo) > 1:
            plan.repetidos.append((clave, len(grupo), elegido))
        plan.registros.append(elegido)
        if elegido["tipo_comprobante"] not in destino["tipos"]:
            plan.tipos_desconocidos[elegido["tipo_comprobante"]] += 1

        actual = destino["existentes"].get(clave)
        if actual is None:
            plan.nuevos.append(elegido)
        elif actual["nombre_archivo"] != MARCA:
            plan.del_portal += 1
        elif any(_distinto(actual[c], elegido[c]) for c in COMPARAR):
            plan.actualizar.append((actual["id"], elegido))
        else:
            plan.iguales += 1
    return plan


def _distinto(a, b) -> bool:
    if isinstance(b, float):
        return abs(float(a or 0) - b) > 0.005
    return (a or None) != (b or None)


def leer_destino(cur) -> dict:
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.tables
                    WHERE table_schema = DATABASE() AND table_name = 'f_mis_comprobantes'""")
    if not cur.fetchone()["n"]:
        salir("Falta f_mis_comprobantes. Correr antes sql/comprobantes_20261107.sql.")
    cur.execute("SELECT codigo FROM arca_tipo_comprobante")
    tipos = {str(f["codigo"]).zfill(3) for f in cur.fetchall()}
    cur.execute(f"SELECT id, {', '.join(c for c in CAMPOS)} FROM f_mis_comprobantes")
    existentes = {(f["cuit_emisor"], str(f["tipo_comprobante"]).zfill(3), str(f["punto_de_venta"]).zfill(5),
                   str(f["numero"]).zfill(8)): f for f in cur.fetchall()}
    return {"tipos": tipos, "existentes": existentes}


# ─────────────────────────────────────────────────────────────────────────────
# Grabación
# ─────────────────────────────────────────────────────────────────────────────

def aplicar(cur, plan: Plan) -> None:
    columnas = ", ".join(CAMPOS)
    valores = ", ".join(f"%({c})s" for c in CAMPOS)
    for r in plan.nuevos:
        cur.execute(f"INSERT INTO f_mis_comprobantes ({columnas}) VALUES ({valores})", r)
    for id_mis, r in plan.actualizar:
        cur.execute(f"""UPDATE f_mis_comprobantes SET {', '.join(f'{c} = %({c})s' for c in COMPARAR)}
                         WHERE id = %(id)s AND nombre_archivo = %(marca)s""",
                    dict(r, id=id_mis, marca=MARCA))
    plan.vinculados = cd.vincular_mis(cur)
    plan.por_numero = cd.vincular_mis_por_numero(cur)
    plan.verificados = cd.marcar_verificacion_mis(cur)
    contar_pendientes(cur, plan)


def contar_pendientes(cur, plan: Plan) -> None:
    """Pendientes = sin comprobante con expediente y sin descartar, como en la pantalla."""
    from mis_comprobantes import SQL_PENDIENTE
    cur.execute(f"""SELECT COUNT(*) AS n,
                           COALESCE(SUM(NOT EXISTS (SELECT 1 FROM c_proveedores p WHERE p.cuit = m.cuit_emisor)), 0) AS sin_alta
                      FROM f_mis_comprobantes m WHERE {SQL_PENDIENTE}""")
    f = cur.fetchone()
    plan.pendientes, plan.pendientes_sin_alta = int(f["n"]), int(f["sin_alta"])


def pendientes_detalle(cur) -> list[dict]:
    from mis_comprobantes import SQL_PENDIENTE
    cur.execute(f"""SELECT m.fecha_emision, m.cuit_emisor, m.razon_social, m.tipo_comprobante, m.punto_de_venta,
                           m.numero, m.importe_total, m.cae, m.nombre_archivo,
                           EXISTS (SELECT 1 FROM c_proveedores p WHERE p.cuit = m.cuit_emisor) AS proveedor
                      FROM f_mis_comprobantes m WHERE {SQL_PENDIENTE}
                     ORDER BY m.fecha_emision, m.cuit_emisor""")
    return cur.fetchall()


# ─────────────────────────────────────────────────────────────────────────────
# Informe
# ─────────────────────────────────────────────────────────────────────────────

def escribir_informe(plan: Plan, aplicado: bool, inicio: datetime, pendientes: list[dict]):
    CARPETA_LOGS.mkdir(exist_ok=True)
    sello = inicio.strftime("%Y%m%d_%H%M%S")
    resumen = CARPETA_LOGS / f"importar_aeda_mis_comprobantes_{sello}.txt"
    detalle = CARPETA_LOGS / f"importar_aeda_mis_comprobantes_{sello}.csv"

    tipos = Counter(r["tipo_comprobante"] for r in plan.registros)
    fechas = [r["fecha_emision"] for r in plan.registros]
    lineas = [
        f"  Mis Comprobantes desde AEDA (adm_comprobafip) — {'GRABADO' if aplicado else 'SIMULACIÓN, no se grabó nada'}",
        f"  {inicio:%d/%m/%Y %H:%M}",
        "",
        f"  Filas leídas de AEDA          {plan.leidos:>6}",
        f"  Comprobantes distintos        {len(plan.registros):>6}"
        + (f"   (del {min(fechas):%d/%m/%Y} al {max(fechas):%d/%m/%Y})" if fechas else ""),
        f"    nuevos                      {len(plan.nuevos):>6}",
        f"    actualizados (cambió AEDA)  {len(plan.actualizar):>6}",
        f"    iguales a lo ya importado   {plan.iguales:>6}",
        f"    ya estaban por el archivo   {plan.del_portal:>6}   (no se tocan: manda el archivo de ARCA)",
        f"  Repetidos en AEDA             {len(plan.repetidos):>6}   (entra uno por clave)",
        f"  Omitidos                      {len(plan.omitidos):>6}",
        "",
        "  Por tipo: " + ", ".join(f"{t} × {n}" for t, n in sorted(tipos.items())),
    ]
    if plan.tipos_desconocidos:
        lineas.append("  Tipos que no están en arca_tipo_comprobante (entran igual): "
                      + ", ".join(f"{t} × {n}" for t, n in sorted(plan.tipos_desconocidos.items())))
    for clave, n, elegido in plan.repetidos:
        lineas.append(f"  Repetido {n} veces: CUIT {clave[0]} {clave[1]} {clave[2]}-{clave[3]}"
                      f" — quedó el de CAE {elegido['cae'] or '(sin CAE)'}")
    for f, motivo in plan.omitidos[:20]:
        lineas.append(f"  Omitido (orden {f.get('orden')}): {motivo}")
    lineas += ["",
               f"  Vinculados en esta corrida              {plan.vinculados + len(plan.por_numero):>6}",
               f"    de esos, con otro punto de venta      {len(plan.por_numero):>6}   (AEDA lo cortó: ver el detalle)",
               f"  Marcados verificados por ARCA (corrida) {plan.verificados:>6}",
               f"  Pendientes de cargar (toda la tabla)    {plan.pendientes:>6}"
               f"   ({plan.pendientes_sin_alta} de emisores sin alta de proveedor)"]
    lineas.append("")
    resumen.write_text("\n".join(lineas), encoding="utf-8")

    with detalle.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["que", "fecha", "cuit", "razon_social", "tipo", "punto_de_venta", "numero", "total", "cae",
                    "motivo"])
        for f, motivo in plan.omitidos:
            w.writerow(["omitido", limpio(f["fecha"]), limpio(f["cuit"]), limpio(f["nombre"]), limpio(f["tipo"]),
                        limpio(f["prefijo"]), limpio(f["numero"]), f["importe"], limpio(f["cae"]), motivo])
        for p in plan.por_numero:
            w.writerow(["vinculado otro pv", "", p["cuit_emisor"], "", p["tipo_comprobante"], p["pv_arca"],
                        p["numero"], p["importe_total"], "",
                        f"cargado con punto de venta {p['pv_cargado']} (id {p['id_comprobante']})"])
        for id_mis, r in plan.actualizar:
            w.writerow(["actualizado", r["fecha_emision"], r["cuit_emisor"], r["razon_social"],
                        r["tipo_comprobante"], r["punto_de_venta"], r["numero"], r["importe_total"], r["cae"], ""])
        for p in pendientes:
            w.writerow(["pendiente", p["fecha_emision"], p["cuit_emisor"], p["razon_social"], p["tipo_comprobante"],
                        p["punto_de_venta"], p["numero"], p["importe_total"], p["cae"],
                        "" if p["proveedor"] else "emisor sin alta de proveedor"])
    return resumen, detalle


def main():
    parser = argparse.ArgumentParser(description="Mis Comprobantes (adm_comprobafip) desde AEDA.")
    parser.add_argument("--aplicar", action="store_true", help="grabar en la base (sin esto, solo simula)")
    args = parser.parse_args()
    inicio = datetime.now()

    cn = conexion_aeda()
    try:
        filas = leer_aeda(cn)
    finally:
        cn.close()

    with get_connection() as conn:
        with conn.cursor() as cur:
            plan = armar_plan(filas, leer_destino(cur))
        # También la simulación graba, dentro de la transacción, y la deshace:
        # así vínculos y pendientes del informe son los que van a quedar.
        conn.begin()
        try:
            with conn.cursor() as cur:
                aplicar(cur, plan)
                pendientes = pendientes_detalle(cur)
            if args.aplicar:
                conn.commit()
            else:
                conn.rollback()
        except Exception:
            conn.rollback()
            print("\n  Falló la importación; no se grabó nada.\n")
            raise

    resumen, detalle = escribir_informe(plan, args.aplicar, inicio, pendientes)
    print()
    print(resumen.read_text(encoding="utf-8"))
    print(f"  Detalle: {detalle}")
    if not args.aplicar:
        print("  Para grabar:  python importar_aeda_mis_comprobantes.py --aplicar\n")


if __name__ == "__main__":
    sys.exit(main())
