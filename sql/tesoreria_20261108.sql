-- ============================================================================
-- tesoreria_20261108.sql — Tablas de tesorería: lo que necesitan las pantallas
-- ============================================================================
--
--   1. c_concepto_de_gastos.activo: un concepto que ya se usó no se borra, se
--      desactiva. Los motivos de ingreso ya lo tenían.
--   2. c_cuentas_de_fondos.predeterminada: la cuenta de pago que viene elegida
--      al cargar un instrumento de pago. Como en gestion_adm: a lo sumo una en
--      toda la tabla (índice único sobre IF(predeterminada = 1, 1, NULL)).
--   3. Códigos de banco del BCRA: los bancos de la nómina vigente, con el
--      código de tres dígitos que encabeza el CBU. Fuente: BCRA, Comunicación
--      «A» 8139 (Grupos A, B y C, 02/12/2024), con los cambios de la
--      publicación «Información de Entidades Financieras» de junio de 2026
--      (Wilobank es Ualá Bank; HSBC se fusionó con Galicia: el 150 queda por
--      los CBU viejos). Sin las compañías financieras (códigos de 5 dígitos),
--      que no abren cuentas. Los que ya estaban se actualizan por código.
--   4. Menú, dentro de Tesorería, para Administrador y Supervisor:
--        66 Cuentas de Fondos      /tesoreria/cuentas_fondos
--        67 Bancos (código BCRA)   /tesoreria/bancos
--        68 Conceptos de Gasto     /tesoreria/conceptos_gasto
--        69 Motivos de Ingreso     /tesoreria/motivos_ingreso
--      Los permisos se leen al iniciar sesión: hay que volver a entrar.
--
-- Después de esto: importar_aeda_tesoreria.py (plan de cuentas, conceptos,
-- motivos, cuentas de fondos y chequeras de AEDA).
--
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X). Idempotente.

USE sindicato;

-- 1 ─────────────────────────────────────────────────────────────────────────
SET @hay := (SELECT COUNT(*) FROM information_schema.COLUMNS
              WHERE TABLE_SCHEMA = 'sindicato' AND TABLE_NAME = 'c_concepto_de_gastos'
                AND COLUMN_NAME = 'activo');
SET @sql := IF(@hay = 0,
  'ALTER TABLE c_concepto_de_gastos ADD COLUMN activo TINYINT(1) NOT NULL DEFAULT 1 COMMENT ''0 = no se ofrece; uno usado se desactiva en vez de borrarse'' AFTER es_reintegro',
  'SELECT ''c_concepto_de_gastos.activo ya existe''');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- 2 ─────────────────────────────────────────────────────────────────────────
SET @hay := (SELECT COUNT(*) FROM information_schema.COLUMNS
              WHERE TABLE_SCHEMA = 'sindicato' AND TABLE_NAME = 'c_cuentas_de_fondos'
                AND COLUMN_NAME = 'predeterminada');
SET @sql := IF(@hay = 0,
  'ALTER TABLE c_cuentas_de_fondos ADD COLUMN predeterminada TINYINT(1) NOT NULL DEFAULT 0 COMMENT ''La que viene elegida al cargar un instrumento de pago. Solo con esdepago = 1. A lo sumo una en toda la tabla'' AFTER esdepago',
  'SELECT ''c_cuentas_de_fondos.predeterminada ya existe''');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

SET @hay := (SELECT COUNT(*) FROM information_schema.STATISTICS
              WHERE TABLE_SCHEMA = 'sindicato' AND TABLE_NAME = 'c_cuentas_de_fondos'
                AND INDEX_NAME = 'uq_cuenta_predeterminada');
SET @sql := IF(@hay = 0,
  'ALTER TABLE c_cuentas_de_fondos ADD UNIQUE INDEX uq_cuenta_predeterminada ((IF(predeterminada = 1, 1, NULL)))',
  'SELECT ''uq_cuenta_predeterminada ya existe''');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- 3 ─────────────────────────────────────────────────────────────────────────
INSERT INTO c_codigo_de_banco (codigo, nombre) VALUES
  ('007', 'BANCO DE GALICIA Y BUENOS AIRES S.A.U.'),
  ('011', 'BANCO DE LA NACION ARGENTINA'),
  ('014', 'BANCO DE LA PROVINCIA DE BUENOS AIRES'),
  ('015', 'ICBC - INDUSTRIAL AND COMMERCIAL BANK OF CHINA (ARGENTINA) S.A.U.'),
  ('016', 'CITIBANK N.A.'),
  ('017', 'BANCO BBVA ARGENTINA S.A.'),
  ('020', 'BANCO DE LA PROVINCIA DE CORDOBA S.A.'),
  ('027', 'BANCO SUPERVIELLE S.A.'),
  ('029', 'BANCO DE LA CIUDAD DE BUENOS AIRES'),
  ('034', 'BANCO PATAGONIA S.A.'),
  ('044', 'BANCO HIPOTECARIO S.A.'),
  ('045', 'BANCO DE SAN JUAN S.A.'),
  ('065', 'BANCO MUNICIPAL DE ROSARIO'),
  ('072', 'BANCO SANTANDER ARGENTINA S.A.'),
  ('083', 'BANCO DEL CHUBUT S.A.'),
  ('086', 'BANCO DE SANTA CRUZ S.A.'),
  ('093', 'BANCO DE LA PAMPA SOCIEDAD DE ECONOMIA MIXTA'),
  ('094', 'BANCO DE CORRIENTES S.A.'),
  ('097', 'BANCO PROVINCIA DEL NEUQUEN S.A.'),
  ('131', 'BANK OF CHINA LIMITED, SUCURSAL BUENOS AIRES'),
  ('143', 'BRUBANK S.A.U.'),
  ('147', 'BIBANK S.A.'),
  ('150', 'EX HSBC BANK ARGENTINA (GALICIA MAS, FUSIONADO CON GALICIA)'),
  ('165', 'JPMORGAN CHASE BANK, NATIONAL ASSOCIATION (SUCURSAL BUENOS AIRES)'),
  ('191', 'BANCO CREDICOOP COOPERATIVO LIMITADO'),
  ('198', 'BANCO DE VALORES S.A.'),
  ('247', 'BANCO ROELA S.A.'),
  ('254', 'BANCO MARIVA S.A.'),
  ('266', 'BNP PARIBAS'),
  ('268', 'BANCO PROVINCIA DE TIERRA DEL FUEGO'),
  ('269', 'BANCO DE LA REPUBLICA ORIENTAL DEL URUGUAY'),
  ('277', 'BANCO SAENZ S.A.'),
  ('281', 'BANCO MERIDIAN S.A.'),
  ('285', 'BANCO MACRO S.A.'),
  ('299', 'BANCO COMAFI S.A.'),
  ('300', 'BANCO DE INVERSION Y COMERCIO EXTERIOR S.A. (BICE)'),
  ('301', 'BANCO PIANO S.A.'),
  ('305', 'BANCO JULIO S.A.'),
  ('309', 'BANCO RIOJA S.A.U.'),
  ('310', 'BANCO DEL SOL S.A.'),
  ('311', 'NUEVO BANCO DEL CHACO S.A.'),
  ('312', 'BANCO VOII S.A.'),
  ('315', 'BANCO DE FORMOSA S.A.'),
  ('319', 'BANCO CMF S.A.'),
  ('321', 'BANCO DE SANTIAGO DEL ESTERO S.A.'),
  ('322', 'BANCO INDUSTRIAL S.A.'),
  ('330', 'NUEVO BANCO DE SANTA FE S.A.'),
  ('331', 'BANCO CETELEM ARGENTINA S.A.'),
  ('332', 'BANCO DE SERVICIOS FINANCIEROS S.A. (CARREFOUR)'),
  ('338', 'BANCO DE SERVICIOS Y TRANSACCIONES S.A.U.'),
  ('339', 'RCI BANQUE S.A.'),
  ('340', 'BACS BANCO DE CREDITO Y SECURITIZACION S.A.'),
  ('341', 'BANCO MASVENTAS S.A.'),
  ('384', 'UALA BANK S.A.U. (EX WILOBANK)'),
  ('386', 'NUEVO BANCO DE ENTRE RIOS S.A.'),
  ('389', 'BANCO COLUMBIA S.A.'),
  ('426', 'BANCO BICA S.A.'),
  ('431', 'BANCO COINAG S.A.'),
  ('432', 'BANCO DE COMERCIO S.A.'),
  ('435', 'BANCO SUCREDITO REGIONAL S.A.U.'),
  ('448', 'BANCO DINO S.A.')
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre);

-- 4 ─────────────────────────────────────────────────────────────────────────
INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo) VALUES
  (66, 60, 'Cuentas de Fondos',    '/tesoreria/cuentas_fondos',  NULL, 6, 2, 1),
  (67, 60, 'Bancos (código BCRA)', '/tesoreria/bancos',          NULL, 7, 2, 1),
  (68, 60, 'Conceptos de Gasto',   '/tesoreria/conceptos_gasto', NULL, 8, 2, 1),
  (69, 60, 'Motivos de Ingreso',   '/tesoreria/motivos_ingreso', NULL, 9, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url),
  padre_id = VALUES(padre_id), orden = VALUES(orden), activo = 1;

INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT m.id, r.id
  FROM s_menu m
  JOIN s_roles r ON r.id IN (1, 2)
 WHERE m.id IN (66, 67, 68, 69) AND r.activo = 1
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = m.id AND x.rol_id = r.id);

-- Control
SELECT COUNT(*) AS bancos FROM c_codigo_de_banco;
SELECT m.id, m.nombre, m.url, m.orden, GROUP_CONCAT(r.nombre ORDER BY r.id) AS roles
  FROM s_menu m
  LEFT JOIN s_menu_rol mr ON mr.menu_id = m.id
  LEFT JOIN s_roles r ON r.id = mr.rol_id
 WHERE m.padre_id = 60
 GROUP BY m.id, m.nombre, m.url, m.orden
 ORDER BY m.orden;
