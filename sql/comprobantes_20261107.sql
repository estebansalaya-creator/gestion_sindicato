-- Comprobantes de proveedores y mesa de entradas — 07/11/2026
--
-- Lo que necesitan la carga de comprobantes (comprobantes.py), Comprobantes
-- ARCA (mis_comprobantes.py) y la mesa de entradas (mesa.py). Las tablas del
-- circuito —f_comprobantes_arca, me_expedientes, me_expediente_movimientos,
-- c_pasivo_liquidacion— ya estaban: vinieron de `contable` con la estructura
-- de gestion_adm.
--
--   1. f_mis_comprobantes: lo que ARCA informa como recibido (export de Mis
--      Comprobantes). Misma estructura que en gestion_adm. Faltaba.
--   2. Menú, dentro de Proveedores:
--        32 Carga de Comprobantes   /comprobantes/carga   (ya estaba; cambia la URL)
--        34 Comprobantes ARCA       /comprobantes/arca    (nueva)
--        35 Mesa de Entradas        /mesa                 (nueva)
--      Con los mismos roles que la carga: Administrador y Supervisor. Los
--      permisos se leen al iniciar sesión: hay que volver a entrar.
--
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X). Idempotente.

USE sindicato;

-- 1 ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS f_mis_comprobantes (
  id               INT           NOT NULL AUTO_INCREMENT,
  fecha_emision    DATE          NOT NULL,
  tipo_comprobante VARCHAR(3)    NOT NULL,
  punto_de_venta   VARCHAR(5)    NOT NULL,
  numero           VARCHAR(8)    NOT NULL,
  cuit_emisor      CHAR(11)      NOT NULL,
  razon_social     VARCHAR(200)  DEFAULT NULL,
  importe_neto     DECIMAL(15,2) NOT NULL DEFAULT '0.00',
  importe_no_grav  DECIMAL(15,2) NOT NULL DEFAULT '0.00',
  importe_exento   DECIMAL(15,2) NOT NULL DEFAULT '0.00',
  importe_iva      DECIMAL(15,2) NOT NULL DEFAULT '0.00',
  importe_otros    DECIMAL(15,2) NOT NULL DEFAULT '0.00',
  importe_total    DECIMAL(15,2) NOT NULL DEFAULT '0.00',
  moneda           VARCHAR(3)    NOT NULL DEFAULT 'PES',
  tipo_de_cambio   DECIMAL(10,4) NOT NULL DEFAULT '1.0000',
  cae              VARCHAR(14)   DEFAULT NULL,
  id_comprobante   INT           DEFAULT NULL COMMENT 'f_comprobantes_arca cuando ya fue cargado',
  ignorado         TINYINT(1)    NOT NULL DEFAULT '0' COMMENT 'marcado como no corresponde cargar',
  nombre_archivo   VARCHAR(200)  DEFAULT NULL,
  importado        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_mis_comp (cuit_emisor, tipo_comprobante, punto_de_venta, numero),
  KEY idx_mis_cuit (cuit_emisor),
  KEY idx_mis_fecha (fecha_emision),
  KEY idx_mis_pend (id_comprobante, ignorado)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Comprobantes recibidos según ARCA (export de Mis Comprobantes)';

-- 2 ─────────────────────────────────────────────────────────────────────────
UPDATE s_menu SET nombre = 'Carga de Comprobantes', url = '/comprobantes/carga', orden = 2
 WHERE id = 32;
UPDATE s_menu SET orden = 5 WHERE id = 33;

INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo) VALUES
  (34, 30, 'Comprobantes ARCA', '/comprobantes/arca', NULL, 3, 2, 1),
  (35, 30, 'Mesa de Entradas',  '/mesa',              NULL, 4, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url),
  padre_id = VALUES(padre_id), orden = VALUES(orden), activo = 1;

INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT m.id, r.id
  FROM s_menu m
  JOIN s_roles r ON r.id IN (1, 2)
 WHERE m.id IN (32, 34, 35) AND r.activo = 1
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = m.id AND x.rol_id = r.id);

-- Control
SELECT m.id, m.nombre, m.url, m.orden, GROUP_CONCAT(r.nombre ORDER BY r.id) AS roles
  FROM s_menu m
  LEFT JOIN s_menu_rol mr ON mr.menu_id = m.id
  LEFT JOIN s_roles r ON r.id = mr.rol_id
 WHERE m.padre_id = 30
 GROUP BY m.id, m.nombre, m.url, m.orden
 ORDER BY m.orden;
SELECT cuit AS cuit_del_sindicato FROM s_institucion;
