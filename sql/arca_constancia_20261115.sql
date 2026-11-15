-- =============================================================================
-- Constancia de inscripción de ARCA guardada por CUIT (15/11/2026)
--
-- Cada «Consultar ARCA» de empleadores y proveedores (y «Actualizar desde ARCA») (ws_sr_constancia_inscripcion,
-- arca_constancia.py) guarda lo que informó ARCA del CUIT: estado de la clave,
-- condición de IVA, impuestos y actividades registradas. La ficha del empleador
-- lo muestra en la solapa ARCA. Las mismas tablas que gestion_adm tiene en
-- contable (sql/arca_constancia_20261114.sql de allá), acá en `sindicato`.
--
-- Va por CUIT y no por id: queda guardada aunque el empleador todavía no esté
-- dado de alta (se consulta antes de crearlo) y sirve igual para un proveedor.
--
-- Sin estas tablas la consulta funciona igual: no se guarda y la solapa lo dice.
-- Se corre a mano, una vez. app_sindicato tiene permiso sobre todo el esquema.
-- =============================================================================

USE sindicato;

CREATE TABLE IF NOT EXISTS arca_constancia (
    cuit                  CHAR(11)     NOT NULL,
    razon_social          VARCHAR(200) NULL,
    estado_clave          VARCHAR(30)  NULL,
    tipo_persona          VARCHAR(30)  NULL,
    condicion_iva         VARCHAR(60)  NULL,
    categoria_monotributo VARCHAR(100) NULL,
    consultado            DATETIME     NOT NULL,
    id_usuario            INT          NULL COMMENT 's_usuarios.id',
    PRIMARY KEY (cuit)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Última constancia de inscripción de ARCA consultada por CUIT';

CREATE TABLE IF NOT EXISTS arca_constancia_impuestos (
    id            INT          NOT NULL AUTO_INCREMENT,
    cuit          CHAR(11)     NOT NULL,
    id_impuesto   INT          NULL,
    descripcion   VARCHAR(200) NULL,
    estado        VARCHAR(10)  NULL COMMENT 'estadoImpuesto de ARCA (AC = activo)',
    periodo_desde VARCHAR(8)   NULL COMMENT 'AAAAMM',
    PRIMARY KEY (id),
    KEY ix_arca_constancia_impuestos_cuit (cuit)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS arca_constancia_actividades (
    id            INT          NOT NULL AUTO_INCREMENT,
    cuit          CHAR(11)     NOT NULL,
    id_actividad  BIGINT       NULL,
    descripcion   VARCHAR(300) NULL,
    nomenclador   INT          NULL,
    orden         INT          NULL COMMENT '1 = actividad principal',
    periodo_desde VARCHAR(8)   NULL COMMENT 'AAAAMM',
    PRIMARY KEY (id),
    KEY ix_arca_constancia_actividades_cuit (cuit)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Lo que «Actualizar desde ARCA» (empleadores_arca.py) cambió en el domicilio
-- fiscal de p_empresas (fdom_*): campo por campo, con el valor de antes. Sin
-- esta tabla la actualización no se corre.
CREATE TABLE IF NOT EXISTS arca_constancia_cambios (
    id          INT          NOT NULL AUTO_INCREMENT,
    fecha       DATETIME     NOT NULL,
    cuit        CHAR(11)     NOT NULL,
    id_empresa  INT          NULL COMMENT 'p_empresas.id',
    campo       VARCHAR(40)  NOT NULL,
    antes       VARCHAR(200) NULL,
    despues     VARCHAR(200) NULL,
    id_usuario  INT          NULL COMMENT 's_usuarios.id',
    PRIMARY KEY (id),
    KEY ix_arca_constancia_cambios_cuit (cuit),
    KEY ix_arca_constancia_cambios_fecha (fecha)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- En `sindicato` ya estaban creadas el 15/11/2026 en utf8mb4_unicode_ci (la
-- primera versión del script de gestion_adm, corrida acá); el resto de la base
-- es utf8mb4_0900_ai_ci. Convertirlas no hace nada si ya están bien.
ALTER TABLE arca_constancia             CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
ALTER TABLE arca_constancia_impuestos   CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
ALTER TABLE arca_constancia_actividades CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

SELECT table_name, table_collation FROM information_schema.tables
 WHERE table_schema = DATABASE() AND table_name LIKE 'arca_constancia%';
