"""
aplicar_cobros.py — Aplicación automática de los cobros a las cuotas sindicales.

La misma que el botón «Aplicar automáticamente» de Empleadores → Aplicación de
Cobros (fisca_aplicaciones.aplicar_automatico): cada cobro a su propio período
hasta el saldo de la cuota y, con --deuda-vieja, lo que sobra a la deuda más
vieja del mismo empleador. Saca lo aplicado a órdenes o liquidaciones anuladas
y recorta lo automático de una cuota que se reliquidó por menos. Lo aplicado a
mano no lo toca.

Uso
---
    python aplicar_cobros.py                         simula: graba, informa y deshace
    python aplicar_cobros.py --aplicar               graba
    python aplicar_cobros.py --aplicar --deuda-vieja
    python aplicar_cobros.py --cuit 30712345678      solo ese empleador

La primera vez, después de sql/fisca_aplicaciones_20261114.sql: hasta que se
corre, ningún cobro cancela ninguna cuota y la cuenta corriente muestra todos
los períodos impagos.
"""

import argparse
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

import fisca_aplicaciones as fa        # noqa: E402
from db import get_connection          # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Aplicación automática de los cobros a las cuotas sindicales.")
    p.add_argument("--aplicar", action="store_true", help="grabar (sin esto, simula)")
    p.add_argument("--deuda-vieja", action="store_true", help="lo que sobra de cada cobro, a la deuda más vieja")
    p.add_argument("--cuit", help="solo ese empleador")
    a = p.parse_args(argv)
    cuit = re.sub(r"\D", "", a.cuit or "") or None
    if cuit and len(cuit) != 11:
        print("\n  El CUIT tiene que tener 11 dígitos.\n")
        return 1
    with get_connection() as conn:
        with conn.cursor() as cur:
            if fa.falta_esquema(cur):
                print("\n  Falta correr sql/fisca_aplicaciones_20261114.sql.\n")
                return 1
        conn.begin()
        try:
            with conn.cursor() as cur:
                r = fa.aplicar_automatico(cur, cuits=[cuit] if cuit else None, deuda_vieja=a.deuda_vieja)
            if a.aplicar:
                conn.commit()
            else:
                conn.rollback()
        except Exception:
            conn.rollback()
            raise
    print()
    print("  " + fa.texto_resultado(r))
    print(f"  Queda cobrado sin aplicar: {fa._pesos(r['sin_aplicar'])}")
    print("  GRABADO." if a.aplicar else "  SIMULACIÓN: no se grabó nada (--aplicar graba).")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
