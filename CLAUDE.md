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
  fisca_liquidacion.py    liquidación de cuota sindical por período: nómina o DDJJ de OSEDA × alícuota
  empleadores.py          ABM de empleadores (p_empresas)
  afiliados.py            ABM del padrón (p_afiliados): grupo familiar, empleadores, documentación, baja lógica, auditoría
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
  extractos.py            Extractos Bancarios: importar (BNA, ICBC), ver, borrar un renglón suelto
  extractos_bancarios.py  los parsers de los extractos y el control de cuenta (de gestion_adm)
  conciliacion.py         Conciliación Bancaria (extracto contra libro) y Clasificación de conceptos
  transferencias.py       transferencias masivas: elegir pagos, generar el archivo, lotes generados
  transferencias_lote.py  a quién y a qué CBU se transfiere; registro, exclusión y anulación de lotes
  transferencias_formatos.py  los archivos del home banking: BNA24, BNA Empresa, ICBC (Excel)
  contabilidad.py         módulo de contabilidad: por ahora el ABM del plan de cuentas
  pagos.py                circuito de pagos: órdenes, aprobación, emisión, anulación, certificados, ABM de config
  pagos_datos.py          capa de datos de pagos: armar órdenes, niveles de aprobación, ejecutar el pago
  pagos_pdf.py            PDF de la orden de pago y del certificado de retención
  retenciones.py          motor de retenciones de gestion_adm sobre s_institucion (Ganancias RG 830, IVA, IIBB, SUSS)
  numeracion.py           números AAMM-######## y certificados CRT-AAAA-NNNNNN (c_numeradores)
  movimientos_fondos.py   libro de fondos (c_movimientos_de_fondos), copia de gestion_adm
  anulaciones.py          reglas para anular: período cerrado, conciliado, ya transferido
  pago_anulacion.py       anular un pago y anular una orden (deshace lo que grabó cada uno)
  plan_cuentas.py         reglas del plan (el código manda): las usan la pantalla y los importadores
  lector_comprobante.py   el parser del PDF de gestion_adm + Mis Comprobantes si no alcanza
  lector_pdf_ocr.py       texto del PDF, OCR de escaneos, cotejo PDF ↔ datos (de gestion_adm)
  arca_wscdc.py           constatación con ARCA (WSAA + WSCDC), certificado propio y opcional
  exportar.py             POST /exportar/excel — el .xlsx de cualquier grilla
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
  contable_oseda.py       lectura en vivo (solo lectura) de las DDJJ de OSEDA en contable de Railway
  cruce_nomina_ddjj.py    qué empleadores tienen toda su nómina de AEDA en la DDJJ de OSEDA (planillas en logs/)
  cruce_atributo_aeda.py  si los titulares activos de AEDA tienen la marca «AEDA» en el padrón de OSEDA (logs/)
  adjuntos/               comprobantes de reintegros y el logo (SIND_ADJUNTOS); NO va al repositorio
  .env                    variables del entorno — NO va al repositorio
  .env.example            plantilla versionada
  .gitignore  .gitattributes  subir_github.bat   repositorio propio (ver «Repositorio»)
  sql/                    scripts de esquema y permisos, se corren a mano
  static/css/sindicato.css    LA hoja de estilos: no hay otra
  templates/
    base.html             estructura, menú, JS común (grillas, solapas, diálogos)
    _ui.html              macros de interfaz: íconos, acciones, filtros, mensajes, estados
    _contactos.html       bloque de contactos, el mismo en todas las pantallas
    estilos.html          guía visual (/estilos)
    login.html  404.html
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
/fiscalizacion/liquidacion   liquidación de cuota sindical, ?periodo=AAAAMM; /generar POST; /<id> ficha
/login /logout /menu
/empleadores         ABM, ?edit=ID
/afiliados/padron    consulta del padrón (solo lectura), ?ver=ID
/afiliados           ABM, ?edit=ID, ?nuevo=1, ?familiar_de=CUIL (alta de familiar con grupo y domicilio)
                     listado: ?q, ?estado=activo|baja|todos, ?tipo, ?sexo, ?edad_desde, ?edad_hasta, ?atributo,
                     ?orden, ?dir, ?tam, ?pagina (lo mismo en /afiliados/padron); /afiliados/exportar (.xlsx)
/afiliados/empleador razón social de un CUIT (ayuda del formulario)
/afiliados/metricas  tablero; ?estado=todos, ?personas=titulares, ?desde=&hasta=, ?control=<clave>
/contactos/<tipo>/<id>  POST alta/edición/baja de contacto (tipo: empresa | afiliado | proveedor)
/reintegros/solicitud   listado y carga, ?edit=ID, ?nuevo=1; /<id> ficha, /<id>/pdf constancia
/reintegros/auditoria   bandeja; /<id> auditar, /<id>/resolver POST
/reintegros/ordenes     reintegros con saldo → órdenes de pago; /generar POST
/admin/institucion      datos del sindicato; /logo sirve el logo
/admin/usuarios         ABM, ?edit=ID, ?nuevo=1        /admin/roles   ?edit=ID (fijos: no se crean ni se borran)
/admin/permisos         ?usuario=ID (opciones sueltas)  /admin/menu    ?edit=ID, ?nuevo=1, ?padre=ID
/admin/areas            ?edit=ID, ?nuevo=1, ?padre=ID   /admin/areas_usuario  ?usuario=ID
/admin/talonarios       ?solapa=talonarios|clasificaciones|tipos, ?edit=ID, ?edit_clasif=ID, ?edit_tipo=ID, ?nuevo=1;
                        /api/clasificacion y /api/tipo POST (JSON): los formularios satélite
/proveedores         ABM, ?edit=ID, ?nuevo=1, ?solapa=cuentas|contactos|movimientos
/proveedores/<id>/cuenta/<pasivo|gasto>  POST alta/baja de cuenta contable
/proveedores/<id>/mesa   POST área y usuario destino de sus expedientes (solapa Mesa de entradas)
/proveedores/api/cuit/<cuit>  ¿válido y libre? (aviso mientras se tipea); /api/buscar
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
/tesoreria/rg830            escala RG 830; ?edit=ID, ?nuevo=1, ?clonar=ID (nueva vigencia)
/tesoreria/extractos        extracto de una cuenta: ?cuenta, ?desde, ?hasta; /importar POST; /<id>/borrar POST
/tesoreria/conc             conciliaciones: ?cuenta, ?cerradas=1; /nueva POST; /saldo_inicial (JSON)
/tesoreria/conc/<id>        detalle (?anteriores=1); /vincular, /sugeridos, /desvincular, /excepcion,
                            /excepcion/quitar, /generar, /saldo_inicial, /cerrar, /reabrir, /eliminar POST
/tesoreria/conc/clasificar  conceptos del extracto: ?cuenta, ?desde, ?hasta; /guardar, /quitar POST (JSON)
/contabilidad/plan          plan de cuentas, ?edit=ID, ?nuevo=1, ?madre=ID (subcuenta con el código sugerido)
/contabilidad/plan/codigo   qué dice un código mientras se tipea (JSON: clase, tipo, nivel, madre, errores)
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
/estilos             guía visual del sistema
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

- **Menú**: `s_menu` y `s_roles` se cargan con `sql/menu_y_roles_20260826.sql` y se administran desde
  Administración del Sistema → Menú. Las opciones sin pantalla dan el 404 de «pantalla pendiente», no
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
[SIND_ARCA_CERT  SIND_ARCA_KEY  SIND_ARCA_CUIT]   constatación con ARCA (opcional)
[SIND_TESSERACT_CMD]                              OCR de PDF escaneados (opcional)
[SIND_CONTABLE_HOST  _PORT  _USER  _PASS  _DB]    contable en Railway, solo lectura (contable_oseda.py)
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
- **Baja lógica, nunca DELETE**: fecha y motivo (`p_motivo_movimiento`, `es_alta = 0`). La de un
  titular ofrece arrastrar a su grupo. De `p_afiliados` cuelgan por FK reintegros y comprobantes.
- **Auditoría**: todo cambio deja una fila por campo en `p_afiliados_movimientos` (valores legibles:
  «3 · Hijo soltero…», no «3»). Si un campo se agrega a `CAMPOS` de `afiliados.py`, queda auditado;
  si se agrega al formulario y no ahí, se guarda sin rastro.
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
  `s_menu_rol`; los permisos se leen al iniciar sesión.
- **Cambio de CUIL de un titular**: arrastra el `cuil_titular` de su grupo y el `cuil` de
  `p_relaciones_laborales`, que lo referencian por CUIL y no por id.
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
- **Tablas auxiliares** («Tablas Auxiliares», menú 24, `sql/afiliados_tablas_20261110.sql`, roles
  Administrador y Supervisor): estado civil, nacionalidades, parentescos, provincias, tipos de
  documento, motivos de alta y baja, atributos y tipos de documentación (solo los del afiliado). Las
  de «Tablas Auxiliares Padrón SSS» de gestion_adm **sin situación de revista** (pedido del
  10/11/2026) y sin tipo de beneficiario, que el padrón del gremio no tiene. Se declaran en `TABLAS`
  de `afiliados_tablas.py`: el código de las tablas SSS lo pone quien carga y no se cambia después;
  lo que se usa no se borra (se desactiva si la tabla tiene `activo`); el parentesco 0 y el DU no se
  borran.

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
Cuotas, Administrador y Supervisor; `sql/fisca_liquidacion_20261111.sql`). Lo que cada empleador tiene que pagar por
período: `fisca_liquidacion` (una por CUIT y período, `uq_fisca_liq`) + `fisca_liquidacion_detalle` (un renglón por
afiliado). Es lo que AEDA hacía en `fis_deuda` / `fis_deuda_detalle` (202401-202602).

- **Remuneración (decidido el 11/11/2026)**: la nómina del empleador si la cargó para el período
  (`fisca_cuotarecepcion`, origen «nomina»); si no, sus afiliados titulares con la Remuneración imponible 5 de la
  DDJJ de OSEDA de ese período (`contable_oseda.ddjj_del_periodo`, en vivo, de a 500 CUIL; origen «ddjj»). La
  nómina manda: con nómina no se mira la DDJJ del empleador. AEDA solo usaba la DDJJ, así que solo veía a los
  afiliados con OSEDA (≈318 por mes contra ≈1.370 de las nóminas).
- **Cuota** = remuneración × `s_institucion.cuota_alicuota` (2,50 %), al centavo por renglón; vence el día
  `cuota_dia_vto` (20) del mes siguiente. Los dos se editan en Datos del Sindicato (bloque «Cuota sindical»).
- **Liquidar de nuevo** el mismo período rehace el detalle de cada empleador con lo de hoy y anula, con la nota, la
  de un empleador que se quedó sin base. Lo de AEDA no se toca. Con Railway caído se liquida lo que tiene nómina y
  no se anula ninguna de origen DDJJ (no saber no es no tener). Un período que no empezó no se liquida.
- **Historial de AEDA**: `importar_aeda_fisca_deuda.py`, tal cual lo emitió (importe, remuneración, fecha y
  vencimiento), marca `[AEDA fis_deuda N]`, origen «aeda». No pisa un empleador y período ya liquidado acá.
  **Sin cobros** (decidido el 11/11/2026): `fis_deudaaplic` está vacía y `fis_cobros` no se aplica a la deuda.
- **Falta**: aplicar los cobros (recaudación) para tener saldo por empleador e intereses por mora.

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
- **Marca AEDA en OSEDA** (`cruce_atributo_aeda.py`, pedido del 11/11/2026, no escribe nada): los titulares del
  padrón contra `p_afiliados` de contable y su atributo «AEDA — Afiliado al Gremio» (`p_atributos_por_afiliado`, por
  rótulo). Resultado por CUIL: correcto, falta la marca, de baja en OSEDA, familiar en OSEDA, no está en OSEDA, y
  sobra la marca (baja en AEDA, no está en AEDA, puesta a un familiar). La marca se corrige en gestion_adm: deja
  la lista de CUIL sin marca en `logs/`.

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
- **Permisos = roles + sueltos** (`db.roles_y_menu`, que antes era `_roles_y_menu` de app.py). Permisos
  por Usuario solo agrega (`s_menu_usuario`); lo que da un rol se ve tildado y no se toca. En gestion_adm
  esa pantalla copiaba lo del rol y después un cambio en el rol no le llegaba a nadie.
- **Ramas**: tildar una opción tilda su rama, en pantalla y en el servidor (`_con_ancestros`): el menú
  lateral descarta una opción cuya rama no está permitida.
- **Los permisos se leen al iniciar sesión**: un cambio rige desde el próximo ingreso. El de quien hace
  el cambio se refresca en el momento (`_refrescar_sesion`).
- **Roles fijos**: el nombre es la clave del código (`tiene_rol`); se editan descripción, estado y
  opciones. `db_usuario` se ve y no se cambia (necesita la variable `SIND_DB_PASS_<USUARIO>`).
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
- **Usado** = `ultimo_emitido` dentro del rango o filas en `c_comprobantes_emitidos`. Uno usado no se elimina
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
  token a la segunda app. Se guarda en `SIND_ADJUNTOS/arca/ta_wscdc.json` porque IIS corre varios
  procesos. Sin configurar, todo entra «sin constatar»; rechazado ('R') no entra; ARCA caído ('E')
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
  pagos no anulados de clase proveedor, anticipo o reintegro (`transferencias_lote.CLASES`: lo que entra, no
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

Menú Contabilidad (90): Plan de Cuentas (91) en `contabilidad.py`; Ejercicios, Asientos, Libro Diario y
Libro Mayor (92-95) están en el menú y todavía no tienen pantalla. Portado de `gestion_adm/contable.py`
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
- `c_ejercicios` apunta a `p_empresas`: hay que identificar el registro del sindicato antes de abrir
  el primer ejercicio contable

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
- **Estados con texto**: `ui.estado(texto, tipo)`, `ui.activo(activo, fecha_baja)`, `ui.si_no(v)`.
  Una fila dada de baja lleva `.fila-baja`.
- **Formularios**: `.bloque` > `.campos` (grilla de 12) > `.campo style="--span:N"`; ayuda en
  `.campo-ayuda` (`.ok` / `.error`); casillas con `label.campo-check`; pie `.form-acciones`. Selects de
  catálogo con `ui.opciones(items, valor)`: si el valor guardado no está en el catálogo lo agrega en
  vez de dejar que el navegador elija la primera opción y lo cambie al guardar.
- **Mensajes**: `ui.mensajes(errores)` (flash en verde; un flash que empieza con «!» sale como
  advertencia) y `ui.aviso(texto, tipo)`.
- **Solapas**: `ui.solapas([(panel, texto, conteo)], inicial)` + `.abm-panel` + `abmSolapa()`.
  **Diálogos**: `.modal` > `.modal-caja`, `abrirModal(id)` / `cerrarModal(id)`.
- La edición carga por `?edit=ID`, nunca poblando el formulario desde JavaScript.
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
