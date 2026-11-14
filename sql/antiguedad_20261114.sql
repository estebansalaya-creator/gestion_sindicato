-- =============================================================================
-- antiguedad_20261114.sql — Fecha desde la que se cuenta la antigüedad
-- =============================================================================
--
-- `p_relaciones_laborales.fecha_inicio` es el ingreso que vino de AEDA y muchas
-- veces es la fecha de afiliación al gremio, no la de ingreso a la empresa. La
-- fecha real (Simplificación Registral) solo la ve el empleador con su clave.
-- Mientras tanto la antigüedad se cuenta desde la más antigua entre el padrón
-- y el inicio del tramo de DDJJ de OSEDA de ese empleador (antiguedad_ddjj.py
-- --aplicar la calcula y la graba acá). Sin fecha_antiguedad se usa fecha_inicio.
-- Una fecha que informó el empleador (origen «empresa») el script no la pisa.
-- Editar la fecha desde de la relación en la ficha del afiliado la borra: manda
-- lo que se cargó a mano.
--
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X). Idempotente.

USE sindicato;
SET NAMES utf8mb4;

DROP PROCEDURE IF EXISTS _antig_columnas;
DELIMITER //
CREATE PROCEDURE _antig_columnas()
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'sindicato'
                    AND table_name = 'p_relaciones_laborales' AND column_name = 'fecha_antiguedad') THEN
    ALTER TABLE p_relaciones_laborales
      ADD COLUMN fecha_antiguedad DATE NULL
          COMMENT 'Desde cuándo se cuenta la antigüedad; NULL = fecha_inicio' AFTER fecha_fin,
      ADD COLUMN antiguedad_origen ENUM('padron','ddjj','empresa') NULL
          COMMENT 'padron = fecha_inicio; ddjj = inicio del tramo de DDJJ de OSEDA de este empleador; empresa = la informó el empleador (Simplificación Registral)' AFTER fecha_antiguedad,
      ADD COLUMN antiguedad_al_menos TINYINT(1) NOT NULL DEFAULT 0
          COMMENT '1 = el tramo de DDJJ empieza en el primer período de afi_redapo: puede ser mayor' AFTER antiguedad_origen,
      ADD COLUMN antiguedad_nota VARCHAR(200) NULL
          COMMENT 'Resultado del cruce con la DDJJ (antiguedad_ddjj.py)' AFTER antiguedad_al_menos,
      ADD COLUMN antiguedad_calculada DATETIME NULL
          COMMENT 'Cuándo la calculó antiguedad_ddjj.py' AFTER antiguedad_nota;
  END IF;
END //
DELIMITER ;
CALL _antig_columnas();
DROP PROCEDURE _antig_columnas;
