"""
arca_padron.py — Consulta al padrón de ARCA (Padrón A13, «ws_sr_padron_a13»).

Lo usa la ficha del afiliado (afiliados.py, `/afiliados/arca`, pedido del
15/11/2026): con el tipo y el número de documento y el sexo se calcula el CUIL
y se le pregunta a ARCA quién es, para completar apellido y nombres, fecha de
nacimiento y domicilio. Es la consulta de gestion_adm (`afip.consultar_cuit`),
sin zeep, con el mismo acceso que la constatación de comprobantes
(arca_wscdc.py): el certificado del sindicato, `SIND_ARCA_CERT` / `SIND_ARCA_KEY`
/ `SIND_ARCA_CUIT`.

**El certificado tiene que tener el servicio asociado.** En ARCA, Administrador
de Relaciones de Clave Fiscal → Nueva relación → el computador fiscal del
certificado del sindicato → servicio «ws_sr_padron_a13» (Consulta a Padrón
Alcance 13). El token es uno por certificado y por servicio: no se puede usar el
certificado de gestion_adm, que ya lo pide para sí (ver arca_wscdc.py). Sin
certificado, `configurado()` dice qué falta y la ficha calcula el CUIL igual.

Dos operaciones:

    getIdPersonaListByDocumento   los CUIL / CUIT que ARCA tiene para un DNI
    getPersona                    los datos de un CUIL

Se lee la respuesta por nombre de etiqueta, sin depender de los espacios de
nombres, como arca_wscdc.py.
"""
from __future__ import annotations

import datetime
import re
import unicodedata
import xml.etree.ElementTree as ET

import arca_wscdc as W

SERVICIO = "ws_sr_padron_a13"
URL = "https://aws.afip.gov.ar/sr-padron/webservices/personaServiceA13"
NS = "http://a13.soap.ws.server.puc.sr/"

#: Prefijos de CUIL de una persona humana (el resto son CUIT de sociedades).
PREFIJOS_PERSONA = ("20", "23", "24", "27")

ErrorARCA = W.ErrorARCA


class NoEncontrado(Exception):
    """ARCA no tiene a esa persona (no es una falla de la consulta)."""


def configurado() -> tuple[bool, str]:
    ok, motivo = W.configurado()
    if not ok:
        return False, motivo.replace("la constatación con ARCA", "la consulta a ARCA")
    return True, ""


def digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def cuil_valido(c: str) -> bool:
    c = digitos(c)
    if len(c) != 11:
        return False
    suma = sum(int(c[i]) * p for i, p in enumerate((5, 4, 3, 2, 7, 6, 5, 4, 3, 2)))
    resto = suma % 11
    dv = 0 if resto == 0 else (9 if resto == 1 else 11 - resto)
    return dv == int(c[10])


def cuil_de(dni, sexo: str | None) -> str:
    """El CUIL que corresponde a un DNI y un sexo (la cuenta de ARCA): 20 varón,
    27 mujer; si el dígito no entra en uno, 23 y la cuenta otra vez (9 varón, 4
    mujer). Es el probable: ARCA puede haber dado otro prefijo, por eso después
    se le pregunta. La misma función que `cuilDesdeDniSexo` de la ficha."""
    d = digitos(dni)
    if not 7 <= len(d) <= 8:
        return ""
    d = d.zfill(8)

    def dv(base):
        resto = sum(int(base[i]) * p for i, p in enumerate((5, 4, 3, 2, 7, 6, 5, 4, 3, 2))) % 11
        return 0 if resto == 0 else (10 if resto == 1 else 11 - resto)

    prefijo = "27" if sexo == "F" else "20"
    v = dv(prefijo + d)
    if v == 10:
        prefijo = "23"
        v = dv(prefijo + d)
    return f"{prefijo}{d}{v}"


# La provincia del padrón se cruza por NOMBRE: el idProvincia de ws_sr_padron no
# es el `codigo_arca` de p_provincia (en el padrón 4 es Corrientes, 5 Entre Ríos,
# 9 Salta; en p_provincia codigo_arca 4 es Chubut). Lo confirman las respuestas
# guardadas por gestion_adm (contable.arca_domicilios), que también cruza por
# nombre (padron_arca_domicilios.ALIAS_PROVINCIA).
ALIAS_PROVINCIA = {
    "CIUDAD AUTONOMA BUENOS AIRES": "CAPITAL FEDERAL",
    "CIUDAD AUTONOMA DE BUENOS AIRES": "CAPITAL FEDERAL",
    "CABA": "CAPITAL FEDERAL",
    "CIUDAD DE BUENOS AIRES": "CAPITAL FEDERAL",
    "TIERRA DEL FUEGO, ANTARTIDA E ISLAS DEL ATLANTICO SUR": "TIERRA DEL FUEGO",
}


def normalizar(s) -> str:
    """Mayúsculas, sin acentos y sin espacios de más: «Córdoba» → «CORDOBA»."""
    s = unicodedata.normalize("NFD", str(s or "").strip().upper())
    return " ".join("".join(c for c in s if unicodedata.category(c) != "Mn").split())


def provincia_codigo(descripcion: str, provincias: list[dict]):
    """El `codigo` de p_provincia de la provincia que dice ARCA (o None).
    `provincias`: filas con `codigo` y `nombre`."""
    d = normalizar(descripcion)
    d = ALIAS_PROVINCIA.get(d, d)
    if not d:
        return None
    for f in provincias:
        if normalizar(f["nombre"]) == d:
            return f["codigo"]
    return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _hijos(e, nombre) -> list:
    return [x for x in e if _local(x.tag) == nombre]


def _txt(e, nombre) -> str:
    x = next((x for x in e if _local(x.tag) == nombre), None)
    return (x.text or "").strip() if x is not None and x.text else ""


def _llamar(operacion: str, campos: dict) -> ET.Element:
    ok, motivo = configurado()
    if not ok:
        raise ErrorARCA(motivo)
    tk, sg = W.token(SERVICIO)
    extra = "".join(f"<{k}>{v}</{k}>" for k, v in campos.items())
    cuerpo = (f'<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:a13="{NS}">'
              f"<soapenv:Header/><soapenv:Body><a13:{operacion}>"
              f"<token>{tk}</token><sign>{sg}</sign><cuitRepresentada>{W._cuit()}</cuitRepresentada>{extra}"
              f"</a13:{operacion}></soapenv:Body></soapenv:Envelope>")
    resp = W._post(URL, cuerpo, '""', legado=True)
    try:
        raiz = ET.fromstring(resp)
    except ET.ParseError as e:
        raise ErrorARCA(f"el padrón de ARCA contestó algo que no es XML: {resp[:200]}") from e
    falla = W._fault(raiz)
    if falla:
        if re.search(r"no existe persona|no se encontr", falla, re.I):
            raise NoEncontrado(falla)
        raise ErrorARCA(f"el padrón de ARCA contestó con error — {falla}")
    return raiz


def ids_por_documento(dni) -> list[str]:
    """Los CUIL / CUIT que ARCA tiene para ese número de documento."""
    d = digitos(dni)
    if not 7 <= len(d) <= 8:
        return []
    try:
        raiz = _llamar("getIdPersonaListByDocumento", {"documento": d})
    except NoEncontrado:
        return []
    return [digitos(e.text) for e in raiz.iter() if _local(e.tag) == "idPersona" and digitos(e.text)]


def _fecha(v: str) -> str:
    """'1969-09-13T00:00:00-03:00' → '1969-09-13'."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})", v or "")
    return m.group(1) if m else ""


def leer_persona(raiz: ET.Element) -> dict:
    """Los datos de la respuesta de getPersona. Aparte para poder probarlo sin ARCA."""
    p = next((e for e in raiz.iter() if _local(e.tag) == "persona"), None)
    if p is None:
        raise NoEncontrado("la respuesta de ARCA no trae a la persona")
    doms = _hijos(p, "domicilio")
    dom = next((d for d in doms if _txt(d, "tipoDomicilio").upper() == "FISCAL"), None) or (doms[0] if doms else None)
    domicilio = {}
    if dom is not None:
        domicilio = {"calle": _txt(dom, "calle") or _txt(dom, "direccion"), "numero": _txt(dom, "numero"),
                     "piso": _txt(dom, "piso"), "depto": _txt(dom, "oficinaDptoLocal"),
                     "localidad": _txt(dom, "localidad"), "codigo_postal": _txt(dom, "codigoPostal"),
                     "id_provincia": _txt(dom, "idProvincia"), "provincia": _txt(dom, "descripcionProvincia"),
                     "tipo": _txt(dom, "tipoDomicilio")}
    apellido, nombre = _txt(p, "apellido"), _txt(p, "nombre")
    return {"cuil": digitos(_txt(p, "idPersona")),
            "apellido": apellido, "nombre": nombre,
            "razon_social": _txt(p, "razonSocial"),
            "apellido_nombres": " ".join(x for x in (apellido, nombre) if x).upper(),
            "tipo_persona": _txt(p, "tipoPersona"), "estado_clave": _txt(p, "estadoClave"),
            "tipo_documento": _txt(p, "tipoDocumento"), "nro_documento": digitos(_txt(p, "numeroDocumento")),
            "fecha_nacimiento": _fecha(_txt(p, "fechaNacimiento")),
            "fecha_fallecimiento": _fecha(_txt(p, "fechaFallecimiento")),
            "sexo": {"MASCULINO": "M", "FEMENINO": "F", "M": "M", "F": "F"}.get(_txt(p, "sexo").upper(), ""),
            "domicilio": domicilio}


def persona(cuil) -> dict:
    """Los datos de un CUIL. NoEncontrado si ARCA no lo tiene."""
    c = digitos(cuil)
    if len(c) != 11:
        raise ValueError("El CUIL tiene que tener 11 dígitos.")
    return leer_persona(_llamar("getPersona", {"idPersona": c}))


def buscar(cuil: str = "", documento: str = "", sexo: str = "") -> dict:
    """
    Por CUIL, o por documento y sexo: {"persona": {...} o None,
    "candidatos": [CUIL...], "cuil_calculado": ...}.

    Con documento se le piden a ARCA los CUIL de ese número y se quedan los de
    persona humana; con sexo, primero el que corresponde (20 varón, 27 mujer, 23
    y 24 cualquiera). Uno solo: se trae. Varios: vuelven para elegir.
    """
    c = digitos(cuil)
    calculado = cuil_de(documento, sexo) if documento else ""
    if len(c) == 11:
        return {"persona": persona(c), "candidatos": [c], "cuil_calculado": calculado}
    ids = [i for i in ids_por_documento(documento) if i[:2] in PREFIJOS_PERSONA]
    if sexo in ("M", "F"):
        propio = "20" if sexo == "M" else "27"
        ids = [i for i in ids if i[:2] in (propio, "23", "24")] or ids
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise NoEncontrado("ARCA no tiene un CUIL para ese documento.")
    if len(ids) == 1:
        return {"persona": persona(ids[0]), "candidatos": ids, "cuil_calculado": calculado}
    return {"persona": None, "candidatos": ids, "cuil_calculado": calculado}
