-- =============================================================================
-- cc_proveedores_aplicaciones_20261111.sql — Cuenta corriente de proveedores
-- y aplicación de comprobantes
-- =============================================================================
--
-- Pantallas de cc_proveedores.py (portadas de gestion_adm/cc_proveedores_routes.py):
--
--   Proveedores → Cuenta Corriente (33, /proveedores/cc)       ya estaba en el menú
--   Proveedores → Aplicación de Comprobantes (36, nueva)       /proveedores/cc/aplicaciones
--
-- Aplicar = cancelar una factura con una nota de crédito o con un pago que
-- tiene saldo a cuenta, sin mover fondos (c_pasivo_aplicacion, origen
-- «manual»). Desaplicar la borra o le baja el importe; el rastro (cómo estaba,
-- cuánto se soltó, quién y por qué) queda en c_pasivo_aplicacion_baja, la
-- misma tabla de gestion_adm (sql/c_pasivo_aplicacion_baja_20261030.sql).
--
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X). Idempotente.
-- El menú se lee al iniciar sesión: salir y volver a entrar.

USE sindicato;
SET NAMES utf8mb4;

-- Rastro de lo desaplicado ----------------------------------------------------
CREATE TABLE IF NOT EXISTS c_pasivo_aplicacion_baja (
  id                     INT NOT NULL AUTO_INCREMENT,
  id_aplicacion          INT NOT NULL            COMMENT 'c_pasivo_aplicacion.id (ya puede no existir)',
  id_liq_credito         INT NULL                COMMENT 'Nota de crédito aplicada',
  id_pago                INT NULL                COMMENT 'Pago aplicado',
  id_liq_debito          INT NOT NULL            COMMENT 'Factura a la que estaba aplicada',
  importe_aplicado       DECIMAL(18,2) NOT NULL  COMMENT 'Lo aplicado antes de desaplicar',
  importe_desaplicado    DECIMAL(18,2) NOT NULL,
  total                  TINYINT(1) NOT NULL     COMMENT '1 = se borró la aplicación entera',
  fecha_aplicacion       DATE NULL,
  origen                 VARCHAR(20) NULL        COMMENT 'manual | pago | migracion',
  observaciones          VARCHAR(255) NULL       COMMENT 'Las de la aplicación',
  id_usuario_aplicacion  INT NULL                COMMENT 'Quién había aplicado',
  motivo                 VARCHAR(255) NOT NULL,
  id_usuario             INT NULL                COMMENT 'Quién desaplicó',
  creado                 DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_pab_debito (id_liq_debito),
  KEY ix_pab_credito (id_liq_credito),
  KEY ix_pab_pago (id_pago),
  CONSTRAINT fk_pab_usuario FOREIGN KEY (id_usuario) REFERENCES s_usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Aplicaciones de pasivo desaplicadas: quién, cuándo, cuánto y por qué';

-- La aplicación acumula: aplicar dos veces el mismo par suma sobre el mismo
-- renglón (ON DUPLICATE KEY). Las dos claves ya vinieron de contable; se
-- crean si faltan.
SET @hay := (SELECT COUNT(*) FROM information_schema.statistics
              WHERE table_schema = DATABASE() AND table_name = 'c_pasivo_aplicacion' AND index_name = 'uq_pasivo_aplic');
SET @sql := IF(@hay = 0, 'ALTER TABLE c_pasivo_aplicacion ADD UNIQUE KEY uq_pasivo_aplic (id_liq_credito, id_liq_debito)', 'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
SET @hay := (SELECT COUNT(*) FROM information_schema.statistics
              WHERE table_schema = DATABASE() AND table_name = 'c_pasivo_aplicacion' AND index_name = 'uq_pa_pago_debito');
SET @sql := IF(@hay = 0, 'ALTER TABLE c_pasivo_aplicacion ADD UNIQUE KEY uq_pa_pago_debito (id_pago, id_liq_debito)', 'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- Menú: Proveedores → Aplicación de Comprobantes ------------------------------
-- Con su ícono en colores (el de sql/menu_iconos_color_20261111.sql, «link-multiple»):
-- si ese script se corrió antes de que existiera la opción 36, su UPDATE no
-- encontró la fila y la opción quedaba sin ícono. Si ya tiene uno (puesto a
-- mano desde Administración del Sistema → Menú), no se pisa.
SET @icono36 := '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24"><g fill="none"><path fill="url(#m36SVGsQVb4ccU)" fill-rule="evenodd" d="M1 10a5 5 0 0 1 5-5h7a5 5 0 0 1 0 10H6a5 5 0 0 1-5-5m5-3a3 3 0 0 0 0 6h7a3 3 0 1 0 0-6z" clip-rule="evenodd"/><path fill="url(#m36SVGKO9j3bxY)" fill-rule="evenodd" d="M1 10a5 5 0 0 1 5-5h7a5 5 0 0 1 0 10H6a5 5 0 0 1-5-5m5-3a3 3 0 0 0 0 6h7a3 3 0 1 0 0-6z" clip-rule="evenodd"/><path fill="url(#m36SVGDPO00d3r)" fill-rule="evenodd" d="M1 10a5 5 0 0 1 5-5h7a5 5 0 0 1 0 10H6a5 5 0 0 1-5-5m5-3a3 3 0 0 0 0 6h7a3 3 0 1 0 0-6z" clip-rule="evenodd"/><path fill="url(#m36SVGwyNBvdIB)" d="M15.83 9H11a5 5 0 0 0 0 10h7a5 5 0 0 0 0-10h-.1a5 5 0 0 1 0 2h.1a3 3 0 1 1 0 6h-7a3 3 0 1 1 0-6h4.83a3 3 0 0 0 0-2"/><path fill="url(#m36SVGrODl9cNl)" d="M15.83 9H11a5 5 0 0 0 0 10h7a5 5 0 0 0 0-10h-.1a5 5 0 0 1 0 2h.1a3 3 0 1 1 0 6h-7a3 3 0 1 1 0-6h4.83a3 3 0 0 0 0-2"/><path fill="url(#m36SVG06J4tbql)" d="M15.83 9H11a5 5 0 0 0 0 10h7a5 5 0 0 0 0-10h-.1a5 5 0 0 1 0 2h.1a3 3 0 1 1 0 6h-7a3 3 0 1 1 0-6h4.83a3 3 0 0 0 0-2"/><defs><radialGradient id="m36SVGsQVb4ccU" cx="0" cy="0" r="1" gradientTransform="rotate(37.75 -6.426 5.093)scale(17.5909 15.7387)" gradientUnits="userSpaceOnUse"><stop stop-color="#0fafff"/><stop offset=".429" stop-color="#367af2"/><stop offset=".942" stop-color="#5750e2"/><stop offset="1" stop-color="#6f47df"/></radialGradient><radialGradient id="m36SVGKO9j3bxY" cx="0" cy="0" r="1" gradientTransform="matrix(-7 0 0 -7.77785 10.5 14.5)" gradientUnits="userSpaceOnUse"><stop offset=".239" stop-color="#261d82" stop-opacity="0"/><stop offset=".424" stop-color="#261d82"/><stop offset=".568" stop-color="#261d82"/><stop offset=".754" stop-color="#261d82" stop-opacity="0"/></radialGradient><radialGradient id="m36SVGrODl9cNl" cx="0" cy="0" r="1" gradientTransform="matrix(7 0 0 7.77785 13.5 9.5)" gradientUnits="userSpaceOnUse"><stop offset=".246" stop-color="#2764e7" stop-opacity="0"/><stop offset=".396" stop-color="#2764e7"/><stop offset=".578" stop-color="#2764e7"/><stop offset=".748" stop-color="#2764e7" stop-opacity="0"/></radialGradient><linearGradient id="m36SVGDPO00d3r" x1="17" x2="8.382" y1="15.5" y2="5.667" gradientUnits="userSpaceOnUse"><stop stop-color="#5157e4" stop-opacity="0"/><stop offset=".066" stop-color="#5157e4"/><stop offset=".319" stop-color="#5157e4"/><stop offset=".6" stop-color="#5157e4" stop-opacity="0"/></linearGradient><linearGradient id="m36SVGwyNBvdIB" x1=".536" x2="11.117" y1="4.188" y2="28.777" gradientUnits="userSpaceOnUse"><stop stop-color="#36dff1"/><stop offset="1" stop-color="#2764e7"/></linearGradient><linearGradient id="m36SVG06J4tbql" x1="8.5" x2="16.77" y1="5" y2="12.103" gradientUnits="userSpaceOnUse"><stop stop-color="#31b3ee" stop-opacity=".243"/><stop offset=".208" stop-color="#31b3ee"/><stop offset=".569" stop-color="#31b3ee"/><stop offset=".763" stop-color="#31b3ee" stop-opacity="0"/></linearGradient></defs></g></svg>';

INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (36, 30, 'Aplicación de Comprobantes', '/proveedores/cc/aplicaciones', @icono36, 6, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url),
  padre_id = VALUES(padre_id), orden = VALUES(orden), activo = 1,
  icono_svg = COALESCE(NULLIF(icono_svg, ''), VALUES(icono_svg));

INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT 36, r.id FROM s_roles r
 WHERE r.nombre IN ('Administrador', 'Supervisor')
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = 36 AND x.rol_id = r.id);

SELECT m.id, m.nombre, m.url, m.orden, m.icono_svg IS NOT NULL AS con_icono FROM s_menu m WHERE m.padre_id = 30 ORDER BY m.orden;
