"""
fisca_lsd.py — La empresa presenta su Libro de Sueldos Digital y la cuota
sindical se liquida con él.

Pedido del 12/11/2026: «una interfaz para que las empresas suban este archivo
y complete sola la planilla para la liquidación de la cuota sindical con los
CUIL activos de AEDA». El archivo es el de liquidación del Libro de Sueldos
Digital de ARCA («Liquidación de SyJ - DJ F931», lsd_lector.py), el que el
sistema de sueldos de la empresa arma todos los meses.

CÓMO ENTRA LA EMPRESA (decidido el 12/11/2026)
Con un ENLACE PERSONAL, sin usuario ni clave: /empresas/<token>. Se genera en
Empleadores, solapa «Cuota sindical», y se le manda por mail desde ahí. Del
token se guarda solo el hash (fisca_enlace_empresa): el enlace se ve una vez,
al generarlo; para volver a mandarlo se genera otro, y el anterior deja de
andar. «Revocar» lo corta sin generar otro. Con el enlace la empresa ve solo lo
suyo: sube archivos de su CUIT y descarga sus planillas.

EL INSTRUCTIVO (pedido del 15/11/2026: «en el enlace enviar siempre el pdf del
instructivo»). Todas las páginas del enlace tienen el botón «Instructivo»
(/empresas/<token>/instructivo.pdf, instructivo_empresa.py) y la de la empresa
el bloque «Pago de la cuota y consultas»: la cuenta y el correo de Datos del
Sindicato (institucion.pago_cuota). El mail del enlace trae la dirección del
instructivo: un mailto no adjunta archivos. Adentro, /fiscalizacion/lsd/
instructivo.pdf (?id_empresa=) para mirarlo o adjuntarlo a mano.

QUÉ HACE CON EL ARCHIVO
1. Lo lee y lo valida: el diseño de ARCA, el CUIT del enlace, un período que ya
   empezó. Un archivo con errores no se guarda: se muestran los renglones.
2. Arma la planilla (`armar_planilla`), sin grabar todavía (queda «sin
   presentar»): un renglón por afiliado de AEDA —titular del padrón en el
   período, la regla de fisca_liquidacion— que esté en el archivo, con su
   Remuneración imponible 5 (registro 04, la misma base que la DDJJ de OSEDA)
   y la cuota a la alícuota de Datos del Sindicato, más los activos del
   empleador (relación laboral vigente con ese CUIT) que no están en el
   archivo, en cero. Los trabajadores que no son afiliados no entran: se
   cuentan. Si el recibo trae el concepto ARCA 810004 «Cuota Sindical», se
   muestra lo retenido al lado.
3. Al confirmar, la planilla ES la liquidación de ese CUIT y período
   (fisca_liquidacion, origen «lsd»; detalle «lsd» y «sin_lsd»): reemplaza a la
   de DDJJ de OSEDA, conserva lo que había liquidado AEDA, y «Liquidar» por
   DDJJ ya no la pisa. La presentación anterior del mismo período queda
   «reemplazada»: manda la última. Por eso, si el mes tuvo más de una
   liquidación (el SAC aparte), se sube la última, que trae en su registro 04
   las bases acumuladas del mes.
4. Control contra la DDJJ de OSEDA (ficha interna). Antes la planilla la
   generaba el sistema viejo, se mandaba por mail y el empleador la completaba
   a mano: no era nada seguro. Ahora los importes salen del archivo que la
   empresa declaró a ARCA, pero es un texto y se puede editar antes de
   subirlo: por eso la ficha compara, para cada afiliado que está en la DDJJ de
   OSEDA de ese CUIT, su Remuneración imponible 5 con la del archivo, y marca
   las diferencias de un peso o más (`control_ddjj`, en vivo de Railway). Los
   que tienen otra obra social no se pueden controlar así.
5. La empresa descarga la planilla en Excel, con el formato de la planilla de
   aportes del art. 38 de la Ley 23.551 (CUIT, período y empresa en la fila 3;
   un renglón por afiliado desde la 5), el que lee Importar Cuotas.

ADENTRO
Fiscalización de Cuotas → Presentaciones LSD (/fiscalizacion/lsd, menú 7): lo
presentado, con su planilla y el archivo original; subir un archivo por una
empresa (la que lo manda por mail); y anular una presentación, que devuelve la
liquidación a la DDJJ de OSEDA (hace falta Railway).
"""

from __future__ import annotations

import datetime
import hashlib
import io
import os
import re
import secrets
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import quote

from flask import (Blueprint, abort, flash, redirect, render_template, request, send_file, session,
                   url_for)

import almacenamiento
import contable_oseda
import fisca_intereses as FI
import fisca_liquidacion as FL
import fisca_novedades as NOV
import lsd_lector
from pagos_datos import leer_importe
from db import get_connection, puede, usuario_actual, validasesion
from exportar import xlsx

fisca_lsd_bp = Blueprint("fisca_lsd", __name__, url_prefix="/fiscalizacion")
portal_bp = Blueprint("portal", __name__, url_prefix="/empresas")

SQL_ESQUEMA = "sql/fisca_lsd_20261112.sql"
MAX_BYTES = 10 * 1024 * 1024        # un LSD de 2.000 trabajadores ronda 1 MB
CENT = Decimal("0.01")
ESTADOS = {"borrador": ("Sin presentar", "warn"), "presentada": ("Presentada", "ok"),
           "reemplazada": ("Reemplazada", "neutro"), "anulada": ("Anulada", "danger")}
ORIGENES = {"empresa": "La empresa, por su enlace", "interno": "Un usuario del sindicato"}
RE_TOKEN = re.compile(r"^[A-Za-z0-9_-]{30,60}$")

#: Texto de confidencialidad (pedido del 12/11/2026): el mismo en el mail del
#: enlace y en la página donde la empresa sube el archivo. La afiliación
#: sindical es un dato sensible (Ley 25.326, art. 2). Se cambia acá y sale igual
#: en los dos lugares.
CONFIDENCIALIDAD = (
    "Confidencialidad de los datos. La información que se presenta por este medio —datos personales de los "
    "trabajadores, sus remuneraciones y su afiliación sindical— es confidencial y está protegida por la Ley 25.326 "
    "de Protección de Datos Personales; la afiliación sindical es un dato sensible (art. 2). El sindicato la usa "
    "solamente para liquidar y fiscalizar la cuota sindical (Ley 23.551, art. 38), no la cede a terceros y la "
    "guarda con acceso restringido. El enlace es personal de la empresa: no debe reenviarse ni publicarse, y solo "
    "deben usarlo las personas a cargo de la liquidación de sueldos. Si recibieron este enlace por error, avisen "
    "al sindicato y eliminen el mensaje.")


class ErrorPresentacion(ValueError):
    """Un error que se muestra tal cual; `detalle`, los renglones del archivo que fallan."""

    def __init__(self, texto: str, detalle: list[str] | None = None):
        super().__init__(texto)
        self.detalle = detalle or []

    def lista(self) -> list[str]:
        return [str(self)] + self.detalle

    def __str__(self) -> str:
        base = super().__str__()
        return base + (" " + " · ".join(self.detalle) if self.detalle else "")


def _pesos(v) -> str:
    return f"{Decimal(str(v or 0)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def falta_esquema(cur) -> bool:
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.tables
                    WHERE table_schema = DATABASE() AND table_name = 'fisca_lsd_presentacion'""")
    return not cur.fetchone()["n"]


# ─────────────────────────────────────────────────────────────────────────────
# Enlaces de las empresas
# ─────────────────────────────────────────────────────────────────────────────

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def nuevo_enlace(cur, empresa: dict, id_usuario: int | None) -> str:
    """Genera el enlace de la empresa y corta los anteriores. Devuelve el token:
    es la única vez que se lo tiene, en la base queda el hash."""
    cuit = FL._digitos(empresa["CUIT"])
    revocar_enlaces(cur, cuit, id_usuario)
    token = secrets.token_urlsafe(32)
    cur.execute("""INSERT INTO fisca_enlace_empresa (cuit, id_empresa, token_hash, pista, id_usuario)
                   VALUES (%s, %s, %s, %s, %s)""", (cuit, empresa["id"], _hash(token), token[-4:], id_usuario))
    return token


def revocar_enlaces(cur, cuit: str, id_usuario: int | None) -> int:
    cur.execute("""UPDATE fisca_enlace_empresa SET revocado = NOW(), id_usuario_revoca = %s
                    WHERE cuit = %s AND revocado IS NULL""", (id_usuario, cuit))
    return cur.rowcount


def enlace_vigente(cur, cuit: str) -> dict | None:
    cur.execute("""SELECT e.*, u.nombre AS usuario FROM fisca_enlace_empresa e
                     LEFT JOIN s_usuarios u ON u.id = e.id_usuario
                    WHERE e.cuit = %s AND e.revocado IS NULL ORDER BY e.id DESC LIMIT 1""", (cuit,))
    return cur.fetchone()


def enlace_por_token(cur, token: str) -> dict | None:
    if not RE_TOKEN.match(token or ""):
        return None
    cur.execute("""SELECT e.id, e.cuit, e.id_empresa, p.razon_social, p.nombre_fantasia
                     FROM fisca_enlace_empresa e
                     LEFT JOIN p_empresas p ON p.CUIT = CAST(e.cuit AS UNSIGNED)
                    WHERE e.token_hash = %s AND e.revocado IS NULL""", (_hash(token),))
    return cur.fetchone()


def url_enlace(token: str) -> str:
    """El enlace completo. SIND_URL_PUBLICA (https://aeda.seggestion.com.ar) manda
    si está: desde el IIS de la red local, url_for armaría una dirección que
    la empresa no puede abrir."""
    base = os.getenv("SIND_URL_PUBLICA", "").strip().rstrip("/")
    if base:
        return base + url_for("portal.empresa", token=token)
    return url_for("portal.empresa", token=token, _external=True)


def url_instructivo(enlace: str) -> str:
    """El instructivo en PDF de la empresa: cuelga de su enlace (portal.instructivo)."""
    return enlace.rstrip("/") + "/instructivo.pdf"


def mailto(empresa: dict, emails: list[str], enlace: str, inst: dict | None = None) -> str:
    """El mail para mandarle el enlace a la empresa, listo para el cliente de
    correo. Un mailto no puede adjuntar archivos: el instructivo va como
    dirección, y se abre también desde el botón «Instructivo» del enlace."""
    sigla = (inst or {}).get("sigla") or "el sindicato"
    asunto = f"Cuota sindical: enlace para presentar la cuota y la nómina — {empresa.get('razon_social') or ''}"
    cuerpo = (
        f"Estimados:\n\nDesde este enlace pueden presentar todos los meses la cuota sindical de {sigla} —subiendo el "
        f"archivo de liquidación del Libro de Sueldos Digital que su sistema de sueldos genera para ARCA (el .txt de "
        f"«Liquidación de SyJ - DJ F931») o cargando las remuneraciones a mano— y mantener al día la nómina de "
        f"afiliados, informando altas y bajas.\n\n{enlace}\n\n"
        f"Instructivo de uso (PDF), con la cuenta donde se paga la cuota y el correo para consultas:\n"
        f"{url_instructivo(enlace)}\n\n"
        "El sistema arma la planilla con los afiliados y la cuota a pagar, y la pueden descargar en Excel. "
        "Si en el mes hicieron más de una liquidación (por ejemplo el SAC aparte), suban la última.\n\n"
        "Saludos.\n\n— \n" + CONFIDENCIALIDAD)
    return (f"mailto:{','.join(emails)}?subject={quote(asunto)}&body={quote(cuerpo)}")


def emails_empresa(cur, empresa: dict) -> list[str]:
    """Los mails del empleador: el de la ficha y los de sus contactos activos."""
    vistos, salida = set(), []
    textos = [empresa.get("email") or ""]
    cur.execute("""SELECT email FROM s_contactos WHERE entidad_tipo = 'empresa' AND entidad_id = %s
                      AND activo = 1 AND email IS NOT NULL ORDER BY principal DESC, id""", (empresa["id"],))
    textos += [f["email"] for f in cur.fetchall()]
    for t in textos:
        for m in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", t or ""):
            if m.lower() not in vistos:
                vistos.add(m.lower())
                salida.append(m)
    return salida


# ─────────────────────────────────────────────────────────────────────────────
# La planilla
# ─────────────────────────────────────────────────────────────────────────────

def _cuota(remuneracion, alicuota: Decimal) -> Decimal:
    return (Decimal(str(remuneracion or 0)) * alicuota / 100).quantize(CENT, rounding=ROUND_HALF_UP)


def armar_planilla(lectura: dict, padron: dict, alicuota: Decimal, altas: dict | None = None) -> dict:
    """
    La planilla de cuota sindical del archivo, sin base de datos (la prueban los
    tests). `padron` es el de FL.leer_padron. `altas`, las que informó la
    empresa y están pendientes ({cuil: {apellido_nombres, fecha, id_afiliado}},
    fisca_novedades.altas_pendientes): la cuota ya las toma desde su fecha, con
    fuente «alta», estén o no en el archivo.

    {"cuit", "periodo", "lineas": [{cuil, id_afiliado, nombre, remuneracion,
    cuota, fuente, activo, retenido, fecha_alta, fecha_baja}], "trabajadores",
    "no_afiliados", "activos", "en_archivo", "fuera_nomina", "afiliados",
    "remuneracion", "importe", "retenido"}
    """
    cab = lectura["cabecera"]
    cuit, periodo = cab["cuit"], f"{cab['periodo']:06d}"
    del_periodo = FL.afiliados_del_periodo(periodo, padron)
    activos = FL.activos_por_empleador(periodo, padron, del_periodo).get(cuit, {})

    altas = _altas_del_periodo(altas, periodo, activos)
    lineas, no_afiliados = {}, 0
    for t in lectura["trabajadores"]:
        a = del_periodo.get(t["cuil"])
        alta = altas.get(t["cuil"])
        if not a and not alta:
            no_afiliados += 1
            continue
        base = (t["f931"] or {}).get("base_imponible_5") or Decimal("0")
        ret = [c["importe"] for c in t["conceptos"]
               if (c["codigo"] or "").strip() == lsd_lector.CONCEPTO_CUOTA_SINDICAL and c["dc"] == "D"]
        lineas[t["cuil"]] = {"cuil": t["cuil"], "id_afiliado": (a or alta)["id_afiliado"],
                             "nombre": (a or alta)["apellido_nombres"], "remuneracion": base,
                             "fuente": "alta" if alta else "lsd", "activo": t["cuil"] in activos,
                             "retenido": sum(ret, Decimal("0")) if ret else None,
                             "fecha_alta": (a or {}).get("fecha_alta"), "fecha_baja": (a or {}).get("fecha_baja")}
    for cuil, alta in altas.items():
        lineas.setdefault(cuil, _linea_alta(cuil, alta, Decimal("0")))
    for cuil, a in activos.items():
        lineas.setdefault(cuil, {"cuil": cuil, "id_afiliado": a["id_afiliado"], "nombre": a["apellido_nombres"],
                                 "remuneracion": Decimal("0"), "fuente": "sin_lsd", "activo": True,
                                 "retenido": None, "fecha_alta": a["fecha_alta"], "fecha_baja": a["fecha_baja"]})

    salida = []
    for l in lineas.values():
        if l["fuente"] == "lsd" and l["remuneracion"] <= 0 and not l["activo"]:
            continue                   # en el archivo en cero y no es de su nómina: no aporta nada
        l["cuota"] = _cuota(l["remuneracion"], alicuota) if l["remuneracion"] > 0 else Decimal("0.00")
        salida.append(l)
    salida.sort(key=lambda l: (l["fuente"] == "sin_lsd", (l["nombre"] or "").upper(), l["cuil"]))
    return _totales(cuit, periodo, salida, activos, no_afiliados,
                    sum(1 for t in lectura["trabajadores"] if t["f931"]))


def _altas_del_periodo(altas: dict | None, periodo: str, activos: dict) -> dict:
    """Las altas pendientes que cuentan en el período: con fecha de alta hasta el
    último día del mes y que no figuran ya como activos del empleador."""
    hasta = FL.limites(periodo)[1]
    return {c: a for c, a in (altas or {}).items() if c not in activos and a["fecha"] and a["fecha"] <= hasta}


def _linea_alta(cuil: str, alta: dict, remuneracion: Decimal) -> dict:
    return {"cuil": cuil, "id_afiliado": alta.get("id_afiliado"), "nombre": alta.get("apellido_nombres"),
            "remuneracion": remuneracion, "fuente": "alta", "activo": False, "retenido": None,
            "fecha_alta": alta.get("fecha"), "fecha_baja": None}


def _totales(cuit: str, periodo: str, salida: list[dict], activos: dict, no_afiliados: int,
             trabajadores: int) -> dict:
    retenidos = [l["retenido"] for l in salida if l["retenido"] is not None]
    return {
        "cuit": cuit, "periodo": periodo, "lineas": salida,
        "trabajadores": trabajadores,
        "no_afiliados": no_afiliados,
        "activos": len(activos),
        "en_archivo": sum(1 for l in salida if l["activo"] and l["fuente"] in ("lsd", "manual")
                          and (l["fuente"] == "lsd" or l["remuneracion"] > 0)),
        "altas": sum(1 for l in salida if l["fuente"] == "alta"),
        "fuera_nomina": sum(1 for l in salida if not l["activo"]),
        "afiliados": sum(1 for l in salida if l["cuota"] > 0),
        "remuneracion": sum((l["remuneracion"] for l in salida), Decimal("0")),
        "importe": sum((l["cuota"] for l in salida), Decimal("0")),
        "retenido": sum(retenidos, Decimal("0")) if retenidos else None,
    }


def armar_planilla_manual(cuit: str, periodo: str, remuneraciones: dict, padron: dict, alicuota: Decimal,
                          altas: dict | None = None) -> dict:
    """
    La planilla de una carga A MANO (sin el archivo del Libro de Sueldos
    Digital): un renglón por afiliado activo de la empresa en el período (su
    nómina según el padrón), con la remuneración que cargó la empresa (fuente
    «manual»; sin cargar, cero), y uno por cada alta pendiente que cuenta en el
    período (fuente «alta»). `remuneraciones`: {cuil: Decimal}. Sin base de datos.
    """
    del_periodo = FL.afiliados_del_periodo(periodo, padron)
    activos = FL.activos_por_empleador(periodo, padron, del_periodo).get(cuit, {})
    altas = _altas_del_periodo(altas, periodo, activos)
    salida = []
    for cuil, a in activos.items():
        rem = Decimal(str(remuneraciones.get(cuil) or 0))
        salida.append({"cuil": cuil, "id_afiliado": a["id_afiliado"], "nombre": a["apellido_nombres"],
                       "remuneracion": rem, "fuente": "manual", "activo": True, "retenido": None,
                       "fecha_alta": a["fecha_alta"], "fecha_baja": a["fecha_baja"]})
    for cuil, alta in altas.items():
        salida.append(_linea_alta(cuil, alta, Decimal(str(remuneraciones.get(cuil) or 0))))
    for l in salida:
        l["cuota"] = _cuota(l["remuneracion"], alicuota) if l["remuneracion"] > 0 else Decimal("0.00")
    salida.sort(key=lambda l: (l["fuente"] == "alta", (l["nombre"] or "").upper(), l["cuil"]))
    return _totales(cuit, periodo, salida, activos, 0, len(salida))


def validar(lectura: dict, cuit_esperado: str | None = None) -> list[str]:
    """Los errores que impiden usar el archivo (vacío = se puede)."""
    errores = list(lectura["errores"])
    cab = lectura["cabecera"]
    if not cab:
        return errores or ["El archivo no tiene el registro 01."]
    if cab["envio"] not in ("SJ", "RE"):
        errores.append(f"Identificación del envío «{cab['envio']}»: tiene que ser SJ o RE.")
    if cuit_esperado and cab["cuit"] != cuit_esperado:
        errores.append(f"El archivo es del CUIT {cab['cuit']} y este enlace es del CUIT {cuit_esperado}.")
    periodo = f"{cab['periodo'] or 0:06d}"
    if not FL.periodo_valido(periodo):
        errores.append(f"El período del registro 01 («{cab['periodo']}») no es válido.")
    elif FL.limites(periodo)[0] > datetime.date.today():
        errores.append(f"El período {periodo[:4]}-{periodo[4:]} todavía no empezó.")
    if not any(t["f931"] for t in lectura["trabajadores"]):
        errores.append("El archivo no trae trabajadores (registros 04).")
    return errores


def calcular(cur, lectura: dict) -> dict:
    par = FL.parametros(cur)
    periodo = f"{lectura['cabecera']['periodo']:06d}"
    padron = FL.leer_padron(cur, *FL.limites(periodo))
    altas = NOV.altas_pendientes(cur, lectura["cabecera"]["cuit"])
    return {**armar_planilla(lectura, padron, par["alicuota"], altas), **par, "carga": "archivo"}


def calcular_manual(cur, cuit: str, periodo: str, remuneraciones: dict) -> dict:
    par = FL.parametros(cur)
    padron = FL.leer_padron(cur, *FL.limites(periodo))
    altas = NOV.altas_pendientes(cur, cuit)
    return {**armar_planilla_manual(cuit, periodo, remuneraciones, padron, par["alicuota"], altas), **par,
            "carga": "manual"}


def remuneraciones_de(cur, id_pres: int) -> dict:
    cur.execute("SELECT cuil, remuneracion FROM fisca_lsd_manual WHERE id_presentacion = %s", (id_pres,))
    return {f["cuil"]: f["remuneracion"] for f in cur.fetchall()}


def plan_actual(cur, pres: dict) -> dict:
    """La planilla de una presentación con el padrón de hoy: del archivo o de
    lo cargado a mano."""
    if pres.get("carga") == "manual":
        return calcular_manual(cur, pres["cuit"], pres["periodo"], remuneraciones_de(cur, pres["id"]))
    return calcular(cur, _leer(pres["archivo"], pres["cuit"]))


def _leer(contenido: bytes, cuit_esperado: str | None) -> dict:
    lectura = lsd_lector.leer_liquidacion(contenido)
    errores = validar(lectura, cuit_esperado)
    if errores:
        mas = [f"… y {len(errores) - 15} más."] if len(errores) > 15 else []
        raise ErrorPresentacion("El archivo no se puede usar. No se guardó nada.", errores[:15] + mas)
    return lectura


# ─────────────────────────────────────────────────────────────────────────────
# Presentaciones
# ─────────────────────────────────────────────────────────────────────────────

def guardar_borrador(cur, contenido: bytes, nombre: str, origen: str, cuit_esperado: str | None,
                     id_enlace: int | None, id_usuario: int | None, ip: str | None) -> int:
    """Lee el archivo, arma la planilla y la guarda sin presentar. Devuelve el id."""
    if not contenido:
        raise ErrorPresentacion("El archivo está vacío.")
    if len(contenido) > MAX_BYTES:
        raise ErrorPresentacion(f"El archivo pesa más de {MAX_BYTES // (1024 * 1024)} MB: no es un Libro de Sueldos Digital.")
    lectura = _leer(contenido, cuit_esperado)
    plan = calcular(cur, lectura)
    cab = lectura["cabecera"]
    # Un solo borrador por CUIT: subir otro archivo descarta el que no se presentó.
    cur.execute("DELETE FROM fisca_lsd_presentacion WHERE cuit = %s AND estado = 'borrador'", (cab["cuit"],))
    cur.execute("""INSERT INTO fisca_lsd_presentacion
                     (cuit, periodo, envio, tipo_liq, nro_liquidacion, archivo_nombre, archivo_sha256, archivo,
                      trabajadores, no_afiliados, afiliados_activos, activos_en_archivo, afiliados, remuneracion,
                      importe, retenido, estado, origen, id_enlace, id_usuario, ip)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'borrador', %s, %s, %s, %s)""",
                (cab["cuit"], plan["periodo"], cab["envio"], cab["tipo_liq"] or None, cab["nro_liquidacion"],
                 (nombre or "liquidacion.txt")[:200], hashlib.sha256(contenido).hexdigest(), contenido,
                 plan["trabajadores"], plan["no_afiliados"], plan["activos"], plan["en_archivo"], plan["afiliados"],
                 plan["remuneracion"], plan["importe"], plan["retenido"], origen, id_enlace, id_usuario,
                 (ip or "")[:45] or None))
    return cur.lastrowid


MAX_REMUNERACION = Decimal("999999999.99")


def leer_remuneraciones(form, prefijo: str = "rem_") -> tuple[dict, list[str]]:
    """{cuil: Decimal} de los campos «rem_<cuil>» del formulario de la carga a
    mano, y los errores. Vacío es cero."""
    rems, errores = {}, []
    for k in form:
        if not k.startswith(prefijo):
            continue
        cuil = FL._digitos(k[len(prefijo):])
        texto = (form.get(k) or "").strip()
        if len(cuil) != 11 or not texto:
            continue
        v = leer_importe(texto)
        if v is None or v < 0 or Decimal(str(v)) > MAX_REMUNERACION:
            errores.append(f"CUIL {cuil}: «{texto}» no es una remuneración.")
            continue
        rems[cuil] = Decimal(str(v)).quantize(CENT)
    return rems, errores


def guardar_borrador_manual(cur, cuit: str, periodo: str, remuneraciones: dict, origen: str,
                            id_enlace: int | None, id_usuario: int | None, ip: str | None) -> int:
    """La carga a mano: arma la planilla y la guarda sin presentar, con las
    remuneraciones en fisca_lsd_manual. Devuelve el id."""
    periodo = FL.periodo_valido(periodo)
    if not periodo:
        raise ErrorPresentacion("Elijan el mes (período) de la cuota.")
    if FL.limites(periodo)[0] > datetime.date.today():
        raise ErrorPresentacion(f"El período {periodo[:4]}-{periodo[4:]} todavía no empezó.")
    plan = calcular_manual(cur, cuit, periodo, remuneraciones)
    if not plan["lineas"]:
        raise ErrorPresentacion("En el período no hay afiliados activos en la empresa ni altas informadas: no hay "
                                "nada que cargar. Si alguien falta, informen el alta.")
    if not any(l["remuneracion"] > 0 for l in plan["lineas"]):
        raise ErrorPresentacion("Carguen la remuneración de al menos un afiliado.")
    cur.execute("DELETE FROM fisca_lsd_presentacion WHERE cuit = %s AND estado = 'borrador'", (cuit,))
    cur.execute("""INSERT INTO fisca_lsd_presentacion
                     (cuit, periodo, carga, archivo_nombre, trabajadores, no_afiliados, afiliados_activos,
                      activos_en_archivo, afiliados, remuneracion, importe, estado, origen, id_enlace, id_usuario, ip)
                   VALUES (%s, %s, 'manual', 'Carga manual', %s, 0, %s, %s, %s, %s, %s, 'borrador', %s, %s, %s, %s)""",
                (cuit, periodo, len(plan["lineas"]), plan["activos"], plan["en_archivo"], plan["afiliados"],
                 plan["remuneracion"], plan["importe"], origen, id_enlace, id_usuario, (ip or "")[:45] or None))
    id_pres = cur.lastrowid
    cur.executemany("INSERT INTO fisca_lsd_manual (id_presentacion, cuil, remuneracion) VALUES (%s, %s, %s)",
                    [(id_pres, l["cuil"], l["remuneracion"]) for l in plan["lineas"]])
    return id_pres


def leer_presentacion(cur, id_pres: int, cuit: str | None = None, bloquear: bool = False) -> dict | None:
    cur.execute(f"""SELECT p.*, e.razon_social, e.id AS id_empresa, u.nombre AS usuario
                      FROM fisca_lsd_presentacion p
                      LEFT JOIN p_empresas e ON e.CUIT = CAST(p.cuit AS UNSIGNED)
                      LEFT JOIN s_usuarios u ON u.id = p.id_usuario
                     WHERE p.id = %s {'AND p.cuit = %s' if cuit else ''}
                     {'FOR UPDATE' if bloquear else ''}""", (id_pres, cuit) if cuit else (id_pres,))
    return cur.fetchone()


def planilla_de(cur, pres: dict) -> dict:
    """La planilla de una presentación: si es la vigente, la liquidación grabada
    (es lo que se cobra); si no se presentó, se reemplazó o se anuló, la que
    sale de su archivo con el padrón de hoy (la liquidación ya es de otra)."""
    if pres.get("carga") == "manual":
        plan = plan_actual(cur, pres)
    else:
        plan = calcular(cur, lsd_lector.leer_liquidacion(pres["archivo"]))
    if pres["estado"] == "presentada" and pres["id_liquidacion"]:
        cur.execute("""SELECT d.cuil, d.id_afiliado, COALESCE(d.apellido_nombres, a.apellido_nombres) AS nombre,
                              d.remuneracion, d.cuota, d.fuente, d.activo, a.fecha_alta, a.fecha_baja
                         FROM fisca_liquidacion_detalle d
                         LEFT JOIN p_afiliados a ON a.id_afiliado = d.id_afiliado
                        WHERE d.id_liquidacion = %s
                        ORDER BY d.fuente = 'sin_lsd', nombre, d.cuil""", (pres["id_liquidacion"],))
        ret = {l["cuil"]: l["retenido"] for l in plan["lineas"]}
        plan["lineas"] = [dict(l, retenido=ret.get(l["cuil"])) for l in cur.fetchall()]
        for k in ("afiliados", "remuneracion", "importe", "en_archivo", "fuera_nomina", "activos"):
            plan[k] = {"afiliados": pres["afiliados"], "remuneracion": pres["remuneracion"],
                       "importe": pres["importe"], "en_archivo": pres["activos_en_archivo"],
                       "activos": pres["afiliados_activos"],
                       "fuera_nomina": sum(1 for l in plan["lineas"] if not l["activo"])}[k]
    plan["vencimiento"] = FI.vencimiento_931(cur, plan["cuit"], plan["periodo"])
    return plan


TOLERANCIA_DDJJ = Decimal("1.00")     # el redondeo del recibo mueve centavos


def control_ddjj(plan: dict) -> dict:
    """Compara la remuneración de cada renglón con la Remuneración imponible 5 de
    la DDJJ de OSEDA de ese CUIL y ese CUIT en el período. Agrega a cada línea
    `ddjj` (None si no está en la DDJJ de este CUIT) y `dif` (archivo − DDJJ).
    Devuelve {"error"} si Railway no responde, o los contadores."""
    try:
        filas = contable_oseda.ddjj_del_periodo(plan["periodo"], [l["cuil"] for l in plan["lineas"]])
    except contable_oseda.ContableNoDisponible as e:
        return {"error": str(e)}
    rem: dict[str, Decimal] = {}
    for f in filas:
        if FL._digitos(f["cuit"]) == plan["cuit"]:
            rem[f["cuil"]] = rem.get(f["cuil"], Decimal("0")) + Decimal(str(f["rem5"] or 0))
    con, dif, suma = 0, 0, Decimal("0")
    for l in plan["lineas"]:
        l["ddjj"] = rem.get(l["cuil"])
        l["dif"] = None
        if l["ddjj"] is None:
            continue
        con += 1
        l["dif"] = Decimal(str(l["remuneracion"] or 0)) - l["ddjj"]
        if abs(l["dif"]) >= TOLERANCIA_DDJJ:
            dif += 1
            suma += l["dif"]
    return {"error": None, "con_ddjj": con, "con_diferencia": dif, "diferencia": suma,
            "cuota_diferencia": _cuota(suma, plan["alicuota"]) if suma else Decimal("0")}


def _nota(pres: dict, plan: dict, aeda: dict | None) -> str:
    quien = "la empresa" if pres["origen"] == "empresa" else "el sindicato"
    if pres.get("carga") == "manual":
        partes = [f"Liquidada con las remuneraciones que cargó a mano {quien} el {datetime.date.today():%d/%m/%Y}, "
                  f"sin el Libro de Sueldos Digital (presentación {pres['id']})."]
    else:
        partes = [f"Liquidada con el Libro de Sueldos Digital que presentó {quien} el "
                  f"{datetime.date.today():%d/%m/%Y} (liquidación N.º {pres['nro_liquidacion'] or '—'}, "
                  f"presentación {pres['id']})."]
    if plan["activos"] and not plan["en_archivo"]:
        partes.append("Ningún afiliado activo del empleador "
                      + ("tiene remuneración cargada." if pres.get("carga") == "manual" else "figura en el archivo."))
    if plan.get("altas"):
        partes.append(f"{plan['altas']} alta(s) informada(s) por la empresa, pendiente(s) de aprobación.")
    if plan["fuera_nomina"] - plan.get("altas", 0) > 0:
        partes.append(f"{plan['fuera_nomina'] - plan.get('altas', 0)} afiliado(s) en el archivo sin relación laboral "
                      "con el empleador en el padrón.")
    if aeda:
        partes.append(aeda["texto"])
    return " ".join(partes)[:500]


def presentar(cur, id_pres: int, id_usuario: int | None, cuit: str | None = None) -> dict:
    """La planilla pasa a ser la liquidación de ese CUIT y período. Devuelve
    {"id_liquidacion", "importe", "afiliados", "reemplazadas"}."""
    pres = leer_presentacion(cur, id_pres, cuit, bloquear=True)
    if not pres:
        raise ErrorPresentacion("No existe esa presentación.")
    if pres["estado"] != "borrador":
        raise ErrorPresentacion("Esa presentación ya se presentó o se descartó.")
    plan = plan_actual(cur, pres)
    periodo, hoy = plan["periodo"], datetime.date.today()
    vto = FI.vencimiento_931(cur, pres["cuit"], periodo)

    cur.execute("""SELECT id, cuit, origen, estado, importe, afiliados, observaciones,
                          aeda_importe, aeda_afiliados, id_aeda
                     FROM fisca_liquidacion WHERE cuit = %s AND periodo = %s FOR UPDATE""", (pres["cuit"], periodo))
    ya = cur.fetchone()
    aeda = FL._aeda(ya, hoy) if ya else None
    nota = _nota(pres, plan, aeda)
    valores = (hoy, vto, plan["alicuota"], plan["afiliados"], plan["remuneracion"], plan["importe"], nota,
               plan["activos"], plan["en_archivo"], aeda and aeda["importe"], aeda and aeda["afiliados"],
               aeda and aeda["id"], id_usuario)
    if ya:
        cur.execute("""UPDATE fisca_liquidacion
                          SET fecha = %s, vencimiento = %s, alicuota = %s, afiliados = %s, remuneracion = %s,
                              importe = %s, origen = 'lsd', estado = 'vigente', observaciones = %s,
                              afiliados_activos = %s, activos_con_ddjj = %s,
                              aeda_importe = %s, aeda_afiliados = %s, id_aeda = %s, id_usuario = %s
                        WHERE id = %s""", valores + (ya["id"],))
        id_liq = ya["id"]
        cur.execute("DELETE FROM fisca_liquidacion_detalle WHERE id_liquidacion = %s", (id_liq,))
    else:
        cur.execute("""INSERT INTO fisca_liquidacion
                         (fecha, vencimiento, alicuota, afiliados, remuneracion, importe, observaciones,
                          afiliados_activos, activos_con_ddjj, aeda_importe, aeda_afiliados, id_aeda, id_usuario,
                          cuit, periodo, origen, estado)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'lsd', 'vigente')""",
                    valores + (pres["cuit"], periodo))
        id_liq = cur.lastrowid
    if plan["lineas"]:
        cur.executemany("""INSERT INTO fisca_liquidacion_detalle
                             (id_liquidacion, cuil, id_afiliado, apellido_nombres, remuneracion, cuota, fuente, activo)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                        [(id_liq, l["cuil"], l["id_afiliado"], (l["nombre"] or None) and l["nombre"][:100],
                          l["remuneracion"], l["cuota"], l["fuente"], 1 if l["activo"] else 0)
                         for l in plan["lineas"]])
    cur.execute("""UPDATE fisca_lsd_presentacion SET estado = 'reemplazada'
                    WHERE cuit = %s AND periodo = %s AND estado = 'presentada' AND id <> %s""",
                (pres["cuit"], periodo, id_pres))
    reemplazadas = cur.rowcount
    cur.execute("""UPDATE fisca_lsd_presentacion
                      SET estado = 'presentada', presentado = NOW(), id_liquidacion = %s,
                          afiliados_activos = %s, activos_en_archivo = %s, afiliados = %s, no_afiliados = %s,
                          remuneracion = %s, importe = %s, retenido = %s,
                          id_usuario = COALESCE(id_usuario, %s)
                    WHERE id = %s""",
                (id_liq, plan["activos"], plan["en_archivo"], plan["afiliados"], plan["no_afiliados"],
                 plan["remuneracion"], plan["importe"], plan["retenido"], id_usuario, id_pres))
    return {"id_liquidacion": id_liq, "importe": plan["importe"], "afiliados": plan["afiliados"],
            "periodo": periodo, "reemplazadas": reemplazadas, "vencimiento": vto}


def descartar(cur, id_pres: int, cuit: str | None = None) -> bool:
    cur.execute(f"""DELETE FROM fisca_lsd_presentacion WHERE id = %s AND estado = 'borrador'
                    {'AND cuit = %s' if cuit else ''}""", (id_pres, cuit) if cuit else (id_pres,))
    return cur.rowcount > 0


def anular(cur, id_pres: int, id_usuario: int | None, motivo: str) -> dict:
    """Anula una presentación vigente: la liquidación de ese CUIT y período vuelve
    a la DDJJ de OSEDA (la lee de Railway; sin Railway no se anula nada)."""
    pres = leer_presentacion(cur, id_pres, bloquear=True)
    if not pres or pres["estado"] != "presentada":
        raise ErrorPresentacion("Solo se anula una presentación vigente.")
    texto = f"Anulada el {datetime.date.today():%d/%m/%Y}: {motivo}"[:500]
    cur.execute("UPDATE fisca_lsd_presentacion SET estado = 'anulada', observaciones = %s WHERE id = %s",
                (texto, id_pres))
    if not pres["id_liquidacion"]:
        return {"ddjj": None}
    cur.execute("UPDATE fisca_liquidacion SET origen = 'ddjj' WHERE id = %s AND origen = 'lsd'", (pres["id_liquidacion"],))
    try:
        r = FL.generar(cur, pres["periodo"], id_usuario, FL.calcular(cur, pres["periodo"]), solo_cuit=pres["cuit"])
    except FL.ErrorLiquidacion as e:
        raise ErrorPresentacion(str(e)) from e
    return {"ddjj": r}


def presentaciones(cur, cuit: str | None = None, periodo: str | None = None, estado: str | None = None,
                   limite: int = 1000) -> list[dict]:
    cond, args = ["1 = 1"], []
    if cuit:
        cond.append("p.cuit = %s"); args.append(cuit)
    if periodo:
        cond.append("p.periodo = %s"); args.append(periodo)
    if estado:
        cond.append("p.estado = %s"); args.append(estado)
    cur.execute(f"""SELECT p.id, p.cuit, p.periodo, p.envio, p.tipo_liq, p.nro_liquidacion, p.archivo_nombre,
                           p.trabajadores, p.no_afiliados, p.afiliados_activos, p.activos_en_archivo, p.afiliados,
                           p.remuneracion, p.importe, p.retenido, p.estado, p.origen, p.id_liquidacion,
                           p.presentado, p.creado, p.observaciones, e.razon_social, u.nombre AS usuario
                      FROM fisca_lsd_presentacion p
                      LEFT JOIN p_empresas e ON e.CUIT = CAST(p.cuit AS UNSIGNED)
                      LEFT JOIN s_usuarios u ON u.id = p.id_usuario
                     WHERE {' AND '.join(cond)}
                     ORDER BY p.periodo DESC, COALESCE(p.presentado, p.creado) DESC
                     LIMIT {int(limite)}""", args)
    return cur.fetchall()


def _aaaamm(f) -> str:
    return f.strftime("%Y%m") if f else ""


def planilla_xlsx(pres: dict, plan: dict, inst: dict | None = None) -> bytes:
    """La planilla en Excel, con el formato de la de aportes del art. 38 (la que
    lee Importar Cuotas): CUIT, período y empresa en la fila 3, renglones desde la 5."""
    nombre = pres.get("razon_social") or ""
    sigla = (inst or {}).get("sigla") or (inst or {}).get("nombre") or "Sindicato"
    encabezado = [
        f"{sigla} — Planilla de cuota sindical (Ley 23.551, art. 38) · Libro de Sueldos Digital",
        f"Liquidación N.º {pres.get('nro_liquidacion') or '—'} · Alícuota {str(plan['alicuota']).replace('.', ',')} % · "
        f"Vence el {plan['vencimiento']:%d/%m/%Y} · Total a pagar $ {_pesos(plan['importe'])}",
        f"Cuit: {pres['cuit']}   Período: {plan['periodo']}   Empresa: {nombre}   ",
    ]
    columnas = [{"titulo": "CUIL", "tipo": "t"}, {"titulo": "Beneficiario"}, {"titulo": "Período", "tipo": "t"},
                {"titulo": "Remuneración", "tipo": "n"}, {"titulo": "Cuota", "tipo": "n"},
                {"titulo": "Alta", "tipo": "t"}, {"titulo": "Baja", "tipo": "t"},
                {"titulo": "Retenido en el recibo", "tipo": "n"}, {"titulo": "Observación"}]
    filas = []
    for l in plan["lineas"]:
        obs = []
        if l["fuente"] == "sin_lsd":
            obs.append("Activo de la empresa que no está en el archivo")
        elif not l["activo"]:
            obs.append("Sin relación laboral con la empresa en el padrón")
        filas.append([l["cuil"], l["nombre"] or "", plan["periodo"], _pesos(l["remuneracion"]), _pesos(l["cuota"]),
                      _aaaamm(l.get("fecha_alta")), _aaaamm(l.get("fecha_baja")),
                      _pesos(l["retenido"]) if l.get("retenido") is not None else "", "; ".join(obs)])
    filas.append(["", "Total", "", _pesos(plan["remuneracion"]), _pesos(plan["importe"]), "", "",
                  _pesos(plan["retenido"]) if plan.get("retenido") is not None else "", ""])
    return xlsx(f"Cuota {plan['periodo']}", columnas, filas, encabezado=encabezado)


def _nombre_planilla(pres: dict) -> str:
    return f"Cuota sindical {pres['periodo'][:4]}-{pres['periodo'][4:]} {pres['cuit']}.xlsx"


def _institucion() -> dict:
    """Sigla y nombre del sindicato para el portal (no hay sesión, así que el
    context processor de app.py no los pone)."""
    from institucion import encabezado
    try:
        return encabezado()
    except Exception:            # noqa: BLE001 — el portal se muestra igual, sin el nombre
        import logging
        logging.getLogger(__name__).exception("No se pudieron leer los datos del sindicato")
        return {}


def datos_empleador(cur, empresa: dict) -> dict:
    """La solapa «Cuota sindical» de Empleadores: enlace vigente, presentaciones
    y los mails a los que se manda el enlace."""
    if falta_esquema(cur):
        return {"falta_esquema": True, "sql": SQL_ESQUEMA}
    cuit = FL._digitos(empresa.get("CUIT"))
    sin_novedades = NOV.falta_esquema(cur)
    return {"falta_esquema": False, "enlace": enlace_vigente(cur, cuit),
            "presentaciones": presentaciones(cur, cuit=cuit, limite=100),
            "emails": emails_empresa(cur, empresa), "estados": ESTADOS,
            "novedades": [] if sin_novedades else NOV.novedades(cur, cuit=cuit, limite=100),
            "estados_nov": NOV.ESTADOS, "tipos_nov": NOV.TIPOS}


# ─────────────────────────────────────────────────────────────────────────────
# Portal de la empresa (sin sesión: el enlace es la credencial)
# ─────────────────────────────────────────────────────────────────────────────

def _enlace_o_404(cur, token: str) -> dict:
    enlace = enlace_por_token(cur, token)
    if not enlace:
        abort(404)
    return enlace


@portal_bp.before_request
def _token_con_formato():
    """Un token que ni siquiera tiene el formato no va a la base."""
    if not RE_TOKEN.match((request.view_args or {}).get("token") or ""):
        abort(404)


@portal_bp.app_template_global("pago_cuota_portal")
def pago_cuota_portal() -> dict:
    """La cuenta donde se paga la cuota y el contacto (institucion.pago_cuota),
    para el bloque «Pago de la cuota y consultas» y el pie del portal. Si no
    se pueden leer, el portal se muestra igual, sin ellos."""
    import institucion
    try:
        return institucion.pago_cuota()
    except Exception:            # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("No se pudieron leer los datos de pago de la cuota")
        return {}


@portal_bp.errorhandler(404)
def _portal_404(_e):
    return render_template("portal/invalido.html", inst=_institucion()), 404


def periodo_anterior(hoy: datetime.date | None = None) -> str:
    """El mes anterior, «AAAAMM»: el que normalmente se presenta."""
    hoy = hoy or datetime.date.today()
    m = hoy.year * 12 + hoy.month - 2
    return f"{m // 12:04d}{m % 12 + 1:02d}"


def _pagina_empresa(token: str, errores: list[str] | None = None, estado: int = 200, form=None,
                    error_en: str | None = None):
    """La página de la empresa. `error_en`: el bloque al que va el error (alta,
    baja, archivo) para mostrarlo ahí y no arriba de todo."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            enlace = _enlace_o_404(cur, token)
            cur.execute("UPDATE fisca_enlace_empresa SET ultimo_uso = NOW(), usos = usos + 1 WHERE id = %s",
                        (enlace["id"],))
            lista = presentaciones(cur, cuit=enlace["cuit"], limite=60)
            sin_novedades = NOV.falta_esquema(cur)
            nomina = NOV.nomina(cur, enlace["cuit"])
            novedades = [] if sin_novedades else NOV.novedades(cur, cuit=enlace["cuit"], limite=60)
    return render_template("portal/empresa.html", enlace=enlace, token=token, lista=lista, estados=ESTADOS,
                           confidencialidad=CONFIDENCIALIDAD, nomina=nomina, novedades=novedades,
                           sin_novedades=sin_novedades, estados_nov=NOV.ESTADOS, tipos_nov=NOV.TIPOS,
                           periodo_sugerido=periodo_anterior(), hoy=datetime.date.today(),
                           form=form or {}, error_en=error_en,
                           ficha_mb=NOV.DOC.MAX_MB, inst=_institucion(), max_mb=MAX_BYTES // (1024 * 1024),
                           errores=errores if not error_en else None,
                           errores_bloque=errores if error_en else None), estado


@portal_bp.route("/<token>")
def empresa(token):
    return _pagina_empresa(token)


@portal_bp.route("/<token>/subir", methods=["POST"])
def subir(token):
    archivo = request.files.get("archivo")
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            enlace = _enlace_o_404(cur, token)
            contenido = archivo.read(MAX_BYTES + 1) if archivo else b""
            id_pres = guardar_borrador(cur, contenido, archivo.filename if archivo else "", "empresa",
                                       enlace["cuit"], enlace["id"], None, request.remote_addr)
        conn.commit()
    except ErrorPresentacion as e:
        conn.rollback()
        return _pagina_empresa(token, e.lista(), 422, error_en="archivo")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return redirect(url_for("portal.presentacion", token=token, id_pres=id_pres))


# ── Nómina: altas y bajas (fisca_novedades.py) ──────────────────────────────

@portal_bp.route("/<token>/alta", methods=["POST"])
def alta(token):
    """La empresa informa el alta de un CUIL, con la ficha de afiliación si la adjunta."""
    ficha = None
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            enlace = _enlace_o_404(cur, token)
            if NOV.falta_esquema(cur):
                raise NOV.ErrorNovedad("Por ahora no se pueden informar altas por acá: avisen al sindicato.")
            ficha = NOV.guardar_ficha(request.files.get("ficha"))
            NOV.informar_alta(cur, enlace["cuit"], request.form.get("cuil"), request.form.get("apellido_nombres"),
                              request.form.get("fecha"), request.form.get("observaciones"), ficha, "empresa",
                              enlace["id"], request.remote_addr)
        conn.commit()
    except NOV.ErrorNovedad as e:
        conn.rollback()
        if ficha:
            almacenamiento.borrar(ficha["ruta"])
        return _pagina_empresa(token, [str(e)], 422, form=request.form, error_en="alta")
    except Exception:
        conn.rollback()
        if ficha:
            almacenamiento.borrar(ficha["ruta"])
        raise
    finally:
        conn.close()
    flash("Alta informada. El sindicato la revisa; mientras tanto la cuota del mes ya la incluye desde su fecha.")
    return redirect(url_for("portal.empresa", token=token) + "#novedades")


@portal_bp.route("/<token>/baja", methods=["POST"])
def baja(token):
    """La empresa informa la baja de un CUIL que el padrón tiene activo."""
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            enlace = _enlace_o_404(cur, token)
            if NOV.falta_esquema(cur):
                raise NOV.ErrorNovedad("Por ahora no se pueden informar bajas por acá: avisen al sindicato.")
            NOV.informar_baja(cur, enlace["cuit"], request.form.get("cuil"), request.form.get("fecha"),
                              request.form.get("observaciones"), "empresa", enlace["id"], request.remote_addr)
        conn.commit()
    except NOV.ErrorNovedad as e:
        conn.rollback()
        return _pagina_empresa(token, [str(e)], 422, form=request.form, error_en="baja")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    flash("Baja informada. El sindicato la revisa: hasta que la apruebe, la cuota del mes lo sigue incluyendo.")
    return redirect(url_for("portal.empresa", token=token) + "#novedades")


@portal_bp.route("/<token>/novedad/<int:id_nov>/retirar", methods=["POST"])
def retirar_novedad(token, id_nov):
    with get_connection() as conn:
        with conn.cursor() as cur:
            enlace = _enlace_o_404(cur, token)
            ok = NOV.retirar(cur, id_nov, enlace["cuit"])
    flash("Novedad retirada." if ok else "!Esa novedad ya fue revisada por el sindicato: no se puede retirar.")
    return redirect(url_for("portal.empresa", token=token) + "#novedades")


# ── Cuota cargada a mano, sin el archivo ────────────────────────────────────

def _remuneraciones_previas(cur, cuit: str, periodo: str) -> dict:
    """Lo último que se cargó a mano para ese mes (el borrador o lo presentado),
    para no volver a escribirlo."""
    cur.execute("""SELECT id FROM fisca_lsd_presentacion
                    WHERE cuit = %s AND periodo = %s AND carga = 'manual' AND estado IN ('borrador', 'presentada')
                    ORDER BY estado = 'borrador' DESC, id DESC LIMIT 1""", (cuit, periodo))
    f = cur.fetchone()
    return remuneraciones_de(cur, f["id"]) if f else {}


@portal_bp.route("/<token>/manual", methods=["GET", "POST"])
def manual(token):
    """La planilla para cargar a mano las remuneraciones del mes: la nómina del
    período y las altas informadas. Guardarla la deja sin presentar, como un archivo."""
    periodo = FL.periodo_valido(request.values.get("periodo"))
    errores, rems = [], {}
    with get_connection() as conn:
        with conn.cursor() as cur:
            enlace = _enlace_o_404(cur, token)
            if falta_esquema_manual(cur):
                flash("!Por ahora la cuota no se puede cargar a mano: avisen al sindicato o suban el archivo.")
                return redirect(url_for("portal.empresa", token=token))
            if not periodo:
                flash("!Elijan el mes de la cuota.")
                return redirect(url_for("portal.empresa", token=token))
            if request.method == "POST":
                rems, errores = leer_remuneraciones(request.form)
                if not errores:
                    try:
                        conn.begin()
                        id_pres = guardar_borrador_manual(cur, enlace["cuit"], periodo, rems, "empresa",
                                                          enlace["id"], None, request.remote_addr)
                        conn.commit()
                        return redirect(url_for("portal.presentacion", token=token, id_pres=id_pres))
                    except ErrorPresentacion as e:
                        conn.rollback()
                        errores = e.lista()
            else:
                rems = _remuneraciones_previas(cur, enlace["cuit"], periodo)
            plan = calcular_manual(cur, enlace["cuit"], periodo, rems)
    textos = {k[4:]: v for k, v in request.form.items() if k.startswith("rem_")} if request.method == "POST" else {}
    return render_template("portal/manual.html", enlace=enlace, token=token, plan=plan, periodo=periodo,
                           textos=textos, errores=errores, fuentes=FL.FUENTES, fuente_tipo=FL.FUENTE_TIPO,
                           confidencialidad=CONFIDENCIALIDAD, inst=_institucion()), (422 if errores else 200)


def falta_esquema_manual(cur) -> bool:
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.columns WHERE table_schema = DATABASE()
                      AND table_name = 'fisca_lsd_presentacion' AND column_name = 'carga'""")
    return not (cur.fetchone() or {}).get("n")


@portal_bp.route("/<token>/instructivo.pdf")
def instructivo(token):
    """El instructivo en PDF, con los datos de pago y de contacto de hoy y el
    nombre y el CUIT de la empresa. Se abre en el navegador (no se descarga)."""
    import instructivo_empresa
    with get_connection() as conn:
        with conn.cursor() as cur:
            enlace = _enlace_o_404(cur, token)
    buf, nombre = instructivo_empresa.pdf({"razon_social": enlace.get("razon_social"), "cuit": enlace["cuit"]})
    return _pdf_en_linea(buf, nombre)


def _pdf_en_linea(buf: io.BytesIO, nombre: str):
    buf.seek(0)
    respuesta = send_file(buf, mimetype="application/pdf", as_attachment=False, download_name=nombre)
    respuesta.headers["Cache-Control"] = "no-store"
    return respuesta


@portal_bp.route("/<token>/presentacion/<int:id_pres>")
def presentacion(token, id_pres):
    with get_connection() as conn:
        with conn.cursor() as cur:
            enlace = _enlace_o_404(cur, token)
            pres = leer_presentacion(cur, id_pres, enlace["cuit"])
            if not pres:
                abort(404)
            plan = planilla_de(cur, pres)
    return render_template("portal/presentacion.html", enlace=enlace, token=token, pres=pres, plan=plan,
                           confidencialidad=CONFIDENCIALIDAD,
                           estados=ESTADOS, fuentes=FL.FUENTES, fuente_tipo=FL.FUENTE_TIPO, inst=_institucion())


@portal_bp.route("/<token>/presentacion/<int:id_pres>/confirmar", methods=["POST"])
def confirmar(token, id_pres):
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            enlace = _enlace_o_404(cur, token)
            r = presentar(cur, id_pres, None, enlace["cuit"])
        conn.commit()
        flash(f"Presentada la cuota sindical {r['periodo'][:4]}-{r['periodo'][4:]}: {r['afiliados']} afiliado(s), "
              f"$ {_pesos(r['importe'])} a pagar hasta el {r['vencimiento']:%d/%m/%Y}.")
    except ErrorPresentacion as e:
        conn.rollback()
        flash("!" + str(e))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return redirect(url_for("portal.presentacion", token=token, id_pres=id_pres))


@portal_bp.route("/<token>/presentacion/<int:id_pres>/descartar", methods=["POST"])
def descartar_portal(token, id_pres):
    with get_connection() as conn:
        with conn.cursor() as cur:
            enlace = _enlace_o_404(cur, token)
            if descartar(cur, id_pres, enlace["cuit"]):
                flash("Se descartó el archivo: no se presentó nada.")
    return redirect(url_for("portal.empresa", token=token))


@portal_bp.route("/<token>/presentacion/<int:id_pres>/planilla.xlsx")
def planilla_portal(token, id_pres):
    with get_connection() as conn:
        with conn.cursor() as cur:
            enlace = _enlace_o_404(cur, token)
            pres = leer_presentacion(cur, id_pres, enlace["cuit"])
            if not pres:
                abort(404)
            plan = planilla_de(cur, pres)
    return send_file(io.BytesIO(planilla_xlsx(pres, plan, _institucion())), as_attachment=True,
                     download_name=_nombre_planilla(pres),
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ─────────────────────────────────────────────────────────────────────────────
# Adentro: Presentaciones LSD y el enlace en Empleadores
# ─────────────────────────────────────────────────────────────────────────────

def _guardia():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede(url_for("fisca_lsd.lista")):
        flash("!No tenés permiso para las presentaciones del Libro de Sueldos Digital.")
        return redirect(url_for("menu"))
    return None


def _id_usuario():
    return (usuario_actual() or {}).get("id")


@fisca_lsd_bp.route("/lsd")
def lista(errores: list[str] | None = None, estado_http: int = 200):
    salida = _guardia()
    if salida:
        return salida
    periodo = FL.periodo_valido(request.args.get("periodo"))
    estado = request.args.get("estado") if request.args.get("estado") in ESTADOS else None
    # Novedades de las empresas (altas y bajas): por defecto las pendientes.
    nov_estado = request.args.get("nov", "pendiente")
    nov_estado = nov_estado if nov_estado in NOV.ESTADOS or nov_estado == "todas" else "pendiente"
    novedades, sin_novedades = [], True
    with get_connection() as conn:
        with conn.cursor() as cur:
            if falta_esquema(cur):
                flash(f"!Falta correr {SQL_ESQUEMA}: hasta entonces no se pueden recibir presentaciones.")
                filas = []
            else:
                filas = presentaciones(cur, periodo=periodo, estado=estado)
                sin_novedades = NOV.falta_esquema(cur)
                if not sin_novedades:
                    novedades = NOV.novedades(cur, estado=None if nov_estado == "todas" else nov_estado)
    return render_template("fisca/lsd.html", filas=filas, periodo=periodo, estado=estado, estados=ESTADOS,
                           origenes=ORIGENES, max_mb=MAX_BYTES // (1024 * 1024), errores=errores,
                           novedades=novedades, sin_novedades=sin_novedades, nov_estado=nov_estado,
                           estados_nov=NOV.ESTADOS, tipos_nov=NOV.TIPOS, sql_novedades=NOV.SQL_ESQUEMA,
                           puede_empleador=puede(url_for("empleadores.abm_empleadores"))), estado_http


@fisca_lsd_bp.route("/lsd/instructivo.pdf")
def instructivo_interno():
    """El mismo instructivo que ve la empresa, para mirarlo o adjuntarlo a mano.
    Con ?id_empresa= sale a nombre de ese empleador."""
    salida = _guardia()
    if salida:
        return salida
    import instructivo_empresa
    empresa = None
    if (request.args.get("id_empresa") or "").isdigit():
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT razon_social, CUIT FROM p_empresas WHERE id = %s", (int(request.args["id_empresa"]),))
                f = cur.fetchone()
        if f:
            empresa = {"razon_social": f["razon_social"], "cuit": FL._digitos(f["CUIT"])}
    buf, nombre = instructivo_empresa.pdf(empresa)
    return _pdf_en_linea(buf, nombre)


@fisca_lsd_bp.route("/lsd/subir", methods=["POST"])
def subir_interno():
    salida = _guardia()
    if salida:
        return salida
    archivo = request.files.get("archivo")
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            contenido = archivo.read(MAX_BYTES + 1) if archivo else b""
            id_pres = guardar_borrador(cur, contenido, archivo.filename if archivo else "", "interno", None,
                                       None, _id_usuario(), request.remote_addr)
        conn.commit()
    except ErrorPresentacion as e:
        conn.rollback()
        return lista(e.lista(), 422)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return redirect(url_for("fisca_lsd.ficha", id_pres=id_pres))


@fisca_lsd_bp.route("/lsd/<int:id_pres>")
def ficha(id_pres):
    salida = _guardia()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            pres = leer_presentacion(cur, id_pres)
            if not pres:
                flash("!No existe esa presentación.")
                return redirect(url_for("fisca_lsd.lista"))
            plan = planilla_de(cur, pres)
    control = control_ddjj(plan)
    return render_template("fisca/lsd_ficha.html", pres=pres, plan=plan, control=control, estados=ESTADOS,
                           origenes=ORIGENES,
                           fuentes=FL.FUENTES, fuente_tipo=FL.FUENTE_TIPO,
                           puede_empleador=puede(url_for("empleadores.abm_empleadores")),
                           puede_liquidacion=puede(url_for("fisca_liq.liquidacion")))


@fisca_lsd_bp.route("/lsd/<int:id_pres>/confirmar", methods=["POST"])
def confirmar_interno(id_pres):
    salida = _guardia()
    if salida:
        return salida
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            r = presentar(cur, id_pres, _id_usuario())
        conn.commit()
        flash(f"Presentada: la cuota sindical {r['periodo'][:4]}-{r['periodo'][4:]} quedó liquidada con el archivo, "
              f"{r['afiliados']} afiliado(s), $ {_pesos(r['importe'])}."
              + (f" Reemplaza a {r['reemplazadas']} presentación(es) anterior(es)." if r["reemplazadas"] else ""))
    except ErrorPresentacion as e:
        conn.rollback()
        flash("!" + str(e))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return redirect(url_for("fisca_lsd.ficha", id_pres=id_pres))


@fisca_lsd_bp.route("/lsd/<int:id_pres>/descartar", methods=["POST"])
def descartar_interno(id_pres):
    salida = _guardia()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            flash("Se descartó el archivo." if descartar(cur, id_pres) else "!Solo se descarta lo que no se presentó.")
    return redirect(url_for("fisca_lsd.lista"))


@fisca_lsd_bp.route("/lsd/<int:id_pres>/anular", methods=["POST"])
def anular_interno(id_pres):
    salida = _guardia()
    if salida:
        return salida
    motivo = (request.form.get("motivo") or "").strip()
    if not motivo:
        flash("!Para anular una presentación hay que decir por qué.")
        return redirect(url_for("fisca_lsd.ficha", id_pres=id_pres))
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            r = anular(cur, id_pres, _id_usuario(), motivo)
        conn.commit()
        d = r["ddjj"]
        flash("Presentación anulada." + (" La liquidación del período volvió a la DDJJ de OSEDA." if d and
                                         (d["reliquidadas"] or d["iguales"] or d["nuevas"]) else
                                         " En la DDJJ de OSEDA no hay base: la liquidación quedó anulada." if d else ""))
    except ErrorPresentacion as e:
        conn.rollback()
        flash("!" + str(e))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return redirect(url_for("fisca_lsd.ficha", id_pres=id_pres))


@fisca_lsd_bp.route("/lsd/<int:id_pres>/planilla.xlsx")
def planilla_interno(id_pres):
    salida = _guardia()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            pres = leer_presentacion(cur, id_pres)
            if not pres:
                abort(404)
            plan = planilla_de(cur, pres)
    return send_file(io.BytesIO(planilla_xlsx(pres, plan, _institucion())), as_attachment=True,
                     download_name=_nombre_planilla(pres),
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@fisca_lsd_bp.route("/lsd/<int:id_pres>/archivo")
def archivo_interno(id_pres):
    salida = _guardia()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            pres = leer_presentacion(cur, id_pres)
    if not pres or not pres["archivo"]:
        abort(404)
    return send_file(io.BytesIO(pres["archivo"]), as_attachment=True, download_name=pres["archivo_nombre"],
                     mimetype="text/plain")


# ── Novedades de las empresas: aprobar o rechazar (fisca_novedades.py) ──────

def _volver_novedades():
    v = request.form.get("volver") or ""
    return v if v.startswith("/") and not v.startswith("//") else url_for("fisca_lsd.lista") + "#novedades"


@fisca_lsd_bp.route("/lsd/novedad/<int:id_nov>/aprobar", methods=["POST"])
def aprobar_novedad(id_nov):
    salida = _guardia()
    if salida:
        return salida
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            hecho = NOV.aprobar(cur, id_nov, _id_usuario())
        conn.commit()
        flash("Novedad aprobada: " + hecho + ".")
    except NOV.ErrorNovedad as e:
        conn.rollback()
        flash("!" + str(e))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return redirect(_volver_novedades())


@fisca_lsd_bp.route("/lsd/novedad/<int:id_nov>/rechazar", methods=["POST"])
def rechazar_novedad(id_nov):
    salida = _guardia()
    if salida:
        return salida
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                NOV.rechazar(cur, id_nov, request.form.get("motivo"), _id_usuario())
        flash("Novedad rechazada. La empresa ve el motivo en su enlace.")
    except NOV.ErrorNovedad as e:
        flash("!" + str(e))
    return redirect(_volver_novedades())


@fisca_lsd_bp.route("/lsd/novedad/<int:id_nov>/ficha")
def ficha_novedad(id_nov):
    salida = _guardia()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            nov = NOV.una(cur, id_nov)
    ruta = NOV.ruta_ficha(nov)
    if not ruta:
        abort(404)
    return send_file(ruta, download_name=nov["ficha_nombre"] or ruta.name,
                     mimetype=NOV.DOC.MIME.get(ruta.suffix.lower(), "application/octet-stream"))


@fisca_lsd_bp.route("/lsd/enlace/<int:id_empresa>", methods=["POST"])
def enlace(id_empresa):
    """Genera (o vuelve a generar) o revoca el enlace de una empresa. El enlace
    nuevo se muestra una sola vez, en la solapa Cuota sindical del empleador."""
    salida = _guardia()
    if salida:
        return salida
    accion = request.form.get("accion")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, CUIT, razon_social, email FROM p_empresas WHERE id = %s", (id_empresa,))
            emp = cur.fetchone()
            if not emp or len(FL._digitos(emp["CUIT"])) != 11:
                flash("!El empleador no existe o no tiene un CUIT de 11 dígitos.")
                return redirect(url_for("empleadores.abm_empleadores"))
            if accion == "revocar":
                n = revocar_enlaces(cur, FL._digitos(emp["CUIT"]), _id_usuario())
                flash("Enlace revocado: la empresa ya no puede entrar con él." if n else "!No tenía enlace vigente.")
            else:
                token = nuevo_enlace(cur, emp, _id_usuario())
                session["sind_enlace_nuevo"] = {"id_empresa": emp["id"], "url": url_enlace(token)}
                flash("Enlace generado. Copialo o mandalo por mail ahora: después no se vuelve a mostrar.")
    return redirect(url_for("empleadores.abm_empleadores", edit=id_empresa, solapa="cuota"))
