-- =============================================================================
-- fisca_recibos_talonarios_20261114.sql — Talonarios de recibos y recibo de fiscalización
-- =============================================================================
--
-- Pedido del 14/11/2026: los recibos se numeran por talonario, uno para la cuota
-- sindical y otro para la fiscalización, y los de fiscalización se emiten a un
-- acta (a las cuotas de su acuerdo de pago), como en OSEDA. Los que vinieron de
-- AEDA van a un talonario aparte, con el número de cobro de AEDA (decidido el
-- 14/11/2026), así lo que se siga importando mientras AEDA cobre no se mezcla
-- con lo que se emite acá:
--
--     Recibos Cuota Sindical          X 0001   se emite desde acá
--     Recibos Fiscalización           X 0002   se emite desde acá
--     Recibos Cuota Sindical (AEDA)   X 0091   fis_cobros de CUOTA SINDICAL, número = cobro_id
--     Recibos Fiscalización (AEDA)    X 0092   fis_cobros de FISCALIZACION, número = cobro_id
--
-- El recibo sigue siendo la orden de ingreso (`ingreso_ordenes`, que es la que va
-- al libro, a la conciliación y a la cuenta corriente); ahora lleva su talonario
-- y su número (único por talonario) y, si es de fiscalización, el acta y el
-- acuerdo. Qué cuota del acuerdo paga cada recibo: `fisca_acuerdo_imputacion`.
-- Los talonarios con que se emite se eligen en Datos del Sindicato
-- (s_institucion); los de AEDA están en s_configuracion.
--
-- Correrlo ENTERO (Alt+X), como root. Idempotente.

USE sindicato;
SET NAMES utf8mb4;

-- ─── Columnas ────────────────────────────────────────────────────────────────

DROP PROCEDURE IF EXISTS _recibos_talonarios;
DELIMITER //
CREATE PROCEDURE _recibos_talonarios()
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'sindicato'
                    AND table_name = 'ingreso_ordenes' AND column_name = 'clase'
                    AND column_type LIKE '%fiscalizacion%') THEN
    ALTER TABLE ingreso_ordenes
      MODIFY COLUMN clase ENUM('capitacion','sssalud','bancario','varios','cuota_sindical','fiscalizacion')
                    NOT NULL DEFAULT 'varios';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'sindicato'
                    AND table_name = 'ingreso_ordenes' AND column_name = 'nro_recibo') THEN
    ALTER TABLE ingreso_ordenes
      ADD COLUMN id_talonario INT NULL COMMENT 'Talonario del recibo (c_talonario)' AFTER nro_orden,
      ADD COLUMN nro_recibo INT NULL COMMENT 'Número del recibo en su talonario' AFTER id_talonario,
      ADD COLUMN id_acta INT NULL COMMENT 'Recibo de fiscalización: el acta que se cobra' AFTER origen,
      ADD COLUMN id_acuerdo INT NULL COMMENT 'Recibo de fiscalización: el acuerdo de pago cuyas cuotas paga' AFTER id_acta,
      ADD UNIQUE KEY uq_io_recibo (id_talonario, nro_recibo),
      ADD KEY ix_io_acta (id_acta),
      ADD KEY ix_io_acuerdo (id_acuerdo),
      ADD CONSTRAINT fk_io_talonario FOREIGN KEY (id_talonario) REFERENCES c_talonario (id),
      ADD CONSTRAINT fk_io_acta FOREIGN KEY (id_acta) REFERENCES fisca_acta (id),
      ADD CONSTRAINT fk_io_acuerdo FOREIGN KEY (id_acuerdo) REFERENCES fisca_acuerdo (id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'sindicato'
                    AND table_name = 's_institucion' AND column_name = 'talonario_recibo_cuota') THEN
    ALTER TABLE s_institucion
      ADD COLUMN talonario_recibo_cuota INT NULL COMMENT 'Talonario de los recibos de cuota sindical',
      ADD COLUMN talonario_recibo_fisca INT NULL COMMENT 'Talonario de los recibos de fiscalización',
      ADD CONSTRAINT fk_inst_tal_cuota FOREIGN KEY (talonario_recibo_cuota) REFERENCES c_talonario (id),
      ADD CONSTRAINT fk_inst_tal_fisca FOREIGN KEY (talonario_recibo_fisca) REFERENCES c_talonario (id);
  END IF;
END //
DELIMITER ;
CALL _recibos_talonarios();
DROP PROCEDURE _recibos_talonarios;

CREATE TABLE IF NOT EXISTS fisca_acuerdo_imputacion (
  id          INT NOT NULL AUTO_INCREMENT,
  id_orden    INT NOT NULL                 COMMENT 'El recibo (ingreso_ordenes)',
  id_acuerdo  INT NOT NULL,
  id_cuota    INT NOT NULL,
  importe     DECIMAL(15,2) NOT NULL,
  creado      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_fisca_imput (id_orden, id_cuota),
  KEY ix_fisca_imput_acuerdo (id_acuerdo),
  KEY ix_fisca_imput_cuota (id_cuota),
  CONSTRAINT fk_fisca_imput_orden FOREIGN KEY (id_orden) REFERENCES ingreso_ordenes (id),
  CONSTRAINT fk_fisca_imput_acuerdo FOREIGN KEY (id_acuerdo) REFERENCES fisca_acuerdo (id),
  CONSTRAINT fk_fisca_imput_cuota FOREIGN KEY (id_cuota) REFERENCES fisca_acuerdo_cuota (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Qué cuota del acuerdo de pago paga cada recibo de fiscalización. Pagado = lo de recibos no anulados';

-- La cuota del acuerdo no se puede borrar con un recibo encima: rehacer el
-- cronograma (DELETE + INSERT) solo vale sin cobros, y lo controla la pantalla.

-- ─── Motivo del interés ──────────────────────────────────────────────────────
-- El recibo de fiscalización se parte en capital (INGRESOS POR FISCALIZACION, un
-- renglón por período del acta: cancela la cuota sindical de ese período en la
-- cuenta corriente) e interés (este motivo: resarcitorio del acta y de la
-- financiación; no es un cobro de cuota). Cuenta contable: la de INGRESOS POR
-- FISCALIZACION, a revisar con el contador.

INSERT INTO c_motivos_de_ingreso (id, descripcion, c_plan_de_cuentasId, c_especiesId, activo)
SELECT (SELECT COALESCE(MAX(id), 0) + 1 FROM c_motivos_de_ingreso), 'INTERESES POR FISCALIZACION',
       COALESCE((SELECT c_plan_de_cuentasId FROM c_motivos_de_ingreso WHERE descripcion = 'INGRESOS POR FISCALIZACION' LIMIT 1),
                (SELECT c_plan_de_cuentasId FROM c_motivos_de_ingreso ORDER BY id LIMIT 1)),
       (SELECT c_especiesId FROM c_motivos_de_ingreso WHERE descripcion = 'INGRESOS POR FISCALIZACION' LIMIT 1), 1
 WHERE NOT EXISTS (SELECT 1 FROM c_motivos_de_ingreso WHERE descripcion = 'INTERESES POR FISCALIZACION');

-- ─── Talonarios ──────────────────────────────────────────────────────────────

INSERT INTO c_contable_comprobante_tipo (nombre, debito_credito, propio, creado)
SELECT 'Recibo', 'C', 1, NOW() WHERE NOT EXISTS (SELECT 1 FROM c_contable_comprobante_tipo WHERE nombre = 'Recibo');
INSERT INTO c_talonario_clasificacion (descripcion, id_comprobante_tipo, creado)
SELECT 'Recibos', (SELECT id FROM c_contable_comprobante_tipo WHERE nombre = 'Recibo'), NOW()
 WHERE NOT EXISTS (SELECT 1 FROM c_talonario_clasificacion WHERE descripcion = 'Recibos');
SET @clasif := (SELECT id FROM c_talonario_clasificacion WHERE descripcion = 'Recibos');

INSERT INTO c_talonario (nombre, letra, punto_de_venta, numero_desde, numero_hasta, ultimo_emitido, habilitado, comentario,
                         c_talonario_clasificacionId)
SELECT x.nombre, 'X', x.pv, 1, 99999999, 0, x.hab, x.coment, @clasif
  FROM (SELECT 'Recibos Cuota Sindical' AS nombre, 1 AS pv, 1 AS hab,
               'Recibos de cuota sindical que se emiten en el sistema' AS coment
        UNION ALL SELECT 'Recibos Fiscalización', 2, 1, 'Recibos de fiscalización: se emiten a un acta (las cuotas de su acuerdo)'
        UNION ALL SELECT 'Recibos Cuota Sindical (AEDA)', 91, 0, 'Cobros de cuota sindical de AEDA (fis_cobros): número = cobro_id. Lo usa importar_aeda_fondos.py'
        UNION ALL SELECT 'Recibos Fiscalización (AEDA)', 92, 0, 'Cobros de fiscalización de AEDA (fis_cobros): número = cobro_id. Lo usa importar_aeda_fondos.py') x
 WHERE NOT EXISTS (SELECT 1 FROM c_talonario t WHERE t.letra = 'X' AND t.punto_de_venta = x.pv
                      AND t.c_talonario_clasificacionId = @clasif);

SET @t_cuota := (SELECT id FROM c_talonario WHERE letra = 'X' AND punto_de_venta = 1  AND c_talonario_clasificacionId = @clasif);
SET @t_fisca := (SELECT id FROM c_talonario WHERE letra = 'X' AND punto_de_venta = 2  AND c_talonario_clasificacionId = @clasif);
SET @a_cuota := (SELECT id FROM c_talonario WHERE letra = 'X' AND punto_de_venta = 91 AND c_talonario_clasificacionId = @clasif);
SET @a_fisca := (SELECT id FROM c_talonario WHERE letra = 'X' AND punto_de_venta = 92 AND c_talonario_clasificacionId = @clasif);

UPDATE s_institucion SET talonario_recibo_cuota = COALESCE(talonario_recibo_cuota, @t_cuota),
                         talonario_recibo_fisca = COALESCE(talonario_recibo_fisca, @t_fisca)
 WHERE id = 1;

INSERT INTO s_configuracion (modulo, tabla, campo, parametro, valor, descripcion)
VALUES ('fiscalizacion', 'c_talonario', 'id', 'talonario_recibos_aeda_cuota', @a_cuota,
        'Talonario de los recibos de cuota sindical que vienen de AEDA (importar_aeda_fondos.py)'),
       ('fiscalizacion', 'c_talonario', 'id', 'talonario_recibos_aeda_fisca', @a_fisca,
        'Talonario de los recibos de fiscalización que vienen de AEDA (importar_aeda_fondos.py)')
ON DUPLICATE KEY UPDATE valor = valor;

-- ─── Los recibos de AEDA, a su talonario ─────────────────────────────────────
-- «AEDA-RC-<cobro_id>»: de fiscalización si su renglón es INGRESOS POR
-- FISCALIZACION, si no de cuota sindical. Entraron como clase «varios».

UPDATE ingreso_ordenes o
  JOIN (SELECT d.id_orden, MAX(m.descripcion = 'INGRESOS POR FISCALIZACION') AS fisca
          FROM ingreso_ordenes_detalle d LEFT JOIN c_motivos_de_ingreso m ON m.id = d.id_motivo_ingreso
         GROUP BY d.id_orden) x ON x.id_orden = o.id
   SET o.clase = IF(x.fisca, 'fiscalizacion', 'cuota_sindical'),
       o.id_talonario = IF(x.fisca, @a_fisca, @a_cuota),
       o.nro_recibo = CAST(SUBSTRING(o.nro_orden, 9) AS UNSIGNED)
 WHERE o.nro_orden LIKE 'AEDA-RC-%' AND SUBSTRING(o.nro_orden, 9) REGEXP '^[0-9]+$' AND o.nro_recibo IS NULL;

UPDATE c_talonario t
   SET t.ultimo_emitido = GREATEST(t.ultimo_emitido,
                                   COALESCE((SELECT MAX(o.nro_recibo) FROM ingreso_ordenes o WHERE o.id_talonario = t.id), 0))
 WHERE t.id IN (@a_cuota, @a_fisca);

-- ─── Control ─────────────────────────────────────────────────────────────────
SELECT t.id, t.nombre, CONCAT(t.letra, ' ', LPAD(t.punto_de_venta, 4, '0')) AS talonario, t.habilitado, t.ultimo_emitido,
       COUNT(o.id) AS recibos, MIN(o.fecha) AS desde, MAX(o.fecha) AS hasta
  FROM c_talonario t LEFT JOIN ingreso_ordenes o ON o.id_talonario = t.id
 WHERE t.c_talonario_clasificacionId = @clasif
 GROUP BY t.id, t.nombre, t.letra, t.punto_de_venta, t.habilitado, t.ultimo_emitido ORDER BY t.punto_de_venta;
SELECT COUNT(*) AS aeda_rc_sin_talonario FROM ingreso_ordenes WHERE nro_orden LIKE 'AEDA-RC-%' AND id_talonario IS NULL;
