-- =============================================================================
-- fisca_liquidacion_escala_20261116.sql — Activos sin DDJJ: por la escala salarial
-- =============================================================================
--
-- Pedido del 16/11/2026: en las liquidaciones por DDJJ de OSEDA, el activo del
-- empleador que no está en su DDJJ (renglón «sin_ddjj», en cero: no hay
-- remuneración de ninguna fuente) se liquida con el sueldo CONFORMADO de la escala
-- del convenio vigente en el período: básico de su antigüedad + almuerzo × 22.
-- La regla está en fisca_liquidacion.py (docstring y armar); esto es:
--
--   1) el esquema: fuente «escala» y la antigüedad usada en el renglón;
--   2) el completado de lo ya liquidado, con la MISMA regla que el código, para
--      no tener que reliquidar (reliquidar da lo mismo).
--
-- Antigüedad: años cumplidos al último día del período (tope 35) desde la fecha
-- más vieja entre las relaciones con ESE empleador que empezaron hasta ese día
-- (fecha_antiguedad o, sin ella, fecha_inicio); sin fecha, 0 («Inicial»).
-- Un período sin escala deja el renglón «sin_ddjj» en cero. No toca lo declarado
-- en cero en la DDJJ ni lo presentado por la empresa (origen «lsd»).
--
-- Correr ENTERO. El paso 2 es idempotente: solo toma renglones «sin_ddjj».

USE sindicato;
SET NAMES utf8mb4;

-- 1) Esquema ------------------------------------------------------------------
ALTER TABLE fisca_liquidacion_detalle
  MODIFY fuente ENUM('nomina','ddjj','aeda','sin_ddjj','lsd','sin_lsd','manual','alta','escala') NOT NULL,
  ADD COLUMN antiguedad TINYINT UNSIGNED NULL COMMENT 'Antigüedad usada si fuente = escala' AFTER activo;

-- 2) Completar lo ya liquidado ---------------------------------------------------
START TRANSACTION;

DROP TEMPORARY TABLE IF EXISTS tmp_esc;
CREATE TEMPORARY TABLE tmp_esc AS
SELECT d.id, d.id_liquidacion, l.periodo, l.alicuota,
       LEAST(35, GREATEST(0, COALESCE(TIMESTAMPDIFF(YEAR,
         (SELECT MIN(COALESCE(r.fecha_antiguedad, r.fecha_inicio))
            FROM p_relaciones_laborales r
           WHERE r.cuil = d.cuil
             AND REGEXP_REPLACE(r.cuit_empleador, '[^0-9]', '') = l.cuit
             AND (r.fecha_inicio IS NULL OR r.fecha_inicio <= LAST_DAY(STR_TO_DATE(CONCAT(l.periodo, '01'), '%Y%m%d')))),
         LAST_DAY(STR_TO_DATE(CONCAT(l.periodo, '01'), '%Y%m%d'))), 0))) AS antig,
       (SELECT MAX(e.periodo_desde) FROM fisca_escala_salarial e
         WHERE e.periodo_desde <= l.periodo AND (e.periodo_hasta IS NULL OR e.periodo_hasta >= l.periodo)) AS escala_desde
  FROM fisca_liquidacion_detalle d
  JOIN fisca_liquidacion l ON l.id = d.id_liquidacion
 WHERE d.fuente = 'sin_ddjj' AND l.origen = 'ddjj' AND l.estado = 'vigente';

DELETE FROM tmp_esc WHERE escala_desde IS NULL;

UPDATE fisca_liquidacion_detalle d
  JOIN tmp_esc t ON t.id = d.id
  JOIN fisca_escala_salarial e ON e.periodo_desde = t.escala_desde AND e.antiguedad = t.antig
   SET d.fuente = 'escala', d.antiguedad = t.antig,
       d.remuneracion = ROUND(e.basico + e.almuerzo * 22, 2),
       d.cuota = ROUND(ROUND(e.basico + e.almuerzo * 22, 2) * t.alicuota / 100, 2);

UPDATE fisca_liquidacion l
  JOIN (SELECT d.id_liquidacion,
               SUM(d.cuota > 0) AS afiliados, SUM(d.remuneracion) AS rem, SUM(d.cuota) AS imp,
               SUM(d.fuente = 'escala') AS por_escala
          FROM fisca_liquidacion_detalle d
         WHERE d.id_liquidacion IN (SELECT DISTINCT id_liquidacion FROM tmp_esc)
         GROUP BY d.id_liquidacion) x ON x.id_liquidacion = l.id
   SET l.afiliados = x.afiliados, l.remuneracion = x.rem, l.importe = x.imp,
       l.observaciones = IF(x.por_escala = 0 OR COALESCE(l.observaciones, '') LIKE '%por la escala salarial%',
         l.observaciones,
         LEFT(CONCAT_WS(' ',
         IF(l.observaciones LIKE 'Ningún afiliado activo del empleador figura en su DDJJ de OSEDA.%',
            'Ningún afiliado activo del empleador figura en su DDJJ de OSEDA.', NULL),
         CONCAT(x.por_escala, ' activo(s) sin DDJJ liquidado(s) por la escala salarial (conformado).'),
         NULLIF(TRIM(IF(l.observaciones LIKE 'Ningún afiliado activo del empleador figura en su DDJJ de OSEDA.%',
            SUBSTRING(l.observaciones, CHAR_LENGTH('Ningún afiliado activo del empleador figura en su DDJJ de OSEDA.') + 1),
            l.observaciones)), '')), 500));

DROP TEMPORARY TABLE tmp_esc;
COMMIT;

-- Verificación
SELECT l.periodo, d.fuente, COUNT(*) AS renglones, SUM(d.cuota) AS cuota
  FROM fisca_liquidacion l JOIN fisca_liquidacion_detalle d ON d.id_liquidacion = l.id
 WHERE l.estado = 'vigente' AND d.fuente IN ('sin_ddjj', 'escala')
 GROUP BY l.periodo, d.fuente ORDER BY l.periodo, d.fuente;
