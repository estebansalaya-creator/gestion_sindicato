"""
importar_aeda_fondos.py — El libro de bancos y caja de AEDA.

`importar_aeda_cc_proveedores.py` y `importar_aeda_cc_afiliados.py` trajeron los
pagos sin tesorería: sin instrumentos y sin renglón en el libro de fondos. Este
script trae lo que falta para que el subdiario de cada cuenta de fondos diga lo
mismo que AEDA, desde el primer movimiento (05/2020):

    adm_movctas OP + adm_pagos P / A    →  pago_pagos_instrumentos de los pagos ya importados
    adm_pagos V + adm_ordpagoit         →  orden por concepto «AEDA-OP-N» pagada + pago «AEDA-PG-N»
                                           (gastos varios: tickets, sueldos, impuestos, subsidios)
    adm_pagos M + adm_movctas PF        →  c_movimiento_entre_cuentas (pases entre cuentas propias)
    adm_movctas DB                      →  c_movimiento_entre_cuentas (depósito de la cartera al banco)
    adm_movctas RC + fis_cobros         →  ingreso_ordenes «AEDA-RC-N» (cuota sindical, fiscalización)
    adm_movctas OI + adm_ordIngre       →  ingreso_ordenes «AEDA-OI-N» (alquileres, YMCA, intereses…)
    adm_valores + adm_valoresmv         →  c_valores_de_terceros con su historia (cartera y depósitos)

y cada comprobante deja su renglón en `c_movimientos_de_fondos` por las
funciones de `movimientos_fondos.py`, las mismas que usan las pantallas.

Uso
---
    python importar_aeda_fondos.py                  simula y escribe el informe en logs/
    python importar_aeda_fondos.py --aplicar        lo mismo, y lo graba (si el control da)
    python importar_aeda_fondos.py --aplicar --forzar   graba aunque algún saldo no dé
    python importar_aeda_fondos.py --usuario mail@… quién figura como el que cargó

Requiere las cuentas de fondos y chequeras de AEDA (importar_aeda_tesoreria.py)
y los pagos (importar_aeda_cc_proveedores.py, importar_aeda_cc_afiliados.py).

Decisiones
----------
Control. Antes de confirmar se compara, cuenta por cuenta, el saldo del libro
(solo lo que vino de AEDA) con el de `adm_movctas` (crédito − débito, sin lo
anulado). Si alguna no da, no se graba nada (salvo --forzar). AEDA no tiene
saldos de apertura: el saldo de una cuenta es el de su libro desde 2020, aunque
no sea el del banco (la cuenta corriente 2049118 da negativa en AEDA).

Pagos. Los instrumentos salen de los renglones OP de `adm_movctas`, uno por
renglón: D transferencia, Q cheque (con su chequera, por el rango de números),
C o una caja, efectivo. Suman el neto (el importe menos lo retenido), como
`pago_pagos_instrumentos` en el sindicato. Un pago de AEDA que no está en el
sindicato y no es un gasto vario (un anticipo sin beneficiario) entra como orden
por concepto, con el concepto que dice su observación.

Gastos varios (tipo V). Orden por concepto con un renglón por ítem de
`adm_ordpagoit`; el concepto se busca por descripción (AEDA corta a 30 letras).
El concepto 136 ya no existe en AEDA: va a GASTOS GENERALES con la nota.

Pases (tipo M). Una cuenta entrega y otra recibe, siempre una de cada lado. Si
toca el plazo fijo es una inversión; si sale de la cartera, un depósito; si sale
de un banco a la caja con cheques, una extracción (con sus cheques). Un pase de
una cuenta a sí misma no mueve nada y no entra.

Recaudación (RC). Cada renglón es un cobro de `fis_cobros`: una orden de
ingreso con el motivo del cobro (cuota sindical o fiscalización), el período y
el empleador. Los cobros de `fis_cobros` sin renglón en el libro de AEDA (2.511,
casi todos de 2023) no movieron ninguna cuenta y no entran; salen en el informe.

Valores de terceros. Los cheques recibidos en la cartera, con su librador (el
CUIT del cobro) y su historia: entran a cartera con el ingreso y pasan a
depositados con el depósito o el pase. `nro_cheque` es de 8: uno más largo
guarda los últimos 8 y el número entero va a observaciones.

Reversiones. En AEDA un pago en estado R se deshizo con otro pago en negativo
(«Reversion Orden de pago N», mismo importe, misma cuenta). Entran los dos: el
revertido sale de la cuenta y la reversión vuelve a entrar (al debe del libro,
que registrar_pago no admite: lo hace `_registrar_reversion`). Una reversión de
un gasto vario lleva los conceptos del revertido, en negativo.

Anulaciones. Lo anulado en AEDA y no importado no entra. Lo anulado en AEDA
después de importado se anula acá (orden, pago, movimiento o ingreso, y su
renglón del libro). Un pago anulado en el sindicato saca su renglón del libro.

Se puede volver a correr: instrumento «AEDA-MOV-<bancomovs_id>» en
`nro_referencia`, «[AEDA adm_pagos N]» / «[AEDA adm_movctas DB N]» en el
comentario del movimiento, ingresos «AEDA-RC-N» / «AEDA-OI-N», valores
«[AEDA adm_valores N]» y sus movimientos «[AEDA adm_valoresmv N]».

No trae la conciliación (`adm_conciliamov`): los renglones bancarios quedan
«emitido», pendientes de conciliar.
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
from importar_aeda_tesoreria import _buscar

import movimientos_fondos as mf
from numeracion import nro_visible
from db import get_connection

CERO = Decimal("0.00")
TOL = Decimal("0.01")
CONCEPTO_DEFECTO = "GASTOS GENERALES"
MOTIVO_DEFECTO = "CUOTA SINDICAL"
RE_PAGO = re.compile(r"^AEDA-PG-(\d+)$")
RE_MOV = re.compile(r"^\[AEDA (adm_pagos|adm_movctas DB) (\d+)\]")
RE_ING = re.compile(r"^AEDA-(RC|OI)-(\d+)$")
RE_VALOR = re.compile(r"^\[AEDA adm_valores (\d+)\]")
RE_VALORMV = re.compile(r"^\[AEDA adm_valoresmv (\d+)\]")
RE_INST = re.compile(r"^AEDA-MOV-(\d+)$")
RE_REVERSION = re.compile(r"REVERSION ORDEN DE PAGO 0*(\d+)")
MOTIVO_ANULADO = "Anulado en AEDA (importar_aeda_fondos.py)."

SQL_AEDA = {
    "movctas": """
        SELECT bancomovs_id, cajabanco_id, fecha, cheque_nro, vcto, debito, credito,
               CAST(obs AS varchar(250)) AS obs, ref_id, ref_nro, usr, TipoMov, status, chqra_id,
               CAST(alaorden AS varchar(100)) AS alaorden
          FROM aeda.dbo.adm_movctas""",
    "pagos": """
        SELECT g.pago_id, g.pago_nro, g.tipo, g.fecha, g.importe, g.estado, g.age_id,
               CAST(g.obs AS varchar(500)) AS obs, g.usr, a.tipo_id
          FROM aeda.dbo.adm_pagos g
          LEFT JOIN aeda.dbo.adm_agentes a ON a.age_id = g.age_id""",
    "items": "SELECT pago_id, conc_id, importe, estado FROM aeda.dbo.adm_ordpagoit",
    "conceptos": "SELECT conc_id, descrip, tipo_pig FROM aeda.dbo.adm_cptogasto",
    "cobros": """
        SELECT cobro_id, fecha, importe, estado, cuit, ref_nro, periodo, conc_id,
               CAST(obs AS varchar(250)) AS obs
          FROM aeda.dbo.fis_cobros""",
    "ingresos": """
        SELECT oi_id, fecha, importe, estado, conc_id, age_id, CAST(obs AS varchar(250)) AS obs, usuario
          FROM aeda.dbo.adm_ordIngre""",
    "valores": """
        SELECT valor_id, cajabanco_id, cod_bco, cod_suc, cod_cta, chq_nro, importe, fch_emision, vcto,
               tipo, status
          FROM aeda.dbo.adm_valores""",
    "valoresmv": """
        SELECT mov_id, valor_id, fch_Movto, Status, importe, ref_id, ref_nro
          FROM aeda.dbo.adm_valoresmv""",
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
    t = solo_digitos(str(v or "").split(".")[0])
    return int(t) if t else 0


def _pesos(v) -> str:
    return f"$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _anulado(v) -> bool:
    return limpio(v).upper() == "X"


def _periodo(v) -> str | None:
    t = solo_digitos(str(v or ""))
    return t if len(t) == 6 and 1 <= int(t[4:]) <= 12 else None


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
    d = {"orden_nro_origen": _columna(cur, "pago_ordenes", "nro_origen")}

    cur.execute("SELECT id, nombre, tipo_de_cuenta, comentario FROM c_cuentas_de_fondos")
    d["cuentas"], d["tipo_cuenta"], d["nombre_cuenta"] = {}, {}, {}
    for f in cur.fetchall():
        m = re.match(r"^\[AEDA adm_ctasfondos (\d+)\]", f["comentario"] or "")
        if m:
            d["cuentas"][int(m.group(1))] = f["id"]
        d["tipo_cuenta"][f["id"]] = f["tipo_de_cuenta"]
        d["nombre_cuenta"][f["id"]] = f["nombre"]
    if not d["cuentas"]:
        salir("No están las cuentas de fondos de AEDA. Correr antes importar_aeda_tesoreria.py --aplicar.")

    cur.execute("SELECT id, c_cuentas_de_fondosId AS cuenta, numero_desde, numero_hasta FROM c_chequeras")
    d["chequeras"] = cur.fetchall()

    cur.execute("""SELECT pp.id AS id_pago, pp.nro_pago, pp.estado, pp.importe_total, pp.id_orden,
                          o.clase, o.estado AS estado_orden
                     FROM pago_pagos pp JOIN pago_ordenes o ON o.id = pp.id_orden
                    WHERE pp.nro_pago LIKE 'AEDA-PG-%'""")
    d["pagos"] = {int(RE_PAGO.match(f["nro_pago"]).group(1)): f for f in cur.fetchall()
                  if RE_PAGO.match(f["nro_pago"] or "")}
    if not d["pagos"]:
        salir("No hay pagos de AEDA. Correr antes importar_aeda_cc_proveedores.py --aplicar.")
    cur.execute("SELECT nro_orden FROM pago_ordenes WHERE nro_orden LIKE 'AEDA-OP-%'")
    d["nros_orden"] = {f["nro_orden"] for f in cur.fetchall()}
    cur.execute("SELECT id_pago, nro_referencia FROM pago_pagos_instrumentos WHERE nro_referencia LIKE 'AEDA-MOV-%'")
    d["instrumentos"] = {int(RE_INST.match(f["nro_referencia"]).group(1)) for f in cur.fetchall()
                         if RE_INST.match(f["nro_referencia"] or "")}
    cur.execute("""SELECT DISTINCT i.id_pago FROM pago_pagos_instrumentos i
                     JOIN pago_pagos p ON p.id = i.id_pago WHERE p.nro_pago LIKE 'AEDA-PG-%'""")
    d["pagos_con_instrumentos"] = {f["id_pago"] for f in cur.fetchall()}

    cur.execute("""SELECT id, comentario, fecha_anulacion FROM c_movimiento_entre_cuentas
                    WHERE comentario LIKE '[AEDA %'""")
    d["movimientos"] = {}
    for f in cur.fetchall():
        m = RE_MOV.match(f["comentario"] or "")
        if m:
            d["movimientos"][("M" if m.group(1) == "adm_pagos" else "DB", int(m.group(2)))] = f

    cur.execute("SELECT id, nro_orden, estado FROM ingreso_ordenes WHERE nro_orden LIKE 'AEDA-%'")
    d["ingresos"] = {}
    for f in cur.fetchall():
        m = RE_ING.match(f["nro_orden"] or "")
        if m:
            d["ingresos"][(m.group(1), int(m.group(2)))] = f

    cur.execute("SELECT id, estado, observaciones FROM c_valores_de_terceros WHERE observaciones LIKE '[AEDA adm_valores %'")
    d["valores"] = {int(RE_VALOR.match(f["observaciones"]).group(1)): f for f in cur.fetchall()
                    if RE_VALOR.match(f["observaciones"] or "")}
    cur.execute("SELECT observaciones FROM c_valores_de_terceros_movimientos "
                "WHERE observaciones LIKE '[AEDA adm_valoresmv %'")
    d["valoresmv"] = {int(RE_VALORMV.match(f["observaciones"]).group(1)) for f in cur.fetchall()
                      if RE_VALORMV.match(f["observaciones"] or "")}

    cur.execute("SELECT id, descripcion FROM c_concepto_de_gastos ORDER BY activo DESC, id")
    d["conceptos"] = cur.fetchall()
    cur.execute("SELECT id, descripcion FROM c_motivos_de_ingreso ORDER BY activo DESC, id")
    d["motivos"] = cur.fetchall()
    cur.execute("SELECT CUIT AS cuit, razon_social FROM p_empresas")
    d["empresas"] = {int(f["cuit"]): limpio(f["razon_social"]) for f in cur.fetchall() if f["cuit"]}

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
    instrumentos: list = field(default_factory=list)      # (id_pago, renglón OP)
    pagos_concepto: list = field(default_factory=list)    # V y pagos sin destino: órdenes por concepto nuevas
    anular_pagos: list = field(default_factory=list)
    movimientos: list = field(default_factory=list)       # pases M y depósitos DB nuevos
    anular_movs: list = field(default_factory=list)
    ingresos: list = field(default_factory=list)          # RC y OI nuevos
    anular_ingresos: list = field(default_factory=list)
    valores: list = field(default_factory=list)
    valoresmv: list = field(default_factory=list)
    esperado: dict = field(default_factory=lambda: defaultdict(Decimal))   # cuenta → saldo de AEDA
    informe: list = field(default_factory=list)
    cuenta: dict = field(default_factory=dict)
    por_origen: dict = field(default_factory=lambda: defaultdict(lambda: [0, CERO]))

    def contar(self, clave, n=1):
        self.cuenta[clave] = self.cuenta.get(clave, 0) + n

    def anotar(self, accion, *bases, **datos):
        fila = {"accion": accion}
        for b in bases:
            fila.update(b)
        fila.update(datos)
        self.informe.append(fila)

    def sumar(self, origen, importe):
        self.por_origen[origen][0] += 1
        self.por_origen[origen][1] += importe


def _concepto(desc, destino):
    return _buscar(desc, destino["conceptos"], set())


def _chequera(cuenta, numero, destino):
    for q in destino["chequeras"]:
        if q["cuenta"] == cuenta and q["numero_desde"] <= numero <= q["numero_hasta"]:
            return q["id"]
    return None


def _instrumento(m, cuenta, destino) -> dict:
    tipo = limpio(m["TipoMov"]).upper()
    numero = _int(m["cheque_nro"])
    if destino["tipo_cuenta"].get(cuenta) == "C" or tipo == "C":
        clase = "efectivo"
    elif tipo == "Q":
        clase = "cheque"
    else:
        clase = "transferencia"
    return {"cuenta": cuenta, "tipo": clase, "importe": _d(m["debito"]),
            "nro_cheque": str(numero) if clase == "cheque" and numero else None,
            "fecha_cheque": _dia(m["vcto"]) if clase == "cheque" else None,
            "id_chequera": _chequera(cuenta, numero, destino) if clase == "cheque" else None,
            "ref": f"AEDA-MOV-{m['bancomovs_id']}", "_aeda": m["bancomovs_id"]}


def armar_plan(aeda: dict, destino: dict) -> Plan:
    plan = Plan()
    cuentas = destino["cuentas"]
    nombres_conc = {c["conc_id"]: limpio(c["descrip"]) for c in aeda["conceptos"]}

    por_ref = defaultdict(list)                  # (ref_id, ref_nro) → renglones
    for m in aeda["movctas"]:
        m["_fecha"] = _dia(m["fecha"])
        m["_ref"] = limpio(m["ref_id"]).upper()
        if m["cajabanco_id"] not in cuentas:
            plan.contar("renglones de AEDA de una cuenta que no está en el sindicato (no entran)")
            plan.anotar("omitido", aeda=f"adm_movctas {m['bancomovs_id']}",
                        nota=f"cuenta {m['cajabanco_id']} de AEDA sin importar")
            continue
        m["_cuenta"] = cuentas[m["cajabanco_id"]]
        por_ref[(m["_ref"], m["ref_nro"])].append(m)
        if not _anulado(m["status"]):
            plan.esperado[m["_cuenta"]] += _d(m["credito"]) - _d(m["debito"])

    # ── Pagos (OP): instrumentos de los ya importados; V como orden por concepto ──
    items = defaultdict(list)
    for i in aeda["items"]:
        if not _anulado(i["estado"]):
            items[i["pago_id"]].append(i)
    pagos_m = {}
    por_nro = {}
    for g in aeda["pagos"]:
        if limpio(g["tipo"]).upper() != "M":
            por_nro.setdefault(g["pago_nro"], g)

    def revertido_por_nro(g):
        """El pago que revierte un «Reversion Orden de pago N» de AEDA (importe negativo)."""
        if _d(g["importe"]) >= 0:
            return None
        m = RE_REVERSION.search(normalizar(g["obs"]))
        return por_nro.get(int(m.group(1))) if m else None
    for g in sorted(aeda["pagos"], key=lambda x: x["pago_id"]):
        pid, tipo = g["pago_id"], limpio(g["tipo"]).upper()
        g.update(_importe=_d(g["importe"]), _fecha=_dia(g["fecha"]), _tipo=tipo)
        base = {"aeda": f"adm_pagos {pid}", "nro": g["pago_nro"], "fecha": g["_fecha"], "importe": g["_importe"],
                "nota": limpio(g["obs"])[:120]}
        if tipo == "M":
            pagos_m[g["pago_nro"]] = g
            continue
        renglones = [m for m in por_ref.get(("OP", pid), []) if not _anulado(m["status"])]
        ya = destino["pagos"].get(pid)
        if _anulado(g["estado"]):
            if ya and ya["estado"] != "anulado" and ya["clase"] == "concepto" and tipo == "V":
                plan.anular_pagos.append(ya)
                plan.contar("gastos varios anulados en AEDA después de importados (se anulan)")
                plan.anotar("anular pago", base)
            elif ya and ya["id_pago"] in destino["pagos_con_instrumentos"]:
                plan.contar("pagos anulados con su renglón en el libro (se revisa que no sume)")
            else:
                plan.contar("pagos anulados en AEDA (no entran)")
            continue
        if not renglones:
            plan.contar("pagos de AEDA sin renglón en el libro (sin instrumentos)")
            plan.anotar("aviso", base, nota="AEDA no tiene de qué cuenta salió")
            continue
        insts = [_instrumento(m, m["_cuenta"], destino) for m in renglones]
        if ya:
            nuevos = [i for i in insts if i["_aeda"] not in destino["instrumentos"]]
            if nuevos:
                plan.instrumentos += [(ya["id_pago"], i) for i in nuevos]
                plan.contar("pagos ya importados a los que se les agregan los instrumentos")
                plan.sumar("Pagos (instrumentos)", sum(i["importe"] for i in nuevos))
            else:
                plan.contar("pagos con sus instrumentos ya importados")
            continue
        if f"AEDA-OP-{pid}" in destino["nros_orden"]:
            plan.contar("pagos con el número de orden ya usado (se saltean)")
            plan.anotar("omitido", base, nota="la orden AEDA-OP ya existe sin su pago")
            continue
        # Lo que no está en el sindicato: gastos varios y pagos sin beneficiario.
        # Uno de un proveedor o un afiliado lo trae su importador, no este.
        if tipo != "V" and g["tipo_id"] in (1, 2):
            quien = "importar_aeda_cc_proveedores.py" if g["tipo_id"] == 1 else "importar_aeda_cc_afiliados.py"
            plan.contar("pagos de proveedores o afiliados que todavía no están en el sindicato (no entran)")
            plan.anotar("omitido", base, nota=f"falta el pago: correr antes {quien} --aplicar")
            continue
        if tipo == "V" and items.get(pid):
            lineas = []
            for it in items[pid]:
                desc_aeda = nombres_conc.get(it["conc_id"])
                c = _concepto(desc_aeda, destino) if desc_aeda else None
                nota = ""
                if not c:
                    c = _concepto(CONCEPTO_DEFECTO, destino)
                    nota = (f"el concepto {it['conc_id']} ya no existe en AEDA" if not desc_aeda
                            else f"«{desc_aeda}» no está en el sindicato") + f": va a {CONCEPTO_DEFECTO}"
                    plan.contar("ítems de gastos varios sin su concepto (van a GASTOS GENERALES)")
                    plan.anotar("aviso", base, nota=nota)
                lineas.append({"concepto": c, "importe": _d(it["importe"])})
            if abs(sum(l["importe"] for l in lineas) - g["_importe"]) > TOL:
                plan.anotar("aviso", base, nota="los ítems no suman el pago")
                plan.contar("gastos varios cuyos ítems no suman el pago (entran igual)")
        elif revertido_por_nro(g):
            # «Reversion Orden de pago N»: el mismo gasto en negativo, con los
            # conceptos del pago que revierte (que en AEDA queda en estado R).
            orig = revertido_por_nro(g)
            lineas = []
            for it in items.get(orig["pago_id"], []):
                desc_aeda = nombres_conc.get(it["conc_id"])
                c = (_concepto(desc_aeda, destino) if desc_aeda else None) or _concepto(CONCEPTO_DEFECTO, destino)
                lineas.append({"concepto": c, "importe": -_d(it["importe"])})
            if not lineas or abs(sum(l["importe"] for l in lineas) - g["_importe"]) > TOL:
                lineas = [{"concepto": _concepto(CONCEPTO_DEFECTO, destino), "importe": g["_importe"]}]
            plan.contar("reversiones de gastos varios (entran en negativo: devuelven la plata a la cuenta)")
            plan.anotar("aviso", base, nota=f"revierte el pago {orig['pago_nro']}")
        else:
            c = _concepto(limpio(g["obs"]).rstrip(".-").strip(), destino) or _concepto(CONCEPTO_DEFECTO, destino)
            lineas = [{"concepto": c, "importe": g["_importe"]}]
            plan.anotar("aviso", base, nota=f"pago tipo {tipo} sin beneficiario en el sindicato: "
                                              f"orden por concepto a {c['descripcion'] if c else '—'}")
            plan.contar("pagos sin beneficiario en el sindicato (entran como orden por concepto)")
        if any(not l["concepto"] for l in lineas):
            plan.contar("gastos varios sin concepto para imputar (no entran)")
            plan.anotar("omitido", base, nota=f"falta el concepto {CONCEPTO_DEFECTO}")
            continue
        plan.pagos_concepto.append({**g, "_lineas": lineas, "_inst": insts})
        plan.contar("gastos varios a importar (orden por concepto + pago)")
        plan.sumar("Gastos varios", sum(i["importe"] for i in insts))
        plan.anotar("crear gasto vario", base,
                    cuenta=", ".join(sorted({destino["nombre_cuenta"][i["cuenta"]] for i in insts})))

    # ── Pases entre cuentas (M / PF) y depósitos (DB) ──
    def _mov(clave, g_fecha, renglones, base, comentario, nro_txt):
        sale = [m for m in renglones if _d(m["debito"]) > 0]
        entra = [m for m in renglones if _d(m["credito"]) > 0]
        c_sale = {m["_cuenta"] for m in sale}
        c_entra = {m["_cuenta"] for m in entra}
        if len(c_sale) != 1 or len(c_entra) != 1:
            plan.contar("movimientos con más de una cuenta de cada lado (no entran)")
            plan.anotar("omitido", base, nota="más de una cuenta de cada lado")
            return
        id_sale, id_entra = c_sale.pop(), c_entra.pop()
        imp_sale, imp_entra = sum(_d(m["debito"]) for m in sale), sum(_d(m["credito"]) for m in entra)
        if id_sale == id_entra:
            plan.contar("pases de una cuenta a sí misma (no mueven nada, no entran)")
            plan.anotar("omitido", base, nota=f"de {destino['nombre_cuenta'][id_sale]} a la misma cuenta")
            return
        if abs(imp_sale - imp_entra) > TOL:
            plan.contar("movimientos que no cierran entre las dos cuentas (no entran)")
            plan.anotar("omitido", base, nota=f"sale {_pesos(imp_sale)} y entra {_pesos(imp_entra)}")
            return
        t_sale, t_entra = destino["tipo_cuenta"].get(id_sale), destino["tipo_cuenta"].get(id_entra)
        cheques = [m for m in sale if limpio(m["TipoMov"]).upper() == "Q"]
        if "I" in (t_sale, t_entra):
            tipo = "inversiones"
        elif t_sale == "R" and t_entra == "B":
            tipo = "deposito_bancario"
        elif t_sale == "B" and t_entra == "C" and cheques:
            tipo = "extraccion_bancaria"
        else:
            tipo = "movimiento_entre_cuentas"
        plan.movimientos.append({
            "clave": clave, "fecha": g_fecha, "sale": id_sale, "entra": id_entra, "importe": imp_sale,
            "tipo": tipo, "comentario": comentario[:250],
            "cheques": [{"numero": _int(m["cheque_nro"]), "importe": _d(m["debito"]),
                         "chequera": _chequera(id_sale, _int(m["cheque_nro"]), destino),
                         "a_la_orden": limpio(m["alaorden"])[:100] or None,
                         "fecha": _dia(m["vcto"]) or m["_fecha"]} for m in cheques]})
        plan.contar(f"{nro_txt} a importar")
        plan.sumar("Pases y depósitos", imp_sale)
        plan.anotar(f"crear {tipo.replace('_', ' ')}", base,
                    cuenta=f"{destino['nombre_cuenta'][id_sale]} → {destino['nombre_cuenta'][id_entra]}")

    for nro, g in sorted(pagos_m.items(), key=lambda x: x[1]["pago_id"]):
        clave = ("M", g["pago_id"])
        ya = destino["movimientos"].get(clave)
        base = {"aeda": f"adm_pagos {g['pago_id']}", "nro": nro, "fecha": g["_fecha"], "importe": g["_importe"],
                "nota": limpio(g["obs"])[:120]}
        if _anulado(g["estado"]):
            if ya and not ya["fecha_anulacion"]:
                plan.anular_movs.append(ya)
                plan.contar("pases anulados en AEDA después de importados (se anulan)")
                plan.anotar("anular pase", base)
            else:
                plan.contar("pases anulados en AEDA (no entran)")
            continue
        if ya:
            plan.contar("pases ya importados")
            continue
        renglones = [m for m in por_ref.get(("PF", nro), []) if not _anulado(m["status"])]
        obs = limpio(g["obs"])
        _mov(clave, g["_fecha"], renglones, base,
             f"[AEDA adm_pagos {g['pago_id']}] Pase {nro} de AEDA" + (f": {obs}" if obs else "."), "pases")

    depositos = defaultdict(list)
    for (ref, nro), ms in por_ref.items():
        if ref == "DB":
            depositos[nro] = ms
    for nro, ms in sorted(depositos.items()):
        clave = ("DB", nro)
        ya = destino["movimientos"].get(clave)
        vivos = [m for m in ms if not _anulado(m["status"])]
        fecha = min(m["_fecha"] for m in ms)
        base = {"aeda": f"adm_movctas DB {nro}", "nro": nro, "fecha": fecha,
                "importe": sum(_d(m["credito"]) for m in vivos)}
        if not vivos:
            if ya and not ya["fecha_anulacion"]:
                plan.anular_movs.append(ya)
                plan.contar("depósitos anulados en AEDA después de importados (se anulan)")
            else:
                plan.contar("depósitos anulados en AEDA (no entran)")
            continue
        if ya:
            plan.contar("depósitos ya importados")
            continue
        _mov(clave, fecha, vivos, base, f"[AEDA adm_movctas DB {nro}] Depósito {nro} de AEDA.", "depósitos")

    # ── Ingresos: recaudación (RC) y órdenes de ingreso (OI) ──
    motivos_aeda = {c["conc_id"]: limpio(c["descrip"]) for c in aeda["conceptos"]}

    def _motivo(conc_id, base):
        desc = motivos_aeda.get(conc_id)
        mot = _buscar(desc, destino["motivos"], set()) if desc else None
        if not mot:
            mot = _buscar(MOTIVO_DEFECTO, destino["motivos"], set())
            plan.contar(f"ingresos sin su motivo en el sindicato (van a {MOTIVO_DEFECTO})")
            plan.anotar("aviso", base, nota=f"motivo {conc_id} «{desc or '—'}»: va a {MOTIVO_DEFECTO}")
        return mot

    cobros = {c["cobro_id"]: c for c in aeda["cobros"]}
    con_renglon = set()
    for (ref, nro), ms in sorted(por_ref.items(), key=lambda x: (x[0][0], x[0][1])):
        if ref != "RC":
            continue
        con_renglon.add(nro)
        clave = ("RC", nro)
        ya = destino["ingresos"].get(clave)
        vivos = [m for m in ms if not _anulado(m["status"])]
        c = cobros.get(nro)
        importe = sum(_d(m["credito"]) - _d(m["debito"]) for m in vivos)
        base = {"aeda": f"fis_cobros {nro}", "nro": nro, "fecha": ms[0]["_fecha"], "importe": importe}
        if not vivos:
            if ya and ya["estado"] != "anulado":
                plan.anular_ingresos.append(ya)
                plan.contar("cobros anulados en AEDA después de importados (se anulan)")
            else:
                plan.contar("cobros anulados en AEDA (no entran)")
            continue
        if ya:
            plan.contar("cobros ya importados")
            continue
        if not c:
            plan.contar("renglones de recaudación sin el cobro en fis_cobros (entran como cuota sindical)")
            plan.anotar("aviso", base, nota="sin el cobro en fis_cobros")
        mot = _motivo(c["conc_id"] if c else None, base)
        if not mot:
            plan.contar("cobros sin motivo para imputar (no entran)")
            plan.anotar("omitido", base, nota=f"falta el motivo {MOTIVO_DEFECTO}")
            continue
        cuit = _int(c["cuit"]) if c else 0
        razon = destino["empresas"].get(cuit, "")
        per = _periodo(c["periodo"]) if c else None
        desc = (mot["descripcion"] + (f" {per[:4]}-{per[4:]}" if per else "")
                + (f" · {razon}" if razon else "") + (f" (CUIT {cuit})" if cuit else ""))
        cuentas_ing = defaultdict(Decimal)
        for m in vivos:
            cuentas_ing[m["_cuenta"]] += _d(m["credito"]) - _d(m["debito"])
        obs = limpio(c["obs"]) if c else ""
        plan.ingresos.append({
            "clave": clave, "nro_orden": f"AEDA-RC-{nro}", "fecha": ms[0]["_fecha"], "importe": importe,
            "motivo": mot, "descripcion": desc[:200], "periodo": per, "cuentas": dict(cuentas_ing),
            "observaciones": f"[AEDA fis_cobros {nro}] Cobro {nro} de AEDA"
                             + (f", comprobante {c['ref_nro']}" if c and c["ref_nro"] else "")
                             + (f". {obs}" if obs else "."),
            "_cuit": cuit})
        plan.contar("cobros de recaudación a importar")
        plan.sumar("Recaudación", importe)
    sin_libro = [c for c in aeda["cobros"] if c["cobro_id"] not in con_renglon and not _anulado(c["estado"])]
    if sin_libro:
        plan.contar("cobros de fis_cobros sin renglón en el libro de AEDA (no movieron ninguna cuenta, no entran)",
                    len(sin_libro))
        por_anio = defaultdict(lambda: [0, CERO])
        for c in sin_libro:
            a = _dia(c["fecha"]).year if c["fecha"] else 0
            por_anio[a][0] += 1
            por_anio[a][1] += _d(c["importe"])
        for a, (n, t) in sorted(por_anio.items()):
            plan.anotar("cobro sin libro", aeda="fis_cobros", nro=a, importe=t,
                        nota=f"{n} cobros de {a} sin renglón en adm_movctas")

    for o in sorted(aeda["ingresos"], key=lambda x: x["oi_id"]):
        nro = o["oi_id"]
        clave = ("OI", nro)
        ya = destino["ingresos"].get(clave)
        ms = [m for m in por_ref.get(("OI", nro), [])]
        vivos = [m for m in ms if not _anulado(m["status"])]
        base = {"aeda": f"adm_ordIngre {nro}", "nro": nro, "fecha": _dia(o["fecha"]), "importe": _d(o["importe"]),
                "nota": limpio(o["obs"])[:120]}
        if _anulado(o["estado"]) or not vivos:
            if ya and ya["estado"] != "anulado":
                plan.anular_ingresos.append(ya)
                plan.contar("órdenes de ingreso anuladas en AEDA después de importadas (se anulan)")
            elif not _anulado(o["estado"]):
                plan.contar("órdenes de ingreso de AEDA sin renglón en el libro (no entran)")
                plan.anotar("omitido", base, nota="sin renglón en adm_movctas")
            else:
                plan.contar("órdenes de ingreso anuladas en AEDA (no entran)")
            continue
        if ya:
            plan.contar("órdenes de ingreso ya importadas")
            continue
        mot = _motivo(o["conc_id"], base)
        if not mot:
            plan.contar("órdenes de ingreso sin motivo para imputar (no entran)")
            continue
        cuentas_ing = defaultdict(Decimal)
        for m in vivos:
            cuentas_ing[m["_cuenta"]] += _d(m["credito"]) - _d(m["debito"])
        importe = sum(cuentas_ing.values())
        obs = limpio(o["obs"])
        per = f"{_dia(o['fecha']):%Y%m}" if o["fecha"] else None
        plan.ingresos.append({
            "clave": clave, "nro_orden": f"AEDA-OI-{nro}", "fecha": _dia(o["fecha"]) or vivos[0]["_fecha"],
            "importe": importe, "motivo": mot, "descripcion": (obs or mot["descripcion"])[:200], "periodo": per,
            "cuentas": dict(cuentas_ing),
            "observaciones": f"[AEDA adm_ordIngre {nro}] Orden de ingreso {nro} de AEDA"
                             + (f" ({limpio(o['usuario'])})" if limpio(o["usuario"]) else "")
                             + (f". {obs}" if obs else "."),
            "_cuit": 0})
        if abs(importe - _d(o["importe"])) > TOL:
            plan.anotar("aviso", base, nota=f"el libro de AEDA dice {_pesos(importe)}")
        plan.contar("órdenes de ingreso a importar")
        plan.sumar("Órdenes de ingreso", importe)

    # ── Valores de terceros ──
    mov_por_valor = defaultdict(list)
    for mv in aeda["valoresmv"]:
        mov_por_valor[mv["valor_id"]].append(mv)
    for v in sorted(aeda["valores"], key=lambda x: x["valor_id"]):
        vid = v["valor_id"]
        cuenta = cuentas.get(v["cajabanco_id"])
        movs = sorted(mov_por_valor.get(vid, []), key=lambda x: x["mov_id"])
        cuit = 0
        for mv in movs:
            if limpio(mv["ref_id"]).upper() == "RC" and mv["ref_nro"] in cobros:
                cuit = _int(cobros[mv["ref_nro"]]["cuit"])
        if vid not in destino["valores"]:
            if not cuenta:
                plan.contar("valores de una cuenta que no está en el sindicato (no entran)")
                continue
            numero = str(_int(v["chq_nro"]))
            estado = {"C": "en_cartera", "D": "depositado", "X": "anulado"}.get(limpio(v["status"]).upper(),
                                                                               "en_cartera")
            plan.valores.append({
                "valor_id": vid, "cuenta": cuenta, "nro_cheque": numero[-8:],
                "codigo_banco": str(_int(v["cod_bco"])).zfill(3)[:3] if _int(v["cod_bco"]) else None,
                "codigo_sucursal": str(_int(v["cod_suc"]))[:4] if _int(v["cod_suc"]) else None,
                "numero_cuenta": limpio(v["cod_cta"])[:20] or None,
                "cuit": str(cuit) if cuit else None, "razon": destino["empresas"].get(cuit) or None,
                "emision": _dia(v["fch_emision"]), "vto": _dia(v["vcto"]), "importe": _d(v["importe"]),
                "estado": estado,
                "obs": f"[AEDA adm_valores {vid}]" + (f" Cheque N° {numero}." if len(numero) > 8 else "")})
            plan.contar("valores de terceros a importar")
        for mv in movs:
            if mv["mov_id"] in destino["valoresmv"]:
                continue
            ref = limpio(mv["ref_id"]).upper()
            plan.valoresmv.append({**mv, "_ref": ref,
                                   "_estado": "en_cartera" if ref == "RC" else "depositado"})
            plan.contar("movimientos de valores a importar")

    plan._pagos_m = pagos_m
    return plan


# ─────────────────────────────────────────────────────────────────────────────
# Escritura
# ─────────────────────────────────────────────────────────────────────────────

def _insertar_instrumento(cur, id_pago, i):
    cur.execute("""INSERT INTO pago_pagos_instrumentos
                     (id_pago, id_cuenta_fondos, tipo_instrumento, importe, nro_cheque, fecha_cheque,
                      nro_referencia, id_chequera)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (id_pago, i["cuenta"], i["tipo"], i["importe"], i["nro_cheque"], i["fecha_cheque"],
                 i["ref"], i["id_chequera"]))


def _crear_gasto_vario(cur, g, destino, usuario) -> int:
    obs = limpio(g["obs"])
    nota = (f"[AEDA adm_pagos {g['pago_id']}] Pago {g['pago_nro']} de AEDA"
            + (f" ({limpio(g['usr'])})" if limpio(g["usr"]) else "") + (f". {obs}" if obs else "."))
    cur.execute("""INSERT INTO pago_ordenes
                     (nro_orden, clase, anio, periodo, fecha, estado, importe_total, moneda,
                      niveles_requeridos, niveles_aprobados, observaciones, id_usuario_creacion, creado)
                   VALUES (%s, 'concepto', %s, %s, %s, 'pagada', %s, 'ARS', 1, 1, %s, %s, %s)""",
                (f"AEDA-OP-{g['pago_id']}", g["_fecha"].year, g["_fecha"].strftime("%Y%m"), g["_fecha"],
                 g["_importe"], nota, usuario, _ahora(g["_fecha"])))
    id_orden = cur.lastrowid
    if destino["orden_nro_origen"] and str(g["pago_nro"] or "").isdigit():
        cur.execute("UPDATE pago_ordenes SET nro_origen = %s WHERE id = %s", (int(g["pago_nro"]), id_orden))
    desc = obs.rstrip(".-").strip()
    for l in g["_lineas"]:
        nombre = l["concepto"]["descripcion"]
        texto = (desc if len(g["_lineas"]) == 1 else f"{nombre}: {desc}") if desc else nombre
        cur.execute("""INSERT INTO pago_ordenes_concepto_det
                         (id_orden, tipo, id_concepto_gasto, id_motivo_ingreso, descripcion, importe, moneda, periodo)
                       VALUES (%s, 'gasto', %s, NULL, %s, %s, 'ARS', %s)""",
                    (id_orden, l["concepto"]["id"], texto[:200], l["importe"], g["_fecha"].strftime("%Y%m")))
    cur.execute("""INSERT INTO pago_pagos
                     (nro_pago, nro_origen, id_orden, fecha_pago, estado, importe_total, observaciones,
                      id_usuario_creacion, creado)
                   VALUES (%s, %s, %s, %s, 'emitido', %s, %s, %s, %s)""",
                (f"AEDA-PG-{g['pago_id']}", g["pago_nro"], id_orden, g["_fecha"], g["_importe"], nota,
                 usuario, _ahora(g["_fecha"])))
    return cur.lastrowid


def _registrar_reversion(cur, id_pago):
    """El renglón del libro de un pago en negativo («Reversion Orden de pago N»
    de AEDA): la plata vuelve a la cuenta, así que va al debe. registrar_pago no
    lo puede hacer (un pago siempre sale por el haber) y borraría el renglón."""
    cur.execute("""SELECT p.fecha_pago, p.nro_pago, p.nro_origen, p.estado,
                          i.id_cuenta_fondos AS cuenta, SUM(i.importe) AS importe
                     FROM pago_pagos p JOIN pago_pagos_instrumentos i ON i.id_pago = p.id
                    WHERE p.id = %s GROUP BY i.id_cuenta_fondos""", (id_pago,))
    filas = cur.fetchall()
    mf._sincronizar(cur, "pago", id_pago, [{
        "cuenta": f["cuenta"], "fecha": f["fecha_pago"], "debe": -f["importe"], "haber": 0,
        "concepto": f"Reversión: pago {nro_visible(f)}"} for f in filas])
    if filas and filas[0]["estado"] == "anulado":
        mf.anular(cur, "pago", id_pago, "Pago anulado")


def aplicar(cur, plan: Plan, destino: dict) -> None:
    usuario = destino["usuario"]["id"]

    # Pagos: instrumentos de los ya importados y gastos varios nuevos.
    tocados = set()
    for id_pago, i in plan.instrumentos:
        _insertar_instrumento(cur, id_pago, i)
        tocados.add(id_pago)
    for g in plan.pagos_concepto:
        id_pago = _crear_gasto_vario(cur, g, destino, usuario)
        for i in g["_inst"]:
            _insertar_instrumento(cur, id_pago, i)
        tocados.add(id_pago)
    for p in plan.anular_pagos:
        cur.execute("UPDATE pago_pagos SET estado = 'anulado', fecha_anulacion = NOW(), motivo_anulacion = %s, "
                    "id_usuario_anulacion = %s WHERE id = %s", (MOTIVO_ANULADO, usuario, p["id_pago"]))
        cur.execute("UPDATE pago_ordenes SET estado = 'anulada', fecha_anulacion = NOW(), motivo_anulacion = %s, "
                    "id_usuario_anulacion = %s WHERE id = %s", (MOTIVO_ANULADO, usuario, p["id_orden"]))
    # El libro de cada pago con instrumentos: lo nuevo, y lo que se anuló acá o en
    # AEDA después (registrar_pago anula el renglón de un pago anulado).
    # Una reversión de AEDA (pago en negativo) devuelve la plata: va al debe.
    cur.execute("""SELECT i.id_pago, SUM(i.importe) AS total FROM pago_pagos_instrumentos i
                     JOIN pago_pagos p ON p.id = i.id_pago WHERE p.nro_pago LIKE 'AEDA-PG-%'
                    GROUP BY i.id_pago""")
    for f in cur.fetchall():
        if f["total"] < 0:
            _registrar_reversion(cur, f["id_pago"])
        else:
            mf.registrar_pago(cur, f["id_pago"])

    # Pases y depósitos.
    mov_de = {k: v["id"] for k, v in destino["movimientos"].items()}
    for m in plan.movimientos:
        cur.execute("""INSERT INTO c_movimiento_entre_cuentas (fecha_emision, tipo_movimiento, importe, comentario,
                                                                id_usuario_emision)
                       VALUES (%s, %s, %s, %s, %s)""", (m["fecha"], m["tipo"], m["importe"], m["comentario"], usuario))
        id_mov = cur.lastrowid
        cur.executemany("""INSERT INTO c_movimiento_entre_cuentas_det (id_movimiento, id_cuenta_fondos, debe, haber,
                                                                        comentario)
                           VALUES (%s, %s, %s, %s, NULL)""",
                        [(id_mov, m["sale"], 0, m["importe"]), (id_mov, m["entra"], m["importe"], 0)])
        mf.registrar_movimiento(cur, id_mov)
        if m["cheques"] and destino["tipo_cuenta"].get(m["sale"]) == "B":
            mf.registrar_cheques(cur, "movimiento", id_mov, m["sale"], m["cheques"])
        mov_de[m["clave"]] = id_mov
    for m in plan.anular_movs:
        cur.execute("UPDATE c_movimiento_entre_cuentas SET fecha_anulacion = NOW(), motivo_anulacion = %s, "
                    "id_usuario_anulacion = %s WHERE id = %s", (MOTIVO_ANULADO, usuario, m["id"]))
        mf.anular(cur, "movimiento", m["id"], MOTIVO_ANULADO, usuario)

    # Ingresos.
    ing_de = {k: v["id"] for k, v in destino["ingresos"].items()}
    for o in plan.ingresos:
        cur.execute("""INSERT INTO ingreso_ordenes (nro_orden, clase, anio, fecha, estado, id_cuenta, importe_total,
                                                     moneda, origen, observaciones, id_usuario_creacion, creado)
                       VALUES (%s, 'varios', %s, %s, 'confirmado', NULL, %s, 'ARS', 'manual', %s, %s, %s)""",
                    (o["nro_orden"], o["fecha"].year, o["fecha"], o["importe"], o["observaciones"], usuario,
                     _ahora(o["fecha"])))
        id_orden = cur.lastrowid
        cur.execute("""INSERT INTO ingreso_ordenes_detalle (id_orden, tipo, id_motivo_ingreso, descripcion,
                                                            importe, moneda, periodo)
                       VALUES (%s, 'ingreso', %s, %s, %s, 'ARS', %s)""",
                    (id_orden, o["motivo"]["id"], o["descripcion"], o["importe"], o["periodo"]))
        cur.executemany("INSERT INTO ingreso_ordenes_cuentas (id_orden, id_cuenta_fondos, importe) VALUES (%s, %s, %s)",
                        [(id_orden, c, imp) for c, imp in o["cuentas"].items()])
        mf.registrar_ingreso(cur, id_orden)
        ing_de[o["clave"]] = id_orden
    for o in plan.anular_ingresos:
        cur.execute("UPDATE ingreso_ordenes SET estado = 'anulado', fecha_anulacion = NOW(), motivo_anulacion = %s, "
                    "id_usuario_anulacion = %s WHERE id = %s", (MOTIVO_ANULADO[:250], usuario, o["id"]))
        mf.anular(cur, "ingreso", o["id"], MOTIVO_ANULADO, usuario)

    # Valores de terceros y su historia.
    valor_de = {k: v["id"] for k, v in destino["valores"].items()}
    for v in plan.valores:
        cur.execute("""INSERT INTO c_valores_de_terceros
                         (tipo_valor, nro_cheque, codigo_banco, codigo_sucursal, numero_cuenta, cuit_librador,
                          razon_social_librador, fecha_emision, fecha_vencimiento, importe, estado,
                          id_cuenta_fondos, observaciones, id_usuario_carga)
                       VALUES ('cheque', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (v["nro_cheque"], v["codigo_banco"], v["codigo_sucursal"], v["numero_cuenta"], v["cuit"],
                     v["razon"], v["emision"], v["vto"], v["importe"], v["estado"], v["cuenta"], v["obs"][:300],
                     usuario))
        valor_de[v["valor_id"]] = cur.lastrowid
    pase_de = {nro: mov_de.get(("M", g["pago_id"])) for nro, g in plan._pagos_m.items()}
    anterior = {}
    for mv in sorted(plan.valoresmv, key=lambda x: x["mov_id"]):
        id_valor = valor_de.get(mv["valor_id"])
        if not id_valor:
            continue
        ref, nro = mv["_ref"], mv["ref_nro"]
        id_ing = ing_de.get(("RC", nro)) if ref == "RC" else None
        id_mov = mov_de.get(("DB", nro)) if ref == "DB" else (pase_de.get(nro) if ref == "PF" else None)
        previo = anterior.get(id_valor, None if ref == "RC" else "en_cartera")
        motivo = {"RC": f"Cobro {nro} de AEDA", "DB": f"Depósito {nro} de AEDA",
                  "PF": f"Pase {nro} de AEDA"}.get(ref, f"{ref} {nro} de AEDA")
        cur.execute("""INSERT INTO c_valores_de_terceros_movimientos
                         (id_valor, estado_anterior, estado_nuevo, fecha_movimiento, motivo, observaciones,
                          id_ingreso, id_movimiento_cuentas, id_usuario)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (id_valor, previo, mv["_estado"], _ahora(mv["fch_Movto"]) or datetime.now(), motivo,
                     f"[AEDA adm_valoresmv {mv['mov_id']}]", id_ing, id_mov, usuario))
        anterior[id_valor] = mv["_estado"]


def verificar(cur, plan: Plan, destino: dict) -> list[dict]:
    """Saldo del libro por cuenta (solo lo que vino de AEDA) contra el de AEDA."""
    cur.execute("""SELECT m.c_cuentas_de_fondosId AS cuenta,
                          COALESCE(SUM(m.importe_debe - m.importe_haber), 0) AS saldo, COUNT(*) AS renglones
                     FROM c_movimientos_de_fondos m
                     LEFT JOIN pago_pagos p ON p.id = m.pago_pagosId
                     LEFT JOIN ingreso_ordenes o ON o.id = m.ingreso_ordenesId
                     LEFT JOIN c_movimiento_entre_cuentas e ON e.id = m.c_movimiento_entre_cuentasId
                    WHERE m.fecha_anulacion IS NULL
                      AND (p.nro_pago LIKE 'AEDA-PG-%' OR o.nro_orden LIKE 'AEDA-%' OR e.comentario LIKE '[AEDA %')
                    GROUP BY m.c_cuentas_de_fondosId""")
    libro = {f["cuenta"]: f for f in cur.fetchall()}
    filas = []
    for cuenta in sorted(set(libro) | set(plan.esperado)):
        aeda = plan.esperado.get(cuenta, CERO)
        sind = _d(libro[cuenta]["saldo"]) if cuenta in libro else CERO
        filas.append({"cuenta": cuenta, "nombre": destino["nombre_cuenta"].get(cuenta, str(cuenta)),
                      "aeda": aeda, "sindicato": sind, "diferencia": sind - aeda,
                      "renglones": libro[cuenta]["renglones"] if cuenta in libro else 0})
    return filas


# ─────────────────────────────────────────────────────────────────────────────
# Informe
# ─────────────────────────────────────────────────────────────────────────────

CAMPOS_INFORME = ["accion", "aeda", "nro", "fecha", "importe", "cuenta", "nota"]


def _csv(v):
    if isinstance(v, Decimal):
        return f"{v:.2f}".replace(".", ",")
    if isinstance(v, date):
        return v.strftime("%d/%m/%Y")
    return v


def escribir_informe(plan: Plan, estado: str, inicio: datetime, usuario: dict, control: list | None):
    CARPETA_LOGS.mkdir(exist_ok=True)
    base = CARPETA_LOGS / f"importar_aeda_fondos_{inicio:%Y%m%d_%H%M%S}"
    detalle, resumen = base.with_suffix(".csv"), base.with_suffix(".txt")
    with open(detalle, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_INFORME, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows({k: _csv(v) for k, v in fila.items()} for fila in plan.informe)
    lineas = [f"Tesorería de AEDA: el libro de bancos y caja  {inicio:%d/%m/%Y %H:%M}",
              estado, f"Figura como cargado por: {usuario['nombre']}", ""]
    lineas += [f"  {n:>6}  {k}" for k, n in plan.cuenta.items()]
    if plan.por_origen:
        lineas += ["", "  Lo nuevo de esta corrida:"]
        lineas += [f"    {k:<24} {n:>6}  {_pesos(t):>22}" for k, (n, t) in plan.por_origen.items()]
    if control:
        lineas += ["", "  Saldo por cuenta (libro del sindicato, lo de AEDA, contra adm_movctas):",
                   f"    {'cuenta':<32} {'AEDA':>22} {'sindicato':>22} {'diferencia':>18} {'renglones':>9}"]
        for f in control:
            marca = "" if abs(f["diferencia"]) <= TOL else "   ← NO DA"
            lineas.append(f"    {f['nombre'][:32]:<32} {_pesos(f['aeda']):>22} {_pesos(f['sindicato']):>22} "
                          f"{_pesos(f['diferencia']):>18} {f['renglones']:>9}{marca}")
    lineas += ["", f"Detalle: {detalle.name}"]
    resumen.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return resumen


def main():
    parser = argparse.ArgumentParser(description="Libro de bancos y caja de AEDA.")
    parser.add_argument("--aplicar", action="store_true", help="grabar en la base (sin esto, solo simula)")
    parser.add_argument("--forzar", action="store_true", help="grabar aunque el control de saldos no dé")
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
                control = verificar(cur, plan, destino)
            no_dan = [f for f in control if abs(f["diferencia"]) > TOL]
            if args.aplicar and (not no_dan or args.forzar):
                conn.commit()
                estado = "APLICADA" + (" (forzada: hay cuentas que no dan)" if no_dan else "")
            else:
                conn.rollback()
                estado = ("NO SE GRABÓ: hay cuentas cuyo saldo no da con AEDA (ver abajo; --forzar para grabar igual)"
                          if args.aplicar else "SIMULACIÓN — no se grabó nada")
        except Exception:
            conn.rollback()
            resumen = escribir_informe(plan, "FALLÓ — no se grabó nada", inicio, destino["usuario"], None)
            print(f"\n  Falló la importación; no se grabó nada. Plan en {resumen}\n")
            raise

    resumen = escribir_informe(plan, estado, inicio, destino["usuario"], control)
    print()
    print(resumen.read_text(encoding="utf-8"))
    if not args.aplicar:
        print("  Para grabar:  python importar_aeda_fondos.py --aplicar\n")


if __name__ == "__main__":
    sys.exit(main())
