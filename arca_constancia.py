"""
arca_constancia.py — Constancia de inscripción de ARCA («ws_sr_constancia_inscripcion», padrón A5).

La usan las fichas de empleadores y de proveedores (botón «Consultar ARCA»,
pedido del 15/11/2026: «igual que en gestion_adm», que en las dos pantallas
consulta la constancia —`afip.consultar_cuit_constancia`,
`/api/constancia_inscripcion/`—). Con el CUIT trae razón social, domicilio
fiscal, condición frente al IVA, impuestos y actividades.

POR QUÉ LA CONSTANCIA Y NO EL A13
---------------------------------
El padrón A13 (arca_padron.py, el de la ficha del afiliado) trae nombre y
domicilio pero no los impuestos, y sin impuestos no hay condición frente al
IVA, que en un proveedor es lo que más importa. Si el certificado tiene el A13
asociado y la constancia no, se cae al A13: vienen la razón social y el
domicilio, y la pantalla avisa que la condición de IVA no.

ACCESO
------
El de arca_wscdc.py: certificado propio del sindicato (`SIND_ARCA_CERT` /
`SIND_ARCA_KEY` / `SIND_ARCA_CUIT`) con el servicio «ws_sr_constancia_inscripcion»
(Constancia de Inscripción) asociado en el Administrador de Relaciones de Clave
Fiscal. El token es uno por servicio (`ta_ws_sr_constancia_inscripcion.json`).

CONDICIÓN FRENTE AL IVA
-----------------------
Se lee de los impuestos activos, primero por la descripción que manda ARCA y,
si no alcanza, por el idImpuesto: 30 IVA (responsable inscripto), 32 IVA
EXENTO, 33 IVA RESPONSABLE NO INSCRIPTO, 34 IVA NO ALCANZADO, 20 MONOTRIBUTO.
Ojo: gestion_adm toma el 32 como inscripto y el 33 como exento; acá manda la
descripción, que no depende de esa tabla. El código es el de
`arca_responsable_tipo`; «no inscripto» no tiene código en esa tabla y queda
vacío, con el texto.

Sin zeep, leyendo la respuesta por nombre de etiqueta, como arca_padron.py.
"""
from __future__ import annotations

import logging
import re
import unicodedata
import xml.etree.ElementTree as ET

import arca_padron as P
import arca_wscdc as W

SERVICIO = "ws_sr_constancia_inscripcion"
URL = "https://aws.arca.gob.ar/sr-padron/webservices/personaServiceA5"   # la que usa gestion_adm
NS = "http://a5.soap.ws.server.puc.sr/"

ErrorARCA = W.ErrorARCA
NoEncontrado = P.NoEncontrado

log = logging.getLogger(__name__)

#: Códigos de `arca_responsable_tipo`.
IVA_TEXTO = {1: "IVA Responsable Inscripto", 4: "IVA Sujeto Exento", 6: "Responsable Monotributo",
             7: "Sujeto no Categorizado", 13: "Monotributista Social", 15: "IVA No Alcanzado",
             16: "Monotributo Trabajador Independiente Promovido"}

#: Condición de Ingresos Brutos de la ficha del proveedor (proveedores.CONDICIONES_IIBB).
IIBB_LOCAL, IIBB_CONVENIO = 1, 2


def configurado() -> tuple[bool, str]:
    return P.configurado()


# ─────────────────────────────────────────────────────────────────────────────
# Lectura de la respuesta
# ─────────────────────────────────────────────────────────────────────────────

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _hijo(e, nombre):
    return next((x for x in e if _local(x.tag) == nombre), None) if e is not None else None


def _hijos(e, nombre) -> list:
    return [x for x in e if _local(x.tag) == nombre] if e is not None else []


def _txt(e, nombre) -> str:
    x = _hijo(e, nombre)
    return (x.text or "").strip() if x is not None and x.text else ""


def _entero(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _norm(s) -> str:
    s = unicodedata.normalize("NFD", str(s or "").upper())
    return " ".join("".join(c for c in s if unicodedata.category(c) != "Mn").split())


def partir_direccion(direccion: str) -> dict:
    """
    La constancia da el domicilio en una sola cadena («AV CORDOBA 1234 Piso:5
    Dpto:B»); la ficha del empleador lo tiene en calle, número, piso y depto.
    Se sacan primero piso y depto, y el número es el último que queda al final:
    así «25 DE MAYO 300» y «CALLE 12 1450» no se cortan en el primer número.
    Lo que no se reconoce queda entero en la calle.
    """
    s = " ".join(str(direccion or "").split())
    piso = depto = ""
    m = re.search(r"\bPISO\s*[:.]?\s*([0-9A-Z]{1,5})\b", s, re.I)
    if m:
        piso, s = m.group(1), (s[:m.start()] + " " + s[m.end():])
    m = re.search(r"\b(?:DPTO|DEPTO|DTO|DPT|DEPARTAMENTO|OF|OFICINA)\s*[:.]?\s*([0-9A-Z]{1,10})\b", s, re.I)
    if m:
        depto, s = m.group(1), (s[:m.start()] + " " + s[m.end():])
    s = " ".join(s.split())
    m = re.match(r"^(.*\S)\s+(\d{1,6}[A-Z]?|S/N|SN)$", s, re.I)
    if m and not re.fullmatch(r"(?i)(RUTA|KM|CALLE)", m.group(1).split()[-1]):
        return {"calle": m.group(1), "numero": m.group(2).upper(), "piso": piso, "depto": depto}
    return {"calle": s, "numero": "", "piso": piso, "depto": depto}


def _impuestos(contenedor) -> list[dict]:
    return [{"id": _entero(_txt(i, "idImpuesto")), "descripcion": _txt(i, "descripcionImpuesto"),
             "estado": _txt(i, "estadoImpuesto"), "periodo": _txt(i, "periodo")}
            for i in _hijos(contenedor, "impuesto")]


def _actividades(contenedor, nombres=("actividad",)) -> list[dict]:
    salida = []
    for n in nombres:
        for a in _hijos(contenedor, n):
            salida.append({"id": _txt(a, "idActividad"), "descripcion": _txt(a, "descripcionActividad"),
                           "orden": _entero(_txt(a, "orden")), "periodo": _txt(a, "periodo")})
    return salida


def condicion_iva(activos: list[dict], categoria_mono: str = "") -> tuple[int | None, str]:
    """(código de arca_responsable_tipo o None, texto) según los impuestos activos."""
    if not activos:
        return None, ""
    for i in activos:
        d = _norm(i["descripcion"])
        if i["id"] == 20 or "MONOTRIBUTO" in d:
            c = _norm(categoria_mono)
            if "SOCIAL" in d or "SOCIAL" in c:
                return 13, IVA_TEXTO[13]
            if "PROMOVIDO" in d or "PROMOVIDO" in c:
                return 16, IVA_TEXTO[16]
            return 6, IVA_TEXTO[6]
    iva = [(i["id"], _norm(i["descripcion"])) for i in activos
           if i["id"] in (30, 32, 33, 34) or _norm(i["descripcion"]).startswith("IVA")]
    for idi, d in iva:
        if "EXENTO" in d or (idi == 32 and not d):
            return 4, IVA_TEXTO[4]
    for idi, d in iva:
        if "NO ALCANZADO" in d or (idi == 34 and not d):
            return 15, IVA_TEXTO[15]
    for idi, d in iva:
        if "NO INSCRIPTO" in d or (idi == 33 and not d):
            return None, "IVA Responsable no Inscripto"
    if iva:
        return 1, IVA_TEXTO[1]
    return 7, IVA_TEXTO[7]


def leer_constancia(raiz: ET.Element, cuit: str = "") -> dict:
    """Los datos de la respuesta de getPersona_v2. Aparte para poder probarlo sin ARCA."""
    ret = next((e for e in raiz.iter() if _local(e.tag) == "personaReturn"), None)
    if ret is None:
        raise NoEncontrado("la respuesta de ARCA no trae a la persona")
    grales = _hijo(ret, "datosGenerales")
    rg = _hijo(ret, "datosRegimenGeneral")
    mono = _hijo(ret, "datosMonotributo")
    avisos = []

    if grales is None:
        # Sin datos generales ARCA no emite la constancia (clave inactiva,
        # sin impuestos…) y dice por qué en errorConstancia, con el nombre.
        err = _hijo(ret, "errorConstancia")
        if err is None:
            raise NoEncontrado("ARCA no devolvió datos para ese CUIT")
        motivos = [(e.text or "").strip() for e in _hijos(err, "error") if (e.text or "").strip()]
        nombre = " ".join(x for x in (_txt(err, "apellido"), _txt(err, "nombre")) if x)
        if not nombre:
            raise NoEncontrado("; ".join(motivos) or "ARCA no emite la constancia de ese CUIT")
        avisos.append("ARCA no emite la constancia" + (": " + "; ".join(motivos) if motivos else "") + ".")
        return {"cuit": P.digitos(_txt(err, "idPersona")) or cuit, "razon_social": nombre.upper(),
                "tipo_persona": "", "estado_clave": "", "condicion_iva_codigo": None, "condicion_iva": "",
                "inscripto_ganancias": None, "condicion_iibb": None, "impuestos": [], "actividades": [],
                "actividad_principal": "", "categoria_monotributo": "", "domicilio": {},
                "avisos": avisos, "fuente": "constancia"}

    razon = _txt(grales, "razonSocial")
    if not razon:
        razon = " ".join(x for x in (_txt(grales, "apellido"), _txt(grales, "nombre")) if x)

    impuestos = _impuestos(rg) + _impuestos(mono)
    activos = [i for i in impuestos if (i["estado"] or "AC").upper() == "AC"]

    cat = _hijo(mono, "categoriaMonotributo")
    categoria = (_txt(cat, "descripcionCategoria") or _txt(cat, "idCategoria")) if cat is not None else ""
    iva_cod, iva_txt = condicion_iva(activos, categoria)

    actividades = _actividades(rg) + _actividades(mono, ("actividadMonotributista", "actividad"))
    actividades.sort(key=lambda a: (a["orden"] is None, a["orden"] or 0))

    def _es_ganancias(i):
        return i["id"] in (10, 11) or _norm(i["descripcion"]).startswith("GANANCIAS ")

    iibb = None
    for i in activos:
        d = _norm(i["descripcion"])
        if i["id"] == 5900 or "CONVENIO MULTILATERAL" in d:
            iibb = IIBB_CONVENIO
            break
        if "INGRESOS BRUTOS" in d or re.search(r"\bIIBB\b", d):
            iibb = IIBB_LOCAL

    dom = _hijo(grales, "domicilioFiscal")
    domicilio = {}
    if dom is not None:
        direccion = " ".join(_txt(dom, "direccion").split())
        domicilio = dict(partir_direccion(direccion), direccion=direccion,
                         localidad=_txt(dom, "localidad"), cp=_txt(dom, "codPostal"),
                         provincia=_txt(dom, "descripcionProvincia"), id_provincia=_txt(dom, "idProvincia"))

    estado = _txt(grales, "estadoClave")
    if estado and estado.upper() != "ACTIVO":
        avisos.append(f"Clave en ARCA: {estado}.")

    return {"cuit": P.digitos(_txt(grales, "idPersona")) or cuit, "razon_social": razon.upper(),
            "tipo_persona": _txt(grales, "tipoPersona"), "estado_clave": estado,
            "condicion_iva_codigo": iva_cod, "condicion_iva": iva_txt,
            "inscripto_ganancias": any(_es_ganancias(i) for i in activos) if activos else None,
            "condicion_iibb": iibb, "impuestos": impuestos, "actividades": actividades,
            "actividad_principal": actividades[0]["descripcion"] if actividades else "",
            "categoria_monotributo": categoria, "domicilio": domicilio,
            "avisos": avisos, "fuente": "constancia"}


# ─────────────────────────────────────────────────────────────────────────────
# Consulta
# ─────────────────────────────────────────────────────────────────────────────

def _no_autorizado(e: Exception) -> bool:
    return bool(re.search(r"notAuthorized|no autorizado", str(e), re.I))


def _constancia(cuit: str) -> dict:
    tk, sg = W.token(SERVICIO)
    cuerpo = (f'<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:a5="{NS}">'
              f"<soapenv:Header/><soapenv:Body><a5:getPersona_v2>"
              f"<token>{tk}</token><sign>{sg}</sign><cuitRepresentada>{W._cuit()}</cuitRepresentada>"
              f"<idPersona>{cuit}</idPersona></a5:getPersona_v2></soapenv:Body></soapenv:Envelope>")
    resp = W._post(URL, cuerpo, '""', legado=True)
    try:
        raiz = ET.fromstring(resp)
    except ET.ParseError as e:
        raise ErrorARCA(f"la constancia de ARCA contestó algo que no es XML: {resp[:200]}") from e
    falla = W._fault(raiz)
    if falla:
        if re.search(r"no existe persona|no se encontr", falla, re.I):
            raise NoEncontrado(falla)
        raise ErrorARCA(f"la constancia de ARCA contestó con error — {falla}")
    return leer_constancia(raiz, cuit)


def _desde_a13(p: dict) -> dict:
    """Lo del padrón A13 con la forma de la constancia (sin impuestos)."""
    d = p.get("domicilio") or {}
    direccion = " ".join(x for x in (d.get("calle"), d.get("numero"),
                                     ("Piso:" + d["piso"]) if d.get("piso") else "",
                                     ("Dpto:" + d["depto"]) if d.get("depto") else "") if x)
    estado = p.get("estado_clave") or ""
    return {"cuit": p.get("cuil") or "", "razon_social": (p.get("razon_social") or p.get("apellido_nombres") or "").upper(),
            "tipo_persona": p.get("tipo_persona") or "", "estado_clave": estado,
            "condicion_iva_codigo": None, "condicion_iva": "", "inscripto_ganancias": None, "condicion_iibb": None,
            "impuestos": [], "actividades": [], "actividad_principal": "", "categoria_monotributo": "",
            "domicilio": {"calle": d.get("calle") or "", "numero": d.get("numero") or "", "piso": d.get("piso") or "",
                          "depto": d.get("depto") or "", "direccion": direccion, "localidad": d.get("localidad") or "",
                          "cp": d.get("codigo_postal") or "", "provincia": d.get("provincia") or "",
                          "id_provincia": d.get("id_provincia") or ""} if d else {},
            "avisos": ([f"Clave en ARCA: {estado}."] if estado and estado.upper() != "ACTIVO" else [])
                      + ["La condición frente al IVA no se trajo: el certificado no tiene asociada la "
                         "Constancia de Inscripción (ws_sr_constancia_inscripcion) en ARCA. Vinieron "
                         "la razón social y el domicilio del padrón A13."],
            "fuente": "padron_a13"}


def consultar(cuit) -> dict:
    """
    Los datos de un CUIT. NoEncontrado si ARCA no lo tiene; ErrorARCA si no se
    pudo preguntar. Si el certificado no tiene la constancia pero sí el A13,
    vuelve lo del A13 con un aviso.
    """
    c = P.digitos(cuit)
    if len(c) != 11:
        raise ValueError("El CUIT tiene que tener 11 dígitos.")
    ok, motivo = configurado()
    if not ok:
        raise ErrorARCA(motivo)
    try:
        return _constancia(c)
    except ErrorARCA as e:
        if not _no_autorizado(e):
            raise
        try:
            return _desde_a13(P.persona(c))
        except ErrorARCA as e2:
            if _no_autorizado(e2):
                raise ErrorARCA("el certificado del sindicato no tiene asociado en ARCA el servicio "
                                "«ws_sr_constancia_inscripcion» (Constancia de Inscripción) ni el "
                                "«ws_sr_padron_a13»") from e
            raise


def provincia_codigo(cur, descripcion: str):
    """El `codigo` de p_provincia de la provincia que dice ARCA, por nombre (ver arca_padron.py)."""
    if not descripcion:
        return None
    cur.execute("SELECT codigo, nombre FROM p_provincia")
    return P.provincia_codigo(descripcion, cur.fetchall())


# ─────────────────────────────────────────────────────────────────────────────
# Para los botones de las fichas
# ─────────────────────────────────────────────────────────────────────────────

def para_ficha(cuit) -> dict:
    """
    Lo común de los «Consultar ARCA» de empleadores y proveedores:
    {"ok": False, "error", "no_configurado"} o {"ok": True, "cuit", "d": consultar()}.
    Cada pantalla arma después sus campos con `d`.
    """
    c = P.digitos(cuit)
    if len(c) != 11 or not P.cuil_valido(c):
        return {"ok": False, "error": "Cargá un CUIT de 11 dígitos que verifique el dígito de control."}
    ok, motivo = configurado()
    if not ok:
        return {"ok": False, "no_configurado": True, "error": f"No se puede consultar ARCA: {motivo}."}
    try:
        return {"ok": True, "cuit": c, "d": consultar(c)}
    except NoEncontrado as e:
        return {"ok": False, "error": f"ARCA no tiene ese CUIT ({e})."}
    except (ErrorARCA, ValueError) as e:
        log.warning("Consulta a ARCA del CUIT %s: %s", c, e)
        return {"ok": False, "error": f"No se pudo consultar ARCA: {e}."}


def texto_domicilio(dom: dict) -> str:
    """«AV CORRIENTES 1234 Piso:5 Dpto:B · 1043 · CIUDAD AUTONOMA BUENOS AIRES»."""
    if not dom:
        return ""
    return " · ".join(x for x in (dom.get("direccion"), " ".join(y for y in (dom.get("cp"), dom.get("localidad")) if y),
                                  dom.get("provincia")) if x)

