"""
importar_aeda_cc_afiliados.py — Expedientes y pagos de los reintegros y
subsidios de AEDA.

Es la otra mitad de `importar_aeda_cc_proveedores.py`: en AEDA lo que se le
paga a un afiliado (agentes `adm_agentes.tipo_id = 2`) sigue el mismo circuito
que una factura —comprobante en `adm_pasivo`, expediente, liquidación, pago y
aplicación—. Es lo que en gestion_adm hicieron `etl_pasivo.py` y
`etl_reintegros_afiliados.py` con los de OSEDA, en un script.

`importar_aeda_reintegros.py` ya trajo cada solicitud (`afi_reintegros`) como
un reintegro `pagada`. Este le agrega lo que le faltaba:

    adm_pasivo (tcomp 50) + mse_expedientes  →  me_expedientes «000002316/26» en
                                                estado `reintegro`, con su ingreso
    adm_pagos (P, y el A que se aplicó)      →  pago_ordenes clase `reintegro`
      + adm_pasivoAplic (qué pagó cada uno)     «AEDA-OP-N» + pago_pagos «AEDA-PG-N»
                                                + pago_ordenes_reintegro_det

y deja `c_reintegro_afiliados.id_orden_pago` apuntando a su orden: la ficha del
reintegro muestra con qué pago salió y `v_reintegro_saldo` da cero.

SOLO EL GASTO, COMO EN GESTION_ADM
Un reintegro o un subsidio no es deuda: contablemente se registra el gasto al
pagarlo, con la cuenta del concepto del reintegro, y nada más (gestion_adm,
contabilidad_ayuda: «la liquidación de un reintegro a afiliado no devenga»).
Por eso la `pres_liquida` de AEDA NO se trae como `c_pasivo_liquidacion` ni el
pago se aplica a una: no hay pasivo que cancelar. Es lo mismo que hace el
circuito de reintegros del sindicato, que va de la solicitud a la orden sin
pasar por la cuenta a pagar. Lo que se trae del expediente de AEDA es el
registro de la mesa (número, carátula, quién lo ingresó y quién lo liquidó).
Si una corrida anterior había creado liquidaciones o aplicaciones de reintegros,
se sacan.

Uso
---
    python importar_aeda_cc_afiliados.py                  simula y escribe el informe en logs/
    python importar_aeda_cc_afiliados.py --aplicar        lo mismo, y lo graba
    python importar_aeda_cc_afiliados.py --usuario mail@… quién figura como el que cargó

Requiere los reintegros ya importados (importar_aeda_reintegros.py) y
sql/reintegros_clase_20261111.sql (la clase subsidio / reintegro de cada concepto).

Decisiones
----------
Qué entra. Solo los comprobantes con expediente (`exp_id` en adm_pasivo) y
activos (estado distinto de X). Los expedientes de AEDA sin comprobante —en
proveedores, 73 copias que dejó la generación automática de septiembre de
2025— no se traen: liquidarían deuda que no existe.

Qué reintegro es. `adm_pasivo.numero` es el `reintegro_id` de `afi_reintegros`
(659 de 659, mismo agente e importe). Un comprobante cuyo reintegro no está
importado no entra y sale en el informe.

Estado del expediente: `reintegro`, como en gestion_adm. Así no figura en la
cuenta corriente de proveedores (la vista excluye ese estado) ni en
`v_expedientes_liquidados_impagos` (pide `liquidado`): un reintegro se paga
desde su propio circuito. La mesa lo muestra como «Reintegro».

Subsidio o reintegro. Sale del concepto (`c_concepto_de_gastos.clase_reintegro`)
y va al asunto del expediente: «Subsidio AEDA-1652 …».

Pagos. Un pago entra como orden `reintegro` si cancela algún reintegro
importado. Uno que no cancela ninguno (en AEDA: un bono de fin de año, servicios
prestados) no es un reintegro: entra como orden por CONCEPTO «AEDA-OP-N», con un
renglón de gasto a nombre del afiliado. AEDA no dice a qué se imputó; el concepto
sale de `CONCEPTOS_SIN_REINTEGRO` por el texto del pago (servicios prestados →
HONORARIOS) y lo demás va a GASTOS GENERALES. Se cambia en la base si el contador
dice otra cosa (volver a correr no lo pisa). Un pago anulado
en AEDA después de importado se anula acá (orden y pago) y se le sacan sus
aplicaciones; el reintegro deja de apuntarle.

Lo impago. Un comprobante de AEDA sin aplicaciones entra con su expediente,
pero el reintegro no se toca (sigue `pagada`, como lo importó
importar_aeda_reintegros.py): sale en el informe para resolverlo a mano.

No trae instrumentos ni movimientos de tesorería, como el de proveedores.

Marcas, para volver a correr: «[AEDA reintegro adm_pasivo N]» en el asunto del
expediente y «AEDA-PG-N» en el pago (la misma serie que proveedores: los pago_id
de AEDA son únicos). Los renglones de la orden se reconcilian con AEDA en cada
corrida.
Ninguna coincide con las que reconoce importar_aeda_cc_proveedores.py, así que
correr uno no toca lo del otro.
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
from importar_aeda import CARPETA_LOGS, _filas, conexion_aeda, limpio, normalizar, salir, solo_digitos

import comprobantes_datos as cd
from db import get_connection

CERO = Decimal("0.00")
TOL = Decimal("0.01")
TCOMP_REINTEGRO = 50
ESTADO_EXP = "reintegro"
MARCA_EXP = "[AEDA reintegro adm_pasivo {}]"
RE_EXP = re.compile(r"^\[AEDA reintegro adm_pasivo (\d+)\]")
RE_PAGO = re.compile(r"^AEDA-PG-(\d+)$")
RE_APLIC = re.compile(r"^\[AEDA reintegro adm_pasivoAplic ([\d,]+)\]")
RE_REINT = re.compile(r"^\[AEDA afi_reintegros (\d+)\]")
CLASE_TXT = {"subsidio": "Subsidio", "reintegro": "Reintegro", None: "Reintegro"}
#: Pagos a afiliados que no cancelan un reintegro: (texto en la observación de
#: AEDA, concepto de gasto). El primero que coincide; si ninguno, el de abajo.
CONCEPTOS_SIN_REINTEGRO = [("SERVICIOS PRESTADOS", "HONORARIOS")]
CONCEPTO_SIN_REINTEGRO_DEFECTO = "GASTOS GENERALES"

SQL_AEDA = {
    "comprobantes": """
        SELECT p.comp_id, p.tcomp_id, p.age_id, p.numero, p.fecha, p.importe, p.estado,
               e.exp_id, e.exp_nro, e.fecha AS exp_fecha, CAST(e.caratula AS varchar(500)) AS caratula,
               e.usuario AS exp_usuario,
               l.liq_id, l.fecha AS liq_fecha, l.fecha_cierre, l.importe_liq, l.importe_debi,
               l.usuario AS liq_usuario
          FROM aeda.dbo.adm_pasivo p
          JOIN aeda.dbo.adm_agentes a ON a.age_id = p.age_id AND a.tipo_id = 2
          JOIN aeda.dbo.mse_expedientes e ON e.exp_id = p.exp_id
          LEFT JOIN aeda.dbo.pres_liquida l ON l.exp_id = p.exp_id""",
    "pagos": """
        SELECT g.pago_id, g.pago_nro, g.tipo, g.fecha, g.importe, g.estado, g.age_id,
               CAST(g.obs AS varchar(500)) AS obs, g.usr,
               b.cuil AS ben_cuil, CAST(b.ben_nombre AS varchar(200)) AS ben_nombre
          FROM aeda.dbo.adm_pagos g
          JOIN aeda.dbo.adm_agentes a ON a.age_id = g.age_id AND a.tipo_id = 2
          LEFT JOIN aeda.dbo.afi_benef b ON b.ben_id = a.cta_id""",
    "aplicaciones": """
        SELECT x.aplicacion_id, x.comp_id, x.tipo_aplic, x.aplica_id, x.fecha, x.aplicado, x.estado
          FROM aeda.dbo.adm_pasivoAplic x
          JOIN aeda.dbo.adm_agentes a ON a.age_id = x.age_id AND a.tipo_id = 2""",
}


def _d(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


def _dia(v) -> date | None:
    if v is None:
        return None
    return v.date() if isinstance(v, datetime) else v


def _ahora(v) -> datetime | None:
    if v is None:
        return None
    return v if isinstance(v, datetime) else datetime(v.year, v.month, v.day)


def _int(v) -> int:
    t = solo_digitos(str(v or ""))
    return int(t) if t else 0


def _pesos(v) -> str:
    return f"$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def leer_aeda(cn) -> dict:
    cur = cn.cursor()
    datos = {k: _filas(cur, sql) for k, sql in SQL_AEDA.items()}
    cur.close()
    return datos


# ─────────────────────────────────────────────────────────────────────────────
# Destino
# ─────────────────────────────────────────────────────────────────────────────

def _columna(cur, tabla, columna) -> bool:
    cur.execute("SELECT COUNT(*) AS n FROM information_schema.columns WHERE table_schema = DATABASE() "
                "AND table_name = %s AND column_name = %s", (tabla, columna))
    return bool(cur.fetchone()["n"])


def leer_destino(cur, email_usuario: str | None) -> dict:
    if not _columna(cur, "c_concepto_de_gastos", "clase_reintegro"):
        salir("Falta c_concepto_de_gastos.clase_reintegro. Correr antes sql/reintegros_clase_20261111.sql.")
    d = {"orden_nro_origen": _columna(cur, "pago_ordenes", "nro_origen")}

    # Los reintegros que trajo importar_aeda_reintegros.py, con su primer renglón.
    cur.execute("""SELECT r.id, r.nro_solicitud, r.estado, r.importe_aprobado, r.id_orden_pago, r.observaciones,
                          t.cuil AS cuil_titular, t.apellido_nombres AS titular,
                          dt.id_concepto_gasto, g.descripcion AS concepto, g.clase_reintegro AS clase,
                          a.id_afiliado AS id_afiliado_det, a.cuil AS cuil_det, a.apellido_nombres AS nombre_det
                     FROM c_reintegro_afiliados r
                     JOIN p_afiliados t ON t.id_afiliado = r.id_afiliado
                     LEFT JOIN c_reintegro_afiliados_detalle dt
                            ON dt.id = (SELECT MIN(x.id) FROM c_reintegro_afiliados_detalle x WHERE x.id_reintegro = r.id)
                     LEFT JOIN c_concepto_de_gastos g ON g.id = dt.id_concepto_gasto
                     LEFT JOIN p_afiliados a ON a.id_afiliado = dt.id_afiliado
                    WHERE r.observaciones LIKE '[AEDA afi_reintegros %'""")
    d["reintegros"] = {}
    for f in cur.fetchall():
        m = RE_REINT.match(f["observaciones"] or "")
        if m:
            d["reintegros"][int(m.group(1))] = f
    if not d["reintegros"]:
        salir("No hay reintegros importados de AEDA. Correr antes importar_aeda_reintegros.py --aplicar.")

    cur.execute("""SELECT e.id AS id_exp, e.nro_expediente, e.estado, e.asunto
                     FROM me_expedientes e
                    WHERE e.asunto LIKE '[AEDA reintegro adm_pasivo %'""")
    d["exp_aeda"] = {int(RE_EXP.match(f["asunto"]).group(1)): f for f in cur.fetchall()
                     if RE_EXP.match(f["asunto"] or "")}
    cur.execute("SELECT nro_expediente FROM me_expedientes")
    d["nros_exp"] = {f["nro_expediente"] for f in cur.fetchall()}

    cur.execute("""SELECT pp.id AS id_pago, pp.nro_pago, pp.estado, pp.importe_total,
                          o.id AS id_orden, o.clase, o.estado AS estado_orden
                     FROM pago_pagos pp JOIN pago_ordenes o ON o.id = pp.id_orden
                    WHERE pp.nro_pago LIKE 'AEDA-PG-%'""")
    d["pagos_aeda"] = {int(RE_PAGO.match(f["nro_pago"]).group(1)): f for f in cur.fetchall()
                       if RE_PAGO.match(f["nro_pago"] or "")}
    cur.execute("SELECT nro_orden FROM pago_ordenes WHERE nro_orden LIKE 'AEDA-OP-%'")
    d["nros_orden"] = {f["nro_orden"] for f in cur.fetchall()}

    # Los renglones de las órdenes de AEDA de reintegros, para reconciliarlos.
    cur.execute("""SELECT d.id, d.id_orden, d.id_reintegro, d.importe
                     FROM pago_ordenes_reintegro_det d JOIN pago_ordenes o ON o.id = d.id_orden
                    WHERE o.nro_orden LIKE 'AEDA-OP-%' AND o.clase = 'reintegro'""")
    d["det_aeda"] = {(f["id_orden"], f["id_reintegro"]): f for f in cur.fetchall()}

    # Los conceptos de gasto para los pagos que no son de un reintegro.
    cur.execute("SELECT id, descripcion FROM c_concepto_de_gastos WHERE activo = 1")
    d["conceptos"] = {normalizar(f["descripcion"]): f for f in cur.fetchall()}

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


# ─────────────────────────────────────────────────────────────────────────────
# Plan
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Plan:
    expedientes: list = field(default_factory=list)       # nuevos
    anular_exp: list = field(default_factory=list)
    pagos: list = field(default_factory=list)             # nuevos
    anular_pagos: list = field(default_factory=list)
    conceptos: list = field(default_factory=list)         # pagos sin reintegro: órdenes por concepto nuevas
    aplicaciones: dict = field(default_factory=dict)      # (pago_id, comp_id) → {importe, ids, fecha}
    impagos: list = field(default_factory=list)
    informe: list = field(default_factory=list)
    cuenta: dict = field(default_factory=dict)
    por_clase: dict = field(default_factory=lambda: defaultdict(lambda: [0, CERO]))

    def contar(self, clave, n=1):
        self.cuenta[clave] = self.cuenta.get(clave, 0) + n

    def anotar(self, accion, **datos):
        self.informe.append({"accion": accion, **datos})


def _concepto_sin_reintegro(g, destino) -> dict | None:
    obs = normalizar(g["obs"])
    nombre = next((c for texto, c in CONCEPTOS_SIN_REINTEGRO if normalizar(texto) in obs),
                  CONCEPTO_SIN_REINTEGRO_DEFECTO)
    return destino["conceptos"].get(normalizar(nombre))


def _nro_expediente(c, destino, usados) -> str:
    nro = limpio(c["exp_nro"]) or f"AEDA-EXP-{c['exp_id']}"
    if nro in destino["nros_exp"] or nro in usados:
        nro = f"{nro}-{c['comp_id']}"
    usados.add(nro)
    return nro[:30]


def armar_plan(aeda: dict, destino: dict) -> Plan:
    plan = Plan()
    usados = set()
    comps = {}                                            # comp_id → lo que pueden usar las aplicaciones
    for c in sorted(aeda["comprobantes"], key=lambda x: x["comp_id"]):
        cid = c["comp_id"]
        estado = limpio(c["estado"]).upper()
        ya = destino["exp_aeda"].get(cid)
        rid = _int(c["numero"])
        r = destino["reintegros"].get(rid)
        c.update(_total=_d(c["importe"]), _fecha=_dia(c["fecha"]), _rid=rid, _r=r)
        base = {"aeda": f"adm_pasivo {cid}", "nro": limpio(c["exp_nro"]), "importe": c["_total"],
                "reintegro": r["nro_solicitud"] if r else f"afi_reintegros {rid}",
                "afiliado": r["titular"] if r else ""}

        if estado == "X":
            if ya and ya["estado"] != "anulado":
                plan.anular_exp.append(ya)
                plan.contar("expedientes anulados en AEDA después de importados (se anulan)")
                plan.anotar("anular expediente", **base, nota="anulado en AEDA")
            else:
                plan.contar("comprobantes anulados en AEDA (no se importan)")
            continue
        if c["tcomp_id"] != TCOMP_REINTEGRO:
            plan.contar(f"comprobantes de tipo {c['tcomp_id']} (no se importan)")
            plan.anotar("omitido", **base, nota=f"tipo de comprobante {c['tcomp_id']} de AEDA")
            continue
        if not r:
            plan.contar("comprobantes sin el reintegro importado (no se importan)")
            plan.anotar("omitido", **base, nota="el reintegro no está en el sindicato: correr "
                                                "importar_aeda_reintegros.py (o el CUIL no está en el padrón)")
            continue
        if r["importe_aprobado"] is not None and abs(_d(r["importe_aprobado"]) - c["_total"]) > TOL:
            plan.anotar("aviso", **base, nota=f"el reintegro es de {_pesos(_d(r['importe_aprobado']))}")
            plan.contar("con otro importe que el reintegro (entran igual)")
        if ya:
            plan.contar("expedientes ya importados")
            comps[cid] = {**c, "_id_exp": ya["id_exp"], "_existente": True}
            continue
        clase = r["clase"] or "reintegro"
        nuevo = {**c, "_nro_exp": _nro_expediente(c, destino, usados), "_clase": clase,
                 "_exp_fecha": _ahora(c["exp_fecha"] or c["fecha"]),
                 "_cierre": _ahora(c["fecha_cierre"] or c["liq_fecha"]), "_existente": False}
        plan.expedientes.append(nuevo)
        comps[cid] = nuevo
        plan.por_clase[CLASE_TXT[clase]][0] += 1
        plan.por_clase[CLASE_TXT[clase]][1] += c["_total"]
        plan.contar("expedientes a importar")
        plan.anotar("crear expediente", **base, fecha=c["_fecha"], clase=CLASE_TXT[clase],
                    nota=r["concepto"] or "")

    # Aplicaciones activas de tipo P (pago → comprobante), agrupadas por par.
    activas = defaultdict(lambda: {"importe": CERO, "ids": [], "fecha": None})
    for x in aeda["aplicaciones"]:
        if limpio(x["estado"]).upper() != "A" or limpio(x["tipo_aplic"]).upper() != "P":
            continue
        if x["comp_id"] not in comps:
            continue
        o = activas[(x["aplica_id"], x["comp_id"])]
        o["importe"] += _d(x["aplicado"])
        o["ids"].append(x["aplicacion_id"])
        f = _dia(x["fecha"])
        o["fecha"] = max(o["fecha"], f) if o["fecha"] and f else (o["fecha"] or f)

    pagos_validos = {}
    con_aplic = {pid for (pid, _) in activas}
    for g in sorted(aeda["pagos"], key=lambda x: x["pago_id"]):
        pid = g["pago_id"]
        estado = limpio(g["estado"]).upper()
        ya = destino["pagos_aeda"].get(pid)
        g.update(_importe=_d(g["importe"]), _fecha=_dia(g["fecha"]))
        base = {"aeda": f"adm_pagos {pid}", "nro": g["pago_nro"], "importe": g["_importe"],
                "nota": limpio(g["obs"])[:120]}
        if estado == "X":
            if ya and ya["estado"] != "anulado":
                plan.anular_pagos.append(ya)
                plan.contar("pagos anulados en AEDA después de importados (se anulan)")
                plan.anotar("anular pago", **base)
            else:
                plan.contar("pagos anulados en AEDA (no se importan)")
            continue
        if pid not in con_aplic:
            if ya and ya["clase"] == "concepto":
                plan.contar("pagos por concepto ya importados")
            elif ya:
                plan.contar("pagos importados como reintegro que ya no cancelan ninguno (revisar)")
                plan.anotar("aviso", **base, fecha=g["_fecha"],
                            nota="en AEDA ya no cancela ningún reintegro: se le sacan los renglones")
            elif f"AEDA-OP-{pid}" in destino["nros_orden"]:
                plan.contar("pagos con el número de orden ya usado (se saltean)")
                plan.anotar("omitido", **base)
            else:
                concepto = _concepto_sin_reintegro(g, destino)
                if not concepto:
                    plan.contar("pagos sin reintegro sin concepto de gasto (no se importan)")
                    plan.anotar("omitido", **base, nota="no está el concepto de gasto para imputarlo")
                    continue
                plan.conceptos.append({**g, "_concepto": concepto})
                plan.contar("pagos a afiliados que no son reintegros (entran como orden por concepto)")
                plan.anotar("crear orden por concepto", **base, fecha=g["_fecha"],
                            afiliado=limpio(g["ben_nombre"]), clase=concepto["descripcion"])
            continue
        if ya:
            plan.contar("pagos ya importados")
            pagos_validos[pid] = {**g, "_existente": True, "_id_pago": ya["id_pago"], "_id_orden": ya["id_orden"]}
            continue
        if f"AEDA-OP-{pid}" in destino["nros_orden"]:
            plan.contar("pagos con el número de orden ya usado (se saltean)")
            plan.anotar("omitido", **base)
            continue
        nuevo = {**g, "_existente": False,
                 "_renglones": [(comps[cid], o["importe"]) for (p, cid), o in activas.items() if p == pid]}
        plan.pagos.append(nuevo)
        pagos_validos[pid] = nuevo
        plan.contar("pagos a importar")
        plan.anotar("crear pago", **base, fecha=g["_fecha"])

    plan.aplicaciones = {k: o for k, o in activas.items() if k[0] in pagos_validos}
    aplicado = defaultdict(Decimal)
    for (pid, cid), o in plan.aplicaciones.items():
        aplicado[cid] += o["importe"]
    for cid, c in comps.items():
        if aplicado[cid] + TOL < c["_total"]:
            plan.impagos.append(c)
            plan.contar("comprobantes impagos o pagados en parte en AEDA")
            plan.anotar("impago", aeda=f"adm_pasivo {cid}", nro=limpio(c["exp_nro"]), importe=c["_total"],
                        reintegro=c["_r"]["nro_solicitud"], afiliado=c["_r"]["titular"],
                        nota=f"pagado en AEDA {_pesos(aplicado[cid])}: el reintegro sigue «pagada», revisarlo")
    plan._comps, plan._pagos = comps, pagos_validos
    return plan


# ─────────────────────────────────────────────────────────────────────────────
# Escritura
# ─────────────────────────────────────────────────────────────────────────────

def _crear_expediente(cur, c, destino, usuario) -> int:
    """El expediente de la mesa, sin liquidación: un reintegro no devenga deuda."""
    r = c["_r"]
    caratula = limpio(c["caratula"])
    asunto = (MARCA_EXP.format(c["comp_id"]) + f" {CLASE_TXT[c['_clase']]} {r['nro_solicitud']}"
              + (f" ({r['concepto']})" if r["concepto"] else "")
              + f". Expediente {limpio(c['exp_nro']) or '—'} de AEDA" + (f": {caratula}" if caratula else ""))
    cur.execute("""
        INSERT INTO me_expedientes
          (nro_expediente, anio, id_comprobante, id_proveedor, cuit_emisor, razon_social_emisor,
           importe_total, moneda, estado, asunto, creado, usuario_creacion)
        VALUES (%s, %s, NULL, NULL, %s, %s, %s, 'PES', %s, %s, %s, %s)
    """, (c["_nro_exp"], c["_exp_fecha"].year, r["cuil_titular"], (r["titular"] or "")[:200], c["_total"],
          ESTADO_EXP, asunto[:500], c["_exp_fecha"], usuario))
    id_exp = cur.lastrowid
    quien = limpio(c["exp_usuario"])
    cur.execute("""INSERT INTO me_expediente_movimientos
                     (id_expediente, tipo, estado_resultante, usuario_id, observaciones, fecha)
                   VALUES (%s, 'ingreso', 'ingresado', %s, %s, %s)""",
                (id_exp, usuario, f"Ingresado en AEDA{' por ' + quien if quien else ''} "
                                  f"(expediente {limpio(c['exp_nro']) or '—'}).", c["_exp_fecha"]))
    liquido = limpio(c["liq_usuario"])
    cur.execute("""INSERT INTO me_expediente_movimientos
                     (id_expediente, tipo, estado_resultante, usuario_id, observaciones, fecha)
                   VALUES (%s, 'nota', %s, %s, %s, %s)""",
                (id_exp, ESTADO_EXP, usuario,
                 (f"Liquidado en AEDA{' por ' + liquido if liquido else ''}"
                  + (f" el {c['_cierre']:%d/%m/%Y}" if c["_cierre"] else "") + ". "
                  if c["liq_id"] else "")
                 + f"{CLASE_TXT[c['_clase']]} a afiliado: solo registra el gasto al pagarse. "
                 "Importado por importar_aeda_cc_afiliados.py.", c["_cierre"] or c["_exp_fecha"]))
    return id_exp


def _crear_pago(cur, g, destino, usuario, clase="reintegro") -> tuple[int, int]:
    obs = limpio(g["obs"])
    nota = (f"[AEDA adm_pagos {g['pago_id']}] Pago {g['pago_nro']} de AEDA"
            + (f" ({limpio(g['usr'])})" if limpio(g["usr"]) else "") + (f". {obs}" if obs else "."))
    cur.execute("""INSERT INTO pago_ordenes
                     (nro_orden, clase, anio, periodo, fecha, estado, importe_total, moneda,
                      niveles_requeridos, niveles_aprobados, observaciones, id_usuario_creacion, creado)
                   VALUES (%s, %s, %s, %s, %s, 'pagada', %s, 'ARS', 1, 1, %s, %s, %s)""",
                (f"AEDA-OP-{g['pago_id']}", clase, g["_fecha"].year, g["_fecha"].strftime("%Y%m"), g["_fecha"],
                 g["_importe"], nota, usuario, _ahora(g["_fecha"])))
    id_orden = cur.lastrowid
    if destino["orden_nro_origen"] and str(g["pago_nro"] or "").isdigit():
        cur.execute("UPDATE pago_ordenes SET nro_origen = %s WHERE id = %s", (int(g["pago_nro"]), id_orden))
    cur.execute("""INSERT INTO pago_pagos
                     (nro_pago, nro_origen, id_orden, fecha_pago, estado, importe_total, observaciones,
                      id_usuario_creacion, creado)
                   VALUES (%s, %s, %s, %s, 'emitido', %s, %s, %s, %s)""",
                (f"AEDA-PG-{g['pago_id']}", g["pago_nro"], id_orden, g["_fecha"], g["_importe"], nota,
                 usuario, _ahora(g["_fecha"])))
    return id_orden, cur.lastrowid


def aplicar(cur, plan: Plan, destino: dict) -> None:
    usuario = destino["usuario"]["id"]

    # Lo que una versión anterior de este script grabó como deuda: la liquidación
    # y la aplicación de un reintegro no corresponden (solo el gasto, al pagar).
    cur.execute("DELETE FROM c_pasivo_aplicacion WHERE observaciones LIKE '[AEDA reintegro adm_pasivoAplic %%'")
    if cur.rowcount:
        plan.contar("aplicaciones de reintegros de una corrida anterior (se sacan)", cur.rowcount)
    cur.execute("""DELETE d FROM c_pasivo_liquidacion_detalle d
                     JOIN c_pasivo_liquidacion l ON l.id = d.id_pasivo_liquidacion
                     JOIN me_expedientes e ON e.id = l.id_expediente
                    WHERE e.asunto LIKE '[AEDA reintegro adm_pasivo %%'""")
    cur.execute("""DELETE l FROM c_pasivo_liquidacion l JOIN me_expedientes e ON e.id = l.id_expediente
                    WHERE e.asunto LIKE '[AEDA reintegro adm_pasivo %%'""")
    if cur.rowcount:
        plan.contar("liquidaciones de reintegros de una corrida anterior (se sacan)", cur.rowcount)

    for c in plan.expedientes:
        _crear_expediente(cur, c, destino, usuario)

    pago_de = {pid: (g["_id_orden"], g["_id_pago"]) for pid, g in plan._pagos.items() if g["_existente"]}
    for g in plan.pagos:
        pago_de[g["pago_id"]] = _crear_pago(cur, g, destino, usuario)

    # Lo que no es un reintegro: orden por concepto con un renglón de gasto a
    # nombre del afiliado (la descripción es lo que la pantalla muestra como beneficiario).
    for g in plan.conceptos:
        id_orden, _ = _crear_pago(cur, g, destino, usuario, clase="concepto")
        nombre = limpio(g["ben_nombre"]) or "Afiliado"
        cuil = solo_digitos(str(g["ben_cuil"] or ""))
        desc = (nombre + (f" (CUIL {cuil})" if cuil else "")
                + f": {limpio(g['obs']).rstrip('.-').strip() or 'pago de AEDA'}")
        cur.execute("""INSERT INTO pago_ordenes_concepto_det
                         (id_orden, tipo, id_concepto_gasto, id_motivo_ingreso, descripcion, importe, moneda, periodo)
                       VALUES (%s, 'gasto', %s, NULL, %s, %s, 'ARS', %s)""",
                    (id_orden, g["_concepto"]["id"], desc[:200], g["_importe"], g["_fecha"].strftime("%Y%m")))

    # Los renglones de la orden: qué reintegro pagó cada pago de AEDA, según sus
    # aplicaciones (adm_pasivoAplic). Se agregan los que faltan, se corrige el
    # importe de los que cambiaron y se sacan los que AEDA ya no tiene.
    existentes = dict(destino["det_aeda"])
    for (pid, cid), o in plan.aplicaciones.items():
        id_orden = pago_de[pid][0]
        c = plan._comps[cid]
        r = c["_r"]
        f = existentes.pop((id_orden, r["id"]), None)
        if f:
            if abs(_d(f["importe"]) - o["importe"]) > TOL:
                cur.execute("UPDATE pago_ordenes_reintegro_det SET importe = %s WHERE id = %s",
                            (o["importe"], f["id"]))
                plan.contar("renglones de orden que cambiaron en AEDA (se corrigen)")
        else:
            cur.execute("""INSERT INTO pago_ordenes_reintegro_det
                             (id_orden, id_reintegro, cuil, nombre, id_afiliado, descripcion, importe, moneda)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, 'ARS')""",
                        (id_orden, r["id"], r["cuil_det"] or r["cuil_titular"],
                         (r["nombre_det"] or r["titular"] or "")[:200], r["id_afiliado_det"],
                         (f"{CLASE_TXT[c.get('_clase') or r['clase']]} {r['nro_solicitud']}"
                          + (f": {r['concepto']}" if r["concepto"] else ""))[:200], o["importe"]))
            plan.contar("renglones de orden nuevos")
        cur.execute("UPDATE c_reintegro_afiliados SET id_orden_pago = %s WHERE id = %s", (id_orden, r["id"]))
    anuladas = {p["id_orden"] for p in plan.anular_pagos}
    for (id_orden, id_reint), f in existentes.items():
        if id_orden in anuladas:
            continue                      # queda en la orden anulada, que no cuenta para el saldo
        cur.execute("DELETE FROM pago_ordenes_reintegro_det WHERE id = %s", (f["id"],))
        cur.execute("UPDATE c_reintegro_afiliados SET id_orden_pago = NULL WHERE id = %s AND id_orden_pago = %s",
                    (id_reint, id_orden))
        plan.contar("renglones de orden que AEDA ya no tiene (se sacan)")

    motivo = "Anulado en AEDA (importar_aeda_cc_afiliados.py)."
    for p in plan.anular_pagos:
        cur.execute("UPDATE pago_pagos SET estado = 'anulado', fecha_anulacion = NOW(), motivo_anulacion = %s, "
                    "id_usuario_anulacion = %s WHERE id = %s", (motivo, usuario, p["id_pago"]))
        cur.execute("UPDATE pago_ordenes SET estado = 'anulada', fecha_anulacion = NOW(), motivo_anulacion = %s, "
                    "id_usuario_anulacion = %s WHERE id = %s", (motivo, usuario, p["id_orden"]))
        cur.execute("UPDATE c_reintegro_afiliados SET id_orden_pago = NULL WHERE id_orden_pago = %s",
                    (p["id_orden"],))
    for e in plan.anular_exp:
        cur.execute("UPDATE me_expedientes SET estado = 'anulado', motivo_anulacion = %s, fecha_anulacion = NOW(), "
                    "id_usuario_anulacion = %s WHERE id = %s", (motivo, usuario, e["id_exp"]))
        cd.movimiento(cur, e["id_exp"], "anulacion", "anulado", usuario, motivo)


def verificar(cur) -> dict:
    """Lo que quedó: expedientes de AEDA, lo pagado por órdenes vivas y cuántos
    reintegros tienen su orden. Ninguna liquidación ni aplicación de reintegros."""
    cur.execute("""SELECT COUNT(*) AS expedientes, COALESCE(SUM(importe_total), 0) AS importe
                     FROM me_expedientes
                    WHERE asunto LIKE '[AEDA reintegro adm_pasivo %' AND estado <> 'anulado'""")
    v = cur.fetchone()
    cur.execute("""SELECT COALESCE(SUM(d.importe), 0) AS pagado
                     FROM pago_ordenes_reintegro_det d JOIN pago_ordenes o ON o.id = d.id_orden
                    WHERE o.nro_orden LIKE 'AEDA-OP-%' AND o.clase = 'reintegro' AND o.estado <> 'anulada'""")
    v["pagado"] = cur.fetchone()["pagado"]
    cur.execute("""SELECT COUNT(*) AS n FROM c_reintegro_afiliados
                    WHERE observaciones LIKE '[AEDA afi_reintegros %' AND id_orden_pago IS NOT NULL""")
    v["con_orden"] = cur.fetchone()["n"]
    cur.execute("""SELECT COUNT(*) AS n, COALESCE(SUM(importe_total), 0) AS importe FROM pago_ordenes
                    WHERE nro_orden LIKE 'AEDA-OP-%' AND clase = 'concepto' AND estado <> 'anulada'
                      AND observaciones LIKE '[AEDA adm_pagos %'""")
    f = cur.fetchone()
    v["conceptos"], v["importe_conceptos"] = f["n"], f["importe"]
    cur.execute("""SELECT (SELECT COUNT(*) FROM c_pasivo_liquidacion l JOIN me_expedientes e ON e.id = l.id_expediente
                            WHERE e.asunto LIKE '[AEDA reintegro adm_pasivo %') AS liquidaciones,
                          (SELECT COUNT(*) FROM c_pasivo_aplicacion
                            WHERE observaciones LIKE '[AEDA reintegro adm_pasivoAplic %') AS aplicaciones""")
    v.update(cur.fetchone())
    return v


# ─────────────────────────────────────────────────────────────────────────────
# Informe
# ─────────────────────────────────────────────────────────────────────────────

CAMPOS_INFORME = ["accion", "aeda", "nro", "reintegro", "afiliado", "clase", "fecha", "importe", "nota"]


def _csv(v):
    if isinstance(v, Decimal):
        return f"{v:.2f}".replace(".", ",")
    if isinstance(v, date):
        return v.strftime("%d/%m/%Y")
    return v


def escribir_informe(plan: Plan, estado: str, inicio: datetime, usuario: dict, control: dict | None):
    CARPETA_LOGS.mkdir(exist_ok=True)
    base = CARPETA_LOGS / f"importar_aeda_cc_afiliados_{inicio:%Y%m%d_%H%M%S}"
    detalle, resumen = base.with_suffix(".csv"), base.with_suffix(".txt")
    with open(detalle, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_INFORME, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows({k: _csv(v) for k, v in fila.items()} for fila in plan.informe)
    lineas = [f"Reintegros y subsidios de AEDA: expedientes y pagos  {inicio:%d/%m/%Y %H:%M}",
              estado, f"Figura como cargado por: {usuario['nombre']}", ""]
    lineas += [f"  {n:>6}  {k}" for k, n in plan.cuenta.items()]
    if plan.por_clase:
        lineas += ["", "  Expedientes nuevos por clase:"]
        lineas += [f"    {k:<10} {n:>5}  {_pesos(t):>18}" for k, (n, t) in sorted(plan.por_clase.items())]
    if control:
        lineas += ["", "  Después de grabar (todo lo importado de AEDA):",
                   f"    expedientes vivos               {control['expedientes']:>6}  {_pesos(_d(control['importe'])):>18}",
                   f"    pagado por órdenes de AEDA             {_pesos(_d(control['pagado'])):>18}",
                   f"    reintegros con su orden de pago {control['con_orden']:>6}",
                   f"    órdenes por concepto (no reintegros) {control['conceptos']:>2}"
                   f"  {_pesos(_d(control['importe_conceptos'])):>18}",
                   f"    liquidaciones / aplicaciones    {control['liquidaciones']:>6} / {control['aplicaciones']}"
                   "   (tienen que ser 0: un reintegro solo registra el gasto)"]
    lineas += ["", f"Detalle: {detalle.name}"]
    resumen.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return resumen


def main():
    parser = argparse.ArgumentParser(description="Expedientes y pagos de reintegros y subsidios desde AEDA.")
    parser.add_argument("--aplicar", action="store_true", help="grabar en la base (sin esto, solo simula)")
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
        # La simulación también graba, dentro de la transacción, y la deshace:
        # el control del informe es el que va a quedar.
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
            resumen = escribir_informe(plan, "FALLÓ — no se grabó nada", inicio, destino["usuario"], None)
            print(f"\n  Falló la importación; no se grabó nada. Plan en {resumen}\n")
            raise

    resumen = escribir_informe(plan, estado, inicio, destino["usuario"], control)
    print()
    print(resumen.read_text(encoding="utf-8"))
    if not args.aplicar:
        print("  Para grabar:  python importar_aeda_cc_afiliados.py --aplicar\n")


if __name__ == "__main__":
    sys.exit(main())
