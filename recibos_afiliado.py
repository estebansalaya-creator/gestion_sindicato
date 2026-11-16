"""
recibos_afiliado.py — El recibo al afiliado por la cuota social (YMCA).

Pedido del 15/11/2026. Las transferencias de importe fijo que hacen los
afiliados no son cuota sindical: es la cuota social de la YMCA ($ 25.000 por mes
hasta agosto de 2026, $ 30.000 desde septiembre; el doble paga dos meses). AEDA
las registraba juntas, en una orden de ingreso por cuenta y por mes con el
concepto «YMCA» (adm_ordIngre, concepto 148; vinieron con importar_aeda_tesoreria
con el motivo de ingreso YMCA). Acá cada transferencia lleva su recibo al
afiliado (decidido el 15/11/2026):

  · Es una orden de ingreso de clase «afiliado» con el CUIL del afiliado
    (`ingreso_ordenes.cuil_afiliado`), numerada en su propio talonario
    (Recibos Afiliados, X 0003), con un renglón por mes que paga, el motivo de
    ingreso de Datos del Sindicato (YMCA) y el renglón del extracto. Va al libro
    de fondos y, si la conciliación de la cuenta está abierta, queda conciliada
    en el acto, igual que el recibo de cuota sindical.
  · El MES es el de la acreditación (como AEDA: «CUOTA SOCIAL JUNIO» para lo
    acreditado en junio). Una transferencia que es justo N cuotas (el importe por
    mes de Datos del Sindicato) paga N meses desde ese; otra cualquiera, un solo
    renglón por todo, y no sale en lote: se revisa al emitirla de a uno.
  · Lo que AEDA ya registró no se vuelve a emitir: una acreditación de un mes
    para el que AEDA cargó su orden YMCA en esa cuenta (con fecha igual o
    posterior) se ve como «Ya tiene recibo», con esa orden.

Se emite desde Fiscalización → Emisión de Recibos (fisca_recibos.py), de a uno
o en lote; se ve en la solapa «Cuota social» del afiliado y en Tesorería →
Recibos Emitidos; se anula en Tesorería → Anulaciones.

Sin sql/recibos_afiliados_20261115.sql (`config` → None) las transferencias de
afiliados quedan como «Otro ingreso», como antes.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import movimientos_fondos as mf
import recibos_talonario as RT
from numeracion import proximo_numero

SQL_ESQUEMA = "sql/recibos_afiliados_20261115.sql"
CENT = Decimal("0.01")
#: Una transferencia paga a lo sumo un año de cuotas.
MAX_MESES = 12


class ErrorReciboAfiliado(ValueError):
    """Un error que se muestra tal cual."""


def _d(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(CENT)


def _pesos(v) -> str:
    entero, _, dec = f"{_d(v):,.2f}".partition(".")
    return f"$ {entero.replace(',', '.')},{dec}"


def periodo_txt(p: str | None) -> str:
    return f"{p[:4]}-{p[4:]}" if p and len(p) == 6 else (p or "")


def sumar_meses(periodo: str, n: int) -> str:
    m = int(periodo[:4]) * 12 + int(periodo[4:]) - 1 + n
    return f"{m // 12:04d}{m % 12 + 1:02d}"


def hay_esquema(cur) -> bool:
    cur.execute("""SELECT COUNT(*) AS n FROM information_schema.columns WHERE table_schema = DATABASE()
                     AND ((table_name = 'ingreso_ordenes' AND column_name = 'cuil_afiliado')
                       OR (table_name = 's_institucion' AND column_name = 'recibo_afiliado_cuota'))""")
    return int(cur.fetchone()["n"] or 0) == 2


def config(cur) -> dict | None:
    """Lo de Datos del Sindicato: talonario, motivo (y su texto), concepto y
    cuota por mes. None si falta el script."""
    if not hay_esquema(cur):
        return None
    cur.execute("""SELECT i.talonario_recibo_afiliado AS talonario, i.recibo_afiliado_motivo AS motivo,
                          i.recibo_afiliado_concepto AS concepto, i.recibo_afiliado_cuota AS cuota,
                          m.descripcion AS motivo_txt
                     FROM s_institucion i LEFT JOIN c_motivos_de_ingreso m ON m.id = i.recibo_afiliado_motivo
                    WHERE i.id = 1""")
    c = dict(cur.fetchone() or {})
    c["concepto"] = (c.get("concepto") or c.get("motivo_txt") or "Cuota social").strip()
    c["cuota"] = _d(c["cuota"]) if c.get("cuota") else None
    return c


def meses_justos(importe, cuota) -> int:
    """Cuántas cuotas justas es el importe (0 si no es un múltiplo, de 1 a 12)."""
    imp, cuota = _d(importe), _d(cuota) if cuota else Decimal("0")
    if cuota <= 0 or imp <= 0:
        return 0
    n = imp / cuota
    return int(n) if n == n.to_integral_value() and 1 <= n <= MAX_MESES else 0


def periodos(importe, fecha: datetime.date, cuota) -> list[tuple[str, Decimal]]:
    """Los meses que paga una transferencia: N cuotas justas, N meses desde el
    de la acreditación; si no, un renglón por todo en ese mes."""
    mes = fecha.strftime("%Y%m")
    n = meses_justos(importe, cuota)
    if n:
        return [(sumar_meses(mes, i), _d(cuota)) for i in range(n)]
    return [(mes, _d(importe))]


def afiliado(cur, cuil: str) -> dict | None:
    cur.execute("""SELECT id_afiliado, cuil, apellido_nombres, activo FROM p_afiliados WHERE cuil = %s
                    ORDER BY activo DESC, id_afiliado LIMIT 1""", (cuil,))
    return cur.fetchone()


def ordenes_aeda(cur, id_cuenta: int, motivo: int | None, desde: datetime.date, hasta: datetime.date) -> list[dict]:
    """Las órdenes agrupadas que AEDA cargó con el motivo de los recibos a
    afiliados (YMCA) en esa cuenta, del mes de `desde` al de `hasta`."""
    if not motivo:
        return []
    ini = desde.replace(day=1)
    fin = (hasta.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
    cur.execute("""SELECT o.id AS id_orden, o.nro_orden, o.fecha, o.importe_total
                     FROM ingreso_ordenes o
                    WHERE o.nro_orden LIKE 'AEDA-%%' AND o.estado <> 'anulado' AND o.fecha BETWEEN %s AND %s
                      AND (o.id_cuenta = %s OR EXISTS (SELECT 1 FROM ingreso_ordenes_cuentas c
                                                         WHERE c.id_orden = o.id AND c.id_cuenta_fondos = %s))
                      AND EXISTS (SELECT 1 FROM ingreso_ordenes_detalle d
                                   WHERE d.id_orden = o.id AND d.id_motivo_ingreso = %s)
                    ORDER BY o.fecha, o.id""", (ini, fin, id_cuenta, id_cuenta, motivo))
    return cur.fetchall()


def cubierta(fecha: datetime.date, ordenes: list[dict]) -> dict | None:
    """La orden de AEDA que ya registró una acreditación: la primera del mismo
    mes con fecha igual o posterior."""
    return next((o for o in ordenes if o["fecha"].year == fecha.year and o["fecha"].month == fecha.month
                 and o["fecha"] >= fecha), None)


def leer_renglones(form, hoy: datetime.date | None = None) -> tuple[list[tuple[str, Decimal]], list[str]]:
    """Los meses y los importes del formulario (r_periodo, r_importe)."""
    from pagos_datos import leer_importe
    errores, out, vistos = [], [], set()
    for i, (per, imp) in enumerate(zip(form.getlist("r_periodo"), form.getlist("r_importe")), 1):
        if not (per.strip() or imp.strip()):
            continue
        p = per.strip().replace("-", "")
        p = p if len(p) == 6 and p.isdigit() and 1 <= int(p[4:]) <= 12 else None
        v = leer_importe(imp)
        if not p:
            errores.append(f"Renglón {i}: el mes no es válido.")
        if not v or v <= 0:
            errores.append(f"Renglón {i}: el importe tiene que ser mayor que cero.")
        if p and p in vistos:
            errores.append(f"El mes {periodo_txt(p)} está dos veces: sumá los importes en un renglón.")
        if p:
            vistos.add(p)
        out.append((p, _d(v)))
    if not out:
        errores.append("Cargá al menos un mes.")
    return out, errores


def emitir(cur, extracto: dict, cuil: str, renglones: list[tuple[str, Decimal]], uid, cfg: dict,
           observaciones: str | None = None, fecha_valida=None) -> dict:
    """Emite el recibo al afiliado de una acreditación. `extracto`: el renglón
    del extracto ya bloqueado y validado (fisca_recibos._extracto_bloqueado).
    Con el cursor de una transacción: si algo falla, no queda nada."""
    e = extracto
    if not cfg or not cfg.get("motivo"):
        raise ErrorReciboAfiliado("Falta elegir el motivo de ingreso de los recibos a afiliados en Datos del Sindicato.")
    a = afiliado(cur, cuil)
    if not a:
        raise ErrorReciboAfiliado(f"El CUIL {cuil or '—'} no está en el padrón.")
    total = _d(e["credito"])
    mes = e["fecham"].strftime("%Y%m")
    tope = sumar_meses(mes, MAX_MESES - 1)
    for p, imp in renglones:
        if not p:
            raise ErrorReciboAfiliado("Hay un mes que no es válido.")
        if p > tope:
            raise ErrorReciboAfiliado(f"El mes {periodo_txt(p)} está a más de un año de la acreditación.")
        if imp <= 0:
            raise ErrorReciboAfiliado("Hay un importe en cero.")
    if len({p for p, _ in renglones}) != len(renglones):
        raise ErrorReciboAfiliado("Hay un mes repetido.")
    suma = sum((imp for _, imp in renglones), Decimal("0"))
    if abs(suma - total) >= CENT:
        raise ErrorReciboAfiliado(f"Los meses suman {_pesos(suma)} y la acreditación es de {_pesos(total)}: "
                                  "tienen que dar lo mismo.")
    if fecha_valida:
        error = fecha_valida(cur, e["fecham"])
        if error:
            raise ErrorReciboAfiliado(error)
    nombre = (a["apellido_nombres"] or "").strip()

    talon = RT.reservar(cur, "afiliado")
    nro_orden = proximo_numero(cur, "ingreso_ordenes", e["fecham"])
    obs = " · ".join(x for x in (
        f"Recibo de {cfg['concepto'].lower()} a {nombre} (CUIL {cuil}) desde el extracto de {e['cuenta']}",
        f"acreditación del {e['fecham']:%d/%m/%Y}", f"ref. {e['ref_nro']}" if e.get("ref_nro") else None,
        (e.get("concepto") or "").strip() or None, observaciones) if x)[:2000]
    cur.execute("""INSERT INTO ingreso_ordenes (nro_orden, id_talonario, nro_recibo, clase, anio, fecha, estado, id_cuenta,
                                                importe_total, moneda, origen, cuil_afiliado, observaciones,
                                                id_usuario_creacion)
                   VALUES (%s, %s, %s, 'afiliado', %s, %s, 'confirmado', %s, %s, 'ARS', 'extracto', %s, %s, %s)""",
                (nro_orden, talon["id"], talon["nro"], e["fecham"].year, e["fecham"], e["c_cuentas_de_fondos_id"], total,
                 cuil, obs, uid))
    id_orden = cur.lastrowid
    for p, imp in sorted(renglones):
        cur.execute("""INSERT INTO ingreso_ordenes_detalle (id_orden, tipo, id_motivo_ingreso, descripcion, importe,
                                                            moneda, periodo, cuit, id_extracto_origen)
                       VALUES (%s, 'ingreso', %s, %s, %s, 'ARS', %s, NULL, %s)""",
                    (id_orden, cfg["motivo"], f"{cfg['concepto']} {periodo_txt(p)} · {nombre} (CUIL {cuil})"[:200],
                     imp, p, e["id"]))
    cur.execute("INSERT INTO ingreso_ordenes_cuentas (id_orden, id_cuenta_fondos, importe) VALUES (%s, %s, %s)",
                (id_orden, e["c_cuentas_de_fondos_id"], total))
    mf.registrar_ingreso(cur, id_orden)
    import fisca_recibo_acta as FRA      # acá: arriba armaría un ciclo con afiliados (conciliación → tesorería)
    conciliado = FRA.conciliar_en_el_acto(cur, e["c_cuentas_de_fondos_id"], e["fecham"], id_orden, total, e["id"],
                                          cfg["motivo"], uid)
    return {"id_orden": id_orden, "nro": talon["texto"], "nro_orden": nro_orden, "conciliado": conciliado,
            "razon": nombre, "total": total}


def concepto_de(detalle: list[dict]) -> str | None:
    """El concepto con que se emitió («Cuota social YMCA»): lo que va antes del
    mes en la descripción del renglón. Así un cambio en Datos del Sindicato no
    cambia lo que dicen los recibos ya emitidos."""
    for d in detalle:
        mes = periodo_txt(d.get("periodo"))
        texto = d.get("descripcion") or ""
        if mes and f" {mes}" in texto:
            return texto.split(f" {mes}")[0].strip() or None
    return None


def del_afiliado(cur, cuil: str) -> list[dict]:
    """Los recibos al afiliado (todos sus CUIL del padrón comparten uno), para
    su solapa: el más nuevo primero, con los meses que paga."""
    if not cuil or not hay_esquema(cur):
        return []
    cur.execute(f"""SELECT o.id, o.fecha, o.estado, o.importe_total, o.nro_orden, o.motivo_anulacion,
                           {RT.sql_texto('o', 't')} AS numero, cf.nombre AS cuenta,
                           (SELECT GROUP_CONCAT(d.periodo ORDER BY d.periodo SEPARATOR ',')
                              FROM ingreso_ordenes_detalle d WHERE d.id_orden = o.id) AS periodos,
                           (SELECT m.descripcion FROM ingreso_ordenes_detalle d
                              JOIN c_motivos_de_ingreso m ON m.id = d.id_motivo_ingreso
                             WHERE d.id_orden = o.id LIMIT 1) AS motivo
                      FROM ingreso_ordenes o
                      LEFT JOIN c_talonario t ON t.id = o.id_talonario
                      LEFT JOIN c_cuentas_de_fondos cf ON cf.id = o.id_cuenta
                     WHERE o.clase = 'afiliado' AND o.cuil_afiliado = %s
                     ORDER BY o.fecha DESC, o.id DESC""", (cuil,))
    filas = cur.fetchall()
    for f in filas:
        f["meses"] = [periodo_txt(p) for p in (f["periodos"] or "").split(",") if p]
    return filas


def transferencias_sin_recibo(cur, cuil: str, cfg: dict | None) -> list[dict]:
    """Las acreditaciones del extracto que hizo el afiliado y no tienen recibo
    vigente, con lo que AEDA ya registró en su orden del mes («aeda»)."""
    if not cuil or not cfg:
        return []
    cur.execute("""SELECT e.id, e.fecham, e.credito, e.ref_nro, e.concepto, e.c_cuentas_de_fondos_id AS id_cuenta,
                          cf.nombre AS cuenta
                     FROM c_extractos_bancarios e
                     JOIN c_cuentas_de_fondos cf ON cf.id = e.c_cuentas_de_fondos_id
                    WHERE e.cuit = %s AND e.credito > 0
                      AND NOT EXISTS (SELECT 1 FROM ingreso_ordenes_detalle d JOIN ingreso_ordenes o ON o.id = d.id_orden
                                       WHERE d.id_extracto_origen = e.id AND o.estado <> 'anulado')
                    ORDER BY e.fecham DESC, e.id DESC LIMIT 200""", (cuil,))
    filas = cur.fetchall()
    por_cuenta: dict[int, list] = {}
    for f in filas:
        por_cuenta.setdefault(f["id_cuenta"], []).append(f)
    for id_cuenta, lista in por_cuenta.items():
        ordenes = ordenes_aeda(cur, id_cuenta, cfg.get("motivo"), min(x["fecham"] for x in lista),
                               max(x["fecham"] for x in lista))
        for f in lista:
            f["aeda"] = cubierta(f["fecham"], ordenes)
            f["justas"] = meses_justos(f["credito"], cfg.get("cuota"))
    return filas
