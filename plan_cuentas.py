"""
plan_cuentas.py — Reglas del plan de cuentas (c_plan_de_cuentas), sin Flask.

Las usan la pantalla (contabilidad.py) y los importadores de AEDA. El código
manda: de él salen la clase, el nivel, la cuenta madre, si es imputable y si es
corriente. Así la jerarquía no se puede desarmar a mano, y crear una cuenta
título que faltaba (AEDA no tiene 5-2-0-00-000 ni 5-3-0-00-000) acomoda sola a
las que le corresponden.

Formato del código: tramos de dígitos con un separador, como los de AEDA
(1-1-1-02-020, máscara 9-9-9-99-999). La máscara sale de las cuentas que ya
están; con el plan vacío, la de AEDA.

Diferencias con gestion_adm (contable.py):
- Nivel = posición del último tramo distinto de cero. En gestion_adm se
  contaban los tramos distintos de cero desde la izquierda hasta el primer
  cero, y como el plan usa ceros en el medio (4-1-0-01-050), una cuenta
  imputable quedaba en nivel 2.
- La cuenta madre no se elige: es la más cercana que existe recortando el
  código (poniendo en cero el último tramo, después el anterior…).
- Imputable = el último tramo no es cero. Es la regla de gestion_adm
  (`_es_imputable`) y la que cumple todo el plan de AEDA salvo una cuenta.
"""

from __future__ import annotations

import re
from collections import Counter

MASCARA_AEDA = "9-9-9-99-999"

#: Dónde se usa una cuenta del plan: (tabla, columna, cómo se lee en pantalla).
#: c_rubros_de_pasivo guarda el id como texto.
USOS = [
    ("c_concepto_de_gastos", "c_plan_de_cuentasId", "conceptos de gasto"),
    ("c_motivos_de_ingreso", "c_plan_de_cuentasId", "motivos de ingreso"),
    ("c_cuentas_de_fondos", "c_plan_de_cuentasId", "cuentas de fondos"),
    ("c_rubros_de_pasivo", "c_plan_de_cuentasId", "rubros de pasivo"),
    ("c_rubros_de_activo", "c_plan_de_cuentasId", "rubros de activo"),
    ("pago_imputaciones_config", "id_cuenta_debe", "imputaciones de pago"),
    ("pago_imputaciones_config", "id_cuenta_haber", "imputaciones de pago"),
    ("c_concepto_de_facturacion", "c_plan_de_cuentasid", "conceptos de facturación"),
    ("c_pago_sueldos_imputaciones", "id_cuenta", "imputaciones de sueldos"),
    ("c_asientos_automaticos_lineas", "id_cuenta", "asientos automáticos"),
    ("c_asientos_automaticos_lineas", "id_cuenta_base", "asientos automáticos"),
    ("c_asiento_detalle", "id_cuenta", "renglones de asientos"),
    ("c_balance_general", "id_cuenta", "balances generados"),
    ("c_balance_sumas_saldos", "id_cuenta", "balances generados"),
    ("c_estado_resultados", "id_cuenta", "balances generados"),
    ("c_estado_resultados", "id_cuenta_rubro", "balances generados"),
]
#: Los que impiden cambiarle el código o desactivarla: lo que imputa hoy.
USOS_VIVOS = {"conceptos de gasto", "motivos de ingreso", "cuentas de fondos", "rubros de pasivo",
              "rubros de activo", "imputaciones de pago", "conceptos de facturación",
              "imputaciones de sueldos", "asientos automáticos"}


# ─────────────────────────────────────────────────────────────────────────────
# Código
# ─────────────────────────────────────────────────────────────────────────────

def _forma(codigo: str) -> str:
    return re.sub(r"\d", "9", codigo)


def mascara(codigos) -> str:
    """La forma más usada entre los códigos que ya están; sin códigos, la de AEDA."""
    formas = Counter(_forma(c) for c in codigos if c)
    return formas.most_common(1)[0][0] if formas else MASCARA_AEDA


def separador(masc: str) -> str:
    return next((ch for ch in masc if ch != "9"), "-")


def normalizar_codigo(texto: str, masc: str) -> str:
    """Acepta el código con otro separador o sin ceros a la izquierda en cada
    tramo («5.3.0.0.14» → «5-3-0-00-014») si la cantidad de tramos coincide."""
    t = (texto or "").strip()
    sep = separador(masc)
    tramos = re.split(r"[^\d]+", t)
    tramos = [x for x in tramos if x != ""]
    largos = [len(x) for x in masc.split(sep)]
    if len(tramos) != len(largos) or any(len(x) > n for x, n in zip(tramos, largos)):
        return t
    return sep.join(x.zfill(n) for x, n in zip(tramos, largos))


def error_codigo(codigo: str, masc: str) -> str | None:
    if not codigo:
        return "El código es obligatorio."
    if _forma(codigo) != masc:
        return f"El código tiene que tener la forma {masc} (por ejemplo {masc.replace('9', '0').replace('0', '1', 1)})."
    if int(codigo.split(separador(masc))[0]) == 0:
        return "El primer tramo dice la clase (1 activo … 5 egresos): no puede ser cero."
    return None


def tramos(codigo: str) -> list[str]:
    return re.split(r"[^\d]", codigo)


def nivel(codigo: str) -> int:
    """Posición del último tramo distinto de cero (1-0-0-00-000 → 1, 5-3-0-00-014 → 5)."""
    n = 1
    for i, t in enumerate(tramos(codigo)):
        if t.isdigit() and int(t):
            n = i + 1
    return n


def imputable(codigo: str) -> bool:
    ultimo = tramos(codigo)[-1]
    return ultimo.isdigit() and int(ultimo) != 0


def corriente(codigo: str) -> int:
    """1-2 y 2-2 son no corrientes; el resto, corriente (en resultados no importa)."""
    t = tramos(codigo)
    return 0 if t[0] in ("1", "2") and len(t) > 1 and t[1] == "2" else 1


def monetaria(codigo: str) -> int:
    """Sugerencia: disponibilidades, inversiones y créditos (1-1, salvo bienes de
    cambio 1-1-5) y todo el pasivo. Se cambia en la ficha."""
    t = tramos(codigo)
    return 1 if (t[0] == "1" and t[1:2] == ["1"] and t[2:3] != ["5"]) or t[0] == "2" else 0


def ancestros(codigo: str) -> list[str]:
    """Los códigos de las madres posibles, de la más cercana a la raíz."""
    sep = next((ch for ch in codigo if not ch.isdigit()), "-")
    t = tramos(codigo)
    n = nivel(codigo)
    out = []
    for k in range(n - 1, 0, -1):
        out.append(sep.join(x if i < k else "0" * len(x) for i, x in enumerate(t)))
    return out


def madre(codigo: str, existentes) -> str | None:
    for c in ancestros(codigo):
        if c in existentes and c != codigo:
            return c
    return None


def faltantes(codigo: str, existentes) -> list[str]:
    """Las madres que faltan entre la cuenta y la que existe más cerca."""
    out = []
    for c in ancestros(codigo):
        if c in existentes:
            break
        out.append(c)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Base
# ─────────────────────────────────────────────────────────────────────────────

def mascara_actual(cur) -> str:
    cur.execute("SELECT codigo FROM c_plan_de_cuentas")
    return mascara([f["codigo"] for f in cur.fetchall()])


def rearmar_jerarquia(cur) -> int:
    """Madre y nivel de todas las cuentas, según el código. Devuelve cuántas
    cambiaron. Se llama después de cada alta, cambio de código o baja."""
    cur.execute("SELECT id_cuenta, codigo, id_cuenta_padre, nivel FROM c_plan_de_cuentas")
    filas = cur.fetchall()
    por_codigo = {f["codigo"]: f["id_cuenta"] for f in filas}
    cambios = 0
    for f in filas:
        m = madre(f["codigo"], por_codigo)
        id_madre = por_codigo.get(m) if m else None
        n = nivel(f["codigo"])
        if f["id_cuenta_padre"] != id_madre or f["nivel"] != n:
            cur.execute("UPDATE c_plan_de_cuentas SET id_cuenta_padre = %s, nivel = %s WHERE id_cuenta = %s",
                        (id_madre, n, f["id_cuenta"]))
            cambios += 1
    return cambios


def usos(cur) -> dict:
    """id_cuenta → {texto: cantidad}: dónde se usa cada cuenta."""
    out: dict = {}
    for tabla, col, texto in USOS:
        cur.execute(f"SELECT {col} AS id, COUNT(*) AS n FROM {tabla} WHERE {col} IS NOT NULL GROUP BY {col}")
        for f in cur.fetchall():
            v = str(f["id"]).strip()
            if v.isdigit():
                d = out.setdefault(int(v), {})
                d[texto] = d.get(texto, 0) + f["n"]
    return out


def describir_usos(u: dict) -> str:
    return ", ".join(f"{n} {t}" for t, n in u.items())
