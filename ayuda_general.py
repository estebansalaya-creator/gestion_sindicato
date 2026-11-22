"""ayuda_general.py — Manual «Uso del sistema»: lo que vale en todas las pantallas."""

CLAVE = "general"
MODULO = "Uso del sistema"

INTRO = """
<p>Este manual explica lo que es igual en todas las pantallas: cómo se entra, cómo se
busca, cómo se leen y se filtran las grillas, qué significa cada botón y de dónde salen
los permisos. Los demás manuales, uno por módulo del menú, explican cada pantalla.</p>
<p>En cualquier pantalla, el botón <b>Ayuda</b> de abajo a la derecha (o la tecla
<b>F1</b>) abre el manual justo en la sección de esa pantalla.</p>
"""

CIRCUITO = [
    ("Ingresar", "Con el correo y la contraseña que da el administrador del sistema."),
    ("Elegir la pantalla", "Desde el menú de la izquierda o con su buscador de opciones."),
    ("Buscar", "Un afiliado, un empleador o un proveedor desde el buscador de la barra."),
    ("Trabajar", "Grillas con los mismos filtros y botones en todas las pantallas."),
]

SECCIONES = [

{
 "grupo": "Primeros pasos",
 "id": "gen_ingreso",
 "titulo": "Ingreso y salida",
 "url": "",
 "endpoints": [],
 "resumen": "Con qué se entra, cuánto dura la sesión y cómo se sale.",
 "bloques": [
   {"tipo": "texto", "html":
    "Se entra con el <b>correo</b> y la <b>contraseña</b> que da de alta el administrador del "
    "sistema (Administración del Sistema → Usuarios). No hay ingreso con Google ni registro propio: "
    "si alguien necesita usuario, se lo pide al administrador."},
   {"tipo": "campos", "items": [
     ("Inicio", "El panel de inicio con tus accesos directos o, si no fijaste ninguno, el Panel de "
                "Fiscalización. Es también a donde se llega al ingresar."),
     ("Volver", "Aparece cuando hay una pantalla anterior y lleva a ella. La tecla <b>Esc</b> hace lo "
                "mismo (si hay un diálogo abierto, primero lo cierra)."),
     ("Salir", "Cierra la sesión. Conviene usarlo en una computadora compartida."),
     ("Ayuda (abajo a la derecha)", "Abre el manual en la sección de la pantalla actual; donde no hay "
      "manual, la lista de todos. También con <b>F1</b>."),
   ]},
   {"tipo": "aviso", "html":
    "La contraseña se cambia desde Usuarios (la cambia el administrador). Si se olvidó, no hay "
    "recuperación por correo: se pide una nueva."},
 ]},

{
 "grupo": "Primeros pasos",
 "id": "gen_menu",
 "titulo": "El menú y los permisos",
 "url": "",
 "endpoints": [],
 "resumen": "Qué opciones aparecen, cómo se buscan y qué pasa con una pantalla pendiente.",
 "bloques": [
   {"tipo": "texto", "html":
    "El menú de la izquierda tiene los módulos (Mesa de Entradas, Fiscalización de Cuotas, "
    "Empleadores, Padrón de Afiliados, Proveedores, Tesorería, Contabilidad, Administración) y "
    "dentro de cada uno sus pantallas. Lo que queda abierto se recuerda de una vez para la otra."},
   {"tipo": "campos", "items": [
     ("Buscar opción del menú", "El cuadro de arriba del menú filtra las pantallas mientras se "
      "escribe: cada palabra tiene que estar en la opción o en su rama («recibos fisca»). Con las "
      "flechas se elige, <b>Enter</b> va y <b>Esc</b> limpia."),
     ("Una opción que no está", "Si una pantalla no aparece en el menú, el usuario no tiene ese permiso."),
   ]},
   {"tipo": "criterio", "html":
    "<b>El permiso es la opción de menú.</b> Quien tiene la opción «ABM de Afiliados» puede editar "
    "afiliados; quien solo tiene «Consulta del Padrón» los ve sin poder cambiarlos. Los permisos "
    "se asignan por rol y, de a uno, por usuario (Administración del Sistema). El sistema vuelve a "
    "leerlos <b>cada minuto</b>: un permiso nuevo aparece solo, sin salir y volver a entrar. "
    "Las acciones se controlan también en el servidor: esconder un botón no es la única barrera."},
   {"tipo": "aviso", "html":
    "Algunas opciones del menú todavía no tienen pantalla (por ejemplo Ejercicios, Asientos o "
    "Sueldos). Al abrirlas se ve el aviso <b>«Esta pantalla está prevista pero todavía no está "
    "desarrollada»</b>: no es un error ni un enlace roto."},
 ]},

{
 "grupo": "Primeros pasos",
 "id": "gen_inicio",
 "titulo": "Panel de inicio y accesos directos",
 "url": "",
 "endpoints": ["menu"],
 "resumen": "Las pantallas de todos los días, a un clic desde Inicio.",
 "bloques": [
   {"tipo": "pasos", "items": [
     "Pasá el mouse por una pantalla del menú de la izquierda: a la derecha del nombre aparece una "
     "<b>chincheta</b>.",
     "Un clic la fija en el panel de inicio (la chincheta queda llena). Otro clic la saca.",
     "<b>Inicio</b> muestra las fijadas como tarjetas, agrupadas por módulo. Se ordenan "
     "<b>arrastrándolas</b> dentro de su módulo y se sacan con la <b>X</b> de la tarjeta.",
   ]},
   {"tipo": "criterio", "html":
    "Cada uno tiene sus propios accesos. Fijar una pantalla no da permiso sobre nada: si a alguien le "
    "sacan una pantalla, su tarjeta deja de verse sola (y vuelve si le devuelven el permiso). Se fijan "
    "pantallas, no las ramas del menú."},
   {"tipo": "aviso", "html":
    "Quien no fijó ninguna pantalla entra al Panel de Fiscalización, como siempre. Desde el panel de "
    "inicio, el botón <b>Panel de Fiscalización</b> lleva a él (también se puede fijar)."},
 ]},

{
 "grupo": "Primeros pasos",
 "id": "gen_buscador",
 "titulo": "El buscador general",
 "url": "",
 "endpoints": [],
 "resumen": "Encuentra afiliados, empleadores y proveedores desde cualquier pantalla.",
 "bloques": [
   {"tipo": "texto", "html":
    "El cuadro <b>«Buscar CUIL, CUIT, DNI o nombre…»</b> de la barra de arriba busca solo, un "
    "momento después de dejar de escribir, y muestra los resultados agrupados: afiliados, "
    "empleadores y proveedores."},
   {"tipo": "lista", "items": [
     "Por nombre, <b>cada palabra tiene que estar</b> y en cualquier orden: «camila ali» encuentra a "
     "ALI CAMILA AILEN.",
     "Por número, con o sin puntos y guiones: «27-41380797-8», «41.380.797» o una parte, como «4138».",
     "Se puede combinar: «ali 4138».",
     "Con las flechas se recorre la lista y <b>Enter</b> abre el elegido; con Ctrl o el botón del "
     "medio del mouse se abre en otra pestaña. <b>Esc</b> la cierra.",
   ]},
   {"tipo": "criterio", "html":
    "Solo aparece lo que el usuario puede abrir: sin acceso al padrón no se buscan afiliados, y así "
    "con el resto. El afiliado lleva a su ficha; el empleador, a su ficha; el proveedor, a su cuenta "
    "corriente (o a la ficha). Un familiar muestra su parentesco y una baja se marca en rojo."},
 ]},

{
 "grupo": "Pantallas",
 "id": "gen_grillas",
 "titulo": "Grillas, filtros y Excel",
 "url": "",
 "endpoints": [],
 "resumen": "Cómo se buscan, ordenan, filtran y exportan las listas.",
 "bloques": [
   {"tipo": "texto", "html":
    "Todas las listas tienen la misma barra arriba: el cuadro de búsqueda, los filtros propios de "
    "la pantalla, <b>Filtrar</b> y <b>Quitar filtro</b>, el contador de registros, "
    "<b>Exportar a Excel</b> y la cantidad de filas por página."},
   {"tipo": "campos", "items": [
     ("Buscar", "Filtra mientras se escribe, en todas las columnas de la grilla."),
     ("Filtros con lista o casilla", "Se aplican solos al elegir."),
     ("Fechas y períodos", "Esperan a <b>Filtrar</b>: un rango son dos campos y no se busca con uno solo."),
     ("Quitar filtro", "Vuelve la grilla a como estaba al entrar."),
     ("Encabezados", "Un clic ordena por esa columna (⇅); otro clic invierte el orden (▲ ▼)."),
     ("Exportar a Excel", "Baja lo que muestra la grilla con los filtros aplicados, <b>todas las "
      "páginas</b>, no solo la que se ve."),
     ("Filas por página", "Cuántos renglones se ven a la vez."),
   ]},
   {"tipo": "texto", "html":
    "En las grillas anchas aparece una segunda barra de desplazamiento <b>arriba</b>, para correr "
    "las columnas sin bajar hasta el final."},
   {"tipo": "criterio", "html":
    "Las listas grandes (el padrón, la mesa de entradas) se paginan en el servidor: los filtros, el "
    "orden y la página quedan en la dirección de la pantalla, así que se pueden guardar o compartir "
    "tal cual. En esas, el Excel también trae todo lo filtrado."},
 ]},

{
 "grupo": "Pantallas",
 "id": "gen_acciones",
 "titulo": "Los botones de cada renglón",
 "url": "",
 "endpoints": [],
 "resumen": "Cada acción tiene siempre el mismo ícono y el mismo color.",
 "bloques": [
   {"tipo": "texto", "html":
    "La primera columna de las grillas (<b>Acciones</b>) tiene los botones del renglón. Pasando el "
    "mouse por encima se lee qué hace cada uno."},
   {"tipo": "campos", "items": [
     ("Ojo verde", "Ver: abre la ficha o el detalle."),
     ("Lápiz azul", "Editar."),
     ("Tacho rojo", "Borrar. Pide confirmación. Lo que ya se usó en otro lado no se borra: se da de baja."),
     ("Prohibido rojo", "Dar de baja (queda en el historial, se puede reactivar)."),
     ("Flecha verde", "Reactivar lo dado de baja."),
     ("Más azul", "Agregar."),
     ("PDF rojo · planilla verde", "Bajar el PDF o el Excel."),
     ("Reloj", "Historial o auditoría de cambios."),
     ("Eslabón azul · eslabón roto rojo", "Ver aplicaciones · desaplicar (cuentas corrientes)."),
   ]},
   {"tipo": "criterio", "html":
    "<b>Nada se borra si ya se usó.</b> Un afiliado, un proveedor, un pago o un recibo se dan de baja "
    "o se anulan con un motivo, y queda el rastro de quién y cuándo. Borrar solo se puede con lo que "
    "nunca tuvo movimiento."},
 ]},

{
 "grupo": "Pantallas",
 "id": "gen_formularios",
 "titulo": "Formularios y avisos",
 "url": "",
 "endpoints": [],
 "resumen": "Cómo se carga, qué controla el sistema y cómo se leen los mensajes.",
 "bloques": [
   {"tipo": "lista", "items": [
     "Los campos con <b>*</b> son obligatorios. Si falta uno en una solapa cerrada, al guardar el "
     "sistema abre esa solapa y lleva el cursor al campo.",
     "Los importes se escriben con coma decimal; los puntos de miles se ponen solos.",
     "Un CUIL, CUIT o CBU se controla mientras se escribe (dígito verificador) y se avisa debajo del campo.",
     "Las fichas largas van en <b>solapas</b> (Datos, Contactos, Documentación…); el número al lado "
     "de cada una dice cuántos registros tiene.",
   ]},
   {"tipo": "campos", "items": [
     ("Verde", "Se hizo lo pedido."),
     ("Ámbar", "Se hizo, pero hay algo para revisar; o una advertencia que se puede pasar."),
     ("Rojo", "No se hizo: el mensaje dice por qué."),
     ("Azul", "Información."),
   ]},
   {"tipo": "aviso", "html":
    "Un proceso largo (importar, liquidar, generar) muestra un cartel de espera. No conviene "
    "recargar ni apretar dos veces: el sistema ya está trabajando."},
 ]},

{
 "grupo": "Pantallas",
 "id": "gen_mensajes",
 "titulo": "Mensajes",
 "url": "/mensajes",
 "endpoints": ["mensajes.index"],
 "resumen": "Mensajes internos entre los usuarios del sistema: conversaciones de a dos y grupos.",
 "bloques": [
   {"tipo": "texto", "html":
    "El botón <b>Mensajes</b> de la barra de arriba abre las conversaciones. El número rojo dice cuántas "
    "tienen algo sin leer; se actualiza solo, y suena cuando llega algo nuevo (la campanita lo apaga). "
    "Se le puede escribir a cualquier usuario activo que también tenga Mensajes."},
   {"tipo": "pasos", "items": [
     "<b>Nuevo</b>: elegí a la persona y escribí. Si ya tenían una conversación, se abre esa.",
     "<b>Grupo</b>: ponele un nombre y elegí a los integrantes. Quien lo arma lo administra: agrega, saca "
     "y le cambia el nombre.",
     "<b>Enter</b> manda el mensaje; <b>Shift+Enter</b> baja de renglón.",
   ]},
   {"tipo": "campos", "items": [
     ("Clip", "Adjunta un PDF, una imagen, un Word, un Excel, un CSV o un texto (hasta 20 MB). También se "
      "puede arrastrar el archivo o pegar una captura."),
     ("Micrófono", "Graba un mensaje de voz (hasta 5 minutos)."),
     ("✓✓", "El mensaje ya lo leyeron."),
     ("En línea / Últ. vez", "Si la otra persona está usando el sistema, o cuándo se la vio por última vez."),
     ("Silenciar", "La conversación deja de sumar al número de la barra y de sonar."),
     ("Eliminar", "Quien mandó un mensaje lo puede retirar: queda «Mensaje eliminado» y el archivo deja de verse."),
   ]},
   {"tipo": "aviso", "html":
    "Es para el trabajo interno: lo que hace falta dejar asentado (una autorización, un expediente) va "
    "en su pantalla, no en un mensaje."},
 ]},

]
