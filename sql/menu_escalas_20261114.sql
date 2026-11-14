-- =============================================================================
-- menu_escalas_20261114.sql — Fiscalización de Cuotas → Escalas Salariales
-- =============================================================================
-- La pantalla de fisca_escalas.py. Requiere sql/fisca_escalas_20261114.sql.
-- Correrlo ENTERO (Alt+X). Idempotente. El menú se lee al iniciar sesión.

USE sindicato;
SET NAMES utf8mb4;

SET @id := (SELECT id FROM s_menu WHERE url = '/fiscalizacion/escalas' LIMIT 1);
SET @id := COALESCE(@id, IF(EXISTS (SELECT 1 FROM s_menu WHERE id = 9), (SELECT MAX(id) + 1 FROM s_menu), 9));
INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (@id, 1, 'Escalas Salariales', '/fiscalizacion/escalas', NULL, 8, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url),
  padre_id = VALUES(padre_id), orden = VALUES(orden), activo = 1;

INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT @id, r.id FROM s_roles r
 WHERE r.nombre IN ('Administrador', 'Supervisor')
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = @id AND x.rol_id = r.id);

SELECT m.id, m.nombre, m.url, m.orden FROM s_menu m WHERE m.padre_id = 1 ORDER BY m.orden;
