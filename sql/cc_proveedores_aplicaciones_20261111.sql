-- =============================================================================
-- cc_proveedores_aplicaciones_20261111.sql — Cuenta corriente de proveedores
-- y aplicación de comprobantes
-- =============================================================================
--
-- Pantallas de cc_proveedores.py (portadas de gestion_adm/cc_proveedores_routes.py):
--
--   Proveedores → Cuenta Corriente (33, /proveedores/cc)       ya estaba en el menú
--   Proveedores → Aplicación de Comprobantes (36, nueva)       /proveedores/cc/aplicaciones
--
-- Aplicar = cancelar una factura con una nota de crédito o con un pago que
-- tiene saldo a cuenta, sin mover fondos (c_pasivo_aplicacion, origen
-- «manual»). Desaplicar la borra o le baja el importe; el rastro (cómo estaba,
-- cuánto se soltó, quién y por qué) queda en c_pasivo_aplicacion_baja, la
-- misma tabla de gestion_adm (sql/c_pasivo_aplicacion_baja_20261030.sql).
--
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X). Idempotente.
-- El menú se lee al iniciar sesión: salir y volver a entrar.

USE sindicato;
SET NAMES utf8mb4;

-- Rastro de lo desaplicado ----------------------------------------------------
CREATE TABLE IF NOT EXISTS c_pasivo_aplicacion_baja (
  id                     INT NOT NULL AUTO_INCREMENT,
  id_aplicacion          INT NOT NULL            COMMENT 'c_pasivo_aplicacion.id (ya puede no existir)',
  id_liq_credito         INT NULL                COMMENT 'Nota de crédito aplicada',
  id_pago                INT NULL                COMMENT 'Pago aplicado',
  id_liq_debito          INT NOT NULL            COMMENT 'Factura a la que estaba aplicada',
  importe_aplicado       DECIMAL(18,2) NOT NULL  COMMENT 'Lo aplicado antes de desaplicar',
  importe_desaplicado    DECIMAL(18,2) NOT NULL,
  total                  TINYINT(1) NOT NULL     COMMENT '1 = se borró la aplicación entera',
  fecha_aplicacion       DATE NULL,
  origen                 VARCHAR(20) NULL        COMMENT 'manual | pago | migracion',
  observaciones          VARCHAR(255) NULL       COMMENT 'Las de la aplicación',
  id_usuario_aplicacion  INT NULL                COMMENT 'Quién había aplicado',
  motivo                 VARCHAR(255) NOT NULL,
  id_usuario             INT NULL                COMMENT 'Quién desaplicó',
  creado                 DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_pab_debito (id_liq_debito),
  KEY ix_pab_credito (id_liq_credito),
  KEY ix_pab_pago (id_pago),
  CONSTRAINT fk_pab_usuario FOREIGN KEY (id_usuario) REFERENCES s_usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Aplicaciones de pasivo desaplicadas: quién, cuándo, cuánto y por qué';

-- La aplicación acumula: aplicar dos veces el mismo par suma sobre el mismo
-- renglón (ON DUPLICATE KEY). Las dos claves ya vinieron de contable; se
-- crean si faltan.
SET @hay := (SELECT COUNT(*) FROM information_schema.statistics
              WHERE table_schema = DATABASE() AND table_name = 'c_pasivo_aplicacion' AND index_name = 'uq_pasivo_aplic');
SET @sql := IF(@hay = 0, 'ALTER TABLE c_pasivo_aplicacion ADD UNIQUE KEY uq_pasivo_aplic (id_liq_credito, id_liq_debito)', 'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
SET @hay := (SELECT COUNT(*) FROM information_schema.statistics
              WHERE table_schema = DATABASE() AND table_name = 'c_pasivo_aplicacion' AND index_name = 'uq_pa_pago_debito');
SET @sql := IF(@hay = 0, 'ALTER TABLE c_pasivo_aplicacion ADD UNIQUE KEY uq_pa_pago_debito (id_pago, id_liq_debito)', 'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- Menú: Proveedores → Aplicación de Comprobantes ------------------------------
INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (36, 30, 'Aplicación de Comprobantes', '/proveedores/cc/aplicaciones', NULL, 6, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url),
  padre_id = VALUES(padre_id), orden = VALUES(orden), activo = 1;

INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT 36, r.id FROM s_roles r
 WHERE r.nombre IN ('Administrador', 'Supervisor')
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = 36 AND x.rol_id = r.id);

SELECT m.id, m.nombre, m.url, m.orden FROM s_menu m WHERE m.padre_id = 30 ORDER BY m.orden;
