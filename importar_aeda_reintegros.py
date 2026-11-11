"""
importar_aeda_reintegros.py — Historial de reintegros desde AEDA a `sindicato`.

Origen: `aeda.dbo.afi_reintegros` (ver importar_aeda.py, que resuelve la
conexión). En el gremio un reintegro es un subsidio o un gasto que se le
devuelve al afiliado: educación inicial, nacimiento, casamiento, movilidad…
Todos los que tiene AEDA están liquidados (estado `L`) y pagados desde AEDA.

Cada fila de AEDA es una solicitud de un renglón:

    c_reintegro_afiliados            estado `pagada`, N° «AEDA-<reintegro_id>»,
                                     importe solicitado = aprobado = el de AEDA
    c_reintegro_afiliados_detalle    el afiliado, el concepto y la fecha

Quedan cerradas: no aparecen para pagar en «Órdenes de pago» (se pagaron en
AEDA) ni se pueden editar. Sirven de historial: la ficha del reintegro, la
constancia y el listado con sus filtros.

Uso
---
    python importar_aeda_reintegros.py                       simula y escribe el informe en logs/
    python importar_aeda_reintegros.py --aplicar             lo mismo, y lo graba
    python importar_aeda_reintegros.py --usuario mail@…      quién figura como que cargó

Requiere sql/reintegros_20261107.sql aplicado: agrega los conceptos de AEDA
al catálogo y la marca `es_reintegro`. Sin eso no arranca.

Decisiones sobre los datos de AEDA
----------------------------------
Afiliado. El CUIL de AEDA es el del titular. Si en el padrón es un familiar,
la solicitud va al titular de su grupo y el renglón queda a nombre del
familiar. Si el CUIL no está en el padrón se usa el del beneficiario del agente
de AEDA (`adm_agentes.cta_id` → `afi_benef`): hay reintegros con el CUIL mal
tipeado (27303651956 por 27303651964) o con el DNI de un hijo, y el agente es a
quien AEDA le pagó. Queda la nota. Si tampoco ese está, no se importa y queda
en el informe.

Concepto. Se busca por descripción entre los conceptos marcados `es_reintegro`
(AEDA corta las descripciones a 30 letras: «SUBSIDIO Y SERVICIO POR FALLEC»
se completa). Un concepto de AEDA sin equivalente no se importa: hay que
agregarlo al catálogo y marcarlo, y volver a correr.

Pago. AEDA no relaciona el reintegro con su pago. Se busca en `adm_pagos` el
pago al mismo agente (`age_id`) por el mismo importe entre la fecha del
reintegro y 30 días después, el más cercano, y sin usar un pago para dos
reintegros. Si aparece, el número y la fecha van a las observaciones y el
texto del pago («SUBSIDIO GUARDERIA») al comentario del renglón.

Usuario. AEDA no dice quién cargó cada uno. Figura el de --usuario o, sin
eso, el primer Administrador activo.

Se puede correr más de una vez —mientras AEDA siga en uso, para traer los
nuevos—: lo importado lleva su origen al principio de `observaciones`
(«[AEDA afi_reintegros 1652]») y lo que ya está se saltea.
"""

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

# importar_aeda carga el .env y trae la conexión a AEDA.
from importar_aeda import CARPETA_LOGS, _filas, conexion_aeda, limpio, normalizar, salir, solo_digitos

from db import get_connection

RE_MARCA = re.compile(r"^\[AEDA afi_reintegros (\d+)\]")
VENTANA_PAGO = timedelta(days=30)

#: AEDA corta las descripciones a 30 letras.
ALIAS_CONCEPTOS = {
    "SUBSIDIO Y SERVICIO POR FALLEC": "SUBSIDIO Y SERVICIO POR FALLECIMIENTO",
}

ESTADOS_AEDA = {"L": "pagada"}


# ─────────────────────────────────────────────────────────────────────────────
# Lectura
# ─────────────────────────────────────────────────────────────────────────────

def leer_aeda(cn) -> dict:
    cur = cn.cursor()
    reintegros = _filas(cur, """
        SELECT r.reintegro_id, r.fecha, r.cuil, r.age_id, r.importe, r.conc_id,
               r.estado, g.descrip AS concepto, b.cuil AS cuil_agente
          FROM aeda.dbo.afi_reintegros r
          LEFT JOIN aeda.dbo.adm_cptogasto g ON g.conc_id = r.conc_id
          LEFT JOIN aeda.dbo.adm_agentes ag ON ag.age_id = r.age_id AND ag.tipo_id = 2
          LEFT JOIN aeda.dbo.afi_benef b ON b.ben_id = ag.cta_id
         ORDER BY r.reintegro_id
    """)
    # Los pagos anulados (`X`) no cuentan: el reintegro se pagó con otro.
    pagos = _filas(cur, """
        SELECT p.pago_id, p.pago_nro, p.fecha, p.importe, p.age_id,
               CAST(p.obs AS varchar(500)) AS obs
          FROM aeda.dbo.adm_pagos p
         WHERE p.estado <> 'X'
           AND p.age_id IN (SELECT age_id FROM aeda.dbo.afi_reintegros)
    """)
    return {"reintegros": reintegros, "pagos": pagos}


def leer_destino(cur, email_usuario: str | None) -> dict:
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.columns
                    WHERE table_schema = DATABASE() AND table_name = 'c_concepto_de_gastos'
                      AND column_name = 'es_reintegro'""")
    if not cur.fetchone()["n"]:
        salir("Falta c_concepto_de_gastos.es_reintegro. Correr antes sql/reintegros_20261107.sql.")

    cur.execute("SELECT id, descripcion FROM c_concepto_de_gastos WHERE es_reintegro = 1")
    conceptos = {normalizar(f["descripcion"]): f for f in cur.fetchall()}

    cur.execute("""SELECT a.id_afiliado, a.cuil, a.cod_parentesco, a.cuil_titular,
                          a.apellido_nombres AS nombre
                     FROM p_afiliados a WHERE a.cuil IS NOT NULL AND a.cuil <> ''""")
    por_cuil = {f["cuil"]: f for f in cur.fetchall()}

    # Sin parámetros: con argumentos, PyMySQL toma el `%` del LIKE como marcador.
    cur.execute("SELECT observaciones FROM c_reintegro_afiliados "
                "WHERE observaciones LIKE '[AEDA afi_reintegros %'")
    ya = {int(RE_MARCA.match(f["observaciones"]).group(1)) for f in cur.fetchall()
          if RE_MARCA.match(f["observaciones"] or "")}
    cur.execute("SELECT nro_solicitud FROM c_reintegro_afiliados WHERE nro_solicitud LIKE 'AEDA-%'")
    nros = {f["nro_solicitud"] for f in cur.fetchall()}

    if email_usuario:
        cur.execute("SELECT id, nombre FROM s_usuarios WHERE email = %s AND activo = 1",
                    (email_usuario,))
    else:
        cur.execute("""SELECT u.id, u.nombre FROM s_usuarios u
                         JOIN s_usuario_rol ur ON ur.usuario_id = u.id
                         JOIN s_roles r ON r.id = ur.rol_id
                        WHERE u.activo = 1 AND r.nombre = 'Administrador'
                        ORDER BY u.id LIMIT 1""")
    usuario = cur.fetchone()
    if not usuario:
        salir(f"No hay usuario activo {email_usuario or 'con rol Administrador'} para figurar "
              "como el que cargó los reintegros. Indicarlo con --usuario mail@…")

    return {"conceptos": conceptos, "por_cuil": por_cuil, "ya": ya, "nros": nros,
            "usuario": usuario}


# ─────────────────────────────────────────────────────────────────────────────
# Plan
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Plan:
    solicitudes: list[dict] = field(default_factory=list)
    informe: list[dict] = field(default_factory=list)
    cuenta: dict = field(default_factory=dict)

    def contar(self, clave, n=1):
        self.cuenta[clave] = self.cuenta.get(clave, 0) + n

    def anotar(self, accion, **datos):
        self.informe.append({"accion": accion, **datos})


def _dia(valor) -> date | None:
    if valor is None:
        return None
    return valor.date() if isinstance(valor, datetime) else valor


def _texto_pago(obs) -> str:
    """«SUBSIDIO GUARDERIA.-» → «SUBSIDIO GUARDERIA»."""
    return re.sub(r"[\s.\-]+$", "", limpio(obs))


def armar_plan(aeda: dict, destino: dict) -> Plan:
    plan = Plan()

    pagos_por_agente: dict = {}
    for p in aeda["pagos"]:
        pagos_por_agente.setdefault(p["age_id"], []).append(p)
    usados: set = set()

    for r in aeda["reintegros"]:
        rid = r["reintegro_id"]
        cuil = solo_digitos(r["cuil"])
        base = {"reintegro_id": rid, "fecha": _dia(r["fecha"]), "cuil": cuil,
                "importe": r["importe"], "concepto": limpio(r["concepto"])}

        if rid in destino["ya"] or f"AEDA-{rid}" in destino["nros"]:
            plan.contar("ya importados antes (se saltean)")
            continue

        estado = ESTADOS_AEDA.get(limpio(r["estado"]))
        if not estado:
            plan.contar("con un estado de AEDA que no se conoce (no se importan)")
            plan.anotar("estado desconocido", **base, nota=f"estado «{limpio(r['estado'])}»")
            continue

        afiliado, nota_cuil = destino["por_cuil"].get(cuil), None
        if not afiliado:
            # El CUIL de AEDA está mal: se usa el del beneficiario del agente,
            # que es a quien AEDA le pagó.
            cuil_agente = solo_digitos(r.get("cuil_agente"))
            afiliado = destino["por_cuil"].get(cuil_agente) if cuil_agente else None
            if afiliado:
                nota_cuil = (f"el CUIL de AEDA ({cuil}) no está en el padrón: va al beneficiario "
                             f"del agente, CUIL {cuil_agente}")
                plan.contar("con el CUIL de AEDA mal, tomado del agente")
        if not afiliado:
            plan.contar("con un CUIL que no está en el padrón (no se importan)")
            plan.anotar("sin afiliado", **base)
            continue

        # El renglón es del afiliado; la solicitud, del titular de su grupo.
        titular, nota = afiliado, nota_cuil
        if afiliado["cod_parentesco"] != 0:
            titular = destino["por_cuil"].get(afiliado["cuil_titular"] or "")
            if not titular:
                titular = afiliado
                nota = "; ".join(x for x in (nota_cuil, "es familiar y su titular no está en el "
                                                        "padrón: queda a su nombre") if x)
            else:
                plan.contar("de un familiar, cargados a nombre de su titular")

        descripcion = ALIAS_CONCEPTOS.get(base["concepto"], base["concepto"])
        concepto = destino["conceptos"].get(normalizar(descripcion))
        if not concepto:
            plan.contar("con un concepto sin equivalente marcado es_reintegro (no se importan)")
            plan.anotar("concepto sin equivalente", **base)
            continue

        # El pago: mismo agente, mismo importe, desde la fecha del reintegro
        # hasta 30 días después; el más cercano que no se haya usado ya.
        fecha_r = base["fecha"]
        candidatos = [p for p in pagos_por_agente.get(r["age_id"], [])
                      if p["pago_id"] not in usados and Decimal(p["importe"]) == Decimal(r["importe"])
                      and fecha_r <= _dia(p["fecha"]) <= fecha_r + VENTANA_PAGO]
        candidatos.sort(key=lambda p: ((_dia(p["fecha"]) - fecha_r).days, p["pago_id"]))
        pago = candidatos[0] if candidatos else None
        if pago:
            usados.add(pago["pago_id"])
            plan.contar("con su pago de AEDA identificado")
        else:
            plan.contar("sin pago identificable en AEDA (se importan igual)")

        obs = f"[AEDA afi_reintegros {rid}] Pagado desde AEDA"
        if pago:
            obs += f": pago N° {pago['pago_nro']} del {_dia(pago['fecha']):%d/%m/%Y}"
        obs += "."
        if nota_cuil:
            obs += f" Ojo: {nota_cuil}."
        elif nota:
            obs += f" El CUIL {cuil} {nota}."

        plan.solicitudes.append({
            "nro_solicitud": f"AEDA-{rid}",
            "anio": fecha_r.year,
            "id_afiliado": titular["id_afiliado"],
            "fecha_solicitud": fecha_r,
            "estado": estado,
            "importe": Decimal(r["importe"]),
            "observaciones": obs[:500],
            "detalle": {
                "id_concepto_gasto": concepto["id"],
                "id_afiliado": afiliado["id_afiliado"],
                "fecha_gasto": fecha_r,
                "nro_comprobante": f"PAGO {pago['pago_nro']}" if pago else None,
                "comentario_solicitud": (_texto_pago(pago["obs"])[:250] or None) if pago else None,
            },
        })
        plan.contar("reintegros a importar")
        plan.anotar("importar", **base, afiliado=afiliado["nombre"],
                    titular=titular["nombre"], concepto_destino=concepto["descripcion"],
                    pago=pago["pago_nro"] if pago else "", nota=nota or "")
    return plan


# ─────────────────────────────────────────────────────────────────────────────
# Escritura
# ─────────────────────────────────────────────────────────────────────────────

def aplicar(cur, plan: Plan, id_usuario: int) -> None:
    for s in plan.solicitudes:
        cur.execute("""
            INSERT INTO c_reintegro_afiliados
                (nro_solicitud, anio, id_afiliado, fecha_solicitud, id_usuario_solicitud,
                 estado, niveles_requeridos, niveles_aprobados, importe_solicitado,
                 importe_aprobado, moneda, importado_csv, observaciones)
            VALUES (%s, %s, %s, %s, %s, %s, 1, 1, %s, %s, 'ARS', 1, %s)
        """, (s["nro_solicitud"], s["anio"], s["id_afiliado"], s["fecha_solicitud"], id_usuario,
              s["estado"], s["importe"], s["importe"], s["observaciones"]))
        d = s["detalle"]
        cur.execute("""
            INSERT INTO c_reintegro_afiliados_detalle
                (id_reintegro, id_concepto_gasto, id_afiliado, fecha_gasto, nro_comprobante,
                 importe_solicitado, importe_aprobado, comentario_solicitud)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (cur.lastrowid, d["id_concepto_gasto"], d["id_afiliado"], d["fecha_gasto"],
              d["nro_comprobante"], s["importe"], s["importe"], d["comentario_solicitud"]))


CAMPOS_INFORME = ["accion", "reintegro_id", "fecha", "cuil", "afiliado", "titular", "importe",
                  "concepto", "concepto_destino", "pago", "nota"]


def escribir_informe(plan: Plan, aplicado: bool, inicio: datetime, usuario: dict):
    CARPETA_LOGS.mkdir(exist_ok=True)
    base = CARPETA_LOGS / f"importar_aeda_reintegros_{inicio:%Y%m%d_%H%M%S}"
    detalle, resumen = base.with_suffix(".csv"), base.with_suffix(".txt")
    with open(detalle, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_INFORME, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(plan.informe)
    total = sum(s["importe"] for s in plan.solicitudes)
    lineas = [f"Importación de reintegros AEDA → sindicato  {inicio:%d/%m/%Y %H:%M}",
              "APLICADA" if aplicado else "SIMULACIÓN — no se grabó nada",
              f"Figuran cargados por: {usuario['nombre']}", ""]
    lineas += [f"  {n:>6}  {k}" for k, n in plan.cuenta.items()]
    lineas += ["", f"  Importe de lo que se importa: $ {total:,.2f}".replace(",", "X")
               .replace(".", ",").replace("X", "."), "", f"Detalle: {detalle.name}"]
    resumen.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return resumen


def main():
    parser = argparse.ArgumentParser(description="Historial de reintegros desde AEDA.")
    parser.add_argument("--aplicar", action="store_true",
                        help="grabar en la base (sin esto, solo simula)")
    parser.add_argument("--usuario", help="mail del usuario que figura como el que cargó")
    args = parser.parse_args()
    inicio = datetime.now()

    cn = conexion_aeda()
    try:
        aeda = leer_aeda(cn)
    finally:
        cn.close()

    with get_connection() as conn:
        with conn.cursor() as cur:
            destino = leer_destino(cur, args.usuario)
        plan = armar_plan(aeda, destino)

        if args.aplicar and plan.solicitudes:
            # Todo o nada: con la mitad grabada, la segunda corrida igual sabría
            # qué falta (por la marca), pero el informe de esta mentiría.
            conn.begin()
            try:
                with conn.cursor() as cur:
                    aplicar(cur, plan, destino["usuario"]["id"])
                conn.commit()
            except Exception:
                conn.rollback()
                resumen = escribir_informe(plan, False, inicio, destino["usuario"])
                print(f"\n  Falló la importación; no se grabó nada. Plan en {resumen}\n")
                raise

    resumen = escribir_informe(plan, args.aplicar, inicio, destino["usuario"])
    print()
    print(resumen.read_text(encoding="utf-8"))
    if not args.aplicar:
        print("  Para grabar:  python importar_aeda_reintegros.py --aplicar\n")


if __name__ == "__main__":
    sys.exit(main())
