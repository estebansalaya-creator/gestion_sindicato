"""ayuda_beneficios.py — Manual de Beneficios (Convenio YMCA y Campañas)."""

CLAVE = "beneficios"
MODULO = "Beneficios"

INTRO = """
<p>Los beneficios para los afiliados: el <b>convenio con el gimnasio</b> (la YMCA) y las <b>campañas</b>
que se mandan por correo.</p>
<p>En el convenio, los afiliados que se adhieren pagan una cuota fija por mes y el gimnasio le factura
al sindicato todos los meses por los adheridos; <b>la diferencia la cubre el sindicato</b>. Lo que pagan
los afiliados va aparte de la cuota sindical: tiene sus propios recibos.</p>
"""

CIRCUITO = [
    ("Nómina", "Quién está adherido y desde qué mes."),
    ("Cobro", "Las transferencias de los afiliados llevan su recibo, con los meses que pagan."),
    ("Cuotas", "Qué grupo familiar pagó y quién debe."),
    ("Control", "La factura del gimnasio contra la nómina por el precio, y lo que cubre el sindicato."),
]

SECCIONES = [

{
 "grupo": "Convenio YMCA",
 "id": "ben_adheridos",
 "titulo": "Nómina de Adheridos",
 "url": "/beneficios/ymca/adheridos",
 "endpoints": ["ben_conv.adheridos_abm"],
 "resumen": "Quién está adherido al convenio, desde y hasta qué mes.",
 "bloques": [
   {"tipo": "texto", "html":
    "Cada adherido es un afiliado del padrón, titular o familiar, con el <b>primer mes que paga</b> y, cuando "
    "deja, el <b>último</b>. La cuota la paga su grupo familiar: un titular con un hijo adherido debe dos cuotas."},
   {"tipo": "pasos", "items": [
     "<b>Agregar</b>: el CUIL del padrón y el mes desde.",
     "<b>Dar de baja</b> (el ícono rojo): el último mes que paga. No se borra: queda la historia.",
     "La solapa <b>Transfirieron y no están</b> lista a los afiliados que acreditaron en el banco en los "
     "últimos meses y cuyo grupo no está en la nómina: sirve para armarla. El <b>+</b> lo agrega con el mes "
     "de la última transferencia (revisá que sea la cuota del gimnasio y no otro pago).",
   ]},
   {"tipo": "aviso", "html":
    "Eliminar es solo para una carga equivocada que todavía no generó cuotas; si ya las generó, se da de baja."},
 ]},

{
 "grupo": "Convenio YMCA",
 "id": "ben_recibos",
 "titulo": "Recibos de Adheridos",
 "url": "/beneficios/ymca/recibos",
 "endpoints": ["ben_conv.recibos", "ben_conv.emitir_uno"],
 "resumen": "El recibo al afiliado de cada transferencia, aparte de la cuota sindical.",
 "bloques": [
   {"tipo": "texto", "html":
    "Las acreditaciones del extracto de la cuenta elegida que hizo un <b>afiliado</b> (no un empleador). Ya no "
    "salen en Fiscalización → Emisión de Recibos. Cada una lleva el recibo al afiliado (talonario de afiliados) "
    "con un renglón por mes: tantos meses como <b>cuotas justas del grupo</b> entran en el importe."},
   {"tipo": "criterio", "html":
    "En <b>lote</b> solo van las de un grupo que está en la nómina ese mes y cuyo importe es un número justo de "
    "cuotas del grupo. Las demás se emiten de a una (el <b>+</b>), donde se corrigen los meses. Lo que AEDA ya "
    "registró en su orden del mes sale como «Ya tiene recibo»."},
   {"tipo": "aviso", "html":
    "Queda a criterio de quien emite. Lo que un afiliado transfiere con centavos o no redondo a la medida de la "
    "cuota ya no llega acá: es la cuota sindical del empleador de su ficha y sale en Emisión de Recibos. Si una "
    "de las que llegan no es la cuota del gimnasio, el botón del <b>edificio</b> la emite como cuota sindical de "
    "una empresa, y <b>Asociar</b> (la persona) deja dicho de quién son los pagos de ese CUIT: la <b>cuota "
    "sindical</b> de una empresa o la <b>cuota social</b> de un afiliado (el mismo CUIT puede tener las dos)."},
 ]},

{
 "grupo": "Convenio YMCA",
 "id": "ben_cuotas",
 "titulo": "Cuotas de Adheridos",
 "url": "/beneficios/ymca/cuotas",
 "endpoints": ["ben_conv.cuotas", "ben_conv.cuota_grupo"],
 "resumen": "La cuenta de cada grupo familiar: cuotas, lo pagado y quién debe.",
 "bloques": [
   {"tipo": "campos", "items": [
     ("Cuotas", "Mes por mes, la cuota de la vigencia por los adheridos del grupo ese mes."),
     ("Pagado", "Los recibos de cualquiera del grupo, a los meses que dicen."),
     ("Saldo", "Positivo = debe; negativo = pagó de más."),
     ("Meses adeudados", "Los meses con saldo."),
   ]},
   {"tipo": "aviso", "html":
    "Se lleva desde el mes que dice Datos del Convenio (noviembre de 2026): antes AEDA registraba lo cobrado "
    "en una orden por mes, sin detalle por afiliado."},
 ]},

{
 "grupo": "Convenio YMCA",
 "id": "ben_control",
 "titulo": "Control Mensual",
 "url": "/beneficios/ymca/control",
 "endpoints": ["ben_conv.control"],
 "resumen": "La factura del gimnasio contra la nómina por el precio, lo cobrado y lo que cubre el sindicato.",
 "bloques": [
   {"tipo": "campos", "items": [
     ("Esperado", "Los adheridos de la nómina ese mes por el precio que factura el gimnasio."),
     ("Facturado · Diferencia", "Las facturas del gimnasio de ese período (cargadas en Proveedores) y la "
      "diferencia con lo esperado: en rojo si no coincide."),
     ("Adheridos según factura", "Lo facturado dividido el precio: cuántos adheridos está cobrando el gimnasio."),
     ("A cobrar · Cobrado", "La cuota por los adheridos, y lo que efectivamente se cobró a los afiliados ese mes "
      "(también lo que AEDA registró agrupado)."),
     ("Cubre el sindicato", "Facturado menos cobrado."),
   ]},
 ]},

{
 "grupo": "Convenio YMCA",
 "id": "ben_convenio",
 "titulo": "Datos del Convenio",
 "url": "/beneficios/ymca/convenio",
 "endpoints": ["ben_conv.convenio_ficha"],
 "resumen": "El gimnasio, el motivo de los recibos y los importes de cada vigencia.",
 "bloques": [
   {"tipo": "campos", "items": [
     ("Proveedor", "El gimnasio: sus facturas son las que se controlan."),
     ("Motivo de los recibos", "El motivo de ingreso de los recibos a los adheridos (YMCA)."),
     ("Precio del gimnasio", "Lo que factura por cada adherido y por mes."),
     ("Cuota del adherido", "Lo que paga cada adherido por mes. Igual para todos."),
   ]},
   {"tipo": "criterio", "html":
    "Cada vigencia rige desde su mes hasta el anterior a la siguiente. Un aumento es una vigencia nueva: así los "
    "meses de antes conservan su importe."},
 ]},

{
 "grupo": "Campañas",
 "id": "ben_campanias",
 "titulo": "Campañas",
 "url": "/beneficios/campanias",
 "endpoints": ["ben_camp.lista", "ben_camp.editar", "ben_camp.ficha"],
 "resumen": "Flyers de beneficios y novedades que se mandan por correo a los afiliados.",
 "bloques": [
   {"tipo": "pasos", "items": [
     "<b>Nueva campaña</b>: un título (para la lista), el asunto, el texto y el <b>flyer</b> (imagen o PDF). "
     "En el texto, {nombre} se reemplaza por el nombre de cada afiliado.",
     "Elegí <b>a quién va</b>: titulares activos, titulares y familiares, los adheridos de un convenio o "
     "<b>según los filtros del padrón</b> (buscar, estado, titular o familiar, sexo, edad, atributo: los de la "
     "Consulta del Padrón). Abajo dice a cuántas direcciones llega mientras elegís. Desde la Consulta del "
     "Padrón, <b>Campaña con estos filtros</b> abre una campaña nueva con los filtros que estás mirando.",
     "En la ficha mirá <b>cómo queda</b> y a cuántas direcciones llega, y mandate una <b>prueba</b>.",
     "<b>Enviar</b>: sale de a un mail por afiliado, en segundo plano. La ficha muestra el avance; se puede "
     "cerrar, pausar y reanudar.",
   ]},
   {"tipo": "criterio", "html":
    "Las direcciones salen de los <b>contactos</b> de cada afiliado (la principal o la primera), sin repetir y "
    "sin las que pidieron no recibir más. Al pie de cada mail va el enlace para darse de baja. La lista se arma al "
    "enviar, con los filtros guardados en la campaña; <b>Lista en Excel</b> la baja (a quién le llega o, ya "
    "enviada, cómo salió cada una)."},
   {"tipo": "aviso", "html":
    "Sale por el Correo Saliente del sistema y respeta su límite de 24 horas: una campaña más grande que el "
    "límite queda <b>pausada</b> con el motivo y se reanuda al día siguiente, desde donde quedó. Si el servidor "
    "de correo no responde, corta la conexión o frena a la cuenta, también se pausa en el acto, con el motivo y "
    "el paso en que falló, y ese afiliado sigue pendiente: al reanudar se le manda. Antes de reanudar, "
    "<b>Probar la conexión</b> en Correo Saliente dice si ya anda, sin mandar nada."},
   {"tipo": "criterio", "html":
    "<b>Editar</b>: un borrador se cambia entero. Una campaña <b>pausada</b> también se edita, pero solo el título, "
    "el asunto, el texto y el flyer: a quién va no se cambia, porque la lista ya está armada. Los que faltan "
    "reciben la versión nueva; a los que ya les llegó no se les vuelve a mandar. Si el flyer no está en el servidor, "
    "la ficha lo avisa y no se puede probar ni seguir enviando hasta cargarlo de nuevo."},
   {"tipo": "criterio", "html":
    "<b>Eliminar</b> (el tacho en la lista o el botón en la ficha) borra la campaña con su flyer y su lista de "
    "direcciones, en cualquier estado: borrador, enviada, pausada o cancelada. No se puede mientras se está "
    "enviando (primero se pausa o se cancela) ni si tiene padrón de entrega, porque se perdería quién retiró el "
    "beneficio. Los correos que ya salieron siguen en Correo Saliente › Envíos. No se puede deshacer."},
 ]},

{
 "grupo": "Campañas",
 "id": "ben_entrega",
 "titulo": "Padrón de entrega",
 "url": "/beneficios/campanias",
 "endpoints": ["ben_ent.entrega", "ben_ent.accion"],
 "resumen": "Quiénes reciben el beneficio de una campaña (las cajas navideñas) y quién ya lo retiró.",
 "bloques": [
   {"tipo": "pasos", "items": [
     "En la ficha de la campaña, <b>Crear padrón de entrega</b> arma la lista con el mismo grupo de "
     "<b>A quién va</b> (los filtros del padrón, titulares, adheridos…), <b>tengan o no correo</b>. Para una "
     "caja por familia, elegí «solo titulares» en los filtros antes de crearlo.",
     "Cuando vienen a retirar, buscá al afiliado en el filtro de la grilla (documento, CUIL o apellido) y tocá "
     "<b>Marcar que retiró</b> (el tilde verde). Si retira otra persona, anotá su nombre y documento; si es el "
     "afiliado, Enter y listo. No recarga la página: el filtro queda puesto para el siguiente.",
     "<b>Quitar el retiro</b>: si se marcó a alguien por error, con el motivo.",
     "<b>Agregar al padrón</b> (abajo): alguien que no entró y le corresponde, por CUIL o documento, con el "
     "motivo. <b>Quitar del padrón</b> (el tacho): solo a quien no retiró, con el motivo.",
     "<b>Volver a crear</b>: rehace la lista con el padrón de hoy. Solo mientras nadie retiró; se pierden los "
     "agregados y quitados a mano.",
     "<b>Actualizar padrón</b>: suma al final de la lista a quienes hoy están en el grupo y no en el padrón de "
     "entrega (altas nuevas, afiliados que se reincorporaron), aunque ya haya retiros. No cambia los números de "
     "orden que ya hay, no saca a nadie (las bajas se quitan a mano) y no vuelve a poner a quien se quitó a mano.",
     "<b>Entregar a alguien fuera del padrón</b> (abajo de la grilla): documento o CUIL y el motivo. Si es "
     "afiliado, entra al padrón de entrega como agregado y ya con el retiro; si no es afiliado, escribí su "
     "apellido y nombre. Aparece en la grilla como «Fuera del padrón».",
   ]},
   {"tipo": "pasos", "items": [
     "<b>Retira por la empresa</b>: escribí el nombre de la empresa en el buscador de la grilla. Cuando todo lo "
     "que queda filtrado es de una sola empresa, arriba de la grilla aparece cuántos faltan y cuántos ya "
     "retiraron, con el botón <b>Retira por la empresa</b>.",
     "El diálogo muestra primero los de esa empresa que <b>ya retiraron</b> (cuándo y quién), para no "
     "entregar dos veces, y abajo los que faltan, tildados: destildá a quien no se lleve. Escribí el nombre y "
     "el <b>DNI</b> de quien retira (obligatorios); la cantidad es la de los tildados.",
     "Al registrarlo se abre la <b>constancia en PDF por duplicado</b> (original y duplicado, con el detalle "
     "de los afiliados y las firmas): imprimila para que la firme quien retira. Si el navegador bloquea la "
     "ventana, está el botón «Imprimir constancia por duplicado».",
     "La solapa <b>Retiros por empresa</b> lista las constancias para volver a imprimirlas; en la grilla, cada "
     "afiliado retirado así tiene su botón PDF. Se registra todo o nada: si otro puesto marcó a alguno en el "
     "medio, no se graba y hay que volver a filtrar. Con stock cargado, tiene que alcanzar para todos.",
   ]},
   {"tipo": "pasos", "items": [
     "En la solapa <b>Stock</b> cargá cuántos hay: una cantidad positiva suma (la compra, con el remito en el "
     "detalle) y una negativa ajusta (rotas, devueltas).",
     "Arriba, <b>Stock</b> dice cuántos quedan: lo cargado menos lo retirado, contando también los de fuera del "
     "padrón. Cuando no queda, el sistema no deja registrar más retiros hasta que se cargue más.",
     "Sin ninguna carga de stock los retiros no se controlan: la pantalla lo avisa.",
   ]},
   {"tipo": "criterio", "html":
    "El padrón de entrega es una <b>foto</b> del grupo al crearlo: lo que cambie después en el padrón de "
    "afiliados no lo toca, salvo las altas y reincorporaciones que suma «Actualizar padrón». Es aparte del correo: se crea con la campaña en borrador o ya enviada. Dos puestos "
    "pueden marcar a la vez: si alguien ya retiró, el segundo ve a qué hora y quién lo marcó."},
   {"tipo": "aviso", "html":
    "Todo queda en la solapa <b>Movimientos</b>: cada retiro (y quién retiró), cada retiro quitado, cada "
    "agregado o quitado, cada entrega fuera del padrón y cada carga de stock, con la fecha y el usuario. La grilla se exporta a Excel con los filtros puestos."},
 ]},

]
