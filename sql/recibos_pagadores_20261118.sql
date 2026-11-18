-- =============================================================================
-- Identificar a quien pagó una acreditación (pedido del 18/11/2026)
--
-- 1. c_extractos_bancarios.cuit_manual: el banco no siempre trae el CUIT de quien
--    transfirió (TRANSF.INT.DIST.TITULAR sin CUIT: tampoco lo tiene AEDA en
--    adm_bna24). Desde Emisión de Recibos se carga a mano en el renglón, con quién
--    y cuándo; un CUIT que trajo el banco no se pisa.
-- 2. fisca_cuit_afiliado: el CUIT/CUIL que paga por un afiliado (el cónyuge, un
--    familiar que no está en el padrón, una cuenta de otro titular). Sus pagos se
--    reconocen como del afiliado: van por Beneficios (cuota social), como los que
--    paga el afiliado desde su cuenta. Es el par de fisca_cuit_relacionado, que
--    hace lo mismo con un empleador.
--
-- Sin este script la pantalla funciona igual, sin «Asociar».
-- =============================================================================

ALTER TABLE c_extractos_bancarios
  ADD COLUMN cuit_manual TINYINT NOT NULL DEFAULT 0
      COMMENT '1 = el CUIT lo cargó una persona porque el banco no lo traía',
  ADD COLUMN cuit_manual_usuario INT NULL,
  ADD COLUMN cuit_manual_fecha DATETIME NULL;

CREATE TABLE IF NOT EXISTS fisca_cuit_afiliado (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  cuit_pagador   VARCHAR(11)  NOT NULL,
  cuil_afiliado  VARCHAR(11)  NOT NULL,
  observaciones  VARCHAR(250) NULL,
  activo         TINYINT      NOT NULL DEFAULT 1,
  id_usuario     INT          NULL,
  creado         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_fisca_cuit_afiliado (cuit_pagador),
  KEY ix_fisca_cuit_afiliado_cuil (cuil_afiliado)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
