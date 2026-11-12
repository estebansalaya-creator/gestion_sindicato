-- =============================================================================
-- conciliacion_bancaria_20261111.sql — Extractos, clasificación de conceptos
-- y conciliación bancaria
-- =============================================================================
--
-- Pantallas (portadas de gestion_adm, ver CLAUDE.md «Tesorería: extractos y
-- conciliación»):
--
--   71 Extractos Bancarios                /tesoreria/extractos       extractos.py
--   72 Conciliación Bancaria              /tesoreria/conc            conciliacion.py
--   73 Clasificación Conceptos Bancarios  /tesoreria/conc/clasificar conciliacion.py
--
-- Las tablas ya estaban (vinieron con la estructura de contable, vacías). Les
-- falta:
--
--   1. conc_reglas.tipo_resultado 'movimiento_cuentas' y id_cuenta_destino: un
--      concepto del extracto que es plata que pasa a otra cuenta propia (el
--      barrido de la recaudadora a la cuenta corriente). En gestion_adm se
--      agregó después y por eso su código preguntaba si la columna existía.
--   2. conciliacion_comprobantes.id_debito_credito: el lado libro de la
--      conciliación es el instrumento (c_debitos_creditos_bancarios: un
--      renglón por cheque, transferencia o depósito), no el comprobante. Un
--      pago con seis cheques diferidos se debita en seis días distintos y cada
--      cheque se concilia solo. gestion_adm lo resolvía con id_movimiento +
--      id_instrumento; acá el instrumento ya tiene su renglón propio.
--
-- Las opciones de menú 71-73 ya estaban (menu_y_roles_20260826.sql) y daban
-- «pantalla pendiente».
--
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X). Idempotente.

USE sindicato;
SET NAMES utf8mb4;

-- 1. Reglas: movimiento entre cuentas -----------------------------------------
ALTER TABLE conc_reglas
  MODIFY tipo_resultado ENUM('concepto_gasto','motivo_ingreso','movimiento_cuentas','orden_pago','prisma','manual')
         NOT NULL COMMENT 'Qué es el concepto: gasto (OP por concepto), ingreso (OI), pase a otra cuenta propia o se concilia a mano';

SET @hay := (SELECT COUNT(*) FROM information_schema.columns
              WHERE table_schema = DATABASE() AND table_name = 'conc_reglas' AND column_name = 'id_cuenta_destino');
SET @sql := IF(@hay = 0,
  'ALTER TABLE conc_reglas ADD COLUMN id_cuenta_destino INT NULL COMMENT ''movimiento_cuentas: la otra cuenta propia'' AFTER id_motivo_ingreso, ADD KEY fk_regla_cuenta_destino (id_cuenta_destino), ADD CONSTRAINT fk_regla_cuenta_destino FOREIGN KEY (id_cuenta_destino) REFERENCES c_cuentas_de_fondos (id)',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- 2. Vínculo con el instrumento del libro --------------------------------------
SET @hay := (SELECT COUNT(*) FROM information_schema.columns
              WHERE table_schema = DATABASE() AND table_name = 'conciliacion_comprobantes' AND column_name = 'id_debito_credito');
SET @sql := IF(@hay = 0,
  'ALTER TABLE conciliacion_comprobantes ADD COLUMN id_debito_credito INT NULL COMMENT ''c_debitos_creditos_bancarios.id: el instrumento del libro que se concilió'' AFTER id_grupo, ADD UNIQUE KEY uq_cc_debito_credito (id_debito_credito), ADD CONSTRAINT fk_cc_debito_credito FOREIGN KEY (id_debito_credito) REFERENCES c_debitos_creditos_bancarios (id)',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- 3. Desde cuándo se concilia (12/11/2026): lo anterior se da por conciliado ----
INSERT INTO s_configuracion (modulo, tabla, campo, parametro, valor, descripcion)
VALUES ('tesoreria', 'conciliacion_header', 'fecha_desde', 'conc_fecha_corte', '2026-11-01',
        'Desde cuándo se concilia: lo anterior del libro se da por conciliado y no hay conciliaciones de antes (AAAA-MM-DD)')
ON DUPLICATE KEY UPDATE valor = VALUES(valor), descripcion = VALUES(descripcion);

-- Control ----------------------------------------------------------------------
SELECT column_name, column_type FROM information_schema.columns
 WHERE table_schema = DATABASE()
   AND ((table_name = 'conc_reglas' AND column_name IN ('tipo_resultado', 'id_cuenta_destino'))
     OR (table_name = 'conciliacion_comprobantes' AND column_name = 'id_debito_credito'));
SELECT id, nombre, url FROM s_menu WHERE id IN (71, 72, 73);
SELECT parametro, valor FROM s_configuracion WHERE parametro = 'conc_fecha_corte';
