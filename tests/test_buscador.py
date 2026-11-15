"""
Pruebas de buscador.py (sin base): cómo se parte lo tipeado y el armado del
WHERE.  python tests/test_buscador.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import buscador as B  # noqa: E402

ok = fallos = 0


def v(cond, msg):
    global ok, fallos
    ok, fallos = (ok + 1, fallos) if cond else (ok, fallos + 1)
    print(("  OK   " if cond else "  FALLA ") + msg)


print("\nPalabras")
v(B.palabras("camila ali") == (["camila", "ali"], []), "dos palabras, en cualquier orden")
v(B.palabras("27-41380797-8") == ([], ["27413807978"]), "un CUIL con guiones: los dígitos")
v(B.palabras("41.380.797") == ([], ["41380797"]), "un DNI con puntos")
v(B.palabras("ali 4138") == (["ali"], ["4138"]), "nombre y parte del documento")
v(B.palabras("a 12 x") == ([], []), "lo de una letra y los números de menos de tres dígitos no cuentan")
v(B.palabras("  ") == ([], []), "vacío")

print("\nWHERE")
w, p = B._where(["ali", "50%"], ["4138"], ["a.apellido_nombres"], ["a.cuil", "a.nro_documento"])
v(w == "(a.apellido_nombres LIKE %s) AND (a.apellido_nombres LIKE %s) AND (a.cuil LIKE %s OR a.nro_documento LIKE %s)",
  "cada palabra en sus columnas, todas juntas")
v(p == ["%ali%", "%50\\%%", "%4138%", "%4138%"], "el % tipeado no es comodín")

print("\nNombre de fantasía")
v(B._con_fantasia("KOHLER SA", "kohler sa") == "KOHLER SA", "igual a la razón social: no se repite")
v(B._con_fantasia("E&N SERVICIOS SRL", "EYN SERVICIOS SRL") == "E&N SERVICIOS SRL (EYN SERVICIOS SRL)", "distinto: entre paréntesis")
v(B._con_fantasia(None, "LA ESQUINA") == "LA ESQUINA", "sin razón social: la de fantasía")

print(f"\n{ok} bien, {fallos} mal")
sys.exit(1 if fallos else 0)
