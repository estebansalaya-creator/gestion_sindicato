"""ayuda_padron.py — Manual del Padrón de Afiliados."""

CLAVE = "padron"
MODULO = "Padrón de Afiliados"

INTRO = """
<p>El padrón tiene <b>una fila por persona</b>: los afiliados titulares y sus familiares a
cargo. El grupo familiar lo da el CUIL del titular; el titular tiene parentesco «Titular» y es
su propio titular. Todos los de esta base son afiliados al gremio: no hay una marca aparte.</p>
<p>Hay dos formas de entrar: la <b>Consulta del Padrón</b> muestra listado y ficha sin poder
cambiar nada; el <b>ABM de Afiliados</b> es la misma pantalla con la edición. Quien tiene el ABM
también ve los botones de editar desde la consulta.</p>
"""

CIRCUITO = [
    ("Alta", "Documento, sexo y CUIL; ARCA completa nombre, nacimiento y domicilio."),
    ("Grupo y empleo", "Los familiares a cargo y el historial de empleadores."),
    ("Seguimiento", "Documentación, aportes de la DDJJ de OSEDA, contactos y auditoría."),
    ("Baja", "Con fecha y motivo; nunca se borra."),
]

SECCIONES = [

{
 "grupo": "Padrón",
 "id": "pad_listado",
 "titulo": "Consulta del Padrón y listado",
 "url": "/afiliados/padron",
 "endpoints": ["afiliados.padron"],
 "resumen": "Buscar y filtrar el padrón; abrir la ficha de una persona.",
 "bloques": [
   {"tipo": "texto", "html":
    "El listado se pagina en el servidor (50 por página): los filtros, el orden y la página quedan en "
    "la dirección. <b>Exportar a Excel</b> baja todo lo filtrado."},
   {"tipo": "campos", "items": [
     ("Buscar", "Cada palabra en apellido y nombres, localidad o empleador; los números (sin guiones) "
      "en CUIL, CUIL del titular y documento."),
     ("Estado", "Activos (por defecto), de baja o todos."),
     ("Titular o familiar · Sexo · Edad desde / hasta", "Para armar listas: hijos de cierta edad, "
      "titulares mujeres, etc."),
     ("Atributo", "Los que tienen una marca: Tiene hijos, Judicializado, Amparo, Seguimiento."),
   ]},
   {"tipo": "texto", "html":
    "En la consulta, el ojo abre la ficha de solo lectura. Quien no tiene el ABM y abre un enlace de "
    "edición llega igual a la consulta de esa persona."},
 ]},

{
 "grupo": "Padrón",
 "id": "pad_alta",
 "titulo": "ABM de Afiliados: alta y ficha",
 "url": "/afiliados",
 "endpoints": ["afiliados.abm_afiliados"],
 "resumen": "Cargar una persona: documento, sexo, CUIL y lo que completa ARCA.",
 "bloques": [
   {"tipo": "pasos", "items": [
     "<b>Nuevo afiliado</b>. La ficha empieza por <b>Identificación</b>: tipo de documento, número y "
     "sexo, en ese orden.",
     "Con DNI, LE o LC el <b>CUIL se calcula solo</b> (20 varón, 27 mujer; 23 cuando el dígito no "
     "entra). Un CUIL escrito a mano no se pisa.",
     "Con documento y sexo el sistema le <b>pregunta a ARCA</b>: el CUIL que tiene ese documento "
     "(puede no ser el calculado; si hay varios, se elige) y sus datos completan lo vacío — apellido "
     "y nombres, nacimiento y domicilio fiscal (solo si el domicilio está vacío entero).",
     "Completá el <b>Grupo familiar</b> (parentesco; un familiar lleva el CUIL de su titular), el "
     "empleador, la fecha de alta y lo demás, y <b>Guardar cambios</b>.",
   ]},
   {"tipo": "campos", "items": [
     ("Consultar ARCA", "Pregunta a pedido, también en una ficha ya cargada."),
     ("Ya está en el padrón", "Si el CUIL ya existe, avisa con el enlace a esa ficha y no completa nada."),
     ("ARCA dice distinto", "Lo cargado no se pisa: se lista lo diferente con <b>Usar los datos de ARCA</b>."),
     ("Fallecimiento · clave no activa", "Si ARCA los informa, se avisan."),
     ("Agregar familiar", "Desde la ficha del titular: abre un alta con el grupo y el domicilio del titular."),
   ]},
   {"tipo": "criterio", "html":
    "<b>Apellido y nombres</b> van en un solo campo, primero el apellido, como en el DNI: los "
    "apellidos compuestos hacen imposible partirlos por regla. El <b>empleador</b> de la ficha es el de "
    "la relación laboral vigente más nueva: en el alta se carga y crea la primera relación; después se "
    "cambia en la solapa Empleadores."},
   {"tipo": "aviso", "html":
    "La consulta a ARCA necesita el certificado del sindicato habilitado para el padrón de ARCA. "
    "Mientras no esté, el CUIL se calcula igual y la pantalla lo dice. Cambiar el CUIL de un titular "
    "arrastra el de su grupo y sus relaciones laborales."},
 ]},

{
 "grupo": "Padrón",
 "id": "pad_solapas",
 "titulo": "Las solapas de la ficha",
 "url": "",
 "endpoints": [],
 "resumen": "Grupo familiar, empleadores, documentación, aportes, contactos y movimientos.",
 "bloques": [
   {"tipo": "campos", "items": [
     ("Grupo familiar", "El titular y sus familiares, con parentesco y estado."),
     ("Empleadores", "El historial laboral: empleador, desde, hasta, categoría. No se aceptan dos "
      "períodos superpuestos con el mismo empleador, y el empleador tiene que estar dado de alta. "
      "Vigente = activa y sin egreso (o con egreso de hoy en adelante). Se muestra también la "
      "antigüedad, que puede venir de la DDJJ."),
     ("Documentación", "PDF o imagen de hasta 10 MB: DNI, partidas, certificados de estudio. La ve "
      "quien consulta el padrón; la sube y la borra quien tiene el ABM."),
     ("Aportes OSEDA", "Aparece si la persona (o su titular) tiene DDJJ en OSEDA: período por período, "
      "lo declarado, lo transferido por ARCA, la diferencia y la cuota sindical liquidada. La "
      "diferencia sale del empleador; hasta $ 1,50 es redondeo."),
     ("Contactos", "Teléfonos y correos de la persona."),
     ("Movimientos", "La auditoría: cada cambio, campo por campo, con el valor anterior, el nuevo, "
      "quién y cuándo."),
   ]},
   {"tipo": "criterio", "html":
    "Los aportes son del titular: la ficha de un familiar muestra los del titular, y quien aporta a su "
    "nombre (relación de dependencia o monotributo) tiene su propia grilla."},
 ]},

{
 "grupo": "Padrón",
 "id": "pad_baja",
 "titulo": "Baja y reactivación",
 "url": "",
 "endpoints": [],
 "resumen": "Una persona nunca se borra: se da de baja con fecha y motivo.",
 "bloques": [
   {"tipo": "pasos", "items": [
     "En la ficha, <b>Dar de baja</b>.",
     "Fecha de baja y motivo (los motivos se administran en Tablas Auxiliares).",
     "Si es un titular, se ofrece dar de baja también a su grupo familiar.",
   ]},
   {"tipo": "texto", "html":
    "<b>Reactivar</b> la deja activa otra vez. De una persona cuelgan reintegros, comprobantes y la "
    "historia de la cuota sindical: por eso no se borra nunca."},
 ]},

{
 "grupo": "Análisis",
 "id": "pad_metricas",
 "titulo": "Métricas del Padrón",
 "url": "/afiliados/metricas",
 "endpoints": ["padron_metricas.metricas"],
 "resumen": "Indicadores, altas y bajas, pirámide, empleadores y controles del padrón.",
 "bloques": [
   {"tipo": "texto", "html":
    "Afiliado = <b>titular</b>; los familiares son personas a cargo. Arriba: afiliados activos, "
    "familiares, personas por afiliado, edad promedio, empleadores con afiliados y altas menos bajas. "
    "Abajo: altas y bajas por mes, motivos de baja, edad y sexo, composición del grupo familiar, "
    "antigüedad, provincia, localidad y afiliados por empleador."},
   {"tipo": "campos", "items": [
     ("Estado", "Activos o el padrón completo."),
     ("Personas", "Titulares y familiares, o solo titulares."),
     ("Altas y bajas desde / hasta", "El período de los gráficos de movimientos (por defecto 24 meses)."),
   ]},
   {"tipo": "texto", "html":
    "<b>Controles del padrón</b>: hijos que cumplieron 21, estudiantes de 26, estudiantes sin "
    "certificado del año, familiares sin titular activo, titulares sin empleador vigente, sin CUIL, "
    "CUIL que no verifica, sexo contra el prefijo del CUIL, sin nacimiento, domicilio incompleto, "
    "alta futura y bajas sin motivo. Cada uno abre la lista con el enlace a la ficha."},
   {"tipo": "campos", "items": [
     ("Empleador distinto del que lo declara", "Titulares cuyo empleador en el padrón no es el último "
      "que los declaró en la DDJJ de OSEDA. Se consulta a OSEDA al abrirlo, por eso en la tabla dice "
      "«Se consulta al abrirlo»."),
   ]},
   {"tipo": "criterio", "html":
    "Los indicadores, el bloque de empleadores y los controles son el padrón activo de <b>hoy</b> y no "
    "siguen los filtros; las altas y bajas se cuentan sobre el padrón completo. Un titular con dos "
    "empleos cuenta en los dos empleadores."},
 ]},

{
 "grupo": "Tablas",
 "id": "pad_tablas",
 "titulo": "Tablas Auxiliares",
 "url": "/afiliados/tablas",
 "endpoints": ["afiliados_tablas.tablas"],
 "resumen": "Los catálogos del padrón: estado civil, parentescos, motivos, atributos…",
 "bloques": [
   {"tipo": "texto", "html":
    "Una solapa por catálogo: estado civil, nacionalidades, parentescos, provincias, tipos de "
    "documento, motivos de alta y de baja, atributos y tipos de documentación del afiliado."},
   {"tipo": "criterio", "html":
    "El código de las tablas del padrón de la SSS lo pone quien carga y no se cambia después. Lo que "
    "ya se usa no se borra: se desactiva (si la tabla tiene esa opción). El parentesco «Titular» y el "
    "DNI no se borran nunca."},
 ]},

]
