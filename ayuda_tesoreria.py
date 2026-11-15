"""ayuda_tesoreria.py — Manual de Tesorería (sin el circuito de pagos, que tiene el suyo)."""

CLAVE = "tesoreria"
MODULO = "Tesorería"

INTRO = """
<p>Tesorería lleva la plata del sindicato: las <b>cuentas de fondos</b> (bancos, caja, cartera
de cheques), todo lo que entra y sale de cada una en un <b>libro único</b> (el subdiario), los
extractos de los bancos y la <b>conciliación</b> del libro contra el banco. Los pagos a
proveedores y reintegros tienen su propio manual (Pagos).</p>
"""

CIRCUITO = [
    ("Ingresos", "Recibos de cuota sindical y órdenes de ingreso."),
    ("Egresos", "Pagos (órdenes de pago), extracciones."),
    ("Entre cuentas", "Pases, depósitos de efectivo o cheques."),
    ("Banco", "Se importa el extracto y se concilia contra el libro."),
]

SECCIONES = [

{
 "grupo": "Tesorería",
 "id": "tes_panel",
 "titulo": "Panel de Control",
 "url": "/tesoreria",
 "endpoints": ["tes_panel.panel"],
 "resumen": "Lo pendiente de Tesorería y el saldo de cada cuenta, en una foto de hoy.",
 "bloques": [
   {"tipo": "texto", "html":
    "Las tarjetas de arriba dicen qué hay para hacer y llevan a la pantalla donde se resuelve: órdenes "
    "por pagar y esperando aprobación, comprobantes liquidados sin orden, reintegros con saldo, "
    "transferencias que no salieron en un archivo (y cuántas no tienen CBU) y valores en cartera (y "
    "cuántos ya se pueden depositar)."},
   {"tipo": "campos", "items": [
     ("Cuentas de fondos", "El saldo del libro, el del último extracto y la diferencia, con el enlace "
      "al subdiario de la cuenta."),
     ("Órdenes de pago en curso", "Por estado."),
     ("Extractos bancarios", "Hasta qué fecha está importado cada banco; se marca atrasado a los 7 días."),
   ]},
   {"tipo": "aviso", "html":
    "El sistema anterior no tenía saldos de apertura: el saldo del libro es lo movido desde 2020 y "
    "puede no coincidir con el del banco hasta que se cargue un ajuste de apertura."},
 ]},

{
 "grupo": "Movimientos",
 "id": "tes_ingreso",
 "titulo": "Orden de Ingreso",
 "url": "/tesoreria/nueva_orden_concepto",
 "endpoints": ["tes_mov.orden_ingreso", "tes_mov.ingreso"],
 "resumen": "Un ingreso que no es cuota sindical: alquileres, intereses, varios.",
 "bloques": [
   {"tipo": "pasos", "items": [
     "Fecha y descripción de la orden.",
     "<b>Motivos</b>: qué se cobra (motivo de ingreso, período e importe). <b>Agregar motivo</b> para más de uno.",
     "<b>Cuentas</b>: a qué cuenta entra (banco, caja o cartera) y cuánto. Tienen que sumar lo mismo "
     "que los motivos; cada cuenta, una vez.",
     "Si entra a una cartera, los <b>valores de terceros</b> (cheques, e-cheqs) que la respaldan.",
     "<b>Registrar la orden</b>. Se numera AAMM-######## con el mes de la fecha.",
   ]},
   {"tipo": "aviso", "html":
    "Los recibos de cuota sindical no se hacen acá sino en Fiscalización → Emisión de Recibos. Una "
    "orden se anula en Anulaciones, no si un valor suyo ya salió de la cartera."},
 ]},

{
 "grupo": "Movimientos",
 "id": "tes_movimientos",
 "titulo": "Movimiento entre Cuentas, Depósitos y Extracciones",
 "url": "/tesoreria/movimientos/nuevo/transferencia",
 "endpoints": ["tes_mov.movimiento_nuevo", "tes_mov.movimiento"],
 "resumen": "Plata que pasa de una cuenta propia a otra. No hay tercero.",
 "bloques": [
   {"tipo": "campos", "items": [
     ("Movimiento entre cuentas", "De cualquier cuenta a cualquier otra (menos inversiones)."),
     ("Depósito bancario", "De la caja o de la cartera a un banco. Con valores elegidos, el importe es "
      "su suma y salen de la cartera donde están (un cheque diferido no se deposita antes de su fecha); "
      "sin valores, es efectivo."),
     ("Extracción", "Del banco a la caja, con cheques propios de una chequera de la cuenta: números "
      "dentro de la chequera, no usados antes, que sumen el importe."),
   ]},
   {"tipo": "criterio", "html":
    "El tipo de cada cuenta se controla en el servidor. Nada con fecha futura ni en un período cerrado. "
    "Los cheques depositados pasan a «depositado»; anular el movimiento los devuelve a la cartera."},
 ]},

{
 "grupo": "Movimientos",
 "id": "tes_subdiario",
 "titulo": "Subdiario de Cuentas de Fondos",
 "url": "/tesoreria/movimientos",
 "endpoints": ["tes_mov.subdiario"],
 "resumen": "El libro: cada entrada y salida de cada cuenta.",
 "bloques": [
   {"tipo": "texto", "html":
    "Un renglón por comprobante y por cuenta: pagos, recibos, órdenes de ingreso, movimientos entre "
    "cuentas. Por defecto, el mes en curso. Trae hasta 5.000 renglones (avisa si hay más)."},
   {"tipo": "campos", "items": [
     ("Cuenta", "Con una cuenta elegida, y sin filtros de origen ni de importe, aparece el <b>saldo</b> "
      "corrido, arrastrando el saldo anterior."),
     ("Origen", "Pagos, ingresos, movimientos…"),
     ("Importe desde / hasta", "Para encontrar un movimiento por su monto."),
     ("Con los anulados", "Los muestra tachados; no suman."),
   ]},
 ]},

{
 "grupo": "Movimientos",
 "id": "tes_anulaciones",
 "titulo": "Anulaciones",
 "url": "/tesoreria/anulaciones",
 "endpoints": ["tes_mov.anulaciones_lista"],
 "resumen": "Anular un pago, una orden de ingreso (o recibo) o un movimiento entre cuentas.",
 "bloques": [
   {"tipo": "texto", "html":
    "La lista tiene lo vigente de cada tipo. Lo que no se puede anular muestra un candado con el motivo. "
    "<b>Anular</b> pide el motivo; nada se borra."},
   {"tipo": "criterio", "html":
    "No se anula: lo de un <b>período cerrado</b>; lo que tiene algo <b>conciliado</b> con el banco "
    "(primero se desvincula en la conciliación); un pago que ya salió en una <b>transferencia masiva</b>; "
    "un pago que vino de AEDA (se anula allá y el importador trae la anulación); un movimiento cuyos "
    "cheques depositados ya siguieron su camino; una orden de ingreso con valores que ya salieron de "
    "la cartera. Anular un pago es solo para el Administrador."},
   {"tipo": "texto", "html":
    "Anular un <b>recibo de cuota sindical</b> saca su cobro de la cuenta corriente del empleador y la "
    "acreditación del banco vuelve a quedar sin recibo; si era de un acuerdo de pago que había "
    "cancelado, el acuerdo vuelve a vigente."},
 ]},

{
 "grupo": "Bancos",
 "id": "tes_extractos",
 "titulo": "Extractos Bancarios",
 "url": "/tesoreria/extractos",
 "endpoints": ["extractos.index"],
 "resumen": "Importar los movimientos del banco: Nación e ICBC.",
 "bloques": [
   {"tipo": "pasos", "items": [
     "Elegí la cuenta y <b>Importar extracto</b>.",
     "Subí uno o varios archivos (o una carpeta): Banco Nación (CSV o el reporte de Banca Empresas) e "
     "ICBC (cuenta corriente o reporte de recaudaciones).",
     "El resultado dice cuántos renglones entraron y cuántos ya estaban.",
   ]},
   {"tipo": "criterio", "html":
    "Un renglón repetido (mismo número de operación, fecha e importe) no entra dos veces: se puede "
    "importar el mismo período otra vez sin miedo. El archivo se controla contra la cuenta elegida "
    "(los últimos dígitos del número o del CBU): si es de otra cuenta, no entra nada."},
   {"tipo": "aviso", "html":
    "Un renglón que ya está en una conciliación no se borra. Las acreditaciones importadas son las que "
    "usa Emisión de Recibos para la cuota sindical."},
 ]},

{
 "grupo": "Bancos",
 "id": "tes_conciliacion",
 "titulo": "Conciliación Bancaria",
 "url": "/tesoreria/conc",
 "endpoints": ["conc.lista", "conc.detalle"],
 "resumen": "El extracto del banco contra el libro, mes por mes y cuenta por cuenta.",
 "bloques": [
   {"tipo": "pasos", "items": [
     "<b>Nueva conciliación</b>: cuenta y período. La primera de una cuenta pide el saldo inicial (se "
     "propone el del extracto).",
     "A la izquierda, el <b>extracto</b>; a la derecha, el <b>libro</b> (cada cheque, transferencia o "
     "depósito por separado). Se tilda de un lado y del otro y <b>Vincular</b>.",
     "<b>Conciliar sugeridos</b> vincula de una vez los pares que el sistema encontró.",
     "Lo del banco que no tiene contraparte: <b>Excepción</b> con un motivo, o <b>Generar "
     "comprobantes</b> para lo clasificado (gastos bancarios, intereses, pases).",
     "Sin pendientes y con el saldo final igual al del banco, <b>Cerrar conciliación</b>.",
   ]},
   {"tipo": "criterio", "html":
    "<b>Sugerencias</b>, de la más segura a la menos: número de cheque, CUIT + fecha + importe, CUIT + "
    "importe, fecha + importe, solo importe; siempre únicas de los dos lados. Nunca vinculan solas. Un "
    "grupo puede ser N renglones del banco contra M del libro; con diferencia de importe, solo con "
    "observación."},
   {"tipo": "aviso", "html":
    "Se concilia desde el <b>01/11/2026</b>: lo anterior del libro (el historial de AEDA) se da por "
    "conciliado. Una conciliación se cierra con las anteriores de la cuenta cerradas; <b>Reabrir</b> "
    "(Administrador, con motivo) solo si no hay una posterior cerrada. Lo conciliado no se puede anular "
    "hasta desvincularlo."},
 ]},

{
 "grupo": "Bancos",
 "id": "tes_clasificacion",
 "titulo": "Clasificación Conceptos Bancarios",
 "url": "/tesoreria/conc/clasificar",
 "endpoints": ["conc.clasificar"],
 "resumen": "Reglas para que lo repetido del banco se concilie solo: gastos, ingresos, pases.",
 "bloques": [
   {"tipo": "texto", "html":
    "Agrupa los conceptos del extracto (por ejemplo «IMPUESTO LEY 25413») y a cada uno se le asigna "
    "qué es: un <b>gasto</b> (con su concepto de gasto), un <b>ingreso</b> (con su motivo), un "
    "<b>pase a otra cuenta propia</b> o «a mano»."},
   {"tipo": "criterio", "html":
    "Con «genera comprobante», la conciliación ofrece crearlo: un gasto se convierte en una orden por "
    "concepto pagada desde la cuenta, un ingreso en una orden de ingreso y un pase en un movimiento "
    "entre cuentas, uno por renglón o uno por día si la regla agrupa. Si dos reglas coinciden, gana la "
    "más larga. Si el libro ya tiene algo que coincide, el renglón viene destildado."},
 ]},

{
 "grupo": "Tablas",
 "id": "tes_cuentas",
 "titulo": "Cuentas de Fondos y chequeras",
 "url": "/tesoreria/cuentas_fondos",
 "endpoints": ["tesoreria.cuentas_fondos"],
 "resumen": "Bancos, caja, cartera, inversiones: cada cuenta con su imputación y sus chequeras.",
 "bloques": [
   {"tipo": "campos", "items": [
     ("Tipo", "Banco, caja, cartera (valores de terceros), inversiones, tarjeta u otra."),
     ("Banco, número y CBU", "Obligatorios en un banco. El banco sale de los tres primeros dígitos del "
      "CBU: se elige solo y no se acepta uno distinto."),
     ("Cuenta contable", "Del activo del plan de cuentas."),
     ("Predeterminada", "La que viene elegida al pagar. Una sola."),
     ("Formato de transferencia", "El archivo del home banking que arma Transferencias Masivas desde "
      "esta cuenta (BNA24, BNA Empresa, ICBC). Vacío = el primero de su banco."),
     ("Chequeras", "En la solapa de un banco: rango de números, tipo (al día, diferido) y el último "
      "usado. Los rangos no se superponen."),
   ]},
   {"tipo": "aviso", "html":
    "Una cuenta con movimientos no se elimina: se deshabilita. Una chequera con cheques emitidos, igual."},
 ]},

{
 "grupo": "Tablas",
 "id": "tes_tablas",
 "titulo": "Bancos, Conceptos de Gasto y Motivos de Ingreso",
 "url": "/tesoreria/conceptos_gasto",
 "endpoints": ["tesoreria.bancos", "tesoreria.conceptos_gasto", "tesoreria.motivos_ingreso"],
 "resumen": "Los catálogos de Tesorería.",
 "bloques": [
   {"tipo": "campos", "items": [
     ("Códigos de Banco BCRA", "La nómina de bancos con su código (los tres primeros dígitos del CBU)."),
     ("Conceptos de Gasto", "En qué se gasta, con su cuenta contable. Un concepto de reintegro lleva su "
      "clase: subsidio o reintegro."),
     ("Motivos de Ingreso", "Por qué entra plata (cuota sindical, fiscalización, alquileres…), con su "
      "cuenta contable."),
   ]},
   {"tipo": "criterio", "html":
    "La cuenta contable tiene que ser imputable y activa en el plan de cuentas. Lo que se usa no se "
    "borra: se desactiva y deja de ofrecerse, sin cambiar lo ya cargado."},
 ]},

{
 "grupo": "Tablas",
 "id": "tes_rg830",
 "titulo": "Escala RG 830",
 "url": "/tesoreria/rg830",
 "endpoints": ["rg830.escalas"],
 "resumen": "Los regímenes de retención de Ganancias: mínimo, alícuota o escala, vigencia.",
 "bloques": [
   {"tipo": "texto", "html":
    "Por código de régimen: alícuota fija o escala por tramos, mínimo no sujeto, retención mínima y "
    "vigencia. El pago toma la fila activa más nueva que cubre la fecha. El <b>simulador</b> calcula una "
    "retención con lo cargado, sin guardar."},
   {"tipo": "criterio", "html":
    "Una escala que <b>ya retuvo</b> no cambia valores ni tramos: se usa <b>Nueva vigencia</b>, que copia "
    "y, al guardar, cierra la anterior el día antes. Las vigencias de un código no se pisan. Los tramos "
    "empiezan en 0, son contiguos y solo el último no tiene tope."},
   {"tipo": "aviso", "html":
    "La única escala vigente de un código con proveedores no se desactiva ni se elimina: los dejaría "
    "sin régimen."},
 ]},

]
