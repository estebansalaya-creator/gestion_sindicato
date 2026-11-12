"""
importar_aeda_fisca_deuda.py — Las liquidaciones de cuota sindical de AEDA.

    fis_deuda           →  fisca_liquidacion (una por CUIT y período), origen «aeda»
    fis_deuda_detalle   →  fisca_liquidacion_detalle (un renglón por afiliado), fuente «aeda»

AEDA liquidó de 202401 a 202602: afiliados de su padrón × Remuneración
imponible 5 de la DDJJ de OSEDA × 2,5 %, vencimiento el 20 del mes siguiente.
Se trae tal cual la emitió (importe, remuneración, fecha y vencimiento); la
pantalla de liquidación no reliquida lo que vino de AEDA.

Sin cobros (decidido el 11/11/2026): `fis_deudaaplic` está vacía en AEDA y no se
aplica `fis_cobros` a estas deudas.

Uso
---
    python importar_aeda_fisca_deuda.py               simula y escribe el informe en logs/
    python importar_aeda_fisca_deuda.py --aplicar     lo mismo, y lo graba
    python importar_aeda_fisca_deuda.py --usuario mail@…

Requiere sql/fisca_liquidacion_20261111.sql.

Decisiones
----------
- Marca «[AEDA fis_deuda N]» al principio de observaciones: se puede volver a
  correr. Si AEDA cambió el importe o los renglones, se rehace el detalle; si la
  anuló (estado X), se anula.
- Un empleador y período que ya se liquidó en el sindicato (origen nómina o
  DDJJ) no se pisa: sale en el informe. Tampoco una de AEDA que ya se
  reliquidó por DDJJ (12/11/2026): pasó a origen «ddjj» y su importe de AEDA
  quedó en `aeda_importe`.
- El afiliado se busca por CUIL en el padrón; uno que no está entra igual, sin
  id_afiliado.
"""

import argparse
import csv
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

# importar_aeda carga el .env y trae la conexión a AEDA.
from importar_aeda import CARPETA_LOGS, _filas, conexion_aeda, limpio, salir, solo_digitos

from db import get_connection

TOL = Decimal("0.01")
RE_MARCA = re.compile(r"^\[AEDA fis_deuda (\d+)\]")

SQL_AEDA = {
    "deudas": """SELECT deuda_id, cuit, periodo, fecha, vto, importe, totremu, cuiles, estado, usuario
                   FROM aeda.dbo.fis_deuda""",
    "detalle": "SELECT id, cuit, cuil, periodo, remuneracion, cuota FROM aeda.dbo.fis_deuda_detalle",
}


def _d(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


def _dia(v):
    if v is None:
        return None
    return v.date() if isinstance(v, datetime) else v


def _pesos(v) -> str:
    return f"$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def leer_aeda(cn) -> dict:
    cur = cn.cursor()
    datos = {k: _filas(cur, sql) for k, sql in SQL_AEDA.items()}
    cur.close()
    return datos


def leer_destino(cur, email_usuario):
    cur.execute("SELECT COUNT(*) AS n FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = 'fisca_liquidacion'")
    if not cur.fetchone()["n"]:
        salir("Falta fisca_liquidacion. Correr antes sql/fisca_liquidacion_20261111.sql.")
    d = {}
    cur.execute("SELECT id, cuit, periodo, origen, estado, importe, afiliados, observaciones FROM fisca_liquidacion")
    d["por_clave"], d["por_marca"] = {}, {}
    for f in cur.fetchall():
        d["por_clave"][(f["cuit"], f["periodo"])] = f
        # Solo las que siguen siendo de AEDA: una reliquidada por DDJJ (12/11/2026) es del
        # sindicato y queda en por_clave, así no se pisa.
        m = RE_MARCA.match(f["observaciones"] or "")
        if m and f["origen"] == "aeda":
            d["por_marca"][int(m.group(1))] = f
    cur.execute("SELECT cuil, id_afiliado, apellido_nombres FROM p_afiliados WHERE cuil REGEXP '^[0-9]{11}$'")
    d["padron"] = {f["cuil"]: f for f in cur.fetchall()}
    if email_usuario:
        cur.execute("SELECT id, nombre FROM s_usuarios WHERE email = %s AND activo = 1", (email_usuario,))
    else:
        cur.execute("""SELECT u.id, u.nombre FROM s_usuarios u
                         JOIN s_usuario_rol ur ON ur.usuario_id = u.id
                         JOIN s_roles r ON r.id = ur.rol_id
                        WHERE u.activo = 1 AND r.nombre = 'Administrador'
                        ORDER BY u.id LIMIT 1""")
    d["usuario"] = cur.fetchone()
    if not d["usuario"]:
        salir(f"No hay usuario activo {email_usuario or 'con rol Administrador'} para figurar "
              "como el que cargó. Indicarlo con --usuario mail@…")
    return d


@dataclass
class Plan:
    nuevas: list = field(default_factory=list)
    actualizar: list = field(default_factory=list)
    anular: list = field(default_factory=list)
    informe: list = field(default_factory=list)
    cuenta: dict = field(default_factory=dict)
    por_periodo: dict = field(default_factory=lambda: defaultdict(lambda: [0, Decimal("0")]))

    def contar(self, clave, n=1):
        self.cuenta[clave] = self.cuenta.get(clave, 0) + n

    def anotar(self, accion, **datos):
        self.informe.append({"accion": accion, **datos})


def armar_plan(aeda, destino) -> Plan:
    plan = Plan()
    detalle = defaultdict(list)
    for x in aeda["detalle"]:
        detalle[(solo_digitos(x["cuit"] or ""), limpio(x["periodo"]))].append(x)

    for g in sorted(aeda["deudas"], key=lambda x: x["deuda_id"]):
        did = g["deuda_id"]
        cuit, periodo = solo_digitos(g["cuit"] or ""), limpio(g["periodo"])
        anulada = limpio(g["estado"]).upper() == "X"
        ya = destino["por_marca"].get(did)
        base = {"aeda": f"fis_deuda {did}", "cuit": cuit, "periodo": periodo, "importe": _d(g["importe"])}
        if len(cuit) != 11 or not re.fullmatch(r"\d{6}", periodo):
            plan.contar("deudas con CUIT o período inválido (no entran)")
            plan.anotar("omitida", **base, nota="CUIT o período inválido")
            continue
        if anulada:
            if ya and ya["estado"] != "anulada":
                plan.anular.append(ya)
                plan.contar("deudas anuladas en AEDA después de importadas (se anulan)")
            else:
                plan.contar("deudas anuladas en AEDA (no entran)")
            continue
        lineas = {}
        for x in detalle.get((cuit, periodo), []):
            cuil = solo_digitos(x["cuil"] or "")
            l = lineas.setdefault(cuil, {"cuil": cuil, "remuneracion": Decimal("0"), "cuota": Decimal("0")})
            l["remuneracion"] += _d(x["remuneracion"])
            l["cuota"] += _d(x["cuota"])
        for l in lineas.values():
            a = destino["padron"].get(l["cuil"]) or {}
            l["id_afiliado"], l["nombre"] = a.get("id_afiliado"), a.get("apellido_nombres")
        sin_padron = sum(1 for l in lineas.values() if not l["id_afiliado"])
        rem = _d(g["totremu"])
        nueva = {**g, "_cuit": cuit, "_periodo": periodo, "_importe": _d(g["importe"]), "_rem": rem,
                 "_alicuota": (_d(g["importe"]) / rem * 100).quantize(Decimal("0.01")) if rem else Decimal("2.50"),
                 "_lineas": list(lineas.values()), "_sin_padron": sin_padron}
        if abs(sum(l["cuota"] for l in lineas.values()) - nueva["_importe"]) > TOL:
            plan.contar("deudas cuyo detalle no suma el importe (entran igual)")
            plan.anotar("aviso", **base, nota="el detalle no suma el importe de la deuda")
        if ya:
            if (ya["estado"] != "vigente" or abs(_d(ya["importe"]) - nueva["_importe"]) > TOL
                    or ya["afiliados"] != len(lineas)):
                plan.actualizar.append({**nueva, "_id": ya["id"]})
                plan.contar("deudas que cambiaron en AEDA (se rehacen)")
                plan.anotar("actualizar", **base)
            else:
                plan.contar("deudas ya importadas")
            continue
        otra = destino["por_clave"].get((cuit, periodo))
        if otra:
            plan.contar("empleador y período ya liquidados en el sindicato (no se pisan)")
            plan.anotar("omitida", **base, nota=f"ya liquidado acá (origen {otra['origen']}, "
                                                f"{_pesos(_d(otra['importe']))})")
            continue
        plan.nuevas.append(nueva)
        plan.contar("deudas a importar")
        if sin_padron:
            plan.contar("renglones de afiliados que no están en el padrón (entran sin vincular)", sin_padron)
        plan.por_periodo[periodo][0] += 1
        plan.por_periodo[periodo][1] += nueva["_importe"]
    return plan


def _obs(g) -> str:
    return (f"[AEDA fis_deuda {g['deuda_id']}] Liquidada en AEDA"
            + (f" por {limpio(g['usuario'])}" if limpio(g["usuario"]) else "") + "."
            + (f" {g['_sin_padron']} afiliado(s) que no están en el padrón." if g["_sin_padron"] else ""))[:500]


def _detalle(cur, id_liq, g):
    cur.execute("DELETE FROM fisca_liquidacion_detalle WHERE id_liquidacion = %s", (id_liq,))
    cur.executemany("""INSERT INTO fisca_liquidacion_detalle
                         (id_liquidacion, cuil, id_afiliado, apellido_nombres, remuneracion, cuota, fuente)
                       VALUES (%s, %s, %s, %s, %s, %s, 'aeda')""",
                    [(id_liq, l["cuil"], l["id_afiliado"], (l["nombre"] or None) and l["nombre"][:100],
                      l["remuneracion"], l["cuota"]) for l in g["_lineas"]])


def aplicar(cur, plan: Plan, destino) -> None:
    usuario = destino["usuario"]["id"]
    for g in plan.nuevas:
        cur.execute("""INSERT INTO fisca_liquidacion
                         (cuit, periodo, fecha, vencimiento, alicuota, afiliados, remuneracion, importe, origen,
                          estado, observaciones, id_usuario)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'aeda', 'vigente', %s, %s)""",
                    (g["_cuit"], g["_periodo"], _dia(g["fecha"]), _dia(g["vto"]), g["_alicuota"],
                     len(g["_lineas"]), g["_rem"], g["_importe"], _obs(g), usuario))
        _detalle(cur, cur.lastrowid, g)
    for g in plan.actualizar:
        cur.execute("""UPDATE fisca_liquidacion SET fecha = %s, vencimiento = %s, alicuota = %s, afiliados = %s,
                              remuneracion = %s, importe = %s, estado = 'vigente', observaciones = %s
                        WHERE id = %s""",
                    (_dia(g["fecha"]), _dia(g["vto"]), g["_alicuota"], len(g["_lineas"]), g["_rem"],
                     g["_importe"], _obs(g), g["_id"]))
        _detalle(cur, g["_id"], g)
    for f in plan.anular:
        cur.execute("UPDATE fisca_liquidacion SET estado = 'anulada', observaciones = CONCAT(observaciones, %s) "
                    "WHERE id = %s", (" Anulada en AEDA.", f["id"]))


def verificar(cur) -> list[dict]:
    cur.execute("""SELECT periodo, COUNT(*) AS n, SUM(importe) AS importe, SUM(afiliados) AS afiliados
                     FROM fisca_liquidacion WHERE origen = 'aeda' AND estado = 'vigente'
                    GROUP BY periodo ORDER BY periodo""")
    return cur.fetchall()


def _csv(v):
    if isinstance(v, Decimal):
        return f"{v:.2f}".replace(".", ",")
    if isinstance(v, date):
        return v.strftime("%d/%m/%Y")
    return v


def escribir_informe(plan, estado, inicio, usuario, control, aeda_tot):
    CARPETA_LOGS.mkdir(exist_ok=True)
    base = CARPETA_LOGS / f"importar_aeda_fisca_deuda_{inicio:%Y%m%d_%H%M%S}"
    detalle, resumen = base.with_suffix(".csv"), base.with_suffix(".txt")
    with open(detalle, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["accion", "aeda", "cuit", "periodo", "importe", "nota"],
                           delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows({k: _csv(v) for k, v in fila.items()} for fila in plan.informe)
    lineas = [f"Liquidaciones de cuota sindical de AEDA (fis_deuda)  {inicio:%d/%m/%Y %H:%M}",
              estado, f"Figura como cargado por: {usuario['nombre']}", ""]
    lineas += [f"  {n:>6}  {k}" for k, n in plan.cuenta.items()]
    if control is not None:
        lineas += ["", "  Por período (lo de AEDA en el sindicato, contra fis_deuda):",
                   f"    {'período':<8} {'deudas':>7} {'afiliados':>9} {'sindicato':>20} {'AEDA':>20}"]
        for f in control:
            a = aeda_tot.get(f["periodo"], Decimal("0"))
            marca = "" if abs(_d(f["importe"]) - a) <= TOL else "   ← NO DA"
            lineas.append(f"    {f['periodo'][:4]}-{f['periodo'][4:]:<3} {f['n']:>7} {int(f['afiliados'] or 0):>9} "
                          f"{_pesos(_d(f['importe'])):>20} {_pesos(a):>20}{marca}")
    lineas += ["", f"Detalle: {detalle.name}"]
    resumen.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return resumen


def main():
    parser = argparse.ArgumentParser(description="Liquidaciones de cuota sindical de AEDA (fis_deuda).")
    parser.add_argument("--aplicar", action="store_true", help="grabar en la base (sin esto, solo simula)")
    parser.add_argument("--usuario", help="mail del usuario que figura como el que cargó")
    args = parser.parse_args()
    inicio = datetime.now()

    cn = conexion_aeda()
    try:
        aeda = leer_aeda(cn)
    finally:
        cn.close()
    aeda_tot = defaultdict(Decimal)
    for g in aeda["deudas"]:
        if limpio(g["estado"]).upper() != "X":
            aeda_tot[limpio(g["periodo"])] += _d(g["importe"])

    with get_connection() as conn:
        with conn.cursor() as cur:
            destino = leer_destino(cur, args.usuario)
        plan = armar_plan(aeda, destino)
        conn.begin()
        try:
            with conn.cursor() as cur:
                aplicar(cur, plan, destino)
                control = verificar(cur)
            if args.aplicar:
                conn.commit()
                estado = "APLICADA"
            else:
                conn.rollback()
                estado = "SIMULACIÓN — no se grabó nada"
        except Exception:
            conn.rollback()
            resumen = escribir_informe(plan, "FALLÓ — no se grabó nada", inicio, destino["usuario"], None, aeda_tot)
            print(f"\n  Falló la importación; no se grabó nada. Plan en {resumen}\n")
            raise

    resumen = escribir_informe(plan, estado, inicio, destino["usuario"], control, aeda_tot)
    print()
    print(resumen.read_text(encoding="utf-8"))
    if not args.aplicar:
        print("  Para grabar:  python importar_aeda_fisca_deuda.py --aplicar\n")


if __name__ == "__main__":
    sys.exit(main())
