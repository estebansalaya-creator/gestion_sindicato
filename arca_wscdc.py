"""
arca_wscdc.py — Constatación de comprobantes contra ARCA (WSCDC).

Le pregunta a ARCA si un comprobante existe y si sus datos —CUIT del emisor,
tipo, punto de venta, número, fecha, importe y CAE— son los que autorizó. Es
lo mismo que hace gestion_adm (`afip.constatar_comprobante`), con dos
diferencias:

CERTIFICADO PROPIO
------------------
El token del WSAA es uno por certificado y por servicio: si el sindicato usara
el certificado de gestion_adm, cada app pediría el suyo y ARCA le contestaría a
la segunda «ya posee un TA válido» hasta que venza el de la primera (12 horas).
Por eso va un certificado para esta app —puede ser del mismo CUIT, con otro
alias— con el servicio «wscdc» asociado en el Administrador de Relaciones.

    SIND_ARCA_CERT   ruta del .crt (o .pem) que entregó ARCA
    SIND_ARCA_KEY    ruta de la clave privada con la que se pidió
    SIND_ARCA_CUIT   CUIT dueño del certificado (si falta, el de «Datos del
                     sindicato»)

En Railway no hay archivos: `SIND_ARCA_CERT_B64` y `SIND_ARCA_KEY_B64` llevan
el contenido en base64 (como `AFIP_CERT_B64` en gestion_adm) y se escriben en
una carpeta temporal la primera vez. Con la ruta y el base64, manda la ruta.

El certificado del sindicato (15/11/2026) es el alias «gestionsindicato» de
AEDA (CUIT 30-65793727-0), con wscdc, ws_sr_padron_a13 y
ws_sr_constancia_inscripcion asociados; en este servidor está en
C:\web\certs\aeda_sindicato.crt / .key.

Sin esas variables la constatación queda apagada y los comprobantes se cargan
«sin constatar»: no es un error, es la configuración por defecto hasta tener el
certificado. Los que vienen de Mis Comprobantes ya los informó ARCA.

SIN ZEEP
--------
Los dos servicios son SOAP de una sola operación: se arman a mano con la
biblioteca estándar. La firma del pedido de acceso (CMS) se hace con
`cryptography` si está instalada y, si no, con el `openssl` del sistema, como
gestion_adm. El servidor de constatación de ARCA usa una clave Diffie-Hellman
chica que Python rechaza por defecto: se baja el nivel de seguridad del
cifrado solo para esa conexión.

EL TOKEN VA A LA BASE
---------------------
ARCA no entrega un token nuevo mientras el anterior siga vigente («El CEE ya
posee un TA válido»). Con el token solo en memoria, cada proceso de IIS pediría
el suyo y ARCA rechazaría todos menos el primero; con un archivo por servidor,
el IIS local y Railway —que usan la misma base— se pisarían igual. Por eso se
guarda en `arca_wsaa_ta` (sql/arca_wsaa_ta_20261115.sql), que leen todos, y el
pedido al WSAA va bajo GET_LOCK para que dos procesos no lo pidan a la vez. Es
lo que hace gestion_adm con wsfe (`arca_wsfe.py`). Mientras la tabla no exista,
queda el archivo `SIND_ADJUNTOS/arca/ta_<servicio>.json` de antes.

EL MISMO CERTIFICADO, OTROS SERVICIOS
-------------------------------------
El acceso (`token(servicio)`) sirve para cualquier servicio de ARCA que el
certificado tenga asociado: también lo usan la consulta al padrón
(arca_padron.py, «ws_sr_padron_a13») y la constancia de inscripción
(arca_constancia.py, «ws_sr_constancia_inscripcion»). Cada servicio tiene su
token. Para probar los tres contra ARCA: `python probar_arca.py [CUIT]`.
"""
from __future__ import annotations

import base64
import datetime
import html
import json
import logging
import os
import re
import shutil
import ssl
import subprocess
import tempfile
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

log = logging.getLogger(__name__)

SERVICIO = "wscdc"
WSAA_URL = "https://wsaa.afip.gov.ar/ws/services/LoginCms"
WSCDC_URL = "https://servicios1.afip.gov.ar/WSCDC/service.asmx"
TIMEOUT = 40

_wsdl: dict = {}


class ErrorARCA(Exception):
    """Algo que impidió preguntarle a ARCA (no un comprobante rechazado)."""


# ─────────────────────────────────────────────────────────────────────────────
# Configuración
# ─────────────────────────────────────────────────────────────────────────────

def _ruta(var: str) -> Path | None:
    """La ruta de `var` o, si no está, el archivo armado con `var`_B64 (Railway)."""
    v = (os.getenv(var) or "").strip()
    if v:
        return Path(v)
    b64 = re.sub(r"\s", "", os.getenv(var + "_B64") or "")
    if not b64:
        return None
    destino = Path(tempfile.gettempdir()) / "sind_arca" / var.lower()
    try:
        contenido = base64.b64decode(b64, validate=True)
    except ValueError:
        log.warning("%s_B64 no es base64 válido", var)
        return None
    if not destino.is_file() or destino.read_bytes() != contenido:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(contenido)
        try:
            os.chmod(destino, 0o600)
        except OSError:
            pass
    return destino


def _cuit() -> str:
    cuit = re.sub(r"\D", "", os.getenv("SIND_ARCA_CUIT") or "")
    if not cuit:
        try:
            import institucion
            cuit = re.sub(r"\D", "", institucion.obtener().get("cuit") or "")
        except Exception:                                    # noqa: BLE001
            cuit = ""
    return cuit


def configurado() -> tuple[bool, str]:
    """¿Se puede constatar? Devuelve (sí/no, por qué no)."""
    cert, key = _ruta("SIND_ARCA_CERT"), _ruta("SIND_ARCA_KEY")
    if not cert or not key:
        return False, ("la constatación con ARCA no está configurada (faltan "
                       "SIND_ARCA_CERT y SIND_ARCA_KEY en el .env, o sus _B64)")
    if not cert.is_file():
        return False, f"no se encuentra el certificado de ARCA ({cert})"
    if not key.is_file():
        return False, f"no se encuentra la clave privada de ARCA ({key})"
    if len(_cuit()) != 11:
        return False, ("falta el CUIT del certificado: SIND_ARCA_CUIT, o el CUIT en "
                       "Datos del Sindicato")
    return True, ""


def _carpeta() -> Path:
    base = Path(os.getenv("SIND_ADJUNTOS") or Path(__file__).with_name("adjuntos"))
    d = base / "arca"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ─────────────────────────────────────────────────────────────────────────────
# WSAA: el token de acceso
# ─────────────────────────────────────────────────────────────────────────────

def _tra(servicio: str = SERVICIO) -> bytes:
    ahora = datetime.datetime.now(datetime.timezone.utc)
    fmt = "%Y-%m-%dT%H:%M:%S+00:00"
    return (f'<?xml version="1.0" encoding="UTF-8"?><loginTicketRequest version="1.0"><header>'
            f"<uniqueId>{int(ahora.timestamp())}</uniqueId>"
            f"<generationTime>{(ahora - datetime.timedelta(minutes=10)).strftime(fmt)}</generationTime>"
            f"<expirationTime>{(ahora + datetime.timedelta(hours=12)).strftime(fmt)}</expirationTime>"
            f"</header><service>{servicio}</service></loginTicketRequest>").encode()


def _firmar(tra: bytes) -> str:
    """El TRA firmado en CMS (DER, con el contenido adentro), en base64."""
    cert_p, key_p = _ruta("SIND_ARCA_CERT"), _ruta("SIND_ARCA_KEY")
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.serialization import pkcs7
        cert = x509.load_pem_x509_certificate(cert_p.read_bytes())
        key = serialization.load_pem_private_key(key_p.read_bytes(), password=None)
        der = (pkcs7.PKCS7SignatureBuilder().set_data(tra)
               .add_signer(cert, key, hashes.SHA256())
               .sign(serialization.Encoding.DER, []))
        return base64.b64encode(der).decode()
    except ImportError:
        pass

    exe = shutil.which("openssl") or next(
        (c for c in (r"C:\Program Files\OpenSSL-Win64\bin\openssl.exe",
                     r"C:\Program Files\Git\usr\bin\openssl.exe") if os.path.exists(c)), None)
    if not exe:
        raise ErrorARCA("para firmar el pedido a ARCA hace falta la biblioteca "
                        "`cryptography` (pip install cryptography) o openssl en el PATH")
    with tempfile.TemporaryDirectory() as tmp:
        ent, sal = Path(tmp) / "tra.xml", Path(tmp) / "tra.cms"
        ent.write_bytes(tra)
        r = subprocess.run([exe, "smime", "-sign", "-in", str(ent), "-out", str(sal),
                            "-signer", str(cert_p), "-inkey", str(key_p),
                            "-outform", "DER", "-nodetach"], capture_output=True, timeout=30)
        if r.returncode != 0:
            raise ErrorARCA("openssl no pudo firmar: " + r.stderr.decode(errors="replace")[:300])
        return base64.b64encode(sal.read_bytes()).decode()


def _contexto_ssl(legado: bool = False) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if legado:
        ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
    if (os.getenv("SIND_ARCA_SIN_VERIFICAR_SSL") or "").strip() == "1":
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _post(url: str, cuerpo: str, accion: str, legado: bool = False) -> str:
    pedido = urllib.request.Request(url, data=cuerpo.encode("utf-8"), method="POST", headers={
        "Content-Type": "text/xml; charset=utf-8", "SOAPAction": accion})
    try:
        with urllib.request.urlopen(pedido, timeout=TIMEOUT, context=_contexto_ssl(legado)) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        # Un SOAP Fault viene con 500: el cuerpo es el que explica.
        return e.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError) as e:
        raise ErrorARCA(f"no se pudo conectar con ARCA ({e})") from e


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _buscar(raiz, nombre):
    return next((e for e in raiz.iter() if _local(e.tag) == nombre), None)


def _texto(raiz, nombre) -> str:
    e = _buscar(raiz, nombre)
    return (e.text or "").strip() if e is not None else ""


def _fault(raiz) -> str:
    f = _buscar(raiz, "Fault")
    if f is None:
        return ""
    return f"{_texto(f, 'faultcode')}: {_texto(f, 'faultstring')}".strip(": ")


def _vigente(ta: dict | None) -> dict | None:
    try:
        vence = datetime.datetime.fromisoformat(ta["expira"])
        if vence.tzinfo is None:
            vence = vence.replace(tzinfo=datetime.timezone.utc)
        if ta.get("cuit") == _cuit() and vence > datetime.datetime.now(datetime.timezone.utc) \
                + datetime.timedelta(minutes=5):
            return ta
    except (TypeError, ValueError, KeyError):
        pass
    return None


def _ta_base(servicio: str) -> dict | None:
    """El token guardado en `arca_wsaa_ta`, o None (sin tabla o sin base: el archivo)."""
    try:
        from db import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT token, sign, cuit, expira FROM arca_wsaa_ta "
                            "WHERE servicio = %s AND cuit = %s", (servicio, _cuit()))
                f = cur.fetchone()
    except Exception as e:                                   # noqa: BLE001
        if "1146" not in str(e):                             # sin la tabla: el archivo, en silencio
            log.warning("No se pudo leer el token de ARCA de la base: %s", e)
        return None
    if not f:
        return None
    return {"token": f["token"], "sign": f["sign"], "cuit": f["cuit"],
            "expira": f["expira"].replace(tzinfo=datetime.timezone.utc).isoformat()}


def _ta_archivo(servicio: str) -> dict | None:
    try:
        return json.loads((_carpeta() / f"ta_{servicio}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _leer_ta(servicio: str = SERVICIO) -> dict | None:
    return _vigente(_ta_base(servicio)) or _vigente(_ta_archivo(servicio))


def _guardar_ta(servicio: str, ta: dict) -> None:
    """En la base (la que leen todos los servidores) y en el archivo."""
    try:
        from db import get_connection
        vence = datetime.datetime.fromisoformat(ta["expira"]).astimezone(datetime.timezone.utc)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("REPLACE INTO arca_wsaa_ta (servicio, cuit, token, sign, expira) "
                            "VALUES (%s, %s, %s, %s, %s)",
                            (servicio, ta["cuit"], ta["token"], ta["sign"], vence.replace(tzinfo=None)))
    except Exception as e:                                   # noqa: BLE001
        if "1146" not in str(e):
            log.warning("No se pudo guardar el token de ARCA en la base: %s", e)
    try:
        (_carpeta() / f"ta_{servicio}.json").write_text(json.dumps(ta), encoding="utf-8")
    except OSError as e:
        log.warning("No se pudo guardar el token de ARCA: %s", e)


class _Candado:
    """GET_LOCK de MySQL mientras se pide el token: dos procesos (o el IIS y
    Railway) no le piden a ARCA a la vez. Sin base, sigue sin candado."""

    def __init__(self, servicio: str):
        self.nombre, self.conn = f"sind_wsaa_{servicio}"[:64], None

    def __enter__(self):
        try:
            from db import get_connection
            self.conn = get_connection()
            with self.conn.cursor() as cur:
                cur.execute("SELECT GET_LOCK(%s, 30) AS ok", (self.nombre,))
        except Exception as e:                               # noqa: BLE001
            log.warning("Sin candado para pedir el token de ARCA: %s", e)
            self.conn = None
        return self

    def __exit__(self, *exc):
        if self.conn is not None:
            try:
                with self.conn.cursor() as cur:
                    cur.execute("SELECT RELEASE_LOCK(%s)", (self.nombre,))
                self.conn.close()
            except Exception:                                # noqa: BLE001
                pass
        return False


def token(servicio: str = SERVICIO) -> tuple[str, str]:
    """(token, sign) vigentes para `servicio`: los guardados o uno nuevo del WSAA."""
    ta = _leer_ta(servicio)
    if ta:
        return ta["token"], ta["sign"]
    with _Candado(servicio):
        # Mientras se esperaba el candado lo pudo haber pedido otro.
        ta = _leer_ta(servicio)
        if ta:
            return ta["token"], ta["sign"]
        return _pedir_token(servicio)


def _pedir_token(servicio: str) -> tuple[str, str]:
    cuerpo = ('<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
              'xmlns:wsaa="http://wsaa.view.sua.dvadac.desein.afip.gov"><soapenv:Header/>'
              f"<soapenv:Body><wsaa:loginCms><wsaa:in0>{_firmar(_tra(servicio))}</wsaa:in0>"
              "</wsaa:loginCms></soapenv:Body></soapenv:Envelope>")
    resp = _post(WSAA_URL, cuerpo, '""')
    try:
        raiz = ET.fromstring(resp)
    except ET.ParseError as e:
        raise ErrorARCA(f"el WSAA contestó algo que no es XML: {resp[:200]}") from e
    falla = _fault(raiz)
    if falla:
        if "alreadyAuthenticated" in falla:
            # Otro proceso lo pidió recién: lo dejó en la base o en el archivo.
            ta = _leer_ta(servicio)
            if ta:
                return ta["token"], ta["sign"]
            raise ErrorARCA("ARCA dice que este certificado ya tiene un token vigente "
                            f"para {servicio} y no está guardado acá. Pasa si lo pidió otro "
                            "servidor (el IIS local o Railway) sin la tabla arca_wsaa_ta, o si lo "
                            "usa otra aplicación: hay que esperar a que venza (hasta 12 horas). "
                            "Cada aplicación necesita su propio certificado.")
        raise ErrorARCA(f"el WSAA rechazó el pedido de acceso — {falla}")

    ret = html.unescape(_texto(raiz, "loginCmsReturn"))
    ticket = ET.fromstring(ret)
    ta = {"token": _texto(ticket, "token"), "sign": _texto(ticket, "sign"), "cuit": _cuit(),
          "expira": datetime.datetime.fromisoformat(_texto(ticket, "expirationTime")).isoformat()}
    _guardar_ta(servicio, ta)
    return ta["token"], ta["sign"]


# ─────────────────────────────────────────────────────────────────────────────
# WSCDC
# ─────────────────────────────────────────────────────────────────────────────

def _definicion() -> dict:
    """Espacio de nombres y SOAPAction de ComprobanteConstatar, del WSDL."""
    if not _wsdl:
        pedido = urllib.request.Request(WSCDC_URL + "?WSDL")
        try:
            with urllib.request.urlopen(pedido, timeout=TIMEOUT, context=_contexto_ssl(True)) as r:
                wsdl = r.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, OSError) as e:
            raise ErrorARCA(f"no se pudo leer la definición del servicio de constatación ({e})") from e
        ns = re.search(r'targetNamespace="([^"]+)"', wsdl)
        acc = re.search(r'soapAction="([^"]*ComprobanteConstatar)"', wsdl)
        _wsdl["ns"] = ns.group(1) if ns else "http://servicios1.afip.gob.ar/wscdc/"
        _wsdl["accion"] = acc.group(1) if acc else _wsdl["ns"] + "ComprobanteConstatar"
    return _wsdl


def _lista(raiz, contenedor, item) -> list[dict]:
    c = _buscar(raiz, contenedor)
    if c is None:
        return []
    return [{"code": _texto(i, "Code"), "msg": _texto(i, "Msg")}
            for i in c.iter() if _local(i.tag) == item]


def constatar(cuit_emisor, tipo, punto_venta, numero, fecha, importe_total, cae,
              cuit_receptor=None) -> dict:
    """
    Constata un comprobante. `fecha` como date o 'AAAAMMDD'.

    Devuelve {"resultado": 'A'|'R'|'E', "fch_proceso", "observaciones", "errores"}.
    'E' es que no se pudo preguntar (configuración, red, servicio caído): el
    comprobante no está ni aprobado ni rechazado.
    """
    ok, motivo = configurado()
    if not ok:
        return {"resultado": "E", "fch_proceso": "", "observaciones": [],
                "errores": [{"code": "0", "msg": motivo}]}
    try:
        tk, sg = token()
        d = _definicion()
        fch = fecha.strftime("%Y%m%d") if hasattr(fecha, "strftime") else re.sub(r"\D", "", str(fecha))
        rec = ""
        if cuit_receptor:
            rec = (f"<ws:DocTipoReceptor>80</ws:DocTipoReceptor>"
                   f"<ws:DocNroReceptor>{re.sub(r'[^0-9]', '', str(cuit_receptor))}</ws:DocNroReceptor>")
        cuerpo = (f'<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
                  f'xmlns:ws="{d["ns"]}"><soap:Body><ws:ComprobanteConstatar>'
                  f"<ws:Auth><ws:Token>{tk}</ws:Token><ws:Sign>{sg}</ws:Sign>"
                  f"<ws:Cuit>{_cuit()}</ws:Cuit></ws:Auth>"
                  f"<ws:CmpReq><ws:CbteModo>CAE</ws:CbteModo>"
                  f"<ws:CuitEmisor>{re.sub(r'[^0-9]', '', str(cuit_emisor))}</ws:CuitEmisor>"
                  f"<ws:PtoVta>{int(punto_venta)}</ws:PtoVta><ws:CbteTipo>{int(tipo)}</ws:CbteTipo>"
                  f"<ws:CbteNro>{int(numero)}</ws:CbteNro><ws:CbteFch>{fch}</ws:CbteFch>"
                  f"<ws:ImpTotal>{float(importe_total):.2f}</ws:ImpTotal>"
                  f"<ws:CodAutorizacion>{re.sub(r'[^0-9]', '', str(cae))}</ws:CodAutorizacion>"
                  f"{rec}</ws:CmpReq></ws:ComprobanteConstatar></soap:Body></soap:Envelope>")
        resp = _post(WSCDC_URL, cuerpo, d["accion"], legado=True)
        raiz = ET.fromstring(resp)
        falla = _fault(raiz)
        if falla:
            raise ErrorARCA(f"el servicio de constatación contestó con error — {falla}")
        res = _buscar(raiz, "ComprobanteConstatarResult")
        if res is None:
            raise ErrorARCA("la respuesta de ARCA no trae el resultado")
        return {"resultado": _texto(res, "Resultado") or "E",
                "fch_proceso": _texto(res, "FchProceso"),
                "observaciones": _lista(res, "Observaciones", "Obs"),
                "errores": _lista(res, "Errors", "Err")}
    except (ErrorARCA, ET.ParseError, ValueError, TypeError) as e:
        log.warning("Constatación ARCA: %s", e)
        return {"resultado": "E", "fch_proceso": "", "observaciones": [],
                "errores": [{"code": "0", "msg": str(e)}]}


def texto_resultado(cst: dict) -> str:
    """Las observaciones y errores de ARCA en una línea."""
    msgs = [f"{o.get('code')}: {o.get('msg')}" if o.get("code") not in (None, "", "0") else o.get("msg", "")
            for o in (cst.get("errores") or []) + (cst.get("observaciones") or [])]
    return " · ".join(m for m in msgs if m)
