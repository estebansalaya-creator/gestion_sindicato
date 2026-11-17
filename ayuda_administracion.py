"""ayuda_administracion.py — Manual de Administración del Sistema."""

CLAVE = "administracion"
MODULO = "Administración del Sistema"

INTRO = """
<p>Quién entra al sistema y qué puede hacer: usuarios, roles, permisos sueltos y el menú. Además,
las áreas (para la mesa de entradas), los talonarios de comprobantes y los datos del sindicato
que salen en los documentos.</p>
<p><b>El permiso es la opción de menú</b>: a un rol o a un usuario se le dan opciones del menú,
y con eso ve la pantalla y puede usarla. No hay otra tabla de permisos.</p>
"""

CIRCUITO = [
    ("Usuario", "Alta con correo y contraseña, y sus roles."),
    ("Roles", "Qué opciones del menú tiene cada rol."),
    ("Permisos sueltos", "Opciones de más para una persona puntual."),
    ("Vigencia", "Los permisos se vuelven a leer cada minuto."),
]

SECCIONES = [

{
 "grupo": "Accesos",
 "id": "adm_usuarios",
 "titulo": "Usuarios",
 "url": "/admin/usuarios",
 "endpoints": ["admin.usuarios"],
 "resumen": "Alta de usuarios, contraseña y roles.",
 "bloques": [
   {"tipo": "campos", "items": [
     ("Correo", "Es el usuario para entrar. En minúsculas y único."),
     ("Contraseña", "Obligatoria en el alta, de 8 caracteres como mínimo. Para cambiarla se escribe una nueva."),
     ("Roles", "Los que tiene. Un rol inactivo que ya tenía se conserva."),
     ("Permisos sueltos · Áreas", "Llevan a esas pantallas para este usuario."),
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
 "resumen": "Qué opciones del menú tiene cada rol.",
 "bloques": [
   {"tipo": "texto", "html":
    "Los roles son fijos (Administrador, Supervisor, Operador…): se editan la descripción, el estado y "
    "las opciones, en un árbol con casillas (<b>Tildar todas</b>, <b>Destildar todas</b>, y filtros para "
    "ver solo lo tildado)."},
   {"tipo": "criterio", "html":
    "Tildar una opción tilda su rama: el menú no muestra una pantalla cuya rama no está permitida. El "
    "rol Administrador no se desactiva ni pierde Usuarios, Roles y Menú."},
 ]},

{
 "grupo": "Accesos",
 "id": "adm_permisos",
 "titulo": "Permisos por Usuario",
 "url": "/admin/permisos",
 "endpoints": ["admin.permisos"],
 "resumen": "Opciones de menú sueltas para una persona, además de las de sus roles.",
 "bloques": [
   {"tipo": "texto", "html":
    "Se elige el usuario: lo que le dan sus roles se ve tildado y no se toca acá; lo que se tilde "
    "<b>se suma</b>. Así, un cambio en el rol le sigue llegando a todos los que lo tienen."},
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
