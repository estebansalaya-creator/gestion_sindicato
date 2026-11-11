"""
importar_aeda.py — Empleadores y sus contactos desde AEDA a la base `sindicato`.

AEDA es el sistema viejo del sindicato: la base `aeda` del SQL Server de origen.
De ahí salen dos cosas:

1. Los empleadores de `afi_empresas` que todavía no están en `p_empresas`.
   `p_empresas` se copió de `contable` —el padrón de la obra social— y una parte
   grande de los empleadores de AEDA no figura ahí.
2. Los contactos de los empleadores, hacia `s_contactos`. Vienen de dos lados:
   - `adm_contactos` con `ref_id = 'E'`: personas, con `ref_nro` = `empre_id`.
     Casi todas tienen cargo «PAGOS».
   - `emp_telefono` y `emp_email` de `afi_empresas`: los datos generales de la
     empresa, que se cargan como un contacto más a nombre de la razón social,
     salvo que repitan los de una persona de la misma empresa.

Uso
---
    python importar_aeda.py             simula: lee todo, arma el plan y escribe el informe
    python importar_aeda.py --aplicar   lo mismo, y además lo graba en una sola transacción

La simulación no escribe nada en la base. El informe queda en `logs/` en las dos
modalidades: conviene leerlo antes de aplicar.

Se puede correr más de una vez
------------------------------
Cada fila importada lleva su origen al principio de `observaciones`:
`[AEDA afi_empresas 755]` o `[AEDA adm_contactos 2730]`. Una segunda corrida
saltea lo que ya tiene marca, aunque después se lo haya dado de baja: la baja
lógica es una decisión de alguien, y reimportar la desharía en silencio. La
pantalla de contactos no edita `observaciones`, así que la marca sobrevive a
las modificaciones.

Las empresas no necesitan marca para esto: se cruzan por CUIT, que es único en
`p_empresas`. La llevan igual, para poder saber después cuáles entraron por acá.

Qué NO hace
-----------
- No modifica las empresas que ya estaban en `p_empresas`: solo les agrega
  contactos.
- No da de alta CUIT que no pasan el dígito verificador. El ABM no dejaría
  volver a guardar esa empresa; se listan en el informe para corregirlos.
- No toca el principal de una empresa que ya tenía uno.
"""

import argparse
import csv
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Contra `__file__` y no contra el directorio de trabajo: el script se corre a
# mano desde cualquier lado, y el .env tiene que ser siempre el de al lado.
load_dotenv(Path(__file__).with_name(".env"))

from contactos import RE_EMAIL          # noqa: E402  — la misma regla que la pantalla
from db import get_connection           # noqa: E402
from empleadores import cuit_valido     # noqa: E402


#: Base de origen. Fija, por la misma razón que `DB_NAME` en db.py: el servidor
#: tiene también la base `oseda`, con tablas del mismo nombre (`afi_empresas`
#: incluida), y una consulta contra la base equivocada no falla — devuelve
#: otras empresas.
AEDA_DB = "aeda"

ENTIDAD = "empresa"     # `entidad_tipo` de los empleadores, como en contactos.ENTIDADES

CARPETA_LOGS = Path(__file__).with_name("logs")


# ─────────────────────────────────────────────────────────────────────────────
# Lectura de AEDA
# ─────────────────────────────────────────────────────────────────────────────

def conexion_aeda():
    """
    Conexión de solo lectura a la base `aeda`.

    Usa los mismos datos que el conector `sqlserver-origen`: la IP con el puerto
    (`IP,1433`) y el login de solo lectura `mcp_lectura`. Con el puerto escrito
    el driver va directo y no depende del SQL Browser; con `SERVIDOR\\INSTANCIA`
    lo necesita, y falla con «Error Locating Server/Instance Specified».

    Sin SIND_AEDA_USER intenta autenticación de Windows.
    """
    try:
        import pyodbc
    except ImportError:
        salir("Falta pyodbc. Instalarlo con:  pip install pyodbc")

    servidor = os.getenv("SIND_AEDA_SERVER", "").strip()
    if not servidor:
        salir("Falta SIND_AEDA_SERVER en el .env: la IP del conector sqlserver-origen, "
              "con el puerto (IP,1433).")

    driver = os.getenv("SIND_AEDA_DRIVER", "ODBC Driver 17 for SQL Server").strip()
    partes = [f"DRIVER={{{driver}}}", f"SERVER={servidor}", f"DATABASE={AEDA_DB}"]
    usuario = os.getenv("SIND_AEDA_USER", "").strip()
    if usuario:
        partes += [f"UID={usuario}", f"PWD={os.getenv('SIND_AEDA_PASS', '')}"]
    else:
        partes.append("Trusted_Connection=yes")

    try:
        cn = pyodbc.connect(";".join(partes), readonly=True, timeout=15)
    except pyodbc.Error as e:
        salir(f"No se pudo conectar a {servidor}/{AEDA_DB}: {e}")

    # Los `varchar` de AEDA se piden ya convertidos a UTF-16 por el driver. Con
    # la decodificación por defecto, según la versión de pyodbc, «PEÑA» llega
    # como «PE�A» o rompe con UnicodeDecodeError.
    cn.setdecoding(pyodbc.SQL_CHAR, encoding="utf-16le", ctype=pyodbc.SQL_WCHAR)
    return cn


def _filas(cur, sql: str) -> list[dict]:
    cur.execute(sql)
    columnas = [d[0] for d in cur.description]
    return [dict(zip(columnas, fila)) for fila in cur.fetchall()]


def leer_aeda(cn) -> dict:
    cur = cn.cursor()
    empresas = _filas(cur, """
        SELECT e.empre_id, e.emp_Cuit AS cuit, e.emp_raz AS razon,
               e.emp_calle AS calle, e.emp_locali AS localidad,
               p.prov_nombre AS provincia, e.emp_codpos AS cp,
               e.emp_domest AS domest, e.emp_locest AS locest,
               e.emp_obs AS obs, e.emp_telefono AS telefono, e.emp_email AS email,
               e.emp_activa AS activa, e.emp_inicio AS inicio
          FROM dbo.afi_empresas e
          LEFT JOIN dbo.afi_provincia p ON p.prov_id = e.prov_id
         ORDER BY e.empre_id
    """)
    contactos = _filas(cur, """
        SELECT contacto_id, ref_nro AS empre_id, nombre, cargo, telefono, email
          FROM dbo.adm_contactos
         WHERE ref_id = 'E'
         ORDER BY ref_nro, contacto_id
    """)
    cur.close()
    return {"empresas": empresas, "contactos": contactos}


# ─────────────────────────────────────────────────────────────────────────────
# Lectura del destino
# ─────────────────────────────────────────────────────────────────────────────

RE_MARCA = re.compile(r"^\[AEDA [^\]]+\]")


def leer_destino(cur) -> dict:
    cur.execute("SELECT id, CUIT FROM p_empresas")
    empresas = {int(f["CUIT"]): f["id"] for f in cur.fetchall()}

    cur.execute("SELECT codigo, nombre FROM p_provincia")
    provincias = {normalizar(f["nombre"]): (str(f["codigo"]), f["nombre"])
                  for f in cur.fetchall()}

    cur.execute("SELECT id, nombre FROM c_areas_contacto WHERE activo = 1")
    areas = {f["nombre"]: f["id"] for f in cur.fetchall()}

    # Sin parámetros a propósito: con argumentos, PyMySQL interpreta el `%`
    # del LIKE como marcador de sustitución.
    cur.execute("SELECT observaciones FROM s_contactos "
                "WHERE entidad_tipo = 'empresa' AND observaciones LIKE '[AEDA %'")
    marcas = set()
    for f in cur.fetchall():
        m = RE_MARCA.match(f["observaciones"] or "")
        if m:
            marcas.add(m.group(0))

    cur.execute("SELECT DISTINCT entidad_id FROM s_contactos "
                "WHERE entidad_tipo = 'empresa' AND activo = 1 AND principal = 1")
    con_principal = {f["entidad_id"] for f in cur.fetchall()}

    return {"empresas": empresas, "provincias": provincias, "areas": areas,
            "marcas": marcas, "con_principal": con_principal}


# ─────────────────────────────────────────────────────────────────────────────
# Limpieza de datos
# ─────────────────────────────────────────────────────────────────────────────

def limpio(valor) -> str:
    """Texto sin espacios de más. Los `char` de AEDA vienen rellenos a la derecha."""
    if valor is None:
        return ""
    return re.sub(r"\s+", " ", str(valor)).strip()


def normalizar(valor) -> str:
    """Para comparar: sin tildes, en mayúsculas, espacios simples."""
    t = unicodedata.normalize("NFKD", limpio(valor))
    return "".join(c for c in t if not unicodedata.combining(c)).upper()


def solo_digitos(valor) -> str:
    return re.sub(r"\D", "", valor or "")


def limpiar_mails(texto) -> tuple[list[str], str | None, str | None]:
    """
    Separa los mails de un campo de AEDA.

    Devuelve `(mails, web, original)`: las direcciones válidas —sin repetir, en
    minúscula—, un sitio web si lo había, y el texto original completo cuando
    quedó algo que no es ninguna de las dos cosas. Ese original va tal cual a
    observaciones: un nombre anotado al lado del mail («ctc: yesica chavez»),
    una indicación («- no copiar») o una dirección cortada a los 50 caracteres
    no se pueden corregir con una regla, y descartarlos pierde la pista.

    Casos reales de AEDA detrás de cada paso:
      «pereyra @netex.com.ar»               espacio pegado a la arroba
      «dbusca@speedy .com.ar»               espacio antes del punto
      «Aime Perrone <aime@oapce.com.ar>»    nombre y dirección entre <>
      «a@x.com.ar/b@x.com.ar»               varias, con / o espacio
      «www.asapce.com»                      el sitio en lugar del mail
    """
    original = limpio(texto)
    if not original:
        return [], None, None

    t = re.sub(r"\s*@\s*", "@", original)
    t = re.sub(r"\s+\.(?=[A-Za-z])", ".", t)

    mails, web, sobrante = [], None, False
    for tok in re.split(r"[\s;,/<>()]+", t):
        tok = tok.strip(".:-'\"").lower()
        if tok in ("", "y", "e", "o"):
            continue
        if RE_EMAIL.match(tok):
            if tok not in mails:
                mails.append(tok)
        elif tok.startswith("www.") and web is None:
            web = tok
        else:
            sobrante = True
    return mails, web, (original if sobrante else None)


#: «Aime Perrone <aime.perrone@oapce.com.ar>»: nombre y dirección en el campo de mail.
RE_NOMBRE_Y_MAIL = re.compile(r"^\s*([^<>@]*?)\s*<\s*([^<>]+@[^<>]+?)\s*>\s*$")

#: Un mail escrito en el campo del teléfono.
RE_MAIL_SUELTO = re.compile(r"[^\s@;,/<>()]+@[^\s@;,/<>()]+\.[^\s@;,/<>()]+")

#: Un teléfono escrito en el campo del mail: solo dígitos y separadores.
RE_SOLO_TELEFONO = re.compile(r"[\d\s\-/().+]+")


def acomodar_campos(telefono, email) -> tuple[str, str, str]:
    """
    Devuelve `(telefono, email, nombre)` con lo que estaba en el campo equivocado
    puesto en su lugar. Casos reales de AEDA:

      tel «5032-1190 al 1192 daniel@languenari.com»   mail «5276-9785»
      mail «Aime Perrone <aime.perrone@oapce.com.ar>»
    """
    tel, mail, nombre = limpio(telefono), limpio(email), ""

    m = RE_NOMBRE_Y_MAIL.match(mail)
    if m:
        nombre, mail = m.group(1).strip(" \"'"), m.group(2)

    # Primero se separa lo que cada campo tiene del otro, y recién después se
    # cruza: al revés, el mail que venía en el teléfono le agrega una «@» al
    # campo de mail y el número que estaba ahí ya no se reconoce.
    sueltos = RE_MAIL_SUELTO.findall(tel)
    for s in sueltos:
        tel = tel.replace(s, " ")
    tel = limpio(tel).strip(" -/;,")

    if mail and "@" not in mail and RE_SOLO_TELEFONO.fullmatch(mail) \
            and len(solo_digitos(mail)) >= 6:
        junto = f"{tel} / {mail}" if tel else mail
        if len(junto) <= 50:            # el ancho de `s_contactos.telefono`
            tel, mail = junto, ""

    if sueltos:
        mail = " ".join([mail] + sueltos).strip()

    return tel, mail, nombre


def nota_original(tel0, mail0, tel, mail, sin_interpretar: bool) -> str | None:
    """
    La nota con el texto de AEDA tal cual, cuando el contacto no lo refleja
    entero: porque algo se cambió de campo o porque quedó texto sin interpretar.
    """
    tel0, mail0 = limpio(tel0), limpio(mail0)
    if (tel, mail) != (tel0, mail0):
        partes = [f"teléfono «{tel0}»" if tel0 else "", f"mail «{mail0}»" if mail0 else ""]
        return "Original en AEDA: " + ", ".join(p for p in partes if p) + "."
    if sin_interpretar:
        return f"Mail original en AEDA: «{mail0}»."
    return None


RE_CEL = re.compile(r"\bCEL(?:ULAR)?\b\.?:?", re.IGNORECASE)


def separar_telefono(texto) -> tuple[str | None, str | None]:
    """
    Teléfono y celular. Se separan solo cuando AEDA lo escribe («4574-5191 CEL
    15 5730-3907»): adivinar por el número confunde fijos y móviles del AMBA,
    que empiezan igual.
    """
    t = limpio(texto)
    if not t:
        return None, None
    m = RE_CEL.search(t)
    if not m:
        return t, None
    tel = t[:m.start()].strip(" -/;,") or None
    cel = t[m.end():].strip(" -/;,") or None
    return tel, cel


def area_para(cargo) -> str | None:
    """
    Área de `c_areas_contacto` según el cargo de AEDA.

    «PAGOS» va a Cobranzas porque el catálogo define cada área por lo que
    recibe —Cobranzas: «Recibe recibos y avisos de cobro»— y eso es lo que el
    sindicato le manda a esa persona. Que en la empresa se llame «pagos» es la
    misma tarea vista desde la otra punta.
    """
    c = normalizar(cargo)
    if c.startswith("PAGO"):
        return "Cobranzas"
    if c in ("CONTADOR", "ESTUDIO CONTABLE") or c.startswith("JEFE DE ADM"):
        return "Administración"
    return None


def provincia_para(nombre_aeda, provincias: dict) -> tuple[str | None, str | None]:
    """`(codigo, nombre)` de `p_provincia`, el mismo par que guarda el ABM."""
    n = normalizar(nombre_aeda)
    if not n:
        return None, None
    # AEDA distingue «BUENOS AIRES - CONURBANO»; `p_provincia`, no.
    n = n.split(" - ")[0]
    return provincias.get(n, (None, None))


# ─────────────────────────────────────────────────────────────────────────────
# Plan
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Plan:
    empresas_nuevas: list[dict] = field(default_factory=list)
    contactos: list[dict] = field(default_factory=list)
    informe: list[dict] = field(default_factory=list)
    cuenta: dict = field(default_factory=dict)

    def contar(self, clave, n=1):
        self.cuenta[clave] = self.cuenta.get(clave, 0) + n

    def anotar(self, accion, **datos):
        self.informe.append({"accion": accion, **datos})


def armar_empresa(e: dict, cuit: int, destino: dict, hoy: datetime) -> tuple[dict, list[str]]:
    razon = limpio(e["razon"])
    prov_id, prov_nombre = provincia_para(e["provincia"], destino["provincias"])
    notas = []
    if limpio(e["provincia"]) and not prov_id:
        notas.append(f"provincia «{limpio(e['provincia'])}» sin equivalente en p_provincia")

    obs = [f"[AEDA afi_empresas {e['empre_id']}] Alta por importación desde AEDA "
           f"el {hoy:%d/%m/%Y}."]
    if limpio(e["inicio"]):
        obs.append(f"Inicio en AEDA: {limpio(e['inicio'])}.")
    if limpio(e["obs"]):
        obs.append(f"Obs. AEDA: {limpio(e['obs'])}")
    # Domicilio del establecimiento: casi siempre vacío, pero cuando está no
    # tiene columna de destino —el `fdom_` es el fiscal, que es otra cosa—.
    est = ", ".join(x for x in (limpio(e["domest"]), limpio(e["locest"])) if x)
    if est:
        obs.append(f"Establecimiento en AEDA: {est}.")

    cp = e["cp"]
    fila = {
        "CUIT":                 cuit,
        "razon_social":         razon,
        # NOT NULL en la tabla. Las 2.854 copiadas de `contable` repiten la
        # razón social; se sigue igual para que la grilla no muestre huecos.
        "nombre_fantasia":      razon,
        "telefonos":            None,   # los contactos van a s_contactos
        "email":                None,
        "observaciones":        " ".join(obs),
        "Activo":               1 if e["activa"] == 1 else 0,
        "dom_provincia_id":     prov_id,
        "dom_provincia_nombre": prov_nombre,
        "dom_localidad_nombre": limpio(e["localidad"]) or None,
        # AEDA guarda calle, número, piso y oficina en un solo texto libre
        # («AV BELGRANO 615 21 I», «CHACABUCO 361-8PISO F»). Partirlo a ojo
        # mete números de piso en el campo número; va entero a `dom_calle`.
        "dom_calle":            limpio(e["calle"]) or None,
        "dom_cp":               str(cp) if cp and cp > 0 else None,
    }
    return fila, notas


CLAVE_MAIL_ORIGINAL = ("teléfonos o mails reacomodados o con texto sin interpretar "
                       "(original en observaciones)")


def _contactos(base: dict, marca: str, mails: list[str], web, nota_aeda,
               telefono, celular, prioridad: int, plan: Plan) -> list[dict]:
    """
    Uno o más contactos con los mismos datos, uno por mail.

    Un contacto guarda una sola dirección. Si en AEDA había dos, la segunda va
    en un contacto aparte —mismo nombre y cargo, sin teléfono— para que los
    avisos les lleguen a las dos.
    """
    if nota_aeda:
        plan.contar(CLAVE_MAIL_ORIGINAL)
    filas = []
    for i, mail in enumerate(mails or [None]):
        m = marca if i == 0 else marca[:-1] + f" mail {i + 1}]"
        nota = nota_aeda if (nota_aeda and i == 0) else ""
        filas.append({
            **base,
            "marca": m,
            "telefono": telefono if i == 0 else None,
            "celular": celular if i == 0 else None,
            "email": mail,
            "web": web if i == 0 else None,
            "observaciones": f"{m} {nota}".strip()[:300],
            "principal": 0,
            # Sin mail no hay a quién mandarle el aviso: no puede ganarle a
            # nadie que sí tenga.
            "prioridad": prioridad + i + (0 if mail else 10),
        })
    return filas


def contactos_de_empresa(e: dict, personas: list[dict], cuit: int, entidad,
                         destino: dict, plan: Plan, marca_general: str | None = None) -> list[dict]:
    """
    Los contactos a crear para una empresa, deduplicados y con prioridad.

    `entidad` es `("id", <id en p_empresas>)` o `("alta", <empre_id>)` cuando la
    empresa todavía no existe y el id se conoce recién al insertarla.

    `marca_general` es el origen de los datos generales (teléfono y mail de la
    ficha): «[AEDA afi_empresas N]» si no se indica. El importador de
    proveedores usa la misma lógica con «[AEDA adm_proveedor N]».
    """
    razon = limpio(e["razon"])
    areas = destino["areas"]
    nuevos = []
    mails_personas, tels_personas = set(), set()

    for p in personas:
        cid = p["contacto_id"]
        nombre, cargo = limpio(p["nombre"]), limpio(p["cargo"])
        tel_txt, mail_txt, nombre_en_mail = acomodar_campos(p["telefono"], p["email"])
        nombre = nombre or nombre_en_mail
        telefono, celular = separar_telefono(tel_txt)
        mails, web, sobrante = limpiar_mails(mail_txt)
        nota = nota_original(p["telefono"], p["email"], tel_txt, mail_txt, bool(sobrante))

        if not (nombre or telefono or celular or mails or web or nota):
            plan.contar("personas vacías (sin nombre, teléfono ni mail)")
            plan.anotar("omitido", empre_id=e["empre_id"], cuit=cuit, razon=razon,
                        origen=f"adm_contactos {cid}", cargo=cargo,
                        nota="sin nombre, teléfono ni mail")
            continue

        mails_personas.update(mails)
        tels_personas.update(solo_digitos(t) for t in (telefono, celular) if t)
        area = area_para(cargo)
        # Quién recibe los avisos cuando no se pide un área: primero «PAGOS 1»
        # o «PRIORIDAD 1», después el resto de pagos, después los generales de
        # la empresa (prioridad 2) y al final cualquier otra persona.
        c = normalizar(cargo)
        de_pagos = c.startswith(("PAGO", "PRIORIDAD"))
        prioridad = 0 if de_pagos and "1" in c else 1 if de_pagos else 3

        base = {"empre_id": e["empre_id"], "cuit": cuit, "razon": razon,
                "entidad": entidad, "orden": cid,
                "nombre": (nombre or razon)[:150], "cargo": cargo[:100] or None,
                "area": area, "id_area_contacto": areas.get(area) if area else None}
        nuevos += _contactos(base, f"[AEDA adm_contactos {cid}]", mails, web, nota,
                             telefono, celular, prioridad, plan)

    # Los datos generales de afi_empresas, solo con lo que no esté ya en una
    # persona: la misma dirección dos veces duplica cada aviso.
    tel_txt, mail_txt, nombre_en_mail = acomodar_campos(e["telefono"], e["email"])
    telefono, celular = separar_telefono(tel_txt)
    mails, web, sobrante = limpiar_mails(mail_txt)
    nota = nota_original(e["telefono"], e["email"], tel_txt, mail_txt, bool(sobrante))
    mails_nuevos = [m for m in mails if m not in mails_personas]
    if telefono and solo_digitos(telefono) in tels_personas:
        telefono = None
    if celular and solo_digitos(celular) in tels_personas:
        celular = None
    if (mails and not mails_nuevos) or (limpio(e["telefono"]) and not (telefono or celular)):
        plan.contar("datos generales ya presentes en una persona (no se duplican)")

    if telefono or celular or mails_nuevos or web or nota:
        base = {"empre_id": e["empre_id"], "cuit": cuit, "razon": razon,
                "entidad": entidad, "orden": 0,
                "nombre": (nombre_en_mail or razon)[:150], "cargo": None,
                "area": None, "id_area_contacto": None}
        nuevos += _contactos(base, marca_general or f"[AEDA afi_empresas {e['empre_id']}]", mails_nuevos,
                             web, nota, telefono, celular, 2, plan)
    return nuevos


def armar_plan(aeda: dict, destino: dict, hoy: datetime) -> Plan:
    plan = Plan()
    personas_por_empresa: dict[int, list[dict]] = {}
    for p in aeda["contactos"]:
        personas_por_empresa.setdefault(p["empre_id"], []).append(p)

    ids_aeda = {e["empre_id"] for e in aeda["empresas"]}
    for empre_id, personas in personas_por_empresa.items():
        if empre_id not in ids_aeda:
            for p in personas:
                plan.contar("personas de una empresa inexistente en AEDA")
                plan.anotar("omitido", empre_id=empre_id, origen=f"adm_contactos {p['contacto_id']}",
                            nombre=limpio(p["nombre"]), cargo=limpio(p["cargo"]),
                            telefono=limpio(p["telefono"]), email=limpio(p["email"]),
                            nota="ref_nro no existe en afi_empresas")

    plan.contar("empresas en AEDA", len(aeda["empresas"]))
    plan.contar("personas de empresas en adm_contactos", len(aeda["contactos"]))

    altas_por_cuit: dict[int, int] = {}     # CUIT → empre_id del alta planeada
    con_principal = {("id", i) for i in destino["con_principal"]}

    for e in aeda["empresas"]:
        razon = limpio(e["razon"])
        txt_cuit = limpio(e["cuit"])
        personas = personas_por_empresa.get(e["empre_id"], [])
        cuit = int(txt_cuit) if txt_cuit.isdigit() and len(txt_cuit) == 11 else None

        if cuit is not None and cuit in destino["empresas"]:
            entidad = ("id", destino["empresas"][cuit])
            plan.contar("empresas que ya estaban en p_empresas")
        elif cuit is not None and cuit in altas_por_cuit:
            # El mismo CUIT dos veces en AEDA: una sola alta, y los contactos
            # de las dos filas a esa empresa. Insertarlo dos veces choca con
            # la clave única y tira abajo toda la importación.
            entidad = ("alta", altas_por_cuit[cuit])
            plan.contar("filas de AEDA con un CUIT repetido (unificadas)")
        elif cuit is not None and cuit_valido(txt_cuit):
            fila, notas = armar_empresa(e, cuit, destino, hoy)
            plan.empresas_nuevas.append({"empre_id": e["empre_id"], **fila})
            altas_por_cuit[cuit] = e["empre_id"]
            entidad = ("alta", e["empre_id"])   # el id se conoce al insertar
            plan.contar("empresas nuevas")
            plan.anotar("alta empresa", empre_id=e["empre_id"], cuit=cuit, razon=razon,
                        origen=f"afi_empresas {e['empre_id']}",
                        nota="; ".join(notas + ([] if fila["Activo"] else ["inactiva en AEDA"])))
        else:
            motivo = ("CUIT mal formado" if cuit is None
                      else "CUIT con dígito verificador inválido")
            plan.contar("empresas rechazadas por CUIT")
            plan.anotar("rechazada", empre_id=e["empre_id"], cuit=txt_cuit, razon=razon,
                        origen=f"afi_empresas {e['empre_id']}",
                        telefono=limpio(e["telefono"]), email=limpio(e["email"]),
                        nota=motivo)
            # Las personas también al informe, una por fila: si alguien corrige
            # el CUIT y carga la empresa a mano, es la lista que necesita.
            for p in personas:
                plan.contar("personas de empresas rechazadas")
                plan.anotar("omitido", empre_id=e["empre_id"], cuit=txt_cuit, razon=razon,
                            origen=f"adm_contactos {p['contacto_id']}",
                            nombre=limpio(p["nombre"]), cargo=limpio(p["cargo"]),
                            telefono=limpio(p["telefono"]), email=limpio(p["email"]),
                            nota=f"empresa rechazada: {motivo}")
            continue

        nuevos = contactos_de_empresa(e, personas, cuit, entidad, destino, plan)

        ya = [c for c in nuevos if c["marca"] in destino["marcas"]]
        if ya:
            plan.contar("contactos importados en una corrida anterior", len(ya))
        nuevos = [c for c in nuevos if c["marca"] not in destino["marcas"]]
        if not nuevos:
            continue

        # Un principal por empresa, si no tenía: el que usa el envío cuando el
        # aviso no pide un área.
        if entidad not in con_principal:
            min(nuevos, key=lambda c: (c["prioridad"], c["orden"]))["principal"] = 1
            con_principal.add(entidad)

        for c in nuevos:
            plan.contactos.append(c)
            plan.anotar("alta contacto", empre_id=c["empre_id"], cuit=cuit, razon=c["razon"],
                        origen=c["marca"].strip("[]").replace("AEDA ", ""),
                        nombre=c["nombre"], cargo=c["cargo"] or "", area=c["area"] or "",
                        telefono=c["telefono"] or "", celular=c["celular"] or "",
                        email=c["email"] or "", web=c["web"] or "",
                        principal="sí" if c["principal"] else "",
                        nota=c["observaciones"].replace(c["marca"], "", 1).strip())

    plan.contar("contactos a crear", len(plan.contactos))
    plan.contar("empresas con al menos un contacto nuevo",
                len({c["empre_id"] for c in plan.contactos}))
    return plan


# ─────────────────────────────────────────────────────────────────────────────
# Aplicación
# ─────────────────────────────────────────────────────────────────────────────

COLUMNAS_CONTACTO = ("nombre", "cargo", "id_area_contacto", "telefono", "celular",
                     "email", "web", "principal", "observaciones")


def aplicar(cur, plan: Plan) -> dict[int, int]:
    """Graba el plan. Devuelve `empre_id` de AEDA → `id` nuevo en p_empresas."""
    nuevos_ids = {}
    for emp in plan.empresas_nuevas:
        valores = {k: v for k, v in emp.items() if k != "empre_id"}
        columnas = ", ".join(f"`{k}`" for k in valores)
        marcadores = ", ".join(["%s"] * len(valores))
        cur.execute(f"INSERT INTO p_empresas ({columnas}) VALUES ({marcadores})",
                    list(valores.values()))
        nuevos_ids[emp["empre_id"]] = cur.lastrowid

    for c in plan.contactos:
        tipo, valor = c["entidad"]
        entidad_id = valor if tipo == "id" else nuevos_ids[valor]
        cur.execute(f"""
            INSERT INTO s_contactos
                (entidad_tipo, entidad_id, {", ".join(COLUMNAS_CONTACTO)},
                 activo, creado, actualizado)
            VALUES (%s, %s, {", ".join(["%s"] * len(COLUMNAS_CONTACTO))}, 1, NOW(), NOW())
        """, [ENTIDAD, entidad_id] + [c[k] for k in COLUMNAS_CONTACTO])
    return nuevos_ids


# ─────────────────────────────────────────────────────────────────────────────
# Informe
# ─────────────────────────────────────────────────────────────────────────────

CAMPOS_INFORME = ["accion", "empre_id", "cuit", "razon", "origen", "nombre", "cargo",
                  "area", "telefono", "celular", "email", "web", "principal", "nota"]

ORDEN_RESUMEN = [
    "empresas en AEDA",
    "empresas que ya estaban en p_empresas",
    "empresas nuevas",
    "empresas rechazadas por CUIT",
    "personas de empresas en adm_contactos",
    "personas vacías (sin nombre, teléfono ni mail)",
    "personas de una empresa inexistente en AEDA",
    "personas de empresas rechazadas",
    "filas de AEDA con un CUIT repetido (unificadas)",
    "datos generales ya presentes en una persona (no se duplican)",
    CLAVE_MAIL_ORIGINAL,
    "contactos importados en una corrida anterior",
    "contactos a crear",
    "empresas con al menos un contacto nuevo",
]


def escribir_informe(plan: Plan, aplicado: bool, inicio: datetime) -> tuple[Path, Path]:
    CARPETA_LOGS.mkdir(exist_ok=True)
    base = CARPETA_LOGS / f"importar_aeda_{inicio:%Y%m%d_%H%M%S}"
    detalle, resumen = base.with_suffix(".csv"), base.with_suffix(".txt")

    # `;` y BOM: es lo que el Excel en castellano abre directo en columnas.
    with open(detalle, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_INFORME, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(plan.informe)

    lineas = [f"Importación AEDA → sindicato  {inicio:%d/%m/%Y %H:%M}",
              "APLICADA" if aplicado else "SIMULACIÓN — no se grabó nada", ""]
    claves = ORDEN_RESUMEN + [k for k in plan.cuenta if k not in ORDEN_RESUMEN]
    for k in claves:
        if k in plan.cuenta:
            lineas.append(f"  {plan.cuenta[k]:>6}  {k}")
    lineas += ["", f"Detalle: {detalle.name}"]
    resumen.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return resumen, detalle


# ─────────────────────────────────────────────────────────────────────────────

def salir(mensaje: str):
    print(f"\n  {mensaje}\n")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
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

        if args.aplicar and (plan.empresas_nuevas or plan.contactos):
            # Todo o nada: con empresas dadas de alta y sus contactos a medias,
            # la segunda corrida no sabría distinguir qué faltó.
            conn.begin()
            try:
                with conn.cursor() as cur:
                    aplicar(cur, plan)
                conn.commit()
            except Exception:
                conn.rollback()
                resumen, _ = escribir_informe(plan, False, inicio)
                print(f"\n  Falló la importación; no se grabó nada. Plan en {resumen}\n")
                raise

    resumen, detalle = escribir_informe(plan, args.aplicar, inicio)
    print()
    print(resumen.read_text(encoding="utf-8"))
    if not args.aplicar:
        print("  Para grabar:  python importar_aeda.py --aplicar\n")


if __name__ == "__main__":
    main()
