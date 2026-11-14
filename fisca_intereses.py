"""
fisca_intereses.py — Vencimiento del F.931 e interés resarcitorio de ARCA.

La cuota sindical vence el mismo día que el F.931 del empleador (decidido el
14/11/2026): el que fija ARCA para la presentación y el pago de la DDJJ de la
seguridad social, según la terminación del CUIT. Los intereses son los
resarcitorios de ARCA (art. 37 Ley 11.683), con la tasa vigente en cada tramo.

VENCIMIENTO (`vencimiento_931`)
  1. `arca_vencimientos` (obligación F931, período, dígito): la tabla de
     gestion_adm, que se copia con importar_arca_tablas.py.
  2. Si el período no está: la regla de ARCA, día 9 (CUIT terminado en 0 a 3),
     10 (4 a 6) u 11 (7 a 9) del mes siguiente, corrido al día hábil siguiente
     si cae sábado, domingo o feriado (`arca_feriados`). Es la misma fórmula con
     la que gestion_adm armó su tabla.

INTERÉS (`interes`, `tramos`)
  Interés simple: capital × Σ (tasa mensual / 30 / 100 × días del tramo). Los
  días van del día siguiente al vencimiento hasta el día del pago (o de la
  fecha de cálculo) inclusive: (pago − vencimiento) días. Cada día lleva la
  tasa de `arca_intereses` vigente ese día (vigencia_hasta inclusive; NULL =
  vigente). gestion_adm cortaba cada tramo en vigencia_hasta sin incluirla y
  perdía un día en cada cambio de tasa; acá la suma de días es exacta.
"""

from __future__ import annotations

import datetime
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
#: Día del mes siguiente según la terminación del CUIT (regla de ARCA para el F.931).
DIA_931 = {**{str(d): 9 for d in range(4)}, **{str(d): 10 for d in range(4, 7)}, **{str(d): 11 for d in range(7, 10)}}


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


def redondear(v) -> Decimal:
    return _d(v).quantize(CENT, rounding=ROUND_HALF_UP)


# ─────────────────────────────────────────────────────────────────────────────
# Vencimientos
# ─────────────────────────────────────────────────────────────────────────────

class Calendario:
    """Los vencimientos del F.931 y los feriados, leídos una vez."""

    def __init__(self, cur):
        self.oficiales: dict[tuple[str, str], datetime.date] = {}
        self.feriados: set[datetime.date] = set()
        cur.execute("""SELECT COUNT(*) AS n FROM information_schema.tables
                        WHERE table_schema = DATABASE() AND table_name = 'arca_vencimientos'""")
        if cur.fetchone()["n"]:
            cur.execute("""SELECT periodo, digito_verificador AS d, fecha_vencimiento AS f
                             FROM arca_vencimientos WHERE obligacion = 'F931'""")
            self.oficiales = {(f["periodo"], str(f["d"])): f["f"] for f in cur.fetchall() if f["f"]}
        cur.execute("""SELECT COUNT(*) AS n FROM information_schema.tables
                        WHERE table_schema = DATABASE() AND table_name = 'arca_feriados'""")
        if cur.fetchone()["n"]:
            cur.execute("SELECT fecha FROM arca_feriados WHERE activo = 1")
            self.feriados = {f["fecha"] for f in cur.fetchall()}

    def habil(self, fecha: datetime.date) -> datetime.date:
        while fecha.weekday() >= 5 or fecha in self.feriados:
            fecha += datetime.timedelta(days=1)
        return fecha

    def por_formula(self, periodo: str, digito: str) -> datetime.date:
        anio, mes = int(periodo[:4]), int(periodo[4:])
        anio, mes = (anio + 1, 1) if mes == 12 else (anio, mes + 1)
        return self.habil(datetime.date(anio, mes, DIA_931.get(digito, 11)))

    def vencimiento(self, cuit: str, periodo: str) -> datetime.date:
        """El del F.931 de ese CUIT para ese período."""
        digito = (str(cuit or "").strip() or "9")[-1]
        return self.oficiales.get((periodo, digito)) or self.por_formula(periodo, digito)

    def es_oficial(self, cuit: str, periodo: str) -> bool:
        return (periodo, (str(cuit or "").strip() or "9")[-1]) in self.oficiales


def vencimiento_931(cur, cuit: str, periodo: str) -> datetime.date:
    return Calendario(cur).vencimiento(cuit, periodo)


# ─────────────────────────────────────────────────────────────────────────────
# Tasas e intereses
# ─────────────────────────────────────────────────────────────────────────────

def tasas(cur) -> list[dict]:
    """`arca_intereses` completa (son pocas filas), de la más vieja a la más nueva."""
    cur.execute("""SELECT id, vigencia_desde, vigencia_hasta, resarcitorio, resolucion, tipo
                     FROM arca_intereses WHERE vigencia_desde IS NOT NULL ORDER BY vigencia_desde""")
    return list(cur.fetchall())


def tasa_vigente(lista: list[dict], fecha: datetime.date) -> dict | None:
    for t in reversed(lista):
        if t["vigencia_desde"] <= fecha and (t["vigencia_hasta"] is None or fecha <= t["vigencia_hasta"]):
            return t
    return None


def tramos(lista: list[dict], desde: datetime.date, hasta: datetime.date) -> list[dict]:
    """Los días entre `desde` (el vencimiento) y `hasta` (el pago), por tasa.
    Cuenta del día siguiente a `desde` hasta `hasta` inclusive."""
    if not desde or not hasta or hasta <= desde:
        return []
    ini, fin = desde + datetime.timedelta(days=1), hasta            # días que devengan, inclusive
    out = []
    for t in lista:
        vd = t["vigencia_desde"]
        vh = t["vigencia_hasta"] or datetime.date(9999, 12, 31)
        a, b = max(ini, vd), min(fin, vh)
        if a > b:
            continue
        dias = (b - a).days + 1
        tasa = _d(t["resarcitorio"])
        out.append({"desde": a, "hasta": b, "dias": dias, "tasa": tasa, "resolucion": t.get("resolucion"),
                    "coef": tasa / Decimal(30) / Decimal(100) * dias})
    cubiertos = sum(x["dias"] for x in out)
    total = (fin - ini).days + 1
    if cubiertos < total:
        raise ValueError(f"No hay tasa de interés resarcitorio cargada para {total - cubiertos} día(s) entre "
                         f"{ini:%d/%m/%Y} y {fin:%d/%m/%Y} (arca_intereses).")
    return out


def coeficiente(lista: list[dict], desde: datetime.date, hasta: datetime.date) -> Decimal:
    return sum((x["coef"] for x in tramos(lista, desde, hasta)), Decimal("0"))


def interes(lista: list[dict], capital, desde: datetime.date, hasta: datetime.date) -> Decimal:
    """Interés resarcitorio de `capital` entre el vencimiento y el pago, al centavo."""
    if _d(capital) <= 0:
        return Decimal("0.00")
    return redondear(_d(capital) * coeficiente(lista, desde, hasta))
