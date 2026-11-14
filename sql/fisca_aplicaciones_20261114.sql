-- =============================================================================
-- fisca_aplicaciones_20261114.sql — Aplicación de cobros a las cuotas
-- =============================================================================
--
-- Qué parte de cada cobro (un renglón de orden de ingreso con el CUIT del
-- empleador: recibo de cuota sindical, AEDA-RC, ingreso por fiscalización)
-- cancela qué liquidación de cuota sindical (`fisca_liquidacion`, un CUIT y un
-- período). Hasta acá lo cobrado cancelaba solo su propio período; con esto un
-- cobro se puede aplicar a otro período (la deuda más vieja, por ejemplo) y lo
-- pagado de más queda como saldo a favor del empleador, para aplicar después.
--
--   saldo del período = liquidado − aplicado
--   cobro sin aplicar = importe − aplicado
--   saldo del empleador = liquidado − cobrado (no cambia con las aplicaciones)
--
-- Solo cuentan las aplicaciones de órdenes no anuladas a liquidaciones
-- vigentes. Desaplicar deja el rastro en fisca_aplicacion_baja (quién, cuándo
-- y por qué). La primera aplicación de lo que ya está cargado la hace
-- `python aplicar_cobros.py --aplicar` (cada cobro a su período).
--
-- Menú 13: Empleadores → Aplicación de Cobros (Administrador y Supervisor).
--
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X). Idempotente.

USE sindicato;
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS fisca_aplicacion (
  id              INT NOT NULL AUTO_INCREMENT,
  id_detalle      INT NOT NULL              COMMENT 'ingreso_ordenes_detalle: el cobro',
  id_liquidacion  INT NOT NULL              COMMENT 'fisca_liquidacion: la cuota que cancela',
  importe         DECIMAL(15,2) NOT NULL,
  origen          ENUM('periodo','deuda_vieja','recibo','manual') NOT NULL
                  COMMENT 'periodo = a su propio período (automática); deuda_vieja = lo que sobraba, a la deuda más vieja; recibo = al emitirlo; manual = desde la pantalla',
  fecha           DATE NOT NULL             COMMENT 'Fecha de la aplicación',
  observaciones   VARCHAR(255) NULL,
  id_usuario      INT NULL,
  creado          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_fisca_aplic (id_detalle, id_liquidacion),
  KEY ix_fisca_aplic_liq (id_liquidacion),
  CONSTRAINT fk_fisca_aplic_detalle FOREIGN KEY (id_detalle) REFERENCES ingreso_ordenes_detalle (id),
  CONSTRAINT fk_fisca_aplic_liq FOREIGN KEY (id_liquidacion) REFERENCES fisca_liquidacion (id),
  CONSTRAINT fk_fisca_aplic_usuario FOREIGN KEY (id_usuario) REFERENCES s_usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Aplicación de cobros a las liquidaciones de cuota sindical';

CREATE TABLE IF NOT EXISTS fisca_aplicacion_baja (
  id              INT NOT NULL AUTO_INCREMENT,
  id_aplicacion   INT NOT NULL              COMMENT 'El id que tenía en fisca_aplicacion',
  id_detalle      INT NOT NULL,
  id_liquidacion  INT NOT NULL,
  importe         DECIMAL(15,2) NOT NULL    COMMENT 'Lo desaplicado (toda la aplicación o una parte)',
  origen          VARCHAR(20) NOT NULL      COMMENT 'El origen de la aplicación',
  fecha_aplicacion DATE NULL,
  motivo          VARCHAR(255) NOT NULL,
  id_usuario      INT NULL,
  fecha_baja      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_fisca_aplic_baja_det (id_detalle),
  KEY ix_fisca_aplic_baja_liq (id_liquidacion),
  CONSTRAINT fk_fisca_aplic_baja_usuario FOREIGN KEY (id_usuario) REFERENCES s_usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Rastro de lo desaplicado de fisca_aplicacion';

-- Los cobros de AEDA que importar_aeda_fondos.py trajo después del 12/11/2026
-- entraron sin el CUIT en el renglón (lo tenía solo la descripción).
UPDATE ingreso_ordenes_detalle
   SET cuit = SUBSTRING(REGEXP_SUBSTR(descripcion, 'CUIT [0-9]{11}'), 6)
 WHERE cuit IS NULL AND descripcion REGEXP 'CUIT [0-9]{11}';

-- Menú: Empleadores → Aplicación de Cobros.
SET @id := (SELECT id FROM s_menu WHERE url = '/empleadores/cc/aplicaciones' LIMIT 1);
SET @id := COALESCE(@id, IF(EXISTS (SELECT 1 FROM s_menu WHERE id = 13), (SELECT MAX(id) + 1 FROM s_menu), 13));
INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (@id, 10, 'Aplicación de Cobros', '/empleadores/cc/aplicaciones',
        (SELECT x.icono_svg FROM (SELECT icono_svg FROM s_menu WHERE url = '/proveedores/cc/aplicaciones' LIMIT 1) x),
        3, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url),
  padre_id = VALUES(padre_id), orden = VALUES(orden), activo = 1;

INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT @id, r.id FROM s_roles r
 WHERE r.nombre IN ('Administrador', 'Supervisor')
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = @id AND x.rol_id = r.id);

SELECT m.id, m.nombre, m.url, m.orden FROM s_menu m WHERE m.padre_id = 10 ORDER BY m.orden;
