-- =============================================================================
-- beneficios_entregas_stock_20261118.sql — Stock del beneficio y entregas fuera del padrón
-- =============================================================================
-- Pedido del 18/11/2026, sobre el padrón de entrega de una campaña (ben_entregas.py):
--   · «poder cargar un stock de beneficios»: ben_entrega_stock, una fila por carga
--     (+) o ajuste (−). Lo que queda es lo cargado menos lo retirado.
--   · «poder marcar si se entrega a una persona que no sea del padrón»: en
--     ben_entrega, el afiliado pasa a ser opcional (un no afiliado entra con su
--     nombre y documento, origen «externo») y se guarda el motivo.
--
-- Requiere sql/beneficios_entregas_20261118.sql. Correr ENTERO antes de subir el
-- código. Idempotente.

USE sindicato;
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS ben_entrega_stock (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  id_campania  INT           NOT NULL,
  cantidad     INT           NOT NULL COMMENT 'Positivo: carga. Negativo: ajuste (rotas, devueltas)',
  detalle      VARCHAR(300)  NOT NULL COMMENT 'La compra, el remito, el motivo del ajuste',
  id_usuario   INT           NULL,
  fecha        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_ben_entrega_stock (id_campania, fecha),
  CONSTRAINT fk_ben_entrega_stock_camp FOREIGN KEY (id_campania) REFERENCES ben_campania (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Stock del beneficio de una campaña: cargas y ajustes';

-- Un no afiliado no tiene id_afiliado. La FK y el UNIQUE siguen: MySQL deja
-- varias filas con NULL en un UNIQUE.
ALTER TABLE ben_entrega
  MODIFY id_afiliado INT NULL COMMENT 'NULL: no afiliado, entregado fuera del padrón (origen externo)',
  MODIFY origen ENUM('padron','manual','externo') NOT NULL DEFAULT 'padron'
         COMMENT 'padron: del grupo de la campaña · manual: agregado a mano · externo: no afiliado';

SET @hay := (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE()
              AND table_name = 'ben_entrega' AND column_name = 'observaciones');
SET @sql := IF(@hay = 0,
  'ALTER TABLE ben_entrega ADD COLUMN observaciones VARCHAR(300) NULL COMMENT ''Motivo de una entrega fuera del padrón'' AFTER retiro_documento',
  'SELECT ''ben_entrega ya tiene observaciones'' AS aviso');
PREPARE st FROM @sql; EXECUTE st; DEALLOCATE PREPARE st;

ALTER TABLE ben_entrega_mov
  MODIFY accion ENUM('entrega','quita_entrega','agregado','quitado','generado','stock','externo') NOT NULL;

SHOW COLUMNS FROM ben_entrega WHERE Field IN ('id_afiliado', 'origen', 'observaciones');
SHOW COLUMNS FROM ben_entrega_mov WHERE Field = 'accion';
SELECT table_name FROM information_schema.tables
 WHERE table_schema = DATABASE() AND table_name = 'ben_entrega_stock';
