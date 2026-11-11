-- =============================================================================
-- fisca_liquidacion_20261111.sql — Liquidación de cuota sindical por período
-- =============================================================================
--
-- Lo que cada empleador tiene que pagar de cuota sindical en un período: una
-- liquidación por CUIT y período (fisca_liquidacion) con un renglón por
-- afiliado (fisca_liquidacion_detalle). La arma Fiscalización de Cuotas →
-- Liquidación de Cuota Sindical (fisca_liquidacion.py):
--
--   - si el empleador cargó la nómina del período (fisca_cuotarecepcion), con
--     la remuneración que declaró;
--   - si no, con sus afiliados y la Remuneración imponible 5 de la DDJJ de
--     OSEDA (f_ddjj_procesada en contable de Railway, en vivo);
--   - cuota = remuneración × alícuota; vence el día fijado del mes siguiente.
--
-- La alícuota (2,50 %) y el día de vencimiento (20) van en Datos del Sindicato
-- (s_institucion). Es lo que hacía AEDA en fis_deuda / fis_deuda_detalle; el
-- historial de AEDA lo trae importar_aeda_fisca_deuda.py (origen «aeda»).
--
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X). Idempotente.
-- El menú se lee al iniciar sesión: salir y volver a entrar.

USE sindicato;
SET NAMES utf8mb4;

-- Parámetros en Datos del Sindicato ------------------------------------------
SET @hay := (SELECT COUNT(*) FROM information_schema.columns
              WHERE table_schema = DATABASE() AND table_name = 's_institucion' AND column_name = 'cuota_alicuota');
SET @sql := IF(@hay = 0,
  'ALTER TABLE s_institucion
     ADD COLUMN cuota_alicuota DECIMAL(5,2) NULL DEFAULT 2.50 COMMENT ''Cuota sindical: % sobre la remuneración'',
     ADD COLUMN cuota_dia_vto TINYINT UNSIGNED NULL DEFAULT 20 COMMENT ''Cuota sindical: día de vencimiento del mes siguiente''',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
UPDATE s_institucion SET cuota_alicuota = 2.50 WHERE cuota_alicuota IS NULL;
UPDATE s_institucion SET cuota_dia_vto = 20 WHERE cuota_dia_vto IS NULL;

-- Liquidaciones ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fisca_liquidacion (
  id            INT NOT NULL AUTO_INCREMENT,
  cuit          VARCHAR(11) NOT NULL,
  periodo       CHAR(6) NOT NULL                COMMENT 'AAAAMM',
  fecha         DATE NOT NULL                   COMMENT 'Fecha de la liquidación',
  vencimiento   DATE NOT NULL,
  alicuota      DECIMAL(5,2) NOT NULL           COMMENT '% con que se calculó',
  afiliados     INT NOT NULL DEFAULT 0,
  remuneracion  DECIMAL(18,2) NOT NULL DEFAULT 0,
  importe       DECIMAL(15,2) NOT NULL DEFAULT 0,
  origen        ENUM('nomina','ddjj','aeda') NOT NULL COMMENT 'De dónde salió la remuneración',
  estado        ENUM('vigente','anulada') NOT NULL DEFAULT 'vigente',
  observaciones VARCHAR(500) NULL,
  id_usuario    INT NULL,
  creado        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actualizado   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_fisca_liq (cuit, periodo),
  KEY ix_fisca_liq_periodo (periodo, estado),
  CONSTRAINT fk_fisca_liq_usuario FOREIGN KEY (id_usuario) REFERENCES s_usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Cuota sindical a pagar por empleador y período';

CREATE TABLE IF NOT EXISTS fisca_liquidacion_detalle (
  id               INT NOT NULL AUTO_INCREMENT,
  id_liquidacion   INT NOT NULL,
  cuil             VARCHAR(11) NOT NULL,
  id_afiliado      INT NULL,
  apellido_nombres VARCHAR(100) NULL,
  remuneracion     DECIMAL(15,2) NOT NULL DEFAULT 0,
  cuota            DECIMAL(15,2) NOT NULL DEFAULT 0,
  fuente           ENUM('nomina','ddjj','aeda') NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_fisca_liq_det (id_liquidacion, cuil),
  KEY ix_fisca_liq_det_cuil (cuil),
  CONSTRAINT fk_fisca_liq_det FOREIGN KEY (id_liquidacion) REFERENCES fisca_liquidacion (id) ON DELETE CASCADE,
  CONSTRAINT fk_fisca_liq_det_afi FOREIGN KEY (id_afiliado) REFERENCES p_afiliados (id_afiliado)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Un renglón por afiliado de la liquidación de cuota sindical';

-- Menú: Fiscalización de Cuotas → Liquidación de Cuota Sindical ---------------
INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (6, 1, 'Liquidación de Cuota Sindical', '/fiscalizacion/liquidacion', NULL, 5, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url),
  padre_id = VALUES(padre_id), orden = VALUES(orden), activo = 1;

INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT 6, r.id FROM s_roles r
 WHERE r.nombre IN ('Administrador', 'Supervisor')
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = 6 AND x.rol_id = r.id);

SELECT m.id, m.nombre, m.url, m.orden FROM s_menu m WHERE m.padre_id = 1 ORDER BY m.orden;
SELECT cuota_alicuota, cuota_dia_vto FROM s_institucion;
