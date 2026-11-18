-- =============================================================================
-- beneficios_entregas_20261118.sql — Padrón de entrega de una campaña de Beneficios
-- =============================================================================
-- Pedido del 18/11/2026: en una campaña, con el grupo elegido en «A quién va»
-- (los filtros del padrón, titulares, adheridos…), «Crear padrón de entrega»
-- arma la lista de quienes reciben el beneficio —las cajas navideñas— y, cuando
-- vienen a retirarlo, se marca que retiró (ben_entregas.py).
--
--   ben_campania.entrega_generada   cuándo se armó el padrón de entrega
--   ben_entrega                     el padrón de entrega (una foto del padrón de
--                                   afiliados al crearlo) y quién retiró: cuándo,
--                                   quién lo marcó y, si no fue el afiliado, quién
--   ben_entrega_mov                 el rastro: retiró, retiro quitado, agregado,
--                                   quitado, padrón creado
--
-- Requiere sql/beneficios_correo_20261117.sql. Usa el permiso de Campañas
-- (menú 127): no agrega opciones de menú. Correr ENTERO antes de subir el
-- código. Idempotente.

USE sindicato;
SET NAMES utf8mb4;

SET @hay := (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE()
              AND table_name = 'ben_campania' AND column_name = 'entrega_generada');
SET @sql := IF(@hay = 0,
  'ALTER TABLE ben_campania ADD COLUMN entrega_generada DATETIME NULL COMMENT ''Cuándo se armó el padrón de entrega del beneficio (ben_entrega)''',
  'SELECT ''ben_campania ya tiene entrega_generada'' AS aviso');
PREPARE st FROM @sql; EXECUTE st; DEALLOCATE PREPARE st;

CREATE TABLE IF NOT EXISTS ben_entrega (
  id                 INT AUTO_INCREMENT PRIMARY KEY,
  id_campania        INT           NOT NULL,
  id_afiliado        INT           NOT NULL,
  orden              INT           NOT NULL COMMENT 'Número de orden (alfabético; los agregados a mano, al final)',
  cuil               VARCHAR(11)   NULL,
  nro_documento      VARCHAR(20)   NULL,
  apellido_nombres   VARCHAR(100)  NOT NULL,
  cod_parentesco     INT           NULL COMMENT '0 = titular',
  parentesco         VARCHAR(60)   NULL,
  cuil_titular       VARCHAR(11)   NULL,
  empleador          VARCHAR(200)  NULL,
  origen             ENUM('padron','manual') NOT NULL DEFAULT 'padron',
  entregado          TINYINT(1)    NOT NULL DEFAULT 0,
  fecha_entrega      DATETIME      NULL,
  id_usuario_entrega INT           NULL,
  retiro_nombre      VARCHAR(150)  NULL COMMENT 'Si no lo retiró el afiliado: quién',
  retiro_documento   VARCHAR(20)   NULL,
  creado             DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_ben_entrega (id_campania, id_afiliado),
  KEY idx_ben_entrega_doc (id_campania, nro_documento),
  KEY idx_ben_entrega_estado (id_campania, entregado),
  CONSTRAINT fk_ben_entrega_camp FOREIGN KEY (id_campania) REFERENCES ben_campania (id) ON DELETE CASCADE,
  CONSTRAINT fk_ben_entrega_afi  FOREIGN KEY (id_afiliado) REFERENCES p_afiliados (id_afiliado)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Padrón de entrega del beneficio de una campaña y quién retiró';

CREATE TABLE IF NOT EXISTS ben_entrega_mov (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  id_campania  INT           NOT NULL,
  id_afiliado  INT           NULL COMMENT 'NULL en «padrón creado»',
  accion       ENUM('entrega','quita_entrega','agregado','quitado','generado') NOT NULL,
  detalle      VARCHAR(300)  NULL,
  id_usuario   INT           NULL,
  fecha        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_ben_entrega_mov (id_campania, fecha),
  CONSTRAINT fk_ben_entrega_mov_camp FOREIGN KEY (id_campania) REFERENCES ben_campania (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Rastro del padrón de entrega: retiros, retiros quitados, altas y quitas';

SHOW COLUMNS FROM ben_campania WHERE Field = 'entrega_generada';
SELECT table_name FROM information_schema.tables
 WHERE table_schema = DATABASE() AND table_name IN ('ben_entrega', 'ben_entrega_mov');
