"""ayuda_empleadores.py — Manual de Empleadores."""

CLAVE = "empleadores"
MODULO = "Empleadores"

INTRO = """
<p>Los empleadores son las empresas donde trabajan los afiliados y las que retienen la
cuota sindical. De cada uno: su ficha, su nómina de afiliados (con lo que declaró en la DDJJ
de OSEDA), sus contactos, el enlace para presentar el Libro de Sueldos Digital y la
<b>cuenta corriente</b>: lo liquidado, lo cobrado y lo que debe.</p>
"""

CIRCUITO = [
    ("Ficha", "Datos, domicilios, contactos y el enlace personal de la empresa."),
    ("Nómina", "Los afiliados que trabajan ahí y si los declara en la DDJJ."),
    ("Cuenta corriente", "Liquidado contra cobrado, período por período."),
    ("Aplicación", "Qué cobro cancela qué cuota."),
]

SECCIONES = [

{
 "grupo": "Empleadores",
 "id": "emp_abm",
 "titulo": "ABM de Empleadores",
 "url": "/empleadores",
 "endpoints": ["empleadores.abm_empleadores"],
 "resumen": "La ficha de cada empresa: datos, nómina, contactos y cuota sindical.",
 "bloques": [
   {"tipo": "texto", "html":
    "El listado viene ordenado por <b>empleados activos</b> (afiliados con relación laboral vigente), "
    "de mayor a menor. El lápiz abre la ficha, con sus solapas."},
   {"tipo": "campos", "items": [
     ("Datos", "CUIT (se controla el dígito; se puede pegar con guiones), razón social, nombre de "
      "fantasía, teléfonos, correo y los domicilios legal y fiscal (<b>Copiar legal → fiscal</b>)."),
     ("Consultar ARCA", "Trae de la constancia de inscripción la razón social y el domicilio fiscal, y "
      "completa lo vacío; el domicilio legal, solo si está vacío entero. En el alta pregunta solo al "
      "completar el CUIT. Lo cargado y distinto no se pisa: se lista con <b>Usar los datos de ARCA</b>. "
      "Si el CUIT ya es de otro empleador, avisa con el enlace y no completa nada."),
     ("Nómina", "Los afiliados con relación laboral con este empleador (ver abajo)."),
     ("Contactos", "Las personas de la empresa: nombre, cargo, área, teléfono y correo."),
     ("Cuota sindical", "El enlace para que la empresa presente su Libro de Sueldos Digital y sus "
      "presentaciones."),
     ("Cuenta corriente", "El botón de arriba lleva a su estado de cuenta."),
   ]},
   {"tipo": "aviso", "html":
    "<b>Eliminar</b> borra la ficha: usarlo solo con un empleador cargado por error. Uno con afiliados, "
    "liquidaciones o cobros tiene que quedar, porque su historia se busca por el CUIT. Los que vinieron "
    "del sistema anterior (AEDA) dicen su origen al principio de las observaciones."},
 ]},

{
 "grupo": "Empleadores",
 "id": "emp_nomina",
 "titulo": "La nómina del empleador",
 "url": "",
 "endpoints": [],
 "resumen": "Quién trabaja ahí, desde cuándo y si figura en su DDJJ de OSEDA.",
 "bloques": [
   {"tipo": "texto", "html":
    "La solapa <b>Nómina</b> lista las relaciones laborales del empleador: cada afiliado con su "
    "estado, fecha de alta y de baja, antigüedad y la <b>última DDJJ de OSEDA</b> en la que este "
    "empleador lo declaró, con su remuneración imponible 5."},
   {"tipo": "campos", "items": [
     ("Activo", "Relación activa sin fecha de egreso, o con egreso de hoy en adelante."),
     ("Baja con *", "La relación vino de AEDA sin fecha de egreso: se muestra la baja del afiliado."),
     ("Antigüedad", "Años cumplidos. Con ¹ se cuenta desde la primera DDJJ de ese empleador (cuando "
      "es más vieja que el ingreso cargado); con ≥, la DDJJ empieza en 1996-07 y puede ser más."),
     ("DDJJ OSEDA", "El filtro separa a los declarados de los que no: los activos que no figuran son "
      "los que hay que mirar."),
   ]},
   {"tipo": "aviso", "html":
    "La DDJJ se lee en vivo de la base de OSEDA. Si no responde, la nómina se ve igual, con un aviso "
    "y sin esas columnas. Un afiliado con otra obra social no figura en la DDJJ de OSEDA aunque "
    "trabaje ahí."},
 ]},

{
 "grupo": "Empleadores",
 "id": "emp_enlace",
 "titulo": "El enlace de la empresa (Libro de Sueldos Digital)",
 "url": "",
 "endpoints": [],
 "resumen": "Cómo se le da a una empresa su acceso para presentar el LSD.",
 "bloques": [
   {"tipo": "pasos", "items": [
     "En la solapa <b>Cuota sindical</b>, <b>Generar un enlace nuevo</b>.",
     "El enlace se ve <b>una sola vez</b>: <b>Copiar</b> o <b>Enviar por mail</b>, que abre el correo "
     "de quien lo manda dirigido a los correos de la ficha y de los contactos, con el texto de "
     "confidencialidad.",
     "La empresa entra con ese enlace, sin usuario ni clave, sube su archivo y lo presenta.",
   ]},
   {"tipo": "criterio", "html":
    "El sistema no guarda el enlace, solo una huella: por eso no se puede volver a ver. Si se perdió, "
    "se genera otro, y el anterior deja de funcionar. <b>Revocar</b> lo corta sin generar otro (por "
    "ejemplo, si cambió quien liquida los sueldos)."},
   {"tipo": "aviso", "html":
    "Con el enlace se ven los datos de los afiliados de esa empresa (la afiliación sindical es un dato "
    "sensible, Ley 25.326): mandarlo solo a quien liquida los sueldos. El sistema no envía correos: "
    "abre el programa de correo de quien lo manda."},
 ]},

{
 "grupo": "Cuenta corriente",
 "id": "emp_cc",
 "titulo": "Cuenta Corriente",
 "url": "/empleadores/cc",
 "endpoints": ["cc_emp.bandeja"],
 "resumen": "Todos los empleadores con lo liquidado, lo cobrado y el saldo.",
 "bloques": [
   {"tipo": "texto", "html":
    "Un renglón por CUIT: lo <b>liquidado</b> (las cuotas sindicales), lo <b>cobrado</b> (los "
    "recibos), lo aplicado, el saldo y lo vencido."},
   {"tipo": "campos", "items": [
     ("Saldo", "Deuda (lo que debe, en rojo), a favor (pagó de más, en verde) o todos."),
     ("Período desde / hasta", "Cuenta solo lo liquidado de esos períodos y lo aplicado a ellos."),
     ("Vencido", "El saldo de los períodos con el vencimiento ya pasado."),
   ]},
   {"tipo": "criterio", "html":
    "<b>Saldo = liquidado − aplicado.</b> Lo que cancela una cuota no es haber cobrado algo en el mes "
    "sino la <b>aplicación</b> de ese cobro a esa cuota. Lo cobrado sin aplicar es saldo a favor del "
    "empleador hasta que se aplique."},
 ]},

{
 "grupo": "Cuenta corriente",
 "id": "emp_estado",
 "titulo": "Estado de cuenta del empleador",
 "url": "",
 "endpoints": ["cc_emp.estado_cuenta", "cc_emp.periodo"],
 "resumen": "Período por período: liquidado, aplicado, saldo, mora y cobros.",
 "bloques": [
   {"tipo": "texto", "html":
    "Arriba, los <b>períodos</b>: lo liquidado, lo aplicado, el saldo, el acumulado (lo anterior al "
    "«desde» entra como saldo anterior), los días de mora, lo que había liquidado AEDA y el acta que "
    "lo reclama, si hay. Abajo, los <b>cobros</b>: cada recibo con lo aplicado, lo que le queda sin "
    "aplicar y a qué períodos fue."},
   {"tipo": "campos", "items": [
     ("Ojo de un período", "Abre la cuota de ese período: la liquidación, los cobros aplicados, los "
      "cobros del período sin aplicar y los afiliados. <b>Estado de cuenta</b> vuelve con los mismos filtros."),
     ("Solo con saldo", "Deja los períodos que deben algo."),
     ("Aplicar / desaplicar", "Lleva a la Aplicación de Cobros de este empleador."),
     ("Acta de fiscalización", "Calcula el acta con la deuda de este empleador."),
   ]},
 ]},

{
 "grupo": "Cuenta corriente",
 "id": "emp_aplicacion",
 "titulo": "Aplicación de Cobros",
 "url": "/empleadores/cc/aplicaciones",
 "endpoints": ["cc_emp.aplicaciones"],
 "resumen": "Qué cobro cancela qué cuota: a mano, de a una, o automática.",
 "bloques": [
   {"tipo": "texto", "html":
    "Sin empleador elegido, la lista de <b>empleadores con algo para aplicar</b> (cuotas con saldo y "
    "cobros sin aplicar). Elegido uno, dos columnas lado a lado: a la izquierda las <b>cuotas con "
    "saldo</b> (las vencidas marcadas), a la derecha los <b>cobros con saldo</b>."},
   {"tipo": "pasos", "items": [
     "Hacé clic en una cuota y en un cobro (o movete con el teclado y Enter). Se marcan sugeridos los "
     "del mismo período.",
     "El importe propone el menor de los dos saldos; se puede bajar.",
     "<b>Aplicar</b>. Las dos listas se actualizan.",
   ]},
   {"tipo": "campos", "items": [
     ("Aplicación automática", "Cada cobro a su propio período, hasta el saldo; con «deuda vieja», lo "
      "que sobra a la deuda más vieja (de los cobros más viejos a los más nuevos, solo a períodos ya "
      "empezados al cobrar). Por empleador o de todos."),
     ("Desaplicar", "En «Aplicaciones registradas», entera o en parte, con motivo obligatorio. Queda el rastro."),
     ("Origen", "Período (automática), deuda vieja, recibo (al emitirlo) o manual."),
   ]},
   {"tipo": "criterio", "html":
    "Los recibos se aplican solos al emitirlos (cada renglón a la cuota de su período). La automática "
    "también limpia lo aplicado a recibos o liquidaciones anuladas y recorta lo automático de una cuota "
    "que se reliquidó por menos; <b>lo aplicado a mano no lo toca</b>: avisa «aplicado de más»."},
   {"tipo": "aviso", "html":
    "Un cobro de un período que todavía no está liquidado espera: se aplica cuando se liquide ese período."},
 ]},

]
