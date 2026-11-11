"""
importar_aeda_afiliados.py — Padrón de afiliados desde AEDA a la base `sindicato`.

Origen: la base `aeda` del SQL Server de origen (ver importar_aeda.py, que
resuelve la conexión). Carga, en una sola transacción:

1. `afi_benef` → `p_afiliados`: titulares y familiares, una fila por persona.
2. `afi_afixempre` → `p_relaciones_laborales`: qué empresa declara a cada uno.
3. `adm_contactos` con `ref_id = 'A'` (`ref_nro` = `ben_id`) → `s_contactos`,
   entidad `afiliado`, área «Personal».
4. Un movimiento de ALTA por afiliado en `p_afiliados_movimientos`, y uno de
   BAJA para los que AEDA tiene dados de baja, con origen IMPORTACION. Así la
   solapa de movimientos de la ficha arranca con la historia que se conoce.

Uso
---
    python importar_aeda_afiliados.py             simula y escribe el informe en logs/
    python importar_aeda_afiliados.py --aplicar   lo mismo, y lo graba

Requiere sql/afiliados_20261107.sql aplicado (amplía `domicilio_calle`). Si no
lo está, el script lo detecta y no arranca: con la columna en 20 caracteres la
importación cortaría a mitad de camino.

Decisiones sobre los datos de AEDA
----------------------------------
Nombre. AEDA guarda apellido y nombres en un solo campo («DIAZ RAIDAN MAYRA
CANDELA»). Partirlo con una regla falla justo con los apellidos compuestos, y
el error no se nota: queda un apellido «DIAZ» con toda la pinta de correcto.
Va entero a `apellido_nombres`, el único campo de nombre del padrón.

CUIL repetido. `p_afiliados` tiene un CUIL único. En AEDA se repite de dos
maneras distintas, y cada una se trata distinto:
  - La misma persona en dos grupos, casi siempre como titular en el suyo y
    como hijo en el de los padres. Queda una sola fila —la activa; entre
    activas, la de titular; después, la cargada más recientemente— y la otra
    pertenencia se anota en observaciones.
  - Dos personas con el mismo CUIL (mellizas, un cónyuge mal cargado). Entran
    las dos: una con el CUIL y la otra sin CUIL, con una nota. Se distinguen
    por el nombre: con un parecido de 0,85 o más se toman como la misma
    persona («VERGERIO LEONARDO DARTE» y «… DANTE» lo son).

CUIL inválido. Entra igual, con la observación. Un beneficiario que falta en
el padrón tiene más consecuencias que una empresa sin contactos, así que acá no
se rechaza; la ficha no deja volver a guardarlo hasta que se corrija.

Fechas en 01/01/1900: es el «vacío» de AEDA. Van como NULL.

El campo `aeda` de `afi_benef` no se importa. El catálogo `p_afiliado_atributo`
vino de la obra social con una marca «AEDA — Afiliado al Gremio», pero esta es
la base del gremio: acá todos lo son, y la marca no distingue nada.

Filas sin nombre, sin CUIL y sin documento: se descartan.

Se puede correr más de una vez: lo importado lleva su origen al principio de
`observaciones` («[AEDA afi_benef 4269]»), y lo que ya tiene marca se saltea.
"""

import argparse
import csv
import sys
from dataclasses import dataclass, field
from datetime import datetime, date
from difflib import SequenceMatcher

# importar_aeda carga el .env y trae la conexión a AEDA y la limpieza de
# teléfonos y mails. Reusarla es lo que hace que un mail mal escrito se
# corrija igual en una empresa que en un afiliado.
from importar_aeda import (CARPETA_LOGS, RE_MARCA, acomodar_campos, conexion_aeda,
                           limpiar_mails, limpio, normalizar, nota_original,
                           provincia_para, salir, separar_telefono, solo_digitos,
                           _filas)
from db import get_connection
from empleadores import cuit_valido     # CUIL y CUIT comparten el dígito verificador

ENTIDAD = "afiliado"
ANCHO_CALLE = 100       # el que deja sql/afiliados_20261107.sql
PARECIDO_MISMA_PERSONA = 0.85


# ─────────────────────────────────────────────────────────────────────────────
# Lectura
# ─────────────────────────────────────────────────────────────────────────────

def leer_aeda(cn) -> dict:
    cur = cn.cursor()
    benef = _filas(cur, """
        SELECT b.ben_id, b.cuil, b.ben_grupo AS grupo, b.par_id, b.ben_nombre AS nombre,
               b.tdoc_id, b.ben_doc AS doc, b.ben_sexo AS sexo, b.ecv_id, b.nac_id,
               b.ben_calle AS calle, b.ben_puerta AS puerta, b.ben_piso AS piso,
               b.ben_depto AS depto, b.localidad, b.cpostal, p.prov_nombre AS provincia,
               b.ben_disca AS disca, b.ben_obs AS obs, b.ben_fnac AS fnac,
               b.ben_falta AS falta, b.ben_fbaja AS fbaja, b.ben_fcarga AS fcarga,
               b.categoria_id, b.hijos, b.cbu
          FROM dbo.afi_benef b
          LEFT JOIN dbo.afi_provincia p ON p.prov_id = b.prov_id
         ORDER BY b.ben_id
    """)
    empleos = _filas(cur, """
        SELECT id, cuil, cuit, fechaingreso FROM dbo.afi_afixempre ORDER BY id
    """)
    contactos = _filas(cur, """
        SELECT contacto_id, ref_nro AS ben_id, nombre, cargo, telefono, email
          FROM dbo.adm_contactos
         WHERE ref_id = 'A'
         ORDER BY ref_nro, contacto_id
    """)
    cur.close()
    return {"benef": benef, "empleos": empleos, "contactos": contactos}


def leer_destino(cur) -> dict:
    cur.execute("""SELECT CHARACTER_MAXIMUM_LENGTH AS ancho FROM information_schema.columns
                    WHERE table_schema = DATABASE() AND table_name = 'p_afiliados'
                      AND column_name = 'domicilio_calle'""")
    ancho = (cur.fetchone() or {}).get("ancho") or 0
    if ancho < ANCHO_CALLE:
        salir(f"p_afiliados.domicilio_calle tiene {ancho} caracteres y AEDA necesita "
              f"{ANCHO_CALLE}. Correr antes sql/afiliados_20261107.sql.")

    cur.execute("SELECT id_afiliado, cuil, activo, observaciones FROM p_afiliados")
    por_cuil, por_ben = {}, {}
    for f in cur.fetchall():
        if f["cuil"]:
            por_cuil[f["cuil"]] = f
        m = RE_MARCA.match(f["observaciones"] or "")
        if m and m.group(0).startswith("[AEDA afi_benef "):
            por_ben[int(m.group(0)[16:-1])] = f

    cur.execute("SELECT id, CUIT FROM p_empresas")
    empresas = {int(f["CUIT"]): f["id"] for f in cur.fetchall()}

    cur.execute("SELECT codigo, nombre FROM p_provincia")
    provincias = {normalizar(f["nombre"]): (str(f["codigo"]), f["nombre"])
                  for f in cur.fetchall()}

    def codigos(sql):
        cur.execute(sql)
        return {f["codigo"] for f in cur.fetchall()}

    cur.execute("SELECT id FROM c_areas_contacto WHERE nombre = 'Personal' AND activo = 1")
    fila = cur.fetchone()
    id_area_personal = fila["id"] if fila else None

    # Sin parámetros: con argumentos, PyMySQL toma el `%` del LIKE como marcador.
    cur.execute("SELECT observaciones FROM p_relaciones_laborales "
                "WHERE observaciones LIKE '[AEDA %'")
    marcas_rel = {RE_MARCA.match(f["observaciones"]).group(0) for f in cur.fetchall()
                  if RE_MARCA.match(f["observaciones"] or "")}
    cur.execute("SELECT observaciones FROM s_contactos "
                "WHERE entidad_tipo = 'afiliado' AND observaciones LIKE '[AEDA %'")
    marcas_cto = {RE_MARCA.match(f["observaciones"]).group(0) for f in cur.fetchall()
                  if RE_MARCA.match(f["observaciones"] or "")}
    cur.execute("SELECT DISTINCT entidad_id FROM s_contactos "
                "WHERE entidad_tipo = 'afiliado' AND activo = 1 AND principal = 1")
    con_principal = {f["entidad_id"] for f in cur.fetchall()}

    return {
        "por_cuil": por_cuil, "por_ben": por_ben, "empresas": empresas,
        "provincias": provincias,
        "parentescos": codigos("SELECT codigo FROM p_parentesco"),
        "estados_civiles": codigos("SELECT codigo FROM p_estado_civil"),
        "nacionalidades": codigos("SELECT codigo FROM p_nacionalidad"),
        "tipos_doc": codigos("SELECT codigo FROM p_tipo_documento"),
        "id_area_personal": id_area_personal,
        "marcas_rel": marcas_rel, "marcas_cto": marcas_cto, "con_principal": con_principal,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Limpieza
# ─────────────────────────────────────────────────────────────────────────────

def fecha(valor) -> date | None:
    """Las fechas de AEDA, con el 01/01/1900 —su «vacío»— como NULL."""
    if valor is None:
        return None
    if isinstance(valor, datetime):
        valor = valor.date()
    return None if valor.year <= 1900 else valor


def entero(valor) -> int | None:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def cuil_de(texto) -> str | None:
    """Once dígitos que no sean todos iguales («00000000000» es un relleno)."""
    d = solo_digitos(limpio(texto))
    return d if len(d) == 11 and len(set(d)) > 1 else None


def parecido(a, b) -> float:
    return SequenceMatcher(None, normalizar(a), normalizar(b)).ratio()


def ddmmaaaa(f: date | None) -> str:
    return f.strftime("%d/%m/%Y") if f else ""


# ─────────────────────────────────────────────────────────────────────────────
# Plan
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Plan:
    afiliados: list[dict] = field(default_factory=list)
    relaciones: list[dict] = field(default_factory=list)
    contactos: list[dict] = field(default_factory=list)
    informe: list[dict] = field(default_factory=list)
    cuenta: dict = field(default_factory=dict)

    def contar(self, clave, n=1):
        self.cuenta[clave] = self.cuenta.get(clave, 0) + n

    def anotar(self, accion, **datos):
        self.informe.append({"accion": accion, **datos})


def _preferencia(b: dict):
    """Cuál fila de un CUIL repetido se queda: activa, titular, más reciente."""
    # `toordinal` y no `timestamp`: en Windows, `timestamp()` de una fecha
    # anterior a 1970 tira OSError, y AEDA está lleno de 01/01/1900.
    carga = fecha(b["fcarga"]) or date.min
    return (fecha(b["fbaja"]) is not None, entero(b["par_id"]) != 0,
            -carga.toordinal(), -b["ben_id"])


def armar_afiliado(b: dict, destino: dict, notas: list[str], sin_cuil=False) -> dict:
    """La fila de `p_afiliados` para un beneficiario de AEDA."""
    cuil_raw = limpio(b["cuil"])
    cuil = None if sin_cuil else cuil_de(cuil_raw)
    if not sin_cuil:
        if cuil_raw and not cuil:
            notas.append(f"CUIL en AEDA no válido: «{cuil_raw}».")
        elif cuil and not cuit_valido(cuil):
            notas.append("El CUIL no verifica el dígito de control.")

    par = entero(b["par_id"])
    if par not in destino["parentescos"]:
        notas.append(f"Parentesco en AEDA: {b['par_id']}.")
        par = 10
    grupo = cuil_de(b["grupo"])
    if par == 0:
        if limpio(b["grupo"]) and grupo != cuil and cuil:
            notas.append(f"Grupo en AEDA: «{limpio(b['grupo'])}».")
        cuil_titular = cuil or grupo
    else:
        if limpio(b["grupo"]) and not grupo:
            notas.append(f"Grupo en AEDA no válido: «{limpio(b['grupo'])}».")
        cuil_titular = grupo

    doc_raw = limpio(b["doc"])
    doc = solo_digitos(doc_raw)
    if not doc_raw.isdigit() or not (1 <= len(doc) <= 8) or int(doc) == 0:
        derivado = cuil[2:10] if cuil else ""
        if doc_raw and doc_raw != "0":
            notas.append(f"Documento en AEDA: «{doc_raw}»"
                         + (" — se tomó del CUIL." if derivado else "."))
        doc = derivado

    nombre = limpio(b["nombre"])
    sexo = limpio(b["sexo"]).upper()
    if sexo and sexo not in ("M", "F", "X"):
        notas.append(f"Sexo en AEDA: «{sexo}».")
    nac = entero(b["nac_id"])
    if nac is not None and nac not in destino["nacionalidades"]:
        notas.append(f"Nacionalidad en AEDA: código {nac}.")
        nac = None
    ecv = entero(b["ecv_id"])
    cbu_raw = limpio(b["cbu"])
    cbu = solo_digitos(cbu_raw)
    if cbu_raw and len(cbu) != 22:
        notas.append(f"CBU en AEDA no válido: «{cbu_raw}».")
    prov_id, _ = provincia_para(b["provincia"], destino["provincias"])
    cp = entero(b["cpostal"])
    tdoc = limpio(b["tdoc_id"]).upper()

    extra = []
    if entero(b["categoria_id"]):
        extra.append(f"Categoría en AEDA: {entero(b['categoria_id'])}.")
    if entero(b["hijos"]):
        extra.append(f"Hijos declarados en AEDA: {entero(b['hijos'])}.")
    if limpio(b["obs"]):
        extra.append(f"Obs. AEDA: {limpio(b['obs'])}")

    baja = fecha(b["fbaja"])
    return {
        "ben_id":           b["ben_id"],
        "cod_obra_social":  "",
        "cuit_empleador":   None,           # se completa con afi_afixempre
        "cuil_titular":     cuil_titular,
        "cod_parentesco":   par,
        "cuil":             cuil,
        "tipo_documento":   tdoc if tdoc in destino["tipos_doc"] else "DU",
        "nro_documento":    doc,
        "apellido_nombres": (nombre or "(sin nombre en AEDA)")[:100],
        "sexo":             sexo if sexo in ("M", "F", "X") else None,
        "estado_civil":     ecv if ecv in destino["estados_civiles"] else None,
        "nacionalidad":     nac,
        "domicilio_calle":  limpio(b["calle"])[:ANCHO_CALLE] or None,
        "domicilio_numero": limpio(b["puerta"])[:5] or None,
        "domicilio_piso":   limpio(b["piso"])[:4] or None,
        "domicilio_depto":  limpio(b["depto"])[:4] or None,
        "localidad":        limpio(b["localidad"])[:20] or None,
        "codigo_postal":    str(cp) if cp and cp > 0 else None,
        "provincia":        int(prov_id) if prov_id else None,
        "cbu_pago":         cbu if len(cbu) == 22 else None,
        "incapacidad":      1 if limpio(b["disca"]).upper() == "S" else 0,
        "fecha_nacimiento": fecha(b["fnac"]),
        "fecha_alta":       fecha(b["falta"]),
        "fecha_baja":       baja,
        "activo":           0 if baja else 1,
        "_extra":           extra,
    }


def armar_plan(aeda: dict, destino: dict, hoy: datetime) -> Plan:
    plan = Plan()
    plan.contar("beneficiarios en AEDA", len(aeda["benef"]))

    # ── Personas ─────────────────────────────────────────────────────────────
    validos, descartados = [], 0
    for b in aeda["benef"]:
        if not (limpio(b["nombre"]) or cuil_de(b["cuil"]) or solo_digitos(limpio(b["doc"])).strip("0")):
            descartados += 1
            plan.anotar("descartado", ben_id=b["ben_id"], nota="sin nombre, CUIL ni documento")
            continue
        validos.append(b)
    plan.contar("filas vacías descartadas", descartados)

    por_cuil: dict[str, list[dict]] = {}
    for b in validos:
        c = cuil_de(b["cuil"])
        if c:
            por_cuil.setdefault(c, []).append(b)

    # ben_id de AEDA → ben_id de la fila que lo representa (él mismo, salvo
    # cuando es la misma persona repetida y se unificó con otra).
    representa: dict[int, int] = {b["ben_id"]: b["ben_id"] for b in validos}
    sin_cuil: set[int] = set()
    notas_extra: dict[int, list[str]] = {}

    for c, filas in por_cuil.items():
        if len(filas) == 1:
            continue
        filas.sort(key=_preferencia)
        queda = filas[0]
        # Si son personas distintas, el CUIL es de la que coincide con el sexo
        # que indica el prefijo (20 masculino, 27 femenino), cuando eso
        # desempata: entre la cónyuge y el titular cargados con el mismo CUIL
        # 27, es de ella.
        sexo_cuil = {"20": "M", "27": "F"}.get(c[:2])
        distintas = [f for f in filas[1:] if parecido(f["nombre"], queda["nombre"]) < PARECIDO_MISMA_PERSONA]
        if sexo_cuil and distintas and limpio(queda["sexo"]).upper() != sexo_cuil:
            coincide = [f for f in distintas if limpio(f["sexo"]).upper() == sexo_cuil]
            if len(coincide) == 1:
                filas.remove(coincide[0])
                filas.insert(0, coincide[0])
                queda = coincide[0]
        for otra in filas[1:]:
            par = entero(otra["par_id"])
            if parecido(otra["nombre"], queda["nombre"]) >= PARECIDO_MISMA_PERSONA:
                representa[otra["ben_id"]] = queda["ben_id"]
                baja = fecha(otra["fbaja"])
                notas_extra.setdefault(queda["ben_id"], []).append(
                    f"En AEDA también figura en el grupo {limpio(otra['grupo'])} con "
                    f"parentesco {par} (afi_benef {otra['ben_id']}"
                    + (f", baja {ddmmaaaa(baja)}" if baja else "") + ").")
                plan.contar("CUIL repetidos: misma persona, unificada en una fila")
                plan.anotar("unificado", ben_id=otra["ben_id"], cuil=c,
                            nombre=limpio(otra["nombre"]), parentesco=par,
                            grupo=limpio(otra["grupo"]),
                            nota=f"misma persona que afi_benef {queda['ben_id']}")
            else:
                sin_cuil.add(otra["ben_id"])
                notas_extra.setdefault(otra["ben_id"], []).append(
                    f"CUIL {c} repetido en AEDA con «{limpio(queda['nombre'])}» "
                    f"(afi_benef {queda['ben_id']}); se cargó sin CUIL.")
                plan.contar("CUIL repetidos: personas distintas, la segunda sin CUIL")

    # ── Empleo de cada CUIL (el último ingreso) ──────────────────────────────
    empleo_de: dict[str, dict] = {}
    for x in aeda["empleos"]:
        c = cuil_de(x["cuil"])
        if not c:
            continue
        previo = empleo_de.get(c)
        if previo is None or (fecha(x["fechaingreso"]) or date.min) >= (fecha(previo["fechaingreso"]) or date.min):
            empleo_de[c] = x

    # ── Altas ────────────────────────────────────────────────────────────────
    # clave de afiliado: ("id", id_afiliado) si ya está, ("alta", ben_id) si entra ahora
    clave_de: dict[int, tuple] = {}
    activo_de: dict[tuple, int] = {}
    nombre_de: dict[tuple, str] = {}
    cuil_a_clave: dict[str, tuple] = {}

    for b in validos:
        bid = b["ben_id"]
        if representa[bid] != bid:
            continue

        existente = destino["por_ben"].get(bid)
        c = None if bid in sin_cuil else cuil_de(b["cuil"])
        if existente is None and c:
            existente = destino["por_cuil"].get(c)
        if existente is not None:
            clave = ("id", existente["id_afiliado"])
            clave_de[bid] = clave
            activo_de[clave] = existente["activo"]
            nombre_de[clave] = limpio(b["nombre"])
            if c:
                cuil_a_clave[c] = clave
            plan.contar("afiliados que ya estaban en p_afiliados")
            continue

        notas: list[str] = []
        fila = armar_afiliado(b, destino, notas, sin_cuil=bid in sin_cuil)
        notas += notas_extra.get(bid, [])
        if fila["cod_parentesco"] == 0 and fila["cuil"] in empleo_de:
            cuit = cuil_de(empleo_de[fila["cuil"]]["cuit"])
            fila["cuit_empleador"] = cuit

        marca = f"[AEDA afi_benef {bid}]"
        fila["observaciones"] = " ".join(
            [marca, f"Importado de AEDA el {hoy:%d/%m/%Y}."] + notas + fila.pop("_extra")
        )
        plan.afiliados.append(fila)
        clave = ("alta", bid)
        clave_de[bid] = clave
        activo_de[clave] = fila["activo"]
        nombre_de[clave] = fila["apellido_nombres"]
        if fila["cuil"]:
            cuil_a_clave[fila["cuil"]] = clave
        plan.contar("afiliados nuevos")
        if not fila["activo"]:
            plan.contar("  de ellos, con baja en AEDA")
        if notas:
            plan.contar("  de ellos, con alguna observación sobre los datos")
        plan.anotar("alta afiliado", ben_id=bid, cuil=fila["cuil"] or "",
                    nombre=fila["apellido_nombres"], parentesco=fila["cod_parentesco"],
                    grupo=fila["cuil_titular"] or "",
                    estado="activo" if fila["activo"] else f"baja {ddmmaaaa(fila['fecha_baja'])}",
                    nota=" ".join(notas))

    # ── Relaciones laborales ─────────────────────────────────────────────────
    for x in aeda["empleos"]:
        marca = f"[AEDA afi_afixempre {x['id']}]"
        c, cuit = cuil_de(x["cuil"]), cuil_de(x["cuit"])
        clave = cuil_a_clave.get(c) if c else None
        if marca in destino["marcas_rel"]:
            plan.contar("relaciones laborales importadas en una corrida anterior")
            continue
        if not clave or not cuit:
            plan.contar("relaciones laborales sin afiliado o con CUIT inválido")
            plan.anotar("omitida relación", cuil=limpio(x["cuil"]), cuit=limpio(x["cuit"]),
                        origen=f"afi_afixempre {x['id']}",
                        nota="el CUIL no está en afi_benef" if not clave else "CUIT inválido")
            continue
        plan.relaciones.append({
            "clave": clave, "cuil": c, "cuit_empleador": cuit,
            "id_empleador": destino["empresas"].get(int(cuit)),
            "fecha_inicio": fecha(x["fechaingreso"]),
            # AEDA no guarda el egreso: la relación sigue el estado del afiliado.
            "estado": "activa" if activo_de.get(clave) else "inactiva",
            "observaciones": marca,
        })
    plan.contar("relaciones laborales nuevas", len(plan.relaciones))
    plan.contar("  de ellas, con una empresa que no está en p_empresas",
                sum(1 for r in plan.relaciones if r["id_empleador"] is None))

    # ── Contactos ────────────────────────────────────────────────────────────
    por_clave: dict[tuple, list[dict]] = {}
    for c in aeda["contactos"]:
        cid = c["contacto_id"]
        bid = representa.get(c["ben_id"])
        clave = clave_de.get(bid) if bid else None
        if clave is None:
            plan.contar("contactos de un beneficiario inexistente o descartado")
            plan.anotar("omitido contacto", ben_id=c["ben_id"], origen=f"adm_contactos {cid}",
                        nombre=limpio(c["nombre"]), nota="ref_nro no está en afi_benef")
            continue

        tel_txt, mail_txt, nombre_en_mail = acomodar_campos(c["telefono"], c["email"])
        telefono, celular = separar_telefono(tel_txt)
        mails, web, sobrante = limpiar_mails(mail_txt)
        nota = nota_original(c["telefono"], c["email"], tel_txt, mail_txt, bool(sobrante))
        if not (telefono or celular or mails or web or nota):
            plan.contar("contactos vacíos (sin teléfono ni mail)")
            continue
        if nota:
            plan.contar("contactos con teléfono o mail reacomodado (original en observaciones)")

        nombre = limpio(c["nombre"]) or nombre_en_mail or nombre_de[clave]
        for i, mail in enumerate(mails or [None]):
            marca = f"[AEDA adm_contactos {cid}]" if i == 0 else \
                    f"[AEDA adm_contactos {cid} mail {i + 1}]"
            if marca in destino["marcas_cto"]:
                plan.contar("contactos importados en una corrida anterior")
                continue
            por_clave.setdefault(clave, []).append({
                "clave": clave, "nombre": nombre[:150],
                "cargo": limpio(c["cargo"])[:100] or None,
                "id_area_contacto": destino["id_area_personal"],
                "telefono": telefono if i == 0 else None,
                "celular": celular if i == 0 else None,
                "email": mail, "web": web if i == 0 else None,
                "principal": 0,
                "observaciones": f"{marca} {nota if (nota and i == 0) else ''}".strip()[:300],
                "orden": (0 if mail else 1, cid, i),
            })

    for clave, lista in por_clave.items():
        if not (clave[0] == "id" and clave[1] in destino["con_principal"]):
            min(lista, key=lambda x: x["orden"])["principal"] = 1
        plan.contactos += lista
    plan.contar("contactos nuevos", len(plan.contactos))
    return plan


# ─────────────────────────────────────────────────────────────────────────────
# Aplicación
# ─────────────────────────────────────────────────────────────────────────────

COLUMNAS_AFILIADO = [
    "cod_obra_social", "cuit_empleador", "cuil_titular", "cod_parentesco", "cuil",
    "tipo_documento", "nro_documento", "apellido_nombres", "sexo", "estado_civil",
    "nacionalidad", "domicilio_calle", "domicilio_numero", "domicilio_piso",
    "domicilio_depto", "localidad", "codigo_postal", "provincia", "cbu_pago",
    "incapacidad", "fecha_nacimiento", "fecha_alta", "fecha_baja", "activo",
    "observaciones",
]


def aplicar(cur, plan: Plan) -> int:
    """Graba el plan. Devuelve cuántos movimientos de auditoría escribió."""
    ids: dict[tuple, int] = {}
    movimientos = []
    for a in plan.afiliados:
        cur.execute(
            f"INSERT INTO p_afiliados ({', '.join(COLUMNAS_AFILIADO)}) "
            f"VALUES ({', '.join(['%s'] * len(COLUMNAS_AFILIADO))})",
            [a[k] for k in COLUMNAS_AFILIADO])
        id_afiliado = cur.lastrowid
        ids[("alta", a["ben_id"])] = id_afiliado

        ref = f"AEDA afi_benef {a['ben_id']}"
        # «sí»/«no» y no 1/0: es como los escribe la pantalla (afiliados._legible),
        # y la solapa de movimientos los muestra tal cual.
        movimientos.append((id_afiliado, a["cuil"], a["fecha_alta"], "ALTA", ref, a["ben_id"],
                            None, "sí", "Alta importada de AEDA"))
        if not a["activo"]:
            movimientos.append((id_afiliado, a["cuil"], a["fecha_baja"], "BAJA", ref,
                                a["ben_id"], "sí", "no", "Baja registrada en AEDA"))

    def id_de(clave):
        return clave[1] if clave[0] == "id" else ids[clave]

    cur.executemany("""
        INSERT INTO p_afiliados_movimientos
            (id_afiliado, cuil, fecha_vigencia, tipo_movimiento, origen, origen_ref,
             id_origen, campo, campo_label, valor_anterior, valor_actual,
             usuario, observaciones)
        VALUES (%s, %s, %s, %s, 'IMPORTACION', %s, %s, 'activo', 'Activo', %s, %s,
                'importar_aeda_afiliados', %s)
    """, movimientos)

    cur.executemany("""
        INSERT INTO p_relaciones_laborales
            (cuil, cuit_empleador, id_empleador, fecha_inicio, estado, observaciones)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, [(r["cuil"], r["cuit_empleador"], r["id_empleador"], r["fecha_inicio"],
           r["estado"], r["observaciones"]) for r in plan.relaciones])

    cur.executemany("""
        INSERT INTO s_contactos
            (entidad_tipo, entidad_id, nombre, cargo, id_area_contacto, telefono, celular,
             email, web, principal, observaciones, activo, creado, actualizado)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, NOW(), NOW())
    """, [(ENTIDAD, id_de(c["clave"]), c["nombre"], c["cargo"], c["id_area_contacto"],
           c["telefono"], c["celular"], c["email"], c["web"], c["principal"],
           c["observaciones"]) for c in plan.contactos])
    return len(movimientos)


# ─────────────────────────────────────────────────────────────────────────────
# Informe
# ─────────────────────────────────────────────────────────────────────────────

CAMPOS_INFORME = ["accion", "ben_id", "cuil", "nombre", "parentesco", "grupo",
                  "estado", "cuit", "origen", "nota"]


def escribir_informe(plan: Plan, aplicado: bool, inicio: datetime):
    CARPETA_LOGS.mkdir(exist_ok=True)
    base = CARPETA_LOGS / f"importar_aeda_afiliados_{inicio:%Y%m%d_%H%M%S}"
    detalle, resumen = base.with_suffix(".csv"), base.with_suffix(".txt")
    with open(detalle, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_INFORME, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(plan.informe)
    lineas = [f"Importación de afiliados AEDA → sindicato  {inicio:%d/%m/%Y %H:%M}",
              "APLICADA" if aplicado else "SIMULACIÓN — no se grabó nada", ""]
    lineas += [f"  {n:>6}  {k}" for k, n in plan.cuenta.items()]
    lineas += ["", f"Detalle: {detalle.name}"]
    resumen.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return resumen


def main():
    parser = argparse.ArgumentParser(description="Padrón de afiliados desde AEDA.")
    parser.add_argument("--aplicar", action="store_true",
                        help="grabar en la base (sin esto, solo simula)")
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
        plan = armar_plan(aeda, destino, inicio)

        if args.aplicar and (plan.afiliados or plan.relaciones or plan.contactos):
            # Todo o nada: con afiliados cargados y sus contactos a medias, la
            # segunda corrida no sabría qué faltó.
            conn.begin()
            try:
                with conn.cursor() as cur:
                    n = aplicar(cur, plan)
                conn.commit()
                plan.contar("movimientos de auditoría escritos", n)
            except Exception:
                conn.rollback()
                resumen = escribir_informe(plan, False, inicio)
                print(f"\n  Falló la importación; no se grabó nada. Plan en {resumen}\n")
                raise

    resumen = escribir_informe(plan, args.aplicar, inicio)
    print()
    print(resumen.read_text(encoding="utf-8"))
    if not args.aplicar:
        print("  Para grabar:  python importar_aeda_afiliados.py --aplicar\n")


if __name__ == "__main__":
    sys.exit(main())
