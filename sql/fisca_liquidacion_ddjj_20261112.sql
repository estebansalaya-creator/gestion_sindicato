-- =============================================================================
-- fisca_liquidacion_ddjj_20261112.sql — Liquidación por DDJJ de OSEDA con los
-- afiliados activos del empleador
-- =============================================================================
--
-- Pedido del 12/11/2026: liquidar todos los períodos desde 202401 según la DDJJ
-- de OSEDA, y que cada liquidación (CUIT + período) diga cuántos de los
-- titulares activos del empleador en el período tienen DDJJ, cuántos no, el
-- total y el porcentaje. El detalle lleva a todos los activos, aunque no estén
-- en la DDJJ (renglón «sin_ddjj», en cero).
--
--   fisca_liquidacion
--     afiliados_activos   titulares activos del empleador en el período
--     activos_con_ddjj    de esos, los que están en su DDJJ de OSEDA
--     activos_sin_ddjj    calculada: activos − con DDJJ
--     porc_ddjj           calculada: con DDJJ × 100 / activos (NULL sin activos)
--     aeda_importe, aeda_afiliados, id_aeda
--                         lo que había liquidado AEDA, cuando se reliquida una suya
--   fisca_liquidacion_detalle
--     fuente + 'sin_ddjj' activo del empleador que no figura en su DDJJ
--     activo              1 = el afiliado es activo del empleador en el período
--
-- Requiere sql/fisca_liquidacion_20261111.sql. Correrlo ENTERO: en DBeaver,
-- «Ejecutar script» (Alt+X). Idempotente.

USE sindicato;
SET NAMES utf8mb4;

-- fisca_liquidacion -----------------------------------------------------------
SET @hay := (SELECT COUNT(*) FROM information_schema.columns
              WHERE table_schema = DATABASE() AND table_name = 'fisca_liquidacion' AND column_name = 'afiliados_activos');
SET @sql := IF(@hay = 0,
  'ALTER TABLE fisca_liquidacion
     ADD COLUMN afiliados_activos INT NOT NULL DEFAULT 0 COMMENT ''Titulares activos del empleador en el período'' AFTER afiliados,
     ADD COLUMN activos_con_ddjj INT NOT NULL DEFAULT 0 COMMENT ''De los activos, los que están en su DDJJ de OSEDA'' AFTER afiliados_activos,
     ADD COLUMN aeda_importe DECIMAL(15,2) NULL COMMENT ''Lo que liquidó AEDA (fis_deuda), si se reliquidó una suya'' AFTER importe,
     ADD COLUMN aeda_afiliados INT NULL COMMENT ''Afiliados de la liquidación de AEDA'' AFTER aeda_importe,
     ADD COLUMN id_aeda INT NULL COMMENT ''fis_deuda.deuda_id de AEDA'' AFTER aeda_afiliados',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- Las dos calculadas, aparte: se apoyan en las columnas que agrega el paso anterior.
SET @hay := (SELECT COUNT(*) FROM information_schema.columns
              WHERE table_schema = DATABASE() AND table_name = 'fisca_liquidacion' AND column_name = 'porc_ddjj');
SET @sql := IF(@hay = 0,
  'ALTER TABLE fisca_liquidacion
     ADD COLUMN activos_sin_ddjj INT AS (afiliados_activos - activos_con_ddjj) STORED
         COMMENT ''Activos que no están en su DDJJ'' AFTER activos_con_ddjj,
     ADD COLUMN porc_ddjj DECIMAL(5,2) AS (IF(afiliados_activos > 0, ROUND(activos_con_ddjj * 100 / afiliados_activos, 2), NULL)) STORED
         COMMENT ''% de los activos con DDJJ'' AFTER activos_sin_ddjj',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- fisca_liquidacion_detalle ---------------------------------------------------
ALTER TABLE fisca_liquidacion_detalle
  MODIFY COLUMN fuente ENUM('nomina','ddjj','aeda','sin_ddjj') NOT NULL;

SET @hay := (SELECT COUNT(*) FROM information_schema.columns
              WHERE table_schema = DATABASE() AND table_name = 'fisca_liquidacion_detalle' AND column_name = 'activo');
SET @sql := IF(@hay = 0,
  'ALTER TABLE fisca_liquidacion_detalle
     ADD COLUMN activo TINYINT(1) NOT NULL DEFAULT 0 COMMENT ''1 = activo del empleador en el período (relación laboral)'' AFTER fuente',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- Verificación ----------------------------------------------------------------
SELECT column_name, column_type, generation_expression
  FROM information_schema.columns
 WHERE table_schema = DATABASE() AND table_name IN ('fisca_liquidacion', 'fisca_liquidacion_detalle')
   AND column_name IN ('afiliados_activos', 'activos_con_ddjj', 'activos_sin_ddjj', 'porc_ddjj',
                       'aeda_importe', 'aeda_afiliados', 'id_aeda', 'fuente', 'activo')
 ORDER BY table_name, ordinal_position;
