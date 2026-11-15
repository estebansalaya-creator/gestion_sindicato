"""ayuda_pagos.py — Manual del circuito de pagos (Tesorería → Pagos)."""

CLAVE = "pagos"
MODULO = "Pagos"

INTRO = """
<p>Todo pago sale de una <b>orden de pago</b>: a un proveedor por sus comprobantes, un
anticipo a cuenta, un pago por concepto (gastos sin comprobante de proveedor) o un reintegro a un
afiliado. La orden se arma, se aprueba en los niveles configurados y se paga con uno o más
instrumentos (cheque, transferencia, efectivo, débito), calculando las retenciones.</p>
"""

CIRCUITO = [
    ("Borrador", "Se arma la orden: qué se paga y cuánto."),
    ("Pendiente", "Se envía a aprobación: un renglón por nivel."),
    ("Aprobada", "Aprobaron todos los niveles: lista para pagar."),
    ("Pagada", "Con los instrumentos, las retenciones y el libro de fondos."),
]

SECCIONES = [

{
 "grupo": "Órdenes",
 "id": "pag_ordenes",
 "titulo": "Órdenes de Pago Proveedores",
 "url": "/pagos/ordenes",
 "endpoints": ["pagos.ordenes", "pagos.nueva", "pagos.nueva_proveedor"],
 "resumen": "Las órdenes y el armado de una nueva a un proveedor.",
 "bloques": [
   {"tipo": "texto", "html":
    "La lista tiene todas las órdenes (proveedor, anticipo, concepto, reintegro) con su estado. "
    "<b>Nueva orden</b> muestra los proveedores con comprobantes liquidados impagos."},
   {"tipo": "pasos", "items": [
     "Elegí el proveedor: aparecen sus comprobantes con saldo.",
     "Tildá los que se pagan. Se puede pagar <b>menos que el saldo</b> de uno (pago parcial): el "
     "comprobante sigue apareciendo con lo que le falta.",
     "Si tiene notas de crédito o pagos a cuenta con saldo, se ofrecen: conviene aplicarlos antes "
     "(<b>Aplicarlo a las facturas</b>). También se avisa si tiene otras órdenes sin pagar.",
     "Crear la orden: queda en <b>borrador</b>, con su número AAMM-########.",
   ]},
   {"tipo": "aviso", "html":
    "Lo importado de AEDA conserva su número de allá. Los comprobantes cargados en este sistema "
    "todavía no llegan acá hasta que exista la auditoría de comprobantes."},
 ]},

{
 "grupo": "Órdenes",
 "id": "pag_anticipo_concepto",
 "titulo": "Orden de Pago Anticipos y por Concepto",
 "url": "/pagos/ordenes/concepto/nueva",
 "endpoints": ["pagos.anticipo_nueva", "pagos.concepto_nueva"],
 "resumen": "Un pago a cuenta a un proveedor, o un gasto sin comprobante de proveedor.",
 "bloques": [
   {"tipo": "campos", "items": [
     ("Anticipo", "Plata a cuenta a un proveedor, con su rubro de pasivo; después se aplica a sus "
      "facturas. Necesita la imputación contable de anticipos (Imputaciones Contables)."),
     ("Por concepto", "Gastos e ingresos con período, por renglón (<b>Agregar renglón</b>): un gasto "
      "bancario, un pago a un afiliado que no es reintegro."),
   ]},
 ]},

{
 "grupo": "Órdenes",
 "id": "pag_orden",
 "titulo": "La orden: aprobación, pago y anulación",
 "url": "",
 "endpoints": ["pagos.orden"],
 "resumen": "La ficha de la orden, de borrador a pagada.",
 "bloques": [
   {"tipo": "pasos", "items": [
     "En borrador, <b>Enviar a aprobación</b>. Pide tantos niveles como el mayor configurado.",
     "Cada aprobador (Config. Aprobadores) entra a la orden y <b>Aprueba su nivel</b> o la "
     "<b>Rechaza</b> (con observación). Rechazada, para rehacerla se anula y se arma otra.",
     "Aprobada, en <b>Pagar la orden</b>: fecha de pago, retenciones (se muestran antes de confirmar) "
     "e instrumentos que cubren el <b>neto</b>.",
     "Confirmar: la orden queda <b>pagada</b>.",
   ]},
   {"tipo": "campos", "items": [
     ("Cheque", "De una chequera habilitada de la cuenta. Se pueden generar varios con vencimientos "
      "cada tantos días o cada mes; los centavos van en el último. La chequera avanza."),
     ("Transferencia", "Con el CBU o alias del beneficiario precargado. Después sale en Transferencias Masivas."),
     ("Efectivo", "Desde una caja (no desde un banco)."),
     ("Débito", "El banco lo debita directamente."),
     ("Completar la diferencia", "Pone en el último instrumento lo que falta para el neto."),
   ]},
   {"tipo": "criterio", "html":
    "<b>Retenciones</b>: solo de los impuestos de los que el sindicato es agente (Datos del Sindicato) "
    "y solo a proveedores. Ganancias (RG 830) una vez por proveedor y pago, sobre lo acumulado del mes "
    "menos el mínimo no sujeto y lo ya retenido; IVA e Ingresos Brutos sobre el neto gravado; SUSS sobre "
    "el total. El servidor las vuelve a calcular al grabar. Cada retención deja su certificado."},
   {"tipo": "criterio", "html":
    "El pago cancela lo pagado de cada comprobante (el bruto: la retención también cancela deuda). El "
    "expediente pasa a «pagado» solo si el saldo llega a cero."},
   {"tipo": "campos", "items": [
     ("Anular el pago", "Solo el Administrador, con motivo. No si el período está cerrado, si algo "
      "está conciliado o si ya salió en una transferencia masiva. La orden vuelve a «aprobada»."),
     ("Anular la orden", "Solo sin un pago vivo. Libera los comprobantes."),
   ]},
 ]},

{
 "grupo": "Pagos",
 "id": "pag_emision",
 "titulo": "Emisión de Pagos y Pagos Emitidos",
 "url": "/pagos/emision",
 "endpoints": ["pagos.emision", "pagos.emitidos"],
 "resumen": "Las órdenes aprobadas para pagar, y los pagos ya hechos.",
 "bloques": [
   {"tipo": "texto", "html":
    "<b>Emisión de pagos</b> lista las órdenes por pagar (aprobadas) y las que esperan aprobación; el "
    "ojo abre la orden para pagarla. <b>Pagos emitidos</b> lista los pagos con su neto, retenciones e "
    "instrumentos, filtrables por clase, estado y fechas."},
 ]},

{
 "grupo": "Pagos",
 "id": "pag_transferencias",
 "titulo": "Transferencias Masivas",
 "url": "/pagos/transferencias",
 "endpoints": ["transferencias.index", "transferencias.lote_ver"],
 "resumen": "El archivo para subir al home banking con las transferencias de los pagos.",
 "bloques": [
   {"tipo": "pasos", "items": [
     "Elegí la <b>cuenta de origen</b> y las fechas de los pagos (por defecto, los de hoy y la cuenta "
     "predeterminada).",
     "Tildá las transferencias que van en el archivo y elegí el concepto.",
     "<b>Generar archivo</b>: queda registrado el lote y se baja el archivo en el formato del banco "
     "de la cuenta (BNA24, BNA Empresa o la planilla del ICBC).",
     "Subí el archivo al home banking.",
   ]},
   {"tipo": "criterio", "html":
    "El destino es el CBU o alias del instrumento; si no tiene, el de la ficha del proveedor (o del "
    "afiliado, en un reintegro). Lo que <b>no puede ir</b> se ve apagado con el motivo: sin CBU, CBU que "
    "no verifica o un alias en un formato del Nación (que no los acepta)."},
   {"tipo": "aviso", "html":
    "Desde que un pago sale en un archivo, <b>no se anula</b>. Si el archivo todavía no se subió al "
    "banco: <b>Sacar del archivo</b> un renglón (con motivo) o <b>Anular el archivo</b> entero. El archivo "
    "se arma siempre con lo registrado: bajarlo de nuevo da lo mismo aunque cambie la ficha del proveedor."},
 ]},

{
 "grupo": "Configuración",
 "id": "pag_certificados",
 "titulo": "Certificados de Retención",
 "url": "/pagos/certificados",
 "endpoints": ["pagos.certificados", "pagos.certificado"],
 "resumen": "Los certificados de las retenciones practicadas, para entregar al proveedor.",
 "bloques": [
   {"tipo": "texto", "html":
    "Uno por retención (CRT-AAAA-NNNNNN), filtrables por impuesto, período y estado; el PDF es el "
    "certificado. Los de AEDA conservan su número. Anular el pago anula sus certificados."},
   {"tipo": "aviso", "html":
    "La exportación a SICORE / SIRE todavía no está en el sistema."},
 ]},

{
 "grupo": "Configuración",
 "id": "pag_config",
 "titulo": "Imputaciones Contables y Config. Aprobadores",
 "url": "/pagos/config_aprobadores",
 "endpoints": ["pagos.aprobadores", "pagos.imputaciones"],
 "resumen": "Quién aprueba cada nivel y las cuentas de anticipos y retenciones.",
 "bloques": [
   {"tipo": "campos", "items": [
     ("Aprobadores", "Un usuario por nivel (1 a 9; puede haber varios por nivel). Sin aprobadores una "
      "orden no se puede enviar ni pagar."),
     ("Imputaciones", "La cuenta contable del anticipo (debe) y la de cada retención (haber)."),
   ]},
 ]},

]
