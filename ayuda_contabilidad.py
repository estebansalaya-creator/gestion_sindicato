"""ayuda_contabilidad.py — Manual de Contabilidad."""

CLAVE = "contabilidad"
MODULO = "Contabilidad"

INTRO = """
<p>El <b>plan de cuentas</b> (vino de AEDA y se completa acá), los <b>ejercicios</b> con sus períodos
mensuales, la <b>carga de asientos</b> y el <b>Libro Diario</b>, con las mismas opciones que el de la obra
social: exportar los asientos, el libro en Excel y PDF, la exportación al sistema contable externo, el
modelo y la importación de asientos, y la renumeración. Los asientos que generó AEDA se traen con un
importador. El Libro Mayor todavía no tiene pantalla.</p>
"""

CIRCUITO = [
    ("Plan de cuentas", "Código y nombre; lo demás sale del código."),
    ("Ejercicio", "Se abre con sus períodos mensuales; uno es el de trabajo."),
    ("Asiento", "Se carga en borrador, balanceado, en un período abierto."),
    ("Confirmado", "Queda en el Libro Diario y en lo que se exporta."),
    ("Cierre", "Un período o ejercicio cerrado no admite asientos."),
]

SECCIONES = [

{
 "grupo": "Contabilidad",
 "id": "con_plan",
 "titulo": "Plan de Cuentas",
 "url": "/contabilidad/plan",
 "endpoints": ["contabilidad.plan"],
 "resumen": "Las cuentas con su código 9-9-9-99-999 y dónde se usa cada una.",
 "bloques": [
   {"tipo": "pasos", "items": [
     "<b>Nueva cuenta</b> (o el botón de agregar de una cuenta, que propone el código de la "
     "siguiente subcuenta).",
     "Escribí el código: se acepta con puntos o sin los ceros de cada tramo («5.3.0.0.14» es "
     "5-3-0-00-014). Mientras se escribe, la pantalla dice qué sale de él.",
     "El nombre, si es monetaria y si está activa. <b>Guardar cambios</b>.",
   ]},
   {"tipo": "criterio", "html":
    "<b>El código manda.</b> El primer tramo es la clase (activo, pasivo, patrimonio, ingresos, egresos); "
    "el nivel es la posición del último tramo distinto de cero; es <b>imputable</b> si el último tramo "
    "no es cero (si no, es un título); es <b>corriente</b> si no empieza con 1-2 ni 2-2. La cuenta madre "
    "es la más cercana que existe recortando el código: crear un título intermedio hace que las cuentas "
    "de debajo pasen a colgar de él."},
   {"tipo": "campos", "items": [
     ("Dónde se usa", "En la ficha: conceptos, motivos, cuentas de fondos, rubros, imputaciones."),
     ("Monetaria", "Viene sugerida (el activo corriente salvo bienes de cambio, y todo el pasivo). "
      "Revisarla con el contador antes del primer ajuste por inflación."),
   ]},
   {"tipo": "aviso", "html":
    "Una cuenta con cuentas debajo o con usos <b>no cambia de código ni se elimina</b>; si la usa algo "
    "vigente, tampoco se desactiva. Dos cuentas con el mismo nombre bajo la misma madre no se aceptan."},
 ]},


{
 "grupo": "Contabilidad",
 "id": "con_ejercicios",
 "titulo": "Ejercicios",
 "url": "/contabilidad/ejercicios",
 "endpoints": ["cont_ej.ejercicios"],
 "resumen": "Los ejercicios contables con sus períodos mensuales, y cuál es el de trabajo.",
 "bloques": [
   {"tipo": "pasos", "items": [
     "<b>Abrir un ejercicio</b>: nombre y fechas de inicio y cierre. Viene propuesto el año siguiente al último "
     "(o el año en curso si no hay ninguno). El CUIT y la razón social son los de Datos del Sindicato.",
     "Se crean los períodos, uno por mes («Enero 2026»), abiertos.",
     "El primero que se abre queda como <b>ejercicio de trabajo</b>: el que muestran el Libro Diario y la carga. "
     "Se cambia con «Hacerlo el ejercicio de trabajo» en la ficha.",
   ]},
   {"tipo": "criterio", "html":
    "Los ejercicios <b>no se superponen</b>: cada fecha es de un solo período. Desde la ficha (el ojo) se "
    "<b>cierran</b>, <b>bloquean</b> y <b>reabren</b> los períodos de a uno; cerrar el ejercicio cierra todos "
    "los suyos. Un período con asientos en borrador no se cierra: primero se confirman o se eliminan."},
   {"tipo": "aviso", "html":
    "Un período cerrado o bloqueado <b>no admite asientos</b>, y Tesorería <b>no anula</b> pagos, ingresos ni "
    "movimientos de esas fechas. Cerrar el ejercicio todavía no genera el asiento de cierre. Un ejercicio con "
    "asientos no se elimina."},
 ]},

{
 "grupo": "Contabilidad",
 "id": "con_asientos",
 "titulo": "Asientos",
 "url": "/contabilidad/asientos",
 "endpoints": ["cont_diario.carga"],
 "resumen": "La carga de un asiento de partida doble, nuevo o la corrección de un borrador.",
 "bloques": [
   {"tipo": "pasos", "items": [
     "Fecha, tipo (apertura, operación, ajuste, cierre, rectificación), referencia y descripción.",
     "Los renglones: la cuenta (solo imputables y activas), el detalle y el importe en el debe o en el haber. "
     "<b>Agregar renglón</b> propone lo que falta para balancear.",
     "<b>Guardar en borrador</b>, <b>Guardar y cargar otro</b> o <b>Guardar y confirmar</b> (solo si balancea).",
   ]},
   {"tipo": "criterio", "html":
    "El <b>período sale de la fecha</b> y tiene que estar abierto. El <b>número</b> es el siguiente del "
    "ejercicio. Hacen falta al menos dos renglones y el debe igual al haber, al centavo. Un borrador se "
    "corrige o se elimina; un confirmado ya no (la anulación todavía no tiene pantalla)."},
   {"tipo": "campos", "items": [
     ("Copiar en uno nuevo", "Desde la ficha de un asiento: arma uno nuevo con los mismos renglones y la fecha de hoy."),
   ]},
 ]},

{
 "grupo": "Contabilidad",
 "id": "con_diario",
 "titulo": "Libro Diario",
 "url": "/contabilidad/diario",
 "endpoints": ["cont_diario.diario", "cont_diario.asiento"],
 "resumen": "Los asientos del ejercicio, sus exportaciones y la importación.",
 "bloques": [
   {"tipo": "texto", "html":
    "Muestra el <b>ejercicio de trabajo</b> (o el que se elija, o todos), con filtros por período, estado, "
    "tipo y fechas. Arriba, los asientos, los borradores, el total confirmado y los que no balancean. El ojo "
    "abre el asiento con sus renglones."},
   {"tipo": "campos", "items": [
     ("Libro Diario Excel / PDF", "El libro con los filtros de arriba (sin los anulados): cada asiento con sus renglones."),
     ("Asientos Excel / CSV", "Los confirmados del filtro con las columnas del archivo de importación: lo exportado se puede volver a importar."),
     ("Exportar al sistema contable externo", "Los confirmados de un rango de fechas (obligatorio) en el formato de intercambio: la cuenta sin guiones, la fecha como texto, los textos a ancho fijo."),
     ("Modelo para importar", "El archivo de ejemplo con las columnas: N° de asiento (solo agrupa), fecha, tipo, descripción, referencia, código de cuenta, detalle, debe, haber."),
     ("Importar asientos", "Un .xlsx o .csv. Cada asiento entra en <b>borrador</b>, en el período de su fecha y con su número del ejercicio; los que tienen errores se informan y no frenan a los demás."),
     ("Confirmar los borradores", "Confirma los borradores del filtro de una vez; los que no balancean quedan en borrador."),
     ("Renumerar el ejercicio", "Ordena los números del ejercicio: la apertura primero, el resto por fecha. Los números de AEDA se pierden."),
   ]},
   {"tipo": "aviso", "html":
    "Los asientos de AEDA (pagos, pases, ingresos, depósitos) se traen con <b>importar_aeda_asientos.py</b>: "
    "con su número y referencia de AEDA, confirmados si balancean. Los pagos de reintegros, que AEDA deja sin "
    "cuenta, se imputan al gasto del concepto del reintegro. Todavía no tienen pantalla la anulación de un "
    "asiento confirmado ni el libro de trabajo (los asientos que generarían las operaciones)."},
 ]},

]
