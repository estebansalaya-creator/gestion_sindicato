"""ayuda_mesa.py — Manual de la Mesa de Entradas."""

CLAVE = "mesa"
MODULO = "Mesa de Entradas"

INTRO = """
<p>Cada comprobante de un proveedor que entra al sindicato abre un <b>expediente</b>
(EXP-AAAA-NNNNNN) en la mesa de entradas. El expediente es el legajo del comprobante:
dónde está, quién lo tiene, qué se dijo de él y en qué estado quedó, desde que se carga
hasta que se paga.</p>
<p>Los expedientes se crean solos al cargar un comprobante (Proveedores → Carga de
Comprobantes); en la mesa se siguen, se derivan y se resuelven.</p>
"""

CIRCUITO = [
    ("Ingreso", "Se carga el comprobante: nace el expediente, en estado «Ingresado»."),
    ("Revisión", "Se deriva a un área o a una persona; se observa, se anotan notas."),
    ("Resolución", "Se aprueba, se rechaza o se archiva."),
    ("Parte contable", "Liquidado y pagado ya los maneja el circuito de pagos."),
]

SECCIONES = [

{
 "grupo": "Expedientes",
 "id": "mesa_bandeja",
 "titulo": "Expedientes (bandeja)",
 "url": "/mesa",
 "endpoints": ["mesa.bandeja"],
 "resumen": "Todos los expedientes con su estado y a dónde están derivados.",
 "bloques": [
   {"tipo": "texto", "html":
    "Arriba, la cantidad de expedientes y el importe total de lo filtrado. La grilla muestra el "
    "número de expediente, el comprobante (tipo, número, fecha de emisión y sus marcas), el "
    "proveedor, la fecha de ingreso, el importe, el estado y el destino."},
   {"tipo": "campos", "items": [
     ("Buscar", "Por número de expediente o de comprobante, proveedor o CUIT."),
     ("Estado", "Por defecto, lo que todavía está en la mesa: ingresado, en revisión, aprobado y rechazado."),
     ("Área destino · Usuario destino", "Lo que tiene un área o una persona: la bandeja de cada uno."),
     ("Ingresado desde / hasta", "Por fecha de ingreso (con <b>Filtrar</b>)."),
     ("Cargar comprobante", "Lleva a la carga de comprobantes, que crea el expediente."),
   ]},
   {"tipo": "campos", "items": [
     ("Escudo", "El comprobante se constató con ARCA."),
     ("Robot", "El PDF se leyó y dice lo mismo que los datos cargados."),
     ("Ojo", "Alguien lo verificó a ojo."),
   ]},
   {"tipo": "aviso", "html":
    "Los reintegros y subsidios que vinieron de AEDA tienen expediente pero no se ven en la bandeja: "
    "se siguen en Reintegros. Su expediente se abre igual desde el enlace."},
 ]},

{
 "grupo": "Expedientes",
 "id": "mesa_expediente",
 "titulo": "El expediente",
 "url": "",
 "endpoints": ["mesa.detalle"],
 "resumen": "El comprobante, su PDF, la liquidación y el historial de movimientos.",
 "bloques": [
   {"tipo": "texto", "html":
    "La ficha muestra el expediente (número, estado, destino, quién lo cargó), el comprobante con "
    "sus importes, el PDF, la liquidación (lo que se le va a pagar y con qué imputación) y todos los "
    "movimientos, del más nuevo al más viejo."},
   {"tipo": "campos", "items": [
     ("Derivación", "Lo manda a un área o a una persona. Pide el destino. Pasa a «En revisión»."),
     ("Observación", "Deja un comentario sin cambiar el estado. Pide el texto."),
     ("Aprobación", "Pasa a «Aprobado»."),
     ("Rechazo", "Pasa a «Rechazado». Pide el motivo."),
     ("Archivo", "Pasa a «Archivado»: no sigue."),
     ("Nota", "Un apunte en el historial. Pide el texto."),
   ]},
   {"tipo": "pasos", "items": [
     "En <b>Nuevo movimiento</b> elegí el tipo.",
     "Completá el destino (en una derivación) o el texto (observación, rechazo, nota).",
     "<b>Registrar movimiento</b>. Queda con la fecha y el usuario.",
   ]},
   {"tipo": "campos", "items": [
     ("Reemplazar PDF", "Adjunta el PDF si faltaba o lo cambia, mientras la liquidación siga abierta "
      "y el PDF no se haya confirmado."),
     ("Anular expediente", "Anula expediente y comprobante con un motivo. Solo mientras la liquidación "
      "esté abierta y el comprobante no esté en una orden de pago. No se borra nada."),
   ]},
   {"tipo": "criterio", "html":
    "<b>Liquidado</b> y <b>pagado</b> son estados de la parte contable: un movimiento de la mesa queda "
    "registrado pero no hace retroceder el estado. Las operaciones de pago nunca son movimientos de la "
    "mesa: se hacen en Tesorería → Pagos."},
 ]},

]
