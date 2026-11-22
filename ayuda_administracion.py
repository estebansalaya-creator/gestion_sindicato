"""ayuda_administracion.py — Manual de Administración del Sistema."""

CLAVE = "administracion"
MODULO = "Administración del Sistema"

INTRO = """
<p>Quién entra al sistema y qué puede hacer: usuarios, roles, permisos por usuario y el menú. Además,
las áreas (para la mesa de entradas), los talonarios de comprobantes y los datos del sindicato
que salen en los documentos.</p>
<p><b>El permiso es la opción de menú</b>: a cada usuario se le dan opciones del menú, y con eso ve la
pantalla y puede usarla. No hay otra tabla de permisos. <b>El rol no da pantallas</b>: dice el nivel de la
persona (el Administrador puede anular pagos, reabrir conciliaciones, etc.).</p>
"""

CIRCUITO = [
    ("Usuario", "Alta con correo, contraseña y rol; puede copiar las pantallas de otro usuario."),
    ("Permisos por usuario", "Las pantallas que ve cada persona."),
    ("Roles", "El nivel de cada persona: qué puede autorizar."),
    ("Vigencia", "Los permisos se vuelven a leer cada minuto."),
]

SECCIONES = [

{
 "grupo": "Accesos",
 "id": "adm_usuarios",
 "titulo": "Usuarios",
 "url": "/admin/usuarios",
 "endpoints": ["admin.usuarios"],
 "resumen": "Alta de usuarios, contraseña, rol y de quién copia las pantallas.",
 "bloques": [
   {"tipo": "campos", "items": [
     ("Correo", "Es el usuario para entrar. En minúsculas y único."),
     ("Contraseña", "Obligatoria en el alta, de 8 caracteres como mínimo. Para cambiarla se escribe una nueva."),
     ("Roles", "Los que tiene. Un rol inactivo que ya tenía se conserva. El rol no da pantallas."),
     ("Copiar los permisos de", "Solo en el alta: el usuario nuevo arranca con las mismas pantallas que la "
      "persona elegida. Al dar de alta se abre Permisos por Usuario para ajustarlas."),
     ("Opciones de menú · Áreas", "Cuántas pantallas tiene y a qué áreas pertenece."),
   ]},
   {"tipo": "criterio", "html":
    "Un usuario que <b>operó</b> (cargó, aprobó, pagó) no se elimina: se da de baja. Siempre queda al "
    "menos un usuario activo con el rol Administrador: nadie se da de baja ni se quita ese rol a sí mismo."},
 ]},

{
 "grupo": "Accesos",
 "id": "adm_roles",
 "titulo": "Roles",
 "url": "/admin/roles",
 "endpoints": ["admin.roles"],
 "resumen": "El nivel de cada persona en el sistema; no da pantallas.",
 "bloques": [
   {"tipo": "texto", "html":
    "Un rol dice el <b>nivel</b> de la persona, no qué pantallas ve: eso se elige en Permisos por Usuario. "
    "Se pueden crear, renombrar y ordenar por prioridad (solo ordena los listados)."},
   {"tipo": "criterio", "html":
    "<b>Administrador</b> es el único que el sistema reconoce por el nombre: anula pagos, reabre "
    "conciliaciones y marca votos fuera del día, y ve siempre Usuarios, Roles y Menú tenga tildado lo que "
    "tenga. No se renombra, no se desactiva ni se elimina. Un rol que alguien tiene no se elimina: se desactiva."},
 ]},

{
 "grupo": "Accesos",
 "id": "adm_permisos",
 "titulo": "Permisos por Usuario",
 "url": "/admin/permisos",
 "endpoints": ["admin.permisos"],
 "resumen": "Las pantallas que ve cada persona.",
 "bloques": [
   {"tipo": "texto", "html":
    "Se elige el usuario y se tildan sus pantallas: es todo lo que ve, el rol no suma nada. Tildar una "
    "pantalla tilda su rama."},
   {"tipo": "pasos", "items": [
    "Elegí el usuario.",
    "Para no tildar de cero, en <b>Copiar los permisos de</b> elegí a alguien que hace lo mismo: se ven sus "
    "pantallas tildadas.",
    "Ajustá lo que haga falta y <b>Guardar permisos</b>. Hasta guardar no cambia nada.",
   ]},
   {"tipo": "criterio", "html":
    "A quien tiene el rol Administrador, Usuarios, Roles y Menú se le ven tildadas y no se pueden sacar: "
    "sin ellas nadie podría volver a dar permisos."},
   {"tipo": "aviso", "html":
    "Los permisos se vuelven a leer cada minuto: un cambio rige al rato, sin que la persona tenga que "
    "salir y volver a entrar."},
 ]},

{
 "grupo": "Accesos",
 "id": "adm_menu",
 "titulo": "Menú",
 "url": "/admin/menu",
 "endpoints": ["admin.menu"],
 "resumen": "Las opciones del menú lateral: ramas y pantallas.",
 "bloques": [
   {"tipo": "campos", "items": [
     ("Rama", "Sin URL: agrupa otras opciones."),
     ("Pantalla", "Con URL (única), sin nada debajo."),
     ("Pendiente", "Una pantalla del menú que todavía no existe en el sistema: al abrirla se ve el aviso "
      "de pantalla pendiente."),
     ("Ícono", "Un SVG (sin scripts). Se dibuja en el menú lateral."),
   ]},
   {"tipo": "criterio", "html":
    "Hasta 4 niveles. Una opción con opciones debajo no se elimina. Usuarios, Roles y Menú no se "
    "desactivan, no se eliminan y no cambian de URL: sin ellas no habría forma de administrar."},
 ]},

{
 "grupo": "Organización",
 "id": "adm_areas",
 "titulo": "Áreas y Áreas por Usuario",
 "url": "/admin/areas",
 "endpoints": ["admin.areas", "admin.areas_usuario"],
 "resumen": "Las áreas del sindicato y quién trabaja en cada una.",
 "bloques": [
   {"tipo": "texto", "html":
    "Las áreas (hasta 5 niveles) son los destinos de la mesa de entradas y de los proveedores. En "
    "<b>Áreas por usuario</b> se tildan las áreas de cada persona, con su función."},
   {"tipo": "criterio", "html":
    "Un área que se usa (expedientes, proveedores) no se elimina: se desactiva. Al eliminar una sin uso, "
    "sus subáreas pasan a depender de su área madre."},
 ]},

{
 "grupo": "Organización",
 "id": "adm_talonarios",
 "titulo": "Talonarios",
 "url": "/admin/talonarios",
 "endpoints": ["talonarios.index"],
 "resumen": "Tipos de comprobante, clasificaciones y talonarios (punto de venta, letra, rango).",
 "bloques": [
   {"tipo": "texto", "html":
    "Tres solapas: <b>tipos de comprobante</b> (debe o haber), <b>clasificaciones</b> y "
    "<b>talonarios</b> (punto de venta, letra, desde, hasta y último emitido). Desde el talonario se "
    "puede crear la clasificación, y desde ella el tipo, en un diálogo, sin perder lo escrito."},
   {"tipo": "campos", "items": [
     ("X 0001 · X 0002", "Los recibos de cuota sindical y de fiscalización (se eligen en Datos del Sindicato)."),
     ("X 0091 · X 0092 (AEDA)", "Deshabilitados: los recibos que emitió el sistema anterior, con su número."),
   ]},
   {"tipo": "criterio", "html":
    "Un talonario <b>usado</b> no se elimina (se deshabilita) ni cambia punto de venta, letra, desde o "
    "clasificación; el hasta no baja de lo emitido y el último emitido nunca retrocede. Dos talonarios "
    "del mismo tipo, punto de venta y letra no se superponen. Anular un recibo no devuelve su número."},
 ]},

{
 "grupo": "Organización",
 "id": "adm_institucion",
 "titulo": "Datos del Sindicato",
 "url": "/admin/institucion",
 "endpoints": ["institucion.datos"],
 "resumen": "Membrete, datos fiscales, agente de retención, cuota sindical y logo.",
 "bloques": [
   {"tipo": "campos", "items": [
     ("Identificación · Domicilio · Autoridades", "Salen en el membrete de recibos, actas, órdenes y constancias."),
     ("Datos fiscales", "El CUIT: es el receptor que se controla al cargar comprobantes."),
     ("Agente de retención", "De qué impuestos el sindicato es agente (IVA, Ganancias, Ingresos Brutos, "
      "SUSS), con sus alícuotas por defecto. Solo esos se calculan al pagar."),
     ("Cuota sindical", "La alícuota (2,50 %), los talonarios de recibos de cuota y de fiscalización, "
      "el lugar de pago y el plazo de intimación de las actas."),
     ("Recibos a afiliados", "El talonario (X 0003), el motivo de ingreso (YMCA), el concepto que dice el "
      "recibo y la cuota por mes de los recibos a afiliados por la cuota social que transfieren."),
     ("Pago de la cuota sindical y consultas", "La cuenta donde las empresas pagan la cuota —una de "
      "Tesorería → Cuentas de Fondos: el banco, el número, el CBU y el alias se corrigen allá—, las "
      "indicaciones para el pago y el correo y el teléfono para consultas (vacíos, los generales). Las "
      "empresas los ven en su enlace y en el instructivo en PDF; <b>Ver el instructivo</b> lo muestra "
      "como lo reciben."),
     ("Logo", "Sale en el encabezado y en los PDF (un SVG se ve en pantalla pero no en los PDF)."),
   ]},
   {"tipo": "aviso", "html":
    "Cambiar la alícuota no reliquida lo ya liquidado: rige para lo que se liquide después."},
 ]},

{
 "grupo": "Organización",
 "id": "adm_correo",
 "titulo": "Correo Saliente",
 "url": "/admin/correo",
 "endpoints": ["correo.config", "correo.envios"],
 "resumen": "La cuenta con la que salen los correos del sistema, la prueba, los remitentes y lo enviado.",
 "bloques": [
   {"tipo": "texto", "html":
    "Como en OSEDA: una cuenta de correo (servidor, usuario y contraseña) por la que salen todos los mails "
    "del sistema —hoy, las campañas de Beneficios—. La contraseña se guarda cifrada y no se vuelve a mostrar."},
   {"tipo": "pasos", "items": [
     "Completá el <b>servidor</b> (con Gmail o Google Workspace: smtp.gmail.com, puerto 587, STARTTLS), el "
     "<b>usuario</b> y la <b>contraseña</b> (con Google, una contraseña de aplicación).",
     "Completá el <b>remitente</b>: el nombre y la dirección que ve quien recibe, y a quién se responde.",
     "Tildá <b>Activar el envío de correos</b> y <b>Guardar</b>.",
     "<b>Enviar prueba</b> a tu dirección: es lo único que confirma que la cuenta anda.",
   ]},
   {"tipo": "campos", "items": [
     ("Límite cada 24 horas", "Freno de seguridad: pasado ese número de mails en las últimas 24 horas no sale "
      "ninguno más (una campaña queda pausada y se reanuda después). Gmail corta en 2.000."),
     ("Remitentes", "Otras direcciones desde las que puede salir un aviso; pueden tener su propia cuenta."),
     ("Envíos", "Cada mail que salió, a quién, con qué resultado y el texto tal como se mandó."),
   ]},
   {"tipo": "aviso", "html":
    "Arranca <b>apagado</b>: no sale ningún mail hasta activarlo. El dominio del remitente tiene que autorizar "
    "la dirección (SPF y DKIM): si no, el mail sale, no da error y cae en spam."},
 ]},

{
 "grupo": "Organización",
 "id": "adm_errores",
 "titulo": "Log de Errores",
 "url": "/admin/errores",
 "endpoints": ["errores.errores"],
 "resumen": "Lo que falló en el sistema: el error, la pantalla, quién estaba y cuándo.",
 "bloques": [
   {"tipo": "texto", "html":
    "Cada vez que una pantalla falla, el sistema lo anota solo: la fecha y hora, el usuario, la dirección, "
    "el error y el detalle técnico (traceback). Quien vio «La pantalla no se pudo abrir» recibe un "
    "<b>código</b> (#123): es el número de la fila acá."},
   {"tipo": "campos", "items": [
     ("Excepción", "La pantalla se cayó: el usuario vio «La pantalla no se pudo abrir»."),
     ("Respuesta 500", "Una consulta de la pantalla (una búsqueda, un botón) respondió con error."),
     ("Atajado", "La pantalla atajó el error y le mostró un aviso al usuario («No se pudo…»)."),
     ("Veces", "El mismo error del mismo usuario en menos de 5 minutos se cuenta en una sola fila."),
     ("Marcar revisado", "Saca el error de los pendientes, con quién y cuándo. «Volver a pendiente» lo "
      "deshace."),
   ]},
   {"tipo": "aviso", "html":
    "No se anotan los avisos de validación (un dato que falta), los «no tenés permiso» ni las páginas "
    "inexistentes: no son fallas. Se guarda 180 días."},
 ]},

{
 "grupo": "Organización",
 "id": "adm_estilos",
 "titulo": "Guía de estilos",
 "url": "/estilos",
 "endpoints": [],
 "resumen": "Para quien desarrolla: los componentes de pantalla del sistema.",
 "bloques": [
   {"tipo": "texto", "html":
    "Muestra cada componente (botones, grillas, estados, formularios) con la línea para usarlo. Es la "
    "referencia para armar una pantalla nueva; para operar el sistema no hace falta."},
 ]},

]
