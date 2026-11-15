"""ayuda_proveedores.py — Manual de Proveedores."""

CLAVE = "proveedores"
MODULO = "Proveedores"

INTRO = """
<p>Los proveedores son a quienes el sindicato les paga: comercios, profesionales, servicios.
De cada uno: su ficha con los datos impositivos y la imputación contable, la carga de sus
comprobantes (que abre el expediente en la mesa de entradas), su cuenta corriente y la
aplicación de notas de crédito y pagos a cuenta contra sus facturas.</p>
"""

CIRCUITO = [
    ("Ficha", "CUIT, condición de IVA, retenciones, CBU e imputación."),
    ("Comprobante", "Se carga (del PDF, a mano o de Mis Comprobantes) y abre el expediente."),
    ("Deuda", "Auditado, el comprobante pasa a la cuenta corriente."),
    ("Pago", "La orden de pago lo cancela; los créditos se aplican a las facturas."),
]

SECCIONES = [

{
 "grupo": "Proveedores",
 "id": "prov_abm",
 "titulo": "ABM de Proveedores",
 "url": "/proveedores",
 "endpoints": ["proveedores.abm"],
 "resumen": "La ficha del proveedor: identificación, impuestos, pago, imputación y contactos.",
 "bloques": [
   {"tipo": "campos", "items": [
     ("Identificación", "CUIT (uno por proveedor: avisa mientras se escribe si ya existe o no "
      "verifica), razón social, nombre de fantasía."),
     ("Datos impositivos", "Condición de IVA, Ingresos Brutos."),
     ("Retenciones", "Solo los impuestos de los que el sindicato es agente de retención (Datos del "
      "Sindicato) se pueden editar; los demás se ven apagados. En Ganancias: si aplica y el régimen."),
     ("Pago", "CBU (se controla el dígito) o alias, para las transferencias."),
     ("Imputación", "En el alta, el rubro de pasivo y el concepto de gasto son obligatorios. En la "
      "solapa Cuentas se agregan otros; uno de cada clase es el predeterminado y el último activo no "
      "se puede dar de baja."),
     ("Mesa de entradas", "El área y el usuario a los que van sus expedientes al cargar un "
      "comprobante, y los últimos expedientes. Cambiarlo no mueve los que ya existen."),
     ("Movimientos", "La auditoría de la ficha: cada cambio, con quién y cuándo."),
   ]},
   {"tipo": "criterio", "html":
    "<b>Ganancias (RG 830)</b>: del proveedor se guarda solo el régimen; el mínimo, la alícuota o la "
    "escala salen de la tabla vigente (Tesorería → Escala RG 830), así todos los proveedores del mismo "
    "régimen retienen igual. A un monotributista no se le retiene Ganancias."},
   {"tipo": "aviso", "html":
    "Un proveedor con comprobantes o retenciones no se elimina: se da de baja."},
 ]},

{
 "grupo": "Comprobantes",
 "id": "prov_carga",
 "titulo": "Carga de Comprobantes",
 "url": "/comprobantes/carga",
 "endpoints": ["comprobantes.carga"],
 "resumen": "Una factura de proveedor: la lee del PDF, se carga a mano o viene de ARCA.",
 "bloques": [
   {"tipo": "texto", "html":
    "Tres formas de cargar, un mismo formulario: <b>subir el PDF</b> (el sistema lo lee, con OCR si "
    "es un escaneo, y completa los datos), <b>Cargar a mano</b> (se busca el proveedor por nombre y "
    "se ofrecen sus comprobantes pendientes de ARCA) o <b>Desde Comprobantes ARCA</b> (los datos los "
    "da ARCA)."},
   {"tipo": "pasos", "items": [
     "Subí el PDF (o elegí otra forma). Revisá lo que leyó.",
     "El proveedor tiene que estar dado de alta y activo; si no, <b>Dar de alta el proveedor</b> "
     "abre el alta con el CUIT y la razón social.",
     "Completá el período y la imputación (rubro de pasivo y concepto de gasto, si el proveedor "
     "tiene más de uno).",
     "<b>Guardar comprobante</b>: queda el comprobante, su expediente en la mesa (derivado al destino "
     "del proveedor) y la liquidación abierta, todo junto.",
   ]},
   {"tipo": "criterio", "html":
    "Se controla en el servidor, siempre: que no esté repetido (por CAE y por tipo + CUIT + punto de "
    "venta + número), que el receptor sea el CUIT del sindicato, que el período no sea posterior a la "
    "emisión y que los importes cierren con el total. Una <b>nota de crédito</b> se carga en positivo: "
    "el tipo de comprobante decide el signo."},
   {"tipo": "campos", "items": [
     ("Escudo", "Constatado con ARCA. Si ARCA lo rechaza no entra; si ARCA no responde entra con aviso."),
     ("Robot", "El PDF dice lo mismo que los datos cargados."),
   ]},
   {"tipo": "aviso", "html":
    "El comprobante entra a la mesa como <b>pendiente de auditoría</b>: todavía no es deuda ni se "
    "puede pagar. La auditoría de comprobantes, que lo pasa a la cuenta corriente, todavía no está en "
    "el sistema; mientras tanto la deuda con proveedores es la que viene de AEDA."},
 ]},

{
 "grupo": "Comprobantes",
 "id": "prov_arca",
 "titulo": "Comprobantes ARCA",
 "url": "/comprobantes/arca",
 "endpoints": ["mis_comp.listado"],
 "resumen": "Lo que ARCA dice que recibió el sindicato, cruzado con lo cargado.",
 "bloques": [
   {"tipo": "pasos", "items": [
     "En el portal de ARCA: Mis Comprobantes → Recibidos → exportar.",
     "Acá, <b>Importar</b> el archivo .zip tal como se bajó. Reimportar no duplica.",
     "Los <b>pendientes</b> (sin expediente) se cargan desde el renglón: abre la carga con los datos de ARCA.",
   ]},
   {"tipo": "campos", "items": [
     ("Pendiente", "Está en ARCA y no se cargó."),
     ("Cargado", "Ya tiene comprobante cargado (con su expediente)."),
     ("Descartado", "No corresponde cargarlo (la flecha verde lo restaura como pendiente)."),
     ("Proveedor", "Con o sin alta de proveedor: los que no tienen alta hay que darlos de alta antes de cargar."),
   ]},
   {"tipo": "aviso", "html":
    "La copia de Mis Comprobantes del sistema anterior (desde 09/2023) ya está importada. La descarga "
    "automática del portal no es posible: ARCA la bloquea; se baja a mano."},
 ]},

{
 "grupo": "Cuenta corriente",
 "id": "prov_cc",
 "titulo": "Cuenta Corriente de Proveedores",
 "url": "/proveedores/cc",
 "endpoints": ["cc_prov.bandeja", "cc_prov.estado_cuenta", "cc_prov.por_cuit"],
 "resumen": "Debe, haber y saldo de cada proveedor; su estado de cuenta.",
 "bloques": [
   {"tipo": "texto", "html":
    "La bandeja tiene arriba el Debe, el Haber, el saldo final y lo pendiente de auditoría; abajo un "
    "renglón por proveedor. El ojo abre el <b>estado de cuenta</b>: los comprobantes (liquidaciones) "
    "y los pagos, con el saldo acumulado."},
   {"tipo": "criterio", "html":
    "<b>Saldo = Debe − Haber</b>: <b>negativo es acreedor</b> (le debemos). Las facturas van al Haber; "
    "los pagos, los anticipos y las notas de crédito, al Debe. Lo que está pendiente de auditoría no suma."},
   {"tipo": "campos", "items": [
     ("Saldo al", "El saldo a una fecha."),
     ("Rubro de pasivo", "El saldo de esa cuenta solamente."),
     ("Período (6 meses, 12 meses, Todo)", "En el estado de cuenta; lo anterior entra como saldo anterior."),
     ("Comprobante", "Buscar uno («8532» o «143-8532»); ignora las fechas."),
     ("Saldo comp.", "Lo que le falta a una factura (negativo) o lo que un pago o una nota tienen sin "
      "imputar (positivo)."),
     ("Vista por aplicación", "Un renglón por comprobante y por cada forma en que se canceló; desde ahí "
      "se desaplica."),
     ("Reloj", "Con qué se canceló un comprobante."),
     ("Exportar PDF · Excel", "El estado de cuenta con los mismos filtros."),
   ]},
 ]},

{
 "grupo": "Cuenta corriente",
 "id": "prov_aplicacion",
 "titulo": "Aplicación de Comprobantes",
 "url": "/proveedores/cc/aplicaciones",
 "endpoints": ["cc_prov.aplicaciones"],
 "resumen": "Notas de crédito y pagos a cuenta contra las facturas del proveedor.",
 "bloques": [
   {"tipo": "pasos", "items": [
     "Elegí el proveedor (o uno de «Proveedores con algo para aplicar»).",
     "Elegí un <b>débito</b> (factura con saldo) y un <b>crédito</b> (nota de crédito o pago con saldo).",
     "El importe propone el menor de los dos saldos. <b>Aplicar</b>.",
   ]},
   {"tipo": "criterio", "html":
    "Solo del mismo rubro de pasivo. <b>Lo que está en una orden de pago viva no se aplica</b>: el pago "
    "lo cancelaría otra vez. No en un período cerrado. Al aplicar o desaplicar, el expediente pasa a "
    "«pagado» si el comprobante quedó en cero o vuelve a «liquidado» si le queda saldo."},
   {"tipo": "aviso", "html":
    "<b>Desaplicar</b> (eslabón roto) pide motivo y puede ser parcial. Una aplicación que vino de AEDA "
    "vuelve si se corre de nuevo la importación de AEDA: allá manda AEDA."},
 ]},

]
