"""
afiliado_aportes.py — La solapa «Aportes OSEDA» de la ficha del afiliado.

Es la solapa Aportes del Análisis de afiliado de gestion_adm
(`afiliado_analisis._aportes` + `padron._fila_diferencia`) sobre las DDJJ de
OSEDA que esta app lee en vivo de contable en Railway (contable_oseda.py, solo
lectura): por período, lo declarado en la DDJJ contra lo que ARCA transfirió,
más el pago de monotributo, y la diferencia. Le agrega lo del gremio: la
Remuneración imponible 5 (la base de la cuota sindical) y la cuota que se le
liquidó al afiliado en ese período (`fisca_liquidacion_detalle`).

**Solo para quien tiene o tuvo DDJJ de OSEDA** (pedido del 15/11/2026): si
nadie del grupo familiar figura en una DDJJ, `solapa()` devuelve None y la
ficha no muestra la solapa. La ficha la pide aparte, cuando ya está dibujada
(`/afiliados/<id>/aportes`): así abrir o guardar una ficha no espera a Railway
ni depende de que responda.

Como en OSEDA:

- **Los aportes son del titular.** La DDJJ se presenta a nombre de quien
  trabaja: un familiar a cargo no tiene filas propias, así que su ficha muestra
  las del titular del grupo. Si un integrante aporta a su nombre (trabaja en
  relación de dependencia o es monotributista), va en su propia grilla.
- **Últimos 36 períodos** con algo (DDJJ o transferencia) de ese CUIL; desde
  cuándo lo declaran sale de toda la historia de la DDJJ.
- **La diferencia sale del empleador, no del prorrateo por CUIL**
  (`fila_diferencia`). Hasta $ 1,50 por período es redondeo.
"""

from decimal import Decimal

import contable_oseda

#: Hasta un peso y medio por período es redondeo del prorrateo de ARCA, no
#: deuda (padron.TOLERANCIA_APORTES de gestion_adm).
TOLERANCIA = Decimal("1.50")

#: Períodos que muestra cada grilla, como el Análisis de afiliado de OSEDA.
LIMITE = 36

#: Los importes de un renglón (empleador + período) que se suman por período.
CAMPOS = ("remuneracion", "rem5", "aporte_decl", "contrib_decl", "total_a_pagar",
          "aporte_perc", "contrib_perc", "monotributo", "total_percibido",
          "total_pagado", "diferencia", "cuota")

CERO = Decimal("0")


def _d(v) -> Decimal:
    try:
        return Decimal(str(v)) if v is not None else CERO
    except (ArithmeticError, ValueError):
        return CERO


def _cuit(v) -> str:
    return "".join(c for c in str(v or "") if c.isdigit()).zfill(11)


def fila_diferencia(r: dict) -> dict:
    """
    Total a pagar, total pagado y diferencia de UN renglón (empleador + período).
    Es `padron._fila_diferencia` de gestion_adm, con Decimal.

    ARCA paga al empleador entero y después reparte lo transferido entre sus
    CUIL con otra base (las contribuciones y las retenciones se prorratean), así
    que comparar lo declarado del afiliado contra lo prorrateado muestra «deuda»
    o «a favor» que no existen. Cuando `f_deuda_empresa` tiene al empleador en el
    período (`emp_decl` = lo declarado por toda la nómina, `emp_deuda` = lo que
    quedó sin pagar), la deuda del afiliado es SU PARTE de la del empleador:

        diferencia = a pagar del afiliado × deuda del empleador / declarado del empleador

    y si el empleador no debe, el afiliado tampoco. El pagado es a pagar −
    diferencia; lo que ARCA prorrateó queda en `total_percibido`. Sin el
    empleador en `f_deuda_empresa` se compara contra lo prorrateado.
    """
    r["total_a_pagar"] = _d(r.get("aporte_decl")) + _d(r.get("contrib_decl"))
    emp_decl = _d(r.get("emp_decl"))
    if r.get("emp_decl") is not None and emp_decl > 0:
        deuda_emp = _d(r.get("emp_deuda"))
        if deuda_emp <= TOLERANCIA:
            dif = CERO
        else:
            dif = (r["total_a_pagar"] * min(Decimal(1), deuda_emp / emp_decl)).quantize(Decimal("0.01"))
        r["diferencia"] = CERO if abs(dif) <= TOLERANCIA else dif
        r["total_pagado"] = r["total_a_pagar"] - r["diferencia"]
    else:
        r["total_pagado"] = _d(r.get("total_percibido"))
        dif = r["total_a_pagar"] - r["total_pagado"]
        r["diferencia"] = CERO if abs(dif) <= TOLERANCIA else dif
    return r


def aportes(cuil: str, datos: dict, cuotas: dict, empresas: dict, limite: int = LIMITE) -> dict:
    """
    La grilla de un CUIL: un renglón por período (los empleadores del período
    sumados) con los últimos `limite` períodos, y sus totales.

    `datos` es lo de contable_oseda.aportes_de_cuiles; `cuotas`,
    {(cuil, cuit, periodo): cuota liquidada}; `empresas`, {cuit: razón social}.
    """
    cuil = str(cuil or "")
    salida = {"cuil": cuil, "detalle": [], "totales": {"periodos": 0}}
    if not cuil:
        return salida

    renglones: dict[tuple, dict] = {}

    def renglon(f):
        clave = (_cuit(f["cuit"]), str(f["periodo"]))
        return renglones.setdefault(clave, {"cuit": clave[0], "periodo": clave[1]})

    periodos_ddjj = []
    for f in datos.get("ddjj") or []:
        if str(f["cuil"]) != cuil:
            continue
        periodos_ddjj.append(str(f["periodo"]))
        r = renglon(f)
        r["remuneracion"] = _d(f.get("remosimp"))
        r["rem5"] = _d(f.get("rem5"))
        r["aporte_decl"] = _d(f.get("aporte_decl"))
        r["contrib_decl"] = _d(f.get("contrib_decl"))
    for f in datos.get("transferencias") or []:
        if str(f["cuil"]) != cuil:
            continue
        r = renglon(f)
        for c in ("aporte_perc", "contrib_perc", "total_percibido", "monotributo"):
            r[c] = _d(f.get(c))
    if not renglones:
        return salida

    ultimos = sorted({p for _, p in renglones}, reverse=True)[:limite]
    deuda = datos.get("deuda_empresa") or {}
    por_periodo: dict[str, dict] = {}
    for (cuit, per), r in sorted(renglones.items(), key=lambda x: (x[0][1], x[0][0]), reverse=True):
        if per not in ultimos:
            continue
        emp = deuda.get((cuit, per)) or {}
        r["emp_decl"], r["emp_deuda"] = emp.get("emp_decl"), emp.get("emp_deuda")
        fila_diferencia(r)
        cuota = cuotas.get((cuil, cuit, per))
        r["cuota"] = _d(cuota)
        p = por_periodo.get(per)
        if p is None:
            p = por_periodo[per] = {"periodo": per, "empleadores_det": [], **{c: CERO for c in CAMPOS}}
        for c in CAMPOS:
            p[c] += _d(r.get(c))
        p["empleadores_det"].append({"cuit": cuit, "razon_social": empresas.get(cuit) or "",
                                     "liquidada": cuota is not None})

    detalle = [por_periodo[p] for p in ultimos if p in por_periodo]
    tot = {c: sum((r[c] for r in detalle), CERO) for c in CAMPOS}
    tot["periodos"] = len(detalle)
    tot["ultimo"] = detalle[0]["periodo"] if detalle else None
    tot["primero"] = detalle[-1]["periodo"] if detalle else None
    # Cómo aporta: con DDJJ es relación de dependencia; sin DDJJ y con pago de
    # monotributo, monotributista. Puede ser las dos cosas.
    tipos = []
    if any(r["aporte_decl"] or r["contrib_decl"] or r["aporte_perc"] or r["contrib_perc"] for r in detalle):
        tipos.append("Relación de dependencia")
    if any(r["monotributo"] for r in detalle):
        tipos.append("Monotributo")
    tot["tipo"] = " y ".join(tipos)
    # Desde cuándo lo declaran: toda la historia, no solo los 36 de la grilla.
    tot["ddjj_desde"] = min(periodos_ddjj) if periodos_ddjj else None
    tot["ddjj_hasta"] = max(periodos_ddjj) if periodos_ddjj else None
    tot["ddjj_periodos"] = len(set(periodos_ddjj))
    salida.update(detalle=detalle, totales=tot)
    return salida


def _cuotas(cur, cuiles) -> dict:
    """La cuota sindical liquidada a cada CUIL, por empleador y período, de
    las liquidaciones vigentes: {(cuil, cuit, periodo): cuota}."""
    cuiles = sorted({str(c) for c in cuiles if c})
    if not cuiles:
        return {}
    marcas = ",".join(["%s"] * len(cuiles))
    cur.execute(f"""SELECT d.cuil, l.cuit, l.periodo, SUM(d.cuota) AS cuota
                      FROM fisca_liquidacion_detalle d
                      JOIN fisca_liquidacion l ON l.id = d.id_liquidacion AND l.estado = 'vigente'
                     WHERE d.cuil IN ({marcas})
                     GROUP BY d.cuil, l.cuit, l.periodo""", cuiles)
    return {(str(f["cuil"]), _cuit(f["cuit"]), str(f["periodo"])): f["cuota"] for f in cur.fetchall()}


def _empresas(cur, cuits) -> dict:
    """Razón social del padrón de empleadores del gremio: {cuit: razón social}."""
    numeros = sorted({int(c) for c in cuits if c and c.isdigit()})
    if not numeros:
        return {}
    marcas = ",".join(["%s"] * len(numeros))
    cur.execute(f"SELECT CUIT, razon_social FROM p_empresas WHERE CUIT IN ({marcas})", numeros)
    return {_cuit(f["CUIT"]): f["razon_social"] for f in cur.fetchall()}


def solapa(cur, af: dict, grupo: list[dict]) -> dict | None:
    """
    Lo que muestra la solapa para la ficha `af` (con `grupo`, los integrantes
    de su grupo familiar), o None si nadie del grupo tiene ni tuvo DDJJ de
    OSEDA. `cur` es de la base del sindicato. Si Railway no responde, sale
    ContableNoDisponible: lo maneja quien llama.

        titular    la grilla del titular del grupo (la principal)
        propio     la del consultado, si es familiar y aporta a su nombre
        otros      las de los demás integrantes que aportan a su nombre
        conteo     períodos de todas las grillas (el número de la solapa)
    """
    cuil = str(af.get("cuil") or "")
    cuil_tit = str(af.get("cuil_titular") or "") or cuil
    personas = [p for p in grupo if p.get("cuil")]
    if cuil and not any(str(p["cuil"]) == cuil for p in personas):
        personas.append(af)
    cuiles = list(dict.fromkeys(c for c in [cuil_tit, cuil] + [str(p["cuil"]) for p in personas] if c))
    if not cuiles:
        return None

    datos = contable_oseda.aportes_de_cuiles(cuiles)
    if not datos["ddjj"]:
        return None

    cuits = {_cuit(f["cuit"]) for f in datos["ddjj"] + datos["transferencias"]}
    # Primero el nombre que tiene el gremio; si no está en su padrón, el de OSEDA.
    empresas = {_cuit(k): v for k, v in (datos.get("empresas") or {}).items()}
    empresas.update(_empresas(cur, cuits))
    cuotas = _cuotas(cur, cuiles)

    titular = aportes(cuil_tit, datos, cuotas, empresas)
    propio, otros = None, []
    for p in personas:
        c = str(p["cuil"])
        if c == cuil_tit:
            continue
        ap = aportes(c, datos, cuotas, empresas)
        if not ap["detalle"]:
            continue
        item = {"cuil": c, "apellido_nombres": p.get("apellido_nombres") or "",
                "parentesco": p.get("parentesco") or "", "activo": p.get("activo"),
                "id_afiliado": p.get("id_afiliado"), "aportes": ap}
        if c == cuil:
            propio = item
        else:
            otros.append(item)

    conteo = (titular["totales"]["periodos"] + (propio["aportes"]["totales"]["periodos"] if propio else 0)
              + sum(o["aportes"]["totales"]["periodos"] for o in otros))
    return {"es_titular": cuil == cuil_tit, "cuil_titular": cuil_tit,
            "titular": titular, "propio": propio, "otros": otros, "conteo": conteo}
