"""ayuda_reintegros.py — Manual de Reintegros y subsidios."""

CLAVE = "reintegros"
MODULO = "Reintegros y subsidios"

INTRO = """
<p>El sindicato devuelve a sus afiliados gastos (<b>reintegros</b>: movilidad, gastos gremiales,
honorarios) y paga <b>subsidios</b> (nacimiento, casamiento, fallecimiento, educación, ajuares).
Lo dice el concepto de cada renglón; una solicitud con las dos clases es «mixta».</p>
<p>El circuito tiene tres pantallas, y cada una es un permiso: quien carga, quien audita y quien
genera las órdenes de pago. La ficha de una solicitud la ve quien tenga cualquiera de las tres.</p>
"""

CIRCUITO = [
    ("Solicitud", "Se carga el titular, los renglones y los comprobantes."),
    ("Auditoría", "Se reconoce cada renglón (todo, parte o nada) o se rechaza."),
    ("Orden de pago", "Una por titular, por lo aprobado."),
    ("Pago", "Se aprueba y se paga en Tesorería → Pagos."),
]

SECCIONES = [

{
 "grupo": "Reintegros",
 "id": "rei_solicitud",
 "titulo": "Solicitudes de Reintegro",
 "url": "/reintegros/solicitud",
 "endpoints": ["reintegros.solicitud", "reintegros.inicio"],
 "resumen": "Cargar una solicitud y seguir las cargadas.",
 "bloques": [
   {"tipo": "pasos", "items": [
     "<b>Nueva solicitud</b>. Buscá el <b>titular</b> por nombre, CUIL o DNI.",
     "Por renglón: el integrante del grupo familiar, el concepto, la fecha del gasto, el número de "
     "comprobante y el importe. <b>Agregar renglón</b> para más.",
     "Adjuntá los comprobantes (PDF o imagen, hasta 10 MB) y, si se paga por transferencia, el CBU o alias.",
     "<b>Guardar borrador</b> (sigue editable), <b>Enviar a auditoría</b> o, quien también audita, "
     "<b>Guardar y auditar</b>.",
   ]},
   {"tipo": "campos", "items": [
     ("Borrador", "Cargada, sin enviar."),
     ("En auditoría", "Esperando que la revisen."),
     ("Aprobada · Pago parcial · Con orden", "Reconocida; con una orden de pago por todo o por parte."),
     ("Rechazada · Anulada", "Cerradas."),
     ("Pagada", "Las que vinieron pagadas del sistema anterior (AEDA)."),
   ]},
   {"tipo": "texto", "html":
    "Se numeran RA-AAAA-NNNNNN (las de AEDA, AEDA-número). <b>Imprimir constancia</b> da el PDF con el "
    "membrete del sindicato."},
 ]},

{
 "grupo": "Reintegros",
 "id": "rei_auditoria",
 "titulo": "Auditoría de Reintegros",
 "url": "/reintegros/auditoria",
 "endpoints": ["reintegros.auditoria", "reintegros.auditoria_ficha", "reintegros.ficha"],
 "resumen": "Reconocer cada renglón o rechazar la solicitud.",
 "bloques": [
   {"tipo": "pasos", "items": [
     "La bandeja tiene las solicitudes en auditoría. <b>Auditar</b> abre la ficha.",
     "Por renglón, el <b>importe reconocido</b> (todo, una parte o cero) y un comentario. <b>Reconocer "
     "todo</b> y <b>Todo en 0</b> ayudan.",
     "<b>Cerrar auditoría y autorizar</b>, o <b>Rechazar solicitud</b> con el motivo.",
   ]},
   {"tipo": "criterio", "html":
    "Corregir una solicitud ya auditada la <b>devuelve a auditoría</b> con lo reconocido en blanco: lo "
    "autorizado se decidió sobre otros renglones. Lo que cierra la edición es la orden de pago. Anular "
    "también es de quien audita."},
 ]},

{
 "grupo": "Reintegros",
 "id": "rei_ordenes",
 "titulo": "Órdenes de Pago de Reintegros",
 "url": "/reintegros/ordenes",
 "endpoints": ["reintegros.ordenes"],
 "resumen": "Lo aprobado con saldo, para generar las órdenes de pago.",
 "bloques": [
   {"tipo": "pasos", "items": [
     "La grilla agrupa por titular los reintegros aprobados con saldo.",
     "Tildá los que se pagan y <b>Generar órdenes de pago</b>: una por titular, en borrador.",
     "La orden se envía a aprobación y se paga en Tesorería → Pagos, como cualquier otra.",
   ]},
   {"tipo": "criterio", "html":
    "Un reintegro se puede pagar en partes: el saldo es lo aprobado menos lo que está en órdenes no "
    "anuladas. Anular la orden lo devuelve a la lista. Pagar la orden no cambia el estado del reintegro "
    "(«con orden»)."},
 ]},

]
