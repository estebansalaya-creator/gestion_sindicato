"""ayuda_contabilidad.py — Manual de Contabilidad."""

CLAVE = "contabilidad"
MODULO = "Contabilidad"

INTRO = """
<p>Por ahora el módulo tiene el <b>plan de cuentas</b>, que vino del sistema anterior (AEDA) y se
completa acá. De él toman su cuenta los conceptos de gasto, los motivos de ingreso, las cuentas
de fondos, los rubros de proveedores y las imputaciones de pagos. Ejercicios, asientos y los
libros Diario y Mayor están en el menú y todavía no tienen pantalla.</p>
"""

CIRCUITO = [
    ("Código", "Se escribe el código y el nombre."),
    ("Lo que sale del código", "Clase, nivel, cuenta madre, si es imputable y si es corriente."),
    ("Uso", "Las demás pantallas eligen entre las imputables y activas."),
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

]
