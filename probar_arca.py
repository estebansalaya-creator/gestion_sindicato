r"""
probar_arca.py — Probar desde la consola el acceso del sindicato a ARCA
=======================================================================
No graba nada en el sistema (salvo el token de acceso, en `arca_wsaa_ta`).
Para el primer paso de cada servidor: ¿está el certificado, llega a ARCA,
consigue el token de cada servicio, contesta la constancia y el padrón?

    python probar_arca.py                 con el CUIT del certificado (AEDA)
    python probar_arca.py 30709768359     la constancia y el padrón de ese CUIT

Servicios que prueba (los asociados al alias «gestionsindicato» de AEDA):

    wscdc                          constatación de comprobantes
    ws_sr_padron_a13               padrón A13 (ficha del afiliado)
    ws_sr_constancia_inscripcion   constancia (empleadores y proveedores)

Toma las variables del .env de esta carpeta, como la aplicación
(SIND_ARCA_CERT / SIND_ARCA_KEY / SIND_ARCA_CUIT, o sus _B64).
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

import arca_constancia as C  # noqa: E402
import arca_padron as P      # noqa: E402
import arca_wscdc as W       # noqa: E402

SERVICIOS = ("wscdc", P.SERVICIO, C.SERVICIO)
fallos = 0


def linea(ok, texto):
    global fallos
    fallos += not ok
    print(("  OK     " if ok else "  FALLA  ") + texto)


def main():
    print("\nCertificado")
    ok, motivo = W.configurado()
    linea(ok, f"{W._ruta('SIND_ARCA_CERT')} · CUIT {W._cuit() or '—'}" if ok else motivo)
    if not ok:
        return

    print("\nToken guardado en la base")
    try:
        from db import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT servicio, expira FROM arca_wsaa_ta ORDER BY servicio")
                filas = cur.fetchall()
        linea(True, "tabla arca_wsaa_ta: " + (", ".join(f"{f['servicio']} vence {f['expira']} UTC"
                                                         for f in filas) or "vacía"))
    except Exception as e:                                   # noqa: BLE001
        linea(False, "sin la tabla arca_wsaa_ta (falta correr sql/arca_wsaa_ta_20261115.sql): "
                     f"el token queda solo en un archivo de este servidor — {e}")

    print("\nAcceso a cada servicio (WSAA)")
    for s in SERVICIOS:
        try:
            W.token(s)
            linea(True, s)
        except W.ErrorARCA as e:
            linea(False, f"{s}: {e}")

    cuit = P.digitos(sys.argv[1]) if len(sys.argv) > 1 else W._cuit()

    print(f"\nConstancia de inscripción de {cuit}")
    try:
        d = C._constancia(cuit)
        linea(True, f"{d['razon_social']} · {d['condicion_iva'] or 'sin condición de IVA'}"
                    + (f" ({d['categoria_monotributo']})" if d["categoria_monotributo"] else ""))
        print(f"           domicilio: {C.texto_domicilio(d['domicilio']) or '—'}")
        print(f"           actividad: {d['actividad_principal'] or '—'}")
        for a in d["avisos"]:
            print(f"           aviso: {a}")
    except (C.ErrorARCA, C.NoEncontrado, ValueError) as e:
        linea(False, str(e))

    print(f"\nPadrón A13 de {cuit}")
    try:
        p = P.persona(cuit)
        dom = p.get("domicilio") or {}
        linea(True, f"{p['razon_social'] or p['apellido_nombres']} · clave {p['estado_clave'] or '—'}")
        print(f"           domicilio: {' '.join(x for x in (dom.get('calle'), dom.get('numero'), dom.get('localidad'), dom.get('provincia')) if x) or '—'}")
    except (P.ErrorARCA, P.NoEncontrado, ValueError) as e:
        linea(False, str(e))


if __name__ == "__main__":
    main()
    print("\nTodo bien." if not fallos else f"\n{fallos} con falla.")
    sys.exit(1 if fallos else 0)
