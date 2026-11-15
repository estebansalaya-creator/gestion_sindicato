-- =============================================================================
-- fisca_novedades_empresa_20261115.sql — La empresa, por su enlace: nómina,
-- altas y bajas, y la cuota cargada a mano
-- =============================================================================
--
-- Pedido del 15/11/2026: cuando la empresa entra por su enlace (fisca_lsd.py)
--   · ve su nómina: los afiliados que según el padrón trabajan ahí;
--   · informa el ALTA de un CUIL que corresponde cuota, con fecha de alta, y
--     puede adjuntar la ficha de afiliación firmada; si el CUIL no está en el
--     padrón, con apellido y nombre;
--   · informa la BAJA de un CUIL que el padrón tiene activo, con la fecha;
--   · carga A MANO las remuneraciones del mes, sin el archivo del Libro de
--     Sueldos Digital.
-- Las altas y bajas quedan PENDIENTES: el sindicato las aprueba o rechaza en
-- Presentaciones LSD, y recién ahí cambia el padrón (decidido el 15/11/2026).
-- La cuota del mes ya toma el alta pendiente; la baja, solo cuando se aprueba.
--
--   fisca_novedad_empresa       las altas y bajas informadas
--   fisca_lsd_presentacion      + carga ('archivo' | 'manual'); el archivo
--                               pasa a ser opcional
--   fisca_lsd_manual            las remuneraciones de una carga manual
--   fisca_liquidacion_detalle   fuente + 'manual' (cargada a mano) y 'alta'
--                               (alta informada por la empresa, pendiente)
--   p_tipo_documentacion        «Ficha de afiliación» (al aprobar un alta, la
--                               ficha adjunta pasa a la documentación del afiliado)
--
-- Requiere sql/fisca_lsd_20261112.sql. Correrlo ENTERO: en DBeaver, «Ejecutar
-- script» (Alt+X). Idempotente.

USE sindicato;
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS fisca_novedad_empresa (
  id               INT NOT NULL AUTO_INCREMENT,
  cuit             VARCHAR(11) NOT NULL,
  tipo             ENUM('alta','baja') NOT NULL,
  cuil             VARCHAR(11) NOT NULL,
  apellido_nombres VARCHAR(100) NULL      COMMENT 'El que informó la empresa (alta de alguien que no está en el padrón)',
  fecha            DATE NOT NULL          COMMENT 'Fecha de alta o de baja en la empresa',
  observaciones    VARCHAR(300) NULL      COMMENT 'Lo que escribió la empresa',
  ficha_nombre     VARCHAR(255) NULL      COMMENT 'Ficha de afiliación adjunta: nombre original',
  ficha_archivo    VARCHAR(80) NULL       COMMENT 'Nombre generado en SIND_ADJUNTOS/novedades_empresa/',
  ficha_bytes      INT NULL,
  estado           ENUM('pendiente','aprobada','rechazada','retirada') NOT NULL DEFAULT 'pendiente',
  motivo           VARCHAR(300) NULL      COMMENT 'Por qué se rechazó',
  resultado        VARCHAR(300) NULL      COMMENT 'Qué hizo la aprobación en el padrón',
  id_afiliado      INT NULL               COMMENT 'El titular del padrón (el que ya estaba o el que se creó al aprobar)',
  id_relacion      INT NULL               COMMENT 'La relación laboral creada (alta) o cerrada (baja)',
  origen           ENUM('empresa','interno') NOT NULL DEFAULT 'empresa',
  id_enlace        INT NULL,
  ip               VARCHAR(45) NULL,
  creado           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  resuelto         DATETIME NULL,
  id_usuario       INT NULL               COMMENT 'Quién la resolvió',
  PRIMARY KEY (id),
  KEY ix_nov_cuit (cuit, estado),
  KEY ix_nov_estado (estado, creado),
  KEY ix_nov_cuil (cuil),
  CONSTRAINT fk_nov_enlace FOREIGN KEY (id_enlace) REFERENCES fisca_enlace_empresa (id),
  CONSTRAINT fk_nov_usuario FOREIGN KEY (id_usuario) REFERENCES s_usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Altas y bajas de afiliados que informan las empresas por su enlace';

-- La carga manual: sin archivo
SET @hay := (SELECT COUNT(*) FROM information_schema.columns
              WHERE table_schema = DATABASE() AND table_name = 'fisca_lsd_presentacion' AND column_name = 'carga');
SET @sql := IF(@hay = 0,
  'ALTER TABLE fisca_lsd_presentacion
     ADD COLUMN carga ENUM(''archivo'',''manual'') NOT NULL DEFAULT ''archivo''
         COMMENT ''archivo: el del Libro de Sueldos Digital · manual: remuneraciones cargadas a mano'' AFTER periodo',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

ALTER TABLE fisca_lsd_presentacion
  MODIFY COLUMN envio          CHAR(2) NULL          COMMENT 'SJ liquidación + F931 · RE solo F931 (vacío en la carga manual)',
  MODIFY COLUMN archivo_nombre VARCHAR(200) NOT NULL,
  MODIFY COLUMN archivo_sha256 CHAR(64) NULL,
  MODIFY COLUMN archivo        MEDIUMBLOB NULL       COMMENT 'El archivo tal como lo subió la empresa (vacío en la carga manual)';

CREATE TABLE IF NOT EXISTS fisca_lsd_manual (
  id_presentacion INT NOT NULL,
  cuil            VARCHAR(11) NOT NULL,
  remuneracion    DECIMAL(18,2) NOT NULL DEFAULT 0,
  PRIMARY KEY (id_presentacion, cuil),
  CONSTRAINT fk_lsd_manual_pres FOREIGN KEY (id_presentacion) REFERENCES fisca_lsd_presentacion (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Remuneraciones cargadas a mano en una presentación (carga = manual)';

ALTER TABLE fisca_liquidacion_detalle
  MODIFY COLUMN fuente ENUM('nomina','ddjj','aeda','sin_ddjj','lsd','sin_lsd','manual','alta') NOT NULL;

INSERT INTO p_tipo_documentacion (codigo, descripcion, aplica_a, obligatorio, activo, orden)
SELECT 'ficha_afiliacion', 'Ficha de afiliación', 'afiliado', 0, 1, 0
  FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM p_tipo_documentacion WHERE codigo = 'ficha_afiliacion');

-- Verificación ----------------------------------------------------------------
SELECT table_name, column_name, column_type
  FROM information_schema.columns
 WHERE table_schema = DATABASE()
   AND ((table_name = 'fisca_lsd_presentacion' AND column_name IN ('carga', 'envio', 'archivo'))
     OR (table_name = 'fisca_liquidacion_detalle' AND column_name = 'fuente'))
UNION ALL
SELECT table_name, '(tabla)', table_comment FROM information_schema.tables
 WHERE table_schema = DATABASE() AND table_name IN ('fisca_novedad_empresa', 'fisca_lsd_manual');
SELECT id_tipo_doc, codigo, descripcion FROM p_tipo_documentacion WHERE codigo = 'ficha_afiliacion';
