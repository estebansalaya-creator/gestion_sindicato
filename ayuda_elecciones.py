"""ayuda_elecciones.py — Manual de Elecciones (configuración, padrón electoral y mesa de votación)."""

CLAVE = "elecciones"
MODULO = "Elecciones"

INTRO = """
<p>Las <b>elecciones del gremio</b>: se cargan con su motivo y el día de la votación, se arma el
<b>padrón electoral</b> con los afiliados que pueden votar y, el día de la votación, en la
<b>mesa</b> se marca a cada afiliado que vino a votar.</p>
"""

CIRCUITO = [
    ("Elección", "Motivo, día de la votación, lugar y horario, corte del padrón y antigüedad mínima."),
    ("Padrón", "Se arma solo al guardar: los afiliados titulares de alta al corte, con la antigüedad pedida."),
    ("Votación", "En la mesa se busca a cada uno y se registra que votó, con la hora y quién lo marcó."),
    ("Cierre", "Terminada la votación se cierra: ya no se registran votos y queda la participación."),
]

SECCIONES = [

{
 "grupo": "Elecciones",
 "id": "el_elecciones",
 "titulo": "Elecciones y Padrón",
 "url": "/elecciones",
 "endpoints": ["elecciones.listado", "elecciones.nueva"],
 "resumen": "Cargar una elección y armar su padrón electoral.",
 "bloques": [
   {"tipo": "texto", "html":
    "La lista tiene todas las elecciones, con el día, cuántos hay en el padrón, cuántos votaron y el estado. "
    "<b>Nueva elección</b> pide:"},
   {"tipo": "campos", "items": [
     ("Motivo", "Para qué es la elección: renovación de la Comisión Directiva, delegados, una asamblea…"),
     ("Día de la votación", "El único día en que se registran votos (salvo el Administrador, ver la mesa)."),
     ("Abre, cierra y lugar", "Opcionales: se muestran en la ficha y en la mesa."),
     ("Corte del padrón", "Entran los afiliados que lo eran a esa fecha. Vacío, el día de la votación."),
     ("Antigüedad mínima", "Meses en el gremio al corte (por la fecha de alta). 0 = sin mínimo."),
   ]},
   {"tipo": "criterio", "html":
    "Al guardar se arma el <b>padrón electoral</b>: los afiliados <b>titulares</b> (los familiares a cargo no "
    "votan) con el alta hecha al corte, que no estaban de baja y que tienen la antigüedad pedida. Sin fecha de "
    "alta entran solo si no se pide antigüedad. Cada uno lleva un <b>número de orden</b> alfabético."},
 ]},

{
 "grupo": "Elecciones",
 "id": "el_ficha",
 "titulo": "Ficha de la elección",
 "url": "/elecciones",
 "endpoints": ["elecciones.ficha"],
 "resumen": "El padrón electoral, quién votó, los datos y los movimientos.",
 "bloques": [
   {"tipo": "texto", "html":
    "El padrón es una <b>foto</b> del padrón de afiliados del momento en que se generó: lo que cambie después en "
    "el padrón de afiliados no lo toca. La solapa <b>Padrón electoral</b> muestra cada afiliado con su orden, "
    "documento, empleador, si tiene <b>OSEDA</b> y si votó (hora y quién lo registró); se filtra por «Votaron» / "
    "«No votaron» y por «Con OSEDA» / «Sin OSEDA», y se exporta a Excel con los filtros puestos."},
   {"tipo": "criterio", "html":
    "La columna <b>OSEDA</b> dice si el afiliado está <b>hoy</b> en el padrón de la obra social OSEDA: «Sí» (titular), «Sí, familiar» "
    "(está como familiar de otro titular), «De baja» (con la fecha) o «No». Se consulta cada vez que se abre la "
    "ficha, no es parte de la foto del padrón. Si la consulta no responde, la columna sale con «—» y un aviso."},
   {"tipo": "pasos", "items": [
     "<b>Volver a generar</b>: rehace el padrón con el padrón de afiliados de hoy. Solo mientras nadie votó, y se "
     "pierden los agregados y quitados a mano.",
     "<b>Agregar al padrón</b> (abajo de la grilla): un titular que no entró, por CUIL o documento, con el motivo.",
     "<b>Quitar del padrón</b> (el tacho): solo a quien no votó, con el motivo.",
     "<b>Quitar el voto</b>: si se marcó a alguien por error, con el motivo.",
     "En <b>Datos de la elección</b> se corrigen los datos. Cambiar el corte o la antigüedad vuelve a generar el "
     "padrón; con votos registrados, el día, el corte y la antigüedad ya no se cambian.",
     "<b>Cerrar la elección</b> al terminar: ya no se registran ni se quitan votos. El Administrador la puede "
     "reabrir. <b>Anular</b> pide el motivo.",
   ]},
   {"tipo": "aviso", "html":
    "Todo lo que se hace con el padrón queda en la solapa <b>Movimientos</b>: cada voto, cada voto quitado y cada "
    "agregado o quitado, con la fecha, el usuario y el motivo."},
 ]},

{
 "grupo": "Elecciones",
 "id": "el_mesa",
 "titulo": "Mesa de Votación",
 "url": "/elecciones/votacion",
 "endpoints": ["elecciones.mesa_inicio", "elecciones.mesa"],
 "resumen": "El día de la votación: buscar al afiliado y registrar que votó.",
 "bloques": [
   {"tipo": "texto", "html":
    "Si hoy hay una sola elección, la mesa abre directo; si no, se elige. Arriba, el padrón, cuántos votaron "
    "y cuántos faltan; abajo, los últimos votos. Se actualiza solo: pueden trabajar varias mesas a la vez."},
   {"tipo": "pasos", "items": [
     "Escribí el <b>documento</b>, el <b>CUIL</b>, el <b>número de orden</b> o el <b>apellido</b> de quien viene "
     "a votar. Busca mientras escribís; Enter busca enseguida.",
     "Controlá que sea la persona y apretá <b>Registrar voto</b> (si hay uno solo, Enter otra vez). Queda la hora "
     "y tu usuario, y la búsqueda se limpia para el siguiente.",
     "Si otra mesa ya lo había marcado, avisa a qué hora y quién: no se marca dos veces.",
     "Si se marcó a alguien por error, buscalo y quitale el voto (el ícono de la fila), con el motivo.",
   ]},
   {"tipo": "criterio", "html":
    "Si el documento no está en el padrón electoral, la mesa dice por qué: es familiar a cargo, estaba de baja "
    "al corte, el alta es posterior, no tiene la antigüedad o no está en el padrón de afiliados. Si corresponde "
    "que vote, se lo agrega desde la ficha de la elección."},
   {"tipo": "aviso", "html":
    "Los votos se registran <b>el día de la votación</b>. Otro día solo puede el Administrador (por ejemplo, para "
    "pasar un acta en papel), y la pantalla lo avisa. Cerrada la elección, la mesa ya no registra nada."},
 ]},

]
