"""
importar_aeda_cc_proveedores.py — Cuentas corrientes de proveedores desde AEDA.

Trae la historia de cada proveedor —comprobantes, pagos, anticipos, cómo se
aplicó cada pago y las retenciones— para que la cuenta corriente del sindicato
(`v_cc_proveedores_movimientos` / `v_cc_proveedores_saldo`) dé lo mismo que
AEDA. Es lo que en gestion_adm hicieron los ETL de mcp_migracion (etl_pasivo,
etl_pagos, migrar_pagos_a_aplicaciones, etl_anticipo_detalle,
etl_retenciones_origen), en un solo script y sin tablas intermedias.

Origen (base `aeda`, agentes `adm_agentes.tipo_id = 1`, los proveedores):

    adm_pasivo + mse_expedientes      →  f_comprobantes_arca + me_expedientes
      + mse_anexos (CAE)                  («000002303/26»: el número de AEDA tal
                                          cual, como los migrados de gestion_adm;
                                          con su ingreso y su liquidación)
    pres_liquida + pres_liquidait     →  c_pasivo_liquidacion CERRADA (es deuda)
                                          + c_pasivo_liquidacion_detalle
    adm_pagos tipo P (pago)           →  pago_ordenes clase proveedor «AEDA-OP-N»
                                          + pago_pagos «AEDA-PG-N» (N° de AEDA en
                                          nro_origen) + pago_ordenes_detalle
    adm_pagos tipo A (anticipo)       →  pago_ordenes clase anticipo + pago_pagos
                                          + pago_ordenes_anticipo_det
    adm_pasivoAplic                   →  c_pasivo_aplicacion (origen «migracion»):
                                          P = un pago cancela una factura,
                                          C = una nota de crédito cancela una factura
    adm_retgan                        →  pago_retenciones + pago_retenciones_certificado
                                          («AEDA-CRT-N»: el número que el proveedor
                                          tiene en su certificado)

Uso
---
    python importar_aeda_cc_proveedores.py                  simula y escribe el informe en logs/
    python importar_aeda_cc_proveedores.py --aplicar        lo mismo, y lo graba
    python importar_aeda_cc_proveedores.py --usuario mail@… quién figura como el que cargó

Requiere los proveedores ya importados (importar_aeda_proveedores.py) y
sql/comprobantes_20261107.sql. Sin eso no arranca.

Se puede correr más de una vez —mientras AEDA siga en uso, para traer lo
nuevo—: lo importado lleva su origen («[AEDA adm_pasivo 7255]» en el asunto
del expediente, «AEDA-PG-12074» en el pago, «[AEDA adm_pasivoAplic 9196]» en
la aplicación, «[AEDA adm_retgan 342]» en la retención) y lo que ya está no se
vuelve a crear. Lo que se anuló en AEDA después de importado se anula acá; las
aplicaciones se reconcilian enteras (las que AEDA ya no tiene se sacan). Un
importe que cambió en AEDA no se pisa: sale en el informe.

Todo o nada, y con control: con --aplicar se graba todo en una transacción y,
ANTES de confirmarla, se compara el saldo de cada proveedor en la vista de la
cuenta corriente con el de AEDA. Si alguno no da, no se graba nada (salvo
--forzar) y el informe dice cuál.

Decisiones sobre los datos de AEDA
----------------------------------
Qué entra. Comprobantes en estado A (los X están anulados) y pagos que no
están anulados (E emitido; R, un anticipo de 2023 que tiene su aplicación
activa, cuenta como pago). Las aplicaciones en estado A.

Saldo de AEDA = facturas − notas de crédito − pagos − anticipos. En el
sindicato el saldo es debe − haber: el signo contrario (negativo = se le debe).

Tipo de comprobante. AEDA dice «Factura» o «Nota de Crédito», sin la letra. La
letra sale, en este orden, de Mis Comprobantes del sindicato (f_mis_comprobantes,
si se importó), de la copia de Mis Comprobantes que tiene AEDA (adm_comprobafip)
—de ahí también neto, IVA y exento, si el total coincide— y, si no aparece, de
la condición de IVA del proveedor: un responsable inscripto le factura B al
sindicato (exento); los demás, C.

Período. El de AEDA va a `periodo_desde`/`periodo_hasta` (el mes entero):
`periodo` es una columna calculada.

Concepto de la liquidación. El ítem de pres_liquidait (HONORARIOS, ATENCION
AFILIADOS…) buscado por descripción en c_concepto_de_gastos; si no está se
agrega al catálogo con la imputación de «GASTOS GENERALES», como hizo
importar_aeda_proveedores.py. El rubro de pasivo es el de la ficha del proveedor.

Estado del expediente. «pagado» si sus aplicaciones lo cancelan entero,
«liquidado» si queda saldo: así lo que AEDA dejó impago aparece en
v_expedientes_liquidados_impagos para la orden de pago.

Pago sin aplicaciones. Un pago P de AEDA que no cancela ninguna factura (la
que pagaba se anuló) es plata a cuenta del proveedor: entra como anticipo,
que es como la cuenta corriente lo puede mostrar.

Aplicación mal cargada en AEDA. Si un pago quedó aplicado por más de lo que se
pagó y hay UN solo pago del mismo proveedor, sin aplicar, por exactamente el
excedente, la aplicación sobrante se pasa a ese pago (E&N SERVICIOS: la factura
0003-00000001 de $43.130.000 tiene dos aplicaciones al anticipo 4260 de
$4.000.000; la de $15.000.000 es del anticipo 3916, que quedó sin aplicar). Si
no hay uno solo, queda como está y sale en el informe.

Comprobante ya cargado en el sindicato. Si el mismo comprobante (CUIT, punto
de venta, número y clase) ya entró por la carga nueva, no se duplica: los
pagos de AEDA se aplican a esa liquidación.

Retenciones. Solo Ganancias (AEDA no retiene otra cosa). El régimen sale de la
ficha del proveedor, que es de donde lo toma el cálculo nuevo; si la ficha no
lo tiene entra sin régimen y sale en el informe: completarla y volver a correr
lo completa. El comprobante del certificado es la factura si el pago cancela
una sola; si no, la orden de pago (tipo 6, con el número de AEDA).

Qué NO trae. Los instrumentos del pago (cheques, transferencias) ni los
movimientos de tesorería: son de la importación de bancos y fondos.
"""

import argparse
import calendar
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
import rg830
from db import get_connection

CERO = Decimal("0.00")
TOL = Decimal("0.01")

TCOMP_DEBITO = {13: "factura", 6: "nota de débito"}
TCOMP_CREDITO = {5: "nota de crédito"}
PLURAL = {"factura": "facturas", "nota de débito": "notas de débito", "nota de crédito": "notas de crédito"}
ESTADOS_PAGO_VALIDOS = {"E", "R"}
TIPOS_PAGO = {"P": "pago", "A": "anticipo"}

#: Sin el tipo en Mis Comprobantes: lo que factura cada condición al sindicato.
TIPO_POR_IVA = {True: {"factura": "006", "nota de débito": "007", "nota de crédito": "008"},
                False: {"factura": "011", "nota de débito": "012", "nota de crédito": "013"}}
#: comprobante_tipo de pago_retenciones_certificado: 1 FAC 2 REC 3 NC 4 ND 6 OP.
TIPO_CERTIFICADO = {"factura": 1, "recibo": 2, "nota de crédito": 3, "nota de débito": 4}
FORMULARIO_SIRE = "2005"
CONCEPTO_PLANTILLA = "GASTOS GENERALES"

RE_EXP = re.compile(r"^\[AEDA adm_pasivo (\d+)\]")
RE_ORDEN = re.compile(r"^AEDA-OP-(\d+)$")
RE_PAGO = re.compile(r"^AEDA-PG-(\d+)$")
RE_APLIC = re.compile(r"^\[AEDA adm_pasivoAplic ([\d,]+)\]")
RE_RET = re.compile(r"^\[AEDA adm_retgan (\d+)\]")
RE_PROV = re.compile(r"^\[AEDA adm_proveedor (\d+)\]")


def _d(v) -> Decimal:
    return Decimal(str(v)).quantize(TOL) if v is not None else CERO


def _dia(v) -> date | None:
    if v is None:
        return None
    return v.date() if isinstance(v, datetime) else v


def _ahora(v) -> datetime | None:
    if v is None:
        return None
    return v if isinstance(v, datetime) else datetime(v.year, v.month, v.day)


def _int(v) -> int:
    t = solo_digitos(v)
    return int(t) if t else 0


def _pesos(v) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ─────────────────────────────────────────────────────────────────────────────
# Lectura de AEDA
# ─────────────────────────────────────────────────────────────────────────────

SQL_AEDA = {
    "agentes": """
        SELECT a.age_id, a.cta_id AS prest_id, p.cuit, p.prest_nombre
          FROM aeda.dbo.adm_agentes a
          JOIN aeda.dbo.adm_proveedor p ON p.prest_id = a.cta_id
         WHERE a.tipo_id = 1""",
    "comprobantes": """
        SELECT p.comp_id, p.tcomp_id, p.age_id, p.prefijo, p.numero, p.fecha, p.vence,
               p.importe, p.periodo, p.estado,
               e.exp_id, e.exp_nro, e.fecha AS exp_fecha, CAST(e.caratula AS varchar(500)) AS caratula,
               e.usuario AS exp_usuario,
               l.liq_id, l.fecha AS liq_fecha, l.fecha_cierre, l.importe_liq, l.importe_debi,
               l.usuario AS liq_usuario, an.cae
          FROM aeda.dbo.adm_pasivo p
          JOIN aeda.dbo.adm_agentes a ON a.age_id = p.age_id AND a.tipo_id = 1
          LEFT JOIN aeda.dbo.mse_expedientes e ON e.exp_id = p.exp_id AND p.exp_id > 0
          LEFT JOIN aeda.dbo.pres_liquida l ON l.exp_id = p.exp_id AND p.exp_id > 0
          LEFT JOIN aeda.dbo.mse_anexos an ON an.exp_id = p.exp_id AND p.exp_id > 0""",
    "items": """
        SELECT i.liqit_id, i.liq_id, i.importe, i.debito, g.descrip AS concepto
          FROM aeda.dbo.pres_liquidait i
          JOIN aeda.dbo.pres_liquida l ON l.liq_id = i.liq_id
          JOIN aeda.dbo.adm_pasivo p ON p.exp_id = l.exp_id AND p.exp_id > 0
          JOIN aeda.dbo.adm_agentes a ON a.age_id = p.age_id AND a.tipo_id = 1
          LEFT JOIN aeda.dbo.adm_cptogasto g ON g.conc_id = i.conc_id""",
    "pagos": """
        SELECT g.pago_id, g.pago_nro, g.tipo, g.fecha, g.importe, g.estado, g.age_id,
               CAST(g.obs AS varchar(500)) AS obs, g.usr
          FROM aeda.dbo.adm_pagos g
          JOIN aeda.dbo.adm_agentes a ON a.age_id = g.age_id AND a.tipo_id = 1""",
    "aplicaciones": """
        SELECT x.aplicacion_id, x.age_id, x.comp_id, x.tipo_aplic, x.aplica_id, x.fecha,
               x.aplicado, x.usuario, x.estado
          FROM aeda.dbo.adm_pasivoAplic x
          JOIN aeda.dbo.adm_agentes a ON a.age_id = x.age_id AND a.tipo_id = 1""",
    "retenciones": """
        SELECT r.certif_Nro AS certificado, r.fecha, r.pago_id, r.pago_nro, r.base_ret,
               r.retencion, r.age_id, r.tasa, r.status
          FROM aeda.dbo.adm_retgan r
          JOIN aeda.dbo.adm_agentes a ON a.age_id = r.age_id AND a.tipo_id = 1""",
    # La copia de Mis Comprobantes que guarda AEDA: tipo con letra e importes.
    "comprobafip": """
        SELECT cuit, prefijo, numero, cae, tipo, netogra, nogra, exento, iva, importe
          FROM aeda.dbo.adm_comprobafip""",
}


def leer_aeda(cn) -> dict:
    cur = cn.cursor()
    datos = {k: _filas(cur, sql) for k, sql in SQL_AEDA.items()}
    cur.close()
    return datos


# ─────────────────────────────────────────────────────────────────────────────
# Lectura del destino
# ─────────────────────────────────────────────────────────────────────────────

def _existe(cur, tabla) -> bool:
    cur.execute("SELECT COUNT(*) AS n FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = %s", (tabla,))
    return bool(cur.fetchone()["n"])


def leer_destino(cur, email_usuario: str | None) -> dict:
    for tabla, script in (("f_mis_comprobantes", "sql/comprobantes_20261107.sql"),
                          ("c_proveedores_movimientos", "sql/proveedores_20261107.sql")):
        if not _existe(cur, tabla):
            salir(f"Falta {tabla}. Correr antes {script}.")
    d = {}
    # La orden lleva el N° de AEDA como número visible (sql/pagos_20261108.sql
    # agrega la columna; sin ella, el número sigue estando en el pago).
    cur.execute("SELECT COUNT(*) AS n FROM information_schema.columns WHERE table_schema = DATABASE() "
                "AND table_name = 'pago_ordenes' AND column_name = 'nro_origen'")
    d["orden_nro_origen"] = bool(cur.fetchone()["n"])

    cur.execute("""SELECT p.id, p.cuit, p.razon_social, p.condicion_iva, rt.descripcion AS condicion_iva_txt,
                          p.ret_ganancias_codigo_sir, p.observaciones,
                          (SELECT cp.id_rubro_pasivo FROM c_proveedores_cuentas_pasivo cp
                            WHERE cp.id_proveedor = p.id AND cp.activa = 1
                            ORDER BY cp.predeterminada DESC, cp.id LIMIT 1) AS id_rubro,
                          (SELECT cg.id_concepto_gasto FROM c_proveedores_cuentas_gasto cg
                            WHERE cg.id_proveedor = p.id AND cg.activa = 1
                            ORDER BY cg.predeterminada DESC, cg.id LIMIT 1) AS id_concepto
                     FROM c_proveedores p
                     LEFT JOIN arca_responsable_tipo rt ON rt.codigo = p.condicion_iva""")
    d["por_prest"], d["por_cuit"], d["proveedores"] = {}, {}, {}
    for f in cur.fetchall():
        d["proveedores"][f["id"]] = f
        d["por_cuit"][solo_digitos(f["cuit"])] = f
        m = RE_PROV.match(f["observaciones"] or "")
        if m:
            d["por_prest"][int(m.group(1))] = f
    if not d["por_prest"]:
        salir("No hay proveedores importados de AEDA. Correr antes importar_aeda_proveedores.py --aplicar.")

    cur.execute("SELECT id, nombre FROM c_rubros_de_pasivo")
    rubros = {normalizar(f["nombre"]): f["id"] for f in cur.fetchall()}
    if "PROVEEDORES" not in rubros:
        salir("Falta el rubro de pasivo «Proveedores». Correr antes sql/proveedores_20261107.sql.")
    d["rubro_proveedores"] = rubros["PROVEEDORES"]

    cur.execute("SELECT id, descripcion, c_plan_de_cuentasId, c_especiesId, arca_tasa_ivaid "
                "FROM c_concepto_de_gastos")
    filas = cur.fetchall()
    d["conceptos"] = {normalizar(f["descripcion"]): f["id"] for f in filas}
    d["plantilla"] = next((f for f in filas if normalizar(f["descripcion"]) == CONCEPTO_PLANTILLA),
                          filas[0] if filas else None)

    cur.execute("SELECT codigo, descripcion FROM arca_tipo_comprobante")
    d["tipos"] = {f["codigo"]: f["descripcion"] for f in cur.fetchall()}

    cur.execute("SELECT cuit_emisor, tipo_comprobante, punto_de_venta, numero, importe_total "
                "FROM f_mis_comprobantes")
    d["mis"] = defaultdict(list)
    for f in cur.fetchall():
        d["mis"][(solo_digitos(f["cuit_emisor"]), _int(f["punto_de_venta"]), _int(f["numero"]))].append(f)

    # Comprobantes cargados (de AEDA o por la carga nueva), con su expediente
    # y su liquidación.
    cur.execute("""SELECT c.id AS id_comprobante, c.cuit_emisor, c.tipo_comprobante, c.punto_de_venta,
                          c.numero, c.importe_total, c.estado AS estado_cmp,
                          e.id AS id_exp, e.nro_expediente, e.asunto, e.estado, e.id_proveedor,
                          l.id AS id_liq, l.importe_liquidado, l.fecha_cierre
                     FROM f_comprobantes_arca c
                     LEFT JOIN me_expedientes e ON e.id_comprobante = c.id
                     LEFT JOIN c_pasivo_liquidacion l ON l.id_expediente = e.id""")
    d["exp_aeda"], d["nativos"], d["claves_cmp"] = {}, {}, set()
    for f in cur.fetchall():
        cuit, pv, nro = solo_digitos(f["cuit_emisor"]), _int(f["punto_de_venta"]), _int(f["numero"])
        d["claves_cmp"].add((cuit, str(f["tipo_comprobante"]).zfill(3), pv, nro))
        m = RE_EXP.match(f["asunto"] or "")
        if m:
            d["exp_aeda"][int(m.group(1))] = f
        elif f["estado_cmp"] != "anulado" and f["estado"] != "anulado":
            clase = "credito" if _es_credito(d["tipos"].get(str(f["tipo_comprobante"]).zfill(3))) else "debito"
            d["nativos"][(cuit, pv, nro, clase)] = f
    cur.execute("SELECT nro_expediente FROM me_expedientes")
    d["nros_exp"] = {f["nro_expediente"] for f in cur.fetchall()}

    cur.execute("""SELECT pp.id AS id_pago, pp.nro_pago, pp.estado, pp.importe_total,
                          o.id AS id_orden, o.nro_orden, o.clase, o.estado AS estado_orden
                     FROM pago_pagos pp JOIN pago_ordenes o ON o.id = pp.id_orden""")
    d["pagos_aeda"], d["nros_pago"] = {}, set()
    for f in cur.fetchall():
        d["nros_pago"].add(f["nro_pago"])
        m = RE_PAGO.match(f["nro_pago"] or "")
        if m:
            d["pagos_aeda"][int(m.group(1))] = f
    cur.execute("SELECT nro_orden FROM pago_ordenes")
    d["nros_orden"] = {f["nro_orden"] for f in cur.fetchall()}

    cur.execute("""SELECT id, id_liq_credito, id_pago, id_liq_debito, importe_aplicado, origen,
                          COALESCE(observaciones, '') AS observaciones
                     FROM c_pasivo_aplicacion""")
    d["aplic_aeda"], d["pares_nativos"] = [], set()
    for f in cur.fetchall():
        m = RE_APLIC.match(f["observaciones"])
        if f["origen"] == "migracion" and m:
            f["ids"] = sorted(int(x) for x in m.group(1).split(",") if x)
            d["aplic_aeda"].append(f)
        else:
            d["pares_nativos"].add(("P", f["id_pago"], f["id_liq_debito"]) if f["id_pago"]
                                   else ("C", f["id_liq_credito"], f["id_liq_debito"]))

    cur.execute("""SELECT d.id, d.id_orden, d.id_liquidacion, d.importe, o.nro_orden
                     FROM pago_ordenes_detalle d JOIN pago_ordenes o ON o.id = d.id_orden
                    WHERE o.nro_orden LIKE 'AEDA-OP-%'""")
    d["detalle_aeda"] = cur.fetchall()

    cur.execute("""SELECT id, id_pago, anulado, regimen, observaciones, id_certificado_emitido
                     FROM pago_retenciones WHERE observaciones LIKE '[AEDA adm_retgan %'""")
    d["ret_aeda"] = {int(RE_RET.match(f["observaciones"]).group(1)): f for f in cur.fetchall()
                     if RE_RET.match(f["observaciones"] or "")}
    cur.execute("SELECT nro_certificado FROM pago_retenciones_certificado")
    d["nros_cert"] = {f["nro_certificado"] for f in cur.fetchall()}

    cur.execute("""SELECT id FROM pago_imputaciones_config WHERE clase = 'anticipo' AND activo = 1
                    ORDER BY (subtipo IS NULL) DESC, id LIMIT 1""")
    d["id_imputacion"] = (cur.fetchone() or {}).get("id")

    d["escalas"] = {r["codigo"] for r in rg830.vigentes(cur) if r.get("tipo_calculo") == "escala"}
    d["institucion"] = cd.institucion(cur)

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


def _es_credito(descripcion) -> bool:
    return "NOTA DE CREDITO" in normalizar(descripcion)


# ─────────────────────────────────────────────────────────────────────────────
# Plan
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Plan:
    comprobantes: list[dict] = field(default_factory=list)      # nuevos
    usar_nativo: dict = field(default_factory=dict)              # comp_id → fila nativa
    anular_exp: list[dict] = field(default_factory=list)
    pagos: list[dict] = field(default_factory=list)              # nuevos
    anular_pagos: list[dict] = field(default_factory=list)
    aplicaciones: dict = field(default_factory=dict)             # clave → objetivo
    detalle: dict = field(default_factory=dict)                  # (pago_id, comp_id) → importe
    retenciones: list[dict] = field(default_factory=list)
    anular_ret: list[dict] = field(default_factory=list)
    completar_regimen: list[dict] = field(default_factory=list)
    conceptos_nuevos: list[str] = field(default_factory=list)
    saldos: dict = field(default_factory=dict)                   # id_proveedor → cuentas
    informe: list[dict] = field(default_factory=list)
    cuenta: dict = field(default_factory=dict)
    verificacion: list[dict] = field(default_factory=list)

    def contar(self, clave, n=1):
        self.cuenta[clave] = self.cuenta.get(clave, 0) + n

    def anotar(self, accion, **datos):
        self.informe.append({"accion": accion, **datos})

    def saldo(self, prov) -> dict:
        return self.saldos.setdefault(prov["id"], {
            "id_proveedor": prov["id"], "cuit": prov["cuit"], "razon": prov["razon_social"],
            "facturas": CERO, "creditos": CERO, "pagos": CERO, "anticipos": CERO,
            "no_importado": CERO})


def _tipo_arca(c, prov, destino, fip, plan) -> tuple[str, dict | None, str]:
    """El tipo ARCA del comprobante, la fila de adm_comprobafip si la hay (para
    los importes) y de dónde salió el tipo."""
    clase = c["_clase"]
    credito = clase == "nota de crédito"
    clave = (c["_cuit"], c["_pv"], c["_nro"])
    for m in destino["mis"].get(clave, []):
        cod = str(m["tipo_comprobante"]).zfill(3)
        if _es_credito(destino["tipos"].get(cod)) == credito:
            return cod, None, "Mis Comprobantes"
    candidatos = []
    for f in fip.get(clave, []):
        cod = solo_digitos(str(f["tipo"]).split("-")[0]).zfill(3)
        if cod in destino["tipos"] and _es_credito(destino["tipos"][cod]) == credito:
            candidatos.append((abs(_d(f["importe"]) - c["_total"]) > TOL, cod, f))
    if candidatos:
        candidatos.sort(key=lambda x: x[0])
        distinto, cod, f = candidatos[0]
        return cod, (None if distinto else f), "adm_comprobafip"
    cod = TIPO_POR_IVA[prov["condicion_iva"] == 1][clase]
    plan.contar("comprobantes con la letra deducida de la condición de IVA")
    return cod, None, "condición de IVA"


def _periodo(c) -> tuple[date, date]:
    t = solo_digitos(c["periodo"])
    if len(t) == 6 and 1 <= int(t[4:]) <= 12:
        a, m = int(t[:4]), int(t[4:])
    else:
        a, m = c["_fecha"].year, c["_fecha"].month
    return date(a, m, 1), date(a, m, calendar.monthrange(a, m)[1])


def _nro_expediente(c, destino, usados) -> str:
    """El número de expediente de AEDA tal cual («000002303/26»): es lo que hizo
    gestion_adm con los que migró del sistema viejo, y es el que figura en los
    papeles. Lo importado se reconoce por el asunto («[AEDA adm_pasivo N]»), no
    por el número, así que el formato se puede cambiar sin duplicar nada."""
    nro = limpio(c["exp_nro"]) or f"AEDA-EXP-{c['exp_id'] or c['comp_id']}"
    if nro in destino["nros_exp"] or nro in usados:
        nro = f"{nro}-{c['comp_id']}"
    usados.add(nro)
    return nro[:30]


def armar_comprobantes(aeda, destino, plan, agente_prov) -> dict:
    """Devuelve comp_id → comprobante de AEDA importable (nuevo, ya importado o
    cargado en el sindicato): lo que las aplicaciones pueden usar."""
    fip = defaultdict(list)
    for f in aeda["comprobafip"]:
        fip[(solo_digitos(f["cuit"]), _int(f["prefijo"]), _int(f["numero"]))].append(f)
    items = defaultdict(list)
    for i in aeda["items"]:
        items[i["liq_id"]].append(i)
    usados, validos = set(), {}

    for c in sorted(aeda["comprobantes"], key=lambda x: x["comp_id"]):
        cid = c["comp_id"]
        prov = agente_prov.get(c["age_id"])
        estado = limpio(c["estado"]).upper()
        clase = TCOMP_DEBITO.get(c["tcomp_id"]) or TCOMP_CREDITO.get(c["tcomp_id"])
        c.update(_clase=clase, _total=_d(c["importe"]), _fecha=_dia(c["fecha"]),
                 _pv=_int(c["prefijo"]), _nro=_int(c["numero"]))
        ya = destino["exp_aeda"].get(cid)

        if estado != "A":
            if ya and ya["estado"] != "anulado":
                plan.anular_exp.append(ya)
                plan.contar("expedientes anulados en AEDA después de importados (se anulan)")
                plan.anotar("anular expediente", aeda=f"adm_pasivo {cid}", nro=ya["nro_expediente"],
                            proveedor=prov["razon_social"] if prov else "", importe=c["_total"],
                            nota="anulado en AEDA")
            else:
                plan.contar("comprobantes anulados en AEDA (no se importan)")
            continue
        if not prov:
            plan.contar("comprobantes de un proveedor que no está en el sindicato (no se importan)")
            plan.anotar("omitido", aeda=f"adm_pasivo {cid}", importe=c["_total"],
                        nota=f"el agente {c['age_id']} no tiene proveedor importado")
            continue
        if not clase:
            plan.contar(f"comprobantes de tipo {c['tcomp_id']} de AEDA (no se importan)")
            plan.anotar("omitido", aeda=f"adm_pasivo {cid}", proveedor=prov["razon_social"],
                        importe=c["_total"], nota=f"tipo de comprobante {c['tcomp_id']} sin equivalente")
            plan.saldo(prov)["no_importado"] += c["_total"]
            continue
        c["_cuit"] = solo_digitos(prov["cuit"])
        signo = -1 if clase == "nota de crédito" else 1
        s = plan.saldo(prov)

        if ya:
            if ya["estado"] == "anulado":
                plan.contar("ya importados pero anulados en el sindicato (quedan así)")
                plan.anotar("aviso", aeda=f"adm_pasivo {cid}", nro=ya["nro_expediente"],
                            proveedor=prov["razon_social"], importe=c["_total"],
                            nota="activo en AEDA y anulado en el sindicato: no se toca")
                s["no_importado"] += c["_total"] * signo
                continue
            plan.contar("comprobantes ya importados")
            if ya["importe_liquidado"] is not None and abs(abs(_d(ya["importe_liquidado"])) - c["_total"]) > TOL:
                # No se pisa: el control de saldos lo va a mostrar.
                plan.contar("ya importados con otro importe en AEDA (no se pisa)")
                plan.anotar("aviso", aeda=f"adm_pasivo {cid}", nro=ya["nro_expediente"],
                            proveedor=prov["razon_social"], importe=c["_total"],
                            nota=f"en el sindicato es {_pesos(abs(_d(ya['importe_liquidado'])))}")
            validos[cid] = {**c, "_prov": prov, "_id_exp": ya["id_exp"], "_id_liq": ya["id_liq"],
                            "_signo": signo, "_existente": True}
            s["creditos" if signo < 0 else "facturas"] += c["_total"]
            continue

        nativo = destino["nativos"].get((c["_cuit"], c["_pv"], c["_nro"],
                                         "credito" if signo < 0 else "debito"))
        if nativo:
            plan.usar_nativo[cid] = nativo
            plan.contar("comprobantes que ya entraron por la carga del sindicato (se usa ese)")
            plan.anotar("usar cargado", aeda=f"adm_pasivo {cid}", nro=nativo["nro_expediente"],
                        proveedor=prov["razon_social"], importe=c["_total"],
                        nota="liquidación " + ("cerrada" if nativo["fecha_cierre"] else
                                               "ABIERTA: no es deuda hasta que se audite"))
            s["no_importado"] += c["_total"] * signo
            if nativo["id_liq"]:
                validos[cid] = {**c, "_prov": prov, "_id_exp": nativo["id_exp"],
                                "_id_liq": nativo["id_liq"], "_signo": signo, "_existente": True}
            continue

        tipo, fila_fip, origen_tipo = _tipo_arca(c, prov, destino, fip, plan)
        if (c["_cuit"], tipo, c["_pv"], c["_nro"]) in destino["claves_cmp"]:
            plan.contar("comprobantes que chocan con uno anulado en el sindicato (no se importan)")
            plan.anotar("omitido", aeda=f"adm_pasivo {cid}", proveedor=prov["razon_social"],
                        importe=c["_total"], nota=f"ya hay un {tipo} {c['_pv']}-{c['_nro']} anulado")
            s["no_importado"] += c["_total"] * signo
            continue
        destino["claves_cmp"].add((c["_cuit"], tipo, c["_pv"], c["_nro"]))

        desde, hasta = _periodo(c)
        imp = {"importe_neto_gravado": c["_total"], "importe_neto_no_grav": CERO,
               "importe_exento": CERO, "importe_iva": CERO, "importe_otros": CERO}
        if fila_fip:
            imp = {"importe_neto_gravado": _d(fila_fip["netogra"]), "importe_neto_no_grav": _d(fila_fip["nogra"]),
                   "importe_exento": _d(fila_fip["exento"]), "importe_iva": _d(fila_fip["iva"]),
                   "importe_otros": CERO}
            # AEDA guardó el neto de las facturas A pero no el IVA, y de las B y C
            # solo el total: lo que falta para el total va donde corresponde.
            resto = c["_total"] - sum(imp.values())
            if resto:
                if not imp["importe_neto_gravado"] and not imp["importe_iva"]:
                    clave = "importe_neto_gravado"
                elif not imp["importe_iva"]:
                    clave = "importe_iva"
                else:
                    clave = "importe_otros"
                imp[clave] += resto
        cae = solo_digitos(c["cae"])
        renglones = items.get(c["liq_id"], [])
        if renglones and abs(sum(_d(i["importe"]) for i in renglones) - c["_total"]) > TOL:
            renglones = [{"liqit_id": None, "importe": c["_total"], "debito": 0,
                          "concepto": renglones[0]["concepto"]}]
        for i in renglones:
            conc = limpio(i["concepto"])
            if conc and normalizar(conc) not in destino["conceptos"] and conc not in plan.conceptos_nuevos:
                plan.conceptos_nuevos.append(conc)
        nuevo = {
            **c, "_prov": prov, "_signo": signo, "_tipo": tipo, "_origen_tipo": origen_tipo,
            "_nro_exp": _nro_expediente(c, destino, usados), "_desde": desde, "_hasta": hasta,
            "_importes": imp, "_cae": cae if len(cae) == 14 else None, "_items": renglones,
            "_cierre": _dia(c["fecha_cierre"] or c["liq_fecha"] or c["fecha"]),
            "_exp_fecha": _ahora(c["exp_fecha"] or c["fecha"]),
        }
        plan.comprobantes.append(nuevo)
        validos[cid] = {**nuevo, "_existente": False}
        s["creditos" if signo < 0 else "facturas"] += c["_total"]
        plan.contar(f"{PLURAL[clase]} a importar")
        plan.anotar("crear comprobante", aeda=f"adm_pasivo {cid}", nro=nuevo["_nro_exp"],
                    proveedor=prov["razon_social"], fecha=c["_fecha"],
                    comprobante=f"{destino['tipos'].get(tipo, tipo)} {str(c['_pv']).zfill(5)}-{str(c['_nro']).zfill(8)}",
                    importe=c["_total"] * signo,
                    nota=f"tipo según {origen_tipo}" + ("" if nuevo["_cae"] else "; sin CAE"))
    return validos


def armar_pagos(aeda, destino, plan, agente_prov) -> dict:
    """pago_id → pago de AEDA importable (nuevo o ya importado)."""
    validos = {}
    for g in sorted(aeda["pagos"], key=lambda x: x["pago_id"]):
        pid = g["pago_id"]
        tipo, estado = limpio(g["tipo"]).upper(), limpio(g["estado"]).upper()
        prov = agente_prov.get(g["age_id"])
        g.update(_tipo=tipo, _importe=_d(g["importe"]), _fecha=_dia(g["fecha"]), _prov=prov)
        ya = destino["pagos_aeda"].get(pid)
        if tipo not in TIPOS_PAGO:
            plan.contar(f"pagos de tipo {tipo or '?'} de AEDA (no se importan)")
            continue
        if estado not in ESTADOS_PAGO_VALIDOS:
            if ya and ya["estado"] != "anulado":
                plan.anular_pagos.append(ya)
                plan.contar("pagos anulados en AEDA después de importados (se anulan)")
                plan.anotar("anular pago", aeda=f"adm_pagos {pid}", nro=ya["nro_pago"],
                            proveedor=prov["razon_social"] if prov else "", importe=g["_importe"],
                            nota="anulado en AEDA")
            else:
                plan.contar(f"{TIPOS_PAGO[tipo]}s anulados en AEDA (no se importan)")
            continue
        if not prov:
            plan.contar("pagos a un proveedor que no está en el sindicato (no se importan)")
            plan.anotar("omitido", aeda=f"adm_pagos {pid}", importe=g["_importe"],
                        nota=f"el agente {g['age_id']} no tiene proveedor importado")
            continue
        s = plan.saldo(prov)
        if ya:
            if ya["estado"] == "anulado":
                plan.contar("pagos activos en AEDA y anulados en el sindicato (quedan así)")
                plan.anotar("aviso", aeda=f"adm_pagos {pid}", nro=ya["nro_pago"],
                            proveedor=prov["razon_social"], importe=g["_importe"],
                            nota="activo en AEDA y anulado en el sindicato: no se toca")
                s["no_importado"] -= g["_importe"]
                continue
            if abs(_d(ya["importe_total"]) - g["_importe"]) > TOL:
                plan.contar("pagos ya importados con otro importe en AEDA (no se pisa)")
                plan.anotar("aviso", aeda=f"adm_pagos {pid}", nro=ya["nro_pago"],
                            proveedor=prov["razon_social"], importe=g["_importe"],
                            nota=f"en el sindicato es {_pesos(_d(ya['importe_total']))}")
            plan.contar("pagos y anticipos ya importados")
            validos[pid] = {**g, "_existente": True, "_clase": ya["clase"],
                            "_id_pago": ya["id_pago"], "_id_orden": ya["id_orden"]}
        elif f"AEDA-OP-{pid}" in destino["nros_orden"] or f"AEDA-PG-{pid}" in destino["nros_pago"]:
            plan.contar("pagos con el número de orden ya usado y sin su pago (se saltean)")
            plan.anotar("omitido", aeda=f"adm_pagos {pid}", proveedor=prov["razon_social"],
                        importe=g["_importe"], nota=f"ya hay una orden AEDA-OP-{pid} sin el pago AEDA-PG-{pid}")
            s["no_importado"] -= g["_importe"]
            continue
        else:
            validos[pid] = {**g, "_existente": False}
            if estado == "R":
                plan.anotar("aviso", aeda=f"adm_pagos {pid}", proveedor=prov["razon_social"],
                            importe=g["_importe"], nota="en AEDA está en estado R: entra como pago")
        s["anticipos" if tipo == "A" else "pagos"] += g["_importe"]
    return validos


def armar_aplicaciones(aeda, plan, comps, pagos):
    """Las aplicaciones activas de AEDA, corregidas y agrupadas por par."""
    activas = [dict(x, _aplicado=_d(x["aplicado"]), _tipo=limpio(x["tipo_aplic"]).upper())
               for x in aeda["aplicaciones"] if limpio(x["estado"]).upper() == "A"]
    aplicado = defaultdict(Decimal)
    por_pago = defaultdict(list)
    for x in activas:
        if x["_tipo"] == "P":
            aplicado[x["aplica_id"]] += x["_aplicado"]
            por_pago[x["aplica_id"]].append(x)

    # Aplicaciones a un pago por más de lo pagado: si el sobrante es justo lo
    # que le falta aplicar a UN solo pago del mismo proveedor, era de ese.
    for pid, total in list(aplicado.items()):
        g = pagos.get(pid)
        if not g or total - g["_importe"] <= TOL:
            continue
        exceso = total - g["_importe"]
        resuelto = False
        for x in sorted(por_pago[pid], key=lambda a: -a["aplicacion_id"]):
            if abs(x["_aplicado"] - exceso) > TOL:
                continue
            cands = [o for o in pagos.values()
                     if o["pago_id"] != pid and o["age_id"] == g["age_id"] and o["_tipo"] == g["_tipo"]
                     and abs(o["_importe"] - aplicado.get(o["pago_id"], CERO) - x["_aplicado"]) <= TOL]
            if len(cands) == 1:
                nuevo = cands[0]["pago_id"]
                x["aplica_id"] = nuevo
                aplicado[pid] -= x["_aplicado"]
                aplicado[nuevo] += x["_aplicado"]
                plan.contar("aplicaciones de AEDA pasadas al pago que correspondía")
                plan.anotar("corregir aplicación", aeda=f"adm_pasivoAplic {x['aplicacion_id']}",
                            proveedor=g["_prov"]["razon_social"] if g["_prov"] else "",
                            importe=x["_aplicado"],
                            nota=f"en AEDA aplicada al pago {g['pago_nro']}, que ya estaba aplicado "
                                 f"entero; pasa al {cands[0]['pago_nro']}, el único sin aplicar por ese importe")
                resuelto = True
                break
        if not resuelto:
            plan.contar("pagos aplicados por más de lo pagado (quedan así)")
            plan.anotar("aviso", aeda=f"adm_pagos {pid}",
                        proveedor=g["_prov"]["razon_social"] if g["_prov"] else "", importe=exceso,
                        nota=f"el pago {g['pago_nro']} está aplicado por {_pesos(total)}")

    objetivos = {}
    for x in activas:
        deb = comps.get(x["comp_id"])
        if x["_tipo"] == "P":
            origen = pagos.get(x["aplica_id"])
        elif x["_tipo"] == "C":
            origen = comps.get(x["aplica_id"])
        else:
            plan.contar(f"aplicaciones de tipo {x['_tipo']} (no se importan)")
            continue
        if not deb or not origen or deb["_signo"] < 0 or (x["_tipo"] == "C" and origen["_signo"] > 0):
            plan.contar("aplicaciones a algo que no se importa (se saltean)")
            continue
        clave = (x["_tipo"], x["aplica_id"], x["comp_id"])
        o = objetivos.setdefault(clave, {"importe": CERO, "ids": [], "fecha": None})
        o["importe"] += x["_aplicado"]
        o["ids"].append(x["aplicacion_id"])
        f = _dia(x["fecha"])
        o["fecha"] = max(o["fecha"], f) if o["fecha"] and f else (o["fecha"] or f)
    plan.aplicaciones = objetivos

    por_factura = defaultdict(Decimal)
    for (t, _, comp), o in objetivos.items():
        por_factura[comp] += o["importe"]
    for comp, total in por_factura.items():
        if total - comps[comp]["_total"] > TOL:
            plan.contar("facturas aplicadas por más de su importe")
            plan.anotar("aviso", aeda=f"adm_pasivo {comp}", proveedor=comps[comp]["_prov"]["razon_social"],
                        importe=total, nota=f"la factura es de {_pesos(comps[comp]['_total'])}")

    # Las órdenes de pago P: qué pagó cada una (pago_ordenes_detalle).
    plan.detalle = {(pid, comp): o["importe"] for (t, pid, comp), o in objetivos.items() if t == "P"}
    con_facturas = {pid for (pid, _) in plan.detalle}
    for g in pagos.values():
        if not g["_existente"]:
            g["_clase"] = "proveedor" if g["_tipo"] == "P" and g["pago_id"] in con_facturas else "anticipo"
            if g["_tipo"] == "P" and g["_clase"] == "anticipo":
                plan.contar("pagos sin factura aplicada (entran como pago a cuenta)")
                plan.anotar("aviso", aeda=f"adm_pagos {g['pago_id']}", proveedor=g["_prov"]["razon_social"],
                            importe=g["_importe"],
                            nota=f"el pago {g['pago_nro']} no cancela ninguna factura activa: pago a cuenta")
            plan.pagos.append(g)
            plan.contar(f"{'anticipos' if g['_clase'] == 'anticipo' else 'pagos'} a importar")
            plan.anotar("crear pago", aeda=f"adm_pagos {g['pago_id']}", nro=f"AEDA-PG-{g['pago_id']}",
                        proveedor=g["_prov"]["razon_social"], fecha=g["_fecha"], importe=g["_importe"],
                        comprobante=f"{TIPOS_PAGO[g['_tipo']]} {g['pago_nro']}", nota=limpio(g["obs"])[:120])


def armar_retenciones(aeda, destino, plan, pagos, comps):
    for r in sorted(aeda["retenciones"], key=lambda x: x["certificado"]):
        n = r["certificado"]
        ya = destino["ret_aeda"].get(n)
        g = pagos.get(r["pago_id"])
        vale = limpio(r["status"]).upper() == "E" and g is not None
        if not vale:
            if ya and not ya["anulado"]:
                plan.anular_ret.append(ya)
                plan.contar("retenciones anuladas en AEDA después de importadas (se anulan)")
            elif limpio(r["status"]).upper() == "E":
                plan.contar("retenciones de un pago que no se importa (se saltean)")
            continue
        prov = g["_prov"]
        regimen = rg830.normalizar_regimen(prov["ret_ganancias_codigo_sir"]) or None
        if ya:
            if not ya["regimen"] and regimen:
                plan.completar_regimen.append({**ya, "regimen": regimen})
                plan.contar("retenciones a las que se les completa el régimen")
            continue
        if f"AEDA-CRT-{n}" in destino["nros_cert"]:
            plan.contar("certificados con el número ya usado (se saltean)")
            continue
        # El comprobante del certificado: la factura que cancela el pago, si es
        # una sola. Un anticipo se retuvo antes de la factura: va la orden de pago.
        facturas = [comp for (pid, comp) in plan.detalle if pid == g["pago_id"]] if g["_tipo"] == "P" else []
        r.update(_pago=g, _prov=prov, _regimen=regimen, _fecha=_dia(r["fecha"]),
                 _comp=comps.get(facturas[0]) if len(facturas) == 1 else None)
        plan.retenciones.append(r)
        plan.contar("retenciones a importar")
        if not regimen:
            plan.contar("retenciones sin régimen en la ficha del proveedor")
            plan.anotar("aviso", aeda=f"adm_retgan {n}", proveedor=prov["razon_social"],
                        importe=_d(r["retencion"]),
                        nota="la ficha no tiene el régimen de Ganancias: entra sin régimen")


def armar_plan(aeda: dict, destino: dict) -> Plan:
    plan = Plan()
    agente_prov = {}
    for a in aeda["agentes"]:
        prov = destino["por_prest"].get(a["prest_id"]) or destino["por_cuit"].get(solo_digitos(a["cuit"]))
        if prov:
            agente_prov[a["age_id"]] = prov
    plan.contar("proveedores de AEDA", len(aeda["agentes"]))
    plan.contar("proveedores de AEDA sin proveedor en el sindicato", len(aeda["agentes"]) - len(agente_prov))

    comps = armar_comprobantes(aeda, destino, plan, agente_prov)
    pagos = armar_pagos(aeda, destino, plan, agente_prov)
    armar_aplicaciones(aeda, plan, comps, pagos)
    armar_retenciones(aeda, destino, plan, pagos, comps)
    plan._comps, plan._pagos = comps, pagos

    if plan.conceptos_nuevos:
        plan.contar("conceptos de gasto de AEDA que se agregan al catálogo", len(plan.conceptos_nuevos))
        for c in plan.conceptos_nuevos:
            plan.anotar("concepto nuevo", nota=f"{c}, con la imputación de {CONCEPTO_PLANTILLA}")
    return plan


# ─────────────────────────────────────────────────────────────────────────────
# Escritura
# ─────────────────────────────────────────────────────────────────────────────

def _imputacion_anticipo(cur, destino) -> int:
    if destino["id_imputacion"]:
        return destino["id_imputacion"]
    cur.execute("""INSERT INTO pago_imputaciones_config (clase, subtipo, nombre, activo, observaciones)
                   VALUES ('anticipo', NULL, 'Anticipo a proveedores', 1, %s)""",
                ("Creada por importar_aeda_cc_proveedores.py para los anticipos de AEDA. "
                 "Falta la imputación contable (cuentas debe y haber).",))
    destino["id_imputacion"] = cur.lastrowid
    return destino["id_imputacion"]


def _crear_comprobante(cur, c, destino, conceptos, usuario) -> tuple[int, int]:
    prov, inst = c["_prov"], destino["institucion"]
    imp = c["_importes"]
    cur.execute("""
        INSERT INTO f_comprobantes_arca
          (id_proveedor, cuit_emisor, razon_social_emisor, condicion_iva_emisor,
           cuit_receptor, razon_social_receptor, tipo_comprobante, punto_de_venta, numero,
           fecha_emision, fecha_vto_pago, periodo_desde, periodo_hasta,
           importe_neto_gravado, importe_neto_no_grav, importe_exento, importe_iva, importe_otros,
           importe_total, moneda, tipo_de_cambio, cae, estado, fecha_carga, usuario_id)
        VALUES (%s,%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s,%s,%s, %s,'PES',1,%s,'liquidado',%s,%s)
    """, (prov["id"], c["_cuit"], prov["razon_social"][:200], prov["condicion_iva_txt"],
          inst["cuit"] or None, inst["nombre"][:200] or None, c["_tipo"],
          str(c["_pv"]).zfill(5), str(c["_nro"]).zfill(8),
          c["_fecha"], _dia(c["vence"]), c["_desde"], c["_hasta"],
          imp["importe_neto_gravado"], imp["importe_neto_no_grav"], imp["importe_exento"],
          imp["importe_iva"], imp["importe_otros"], c["_total"], c["_cae"], c["_exp_fecha"], usuario))
    id_cmp = cur.lastrowid

    caratula = limpio(c["caratula"])
    asunto = (f"[AEDA adm_pasivo {c['comp_id']}] Expediente {limpio(c['exp_nro']) or '—'} de AEDA"
              + (f": {caratula}" if caratula else ""))
    cur.execute("""
        INSERT INTO me_expedientes
          (nro_expediente, anio, id_comprobante, id_proveedor, cuit_emisor, razon_social_emisor,
           importe_total, moneda, estado, asunto, creado, usuario_creacion)
        VALUES (%s,%s,%s,%s,%s,%s,%s,'PES','liquidado',%s,%s,%s)
    """, (c["_nro_exp"], c["_exp_fecha"].year, id_cmp, prov["id"], c["_cuit"], prov["razon_social"][:200],
          c["_total"], asunto[:500], c["_exp_fecha"], usuario))
    id_exp = cur.lastrowid
    quien = limpio(c["exp_usuario"])
    cur.execute("""INSERT INTO me_expediente_movimientos
                     (id_expediente, tipo, estado_resultante, usuario_id, observaciones, fecha)
                   VALUES (%s, 'ingreso', 'ingresado', %s, %s, %s)""",
                (id_exp, usuario, f"Ingresado en AEDA{' por ' + quien if quien else ''} "
                                  f"(expediente {limpio(c['exp_nro']) or '—'}).", c["_exp_fecha"]))

    total = c["_total"] * c["_signo"]
    rubro = prov["id_rubro"] or destino["rubro_proveedores"]
    liquido = limpio(c["liq_usuario"])
    cur.execute("""INSERT INTO c_pasivo_liquidacion
                     (creado, fecha_cierre, periodo, importe_liquidado, importe_debitado, comentario,
                      id_expediente, id_usuario, id_rubro_pasivo)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (_ahora(c["liq_fecha"]) or c["_exp_fecha"], c["_cierre"], c["_desde"].strftime("%Y%m"),
                 total, _d(c["importe_debi"]),
                 f"[AEDA pres_liquida {c['liq_id']}] Liquidado en AEDA"
                 + (f" por {liquido}" if liquido else "") + f" el {c['_cierre']:%d/%m/%Y}.",
                 id_exp, usuario, rubro))
    id_liq = cur.lastrowid
    renglones = c["_items"] or [{"liqit_id": None, "importe": c["_total"], "debito": 0, "concepto": None}]
    for i in renglones:
        conc = limpio(i["concepto"])
        id_conc = (conceptos.get(normalizar(conc)) if conc else None) or prov["id_concepto"] \
            or destino["plantilla"]["id"]
        cur.execute("""INSERT INTO c_pasivo_liquidacion_detalle
                         (id_pasivo_liquidacion, id_rubro_pasivo, id_concepto_liquidacion,
                          importe_liquidado, importe_debitado, fecha_devengado, comentario, id_usuario)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (id_liq, rubro, id_conc, _d(i["importe"]) * c["_signo"], _d(i.get("debito")),
                     _ahora(c["_fecha"]),
                     (f"[AEDA pres_liquidait {i['liqit_id']}] " if i["liqit_id"] else "[AEDA] ")
                     + (conc or "sin concepto en AEDA"), usuario))
    cur.execute("""INSERT INTO me_expediente_movimientos
                     (id_expediente, tipo, estado_resultante, usuario_id, observaciones, fecha)
                   VALUES (%s, 'nota', 'liquidado', %s, %s, %s)""",
                (id_exp, usuario, f"Liquidado en AEDA{' por ' + liquido if liquido else ''}. "
                                  "Importado por importar_aeda_cc_proveedores.py.", _ahora(c["_cierre"])))
    return id_exp, id_liq


def _crear_pago(cur, g, destino, usuario) -> tuple[int, int]:
    prov = g["_prov"]
    obs = limpio(g["obs"])
    nota = (f"[AEDA adm_pagos {g['pago_id']}] {TIPOS_PAGO[g['_tipo']].capitalize()} {g['pago_nro']} de AEDA"
            + (f" ({limpio(g['usr'])})" if limpio(g["usr"]) else "") + (f". {obs}" if obs else "."))
    cur.execute("""INSERT INTO pago_ordenes
                     (nro_orden, clase, anio, periodo, fecha, estado, importe_total, moneda,
                      niveles_requeridos, niveles_aprobados, observaciones, id_usuario_creacion, creado)
                   VALUES (%s, %s, %s, %s, %s, 'pagada', %s, 'ARS', 1, 1, %s, %s, %s)""",
                (f"AEDA-OP-{g['pago_id']}", g["_clase"], g["_fecha"].year, g["_fecha"].strftime("%Y%m"),
                 g["_fecha"], g["_importe"], nota, usuario, _ahora(g["_fecha"])))
    id_orden = cur.lastrowid
    if destino.get("orden_nro_origen") and str(g["pago_nro"] or "").isdigit():
        cur.execute("UPDATE pago_ordenes SET nro_origen = %s WHERE id = %s", (int(g["pago_nro"]), id_orden))
    cur.execute("""INSERT INTO pago_pagos
                     (nro_pago, nro_origen, id_orden, fecha_pago, estado, importe_total, observaciones,
                      id_usuario_creacion, creado)
                   VALUES (%s, %s, %s, %s, 'emitido', %s, %s, %s, %s)""",
                (f"AEDA-PG-{g['pago_id']}", g["pago_nro"], id_orden, g["_fecha"], g["_importe"], nota,
                 usuario, _ahora(g["_fecha"])))
    id_pago = cur.lastrowid
    if g["_clase"] == "anticipo":
        desc = obs or f"Anticipo {g['pago_nro']}"
        if g["_tipo"] == "P":
            desc = f"Pago a cuenta {g['pago_nro']}" + (f": {obs}" if obs else "")
        cur.execute("""INSERT INTO pago_ordenes_anticipo_det
                         (id_orden, id_proveedor, id_imputacion, id_rubro_pasivo, descripcion, importe, moneda)
                       VALUES (%s, %s, %s, %s, %s, %s, 'ARS')""",
                    (id_orden, prov["id"], _imputacion_anticipo(cur, destino),
                     prov["id_rubro"] or destino["rubro_proveedores"], desc[:200], g["_importe"]))
    return id_orden, id_pago


def _reconciliar_aplicaciones(cur, plan, destino, liq_de, pago_de, usuario) -> None:
    """Las aplicaciones de AEDA quedan iguales a las de AEDA: se agregan las
    nuevas, se corrigen las que cambiaron y se sacan las que AEDA ya no tiene."""
    comp_de_liq = {v: k for k, v in liq_de.items()}
    pagoaeda_de = {v[1]: k for k, v in pago_de.items()}
    existentes = {}
    for f in destino["aplic_aeda"]:
        if f["id_pago"]:
            clave = ("P", pagoaeda_de.get(f["id_pago"]), comp_de_liq.get(f["id_liq_debito"]))
        else:
            clave = ("C", comp_de_liq.get(f["id_liq_credito"]), comp_de_liq.get(f["id_liq_debito"]))
        if None in clave or clave in existentes:
            # No se reconoce de dónde vino, o es una repetida: se saca y se
            # vuelve a armar desde AEDA.
            cur.execute("DELETE FROM c_pasivo_aplicacion WHERE id = %s", (f["id"],))
            plan.contar("aplicaciones importadas que no se reconocen (se rehacen)")
            continue
        existentes[clave] = f

    for clave, o in plan.aplicaciones.items():
        tipo, origen, comp = clave
        obs = f"[AEDA adm_pasivoAplic {','.join(str(i) for i in sorted(o['ids']))}]"
        if len(obs) > 255:
            obs = obs[:250].rsplit(",", 1)[0] + "…]"
        id_deb = liq_de[comp]
        f = existentes.pop(clave, None)
        if f:
            if abs(_d(f["importe_aplicado"]) - o["importe"]) > TOL or f["ids"] != sorted(o["ids"]):
                cur.execute("UPDATE c_pasivo_aplicacion SET importe_aplicado = %s, observaciones = %s "
                            "WHERE id = %s", (o["importe"], obs, f["id"]))
                plan.contar("aplicaciones que cambiaron en AEDA (se corrigen)")
            continue
        if tipo == "P":
            id_pago, id_cred = pago_de[origen][1], None
            par = ("P", id_pago, id_deb)
        else:
            id_pago, id_cred = None, liq_de[origen]
            par = ("C", id_cred, id_deb)
        if par in destino["pares_nativos"]:
            plan.contar("aplicaciones que ya estaban cargadas a mano (se saltean)")
            continue
        cur.execute("""INSERT INTO c_pasivo_aplicacion
                         (id_liq_credito, id_pago, id_liq_debito, importe_aplicado, fecha, origen,
                          observaciones, id_usuario)
                       VALUES (%s, %s, %s, %s, %s, 'migracion', %s, %s)""",
                    (id_cred, id_pago, id_deb, o["importe"], o["fecha"] or date.today(), obs, usuario))
        plan.contar("aplicaciones nuevas")
    for f in existentes.values():
        cur.execute("DELETE FROM c_pasivo_aplicacion WHERE id = %s", (f["id"],))
        plan.contar("aplicaciones que AEDA ya no tiene (se sacan)")


def _reconciliar_detalle(cur, plan, destino, exp_de, liq_de, pago_de) -> None:
    comp_de_liq = {v: k for k, v in liq_de.items()}
    existentes = {}
    for f in destino["detalle_aeda"]:
        clave = (int(RE_ORDEN.match(f["nro_orden"]).group(1)), comp_de_liq.get(f["id_liquidacion"]))
        if clave[1] is None or clave in existentes:
            cur.execute("DELETE FROM pago_ordenes_detalle WHERE id = %s", (f["id"],))
            continue
        existentes[clave] = f
    for (pid, comp), importe in plan.detalle.items():
        if pid not in pago_de or plan._pagos[pid]["_clase"] != "proveedor":
            continue
        f = existentes.pop((pid, comp), None)
        if f:
            if abs(_d(f["importe"]) - importe) > TOL:
                cur.execute("UPDATE pago_ordenes_detalle SET importe = %s WHERE id = %s", (importe, f["id"]))
            continue
        cur.execute("""INSERT INTO pago_ordenes_detalle (id_orden, id_expediente, id_liquidacion, importe, moneda)
                       VALUES (%s, %s, %s, %s, 'ARS')""", (pago_de[pid][0], exp_de[comp], liq_de[comp], importe))
    for f in existentes.values():
        cur.execute("DELETE FROM pago_ordenes_detalle WHERE id = %s", (f["id"],))


def _crear_retencion(cur, r, destino, pago_de, exp_de, usuario) -> None:
    g, prov = r["_pago"], r["_prov"]
    id_orden, id_pago = pago_de[g["pago_id"]]
    n, regimen = r["certificado"], r["_regimen"]
    c = r["_comp"]
    if c:
        cmp_tipo = TIPO_CERTIFICADO["recibo" if c.get("_tipo") == "015" else c["_clase"]]
        cmp = (cmp_tipo, c["_pv"], c["_nro"], c["_fecha"], c["_total"], c.get("_cae") or solo_digitos(c["cae"]) or None)
    else:
        cmp = (6, None, g["pago_nro"], g["_fecha"], g["_importe"], None)
    nota = f"[AEDA adm_retgan {n}] Certificado {n} de AEDA, pago {r['pago_nro'] or g['pago_nro']}."
    cur.execute("""INSERT INTO pago_retenciones_certificado
                     (nro_certificado, tipo, codigo_regimen, formulario_sire, id_pago, id_orden, id_proveedor,
                      cuit_proveedor, razon_social_proveedor, condicion_fiscal, fecha_emision, periodo_fiscal,
                      base_calculo, alicuota, importe_retenido, comprobante_tipo, comprobante_pv,
                      comprobante_nro, comprobante_fecha, comprobante_importe, comprobante_cae,
                      estado, observaciones, id_usuario_creacion)
                   VALUES (%s, 'GANANCIAS', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s, %s, 'emitido', %s, %s)""",
                (f"AEDA-CRT-{n}", regimen, FORMULARIO_SIRE, id_pago, id_orden, prov["id"],
                 solo_digitos(prov["cuit"]), prov["razon_social"][:200], (prov["condicion_iva_txt"] or "")[:30] or None,
                 r["_fecha"], r["_fecha"].strftime("%Y%m"), _d(r["base_ret"]), _d(r["tasa"]),
                 _d(r["retencion"]), *cmp, nota, usuario))
    id_cert = cur.lastrowid
    cur.execute("""INSERT INTO pago_retenciones
                     (id_pago, id_orden, id_expediente, id_proveedor, tipo, regimen, base_calculo, alicuota,
                      importe, origen_alicuota, id_certificado, id_certificado_emitido, fecha, id_usuario,
                      observaciones)
                   VALUES (%s, %s, %s, %s, 'GANANCIAS', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (id_pago, id_orden, exp_de.get(c["comp_id"]) if c else None, prov["id"], regimen,
                 _d(r["base_ret"]), _d(r["tasa"]), _d(r["retencion"]),
                 "escala" if regimen in destino["escalas"] else "proveedor",
                 id_cert, id_cert, r["_fecha"], usuario, nota))


def aplicar(cur, plan: Plan, destino: dict) -> None:
    usuario = destino["usuario"]["id"]
    conceptos = dict(destino["conceptos"])
    base = destino["plantilla"]
    for desc in plan.conceptos_nuevos:
        cur.execute("""INSERT INTO c_concepto_de_gastos
                           (descripcion, c_plan_de_cuentasId, c_especiesId, arca_tasa_ivaid, esliquidacion)
                       VALUES (%s, %s, %s, %s, 0)""",
                    (desc[:50], base["c_plan_de_cuentasId"], base["c_especiesId"], base["arca_tasa_ivaid"]))
        conceptos[normalizar(desc)] = cur.lastrowid

    # comp_id de AEDA → expediente y liquidación del sindicato.
    exp_de, liq_de = {}, {}
    for cid, c in plan._comps.items():
        if c["_existente"]:
            exp_de[cid], liq_de[cid] = c["_id_exp"], c["_id_liq"]
    for f in destino["exp_aeda"].values():   # los anulados también: las aplicaciones viejas los nombran
        m = RE_EXP.match(f["asunto"])
        exp_de.setdefault(int(m.group(1)), f["id_exp"])
        if f["id_liq"]:
            liq_de.setdefault(int(m.group(1)), f["id_liq"])
    nuevos_cmp = []
    for c in plan.comprobantes:
        exp_de[c["comp_id"]], liq_de[c["comp_id"]] = _crear_comprobante(cur, c, destino, conceptos, usuario)
        nuevos_cmp.append(exp_de[c["comp_id"]])

    pago_de = {pid: (f["id_orden"], f["id_pago"]) for pid, f in destino["pagos_aeda"].items()}
    for g in plan.pagos:
        pago_de[g["pago_id"]] = _crear_pago(cur, g, destino, usuario)

    _reconciliar_aplicaciones(cur, plan, destino, liq_de, pago_de, usuario)
    _reconciliar_detalle(cur, plan, destino, exp_de, liq_de, pago_de)

    for r in plan.retenciones:
        _crear_retencion(cur, r, destino, pago_de, exp_de, usuario)
    for r in plan.completar_regimen:
        cur.execute("UPDATE pago_retenciones SET regimen = %s WHERE id = %s", (r["regimen"], r["id"]))
        if r["id_certificado_emitido"]:
            cur.execute("UPDATE pago_retenciones_certificado SET codigo_regimen = %s "
                        "WHERE id = %s AND codigo_regimen IS NULL", (r["regimen"], r["id_certificado_emitido"]))

    motivo = "Anulado en AEDA (importar_aeda_cc_proveedores.py)."
    for r in plan.anular_ret:
        cur.execute("UPDATE pago_retenciones SET anulado = 1, fecha_anulacion = NOW(), id_usuario_anulacion = %s "
                    "WHERE id = %s", (usuario, r["id"]))
        if r["id_certificado_emitido"]:
            cur.execute("UPDATE pago_retenciones_certificado SET estado = 'anulado', fecha_anulacion = NOW(), "
                        "id_usuario_anulacion = %s, motivo_anulacion = %s WHERE id = %s",
                        (usuario, motivo, r["id_certificado_emitido"]))
    for p in plan.anular_pagos:
        cur.execute("UPDATE pago_pagos SET estado = 'anulado', fecha_anulacion = NOW(), motivo_anulacion = %s, "
                    "id_usuario_anulacion = %s WHERE id = %s", (motivo, usuario, p["id_pago"]))
        cur.execute("UPDATE pago_ordenes SET estado = 'anulada' WHERE id = %s", (p["id_orden"],))
        cur.execute("UPDATE pago_retenciones SET anulado = 1, fecha_anulacion = NOW(), id_usuario_anulacion = %s "
                    "WHERE id_pago = %s AND anulado = 0", (usuario, p["id_pago"]))
        cur.execute("UPDATE pago_retenciones_certificado SET estado = 'anulado', fecha_anulacion = NOW(), "
                    "id_usuario_anulacion = %s, motivo_anulacion = %s WHERE id_pago = %s AND estado = 'emitido'",
                    (usuario, motivo, p["id_pago"]))
    for e in plan.anular_exp:
        cur.execute("UPDATE me_expedientes SET estado = 'anulado', motivo_anulacion = %s, fecha_anulacion = NOW(), "
                    "id_usuario_anulacion = %s WHERE id = %s", (motivo, usuario, e["id_exp"]))
        cur.execute("UPDATE f_comprobantes_arca SET estado = 'anulado' WHERE id = %s", (e["id_comprobante"],))
        cd.movimiento(cur, e["id_exp"], "anulacion", "anulado", usuario, motivo)

    # Pagado o liquidado, según lo que cancelan sus aplicaciones.
    cur.execute("""
        UPDATE me_expedientes e
          JOIN c_pasivo_liquidacion l ON l.id_expediente = e.id
          LEFT JOIN (SELECT id_liq_debito AS id, SUM(importe_aplicado) AS s
                       FROM c_pasivo_aplicacion GROUP BY id_liq_debito) d ON d.id = l.id
          LEFT JOIN (SELECT id_liq_credito AS id, SUM(importe_aplicado) AS s
                       FROM c_pasivo_aplicacion WHERE id_liq_credito IS NOT NULL
                      GROUP BY id_liq_credito) c ON c.id = l.id
           SET e.estado = IF(ABS(ABS(l.importe_liquidado)
                                 - COALESCE(IF(l.importe_liquidado >= 0, d.s, c.s), 0)) <= 0.01,
                             'pagado', 'liquidado')
         WHERE e.asunto LIKE '[AEDA adm_pasivo %' AND e.estado IN ('liquidado', 'pagado')
           AND l.fecha_cierre IS NOT NULL""")
    cur.execute("""UPDATE f_comprobantes_arca c JOIN me_expedientes e ON e.id_comprobante = c.id
                      SET c.estado = e.estado
                    WHERE e.asunto LIKE '[AEDA adm_pasivo %' AND c.estado <> e.estado""")

    # Lo que ARCA ya informó en Mis Comprobantes deja de figurar pendiente.
    cd.vincular_mis(cur)
    if nuevos_cmp:
        cur.execute(f"SELECT id_comprobante FROM me_expedientes WHERE id IN ({','.join(['%s'] * len(nuevos_cmp))})",
                    nuevos_cmp)
        cd.marcar_verificacion_mis(cur, [f["id_comprobante"] for f in cur.fetchall()])


# ─────────────────────────────────────────────────────────────────────────────
# Control: el saldo de la cuenta corriente contra el de AEDA
# ─────────────────────────────────────────────────────────────────────────────

SQL_SALDOS = """
    SELECT m.id_proveedor,
           SUM(CASE WHEN COALESCE(e.asunto, '') LIKE '[AEDA adm_pasivo %'
                      OR COALESCE(pp.nro_pago, '') LIKE 'AEDA-PG-%'
                    THEN m.debe - m.haber ELSE 0 END) AS saldo_aeda,
           SUM(m.debe - m.haber) AS saldo
      FROM v_cc_proveedores_movimientos m
      LEFT JOIN me_expedientes e ON e.id = m.id_expediente
      LEFT JOIN pago_pagos pp ON pp.id = m.id_pago AND m.id_expediente IS NULL
     GROUP BY m.id_proveedor
"""


def verificar(cur, plan: Plan) -> list[dict]:
    """Por proveedor: el saldo que dejó AEDA y el que muestra la cuenta corriente
    del sindicato con lo importado. Lo cargado acá va aparte (no se compara)."""
    cur.execute(SQL_SALDOS)
    vista = {f["id_proveedor"]: f for f in cur.fetchall()}
    filas = []
    for pid, s in sorted(plan.saldos.items(), key=lambda x: x[1]["razon"]):
        # Lo que tendría que mostrar la cuenta corriente con lo importado
        # (debe − haber) y el saldo de AEDA con todo lo activo, incluso lo que
        # no se importó, con el signo de AEDA (positivo: se le debe).
        esperado = s["pagos"] + s["anticipos"] - s["facturas"] + s["creditos"]
        v = vista.get(pid, {})
        importado = _d(v.get("saldo_aeda"))
        filas.append({**s, "saldo_aeda": s["no_importado"] - esperado, "esperado": esperado,
                      "sindicato_importado": importado, "sindicato_total": _d(v.get("saldo")),
                      "diferencia": importado - esperado})
    plan.verificacion = filas
    return [f for f in filas if abs(f["diferencia"]) > TOL]


# ─────────────────────────────────────────────────────────────────────────────
# Informe
# ─────────────────────────────────────────────────────────────────────────────

CAMPOS_INFORME = ["accion", "aeda", "nro", "proveedor", "fecha", "comprobante", "importe", "nota"]
CAMPOS_SALDOS = ["id_proveedor", "cuit", "razon", "facturas", "creditos", "pagos", "anticipos",
                 "saldo_aeda", "no_importado", "esperado", "sindicato_importado", "sindicato_total", "diferencia"]


def _csv(v):
    if isinstance(v, Decimal):
        return f"{v:.2f}".replace(".", ",")
    if isinstance(v, date):
        return v.strftime("%d/%m/%Y")
    return v


def escribir_informe(plan: Plan, estado: str, inicio: datetime, usuario: dict, diferencias=None):
    CARPETA_LOGS.mkdir(exist_ok=True)
    base = CARPETA_LOGS / f"importar_aeda_cc_proveedores_{inicio:%Y%m%d_%H%M%S}"
    detalle, saldos, resumen = (base.with_suffix(".csv"), base.with_name(base.name + "_saldos.csv"),
                                base.with_suffix(".txt"))
    with open(detalle, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_INFORME, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows({k: _csv(v) for k, v in fila.items()} for fila in plan.informe)
    filas = plan.verificacion or [
        {**s, "esperado": s["pagos"] + s["anticipos"] - s["facturas"] + s["creditos"],
         "saldo_aeda": s["facturas"] - s["creditos"] - s["pagos"] - s["anticipos"] + s["no_importado"]}
        for s in sorted(plan.saldos.values(), key=lambda x: x["razon"])]
    with open(saldos, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_SALDOS, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows({k: _csv(v) for k, v in fila.items()} for fila in filas)

    tot = {k: sum((s[k] for s in plan.saldos.values()), CERO)
           for k in ("facturas", "creditos", "pagos", "anticipos", "no_importado")}
    saldo_aeda = tot["facturas"] - tot["creditos"] - tot["pagos"] - tot["anticipos"] + tot["no_importado"]
    lineas = [f"Cuentas corrientes de proveedores AEDA → sindicato  {inicio:%d/%m/%Y %H:%M}",
              estado, f"Figura como cargado por: {usuario['nombre']}", ""]
    lineas += [f"  {n:>6}  {k}" for k, n in plan.cuenta.items()]
    lineas += ["", "  Totales de AEDA de los proveedores del sindicato (lo activo):",
               f"    facturas y notas de débito  {_pesos(tot['facturas']):>20}",
               f"    notas de crédito            {_pesos(tot['creditos']):>20}",
               f"    pagos                       {_pesos(tot['pagos']):>20}",
               f"    anticipos                   {_pesos(tot['anticipos']):>20}",
               f"    saldo (positivo: se debe)   {_pesos(saldo_aeda):>20}"]
    if tot["no_importado"]:
        lineas.append(f"    de eso, no importado        {_pesos(tot['no_importado']):>20}  (ver «omitido» y «usar cargado»)")
    if plan.verificacion:
        dif = [f for f in plan.verificacion if abs(f["diferencia"]) > TOL]
        lineas += ["", f"  Control contra la cuenta corriente del sindicato: {len(plan.verificacion)} proveedores, "
                       + ("todos dan igual." if not dif else f"{len(dif)} NO dan igual:")]
        for f in dif[:40]:
            lineas.append(f"    {f['razon'][:40]:40}  esperado {_pesos(f['esperado']):>16}  "
                          f"sindicato {_pesos(f['sindicato_importado']):>16}  dif {_pesos(f['diferencia']):>14}")
    if plan.conceptos_nuevos:
        lineas += ["", "  Conceptos de gasto nuevos: " + ", ".join(plan.conceptos_nuevos)]
    lineas += ["", f"Detalle: {detalle.name}", f"Saldos por proveedor: {saldos.name}"]
    resumen.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return resumen


# ─────────────────────────────────────────────────────────────────────────────

def hay_cambios(plan: Plan) -> bool:
    return any((plan.comprobantes, plan.pagos, plan.retenciones, plan.anular_exp, plan.anular_pagos,
                plan.anular_ret, plan.completar_regimen, plan.aplicaciones))


def main():
    parser = argparse.ArgumentParser(description="Cuentas corrientes de proveedores desde AEDA.")
    parser.add_argument("--aplicar", action="store_true", help="grabar en la base (sin esto, solo simula)")
    parser.add_argument("--usuario", help="mail del usuario que figura como el que cargó")
    parser.add_argument("--forzar", action="store_true",
                        help="grabar aunque algún saldo no dé igual que en AEDA")
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
        estado = "SIMULACIÓN — no se grabó nada"
        if args.aplicar and hay_cambios(plan):
            conn.begin()
            try:
                with conn.cursor() as cur:
                    aplicar(cur, plan, destino)
                    diferencias = verificar(cur, plan)
                if diferencias and not args.forzar:
                    conn.rollback()
                    estado = (f"NO SE GRABÓ: {len(diferencias)} proveedores no dan el saldo de AEDA "
                              "(ver el control abajo). Con --forzar se graba igual.")
                else:
                    conn.commit()
                    estado = "APLICADA" + (f" con {len(diferencias)} saldos distintos (--forzar)" if diferencias else "")
            except Exception:
                conn.rollback()
                resumen = escribir_informe(plan, "FALLÓ — no se grabó nada", inicio, destino["usuario"])
                print(f"\n  Falló la importación; no se grabó nada. Plan en {resumen}\n")
                raise
        elif args.aplicar:
            with conn.cursor() as cur:
                verificar(cur, plan)
            estado = "Nada nuevo para grabar"

    resumen = escribir_informe(plan, estado, inicio, destino["usuario"])
    print()
    print(resumen.read_text(encoding="utf-8"))
    if not args.aplicar:
        print("  Para grabar:  python importar_aeda_cc_proveedores.py --aplicar\n")


if __name__ == "__main__":
    sys.exit(main())
