"""
antiguedad_ddjj.py — Antigüedad de los afiliados según las DDJJ de OSEDA.

Para cada afiliado titular activo con relación laboral vigente (la nómina del
padrón, la misma regla que cruce_nomina_ddjj.py) busca en qué períodos lo
declaró ESE empleador en la DDJJ de OSEDA y la compara con la fecha de ingreso
del padrón (`p_relaciones_laborales.fecha_inicio`, la que vino de AEDA).

La DDJJ se lee de `oseda.dbo.afi_redapo` en el SQL Server de origen (el del
conector sqlserver-origen), no de `f_ddjj_procesada` de contable: en contable
se descartaron períodos y la serie empieza en 199807; en afi_redapo empieza en
199607. Solo lectura, con la misma conexión que los importadores de AEDA.

El ingreso según la DDJJ es el principio del TRAMO ACTUAL: hacia atrás desde el
último período declarado por el empleador, mientras no falten más de --hueco
meses seguidos (por defecto 2: una DDJJ que no se presentó a tiempo no corta).
Un tramo que empieza en el primer período de afi_redapo es «al menos»: la
antigüedad real puede ser mayor.

Resultado por afiliado:

    coincide          ingreso del padrón y tramo de la DDJJ a ±--tolerancia meses
    DDJJ anterior     la DDJJ empieza antes: la fecha del padrón sería la de
                      afiliación al gremio, no la de ingreso a la empresa
    DDJJ posterior    la DDJJ empieza después: antes aportaba a otra obra social
                      o hubo un corte de más de --hueco meses
    sin fecha         el padrón no tiene ingreso (o es el 01/01/1900 de AEDA)
    sin DDJJ          su empleador nunca lo declaró en OSEDA (otra obra social,
                      o lo declara otro CUIT: se muestra cuál)

La «fecha sugerida» es la más antigua de las dos cuando difieren (la DDJJ
prueba que ya trabajaba ahí; una fecha del padrón anterior a la DDJJ puede
venir de otra obra social), y la de la DDJJ cuando el padrón no tiene.

Con --aplicar la graba en `p_relaciones_laborales.fecha_antiguedad` (+ origen,
«al menos», nota y fecha del cálculo; sql/antiguedad_20261114.sql), que es de
donde cuentan la antigüedad la Nómina del empleador y la ficha del afiliado.
`fecha_inicio` no se toca. Solo las relaciones vigentes de titulares activos.
Una relación cuya fecha desde se editó en la ficha después del último cálculo
no se pisa: manda lo cargado a mano; tampoco una que informó el empleador
(origen «empresa»).

Uso
---
    python antiguedad_ddjj.py                  simula: no graba nada
    python antiguedad_ddjj.py --aplicar        graba la fecha sugerida
    python antiguedad_ddjj.py --hueco 3 --tolerancia 2

Deja en logs/ el resumen (.txt) y la planilla por afiliado (.xlsx).
"""

import argparse
import sys
from collections import defaultdict
from datetime import date, datetime

# importar_aeda carga el .env.
from importar_aeda import CARPETA_LOGS, conexion_aeda, salir

from db import get_connection
from exportar import xlsx

#: Base de la obra social en el servidor de origen. Fija, como AEDA_DB.
OSEDA_DB = "oseda"
#: Código de OSEDA en las DDJJ (el mismo filtro que contable_oseda.py).
CODOSOC = "106104"
#: CUIL por consulta (el IN de SQL Server admite bastante más; así cada
#: consulta tarda poco y no se corta por tiempo).
LOTE = 400
#: Fecha que AEDA usa como «sin dato».
SIN_DATO = date(1900, 1, 1)

RESULTADOS = {"coincide": "Coincide", "ddjj_antes": "DDJJ anterior", "ddjj_despues": "DDJJ posterior",
              "sin_fecha": "Sin fecha en el padrón", "sin_ddjj": "Sin DDJJ de su empleador"}


def _mes(p: str) -> int:
    """'AAAAMM' → número de mes corrido."""
    return int(p[:4]) * 12 + int(p[4:]) - 1


def _per(p: str | None) -> str:
    return f"{p[:4]}-{p[4:]}" if p else ""


def _fecha(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if isinstance(d, date) else ""


def _años(desde: date, hasta: date) -> int:
    return hasta.year - desde.year - ((hasta.month, hasta.day) < (desde.month, desde.day))


def _num(v) -> str:
    return "" if v is None else str(int(v))


def leer_nomina(cur) -> list[dict]:
    cur.execute("""SELECT r.id_relacion, r.cuit_empleador AS cuit, a.cuil, a.apellido_nombres, a.id_afiliado,
                          r.fecha_inicio, r.fecha_antiguedad, r.antiguedad_origen, r.antiguedad_al_menos,
                          r.antiguedad_nota, r.antiguedad_calculada, r.updated_at, e.razon_social
                     FROM p_relaciones_laborales r
                     JOIN p_afiliados a ON a.cuil = r.cuil
                     LEFT JOIN p_empresas e ON e.CUIT = CAST(r.cuit_empleador AS UNSIGNED)
                    WHERE r.estado = 'activa' AND (r.fecha_fin IS NULL OR r.fecha_fin >= CURDATE())
                      AND a.fecha_baja IS NULL AND a.cod_parentesco = 0
                      AND r.cuit_empleador REGEXP '^[0-9]{11}$' AND a.cuil REGEXP '^[0-9]{11}$'
                    ORDER BY r.cuit_empleador, a.apellido_nombres""")
    return list(cur.fetchall())


def leer_ddjj(cn, cuiles: list[str]) -> tuple[dict, str, str]:
    """{cuil: {cuit: {periodos}}}, primer y último período de afi_redapo."""
    cur = cn.cursor()
    cur.execute(f"SELECT MIN(periodo), MAX(periodo) FROM {OSEDA_DB}.dbo.afi_redapo WHERE codosoc = ?",
                CODOSOC)
    primero, ultimo = cur.fetchone()
    por_cuil: dict = defaultdict(lambda: defaultdict(set))
    for i in range(0, len(cuiles), LOTE):
        lote = cuiles[i:i + LOTE]
        marcas = ",".join("?" * len(lote))
        cur.execute(f"""SELECT cuil, cuit, periodo FROM {OSEDA_DB}.dbo.afi_redapo
                         WHERE codosoc = ? AND cuil IN ({marcas})
                         GROUP BY cuil, cuit, periodo""", CODOSOC, *lote)
        for cuil, cuit, periodo in cur.fetchall():
            por_cuil[cuil.strip()][(cuit or "").strip()].add(periodo.strip())
        print(f"  DDJJ: {min(i + LOTE, len(cuiles))} de {len(cuiles)} CUIL", end="\r")
    print()
    return por_cuil, primero.strip(), ultimo.strip()


def tramo_actual(periodos: set[str], hueco: int) -> tuple[str, str, int, int]:
    """(inicio del tramo, último, períodos declarados en el tramo, meses que faltan en él)."""
    orden = sorted(periodos, reverse=True)
    inicio = orden[0]
    for p in orden[1:]:
        if _mes(inicio) - _mes(p) - 1 > hueco:
            break
        inicio = p
    dentro = [p for p in orden if p >= inicio]
    faltan = _mes(orden[0]) - _mes(inicio) + 1 - len(dentro)
    return inicio, orden[0], len(dentro), faltan


def analizar(n: dict, ddjj: dict, primero: str, hoy: date, hueco: int, tolerancia: int) -> dict:
    ingreso = n["fecha_inicio"] if isinstance(n["fecha_inicio"], date) and n["fecha_inicio"] > SIN_DATO else None
    decl = ddjj.get(n["cuil"], {})
    propios = decl.get(n["cuit"], set())
    otros = sorted(c for c in decl if c != n["cuit"])
    f = {**n, "ingreso": ingreso, "otros": otros, "primera": None, "inicio": None, "ultimo": None,
         "declarados": None, "faltan": None, "al_menos": False, "dif": None, "sugerida": ingreso}
    if not propios:
        f["resultado"] = "sin_ddjj"
    else:
        inicio, ultimo, declarados, faltan = tramo_actual(propios, hueco)
        f.update(primera=min(propios), inicio=inicio, ultimo=ultimo, declarados=declarados, faltan=faltan,
                 al_menos=inicio == primero)
        desde_ddjj = date(int(inicio[:4]), int(inicio[4:]), 1)
        if not ingreso:
            f["resultado"], f["sugerida"] = "sin_fecha", desde_ddjj
        else:
            f["dif"] = _mes(inicio) - (ingreso.year * 12 + ingreso.month - 1)
            if abs(f["dif"]) <= tolerancia:
                f["resultado"] = "coincide"
            elif f["dif"] < 0:
                f["resultado"], f["sugerida"] = "ddjj_antes", desde_ddjj
            else:
                f["resultado"] = "ddjj_despues"
    if f["resultado"] in ("sin_fecha", "ddjj_antes"):
        f["origen"] = "ddjj"
    else:
        f["origen"] = "padron" if f["sugerida"] else None
    f["nota"] = RESULTADOS[f["resultado"]] + (f" (DDJJ desde {_per(f['inicio'])})" if f["inicio"] else "")
    f["antig_padron"] = _años(ingreso, hoy) if ingreso else None
    f["antig_ddjj"] = _años(date(int(f["inicio"][:4]), int(f["inicio"][4:]), 1), hoy) if f["inicio"] else None
    f["antig_sugerida"] = _años(f["sugerida"], hoy) if f["sugerida"] else None
    return f


def aplicar(cur, filas: list[dict], ahora: datetime) -> dict:
    """Graba la fecha sugerida. Devuelve los contadores."""
    c = {"grabadas": 0, "iguales": 0, "manuales": 0, "empresa": 0}
    for f in filas:
        # Editada en la ficha después del último cálculo (updated_at cambia con
        # cualquier UPDATE de la fila, también con el nuestro: por eso se
        # compara con un margen de un minuto).
        if f["antiguedad_origen"] == "empresa":         # la informó el empleador: manda
            c["empresa"] += 1
            continue
        if (f["antiguedad_calculada"] and f["updated_at"]
                and (f["updated_at"] - f["antiguedad_calculada"]).total_seconds() > 60
                and f["fecha_antiguedad"] is None):
            c["manuales"] += 1
            continue
        nuevo = (f["sugerida"], f["origen"], 1 if f["al_menos"] else 0, f["nota"][:200])
        viejo = (f["fecha_antiguedad"], f["antiguedad_origen"], f["antiguedad_al_menos"] or 0,
                 f["antiguedad_nota"])
        if nuevo == viejo:
            c["iguales"] += 1
            continue
        cur.execute("""UPDATE p_relaciones_laborales
                          SET fecha_antiguedad = %s, antiguedad_origen = %s, antiguedad_al_menos = %s,
                              antiguedad_nota = %s, antiguedad_calculada = %s
                        WHERE id_relacion = %s""", nuevo + (ahora, f["id_relacion"]))
        c["grabadas"] += 1
    return c


def main():
    parser = argparse.ArgumentParser(description="Antigüedad de los afiliados según las DDJJ de OSEDA.")
    parser.add_argument("--hueco", type=int, default=2,
                        help="meses seguidos sin DDJJ que no cortan el tramo (por defecto 2)")
    parser.add_argument("--tolerancia", type=int, default=2,
                        help="meses de diferencia que se toman como coincidencia (por defecto 2)")
    parser.add_argument("--aplicar", action="store_true",
                        help="grabar la fecha sugerida en p_relaciones_laborales (sin esto, simula)")
    args = parser.parse_args()
    inicio = datetime.now()
    hoy = inicio.date()

    with get_connection() as conn:
        with conn.cursor() as cur:
            nomina = leer_nomina(cur)
    if not nomina:
        salir("No hay afiliados titulares activos con relación laboral vigente.")
    cn = conexion_aeda()
    try:
        ddjj, primero, ultimo_tabla = leer_ddjj(cn, sorted({n["cuil"] for n in nomina}))
    finally:
        cn.close()

    filas = [analizar(n, ddjj, primero, hoy, args.hueco, args.tolerancia) for n in nomina]
    grabado = None
    if args.aplicar:
        with get_connection() as conn:
            try:
                with conn.cursor() as cur:
                    grabado = aplicar(cur, filas, inicio.replace(microsecond=0))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
    cuenta = defaultdict(int)
    for f in filas:
        cuenta[f["resultado"]] += 1
    afiliados = len({f["cuil"] for f in filas})
    con_ddjj = len({f["cuil"] for f in filas if f["inicio"]})
    al_menos = len({f["cuil"] for f in filas if f["al_menos"]})
    vigentes = sum(1 for f in filas if f["ultimo"] and _mes(ultimo_tabla) - _mes(f["ultimo"]) <= 2)
    con_cortes = sum(1 for f in filas if f["primera"] and f["primera"] != f["inicio"])

    CARPETA_LOGS.mkdir(exist_ok=True)
    base = CARPETA_LOGS / f"antiguedad_ddjj_{inicio:%Y%m%d_%H%M%S}"
    columnas = [{"titulo": "CUIT", "tipo": "t"}, {"titulo": "Empleador"}, {"titulo": "CUIL", "tipo": "t"},
                {"titulo": "Apellido y nombres"}, {"titulo": "Ingreso (padrón)"},
                {"titulo": "Primera DDJJ del empleador", "tipo": "t"}, {"titulo": "Inicio del tramo actual", "tipo": "t"},
                {"titulo": "Última DDJJ", "tipo": "t"}, {"titulo": "Períodos declarados en el tramo", "tipo": "n"},
                {"titulo": "Meses que faltan en el tramo", "tipo": "n"}, {"titulo": "Diferencia (meses)", "tipo": "n"},
                {"titulo": "Resultado"}, {"titulo": "Fecha sugerida"}, {"titulo": "Antigüedad padrón (años)", "tipo": "n"},
                {"titulo": "Antigüedad DDJJ (años)", "tipo": "n"}, {"titulo": "Antigüedad sugerida (años)", "tipo": "n"},
                {"titulo": "Observación"}, {"titulo": "Declarado por (otros CUIT)", "tipo": "t"}]
    datos = []
    for f in filas:
        obs = []
        if f["al_menos"]:
            obs.append(f"el tramo empieza en {_per(primero)}, el primer período de la tabla: antigüedad al menos")
        if f["primera"] and f["primera"] != f["inicio"]:
            obs.append(f"tuvo un tramo anterior con este empleador desde {_per(f['primera'])}")
        if f["ultimo"] and _mes(ultimo_tabla) - _mes(f["ultimo"]) > 2:
            obs.append(f"el empleador no lo declara desde {_per(f['ultimo'])}")
        datos.append([f["cuit"], f["razon_social"] or "— no está en Empleadores —", f["cuil"],
                      f["apellido_nombres"] or "", _fecha(f["ingreso"]), _per(f["primera"]), _per(f["inicio"]),
                      _per(f["ultimo"]), _num(f["declarados"]), _num(f["faltan"]), _num(f["dif"]),
                      RESULTADOS[f["resultado"]], _fecha(f["sugerida"]), _num(f["antig_padron"]),
                      _num(f["antig_ddjj"]), _num(f["antig_sugerida"]), "; ".join(obs), ", ".join(f["otros"])])
    planilla = base.with_suffix(".xlsx")
    planilla.write_bytes(xlsx("Antigüedad", columnas, datos))

    total = len(filas)
    lineas = [f"Antigüedad según las DDJJ de OSEDA  {inicio:%d/%m/%Y %H:%M}",
              f"DDJJ: {OSEDA_DB}.dbo.afi_redapo, {_per(primero)} a {_per(ultimo_tabla)}; "
              f"hueco tolerado {args.hueco} meses, coincidencia ±{args.tolerancia} meses", "",
              f"  Afiliados titulares con relación vigente       {afiliados:>6}   ({total} relaciones)",
              f"  Con DDJJ de su empleador (antigüedad calculable) {con_ddjj:>4}"
              f"   ({100 * con_ddjj / afiliados:.1f} %)",
              f"    declarados en los últimos 3 períodos          {vigentes:>6}",
              f"    con un tramo anterior cortado                 {con_cortes:>6}",
              f"    tramo desde el primer período (al menos)      {al_menos:>6}", "",
              "  Resultado por relación:"]
    lineas += [f"    {RESULTADOS[k]:<44} {cuenta[k]:>6}  ({100 * cuenta[k] / total:.1f} %)" for k in RESULTADOS]
    if grabado:
        lineas += ["", f"  Grabado en p_relaciones_laborales.fecha_antiguedad: {grabado['grabadas']}",
                   f"    sin cambios                                   {grabado['iguales']:>6}",
                   f"    editadas a mano después del cálculo (no se tocan) {grabado['manuales']:>3}",
                   f"    informadas por el empleador (no se tocan)     {grabado['empresa']:>6}"]
    else:
        lineas += ["", "  Simulación: no se grabó nada (--aplicar graba la fecha sugerida)."]
    lineas += ["", f"Planilla: {planilla.name}"]
    resumen = base.with_suffix(".txt")
    resumen.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print()
    print(resumen.read_text(encoding="utf-8"))


if __name__ == "__main__":
    sys.exit(main())
