"""
fisca_escalas.py — Fiscalización de Cuotas › Escalas Salariales (menú 9).

    /fiscalizacion/escalas                      vigencias y la escala elegida: ?ver=AAAAMM
    /fiscalizacion/escalas/nueva                GET (?base=AAAAMM) / POST: alta de una vigencia
    /fiscalizacion/escalas/<desde>/editar       GET / POST: corrige una cargada acá
    /fiscalizacion/escalas/<desde>/eliminar     POST: borra una cargada acá

La escala del convenio (CCT 417/05): básico por antigüedad (0 a 35 años) y el
almuerzo diario, por vigencia (`fisca_escala_salarial`, sql/fisca_escalas_20261114.sql).
Pedido del 14/11/2026: consultar, importar y cargar las nuevas. Lo de AEDA lo trae
importar_aeda_fisca_escalas.py (desde la máquina local: Railway no llega a AEDA), así
que acá se ve y no se toca; lo cargado acá (origen «manual») se corrige o se borra.

- **Conformado** = básico + almuerzo × 22 días (la «comida» del art. 9 CCT 417/05:
  así sale en las circulares; enero 2025: 7.512 × 22 = 165.264).
- **Vigencias**: la nueva arranca en su período y llega hasta el mes anterior a la
  siguiente (o queda abierta si es la última). La anterior, si estaba abierta o la
  pisaba, se cierra el mes antes. No se parte una de AEDA ni se repite un período.
  Al borrar una, la anterior se estira hasta donde llegaba la borrada.
- **Controles al grabar** (los de las circulares del 14/11/2026; se pueden pasar
  con «Grabar igual»): el básico no baja al subir la antigüedad (AEDA tiene uno así
  en 2022-01, 29 años) y, contra la escala anterior, todas las antigüedades suben en
  la misma proporción (±0,03 %): un número mal copiado se despega del resto.
- **Pegar**: los 36 básicos de una planilla o de la circular de una vez; acepta
  «506,404.46» y «506.404,46». Solo toma importes con centavos, así «1 año» no
  cuenta como número. Si vienen 37, el último es el almuerzo.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from flask import Blueprint, flash, redirect, render_template, request, url_for

from db import get_connection, puede, validasesion

fisca_esc_bp = Blueprint("fisca_esc", __name__, url_prefix="/fiscalizacion")

URL = "/fiscalizacion/escalas"
SQL_ESQUEMA = "sql/fisca_escalas_20261114.sql"
ANTIGUEDADES = 36
DIAS_COMIDA = 22
#: Cuánto se puede despegar una antigüedad de la proporción del resto.
TOLERANCIA = Decimal("0.0003")
CENT = Decimal("0.01")
ORIGENES = {"aeda": ("AEDA", "neutro"), "manual": ("Cargada acá", "info")}


# =============================================================================
# Lógica (sin base)
# =============================================================================

def numero(texto) -> Decimal | None:
    """«506,404.46», «506.404,46», «$ 506404,46» o «506404.46» → Decimal. El
    separador decimal es el último que aparece; sin decimales, los puntos y
    comas son de miles."""
    t = re.sub(r"[^\d.,\-]", "", str(texto or ""))
    if not t or not re.search(r"\d", t):
        return None
    ult = max(t.rfind("."), t.rfind(","))
    if ult >= 0 and len(t) - ult - 1 in (1, 2):
        entero, dec = t[:ult], t[ult + 1:]
    else:
        entero, dec = t, ""
    entero = re.sub(r"[.,]", "", entero)
    try:
        return Decimal(f"{entero or '0'}.{dec or '0'}").quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


_RE_IMPORTE = re.compile(r"\d[\d.,]*[.,]\d{2}(?!\d)")


def importes_de(texto) -> list[Decimal]:
    """Los importes con centavos de un texto pegado, en orden."""
    return [n for n in (numero(m.group(0)) for m in _RE_IMPORTE.finditer(texto or "")) if n is not None]


def periodo_de(texto) -> str | None:
    t = re.sub(r"\D", "", str(texto or ""))
    if len(t) == 6 and 1 <= int(t[4:]) <= 12 and 2000 <= int(t[:4]) <= 2100:
        return t
    return None


def periodo_txt(p) -> str:
    return f"{p[:4]}-{p[4:]}" if p and len(p) == 6 else (p or "")


def mes_anterior(p: str) -> str:
    y, m = int(p[:4]), int(p[4:]) - 1
    if m == 0:
        y, m = y - 1, 12
    return f"{y}{m:02d}"


def bajan(basicos: list[Decimal]) -> list[int]:
    """Antigüedades cuyo básico es menor que el de la anterior."""
    return [i for i in range(1, len(basicos)) if basicos[i] < basicos[i - 1]]


def factor(anterior: list[Decimal], nueva: list[Decimal]) -> tuple[Decimal | None, list[int]]:
    """La proporción con que subió la escala (la mediana) y las antigüedades que
    se despegan de ella."""
    if not anterior or len(anterior) != len(nueva) or any(not a for a in anterior):
        return None, []
    r = [nueva[i] / anterior[i] for i in range(len(nueva))]
    med = sorted(r)[len(r) // 2]
    return med, [i for i, x in enumerate(r) if abs(x - med) > TOLERANCIA]


def nombre_antig(i: int) -> str:
    return "Inicial" if i == 0 else ("1 año" if i == 1 else f"{i} años")


def conformado(basico, almuerzo) -> Decimal:
    return (Decimal(basico or 0) + Decimal(almuerzo or 0) * DIAS_COMIDA).quantize(CENT)


# =============================================================================
# Base
# =============================================================================

def _guardia():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede(URL):
        flash("!No tenés permiso para las escalas salariales.")
        return redirect(url_for("menu"))
    return None


def _falta_esquema(cur) -> bool:
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.tables
                    WHERE table_schema = DATABASE() AND table_name = 'fisca_escala_salarial'""")
    return not cur.fetchone()["n"]


def vigencias(cur) -> list[dict]:
    cur.execute("""SELECT periodo_desde, MAX(periodo_hasta) AS periodo_hasta, MAX(origen) AS origen,
                          COUNT(*) AS antiguedades, MAX(almuerzo) AS almuerzo,
                          MAX(IF(antiguedad = 0, basico, NULL)) AS inicial,
                          MAX(IF(antiguedad = 35, basico, NULL)) AS a35,
                          SUM(IF(periodo_hasta IS NULL, 1, 0)) AS abierta, MAX(actualizado) AS actualizado
                     FROM fisca_escala_salarial GROUP BY periodo_desde ORDER BY periodo_desde DESC""")
    filas = list(cur.fetchall())
    for i, v in enumerate(filas):
        v["abierta"] = bool(v["abierta"])
        ant = filas[i + 1] if i + 1 < len(filas) else None
        v["aumento"] = ((Decimal(v["inicial"]) / Decimal(ant["inicial"]) - 1) * 100).quantize(CENT) \
            if ant and v["inicial"] and ant["inicial"] else None
        v["anterior"] = ant["periodo_desde"] if ant else None
    return filas


def escala(cur, desde) -> list[dict]:
    cur.execute("""SELECT * FROM fisca_escala_salarial WHERE periodo_desde = %s ORDER BY antiguedad""", (desde,))
    return list(cur.fetchall())


def _basicos(filas) -> list[Decimal]:
    return [Decimal(f["basico"]) for f in filas]


def anterior_a(cur, desde) -> str | None:
    cur.execute("SELECT MAX(periodo_desde) AS p FROM fisca_escala_salarial WHERE periodo_desde < %s", (desde,))
    return (cur.fetchone() or {}).get("p")


def siguiente_a(cur, desde) -> str | None:
    cur.execute("SELECT MIN(periodo_desde) AS p FROM fisca_escala_salarial WHERE periodo_desde > %s", (desde,))
    return (cur.fetchone() or {}).get("p")


# =============================================================================
# Pantallas
# =============================================================================

@fisca_esc_bp.route("/escalas")
def lista():
    salida = _guardia()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            if _falta_esquema(cur):
                flash(f"!Falta correr {SQL_ESQUEMA} en esta base.")
                return render_template("fisca/escalas.html", vigs=[], sel=None, filas=[], origenes=ORIGENES)
            vigs = vigencias(cur)
            ver = periodo_de(request.args.get("ver")) or (vigs[0]["periodo_desde"] if vigs else None)
            sel = next((v for v in vigs if v["periodo_desde"] == ver), None)
            filas = escala(cur, ver) if sel else []
            ant = escala(cur, sel["anterior"]) if sel and sel["anterior"] else []
    previo = {f["antiguedad"]: Decimal(f["basico"]) for f in ant}
    for f in filas:
        f["conformado"] = conformado(f["basico"], f["almuerzo"])
        p = previo.get(f["antiguedad"])
        f["aumento"] = ((Decimal(f["basico"]) / p - 1) * 100).quantize(CENT) if p else None
    fac, raros = factor(_basicos(ant), _basicos(filas)) if ant and len(ant) == len(filas) else (None, [])
    return render_template("fisca/escalas.html", vigs=vigs, sel=sel, filas=filas, origenes=ORIGENES,
                           baja=bajan(_basicos(filas)), raros=raros,
                           factor=((fac - 1) * 100).quantize(CENT) if fac else None, dias=DIAS_COMIDA)


def _leer_form(form) -> tuple[dict, list[str]]:
    errores = []
    e = {"desde": periodo_de(form.get("periodo_desde")), "desde_txt": form.get("periodo_desde") or "",
         "almuerzo": numero(form.get("almuerzo")), "almuerzo_txt": form.get("almuerzo") or "",
         "basicos_txt": form.getlist("basico")[:ANTIGUEDADES], "basicos": []}
    if not e["desde"]:
        errores.append("Elegí el período desde el que rige.")
    if e["almuerzo"] is None or e["almuerzo"] < 0:
        errores.append("El almuerzo tiene que ser un importe (puede ser cero).")
    while len(e["basicos_txt"]) < ANTIGUEDADES:
        e["basicos_txt"].append("")
    for i, t in enumerate(e["basicos_txt"]):
        n = numero(t)
        if n is None or n <= 0:
            errores.append(f"{nombre_antig(i)}: falta el básico o no es un importe.")
        e["basicos"].append(n or Decimal("0"))
    return e, errores


def _controles(cur, e, excluir=None) -> list[str]:
    """Los avisos que se pueden pasar con «Grabar igual»."""
    avisos = []
    b = bajan(e["basicos"])
    if b:
        avisos.append("El básico baja al subir la antigüedad en " + ", ".join(nombre_antig(i) for i in b)
                      + ": revisá que no esté mal copiado.")
    ant = anterior_a(cur, e["desde"])
    if ant and ant != excluir:
        fac, raros = factor(_basicos(escala(cur, ant)), e["basicos"])
        if fac is not None:
            if raros:
                avisos.append(f"Contra la escala de {periodo_txt(ant)} sube {str(((fac - 1) * 100).quantize(CENT)).replace('.', ',')} %, "
                              "pero no en " + ", ".join(nombre_antig(i) for i in raros)
                              + ": un número mal copiado se despega del resto.")
            if fac < 1:
                avisos.append(f"Es más baja que la escala de {periodo_txt(ant)}.")
    return avisos


def _grabar(cur, e, origen_desde=None) -> None:
    """Graba la vigencia (alta, o corrección si `origen_desde`) y acomoda las
    vigencias de alrededor. Con el cursor de una transacción."""
    d = e["desde"]
    if origen_desde:
        cur.execute("SELECT periodo_hasta FROM fisca_escala_salarial WHERE periodo_desde = %s LIMIT 1", (origen_desde,))
        hasta_viejo = (cur.fetchone() or {}).get("periodo_hasta")
        cur.execute("DELETE FROM fisca_escala_salarial WHERE periodo_desde = %s AND origen = 'manual'", (origen_desde,))
        # La anterior se estira como si se hubiera borrado; la nueva fecha la vuelve a cortar.
        ant = anterior_a(cur, origen_desde)
        if ant:
            cur.execute("""UPDATE fisca_escala_salarial SET periodo_hasta = %s
                            WHERE periodo_desde = %s AND origen = 'manual' AND periodo_hasta = %s""",
                        (hasta_viejo, ant, mes_anterior(origen_desde)))
    cur.execute("SELECT COUNT(*) AS n FROM fisca_escala_salarial WHERE periodo_desde = %s", (d,))
    if cur.fetchone()["n"]:
        raise ValueError(f"Ya hay una escala desde {periodo_txt(d)}: corregí esa.")
    ant = anterior_a(cur, d)
    if ant:
        cur.execute("""SELECT MAX(periodo_hasta) AS h, SUM(periodo_hasta IS NULL) AS abierta, MAX(origen) AS o
                         FROM fisca_escala_salarial WHERE periodo_desde = %s""", (ant,))
        a = cur.fetchone()
        if a["abierta"] or (a["h"] and a["h"] >= d):
            if a["o"] == "aeda" and not a["abierta"]:
                raise ValueError(f"{periodo_txt(d)} cae dentro de la escala de AEDA de {periodo_txt(ant)} a "
                                 f"{periodo_txt(a['h'])}: esa no se parte.")
            cur.execute("UPDATE fisca_escala_salarial SET periodo_hasta = %s WHERE periodo_desde = %s",
                        (mes_anterior(d), ant))
    sig = siguiente_a(cur, d)
    hasta = mes_anterior(sig) if sig else None
    cur.executemany("""INSERT INTO fisca_escala_salarial (periodo_desde, periodo_hasta, antiguedad, basico, almuerzo, origen)
                       VALUES (%s, %s, %s, %s, %s, 'manual')""",
                    [(d, hasta, i, b, e["almuerzo"]) for i, b in enumerate(e["basicos"])])


def _form(e, errores, avisos, editando, vigs, bases):
    return render_template("fisca/escala_form.html", e=e, errores=errores, avisos=avisos, editando=editando,
                           vigs=vigs, bases=bases, n=ANTIGUEDADES, dias=DIAS_COMIDA)


def _formulario(editar: str | None):
    salida = _guardia()
    if salida:
        return salida
    with get_connection() as conn:
        with conn.cursor() as cur:
            if _falta_esquema(cur):
                flash(f"!Falta correr {SQL_ESQUEMA} en esta base.")
                return redirect(url_for("fisca_esc.lista"))
            vigs = vigencias(cur)
            bases = {v["periodo_desde"]: [str(b) for b in _basicos(escala(cur, v["periodo_desde"]))] for v in vigs[:24]}
            actual = escala(cur, editar) if editar else []
    if editar and (not actual or actual[0]["origen"] != "manual"):
        flash("!Esa escala no existe o vino de AEDA: las de AEDA no se corrigen acá.")
        return redirect(url_for("fisca_esc.lista", ver=editar))

    if request.method == "GET":
        if actual:
            e = {"desde": editar, "desde_txt": periodo_txt(editar), "almuerzo": actual[0]["almuerzo"],
                 "almuerzo_txt": f"{actual[0]['almuerzo']}", "basicos_txt": [str(f["basico"]) for f in actual]}
        else:
            base = periodo_de(request.args.get("base")) or (vigs[0]["periodo_desde"] if vigs else None)
            sug = None
            if vigs:
                y, m = int(vigs[0]["periodo_desde"][:4]), int(vigs[0]["periodo_desde"][4:]) + 1
                sug = f"{y + (m > 12)}-{(m - 1) % 12 + 1:02d}"
            e = {"desde": None, "desde_txt": sug or "", "almuerzo_txt": "", "basicos_txt": [""] * ANTIGUEDADES,
                 "base": base}
        return _form(e, [], [], editar, vigs, bases)

    e, errores = _leer_form(request.form)
    avisos = []
    if not errores:
        conn = get_connection()
        try:
            conn.begin()
            with conn.cursor() as cur:
                avisos = _controles(cur, e, excluir=editar)
                if avisos and not request.form.get("grabar_igual"):
                    conn.rollback()
                    return _form(e, [], avisos, editar, vigs, bases)
                _grabar(cur, e, origen_desde=editar)
            conn.commit()
        except ValueError as ex:
            conn.rollback()
            errores.append(str(ex))
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    if errores:
        return _form(e, errores, [], editar, vigs, bases)
    flash(f"Escala desde {periodo_txt(e['desde'])} {'corregida' if editar else 'grabada'}."
          + (" Se grabó con avisos." if avisos else ""))
    return redirect(url_for("fisca_esc.lista", ver=e["desde"]))


@fisca_esc_bp.route("/escalas/nueva", methods=["GET", "POST"])
def nueva():
    return _formulario(None)


@fisca_esc_bp.route("/escalas/<desde>/editar", methods=["GET", "POST"])
def editar(desde):
    return _formulario(periodo_de(desde))


@fisca_esc_bp.route("/escalas/<desde>/eliminar", methods=["POST"])
def eliminar(desde):
    salida = _guardia()
    if salida:
        return salida
    d = periodo_de(desde)
    conn = get_connection()
    try:
        conn.begin()
        with conn.cursor() as cur:
            cur.execute("""SELECT MAX(origen) AS o, MAX(periodo_hasta) AS h, SUM(periodo_hasta IS NULL) AS abierta, COUNT(*) AS n
                             FROM fisca_escala_salarial WHERE periodo_desde = %s""", (d,))
            r = cur.fetchone()
            if not r["n"] or r["o"] != "manual":
                conn.rollback()
                flash("!Esa escala no existe o vino de AEDA: las de AEDA no se borran acá.")
                return redirect(url_for("fisca_esc.lista", ver=d))
            cur.execute("DELETE FROM fisca_escala_salarial WHERE periodo_desde = %s AND origen = 'manual'", (d,))
            ant = anterior_a(cur, d)
            if ant:
                # La anterior vuelve a cubrir lo que cubría la borrada.
                cur.execute("""UPDATE fisca_escala_salarial SET periodo_hasta = %s
                                WHERE periodo_desde = %s AND periodo_hasta = %s""",
                            (None if r["abierta"] else r["h"], ant, mes_anterior(d)))
        conn.commit()
    finally:
        conn.close()
    flash(f"Escala desde {periodo_txt(d)} borrada." + (f" La de {periodo_txt(ant)} cubre ahora sus meses." if ant else ""))
    return redirect(url_for("fisca_esc.lista"))
