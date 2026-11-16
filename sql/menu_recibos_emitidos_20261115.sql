-- Tesorería → Recibos Emitidos — 15/11/2026
--
-- /tesoreria/recibos (recibos_emitidos.py): los recibos de cuota sindical y de
-- fiscalización ya emitidos —los del sistema y los de AEDA—, para buscarlos,
-- verlos, imprimirlos y bajarlos a Excel. Como «Recibos emitidos» de
-- gestion_adm. Va después de Orden de Ingreso, para Administrador y
-- Supervisor (los mismos roles que el resto de Tesorería). No hace falta
-- ninguna tabla nueva.
--
-- Quien tiene esta opción ve el recibo y su PDF aunque no tenga Emisión de
-- Recibos (Fiscalización).
--
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X).
-- Idempotente. El menú se lee al iniciar sesión: salir y volver a entrar.

USE sindicato;

INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (76, 60, 'Recibos Emitidos', '/tesoreria/recibos', NULL, 3, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url),
  padre_id = VALUES(padre_id), orden = VALUES(orden), nivel = VALUES(nivel), activo = 1;

-- El mismo ícono que Emisión de Recibos.
UPDATE s_menu m
  JOIN (SELECT icono_svg FROM s_menu WHERE url = '/fiscalizacion/recibos' LIMIT 1) r
   SET m.icono_svg = r.icono_svg
 WHERE m.id = 76 AND m.icono_svg IS NULL;

INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT 76, r.rol_id FROM (SELECT DISTINCT rol_id FROM s_menu_rol WHERE menu_id = 60) r
 WHERE NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = 76 AND x.rol_id = r.rol_id);

SELECT m.id, m.nombre, m.url, m.orden,
       (SELECT GROUP_CONCAT(rol_id) FROM s_menu_rol WHERE menu_id = m.id) AS roles
  FROM s_menu m WHERE m.padre_id = 60 ORDER BY m.orden, m.nombre;
