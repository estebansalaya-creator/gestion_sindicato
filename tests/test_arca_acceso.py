"""
Pruebas del acceso a ARCA de arca_wscdc.py (sin ARCA ni base): el certificado
desde base64 (Railway), cuándo un token guardado sirve y que no se le pida a
ARCA uno nuevo si hay uno vigente.  python tests/test_arca_acceso.py
"""
import base64
import datetime
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import arca_wscdc as W  # noqa: E402

ok = fallos = 0


def v(cond, msg):
    global ok, fallos
    ok, fallos = (ok + 1, fallos) if cond else (ok, fallos + 1)
    print(("  OK   " if cond else "  FALLA ") + msg)


print("\nCertificado desde base64")
for k in ("SIND_ARCA_CERT", "SIND_ARCA_CERT_B64"):
    os.environ.pop(k, None)
v(W._ruta("SIND_ARCA_CERT") is None, "sin variables: no hay")
os.environ["SIND_ARCA_CERT_B64"] = base64.b64encode(b"-----BEGIN CERTIFICATE-----\nabc\n").decode()
r = W._ruta("SIND_ARCA_CERT")
v(r is not None and r.read_bytes() == b"-----BEGIN CERTIFICATE-----\nabc\n", "se escribe en un archivo temporal")
os.environ["SIND_ARCA_CERT_B64"] = base64.b64encode(b"otro").decode()
v(W._ruta("SIND_ARCA_CERT").read_bytes() == b"otro", "si cambia la variable, se reescribe")
os.environ["SIND_ARCA_CERT"] = "C:/web/certs/x.crt"
v(str(W._ruta("SIND_ARCA_CERT")).replace("\\", "/") == "C:/web/certs/x.crt", "con ruta y base64, manda la ruta")
os.environ.pop("SIND_ARCA_CERT")
os.environ["SIND_ARCA_CERT_B64"] = "esto no es base64!!"
v(W._ruta("SIND_ARCA_CERT") is None, "base64 roto: no hay certificado")
os.environ.pop("SIND_ARCA_CERT_B64")

print("\nToken vigente")
os.environ["SIND_ARCA_CUIT"] = "30657937270"
ahora = datetime.datetime.now(datetime.timezone.utc)
ta = {"token": "T", "sign": "S", "cuit": "30657937270", "expira": (ahora + datetime.timedelta(hours=3)).isoformat()}
v(W._vigente(ta) is ta, "vigente y del mismo CUIT")
v(W._vigente(dict(ta, cuit="20211076004")) is None, "de otro CUIT: no")
v(W._vigente(dict(ta, expira=(ahora + datetime.timedelta(minutes=3)).isoformat())) is None, "vence en menos de 5 minutos: no")
v(W._vigente(dict(ta, expira=(ahora + datetime.timedelta(hours=1)).replace(tzinfo=None).isoformat())) is not None,
  "la fecha sin zona (la de la base) es UTC")
v(W._vigente(None) is None and W._vigente({}) is None, "nada guardado")

print("\nNo se pide otro si hay uno")
tmp = tempfile.mkdtemp()
os.environ["SIND_ADJUNTOS"] = tmp
W._ta_base = lambda s: None                     # sin base
pedidos = []
W._pedir_token = lambda s: (pedidos.append(s), ("NUEVO", "FIRMA"))[1]
W._Candado.__enter__ = lambda self: self
W._Candado.__exit__ = lambda self, *e: False
v(W.token("wscdc") == ("NUEVO", "FIRMA") and pedidos == ["wscdc"], "sin token guardado: se pide")
os.makedirs(os.path.join(tmp, "arca"), exist_ok=True)
with open(os.path.join(tmp, "arca", "ta_ws_sr_padron_a13.json"), "w", encoding="utf-8") as f:
    json.dump(ta, f)
v(W.token("ws_sr_padron_a13") == ("T", "S") and pedidos == ["wscdc"], "con el del archivo: no se pide")
W._ta_base = lambda s: dict(ta, token="DE_LA_BASE") if s == "ws_sr_constancia_inscripcion" else None
v(W.token("ws_sr_constancia_inscripcion") == ("DE_LA_BASE", "S") and len(pedidos) == 1, "el de la base manda")

print(f"\n{ok} bien, {fallos} mal")
sys.exit(1 if fallos else 0)
