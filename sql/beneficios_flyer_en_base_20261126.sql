-- =============================================================================
-- beneficios_flyer_en_base_20261126.sql — Copia del flyer de cada campaña en la base
-- =============================================================================
-- Pedido del 26/11/2026: en Railway el flyer de la campaña se perdía y había que
-- volver a cargarlo. El archivo estaba solo en el disco del contenedor
-- (SIND_ADJUNTOS), que se vacía en cada deploy o reinicio si no hay un volumen
-- permanente ni bucket. Ahora la campaña guarda también los bytes del flyer acá
-- (hasta 5 MB) y ben_campanias.ruta_flyer lo vuelve a escribir al disco cuando falta.
--
-- Tabla aparte (no una columna de ben_campania) para que los SELECT c.* de la
-- lista y la ficha no traigan el archivo. Cae con la campaña (FK CASCADE).
-- Idempotente. Se puede correr antes o después de subir el código.

USE sindicato;
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS ben_campania_flyer (
  id_campania  INT          NOT NULL PRIMARY KEY,
  archivo      VARCHAR(255) NOT NULL COMMENT 'El mismo ben_campania.flyer_archivo: si no coincide, la copia es de un flyer anterior',
  datos        MEDIUMBLOB   NOT NULL,
  guardado     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_ben_campania_flyer FOREIGN KEY (id_campania) REFERENCES ben_campania (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Copia del flyer de la campaña, por si el disco del servidor se vacía';

SHOW COLUMNS FROM ben_campania_flyer;
