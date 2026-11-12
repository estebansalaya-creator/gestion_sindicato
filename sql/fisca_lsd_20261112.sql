-- =============================================================================
-- fisca_lsd_20261112.sql — Las empresas presentan su Libro de Sueldos Digital
-- y la cuota sindical se liquida con él
-- =============================================================================
--
-- Pedido del 12/11/2026: una interfaz para que las empresas suban el archivo de
-- liquidación del Libro de Sueldos Digital de ARCA y se complete sola la
-- planilla de la cuota sindical con los afiliados activos de AEDA.
--   · Cada empresa entra con un ENLACE PERSONAL que se genera en Empleadores
--     (solapa Cuota sindical) y se le manda por mail. Sin usuario ni clave.
--   · Lo que la empresa presenta ES la liquidación de ese CUIT y período
--     (origen «lsd»): reemplaza a la de DDJJ de OSEDA, y «Liquidar» por DDJJ
--     ya no la pisa.
--
--   fisca_enlace_empresa     un enlace por empresa; se guarda el hash del token,
--                            nunca el token
--   fisca_lsd_presentacion   cada archivo subido, con el archivo mismo
--   fisca_liquidacion        origen + 'lsd'
--   fisca_liquidacion_detalle fuente + 'lsd' (está en el archivo) y 'sin_lsd'
--                            (activo del empleador que no está en el archivo)
--   s_menu                   Fiscalización de Cuotas → Presentaciones LSD
--
-- Requiere sql/fisca_liquidacion_ddjj_20261112.sql. Correrlo ENTERO: en DBeaver,
-- «Ejecutar script» (Alt+X). Idempotente.

USE sindicato;
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS fisca_enlace_empresa (
  id              INT NOT NULL AUTO_INCREMENT,
  cuit            VARCHAR(11) NOT NULL,
  id_empresa      INT NULL,
  token_hash      CHAR(64) NOT NULL              COMMENT 'SHA-256 del token del enlace: el token no se guarda',
  pista           CHAR(4) NOT NULL               COMMENT 'Últimos 4 caracteres del token, para reconocer el enlace',
  creado          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  id_usuario      INT NULL                       COMMENT 'Quién lo generó',
  revocado        DATETIME NULL,
  id_usuario_revoca INT NULL,
  ultimo_uso      DATETIME NULL,
  usos            INT NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY uq_enlace_token (token_hash),
  KEY ix_enlace_cuit (cuit, revocado),
  CONSTRAINT fk_enlace_empresa FOREIGN KEY (id_empresa) REFERENCES p_empresas (id),
  CONSTRAINT fk_enlace_usuario FOREIGN KEY (id_usuario) REFERENCES s_usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Enlace personal de cada empresa para presentar su Libro de Sueldos Digital';

CREATE TABLE IF NOT EXISTS fisca_lsd_presentacion (
  id              INT NOT NULL AUTO_INCREMENT,
  cuit            VARCHAR(11) NOT NULL,
  periodo         CHAR(6) NOT NULL               COMMENT 'AAAAMM, del registro 01',
  envio           CHAR(2) NOT NULL               COMMENT 'SJ liquidación + F931 · RE solo F931',
  tipo_liq        CHAR(1) NULL                   COMMENT 'M mensual · Q quincenal · S semanal',
  nro_liquidacion INT NULL,
  archivo_nombre  VARCHAR(200) NOT NULL,
  archivo_sha256  CHAR(64) NOT NULL,
  archivo         MEDIUMBLOB NOT NULL            COMMENT 'El archivo tal como lo subió la empresa',
  trabajadores    INT NOT NULL DEFAULT 0         COMMENT 'Trabajadores del archivo (registros 04)',
  no_afiliados    INT NOT NULL DEFAULT 0         COMMENT 'De esos, los que no son afiliados de AEDA en el período',
  afiliados_activos INT NOT NULL DEFAULT 0       COMMENT 'Titulares activos de AEDA con relación laboral con el CUIT',
  activos_en_archivo INT NOT NULL DEFAULT 0,
  afiliados       INT NOT NULL DEFAULT 0         COMMENT 'Renglones con cuota',
  remuneracion    DECIMAL(18,2) NOT NULL DEFAULT 0,
  importe         DECIMAL(15,2) NOT NULL DEFAULT 0,
  retenido        DECIMAL(15,2) NULL             COMMENT 'Cuota sindical retenida en los recibos (concepto 810004), si viene',
  estado          ENUM('borrador','presentada','reemplazada','anulada') NOT NULL DEFAULT 'borrador',
  origen          ENUM('empresa','interno') NOT NULL COMMENT 'La subió la empresa por su enlace o un usuario del sindicato',
  id_enlace       INT NULL,
  id_usuario      INT NULL,
  ip              VARCHAR(45) NULL,
  id_liquidacion  INT NULL,
  presentado      DATETIME NULL,
  observaciones   VARCHAR(500) NULL,
  creado          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actualizado     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_lsd_cuit_periodo (cuit, periodo, estado),
  KEY ix_lsd_periodo (periodo, estado),
  CONSTRAINT fk_lsd_enlace FOREIGN KEY (id_enlace) REFERENCES fisca_enlace_empresa (id),
  CONSTRAINT fk_lsd_usuario FOREIGN KEY (id_usuario) REFERENCES s_usuarios (id),
  CONSTRAINT fk_lsd_liquidacion FOREIGN KEY (id_liquidacion) REFERENCES fisca_liquidacion (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Archivos de Libro de Sueldos Digital presentados para la cuota sindical';

ALTER TABLE fisca_liquidacion
  MODIFY COLUMN origen ENUM('nomina','ddjj','aeda','lsd') NOT NULL COMMENT 'De dónde salió la remuneración';
ALTER TABLE fisca_liquidacion_detalle
  MODIFY COLUMN fuente ENUM('nomina','ddjj','aeda','sin_ddjj','lsd','sin_lsd') NOT NULL;

-- Menú: Fiscalización de Cuotas → Presentaciones LSD (id 7, o el siguiente libre)
SET @id := (SELECT id FROM s_menu WHERE url = '/fiscalizacion/lsd' LIMIT 1);
SET @id := COALESCE(@id, IF(EXISTS (SELECT 1 FROM s_menu WHERE id = 7), (SELECT MAX(id) + 1 FROM s_menu), 7));
INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (@id, 1, 'Presentaciones LSD', '/fiscalizacion/lsd', NULL, 6, 2, 1)
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
   AND ((table_name = 'fisca_liquidacion' AND column_name = 'origen')
     OR (table_name = 'fisca_liquidacion_detalle' AND column_name = 'fuente'))
UNION ALL
SELECT table_name, '(tabla)', table_comment FROM information_schema.tables
 WHERE table_schema = DATABASE() AND table_name IN ('fisca_enlace_empresa', 'fisca_lsd_presentacion');
SELECT m.id, m.nombre, m.url, m.orden FROM s_menu m WHERE m.padre_id = 1 ORDER BY m.orden;
