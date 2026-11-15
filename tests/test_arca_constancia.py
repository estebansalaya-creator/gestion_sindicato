"""
Pruebas de arca_constancia.py (sin ARCA ni base): la lectura de la respuesta de
getPersona_v2, la condición frente al IVA y cómo se parte el domicilio.
    python tests/test_arca_constancia.py
"""
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import arca_constancia as C  # noqa: E402

ok = fallos = 0


def v(cond, msg):
    global ok, fallos
    ok, fallos = (ok + 1, fallos) if cond else (ok, fallos + 1)
    print(("  OK   " if cond else "  FALLA ") + msg)


def sobre(cuerpo):
    return ET.fromstring('<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>'
                         '<ns2:getPersona_v2Response xmlns:ns2="http://a5.soap.ws.server.puc.sr/"><personaReturn>'
                         + cuerpo + '</personaReturn></ns2:getPersona_v2Response></soap:Body></soap:Envelope>')


print("\nUna SA responsable inscripta")
SA = """
<datosGenerales>
  <domicilioFiscal><codPostal>1043</codPostal><descripcionProvincia>CIUDAD AUTONOMA BUENOS AIRES</descripcionProvincia>
    <direccion>AV CORRIENTES 1234 Piso:5 Dpto:B</direccion><idProvincia>0</idProvincia><localidad></localidad>
    <tipoDomicilio>FISCAL</tipoDomicilio></domicilioFiscal>
  <estadoClave>ACTIVO</estadoClave><idPersona>30709768359</idPersona><razonSocial>Lesmaher SA</razonSocial>
  <tipoPersona>JURIDICA</tipoPersona>
</datosGenerales>
<datosRegimenGeneral>
  <actividad><descripcionActividad>VENTA AL POR MAYOR</descripcionActividad><idActividad>461011</idActividad>
    <nomenclador>883</nomenclador><orden>2</orden><periodo>201311</periodo></actividad>
  <actividad><descripcionActividad>SERVICIOS DE LIMPIEZA</descripcionActividad><idActividad>812010</idActividad>
    <nomenclador>883</nomenclador><orden>1</orden><periodo>201311</periodo></actividad>
  <impuesto><descripcionImpuesto>GANANCIAS SOCIEDADES</descripcionImpuesto><estadoImpuesto>AC</estadoImpuesto><idImpuesto>10</idImpuesto><periodo>200501</periodo></impuesto>
  <impuesto><descripcionImpuesto>IVA</descripcionImpuesto><estadoImpuesto>AC</estadoImpuesto><idImpuesto>30</idImpuesto><periodo>200501</periodo></impuesto>
  <impuesto><descripcionImpuesto>EMPLEADOR-APORTES SEG. SOCIAL</descripcionImpuesto><estadoImpuesto>AC</estadoImpuesto><idImpuesto>301</idImpuesto><periodo>200501</periodo></impuesto>
</datosRegimenGeneral>"""
d = C.leer_constancia(sobre(SA))
v(d["razon_social"] == "LESMAHER SA" and d["cuit"] == "30709768359", "razón social en mayúsculas y CUIT")
v(d["condicion_iva_codigo"] == 1, "IVA 30 → responsable inscripto (1)")
v(d["inscripto_ganancias"] is True, "Ganancias sociedades → inscripto")
v(d["actividad_principal"] == "SERVICIOS DE LIMPIEZA", "la actividad principal es la de orden 1")
dom = d["domicilio"]
v((dom["calle"], dom["numero"], dom["piso"], dom["depto"]) == ("AV CORRIENTES", "1234", "5", "B"),
  "el domicilio partido en calle, número, piso y depto")
v(dom["direccion"] == "AV CORRIENTES 1234 Piso:5 Dpto:B" and dom["cp"] == "1043", "la dirección entera y el CP")
v(C.P.provincia_codigo(dom["provincia"], [{"codigo": 1, "nombre": "Capital Federal"}]) == 1,
  "CABA se cruza con «Capital Federal» por nombre")
v(d["avisos"] == [] and d["fuente"] == "constancia", "sin avisos")

print("\nCondición frente al IVA")
def imp(i, desc):
    return {"id": i, "descripcion": desc, "estado": "AC", "periodo": ""}
v(C.condicion_iva([imp(32, "IVA EXENTO")])[0] == 4, "32 IVA EXENTO → exento (4)")
v(C.condicion_iva([imp(34, "IVA NO ALCANZADO")])[0] == 15, "34 → no alcanzado (15)")
v(C.condicion_iva([imp(33, "IVA RESPONSABLE NO INSCRIPTO")]) == (None, "IVA Responsable no Inscripto"),
  "33 → no inscripto, sin código en la tabla")
v(C.condicion_iva([imp(20, "MONOTRIBUTO")], "H LOCACIONES DE SERVICIO")[0] == 6, "monotributo (6)")
v(C.condicion_iva([imp(20, "MONOTRIBUTO")], "SOCIAL")[0] == 13, "monotributo social (13)")
v(C.condicion_iva([imp(11, "GANANCIAS PERSONAS FISICAS")])[0] == 7, "sin IVA ni monotributo → no categorizado (7)")
v(C.condicion_iva([]) == (None, ""), "sin impuestos: no se sabe")
v(C.condicion_iva([imp(301, "EMPLEADOR-APORTES SEG. SOCIAL"), imp(30, "IVA")])[0] == 1,
  "el 301 (empleador) no es monotributo social")

print("\nUn monotributista")
MONO = """
<datosGenerales>
  <apellido>PEREZ</apellido><nombre>JUAN CARLOS</nombre>
  <domicilioFiscal><codPostal>5000</codPostal><descripcionProvincia>CORDOBA</descripcionProvincia>
    <direccion>25 DE MAYO 300</direccion><idProvincia>3</idProvincia><localidad>CORDOBA</localidad>
    <tipoDomicilio>FISCAL</tipoDomicilio></domicilioFiscal>
  <estadoClave>ACTIVO</estadoClave><idPersona>20123456786</idPersona><tipoPersona>FISICA</tipoPersona>
</datosGenerales>
<datosMonotributo>
  <actividadMonotributista><descripcionActividad>SERVICIOS DE CONTABILIDAD</descripcionActividad><idActividad>692000</idActividad><orden>1</orden><periodo>201901</periodo></actividadMonotributista>
  <categoriaMonotributo><descripcionCategoria>D LOCACIONES DE SERVICIO</descripcionCategoria><idCategoria>4</idCategoria><idImpuesto>20</idImpuesto><periodo>202402</periodo></categoriaMonotributo>
  <impuesto><descripcionImpuesto>MONOTRIBUTO</descripcionImpuesto><estadoImpuesto>AC</estadoImpuesto><idImpuesto>20</idImpuesto><periodo>201901</periodo></impuesto>
</datosMonotributo>
<errorRegimenGeneral><error>El contribuyente no está inscripto en el régimen general</error></errorRegimenGeneral>"""
m = C.leer_constancia(sobre(MONO))
v(m["razon_social"] == "PEREZ JUAN CARLOS", "persona humana: apellido y nombre")
v(m["condicion_iva_codigo"] == 6 and m["categoria_monotributo"] == "D LOCACIONES DE SERVICIO", "monotributo y categoría")
v(m["inscripto_ganancias"] is False, "no inscripto en Ganancias")
v(m["actividad_principal"] == "SERVICIOS DE CONTABILIDAD", "actividad del monotributo")
v((m["domicilio"]["calle"], m["domicilio"]["numero"]) == ("25 DE MAYO", "300"), "«25 DE MAYO 300» no se corta en el 25")

print("\nSin constancia (errorConstancia)")
ERR = """<errorConstancia><apellido>GOMEZ</apellido><error>La clave se encuentra inactiva</error>
<idPersona>20111111112</idPersona><nombre>ANA</nombre></errorConstancia>"""
e = C.leer_constancia(sobre(ERR))
v(e["razon_social"] == "GOMEZ ANA" and e["condicion_iva_codigo"] is None, "el nombre sí, la condición no")
v(e["avisos"] and "inactiva" in e["avisos"][0], "dice por qué no hay constancia")
try:
    C.leer_constancia(sobre("<metadata/>"))
    v(False, "sin datos: NoEncontrado")
except C.NoEncontrado:
    v(True, "sin datos: NoEncontrado")

print("\nDomicilio en una cadena")
p = C.partir_direccion
v(p("CALLE 12 1450") == {"calle": "CALLE 12", "numero": "1450", "piso": "", "depto": ""}, "calle con número en el nombre")
v(p("RUTA 8 KM 50")["calle"] == "RUTA 8 KM 50", "ruta y kilómetro: entero en la calle")
v(p("CALLE 12")["calle"] == "CALLE 12", "«CALLE 12» sola no se parte")
v(p("SAN MARTIN S/N")["numero"] == "S/N", "sin número")
v(p("BELGRANO 455 PISO 3 DEPTO 12") == {"calle": "BELGRANO", "numero": "455", "piso": "3", "depto": "12"},
  "piso y depto escritos con espacio")
v(p("")["calle"] == "", "vacío")

print("\nEl A13 con la forma de la constancia")
a = C._desde_a13({"cuil": "30712345678", "razon_social": "Acme SRL", "apellido_nombres": "", "estado_clave": "ACTIVO",
                  "tipo_persona": "JURIDICA",
                  "domicilio": {"calle": "MITRE", "numero": "10", "piso": "1", "depto": "A", "localidad": "ROSARIO",
                                "codigo_postal": "2000", "provincia": "SANTA FE", "id_provincia": "12"}})
v(a["razon_social"] == "ACME SRL" and a["condicion_iva_codigo"] is None, "razón social; sin condición de IVA")
v(a["domicilio"]["direccion"] == "MITRE 10 Piso:1 Dpto:A" and a["domicilio"]["cp"] == "2000", "dirección armada")
v(a["fuente"] == "padron_a13" and any("ws_sr_constancia_inscripcion" in x for x in a["avisos"]), "avisa por qué falta el IVA")

print(f"\n{ok} bien, {fallos} mal")
sys.exit(1 if fallos else 0)
