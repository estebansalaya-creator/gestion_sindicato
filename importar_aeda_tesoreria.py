"""
importar_aeda_tesoreria.py — Plan de cuentas y tablas de tesorería desde AEDA.

Origen (base `aeda`):

    adm_planctas                 →  c_plan_de_cuentas (151 cuentas, 1-1-1-02-020)
    adm_cptogasto tipo G         →  c_concepto_de_gastos
    adm_cptogasto tipo I         →  c_motivos_de_ingreso
    adm_ctasfondos               →  c_cuentas_de_fondos (caja, bancos, plazo fijo, cartera)
    adm_chequeras + adm_movctas  →  c_chequeras (con el último cheque usado)
    adm_ImpuCont                 →  cuentas de pago_imputaciones_config (anticipos,
                                    retención de Ganancias)

Uso
---
    python importar_aeda_tesoreria.py             simula y escribe el informe en logs/
    python importar_aeda_tesoreria.py --aplicar   lo mismo, y lo graba

Requiere sql/tesoreria_20261108.sql (la columna `activo` de los conceptos y la
`predeterminada` de las cuentas de fondos). Sin eso no arranca.

Decisiones
----------
Plan de cuentas. Lo trae importar_aeda_plan_cuentas.py (este script usa sus
funciones, y las decisiones están explicadas ahí): el código de AEDA se
conserva y su número es el id_cuenta, así las imputaciones se resuelven sin
tabla de equivalencias; clase, nivel, madre e imputable salen del código, con
las reglas de la pantalla (plan_cuentas.py).

Conceptos de gasto y motivos de ingreso. Los de AEDA se buscan por descripción
(AEDA corta a 30 letras: «SUBSIDIO Y SERVICIO POR FALLEC» es el «…FALLECIMIENTO»
que ya está) y quedan con la cuenta de AEDA y activos; los que faltan se
agregan. Los que vinieron copiados de la obra social (apuntan a cuentas de
`contable`, que acá no existen) se borran si nada los usa y se desactivan si
algo los usa. Uno cargado en el sindicato tiene una cuenta del plan: ese no se
toca nunca, ni en la primera corrida ni en las siguientes.

Cuentas de fondos. Tipo C caja, B banco, R cartera, O otra; un banco imputado
en inversiones (1-1-2, el plazo fijo) es I. El banco sale del CBU (sus tres
primeros dígitos) y, sin CBU, del nombre. Una cuenta «NO USAR» o en baja
entra deshabilitada. De pago = caja o banco con pagos (OP) en el último año; la
predeterminada es la que más pagos tuvo en los últimos seis meses.

Chequeras. El próximo número sale del último cheque emitido en ese rango
(adm_movctas, débitos). Una chequera terminada entra deshabilitada.

Se puede correr más de una vez: el plan se completa por código, las cuentas de
fondos llevan su origen en el comentario («[AEDA adm_ctasfondos 3]») y una
chequera se reconoce por su cuenta y su primer número.
"""

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime

# importar_aeda carga el .env y trae la conexión a AEDA.
from importar_aeda import CARPETA_LOGS, _filas, conexion_aeda, limpio, normalizar, salir, solo_digitos

import importar_aeda_plan_cuentas as plan_aeda
import tesoreria
from afiliados import cbu_valido
from db import get_connection

RE_MARCA_CUENTA = re.compile(r"^\[AEDA adm_ctasfondos (\d+)\]")
LARGO_AEDA = 30          # adm_cptogasto.descrip: lo que pasa de 30 letras, AEDA lo corta

TIPO_CUENTA = {"C": "C", "B": "B", "R": "R", "O": "O"}
TIPO_TEXTO = {"C": "Caja", "B": "Banco", "R": "Cartera", "I": "Inversiones", "T": "Tarjeta", "O": "Otra"}
#: Sin CBU, el banco por el nombre de la cuenta.
BANCO_POR_NOMBRE = [("NACION", "011"), ("ICBC", "015"), ("PROVINCIA", "014"), ("GALICIA", "007"),
                    ("SANTANDER", "072"), ("MACRO", "285"), ("CIUDAD", "029"), ("CREDICOOP", "191"),
                    ("BBVA", "017"), ("PATAGONIA", "034"), ("SUPERVIELLE", "027")]

#: Dónde se usa cada catálogo: los mismos que miran las pantallas (tesoreria.py).
USOS_CONCEPTO, USOS_MOTIVO = tesoreria.USOS_CONCEPTO, tesoreria.USOS_MOTIVO


# ─────────────────────────────────────────────────────────────────────────────
# Lectura
# ─────────────────────────────────────────────────────────────────────────────

SQL_AEDA = {
    "plan": plan_aeda.SQL_PLAN,
    "conceptos": "SELECT conc_id, descrip, tipo_pig, pcont_id FROM aeda.dbo.adm_cptogasto",
    "cuentas": """SELECT cajabanco_id, descrip, caja_tipo, pcont_id, cta_nro, espe_id, estado, cbu
                    FROM aeda.dbo.adm_ctasfondos""",
    "chequeras": """
        SELECT q.chqra_id, q.cajabanco_id, q.chq_desde, q.chq_hasta, q.estado,
               (SELECT MAX(m.cheque_nro) FROM aeda.dbo.adm_movctas m
                 WHERE m.cajabanco_id = q.cajabanco_id AND m.debito > 0 AND m.status <> 'X'
                   AND m.cheque_nro BETWEEN q.chq_desde AND q.chq_hasta) AS ultimo
          FROM aeda.dbo.adm_chequeras q""",
    "pagos": """
        SELECT cajabanco_id,
               SUM(CASE WHEN fecha >= DATEADD(day, -365, GETDATE()) THEN 1 ELSE 0 END) AS anio,
               SUM(CASE WHEN fecha >= DATEADD(day, -180, GETDATE()) THEN 1 ELSE 0 END) AS semestre
          FROM aeda.dbo.adm_movctas
         WHERE ref_id = 'OP' AND status <> 'X'
         GROUP BY cajabanco_id""",
    "imputaciones": "SELECT codigo, descri, pcont_id FROM aeda.dbo.adm_ImpuCont",
}


def leer_aeda(cn) -> dict:
    cur = cn.cursor()
    datos = {k: _filas(cur, sql) for k, sql in SQL_AEDA.items()}
    cur.close()
    return datos


def _columnas(cur, tabla) -> set:
    cur.execute("SELECT column_name AS c FROM information_schema.columns "
                "WHERE table_schema = DATABASE() AND table_name = %s", (tabla,))
    return {f["c"] for f in cur.fetchall()}


def leer_destino(cur) -> dict:
    if "activo" not in _columnas(cur, "c_concepto_de_gastos") \
            or "predeterminada" not in _columnas(cur, "c_cuentas_de_fondos"):
        salir("Faltan columnas de tesorería. Correr antes sql/tesoreria_20261108.sql.")
    d = plan_aeda.leer_destino(cur)

    cur.execute("SELECT * FROM c_concepto_de_gastos")
    d["conceptos"] = cur.fetchall()
    d["usos_concepto"] = tesoreria.usos(cur, USOS_CONCEPTO)
    cur.execute("SELECT * FROM c_motivos_de_ingreso")
    d["motivos"] = cur.fetchall()
    d["usos_motivo"] = tesoreria.usos(cur, USOS_MOTIVO)

    cur.execute("SELECT id FROM arca_tasa_iva WHERE descripcion = 'No Gravado' ORDER BY id LIMIT 1")
    f = cur.fetchone()
    if not f:
        cur.execute("SELECT id FROM arca_tasa_iva ORDER BY alicuota, id LIMIT 1")
        f = cur.fetchone()
    if not f:
        salir("arca_tasa_iva está vacía: los conceptos de gasto necesitan una alícuota.")
    d["tasa_iva"] = f["id"]
    cur.execute("SELECT id FROM c_especies WHERE simbolo = '$' OR f_afip_monedaId = 'PES' ORDER BY id LIMIT 1")
    f = cur.fetchone()
    if not f:
        salir("Falta la especie Pesos en c_especies.")
    d["pesos"] = f["id"]

    cur.execute("SELECT id, codigo, nombre FROM c_codigo_de_banco")
    d["bancos"] = {str(f["codigo"]).zfill(3): f for f in cur.fetchall()}
    if len(d["bancos"]) < 10:
        salir("Faltan los códigos de banco del BCRA. Correr antes sql/tesoreria_20261108.sql.")
    cur.execute("SELECT id, comentario, predeterminada FROM c_cuentas_de_fondos")
    filas = cur.fetchall()
    d["cuentas_aeda"] = {int(RE_MARCA_CUENTA.match(f["comentario"]).group(1)): f["id"] for f in filas
                         if RE_MARCA_CUENTA.match(f["comentario"] or "")}
    d["hay_predeterminada"] = any(f["predeterminada"] for f in filas)
    cur.execute("SELECT c_cuentas_de_fondosId AS cuenta, numero_desde FROM c_chequeras")
    d["chequeras"] = {(f["cuenta"], int(f["numero_desde"])) for f in cur.fetchall()}

    cur.execute("SELECT id, nombre, c_plan_de_cuentasId FROM c_rubros_de_pasivo")
    d["rubros"] = cur.fetchall()
    cur.execute("SELECT id, clase, subtipo, id_cuenta_debe, id_cuenta_haber FROM pago_imputaciones_config")
    d["imputaciones"] = cur.fetchall()
    return d


# ─────────────────────────────────────────────────────────────────────────────
# Plan
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Plan:
    cuentas_plan: list[dict] = field(default_factory=list)       # nuevas (importar_aeda_plan_cuentas)
    mapa: dict = field(default_factory=dict)                     # pcont_id → código del destino
    titulos: dict = field(default_factory=dict)                  # código → nombre de la cuenta en AEDA
    conceptos_upd: list[dict] = field(default_factory=list)
    conceptos_ins: list[dict] = field(default_factory=list)
    conceptos_borrar: list[dict] = field(default_factory=list)
    conceptos_baja: list[dict] = field(default_factory=list)
    motivos_upd: list[dict] = field(default_factory=list)
    motivos_ins: list[dict] = field(default_factory=list)
    motivos_borrar: list[dict] = field(default_factory=list)
    motivos_baja: list[dict] = field(default_factory=list)
    cuentas_fondos: list[dict] = field(default_factory=list)
    chequeras: list[dict] = field(default_factory=list)
    rubros: list[dict] = field(default_factory=list)
    imputaciones: list[dict] = field(default_factory=list)
    informe: list[dict] = field(default_factory=list)
    cuenta: dict = field(default_factory=dict)

    def contar(self, clave, n=1):
        self.cuenta[clave] = self.cuenta.get(clave, 0) + n

    def anotar(self, accion, **datos):
        self.informe.append({"accion": accion, **datos})


def _buscar(descripcion, filas, usados) -> dict | None:
    """La fila del destino con esa descripción: igual, o la única que empieza
    así cuando AEDA la cortó a 30 letras."""
    clave = normalizar(descripcion)
    for f in filas:
        if f["id"] not in usados and normalizar(f["descripcion"]) == clave:
            return f
    if len(limpio(descripcion)) >= LARGO_AEDA:
        cand = [f for f in filas if f["id"] not in usados and normalizar(f["descripcion"]).startswith(clave)]
        if len(cand) == 1:
            return cand[0]
    return None


def _catalogo(aeda_filas, destino_filas, usos, plan, destino, nombre, upd, ins, borrar, baja, plural):
    usados = set()
    for a in sorted(aeda_filas, key=lambda x: x["conc_id"]):
        desc = limpio(a["descrip"])
        cod = plan.mapa.get(a["pcont_id"])
        if not cod:
            plan.contar(f"{plural} de AEDA con una cuenta que no está en su plan (no se importan)")
            plan.anotar("omitido", aeda=f"adm_cptogasto {a['conc_id']}", nombre=desc,
                        nota=f"la cuenta {a['pcont_id']} no está en adm_planctas")
            continue
        f = _buscar(desc, destino_filas, usados)
        if f:
            usados.add(f["id"])
            upd.append({"id": f["id"], "_codigo": cod})
            plan.contar(f"{plural} que ya estaban (quedan con la cuenta de AEDA)")
            plan.anotar(f"{nombre} existente", aeda=f"adm_cptogasto {a['conc_id']}", nombre=f["descripcion"],
                        codigo=cod, nota="" if normalizar(f["descripcion"]) == normalizar(desc)
                        else f"en AEDA: {desc}")
        else:
            # Cortada a 30 letras por AEDA: si la cuenta se llama igual pero
            # entera («RETENCION GANANCIAS A DEPOSITA» → «…DEPOSITAR»), va esa.
            titulo = plan.titulos.get(cod, "")
            if len(desc) >= LARGO_AEDA and normalizar(titulo).startswith(normalizar(desc)):
                desc = titulo
            ins.append({"descripcion": desc, "_codigo": cod})
            plan.contar(f"{plural} nuevos de AEDA")
            plan.anotar(f"{nombre} nuevo", aeda=f"adm_cptogasto {a['conc_id']}", nombre=desc, codigo=cod)
    # Lo que no es de AEDA y apunta a una cuenta que no existe vino de la obra social.
    codigos_destino = set(destino["plan_por_codigo"].values())
    for f in destino_filas:
        if f["id"] in usados or f["c_plan_de_cuentasId"] in codigos_destino:
            continue
        n = usos.get(f["id"], 0)
        if n and not f["activo"]:
            plan.contar(f"{plural} de la obra social ya desactivados")
        elif n:
            baja.append(f)
            plan.contar(f"{plural} de la obra social que se usan (se desactivan)")
            plan.anotar(f"desactivar {nombre}", nombre=f["descripcion"], nota=f"se usa en {n} filas")
        else:
            borrar.append(f)
            plan.contar(f"{plural} de la obra social sin usar (se borran)")
            plan.anotar(f"borrar {nombre}", nombre=f["descripcion"])


def _banco(cbu, nombres, bancos, notas):
    """Del CBU; sin CBU, del nombre de la cuenta o, si no, del de su cuenta
    contable («PLAZO FIJO» está imputado a «BANCO NACION PLAZO FIJO»)."""
    if cbu:
        return bancos.get(cbu[:3])
    for nombre in nombres:
        for clave, cod in BANCO_POR_NOMBRE:
            if clave in normalizar(nombre):
                notas.append(f"banco deducido del nombre «{nombre}»")
                return bancos.get(cod)
    return None


def armar_cuentas(aeda, destino, plan):
    pagos = {f["cajabanco_id"]: f for f in aeda["pagos"]}
    nuevas = []
    for c in sorted(aeda["cuentas"], key=lambda x: x["cajabanco_id"]):
        cid = c["cajabanco_id"]
        if cid in destino["cuentas_aeda"]:
            plan.contar("cuentas de fondos que ya estaban")
            continue
        nombre = limpio(c["descrip"])
        cod = plan.mapa.get(c["pcont_id"])
        notas = []
        tipo = TIPO_CUENTA.get(limpio(c["caja_tipo"]).upper(), "O")
        if tipo == "B" and cod and cod.startswith("1-1-2"):
            tipo = "I"
        habilitada = limpio(c["estado"]).upper() == "A" and "NO USAR" not in normalizar(nombre)
        if not habilitada:
            notas.append("deshabilitada: " + ("dice NO USAR" if "NO USAR" in normalizar(nombre) else "en baja en AEDA"))
        cbu = solo_digitos(c["cbu"])
        if cbu and not (len(cbu) == 22 and cbu_valido(cbu)):
            notas.append(f"el CBU de AEDA no verifica: {cbu}")
            cbu = ""
        banco = (_banco(cbu, [nombre, plan.titulos.get(cod, "")], destino["bancos"], notas)
                 if tipo in ("B", "I") else None)
        if tipo == "B" and (not cbu or not limpio(c["cta_nro"])):
            notas.append("le falta " + " y ".join(x for x, v in (("el número de cuenta", limpio(c["cta_nro"])),
                                                                  ("el CBU", cbu)) if not v))
            plan.contar("bancos sin número de cuenta o CBU (completarlos en la pantalla)")
        p = pagos.get(cid) or {}
        # De pago, solo caja y bancos: un plazo fijo con una OP suelta no es
        # una cuenta para pagar.
        esdepago = 1 if habilitada and tipo in ("C", "B") and (p.get("anio") or 0) > 0 else 0
        if not cod:
            plan.contar("cuentas de fondos sin cuenta contable en AEDA (no se importan)")
            plan.anotar("omitida", aeda=f"adm_ctasfondos {cid}", nombre=nombre,
                        nota=f"la cuenta {c['pcont_id']} no está en adm_planctas")
            continue
        marca = f"[AEDA adm_ctasfondos {cid}]"
        nuevas.append({
            "tipo_de_cuenta": tipo, "nombre": nombre[:100], "c_codigo_de_bancoId": banco["id"] if banco else None,
            "numero_de_cuenta": limpio(c["cta_nro"])[:20] or None, "cbu": cbu or None,
            "c_especiesId": destino["pesos"], "_codigo": cod, "habilitada": 1 if habilitada else 0,
            "comentario": (marca + (" " + ". ".join(n[0].upper() + n[1:] for n in notas) + "." if notas else ""))[:250],
            "esdepago": esdepago, "predeterminada": 0, "_aeda": cid, "_semestre": p.get("semestre") or 0,
            "_banco": banco["nombre"] if banco else "", "_notas": notas})
    candidatas = [c for c in nuevas if c["esdepago"] and c["_semestre"]]
    if candidatas and not destino["hay_predeterminada"]:
        max(candidatas, key=lambda c: c["_semestre"])["predeterminada"] = 1
    for c in nuevas:
        plan.contar(f"cuentas de fondos a crear ({TIPO_TEXTO[c['tipo_de_cuenta']].lower()})")
        plan.anotar("crear cuenta de fondos", aeda=f"adm_ctasfondos {c['_aeda']}", nombre=c["nombre"],
                    codigo=c["_codigo"], tipo=TIPO_TEXTO[c["tipo_de_cuenta"]],
                    nota="; ".join(c["_notas"] + (["de pago"] if c["esdepago"] else [])
                                   + (["predeterminada para pagar"] if c["predeterminada"] else [])
                                   + ([c["_banco"]] if c["_banco"] else [])))
    plan.cuentas_fondos = nuevas

    for q in sorted(aeda["chequeras"], key=lambda x: x["chqra_id"]):
        desde, hasta = int(q["chq_desde"]), int(q["chq_hasta"])
        id_dest = destino["cuentas_aeda"].get(q["cajabanco_id"])
        if id_dest and (id_dest, desde) in destino["chequeras"]:
            plan.contar("chequeras que ya estaban")
            continue
        if not id_dest and not any(c["_aeda"] == q["cajabanco_id"] for c in nuevas):
            plan.contar("chequeras de una cuenta que no se importa")
            continue
        ultimo = int(q["ultimo"]) if q["ultimo"] else desde - 1
        proximo = ultimo + 1
        habil = 1 if proximo <= hasta and limpio(q["estado"]).upper() == "H" else 0
        plan.chequeras.append({"_aeda_cuenta": q["cajabanco_id"], "_id_cuenta": id_dest,
                               "descripcion": f"Chequera {q['chqra_id']} de AEDA", "numero_desde": desde,
                               "numero_hasta": hasta, "proximo_numero": proximo, "habilitada": habil})
        plan.contar("chequeras a crear" + ("" if habil else " (terminadas: deshabilitadas)"))
        plan.anotar("crear chequera", aeda=f"adm_chequeras {q['chqra_id']}", codigo=f"{desde}-{hasta}",
                    nota=("terminada" if not habil else f"próximo cheque {proximo}"))


def armar_imputaciones(aeda, destino, plan):
    por_codigo = {limpio(f["codigo"]).upper(): plan.mapa.get(f["pcont_id"]) for f in aeda["imputaciones"]}
    for r in destino["rubros"]:
        actual = solo_digitos(r["c_plan_de_cuentasId"])
        if normalizar(r["nombre"]) == "PROVEEDORES" and (not actual or int(actual) not in destino["plan_ids"]):
            plan.rubros.append({"id": r["id"], "_codigo": "2-1-1-01-010"})
            plan.contar("rubro de pasivo «Proveedores» imputado a 2-1-1-01-010 PROVEEDORES")
    anticipo = next((f for f in destino["imputaciones"] if f["clase"] == "anticipo"), None)
    if anticipo and not anticipo["id_cuenta_debe"] and por_codigo.get("ANTICIPO"):
        plan.imputaciones.append({"accion": "anticipo", "id": anticipo["id"], "_codigo": por_codigo["ANTICIPO"]})
        plan.contar(f"imputación de anticipos a {por_codigo['ANTICIPO']}")
    ret = next((f for f in destino["imputaciones"] if f["clase"] == "retencion" and f["subtipo"] == "GANANCIAS"), None)
    if not ret and por_codigo.get("RETENGAN"):
        plan.imputaciones.append({"accion": "retencion", "_codigo": por_codigo["RETENGAN"]})
        plan.contar(f"imputación de la retención de Ganancias a {por_codigo['RETENGAN']}")


def armar_plan(aeda: dict, destino: dict) -> Plan:
    plan = Plan()
    plan_aeda.armar_plan_cuentas(aeda["plan"], destino, plan)
    gastos = [f for f in aeda["conceptos"] if limpio(f["tipo_pig"]).upper() == "G"]
    ingresos = [f for f in aeda["conceptos"] if limpio(f["tipo_pig"]).upper() == "I"]
    _catalogo(gastos, destino["conceptos"], destino["usos_concepto"], plan, destino, "concepto",
              plan.conceptos_upd, plan.conceptos_ins, plan.conceptos_borrar, plan.conceptos_baja,
              "conceptos de gasto")
    _catalogo(ingresos, destino["motivos"], destino["usos_motivo"], plan, destino, "motivo",
              plan.motivos_upd, plan.motivos_ins, plan.motivos_borrar, plan.motivos_baja,
              "motivos de ingreso")
    armar_cuentas(aeda, destino, plan)
    armar_imputaciones(aeda, destino, plan)
    return plan


# ─────────────────────────────────────────────────────────────────────────────
# Escritura
# ─────────────────────────────────────────────────────────────────────────────

def aplicar(cur, plan: Plan, destino: dict) -> None:
    ids = plan_aeda.aplicar_plan_cuentas(cur, plan, destino)

    for f in plan.conceptos_upd:
        cur.execute("UPDATE c_concepto_de_gastos SET c_plan_de_cuentasId = %s, activo = 1 WHERE id = %s",
                    (ids[f["_codigo"]], f["id"]))
    for f in plan.conceptos_ins:
        cur.execute("""INSERT INTO c_concepto_de_gastos (descripcion, c_plan_de_cuentasId, c_especiesId,
                                                        arca_tasa_ivaid, esliquidacion, es_reintegro, activo)
                       VALUES (%s, %s, %s, %s, 0, 0, 1)""",
                    (f["descripcion"][:50], ids[f["_codigo"]], destino["pesos"], destino["tasa_iva"]))
    for f in plan.conceptos_baja:
        cur.execute("UPDATE c_concepto_de_gastos SET activo = 0 WHERE id = %s", (f["id"],))
    for f in plan.conceptos_borrar:
        cur.execute("DELETE FROM c_concepto_de_gastos WHERE id = %s", (f["id"],))

    for f in plan.motivos_upd:
        cur.execute("UPDATE c_motivos_de_ingreso SET c_plan_de_cuentasId = %s, activo = 1, "
                    "c_especiesId = COALESCE(c_especiesId, %s) WHERE id = %s",
                    (ids[f["_codigo"]], destino["pesos"], f["id"]))
    for f in plan.motivos_ins:
        cur.execute("INSERT INTO c_motivos_de_ingreso (descripcion, c_plan_de_cuentasId, c_especiesId, activo) "
                    "VALUES (%s, %s, %s, 1)", (f["descripcion"][:100], ids[f["_codigo"]], destino["pesos"]))
    for f in plan.motivos_baja:
        cur.execute("UPDATE c_motivos_de_ingreso SET activo = 0 WHERE id = %s", (f["id"],))
    for f in plan.motivos_borrar:
        cur.execute("DELETE FROM c_motivos_de_ingreso WHERE id = %s", (f["id"],))

    nuevas = dict(destino["cuentas_aeda"])
    for c in plan.cuentas_fondos:
        cur.execute("""INSERT INTO c_cuentas_de_fondos
                         (tipo_de_cuenta, nombre, c_codigo_de_bancoId, numero_de_cuenta, cbu, c_especiesId,
                          c_plan_de_cuentasId, habilitada, comentario, esdepago, predeterminada)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (c["tipo_de_cuenta"], c["nombre"], c["c_codigo_de_bancoId"], c["numero_de_cuenta"], c["cbu"],
                     c["c_especiesId"], ids[c["_codigo"]], c["habilitada"], c["comentario"], c["esdepago"],
                     c["predeterminada"]))
        nuevas[c["_aeda"]] = cur.lastrowid
    for q in plan.chequeras:
        cur.execute("""INSERT INTO c_chequeras (c_cuentas_de_fondosId, descripcion, tipo_cheque, impresion,
                                                numero_desde, numero_hasta, proximo_numero, habilitada)
                       VALUES (%s, %s, 'al_dia', 'manual', %s, %s, %s, %s)""",
                    (q["_id_cuenta"] or nuevas[q["_aeda_cuenta"]], q["descripcion"], q["numero_desde"],
                     q["numero_hasta"], q["proximo_numero"], q["habilitada"]))

    for r in plan.rubros:
        if r["_codigo"] in ids:
            cur.execute("UPDATE c_rubros_de_pasivo SET c_plan_de_cuentasId = %s WHERE id = %s",
                        (ids[r["_codigo"]], r["id"]))
    for i in plan.imputaciones:
        if i["accion"] == "anticipo":
            cur.execute("UPDATE pago_imputaciones_config SET id_cuenta_debe = %s, observaciones = %s WHERE id = %s",
                        (ids[i["_codigo"]], "Cuenta de AEDA (adm_ImpuCont ANTICIPO).", i["id"]))
        else:
            cur.execute("""INSERT INTO pago_imputaciones_config (clase, subtipo, nombre, id_cuenta_haber, activo,
                                                                 observaciones)
                           VALUES ('retencion', 'GANANCIAS', 'Retención de Ganancias a depositar', %s, 1,
                                   'Cuenta de AEDA (adm_ImpuCont RETENGAN).')""", (ids[i["_codigo"]],))


# ─────────────────────────────────────────────────────────────────────────────
# Informe
# ─────────────────────────────────────────────────────────────────────────────

CAMPOS_INFORME = ["accion", "aeda", "codigo", "nombre", "tipo", "nota"]


def escribir_informe(plan: Plan, estado: str, inicio: datetime):
    CARPETA_LOGS.mkdir(exist_ok=True)
    base = CARPETA_LOGS / f"importar_aeda_tesoreria_{inicio:%Y%m%d_%H%M%S}"
    detalle, resumen = base.with_suffix(".csv"), base.with_suffix(".txt")
    with open(detalle, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_INFORME, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(plan.informe)
    lineas = [f"Plan de cuentas y tesorería AEDA → sindicato  {inicio:%d/%m/%Y %H:%M}", estado, ""]
    lineas += [f"  {n:>6}  {k}" for k, n in plan.cuenta.items()]
    lineas += ["", f"Detalle: {detalle.name}"]
    resumen.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return resumen


def main():
    parser = argparse.ArgumentParser(description="Plan de cuentas y tablas de tesorería desde AEDA.")
    parser.add_argument("--aplicar", action="store_true", help="grabar en la base (sin esto, solo simula)")
    args = parser.parse_args()
    inicio = datetime.now()

    cn = conexion_aeda()
    try:
        aeda = leer_aeda(cn)
    finally:
        cn.close()

    with get_connection() as conn:
        with conn.cursor() as cur:
            destino = leer_destino(cur)
        plan = armar_plan(aeda, destino)
        estado = "SIMULACIÓN — no se grabó nada"
        if args.aplicar:
            conn.begin()
            try:
                with conn.cursor() as cur:
                    aplicar(cur, plan, destino)
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
        print("  Para grabar:  python importar_aeda_tesoreria.py --aplicar\n")


if __name__ == "__main__":
    sys.exit(main())
