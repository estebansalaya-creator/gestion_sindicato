"""
Pruebas de empleadores_arca.py (sin ARCA ni base): qué cambia del domicilio
fiscal y cómo corre la tanda.  python tests/test_empleadores_arca.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import empleadores_arca as E  # noqa: E402

ok = fallos = 0


def v(cond, msg):
    global ok, fallos
    ok, fallos = (ok + 1, fallos) if cond else (ok, fallos + 1)
    print(("  OK   " if cond else "  FALLA ") + msg)


PROV = [{"codigo": 1, "nombre": "Capital Federal"}, {"codigo": 4, "nombre": "Córdoba"}]
DOM = {"calle": "AV CORRIENTES", "numero": "1234", "piso": "5", "depto": "B", "cp": "1043",
       "localidad": "", "provincia": "CIUDAD AUTONOMA BUENOS AIRES"}

print("\nPeríodo desde")
import datetime as dt  # noqa: E402
v(E.periodo_desde(dt.date(2026, 11, 15)) == 202511 and E.periodo_desde(dt.date(2026, 1, 3)) == 202501, "doce meses atrás")

print("\nDomicilio fiscal")
vacio = {k: None for k in E.CAMPOS}
c = E.domicilio_cambios(vacio, DOM, E._provincia(PROV, DOM["provincia"]))
v(c == {"fdom_calle": "AV CORRIENTES", "fdom_numero": "1234", "fdom_piso": "5", "fdom_depto": "B",
        "fdom_cp": "1043", "fdom_provincia_id": "1", "fdom_provincia_nombre": "Capital Federal"},
  "vacío: todo lo que trae ARCA (sin localidad, que viene vacía)")
igual = dict(vacio, fdom_calle="Av. Corrientes", fdom_numero="1234", fdom_piso="5", fdom_depto="b",
             fdom_cp="01043", fdom_provincia_id="1", fdom_provincia_nombre="Capital Federal")
v(E.domicilio_cambios(igual, DOM, (1, "Capital Federal")) == {}, "igual salvo mayúsculas, signos o ceros: nada")
otro = dict(igual, fdom_numero="1200", fdom_localidad_nombre="CABA", fdom_localidad_id="77")
c = E.domicilio_cambios(otro, dict(DOM, localidad="CIUDAD DE BUENOS AIRES"), (1, "Capital Federal"))
v(c.get("fdom_numero") == "1234" and "fdom_calle" not in c, "cambia el número: solo lo que difiere del bloque")
v(c.get("fdom_localidad_nombre") == "CIUDAD DE BUENOS AIRES" and "fdom_localidad_id" in c and c["fdom_localidad_id"] is None,
  "otra localidad: se vacía su id")
v(E.domicilio_cambios(otro, dict(DOM, calle=""), (1, "Capital Federal")) == {}, "ARCA sin domicilio: no se borra el que hay")
sin_piso = dict(igual, fdom_piso="5")
c = E.domicilio_cambios(sin_piso, dict(DOM, piso="", depto=""), (1, "Capital Federal"))
v(c == {"fdom_piso": None, "fdom_depto": None}, "ARCA ya no informa piso y depto: se vacían")

print("\nUno y la tanda")


class Cur:
    def __init__(self, log): self.log = log
    def execute(self, sql, p=None): self.log.append((" ".join(sql.split())[:40], p))
    def __enter__(self): return self
    def __exit__(self, *a): pass


class Con:
    def __init__(self): self.log = []
    def cursor(self): return Cur(self.log)
    def begin(self): self.log.append(("BEGIN", None))
    def commit(self): self.log.append(("COMMIT", None))
    def rollback(self): self.log.append(("ROLLBACK", None))
    def __enter__(self): return self
    def __exit__(self, *a): pass


def consulta(cuit):
    if cuit.endswith("9"):
        raise E.C.ErrorARCA("no se pudo conectar con ARCA")
    return {"cuit": cuit, "razon_social": "X SA", "estado_clave": "ACTIVO", "tipo_persona": "JURIDICA",
            "condicion_iva": "IVA Responsable Inscripto", "categoria_monotributo": "", "impuestos": [],
            "actividades": [], "domicilio": DOM, "avisos": [], "fuente": "constancia"}


con = Con()
emp = dict(vacio, id=5, CUIT=30682342907, razon_social="ACEBEY S A")
r = E.actualizar_uno(con, emp, PROV, usuario=3, consultar=consulta)
sql = [x[0] for x in con.log]
v(not r["error"] and len(r["cambios"]) == 7 and r["cambios"][0]["rotulo"] == "Calle", "consulta y arma los cambios con rótulo")
v(sql[0] == "BEGIN" and sql[-1] == "COMMIT" and any(x.startswith("UPDATE p_empresas SET") for x in sql), "actualiza p_empresas en una transacción")
v(sum(x.startswith("INSERT INTO arca_constancia_cambios") for x in sql) == 7, "un renglón de auditoría por campo")
v(any(x.startswith("INSERT INTO arca_constancia ") for x in sql), "y guarda la constancia")
con2 = Con()
r = E.actualizar_uno(con2, dict(emp, CUIT=30682342909), PROV, consultar=consulta)
v(r["error"] and con2.log == [], "si ARCA falla, no toca la base")
con3 = Con()
r = E.actualizar_uno(con3, emp, PROV, consultar=lambda c: dict(consulta(c), fuente="padron_a13"))
v(not any(x[0].startswith("INSERT INTO arca_constancia ") for x in con3.log), "lo del A13 no pisa la constancia guardada")

E._TRABAJO = {"total": 3, "hechos": 0, "consultados": 0, "actualizados": [], "errores": [], "terminado": False,
              "cortado": None, "actual": "", "inicio": "", "fin": None}
filas = [emp, dict(emp, id=6, CUIT=30682342909, razon_social="CAIDA"), dict(emp, id=7)]
E.tanda(lambda: Con(), filas, PROV, consultar=consulta, pausa=0)
t = E.estado()
v(t["terminado"] and t["hechos"] == 3 and t["consultados"] == 2, "un error no corta a los demás")
v(len(t["errores"]) == 1 and t["errores"][0]["razon_social"] == "CAIDA" and len(t["actualizados"]) == 2, "errores y actualizados")
E._TRABAJO.update(terminado=False, hechos=0, consultados=0, errores=[], actualizados=[])
E.tanda(lambda: Con(), [dict(emp, id=i, CUIT=30682342909) for i in range(40)], PROV, consultar=consulta, pausa=0)
t = E.estado()
v(t["hechos"] == E.ERRORES_SEGUIDOS_MAX and t["cortado"] and "seguidos" in t["cortado"], "muchos errores iguales seguidos: corta")

print(f"\n{ok} bien, {fallos} mal")
sys.exit(1 if fallos else 0)
