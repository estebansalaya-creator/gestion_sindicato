-- Talonarios en Administración del Sistema — 11/11/2026
--
-- /admin/talonarios (talonarios.py): talonarios, sus clasificaciones y los
-- tipos de comprobante, en una pantalla con tres solapas. Va donde lo tiene
-- gestion_adm («Talonarios» en Administración del Sistema) y para el rol
-- Administrador. Las tablas (c_talonario, c_talonario_clasificacion,
-- c_contable_comprobante_tipo) ya están.
--
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X).
-- Idempotente. El menú se lee al iniciar sesión: salir y volver a entrar.

INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (209, 200, 'Talonarios', '/admin/talonarios', NULL, 7, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url),
  padre_id = VALUES(padre_id), orden = VALUES(orden), activo = 1;

-- Después de Áreas por Usuario (6): Talonarios, Datos del Sindicato, Guía.
UPDATE s_menu SET orden = 8 WHERE id = 207;
UPDATE s_menu SET orden = 9 WHERE id = 206;

INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT m.id, 1 FROM s_menu m
WHERE m.id = 209
  AND NOT EXISTS (SELECT 1 FROM s_menu_rol WHERE menu_id = 209 AND rol_id = 1);

SELECT m.id, m.nombre, m.url, m.orden FROM s_menu m WHERE m.padre_id = 200 ORDER BY m.orden;
