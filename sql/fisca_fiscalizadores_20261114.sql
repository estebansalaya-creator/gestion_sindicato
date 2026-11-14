-- =============================================================================
-- fisca_fiscalizadores_20261114.sql — ABM de fiscalizadores
-- =============================================================================
--
-- Pedido del 14/11/2026: los fiscalizadores (inspectores) que labran las actas
-- de fiscalización salen de un catálogo, como f_inspectores de gestion_adm. El
-- acta guarda el fiscalizador (id_fiscalizador) y, además, su nombre y DNI como
-- quedaron impresos (inspector, inspector_dni): corregir la ficha después no
-- cambia un acta ya labrada.
--
-- Uno que figura en un acta no se elimina: se desactiva y deja de ofrecerse.
-- Los nombres que ya se escribieron a mano en actas pasan al catálogo.
--
-- Menú 16: Fiscalización de Cuotas → Fiscalizadores (Administrador y Supervisor).
-- Requiere sql/fisca_actas_20261114.sql. Correrlo ENTERO (Alt+X), como root. Idempotente.

USE sindicato;
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS fisca_fiscalizador (
  id               INT NOT NULL AUTO_INCREMENT,
  apellido_nombres VARCHAR(150) NOT NULL,
  dni              VARCHAR(20) NULL,
  cargo            VARCHAR(100) NULL,
  telefono         VARCHAR(50) NULL,
  email            VARCHAR(150) NULL,
  id_usuario       INT NULL                 COMMENT 'Su usuario del sistema, si tiene',
  observaciones    VARCHAR(500) NULL,
  activo           TINYINT(1) NOT NULL DEFAULT 1,
  creado           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actualizado      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_fisca_fiscalizador_dni (dni),
  KEY ix_fisca_fiscalizador_nombre (apellido_nombres),
  CONSTRAINT fk_fisca_fiscalizador_usuario FOREIGN KEY (id_usuario) REFERENCES s_usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Fiscalizadores de cuota sindical (labran las actas)';

DROP PROCEDURE IF EXISTS _fiscalizador_columna;
DELIMITER //
CREATE PROCEDURE _fiscalizador_columna()
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'sindicato'
                    AND table_name = 'fisca_acta' AND column_name = 'id_fiscalizador') THEN
    ALTER TABLE fisca_acta
      ADD COLUMN id_fiscalizador INT NULL COMMENT 'fisca_fiscalizador; inspector e inspector_dni son lo impreso' AFTER con_pagos_tarde,
      ADD KEY ix_fisca_acta_fiscalizador (id_fiscalizador),
      ADD CONSTRAINT fk_fisca_acta_fiscalizador FOREIGN KEY (id_fiscalizador) REFERENCES fisca_fiscalizador (id);
  END IF;
END //
DELIMITER ;
CALL _fiscalizador_columna();
DROP PROCEDURE _fiscalizador_columna;

-- Lo escrito a mano en las actas, al catálogo (uno por nombre) y el acta, a él.
INSERT INTO fisca_fiscalizador (apellido_nombres, dni)
SELECT a.inspector, MAX(a.inspector_dni)
  FROM fisca_acta a
 WHERE a.inspector IS NOT NULL AND a.inspector <> ''
   AND NOT EXISTS (SELECT 1 FROM fisca_fiscalizador f WHERE f.apellido_nombres = a.inspector)
 GROUP BY a.inspector;
UPDATE fisca_acta a JOIN fisca_fiscalizador f ON f.apellido_nombres = a.inspector
   SET a.id_fiscalizador = f.id
 WHERE a.id_fiscalizador IS NULL;

SET @id := (SELECT id FROM s_menu WHERE url = '/fiscalizacion/fiscalizadores' LIMIT 1);
SET @id := COALESCE(@id, IF(EXISTS (SELECT 1 FROM s_menu WHERE id = 16), (SELECT MAX(id) + 1 FROM s_menu), 16));
INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (@id, 1, 'Fiscalizadores', '/fiscalizacion/fiscalizadores', NULL, 11, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url), padre_id = VALUES(padre_id),
  orden = VALUES(orden), activo = 1;
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT @id, r.id FROM s_roles r WHERE r.nombre IN ('Administrador', 'Supervisor')
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = @id AND x.rol_id = r.id);

SELECT m.id, m.nombre, m.url, m.orden FROM s_menu m WHERE m.padre_id = 1 ORDER BY m.orden;
