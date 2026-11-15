-- =============================================================================
-- arca_wsaa_ta — el token de acceso de ARCA (WSAA), uno por servicio y CUIT.
--
-- ARCA no entrega un token nuevo mientras el anterior siga vigente (hasta 12
-- horas): contesta «El CEE ya posee un TA válido». El IIS local y Railway usan
-- esta misma base; con el token guardado en un archivo de cada servidor, el
-- segundo que lo pidiera se quedaba sin consultar ARCA hasta que venciera el
-- del primero. Guardado acá lo leen los dos (arca_wscdc.token).
--
-- Servicios: wscdc (constatación), ws_sr_padron_a13 (afiliados),
-- ws_sr_constancia_inscripcion (empleadores y proveedores).
--
-- Se corre a mano, una vez, con un usuario que pueda crear tablas. El usuario
-- de la aplicación (app_sindicato) ya tiene SELECT/INSERT/UPDATE/DELETE.
-- =============================================================================

USE sindicato;

CREATE TABLE IF NOT EXISTS arca_wsaa_ta (
    servicio     VARCHAR(60)  NOT NULL COMMENT 'wscdc, ws_sr_padron_a13, ws_sr_constancia_inscripcion',
    cuit         CHAR(11)     NOT NULL COMMENT 'CUIT del certificado (SIND_ARCA_CUIT)',
    token        TEXT         NOT NULL,
    sign         TEXT         NOT NULL,
    expira       DATETIME     NOT NULL COMMENT 'vencimiento, en UTC',
    actualizado  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (servicio, cuit)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Token de acceso de ARCA (WSAA), compartido entre servidores';
