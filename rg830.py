"""
rg830.py — Regímenes de retención de Ganancias (RG 830) para la ficha del proveedor.

La parte de `gestion_adm/retenciones.py` que necesita el ABM de proveedores:
qué regímenes tienen una escala vigente en `rg830_escala`, el resumen que se
muestra debajo del combo, y la regla de que a un monotributista no se le
retiene Ganancias. El cálculo de la retención —que es del circuito de pagos—
se trae con el resto de `retenciones.py` cuando se haga ese módulo.

Del proveedor se guarda SOLO si aplica y el régimen (`ret_ganancias_codigo_sir`).
Cómo se calcula —escala o alícuota fija—, el mínimo no sujeto y los porcentajes
los dice la fila vigente de `rg830_escala`. En gestion_adm cada proveedor
llegó a tener su propia copia de esos valores, y cada copia decía otra cosa.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

#: Condiciones de IVA (arca_responsable_tipo) que son monotributo: 6, 13 y 16.
#: Al adherido al Régimen Simplificado no se le retiene Ganancias: el impuesto
#: lo paga dentro de la cuota.
CONDICIONES_MONOTRIBUTO = frozenset({6, 13, 16})


def es_monotributista(condicion_iva) -> bool:
    try:
        return int(condicion_iva) in CONDICIONES_MONOTRIBUTO
    except (TypeError, ValueError):
        return False


def normalizar_regimen(codigo) -> str:
    """El código a tres dígitos: «94» → «094». Vacío o cero → «». La tabla guarda
    «94» y los proveedores pueden traer «94», «094» o «0»."""
    txt = "".join(c for c in str(codigo or "") if c.isdigit())
    if not txt or int(txt) == 0:
        return ""
    return txt.zfill(3)


def _pesos(valor) -> str:
    v = Decimal(str(valor or 0))
    txt = f"{v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return "$" + (txt[:-3] if txt.endswith(",00") else txt)


def _pct(valor) -> str:
    v = Decimal(str(valor or 0)).normalize()
    return f"{v:f}".replace(".", ",") + "%"


def resumen(reg: dict) -> str:
    """Forma de cálculo, mínimo no sujeto, retención mínima y resolución."""
    if reg.get("tipo_calculo") == "escala":
        alics = [Decimal(str(t["alicuota"])) for t in reg.get("tramos") or []]
        forma = (f"Escala progresiva del {_pct(min(alics))} al {_pct(max(alics))} "
                 f"en {len(alics)} tramos") if alics else "Escala progresiva SIN TRAMOS CARGADOS"
    else:
        forma = (f"Alícuota fija {_pct(reg['alicuota_fija'])}"
                 if reg.get("alicuota_fija") else "Alícuota fija SIN ALÍCUOTA CARGADA")
    partes = [forma, f"mínimo no sujeto {_pesos(reg.get('monto_no_sujeto_inscripto'))} por mes"]
    if reg.get("retencion_minima_inscripto"):
        partes.append(f"retención mínima {_pesos(reg['retencion_minima_inscripto'])}")
    if reg.get("resolucion"):
        partes.append(str(reg["resolucion"]))
    return " · ".join(partes)


def vigentes(cur, fecha: datetime.date | None = None) -> list[dict]:
    """Los regímenes con fila vigente y activa, uno por código (la vigencia más
    nueva), con su resumen. Es lo que ofrece el combo de la ficha."""
    fecha = fecha or datetime.date.today()
    cur.execute("""
        SELECT id, codigo_regimen, descripcion, tipo_calculo, alicuota_fija,
               monto_no_sujeto_inscripto, retencion_minima_inscripto,
               resolucion, vigencia_desde
          FROM rg830_escala
         WHERE activa = 1 AND vigencia_desde <= %s
           AND (vigencia_hasta IS NULL OR vigencia_hasta >= %s)
         ORDER BY vigencia_desde DESC
    """, (fecha, fecha))
    por_codigo: dict[str, dict] = {}
    for f in cur.fetchall():
        cod = normalizar_regimen(f.get("codigo_regimen"))
        if cod and cod not in por_codigo:
            por_codigo[cod] = dict(f, codigo=cod, tramos=[])
    for reg in por_codigo.values():
        if reg.get("tipo_calculo") == "escala":
            cur.execute("SELECT alicuota FROM rg830_escala_tramos WHERE id_escala = %s",
                        (reg["id"],))
            reg["tramos"] = list(cur.fetchall())
        reg["resumen"] = resumen(reg)
    return [por_codigo[c] for c in sorted(por_codigo)]
