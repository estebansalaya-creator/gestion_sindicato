-- ============================================================================
-- pagos_20261108.sql — Circuito de pagos y menú de Tesorería como gestion_adm
-- ============================================================================
--
--   1. Columnas que gestion_adm agregó después de copiar la estructura:
--        pago_ordenes.nro_origen       el número por el que se conoce la orden
--                                      (en las de AEDA, el N° de pago de AEDA)
--        pago_ordenes.fecha_anulacion, motivo_anulacion, id_usuario_anulacion
--        pago_pagos_instrumentos.id_chequera   de qué chequera salió el cheque
--   2. Las órdenes que vinieron de AEDA (AEDA-OP-<pago_id>) toman como número
--      visible el de su pago, que es el de AEDA.
--   3. Los contadores de c_numeradores a la altura de lo ya numerado.
--   4. El menú de Tesorería igual al de gestion_adm, sin Integración ni
--      Prisma: Panel, Pagos (con Reintegros y Sueldos adentro), Orden de
--      Ingreso, movimientos, Inversiones, Subdiario, Extractos, Conciliación,
--      Clasificación, Anulaciones y Tablas. Desaparecen «Circuito de Pagos»,
--      «Circuito de Ingresos» y «Bancos» como menús aparte. Las opciones que
--      todavía no tienen pantalla dan el aviso de «pantalla pendiente».
--      Para Administrador y Supervisor. Los permisos se leen al iniciar
--      sesión: hay que volver a entrar.
--
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X). Idempotente.

USE sindicato;

-- 1 ─────────────────────────────────────────────────────────────────────────
SET @hay := (SELECT COUNT(*) FROM information_schema.COLUMNS
              WHERE TABLE_SCHEMA = 'sindicato' AND TABLE_NAME = 'pago_ordenes' AND COLUMN_NAME = 'nro_origen');
SET @sql := IF(@hay = 0,
  'ALTER TABLE pago_ordenes ADD COLUMN nro_origen INT NULL COMMENT ''Número por el que se conoce la orden en el sistema de origen (AEDA)'' AFTER nro_orden, ADD INDEX ix_ordenes_nro_origen (nro_origen)',
  'SELECT ''pago_ordenes.nro_origen ya existe''');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

SET @hay := (SELECT COUNT(*) FROM information_schema.COLUMNS
              WHERE TABLE_SCHEMA = 'sindicato' AND TABLE_NAME = 'pago_ordenes' AND COLUMN_NAME = 'fecha_anulacion');
SET @sql := IF(@hay = 0,
  'ALTER TABLE pago_ordenes ADD COLUMN fecha_anulacion DATETIME NULL, ADD COLUMN motivo_anulacion VARCHAR(250) NULL, ADD COLUMN id_usuario_anulacion INT NULL',
  'SELECT ''pago_ordenes.fecha_anulacion ya existe''');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

SET @hay := (SELECT COUNT(*) FROM information_schema.COLUMNS
              WHERE TABLE_SCHEMA = 'sindicato' AND TABLE_NAME = 'pago_pagos_instrumentos' AND COLUMN_NAME = 'id_chequera');
SET @sql := IF(@hay = 0,
  'ALTER TABLE pago_pagos_instrumentos ADD COLUMN id_chequera INT NULL COMMENT ''c_chequeras.id del cheque'', ADD INDEX idx_inst_chequera (id_chequera)',
  'SELECT ''pago_pagos_instrumentos.id_chequera ya existe''');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- 2 ─────────────────────────────────────────────────────────────────────────
UPDATE pago_ordenes o
  JOIN pago_pagos p ON p.id_orden = o.id AND p.nro_pago = REPLACE(o.nro_orden, 'AEDA-OP-', 'AEDA-PG-')
   SET o.nro_origen = p.nro_origen
 WHERE o.nro_orden LIKE 'AEDA-OP-%' AND o.nro_origen IS NULL AND p.nro_origen IS NOT NULL;

-- 3 ─────────────────────────────────────────────────────────────────────────
INSERT INTO c_numeradores (ambito, periodo, ultimo)
SELECT 'pago_ordenes', LEFT(nro_orden, 4), MAX(CAST(SUBSTRING(nro_orden, 6) AS UNSIGNED))
  FROM pago_ordenes WHERE nro_orden REGEXP '^[0-9]{4}-[0-9]{8}$' GROUP BY LEFT(nro_orden, 4)
ON DUPLICATE KEY UPDATE ultimo = GREATEST(ultimo, VALUES(ultimo));
INSERT INTO c_numeradores (ambito, periodo, ultimo)
SELECT 'pago_pagos', LEFT(nro_pago, 4), MAX(CAST(SUBSTRING(nro_pago, 6) AS UNSIGNED))
  FROM pago_pagos WHERE nro_pago REGEXP '^[0-9]{4}-[0-9]{8}$' GROUP BY LEFT(nro_pago, 4)
ON DUPLICATE KEY UPDATE ultimo = GREATEST(ultimo, VALUES(ultimo));

-- 4 ─────────────────────────────────────────────────────────────────────────
-- Fuera «Circuito de Ingresos» (50) como menú: su orden de ingreso y sus
-- inversiones pasan a Tesorería con otros números.
DELETE FROM s_menu_rol     WHERE menu_id IN (50, 51, 52);
DELETE FROM s_menu_usuario WHERE menu_id IN (50, 51, 52);
DELETE FROM s_menu         WHERE id IN (51, 52);
DELETE FROM s_menu         WHERE id = 50;

INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo) VALUES
  -- Tesorería
  (61,  60, 'Panel de Control',                  '/tesoreria',                                    NULL,   1, 2, 1),
  (40,  60, 'Pagos',                             NULL,                                            NULL,   2, 2, 1),
  (56,  60, 'Orden de Ingreso',                  '/tesoreria/nueva_orden_concepto',               NULL,   3, 2, 1),
  (62,  60, 'Movimiento entre Cuentas',          '/tesoreria/movimientos/nuevo/transferencia',    NULL,   4, 2, 1),
  (63,  60, 'Depósitos Bancarios',               '/tesoreria/movimientos/nuevo/deposito',         NULL,   5, 2, 1),
  (64,  60, 'Extracciones',                      '/tesoreria/movimientos/nuevo/extraccion',       NULL,   6, 2, 1),
  (57,  60, 'Inversiones',                       '/tesoreria/inversiones',                        NULL,   7, 2, 1),
  (65,  60, 'Subdiario de Cuentas de Fondos',    '/tesoreria/movimientos',                        NULL,   8, 2, 1),
  (71,  60, 'Extractos Bancarios',               '/tesoreria/extractos',                          NULL, 120, 2, 1),
  (72,  60, 'Conciliación Bancaria',             '/tesoreria/conc',                               NULL, 190, 2, 1),
  (73,  60, 'Clasificación Conceptos Bancarios', '/tesoreria/conc/clasificar',                    NULL, 200, 2, 1),
  (74,  60, 'Anulaciones',                       '/tesoreria/anulaciones',                        NULL, 900, 2, 1),
  (70,  60, 'Tablas',                            NULL,                                            NULL, 990, 2, 1),
  -- Tesorería → Pagos
  (41,  40, 'Órdenes de Pago Proveedores',       '/pagos/ordenes',                                NULL,   1, 3, 1),
  (43,  40, 'Orden de Pago Anticipos',           '/pagos/ordenes/anticipo/nueva',                 NULL,   2, 3, 1),
  (44,  40, 'Orden de Pago por Concepto',        '/pagos/ordenes/concepto/nueva',                 NULL,   3, 3, 1),
  (45,  40, 'Emisión de Pagos',                  '/pagos/emision',                                NULL,   4, 3, 1),
  (42,  40, 'Pagos Emitidos',                    '/pagos/emitidos',                               NULL,   5, 3, 1),
  (46,  40, 'Transferencias Masivas',            '/pagos/transferencias',                         NULL,   6, 3, 1),
  (80,  40, 'Reintegros',                        NULL,                                            NULL, 150, 3, 1),
  (47,  40, 'Certificados de Retención',         '/pagos/certificados',                           NULL, 160, 3, 1),
  (48,  40, 'Imputaciones Contables',            '/pagos/imputaciones',                           NULL, 170, 3, 1),
  (100, 40, 'Sueldos',                           NULL,                                            NULL, 180, 3, 1),
  (49,  40, 'Config. Aprobadores',               '/pagos/config_aprobadores',                     NULL, 990, 3, 1),
  -- Tesorería → Pagos → Reintegros (las pantallas de siempre)
  (81,  80, 'Solicitudes de Reintegro',          '/reintegros/solicitud',                         NULL,   1, 4, 1),
  (82,  80, 'Auditoría de Reintegros',           '/reintegros/auditoria',                         NULL,   2, 4, 1),
  (83,  80, 'Órdenes de Pago de Reintegros',     '/reintegros/ordenes',                           NULL,   3, 4, 1),
  -- Tesorería → Pagos → Sueldos
  (101, 100, 'Nómina de Empleados',              '/pagos/nomina',                                 NULL, 100, 4, 1),
  (102, 100, 'Importar Nómina (Excel)',          '/pagos/nomina/importar',                        NULL, 110, 4, 1),
  (103, 100, 'Imputaciones de Sueldos',          '/pagos/nomina/imputaciones',                    NULL, 120, 4, 1),
  (104, 100, 'Control de Cambios Nómina',        '/pagos/nomina/historial',                       NULL, 130, 4, 1),
  (105, 100, 'Orden de Pago de Sueldos',         '/pagos/ordenes/sueldos/nueva',                  NULL, 140, 4, 1),
  -- Tesorería → Tablas
  (69,  70, 'Motivos de Ingreso',                '/tesoreria/motivos_ingreso',                    NULL, 100, 3, 1),
  (68,  70, 'Conceptos de Gasto',                '/tesoreria/conceptos_gasto',                    NULL, 110, 3, 1),
  (67,  70, 'Códigos de Banco BCRA',             '/tesoreria/bancos',                             NULL, 120, 3, 1),
  (66,  70, 'Cuentas de Fondos',                 '/tesoreria/cuentas_fondos',                     NULL, 130, 3, 1),
  (75,  70, 'Escala RG 830',                     '/tesoreria/rg830',                              NULL, 140, 3, 1)
ON DUPLICATE KEY UPDATE padre_id = VALUES(padre_id), nombre = VALUES(nombre), url = VALUES(url),
  orden = VALUES(orden), nivel = VALUES(nivel), activo = 1;

INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT m.id, r.id
  FROM s_menu m
  JOIN s_roles r ON r.id IN (1, 2)
 WHERE m.id IN (40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 56, 57, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69,
                70, 71, 72, 73, 74, 75, 80, 81, 82, 83, 100, 101, 102, 103, 104, 105)
   AND r.activo = 1
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = m.id AND x.rol_id = r.id);

-- Control
SELECT COUNT(*) AS ordenes_aeda_con_numero FROM pago_ordenes WHERE nro_orden LIKE 'AEDA-OP-%' AND nro_origen IS NOT NULL;
SELECT CONCAT(REPEAT('    ', m.nivel - 1), m.nombre) AS menu, m.id, m.url,
       (SELECT GROUP_CONCAT(r.nombre ORDER BY r.id) FROM s_menu_rol mr JOIN s_roles r ON r.id = mr.rol_id
         WHERE mr.menu_id = m.id) AS roles
  FROM s_menu m
  LEFT JOIN s_menu p ON p.id = m.padre_id
  LEFT JOIN s_menu a ON a.id = p.padre_id
 WHERE 60 IN (m.id, m.padre_id, p.padre_id, a.padre_id)
 ORDER BY m.nivel, m.padre_id, m.orden;
