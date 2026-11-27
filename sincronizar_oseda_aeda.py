"""
sincronizar_oseda_aeda.py — Reintenta en OSEDA lo que quedó pendiente.

El ABM de afiliados aplica el atributo AEDA en OSEDA en el momento. Si en ese
momento OSEDA no respondía, la fila quedó PENDIENTE en `p_afiliados_oseda_aeda`
y este script la vuelve a intentar, en orden. Se puede programar (cada hora
alcanza) o correr a mano.

Uso
---
    python sincronizar_oseda_aeda.py            aplica lo pendiente
    python sincronizar_oseda_aeda.py --listar   solo muestra lo pendiente
"""

import argparse
import sys

from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent / ".env")

import oseda_aeda                     # noqa: E402  (después del .env)
from db import get_connection         # noqa: E402


def listar():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, id_afiliado, cuil, motivo, accion, intentos, creado, ultimo_error
                  FROM p_afiliados_oseda_aeda WHERE estado = 'PENDIENTE' ORDER BY id
            """)
            filas = cur.fetchall()
    if not filas:
        print("No hay nada pendiente.")
        return
    for f in filas:
        print(f"{f['id']:>6}  {f['creado']:%d/%m/%Y %H:%M}  {f['cuil'] or '-':<11}  "
              f"{f['motivo']:<12} {f['accion']:<8} intentos {f['intentos']}  {f['ultimo_error'] or ''}")
    print(f"\n{len(filas)} pendiente(s).")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--listar", action="store_true", help="solo mostrar lo pendiente")
    args = ap.parse_args()
    if args.listar:
        listar()
        return
    conteo = oseda_aeda.procesar()
    if not conteo:
        print("No hay nada pendiente.")
        return
    for clave, n in sorted(conteo.items()):
        if clave not in ("error", "sin_configurar"):
            print(f"{n:>6}  {clave}")
    if conteo.get("sin_configurar"):
        print("\nFalta SIND_CONTABLE_HOST / SIND_OSEDA_AEDA_USER en el .env: no se tocó OSEDA.")
    if conteo.get("error"):
        print(f"\nÚltimo error: {conteo['error']}")
    sys.exit(1 if conteo.get("PENDIENTE") else 0)


if __name__ == "__main__":
    main()
