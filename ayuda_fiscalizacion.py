"""ayuda_fiscalizacion.py — Manual de Fiscalización de Cuotas."""

CLAVE = "fiscalizacion"
MODULO = "Fiscalización de Cuotas"

INTRO = """
<p>El empleador es <b>agente de retención</b> de la cuota sindical (Ley 23.551, art. 38):
se la descuenta a los afiliados del recibo de sueldo y la deposita al sindicato. Este módulo
calcula lo que cada empleador tiene que pagar por período, recibe sus pagos, emite los recibos
y, cuando no paga, labra el acta de fiscalización y el acuerdo de pago.</p>
<p>La cuota se calcula sobre la <b>Remuneración imponible 5</b> de cada afiliado, la misma base
de la declaración jurada de la obra social (OSEDA), por la alícuota que figura en Datos del
Sindicato (2,50 %). La fuente puede ser la DDJJ de OSEDA o el Libro de Sueldos Digital que
presenta la propia empresa.</p>
"""

CIRCUITO = [
    ("Liquidar", "Cuánto debe cada empleador por período: DDJJ de OSEDA o su Libro de Sueldos Digital."),
    ("Cobrar", "Cada acreditación del banco se convierte en un recibo y cancela su cuota."),
    ("Controlar", "La cuenta corriente del empleador muestra lo liquidado, lo cobrado y lo vencido."),
    ("Fiscalizar", "Lo impago va a un acta con sus intereses; el acta puede terminar en un acuerdo de pago."),
]

SECCIONES = [

# ── Panel e importación ─────────────────────────────────────────────────────
{
 "grupo": "Panel e importación",
 "id": "fis_panel",
 "titulo": "Panel de Fiscalización",
 "url": "/dashboard",
 "endpoints": ["sindicato.fisca_dashboard"],
 "resumen": "Los totales de las planillas de cuota sindical que presentaron los empleadores.",
 "bloques": [
   {"tipo": "texto", "html":
    "Es la pantalla de inicio. Arriba, los períodos, empresas y empleados con planilla cargada y la "
    "cuota y las remuneraciones del último período; abajo, la evolución de los últimos períodos, las "
    "diez empresas que más aportaron y el resumen por período, con el detalle de cada uno."},
   {"tipo": "criterio", "html":
    "Todo lo de esta pantalla sale de las <b>planillas que mandan los empleadores</b> (Importar "
    "Cuotas). El «último período» es el último <b>cargado</b>, no el último vencido: si faltan "
    "planillas de empresas grandes, el total se ve bajo y no es un problema de recaudación."},
   {"tipo": "aviso", "html":
    "Lo que el sindicato <b>cobra y reclama</b> no sale de acá sino de la Liquidación de Cuota "
    "Sindical y de la cuenta corriente de cada empleador (Empleadores → Cuenta Corriente)."},
 ]},

{
 "grupo": "Panel e importación",
 "id": "fis_importar",
 "titulo": "Importar Cuotas",
 "url": "/importar_cuotas",
 "endpoints": ["sindicato.fisca_importar_cuotas"],
 "resumen": "Carga de una vez una carpeta con las planillas de aportes de los empleadores.",
 "bloques": [
   {"tipo": "texto", "html":
    "Los empleadores mandan una planilla Excel de aportes (art. 38) con la remuneración y la cuota "
    "retenida a cada afiliado. Esta pantalla toma una <b>carpeta</b> entera: lee todos los "
    "<code>.xlsx</code>, muestra qué encontró en cada uno y los importa."},
   {"tipo": "pasos", "items": [
     "Hacé clic en la zona de carga y elegí la carpeta.",
     "Revisá la lista: empresa (CUIT), período y cantidad de filas de cada archivo. Los que no se "
     "pueden leer se marcan con el motivo.",
     "Elegí qué hacer con lo que ya esté cargado: ignorarlo, actualizarlo o avisar.",
     "<b>Importar todos los archivos</b>. La barra muestra el avance archivo por archivo.",
   ]},
   {"tipo": "campos", "items": [
     ("Ignorar", "Lo que ya existe para ese CUIT, CUIL y período queda como está. Para reintentar una "
      "importación que quedó a medias."),
     ("Actualizar", "Pisa lo cargado con lo nuevo. Para una planilla corregida por la empresa."),
     ("Avisar", "No importa lo repetido y lo informa."),
   ]},
   {"tipo": "aviso", "html":
    "Desde noviembre de 2026 la cuota se liquida con la DDJJ de OSEDA o con el Libro de Sueldos "
    "Digital: las planillas importadas acá sirven de consulta y de control, pero <b>no generan la "
    "deuda</b> del empleador."},
 ]},

{
 "grupo": "Panel e importación",
 "id": "fis_historial",
 "titulo": "Historial de Importaciones",
 "url": "/importaciones_log",
 "endpoints": ["sindicato.fisca_importaciones_log"],
 "resumen": "Qué se importó, cuándo, quién y con qué resultado.",
 "bloques": [
   {"tipo": "texto", "html":
    "Cada archivo importado deja su renglón: nombre, empresa, período, filas nuevas, actualizadas, "
    "ignoradas y con error, usuario y fecha. El ojo abre el detalle."},
   {"tipo": "criterio", "html":
    "Muchas <b>ignoradas</b> casi siempre quiere decir que se volvió a importar algo que ya estaba; "
    "muchas con <b>error</b>, que el archivo trae filas que no se pudieron leer (CUIL mal escrito, "
    "importes con texto)."},
 ]},

# ── Liquidación ─────────────────────────────────────────────────────────────
{
 "grupo": "Liquidación",
 "id": "fis_liquidacion",
 "titulo": "Liquidación de Cuota Sindical",
 "url": "/fiscalizacion/liquidacion",
 "endpoints": ["fisca_liq.liquidacion", "fisca_liq.liquidacion_ficha"],
 "resumen": "Lo que cada empleador tiene que pagar por período, con sus afiliados.",
 "bloques": [
   {"tipo": "texto", "html":
    "Para cada período, una liquidación por empleador: los afiliados que declaró en la DDJJ de "
    "OSEDA, su remuneración imponible 5 y la cuota (remuneración × 2,50 %, al centavo por "
    "afiliado). Además lleva a <b>todos los afiliados activos</b> del empleador en el período, "
    "estén o no en su DDJJ, para ver qué porcentaje declara."},
   {"tipo": "pasos", "items": [
     "Elegí <b>Desde el período</b> y <b>Hasta el período</b> (para uno solo, el mismo en los dos; "
     "hasta 48 períodos).",
     "<b>Liquidar</b>. Lee la DDJJ de OSEDA de esos períodos en vivo y arma o rehace las liquidaciones.",
     "Elegí un período en <b>Períodos liquidados</b> para ver sus empleadores; el ojo abre la ficha "
     "con los afiliados.",
   ]},
   {"tipo": "campos", "items": [
     ("Activos", "Titulares con relación laboral vigente con ese empleador en el período."),
     ("Con DDJJ · Sin DDJJ", "De los activos, cuántos están en la DDJJ de ese empleador y cuántos no."),
     ("% con DDJJ", "Con DDJJ sobre activos. El filtro de tramos (100 %, 50 a 99 %…) ayuda a encontrar "
      "a los que declaran poco."),
     ("Liquidados", "Los afiliados con remuneración: son los que generan cuota."),
     ("Por escala salarial", "Un activo que no está en la DDJJ de su empleador se liquida con el sueldo "
      "conformado de la escala del convenio de ese período (básico de su antigüedad más el almuerzo × 22 "
      "días). La antigüedad se cuenta desde su fecha de antigüedad con ese empleador o, si no la hay, "
      "desde el ingreso; sin ninguna fecha, como «Inicial». Si el período no tiene escala cargada, queda "
      "en cero."),
     ("Origen", "DDJJ de OSEDA, Libro de Sueldos Digital (lo presentó la empresa) o AEDA."),
     ("Liquidado AEDA", "Lo que había liquidado el sistema anterior para ese período, para comparar."),
     ("Vencimiento", "El mismo día que vence el F.931 del empleador (ver «Vencimientos e intereses»)."),
   ]},
   {"tipo": "criterio", "html":
    "<b>Liquidar de nuevo</b> rehace el detalle con lo que dice hoy la DDJJ y anula, con una nota, la "
    "de un empleador que se quedó sin afiliados. Lo que una empresa presentó con su <b>Libro de "
    "Sueldos Digital no se pisa</b>: manda su archivo. Lo cobrado aplicado a una cuota sigue a la "
    "cuota aunque se reliquide."},
   {"tipo": "aviso", "html":
    "«Sin DDJJ» es no estar en la DDJJ de <b>OSEDA</b>: un afiliado con otra obra social no figura "
    "ahí aunque su empleador le retenga la cuota. Y el último período suele tener la DDJJ incompleta: "
    "conviene volver a liquidarlo cuando se complete. Sin conexión con la base de OSEDA no se liquida."},
 ]},

{
 "grupo": "Liquidación",
 "id": "fis_lsd",
 "titulo": "Presentaciones LSD",
 "url": "/fiscalizacion/lsd",
 "endpoints": ["fisca_lsd.lista", "fisca_lsd.ficha", "fisca_lsd.ficha_novedad"],
 "resumen": "La empresa presenta su cuota (con el Libro de Sueldos Digital o a mano) e informa altas y bajas.",
 "bloques": [
   {"tipo": "texto", "html":
    "En lugar de completar una planilla a mano, la empresa sube el <b>archivo de liquidación del "
    "Libro de Sueldos Digital</b> que le presenta a ARCA. El sistema arma solo la planilla de la "
    "cuota sindical: cada afiliado que está en el archivo con su remuneración imponible 5 (registro "
    "04) por la alícuota, más los activos del empleador que no están, en cero."},
   {"tipo": "pasos", "items": [
     "En Empleadores, solapa <b>Cuota sindical</b>, se genera el <b>enlace personal</b> de la empresa "
     "y se le manda por correo (ver el manual de Empleadores).",
     "La empresa entra con su enlace, sube el archivo del período —o, si no lo tiene, <b>carga a mano</b> "
     "la remuneración de cada afiliado de su nómina— y revisa la planilla.",
     "La empresa la <b>presenta</b>: la planilla pasa a ser la liquidación del período, con origen "
     "«Presentada por la empresa».",
     "Acá se ve la presentación, se controla contra la DDJJ y, si hace falta, se anula.",
   ]},
   {"tipo": "campos", "items": [
     ("Subir un archivo por una empresa", "Un usuario del sindicato puede subirlo en nombre de la "
      "empresa (por ejemplo, si lo mandó por correo): <b>Leer el archivo</b> y después presentarlo."),
     ("Estado", "Sin presentar (borrador), Presentada, Reemplazada (hubo una más nueva del mismo "
      "período) o Anulada."),
     ("Retenido", "Si el recibo trae el concepto «Cuota Sindical», se muestra lo que la empresa "
      "retuvo al lado de lo calculado."),
     ("DDJJ OSEDA", "En la ficha, la remuneración de cada afiliado contra la de su DDJJ de OSEDA de "
      "ese empleador: se marcan diferencias de $ 1 o más."),
     ("Planilla · Archivo original", "La planilla de aportes en Excel y el archivo tal como se subió."),
     ("Anular presentación", "Con un motivo: la liquidación vuelve a la DDJJ de OSEDA."),
     ("Carga a mano", "Sin el archivo: la empresa carga la remuneración de cada afiliado de su nómina "
      "en el período (y de las altas que informó). En la lista dice «A mano»; el control contra la DDJJ "
      "de OSEDA es el mismo."),
     ("Instructivo de las empresas", "El PDF que la empresa abre desde el botón <b>Instructivo</b> de "
      "su enlace: cómo presentar, la nómina, las altas y bajas, la cuenta donde se paga la cuota y el "
      "contacto. Los datos de pago y de contacto salen de Datos del Sindicato el día que se abre."),
   ]},
   {"tipo": "texto", "html":
    "<b>Altas y bajas que informan las empresas.</b> Por su enlace, la empresa ve su nómina —los "
    "afiliados que según el padrón trabajan ahí— y puede informar el <b>alta</b> de un CUIL que "
    "corresponde cuota (con la fecha y, si quiere, la ficha de afiliación; si no está en el padrón, "
    "con apellido y nombre) y la <b>baja</b> de uno que el padrón tiene activo. Quedan pendientes en "
    "el bloque de arriba de esta pantalla (y en la solapa Cuota sindical del empleador)."},
   {"tipo": "campos", "items": [
     ("Aprobar un alta", "Si el CUIL no está en el padrón, se da de alta al afiliado (titular, con la "
      "fecha de alta); se abre la relación laboral con el empleador, y la ficha adjunta pasa a la "
      "documentación del afiliado. Un afiliado dado de baja no se reactiva solo: se avisa."),
     ("Aprobar una baja", "Se cierra la relación laboral con esa fecha. La afiliación no se toca."),
     ("Rechazar", "Con un motivo, que la empresa ve en su enlace."),
     ("Ficha", "El ojo abre la ficha de afiliación que adjuntó la empresa."),
   ]},
   {"tipo": "criterio", "html":
    "Manda la <b>última presentación</b> del período. Si el mes tuvo varias liquidaciones de sueldo, "
    "se sube la última, que trae las bases acumuladas. Liquidar por DDJJ no pisa un período presentado "
    "por la empresa. Un <b>alta pendiente</b> ya cuenta en la cuota del mes desde su fecha; una "
    "<b>baja pendiente</b>, recién cuando se aprueba."},
   {"tipo": "aviso", "html":
    "El archivo es de texto y se puede editar antes de subirlo: por eso el control contra la DDJJ de "
    "OSEDA. Los afiliados con otra obra social no se pueden controlar así. El enlace no lleva clave: "
    "es personal de cada empresa y quien lo tiene ve los datos de esa empresa."},
 ]},

# ── Cobros ──────────────────────────────────────────────────────────────────
{
 "grupo": "Cobros",
 "id": "fis_recibos",
 "titulo": "Emisión de Recibos",
 "url": "/fiscalizacion/recibos",
 "endpoints": ["fisca_rec.lista", "fisca_rec.emitir_uno", "fisca_rec.recibo"],
 "resumen": "Cada acreditación del extracto bancario se convierte en el recibo del empleador que pagó.",
 "bloques": [
   {"tipo": "texto", "html":
    "Se elige la <b>cuenta del banco</b> y las fechas: la grilla muestra las acreditaciones del "
    "extracto (Tesorería → Extractos Bancarios) con el empleador al que corresponde cada una, los "
    "períodos que paga y si ya tiene recibo."},
   {"tipo": "campos", "items": [
     ("Mismo CUIT", "Quien transfirió es el empleador."),
     ("CUIT relacionado", "Pagó otro CUIT que se sabe que paga por ese empleador (el estudio contable, "
      "otra empresa del grupo). Se cargan abajo, en «CUIT que pagan por un empleador»."),
     ("Afiliado", "Transfirió una persona del padrón: es la <b>cuota social YMCA</b>, no la cuota de una "
      "empresa. Lleva un <b>recibo al afiliado</b> (talonario X 0003), un renglón por mes desde el de la "
      "acreditación: si es justo N cuotas paga N meses y se puede emitir en lote; si no, de a uno. Lo que AEDA "
      "ya registró en su orden YMCA del mes figura «Ya tiene recibo». Si esa persona paga por una empresa, "
      "se carga como CUIT relacionado; y al emitir de a uno se puede emitir como cuota sindical de un "
      "empleador."),
     ("Varios posibles · Sin identificar", "Hay que elegir el empleador al emitir. Sin identificar y un importe de la cuota social (redondo a la medida de la cuota: 30.000, 55.000…): queda «Otro ingreso», porque casi seguro es un afiliado; se puede emitir igual de a uno."),
     ("Importe a distribuir", "Al emitir de a uno, en «Lo que debe»: se escribe el importe (viene el de la acreditación) y se tildan los períodos; cada tilde le aplica su saldo, en el orden en que se tildan, hasta completar el importe, y arma los «Períodos que se pagan». Lo que queda sin distribuir se ve al lado."),
     ("Cuotas impagas por importe", "Al emitir de a uno un pago sin CUIT o sin empleador identificado, la pantalla busca los empleadores con cuotas impagas de los 3 períodos anteriores que suman justo ese importe (una o varias seguidas). «Elegir» lo usa como empleador; es una ayuda, no elige solo."),
     ("Lo pagó el afiliado", "Un afiliado transfirió un importe que no es de la cuota social (tiene centavos o no es redondo a la medida de la cuota): es la cuota sindical del empleador de su ficha. Se emite de a uno."),
     ("Asociar (la persona)", "En todo lo que no es el mismo CUIT del empleador: dice de quién es el pago, a criterio de quien emite. Dos asociaciones: cuota sindical de una empresa o cuota social de un afiliado, y el mismo CUIT puede tener las dos (lo redondo a la medida de la cuota va al afiliado; lo demás, a la empresa). Si el banco no trajo el CUIT, se escribe (queda «a mano»; vacío, es el mismo de la empresa o el afiliado). Los próximos pagos de ese CUIT se reconocen solos. También está en Beneficios › Recibos de Adheridos."),
   ]},
   {"tipo": "campos", "items": [
     ("Sin recibo", "Hay que emitirlo."),
     ("Recibo emitido", "Ya se emitió desde esta acreditación."),
     ("Ya tiene recibo · ¿Ya tiene recibo?", "AEDA ya lo cobró (mismo comprobante, o mismo CUIT e "
      "importe cerca de esa fecha), o hay un ingreso con la misma fecha e importe. Con la duda se "
      "puede emitir igual."),
   ]},
   {"tipo": "pasos", "items": [
     "De a uno: el botón del renglón abre la emisión. Se revisa el empleador, los períodos y el "
     "importe de cada uno, y <b>Emitir el recibo</b>. Si se cambió el empleador, se puede tildar "
     "«Recordar» para que la próxima vez lo reconozca solo.",
     "En lote: se tildan los «Sin recibo» con empleador seguro (mismo CUIT o relacionado) y "
     "<b>Emitir los recibos tildados</b>. Cada recibo se graba por separado.",
   ]},
   {"tipo": "criterio", "html":
    "<b>A qué períodos va el pago</b>: al mes anterior a la acreditación; si el importe es justo el "
    "saldo de un período, a ese; si sobra, a la deuda más vieja; si el mes todavía no está liquidado, "
    "entero a ese mes («pago sin liquidar»). Al emitir de a uno se puede cambiar. Cada renglón del "
    "recibo <b>cancela la cuota de su período</b> en la cuenta corriente."},
   {"tipo": "texto", "html":
    "El recibo se numera con el talonario de cuota sindical («X 0001-00000123»), queda como ingreso "
    "en la cuenta del banco con la fecha de la acreditación y, si la cuenta tiene una conciliación "
    "abierta que incluye esa fecha, <b>se concilia solo</b>. El PDF lleva el membrete del sindicato y "
    "el importe en letras."},
   {"tipo": "aviso", "html":
    "Si el empleador tiene un <b>acuerdo de pago</b> vigente, la acreditación ofrece «Fiscalización · "
    "AP-…»: el recibo va al acuerdo (ver «Acuerdos de Pago») y no entra en el lote como cuota. Un "
    "recibo se anula en Tesorería → Anulaciones; la acreditación vuelve a quedar sin recibo."},
 ]},

# ── Fiscalización ───────────────────────────────────────────────────────────
{
 "grupo": "Fiscalización",
 "id": "fis_intereses",
 "titulo": "Vencimientos e intereses",
 "url": "",
 "endpoints": [],
 "resumen": "Cuándo vence cada cuota y cómo se calcula el interés resarcitorio.",
 "bloques": [
   {"tipo": "texto", "html":
    "La cuota de un período <b>vence el mismo día que el F.931</b> del empleador: según la "
    "terminación de su CUIT, el día 9 (0 a 3), 10 (4 a 6) u 11 (7 a 9) del mes siguiente, corrido al "
    "día hábil siguiente si cae en feriado o fin de semana. Si ARCA publicó otra fecha en su agenda "
    "(pasa algunos meses), manda la de ARCA."},
   {"tipo": "criterio", "html":
    "<b>Interés resarcitorio de ARCA</b>, simple: capital × tasa mensual ÷ 30 × días, cada día con la "
    "tasa vigente ese día (cuando la tasa cambia, el cálculo se parte en tramos). Los días van desde "
    "el siguiente al vencimiento hasta el pago o hasta la fecha de cálculo del acta. Desde el "
    "01/07/2025 la tasa es 2,75 % mensual."},
   {"tipo": "aviso", "html":
    "Las tasas, los vencimientos y los feriados se traen de ARCA (los mantiene gestion_adm). Si ARCA "
    "cambia la tasa, hay que actualizarla antes de labrar actas nuevas."},
 ]},

{
 "grupo": "Fiscalización",
 "id": "fis_actas",
 "titulo": "Actas de Fiscalización",
 "url": "/fiscalizacion/actas",
 "endpoints": ["fisca_acta.actas", "fisca_acta.acta_nueva", "fisca_acta.acta"],
 "resumen": "La deuda del empleador, período por período, con los intereses a una fecha.",
 "bloques": [
   {"tipo": "pasos", "items": [
     "En <b>Acta nueva</b> escribí el CUIT del empleador y <b>Calcular</b> (también se llega con el "
     "botón «Acta de fiscalización» de su cuenta corriente).",
     "Ajustá <b>Período desde / hasta</b> e <b>Intereses hasta</b> (la fecha de cálculo). Con «pagos "
     "fuera de término» tildado (por defecto) se suma el interés de lo que pagó tarde.",
     "Revisá la <b>Deuda por período</b>. El botón del ojo de cada período abre su detalle: los "
     "afiliados, los cobros aplicados y el interés por tramo de tasa.",
     "Completá el fiscalizador, quién atiende por el empleador, el lugar y la fecha, y "
     "<b>Guardar acta</b>. Queda <b>abierta</b>: se puede corregir con <b>Guardar y recalcular</b>.",
     "<b>Cerrar acta</b>: la deuda queda firme y se puede hacer el acuerdo de pago. El <b>PDF</b> es "
     "el acta para firmar.",
   ]},
   {"tipo": "criterio", "html":
    "Entran las liquidaciones vigentes del empleador en el rango, <b>vencidas</b> a la fecha de "
    "cálculo y que no estén en otra acta cerrada. Por período: lo pagado en término y tarde (lo "
    "cobrado después de la fecha de cálculo no cuenta), el saldo con su interés y el interés de cada "
    "pago tardío. El acta guarda lo calculado ese día: no cambia si después entran pagos."},
   {"tipo": "campos", "items": [
     ("Abierta", "Una por empleador. Se corrige y se recalcula."),
     ("Cerrada", "La deuda queda firme. Habilita el acuerdo de pago."),
     ("Anulada", "Con motivo. No se puede con un acuerdo vigente. Sus períodos se pueden volver a reclamar."),
   ]},
   {"tipo": "aviso", "html":
    "Los textos legales del acta (determinación, intimación) están <b>a revisar con el asesor "
    "legal</b>. El lugar de pago y el plazo de intimación se configuran en Datos del Sindicato."},
 ]},

{
 "grupo": "Fiscalización",
 "id": "fis_acuerdos",
 "titulo": "Acuerdos de Pago",
 "url": "/fiscalizacion/acuerdos",
 "endpoints": ["fisca_acta.acuerdos", "fisca_acta.acuerdo", "fisca_acta.acuerdo_cobrar"],
 "resumen": "La deuda de un acta cerrada en cuotas, y sus cobros.",
 "bloques": [
   {"tipo": "pasos", "items": [
     "Desde el acta cerrada, <b>Acuerdo de pago</b>. La deuda es el total del acta.",
     "Escribí el <b>interés de financiación</b>, la cantidad de cuotas y el vencimiento de la primera, "
     "y <b>Generar cuotas iguales</b>. Las cuotas se pueden corregir a mano o agregar.",
     "<b>Guardar acuerdo</b>. El <b>PDF</b> es el convenio para firmar.",
   ]},
   {"tipo": "criterio", "html":
    "El total financiado es la suma de las cuotas, y el interés es lo que supera a la deuda: si las "
    "cuotas no cubren la deuda, no se graba. Un acta tiene un solo acuerdo vigente; con uno cancelado "
    "(pagado) no admite otro."},
   {"tipo": "campos", "items": [
     ("Vigente", "Se está pagando."),
     ("Cancelado", "Pagado entero: pasa solo cuando no le queda saldo."),
     ("Judicializado", "Se reclama por vía judicial. Se puede seguir cobrando."),
     ("Anulado", "Con motivo."),
   ]},
   {"tipo": "texto", "html":
    "<b>Cobrar</b> (en el acuerdo) emite el recibo de fiscalización: la cuenta de banco o caja, la "
    "fecha y el importe; se imputa a las cuotas en orden. Si el pago llegó por transferencia, mejor "
    "emitirlo desde Emisión de Recibos, que lo toma del extracto y lo concilia. El recibo usa el "
    "talonario de fiscalización («X 0002-…»)."},
   {"tipo": "criterio", "html":
    "Cada recibo del acuerdo se <b>parte en capital e interés</b> en la proporción entre el capital "
    "que falta y lo que falta del acuerdo. El capital va a las cuotas sindicales de los períodos del "
    "acta, del más viejo al más nuevo, y la cuenta corriente baja; el interés va a «Intereses por "
    "fiscalización». El recibo que lo termina se lleva todo el capital que queda."},
   {"tipo": "aviso", "html":
    "Con recibos emitidos el cronograma ya no se modifica. Anular un recibo (Tesorería → "
    "Anulaciones) vuelve el acuerdo a «Vigente» si lo había cancelado ese pago."},
 ]},

{
 "grupo": "Fiscalización",
 "id": "fis_fiscalizadores",
 "titulo": "Fiscalizadores",
 "url": "/fiscalizacion/fiscalizadores",
 "endpoints": ["fisca_acta.fiscalizadores"],
 "resumen": "Quiénes labran las actas.",
 "bloques": [
   {"tipo": "texto", "html":
    "Apellido y nombres, DNI (no se repite), cargo, teléfono, correo y, si lo tiene, su usuario del "
    "sistema. El acta se labra con un fiscalizador activo y guarda su nombre y DNI como se "
    "imprimieron: corregir la ficha después no cambia un acta ya labrada."},
   {"tipo": "aviso", "html":
    "Uno que figura en actas no se elimina: se da de baja y deja de ofrecerse."},
 ]},

# ── Escalas ─────────────────────────────────────────────────────────────────
{
 "grupo": "Convenio",
 "id": "fis_escalas",
 "titulo": "Escalas Salariales",
 "url": "/fiscalizacion/escalas",
 "endpoints": ["fisca_esc.lista", "fisca_esc.ficha", "fisca_esc.nueva", "fisca_esc.editar"],
 "resumen": "El básico por antigüedad y el almuerzo de cada vigencia del convenio.",
 "bloques": [
   {"tipo": "texto", "html":
    "Cada escala rige desde un período hasta el mes anterior a la siguiente: el básico para cada año "
    "de antigüedad (0 a 35) y el almuerzo diario. El <b>conformado</b> es básico + almuerzo × 22 días. "
    "Las que vinieron de AEDA (2012 a 2023) se ven pero no se tocan; las paritarias 2025-2026 se "
    "cargaron de las circulares."},
   {"tipo": "pasos", "items": [
     "<b>Nueva escala</b> (o «Nueva escala a partir de esta» desde una ficha, que copia sus valores).",
     "Elegí desde qué período rige y el almuerzo diario.",
     "Cargá los básicos: pegando la columna de la planilla o la circular (<b>Repartir en la tabla</b>; "
     "toma los importes con centavos y un 37.º valor es el almuerzo) o calculándolos desde otra "
     "escala con un porcentaje (<b>Calcular</b>).",
     "<b>Grabar la escala</b>.",
   ]},
   {"tipo": "criterio", "html":
    "Al grabar se controla que el básico no baje al subir la antigüedad y que, contra la escala "
    "anterior, todas las antigüedades suban en la misma proporción. Son avisos: con <b>Grabar "
    "igual</b> se pasan. La escala anterior se cierra sola el mes antes de la nueva."},
   {"tipo": "aviso", "html":
    "Un mes sin escala propia no tuvo aumento: rige la anterior. Falta cargar de 2023-10 a 2024-12. "
    "Solo se corrigen o borran las cargadas en este sistema; al borrar una, la anterior vuelve a "
    "cubrir esos meses."},
 ]},

]
