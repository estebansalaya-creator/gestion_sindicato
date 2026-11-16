-- =============================================================================
-- recibos_afiliados_20261115.sql — Recibos a afiliados: la cuota social YMCA
-- =============================================================================
--
-- Pedido del 15/11/2026. Las transferencias de importe fijo de los afiliados
-- ($ 25.000 hasta agosto de 2026, $ 30.000 desde septiembre; el doble, dos
-- meses) no son cuota sindical: AEDA las registraba como «YMCA» (cuota social),
-- en órdenes de ingreso agrupadas por cuenta y por mes (adm_ordIngre, concepto
-- 148; se importaron con el motivo de ingreso YMCA). Acá cada transferencia
-- lleva su RECIBO AL AFILIADO:
--
--   · Clase de orden de ingreso «afiliado», con el CUIL del afiliado
--     (`ingreso_ordenes.cuil_afiliado`).
--   · Talonario propio: Recibos Afiliados, X 0003.
--   · En Datos del Sindicato: el talonario, el motivo de ingreso (YMCA), el
--     concepto que dice el recibo («Cuota social YMCA») y el importe de la cuota
--     por mes (30.000): una transferencia que es justo N cuotas paga N meses
--     desde el de la acreditación, y solo esas se emiten en lote.
--
-- Pantallas: Fiscalización → Emisión de Recibos (de a uno y en lote), la solapa
-- «Cuota social» del afiliado y Tesorería → Recibos Emitidos.
--
-- Correrlo ENTERO (Alt+X), como root. Idempotente.

USE sindicato;
SET NAMES utf8mb4;

DROP PROCEDURE IF EXISTS _recibos_afiliados;
DELIMITER //
CREATE PROCEDURE _recibos_afiliados()
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'sindicato'
                    AND table_name = 'ingreso_ordenes' AND column_name = 'clase'
                    AND column_type LIKE '%afiliado%') THEN
    ALTER TABLE ingreso_ordenes
      MODIFY COLUMN clase ENUM('capitacion','sssalud','bancario','varios','cuota_sindical','fiscalizacion','afiliado')
                    NOT NULL DEFAULT 'varios';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'sindicato'
                    AND table_name = 'ingreso_ordenes' AND column_name = 'cuil_afiliado') THEN
    ALTER TABLE ingreso_ordenes
      ADD COLUMN cuil_afiliado CHAR(11) NULL COMMENT 'Recibo a un afiliado (clase afiliado): su CUIL' AFTER id_acuerdo,
      ADD KEY ix_io_cuil_afiliado (cuil_afiliado);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'sindicato'
                    AND table_name = 's_institucion' AND column_name = 'talonario_recibo_afiliado') THEN
    ALTER TABLE s_institucion
      ADD COLUMN talonario_recibo_afiliado INT NULL COMMENT 'Talonario de los recibos a afiliados (cuota social)',
      ADD COLUMN recibo_afiliado_motivo INT NULL COMMENT 'Motivo de ingreso de los recibos a afiliados (c_motivos_de_ingreso)',
      ADD COLUMN recibo_afiliado_concepto VARCHAR(100) NULL COMMENT 'Lo que dice el recibo: «Cuota social YMCA»',
      ADD COLUMN recibo_afiliado_cuota DECIMAL(15,2) NULL COMMENT 'Importe de la cuota por mes: N cuotas justas pagan N meses',
      ADD CONSTRAINT fk_inst_tal_afiliado FOREIGN KEY (talonario_recibo_afiliado) REFERENCES c_talonario (id),
      ADD CONSTRAINT fk_inst_motivo_afiliado FOREIGN KEY (recibo_afiliado_motivo) REFERENCES c_motivos_de_ingreso (id);
  END IF;
  -- La solapa del afiliado busca sus transferencias en el extracto por el CUIT del banco.
  IF NOT EXISTS (SELECT 1 FROM information_schema.statistics WHERE table_schema = 'sindicato'
                    AND table_name = 'c_extractos_bancarios' AND index_name = 'ix_ext_cuit') THEN
    ALTER TABLE c_extractos_bancarios ADD KEY ix_ext_cuit (cuit);
  END IF;
END //
DELIMITER ;
CALL _recibos_afiliados();
DROP PROCEDURE _recibos_afiliados;

-- ─── Talonario X 0003 ────────────────────────────────────────────────────────

SET @clasif := (SELECT id FROM c_talonario_clasificacion WHERE descripcion = 'Recibos');
INSERT INTO c_talonario (nombre, letra, punto_de_venta, numero_desde, numero_hasta, ultimo_emitido, habilitado, comentario,
                         c_talonario_clasificacionId)
SELECT 'Recibos Afiliados', 'X', 3, 1, 99999999, 0, 1,
       'Recibos a afiliados por la cuota social (YMCA) que transfieren al sindicato', @clasif
 WHERE @clasif IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM c_talonario t WHERE t.letra = 'X' AND t.punto_de_venta = 3
                      AND t.c_talonario_clasificacionId = @clasif);
SET @t_afi := (SELECT id FROM c_talonario WHERE letra = 'X' AND punto_de_venta = 3 AND c_talonario_clasificacionId = @clasif);

-- ─── Datos del Sindicato ─────────────────────────────────────────────────────

UPDATE s_institucion
   SET talonario_recibo_afiliado = COALESCE(talonario_recibo_afiliado, @t_afi),
       recibo_afiliado_motivo    = COALESCE(recibo_afiliado_motivo,
                                            (SELECT id FROM c_motivos_de_ingreso WHERE descripcion = 'YMCA' LIMIT 1)),
       recibo_afiliado_concepto  = COALESCE(recibo_afiliado_concepto, 'Cuota social YMCA'),
       recibo_afiliado_cuota     = COALESCE(recibo_afiliado_cuota, 30000)
 WHERE id = 1;

-- Para revisar.
SELECT i.talonario_recibo_afiliado, t.nombre AS talonario, CONCAT(t.letra, ' ', LPAD(t.punto_de_venta, 4, '0')) AS pv,
       i.recibo_afiliado_motivo, m.descripcion AS motivo, i.recibo_afiliado_concepto, i.recibo_afiliado_cuota
  FROM s_institucion i
  LEFT JOIN c_talonario t ON t.id = i.talonario_recibo_afiliado
  LEFT JOIN c_motivos_de_ingreso m ON m.id = i.recibo_afiliado_motivo
 WHERE i.id = 1;
