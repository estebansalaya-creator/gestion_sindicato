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

import contable_oseda
import fisca_liquidacion as FL
import lsd_lector
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


def mailto(empresa: dict, emails: list[str], enlace: str, inst: dict | None = None) -> str:
    """El mail para mandarle el enlace a la empresa, listo para el cliente de correo."""
    sigla = (inst or {}).get("sigla") or "el sindicato"
    asunto = f"Cuota sindical: enlace para presentar el Libro de Sueldos Digital — {empresa.get('razon_social') or ''}"
    cuerpo = (
        f"Estimados:\n\nDesde este enlace pueden presentar todos los meses la liquidación de la cuota sindical "
        f"de {sigla}, subiendo el archivo de liquidación del Libro de Sueldos Digital que su sistema de sueldos "
        f"genera para ARCA (el .txt de «Liquidación de SyJ - DJ F931»).\n\n{enlace}\n\n"
        "El sistema arma la planilla con los afiliados activos y la cuota a pagar, y la pueden descargar en Excel. "
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


def armar_planilla(lectura: dict, padron: dict, alicuota: Decimal) -> dict:
    """
    La planilla de cuota sindical del archivo, sin base de datos (la prueban los
    tests). `padron` es el de FL.leer_padron.

    {"cuit", "periodo", "lineas": [{cuil, id_afiliado, nombre, remuneracion,
    cuota, fuente, activo, retenido, fecha_alta, fecha_baja}], "trabajadores",
    "no_afiliados", "activos", "en_archivo", "fuera_nomina", "afiliados",
    "remuneracion", "importe", "retenido"}
    """
    cab = lectura["cabecera"]
    cuit, periodo = cab["cuit"], f"{cab['periodo']:06d}"
    del_periodo = FL.afiliados_del_periodo(periodo, padron)
    activos = FL.activos_por_empleador(periodo, padron, del_periodo).get(cuit, {})

    lineas, no_afiliados = {}, 0
    for t in lectura["trabajadores"]:
        a = del_periodo.get(t["cuil"])
        if not a:
            no_afiliados += 1
            continue
        base = (t["f931"] or {}).get("base_imponible_5") or Decimal("0")
        ret = [c["importe"] for c in t["conceptos"]
               if (c["codigo"] or "").strip() == lsd_lector.CONCEPTO_CUOTA_SINDICAL and c["dc"] == "D"]
        lineas[t["cuil"]] = {"cuil": t["cuil"], "id_afiliado": a["id_afiliado"], "nombre": a["apellido_nombres"],
                             "remuneracion": base, "fuente": "lsd", "activo": t["cuil"] in activos,
                             "retenido": sum(ret, Decimal("0")) if ret else None,
                             "fecha_alta": a["fecha_alta"], "fecha_baja": a["fecha_baja"]}
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
    retenidos = [l["retenido"] for l in salida if l["retenido"] is not None]
    return {
        "cuit": cuit, "periodo": periodo, "lineas": salida,
        "trabajadores": sum(1 for t in lectura["trabajadores"] if t["f931"]),
        "no_afiliados": no_afiliados,
        "activos": len(activos),
        "en_archivo": sum(1 for l in salida if l["activo"] and l["fuente"] == "lsd"),
        "fuera_nomina": sum(1 for l in salida if not l["activo"]),
        "afiliados": sum(1 for l in salida if l["cuota"] > 0),
        "remuneracion": sum((l["remuneracion"] for l in salida), Decimal("0")),
        "importe": sum((l["cuota"] for l in salida), Decimal("0")),
        "retenido": sum(retenidos, Decimal("0")) if retenidos else None,
    }


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
    return {**armar_planilla(lectura, padron, par["alicuota"]), **par}


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
    lectura = lsd_lector.leer_liquidacion(pres["archivo"])
    plan = calcular(cur, lectura)
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
    plan["vencimiento"] = FL.vencimiento(plan["periodo"], plan["dia_vto"])
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
    partes = [f"Liquidada con el Libro de Sueldos Digital que presentó {quien} el "
              f"{datetime.date.today():%d/%m/%Y} (liquidación N.º {pres['nro_liquidacion'] or '—'}, "
              f"presentación {pres['id']})."]
    if plan["activos"] and not plan["en_archivo"]:
        partes.append("Ningún afiliado activo del empleador figura en el archivo.")
    if plan["fuera_nomina"]:
        partes.append(f"{plan['fuera_nomina']} afiliado(s) en el archivo sin relación laboral con el empleador en el padrón.")
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
    lectura = _leer(pres["archivo"], pres["cuit"])
    plan = calcular(cur, lectura)
    periodo, hoy = plan["periodo"], datetime.date.today()
    vto = FL.vencimiento(periodo, plan["dia_vto"])

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
    return {"falta_esquema": False, "enlace": enlace_vigente(cur, cuit),
            "presentaciones": presentaciones(cur, cuit=cuit, limite=100),
            "emails": emails_empresa(cur, empresa), "estados": ESTADOS}


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


@portal_bp.errorhandler(404)
def _portal_404(_e):
    return render_template("portal/invalido.html", inst=_institucion()), 404


def _pagina_empresa(token: str, errores: list[str] | None = None, estado: int = 200):
    with get_connection() as conn:
        with conn.cursor() as cur:
            enlace = _enlace_o_404(cur, token)
            cur.execute("UPDATE fisca_enlace_empresa SET ultimo_uso = NOW(), usos = usos + 1 WHERE id = %s",
                        (enlace["id"],))
            lista = presentaciones(cur, cuit=enlace["cuit"], limite=60)
    return render_template("portal/empresa.html", enlace=enlace, token=token, lista=lista, estados=ESTADOS,
                           confidencialidad=CONFIDENCIALIDAD,
                           inst=_institucion(), max_mb=MAX_BYTES // (1024 * 1024), errores=errores), estado


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
        return _pagina_empresa(token, e.lista(), 422)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return redirect(url_for("portal.presentacion", token=token, id_pres=id_pres))


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
    with get_connection() as conn:
        with conn.cursor() as cur:
            if falta_esquema(cur):
                flash(f"!Falta correr {SQL_ESQUEMA}: hasta entonces no se pueden recibir presentaciones.")
                filas = []
            else:
                filas = presentaciones(cur, periodo=periodo, estado=estado)
    return render_template("fisca/lsd.html", filas=filas, periodo=periodo, estado=estado, estados=ESTADOS,
                           origenes=ORIGENES, max_mb=MAX_BYTES // (1024 * 1024), errores=errores), estado_http


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
    if not pres:
        abort(404)
    return send_file(io.BytesIO(pres["archivo"]), as_attachment=True, download_name=pres["archivo_nombre"],
                     mimetype="text/plain")


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
