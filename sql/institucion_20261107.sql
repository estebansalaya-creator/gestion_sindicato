-- Datos del sindicato — 07/11/2026
--
-- Una sola fila con los datos propios: identificación gremial, datos fiscales,
-- condición de agente de retención, domicilio, autoridades y logo. Es el
-- equivalente de `os_parametros` de gestion_adm (Parámetros de la Obra
-- Social), con los campos de un gremio en lugar de los de una obra social:
-- personería e inscripción gremial en vez de RNOS y código de OS.
--
-- Los campos de retenciones se llaman igual que en `os_parametros` (ret_iva,
-- ret_ganancias, ret_arca_tasa_ivaid, …): el motor de retenciones de
-- gestion_adm se podrá traer cambiando solo el nombre de la tabla.
--
-- Pantalla: Administración del Sistema → Datos del Sindicato (/admin/institucion).
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X). Idempotente.

USE sindicato;

CREATE TABLE IF NOT EXISTS s_institucion (
  id                     TINYINT      NOT NULL DEFAULT 1 COMMENT 'Siempre 1: hay una sola fila',
  -- Identificación
  nombre                 VARCHAR(150) NOT NULL COMMENT 'Denominación completa',
  sigla                  VARCHAR(20)  NULL,
  cuit                   CHAR(11)     NULL,
  personeria_gremial     VARCHAR(60)  NULL COMMENT 'N° de personería gremial (MTEySS)',
  inscripcion_gremial    VARCHAR(60)  NULL COMMENT 'N° de inscripción gremial',
  ambito                 VARCHAR(250) NULL COMMENT 'Ámbito personal y territorial de representación',
  -- Datos fiscales
  condicion_iva          INT          NULL COMMENT 'arca_responsable_tipo.codigo',
  nro_iibb               VARCHAR(30)  NULL,
  inicio_actividades     DATE         NULL,
  exencion_ganancias     VARCHAR(100) NULL COMMENT 'Certificado o resolución de exención en Ganancias',
  exencion_ganancias_vto DATE         NULL,
  -- Agente de retención (mismos nombres que os_parametros)
  ret_iva                TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '1 = Agente de Retención IVA (RG 2854)',
  ret_iva_alicuota       DECIMAL(5,2) NULL COMMENT 'Alícuota por defecto, si el proveedor no tiene una propia',
  ret_ganancias          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '1 = Agente de Retención Ganancias (RG 830)',
  ret_ganancias_alicuota DECIMAL(5,2) NULL,
  ret_arca_tasa_ivaid    INT          NULL COMMENT 'Tasa de IVA con la que se netea la orden para la base de Ganancias',
  ret_iibb               TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '1 = Agente de Retención Ingresos Brutos',
  ret_iibb_alicuota      DECIMAL(5,2) NULL,
  ret_iibb_regimen       VARCHAR(20)  NULL COMMENT 'SIRCAR / SIRCREB / ARBA / AGIP / OTRO',
  ret_suss               TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '1 = Agente de Retención SUSS (RG 1556)',
  ret_suss_alicuota      DECIMAL(5,2) NULL,
  nro_resolucion_ret     VARCHAR(100) NULL COMMENT 'Resolución o constancia que lo designa agente',
  -- Domicilio y contacto
  domicilio              VARCHAR(200) NULL,
  localidad              VARCHAR(100) NULL,
  provincia              SMALLINT     NULL COMMENT 'p_provincia.codigo',
  cp                     VARCHAR(8)   NULL,
  telefono               VARCHAR(50)  NULL,
  email                  VARCHAR(100) NULL,
  web                    VARCHAR(100) NULL,
  -- Autoridades (firman los documentos)
  secretario_general     VARCHAR(150) NULL,
  secretario_adjunto     VARCHAR(150) NULL,
  tesorero               VARCHAR(150) NULL COMMENT 'Tesorero o secretario de finanzas',
  -- Logo
  logo_path              VARCHAR(255) NULL COMMENT 'Relativa a SIND_ADJUNTOS',
  actualizado_at         DATETIME     NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  actualizado_por        VARCHAR(100) NULL,
  PRIMARY KEY (id),
  CONSTRAINT ck_institucion_una_fila CHECK (id = 1),
  CONSTRAINT fk_institucion_cond_iva  FOREIGN KEY (condicion_iva)       REFERENCES arca_responsable_tipo (codigo),
  CONSTRAINT fk_institucion_tasa_iva  FOREIGN KEY (ret_arca_tasa_ivaid) REFERENCES arca_tasa_iva (id),
  CONSTRAINT fk_institucion_provincia FOREIGN KEY (provincia)           REFERENCES p_provincia (codigo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Datos del sindicato: identificación, fiscales, agente de retención, autoridades. Una fila.';

-- Menú: Administración del Sistema → Datos del Sindicato, para Administrador.
INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (207, 200, 'Datos del Sindicato', '/admin/institucion', NULL, 6, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url),
  padre_id = VALUES(padre_id), orden = VALUES(orden), activo = 1;
UPDATE s_menu SET orden = 7 WHERE id = 206;   -- la guía de estilos, al final

INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT m.id, r.id
  FROM s_menu m JOIN s_roles r ON r.id = 1
 WHERE m.id = 207
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = m.id AND x.rol_id = r.id);
