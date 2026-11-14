-- =============================================================================
-- fisca_escalas_20261114.sql — Escalas salariales del convenio (de AEDA)
-- =============================================================================
--
-- El sueldo básico por antigüedad (0 a 35 años) y el adicional por almuerzo de
-- cada vigencia del convenio: lo que AEDA guarda en `aeda.dbo.fis_escalas`
-- (38 vigencias, de 2012-10 a 2023-09, 36 antigüedades cada una). Los datos los
-- trae importar_aeda_fisca_escalas.py.
--
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X). Idempotente.

USE sindicato;
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS fisca_escala_salarial (
  id             INT NOT NULL AUTO_INCREMENT,
  periodo_desde  CHAR(6) NOT NULL              COMMENT 'AAAAMM: primer período de la vigencia',
  periodo_hasta  CHAR(6) NOT NULL              COMMENT 'AAAAMM: último período de la vigencia',
  antiguedad     TINYINT UNSIGNED NOT NULL     COMMENT 'Años de antigüedad (0 a 35)',
  basico         DECIMAL(15,2) NOT NULL        COMMENT 'Sueldo básico para esa antigüedad',
  almuerzo       DECIMAL(15,2) NOT NULL DEFAULT 0 COMMENT 'Adicional por almuerzo (igual para todas las antigüedades)',
  origen         ENUM('aeda','manual') NOT NULL DEFAULT 'manual' COMMENT 'aeda = vino de fis_escalas; manual = cargada acá',
  creado         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actualizado    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_fisca_escala (periodo_desde, antiguedad),
  KEY ix_fisca_escala_hasta (periodo_hasta)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Escala salarial del convenio: básico por antigüedad y almuerzo, por vigencia';

-- Verificación
SELECT periodo_desde, periodo_hasta, COUNT(*) AS antiguedades, MIN(basico) AS basico_0, MAX(basico) AS basico_max,
       MAX(almuerzo) AS almuerzo
  FROM fisca_escala_salarial GROUP BY periodo_desde, periodo_hasta ORDER BY periodo_desde;
