-- =============================================================================
-- beneficios_entregas_empresa_20261124.sql — Retiro del beneficio por la empresa
-- =============================================================================
-- Pedido del 24/11/2026, sobre el padrón de entrega de una campaña (ben_entregas.py):
-- con la grilla filtrada a una sola empresa, «Retira por la empresa» registra de
-- una vez el retiro de los afiliados de esa empresa que faltan, a nombre de quien
-- viene a buscarlos (nombre y DNI), y saca la constancia en PDF por duplicado
-- para que la firme.
--
--   ben_entrega_retiro     un retiro por la empresa: empresa, quién retiró, cuántos,
--                          cuándo y quién lo registró. Su id es el N° de constancia.
--   ben_entrega.id_retiro  a qué retiro por la empresa pertenece cada fila
--
-- Requiere sql/beneficios_entregas_20261118.sql y sql/beneficios_entregas_stock_20261118.sql.
-- Correr ENTERO antes de subir el código. Idempotente.

USE sindicato;
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS ben_entrega_retiro (
  id                INT AUTO_INCREMENT PRIMARY KEY,
  id_campania       INT           NOT NULL,
  empleador         VARCHAR(200)  NOT NULL COMMENT 'La empresa, como figura en el padrón de entrega',
  retiro_nombre     VARCHAR(150)  NOT NULL COMMENT 'Quién vino a retirar por la empresa',
  retiro_documento  VARCHAR(20)   NOT NULL,
  cantidad          INT           NOT NULL COMMENT 'Cuántos retiró (al registrarlo)',
  id_usuario        INT           NULL,
  fecha             DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_ben_entrega_retiro (id_campania, fecha),
  CONSTRAINT fk_ben_entrega_retiro_camp FOREIGN KEY (id_campania) REFERENCES ben_campania (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Retiros del beneficio hechos por la empresa para sus afiliados (constancia por duplicado)';

SET @hay := (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE()
              AND table_name = 'ben_entrega' AND column_name = 'id_retiro');
SET @sql := IF(@hay = 0,
  'ALTER TABLE ben_entrega ADD COLUMN id_retiro INT NULL COMMENT ''Retiro por la empresa (ben_entrega_retiro)'' AFTER retiro_documento,
     ADD KEY idx_ben_entrega_retiro (id_retiro),
     ADD CONSTRAINT fk_ben_entrega_retiro FOREIGN KEY (id_retiro) REFERENCES ben_entrega_retiro (id) ON DELETE SET NULL',
  'SELECT ''ben_entrega ya tiene id_retiro'' AS aviso');
PREPARE st FROM @sql; EXECUTE st; DEALLOCATE PREPARE st;

SHOW COLUMNS FROM ben_entrega WHERE Field = 'id_retiro';
SELECT table_name FROM information_schema.tables
 WHERE table_schema = DATABASE() AND table_name = 'ben_entrega_retiro';
