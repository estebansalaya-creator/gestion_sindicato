"""
movimientos_fondos.py — Libro de tesorería (c_movimientos_de_fondos).

Copiado de `gestion_adm/movimientos_fondos.py` sin cambios de lógica.

QUE ES
------
`c_movimientos_de_fondos` tiene un renglón por comprobante y cuenta, con el
total de esa cuenta en ese comprobante. Es de donde sale el saldo de
cualquier cuenta de fondos, venga la plata de donde venga.

Este módulo es la única puerta de escritura. Los circuitos no arman el
renglón a mano: llaman a la función que les corresponde y ésta lo deriva de
los datos que el circuito ya guardó.

    registrar_pago(cur, id_pago)              egreso, desde los instrumentos
    registrar_ingreso(cur, id_orden)          ingreso, desde las cuentas
    registrar_movimiento(cur, id_movimiento)  entre cuentas, desde el detalle
    registrar_cobranza(cur, id_comprobante, cuentas)   recibo

    anular(cur, origen, id_comprobante, motivo, id_usuario)
    reactivar(cur, origen, id_comprobante)

COMO SE USA
-----------
Siempre con el cursor de la transacción que está guardando el comprobante,
nunca con uno propio:

    cur.execute("INSERT INTO pago_pagos …")
    id_pago = cur.lastrowid
    …
    mf.registrar_pago(cur, id_pago)

Si el comprobante se cae, el renglón se cae con él. Un libro que se pueda
desincronizar del comprobante no sirve para nada.

POR QUE DERIVAN EN VEZ DE RECIBIR PARAMETROS
--------------------------------------------
Cada función vuelve a leer el comprobante y rearma sus renglones. Es más
lento que pasarle los importes, y es a propósito: si el circuito calculó mal
la cuenta o el importe, el libro repite el error igual, pero al menos no
agrega uno nuevo. Y hace que llamarla dos veces sea inofensivo, que es lo
que permite usarla también al editar.

ANULACION
---------
No se borra el renglón: se le pone `fecha_anulacion`. La vista
`v_saldos_cuentas_fondos` y todo lo que calcule saldo filtran por ese campo.
Queda el rastro de que el movimiento existió y de cuándo dejó de contar.
"""

from __future__ import annotations

from numeracion import nro_visible

# Orígenes válidos -> columna FK en c_movimientos_de_fondos.
# El CHECK de la tabla exige que exactamente una tenga valor.
COLUMNA_ORIGEN = {
    "pago":       "pago_pagosId",
    "ingreso":    "ingreso_ordenesId",
    "movimiento": "c_movimiento_entre_cuentasId",
    "cobranza":   "c_comprobantes_emitidosId",
}


def _sincronizar(cur, origen: str, id_comprobante: int, renglones: list[dict]):
    """Deja en el libro exactamente los renglones que se le pasan.

    `renglones` es [{cuenta, fecha, debe, haber, concepto}, …], uno por
    cuenta. Los que ya estaban se actualizan, los que faltan se insertan y
    los que dejaron de corresponder se borran.

    El UNIQUE (origen, cuenta) de la tabla es el que hace que esto sea
    seguro de repetir.
    """
    col = COLUMNA_ORIGEN[origen]

    for r in renglones:
        debe  = round(float(r.get("debe")  or 0), 2)
        haber = round(float(r.get("haber") or 0), 2)
        # El CHECK de la tabla exige un solo lado positivo. Un comprobante
        # en cero no es un movimiento de fondos: no se registra.
        if debe <= 0 and haber <= 0:
            continue
        if debe > 0 and haber > 0:
            raise ValueError(
                f"{origen} {id_comprobante}, cuenta {r['cuenta']}: "
                f"no puede tener debe y haber a la vez ({debe} / {haber})")

        cur.execute(f"""
            INSERT INTO c_movimientos_de_fondos
                  (c_cuentas_de_fondosId, fecha, importe_debe, importe_haber,
                   concepto, {col})
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                  fecha         = VALUES(fecha),
                  importe_debe  = VALUES(importe_debe),
                  importe_haber = VALUES(importe_haber),
                  concepto      = VALUES(concepto)
        """, (r["cuenta"], r["fecha"], debe, haber,
              (r.get("concepto") or "")[:200], id_comprobante))

    _sincronizar_banco(cur, origen, id_comprobante)

    # Cuentas que el comprobante dejó de tocar — pasa al editar.
    cuentas = [r["cuenta"] for r in renglones
               if float(r.get("debe") or 0) > 0 or float(r.get("haber") or 0) > 0]
    if cuentas:
        marcas = ",".join(["%s"] * len(cuentas))
        cur.execute(f"""
            DELETE FROM c_movimientos_de_fondos
             WHERE {col} = %s AND c_cuentas_de_fondosId NOT IN ({marcas})
        """, [id_comprobante, *cuentas])
    else:
        cur.execute(f"DELETE FROM c_movimientos_de_fondos WHERE {col} = %s",
                    (id_comprobante,))


def _sincronizar_banco(cur, origen: str, id_comprobante: int):
    """Abre el detalle bancario de los renglones que tocan una cuenta banco.

    `c_debitos_creditos_bancarios` es el lado libro de la conciliación: lo
    que se cruza contra `c_extractos_bancarios`. Va al grano con el que el
    banco informa, que es el instrumento, no el comprobante.

    Un pago de $100.000 con dos cheques es UN renglón en el libro y DOS
    acá: el banco los va a debitar por separado y en fechas distintas.

    El signo se da vuelta a propósito. En el libro `debe` es plata que entra
    a la cuenta; acá se usa la óptica del banco, igual que el extracto, para
    que la conciliación compare columna contra columna sin invertir nada.
    """
    col = COLUMNA_ORIGEN[origen]

    cur.execute(f"""
        SELECT v.id, v.fecha, v.importe_debe, v.importe_haber
        FROM   c_movimientos_de_fondos v
        JOIN   c_cuentas_de_fondos c ON c.id = v.c_cuentas_de_fondosId
                                    AND c.tipo_de_cuenta = 'B'
        WHERE  v.{col} = %s
    """, (id_comprobante,))
    renglones = cur.fetchall()
    if not renglones:
        return

    for v in renglones:
        if origen == "pago":
            # Un registro por instrumento. La referencia lleva el id del
            # instrumento, que es lo que lo hace repetible sin duplicar.
            cur.execute("""
                SELECT i.id, i.tipo_instrumento, i.importe, i.nro_cheque,
                       i.fecha_cheque, i.nro_referencia,
                       q.id AS id_chequera
                FROM   pago_pagos_instrumentos i
                JOIN   c_movimientos_de_fondos v
                       ON v.pago_pagosId = i.id_pago
                      AND v.c_cuentas_de_fondosId = i.id_cuenta_fondos
                LEFT   JOIN c_chequeras q
                       ON q.c_cuentas_de_fondosId = i.id_cuenta_fondos
                      AND i.nro_cheque BETWEEN q.numero_desde AND q.numero_hasta
                WHERE  v.id = %s AND i.importe > 0
            """, (v["id"],))
            # `cheque_numero` es bigint del lado del banco y `nro_cheque` es
            # varchar del lado del instrumento: una cadena vacía pasa por el
            # primero y hace fallar el segundo. Se normaliza acá y no sólo en
            # quien graba el instrumento, porque este registrador también
            # corre sobre pagos ya existentes.
            items = [{
                "tipo":     f["tipo_instrumento"],
                "debito":   f["importe"],
                "credito":  0,
                "cheque":   (f["nro_cheque"] or "").strip() or None,
                "chequera": f["id_chequera"],
                "fecha":    f["fecha_cheque"] or v["fecha"],
                "ref":      f["nro_referencia"] or f"INST-{f['id']}",
            } for f in cur.fetchall()]
        else:
            # Sin detalle de instrumento el movimiento ES el instrumento.
            items = [{
                "tipo":     "deposito" if v["importe_debe"] > 0 else "transferencia",
                "debito":   v["importe_haber"],
                "credito":  v["importe_debe"],
                "cheque":   None,
                "chequera": None,
                "fecha":    v["fecha"],
                "ref":      f"MDF-{v['id']}",
            }]

        for it in items:
            cur.execute("""
                INSERT INTO c_debitos_creditos_bancarios
                      (c_movimientos_de_fondosId, tipo_instrumento,
                       importe_debito, importe_credito, cheque_numero,
                       c_chequerasId, fecha_emision, nro_referencia, estado)
                SELECT %s, %s, %s, %s, %s, %s, %s, %s, 'emitido'
                 WHERE NOT EXISTS (SELECT 1 FROM c_debitos_creditos_bancarios x
                                    WHERE x.nro_referencia = %s)
            """, (v["id"], it["tipo"], it["debito"], it["credito"],
                  it["cheque"], it["chequera"], it["fecha"], it["ref"],
                  it["ref"]))


# ─────────────────────────────────────────────────────────────────────────────
# Un registrador por circuito
# ─────────────────────────────────────────────────────────────────────────────

def registrar_pago(cur, id_pago: int):
    """Egreso. La cuenta y el importe salen de los instrumentos.

    Es el instrumento el que dice de qué cuenta salió la plata, no la orden:
    un pago de $100.000 con $10.000 de retención mueve $90.000 del banco. Lo
    retenido no sale de la cuenta, se paga después a ARCA por su circuito.

    Varios instrumentos sobre la misma cuenta se suman en un solo renglón.
    """
    cur.execute("""
        SELECT p.fecha_pago, p.nro_pago, p.nro_origen, p.estado,
               i.id_cuenta_fondos AS cuenta,
               SUM(i.importe)     AS importe,
               COUNT(*)           AS instrumentos
        FROM   pago_pagos p
        JOIN   pago_pagos_instrumentos i ON i.id_pago = p.id
        WHERE  p.id = %s
        GROUP  BY i.id_cuenta_fondos
    """, (id_pago,))
    filas = cur.fetchall()

    _sincronizar(cur, "pago", id_pago, [{
        "cuenta":   f["cuenta"],
        "fecha":    f["fecha_pago"],
        "debe":     0,
        "haber":    f["importe"],
        # El pago se nombra por su número de origen cuando lo tiene: en los
        # migrados `nro_pago` es el id interno del sistema anterior y nadie
        # los conoce por ese. Ver numeracion.py.
        "concepto": f"Pago {nro_visible(f)}" + (
            f" ({f['instrumentos']} instrumentos)"
            if f["instrumentos"] > 1 else ""),
    } for f in filas])

    if filas and filas[0]["estado"] == "anulado":
        anular(cur, "pago", id_pago, "Pago anulado")


def registrar_ingreso(cur, id_orden: int):
    """Ingreso. Las cuentas salen de `ingreso_ordenes_cuentas`.

    Si no hay renglones de cuenta se usa `ingreso_ordenes.id_cuenta` de la
    cabecera. Ese caso existe porque el alta desde conciliación bancaria
    llenaba solo la cabecera; se corrigió, pero quedan órdenes viejas así y
    conviene que sigan produciendo su renglón.
    """
    cur.execute("""
        SELECT o.fecha, o.nro_orden, o.clase, o.estado, o.importe_total,
               o.id_cuenta,
               c.id_cuenta_fondos AS cuenta,
               SUM(c.importe)     AS importe
        FROM   ingreso_ordenes o
        LEFT   JOIN ingreso_ordenes_cuentas c ON c.id_orden = o.id
        WHERE  o.id = %s
        GROUP  BY c.id_cuenta_fondos
    """, (id_orden,))
    filas = cur.fetchall()
    if not filas:
        return

    cab = filas[0]
    if len(filas) == 1 and cab["cuenta"] is None:
        if not cab["id_cuenta"]:
            return
        renglones = [{"cuenta": cab["id_cuenta"], "importe": cab["importe_total"]}]
    else:
        renglones = [{"cuenta": f["cuenta"], "importe": f["importe"]}
                     for f in filas if f["cuenta"] is not None]

    _sincronizar(cur, "ingreso", id_orden, [{
        "cuenta":   r["cuenta"],
        "fecha":    cab["fecha"],
        "debe":     r["importe"],
        "haber":    0,
        "concepto": f"Ingreso {cab['nro_orden']} ({cab['clase']})",
    } for r in renglones])

    if cab["estado"] == "anulado":
        anular(cur, "ingreso", id_orden, "Orden de ingreso anulada")


def registrar_movimiento(cur, id_movimiento: int):
    """Entre cuentas propias. El detalle ya viene con debe y haber."""
    cur.execute("""
        SELECT m.fecha_emision, m.tipo_movimiento, m.fecha_anulacion,
               d.id_cuenta_fondos AS cuenta,
               SUM(d.debe)  AS debe,
               SUM(d.haber) AS haber
        FROM   c_movimiento_entre_cuentas m
        JOIN   c_movimiento_entre_cuentas_det d ON d.id_movimiento = m.id
        WHERE  m.id = %s
        GROUP  BY d.id_cuenta_fondos
    """, (id_movimiento,))
    filas = cur.fetchall()
    if not filas:
        return

    _sincronizar(cur, "movimiento", id_movimiento, [{
        "cuenta":   f["cuenta"],
        "fecha":    f["fecha_emision"],
        "debe":     f["debe"],
        "haber":    f["haber"],
        "concepto": f["tipo_movimiento"].replace("_", " ").capitalize(),
    } for f in filas])

    if filas[0]["fecha_anulacion"]:
        anular(cur, "movimiento", id_movimiento, "Movimiento anulado")


def registrar_cobranza(cur, id_comprobante: int,
                       cuentas: list[tuple] | None = None):
    """Cobranza por recibo. Las cuentas salen de la cobranza del comprobante.

    `c_comprobantes_emitidos_cobranza` ya tiene un renglón por medio de cobro
    con su cuenta: efectivo a la caja, cheque a valores a depositar,
    transferencia al banco. Se agrupa por cuenta.

    `cuentas` — [(id_cuenta, importe), …] — es para los casos en que el
    comprobante se emite sin ese detalle y el circuito sabe la cuenta por
    otro lado. Los recibos migrados están en esa situación.
    """
    cur.execute("""
        SELECT ce.fecha_emision, ce.anulado, ce.razon_social,
               t.letra, t.punto_de_venta, ce.numero_desde
        FROM   c_comprobantes_emitidos ce
        JOIN   c_talonario t ON t.id = ce.id_talonario
        WHERE  ce.id = %s
    """, (id_comprobante,))
    c = cur.fetchone()
    if not c:
        return

    if cuentas is None:
        # `id_cuenta_fondos` puede venir en NULL: una retención no entra a
        # ninguna cuenta, cancela deuda contra el fisco. Esos renglones no
        # son movimiento de fondos.
        cur.execute("""
            SELECT id_cuenta_fondos AS cuenta, SUM(importe) AS importe
            FROM   c_comprobantes_emitidos_cobranza
            WHERE  id_comprobante = %s AND id_cuenta_fondos IS NOT NULL
            GROUP  BY id_cuenta_fondos
        """, (id_comprobante,))
        cuentas = [(f["cuenta"], f["importe"]) for f in cur.fetchall()]
    if not cuentas:
        return

    etiqueta = (f"Cobranza {c['letra']} "
                f"{str(c['punto_de_venta']).zfill(4)}-"
                f"{str(c['numero_desde']).zfill(8)}")
    if c["razon_social"]:
        etiqueta += f" — {c['razon_social']}"

    _sincronizar(cur, "cobranza", id_comprobante, [{
        "cuenta":   cuenta,
        "fecha":    c["fecha_emision"],
        "debe":     importe,
        "haber":    0,
        "concepto": etiqueta,
    } for cuenta, importe in cuentas])

    if c["anulado"]:
        anular(cur, "cobranza", id_comprobante, "Comprobante anulado")


def registrar_cheques(cur, origen: str, id_comprobante: int, id_cuenta: int,
                      cheques: list[dict]):
    """Reemplaza el detalle bancario genérico por los cheques emitidos.

    `_sincronizar_banco` abre un registro por movimiento cuando no hay
    detalle de instrumento. Para una extracción de caja eso no alcanza: la
    empresa no retira efectivo por ventanilla contra nada, emite cheques, y
    el banco los va a informar de a uno.

    Los datos del sistema anterior lo confirman: las siete extracciones
    migradas se pagaron con varios cheques de $50.000 cada una — una de
    $400.000 salió con ocho. El ETL original se quedaba con el último y
    migraba $50.000 en vez de $400.000.

    `cheques` es [{numero, importe, chequera, a_la_orden, fecha}, …].
    """
    col = COLUMNA_ORIGEN[origen]
    cur.execute(f"""
        SELECT v.id FROM c_movimientos_de_fondos v
         WHERE v.{col} = %s AND v.c_cuentas_de_fondosId = %s
    """, (id_comprobante, id_cuenta))
    fila = cur.fetchone()
    if not fila:
        return
    id_mov_fondos = fila["id"]

    # Fuera el registro genérico que dejó _sincronizar_banco.
    cur.execute("""
        DELETE FROM c_debitos_creditos_bancarios
         WHERE c_movimientos_de_fondosId = %s AND nro_referencia = %s
    """, (id_mov_fondos, f"MDF-{id_mov_fondos}"))

    for ch in cheques:
        cur.execute("""
            INSERT INTO c_debitos_creditos_bancarios
                  (c_movimientos_de_fondosId, tipo_instrumento,
                   importe_debito, importe_credito, cheque_numero,
                   c_chequerasId, fecha_emision, a_la_orden,
                   nro_referencia, estado)
            VALUES (%s, 'cheque', %s, 0, %s, %s, %s, %s, %s, 'emitido')
        """, (id_mov_fondos, ch["importe"], ch["numero"], ch["chequera"],
              ch["fecha"], ch.get("a_la_orden"),
              f"MDF-{id_mov_fondos}-CH{ch['numero']}"))


# ─────────────────────────────────────────────────────────────────────────────
# Anular y reactivar
# ─────────────────────────────────────────────────────────────────────────────

def anular(cur, origen: str, id_comprobante: int,
           motivo: str | None = None, id_usuario: int | None = None):
    """Saca el movimiento del saldo sin borrarlo."""
    col = COLUMNA_ORIGEN[origen]
    cur.execute(f"""
        UPDATE c_movimientos_de_fondos
           SET fecha_anulacion      = COALESCE(fecha_anulacion, NOW()),
               motivo_anulacion     = COALESCE(motivo_anulacion, %s),
               id_usuario_anulacion = COALESCE(id_usuario_anulacion, %s)
         WHERE {col} = %s
    """, (motivo, id_usuario, id_comprobante))


def reactivar(cur, origen: str, id_comprobante: int):
    """Deshace la anulación. Para cuando se anuló por error."""
    col = COLUMNA_ORIGEN[origen]
    cur.execute(f"""
        UPDATE c_movimientos_de_fondos
           SET fecha_anulacion = NULL, motivo_anulacion = NULL,
               id_usuario_anulacion = NULL
         WHERE {col} = %s
    """, (id_comprobante,))
