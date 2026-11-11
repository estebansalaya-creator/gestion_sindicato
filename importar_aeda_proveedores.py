"""
importar_aeda_proveedores.py — Proveedores de AEDA a la base `sindicato`.

Origen: `aeda.dbo.adm_proveedor` y sus contactos (`adm_contactos` con
`ref_id = 'P'`). Ver importar_aeda.py, que resuelve la conexión. Carga, en una
sola transacción:

1. `adm_proveedor` → `c_proveedores`, con un movimiento de ALTA (origen
   IMPORTACION) en `c_proveedores_movimientos`.
2. Su cuenta de pasivo (el grupo de pasivo de AEDA, «Proveedores») y su
   concepto de gasto, como cuentas predeterminadas.
3. Los contactos → `s_contactos`, entidad `proveedor`, con la misma limpieza de
   teléfonos y mails que los de empresas (importar_aeda.contactos_de_empresa).

Uso
---
    python importar_aeda_proveedores.py             simula y escribe el informe en logs/
    python importar_aeda_proveedores.py --aplicar   lo mismo, y lo graba

Requiere sql/proveedores_20261107.sql aplicado (auditoría, rubro «Proveedores»
y los regímenes 78 y 31 de RG 830). Sin eso no arranca.

Decisiones sobre los datos de AEDA
----------------------------------
Condición de IVA. AEDA usa letras: I → Responsable Inscripto (1), E → Exento
(4), F → Consumidor Final (5), M → Monotributo (6). «N» (responsable no
inscripto) ya no existe en ARCA: queda vacía, con la nota.

Retención de Ganancias. El «tipo de retención» de AEDA es una letra cuya tabla
(adm_rg2784) dice el mínimo y la alícuota, y con eso se reconoce el régimen de
RG 830: B (67.170, 2%) → 94; C (224.000, 2%) → 78; H (16.830, escala) → 116;
P (160.000, escala) → 119; A (11.200, 6%) → 31. X (exentos) y Z (no corresponde)
no retienen. A un monotributista no se le retiene aunque AEDA lo tuviera
marcado: queda la nota.

Retención de IIBB: el `rib` de AEDA.

CBU. El campo de AEDA tiene CBU, CVU y alias mezclados. 22 dígitos que
verifican → CBU; que no verifican → no se carga y va a observaciones; texto →
alias.

Concepto de gasto. Se busca por descripción en `c_concepto_de_gastos`. Los que
no están (ATENCION AFILIADOS, INSTALACIONES, …) se agregan al catálogo con la
imputación de «GASTOS GENERALES». La imputación de cada uno la deja bien
importar_aeda_tesoreria.py, con la cuenta que tiene en AEDA.
Un proveedor sin concepto en AEDA queda sin cuenta de gasto.

CUIT. Un CUIT que no verifica el dígito entra igual, con la nota: la ficha no
deja volver a guardarlo hasta que se corrija.

Se puede correr más de una vez: lo importado lleva su origen al principio de
`observaciones` («[AEDA adm_proveedor 2153]»), y un CUIT que ya está no se
vuelve a crear (solo se le agregan los contactos que falten).
"""

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime

# importar_aeda carga el .env y trae la conexión a AEDA y la limpieza de
# teléfonos y mails.
from importar_aeda import (CARPETA_LOGS, _filas, conexion_aeda, contactos_de_empresa,
                           normalizar, salir, solo_digitos)
from importar_aeda import limpio as _limpio

import proveedores_movimientos as movs
import rg830
from afiliados import cbu_valido
from db import get_connection
from empleadores import cuit_valido

ENTIDAD = "proveedor"
RE_MARCA = re.compile(r"^\[AEDA adm_proveedor (\d+)\]")
RE_MARCA_CTO = re.compile(r"^\[AEDA [^\]]+\]")
RE_ALIAS = re.compile(r"^[A-Za-z0-9.\-]{6,20}$")

IVA_AEDA = {"I": 1, "E": 4, "F": 5, "M": 6}
REGIMEN_AEDA = {"B": "094", "C": "078", "H": "116", "P": "119", "A": "031"}
SIN_RETENCION = {"X", "Z", ""}
RE_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def limpio(valor) -> str:
    """El de importar_aeda, sin caracteres de control: un nombre de AEDA trae un
    \\x02 al final («CIMAR ELECTRONICA SRL      \\x02»), que no es espacio y
    quedaría pegado a la razón social."""
    return _limpio(RE_CONTROL.sub(" ", str(valor)) if valor is not None else None)


CONCEPTO_PLANTILLA = "GASTOS GENERALES"


# ─────────────────────────────────────────────────────────────────────────────
# Lectura
# ─────────────────────────────────────────────────────────────────────────────

def leer_aeda(cn) -> dict:
    cur = cn.cursor()
    proveedores = _filas(cur, """
        SELECT p.prest_id, p.prest_nombre, p.prest_fantasia, p.calle, p.locali, p.codpos,
               p.telefono, p.fax, p.cuit, p.email, CAST(p.observa AS varchar(2000)) AS observa,
               p.iva, p.rga, p.rib, p.alaorden, p.cbu, p.conc_id,
               g.descrip AS concepto, pg.grpasivo_nombre AS grupo_pasivo
          FROM aeda.dbo.adm_proveedor p
          LEFT JOIN aeda.dbo.adm_cptogasto g    ON g.conc_id = p.conc_id
          LEFT JOIN aeda.dbo.adm_pasivogrupo pg ON pg.grpasivo_id = p.grpasivo_id
         ORDER BY p.prest_id
    """)
    contactos = _filas(cur, """
        SELECT contacto_id, ref_nro AS prest_id, nombre, cargo, telefono, email
          FROM aeda.dbo.adm_contactos
         WHERE ref_id = 'P'
         ORDER BY ref_nro, contacto_id
    """)
    cur.close()
    return {"proveedores": proveedores, "contactos": contactos}


def leer_destino(cur) -> dict:
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.tables
                    WHERE table_schema = DATABASE() AND table_name = 'c_proveedores_movimientos'""")
    if not cur.fetchone()["n"]:
        salir("Falta c_proveedores_movimientos. Correr antes sql/proveedores_20261107.sql.")
    cur.execute("SELECT id, nombre FROM c_rubros_de_pasivo")
    rubros = {normalizar(f["nombre"]): f["id"] for f in cur.fetchall()}
    if "PROVEEDORES" not in rubros:
        salir("Falta el rubro de pasivo «Proveedores». Correr antes sql/proveedores_20261107.sql.")

    cur.execute("SELECT id, cuit, observaciones FROM c_proveedores")
    por_cuit, ya = {}, {}
    for f in cur.fetchall():
        por_cuit[f["cuit"]] = f["id"]
        m = RE_MARCA.match(f["observaciones"] or "")
        if m:
            ya[int(m.group(1))] = f["id"]

    cur.execute("SELECT id, descripcion, c_plan_de_cuentasId, c_especiesId, arca_tasa_ivaid "
                "FROM c_concepto_de_gastos")
    filas = cur.fetchall()
    conceptos = {normalizar(f["descripcion"]): f["id"] for f in filas}
    plantilla = next((f for f in filas if normalizar(f["descripcion"]) == CONCEPTO_PLANTILLA),
                     filas[0] if filas else None)

    cur.execute("SELECT id, nombre FROM c_areas_contacto WHERE activo = 1")
    areas = {f["nombre"]: f["id"] for f in cur.fetchall()}
    # Sin parámetros: con argumentos, PyMySQL toma el `%` del LIKE como marcador.
    cur.execute("SELECT observaciones FROM s_contactos "
                "WHERE entidad_tipo = 'proveedor' AND observaciones LIKE '[AEDA %'")
    marcas = {RE_MARCA_CTO.match(f["observaciones"]).group(0) for f in cur.fetchall()
              if RE_MARCA_CTO.match(f["observaciones"] or "")}
    cur.execute("SELECT DISTINCT entidad_id FROM s_contactos "
                "WHERE entidad_tipo = 'proveedor' AND activo = 1 AND principal = 1")
    con_principal = {("id", f["entidad_id"]) for f in cur.fetchall()}

    return {"rubros": rubros, "por_cuit": por_cuit, "ya": ya, "conceptos": conceptos,
            "plantilla": plantilla, "areas": areas, "marcas": marcas,
            "con_principal": con_principal,
            "regimenes": {r["codigo"] for r in rg830.vigentes(cur)}}


# ─────────────────────────────────────────────────────────────────────────────
# Plan
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Plan:
    proveedores: list[dict] = field(default_factory=list)
    contactos: list[dict] = field(default_factory=list)
    conceptos_nuevos: list[str] = field(default_factory=list)
    informe: list[dict] = field(default_factory=list)
    cuenta: dict = field(default_factory=dict)

    def contar(self, clave, n=1):
        self.cuenta[clave] = self.cuenta.get(clave, 0) + n

    def anotar(self, accion, **datos):
        self.informe.append({"accion": accion, **datos})


def _cbu_y_alias(texto, notas, plan) -> tuple:
    t = limpio(texto).replace(" ", "")
    if not t or set(t) <= {"0"}:
        return None, None
    if t.isdigit():
        if len(t) == 22 and cbu_valido(t):
            return t, None
        if len(t) == 22:
            notas.append(f"CBU de AEDA que no verifica el dígito: {t}")
        else:
            notas.append(f"en el CBU de AEDA figura «{t}», que no es un CBU")
        plan.contar("con un CBU que no verifica (va a observaciones)")
        return None, None
    if RE_ALIAS.match(t):
        return None, t
    notas.append(f"dato de pago de AEDA sin interpretar: {t}")
    return None, None


def armar_proveedor(p: dict, destino: dict, plan: Plan) -> tuple[dict, list[str]]:
    notas = []
    pid = p["prest_id"]
    cuit = solo_digitos(p["cuit"])
    nombre = limpio(p["prest_nombre"]).upper()
    fantasia = limpio(p["prest_fantasia"])
    if normalizar(fantasia) == normalizar(nombre):
        fantasia = ""
    if not cuit_valido(cuit):
        notas.append("el CUIT no verifica el dígito de control")
        plan.contar("con CUIT inválido (entran con la nota)")

    letra_iva = limpio(p["iva"]).upper()
    condicion_iva = IVA_AEDA.get(letra_iva)
    if letra_iva and condicion_iva is None:
        notas.append(f"condición de IVA «{letra_iva}» de AEDA sin equivalente en ARCA")
        plan.contar("con una condición de IVA de AEDA sin equivalente")

    rga = limpio(p["rga"]).upper()
    ret_gan, regimen = 0, None
    if rga in REGIMEN_AEDA:
        if rg830.es_monotributista(condicion_iva):
            notas.append(f"AEDA le retenía Ganancias (tipo {rga}) pero es monotributista: no se le retiene")
            plan.contar("monotributistas con retención de Ganancias en AEDA (se quita)")
        else:
            ret_gan, regimen = 1, REGIMEN_AEDA[rga]
            plan.contar(f"con retención de Ganancias, régimen {regimen}")
            if regimen not in destino["regimenes"]:
                plan.contar(f"régimen {regimen} sin escala vigente en rg830_escala")
    elif rga not in SIN_RETENCION:
        notas.append(f"tipo de retención de Ganancias «{rga}» de AEDA sin equivalente")

    cbu, alias = _cbu_y_alias(p["cbu"], notas, plan)
    obs_aeda = limpio(p["observa"])
    observaciones = f"[AEDA adm_proveedor {pid}]"
    if notas:
        observaciones += " " + " ".join(n[0].upper() + n[1:] + "." for n in notas)
    if obs_aeda:
        observaciones += f" Observaciones de AEDA: {obs_aeda}"

    return {
        "cuit": cuit, "razon_social": nombre[:200], "nombre_fantasia": fantasia[:200] or None,
        "dom_calle": limpio(p["calle"]).upper()[:150] or None,
        "dom_cp": limpio(p["codpos"]).upper()[:10] or None,
        "dom_localidad": limpio(p["locali"]).upper()[:100] or None,
        "condicion_iva": condicion_iva,
        "ret_ganancias": ret_gan, "ret_ganancias_codigo_sir": regimen,
        "ret_iibb": 1 if p["rib"] else 0,
        "cbu": cbu, "cbu_alias": alias,
        "cheque_a_la_orden": limpio(p["alaorden"])[:100] or None,
        "moneda": "ARS", "activo": 1, "observaciones": observaciones,
    }, notas


def armar_plan(aeda: dict, destino: dict) -> Plan:
    plan = Plan()
    plan.contar("proveedores en AEDA", len(aeda["proveedores"]))
    plan.contar("personas de proveedores en adm_contactos", len(aeda["contactos"]))
    ids_aeda = {p["prest_id"] for p in aeda["proveedores"]}
    personas_por = {}
    for c in aeda["contactos"]:
        if c["prest_id"] not in ids_aeda:
            plan.contar("personas de un proveedor inexistente en AEDA")
            plan.anotar("omitido", prest_id=c["prest_id"], origen=f"adm_contactos {c['contacto_id']}",
                        nombre=limpio(c["nombre"]), nota="el proveedor no existe en adm_proveedor")
            continue
        personas_por.setdefault(c["prest_id"], []).append(c)
    con_principal = set(destino["con_principal"])
    rubro_id = destino["rubros"]["PROVEEDORES"]

    for p in aeda["proveedores"]:
        pid = p["prest_id"]
        cuit = solo_digitos(p["cuit"])
        nombre = limpio(p["prest_nombre"]).upper()
        if len(cuit) != 11:
            plan.contar("sin CUIT de 11 dígitos (no se importan)")
            plan.anotar("omitido", prest_id=pid, cuit=cuit, razon=nombre, nota="CUIT incompleto")
            continue

        existente = destino["ya"].get(pid) or destino["por_cuit"].get(cuit)
        if existente:
            plan.contar("ya estaban (se saltean; solo se agregan contactos que falten)")
            entidad = ("id", existente)
        else:
            prov, notas = armar_proveedor(p, destino, plan)
            # Rubro: el grupo de pasivo de AEDA; todos son «Proveedores».
            grupo = normalizar(p["grupo_pasivo"])
            prov["_rubro"] = destino["rubros"].get(grupo, rubro_id)
            concepto = limpio(p["concepto"])
            if concepto:
                clave = normalizar(concepto)
                if clave not in destino["conceptos"] and concepto not in plan.conceptos_nuevos:
                    plan.conceptos_nuevos.append(concepto)
                prov["_concepto"] = concepto
            else:
                prov["_concepto"] = None
                plan.contar("sin concepto de gasto en AEDA (quedan sin cuenta de gasto)")
            prov["_prest_id"] = pid
            plan.proveedores.append(prov)
            plan.contar("proveedores a crear")
            plan.anotar("crear", prest_id=pid, cuit=cuit, razon=nombre,
                        nota="; ".join(notas), concepto=concepto,
                        regimen=prov["ret_ganancias_codigo_sir"] or "")
            entidad = ("alta", pid)

        tel = limpio(p["telefono"])
        if limpio(p["fax"]):
            tel = f"{tel} / FAX {limpio(p['fax'])}".strip(" /")
        e = {"empre_id": pid, "razon": nombre, "telefono": tel, "email": p["email"]}
        nuevos = [c for c in contactos_de_empresa(e, personas_por.get(pid, []), cuit, entidad,
                                                  destino, plan,
                                                  marca_general=f"[AEDA adm_proveedor {pid}]")
                  if c["marca"] not in destino["marcas"]]
        if not nuevos:
            continue
        if entidad not in con_principal:
            min(nuevos, key=lambda c: (c["prioridad"], c["orden"]))["principal"] = 1
            con_principal.add(entidad)
        plan.contactos += nuevos
        plan.contar("contactos a crear", len(nuevos))
        for c in nuevos:
            plan.anotar("contacto", prest_id=pid, cuit=cuit, razon=nombre, origen=c["marca"],
                        nombre=c["nombre"], cargo=c["cargo"], email=c["email"],
                        telefono=c["telefono"], principal="sí" if c["principal"] else "")

    if plan.conceptos_nuevos:
        plan.contar("conceptos de gasto de AEDA que se agregan al catálogo", len(plan.conceptos_nuevos))
        for c in plan.conceptos_nuevos:
            plan.anotar("concepto nuevo", concepto=c, nota="con la imputación de " + CONCEPTO_PLANTILLA)
    return plan


# ─────────────────────────────────────────────────────────────────────────────
# Escritura
# ─────────────────────────────────────────────────────────────────────────────

COLUMNAS_CONTACTO = ("nombre", "cargo", "id_area_contacto", "telefono", "celular",
                     "email", "web", "principal", "observaciones")


def aplicar(cur, plan: Plan, destino: dict) -> None:
    conceptos = dict(destino["conceptos"])
    base = destino["plantilla"]
    for desc in plan.conceptos_nuevos:
        cur.execute("""INSERT INTO c_concepto_de_gastos
                           (descripcion, c_plan_de_cuentasId, c_especiesId, arca_tasa_ivaid, esliquidacion)
                       VALUES (%s, %s, %s, %s, 0)""",
                    (desc[:50], base["c_plan_de_cuentasId"], base["c_especiesId"], base["arca_tasa_ivaid"]))
        conceptos[normalizar(desc)] = cur.lastrowid

    nuevos_ids = {}
    for prov in plan.proveedores:
        valores = {k: v for k, v in prov.items() if not k.startswith("_")}
        cols = list(valores)
        cur.execute(f"INSERT INTO c_proveedores ({', '.join(cols)}) "
                    f"VALUES ({', '.join(['%s'] * len(cols))})", [valores[c] for c in cols])
        pid = cur.lastrowid
        nuevos_ids[prov["_prest_id"]] = pid
        movs.registrar_cambios(cur, pid, None, valores, tipo_movimiento="ALTA",
                               origen="IMPORTACION", origen_ref="importar_aeda_proveedores.py",
                               usuario="importación AEDA")
        cur.execute("INSERT INTO c_proveedores_cuentas_pasivo (id_proveedor, id_rubro_pasivo, "
                    "descripcion, moneda, predeterminada, activa) VALUES (%s, %s, 'Cuenta principal', "
                    "'ARS', 1, 1)", (pid, prov["_rubro"]))
        if prov["_concepto"]:
            cur.execute("INSERT INTO c_proveedores_cuentas_gasto (id_proveedor, id_concepto_gasto, "
                        "descripcion, predeterminada, activa) VALUES (%s, %s, 'Concepto principal', 1, 1)",
                        (pid, conceptos[normalizar(prov["_concepto"])]))

    for c in plan.contactos:
        tipo, valor = c["entidad"]
        entidad_id = valor if tipo == "id" else nuevos_ids[valor]
        cur.execute(f"""
            INSERT INTO s_contactos (entidad_tipo, entidad_id, {", ".join(COLUMNAS_CONTACTO)},
                                     activo, creado, actualizado)
            VALUES (%s, %s, {", ".join(["%s"] * len(COLUMNAS_CONTACTO))}, 1, NOW(), NOW())
        """, [ENTIDAD, entidad_id] + [c[k] for k in COLUMNAS_CONTACTO])


CAMPOS_INFORME = ["accion", "prest_id", "cuit", "razon", "regimen", "concepto", "origen",
                  "nombre", "cargo", "email", "telefono", "principal", "nota"]


def escribir_informe(plan: Plan, aplicado: bool, inicio: datetime):
    CARPETA_LOGS.mkdir(exist_ok=True)
    base = CARPETA_LOGS / f"importar_aeda_proveedores_{inicio:%Y%m%d_%H%M%S}"
    detalle, resumen = base.with_suffix(".csv"), base.with_suffix(".txt")
    with open(detalle, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_INFORME, delimiter=";", extrasaction="ignore")
        w.writeheader()
        # contactos_de_empresa anota con `empre_id`: acá es el prest_id.
        w.writerows({**f, "prest_id": f.get("prest_id", f.get("empre_id"))} for f in plan.informe)
    lineas = [f"Importación de proveedores AEDA → sindicato  {inicio:%d/%m/%Y %H:%M}",
              "APLICADA" if aplicado else "SIMULACIÓN — no se grabó nada", ""]
    lineas += [f"  {n:>6}  {k}" for k, n in plan.cuenta.items()]
    if plan.conceptos_nuevos:
        lineas += ["", "  Conceptos de gasto nuevos: " + ", ".join(plan.conceptos_nuevos)]
    lineas += ["", f"Detalle: {detalle.name}"]
    resumen.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return resumen


def main():
    parser = argparse.ArgumentParser(description="Proveedores desde AEDA.")
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
        if args.aplicar and (plan.proveedores or plan.contactos):
            conn.begin()
            try:
                with conn.cursor() as cur:
                    aplicar(cur, plan, destino)
                conn.commit()
            except Exception:
                conn.rollback()
                resumen = escribir_informe(plan, False, inicio)
                print(f"\n  Falló la importación; no se grabó nada. Plan en {resumen}\n")
                raise

    resumen = escribir_informe(plan, args.aplicar, inicio)
    print()
    print(resumen.read_text(encoding="utf-8"))
    if not args.aplicar:
        print("  Para grabar:  python importar_aeda_proveedores.py --aplicar\n")


if __name__ == "__main__":
    sys.exit(main())
