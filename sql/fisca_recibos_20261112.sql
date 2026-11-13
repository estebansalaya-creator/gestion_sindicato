-- =============================================================================
-- fisca_recibos_20261112.sql — Emisión de recibos de cuota sindical
-- =============================================================================
--
-- Fiscalización de Cuotas → Emisión de Recibos (fisca_recibos.py): de cada
-- acreditación del extracto bancario sale el recibo de cuota sindical del
-- empleador que pagó. El recibo es una orden de ingreso (ingreso_ordenes) de
-- clase «cuota_sindical» y origen «extracto», con un renglón por período
-- (ingreso_ordenes_detalle, con el CUIT del empleador y el renglón del extracto
-- de donde salió).
--
-- El empleador se reconoce por el CUIT que trae el banco: el mismo CUIT, o uno
-- de los que pagan por él (fisca_cuit_relacionado: el estudio contable, el
-- dueño, otra empresa del grupo). La relación se carga en la misma pantalla.
-- Las de AEDA (afi_empresas_rel, 15 al 12/11/2026) entran acá.
--
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X). Idempotente.
-- El menú se lee al iniciar sesión: salir y volver a entrar.

USE sindicato;
SET NAMES utf8mb4;

-- CUIT que pagan por un empleador ---------------------------------------------
CREATE TABLE IF NOT EXISTS fisca_cuit_relacionado (
  id             INT NOT NULL AUTO_INCREMENT,
  cuit_pagador   VARCHAR(11) NOT NULL COMMENT 'CUIT o CUIL que aparece en la acreditación del banco',
  cuit_empleador VARCHAR(11) NOT NULL COMMENT 'Empleador al que corresponde lo que paga',
  observaciones  VARCHAR(250) NULL,
  origen         ENUM('manual','aeda') NOT NULL DEFAULT 'manual',
  activo         TINYINT(1) NOT NULL DEFAULT 1 COMMENT '0 = dada de baja: no se usa para reconocer pagos',
  id_usuario     INT NULL,
  creado         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actualizado    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_fisca_cuit_rel (cuit_pagador, cuit_empleador),
  KEY ix_fisca_cuit_rel_emp (cuit_empleador),
  CONSTRAINT fk_fisca_cuit_rel_usuario FOREIGN KEY (id_usuario) REFERENCES s_usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='CUIT o CUIL que pagan la cuota sindical de un empleador';

INSERT INTO fisca_cuit_relacionado (cuit_pagador, cuit_empleador, origen, observaciones)
SELECT v.pagador, v.empleador, 'aeda', '[AEDA afi_empresas_rel]'
  FROM (SELECT '27181300383' AS pagador, '20041701138' AS empleador
        UNION ALL SELECT '20140082059', '20044297559'
        UNION ALL SELECT '27360654988', '23309258819'
        UNION ALL SELECT '30715403346', '27218155516'
        UNION ALL SELECT '23081898529', '27299415819'
        UNION ALL SELECT '20044390753', '30652980623'
        UNION ALL SELECT '20181107678', '30652980623'
        UNION ALL SELECT '20226547372', '30652980623'
        UNION ALL SELECT '20408293651', '30652980623'
        UNION ALL SELECT '27255681104', '30652980623'
        UNION ALL SELECT '23052203619', '30680616724'
        UNION ALL SELECT '20081898201', '30696906420'
        UNION ALL SELECT '20127917419', '30710216319'
        UNION ALL SELECT '27135654987', '30711382611'
        UNION ALL SELECT '30715331140', '30718636287') v
 WHERE NOT EXISTS (SELECT 1 FROM fisca_cuit_relacionado x
                    WHERE x.cuit_pagador = v.pagador AND x.cuit_empleador = v.empleador);

-- El recibo: clase y origen de la orden de ingreso ----------------------------
ALTER TABLE ingreso_ordenes
  MODIFY COLUMN clase ENUM('capitacion','sssalud','bancario','varios','cuota_sindical') NOT NULL DEFAULT 'varios',
  MODIFY COLUMN origen ENUM('manual','conciliacion','extracto') NOT NULL DEFAULT 'manual'
    COMMENT 'extracto = recibo de cuota sindical emitido desde un renglón del extracto';

-- El empleador de cada renglón (cuota sindical y fiscalización) ---------------
SET @hay := (SELECT COUNT(*) FROM information_schema.columns
              WHERE table_schema = DATABASE() AND table_name = 'ingreso_ordenes_detalle' AND column_name = 'cuit');
SET @sql := IF(@hay = 0,
  'ALTER TABLE ingreso_ordenes_detalle
     ADD COLUMN cuit VARCHAR(11) NULL COMMENT ''Empleador al que se imputa (cuota sindical, fiscalización)'' AFTER periodo,
     ADD KEY ix_ing_det_cuit_periodo (cuit, periodo)',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- Lo ya cargado lleva el CUIT en la descripción: «CUOTA SINDICAL 2026-10 · RAZON (CUIT 30716707519)».
UPDATE ingreso_ordenes_detalle
   SET cuit = SUBSTRING(REGEXP_SUBSTR(descripcion, 'CUIT [0-9]{11}'), 6)
 WHERE cuit IS NULL AND descripcion REGEXP 'CUIT [0-9]{11}';

SET @hay := (SELECT COUNT(*) FROM information_schema.statistics
              WHERE table_schema = DATABASE() AND table_name = 'ingreso_ordenes_detalle'
                AND index_name = 'ix_ing_det_extracto');
SET @sql := IF(@hay = 0, 'ALTER TABLE ingreso_ordenes_detalle ADD KEY ix_ing_det_extracto (id_extracto_origen)', 'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- Menú: Fiscalización de Cuotas → Emisión de Recibos (id 8, o el siguiente libre)
SET @id := (SELECT id FROM s_menu WHERE url = '/fiscalizacion/recibos' LIMIT 1);
SET @id := COALESCE(@id, IF(EXISTS (SELECT 1 FROM s_menu WHERE id = 8), (SELECT MAX(id) + 1 FROM s_menu), 8));
INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (@id, 1, 'Emisión de Recibos', '/fiscalizacion/recibos', NULL, 7, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url),
  padre_id = VALUES(padre_id), orden = VALUES(orden), activo = 1;

INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT @id, r.id FROM s_roles r
 WHERE r.nombre IN ('Administrador', 'Supervisor')
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = @id AND x.rol_id = r.id);

-- Verificación ----------------------------------------------------------------
SELECT table_name, column_name, column_type
  FROM information_schema.columns
 WHERE table_schema = DATABASE()
   AND ((table_name = 'ingreso_ordenes' AND column_name IN ('clase', 'origen'))
     OR (table_name = 'ingreso_ordenes_detalle' AND column_name = 'cuit'));
SELECT origen, COUNT(*) AS relaciones FROM fisca_cuit_relacionado GROUP BY origen;
SELECT COUNT(*) AS renglones_con_cuit FROM ingreso_ordenes_detalle WHERE cuit IS NOT NULL;
SELECT m.id, m.nombre, m.url, m.orden FROM s_menu m WHERE m.padre_id = 1 ORDER BY m.orden;
