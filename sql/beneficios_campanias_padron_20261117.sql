-- =============================================================================
-- beneficios_campanias_padron_20261117.sql — Campañas a una lista armada con los filtros del padrón
-- =============================================================================
-- Pedido del 17/11/2026: en «A quién va», poder generar la lista según los filtros
-- del padrón (estado, titular o familiar, sexo, edad, atributo, buscar). La
-- campaña guarda los filtros (`filtro`, JSON) y la lista se arma con ellos al
-- enviarla (ben_campanias.destinatarios).
--
-- Requiere sql/beneficios_correo_20261117.sql. Correr ENTERO antes de subir el
-- código. Idempotente.

USE sindicato;
SET NAMES utf8mb4;

ALTER TABLE ben_campania
  MODIFY destino ENUM('titulares','todos','adheridos','padron') NOT NULL DEFAULT 'titulares';

SET @hay := (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE()
              AND table_name = 'ben_campania' AND column_name = 'filtro');
SET @sql := IF(@hay = 0,
  'ALTER TABLE ben_campania ADD COLUMN filtro JSON NULL COMMENT ''Con destino «padron»: los filtros del padrón (q, estado, tipo, sexo, edad_desde, edad_hasta, atributo)'' AFTER id_convenio',
  'SELECT ''ben_campania ya tiene filtro'' AS aviso');
PREPARE st FROM @sql; EXECUTE st; DEALLOCATE PREPARE st;

SHOW COLUMNS FROM ben_campania WHERE Field IN ('destino', 'filtro');
