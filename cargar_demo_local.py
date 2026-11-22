"""
cargar_demo_local.py — una muestra chica y ANONIMIZADA de la base de Railway, en la base
`sindicato` de ESTA máquina, para hacer demos.

    python cargar_demo_local.py                 simula: elige la muestra y cuenta, no escribe nada
    python cargar_demo_local.py --aplicar       VACÍA `sindicato` de localhost y la carga

Origen: el MySQL de Railway del .env (SIND_DB_HOST / _PORT / _USER / _PASS), en solo lectura
(SET SESSION TRANSACTION READ ONLY). No escribe en Railway: la conexión de origen no puede.
Destino: 127.0.0.1, base `sindicato` (constante, como en db.py). Usuario --local-user (root por
defecto) y la clave en DEMO_LOCAL_PASS o se pide por consola. Si el destino resulta ser el mismo
servidor que el origen, no hace nada.

Qué trae
  - Tal cual: menú, roles y permisos, catálogos (ARCA, padrón, bancos, RG 830, escalas), plan de
    cuentas, conceptos y motivos, cuentas de fondos y chequeras, talonarios, numeradores, áreas,
    convenio YMCA, la elección.
  - La muestra: ~30 empleadores con pocos afiliados (toda su nómina y sus grupos familiares, toda su
    cuenta corriente: liquidaciones, recibos y aplicaciones), afiliados con reintegros y adheridos a la
    YMCA, ~20 proveedores con toda su cuenta corriente (comprobantes, expedientes, órdenes, pagos,
    retenciones), órdenes por concepto, movimientos entre cuentas y extractos de los últimos 6 meses.
  - Lo que queda colgado de algo que no vino (un pago de un proveedor que no está en la muestra, por
    ejemplo) se borra al final recorriendo las FK de la base, hasta que no quede nada suelto.

Anonimización (consistente: el mismo dato real da siempre el mismo dato falso, en todas las tablas)
  - CUIT/CUIL: otro número con el mismo prefijo y dígito verificador válido; el documento sale del
    CUIL nuevo. También dentro de los textos («(CUIT 30716707519)»).
  - Nombres de personas y razones sociales: inventados; también donde aparecen dentro de un texto.
  - Mails, teléfonos, CBU (válidos, con el banco de siempre), alias, calles, números de cuenta.
  - Usuarios: admin@demo.local / supervisor@demo.local …, clave DEMO_CLAVE (abajo).
  - Datos del Sindicato: nombre, CUIT, autoridades, domicilio y contacto inventados; sin logo.
  - Fuera: correo saliente (queda apagado y sin clave), log de errores, tokens de ARCA, mensajes,
    archivos adjuntos (los PDF no están en esta máquina), el padrón de AEDA de julio.
  - Lo que AEDA dejó en `observaciones` se reduce a sus marcas «[AEDA …]».
"""

import argparse
import datetime as dt
import getpass
import hashlib
import os
import random
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

import pymysql
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv(Path(__file__).with_name(".env"))

DB_NAME = "sindicato"
DEMO_CLAVE = "demo2026"
SAL = "demo-sindicato-2026"          # cambia todos los datos falsos si se cambia
HOY = dt.date.today()
DESDE = (HOY.replace(day=1) - dt.timedelta(days=150)).replace(day=1)   # 6 meses con el actual
N_EMPLEADORES = 30
N_PROVEEDORES = 20
N_REINTEGROS = 25                    # titulares con reintegros, además de los de los empleadores
N_YMCA = 25                          # titulares adheridos a la YMCA, ídem
LOTE = 500

# ── Tablas ────────────────────────────────────────────────────────────────────

# Se copian enteras (los datos personales que tengan pasan igual por el anonimizador).
COMPLETAS = """
arca_c_actividad arca_feriados arca_intereses arca_responsable_tipo arca_tasa_iva arca_tipo_comprobante
arca_tipo_documento arca_unidad_de_medida arca_vencimientos
c_areas_contacto c_chequeras c_clasificacion_plan_cuentas c_codigo_de_banco c_concepto_de_gastos
c_contable_comprobante_tipo c_cuentas_de_fondos c_especies c_motivos_de_ingreso c_numeradores
c_plan_de_cuentas c_plan_de_cuentas_clasificacion c_rubros_de_activo c_rubros_de_pasivo c_talonario
c_talonario_clasificacion c_ejercicios c_periodos c_indices_inflacion c_indices_inflacion_periodos
c_pago_sueldos_imputaciones c_asientos_automaticos c_asientos_automaticos_lineas conc_reglas
fisca_escala_salarial fisca_fiscalizador ben_convenio ben_convenio_precio ben_campania ben_entrega_stock
el_eleccion
p_estado_civil p_motivo_movimiento p_nacionalidad p_obras_sociales p_parentesco p_provincia
p_situacion_revista p_tipo_beneficiario p_tipo_documentacion p_tipo_documento p_afiliado_atributo
pago_imputaciones_config pago_config_aprobadores rg830_escala rg830_escala_tramos
s_areas s_area_usuario s_configuracion s_institucion s_menu s_menu_prefijos s_menu_rol s_menu_tablas
s_menu_usuario s_roles s_usuario_rol s_usuarios s_atributos s_atributos_def s_accesos_directos
mail_tipos mail_tipo_copias mail_remitentes mail_config proc_procesos
""".split()

# No se copian: credenciales, logs, archivos que no están acá, datos de personas fuera de la muestra.
FUERA = """
arca_wsaa_ta s_log_errores s_accesos_denegados s_log_procesos mail_envios chat_conversaciones
chat_mensajes chat_participantes chat_presencia ia_consultas ia_usuario_config proc_corridas
proc_corridas_log proc_solicitudes padron p_documentacion c_reintegro_afiliados_detalle_adjunto
fisca_lsd_presentacion fisca_lsd_manual fisca_aplicacion_baja c_pasivo_aplicacion_baja s_atributos_val
inscripciones_dia_del_nino
""".split()

# FK que se ponen en NULL (en vez de borrar la fila) si lo que apuntan no vino.
A_NULL = {
    ("c_proveedores", "id_grupo"), ("c_proveedores", "id_area_destino"), ("c_proveedores", "id_usuario_destino"),
    ("me_expedientes", "id_area_destino"), ("me_expedientes", "id_usuario_destino"),
    ("me_expediente_movimientos", "id_area_destino"), ("me_expediente_movimientos", "id_usuario_destino"),
    ("c_reintegro_afiliados", "id_orden_pago"), ("p_relaciones_laborales", "id_empleador"),
    ("ingreso_ordenes", "id_acta"), ("ingreso_ordenes", "id_acuerdo"),
    ("ingreso_ordenes_detalle", "id_extracto_origen"), ("pago_ordenes_concepto_det", "id_extracto_origen"),
    ("c_debitos_creditos_bancarios", "c_chequerasId"), ("pago_retenciones", "id_expediente"),
    ("c_ejercicios", "empresa_id"), ("c_ejercicios", "id_asiento_apertura"), ("c_ejercicios", "id_asiento_cierre"),
    ("f_comprobantes_arca", "id_proveedor"),
}
# Toda FK a estas tablas va a NULL (no deberían faltar, pero no vale borrar un pago por eso).
PADRES_A_NULL = {"s_usuarios", "s_areas", "c_talonario", "c_motivos_de_ingreso", "mail_remitentes",
                 "c_areas_contacto", "arca_responsable_tipo", "p_provincia", "arca_tasa_iva"}

# ── Datos falsos ──────────────────────────────────────────────────────────────

APELLIDOS = """GONZALEZ RODRIGUEZ GOMEZ FERNANDEZ LOPEZ DIAZ MARTINEZ PEREZ GARCIA SANCHEZ ROMERO SOSA
ALVAREZ TORRES RUIZ RAMIREZ FLORES ACOSTA BENITEZ MEDINA SUAREZ HERRERA AGUIRRE PEREYRA GUTIERREZ GIMENEZ
MOLINA SILVA CASTRO ROJAS ORTIZ NUÑEZ LUNA JUAREZ CABRERA RIOS FERREYRA GODOY MORALES DOMINGUEZ MOREno
PERALTA VEGA CARRIZO QUIROGA CASTILLO LEDESMA MUÑOZ OJEDA PONCE VERA VAZQUEZ VILLALBA CARDOZO NAVARRO
RAMOS ARIAS CORONEL CORDOBA FIGUEROA CORREA CACERES VARGAS MALDONADO MANSILLA FARIAS RIVERO PAZ MIRANDA
ROLDAN MENDEZ LUCERO CRUZ HERNANDEZ AGÜERO PAEZ BLANCO MENDOZA BARRIOS ESCOBAR AVILA SORIA LEIVA ACUÑA
MARTIN MAIDANA MORENO AYALA OLIVERA BUSTOS RIVAS IBARRA CHAVEZ SALINAS VILLAREAL ZALAZAR""".upper().split()
NOMBRES_M = """JUAN CARLOS JOSE LUIS JORGE MIGUEL ALBERTO DANIEL RICARDO DIEGO MARTIN PABLO SERGIO GUSTAVO
FERNANDO MARCELO ALEJANDRO RAUL HECTOR OSCAR EDUARDO ROBERTO CLAUDIO HUGO MARIANO MATIAS NICOLAS LUCAS
FACUNDO SANTIAGO TOMAS FEDERICO GASTON MAXIMILIANO EZEQUIEL LEANDRO GONZALO HERNAN JAVIER RODRIGO
SEBASTIAN AGUSTIN IGNACIO JULIAN FRANCO ESTEBAN ANDRES CRISTIAN EMILIANO BRUNO THIAGO BENJAMIN""".split()
NOMBRES_F = """MARIA ANA LAURA SILVIA PATRICIA GRACIELA SUSANA ALICIA MONICA CLAUDIA ANDREA SANDRA MARTA
NORMA BEATRIZ ELENA LILIANA CAROLINA GABRIELA ROSA ADRIANA MARCELA CECILIA VERONICA LORENA ROMINA
NATALIA SOLEDAD PAULA FLORENCIA VALERIA JULIETA MARIANA VANESA AGUSTINA CAMILA LUCIA SOFIA MICAELA
JIMENA DANIELA ROCIO BELEN MILAGROS VICTORIA CANDELA LUDMILA MALENA VALENTINA EMILIA""".split()
EMP_A = """DISTRIBUIDORA COMERCIAL LOGISTICA SERVICIOS INDUSTRIAS ALIMENTOS TRANSPORTES CONSULTORA
LABORATORIOS CONSTRUCTORA AGENCIA ESTUDIO IMPORTADORA EXPORTADORA DEPOSITOS TERMINAL CARGAS ADUANERA
SOLUCIONES GRUPO TECNOLOGIA MAYORISTA""".split()
EMP_B = ["DEL SUR", "DEL PLATA", "LOS ALAMOS", "SAN MARTIN", "EL CEIBO", "LA ESTRELLA", "DEL LITORAL",
         "PAMPEANA", "ANDINA", "RIOPLATENSE", "DEL OESTE", "NORTE GRANDE", "LOS TILOS", "LAS ACACIAS",
         "PUERTO NUEVO", "DOCK SUD", "ATLANTICA", "MERIDIANO", "EL HORNERO", "LA RIBERA", "DEL PARANA",
         "CUATRO VIENTOS", "LOS ANDES", "PATAGONICA", "CENTRAL", "MAR DULCE", "TRES CRUCES", "EL MOLINO",
         "BELGRANO", "LA COSTA", "SANTA RITA", "EL TREBOL", "DEL CENTRO", "PORTUARIA", "LAS PALMAS"]
EMP_C = ["S.A.", "S.R.L.", "S.A.S.", "S.A.", "S.R.L."]
CALLES = """AV. RIVADAVIA|AV. CORRIENTES|AV. SAN JUAN|AV. BELGRANO|TUCUMAN|LAVALLE|VIAMONTE|PARAGUAY|
SARMIENTO|MORENO|AV. INDEPENDENCIA|CHACABUCO|PERU|BOLIVAR|DEFENSA|AV. PASEO COLON|AZOPARDO|BALCARCE|
AV. DE MAYO|ALSINA|HIPOLITO YRIGOYEN|URUGUAY|TALCAHUANO|LIBERTAD|CERRITO|AV. CORDOBA|ESMERALDA|
MAIPU|FLORIDA|SAN MARTIN|RECONQUISTA|25 DE MAYO|AV. ALEM|BOUCHARD|AV. MADERO|AV. HUERGO|ITUZAINGO|
ARISTOBULO DEL VALLE|ALMIRANTE BROWN|PEDRO DE MENDOZA|OLAVARRIA|SUAREZ|MONTES DE OCA|PATRICIOS""".replace("\n", "").split("|")

COLS_NOMBRE = {
    "apellido_nombres", "razon_social", "nombre_fantasia", "razon_social_emisor", "razon_social_receptor",
    "razon_social_librador", "razon_social_proveedor", "empleador", "inspector", "representante",
    "retiro_nombre", "a_la_orden", "cheque_a_la_orden", "remitente_nombre", "secretario_general",
    "secretario_adjunto", "tesorero", "empresa", "titular", "beneficiario",
}
TABLAS_NOMBRE_PERSONA = {"s_contactos", "ben_campania_envio", "pago_ordenes_reintegro_det", "mail_remitentes"}
COLS_DNI = {"nro_documento", "dni", "inspector_dni", "representante_dni", "retiro_documento", "documento"}
COLS_TEL = {"telefono", "telefonos", "celular", "cuota_consultas_telefono"}
COLS_CALLE = {"domicilio_calle", "dom_calle", "fdom_calle", "calle", "domicilio"}
COLS_CUENTA = {"numero_de_cuenta", "numero_cuenta"}
COLS_A_NULL = {"google_id", "avatar_url", "ip", "password_cif", "ruta_local", "pdf_path", "flyer_archivo",
               "logo_path", "token", "sign"}
SOLO_MARCAS = {("p_afiliados", "observaciones"), ("p_empresas", "observaciones"),
               ("s_contactos", "observaciones"), ("c_proveedores", "observaciones")}

RE_CUIT_TXT = re.compile(r"(?<![\d-])((?:20|23|24|27|30|33|34)-?\d{8}-?\d)(?![\d-])")
RE_CBU_TXT = re.compile(r"(?<!\d)\d{22}(?!\d)")
RE_MAIL_TXT = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
RE_MARCA = re.compile(r"\[[^\]]*\]")


def sin_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def clave_nombre(s: str) -> str:
    return re.sub(r"\s+", " ", sin_acentos(str(s)).upper()).strip()


def dv_cuit(base10: str) -> int | None:
    pesos = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    r = 11 - sum(int(d) * p for d, p in zip(base10, pesos)) % 11
    if r == 11:
        return 0
    if r == 10:
        return None
    return r


def cbu_valido(banco3: str, h: int) -> str:
    b = banco3 + f"{h % 10000:04d}"
    dv1 = (10 - sum(int(d) * p for d, p in zip(b, [7, 1, 3, 9, 7, 1, 3])) % 10) % 10
    c = f"{(h // 10000) % 10**13:013d}"
    dv2 = (10 - sum(int(d) * p for d, p in zip(c, [3, 9, 7, 1, 3, 9, 7, 1, 3, 9, 7, 1, 3])) % 10) % 10
    return f"{b}{dv1}{c}{dv2}"


class Anon:
    """Datos falsos deterministas: el mismo dato real da siempre el mismo falso."""

    def __init__(self, exentos_cuit: set[str]):
        self.cuits: dict[str, str] = {}
        self.cuits_usados: set[str] = set()
        self.dnis: dict[str, str] = {}
        self.nombres: dict[str, str] = {}      # clave_nombre(real) -> falso
        self.nombres_usados: set[str] = set()
        self.mails: dict[str, str] = {}
        self.exentos = exentos_cuit
        self._re_nombres = None

    def h(self, *partes) -> int:
        return int(hashlib.sha256((SAL + "|" + "|".join(map(str, partes))).encode()).hexdigest(), 16)

    # CUIT / CUIL / DNI
    def cuit(self, v):
        if v is None:
            return None
        s = str(v)
        d = re.sub(r"\D", "", s)
        if len(d) != 11 or d in self.exentos:
            return v
        if d not in self.cuits:
            pref, k = d[:2], 0
            while True:
                body = f"{self.h('cuit', d, k) % 10**8:08d}"
                dv = dv_cuit(pref + body)
                cand = f"{pref}{body}{dv}" if dv is not None else None
                if cand and cand != d and cand not in self.cuits_usados and body[0] != "0":
                    break
                k += 1
            self.cuits[d] = cand
            self.cuits_usados.add(cand)
            if pref in ("20", "23", "24", "27"):
                self.dnis.setdefault(str(int(d[2:10])), str(int(body)))
        f = self.cuits[d]
        if isinstance(v, int):
            return int(f)
        if "-" in s:
            return f"{f[:2]}-{f[2:10]}-{f[10]}"
        return f

    def dni(self, v):
        if v is None:
            return None
        d = re.sub(r"\D", "", str(v))
        if not d:
            return v
        clave = str(int(d))
        if clave not in self.dnis:
            n = len(clave)
            self.dnis[clave] = str(10 ** (n - 1) + self.h("dni", clave) % (9 * 10 ** (n - 1)))
        f = self.dnis[clave]
        return int(f) if isinstance(v, int) else f

    # Nombres
    def _persona(self, real: str, sexo: str | None) -> str:
        k = 0
        while True:
            h = self.h("persona", real, k)
            ap = APELLIDOS[h % len(APELLIDOS)]
            if h % 3 == 0:
                ap += " " + APELLIDOS[(h // 7) % len(APELLIDOS)]
            lista = NOMBRES_F if sexo == "F" else NOMBRES_M if sexo == "M" else (NOMBRES_F + NOMBRES_M)
            nom = lista[(h // 101) % len(lista)]
            if h % 2 == 0:
                nom += " " + lista[(h // 1009) % len(lista)]
            cand = f"{ap} {nom}"
            if cand not in self.nombres_usados:
                return cand
            k += 1

    def _empresa(self, real: str) -> str:
        k = 0
        while True:
            h = self.h("empresa", real, k)
            cand = f"{EMP_A[h % len(EMP_A)]} {EMP_B[(h // 31) % len(EMP_B)]} {EMP_C[(h // 997) % len(EMP_C)]}"
            if cand not in self.nombres_usados:
                return cand
            k += 1

    def registrar(self, real, falso: str | None = None, tipo: str = "persona", sexo: str | None = None):
        if not real or not str(real).strip():
            return real
        k = clave_nombre(real)
        if k not in self.nombres:
            if falso is None:
                falso = self._empresa(k) if tipo == "empresa" else self._persona(k, sexo)
            self.nombres[k] = falso
            self.nombres_usados.add(falso)
            self._re_nombres = None
        return self.nombres[k]

    def nombre(self, v, tipo="persona", sexo=None):
        if v is None or not str(v).strip():
            return v
        k = clave_nombre(v)
        if k in self.nombres:
            f = self.nombres[k]
        else:
            if tipo == "auto":
                tipo = "empresa" if re.search(r"\b(S\.?A\.?S?|S\.?R\.?L|SOCIEDAD|COOP|ASOC|ESTUDIO|CIA)\b", k) else "persona"
            f = self.registrar(v, tipo=tipo, sexo=sexo)
        s = str(v)
        return f if s.isupper() or not s.strip() else f.title()

    # Texto libre
    def _regex_nombres(self):
        if self._re_nombres is None:
            reales = sorted((k for k in self.nombres if len(k) >= 8 and " " in k), key=len, reverse=True)
            self._re_nombres = re.compile(r"(?<!\w)(" + "|".join(re.escape(x) for x in reales) + r")(?!\w)",
                                          re.I) if reales else False
        return self._re_nombres

    def texto(self, s):
        if not isinstance(s, str) or not s:
            return s
        s = RE_CUIT_TXT.sub(lambda m: str(self.cuit(m.group(1))), s)
        s = RE_CBU_TXT.sub(lambda m: self.cbu(m.group(0)), s)
        s = RE_MAIL_TXT.sub(lambda m: self.mail(m.group(0)), s)
        rx = self._regex_nombres()
        if rx and re.search(r"[A-Za-z]{4}", s):
            plano = sin_acentos(s)
            if len(plano) == len(s):          # sin caracteres combinados raros: se puede ubicar por posición
                partes, ult = [], 0
                for m in rx.finditer(plano):
                    partes.append(s[ult:m.start()])
                    f = self.nombres.get(clave_nombre(m.group(0)), m.group(0))
                    partes.append(f if s[m.start():m.end()].isupper() else f.title())
                    ult = m.end()
                partes.append(s[ult:])
                s = "".join(partes)
        return s

    def mail(self, v):
        if not v or "@" not in str(v):
            return v
        k = str(v).strip().lower()
        if k not in self.mails:
            self.mails[k] = f"contacto{self.h('mail', k) % 100000:05d}@ejemplo.com.ar"
        return self.mails[k]

    def tel(self, v):
        if not v:
            return v
        h = self.h("tel", v)
        return f"011 4{h % 1000:03d}-{(h // 1000) % 10000:04d}"

    def cbu(self, v):
        if not v:
            return v
        d = re.sub(r"\D", "", str(v))
        if len(d) != 22:
            return self.alias(v)
        return cbu_valido(d[:3], self.h("cbu", d))

    def alias(self, v):
        if not v:
            return v
        h = self.h("alias", v)
        pal = ["sol", "rio", "mate", "luna", "pampa", "faro", "puerto", "barco", "nube", "trigo", "ceibo", "tango"]
        return f"{pal[h % 12]}.{pal[(h // 13) % 12]}.{pal[(h // 169) % 12]}{h % 100}"

    def calle(self, v):
        if not v:
            return v
        h = self.h("calle", v)
        return f"{CALLES[h % len(CALLES)]} {100 + h % 4800}"

    def digitos(self, v):
        if not v:
            return v
        d = re.sub(r"\D", "", str(v))
        if not d:
            return v
        return f"{self.h('cuenta', d) % 10**len(d):0{len(d)}d}"


# ── Conexiones ────────────────────────────────────────────────────────────────

def conectar_origen():
    host = os.getenv("SIND_DB_HOST", "")
    if host in ("", "localhost", "127.0.0.1", "::1"):
        sys.exit("El origen tiene que ser Railway: SIND_DB_HOST del .env apunta a esta máquina o está vacío.")
    c = pymysql.connect(host=host, port=int(os.getenv("SIND_DB_PORT", "3306")),
                        user=os.environ["SIND_DB_USER"], password=os.getenv("SIND_DB_PASS", ""),
                        database=DB_NAME, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
                        autocommit=True, connect_timeout=20, read_timeout=600)
    with c.cursor() as cur:
        cur.execute("SET SESSION TRANSACTION READ ONLY")
        cur.execute("SET SESSION group_concat_max_len = 1000000")
    return c


def conectar_destino(args):
    clave = os.getenv("DEMO_LOCAL_PASS")
    if clave is None:
        clave = getpass.getpass(f"Clave de {args.local_user}@127.0.0.1 (MySQL local): ")
    return pymysql.connect(host="127.0.0.1", port=args.local_port, user=args.local_user, password=clave,
                           database=DB_NAME, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
                           autocommit=False, read_timeout=600, write_timeout=600)


def q(con, sql, params=()):
    with con.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def en(con, sql, valores, chunk=800):
    """`sql` con un {in}: lo corre de a pedazos con la lista de valores."""
    valores = list({v for v in valores if v is not None})
    filas = []
    for i in range(0, len(valores), chunk):
        parte = valores[i:i + chunk]
        filas += q(con, sql.format(in_=",".join(["%s"] * len(parte))), parte)
    return filas


# ── Muestra ───────────────────────────────────────────────────────────────────

class Muestra:
    def __init__(self, orig):
        self.o = orig
        self.filas: dict[str, dict] = defaultdict(dict)    # tabla -> {pk: fila}
        self.pk: dict[str, list[str]] = {}
        for f in q(orig, """SELECT table_name t, column_name c FROM information_schema.key_column_usage
                            WHERE table_schema = %s AND constraint_name = 'PRIMARY'
                            ORDER BY table_name, ordinal_position""", (DB_NAME,)):
            self.pk.setdefault(f["t"], []).append(f["c"])

    def poner(self, t, filas):
        pk = self.pk.get(t)
        for f in filas:
            clave = tuple(f[c] for c in pk) if pk else tuple(f.values())
            self.filas[t][clave] = f
        return filas

    def ids(self, t, col="id"):
        return {f[col] for f in self.filas[t].values() if f.get(col) is not None}

    def por(self, t, col, valores):
        return self.poner(t, en(self.o, f"SELECT * FROM `{t}` WHERE `{col}` IN ({{in_}})", valores))

    def donde(self, t, where, params=()):
        return self.poner(t, q(self.o, f"SELECT * FROM `{t}` WHERE {where}", params))


def norm_cuit(v):
    d = re.sub(r"\D", "", str(v or ""))
    return d if len(d) == 11 else None


def elegir(m: Muestra, rng: random.Random):
    o = m.o
    print(f"Muestra desde {DESDE:%d/%m/%Y} (movimientos de tesorería y extractos)")

    # Tablas completas
    tablas_origen = {f["t"] for f in q(o, "SELECT table_name t FROM information_schema.tables "
                                          "WHERE table_schema=%s AND table_type='BASE TABLE'", (DB_NAME,))}
    for t in COMPLETAS:
        if t in tablas_origen:
            m.donde(t, "1=1")

    inst = q(o, "SELECT cuit, nombre FROM s_institucion LIMIT 1")
    m.cuit_inst = norm_cuit(inst[0]["cuit"]) if inst else None
    conv = q(o, "SELECT id_proveedor FROM ben_convenio WHERE id_proveedor IS NOT NULL")
    m.prov_convenio = {f["id_proveedor"] for f in conv}

    # 1. Empleadores: pocos afiliados (toda la nómina entra), con cuota liquidada y cobros recientes
    per_desde = f"{DESDE:%Y%m}"
    cand = q(o, """
        SELECT r.cuit_empleador cuit, COUNT(DISTINCT a.id_afiliado) tit
        FROM p_relaciones_laborales r
        JOIN p_afiliados a ON a.cuil = r.cuil AND a.cod_parentesco = 0
        JOIN p_empresas e ON e.CUIT = CAST(r.cuit_empleador AS UNSIGNED) AND r.cuit_empleador REGEXP '^[0-9]{11}$'
        GROUP BY r.cuit_empleador
        HAVING tit BETWEEN 3 AND 15 AND SUM(r.estado = 'activa') >= 2""")
    con_liq = {f["cuit"] for f in q(o, "SELECT DISTINCT cuit FROM fisca_liquidacion WHERE periodo >= %s", (per_desde,))}
    con_cobro = {f["cuit"] for f in q(o, """SELECT DISTINCT d.cuit FROM ingreso_ordenes_detalle d
                                            JOIN ingreso_ordenes o ON o.id = d.id_orden WHERE o.fecha >= %s""", (DESDE,))}
    con_rel = {f["c"] for f in q(o, "SELECT DISTINCT cuit_empleador c FROM fisca_cuit_relacionado")}
    pool = sorted(f["cuit"] for f in cand if f["cuit"] in con_liq and f["cuit"] in con_cobro)
    rng.shuffle(pool)
    elegidos = [c for c in pool if c in con_rel][:3]
    elegidos += [c for c in pool if c not in elegidos][:N_EMPLEADORES - len(elegidos)]
    m.EC = set(elegidos)

    # 2. Afiliados: la nómina de esos empleadores + lo liquidado + reintegros + YMCA, con sus grupos
    tit = {f["cuil"] for f in en(o, """SELECT DISTINCT a.cuil FROM p_relaciones_laborales r
             JOIN p_afiliados a ON a.cuil = r.cuil AND a.cod_parentesco = 0
             WHERE r.cuit_empleador IN ({in_})""", m.EC)}
    m.por("fisca_liquidacion", "cuit", m.EC)
    L = m.ids("fisca_liquidacion")
    m.por("fisca_liquidacion_detalle", "id_liquidacion", L)
    ids_liq = m.ids("fisca_liquidacion_detalle", "id_afiliado")
    tit |= {f["t"] for f in en(o, "SELECT IFNULL(cuil_titular, cuil) t FROM p_afiliados WHERE id_afiliado IN ({in_})", ids_liq)}
    rei = sorted({f["t"] for f in q(o, """SELECT DISTINCT IFNULL(a.cuil_titular, a.cuil) t FROM c_reintegro_afiliados c
              JOIN p_afiliados a ON a.id_afiliado = c.id_afiliado WHERE c.fecha_solicitud >= %s""",
                                           (DESDE - dt.timedelta(days=180),)) if f["t"]})
    rng.shuffle(rei)
    ymca = sorted({f["t"] for f in q(o, """SELECT DISTINCT IFNULL(a.cuil_titular, a.cuil) t FROM ben_adherido b
              JOIN p_afiliados a ON a.id_afiliado = b.id_afiliado""") if f["t"]})
    rng.shuffle(ymca)
    tit |= set(rei[:N_REINTEGROS]) | set(ymca[:N_YMCA])
    tit.discard(None)
    afis = en(o, "SELECT * FROM p_afiliados WHERE cuil_titular IN ({in_})", tit)
    afis += en(o, "SELECT * FROM p_afiliados WHERE cuil IN ({in_})", tit)
    afis += en(o, "SELECT * FROM p_afiliados WHERE id_afiliado IN ({in_})", ids_liq)
    m.poner("p_afiliados", afis)
    A = m.ids("p_afiliados", "id_afiliado")
    AC = {f["cuil"] for f in m.filas["p_afiliados"].values() if f["cuil"]}
    m.A, m.AC = A, AC

    # 3. Empresas: las elegidas + los empleadores de los afiliados (sin su cuenta corriente)
    m.por("p_relaciones_laborales", "cuil", AC)
    emp_cuits = set(m.EC)
    emp_cuits |= {norm_cuit(f["cuit_empleador"]) for f in m.filas["p_relaciones_laborales"].values()}
    emp_cuits |= {norm_cuit(f["cuit_empleador"]) for f in m.filas["p_afiliados"].values()}
    emp_cuits.discard(None)
    m.por("p_empresas", "CUIT", [int(c) for c in emp_cuits])
    E = m.ids("p_empresas")
    E_sel = {f["id"] for f in m.filas["p_empresas"].values() if str(f["CUIT"]) in m.EC}
    m.ECall = {str(f["CUIT"]) for f in m.filas["p_empresas"].values()}

    # 4. Proveedores: los de más comprobantes recientes + el del convenio
    top = q(o, """SELECT id_proveedor, COUNT(*) n FROM f_comprobantes_arca
                  WHERE fecha_emision >= %s AND id_proveedor IS NOT NULL
                  GROUP BY id_proveedor ORDER BY n DESC, id_proveedor LIMIT %s""", (DESDE, N_PROVEEDORES))
    P = {f["id_proveedor"] for f in top} | m.prov_convenio
    m.por("c_proveedores", "id", P)
    m.PC = {norm_cuit(f["cuit"]) for f in m.filas["c_proveedores"].values()} - {None}

    # ── Lo que cuelga ──
    m.por("p_domicilios_explotacion", "id_empleador", E)
    m.por("p_afiliados_movimientos", "id_afiliado", A)
    m.por("p_atributos_por_afiliado", "id_afiliado", A)
    m.por("p_certificados_discapacidad", "cuil", AC)
    m.por("c_cobro_cuil_equivalencia", "cuil_titular", AC)
    m.poner("s_contactos", en(o, "SELECT * FROM s_contactos WHERE entidad_tipo='empresa' AND entidad_id IN ({in_})", E))
    m.poner("s_contactos", en(o, "SELECT * FROM s_contactos WHERE entidad_tipo='afiliado' AND entidad_id IN ({in_})", A))
    m.poner("s_contactos", en(o, "SELECT * FROM s_contactos WHERE entidad_tipo='proveedor' AND entidad_id IN ({in_})", P))
    cuits_arca = m.ECall | m.PC
    for t in ("arca_constancia", "arca_constancia_actividades", "arca_constancia_impuestos", "arca_constancia_cambios"):
        m.por(t, "cuit", cuits_arca)

    # Proveedores: ficha, comprobantes, mesa, deuda
    for t in ("c_proveedores_cuentas_gasto", "c_proveedores_cuentas_pasivo", "c_proveedores_movimientos",
              "c_proveedores_certificados_exencion"):
        m.por(t, "id_proveedor", P)
    m.por("f_comprobantes_arca", "id_proveedor", P)
    m.por("f_mis_comprobantes", "cuit_emisor", m.PC)
    m.por("me_expedientes", "id_proveedor", P)
    m.por("me_expedientes", "id_comprobante", m.ids("f_comprobantes_arca"))
    EXP = m.ids("me_expedientes")
    m.por("me_expediente_movimientos", "id_expediente", EXP)
    m.por("c_pasivo_liquidacion", "id_expediente", EXP)
    LIQP = m.ids("c_pasivo_liquidacion")
    m.por("c_pasivo_liquidacion_detalle", "id_pasivo_liquidacion", LIQP)

    # Reintegros
    m.por("c_reintegro_afiliados", "id_afiliado", A)
    R = m.ids("c_reintegro_afiliados")
    m.por("c_reintegro_afiliados_detalle", "id_reintegro", R)
    m.por("c_reintegro_afiliados_aprobacion", "id_reintegro", R)

    # Órdenes de pago
    ords = set()
    ords |= {f["id_orden"] for f in en(o, "SELECT id_orden FROM pago_ordenes_detalle WHERE id_expediente IN ({in_})", EXP)}
    ords |= {f["id_orden"] for f in en(o, "SELECT id_orden FROM pago_ordenes_anticipo_det WHERE id_proveedor IN ({in_})", P)}
    ords |= {f["id_orden"] for f in en(o, "SELECT id_orden FROM pago_ordenes_reintegro_det WHERE id_reintegro IN ({in_})", R)}
    ords |= {f["id_orden"] for f in en(o, "SELECT id_orden FROM pago_retenciones WHERE id_proveedor IN ({in_})", P)}
    conocidos = m.AC | m.ECall | m.PC | ({m.cuit_inst} if m.cuit_inst else set())
    for f in q(o, "SELECT id, observaciones FROM pago_ordenes WHERE clase = 'concepto' AND fecha >= %s", (DESDE,)):
        textos = [f["observaciones"] or ""] + [d["descripcion"] or "" for d in
                                                q(o, "SELECT descripcion FROM pago_ordenes_concepto_det WHERE id_orden=%s", (f["id"],))]
        ajenos = {re.sub(r"\D", "", x) for t in textos for x in RE_CUIT_TXT.findall(t)} - conocidos
        if not ajenos:
            ords.add(f["id"])
    m.por("pago_ordenes", "id", ords)
    O = m.ids("pago_ordenes")
    for t in ("pago_ordenes_detalle", "pago_ordenes_anticipo_det", "pago_ordenes_concepto_det",
              "pago_ordenes_reintegro_det", "pago_ordenes_aprobacion", "pago_ordenes_sueldos_det", "pago_imputaciones"):
        m.por(t, "id_orden", O)
    m.por("pago_pagos", "id_orden", O)
    PG = m.ids("pago_pagos")
    for t in ("pago_pagos_instrumentos", "pago_retenciones", "pago_retenciones_certificado"):
        m.por(t, "id_pago", PG)
    m.por("c_pasivo_aplicacion", "id_liq_debito", LIQP)

    # Cuota sindical: cobros, aplicaciones, actas
    for t in ("fisca_cuotarecepcion", "fisca_importacion_log"):
        m.por(t, "cuit", m.EC)
    m.por("fisca_cuit_relacionado", "cuit_empleador", m.EC)
    m.por("fisca_cuit_afiliado", "cuil_afiliado", AC)
    m.por("fisca_enlace_empresa", "id_empresa", E_sel)
    m.por("fisca_novedad_empresa", "id_enlace", m.ids("fisca_enlace_empresa"))
    m.por("fisca_acta", "cuit", m.EC)
    ACT = m.ids("fisca_acta")
    m.por("fisca_acta_periodo", "id_acta", ACT)
    m.por("fisca_acta_pago", "id_acta_periodo", m.ids("fisca_acta_periodo"))
    m.por("fisca_acuerdo", "id_acta", ACT)
    m.por("fisca_acuerdo_cuota", "id_acuerdo", m.ids("fisca_acuerdo"))

    io = {f["id_orden"] for f in en(o, "SELECT id_orden FROM ingreso_ordenes_detalle WHERE cuit IN ({in_})", m.EC)}
    io |= {f["id"] for f in en(o, "SELECT id FROM ingreso_ordenes WHERE clase='afiliado' AND cuil_afiliado IN ({in_})", AC)}
    io |= {f["id"] for f in en(o, "SELECT id FROM ingreso_ordenes WHERE id_acta IN ({in_})", ACT)}
    for f in q(o, """SELECT o.id, GROUP_CONCAT(IFNULL(d.cuit,'')) cuits, GROUP_CONCAT(IFNULL(d.descripcion,'') SEPARATOR ' ') txt,
                            o.observaciones
                     FROM ingreso_ordenes o LEFT JOIN ingreso_ordenes_detalle d ON d.id_orden = o.id
                     WHERE o.fecha >= %s AND o.clase NOT IN ('cuota_sindical','fiscalizacion','afiliado')
                     GROUP BY o.id""", (DESDE,)):
        cu = {c for c in (f["cuits"] or "").split(",") if c} | {re.sub(r"\D", "", x) for x in
                                                               RE_CUIT_TXT.findall((f["txt"] or "") + (f["observaciones"] or ""))}
        if not (cu - conocidos):
            io.add(f["id"])
    m.por("ingreso_ordenes", "id", io)
    IO = m.ids("ingreso_ordenes")
    m.por("ingreso_ordenes_detalle", "id_orden", IO)
    m.por("ingreso_ordenes_cuentas", "id_orden", IO)
    m.por("fisca_acuerdo_imputacion", "id_orden", IO)
    m.por("fisca_aplicacion", "id_liquidacion", L)

    # Tesorería: el libro de lo que vino + los pases de los últimos meses
    m.donde("c_movimiento_entre_cuentas", "fecha_emision >= %s", (DESDE,))
    MEC = m.ids("c_movimiento_entre_cuentas")
    m.por("c_movimiento_entre_cuentas_det", "id_movimiento", MEC)
    m.por("c_movimientos_de_fondos", "pago_pagosId", PG)
    m.por("c_movimientos_de_fondos", "ingreso_ordenesId", IO)
    m.por("c_movimientos_de_fondos", "c_movimiento_entre_cuentasId", MEC)
    MF = m.ids("c_movimientos_de_fondos")
    m.por("c_debitos_creditos_bancarios", "c_movimientos_de_fondosId", MF)
    vals = {f["id_valor"] for f in en(o, "SELECT id_valor FROM c_valores_de_terceros_movimientos WHERE id_ingreso IN ({in_})", IO)}
    vals |= {f["id_valor"] for f in en(o, "SELECT id_valor FROM c_valores_de_terceros_movimientos WHERE id_pago IN ({in_})", PG)}
    vals |= {f["id_valor"] for f in en(o, "SELECT id_valor FROM c_valores_de_terceros_movimientos WHERE id_movimiento_cuentas IN ({in_})", MEC)}
    m.por("c_valores_de_terceros", "id", vals)
    m.por("c_valores_de_terceros_movimientos", "id_valor", vals)

    # Extractos: los últimos meses, sin las acreditaciones de terceros que no están en la muestra
    pagadores = {norm_cuit(f["cuit_pagador"]) for f in m.filas["fisca_cuit_relacionado"].values()}
    pagadores |= {norm_cuit(f["cuit_pagador"]) for f in m.filas["fisca_cuit_afiliado"].values()}
    propios = conocidos | pagadores
    ext = q(o, "SELECT * FROM c_extractos_bancarios WHERE fecham >= %s", (DESDE,))
    refs = {f["id_extracto_origen"] for f in m.filas["ingreso_ordenes_detalle"].values()}
    refs |= {f["id_extracto_origen"] for f in m.filas["pago_ordenes_concepto_det"].values()}
    refs.discard(None)
    ya = {f["id"] for f in ext}
    ext += en(o, "SELECT * FROM c_extractos_bancarios WHERE id IN ({in_})", refs - ya)
    m.frecuencia = Counter(tok for f in ext for tok in set((f["concepto"] or "").upper().split()))
    guardar = []
    for f in ext:
        c = norm_cuit(f["cuit"])
        if f["id"] in refs or c in propios or c is None:
            guardar.append(f)
    m.poner("c_extractos_bancarios", guardar)
    m.por("c_extracto_cuil_asignado", "id_extracto", m.ids("c_extractos_bancarios"))

    # Beneficios y elecciones
    for t in ("ben_adherido", "ben_campania_envio", "ben_entrega", "el_padron"):
        m.por(t, "id_afiliado", A)
    m.poner("ben_entrega_mov", en(o, "SELECT * FROM ben_entrega_mov WHERE id_afiliado IN ({in_})", A))
    m.poner("el_padron_mov", en(o, "SELECT * FROM el_padron_mov WHERE id_afiliado IN ({in_})", A))

    # Contabilidad (si hubiera): los asientos de los últimos meses
    if "c_asientos" in tablas_origen:
        m.donde("c_asientos", "fecha >= %s", (DESDE,))
        m.por("c_asiento_detalle", "id_asiento", m.ids("c_asientos", "id_asiento"))

    m.resumen = dict(empleadores=len(m.EC), empresas=len(E), afiliados=len(A),
                     titulares=sum(1 for f in m.filas["p_afiliados"].values() if f["cod_parentesco"] == 0),
                     proveedores=len(P))


# ── Anonimizar ────────────────────────────────────────────────────────────────

def anonimizar(m: Muestra) -> Anon:
    exentos = {norm_cuit(f["cuit"]) for f in m.filas["c_proveedores"].values() if f["id"] in m.prov_convenio}
    exentos.discard(None)
    an = Anon(exentos)

    # Primero se registran las entidades, así los textos se reemplazan con los mismos nombres
    for f in m.filas["s_institucion"].values():
        an.registrar(f["nombre"], "ASOCIACION DE EMPLEADOS DEMO")
        if f.get("cuit"):
            an.cuit(f["cuit"])
        for c in ("secretario_general", "secretario_adjunto", "tesorero"):
            an.registrar(f.get(c))
    for f in m.filas["p_afiliados"].values():
        if f["cuil"]:
            an.cuit(f["cuil"])
        an.registrar(f["apellido_nombres"], sexo=f.get("sexo"))
    for f in m.filas["p_empresas"].values():
        an.cuit(f["CUIT"])
        es_persona = str(f["CUIT"])[:2] in ("20", "23", "24", "27")
        an.registrar(f["razon_social"], tipo="persona" if es_persona else "empresa")
        if f.get("nombre_fantasia") and clave_nombre(f["nombre_fantasia"]) != clave_nombre(f["razon_social"]):
            an.registrar(f["nombre_fantasia"], tipo="empresa")
    for f in m.filas["c_proveedores"].values():
        if f["id"] in m.prov_convenio:
            continue
        an.cuit(f["cuit"])
        es_persona = str(f["cuit"])[:2] in ("20", "23", "24", "27")
        an.registrar(f["razon_social"], tipo="persona" if es_persona else "empresa")
        if f.get("nombre_fantasia"):
            an.registrar(f["nombre_fantasia"], tipo="empresa")
    for f in m.filas["fisca_fiscalizador"].values():
        an.registrar(f["apellido_nombres"])
    for f in m.filas["s_contactos"].values():
        an.registrar(f["nombre"])

    # Usuarios demo: el mismo id, otro mail y otra clave
    roles = defaultdict(list)
    nombres_rol = {f["id"]: f["nombre"] for f in m.filas["s_roles"].values()}
    prio = {f["id"]: f["prioridad"] for f in m.filas["s_roles"].values()}
    for f in m.filas["s_usuario_rol"].values():
        roles[f["usuario_id"]].append(f["rol_id"])
    hash_demo = generate_password_hash(DEMO_CLAVE)
    usados = Counter()
    for f in sorted(m.filas["s_usuarios"].values(), key=lambda x: x["id"]):
        rid = max(roles.get(f["id"], [0]), key=lambda r: prio.get(r, -1))
        rol = sin_acentos(nombres_rol.get(rid, "usuario")).lower()
        usados[rol] += 1
        email = f"{rol}{'' if usados[rol] == 1 else usados[rol]}@demo.local"
        nombre = f"{nombres_rol.get(rid, 'Usuario')} Demo{'' if usados[rol] == 1 else ' ' + str(usados[rol])}"
        an.mails[f["email"].lower()] = email
        an.registrar(f["nombre"], nombre)
        f.update(email=email, nombre=nombre, password_hash=hash_demo, google_id=None, avatar_url=None, activo=1)
    m.usuarios_demo = sorted((f["email"] for f in m.filas["s_usuarios"].values()))

    # Cuentas propias: el número de cuenta también va en el nombre
    for f in m.filas["c_cuentas_de_fondos"].values():
        real = re.sub(r"\D", "", f.get("numero_de_cuenta") or "")
        falso = an.digitos(real) if real else None
        for c in ("nombre", "comentario", "alias"):
            if real and len(real) >= 5 and f.get(c):
                f[c] = f[c].replace(real, falso)
        if f.get("numero_de_cuenta"):
            f["numero_de_cuenta"] = falso
        if f.get("alias"):
            f["alias"] = an.alias(f["alias"])

    # Datos del sindicato
    for f in m.filas["s_institucion"].values():
        f.update(nombre="ASOCIACION DE EMPLEADOS DEMO", sigla="DEMO", personeria_gremial="N° 0000",
                 inscripcion_gremial="N° 0000", web="www.ejemplo.com.ar", logo_path=None,
                 nro_iibb="901-000000-0", nro_resolucion_ret=None)
    for f in m.filas["mail_config"].values():
        f.update(host="smtp.ejemplo.com.ar", usuario="avisos@ejemplo.com.ar", password_cif=None,
                 remitente_email="avisos@ejemplo.com.ar", responder_a=None, activo=0, probado_at=None)
    for f in m.filas["ben_campania"].values():
        f.update(flyer_archivo=None)
    for f in m.filas["f_comprobantes_arca"].values():
        f.update(ruta_local=None, nombre_archivo=None)

    # Extractos: solo las palabras de los conceptos que se repiten (las del banco), no los nombres
    for f in m.filas["c_extractos_bancarios"].values():
        if f.get("concepto"):
            toks = [t for t in f["concepto"].split()
                    if m.frecuencia[t.upper()] >= 15 or (re.search(r"\d", t) and len(re.sub(r"\D", "", t)) < 7)]
            f["concepto"] = " ".join(toks)[:100] or "MOVIMIENTO"
    # Saldos del extracto recalculados sobre lo que vino (no son los del banco)
    por_cuenta = defaultdict(list)
    for f in m.filas["c_extractos_bancarios"].values():
        por_cuenta[f["c_cuentas_de_fondos_id"]].append(f)
    for filas in por_cuenta.values():
        filas.sort(key=lambda x: (x["fecham"], x["id"]))
        acum, minimo = Decimal(0), Decimal(0)
        for f in filas:
            acum += Decimal(f["credito"] or 0) - Decimal(f["debito"] or 0)
            minimo = min(minimo, acum)
        saldo = -minimo + Decimal("2500000")
        for f in filas:
            saldo += Decimal(f["credito"] or 0) - Decimal(f["debito"] or 0)
            f["saldo"] = saldo

    # Columna por columna, en todas las tablas
    n = 0
    for t, filas in m.filas.items():
        for f in filas.values():
            if t == "s_usuarios":
                continue
            sexo = f.get("sexo") if t == "p_afiliados" else None
            for c, v in list(f.items()):
                if v is None or isinstance(v, (bytes, bytearray)):
                    continue
                lc = c.lower()
                if lc in COLS_A_NULL:
                    f[c] = None
                elif (t, c) in SOLO_MARCAS:
                    f[c] = " ".join(RE_MARCA.findall(str(v))) or None
                elif t in ("p_afiliados_movimientos", "c_proveedores_movimientos") and lc in ("valor_anterior", "valor_actual"):
                    f[c] = valor_auditado(an, f.get("campo") or "", v)
                elif "cuit" in lc or "cuil" in lc:
                    f[c] = an.cuit(v)
                elif lc in COLS_DNI:
                    f[c] = an.dni(v)
                elif lc in COLS_NOMBRE or (lc == "nombre" and t in TABLAS_NOMBRE_PERSONA):
                    tipo = "persona" if lc in ("apellido_nombres", "inspector", "representante", "retiro_nombre",
                                               "nombre", "secretario_general", "secretario_adjunto", "tesorero") else "auto"
                    f[c] = an.nombre(v, tipo=tipo, sexo=sexo)
                elif "email" in lc or lc in ("responder_a", "mail"):
                    f[c] = an.mail(v)
                elif lc in COLS_TEL:
                    f[c] = an.tel(v)
                elif "alias" in lc:
                    f[c] = an.alias(v)
                elif "cbu" in lc:
                    f[c] = an.cbu(v)
                elif lc in COLS_CALLE:
                    f[c] = an.calle(v)
                elif lc in COLS_CUENTA:
                    f[c] = an.digitos(v)
                elif lc == "token_hash":
                    f[c] = hashlib.sha256(f"{SAL}{v}".encode()).hexdigest()
                elif isinstance(v, str):
                    f[c] = an.texto(v)
            n += 1
    print(f"Anonimizados {n:,} renglones".replace(",", "."))
    return an


def valor_auditado(an: Anon, campo: str, v):
    c = campo.lower()
    if "cuil" in c or "cuit" in c:
        return an.cuit(v)
    if "documento" in c or c == "dni":
        return an.dni(v)
    if "apellido" in c or "nombre" in c or "razon" in c:
        return an.nombre(v)
    if "mail" in c:
        return an.mail(v)
    if "tel" in c or "celular" in c:
        return an.tel(v)
    if "cbu" in c:
        return an.cbu(v)
    if "alias" in c:
        return an.alias(v)
    if "domicilio" in c or "calle" in c:
        return an.calle(v)
    return an.texto(v)


# ── Grabar ────────────────────────────────────────────────────────────────────

def columnas_destino(dest) -> dict[str, list[str]]:
    cols = defaultdict(list)
    for f in q(dest, """SELECT c.table_name t, c.column_name c, c.extra x FROM information_schema.columns c
                        JOIN information_schema.tables tb ON tb.table_schema = c.table_schema AND tb.table_name = c.table_name
                        WHERE c.table_schema = %s AND tb.table_type = 'BASE TABLE'
                        ORDER BY c.table_name, c.ordinal_position""", (DB_NAME,)):
        if "VIRTUAL GENERATED" in f["x"] or "STORED GENERATED" in f["x"]:
            continue
        cols[f["t"]].append(f["c"])
    return cols


def grabar(m: Muestra, dest):
    cols = columnas_destino(dest)
    with dest.cursor() as cur:
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        cur.execute("SET UNIQUE_CHECKS = 0")
        print("Vaciando sindicato (localhost)…")
        for t in cols:
            cur.execute(f"DELETE FROM `{t}`")
        resultado = {}
        for t, filas in sorted(m.filas.items()):
            if t not in cols or not filas:
                continue
            filas = list(filas.values())
            usar = [c for c in cols[t] if c in filas[0]]
            sql = (f"INSERT IGNORE INTO `{t}` ({','.join('`' + c + '`' for c in usar)}) "
                   f"VALUES ({','.join(['%s'] * len(usar))})")
            n = 0
            for i in range(0, len(filas), LOTE):
                n += cur.executemany(sql, [tuple(f[c] for c in usar) for f in filas[i:i + LOTE]])
            resultado[t] = (len(filas), n)
        print("Sacando lo que quedó colgado…")
        fks = q(dest, """
            SELECT k.constraint_name, k.table_name t, k.column_name c, k.referenced_table_name rt,
                   k.referenced_column_name rc, col.is_nullable nul
            FROM information_schema.key_column_usage k
            JOIN information_schema.columns col ON col.table_schema = k.table_schema AND col.table_name = k.table_name
                 AND col.column_name = k.column_name
            WHERE k.table_schema = %s AND k.referenced_table_name IS NOT NULL""", (DB_NAME,))
        vueltas = 0
        while True:
            vueltas += 1
            tocados = 0
            for fk in fks:
                # Con LEFT JOIN y no con NOT EXISTS: MySQL no deja leer en un subquery la tabla que se
                # modifica (error 1093), y hay FK de una tabla a sí misma (menú, plan, áreas, grupos).
                desde = (f"`{fk['t']}` t LEFT JOIN `{fk['rt']}` p ON p.`{fk['rc']}` = t.`{fk['c']}`")
                cond = f"t.`{fk['c']}` IS NOT NULL AND p.`{fk['rc']}` IS NULL"
                if fk["nul"] == "YES" and ((fk["t"], fk["c"]) in A_NULL or fk["rt"] in PADRES_A_NULL):
                    cur.execute(f"UPDATE {desde} SET t.`{fk['c']}` = NULL WHERE {cond}")
                else:
                    cur.execute(f"DELETE t FROM {desde} WHERE {cond}")
                tocados += cur.rowcount
            if not tocados or vueltas > 15:
                break
        cur.execute("SET UNIQUE_CHECKS = 1")
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")
    dest.commit()
    return resultado, vueltas


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aplicar", action="store_true", help="vacía sindicato de localhost y la carga")
    ap.add_argument("--local-user", default="root")
    ap.add_argument("--local-port", type=int, default=3306)
    args = ap.parse_args()

    orig = conectar_origen()
    dest = conectar_destino(args) if args.aplicar else None
    if dest:
        o_id = q(orig, "SELECT @@server_uuid u")[0]["u"]
        d_id = q(dest, "SELECT @@server_uuid u")[0]["u"]
        if o_id == d_id:
            sys.exit("El destino es el mismo servidor que el origen: no se hace nada.")

    rng = random.Random(SAL)
    m = Muestra(orig)
    elegir(m, rng)
    print("Muestra:", ", ".join(f"{k} {v}" for k, v in m.resumen.items()))
    anonimizar(m)
    total = sum(len(v) for v in m.filas.values())
    print(f"{total:,} renglones en {sum(1 for v in m.filas.values() if v)} tablas".replace(",", "."))
    for t in sorted(m.filas, key=lambda x: -len(m.filas[x]))[:25]:
        print(f"  {t:42} {len(m.filas[t]):>7}")

    if not args.aplicar:
        print("\nSimulación: no se escribió nada. Para cargar: python cargar_demo_local.py --aplicar")
        return
    res, vueltas = grabar(m, dest)
    print(f"\nCargado en sindicato de localhost ({vueltas} vueltas de limpieza de FK).")
    perdidas = {t: (a, b) for t, (a, b) in res.items() if a != b}
    if perdidas:
        print("Renglones que la base no aceptó (duplicados u otros):")
        for t, (a, b) in perdidas.items():
            print(f"  {t:42} {a:>7} → {b:>7}")
    print(f"\nIngreso: {', '.join(m.usuarios_demo)} — clave {DEMO_CLAVE}")


if __name__ == "__main__":
    main()
