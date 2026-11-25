# Proyecto `sindicato` — contexto base

App **separada** de `gestion_adm` (obra social). Comparte convenciones y estructura de base, pero es
otro código y otra base de datos. Nada de este proyecto debe escribir en la base `contable`.

---

## Stack

- Python / Flask con blueprints, Jinja2, JavaScript vanilla
- PyMySQL con `DictCursor`, MySQL 8+
- Base de datos: **`sindicato`** (no `contable`)
- Windows Server con IIS / wfastcgi
- DBeaver como cliente de base

## Regla de oro

El conector MySQL de este proyecto apunta solo a `sindicato`. Si una consulta necesita datos de
`contable`, se resuelve por importación explícita, nunca con un JOIN cross-database en código de
producción.

**Excepción decidida el 10/11/2026**: las DDJJ de OSEDA se leen en vivo de `contable` en Railway
(`contable_oseda.py`), sin copiarlas a `sindicato`. Es una conexión aparte, de solo lectura
(`SET SESSION TRANSACTION READ ONLY`), con sus propias variables `SIND_CONTABLE_*`. El cruce con el
padrón se hace en Python, no con JOIN entre bases. Escribir en `contable` sigue prohibido.

---

## Estructura del proyecto

La app es autónoma: proceso propio, base propia, entrypoint propio. No importa nada de
`gestion_adm`, y gestion_adm tampoco importa nada de acá.

```
gestion_sindicato/
  app.py                  entrypoint: registra blueprints, login/logout/menu, /estilos, filtros `miles`, `periodo`, `svg_unico`
  db.py                   get_connection() a la base `sindicato` + helpers de sesión
  gestion_sindicato.py    blueprint `sindicato` — fiscalización de cuotas
  fisca_liquidacion.py    liquidación de cuota sindical por DDJJ de OSEDA, con los activos del empleador y el % con DDJJ
  fisca_lsd.py            la empresa presenta su Libro de Sueldos Digital por un enlace y la cuota se liquida con él
  fisca_recibos.py        emisión de recibos de cuota sindical desde las acreditaciones del extracto bancario
  fisca_actas.py          actas de fiscalización (deuda + intereses resarcitorios ARCA), acuerdos de pago y fiscalizadores
  fisca_recibo_acta.py    el recibo de fiscalización: a un acta, a las cuotas de su acuerdo (capital e interés)
  recibos_talonario.py    el talonario y el número de cada recibo («X 0001-00000123»)
  fisca_intereses.py      vencimiento del F.931 por terminación de CUIT e interés resarcitorio de ARCA por tramos
  importar_arca_tablas.py vencimientos F.931, tasas y feriados de ARCA desde contable (solo lectura); --aplicar graba
  fisca_escalas.py        escalas salariales del convenio: consulta, alta, corrección (fisca_escala_salarial)
  ben_convenio.py         Beneficios › Convenio YMCA: nómina de adheridos, recibos de sus transferencias, cuotas por
                          grupo familiar, control de la factura del gimnasio, datos y precios del convenio
  ben_campanias.py        Beneficios › Campañas: flyers por correo a los afiliados, envío en segundo plano, baja pública
  elecciones.py           Elecciones: motivo y día de la votación, padrón electoral (foto del padrón) y la mesa
                          de votación que marca quién vino a votar
  mailer.py               el motor del correo saliente (copia del de gestion_adm) + entregar() para las campañas
  correo.py               Administración › Correo Saliente: cuenta SMTP, prueba, remitentes, avisos, envíos
  secretos.py             cifrado Fernet de las contraseñas (SIND_FERNET_KEY), copia del de gestion_adm
  lsd_lector.py           lector del archivo de liquidación del LSD de ARCA (copia del de gestion_adm)
  empleadores.py          ABM de empleadores (p_empresas)
  cc_empleadores.py       cuenta corriente de empleadores y aplicación de cobros a las cuotas (pantallas)
  fisca_aplicaciones.py   qué cobro cancela qué cuota (fisca_aplicacion): aplicar, desaplicar, aplicación automática
  aplicar_cobros.py       la aplicación automática por consola; simula por defecto, --aplicar graba
  afiliados.py            ABM del padrón (p_afiliados): grupo familiar, empleadores, documentación, baja lógica, auditoría
  afiliado_aportes.py     solapa «Aportes OSEDA» de la ficha: DDJJ contra lo transferido por ARCA (de gestion_adm)
  afiliados_dni.py        Carga de DNI: lee las fotos, busca al afiliado, guarda frente/dorso y la foto de la ficha
  lector_dni.py           el código PDF417 del DNI (tarjeta y libreta) y el recorte de la cara (zxing-cpp + OpenCV)
  afiliado_foto.py        la foto de la ficha (p_afiliados.foto): guardar, servir, borrar (disco y bucket)
  afiliados_tablas.py     tablas auxiliares del padrón: una pantalla, una solapa por catálogo (TABLAS)
  afiliados_metricas.py   métricas del padrón: indicadores, altas y bajas, pirámide, empleadores, controles
  documentacion.py        documentación adjunta de cualquier entidad (p_documentacion), parcial _documentacion.html
  contactos.py            contactos de terceros (s_contactos), parcial _contactos.html
  reintegros.py           pantallas de reintegros: solicitud, ficha, auditoría, órdenes, constancia PDF
  reintegros_datos.py     capa de datos del circuito de reintegros (portada de gestion_adm)
  institucion.py          datos del sindicato (s_institucion): fiscales, agente de retención, logo
  admin.py                administración del sistema: usuarios, roles, permisos por usuario, menú, áreas, áreas por usuario
  talonarios.py           talonarios, sus clasificaciones y los tipos de comprobante (con alta en diálogo)
  proveedores.py          ABM de proveedores (c_proveedores): ficha, cuentas contables, contactos
  proveedores_movimientos.py  auditoría de la ficha del proveedor (c_proveedores_movimientos)
  cc_proveedores.py       cuenta corriente de proveedores (bandeja, estado de cuenta) y aplicación de comprobantes
  rg830.py                regímenes de Ganancias vigentes (rg830_escala) y la regla del monotributo
  tesoreria_rg830.py      pantalla de la escala RG 830: vigencias, tramos, simulador
  comprobantes.py         carga de comprobantes de proveedores (PDF, a mano, desde Mis Comprobantes)
  comprobantes_datos.py   capa de datos: validación, comprobante + expediente + liquidación, mesa
  mis_comprobantes.py     Comprobantes ARCA: importa el export de Mis Comprobantes y lo cruza
  mesa.py                 mesa de entradas: bandeja, expediente, movimientos, anulación, PDF
  tesoreria.py            tablas de tesorería: cuentas de fondos y chequeras, bancos BCRA, conceptos, motivos
  tesoreria_movimientos.py  subdiario, movimientos entre cuentas, depósitos, extracciones, órdenes de ingreso, anulaciones
  tesoreria_panel.py      Panel de Control de Tesorería: lo pendiente y los saldos de las cuentas
  extractos.py            Extractos Bancarios: importar (BNA, ICBC, Interbanking .xlsx), ver, borrar un renglón suelto
  extractos_bancarios.py  los parsers de los extractos y el control de cuenta (de gestion_adm)
  conciliacion.py         Conciliación Bancaria (extracto contra libro) y Clasificación de conceptos
  transferencias.py       transferencias masivas: elegir pagos, generar el archivo, lotes generados
  transferencias_lote.py  a quién y a qué CBU se transfiere; registro, exclusión y anulación de lotes
  transferencias_formatos.py  los archivos del home banking: BNA24, BNA Empresa, ICBC (Excel)
  contabilidad.py         módulo de contabilidad: el ABM del plan de cuentas
  asientos.py             ejercicios, períodos y asientos: las reglas, sin Flask (pantallas e importadores)
  contabilidad_ejercicios.py  Contabilidad › Ejercicios: abrir (con sus períodos mensuales), de trabajo, cerrar
  contabilidad_diario.py  Contabilidad › Asientos (carga) y Libro Diario (consulta, exportaciones, importar, renumerar)
  exportar_contable_externo.py  el formato del sistema contable externo (copia del de gestion_adm)
  pagos.py                circuito de pagos: órdenes, aprobación, emisión, anulación, certificados, ABM de config
  pagos_datos.py          capa de datos de pagos: armar órdenes, niveles de aprobación, ejecutar el pago
  pagos_pdf.py            PDF de la orden de pago y del certificado de retención
  retenciones.py          motor de retenciones de gestion_adm sobre s_institucion (Ganancias RG 830, IVA, IIBB, SUSS)
  numeracion.py           números AAMM-######## y certificados CRT-AAAA-NNNNNN (c_numeradores)
  movimientos_fondos.py   libro de fondos (c_movimientos_de_fondos), copia de gestion_adm
  anulaciones.py          reglas para anular: período cerrado, conciliado, ya transferido (y en lote, para la grilla)
  recibos_emitidos.py     Tesorería › Recibos Emitidos: consulta de los recibos de cuota sindical, fiscalización y afiliados
  recibos_afiliado.py     el recibo al afiliado por la cuota social YMCA (talonario X 0003)
  pago_anulacion.py       anular un pago y anular una orden (deshace lo que grabó cada uno)
  plan_cuentas.py         reglas del plan (el código manda): las usan la pantalla y los importadores
  lector_comprobante.py   el parser del PDF de gestion_adm + Mis Comprobantes si no alcanza
  lector_pdf_ocr.py       texto del PDF, OCR de escaneos, cotejo PDF ↔ datos (de gestion_adm)
  arca_wscdc.py           constatación con ARCA (WSAA + WSCDC), certificado propio y opcional
  arca_padron.py          padrón de ARCA (ws_sr_padron_a13): CUIL de un documento y datos de la persona
  arca_constancia.py      constancia de inscripción (ws_sr_constancia_inscripcion): empleadores y proveedores
  fisca_novedades.py      altas y bajas de afiliados que informa la empresa por su enlace, y su aprobación
  instructivo_empresa.py  el instructivo en PDF del enlace de las empresas (texto en docs/instructivo_empresa.md)
  empleadores_arca.py     «Actualizar desde ARCA»: constancia y domicilio fiscal de los empleadores que aportan
  probar_arca.py          prueba desde la consola el certificado, el token de cada servicio y una consulta
  exportar.py             POST /exportar/excel — el .xlsx de cualquier grilla
  buscador.py             buscador general de la barra superior (GET /api/busqueda): afiliados, empleadores, proveedores
  ayuda.py                registro de los manuales de uso (sin Flask): cargar, verificar, qué sección es de qué pantalla
  ayuda_pantallas.py      /ayuda (índice) y /ayuda/<clave> (un manual); url_ayuda() para el botón Ayuda
  accesos_directos.py     los accesos directos del panel de inicio (/menu): la chincheta del menú, quitar y ordenar
  almacenamiento.py       los archivos que sube la gente: SIND_ADJUNTOS en disco + copia en el bucket (si hay).
                          guardar/respaldar al escribir, local() antes de leer, borrar() los dos.
                          `python almacenamiento.py --subir [--aplicar]` sube lo que ya hay
  objetos.py              el cliente S3 del bucket (el de gestion_adm, con variables SIND_BUCKET_*)
  log_errores.py          el log de errores (el de gestion_adm): cada error de una pantalla queda en s_log_errores;
                          la pantalla /admin/errores. Se engancha en app.py antes que los blueprints
  mensajes.py             Mensajes internos entre usuarios (el chat de gestion_adm): conversaciones y grupos,
                          adjuntos en SIND_ADJUNTOS/chat/, el botón de la barra (`chat_encabezado`)
  ayuda_<módulo>.py       el texto de cada manual, SOLO DATOS: general, mesa, fiscalizacion, empleadores, padron,
                          proveedores, tesoreria, pagos, reintegros, contabilidad, administracion
  paginar.py              grillas paginadas en el servidor: tamaño, página y los enlaces de ui.paginacion_srv
  crear_usuario.py        alta de usuarios por consola (el primero no se puede crear desde la app)
  importar_aeda.py        empleadores y contactos desde AEDA; simula por defecto, --aplicar graba
  importar_aeda_afiliados.py  padrón de afiliados desde AEDA; ídem
  importar_aeda_reintegros.py historial de reintegros desde AEDA (afi_reintegros); ídem
  importar_aeda_proveedores.py proveedores y sus contactos desde AEDA (adm_proveedor); ídem
  importar_aeda_cc_proveedores.py cuentas corrientes de proveedores desde AEDA; ídem, con control de saldos
  importar_aeda_cc_afiliados.py   expedientes y pagos de los reintegros y subsidios de AEDA (solo el gasto); ídem
  importar_aeda_plan_cuentas.py  plan de cuentas desde AEDA (adm_planctas); ídem
  importar_aeda_tesoreria.py  plan de cuentas (con el anterior), conceptos, motivos, cuentas y chequeras; ídem
  importar_aeda_mis_comprobantes.py  la copia de Mis Comprobantes de AEDA (adm_comprobafip); ídem
  importar_aeda_fisca_deuda.py  las liquidaciones de cuota sindical de AEDA (fis_deuda); ídem
  importar_aeda_fondos.py     el libro de bancos y caja de AEDA (adm_movctas): instrumentos, gastos varios,
                              pases, depósitos, recaudación, órdenes de ingreso y valores; ídem, con control de saldos
  importar_aeda_extractos.py  los extractos del Nación que AEDA cargó (adm_bna24) → c_extractos_bancarios; ídem
  importar_aeda_fisca_escalas.py  las escalas salariales del convenio (fis_escalas) → fisca_escala_salarial; ídem
  importar_aeda_asientos.py   los asientos de AEDA (adm_asientos) → Libro Diario; ídem, --crear-ejercicios
  contable_oseda.py       lectura en vivo (solo lectura) de las DDJJ de OSEDA en contable de Railway
  cruce_nomina_ddjj.py    qué empleadores tienen toda su nómina de AEDA en la DDJJ de OSEDA (planillas en logs/)
  cruce_atributo_aeda.py  si los titulares activos de AEDA tienen la marca «AEDA» en el padrón de OSEDA (logs/)
  antiguedad_ddjj.py      antigüedad de los afiliados por la DDJJ de OSEDA (oseda.dbo.afi_redapo) contra el ingreso del padrón (logs/)
  adjuntos/               comprobantes de reintegros y el logo (SIND_ADJUNTOS); NO va al repositorio
  .env                    variables del entorno — NO va al repositorio
  .env.example            plantilla versionada
  .gitignore  .gitattributes  subir_github.bat   repositorio propio (ver «Repositorio»)
  sql/                    scripts de esquema y permisos, se corren a mano
  docs/instructivo_empresa.md  el texto del instructivo de las empresas (Markdown simple; ver instructivo_empresa.py)
  static/css/sindicato.css    LA hoja de estilos: no hay otra
  static/js/chat.js       el chat (Mensajes): el contador de la barra y la pantalla /mensajes (copia del de gestion_adm)
  templates/
    base.html             estructura, menú, JS común (grillas, solapas, diálogos)
    _ui.html              macros de interfaz: íconos, acciones, filtros, mensajes, estados
    _contactos.html       bloque de contactos, el mismo en todas las pantallas
    estilos.html          guía visual (/estilos)
    ayuda/                manual.html, indice.html y _bloques.html (cómo se dibuja cada tipo de bloque)
    login.html  404.html  inicio.html (el panel de inicio, /menu)
    empleadores/  afiliados/  reintegros/  proveedores/  comprobantes/  mesa/  tesoreria/  pagos/  contabilidad/  admin/  fisca/
  static/imagenes/
```

### Rutas

El blueprint se monta en la raíz: el sitio ya es el del sindicato, un prefijo `/sindicato`
repetiría en la URL lo que dice el dominio.

```
/  /dashboard        fisca_dashboard
/importar_cuotas     GET vista, POST importación
/importaciones_log   historial
/api/cuotas          API del tab
/fiscalizacion/liquidacion   liquidación de cuota sindical, ?periodo=AAAAMM; /generar POST (desde, hasta); /<id> ficha
/fiscalizacion/lsd           presentaciones del LSD, ?periodo, ?estado; /subir POST; /<id> ficha; /<id>/confirmar,
                             /descartar, /anular POST; /<id>/planilla.xlsx, /<id>/archivo; /enlace/<id_empresa> POST;
                             ?nov=pendiente|aprobada|rechazada|retirada|todas (altas y bajas de las empresas);
                             /novedad/<id>/aprobar, /rechazar POST; /novedad/<id>/ficha;
                             /instructivo.pdf (?id_empresa=): el instructivo de las empresas
/fiscalizacion/actas         actas: ?q, ?estado; /nueva?cuit= (&fecha_calculo, &periodo_desde, &periodo_hasta,
                             &con_pagos_tarde: recalcula sin guardar); /periodo (?id_acta=&periodo= o ?cuit=&periodo=
                             &fecha_calculo=&con_pagos_tarde=: el detalle de un período, HTML para el diálogo);
                             /guardar POST; /<id> ficha; /<id>/cerrar,
                             /<id>/anular POST; /<id>/pdf; /<id>/acuerdo (?id=), /<id>/acuerdo/guardar POST
/fiscalizacion/acuerdos      acuerdos: ?estado; /<id>/estado POST (anular, cancelar, judicializar); /<id>/pdf;
                             /<id>/cobrar GET/POST (el recibo de fiscalización con cuenta y fecha)
/fiscalizacion/fiscalizadores  ABM, ?edit=ID, ?nuevo=1; POST accion=guardar|borrar|baja|reactivar
/fiscalizacion/recibos       acreditaciones de una cuenta: ?cuenta, ?desde, ?hasta; /emitir/<id_extracto> (?cuit=,
                             ?acuerdo= como recibo de fiscalización);
                             /emitir_lote POST; /<id_orden> recibo, /<id_orden>/pdf; /relacion POST, /relacion/<id>/baja POST;
                             /asociar POST (de quién es un pago), /afiliado/<id>/baja POST
/beneficios/ymca/adheridos   nómina (?edit=ID, ?cuil=&desde= alta precargada); POST accion=guardar|baja|borrar
/beneficios/ymca/recibos     transferencias de afiliados: ?cuenta, ?desde, ?hasta; /emitir/<id_extracto>, /emitir_lote POST
/beneficios/ymca/cuotas      cuenta por grupo familiar: ?desde, ?hasta (AAAAMM); /<cuil_titular> la de un grupo
/beneficios/ymca/control     factura del gimnasio contra nómina × precio, cobrado y lo que cubre el sindicato: ?desde, ?hasta
/beneficios/ymca/convenio    datos del convenio y vigencias (?precio=ID); POST accion=datos|precio|borrar_precio
/beneficios/campanias        campañas; /nueva, /<id>, /<id>/editar, /<id>/flyer, /<id>/probar, /<id>/enviar POST,
                             /<id>/pausar|reanudar|cancelar|borrar POST, /<id>/estado (JSON)
/beneficios/baja/<token>     PÚBLICA, sin sesión: «no quiero recibir más» (token firmado con SIND_SECRET_KEY)
/elecciones                  elecciones; /nueva GET/POST; /<id> ficha (?solapa=padron|datos|movs), POST accion=guardar|
                             generar|agregar|quitar|quitar_voto|cerrar|reabrir|anular
/elecciones/votacion         la mesa (?elegir=1 si hay una sola hoy y va directo); /<id> la mesa de una elección;
                             /<id>/api_buscar?q=, /api_estado (JSON); /api_votar, /api_quitar_voto POST JSON
/admin/correo                correo saliente; /guardar, /probar, /remitentes/guardar, /remitentes/<id>/borrar,
                             /tipos/asignar POST; /envios (?origen_tipo=&origen_id=&codigo=&estado=&q=&pagina=)
/fiscalizacion/escalas       vigencias; /<desde> ficha de la escala; /nueva (?base=AAAAMM) GET/POST;
                             /<desde>/editar GET/POST, /<desde>/eliminar POST (solo las cargadas acá)
/empresas/<token>            PORTAL de la empresa, sin sesión; /subir POST; /presentacion/<id> (+ /confirmar,
                             /descartar POST, /planilla.xlsx); /manual?periodo= (GET y POST: la cuota a mano);
                             /alta, /baja POST; /novedad/<id>/retirar POST; /instructivo.pdf (en el navegador)
/login /logout /menu   /menu: el panel de inicio con los accesos directos (sin ninguno, al Panel de Fiscalización)
/accesos-directos/alternar, /quitar, /ordenar   POST JSON: la chincheta del menú y las tarjetas del panel
/empleadores         ABM, ?edit=ID, ?solapa=arca|cuota; /empleadores/arca ?cuit=&id=: la constancia de ARCA completa
                     la ficha (JSON); /empleadores/arca/actualizar POST y /empleadores/arca/estado (?alcance=1)
/empleadores/cc      cuenta corriente: ?q, ?saldo=deuda|favor|todos, ?desde, ?hasta (AAAAMM), ?sin_pagos=N (sin
                     recibos en los últimos N meses, o nunca); /<cuit> estado de cuenta
                     (?desde, ?hasta, ?con_saldo=1); /<cuit>/<periodo> la cuota del período (?volver);
                     /aplicaciones (?cuit=), /aplicaciones/aplicar,
                     /aplicaciones/<id>/desaplicar, /aplicaciones/automatica POST
/afiliados/padron    consulta del padrón (solo lectura), ?ver=ID
/afiliados           ABM, ?edit=ID, ?nuevo=1, ?familiar_de=CUIL (alta de familiar con grupo y domicilio);
                     ?nuevo=1&nro_documento=&apellido_nombres=&fecha_nacimiento=&sexo= (alta desde la carga de DNI)
                     listado: ?q, ?estado=activo|baja|todos, ?tipo, ?sexo, ?edad_desde, ?edad_hasta, ?atributo,
                     ?orden, ?dir, ?tam, ?pagina (lo mismo en /afiliados/padron); /afiliados/exportar (.xlsx);
                     /afiliados/<id>/aportes la solapa Aportes OSEDA (HTML, 204 sin DDJJ; la pide la ficha)
                     /afiliados/arca ?cuil= o ?documento=&sexo= (&id=): ARCA completa la ficha (JSON)
/afiliados/<id>/foto GET la foto de la ficha; POST accion=cambiar (archivo `foto`) | quitar
/afiliados/dni       Carga de DNI: POST accion=leer (imagenes) | buscar (ficha, dni) | guardar | descartar; ?para=ID;
                     /<ficha> el resultado; /<ficha>/<archivo> las imágenes de la carga en curso
/afiliados/empleador razón social de un CUIT (ayuda del formulario)
/afiliados/metricas  tablero; ?estado=todos, ?personas=titulares, ?desde=&hasta=, ?control=<clave>
/contactos/<tipo>/<id>  POST alta/edición/baja de contacto (tipo: empresa | afiliado | proveedor)
/reintegros/solicitud   listado y carga, ?edit=ID, ?nuevo=1; /<id> ficha, /<id>/pdf constancia
/reintegros/auditoria   bandeja; /<id> auditar, /<id>/resolver POST
/reintegros/ordenes     reintegros con saldo → órdenes de pago; /generar POST
/admin/institucion      datos del sindicato; /logo sirve el logo
/admin/errores          log de errores: ?q, ?estado=pendientes|revisados|todos, ?usuario, ?origen, ?desde, ?hasta,
                        ?orden, ?dir, ?tam, ?pagina; POST id[], revisado (marcar revisado / volver a pendiente);
                        /admin/errores/exportar (.xlsx con los mismos filtros)
/mensajes               Mensajes (?c=conversación, ?para=usuario, ?volver=); /mensajes/api (GET contador|lista|
                        usuarios|mensajes, POST con encabezado X-Chat: enviar|abrir|grupo|editar|salir|silenciar|
                        retirar|leido); /mensajes/adjunto/<id> (sólo para quien participa)
/admin/usuarios         ABM, ?edit=ID, ?nuevo=1        /admin/roles   ?edit=ID (fijos: no se crean ni se borran)
/admin/permisos         ?usuario=ID (opciones sueltas)  /admin/menu    ?edit=ID, ?nuevo=1, ?padre=ID
/admin/areas            ?edit=ID, ?nuevo=1, ?padre=ID   /admin/areas_usuario  ?usuario=ID
/admin/talonarios       ?solapa=talonarios|clasificaciones|tipos, ?edit=ID, ?edit_clasif=ID, ?edit_tipo=ID, ?nuevo=1;
                        /api/clasificacion y /api/tipo POST (JSON): los formularios satélite
/proveedores         ABM, ?edit=ID, ?nuevo=1, ?solapa=cuentas|contactos|movimientos
/proveedores/<id>/cuenta/<pasivo|gasto>  POST alta/baja de cuenta contable
/proveedores/<id>/mesa   POST área y usuario destino de sus expedientes (solapa Mesa de entradas)
/proveedores/api/cuit/<cuit>  ¿válido y libre? (aviso mientras se tipea); /api/buscar
/proveedores/api/arca/<cuit>  ?excepto=ID: la constancia de ARCA completa la ficha (JSON)
/proveedores/cc         cuenta corriente: ?saldo=acreedor|deudor|todos, ?rubro, ?activo, ?hasta; /cuit/<cuit>
/proveedores/cc/<id>    estado de cuenta: ?vista=cronologica|aplicacion, ?desde, ?hasta, ?rubro, ?cbte, ?con_saldo=1;
                        /<id>/pdf (mismos filtros), /<id>/aplicaciones_de?liq=|?pago= (JSON)
/proveedores/cc/aplicaciones  ?id_proveedor=; /aplicar POST; /<id_aplic>/deshacer POST (desaplicar)
/comprobantes/carga     carga de comprobantes; ?manual=1, ?mis=<id>; POST accion=leer|guardar
/comprobantes/<id>/pdf  el PDF de un comprobante; /tmp/<ficha> el subido sin guardar
/comprobantes/arca      Comprobantes ARCA (Mis Comprobantes): importar y cruzar; /<id>/ignorar
/mesa                   bandeja: ?q, ?estado, ?area_id, ?usuario_id, ?fecha_desde, ?fecha_hasta, ?orden, ?dir,
                        ?tam, ?pagina; /exportar (.xlsx); /<id> expediente; /<id>/mover, /<id>/anular, /<id>/pdf POST
/tesoreria                  Panel de Control de Tesorería
/tesoreria/cuentas_fondos   ABM, ?edit=ID, ?nuevo=1; /<id>/chequeras POST (alta, edición, baja)
/tesoreria/bancos           códigos de banco del BCRA; /conceptos_gasto, /motivos_ingreso (mismo ABM)
/tesoreria/movimientos      subdiario de cuentas de fondos; ?cuenta, ?origen, ?desde, ?hasta, ?imp_desde, ?imp_hasta, ?anulados=1
/tesoreria/movimientos/nuevo/<transferencia|deposito|extraccion>   alta de un movimiento entre cuentas
/tesoreria/nueva_orden_concepto   orden de ingreso       /tesoreria/ingreso/<id>  /tesoreria/movimiento/<id>  fichas
/tesoreria/anulaciones      pagos, órdenes de ingreso y movimientos vigentes; /anular POST
/tesoreria/recibos          recibos emitidos: ?q, ?nro (exacto), ?desde, ?hasta, ?clase, ?talonario, ?cuenta,
                             ?aplicacion, ?estado=vigente|anulado|todos, orden y página; /exportar (Excel)
/tesoreria/rg830            escala RG 830; ?edit=ID, ?nuevo=1, ?clonar=ID (nueva vigencia)
/tesoreria/extractos        extracto de una cuenta: ?cuenta, ?desde, ?hasta; /importar POST; /<id>/borrar POST
/tesoreria/conc             conciliaciones: ?cuenta, ?cerradas=1; /nueva POST; /saldo_inicial (JSON)
/tesoreria/conc/<id>        detalle (?anteriores=1); /vincular, /sugeridos, /desvincular, /excepcion,
                            /excepcion/quitar, /generar, /saldo_inicial, /cerrar, /reabrir, /eliminar POST
/tesoreria/conc/clasificar  conceptos del extracto: ?cuenta, ?desde, ?hasta; /guardar, /quitar POST (JSON)
/contabilidad/plan          plan de cuentas, ?edit=ID, ?nuevo=1, ?madre=ID (subcuenta con el código sugerido)
/contabilidad/plan/codigo   qué dice un código mientras se tipea (JSON: clase, tipo, nivel, madre, errores)
/contabilidad/ejercicios    ?ver=ID ficha con sus períodos, ?nuevo=1; POST accion=nuevo|guardar|activar|cerrar|reabrir
                            |borrar|periodo (id_periodo, estado)
/contabilidad/asientos      carga: ?edit=ID (un borrador), ?copiar=ID; POST graba (confirmar=1, otro=1)
/contabilidad/diario        ?ejercicio (por defecto el de trabajo; «todos»), ?periodo, ?estado, ?tipo, ?desde, ?hasta;
                            /<id> el asiento; /accion POST (confirmar, borrar, confirmar_todos); /exportar ?formato=
                            xlsx|csv; /libro ?formato=xlsx|pdf; /externo ?desde&hasta; /modelo; /importar,
                            /renumerar POST
/pagos/ordenes              órdenes de pago; /nueva (proveedores con saldo), /nueva/<id_proveedor>,
                            /anticipo/nueva, /concepto/nueva
/pagos/ordenes/<id>         ficha: aprobación, pago y anulación; /aprobacion, /pagar, /anular POST; /pdf
/pagos/pagos/<id>/anular    POST, solo Administrador
/pagos/api/orden/<id>/retenciones   bruto, retenciones y neto a una fecha (JSON, lo usa la ficha)
/pagos/transferencias      pagos por transferencia, ?cuenta, ?desde, ?hasta; /generar POST;
                            /lote/<id> (?descargar=1), /lote/<id>/descargar, /lote/<id>/excluir y /anular POST
/pagos/emision  /pagos/emitidos  /pagos/certificados (/<id>, /<id>/pdf)
/pagos/config_aprobadores  /pagos/imputaciones   ABM
/exportar/excel      POST JSON → .xlsx (lo llama el botón Exportar a Excel de las grillas)
/api/busqueda        buscador general de la barra superior, ?q= (JSON)
/estilos             guía visual del sistema
/ayuda               índice de los manuales (busca en todos); /ayuda/<clave>?s=<sección> un manual
```

### Repositorio

**Repositorio propio desde el 11/11/2026**: `github.com/estebansalaya-creator/gestion_sindicato`
(privado), con `C:\web\gestion_sindicato` como carpeta de trabajo. Antes estaba dentro del repositorio
de gestion_adm (`C:\web`), donde quedan los commits anteriores y la carpeta está en `.gitignore`.
`gestion_adm.py` ya no importa `sindicato_bp` ni monta `/sindicato` (la separación la hizo
`C:\web\separar_sindicato.bat`).

- **Subir**: `subir_github.bat` de esta carpeta: `git add -A`, muestra lo que va, pregunta, commit
  (mensaje de `mensaje_commit.txt` si existe, si no lo pide), `pull --rebase` y `push`.
- **No van** (`.gitignore`): `.env`, `web.config`, `logs/*`, `adjuntos/*`, certificados, `Claude
  outputs/`, `_to_delete/`, planillas.

### Qué falta

- **Menú**: `s_menu` y `s_roles` se cargaron con `sql/menu_y_roles_20260826.sql` y se administran desde
  Administración del Sistema → Menú (las opciones de cada persona, en Permisos por Usuario). Las opciones sin pantalla dan el 404 de «pantalla pendiente», no
  el de IIS; el ABM del menú las marca «Pendiente».
- **Logo**: `static/imagenes/LOGO.GIF` no existe todavía. El `onerror` del template lo oculta.

---

## Railway (aeda.seggestion.com.ar)

Desde el 11/11/2026 el sindicato también corre en Railway, con el subdominio `aeda.seggestion.com.ar`
(gestion_adm es `oseda.seggestion.com.ar`). El servicio web se arma desde **este** repositorio
(`gestion_sindicato`), no desde el de gestion_adm: si la pantalla de ingreso dice «Módulo Administrativo»
y pide `DB_USER`, el servicio está apuntando al repositorio equivocado.

- **Arranque**: `Procfile` (gunicorn `app:app` en `[::]:$PORT`, la red privada de Railway es IPv6) y
  `requirements.txt` (sin `pyodbc`: los importadores de AEDA se corren desde la red local).
- **HTTPS**: `ProxyFix` en `app.py`, como gestion_adm; con `RAILWAY_ENVIRONMENT` la cookie va `Secure`.
- **Base**: `sindicato` restaurada en el MySQL de Railway. `app_sindicato@'%'` y las vistas los deja
  `sql/railway_usuario_aplicacion_20261111.sql`. Variables: `SIND_DB_HOST=${{MySQL.MYSQLHOST}}`,
  `SIND_DB_PORT=${{MySQL.MYSQLPORT}}`, `SIND_DB_USER`, `SIND_DB_PASS`, `SIND_SECRET_KEY`,
  `SIND_ADJUNTOS=/data/adjuntos` (volumen en `/data`) y las `SIND_CONTABLE_*`.
- **Importadores de AEDA**: desde la máquina local, con el `.env` apuntando al proxy público del MySQL de
  Railway. La base viva es la de Railway.
- **OCR** (opcional): `RAILPACK_DEPLOY_APT_PACKAGES="tesseract-ocr tesseract-ocr-spa"`.

### Archivos: disco y bucket (22/11/2026)

Todo archivo que sube la gente (reintegros, documentación, comprobantes y su PDF de paso, logo,
flyers, fichas de las empresas, adjuntos de Mensajes) pasa por `almacenamiento.py`: se escribe en
`SIND_ADJUNTOS` y, si hay `SIND_BUCKET`, se sube la copia con la ruta relativa como clave. Antes de
servirlo o leerlo se llama `almacenamiento.local(ruta)`: si el archivo no está en ese disco (después
de un deploy, o en otra instancia) lo trae del bucket. Al borrar, `almacenamiento.borrar` se lleva los
dos. Es lo que permite correr sin disco permanente (DigitalOcean App Platform) o con dos instancias.

- **Código nuevo que guarde un archivo**: `almacenamiento.guardar(ruta, bytes)` o, después de un
  `save()`, `almacenamiento.respaldar(ruta)`; para leerlo, `almacenamiento.local(ruta)`; para borrarlo,
  `almacenamiento.borrar(ruta)`. Nunca `unlink()` suelto: dejaría la copia en el bucket.
- `arca/` (los tickets de acceso de ARCA) no va al bucket: es caché.
- **Pasar a un bucket**: crearlo, cargar las `SIND_BUCKET_*` en el entorno (y en el `.env` local) y
  correr `python almacenamiento.py --subir` (simula) y `--subir --aplicar` desde donde estén hoy los
  archivos (el volumen de Railway). Prueba: `tests/test_almacenamiento.py` (con `moto`).

## IIS

El sitio corre con wfastcgi. **El sitio se llama `aeda` en la consola de IIS**, no `sindicato`:
esteban lo había creado antes para esto mismo, y se reusó en vez de agregar un cuarto sitio. El
pool sí se llama `sindicato`.

```
sitio      aeda            puerto 5001    C:\web\gestion_sindicato
pool       sindicato       ApplicationPoolIdentity, sin runtime .NET
handler    wfastcgi        Python314 de C:\Users\esteban\AppData\Local\...
```

- **Puertos ocupados en esta máquina**: 80 (Default Web Site), 5000 (gestion), 5001 (este sitio).
  Reservados por el sistema: 50000-50059 y 50128. El servidor de desarrollo usa 5055.
- **`web.config` no lleva credenciales.** Solo `WSGI_HANDLER`, `PYTHONPATH` y `WSGI_LOG`; el resto
  sale del `.env`. El de `gestion_adm` sí tiene todo en `<appSettings>` — no copiar ese patrón.
- **`logs/` tiene que existir**: wfastcgi abre el archivo pero no crea el directorio, y si falta el
  arranque muere con un `FileNotFoundError` del file watcher que no dice nada del problema real.
  Por eso hay un `logs/.gitignore` que ignora el contenido pero conserva la carpeta.
- **Permisos del pool**: `IIS AppPool\sindicato` necesita `RX` sobre la carpeta —sin eso no puede
  leer el `.env` y la app muere con «Falta SIND_DB_USER», que suena a variable faltante y es de
  permisos— y `M` sobre `logs/` y sobre `adjuntos/` (los comprobantes de reintegros).
- **`WSGI_LOG` conviene sacarlo** del `web.config` cuando el sitio quede publicado: manda el
  traceback al navegador, con rutas y consultas adentro.

Los pasos que hay que correr en PowerShell **como administrador** (crear el pool falla en silencio
si no lo está) están en el historial del proyecto: `New-WebAppPool`, `managedRuntimeVersion` vacío,
los dos `icacls`, y `wfastcgi-enable.exe` —este último registra FastCGI a nivel servidor y es el
que más se olvida.

---

## Entorno

Todas las variables llevan prefijo `SIND_` para no cruzarse con las de `gestion_adm`, que tiene su
propio `.env` en su propia carpeta.

```
SIND_DB_HOST  SIND_DB_PORT  SIND_DB_USER  SIND_DB_PASS
SIND_SECRET_KEY  SIND_PORT
SIND_AEDA_SERVER  SIND_AEDA_USER  SIND_AEDA_PASS  [SIND_AEDA_DRIVER]   origen AEDA (importar_aeda.py)
[SIND_ADJUNTOS]                                   comprobantes, PDF y logo (por defecto adjuntos/)
[SIND_BUCKET  SIND_BUCKET_ENDPOINT  SIND_BUCKET_KEY_ID  SIND_BUCKET_SECRET  SIND_BUCKET_REGION]
                                                  el bucket S3 de los adjuntos (almacenamiento.py): DigitalOcean
                                                  Spaces o un bucket de Railway. Sin SIND_BUCKET, sólo el disco
[SIND_ARCA_CERT  SIND_ARCA_KEY  SIND_ARCA_CUIT]   ARCA (opcional): constatación, padrón A13, constancia
[SIND_ARCA_CERT_B64  SIND_ARCA_KEY_B64]           ídem en base64, para Railway (sin archivos)
[SIND_TESSERACT_CMD]                              OCR de PDF escaneados (opcional)
[SIND_CONTABLE_HOST  _PORT  _USER  _PASS  _DB]    contable en Railway, solo lectura (contable_oseda.py)
[SIND_URL_PUBLICA]                                https://aeda.seggestion.com.ar: arma el enlace de las empresas
                                                  y el de «no recibir más» de las campañas
SIND_FERNET_KEY                                   cifra las contraseñas del correo saliente: la MISMA en el .env
                                                  local y en Railway (usan la misma base)
```

- **La base no se configura por entorno.** `DB_NAME = "sindicato"` es constante en `db.py`, para que
  ningún `.env` mal copiado pueda hacer que esta app escriba en `contable`. La regla de oro la
  garantiza el código, no la memoria.
- **`SIND_DB_USER` no tiene default.** Antes de esto la aplicación caía en `root` cuando faltaba la
  variable, sin decir nada. Ahora no arranca.
- **El `.env` se resuelve contra `__file__`, no contra el directorio de trabajo.** `load_dotenv()`
  sin argumentos busca desde el cwd, y el cwd no se controla: IIS arranca el proceso donde quiere y
  una tarea programada usa lo que diga «Iniciar en».
- El usuario de MySQL es `app_sindicato`, creado por `sql/usuario_aplicacion_20260826.sql`, con
  permisos **solo** sobre `sindicato`. Así la separación de bases la aplica MySQL y no depende de
  que el código se porte bien.

## Sesión

Las claves llevan prefijo `sind_`: si las dos apps quedan bajo el mismo dominio y comparten cookie,
entrar a una no habilita la otra. La cookie también tiene nombre propio (`sindicato_session`).

```
sind_validausuario  sind_usuario_id  sind_usuario_email  sind_usuario_nombre  sind_roles
```

Al copiar cualquier template de `gestion_adm`, revisar que no queden `session.get('validausuario')`
ni `session.get('registrado')`: son las claves de la otra app y fallan en silencio — el bloque
simplemente no se dibuja, que es más difícil de notar que un error.

---

## Origen: AEDA (SQL Server)

**Para este proyecto, la base de origen es siempre `aeda`** del servidor que expone el MCP
`sqlserver-origen`. Es el sistema viejo del sindicato.

- **Servidor**: máquina `SERVEROSEDA`, instancia `OSEDA`, SQL Server 2014 (sin `STRING_AGG`: usar
  `FOR XML PATH`). El MCP entra por IP, TCP 1433, con el login de solo lectura `mcp_lectura`.
  `@@SERVERNAME` todavía devuelve `SANDRA-PC\OSEDA` —la máquina se renombró— y ese nombre no
  resuelve: no usarlo para conectar. En el `.env` va `IP,1433`.

- **El MCP abre por defecto en `oseda`** —la obra social—, que tiene tablas con el mismo nombre:
  `oseda.dbo.afi_empresas` tiene 2.580 empresas y `aeda.dbo.afi_empresas`, 840. Una consulta sin
  calificar no falla, devuelve las de la otra base. Escribir siempre `aeda.dbo.<tabla>`.
- En `importar_aeda.py` la base es una constante (`AEDA_DB`), como `DB_NAME` en `db.py`.
- **Contactos**: `aeda.dbo.adm_contactos` es polimórfica por `ref_id` — `E` empresa (`ref_nro` =
  `afi_empresas.empre_id`), `A` afiliado, `P` proveedor. Las de empresa son casi todas cargo
  «PAGOS». Además `afi_empresas` trae `emp_telefono` y `emp_email` sueltos, con varios valores o
  texto libre en el mismo campo.
- `afi_empresas.emp_calle` es calle, número, piso y oficina en un solo texto: va entero a
  `dom_calle`. `prov_id` no coincide con `p_provincia.codigo` a partir del 19: se cruza por nombre.
- Lo importado lleva su origen al principio de `observaciones` —`[AEDA afi_empresas 755]`,
  `[AEDA adm_contactos 2730]`— y es lo que hace que el script se pueda volver a correr sin duplicar.

## Padrón de afiliados

`p_afiliados` vino de `contable` con el diseño del padrón SSS; `sql/afiliados_20261107.sql` amplió
`domicilio_calle` a 100 y agregó el parentesco 10 «Otro» y cuatro nacionalidades que usa AEDA.

- **Una fila por persona**, CUIL único. El grupo es `cuil_titular`; un titular tiene
  `cod_parentesco = 0` y `cuil_titular = cuil`.
- **Apellido y nombres**: una sola columna, `apellido_nombres` varchar(100). AEDA los trae juntos
  («DIAZ RAIDAN MAYRA CANDELA») y partirlos por regla falla con los apellidos compuestos. Hasta el
  10/11/2026 eran `apellido` + `nombre` (siempre vacío); `sql/afiliados_apellido_nombres_20261110.sql`
  los unió, borró `nombre` y rehízo `v_reintegros_afiliados`. La auditoría vieja sigue diciendo
  «Apellido» / «Nombre».
- **CUIL repetido en AEDA**: la misma persona en dos grupos (titular y además hijo en el de los
  padres) queda en una fila —la activa; entre activas, la de titular— y la otra pertenencia va a
  observaciones. Dos personas distintas con el mismo CUIL entran las dos; el CUIL queda para la que
  coincide con el sexo del prefijo (20/27) y la otra entra sin CUIL.
- **No hay marca de «afiliado al gremio»**: esta es la base del gremio y todos lo son. El atributo
  `AEDA — Afiliado al Gremio` de `p_afiliado_atributo` vino copiado de la obra social y está
  desactivado (`sql/afiliados_sin_marca_aeda_20261107.sql`); el campo `aeda` de `afi_benef` no se
  importa.
- **Atributo «Tiene hijos»** (`sql/afiliados_atributo_hijos_20261114.sql`, pedido del 14/11/2026): el titular declara
  hijos aunque no estén cargados en el padrón. En AEDA es `afi_benef.hijos` (0/1, solo titulares), que el importador
  dejaba en observaciones («Hijos declarados en AEDA: 1.»); el script lo pasó al atributo (1.339: 1.032 activos, 307
  de baja; 124 de los activos no tienen hijos cargados) y `importar_aeda_afiliados.py` lo marca en las altas nuevas.
  Se tilda en la ficha (Atributos) y se filtra en el listado. Los atributos Judicializado, Amparo y Seguimiento
  vinieron de la obra social y siguen activos.
- **Baja lógica, nunca DELETE**: fecha y motivo (`p_motivo_movimiento`, `es_alta = 0`). **El grupo cae con el
  titular** (decidido el 17/11/2026): la baja de un titular da de baja a sus familiares activos, siempre, con la
  misma fecha y motivo. AEDA deja a los familiares sin baja aunque el titular se vaya: `importar_aeda_afiliados.py`
  los da de alta de baja con la fecha del titular, y `sql/afiliados_baja_grupo_20261117.sql` corrigió los 445 que
  habían entrado activos (familiares activos: 2.529 → 2.084, como AEDA con el titular activo). De `p_afiliados` cuelgan por FK reintegros y comprobantes.
- **Auditoría**: todo cambio deja una fila por campo en `p_afiliados_movimientos` (valores legibles:
  «3 · Hijo soltero…», no «3»). Si un campo se agrega a `CAMPOS` de `afiliados.py`, queda auditado;
  si se agrega al formulario y no ahí, se guarda sin rastro.
  **La baja y la reactivación son un renglón** (pedido del 25/11/2026, como gestion_adm): la baja, `campo = 'fecha_baja'`,
  rótulo «Baja», valor «25/11/2026 · RENUNCIA» (`CAMPO_BAJA`); la reactivación, `campo = 'estado'`, «Baja … → Activo».
  Antes eran tres (Activo, Fecha de baja, Motivo): `sql/afiliados_movimientos_baja_un_renglon_20261125.sql` juntó los
  que había. El alta ya era uno solo.
- **Listado paginado en el servidor** (11/11/2026): mandar el padrón entero (5.617 personas) eran 8,5 MB de HTML y
  en Railway tardaba. Ahora filtros, orden y página van en la URL (`_filtros_listado`, `_consultar_listado`,
  `paginar.py`) y la base devuelve 50 filas; «Exportar a Excel» es `/afiliados/exportar` con los mismos filtros. Los
  índices ya estaban bien. El buscador busca cada palabra en apellido, localidad y empleador, y los números (sin
  guiones) en CUIL, CUIL titular y documento. Es el patrón para cualquier grilla de miles de filas (ver `/estilos`).
- **Consulta y ABM por separado**: «Consulta del Padrón» (`/afiliados/padron`, menú 23) muestra
  listado y ficha sin poder editar; «ABM de Afiliados» (`/afiliados`, menú 21) edita. Es la misma
  plantilla con `modo`. El permiso **es la opción de menú**: `db.puede(url)` mira si alguna opción
  activa con esa URL está en `sind_menu_ids` de la sesión. Quien tiene el ABM entra también desde
  la consulta y ve ahí los botones de editar; quien no, y abre `/afiliados?edit=ID`, cae en la
  consulta de ese afiliado. El POST de la ficha y el de sus contactos se controlan en el servidor,
  no solo ocultando botones. Para que un rol solo consulte se le quita la opción 21 en
  `s_menu_rol`; los permisos de la sesión se vuelven a leer cada minuto.
- **Cambio de CUIL de un titular**: arrastra el `cuil_titular` de su grupo y el `cuil` de
  `p_relaciones_laborales`, que lo referencian por CUIL y no por id.
- **Documento, sexo, CUIL y ARCA** (pedido del 15/11/2026): la ficha arranca por Identificación, en el orden tipo
  de documento, número, sexo, CUIL. Con DNI, LE o LC el CUIL se calcula solo (`cuilDesdeDniSexo` en la plantilla,
  `arca_padron.cuil_de` en el servidor: 20 varón, 27 mujer, 23 si el dígito no entra); un CUIL escrito a mano no se
  pisa. En el alta, con documento y sexo, se le pregunta a ARCA (`/afiliados/arca`, `arca_padron.py`, padrón A13:
  `getIdPersonaListByDocumento` + `getPersona`): ARCA dice qué CUIL tiene el documento (puede no ser el calculado;
  con varios, se elige) y sus datos completan lo vacío —apellido y nombres, nacimiento, domicilio fiscal (solo si el
  domicilio está vacío entero; la provincia por nombre: el `idProvincia` del padrón de ARCA no es `p_provincia.codigo_arca`)—. Lo cargado y distinto no se pisa: se
  lista con «Usar los datos de ARCA». Un CUIL que ya está en el padrón avisa con el enlace a esa ficha y no completa
  nada; el fallecimiento y una clave no ACTIVO se avisan. «Consultar ARCA» lo hace a pedido (también al editar).
  **Necesita el certificado propio** (`SIND_ARCA_CERT` / `SIND_ARCA_KEY` / `SIND_ARCA_CUIT`, ver «Constatación con
  ARCA») con el servicio `ws_sr_padron_a13` asociado en el Administrador de Relaciones de ARCA; sin eso el CUIL se
  calcula igual y la pantalla lo dice. El token es por servicio (`arca_wscdc.token(servicio)`, `ta_<servicio>.json`).
  Test: `python tests/test_arca_padron.py`, sin ARCA.
- **Historial de empleadores** (solapa Empleadores): `p_relaciones_laborales` por CUIL, con período
  desde/hasta. AEDA (`afi_afixempre`) solo trae el empleador actual y la fecha de ingreso, sin
  egreso: la relación importada sigue el estado del afiliado (`activa`/`inactiva`), 411 vinieron sin
  fecha de ingreso y se pueden editar sin inventarla. Vigente = `activa` y sin egreso o con egreso de
  hoy en adelante. **El empleador de la ficha (`cuit_empleador`) es el de la relación vigente más
  nueva**: se recalcula al guardar en la solapa y en la ficha es de solo lectura; en el alta sí se
  carga y crea la primera relación (desde = fecha de alta). El empleador tiene que estar en
  `p_empresas`; no se aceptan dos períodos superpuestos con el mismo empleador. Situación de
  revista, convenio y remuneración no se muestran. Cada cambio queda en la auditoría
  (campo `relacion_laboral`).
- **Documentación** (solapa Documentación): `p_documentacion` con `entidad_tipo = 'afiliado'`. Los
  tipos son los de `p_tipo_documentacion` con `afiliado` en `aplica_a` más los generales (`aplica_a`
  vacío). PDF o imagen, hasta 10 MB, en `SIND_ADJUNTOS/documentacion/afiliado/<id>/` con nombre
  generado. Ver: quien consulta el padrón; subir y eliminar: quien tiene el ABM. Auditado (campo
  `documentacion`).
- **Carga de DNI y foto** (pedido del 25/11/2026; `afiliados_dni.py`, `lector_dni.py`, `afiliado_foto.py`,
  `sql/afiliados_foto_dni_20261125.sql`): una o dos fotos del DNI en cualquier orden. `lector_dni.leer` lee el PDF417
  del frente (zxing-cpp; la foto de celular casi nunca sale en grises: se prueba binarizada y a varias escalas) y
  recorta la cara (Haar de OpenCV, con un ojo en la mitad de arriba para descartar caras cabeza abajo; prueba primero el
  giro que dio el código). Formatos: **tarjeta** `trámite@APELLIDO@NOMBRES@sexo@DNI@ejemplar@nacimiento@emisión` (sin
  vencimiento, domicilio ni CUIL) y **libreta** (empieza con «@», trae vencimiento). El sexo viene como letra o con
  el código de ARCA / ANSES (1 M, 2 F, 3 X: `lector_dni.SEXO_CODIGO`); otra cosa no se toma. La imagen con código (o con cara) es el frente; la otra, el dorso (domicilio por OCR si hay
  tesseract). Lo leído queda en `tmp_dni/<ficha>_*` (disco y bucket, se borra a los 2 días) y el paso 2
  (`/afiliados/dni/<ficha>`) busca por `nro_documento` y por los 8 del medio del CUIL, con lo que coincide o no
  (apellido, primer nombre, nacimiento, sexo). **Nada se guarda sin elegir a la persona**. Guardar: cada imagen a
  `p_documentacion` con el tipo `dni_frente` / `dni_dorso` (por código) y la foto (JPEG 300×400) a
  `fotos/afiliado/<id>/<uuid>.jpg`, ruta relativa en `p_afiliados.foto`; auditado (campos `documentacion` y `foto`). Los
  datos de la ficha no se tocan. Sin nadie con ese documento: «Dar de alta con estos datos» (`/afiliados?nuevo=1&…`).
  En la ficha la foto va a la derecha de Identificación (`.con-foto`), con Cambiar (cualquier imagen: `lector_dni.retrato`
  recorta la cara o el centro) y Quitar; «Cargar DNI» en el encabezado lleva a la carga con `?para=ID`. Permiso: la
  opción de menú `/afiliados/dni` (el script la da a quien tiene el ABM). **OpenCV anterior a la 5**: la 5 no trae los
  `haarcascade_*.xml`. Prueba sin base: `python tests/test_lector_dni.py`; con una foto: `python lector_dni.py foto.jpg`.
- **Tablas auxiliares** («Tablas Auxiliares», menú 24, `sql/afiliados_tablas_20261110.sql`, roles
  Administrador y Supervisor): estado civil, nacionalidades, parentescos, provincias, tipos de
  documento, motivos de alta y baja, atributos y tipos de documentación (solo los del afiliado). Las
  de «Tablas Auxiliares Padrón SSS» de gestion_adm **sin situación de revista** (pedido del
  10/11/2026) y sin tipo de beneficiario, que el padrón del gremio no tiene. Se declaran en `TABLAS`
  de `afiliados_tablas.py`: el código de las tablas SSS lo pone quien carga y no se cambia después;
  lo que se usa no se borra (se desactiva si la tabla tiene `activo`); el parentesco 0 y el DU no se
  borran.
- **Cuota social YMCA** (solapa de la ficha, pedido del 15/11/2026; `recibos_afiliado.del_afiliado` y
  `transferencias_sin_recibo`): los recibos al afiliado por la cuota social (con ver y PDF) y, arriba, sus
  transferencias del extracto sin recibo (las que AEDA registró en su orden del mes, marcadas). El nombre de la solapa
  es el concepto de Datos del Sindicato; `?solapa=cuota_social`. Lo de antes de noviembre de 2026 no tiene recibo por
  afiliado: AEDA lo registró junto.
- **Aportes OSEDA** (solapa de la ficha, pedido del 15/11/2026; `afiliado_aportes.py`, `_aportes_oseda.html`): la
  solapa Aportes del Análisis de afiliado de gestion_adm (`afiliado_analisis._aportes` + `padron._fila_diferencia`),
  **solo para quien tiene o tuvo DDJJ de OSEDA**: si nadie del grupo familiar figura en `f_ddjj_procesada`, no hay
  solapa. En vivo de contable en Railway (`contable_oseda.aportes_de_cuiles`, una conexión: DDJJ, transferencias,
  `f_deuda_empresa` y razón social). La ficha se dibuja sin esperar a Railway y la pide después
  (`cargarAportes()`, `/afiliados/<id>/aportes`): con 204 no aparece; si Railway no responde, sale con el aviso.
  Por período, últimos 36 con DDJJ o transferencia: remuneración, Rem. 5, aporte y contribución declarados, lo
  percibido, monotributo, pagado y diferencia, más la **cuota sindical liquidada** al afiliado (`fisca_liquidacion`
  vigente; el CUIT lleva a la cuota del período de la cuenta corriente). La diferencia sale del empleador: su parte
  de lo que el empleador quedó debiendo en el período, no lo prorrateado por CUIL; hasta $ 1,50 es redondeo. Los
  aportes son del titular: la ficha de un familiar muestra los del titular, y quien aporta a su nombre (relación de
  dependencia o monotributo) tiene su propia grilla. Test: `python tests/test_afiliado_aportes.py`, sin base.

## Métricas del padrón

`afiliados_metricas.py` (`/afiliados/metricas`, menú 22), el tablero de gestion_adm (`padron.metricas`)
para un gremio: sin cobertura, tipo de beneficiario, comercializadores ni las validaciones del diseño de
la SSS; con afiliados por empleador, antigüedad en el gremio y controles del grupo familiar.

- **Afiliado = titular.** Los familiares son personas a cargo. Indicadores: afiliados activos,
  familiares, personas por afiliado, edad promedio de los afiliados, empleadores con afiliados, altas
  menos bajas del período.
- **Filtros** (GET): estado (activos / padrón completo), personas (titulares y familiares / solo
  titulares) y período de altas y bajas (por defecto los últimos 24 meses, tope 120). Las altas y bajas
  se cuentan sobre el padrón completo; los indicadores, el bloque de empleadores y los controles son el
  padrón activo de hoy y no siguen los filtros.
- **Por empleador**: titulares activos con relación vigente (la regla de la Nómina); uno con dos
  empleos cuenta en los dos. Una relación con un CUIT que no está en `p_empresas` sale con su CUIT.
- **Controles** (`CONTROLES`, con su condición SQL): hijos de 21, estudiantes de 26, estudiantes sin
  certificado del último año, familiares sin titular activo, titulares sin empleador vigente, sin CUIL,
  CUIL que no verifica (en Python, `cuit_valido`), sexo contra el prefijo del CUIL, sin nacimiento,
  domicilio incompleto, alta futura y bajas sin motivo. `?control=<clave>` abre la lista con enlace a
  la ficha (al ABM si tiene permiso, si no a la consulta). Para sumar uno, una línea en `CONTROLES`.
- **Empleador distinto del último que lo declara** (`?control=ddjj_empleador`, pedido del 12/11/2026): titulares
  activos cuyo empleador del padrón (sus relaciones vigentes o, sin ellas, el de la ficha) no es el último CUIT que
  los declaró en la DDJJ de OSEDA, en toda la historia (`contable_oseda.declarantes_por_cuil`, en vivo a Railway).
  Con dos empleos o dos declarantes en el último período alcanza con que uno coincida. Muestra el último período y
  el último en que lo declaró su empleador («nunca»). No está en `CONTROLES`: se consulta solo al abrirlo; en la
  tabla de controles sale con «—» y «Se consulta al abrirlo». Los que no figuran en ninguna DDJJ se cuentan aparte.
- **Gráficos en HTML y CSS** (sindicato.css 15e: `.reparto`, `.evol`, `.piramide`, `.leyenda`), sin
  Chart.js: en la intranet el CDN no siempre responde. Colores `--serie-1/-2/-baja`, validados para
  daltonismo. Cada marca lleva su `title` y el mensual tiene su tabla exportable.

## Liquidación de cuota sindical

`fisca_liquidacion.py` (`/fiscalizacion/liquidacion`, menú 6 «Liquidación de Cuota Sindical» en Fiscalización de
Cuotas, Administrador y Supervisor; `sql/fisca_liquidacion_20261111.sql` y `sql/fisca_liquidacion_ddjj_20261112.sql`).
Lo que cada empleador tiene que pagar por período: `fisca_liquidacion` (una por CUIT y período, `uq_fisca_liq`) +
`fisca_liquidacion_detalle` (un renglón por afiliado). Es lo que AEDA hacía en `fis_deuda` / `fis_deuda_detalle`.

- **Solo DDJJ de OSEDA (decidido el 12/11/2026, reemplaza lo del 11/11)**: la Remuneración imponible 5 de cada titular
  del padrón en la DDJJ del período (`f_ddjj_procesada` en contable de Railway, en vivo); la liquidación es del CUIT que
  lo declaró. La nómina de los empleadores (`fisca_cuotarecepcion`, Importar Cuotas) ya no se usa para liquidar.
  Afiliado del período = titular con alta hasta el último día y sin baja o con baja desde el primero.
- **Activos del empleador y % con DDJJ (pedido del 12/11/2026)**: cada liquidación lleva a TODOS los titulares
  activos del empleador en el período, con DDJJ o sin ella. Activo = relación laboral con ese CUIT vigente en el
  período (ingreso hasta el último día o sin ingreso, egreso desde el primero); una relación inactiva sin egreso (las
  de AEDA) termina con la baja del afiliado, y si el afiliado no tiene baja no cuenta. Columnas: `afiliados_activos`
  (total), `activos_con_ddjj` (en la DDJJ de ESE empleador), `activos_sin_ddjj` y `porc_ddjj` (calculadas en la base);
  `afiliados` = los liquidados (con remuneración). Detalle: fuente `ddjj` (con `activo` = 1 si además es activo del
  empleador; 0 = lo declara sin relación laboral en el padrón) y `sin_ddjj` (activo no declarado, en cero). Un
  empleador con activos y ninguno en su DDJJ tiene su liquidación en cero, con la nota.
- **Activos sin DDJJ, por la escala** (pedido del 16/11/2026, `sql/fisca_liquidacion_escala_20261116.sql`; test:
  `python tests/test_fisca_liquidacion_escala.py`, sin base): el renglón del activo que no está en la DDJJ se
  liquida con el **conformado** de la escala vigente del período (básico de su antigüedad + almuerzo × 22), fuente
  «escala», con la antigüedad usada en `fisca_liquidacion_detalle.antiguedad`. Antigüedad: años cumplidos al último
  día del período (tope 35) desde la fecha más vieja entre las relaciones con ESE empleador que empezaron hasta ese
  día (`fecha_antiguedad` o el ingreso); sin fecha, «Inicial». Sin escala en el período, sigue «sin_ddjj» en cero.
  No toca lo declarado en cero en la DDJJ ni lo presentado por la empresa. `activos_con_ddjj` sigue siendo solo DDJJ.
  El script completa lo ya liquidado con la misma regla (reliquidar da lo mismo).
- **Ojo al leer el %**: «sin DDJJ» es no estar en la DDJJ de OSEDA; un afiliado con otra obra social no figura ahí
  aunque el empleador lo declare en su F.931. Simulado el 12/11/2026: ≈1.950 activos por mes, ≈64 % con DDJJ.
- **Cuota** = remuneración × `s_institucion.cuota_alicuota` (2,50 %, en Datos del Sindicato), al centavo por renglón.
  **Vence el mismo día que el F.931 del empleador** (decidido el 14/11/2026; antes el 20 del mes siguiente,
  `cuota_dia_vto`, que ya no se usa): `fisca_intereses.Calendario`, ver «Actas de fiscalización y acuerdos de pago».
- **Liquidar un rango** (`generar_rango`): padrón una vez, DDJJ de todo el rango de Railway de a 12 períodos, cada
  período en su transacción. Pantalla: Desde / Hasta, hasta 48 períodos. Consola (sin el tope de tiempo de IIS):
  `python fisca_liquidacion.py 202401 202609 [--simular] [--usuario mail@…]`. Sin Railway no se liquida nada.
- **Liquidar de nuevo** rehace el detalle con lo de hoy y anula, con la nota, la de un empleador que se quedó sin
  base. El último período suele tener la DDJJ incompleta (202610 tenía 1.719 filas contra ≈2.420): se reliquida
  cuando se complete.
- **Lo presentado con el Libro de Sueldos Digital no se reliquida por DDJJ** (origen «lsd», ver «Presentación del
  Libro de Sueldos Digital»): manda el archivo de la empresa. Anular la presentación la devuelve a la DDJJ.
- **Lo de AEDA se reliquida** (cambiado el 12/11/2026): pasa a origen «ddjj» y lo que había liquidado AEDA queda en
  `aeda_importe`, `aeda_afiliados` e `id_aeda` (pantalla: columna «Liquidado AEDA»); la marca «[AEDA fis_deuda N]» sale
  de observaciones. `importar_aeda_fisca_deuda.py` solo reconoce como suyas las de origen «aeda», así no pisa una
  reliquidada. AEDA liquidaba ≈250-340 afiliados por mes; por DDJJ son ≈1.300.
- **Sin cobros** (decidido el 11/11/2026): `fis_deudaaplic` está vacía y `fis_cobros` no se aplica a la deuda. La
  cuenta corriente de empleadores, primera etapa (12/11/2026): saldo = liquidado − cobrado, sin aplicar
  (`logs/saldos_empleadores_*.xlsx`). Los cobros se aplican a las cuotas desde el 14/11/2026 (ver «Aplicación de cobros a las cuotas»); faltan los intereses por mora.

## Actas de fiscalización y acuerdos de pago

`fisca_actas.py` + `fisca_intereses.py` (`sql/fisca_actas_20261114.sql`, menú 14 «Actas de Fiscalización» y 15
«Acuerdos de Pago» en Fiscalización de Cuotas › Fiscalización, Administrador y Supervisor; test: `python tests/test_fisca_intereses.py`,
sin base). Pedido del 14/11/2026, portado de gestion_adm (`fiscalizacion_routes.acta_*`, `acuerdo_*`) sobre la cuenta
corriente de acá.

- **Vencimiento = el del F.931** del CUIT (`Calendario.vencimiento`): `arca_vencimientos` (obligación F931, período,
  último dígito; la de gestion_adm, copiada con `importar_arca_tablas.py`) y, si falta, la regla de ARCA: día 9
  (terminación 0-3), 10 (4-6) u 11 (7-9) del mes siguiente, al día hábil siguiente (`arca_feriados`). Lo usan la
  liquidación por DDJJ, la del LSD y `importar_aeda_fisca_deuda.py`; el script SQL pasó las ya hechas. ARCA a veces
  corre una fecha más que la regla (enero de 2026, terminación 7-9: la agenda dijo 13 y la regla da 12).
- **Interés resarcitorio de ARCA** (`interes`, `tramos`): simple, capital × Σ tasa mensual / 30 × días, cada día con
  la tasa de `arca_intereses` vigente (vigencia_hasta inclusive). Los días van del siguiente al vencimiento hasta el
  pago o la fecha de cálculo (pago − vencimiento). gestion_adm perdía un día en cada cambio de tasa; acá no. Al
  14/11/2026 rige 2,75 % mensual (Res. 823/2025 ME, desde el 01/07/2025); una tasa nueva se carga en gestion_adm y se
  trae con `importar_arca_tablas.py --aplicar` (o un INSERT en `arca_intereses`).
- **El acta** (`calcular`): las liquidaciones vigentes del CUIT del rango, vencidas a la fecha de cálculo y que no estén
  en otra acta cerrada. Por período: pagado en término y tarde (las aplicaciones de `fisca_aplicacion` según la fecha
  del cobro; lo cobrado después de la fecha de cálculo no cuenta), saldo con su interés hasta la fecha de cálculo y,
  con «pagos fuera de término» (por defecto sí, decidido el 14/11/2026), el interés de cada cobro tardío del
  vencimiento a su fecha (`fisca_acta_pago`). Se graba el detalle: el acta dice lo que se calculó ese día.
- **Estados**: abierta (una por CUIT; se corrige y «Guardar y recalcular» la rehace), cerrada (la deuda queda firme;
  habilita el acuerdo), anulada (con motivo; no con un acuerdo vigente; sus períodos se pueden volver a reclamar).
  Número `ACTA-AAAA-NNNNNN` y `AP-AAAA-NNNNNN` (`c_numeradores`).
- **Menú como en OSEDA** (`sql/menu_fiscalizacion_20261115.sql`, pedido del 15/11/2026): Fiscalización de Cuotas ›
  **Fiscalización** (rama 17) › Actas de Fiscalización (14), Acuerdos de Pago (15), Fiscalizadores (16), como
  Recaudaciones › Fiscalizacion de gestion_adm. Su «Deuda por Empleador» es acá Empleadores › Cuenta Corriente (botón
  «Acta de fiscalización»); el acta nueva también sale de Actas («Acta nueva», con el CUIT).
- **Fiscalizadores** (`fisca_fiscalizador`, `sql/fisca_fiscalizadores_20261114.sql`, menú 16, pedido del 14/11/2026; el
  `f_inspectores` de gestion_adm): apellido y nombres, DNI (único), cargo, teléfono, correo, usuario del sistema
  opcional. El acta se labra con uno activo: guarda `id_fiscalizador` y, como se imprimió, `inspector` e
  `inspector_dni` (corregir la ficha no cambia un acta labrada). Uno que figura en actas no se elimina: se desactiva.
- **Acuerdo** (sobre un acta cerrada, uno vigente): la deuda es el total del acta; el interés de financiación se escribe
  a mano (decidido el 14/11/2026) y el cronograma se propone en cuotas iguales, editables. El total financiado es la
  suma de las cuotas y el interés lo que supera a la deuda; si no la cubre, no se graba. Estados: vigente, cancelado
  (pagado), judicializado, anulado (con motivo). Un acta con acuerdo cancelado no admite otro.
- **PDF** (reportlab, membrete de Datos del Sindicato): acta (identificación, empleador, determinación, deuda por
  período, pagos fuera de término, tasas usadas, intimación, firmas) y acuerdo (partes, deuda, cronograma, cláusula,
  firmas). Los textos legales están en `TEXTO_*` de `fisca_actas.py`: **a revisar con el asesor legal**. Lugar de pago
  y plazo de intimación en Datos del Sindicato (`acta_lugar_pago`, `acta_plazo_dias`).
- **Detalle de un período** (pedido del 15/11/2026, como los diálogos «por CUIL» y «tramos de interés» de la Deuda por
  Empleador de gestion_adm): el ojo de cada renglón de «Deuda por período» abre un diálogo (`modal-caja pantalla`) con
  `fisca_acta.acta_periodo` → `_acta_periodo.html`: las cifras del renglón; los afiliados de la liquidación con el
  saldo y el interés repartidos en proporción a su cuota (`prorratear`, la diferencia de redondeo a la mayor: la
  columna suma justo el total; es el anexo por afiliado, exportable); los cobros aplicados a la cuota (en término,
  N días tarde con su interés, o después del cálculo) y el interés del saldo por tramo de tasa (`FI.tramos`). De un
  acta guardada muestra lo grabado; de la nueva, lo que calcula la pantalla con sus datos.
- La cuenta corriente marca en cada período el acta que lo reclama y tiene el botón «Acta de fiscalización».
- **Cobros del acuerdo** (14/11/2026): con los recibos de fiscalización (ver «Recibos: talonarios y fiscalización»).
  El acuerdo muestra lo pagado y el saldo de cada cuota y sus recibos; sin saldo pasa solo a «cancelado»; con
  recibos no se modifica. La lista de acuerdos tiene Cobrado y Falta.
- **Pendiente**: multas, el anexo por afiliado en el PDF del acta (en pantalla ya está, en el detalle del período) y
  el envío por mail.

## Presentación del Libro de Sueldos Digital (cuota sindical)

`fisca_lsd.py` + `lsd_lector.py` (`sql/fisca_lsd_20261112.sql`, menú 7 «Presentaciones LSD» en Fiscalización de
Cuotas, Administrador y Supervisor; test: `python tests/test_fisca_lsd.py`, sin base). Pedido del 12/11/2026: que las
empresas suban el archivo de liquidación del Libro de Sueldos Digital y se complete sola la planilla de la cuota
sindical con los afiliados activos. Reemplaza a la planilla que generaba el sistema viejo, que se mandaba por mail y
el empleador completaba a mano («no era nada seguro»).

- **Acceso: enlace personal por empresa** (decidido el 12/11/2026), `/empresas/<token>`, sin usuario ni clave. Se
  genera en Empleadores, solapa «Cuota sindical» (`fisca_lsd.enlace`), y se manda por mail desde ahí (abre el correo
  de quien lo manda, a los mails de la ficha y de los contactos: la app no envía mails). De `fisca_enlace_empresa` se
  guarda el SHA-256 del token, nunca el token: el enlace se ve UNA vez, al generarlo (viaja por la sesión,
  `sind_enlace_nuevo`). Generar otro corta el anterior; «Revocar» lo corta sin generar otro. El portal tiene su propia
  plantilla (`templates/portal/base.html`, sin menú) con `noindex` y `no-referrer`; con el enlace solo se ve y se sube
  lo del CUIT del enlace. Un token sin el formato da el 404 del portal sin ir a la base.
- **Confidencialidad** (pedido del 12/11/2026): el mismo texto (`fisca_lsd.CONFIDENCIALIDAD`, Ley 25.326, la
  afiliación sindical es dato sensible) va en el mail del enlace y arriba de las páginas del portal.
- **El archivo**: el de liquidación del LSD (registros 01 a 06, ver `lsd_lector.py`); se valida el diseño, el CUIT del
  enlace y que el período ya haya empezado. Con errores no se guarda nada y se listan los renglones. Se guarda entero en
  `fisca_lsd_presentacion.archivo`.
- **La planilla** (`armar_planilla`): afiliado del período (la regla de fisca_liquidacion) que está en el archivo, con
  su **Remuneración imponible 5 del registro 04** (la misma base que la DDJJ) × la alícuota de Datos del Sindicato;
  más los activos del empleador que no están en el archivo, en cero; los no afiliados solo se cuentan. Si el recibo
  trae el concepto ARCA 810004 «Cuota Sindical», se muestra lo retenido al lado (con la muestra de 202610 coincidió al
  centavo).
- **Presentar = liquidar**: la planilla pasa a `fisca_liquidacion` con origen **«lsd»** (detalle «lsd» / «sin_lsd»;
  `activos_con_ddjj` cuenta los activos que están en el archivo), conserva lo que había liquidado AEDA y reemplaza a la
  de DDJJ. **«Liquidar» por DDJJ no la pisa** (`generar` las saltea y las cuenta en «por_lsd»). Manda la última
  presentada del período (la anterior queda «reemplazada»): si el mes tuvo varias liquidaciones se sube la última,
  que trae las bases acumuladas en el registro 04. Sin presentar queda un borrador por CUIT.
- **Control contra la DDJJ de OSEDA** (ficha interna, `control_ddjj`, en vivo de Railway): la remuneración de cada
  afiliado contra la Rem. 5 de su DDJJ de OSEDA de ESE CUIT; marca diferencias de $ 1 o más. El archivo es un texto y se
  puede editar antes de subirlo; los que tienen otra obra social no se pueden controlar así.
- **Anular** (ficha interna, con motivo): la liquidación vuelve a la DDJJ de OSEDA (`generar(..., solo_cuit=)`, hace
  falta Railway). La presentación reemplazada antes no vuelve sola: se sube de nuevo.
- **Excel**: `exportar.xlsx(..., encabezado=[…])` con el formato de la planilla de aportes del art. 38 (CUIT, período y
  empresa en la fila 3; renglones desde la 5), el que lee Importar Cuotas, más lo retenido y una observación.
- **Carga a mano, sin el archivo** (pedido del 15/11/2026; `sql/fisca_novedades_empresa_20261115.sql`):
  `/empresas/<token>/manual?periodo=` muestra la nómina del período (activos del empleador, la regla de siempre) y las
  altas pendientes que cuentan, con la remuneración a cargar (`armar_planilla_manual`, fuente **«manual»**; vacío =
  cero; las altas, **«alta»**). Se guarda como borrador (`fisca_lsd_presentacion.carga = 'manual'`, sin archivo,
  `archivo_nombre` = «Carga manual»; las remuneraciones en `fisca_lsd_manual`) y se revisa, corrige y presenta igual
  que el archivo (`plan_actual` elige). Origen de la liquidación: «lsd», que ahora se lee «Presentada por la
  empresa». El control contra la DDJJ de OSEDA es el mismo. Volver a cargar el mes trae lo último cargado.
- **Nómina, altas y bajas de la empresa** (`fisca_novedades.py`, pedido del 15/11/2026): en su enlace la empresa ve
  su nómina (titulares con relación laboral vigente hoy con el CUIT) e informa el **alta** de un CUIL (fecha de alta,
  ficha de afiliación opcional en PDF o imagen, `SIND_ADJUNTOS/novedades_empresa/`; si no está en el padrón, con
  apellido y nombre) o la **baja** de uno de su nómina (fecha). Quedan **pendientes** (`fisca_novedad_empresa`;
  decidido el 15/11/2026): el sindicato las aprueba o rechaza (con motivo, que la empresa ve) en Presentaciones LSD
  —bloque de arriba— o en la solapa Cuota sindical del empleador. La empresa puede retirar una pendiente. **La cuota
  del mes ya toma el alta pendiente** desde su fecha (archivo o carga a mano, fuente «alta», aunque no esté en el
  padrón); la baja pendiente no cambia nada hasta aprobarse. **Aprobar un alta**: si el CUIL no está en el padrón se
  crea el titular (documento y sexo del CUIL, fecha de alta = la informada, empleador); un familiar con ese CUIL no se
  aprueba; uno dado de baja no se reactiva solo (se avisa); se abre la relación laboral (si no estaba) y la ficha pasa
  a la documentación del afiliado (tipo «Ficha de afiliación»). **Aprobar una baja**: cierra la relación con esa fecha
  (estado inactiva si ya pasó); la afiliación no se toca. Todo con su renglón en `p_afiliados_movimientos` y el
  empleador de la ficha sincronizado (`afiliados._sincronizar_empleador`). Probado de punta a punta contra una base
  MariaDB armada con estas tablas.
- **Instructivo y pago** (pedido del 15/11/2026: «en el enlace enviar siempre el pdf del instructivo»; datos en
  `sql/institucion_cuota_pago_20261115.sql`): todas las páginas del enlace tienen el botón **Instructivo** en la
  barra (`/empresas/<token>/instructivo.pdf`, se abre en el navegador, a nombre de la empresa), y la de la empresa
  —y la planilla ya presentada— el bloque **«Pago de la cuota y consultas»** (`templates/portal/_pago.html`): la
  cuenta (titular, CUIT, banco, número, CBU y alias, con «Copiar»), las indicaciones para el pago y el contacto; el
  pie repite el contacto. Todo sale de `institucion.pago_cuota()` (global `pago_cuota_portal()` en las plantillas).
  El PDF lo arma `instructivo_empresa.py` en cada pedido con reportlab y el membrete de `pagos_pdf._Doc`: el texto es
  `docs/instructivo_empresa.md` (el mismo del documento «Instructivo para el empleador»), con `{sigla}`,
  `{alicuota}`, `[[pago]]` y `[[contacto]]` completados con Datos del Sindicato; sin cuenta elegida dice que pidan
  los datos al sindicato, nunca «pendiente». El mail del enlace (`mailto`) trae la dirección del instructivo: un
  mailto no puede adjuntar. Adentro, `/fiscalizacion/lsd/instructivo.pdf` (botón en Presentaciones LSD, en la
  solapa Cuota sindical del empleador con `?id_empresa=` y en Datos del Sindicato) para mirarlo o adjuntarlo a mano.
- **Pendiente**: el envío del mail desde el sistema (hoy abre el cliente de correo, por eso el instructivo va como
  dirección y no adjunto) y avisarle a la empresa los meses que no presentó.

## Cuenta corriente de empleadores

`cc_empleadores.py` (`/empleadores/cc`, menú 12 «Cuenta Corriente» en Empleadores, Administrador, Supervisor y
Operador; pedido del 14/11/2026). Por CUIT y período: **Debe** = la `fisca_liquidacion` vigente (DDJJ, LSD, nómina o
AEDA); **Haber** = los cobros: renglones de órdenes de ingreso no anuladas con ese `ingreso_ordenes_detalle.cuit` y
clase `cuota_sindical` o motivo CUOTA SINDICAL / INGRESOS POR FISCALIZACION (los recibos y los AEDA-RC / AEDA-OI).
Saldo = Debe − Haber, positivo = debe (rojo), negativo = pagó de más (verde).

- **Qué cobro cancela qué cuota lo dicen las aplicaciones** (ver abajo): saldo del período = liquidado − aplicado;
  lo cobrado sin aplicar es saldo a favor del empleador. «Vencido» = saldo de los períodos con el vencimiento pasado.
  Con un rango de períodos la bandeja cuenta lo liquidado de esos períodos y lo aplicado a ellos.
- **Estado de cuenta** (`/empleadores/cc/<cuit>`): un renglón por período liquidado con lo aplicado, saldo, acumulado
  (lo anterior al «desde» es el saldo anterior), días de mora y lo que había liquidado AEDA; debajo, los cobros con lo
  aplicado, lo sin aplicar y a qué períodos, con enlace al recibo o a la orden de ingreso. Botón «Cuenta corriente» en
  la ficha del empleador.
- **La cuota de un período** (`/empleadores/cc/<cuit>/<periodo>`, `cc_periodo.html`, pedido del 14/11/2026): el «ver»
  del estado de cuenta abre en la misma pestaña (no la ficha de Liquidación en otra) la liquidación con lo aplicado y
  el saldo, los cobros aplicados, los cobros de ese período sin aplicar y los afiliados; «Estado de cuenta» vuelve con
  los mismos filtros. Las pantallas de la cuenta corriente no abren pestañas nuevas.
- Al 14/11/2026, desde 202401 y antes de las aplicaciones: 456 CUIT, liquidado $ 1.763,7 M, cobrado $ 2.269,8 M.
- **Pendiente**: intereses por mora, PDF del estado de cuenta.

## Aplicación de cobros a las cuotas

`fisca_aplicaciones.py` (datos) + las pantallas de `cc_empleadores.py` (`/empleadores/cc/aplicaciones`, menú 13
«Aplicación de Cobros», Administrador y Supervisor; `sql/fisca_aplicaciones_20261114.sql`; pedido del 14/11/2026).
`fisca_aplicacion`: qué importe de un cobro (`id_detalle`, un renglón de `ingreso_ordenes_detalle`) cancela qué
liquidación (`id_liquidacion`); uno por par (`uq_fisca_aplic`, aplicar otra vez el mismo par acumula). Origen
`periodo` (automática, a su período), `deuda_vieja`, `recibo` (al emitirlo) o `manual`.

- **Solo cuentan** las aplicaciones de órdenes no anuladas a liquidaciones vigentes del mismo CUIT
  (`sql_aplicado_cobro`, `sql_aplicado_liq`). La liquidación se reliquida en la misma fila (`generar` hace UPDATE),
  así que lo aplicado sigue a su cuota.
- **Aplicar** (pantalla, de a uno): una cuota con saldo + un cobro sin aplicar, hasta el menor de los dos; se revalida
  en el servidor con las dos filas bloqueadas. **La pantalla es la de Aplicación de Comprobantes de proveedores de
  gestion_adm** (pedido del 15/11/2026, «mucho más clara»): cuotas y cobros en dos columnas lado a lado
  (`.columnas-2 > .col-comp`, en la guía «Aplicación»), un clic en cada una y debajo lo elegido (`.campo-valor`) con el
  importe. Elegido uno, del otro lado se marcan los del mismo período o el mismo importe al centavo (los cobros de AEDA
  sin período suelen ser la cuota justa de un mes): ayuda, no elige solo. **Desaplicar**: entera o en parte, motivo obligatorio, el rastro en
  `fisca_aplicacion_baja`.
- **Aplicación automática** (`aplicar_automatico`; botón por empleador o de todos, `aplicar_cobros.py` por consola):
  1) saca lo aplicado a órdenes o liquidaciones anuladas y recorta lo automático de una cuota que se reliquidó por
  menos (lo más nuevo primero; lo manual no se toca, se avisa «aplicado de más»); 2) cada cobro a su propio período,
  hasta el saldo; 3) con «deuda vieja», lo que sobra a la deuda más vieja del CUIT, de los cobros más viejos a los más
  nuevos y solo a períodos ya empezados al cobrar; un cobro de un período todavía sin liquidar espera su liquidación.
- **La primera vez**: después del script SQL, `python aplicar_cobros.py --aplicar` (o el botón). Hasta entonces ningún
  cobro cancela ninguna cuota y la cuenta corriente muestra todo impago.
- **Quién aplica solo**: la emisión de recibos (cada renglón a la cuota de su período, origen `recibo`) e
  `importar_aeda_fondos.py` (los cobros nuevos, y saca lo de los anulados). Desde el 14/11/2026 ese importador graba
  también el CUIT en el renglón (antes iba solo en la descripción; el script SQL completa los que faltaban).
- `fisca_recibos.saldos_de` (lo que sugiere `distribuir`) usa lo aplicado, no lo cobrado por período.

## Emisión de recibos de cuota sindical

`fisca_recibos.py` (`sql/fisca_recibos_20261112.sql`, menú 8 «Emisión de Recibos» en Fiscalización de Cuotas,
Administrador y Supervisor; test: `python tests/test_fisca_recibos.py`, sin base). Pedido del 12/11/2026: el recibo
de cuota sindical sale de la acreditación del extracto bancario; se elige la cuenta del banco y cada acreditación se
relaciona con su empleador por el CUIT. Para probar sin bajar los archivos del banco: `importar_aeda_extractos.py`
(lo que AEDA ya cargó en `adm_bna24`, desde el corte de la conciliación).

- **El empleador** (`resolver_empleador`): el mismo CUIT del banco si está en Empleadores; si no, un CUIT
  relacionado (`fisca_cuit_relacionado`: el estudio, el dueño, otra empresa del grupo; las 15 de AEDA
  `afi_empresas_rel` vinieron con el script). **Nada más** (pedido del 15/11/2026): un afiliado no se relaciona con
  su empleador; su transferencia es un pago por otro concepto. Un pagador relacionado con varios empleadores: se
  elige al emitir.
- **El recibo al afiliado** (`recibos_afiliado.py`, `sql/recibos_afiliados_20261115.sql`; pedido y decisiones del
  15/11/2026). Las transferencias de importe fijo de los afiliados son la **cuota social YMCA** ($ 25.000 por mes de
  abril a agosto de 2026, $ 30.000 desde septiembre; el doble, dos meses). Relevado en AEDA: no van a `fis_cobros`
  (cuota sindical, concepto 146) sino a órdenes de ingreso `adm_ordIngre` con el concepto **148 YMCA**, una por
  cuenta y por mes («CUOTA SOCIAL … SEGÚN DETALLE ADJUNTO»); la de la Recaudadora de octubre ($ 1.105.000) es
  exactamente la suma de esas transferencias. Vinieron con el motivo de ingreso YMCA. Acá un CUIL del padrón que no
  es pagador relacionado lleva un **recibo al afiliado**: orden de ingreso de clase `afiliado` con
  `cuil_afiliado`, talonario propio **X 0003** (Recibos Afiliados), un renglón por **mes desde el de la
  acreditación** con el motivo de Datos del Sindicato (YMCA) y la descripción «<concepto> AAAA-MM · NOMBRE (CUIL …)»
  (de ahí sale el concepto del recibo, `concepto_de`), sin CUIT de empleador (no toca la cuenta corriente). N cuotas
  justas (`recibo_afiliado_cuota`) pagan N meses y salen **en lote**; las demás, de a uno (un renglón por todo,
  editable). Libro de fondos y conciliación en el acto, como el de cuota sindical. Lo que **AEDA ya registró** (su
  orden YMCA del mismo mes y cuenta con fecha igual o posterior, `cubierta`) figura «Ya tiene recibo» y no se emite.
  De a uno se puede elegir emitirlo como cuota sindical de un empleador (`?para=empleador`). Sin el script, la
  transferencia queda «Otro ingreso». **Ojo**: mientras AEDA siga cargando su orden YMCA del mes, si acá se emiten
  recibos de ese mes y después el importador trae la orden agrupada, el ingreso queda dos veces: hay que decidir
  desde qué mes se deja de importar YMCA de AEDA. Al emitir con otro empleador se puede «Recordar» la
  relación; también se cargan y se dan de baja abajo en la pantalla.
- **El recibo** = orden de ingreso clase `cuota_sindical`, origen `extracto`, fecha de la acreditación, a la cuenta
  del extracto; un renglón por período (motivo CUOTA SINDICAL) con `ingreso_ordenes_detalle.cuit` (columna nueva,
  completada desde la descripción en lo ya cargado) e `id_extracto_origen`. La descripción repite el formato de AEDA
  («CUOTA SINDICAL 2026-10 · RAZÓN (CUIT …)»). Número AAMM-######## de las órdenes de ingreso. PDF con el membrete
  de `pagos_pdf._Doc` y el importe en letras (`en_letras`). Se anula en Tesorería → Anulaciones; anulado, la
  acreditación queda otra vez sin recibo.
- **Se concilia solo** si la cuenta tiene una conciliación abierta que incluye la fecha (como lo que genera la
  conciliación). Si no, la conciliación lo sugiere primero de todo: regla «recibo» (el recibo emitido desde ese
  renglón, por `id_extracto_origen`).
- **Períodos** (`distribuir`): el mes anterior a la acreditación; si el importe es exactamente el saldo de un
  período, ese; si no, el mes hasta su saldo, lo que sobra a la deuda más vieja y el resto al mes; si el mes no está
  liquidado, entero ahí («pago sin liquidar»). Saldo = `fisca_liquidacion` vigente − lo cobrado por CUIT y período.
  Se cambia al emitir de a uno.
- **¿Ya tiene recibo?** (`emparejar`, mientras AEDA siga cobrando): emitido desde el renglón; el «comprobante N»
  de los AEDA-RC = la referencia del banco, con el importe; CUIT (banco o empleador) + importe a 15 días; y como «¿ya
  tiene?» (se puede emitir igual) lo único con esa fecha e importe de los dos lados (así caen los AEDA-OI de
  fiscalización). Con los 56 créditos de la recaudadora del 02 al 05/11/2026: 42 ya tenían su AEDA-RC (los 42 que
  AEDA cobró), 3 «¿ya tiene?» (AEDA-OI).
- **Quién pagó** (pedido del 18/11/2026, `sql/recibos_pagadores_20261118.sql`, se corre a mano): en la grilla, lo «Sin
  identificar» tiene **Asociar**: si el banco no trajo el CUIT (TRANSF.INT.DIST.TITULAR sin CUIT: AEDA tampoco lo
  tiene), se carga en el renglón (`c_extractos_bancarios.cuit_manual` = 1, usuario y fecha; la grilla lo marca «a
  mano»; el que trajo el banco no se pisa); y si el que pagó no es la misma empresa o el mismo afiliado, se lo
  relaciona: con una empresa (`fisca_cuit_relacionado`, como siempre) o con un afiliado (**`fisca_cuit_afiliado`**,
  pagador → CUIL; el cónyuge, la cuenta de otro). **Dos asociaciones, una por concepto** (18/11/2026): la de la
  empresa es de la CUOTA SINDICAL y la del afiliado de la CUOTA SOCIAL; el mismo CUIT puede tener las dos y el
  importe decide (`resolver_empleador(..., social=)`: lo redondo a la medida de la cuota va al afiliado antes que a
  las relaciones con un empleador). Queda a criterio del operador: Asociar está en todo lo que no es el mismo CUIT
  del empleador, en Emisión de Recibos y en Beneficios › Recibos de Adheridos (`templates/fisca/_asociar.html`, el
  diálogo y su JS, vuelve con `volver`); en Beneficios, además, `ui.accion('cuota_sindical')` emite la acreditación
  como cuota sindical de una empresa (`fisca_rec.emitir_uno?para=empleador`).
  `resolver_empleador(..., pagadores)` devuelve `como = afiliado` con `cuil` = el del afiliado (no el del banco), y
  Beneficios, el lote y `recibos_afiliado.transferencias_sin_recibo` usan ese CUIL. Sin el script la pantalla
  funciona igual, sin poder cargar el CUIT ni asociar a un afiliado.
- **La transferencia de un afiliado que no es la cuota social** (pedido del 18/11/2026, `por_su_empleador`): la
  cuota social es redonda a la medida de las cuotas del convenio (`recibos_afiliado.es_cuota_social`: múltiplo del
  divisor común de las cuotas vigentes hasta ese mes —con 25.000 y 30.000, 5.000: 55.000 es un mes de cada precio—,
  hasta 12 cuotas). Lo que un afiliado transfiere con centavos o no redondo es la **cuota sindical del empleador de
  su ficha** (así lo registraba AEDA en `fis_cobros`): se sugiere en Emisión de Recibos con ese empleador (como
  `por_afiliado`, «Lo pagó el afiliado»), de a uno y sin «Recordar», y no aparece en Beneficios (ni en «Transfirieron
  y no están» ni en la solapa de cuota social de la ficha). Sin empleador en Empleadores, sigue como afiliado.
- **Importe a distribuir** (pedido del 18/11/2026, solo en la pantalla de emitir de a uno): en «Lo que debe» se
  escribe el importe (por defecto el de la acreditación) y se tildan los períodos con saldo; cada tilde aplica el
  saldo del período, o lo que falta del importe, en el orden en que se tildan, y arma los «Períodos que se pagan»
  (JS `distribuir()` en `fisca/recibo_emitir.html`; el servidor valida igual que siempre que sumen la acreditación).
- **Pago sin empleador: cuotas impagas por importe** (pedido del 18/11/2026, `candidatos_por_importe`): al emitir
  de a uno una acreditación sin CUIT o sin identificar, la pantalla lista los empleadores con cuotas impagas de los
  últimos `PERIODOS_ATRAS` (3) períodos anteriores a la acreditación que suman justo el importe, al centavo: una sola
  o varias seguidas (`coincidencias`). «Elegir» lo usa como empleador; no elige solo. Ej.: 85.403,72 del 03/11/2026
  sin CUIT → ALBORNOZ JULIO RAUL, 2026-09 o 2026-10.
- **Cuota social sin pagador** (pedido del 18/11/2026, `cuotas_sociales`): una acreditación sin pagador identificado
  cuyo importe es de la cuota social (la misma regla, `es_cuota_social`) no se sugiere como cuota sindical: queda «Otro ingreso» con la nota (se puede
  emitir igual de a uno).
- **Lote**: solo lo «sin recibo» con empleador seguro (mismo CUIT o relacionado), con los períodos que muestra la
  grilla; el servidor lo vuelve a calcular y cada recibo va en su transacción (hasta 500).
- **Pendiente**: intereses por mora; mandar el recibo por mail.

## Recibos: talonarios y fiscalización

`recibos_talonario.py` + `fisca_recibo_acta.py` (`sql/fisca_recibos_talonarios_20261114.sql`, pedido del 14/11/2026;
test: `python tests/test_fisca_recibo_acta.py`, sin base):
los recibos se numeran por talonario, uno para la cuota sindical y otro para la fiscalización, y los de fiscalización
se emiten a un acta, como en OSEDA.

- **El recibo sigue siendo la orden de ingreso** (libro, conciliación, cuenta corriente) y ahora lleva `id_talonario` +
  `nro_recibo` (únicos juntos). Se muestra «X 0001-00000123»; el AAMM-######## queda como número de la orden de
  ingreso. Clases `cuota_sindical` y `fiscalizacion` (esta última, nueva en el ENUM).
- **Talonarios** (clasificación «Recibos», tipo Recibo): **X 0001 Recibos Cuota Sindical** y **X 0002 Recibos
  Fiscalización**, los que se eligen en Datos del Sindicato (`s_institucion.talonario_recibo_cuota/_fisca`), y **X 0091
  / X 0092 (AEDA)**, deshabilitados, con los cobros de AEDA y su número de cobro (`fis_cobros.cobro_id`): decidido el
  14/11/2026, como los migrados de OSEDA, para que lo que se siga importando mientras AEDA cobre no se mezcle con lo
  emitido acá. Están en `s_configuracion` (`talonario_recibos_aeda_*`). El script pasó los 9.874 AEDA-RC de cuota y los
  318 de fiscalización (que eran clase «varios») a su clase y talonario; `importar_aeda_fondos.py` numera los nuevos.
  Los AEDA-OI (órdenes de ingreso de AEDA, sin empleador) no son recibos y siguen sin talonario.
- **Numerar** (`reservar`): el talonario bloqueado (FOR UPDATE), el siguiente al mayor entre `ultimo_emitido` y lo
  usado, dentro de la transacción del recibo. Deshabilitado o agotado: no se emite. Anular no devuelve el número.
- **Recibo de fiscalización** (`fisca_recibo_acta.emitir`): al acta y a las cuotas de su acuerdo (vigente o
  judicializado, como OSEDA; uno anulado o cancelado no se cobra). Desde **Emisión de Recibos** (la acreditación de un
  empleador con acuerdo ofrece «Fiscalización · AP-…»: fecha, cuenta e importe del banco, y se concilia solo) o con
  **«Cobrar»** en el acuerdo (cuenta de banco o caja y fecha; un cheque, por Tesorería). Las acreditaciones de un
  empleador con acuerdo no van en el lote como cuota. Qué cuota paga: `fisca_acuerdo_imputacion` (no pasa el saldo de
  la cuota; lo pagado es lo de recibos no anulados).
- **Capital e interés** (`partir`): cada recibo se parte en la proporción entre el capital que falta (el saldo de hoy de
  la cuota sindical de los períodos del acta) y lo que falta del acuerdo; el que lo termina se lleva todo el capital
  que queda. El capital va en un renglón por período (INGRESOS POR FISCALIZACION, con período y CUIT), del más viejo al
  más nuevo y hasta su saldo, y se aplica a la cuota sindical (la cuenta corriente baja); el resto, un renglón
  INTERESES POR FISCALIZACION (motivo nuevo, con la cuenta contable de fiscalización: **a revisar con el contador**),
  que no es cobro de cuota. Proporcional y no «primero los intereses» (art. 903 CCyC): decidido así para que la cuenta
  corriente baje con cada cuota; a revisar.
- **El acuerdo**: sin saldo pasa solo a «cancelado» (`MOTIVO_PAGADO`); anular un recibo en Tesorería → Anulaciones lo
  vuelve a «vigente» si lo había cancelado el pago. Con recibos no se modifica el cronograma.
- **Talonarios ABM**: un talonario con recibos cuenta como usado (no cambia punto de venta, letra ni desde).
- **Pendiente**: cobrar con cheques de terceros desde el acuerdo, el envío por mail.

## Correo saliente

`mailer.py`, `correo.py`, `secretos.py` (pedido del 17/11/2026: «configurar correo saliente como en oseda»): la
pantalla Correo Saliente de gestion_adm (`mail_routes.py`) con el sistema de estilos de acá, en Administración del
Sistema (`/admin/correo`, menú 211, solo Administrador). Las tablas `mail_*` vinieron con la base;
`sql/beneficios_correo_20261117.sql` les agrega el origen del envío (`mail_envios.origen_tipo/_id`) y la cuenta propia
del remitente, y deja la fila de `mail_config` **apagada**: no sale nada hasta activarla y probarla.

- La contraseña se guarda cifrada con Fernet (`SIND_FERNET_KEY`) y nunca vuelve a la pantalla. El IIS local y Railway
  usan la misma base: la clave tiene que ser la misma en los dos.
- `mailer.enviar()` es el de gestion_adm (avisos de `mail_tipos`, todavía no hay ninguno acá); `mailer.entregar()` es
  propio: manda un mensaje ya armado (las campañas, con HTML y el flyer) con la misma configuración, el mismo freno de
  24 horas (`limite_diario`) y el mismo registro en `mail_envios`.
- `p_afiliados` no tiene columna de correo: el del afiliado sale de sus contactos (`s_contactos`, vinieron de AEDA).
  Test: `python tests/test_ben_campanias.py` (incluye `entregar` sin servidor).
- **Errores del servidor** (24/11/2026: la campaña 1 daba «Connection unexpectedly closed» —era el usuario de la
  cuenta mal escrito, «infomes@», que había vuelto con el restore de la base: Gmail corta sin responder— y cada
  reanudación marcaba a diez afiliados como error, que no se vuelven a intentar): `_entregar` dice en qué paso falló (conectar, STARTTLS,
  iniciar sesión, presentar el remitente, entregar) y qué suele ser (`PASOS`, `SUGERENCIAS`, `motivo_conexion`). Lo
  que no es del destinatario —corte, timeout, red, un 421, el remitente o el mensaje rechazados (el límite de Gmail,
  «550 5.4.5»)— levanta **`MailConexionError`** (es MailError): queda en `mail_envios` y la campaña se pausa con ese
  motivo, con el afiliado **pendiente**. Usuario o contraseña siguen como antes; un rechazo de la dirección (550 en
  RCPT) sigue siendo del destinatario y cuenta para los 10 seguidos.
- **Probar la conexión** (`POST /admin/correo/diagnosticar`, `mailer.diagnosticar`): conecta, STARTTLS, inicia sesión,
  `MAIL FROM` + `RSET` y se va, **sin mandar nada** (no necesita el envío activo ni cuenta para el límite). Prueba la
  salida del servidor donde está abierta la pantalla: Railway o el IIS local. La respuesta al EHLO de Gmail trae la IP
  de salida. **Railway no deja salir SMTP (25, 465, 587, 2525) salvo en el plan Pro.**

## Beneficios: Convenio YMCA

`ben_convenio.py` (`/beneficios/ymca/…`, menú 120 «Beneficios» › 121 «Convenio YMCA» › 122-126, Administrador y
Supervisor; `sql/beneficios_correo_20261117.sql`; test: `python tests/test_ben_convenio.py`, sin base). Pedido y
decisiones del 17/11/2026: el ingreso de los pagos de la YMCA va aparte; hay una nómina de afiliados que pagan por mes y
una factura mensual del proveedor (el gimnasio con convenio, proveedor 23). La diferencia entre lo que factura y lo que
pagan los afiliados la cubre el sindicato.

- **Tablas**: `ben_convenio` (proveedor, motivo de los recibos, `cc_desde`), `ben_convenio_precio` (por vigencia:
  `precio_proveedor` por adherido y `cuota_afiliado`, fija para todos; 25.000 desde 2026-04 y 30.000 desde 2026-09; el
  precio del gimnasio **falta cargarlo**), `ben_adherido` (afiliado titular o familiar, mes desde y hasta).
- **La nómina se carga en el sistema** (decidido). Baja = último mes que paga; eliminar solo una carga que no generó
  cuotas. La solapa «Transfirieron y no están» (extracto de los últimos 3 meses, CUIL del padrón que no es empleador,
  grupo sin adheridos) sirve para armarla.
  **Carga inicial (17/11/2026)**: 120 adheridos de las transferencias de AEDA (`adm_bna24`, desde 2025-09: CUIL del
  padrón, importe múltiplo de $ 5.000 hasta $ 360.000). Desde = primer mes que transfirió; hasta = último, salvo que
  haya transferido en 2026-10 o 2026-11 (sigue, vacío). Cada uno lo dice en observaciones. Son los titulares que
  transfieren: los familiares que cubre su pago se agregan a mano. La grilla filtra por período (adheridos en algún
  mes entre desde y hasta).
- **La cuota es del grupo familiar** (`cuil_titular`): cada mes debe cuota × adheridos del grupo; le cuentan los
  recibos de cualquiera del grupo. La cuenta empieza en `cc_desde` (202611): antes AEDA registraba lo cobrado en una
  orden por mes sin detalle.
- **Recibos aparte**: Emisión de Recibos (cuota sindical) ya no muestra las transferencias de afiliados (avisa cuántas
  y lleva a Beneficios) ni las emite en lote; su «emitir» de una de afiliado redirige a `ben_conv.emitir_uno`. El
  recibo es el de `recibos_afiliado.py` (talonario X 0003) con el motivo del convenio; los meses sugeridos son las
  cuotas JUSTAS del grupo; en lote solo grupos en la nómina con cuotas justas. La plantilla de emisión es
  `fisca/recibo_emitir.html` en modo afiliado (`beneficios=True`).
- **Control mensual**: por mes, adheridos de la nómina × precio contra lo facturado (`f_comprobantes_arca` del proveedor
  por `periodo`, las notas de crédito restan), adheridos según la factura, lo cobrado (todo el motivo YMCA, también las
  órdenes agrupadas de AEDA por el mes de su fecha) y lo que cubre el sindicato (facturado − cobrado).

## Beneficios: Campañas

`ben_campanias.py` (`/beneficios/campanias`, menú 127; pedido del 17/11/2026: «cargar flyers de campañas que se puedan
enviar por correo a los afiliados»). `ben_campania` (flyer en `SIND_ADJUNTOS/campanias/`, imagen o PDF hasta 5 MB,
asunto, texto con `{nombre}`, destino: titulares activos, titulares y familiares, adheridos de un convenio),
`ben_campania_envio` (un renglón por dirección: pendiente, ok, error, baja), `ben_baja_correo` (no recibir más).

- Una dirección por afiliado (la principal o la primera de sus contactos), sin repetir, sin las dadas de baja. Un mail
  por destinatario; la imagen va dentro del HTML (cid), el PDF adjunto; al pie y en `List-Unsubscribe` el enlace
  firmado de baja (`/beneficios/baja/<token>`, pública: pregunta y registra con un botón).
- **Enviar** arma la lista en la base y la manda un hilo, de a uno con 1 s de pausa. Un error de cuenta o el límite de
  24 horas la deja **pausada** con la nota; se **reanuda** desde donde quedó (la lista está en la base: un reinicio no
  pierde nada, la ficha ofrece «Seguir enviando»). 10 errores seguidos la pausan. La ficha sigue el avance (JSON).
- Primero «Enviar prueba» a una dirección (asunto con «[PRUEBA]», no toca la lista).
- **Editar** (`puede_editar`): un borrador, entero; una **pausada** (pedido del 24/11/2026), solo título, asunto,
  texto y flyer —a quién va se ve sin poder cambiarlo, la lista ya está armada—. Los pendientes reciben la versión
  nueva. No mientras el hilo está andando.
- **Flyer perdido** (`flyer_perdido`, 24/11/2026: el archivo de la campaña 1 desapareció del servidor y salieron 15
  mails sin la imagen): con `flyer_archivo` cargado y el archivo ausente (ni disco ni bucket) no se prueba, no se
  envía ni se reanuda, el hilo se pausa con el aviso, y la ficha y el formulario piden cargarlo de nuevo.
- **Eliminar** (pedido del 23/11/2026; `puede_eliminar`): en cualquier estado, desde la lista (tacho) o la ficha,
  con su flyer y su lista (`ben_campania_envio` cae por la FK). No mientras se envía (estado «enviando» o el hilo
  andando) ni con padrón de entrega. Lo que salió queda en `mail_envios` (sin FK a la campaña).
- **Lista según los filtros del padrón** (pedido del 17/11/2026, `sql/beneficios_campanias_padron_20261117.sql`):
  destino «padron» con los filtros de la Consulta del Padrón guardados en `ben_campania.filtro` (JSON: q, estado,
  tipo, sexo, edad_desde, edad_hasta, atributo; `filtro_de` los valida con `afiliados._filtros_listado`). La lista
  se arma al enviar con `afiliados._where_listado`: la misma consulta que la grilla del padrón. El formulario muestra
  a cuántas direcciones llega mientras se elige (`/beneficios/campanias/contar`, JSON); la Consulta del Padrón tiene
  «Campaña con estos filtros» (`/beneficios/campanias/nueva?destino=padron&…`); la ficha baja la lista en Excel
  (`/<id>/lista.xlsx`: a quién le llega o, enviada, cómo salió cada una).

## Elecciones

`elecciones.py` (`/elecciones`, `sql/elecciones_20261118.sql`, menú 130 «Elecciones» › 131 «Elecciones y Padrón»
(Administrador y Supervisor) y 132 «Mesa de Votación» (también Operador); test: `python tests/test_elecciones.py`,
sin base). Pedido del 18/11/2026: «configurar fecha de elecciones con motivo de elección y el día de la votación ir
marcando el afiliado si vino a votar».

- **La elección** (`el_eleccion`): motivo, día de la votación, horario y lugar (opcionales), **corte del padrón**
  (vacío = el día de la votación) y **antigüedad mínima** en meses. Estados: vigente, cerrada (ya no se marca ni se
  quita nada; el Administrador la reabre), anulada (con motivo).
- **El padrón electoral** (`el_padron`) es una **foto** del padrón al generarlo (se genera solo al crear la elección):
  titulares (`cod_parentesco = 0`, «afiliado = titular» como en las métricas) con alta hasta el corte, sin baja (sin
  fecha y activo, o con la baja posterior al corte) y, si se pide antigüedad, alta hasta el corte − N meses (sin fecha
  de alta entran solo si no se pide). Lleva orden alfabético, documento, CUIL, empleador y alta copiados. Se vuelve a
  generar mientras nadie votó (pierde lo hecho a mano); cambiar el corte o la antigüedad lo regenera. A mano: agregar
  un titular (CUIL o documento, con motivo; va al final del orden) y quitar a quien no votó (con motivo).
- **La mesa**: busca por documento, CUIL, orden o apellido (`partir_busqueda`) y registra el voto con hora y usuario.
  Varias mesas a la vez: el UPDATE marca solo `voto = 0`, así la segunda marca avisa quién y a qué hora; las cifras
  y los últimos votos se refrescan cada 15 s (`api_estado`). Quitar un voto pide motivo. Si el documento no está en
  el padrón electoral, dice por qué (`por_que_no_esta`: familiar, de baja al corte, alta posterior, sin antigüedad).
- **OSEDA** (pedido del 18/11/2026): la grilla del padrón electoral (y su Excel) dice si cada afiliado tiene OSEDA
  HOY —Sí (titular), Sí, familiar, De baja (con la fecha) o No— por su CUIL en `p_afiliados` de contable
  (`contable_oseda.padron_oseda_por_cuil`, vigente = activo y sin baja o con baja de hoy en adelante), en vivo al
  abrir la ficha: no es parte de la foto. Filtro «Con OSEDA / Sin OSEDA». Sin Railway, «—» y el aviso.
- **Se marca el día de la votación** (`puede_marcar`); otro día solo el Administrador, con el aviso (la carga
  posterior de un acta en papel).
- **Rastro**: `el_padron_mov` (voto, quita_voto, agregado, quitado), con usuario, fecha y motivo; solapa Movimientos.
- **Pendiente**: el padrón para imprimir (PDF por mesa, con lugar para la firma) y repartir el padrón en varias mesas
  (por letra o por empleador).

## Escalas salariales del convenio

`fisca_escala_salarial` (`sql/fisca_escalas_20261114.sql`): básico por antigüedad (0 a 35) y almuerzo diario por
vigencia (desde / hasta AAAAMM; `periodo_hasta` NULL = la vigente). Pantalla `fisca_escalas.py` (menú 9 «Escalas
Salariales» en Fiscalización de Cuotas, `sql/menu_escalas_20261114.sql`, Administrador y Supervisor; test:
`python tests/test_fisca_escalas.py`, sin base). Pedido del 14/11/2026.

- **De AEDA**: `importar_aeda_fisca_escalas.py` (`fis_escalas`, 38 vigencias de 2012-10 a 2023-09, origen «aeda»);
  se ven y no se tocan en la pantalla. AEDA tiene un básico mal cargado: 2022-01, 29 años (96.051,40, menor que el
  de 28).
- **Paritaria 2024-2026**: `sql/fisca_escalas_2025_2026_20261114.sql`, 12 escalas de 2025-01 a 2026-09 pasadas de
  las circulares (origen «manual»). Los meses sin escala propia no tuvieron aumento (confirmado el 14/11/2026).

- **2024** (`sql/fisca_escalas_2024_20261116.sql`, 16/11/2026): 2024-02, 2024-03, 2024-04 y 2024-12 de las circulares,
  y 2024-11 **calculada** (diciembre − 8 % del básico de abril; almuerzo 6.810). Cada una rige solo su mes: los «%»
  de las circulares desde dic-24 son sobre el básico de abril 2024, y de ahí sale que entre mayo y noviembre hubo
  aumentos; marzo 2024 («39 %») sale de una escala con inicial 242.685,68 que rigió entre oct-23 y ene-24. **Siguen
  faltando 2023-10 a 2024-01 y 2024-05 a 2024-10**: en esos huecos no hay escala.
- **Conformado** = básico + almuerzo × 22 días (la «comida» del art. 9 CCT 417/05, como en las circulares).
- **Alta**: rige desde su período hasta el mes anterior a la siguiente (o abierta); la anterior se cierra el mes
  antes si estaba abierta o la pisaba. No se repite un período ni se parte una de AEDA. Corregir o borrar solo lo
  cargado acá; al borrar, la anterior vuelve a cubrir esos meses. Los básicos se pegan de una vez (toma solo
  importes con centavos; «506,404.46» o «506.404,46»; un 37.º es el almuerzo) o se calculan desde otra escala con
  un %.
- **Controles** (avisan; «Grabar igual» los pasa): que el básico no baje al subir la antigüedad y que, contra la
  escala anterior, todas las antigüedades suban en la misma proporción (±0,03 %).

## Nómina del empleador y DDJJ de OSEDA

Solapa «Nómina» de Empleadores (`/empleadores?edit=ID`, solo en edición): las relaciones laborales
(`p_relaciones_laborales`) del empleador, con estado, fecha de alta y de baja, antigüedad en años
cumplidos y la última DDJJ de OSEDA de ese CUIL **para ese CUIT** con su remuneración imponible 5.

- **Activo** = relación `activa` sin egreso o con egreso de hoy en adelante (la regla de «vigente»
  del afiliado). Las importadas de AEDA no traen egreso: si la relación está inactiva sin
  `fecha_fin`, se muestra la fecha de baja del afiliado con un asterisco.
- **Antigüedad**: desde `fecha_inicio` hasta la baja o hasta hoy. Sin fecha de ingreso, «—».
- **DDJJ**: en vivo de `f_ddjj_procesada` en `contable` de Railway (`contable_oseda.py`), filtrada
  por el CUIT del empleador y `codosoc = 106104`. Esa tabla ya tiene una fila por CUIT + CUIL +
  período (la DDJJ vigente). Sin `SIND_CONTABLE_*` o con Railway caído, la nómina se muestra igual
  con un aviso y sin las columnas de DDJJ completas.
- **Listado de empleadores**: columna «Empleados activos» (afiliados con relación vigente, misma regla)
  antes del nombre de fantasía; el listado viene ordenado por ella de mayor a menor. Una columna
  ordenada desde el servidor lleva `data-orden="desc"` en el `<th>` y `base.html` la marca.
- **Períodos**: se muestran `AAAA-MM`, el formato de ARCA en contable/gestion_adm, con el filtro
  `periodo` de `app.py` (`{{ p | periodo }}`). Ordenan bien como texto en las grillas.
- **Cruce de toda la nómina** (`cruce_nomina_ddjj.py`, pedido del 11/11/2026, no escribe nada): cada afiliado
  titular activo con relación vigente se busca en la DDJJ de OSEDA de su empleador en el último período completo
  (el más nuevo con al menos el 80 % de las filas del anterior) y en una ventana de 6. Estados: en la DDJJ, en otro
  período, con otro empleador, no está. «100 %» = todos sus afiliados en su DDJJ del período. Deja el resumen y dos
  planillas (empleadores y afiliados) en `logs/`.
- **Antigüedad por DDJJ** (`antiguedad_ddjj.py`, pedido del 14/11/2026, no escribe nada): para cada titular activo
  con relación vigente, el tramo actual de DDJJ de ESE empleador en `oseda.dbo.afi_redapo` del SQL Server de origen
  (no `f_ddjj_procesada` de contable, que descartó períodos: afi_redapo va desde 199607), cortado por más de 2 meses
  seguidos sin DDJJ, contra `fecha_inicio` del padrón: coincide, DDJJ anterior, DDJJ posterior, sin fecha, sin DDJJ;
  sugiere la más antigua. Al 14/11/2026: 1.573 de 1.907 tienen DDJJ de su empleador. El archivo del LSD no trae la
  fecha de ingreso: solo el registro 05, que es de los trabajadores eventuales.
  Con `--aplicar` la graba en `p_relaciones_laborales.fecha_antiguedad` + `antiguedad_origen` (`padron`, `ddjj`,
  `empresa`), `antiguedad_al_menos`, `antiguedad_nota`, `antiguedad_calculada` (`sql/antiguedad_20261114.sql`);
  `fecha_inicio` no se toca. La Nómina del empleador cuenta la antigüedad desde ahí (sin ella, desde el ingreso; «¹»
  = desde la DDJJ, «≥» = la DDJJ empieza en 1996-07) y la solapa Empleadores del afiliado la muestra. Editar la fecha
  desde en la ficha la borra (manda lo cargado a mano) y el script no la vuelve a calcular; tampoco pisa una de
  origen `empresa`. La fecha real (Simplificación Registral) solo la ve el empleador con su clave: el origen
  `empresa` queda para cuando la informe por el portal (pendiente: hace falta una muestra del export de Mi
  Simplificación).
- **Marca AEDA en OSEDA** (`cruce_atributo_aeda.py`, pedido del 11/11/2026, no escribe nada): los titulares del
  padrón contra `p_afiliados` de contable y su atributo «AEDA — Afiliado al Gremio» (`p_atributos_por_afiliado`, por
  rótulo). Resultado por CUIL: correcto, falta la marca, de baja en OSEDA, familiar en OSEDA, no está en OSEDA, y
  sobra la marca (baja en AEDA, no está en AEDA, puesta a un familiar). La marca se corrige en gestion_adm: deja
  la lista de CUIL sin marca en `logs/`.

## Ayuda (manuales de uso)

Pedido del 15/11/2026: las pantallas de ayuda de todo el sistema, como las de gestion_adm (`ayuda.py`,
`ayuda_render.py`, `templates/ayuda/manual.html`, los `*_ayuda.py`), con el sistema de estilos de acá (sección 18c de
sindicato.css, «Ayuda» en la guía) y sin las demos animadas. Test: `python tests/test_ayuda.py` (levanta app.py, no
usa la base).

- **Un manual por módulo del menú** (`ayuda.MANUALES`, en el orden del índice), más «Uso del sistema» (ingreso, menú y
  permisos, buscador, grillas, botones, formularios). Cada `ayuda_<módulo>.py` es solo datos: `CLAVE`, `MODULO`,
  `INTRO`, `CIRCUITO` y `SECCIONES`, una por pantalla o por tema, con `id` (único en todo el sistema), `grupo`,
  `titulo`, `url` (para «Ir a la pantalla», que sale solo si `db.puede(url)`), `endpoints` (las pantallas que abren
  esa sección), `resumen` y `bloques` (texto, lista, pasos, campos, criterio, aviso; ver el docstring de ayuda.py).
- **El botón Ayuda** es el flotante de abajo a la derecha de base.html (el de gestion_adm, que estaba en la plantilla
  sin registro detrás) y la tecla F1: lleva a la sección de la pantalla actual (`ayuda_pantallas.url_ayuda`, por
  `request.endpoint`) o, si no tiene, al índice. Lo ve cualquiera con sesión; los manuales explican también las
  pantallas que la persona no tiene.
- **Una pantalla nueva lleva su ayuda**: su endpoint en `endpoints` de una sección (nueva o existente).
  `tests/test_ayuda.py` falla con las pantallas GET que no están en ningún manual ni en `ayuda.SIN_AYUDA` (JSON, PDF,
  archivos, el portal de las empresas); también controla ids repetidos, endpoints y direcciones que no existen y que
  cada manual se dibuje. Los manuales se cargan al arrancar (`ayuda.cargar()` en app.py): uno mal armado no deja
  arrancar.
- **Buscar**: el índice busca en el texto de todas las secciones; cada manual, en el suyo (cada palabra tiene que
  estar, sin acentos, como el buscador general).
- **El contenido describe lo que hace el sistema hoy**, en el idioma de quien lo usa (voseo, sin nombres de tablas);
  las pantallas pendientes se nombran como pendientes. Al cambiar una regla de negocio, cambiar también el manual.

## Panel de inicio y accesos directos

`accesos_directos.py` + `templates/inicio.html` (pedido del 15/11/2026: la chincheta del menú lateral estaba en
base.html, copiada de gestion_adm, y llamaba a `/accesos-directos/alternar`, que acá no existía). El de gestion_adm
(`accesos_directos.py`, `templates/menu.html`) con las claves `sind_` y sindicato.css 18d. Test:
`python tests/test_accesos_directos.py`, sin base.

- **La chincheta** de cada pantalla del menú (aparece al pasar el mouse; llena si está fijada) fija o saca la
  pantalla. `s_accesos_directos` vino con la base: usuario, `menu_id` (no el nombre ni la URL: si la pantalla cambia,
  el acceso la sigue) y orden. `inject_menu` lee los fijados en la misma consulta del menú (`accesos_fijados`).
- **El panel de inicio** es `/menu` (Inicio, el logo y el destino del login): las tarjetas por módulo (la rama de
  más arriba, con su ícono), que se ordenan arrastrando con eventos de puntero dentro de su módulo y se sacan con la
  X. **Quien no fijó ninguna va al Panel de Fiscalización**, el inicio de antes: nadie se encuentra con un inicio
  vacío. Desde el panel, un botón lleva al de Fiscalización.
- **El permiso sigue siendo la opción de menú**: solo se fija una pantalla (con URL, activa) de `sind_menu_ids`, y
  el panel vuelve a cruzar con ellas: una pantalla que le sacan a alguien deja de verse sin borrarse.

## Administración del sistema

`admin.py`, las pantallas de «Administración del Sistema» de gestion_adm (`abm_usuarios`, `abm_roles`,
`abm_menu_usuario`, `abm_menu`, `abm_areas`, `abm_area_usuario`) con el sistema de estilos de acá.
Menú 201-205 y 208 (Áreas por Usuario, `sql/menu_admin_20261111.sql`), para el Administrador. Lo que
quedó afuera de gestion_adm: Parámetros (`s_configuracion` está vacía y nada la lee), Guardia de Rutas,
Correo Saliente, Procesos Desatendidos, Talonarios y lo del Asistente.

- **El permiso es la opción de menú** (`db.puede`), también acá: en gestion_adm estas pantallas pedían
  el rol Administrador por nombre. Lo que impide quedarse sin forma de administrar: siempre queda un
  usuario activo con el rol Administrador (nadie se da de baja ni se quita ese rol a sí mismo); el rol
  Administrador no se desactiva ni pierde Usuarios, Roles y Menú; y esas tres opciones
  (`admin.MENU_PROTEGIDO`) no se desactivan, no se eliminan y no cambian de URL.
- **Los roles NO dan opciones de menú** (22/11/2026, pedido: «los roles están mejor definidos en el proyecto
  financiera… que no tenga asociación con las opciones de menú, para eso está Permisos por Usuario»). Lo que
  ve cada persona es SOLO `s_menu_usuario` (`db.roles_y_menu`), que se arma en Permisos por Usuario (con
  «Copiar los permisos de» otro usuario) o en el alta del usuario («Copiar los permisos de», se graba con el
  alta y abre Permisos por Usuario). `s_menu_rol` quedó vacía y sin uso (`sql/roles_sin_menu_20261122.sql`
  copió a cada usuario lo que le daban sus roles). **Un script que agrega una opción de menú la asigna en
  `s_menu_usuario`**, no en `s_menu_rol`. Quien tiene el rol Administrador ve siempre Usuarios, Roles y Menú
  con sus ramas (`db.MENU_ADMIN_SIEMPRE` = `admin.MENU_PROTEGIDO`), tenga tildado lo que tenga.
- **Ramas**: tildar una opción tilda su rama, en pantalla y en el servidor (`_con_ancestros`): el menú
  lateral descarta una opción cuya rama no está permitida.
- **Los permisos de la sesión se vuelven a leer cada minuto** (`app._permisos_al_dia`, desde el 15/11/2026):
  roles y opciones de menú (`sind_menu_ids`) salen de la cookie del login, y antes quedaban fijos hasta salir y
  volver a entrar (las opciones nuevas cargadas por script no aparecían). El de quien hace el cambio se refresca
  en el momento (`_refrescar_sesion`).
- **Roles = nivel de la persona**, como en financiera: se crean, se renombran, se ordenan por prioridad y se
  eliminan si nadie los tiene (con usuarios, se desactivan). El código pregunta solo por **Administrador**
  (`tiene_rol`: anular pagos, reabrir conciliaciones, marcar votos fuera del día), que no se renombra, no se
  desactiva ni se elimina. `db_usuario` no se toca desde la pantalla (necesita `SIND_DB_PASS_<USUARIO>`).
- **Usuarios**: alta con contraseña obligatoria (no hay ingreso con Google), mínimo 8, email en
  minúsculas y único. **Uno que operó no se elimina**: se da de baja. Dónde figura sale de las FK de la
  base (`_referencias` / `_usos`: toda FK a `s_usuarios` que no sea CASCADE), no de una lista a mano como
  `_ACTIVIDAD_USUARIO` de gestion_adm. Los roles inactivos (autogestión) que ya tenga se conservan.
- **Menú**: una opción es rama (sin URL) o pantalla (con URL, sin nada debajo); URL única; hasta 4
  niveles (los que dibuja base.html); no puede ir dentro de sí misma. Con opciones debajo no se elimina
  (la FK borraría la rama entera en cascada). `nivel` se recalcula entero después de cada cambio
  (`_rearmar_niveles`): en gestion_adm mover una rama dejaba mal el nivel de lo de adentro. El ícono se
  dibuja tal cual, así que solo se acepta un SVG sin script, `on…=` ni `javascript:` (hasta 6.000 caracteres).
- **Íconos en colores** (pedido del 11/11/2026, como gestion_adm): `sql/menu_iconos_color_20261111.sql` le pone a
  cada opción, en los cuatro niveles, un ícono de Fluent UI System Color Icons (MIT, el juego de gestion_adm),
  18 × 18. Pintan con degradados por `id`, y `url(#id)` apunta al PRIMER elemento con ese id de la página: si el
  mismo ícono sale dos veces y el primero está en un submenú cerrado, Chrome no lo dibuja. Por eso se dibujan con
  el filtro `svg_unico` de app.py (renombra los id cada vez), en el menú lateral y en el ABM del menú.
  Las opciones que se agregan después quedan sin ícono: `sql/menu_iconos_color_20261114.sql` les puso el suyo a las
  de Fiscalización (LSD, recibos, escalas, actas, acuerdos, fiscalizadores), por URL. Los íconos salen del paquete npm
  `@iconify-json/fluent-color` (`icons.json`, variante `-24`), con los id `SVG…` renombrados a `m<id de menú>SVG…`.
- **Menú lateral**: buscador de opciones arriba (el de gestion_adm: filtra el árbol en el navegador, cada palabra en
  la opción y en sus ramas; flechas, Enter va, Esc limpia; solo busca pantallas, `a.mn-hoja`). Cada nivel con su
  tamaño, peso y color (módulo .88rem 700 negro; hijo .82rem 500 #1c5a8f; nieto .78rem 400 #2c5c96; bisnieto
  .75rem #3d6d9a, 5,45 de contraste), y una rama pesa más que una pantalla de su mismo nivel.
- **Áreas**: hasta 5 niveles; dos con el mismo nombre en el mismo lugar no. Una que se usa
  (expedientes, movimientos, proveedores, nómina: las FK a `s_areas`) no se elimina, se desactiva. Al
  eliminar una sin uso, sus subáreas pasan a depender de su área madre.
- **Áreas por usuario**: área + función (`rol_area`, texto libre). Solo se tildan las activas; lo
  asignado a una inactiva se conserva al guardar.
- **Árbol con casillas**: `templates/admin/_arbol_menu.html` (Roles y Permisos), `.inp-celda` y
  `.menu-icono-muestra` en sindicato.css y en la guía.

## Talonarios

`talonarios.py` (`/admin/talonarios`, menú 209, `sql/menu_talonarios_20261111.sql`), portado de
`gestion_adm/talonarios_routes.py`. Tipo de comprobante (`c_contable_comprobante_tipo`: debe o haber) →
clasificación (`c_talonario_clasificacion`) → talonario (`c_talonario`: punto de venta, letra, rango,
`ultimo_emitido`). Una pantalla, tres solapas.

- **Formularios satélite**: desde el talonario se crea la clasificación, y desde ella el tipo, en un diálogo
  (JSON), sin perder lo tipeado; la nueva queda elegida. Las mismas validaciones que el ABM.
- **Usado** = `ultimo_emitido` dentro del rango, filas en `c_comprobantes_emitidos` o recibos en `ingreso_ordenes`
  (`id_talonario`, ver «Recibos: talonarios y fiscalización»). Uno usado no se elimina
  (se deshabilita) ni cambia punto de venta, letra, número desde o clasificación; el hasta no baja de lo
  emitido. `ultimo_emitido` nunca retrocede; vacío al crear = ninguno (desde − 1).
- **Superposición**: por tipo de comprobante + punto de venta + letra, no por clasificación (en gestion_adm
  dos clasificaciones del mismo tipo podían repetir números).
- Un tipo o una clasificación con algo debajo no se elimina; con comprobantes emitidos no se le cambia el
  lado (tipo) ni el tipo (clasificación): daría vuelta lo ya emitido en las cuentas corrientes.
- **Fuera**: factura electrónica con ARCA (tipo ARCA, ambiente, concepto: las columnas no están en esta base)
  y el editor del modelo de impresión. `codigo_arca_comprobante_tipo` y `template` no se tocan.

## Datos del sindicato

`s_institucion` (`sql/institucion_20261107.sql`), una sola fila: el equivalente de `os_parametros`
de gestion_adm con los campos de un gremio —personería e inscripción gremial, ámbito— en lugar de
RNOS y código de OS. Pantalla: Administración del Sistema → Datos del Sindicato (`/admin/institucion`).

- De ahí sale el membrete de los documentos y la sigla, el nombre y el logo del encabezado
  (`inject_institucion`, un minuto en memoria; guardar lo descarta).
- **Agente de retención**: `ret_iva`, `ret_ganancias` (+ `ret_arca_tasa_ivaid`, la tasa con que se
  netea la orden para la base), `ret_iibb` (+ régimen), `ret_suss`, cada uno con su alícuota por
  defecto, y `nro_resolucion_ret`. Se llaman igual que en `os_parametros`: el motor de retenciones
  de gestion_adm (`retenciones.py`) se trae cambiando el nombre de la tabla.
- **Talonarios de los recibos** (`talonario_recibo_cuota`, `talonario_recibo_fisca`), en el bloque «Cuota sindical»:
  distintos, habilitados y de la clasificación de recibos.
- **Recibos a afiliados** (`sql/recibos_afiliados_20261115.sql`): `talonario_recibo_afiliado` (X 0003, propio),
  `recibo_afiliado_motivo` (YMCA), `recibo_afiliado_concepto` («Cuota social YMCA», lo que dice el recibo) y
  `recibo_afiliado_cuota` (30.000: N cuotas justas pagan N meses y van en lote).
- **Pago de la cuota sindical y consultas** (`sql/institucion_cuota_pago_20261115.sql`): `cuota_cuenta_fondos` (FK a
  `c_cuentas_de_fondos`: se elige una cuenta bancaria habilitada de Tesorería; banco, número, CBU y alias se
  corrigen allá; la ya elegida vale aunque se deshabilite), `cuota_pago_indicaciones` (hasta 500, respeta los
  renglones), `cuota_consultas_email` y `cuota_consultas_telefono` (vacíos: `email` y `telefono` generales). Titular
  y CUIT son los de Identificación. Lo ven las empresas en su enlace y en el instructivo (`institucion.pago_cuota`).
- El logo va a `SIND_ADJUNTOS/institucion/logo.<ext>`: es la carpeta en la que el pool ya escribe.
  Un SVG se ve en pantalla pero reportlab no lo dibuja en los PDF.

## Reintegros

Las mismas pantallas que gestion_adm (`reintegros_routes.py`), con el sistema de estilos de acá. Las
tablas (`c_reintegro_afiliados*`, `pago_ordenes_reintegro_det`, vistas `v_reintegros_afiliados` y
`v_reintegro_saldo`) vinieron de `contable` con la misma estructura. `sql/reintegros_20261107.sql`
agrega `c_concepto_de_gastos.es_reintegro`, los conceptos de AEDA, el titular «APELLIDO NOMBRE» en
la vista y las opciones de menú 81-83.

- **Circuito**: borrador → en_auditoria → aprobada → pago_parcial → con_orden; rechazada y anulada
  cierran. `pagada` es lo pagado fuera de este sistema: el historial de AEDA.
- **Permisos = opciones de menú**, controladas en el servidor con `db.puede`: «Solicitudes de
  Reintegro» (81) carga; «Auditoría de Reintegros» (82) audita, rechaza, anula y corrige una ya
  auditada; «Órdenes de Pago de Reintegros» (83) genera órdenes. La ficha la ve quien tenga
  cualquiera de las tres. En gestion_adm la auditoría se podía postear sin permiso.
- **Corregir una auditada** la devuelve a auditoría con los importes aprobados en blanco: lo
  autorizado se resolvió sobre otros renglones. Lo que cierra la edición es la orden de pago.
- **Órdenes**: una por titular, en `pago_ordenes` clase `reintegro`, en borrador. Un reintegro se
  puede pagar en partes: el saldo es lo aprobado menos lo que está en órdenes no anuladas. Aprobar
  y pagar la orden es del circuito de pagos, que todavía no tiene pantallas acá.
- **Conceptos**: los marcados `es_reintegro` (los de AEDA: subsidios, movilidad, honorarios, gastos
  gremiales). Para ofrecer otro, marcarlo; no hay predeterminado.
- **Subsidio o reintegro**: lo dice el concepto (`c_concepto_de_gastos.clase_reintegro`,
  `sql/reintegros_clase_20261111.sql`, se elige en Conceptos de Gasto). Subsidios: educación inicial,
  nacimiento, casamiento, fallecimiento, ajuares y otros subsidios especiales. Reintegros: movilidad y
  mensajería, gastos gremiales y honorarios (decidido el 11/11/2026). Una solicitud con renglones de las dos
  clases es «Mixta»; sin clase cuenta como reintegro. Columna y filtro «Clase» en Solicitudes, Auditoría y
  Órdenes (`reintegros_datos._clases`).
- **Numeración**: `RA-AAAA-NNNNNN` desde `c_numeradores` (no COUNT(*): borrar un borrador hacía
  repetir el número); las importadas son `AEDA-<reintegro_id>`.
- **Adjuntos**: en `SIND_ADJUNTOS` (por defecto `adjuntos/` del proyecto) con la ruta **relativa**
  guardada en la base. PDF o imagen, hasta 10 MB.
- **Constancia PDF** (reportlab): el membrete —nombre, CUIT, domicilio y logo— sale de «Datos del
  sindicato» (`s_institucion`).
- **Historial de AEDA**: `importar_aeda_reintegros.py`. Cada `afi_reintegros` es una solicitud de un
  renglón en estado `pagada`; el pago se busca en `adm_pagos` (mismo agente e importe, hasta 30
  días después) y su número va a observaciones. Se puede volver a correr para traer los nuevos.
  Si el CUIL de AEDA no está en el padrón se toma el del beneficiario del agente (`adm_agentes.cta_id` →
  `afi_benef`): hay reintegros con el CUIL mal tipeado o con el DNI de un hijo (237, 1323, 1359).
- **Expedientes y pagos de AEDA**: `importar_aeda_cc_afiliados.py` (después del anterior), lo que en
  gestion_adm hicieron `etl_pasivo` + `etl_reintegros_afiliados`. En AEDA un reintegro es un comprobante de
  `adm_pasivo` (agente tipo 2, tcomp 50, `numero` = `reintegro_id`) con expediente y liquidación. Entran
  solo los que tienen `exp_id` en `adm_pasivo` y no están anulados (pedido del 11/11/2026): los expedientes
  de AEDA sin comprobante no se traen. Expediente en estado **`reintegro`** (fuera de la cuenta corriente de
  proveedores y de los liquidados impagos; la mesa lo trata como contable), orden `reintegro` «AEDA-OP-N» +
  pago «AEDA-PG-N» + `pago_ordenes_reintegro_det` (qué reintegro pagó cada pago, de `adm_pasivoAplic`) y
  `c_reintegro_afiliados.id_orden_pago`. **Solo el gasto, como los reintegros de OSEDA** (pedido del
  11/11/2026): un reintegro o subsidio no devenga deuda, se registra el gasto al pagarlo con la cuenta del
  concepto. Por eso `pres_liquida` NO se trae como `c_pasivo_liquidacion` ni se aplica el pago a nada; si una
  corrida anterior las había creado, el script las saca y el control verifica que queden en cero. Los
  pagos a afiliados que no cancelan ningún reintegro (3: un bono de fin de año y dos de servicios prestados)
  entran como **orden por concepto** «AEDA-OP-N» pagada, con un renglón de gasto «APELLIDO NOMBRE (CUIL …):
  obs de AEDA». AEDA no tiene la imputación: `CONCEPTOS_SIN_REINTEGRO` (servicios prestados → HONORARIOS) y
  si no, GASTOS GENERALES (decidido el 11/11/2026, a revisar con el contador; volver a correr no lo pisa).
  Lo impago en AEDA entra sin orden y sale en el informe (el reintegro sigue `pagada`). Lo anulado en AEDA
  después se anula acá. Marcas propias (`[AEDA reintegro adm_pasivo N]`, `[AEDA reintegro
  adm_pasivoAplic N]` de la versión anterior): no se cruzan con las de `importar_aeda_cc_proveedores.py`.

## Proveedores

La ficha de gestion_adm (`proveedores_routes.py`) con el sistema de estilos de acá. Las tablas
(`c_proveedores`, `c_proveedores_cuentas_pasivo`, `c_proveedores_cuentas_gasto`, `rg830_escala*`)
vinieron de `contable`; `sql/proveedores_20261107.sql` agrega la auditoría
(`c_proveedores_movimientos`), el rubro de pasivo «Proveedores» y los regímenes 78 y 31 de RG 830.
Menú: Proveedores → ABM de Proveedores (31). La carga de comprobantes (32), Comprobantes ARCA (34)
y la mesa de entradas (35) están en la sección siguiente; la cuenta corriente (33) y la aplicación de
comprobantes (36), en «Cuenta corriente de proveedores».

- **Fuera, por ser de la obra social**: la solapa Hospital/Integración (prestadores SSS). Las columnas
  quedan en la tabla, sin tocar.
- **Consultar ARCA** (pedido del 15/11/2026, en proveedores y en empleadores, «igual que en gestion_adm», que
  usa la constancia en las dos): `arca_constancia.py`, `ws_sr_constancia_inscripcion` (padrón A5,
  `getPersona_v2`), sin zeep, con el certificado del sindicato (`arca_wscdc.token(servicio)`). Proveedor
  (`/proveedores/api/arca/<cuit>`): razón social, domicilio fiscal (la dirección entera en «Calle y número»),
  condición de IVA y la de IIBB si ARCA la informa; además muestra Ganancias, categoría del monotributo y
  actividad principal. Empleador (`/empleadores/arca`): razón social y domicilio fiscal, partido en calle,
  número, piso y depto (`partir_direccion`); el legal solo si está vacío entero. La provincia, por nombre
  contra `p_provincia` (como el A13). La regla es la de la ficha del afiliado: lo vacío se completa, lo
  distinto se ofrece; un CUIT que ya es de otro registro avisa con el enlace y no completa nada. En el alta
  consulta sola con el CUIT completo. **Condición de IVA**: por la descripción del impuesto (IVA, IVA EXENTO,
  IVA NO ALCANZADO, MONOTRIBUTO…) y, si falta, por el id (30, 32 exento, 33 no inscripto, 34 no alcanzado,
  20 monotributo); gestion_adm toma el 32 como inscripto y el 33 como exento. «No inscripto» no tiene código
  en `arca_responsable_tipo`: queda vacío y se muestra el texto. Si el certificado tiene el A13 y no la
  constancia (WSAA `notAuthorized`), cae al A13: razón social y domicilio, con un aviso. Test:
  `python tests/test_arca_constancia.py`, sin ARCA.
- **Solapa ARCA del empleador** (pedido del 15/11/2026, la de gestion_adm): estado de la clave, tipo de
  persona, condición de IVA, categoría del monotributo, actividades (orden 1 = principal) e impuestos
  (activos primero), con fecha y usuario de la consulta. Cada consulta completa de la constancia (de la
  ficha de empleadores o de proveedores) se guarda por CUIT en `arca_constancia`, `_impuestos` y
  `_actividades` (`sql/arca_constancia_20261115.sql`; `arca_constancia.guardar` / `leer`); lo del A13 o
  una constancia que ARCA no emite no pisa lo guardado. Si nunca se consultó, la solapa consulta sola al
  abrirse.
- **Actualizar desde ARCA** (botón del listado de Empleadores, pedido del 15/11/2026, el de gestion_adm;
  `empleadores_arca.py`): consulta la constancia de los empleadores que aportan —afiliados con relación
  laboral vigente o cuota en `fisca_cuotarecepcion` en los últimos 12 meses; ~370 de los ~3.100—, del que
  hace más tiempo que no se consulta (o nunca) al más reciente. Guarda la constancia y actualiza el
  **domicilio fiscal** (`fdom_*`) si ARCA informa otro; el legal (`dom_*`, el de las actas) y la razón
  social no se tocan (en gestion_adm el bloque que actualiza es `dom_*`, que allá es el fiscal de ARCA).
  Cada campo cambiado, con el valor de antes, en `arca_constancia_cambios` (sin esa tabla no corre), que
  la solapa ARCA muestra. Corre en un hilo con el estado en memoria (un solo proceso: gunicorn con un
  worker, IIS con maxInstances=1); la pantalla sigue el avance. 15 errores seguidos con el mismo motivo la
  cortan. Consola: `python empleadores_arca.py [--dry-run] [--limite N] [--cuits …]`. Test:
  `python tests/test_empleadores_arca.py`.
- **Solapa Mesa de entradas** (pedido del 11/11/2026, como gestion_adm): área y usuario destino de los
  expedientes del proveedor (`id_area_destino`, `id_usuario_destino`; `/proveedores/<id>/mesa` POST, con su
  fila en la auditoría) y los últimos 10 expedientes. La carga de comprobantes ya derivaba el expediente a
  ese destino. Opcional: en gestion_adm es obligatorio porque además decide quién ve al proveedor, y acá no
  hay visibilidad por áreas. Cambiarlo no mueve los expedientes que ya existen.
- **Un proveedor por CUIT** (`uq_cuit`). Se avisa mientras se tipea y se controla al guardar; al
  editar, solo si el CUIT cambió. Un CUIT o un CBU que no verifica el dígito no se guarda.
- **Alta con imputación**: rubro de pasivo y concepto de gasto obligatorios, en la misma transacción.
  La última cuenta activa de cada clase no se puede dar de baja (en pantalla y en el servidor), y una
  sola es predeterminada.
- **Retenciones**: de qué impuestos el sindicato es agente sale de «Datos del sindicato». Los demás
  bloques van en `<fieldset class="grupo-campos solo-lectura" disabled>`: no viajan en el POST y
  `_leer_form` saca esas columnas, así no se pisa lo guardado.
- **Ganancias**: del proveedor se guarda solo si aplica y el régimen (`ret_ganancias_codigo_sir`, tres
  dígitos). Mínimo, alícuota o escala salen de la fila vigente de `rg830_escala` (`rg830.vigentes`);
  el régimen tiene que estar ahí. A un monotributista (IVA 6, 13, 16) no se le retiene. Las columnas
  viejas `ret_ganancias_alicuota/_escala/_minimo` no se usan: en gestion_adm cada proveedor tenía su
  copia y cada copia decía otra cosa.
- **Auditoría**: una fila por campo en `c_proveedores_movimientos` (también las cuentas que se
  agregan o se dan de baja). Sin FK: al eliminar el proveedor su historia queda. Eliminar solo se
  puede sin comprobantes ni retenciones (las FK lo impiden); si no, se da de baja.
- **Desde AEDA**: `importar_aeda_proveedores.py`. IVA I/E/F/M → 1/4/5/6. La letra de retención de
  AEDA se reconoce por su mínimo y alícuota (`adm_rg2784`): B → 94, C → 78, H → 116, P → 119,
  A → 31; X y Z no retienen; a los monotributistas se les quita, con la nota. El campo CBU de AEDA
  mezcla CBU, CVU y alias: lo que no verifica va a observaciones. Los conceptos de gasto de AEDA que
  no están en el catálogo se agregan (imputación a revisar con el plan de cuentas). Contactos con la
  misma limpieza que los de empleadores. Marca `[AEDA adm_proveedor N]`; se puede volver a correr.

## Comprobantes de proveedores y mesa de entradas

Portado de gestion_adm (`carga_comprobante`, `mis_comprobantes.py`, `mesa_entradas.py`). El circuito:

```
carga del comprobante (f_comprobantes_arca)
  → expediente EXP-AAAA-NNNNNN en la mesa (me_expedientes + me_expediente_movimientos)
  → liquidación ABIERTA (c_pasivo_liquidacion sin fecha_cierre): todavía no es deuda
  → auditoría de comprobantes la cierra → cuenta corriente y orden de pago   [falta]
```

`sql/comprobantes_20261107.sql` crea `f_mis_comprobantes` y las opciones de menú 32 (Carga), 34
(Comprobantes ARCA) y 35 (Mesa de Entradas), para Administrador y Supervisor.

- **Una transacción**: comprobante, expediente, movimiento de ingreso y liquidación abierta van
  juntos (`comprobantes_datos.registrar_comprobante`). En gestion_adm eran tres conexiones y
  quedaban comprobantes sin expediente, que necesitaron un botón aparte para repararse.
- **El emisor tiene que ser un proveedor dado de alta y activo**: la liquidación se imputa con su
  rubro de pasivo y su concepto de gasto. Con más de uno activo hay que elegir (la predeterminada
  es una sugerencia). Desde la carga y Comprobantes ARCA hay un enlace al alta con el CUIT y la
  razón social de ARCA (`/proveedores?nuevo=1&cuit=…&razon=…`).
- **Tres entradas, un formulario**: el PDF se lee con el parser de gestion_adm (copiado tal cual en
  `lector_comprobante.py`; cada patrón está por una factura real), con OCR si es un escaneo y Mis
  Comprobantes si lo leído no alcanza. A mano, el proveedor se busca por nombre y se ofrecen sus
  pendientes de ARCA. Desde Mis Comprobantes (`?mis=<id>`) los datos los dio ARCA.
- **Validación en el servidor, siempre**: duplicado por CAE y por tipo + CUIT + punto de venta +
  número, receptor = CUIT del sindicato (Datos del Sindicato), período obligatorio y no posterior al
  mes de emisión, importes que cierran con el total, imputación. Lo que viene de Mis Comprobantes se
  vuelve a comparar con la fila de ARCA; lo constatado, se vuelve a constatar con los valores que
  llegaron. El `readonly` de la pantalla es cortesía, no control.
- **Constatación con ARCA (WSCDC), opcional**: `arca_wscdc.py`, sin zeep, con certificado PROPIO
  (`SIND_ARCA_CERT` / `SIND_ARCA_KEY`, fuera de la carpeta del sitio; el pool necesita leerlos).
  El token del WSAA es uno por certificado y servicio: compartido con gestion_adm, ARCA le niega el
  token a la segunda app. Se guarda en `SIND_ADJUNTOS/arca/ta_wscdc.json` (uno por servicio: el padrón A13 usa
  `ta_ws_sr_padron_a13.json` y la constancia `ta_ws_sr_constancia_inscripcion.json`) porque IIS corre varios
  procesos. Cada servicio se asocia al certificado en el Administrador de Relaciones de ARCA: `wscdc`,
  `ws_sr_padron_a13` (afiliados) y `ws_sr_constancia_inscripcion` (empleadores y proveedores).
  **El certificado** (15/11/2026): alias `gestionsindicato` de AEDA (CUIT 30-65793727-0, representante el
  mismo que OSEDA), con los tres servicios; en el servidor local `C:\web\certs\aeda_sindicato.crt` / `.key`,
  fuera del repositorio; en Railway, `SIND_ARCA_CERT_B64` / `SIND_ARCA_KEY_B64`. `SIND_ARCA_CUIT=30657937270`
  (Datos del sindicato no tiene el CUIT cargado). **El token va a la base** (`arca_wsaa_ta`,
  `sql/arca_wsaa_ta_20261115.sql`), bajo GET_LOCK: el IIS local y Railway usan la misma base y, con un archivo
  por servidor, el segundo se quedaba sin token hasta 12 horas. Sin la tabla, sigue el archivo.
  `python probar_arca.py [CUIT]` prueba todo desde la consola. Test: `python tests/test_arca_acceso.py`. Sin configurar, todo entra «sin constatar»; rechazado ('R') no entra; ARCA caído ('E')
  entra con aviso. Lo vinculado a Mis Comprobantes con el mismo importe y CAE queda en 'A'
  (`marcar_verificacion_mis`): ARCA lo informa como recibido.
- **Signo**: una nota de crédito se carga en positivo y la liquidación va en negativo. Lo decide el
  tipo (nombre en `arca_tipo_comprobante`), no quien carga.
- **PDF**: temporal en `SIND_ADJUNTOS/tmp_comprobantes/` mientras se confirma (al formulario viaja
  una ficha de 32 hex, nunca una ruta), definitivo en `comprobantes/AAAAMM/CUIT_tipo_pv_nro.pdf` con
  la ruta relativa en la base. `leido_automatico` = el PDF dice lo mismo que los datos
  (`lector_pdf_ocr.cotejar_pdf`). Se adjunta después o se reemplaza desde el expediente mientras la
  liquidación esté abierta y el que hay no se haya confirmado.
- **Bandeja de la mesa** (pedido del 11/11/2026): la de gestion_adm — tarjetas Expedientes e Importe total,
  filtros Buscar / Estado / Área destino / Usuario destino / Ingresado desde-hasta, columnas Expediente,
  Comprobante (tipo, número · emisión, marcas), Proveedor / Emisor, Fecha, Importe, Estado, Destino —
  paginada en el servidor (`paginar.py`) con `/mesa/exportar`. Sin los reintegros de AEDA (estado
  `reintegro`): se ven en Reintegros; el expediente se abre igual por su enlace.
- **Mesa**: derivar (a área o persona), observar, aprobar, rechazar, archivar, nota. Rechazo,
  observación y nota piden texto; derivar pide destino. Liquidado y pagado ya son de la parte
  contable: el movimiento queda pero el estado no retrocede. **Anular** solo con la liquidación
  abierta y fuera de órdenes de pago: expediente y comprobante quedan «anulado» con motivo; se saca
  la liquidación abierta. No se borra nada.
- **Comprobantes ARCA**: el export del portal (Mis Comprobantes → Recibidos → Exportar CSV, el .zip
  tal cual). Reimportar no duplica (`uq_mis_comp`). Pendiente = sin expediente; descartado = no
  corresponde cargarlo (se puede restaurar). La descarga automática del portal no se trajo: con
  requests ARCA devuelve 403 (pide un token que arma el JavaScript del portal).
- **Historia desde AEDA**: `importar_aeda_mis_comprobantes.py` trae `aeda.dbo.adm_comprobafip` (la copia de
  Mis Comprobantes que guarda AEDA, desde 09/2023) a `f_mis_comprobantes` con `nombre_archivo` =
  «[AEDA adm_comprobafip]». Una clave repetida en AEDA entra una vez (la que tiene CAE). Lo que vino del
  archivo del portal no se pisa (el archivo manda y trae el neto por alícuota, que AEDA tiene en cero); lo
  que vino de AEDA se actualiza si cambió; nada se borra. La simulación graba y deshace, así el informe
  (`logs/`) ya dice cuántos vinculan y cuántos quedan pendientes.
- **Punto de venta cortado por AEDA**: `adm_pasivo.prefijo` es varchar(4) y un punto de venta tipeado con cinco
  dígitos perdió el último («00011» → «0001»); así entró a `f_comprobantes_arca`. `vincular_mis` no lo
  encuentra, por eso `comprobantes_datos.vincular_mis_por_numero` hace una segunda vuelta (mismo CUIT, tipo,
  número e importe, un único candidato libre, CAE igual si lo hay). La usan la pantalla y el importador; el
  comprobante no se corrige ni se marca verificado.
- **Lo que se sacó por ser de la obra social**: Integración, hospitales y liquidaciones sin CAE,
  hojas del legajo, correo de comprobantes, FACOEP, trazabilidad y visibilidad por áreas.
- **Dependencias**: `pdfplumber` para leer el PDF; `pymupdf` + `pytesseract` + Tesseract para los
  escaneos (opcional); `cryptography` u `openssl` en el PATH para firmar el pedido a ARCA;
  `openpyxl` solo si se importa un .xlsx en vez del .zip.

## Cuentas corrientes de proveedores (historial de AEDA)

`importar_aeda_cc_proveedores.py` trae la historia de cada proveedor para que
`v_cc_proveedores_saldo` dé lo mismo que AEDA. Es lo que en gestion_adm hicieron los ETL de
`mcp_migracion` (etl_pasivo, etl_pagos, migrar_pagos_a_aplicaciones, etl_anticipo_detalle,
etl_retenciones_origen), en un script y sin tablas intermedias. Agentes `adm_agentes.tipo_id = 1`.

```
adm_pasivo + mse_expedientes + mse_anexos  →  f_comprobantes_arca + me_expedientes «000002303/26»
pres_liquida + pres_liquidait              →  c_pasivo_liquidacion CERRADA (deuda) + detalle
adm_pagos P / A                            →  pago_ordenes «AEDA-OP-<pago_id>» clase proveedor / anticipo
                                              + pago_pagos «AEDA-PG-<pago_id>» (nro_origen = N° de AEDA)
                                              + pago_ordenes_detalle / pago_ordenes_anticipo_det
adm_pasivoAplic P / C                      →  c_pasivo_aplicacion origen «migracion» (pago o NC → factura)
adm_retgan                                 →  pago_retenciones + pago_retenciones_certificado «AEDA-CRT-N»
```

- **AEDA, en una cara**: en `aeda` cada comprobante de proveedor tiene exactamente un expediente,
  una liquidación (cerrada, sin débitos) y un anexo con el CAE. Estado `X` es anulado en todas las
  tablas. Saldo de AEDA = facturas − notas de crédito − pagos − anticipos; en el sindicato es
  debe − haber, con el signo contrario (negativo: se le debe).
- **Control antes de grabar**: con `--aplicar` todo va en una transacción y, antes de confirmarla,
  se compara proveedor por proveedor el saldo de la vista (solo los movimientos que vinieron de
  AEDA) con el de AEDA. Si alguno no da, rollback (salvo `--forzar`). Deja tres archivos en `logs/`:
  resumen, detalle y saldos por proveedor.
- **Se vuelve a correr** mientras AEDA siga en uso: lo ya importado se reconoce por las marcas, lo
  anulado después en AEDA se anula acá (pago, orden, retención y certificado; expediente y
  comprobante con movimiento de anulación), y las aplicaciones se reconcilian enteras. Un importe
  que cambió en AEDA no se pisa: lo muestra el control.
- **Número de expediente**: el de AEDA tal cual (`000002303/26`), como dejó gestion_adm los que migró
  del sistema viejo; los cargados acá son `EXP-AAAA-NNNNNN`. Los primeros se importaron como
  `AEDA-2303/26` y `sql/expedientes_numero_aeda_20261108.sql` los pasa a la forma nueva. Lo
  importado se reconoce por el asunto (`[AEDA adm_pasivo N]`), no por el número.
- **Letra del comprobante**: AEDA dice «Factura» sin la letra. Sale de `f_mis_comprobantes`, si no
  de `adm_comprobafip` (la copia de Mis Comprobantes que tiene AEDA, que trae neto e IVA de las A),
  y si no de la condición de IVA: inscripto → B, el resto → C.
- **Estado del expediente**: `pagado` si las aplicaciones lo cancelan entero, `liquidado` si queda
  saldo (y entonces aparece en `v_expedientes_liquidados_impagos` para la orden de pago).
- **Período**: va a `periodo_desde`/`periodo_hasta`; `f_comprobantes_arca.periodo` es calculada.
- **Pago sin factura** (la que pagaba se anuló): entra como anticipo, «pago a cuenta».
- **Aplicación mal cargada en AEDA**: si un pago quedó aplicado por más de lo pagado y hay UN pago del
  mismo proveedor sin aplicar por exactamente el excedente, se pasa a ese (caso real: E&N SERVICIOS,
  la aplicación 9198 de $15.000.000 está al anticipo 4260 y es del 3916).
- **Anticipos**: necesitan una imputación de clase `anticipo` en `pago_imputaciones_config`; si no
  hay, el script crea «Anticipo a proveedores» sin cuentas contables (completar con el plan).
- **Retenciones**: solo Ganancias. El régimen sale de la ficha del proveedor; sin él entra vacío y
  sale en el informe (completar la ficha y volver a correr lo llena). El certificado conserva el
  número de AEDA; su comprobante es la factura si el pago cancela una sola, si no la orden (tipo 6).
- **No trae** instrumentos de pago ni movimientos de tesorería (cheques, transferencias): van con la
  importación de bancos y fondos.

## Cuenta corriente de proveedores

`cc_proveedores.py`, portado de `gestion_adm/cc_proveedores_routes.py` (pedido del 11/11/2026) sin visibilidad
por áreas, Integración ni dispensas. **Bandeja y estado de cuenta con las columnas, los nombres y los botones de
gestion_adm** (pedido del 11/11/2026): tarjetas Debe / Haber / Saldo final / Pendiente de auditoría, filtros y
grilla en una tarjeta, Concepto con Liq. / Ant. / Pago, Saldo comp. y Saldo, «Aplicar / desaplicar», «Exportar
PDF» (`pagos_pdf._Doc`, el mismo `_ctx_estado_cuenta` que la pantalla) y «Exportar Excel» (el de la grilla). Las
grillas del estado de cuenta no se ordenan (el saldo es acumulado); el saldo anterior va en el `<thead>` para que
no se pagine. Los filtros que van al servidor en la misma tarjeta que la grilla llevan `filtro-srv`.
`sql/cc_proveedores_aplicaciones_20261111.sql`: `c_pasivo_aplicacion_baja` (el rastro de lo desaplicado, la
tabla de gestion_adm) y el menú 36 «Aplicación de Comprobantes» (Administrador y Supervisor). La 33 «Cuenta
Corriente» ya estaba (Administrador, Supervisor y Operador).

- **Saldo = Debe − Haber**, negativo = acreedor (le debemos). Movimientos de `v_cc_proveedores_movimientos`:
  liquidaciones CERRADAS al Haber; pagos y anticipos al Debe. La nota de crédito se muestra en el Debe en
  positivo (`_creditos_al_debe`): lo decide el TIPO de comprobante (`sql_es_credito`, nombre «Nota de
  Crédito …» de `arca_tipo_comprobante`), no el signo. Si tipo y signo no coinciden la fila no se mueve
  (cambiaría el saldo) y se marca «signo al revés».
- **Bandeja**: saldo, rubro, activos y «saldo al» van al servidor (con un rubro es el saldo de ESA cuenta);
  la grilla busca y exporta. «Sin auditar» = liquidaciones abiertas (ingresadas por la mesa): no suman.
- **Estado de cuenta**: por defecto 6 meses; lo anterior es el saldo anterior. Buscar un comprobante
  («8532» o «143-8532», `_where_comprobante`) o «solo con saldo» ignoran las fechas. «Saldo comp.»: lo que le
  falta al comprobante (negativo) o lo que el pago o la nota tienen sin imputar (positivo); suma lo mismo que
  el saldo. Cada forma de cancelar corta por su propia fecha (pago directo `fecha_pago`, aplicación
  `c_pasivo_aplicacion.fecha`). Vista por aplicación: un renglón por comprobante y forma de cancelarlo, con
  desaplicar. El botón de reloj abre «con qué se canceló» (JSON `aplicaciones_de`).
- **Pantalla de aplicación** (17/11/2026): la de gestion_adm, débitos y créditos en dos columnas (`.columnas-2 >
  .col-comp`), un clic en cada una; elegido uno, del otro lado se marca lo del mismo importe y se apaga lo de otro
  rubro; lo que está entero en una orden de pago viva se ve apagado con el aviso.
- **Aplicar** (`c_pasivo_aplicacion`, origen `manual`, fecha de hoy): un crédito —nota de crédito o pago con
  saldo a cuenta (el pago es del proveedor por su orden: expedientes o detalle del anticipo)— contra una
  factura, por hasta el menor de los dos saldos. Se revalida en el servidor con las filas bloqueadas; el
  mismo par acumula (`uq_pasivo_aplic`, `uq_pa_pago_debito`). Solo del mismo rubro de pasivo (sin rubro de un
  lado no se bloquea). **Lo que está en una orden de pago viva no se aplica** (`pd.SQL_ORDEN_RESERVA`):
  `ejecutar_pago` aplica el renglón de la orden sin mirar el saldo y se pagaría de más. No en un período
  cerrado.
- **Desaplicar** (motivo obligatorio, entera o en parte): fila en `c_pasivo_aplicacion_baja` con quién y por
  qué, y DELETE o UPDATE. Una de AEDA (`migracion`) vuelve si se corre `importar_aeda_cc_proveedores.py`
  (AEDA manda): se avisa. Una de una orden de pago deja la factura con saldo y se ofrece otra vez para pagar.
- **Estado del expediente** (`recalcular_estado`, después de aplicar y de desaplicar): «pagado» si el
  comprobante quedó en cero, «liquidado» si le queda saldo, con `id_pago` = el último pago aplicado; el
  comprobante sigue al expediente. La regla de `ejecutar_pago` y del importador. En gestion_adm la
  desaplicación parcial no tocaba el estado y la factura quedaba con saldo y sin pantalla para pagarla.
- La orden nueva a un proveedor con crédito sin aplicar ofrece «Aplicarlo a las facturas».
- Acciones de gestion_adm: `ui.accion('aplicaciones')` (eslabón azul, «Ver aplicaciones») y
  `ui.accion('desaplicar')` (eslabón roto rojo). Colores de saldo: `.saldo-acreedor/-deudor/-cero`,
  `.importe-ok/-danger/-pendiente`; grilla agrupada `tr.fila-grupo-cc` / `tr.fila-hija` + `.td-sangria`.

## Tesorería: plan de cuentas y tablas

`sql/tesoreria_20261108.sql` (columna `activo` en conceptos de gasto, `predeterminada` en cuentas de
fondos con índice único sobre `IF(predeterminada = 1, 1, NULL)`, los bancos del BCRA y el menú 66-69
bajo Tesorería) y después `importar_aeda_tesoreria.py`. Pantallas en `tesoreria.py`, portadas de
`gestion_adm/tesoreria_routes.py`.

```
adm_planctas             →  c_plan_de_cuentas (id_cuenta = pcont_id de AEDA, código 1-1-1-02-020)
adm_cptogasto tipo G / I →  c_concepto_de_gastos / c_motivos_de_ingreso, con la cuenta de AEDA
adm_ctasfondos           →  c_cuentas_de_fondos («[AEDA adm_ctasfondos N]» en el comentario)
adm_chequeras            →  c_chequeras (próximo número = último cheque emitido + 1, de adm_movctas)
adm_ImpuCont             →  cuentas de pago_imputaciones_config (anticipos, retención de Ganancias)
```

- **El plan es el de AEDA**: lo trae `importar_aeda_plan_cuentas.py` (este script usa sus funciones;
  da igual cuál se corra primero). Ver «Contabilidad: plan de cuentas».
- **Lo de la obra social**: los conceptos y motivos que vinieron de `contable` apuntan a cuentas que
  acá no existen. El importador borra los que nada usa y desactiva los usados. Uno cargado en el
  sindicato tiene una cuenta del plan y no se toca nunca. Los motivos de ingreso de AEDA no tienen tabla
  propia: son los 9 de `adm_cptogasto` con `tipo_pig = 'I'` (los que usa `adm_ordIngre`); los 10 que
  vinieron de `contable` no se usan en nada y, salvo los 4 con el mismo nombre, se borran.
- **Uso = no se borra**: un concepto, motivo o cuenta de fondos que se usa se desactiva o
  deshabilita. Dónde se usa cada uno está en `tesoreria.USOS_*` (lo leen pantallas e importador):
  `c_pasivo_liquidacion_detalle.id_concepto_liquidacion` no tiene FK y hay que mirarlo igual.
- **Conceptos activos**: lo que se ofrece al cargar sale de `tesoreria.conceptos_activos()` (ABM de
  proveedores, solicitud de reintegro). Desactivar un concepto no cambia lo ya cargado.
- **Cuenta contable**: solo imputables y activas, agrupadas por clase (`ui.opciones_grupo`); una
  cuenta de fondos, solo del activo. Una imputación que no está en el plan se ve como tal y no deja
  guardar hasta elegir una válida.
- **Banco = CBU**: los tres primeros dígitos del CBU dicen el banco; la pantalla lo elige sola y el
  servidor rechaza uno distinto. En un banco, número y CBU obligatorios; en inversiones, opcionales;
  caja, cartera, tarjeta y otra no los llevan (el fieldset deshabilitado no viaja en el POST).
- **Predeterminada**: la cuenta de pago que viene elegida al cargar un instrumento; a lo sumo una.
  Se apaga la anterior antes de grabar la nueva (el índice único rebota dos a la vez).
- **Chequeras** dentro de la cuenta de banco (solapa Chequeras): en pantalla se pide el último
  usado, se guarda el próximo. Rango sin superposición; con cheques emitidos se deshabilita.
- **Bancos del BCRA**: la nómina de la Com. «A» 8139 con los cambios de junio de 2026 (Wilobank es
  Ualá Bank; el 150 queda como ex HSBC por los CBU viejos). Sin compañías financieras.
- **Formato de transferencias** (`formato_transferencia`): el archivo que arma Transferencias Masivas cuando
  la cuenta ordena. Solo los del banco de la cuenta (en pantalla y en el servidor); vacío = el primero de su
  banco.

## Tesorería: circuito de pagos

Portado de gestion_adm (`pagos_routes.py`, `pago_imputaciones_routes.py`, `retenciones.py`,
`pago_anulacion.py`, `anulaciones.py`, `movimientos_fondos.py`) sin lo de la obra social: pagos de Integración, débitos
de Prisma, acuerdos de pago y recibos de fiscalización. `sql/pagos_20261108.sql` agrega a
`pago_ordenes` el número de origen y los datos de la anulación, la chequera de cada cheque, y deja el
menú de Tesorería como el de gestion_adm (Pagos, Reintegros y Sueldos dentro de Tesorería; Bancos y
las tablas también; «Circuito de Ingresos» 50-52 se va).

```
expediente liquidado (v_expedientes_liquidados_impagos)  ─┐
anticipo a proveedor (rubro del proveedor)               ─┼→ pago_ordenes «borrador»
concepto (gastos e ingresos con período)                 ─┤     → «pendiente» (enviar: un renglón por nivel)
reintegros (pantalla de reintegros)                      ─┘     → «aprobada» (todos los niveles)
                                                                → pago_pagos + instrumentos + retenciones
                                                                  + libro de fondos + aplicación → «pagada»
```

- **Número**: `AAMM-########` desde `c_numeradores` (ámbito = tabla, período = AAMM), igual que
  gestion_adm (`numeracion.py`). Lo importado de AEDA conserva su número en `nro_origen` y la
  pantalla muestra ese (`sql_nro_visible`). Certificados: `CRT-AAAA-NNNNNN`.
- **Aprobación**: Tesorería → Pagos → Config. Aprobadores, un usuario por nivel (1 a 9; varios por
  nivel valen). La orden pide tantos niveles como el mayor configurado al crearla; enviar sin
  aprobadores se rechaza con el aviso. Rechazar pide el motivo y deja la orden «rechazada»; para
  rehacerla se anula, que libera los comprobantes. En gestion_adm el rechazo liberaba los
  expedientes con la orden viva: se podían poner en otra orden y la rechazada seguía apuntándolos.
- **Pago parcial**: una orden puede llevar un comprobante por menos de su saldo; el expediente sigue
  `liquidado` (y vuelve a la lista con «cuota N») hasta que el saldo da cero. Notas de crédito y
  pagos a cuenta del proveedor con saldo se ofrecen al armar la orden; las órdenes sin pagar del
  mismo proveedor se avisan.
- **Retenciones** (`retenciones.py`): solo de lo que el sindicato es agente (Datos del Sindicato) y
  solo en órdenes de proveedor y anticipo. Ganancias RG 830 una vez por proveedor y pago: base =
  importe / (1 + IVA de `ret_arca_tasa_ivaid`), acumulado del mes desde `FECHA_INICIO_CRITERIO`,
  menos el mínimo no sujeto y lo ya retenido en el mes; certificados de exención vigentes bajan la
  alícuota. IVA e IIBB sobre el neto gravado, SUSS sobre el total. `pago_retenciones.origen_alicuota`
  dice de dónde salió cada alícuota. La pantalla las muestra antes de confirmar
  (`/api/orden/<id>/retenciones`) y el servidor las vuelve a calcular al grabar.
- **Instrumentos**: los que cubren el neto (lo retenido no sale de la cuenta). Cheque (de una
  chequera habilitada de la cuenta: se generan N con vencimientos cada tantos días o cada mes, los
  centavos en el último; la chequera avanza), transferencia (CBU del beneficiario precargado),
  efectivo (no desde un banco), débito. Un renglón en `c_movimientos_de_fondos` por cuenta y uno en
  `c_debitos_creditos_bancarios` por instrumento de banco.
- **Aplicación**: `c_pasivo_aplicacion` origen `pago` por lo pagado de cada expediente (el bruto: la
  retención también cancela deuda). El expediente pasa a `pagado` solo si el saldo llega a cero.
- **Anular un pago** (Administrador, motivo obligatorio): no si el período está cerrado, si algún
  instrumento está conciliado o si ya salió en una transferencia masiva (`anulaciones.py`). Deshace
  aplicación, retenciones y certificados, libro de fondos y movimientos bancarios; la orden vuelve a
  `aprobada`. **Anular una orden**: solo sin pago vivo; libera los expedientes y recalcula los
  reintegros por su saldo. Nada se borra.
- **Imputaciones contables** (`pago_imputaciones_config`): la cuenta del anticipo (debe, activo) y la
  de cada retención (haber, pasivo). Sin la del anticipo la orden se arma igual; el asiento queda
  para cuando haya contabilidad.
- **Reintegros**: la orden la genera la pantalla de reintegros; aprobarla y pagarla es de esta
  ficha. Pagarla no cambia el estado del reintegro (`con_orden`), como en gestion_adm.
- **Pendiente**: el mail de la orden (no hay SMTP configurado), SIRE/SICORE,
  sueldos e inversiones. Sus opciones de menú ya
  están y dan «pantalla pendiente».

## Tesorería: movimientos de fondos

`tesoreria_movimientos.py`, portado de `gestion_adm/tesoreria_routes.py` (movimientos_cuentas,
movimiento_nuevo, nueva_orden_ingreso, anulaciones). Todo escribe en el libro único
(`c_movimientos_de_fondos`) con `movimientos_fondos.py`. Menú 56 (Orden de Ingreso), 62-64 (Movimiento
entre Cuentas, Depósitos, Extracciones), 65 (Subdiario), 74 (Anulaciones).

- **El historial viene de AEDA** con `importar_aeda_fondos.py` (ver «Tesorería: el libro de AEDA»). Hasta
  correrlo, el subdiario está vacío y el Panel muestra las cuentas en cero.
- **Origen de un renglón del libro**: la columna que tiene el comprobante (`movimientos_fondos.COLUMNA_ORIGEN`),
  no `tipo_origen`, que nadie completa.
- **Subdiario**: trae todo el filtro (tope 5.000 renglones, con aviso) para que la grilla ordene, filtre y
  exporte como todas. Por defecto, el mes en curso. El saldo corre solo con una cuenta elegida y sin filtros
  de origen ni de importe (con ellos la columna no es el saldo de nada); arrastra el saldo anterior. Los
  anulados se ven con «Con los anulados» y no suman.
- **Operaciones**: el tipo de cada cuenta se controla en el servidor (transferencia: cualquiera menos
  inversión; depósito: caja o cartera → banco; extracción: banco → caja). Inversión tiene su pantalla. Nada
  con fecha futura ni de un período cerrado (`anulaciones._fuera_de_periodo`).
- **Depósito**: con valores elegidos, el importe es su suma y sale de la cartera donde están (una por
  depósito); un cheque diferido no se deposita antes de su fecha. Sin valores, es efectivo. Los valores pasan
  a `depositado` con su movimiento en `c_valores_de_terceros_movimientos`.
- **Extracción**: sale con cheques propios de una chequera de la cuenta (un renglón en
  `c_debitos_creditos_bancarios` por cheque, `mf.registrar_cheques`): números dentro de la chequera, no
  emitidos antes, suman el importe; la chequera avanza y se deshabilita al terminarse.
- **Orden de ingreso**: motivos (con período) y cuentas suman lo mismo; una cuenta una vez. Una cartera pide
  los valores de terceros que la respaldan (suman lo asignado). Se numera `AAMM-########` con el mes de la
  fecha de la orden (en gestion_adm, con el de hoy).
- **Anular** (motivo obligatorio; nada se borra): las reglas de `anulaciones.py` más las propias. Pago: solo
  Administrador, y uno de AEDA no (se anula allá y el importador lo trae). Movimiento: no si un cheque
  depositado ya siguió su camino; los depositados vuelven a cartera y los cheques emitidos quedan anulados.
  Orden de ingreso: no si un valor suyo ya salió de la cartera; los que siguen ahí pasan a `anulado` (en
  gestion_adm quedaban en cartera y se podían depositar).
- **La grilla de Anulaciones** dice de cada renglón si se puede anular con `anulaciones.motivos_en_lote` y
  `tesoreria_movimientos._impedimentos_lote`: las mismas reglas con una consulta por regla para todos los renglones.
  Antes eran de 3 a 6 consultas por renglón (900 renglones en 90 días, miles de viajes del IIS a Railway: tardaba
  minutos; 15/11/2026). Al anular se vuelve a validar el comprobante con `motivos_para_no_anular`. Probado contra
  las reglas de a uno, renglón por renglón, con una base MariaDB armada con cada caso.
- **Recibos Emitidos** incluye los recibos a afiliados (clase `afiliado`, «Empleador o afiliado» con su nombre, se
  buscan por CUIL; aplicado = importe, no tienen cuotas que aplicar).
- **Recibos Emitidos** (`recibos_emitidos.py`, menú 76, `sql/menu_recibos_emitidos_20261115.sql`; pedido del
  15/11/2026, como en gestion_adm): las órdenes de ingreso con número de talonario —cuota sindical y fiscalización,
  las del sistema y las de AEDA (X 0091/X 0092)—, paginadas en el servidor, con su empleador (el CUIT de los
  renglones; en fiscalización, el del acta), los períodos, la cuenta, lo **aplicado** (cuota: `fisca_aplicacion` de
  sus renglones; fiscalización: `fisca_acuerdo_imputacion`) y el estado. El número exacto busca ese recibo esté
  como esté. Abre la ficha y el PDF de `fisca_rec.recibo`, que aceptan este permiso o el de Emisión de Recibos
  (`_guardia_ver`; `?volver=` vuelve con los filtros). No manda mails (gestion_adm sí): el sistema no envía correo.
- **Fichas** del movimiento y de la orden: se imprimen desde el navegador (todavía no hay PDF).

## Tesorería: el libro de AEDA

`importar_aeda_fondos.py` (después de `importar_aeda_tesoreria.py` y de los dos `cc_`), pedido del 11/11/2026,
desde el primer movimiento de AEDA (05/2020). Cada comprobante deja su renglón por `movimientos_fondos.py`,
las mismas funciones que las pantallas.

```
adm_movctas OP + adm_pagos P / A   →  pago_pagos_instrumentos de los pagos ya importados (D transferencia,
                                      Q cheque con su chequera, C o caja efectivo), «AEDA-MOV-<bancomovs_id>»
adm_pagos V + adm_ordpagoit        →  orden por concepto «AEDA-OP-N» + pago «AEDA-PG-N» (gastos varios)
adm_pagos M + adm_movctas PF       →  c_movimiento_entre_cuentas «[AEDA adm_pagos N]» (pase, inversión,
                                      depósito o extracción con sus cheques)
adm_movctas DB                     →  c_movimiento_entre_cuentas «[AEDA adm_movctas DB N]» (cartera → banco)
adm_movctas RC + fis_cobros        →  ingreso_ordenes «AEDA-RC-<cobro_id>» (cuota sindical o fiscalización,
                                      período y empleador)
adm_movctas OI + adm_ordIngre      →  ingreso_ordenes «AEDA-OI-N» (alquileres, YMCA, intereses, varios)
adm_valores + adm_valoresmv        →  c_valores_de_terceros «[AEDA adm_valores N]» con su historia
```

- **AEDA, en una cara**: `adm_movctas` es el libro; `debito` es plata que sale de la cuenta y `credito` la que
  entra. `ref_id` dice de dónde viene: OP (`ref_nro` = `pago_id`), PF (`ref_nro` = `pago_nro` del pase M), DB
  (número de depósito, los dos lados), RC (`ref_nro` = `fis_cobros.cobro_id`), OI (`adm_ordIngre.oi_id`). Lo
  pagado por OP es el neto (el importe menos lo retenido).
- **Control**: con `--aplicar`, antes de confirmar, el saldo de cada cuenta en el libro (solo lo de AEDA) contra
  crédito − débito de `adm_movctas` sin lo anulado. Si alguna no da, rollback (salvo `--forzar`).
- **AEDA no tiene saldos de apertura**: el saldo es el del libro desde 2020 y no siempre el del banco (la cuenta
  corriente 2049118 da negativa en AEDA). Para que coincida con el extracto falta un ajuste de apertura.
- **Gastos varios**: concepto por descripción (corte de 30 letras de AEDA); el 136 ya no existe en AEDA y va a
  GASTOS GENERALES. Un pago sin beneficiario (no es de un proveedor ni de un afiliado) entra igual, con el
  concepto que dice su observación. Uno de un proveedor o un afiliado que falta no entra: lo trae su importador.
- **Fuera**: los pases de una cuenta a sí misma (no mueven nada), los 2.511 cobros de `fis_cobros` sin renglón en
  el libro (casi todos de 2023), lo anulado no importado y la conciliación (`adm_conciliamov`): los renglones
  bancarios quedan «emitido».
- **Reversiones**: un pago en estado R de AEDA se deshizo con otro en negativo («Reversion Orden de pago N»,
  misma cuenta e importe: 257/346, 1684/1685 y el anticipo 26/1059). Entran los dos; la reversión vuelve a la
  cuenta por el debe del libro (`_registrar_reversion`, porque `registrar_pago` solo escribe el haber y borraría
  el renglón). Un gasto vario revertido lleva los conceptos del original, en negativo.
- **Valores**: librador = CUIT del cobro; `nro_cheque` es de 8 (uno más largo guarda los últimos 8 y el número
  entero va a observaciones).
- **Se vuelve a correr**: lo anulado en AEDA después se anula acá (pago y orden, movimiento o ingreso, con su
  renglón del libro); `registrar_pago` vuelve a pasar por cada pago de AEDA, así un pago anulado en el sindicato
  saca su renglón.

## Tesorería: Panel de Control

`tesoreria_panel.py` (`/tesoreria`, menú 61), portado de `gestion_adm/tesoreria_routes.index` sin débito
automático (es de la obra social) ni la posición por conciliación (`flujo_fondos`: acá todavía no hay
conciliaciones). Una foto de hoy, bloques uno debajo del otro:

- **Tarjetas** (`a.kpi-card`: cada una lleva a la pantalla donde se resuelve, si el usuario la tiene): órdenes
  por pagar (aprobadas) y esperando aprobación → Emisión; comprobantes liquidados sin orden → nueva orden;
  reintegros con saldo (`reintegros_datos.listar_con_saldo`) → Órdenes de reintegros; transferencias que no
  salieron en un archivo (con cuántas no tienen CBU) → Transferencias Masivas; valores en cartera (y cuántos
  ya vencieron y se pueden depositar) → Depósito.
- **Cuentas de fondos**: saldo del libro (`v_saldos_cuentas_fondos`), saldo del extracto y diferencia, con
  enlace al subdiario de la cuenta. Mientras el libro no tenga movimientos, un aviso dice que los ceros son
  porque falta el historial (no que no haya plata): se trae con `importar_aeda_fondos.py`.
- Órdenes en curso por estado y estado de los extractos de cada banco (atrasado a los 7 días).

## Tesorería: extractos y conciliación

`extractos.py`, `extractos_bancarios.py` y `conciliacion.py` (11/11/2026), portados de
`gestion_adm/extractos_bancarios*.py` y de los `conc_*` de `gestion_adm/tesoreria_routes.py`. Menú 71
(Extractos Bancarios), 72 (Conciliación Bancaria), 73 (Clasificación Conceptos Bancarios). Esquema:
`sql/conciliacion_bancaria_20261111.sql` (regla «pase a otra cuenta» con `conc_reglas.id_cuenta_destino` y
`conciliacion_comprobantes.id_debito_credito`, con índice único).

- **Extractos**: BNA (CSV clásico o `BEE_Reporte` de Banca Empresas) e ICBC (cuenta corriente o reporte de
  recaudaciones, con la fecha al principio del nombre). Varios archivos o una carpeta. Duplicado = mismo número
  de operación, fecha e importe (sin número, el concepto); los renglones idénticos se cuentan. **Control de
  cuenta**: los últimos 5 dígitos del número que trae el archivo, contra el número del maestro o la parte de la
  cuenta del CBU; si no coincide, no entra nada. El BNA clásico no trae cuenta: pasa con aviso. Un renglón que
  entró en una conciliación no se borra.
- **Interbanking** (15/11/2026, como lo carga AEDA): el «Extracto de Cuenta» en Excel (`reporte_-_<fecha>.xlsx`,
  banco `IBK`). `interbanking_a_texto` lo pasa a texto «;» (la hoja declara dimensión A1:A1: `reset_dimensions`)
  y `parsear_interbanking` lo lee: Comprobante → `ref_nro` (el mismo número que el CSV del banco y que
  `adm_bna24` de AEDA, así no se duplica), Importe con signo, Descripción → concepto, CUIT de su columna salvo
  el propio (el del renglón Ley 25.413). No trae saldo por renglón: con el saldo inicial y los movimientos se
  pone el cierre de cada día en su último renglón, y tiene que dar el «Saldo Final» (si no, solo el último
  renglón lo lleva). El `origen` sale del banco de la cuenta (011 BNA, 015 ICBC, si no MANUAL). Se detecta por
  la extensión; elegido a mano otro formato, el .xlsx no entra.
- **Los dos lados**: extracto (`c_extractos_bancarios`) contra libro (`c_debitos_creditos_bancarios`, un renglón
  por cheque, transferencia o depósito, con la óptica del banco). No es el renglón de `c_movimientos_de_fondos`:
  un pago de seis cheques se debita en seis días y cada cheque se concilia solo.
- **Conciliar = un grupo** (`conciliacion_grupos`): N renglones del extracto (`conciliacion_items`, «conciliado»)
  contra M del libro (`conciliacion_comprobantes.id_debito_credito`). Con diferencia de importe, solo con una
  observación. **Excepción**: renglón del extracto explicado sin contraparte, con motivo. Desvincular borra el
  grupo; un comprobante generado desde la conciliación sigue existiendo (se anula en Anulaciones).
- **Desde cuándo**: desde el **01/11/2026** (`s_configuracion` tesoreria / `conc_fecha_corte`, decidido el
  12/11/2026). Lo anterior del libro (el historial de AEDA) se da por conciliado y no se crean conciliaciones que
  empiecen antes. El libro se mira desde el corte (o la primera conciliación de la cuenta, si es posterior) hasta
  el fin del período, con arrastre; «Incluir anteriores» suma 60 días antes del corte.
- **Sugerencias** (no vinculan solas): número de cheque, CUIT + fecha + importe, CUIT + importe, fecha + importe,
  solo importe; siempre únicas de los dos lados, y las dos últimas descartan el par con CUIT o cheque distintos.
  El CUIT del libro: el del beneficiario del pago, o el del empleador en la descripción de la orden de ingreso
  de cuota sindical («(CUIT 30716707519)»). Sin las pasadas de la obra social (familia, nómina, Prisma).
- **Clasificación** (`conc_reglas`, patrón «contiene» = el concepto sin lo que va después de « — »): gasto
  (orden de pago por concepto), ingreso (orden de ingreso), pase a otra cuenta propia, o a mano. Se aplica al
  dibujar la conciliación (no se graban ítems pendientes). Gana la de patrón más largo. Quitar desactiva.
- **Generar comprobantes**: para lo clasificado con «genera»: gasto → orden `concepto` aprobada con todos los
  niveles, pagada en el acto por transferencia desde la cuenta; ingreso → `ingreso_ordenes` clase `bancario`,
  origen `conciliacion`; pase → movimiento entre cuentas (el sentido sale del extracto). Fecha y numeración
  AAMM del banco; uno por renglón o por día si la regla agrupa. Cada grupo en su transacción; no en un período
  contable cerrado. Si el libro ya tiene algo que coincide, el grupo viene destildado: el historial de AEDA
  cargó los gastos bancarios de cada mes en una sola orden («Gastos Bancarios / IMPUESTO LEY…»), que se
  concilia a mano contra los N débitos.
- **Cerrar**: sin pendientes, con las anteriores de la cuenta cerradas, saldo inicial = cierre de la anterior y
  saldo final calculado = saldo del banco (del último renglón con saldo, o escrito). Marca `conciliado` en el
  extracto. **Reabrir** (Administrador, con motivo): si no hay una posterior cerrada.
- **Anular**: `anulaciones.sql_conciliado_libro` — un comprobante con un instrumento vinculado no se anula
  (aunque la conciliación siga abierta): primero se desvincula.
- **Saldos**: `conciliacion_header.diferencia` es columna calculada (no se escribe). El saldo inicial de la
  primera conciliación de una cuenta se carga a mano; el diálogo propone el que se deduce del extracto.
- El bloque «El libro contra el banco» del detalle es informativo: AEDA no tiene saldos de apertura.

## Transferencias masivas

`transferencias.py` (`/pagos/transferencias`, menú 46), `transferencias_lote.py` y
`transferencias_formatos.py`, portados de `gestion_adm` (`transferencias_routes.py`, `transferencias_lote.py`,
`integracion_transferencias.py`, `pago_transferencias_icbc.py`). Sin Integración, sueldos, visibilidad por
áreas ni Interbanking (en gestion_adm depende de sueldos).

- **Qué se ofrece**: un renglón por instrumento de transferencia (un pago abierto en dos cuentas son dos) de
  pagos no anulados (**ni de AEDA**, `AEDA-PG-…`: ya salieron desde allá; 18/11/2026, el Panel de Tesorería
  resolvía el beneficiario de ~2.000 y tardaba minutos) de clase proveedor, anticipo o reintegro (`transferencias_lote.CLASES`: lo que entra, no
  lo que queda afuera), no conciliados (`anulaciones.sql_pago_conciliado`, la misma regla que al anular) y que
  no salieron en un lote vigente. Por defecto, los pagos de hoy y la cuenta predeterminada.
- **La cuenta del filtro es la ordenante**, y el formato es el de la cuenta (Cuentas de Fondos → Formato de
  transferencias; vacío = el primero de su banco por el código BCRA). No se eligen al generar: no hay campo
  que manipular. El servidor vuelve a traer lo elegido con los mismos descartes y rechaza instrumentos de otra
  cuenta.
- **Destino** (`resolver_beneficiario`): el CBU o alias cargado en el instrumento; si no, proveedor y anticipo
  → ficha del proveedor (CBU, si no alias); reintegro → renglón de la orden, solicitud, ficha del afiliado,
  CBU antes que alias en cada nivel. Una orden de más de un proveedor no se transfiere.
- **Lo que no puede ir se ve** (`tr.fila-apagada` + `.td-motivo`), sin casilla: sin CBU, CBU que no verifica,
  o alias en un formato del BNA (`transferencias_formatos.motivo_destino`; el ICBC toma alias). En gestion_adm
  el generador del BNA salteaba esos renglones en silencio y el lote los daba por transferidos.
- **Generar** registra el lote (`pago_transferencias_lote` + `_det`, incluidos y excluidos con su motivo),
  congela el destino en el instrumento si estaba vacío y lleva a la ficha del lote, que baja el archivo solo.
  El archivo no se guarda: se arma siempre con lo registrado (`/lote/<id>/descargar`), así lo que se baja es
  lo asentado aunque la ficha del proveedor cambie después.
- **Desde que sale en un lote el pago no se anula** (`anulaciones.ya_transferido`). Si el archivo no se subió
  al banco: sacar un renglón (motivo; si era el último, el lote se anula solo) o anular el lote entero. Lo
  conciliado no se libera: el banco ya lo debitó.
- **Formatos**: BNA24 (216 posiciones, CBU ordenante y pie con cantidad + 1 y total en centavos), BNA Empresa
  (99, sin ordenante ni pie) y la planilla del ICBC (encabezados exactos, todo como texto con `quotePrefix`,
  monto con punto). Concepto de tres letras para el BNA (FAC por defecto). Los .txt en latin-1 con CRLF.

## Escala RG 830

`tesoreria_rg830.py` (`/tesoreria/rg830`, menú 75: Tesorería → Tablas), portado de
`gestion_adm/tesoreria_routes.py` (rg830_escala), que solo daba de alta. `rg830_escala` (+ `_tramos`): por
código de régimen, alícuota fija o escala, mínimo no sujeto, retención mínima, no inscriptos y vigencia. La
leen `rg830.vigentes` (ficha del proveedor) y `retenciones.regimen_ganancias` (el pago): la fila activa más
nueva que cubre la fecha. Los códigos se comparan normalizados a tres dígitos (la tabla guarda «94»).

- **Usada** = hay retenciones de Ganancias no anuladas de su código dentro de su vigencia
  (`pago_retenciones.regimen`). Una usada no cambia código, valores, tramos ni inicio; se editan descripción,
  resolución, observaciones y el fin (no antes de la última retención). Para cambiar valores, «Nueva
  vigencia» (`?clonar=ID`): copia y, al guardar, cierra la anterior el día antes.
- **Vigencias de un código**: no se pisan. Una nueva que arranca después de otra abierta la cierra el día
  antes, salvo que aquella ya haya retenido desde esa fecha; una que cae en el medio de otra o empieza antes
  de una existente no se acepta.
- **Tramos**: el primero desde 0, contiguos, solo el último sin tope (si no, una base mayor retendría cero).
  El importe fijo de cada uno se compara con lo que acumulan los anteriores: aviso, no bloquea.
- **No dejar proveedores sin régimen**: la única escala vigente de un código con proveedores no se desactiva
  ni se elimina. Una usada no se elimina (se cierra).
- **Simulador** en la ficha: con lo cargado y sin guardar, la misma cuenta que el pago (fijo del tramo +
  excedente × alícuota sobre la base menos el mínimo; retención mínima).

## Contabilidad: plan de cuentas

Menú Contabilidad (90): Plan de Cuentas (91) en `contabilidad.py`; Ejercicios (92), Asientos (93) y Libro Diario
(94) en la sección siguiente; el Libro Mayor (95) todavía no tiene pantalla. Portado de `gestion_adm/contable.py`
sin la importación desde Excel: el plan viene de AEDA y se completa en la pantalla.

```
adm_planctas  →  c_plan_de_cuentas   id_cuenta = pcont_id de AEDA, código 1-1-1-02-020 (máscara 9-9-9-99-999)
```

- **El código manda** (`plan_cuentas.py`, lo mismo en la pantalla y en los importadores). Se carga código
  y nombre; de ahí salen la clase (primer tramo, tiene que estar en `c_clasificacion_plan_cuentas`), el
  nivel (posición del último tramo distinto de cero), la madre, si es imputable (último tramo distinto de
  cero) y si es corriente (no es 1-2 ni 2-2). En gestion_adm la madre se elegía de una lista y el nivel
  contaba tramos hasta el primer cero: 4-1-0-01-050 quedaba en nivel 2.
- **La madre** es la cuenta más cercana que existe recortando el código. AEDA no tiene 5-2-0-00-000,
  5-3-0-00-000 ni algunos títulos de patrimonio: esas cuentas cuelgan de la más cercana (5-0-0-00-000
  EGRESOS). Después de cada alta, cambio de código o baja se rearma la jerarquía entera
  (`rearmar_jerarquia`): crear 5-3-0-00-000 hace que sus 26 cuentas pasen a colgar de ella.
- **AEDA marca 4-2-0-00-000 INGRESOS DIVERSOS como imputable** y tiene seis cuentas debajo (sin
  asientos): entra como título. Es la única cuenta donde la marca de AEDA y el código no coinciden.
  AEDA repite 5-3-0-00-105 CAJA DE SEGURIDAD (122 y 161): entra la primera y lo de la otra va a esa.
- **Monetaria** se elige (viene sugerida: 1-1 salvo bienes de cambio, y todo el pasivo); revisarla con
  el contador antes del primer ajuste por inflación. **Activa** se elige.
- **Dónde se usa una cuenta**: `plan_cuentas.USOS` (conceptos, motivos, cuentas de fondos, rubros,
  imputaciones de pago y de sueldos, asientos automáticos, renglones de asientos, balances). Con cuentas
  debajo o con usos (salvo balances ya generados) no cambia de código; con usos o cuentas debajo no se
  elimina; si la usa algo vigente (todo menos asientos y balances) o tiene cuentas activas debajo, no se
  desactiva. `c_rubros_de_pasivo.c_plan_de_cuentasId` es texto: se compara como número.
- **Código cómodo**: se acepta con puntos o sin los ceros de cada tramo («5.3.0.0.14» → 5-3-0-00-014).
  El código sugerido para una subcuenta (`?madre=ID`) sigue a la última hermana con el mismo paso.
- Dos cuentas con el mismo nombre debajo de la misma madre no se aceptan (no se distinguen al elegir);
  en lugares distintos sí (CAJA título y CAJA imputable).

## Contabilidad: ejercicios, asientos y Libro Diario

Pedido del 18/11/2026: el Libro Diario «con las mismas opciones que OSEDA» (`gestion_adm/contable.py`: asientos,
exportar_asientos, exportar_diario, exportar_asientos_externo, descargar_ejemplo_asientos, importar_asientos,
renumerar_asientos, ejercicios, periodos, seleccionar_ejercicio). Las reglas en `asientos.py`; pantallas en
`contabilidad_ejercicios.py` (92) y `contabilidad_diario.py` (93 Asientos = cargar, 94 Libro Diario = consultar:
el permiso es la opción de menú, como Consulta del Padrón y ABM). `sql/contabilidad_diario_20261118.sql` agrega
`c_asientos.origen` / `id_origen` (único: `aeda` + asto_id, `excel`); las pantallas andan sin él, el importador no.
Tests: `python tests/test_contabilidad_diario.py` (sin base); además se probó de punta a punta contra una MariaDB
armada con estas tablas (alta, edición, confirmación, cierre, renumeración, importación, exportaciones, PDF).

- **Ejercicio**: se abre con sus períodos, uno por mes («Enero 2026»; el primero y el último pueden ser parciales).
  En gestion_adm lo hacía `sp_abrir_ejercicio`, que esta base no tiene. CUIT y razón social de Datos del Sindicato
  (`empresa_id` queda NULL: el sindicato no es un registro de `p_empresas`). No se superponen. Uno es el **de
  trabajo** (`c_ejercicios.activo`): el que muestran el Diario y la carga (el primero que se abre queda activo).
- **Cerrar**: el período (de a uno, desde la ficha: cerrado o bloqueado) o el ejercicio (cierra todos los suyos).
  No con borradores. Cerrar el ejercicio **no genera el asiento de cierre** (`sp_cerrar_ejercicio`): pendiente. Un
  período cerrado no admite asientos y **Tesorería no anula** comprobantes de esas fechas
  (`anulaciones._fuera_de_periodo` ya miraba `c_periodos`).
- **Asiento**: borrador → confirmado (anulado: la pantalla de anulación de gestion_adm todavía no se trajo). El
  **período sale de la fecha** y tiene que estar abierto (en gestion_adm se elegía aparte). Partida doble: dos
  renglones o más, cada uno al debe o al haber, cuentas imputables y activas, debe = haber al centavo. **Número
  correlativo por ejercicio** (`proximo_numero`, con la fila del ejercicio bloqueada; en gestion_adm la carga
  numeraba por período y la importación por ejercicio). Un borrador se corrige y se elimina; un confirmado no.
- **Libro Diario**: filtros ejercicio (por defecto el de trabajo, «todos»), período, estado, tipo, fechas; tarjetas
  con borradores, total y los que no balancean. Exporta: el **libro** (Excel con encabezado, PDF con un bloque por
  asiento), los **asientos** confirmados con las columnas del archivo de importación (lo exportado se reimporta) y
  el **formato externo** de un rango (obligatorio; `exportar_contable_externo.py`, copiado tal cual).
- **Importar** (.xlsx o .csv, el modelo de gestion_adm; acepta la fila de instrucciones arriba y «;» o «,»): el N°
  del archivo solo agrupa; cada asiento entra en **borrador** (en gestion_adm el aviso decía borrador y lo grababa
  confirmado), con un SAVEPOINT por asiento: los que fallan se informan y no frenan a los demás. «Confirmar los
  borradores» confirma los del filtro de una vez.
- **Renumerar**: el ejercicio del filtro, la apertura primero y el resto por fecha (pasa por negativos por el
  índice único período + número). Pierde los números de AEDA.
- **AEDA** (`importar_aeda_asientos.py`): `adm_asientos` + `adm_asienpase` + `adm_asienref` (4.584 asientos al
  17/11/2026, de 10/2023 en adelante, todos en su ejercicio 1: `Adm_Ejercicios` está vacía). `pcont_id` = id_cuenta.
  Número y usuario de AEDA, referencia = sus `adm_asienref` («OP 4475» = el pago AEDA-PG-4475 de acá). **AEDA deja
  sin cuenta (pcont_id 0) el renglón del afiliado en los pagos de reintegros** (664 renglones): se imputa al gasto
  del concepto de lo que el pago canceló (`adm_pasivoAplic` → `afi_reintegros.conc_id` → `adm_cptogasto.pcont_id`;
  652 de 664 cuadran justo), y lo que no se rastrea a `--cuenta-sin-imputar` (5-3-0-00-150 GASTOS GENERALES, la de
  importar_aeda_cc_afiliados.py), con aviso. Confirmado si balancea; si no (12 en AEDA), en borrador. Se puede
  volver a correr (lo importado no se toca); no entra en períodos cerrados ni en fechas sin ejercicio:
  `--crear-ejercicios` abre los que falten por año calendario.
- **Pendiente**: Libro Mayor, anulación de asientos, asiento de cierre, libro de trabajo (los asientos que
  generarían las operaciones; en gestion_adm `libro_trabajo.py`, que es de la obra social).

## Estado de la base

Ver `sindicato_estructura.md` para el detalle completo. Resumen:

- 141 tablas + 16 vistas + 202 FK, replicadas desde `contable` con `CREATE TABLE ... LIKE`
- Collation unificada en `utf8mb4_0900_ai_ci` en toda la base
- Módulos: sistema/seguridad, empleadores, padrón de afiliados, proveedores y pasivo, reintegros,
  circuito de pagos, circuito de ingresos, fondos/tesorería, bancos y conciliación, contabilidad
- Fuera de alcance: liquidación de planes (`l_*`), fiscalización (`f_*`), Mecanismo de Integración,
  SSSalud, débito automático Prisma, nómina ARCA

### Con datos cargados

- `p_empresas`: 2.854 empresas copiadas de `contable` + 266 dadas de alta desde AEDA
  (`importar_aeda.py`, 07/11/2026; llevan `[AEDA afi_empresas N]` en observaciones)
- `s_contactos`: 1.200 contactos de 774 empleadores, desde AEDA
- `p_afiliados`: se carga desde AEDA con `importar_aeda_afiliados.py` (ver «Padrón de afiliados»)
- Catálogos ARCA, provincias, bancos, escalas RG 830, rubros, conceptos de gasto, motivos de ingreso,
  roles, y los catálogos del padrón (parentesco, nacionalidad, obras sociales, etc.)

### Vacías, a definir

- `padron` (3.891 filas, un archivo de AEDA de julio 2026) queda **independiente** de `p_afiliados`:
  no se migra ni se vincula. El padrón vivo es `p_afiliados`, cargado desde `aeda.dbo.afi_benef`.
- `c_proveedores` — se cargan desde AEDA con `importar_aeda_proveedores.py` (ver «Proveedores»);
  su cuenta corriente, con `importar_aeda_cc_proveedores.py`
- `s_usuarios`, `s_areas`, `s_menu` — armar de cero
- `c_ejercicios`: se abren en Contabilidad › Ejercicios (o `importar_aeda_asientos.py --crear-ejercicios`), con
  el CUIT de Datos del Sindicato y `empresa_id` NULL

### Nombres que se prestan a confusión

- **La tabla de empresas es `p_empresas`.** No existe ninguna `a_empresas`, ni acá ni en `contable`.
  El dashboard venía con un `LEFT JOIN a_empresas` tapado por un `except Exception: pass`: fallaba
  siempre y mostraba todo en cero, que se parece bastante a no tener datos.
- **La tabla puente de roles es `s_usuario_rol`** (`usuario_id`, `rol_id`), no `s_usuarios_roles`.
- `fisca_cuotarecepcion.cuit` es `varchar(11)` y `p_empresas.CUIT` es `bigint`. El JOIN necesita
  `CAST` con `REGEXP` antes — ver la constante `JOIN_EMPRESAS` en `gestion_sindicato.py`. El REGEXP
  no es ceremonia: `CAST('30-12345678-9' AS UNSIGNED)` no falla, devuelve `30`, y ese 30 matchea la
  empresa equivocada.

---

## Interfaz: sistema de estilos (no negociable)

Todas las pantallas se arman con **`static/css/sindicato.css`** y las macros de **`templates/_ui.html`**.
La guía visual, con cada componente y la línea para copiarlo, está en **`/estilos`**. En
`gestion_adm` cada plantilla traía su CSS y las copias se fueron separando (el mismo botón con tres
colores, `.btn-accion` definido dos veces): acá eso no se repite.

- **Una plantilla no trae `<style>` ni colores, bordes o tipografía en `style="…"`.** Solo datos de
  la pantalla: el `--span` de un campo, el ancho de una columna. Si falta un componente, se agrega
  a `sindicato.css` **y a la guía**.
- **Colores por función**: `--ok`, `--danger`, `--warn`, `--info` (cada uno con `-texto`, `-bg`,
  `-borde`), `--pdf`, `--excel`. Marca: `--navy #1c5a8f`, `--blue #1a7ac2` (4.56 de contraste con
  blanco: el más claro que pasa WCAG AA; no aclararlo).
- **Íconos y botones de acción, siempre con las macros**: `ui.icono(nombre)`,
  `ui.accion(tipo, href=…| onclick=…, datos={…})`. Cada acción tiene un ícono y un color fijos: ver =
  ojo verde, editar = lápiz azul, borrar = tacho rojo, baja = prohibido rojo, reactivar = flecha
  verde, agregar = más azul, pdf, planilla, descargar, historial, mail. Los valores de la fila viajan
  en `datos` (atributos `data-*`), nunca serializados en el onclick.
- **Grillas**: `.card` > `ui.barra_filtros()` > `.data-table-wrap` > `table.data-table` >
  `ui.paginacion()`, y `gestion_admTable(id, {filtroExtra})`. La barra es igual en todas:
  buscar (en vivo) · filtros propios (`.filtro`, cada uno con su rótulo arriba: `{% call ui.filtro('Estado') %}`;
  selects y casillas se aplican solos, fechas esperan a **Filtrar**) · **Filtrar** (embudo) · **Quitar filtro** (embudo tachado) · contador ·
  **Exportar a Excel** · filas por página. Primera columna `th.col-acciones data-no-sort`. Todos los
  encabezados ordenan (⇅ / ▲ / ▼); `data-exportar` en la tabla nombra el archivo. Arriba de toda
  grilla ancha aparece una segunda barra de desplazamiento, sincronizada.
- **Número de expediente**: siempre con `ui.expediente(id, nro)`, que lleva al expediente en la mesa
  (en otra pestaña; sin permiso para la mesa, el número sin enlace). **Marcas del comprobante**
  (`ui.marcas(fila)`): las tres de gestion_adm —escudo ARCA, robot PDF leído, ojo verificado—
  debajo del número del comprobante, nunca en una columna aparte.
- **Resumen de una carga o ficha** (`.con-resumen` > contenido + `aside.card.resumen`): un bloque
  debajo del otro, el resumen a lo ancho con las cifras en fila y los botones a la derecha. Al
  costado le sacaba ancho a las grillas.
- **Estados con texto**: `ui.estado(texto, tipo)`, `ui.activo(activo, fecha_baja)`, `ui.si_no(v)`. Tipos: ok,
  danger, warn, info, neutro, proceso; para un circuito con más estados, `turquesa`, `violeta` y `naranja` (la mesa
  de entradas: cada estado con su color, `comprobantes_datos.ESTADOS_TIPO`).
  Una fila dada de baja lleva `.fila-baja`.
- **Consultar ARCA** en una ficha: `ui.arca_consulta()` (botón y recuadro `#arca-resultado`) y, en
  base.html, `arcaPedir` / `arcaCompletar` / `arcaMostrar`: lo vacío se completa, lo distinto se lista con
  «Usar los datos de ARCA». La pantalla define `consultarArca(auto)`. Lo usan afiliados, empleadores y
  proveedores.
- **Formularios**: `.bloque` > `.campos` (grilla de 12) > `.campo style="--span:N"`; ayuda en
  `.campo-ayuda` (`.ok` / `.error`); casillas con `label.campo-check`; pie `.form-acciones`. Selects de
  catálogo con `ui.opciones(items, valor)`: si el valor guardado no está en el catálogo lo agrega en
  vez de dejar que el navegador elija la primera opción y lo cambie al guardar.
- **Buscador general** (barra superior, `buscador.py`, pedido del 15/11/2026; el `/api/busqueda_rapida` de
  gestion_adm): afiliados (titulares y familiares), empleadores y proveedores por CUIL o CUIT, DNI o nombre. Cada
  palabra tiene que estar (en el nombre, o en el CUIL / documento / CUIT si es un número de 3 dígitos o más, con
  puntos o guiones); lo que coincide entero va primero. Solo busca lo que el usuario puede abrir (`db.puede`):
  afiliado → ficha del ABM o de la consulta; empleador → su ficha; proveedor → cuenta corriente o ficha. Busca a
  los 300 ms de dejar de tipear; Enter abre el elegido o el único; flechas y Escape. Sin la consulta a ARCA ni
  los aportes de un CUIL que no está en el padrón (de gestion_adm). En la guía, «Buscador general». Test:
  `python tests/test_buscador.py`.
- **Mensajes**: `ui.mensajes(errores)` (flash en verde; un flash que empieza con «!» sale como
  advertencia) y `ui.aviso(texto, tipo)`.
- **Solapas**: `ui.solapas([(panel, texto, conteo)], inicial)` + `.abm-panel` + `abmSolapa()`.
  **Diálogos**: `.modal` > `.modal-caja`, `abrirModal(id)` / `cerrarModal(id)`.
- La edición carga por `?edit=ID`, nunca poblando el formulario desde JavaScript.
- Toda pantalla nueva lleva su sección de ayuda (ver «Ayuda (manuales de uso)»).
- Importes con `{{ (valor or 0) | miles }}` (los paréntesis son obligatorios), a la derecha.
- Los `input.inp-importe` toman separador de miles con `fmtMiles` / `fmtMilesInit` de `base.html`.

## Convenciones de código

- `DictCursor` devuelve diccionarios: nunca `tipo, n = row` ni `row[0]`
- Nunca `DATE_FORMAT` con `%` en SQL que pasa por sustitución de parámetros de PyMySQL —
  usar `CONCAT(YEAR(...), LPAD(MONTH(...),2,'0'))`
- `cur.lastrowid` se captura **dentro** del context manager del cursor
- Nada de `except Exception: pass` ni `return []` silencioso — el error se reporta
- `CAST(campo AS UNSIGNED)` para comparar CUIL/CUIT entre tablas, con `REGEXP '^[0-9]+$'` antes del cast
- `ON DUPLICATE KEY UPDATE` para upserts
- Numeración de comprobantes con `c_numeradores`, nunca con `COUNT(*)`
- Templates en `templates/` con subcarpeta por módulo
- `url_prefix` se define al registrar el blueprint; los decoradores de ruta no lo repiten
- `register_blueprint` antes de llamar a cualquier helper de registro

## Reglas de negocio heredadas

- Las operaciones de pago pertenecen exclusivamente al circuito de órdenes de pago; nunca aparecen
  como tipos de movimiento de mesa de entradas
- `c_movimientos_de_fondos` es el libro único de tesorería: un renglón por comprobante y cuenta
- `c_movimiento_entre_cuentas` es solo entre cuentas propias — no hay tercero involucrado
