"""
Pruebas de arca_padron.py (sin ARCA ni base): el CUIL que sale de documento y
sexo, la lectura de la respuesta de getPersona y cómo se eligen los CUIL de un
documento.  python tests/test_arca_padron.py
"""
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import arca_padron as A  # noqa: E402

ok = fallos = 0


def v(cond, msg):
    global ok, fallos
    ok, fallos = (ok + 1, fallos) if cond else (ok, fallos + 1)
    print(("  OK   " if cond else "  FALLA ") + msg)


print("\nCUIL desde documento y sexo")
v(A.cuil_de("12345678", "M") == "20123456786", "varón: 20")
v(A.cuil_de("12.345.678", "F") == "27123456780", "mujer: 27, con puntos")
v(A.cuil_de("41380797", "F") == "27413807978", "un caso del padrón")
v(A.cuil_de("10000005", "M") == "23100000059", "el dígito no entra: 23 y 9 (varón)")
v(A.cuil_de("10000002", "F") == "23100000024", "el dígito no entra: 23 y 4 (mujer)")
v(A.cuil_de("123456", "M") == "", "menos de 7 dígitos: nada")
v(A.cuil_de("1234567", "M") == "20012345675", "7 dígitos: se completa con ceros")
v(all(A.cuil_valido(A.cuil_de(str(n), s)) for n in range(10000000, 10000300) for s in "MF"),
  "todo CUIL calculado verifica el dígito")
v(not A.cuil_valido("20123456787"), "un dígito mal no verifica")

print("\nRespuesta de getPersona")
XML = """<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>
<ns2:getPersonaResponse xmlns:ns2="http://a13.soap.ws.server.puc.sr/"><personaReturn>
<metadata><fechaHora>2026-11-15T10:00:00</fechaHora></metadata>
<persona>
  <apellido>Ali</apellido><nombre>Camila Ailen</nombre>
  <domicilio><calle>SAN MARTIN</calle><codigoPostal>1900</codigoPostal><descripcionProvincia>BUENOS AIRES</descripcionProvincia>
    <idProvincia>1</idProvincia><localidad>LA PLATA</localidad><numero>100</numero><tipoDomicilio>LEGAL/REAL</tipoDomicilio></domicilio>
  <domicilio><calle>AV SIEMPRE VIVA</calle><codigoPostal>5000</codigoPostal><descripcionProvincia>CORDOBA</descripcionProvincia>
    <idProvincia>3</idProvincia><localidad>CORDOBA</localidad><numero>742</numero><oficinaDptoLocal>B</oficinaDptoLocal>
    <piso>2</piso><tipoDomicilio>FISCAL</tipoDomicilio></domicilio>
  <estadoClave>ACTIVO</estadoClave><fechaNacimiento>1998-03-21T00:00:00-03:00</fechaNacimiento>
  <idPersona>27413807978</idPersona><numeroDocumento>41380797</numeroDocumento><sexo>FEMENINO</sexo>
  <tipoDocumento>DNI</tipoDocumento><tipoPersona>FISICA</tipoPersona>
</persona></personaReturn></ns2:getPersonaResponse></soap:Body></soap:Envelope>"""
p = A.leer_persona(ET.fromstring(XML))
v(p["cuil"] == "27413807978" and p["nro_documento"] == "41380797", "CUIL y documento")
v(p["apellido_nombres"] == "ALI CAMILA AILEN", "apellido y nombres juntos, en mayúsculas (como el padrón)")
v(p["sexo"] == "F" and p["fecha_nacimiento"] == "1998-03-21", "sexo y nacimiento")
v(p["fecha_fallecimiento"] == "", "sin fallecimiento")
d = p["domicilio"]
v(d["tipo"] == "FISCAL" and d["calle"] == "AV SIEMPRE VIVA", "con dos domicilios, el fiscal")
v((d["numero"], d["piso"], d["depto"], d["localidad"], d["codigo_postal"], d["id_provincia"])
  == ("742", "2", "B", "CORDOBA", "5000", "3"), "los campos del domicilio")
sin = A.leer_persona(ET.fromstring(XML.replace("<tipoDomicilio>FISCAL</tipoDomicilio>", "<tipoDomicilio>OTRO</tipoDomicilio>")))
v(sin["domicilio"]["calle"] == "SAN MARTIN", "sin fiscal, el primero")
try:
    A.leer_persona(ET.fromstring("<a><b/></a>"))
    v(False, "sin persona: NoEncontrado")
except A.NoEncontrado:
    v(True, "sin persona: NoEncontrado")

print("\nProvincia")
PROV = [{"codigo": 1, "nombre": "Capital Federal"}, {"codigo": 4, "nombre": "Córdoba"}, {"codigo": 5, "nombre": "Corrientes"},
        {"codigo": 24, "nombre": "Tierra del Fuego"}, {"codigo": 14, "nombre": "Santiago del Estero"}]
v(A.provincia_codigo("CORDOBA", PROV) == 4, "por nombre, sin acentos")
v(A.provincia_codigo("CIUDAD AUTONOMA BUENOS AIRES", PROV) == 1, "la ciudad de Buenos Aires es Capital Federal")
v(A.provincia_codigo("TIERRA DEL FUEGO, ANTARTIDA E ISLAS DEL ATLANTICO SUR", PROV) == 24, "Tierra del Fuego con el nombre largo")
v(A.provincia_codigo("santiago  del estero", PROV) == 14, "espacios y minúsculas")
v(A.provincia_codigo("", PROV) is None and A.provincia_codigo("MARTE", PROV) is None, "vacía o desconocida: nada")

print("\nCUIL de un documento")
ARCA = {}
A.ids_por_documento = lambda dni: ARCA.get(A.digitos(dni), [])
A.persona = lambda c: {"cuil": c}
ARCA["41380797"] = ["27413807978"]
r = A.buscar(documento="41380797", sexo="F")
v(r["persona"] == {"cuil": "27413807978"} and r["cuil_calculado"] == "27413807978", "uno solo: se trae")
ARCA["30111222"] = ["20301112225", "27301112227", "30301112229"]
r = A.buscar(documento="30111222", sexo="M")
v(r["persona"] == {"cuil": "20301112225"}, "dos personas con el número: el del sexo (y una empresa no cuenta)")
r = A.buscar(documento="30111222")
v(r["persona"] is None and r["candidatos"] == ["20301112225", "27301112227"], "sin sexo: los dos para elegir")
ARCA["10000005"] = ["23100000059"]
r = A.buscar(documento="10000005", sexo="M")
v(r["persona"] == {"cuil": "23100000059"}, "el 23 vale para cualquier sexo")
r = A.buscar(cuil="20-12345678-6", documento="41380797", sexo="F")
v(r["persona"] == {"cuil": "20123456786"}, "con CUIL, manda el CUIL")
try:
    A.buscar(documento="99999999", sexo="M")
    v(False, "ARCA sin CUIL para el documento: NoEncontrado")
except A.NoEncontrado:
    v(True, "ARCA sin CUIL para el documento: NoEncontrado")

print(f"\n{ok} bien, {fallos} mal")
sys.exit(1 if fallos else 0)
