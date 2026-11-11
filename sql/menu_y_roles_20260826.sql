-- Menú, roles y permisos del sindicato — 26/08/2026
--
-- Carga `s_roles`, `s_menu` y `s_menu_rol`, que estaban vacías. Es idempotente:
-- se puede correr de nuevo sin duplicar nada (ON DUPLICATE KEY UPDATE, la
-- convención del proyecto).
--
-- QUÉ ESTRUCTURA CARGA
-- Las ramas siguen los módulos que ya existen en la base, no las pantallas que
-- están hechas. Hoy solo Fiscalización tiene código detrás; el resto son
-- destinos previstos. Es a propósito: el menú vale también como hoja de ruta, y
-- que una opción aparezca antes que su pantalla obliga a decidir la URL una vez
-- sola, cuando se diseña, y no cada vez que se agrega algo.
--
-- Las opciones sin pantalla dan 404. `app.py` intercepta ese caso y muestra
-- «esta pantalla todavía no está hecha» en lugar del 404 de IIS, así se
-- distingue de una URL rota de verdad.
--
-- LOS ROLES SON LOS DE gestion_adm, PERO SIN db_usuario
-- Mismos tres nombres y mismas prioridades, para que quien conoce una app
-- entienda la otra. Pero `db_usuario` va en NULL: en `contable` esos roles
-- conectan como app_admin / app_supervisor / app_operador, usuarios de MySQL
-- que en `sindicato` no existen. Si se copiaran los nombres, `db.py` buscaría
-- SIND_DB_PASS_APP_ADMIN, no la encontraría y el login cortaría con un error
-- de configuración. En NULL, todos conectan con el usuario de la aplicación,
-- que es el camino ya documentado en db.py.
--
-- Los roles externos de `contable` (Afiliado, Proveedor/Prestador) no se
-- cargan: son para autogestión web, que acá no está en alcance.

-- ── Roles ────────────────────────────────────────────────────────────────────
INSERT INTO s_roles (id, nombre, descripcion, activo, db_usuario, prioridad) VALUES
  (1, 'Administrador', 'Acceso total al sistema',        1, NULL, 100),
  (2, 'Supervisor',    'Consultas y reportes',           1, NULL,  50),
  (3, 'Operador',      'Acceso operativo básico',        1, NULL,  10)
ON DUPLICATE KEY UPDATE
  nombre = VALUES(nombre), descripcion = VALUES(descripcion),
  activo = VALUES(activo), prioridad = VALUES(prioridad),
  -- `db_usuario` TIENE que estar en esta lista. La tabla no estaba vacía: los
  -- cinco roles vinieron copiados de `contable` con sus usuarios de MySQL
  -- puestos, y la primera versión de este script no listaba la columna, así
  -- que los INSERT se convirtieron en UPDATE y `app_admin` quedó igual. El
  -- script parecía haber funcionado —los nombres y prioridades sí cambiaron—
  -- pero dejaba apuntando a usuarios que en esta base no existen.
  db_usuario = VALUES(db_usuario);

-- Los roles externos heredados de `contable` (Afiliado, Proveedor/Prestador)
-- quedan como estaban: inactivos y sin opciones de menú. No se borran porque
-- no molestan y puede que la autogestión se retome; que estén en `activo = 0`
-- alcanza para que no aparezcan en ningún lado.
UPDATE s_roles SET db_usuario = NULL WHERE id IN (4, 5);

-- ── Menú ─────────────────────────────────────────────────────────────────────
-- Los ids son fijos y con huecos entre ramas: así `padre_id` se puede escribir
-- a mano acá y quedan números libres para insertar opciones nuevas sin
-- renumerar. El `orden` es dentro de cada padre.
--
-- Los íconos van solo en las ramas de nivel 1, que es donde se ven. El template
-- los omite si vienen en NULL.

INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo) VALUES

-- Fiscalización de cuotas — lo único que hoy tiene pantallas
  (  1, NULL, 'Fiscalización de Cuotas', NULL, '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>', 1, 1, 1),
  (  2,    1, 'Panel de Fiscalización',    '/dashboard',          NULL,  1, 2, 1),
  (  3,    1, 'Importar Cuotas',           '/importar_cuotas',    NULL,  2, 2, 1),
  (  4,    1, 'Historial de Importaciones','/importaciones_log',  NULL,  3, 2, 1),
  (  5,    1, 'Consulta de Cuotas',        '/cuotas',             NULL,  4, 2, 1),

-- Empleadores
  ( 10, NULL, 'Empleadores', NULL, '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 21h18M5 21V7l7-4 7 4v14"/><path d="M9 21v-6h6v6"/></svg>', 2, 1, 1),
  ( 11,   10, 'ABM de Empleadores',        '/empleadores',        NULL,  1, 2, 1),
  ( 12,   10, 'Cuenta Corriente',          '/empleadores/cc',     NULL,  2, 2, 1),

-- Padrón de afiliados
  ( 20, NULL, 'Padrón de Afiliados', NULL, '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/></svg>', 3, 1, 1),
  ( 21,   20, 'ABM de Afiliados',          '/afiliados',          NULL,  1, 2, 1),
  ( 22,   20, 'Métricas del Padrón',       '/afiliados/metricas', NULL,  2, 2, 1),

-- Proveedores y pasivo
  ( 30, NULL, 'Proveedores', NULL, '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 3h5v5"/><path d="M8 3H3v5"/><path d="M3 16v5h5"/><path d="M21 16v5h-5"/><rect x="8" y="8" width="8" height="8" rx="1"/></svg>', 4, 1, 1),
  ( 31,   30, 'ABM de Proveedores',        '/proveedores',        NULL,  1, 2, 1),
  ( 32,   30, 'Carga de Comprobantes',     '/proveedores/comprobantes', NULL, 2, 2, 1),
  ( 33,   30, 'Cuenta Corriente',          '/proveedores/cc',     NULL,  3, 2, 1),

-- Circuito de pagos
  ( 40, NULL, 'Circuito de Pagos', NULL, '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/></svg>', 5, 1, 1),
  ( 41,   40, 'Órdenes de Pago',           '/pagos/ordenes',      NULL,  1, 2, 1),
  ( 42,   40, 'Pagos Efectuados',          '/pagos',              NULL,  2, 2, 1),

-- Circuito de ingresos
  ( 50, NULL, 'Circuito de Ingresos', NULL, '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 19V5"/><path d="M5 12l7-7 7 7"/></svg>', 6, 1, 1),
  ( 51,   50, 'Órdenes de Ingreso',        '/ingresos/ordenes',   NULL,  1, 2, 1),
  ( 52,   50, 'Ingresos Registrados',      '/ingresos',           NULL,  2, 2, 1),

-- Fondos y tesorería
  ( 60, NULL, 'Tesorería', NULL, '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v10M9.5 9.5h5M9.5 14.5h5"/></svg>', 7, 1, 1),
  ( 61,   60, 'Panel de Tesorería',        '/tesoreria',          NULL,  1, 2, 1),
  ( 62,   60, 'Movimiento entre Cuentas',  '/tesoreria/transferencias', NULL, 2, 2, 1),
  ( 63,   60, 'Depósitos Bancarios',       '/tesoreria/depositos', NULL, 3, 2, 1),
  ( 64,   60, 'Extracciones',              '/tesoreria/extracciones', NULL, 4, 2, 1),
  ( 65,   60, 'Subdiario de Fondos',       '/tesoreria/movimientos', NULL, 5, 2, 1),

-- Bancos y conciliación
  ( 70, NULL, 'Bancos', NULL, '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 21h18M3 10h18L12 3 3 10z"/><path d="M6 10v11M18 10v11M12 10v11"/></svg>', 8, 1, 1),
  ( 71,   70, 'Extractos Bancarios',       '/bancos/extractos',   NULL,  1, 2, 1),
  ( 72,   70, 'Conciliación Bancaria',     '/bancos/conciliacion', NULL, 2, 2, 1),

-- Reintegros
  ( 80, NULL, 'Reintegros', NULL, '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 3v6h6"/></svg>', 9, 1, 1),
  ( 81,   80, 'Solicitudes de Reintegro',  '/reintegros',         NULL,  1, 2, 1),

-- Contabilidad
  ( 90, NULL, 'Contabilidad', NULL, '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 3h16v18H4z"/><path d="M8 7h8M8 11h8M8 15h5"/></svg>', 10, 1, 1),
  ( 91,   90, 'Plan de Cuentas',           '/contabilidad/plan',  NULL,  1, 2, 1),
  ( 92,   90, 'Ejercicios',                '/contabilidad/ejercicios', NULL, 2, 2, 1),
  ( 93,   90, 'Asientos',                  '/contabilidad/asientos', NULL, 3, 2, 1),
  ( 94,   90, 'Libro Diario',              '/contabilidad/diario', NULL, 4, 2, 1),
  ( 95,   90, 'Libro Mayor',               '/contabilidad/mayor', NULL,  5, 2, 1),

-- Administración del sistema — orden 200 para que quede último, como en gestion_adm
  (200, NULL, 'Administración del Sistema', NULL, '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>', 200, 1, 1),
  (201,  200, 'Usuarios',                  '/admin/usuarios',     NULL,  1, 2, 1),
  (202,  200, 'Roles',                     '/admin/roles',        NULL,  2, 2, 1),
  (203,  200, 'Permisos por Usuario',      '/admin/permisos',     NULL,  3, 2, 1),
  (204,  200, 'Menú',                      '/admin/menu',         NULL,  4, 2, 1),
  (205,  200, 'Áreas',                     '/admin/areas',        NULL,  5, 2, 1)

ON DUPLICATE KEY UPDATE
  padre_id = VALUES(padre_id), nombre = VALUES(nombre), url = VALUES(url),
  icono_svg = VALUES(icono_svg), orden = VALUES(orden),
  nivel = VALUES(nivel), activo = VALUES(activo);

-- ── Permisos por rol ─────────────────────────────────────────────────────────
-- IMPORTANTE: las ramas de nivel 1 también van en esta tabla. El armador del
-- árbol descarta el hijo cuyo padre no está en la lista de ids permitidos —no
-- lo promueve a raíz—, así que un rol que tenga «Importar Cuotas» sin tener
-- «Fiscalización de Cuotas» no ve nada. No es un descuido del armador: un hijo
-- suelto en la raíz del menú se ve como si fuera un módulo entero.

-- Administrador: todo.
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT m.id, 1 FROM s_menu m
ON DUPLICATE KEY UPDATE menu_id = VALUES(menu_id);

-- Supervisor: todo menos la administración del sistema.
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT m.id, 2 FROM s_menu m
WHERE m.id <> 200 AND (m.padre_id IS NULL OR m.padre_id <> 200)
ON DUPLICATE KEY UPDATE menu_id = VALUES(menu_id);

-- Operador: fiscalización completa, y de los demás módulos solo lo de consulta.
-- Sin tesorería, sin contabilidad y sin pagos: ahí es donde se mueve plata.
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT m.id, 3 FROM s_menu m
WHERE m.id IN (1,2,3,4,5,        -- Fiscalización
               10,11,12,         -- Empleadores
               20,21,22,         -- Padrón
               30,31,33)         -- Proveedores: ABM y cuenta corriente, no la carga
ON DUPLICATE KEY UPDATE menu_id = VALUES(menu_id);

-- ── Verificación ─────────────────────────────────────────────────────────────
SELECT r.nombre AS rol, COUNT(*) AS opciones
FROM s_menu_rol mr JOIN s_roles r ON r.id = mr.rol_id
GROUP BY r.nombre ORDER BY MIN(r.prioridad) DESC;

-- Ningún hijo puede quedar sin su padre en el mismo rol: si esto devuelve
-- filas, ese rol tiene opciones que nunca se van a dibujar.
SELECT r.nombre AS rol, m.id, m.nombre AS opcion_huerfana
FROM s_menu_rol mr
JOIN s_menu m  ON m.id = mr.menu_id
JOIN s_roles r ON r.id = mr.rol_id
WHERE m.padre_id IS NOT NULL
  AND m.padre_id NOT IN (SELECT menu_id FROM s_menu_rol WHERE rol_id = mr.rol_id);
