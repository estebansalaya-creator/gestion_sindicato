-- Administración del Sistema — 11/11/2026
--
-- Las pantallas de admin.py: Usuarios (201), Roles (202), Permisos por Usuario
-- (203), Menú (204) y Áreas (205) ya estaban en el menú y daban «pantalla
-- pendiente». Falta «Áreas por Usuario», que en gestion_adm es una opción
-- aparte (abm_area_usuario) y que la mesa de entradas necesita para ofrecer,
-- al derivar a un área, a las personas que la integran. Va después de Áreas y
-- para los mismos roles que la tienen.
--
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X).
-- Idempotente. El menú se lee al iniciar sesión: salir y volver a entrar.

INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (208, 200, 'Áreas por Usuario', '/admin/areas_usuario', NULL, 6, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url),
  padre_id = VALUES(padre_id), orden = VALUES(orden), activo = 1;

-- El orden de gestion_adm: lo de personas y permisos primero, después los
-- datos del sindicato y la guía.
UPDATE s_menu SET orden = 7 WHERE id = 207;
UPDATE s_menu SET orden = 8 WHERE id = 206;

-- Los roles que tienen Áreas (205) reciben también Áreas por Usuario.
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT 208, mr.rol_id FROM s_menu_rol mr
WHERE mr.menu_id = 205
  AND EXISTS (SELECT 1 FROM s_menu WHERE id = 208)
  AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = 208 AND x.rol_id = mr.rol_id);

-- Control: las opciones de Administración del Sistema y quién las tiene.
SELECT m.id, m.nombre, m.url, m.orden,
       GROUP_CONCAT(r.nombre ORDER BY r.prioridad DESC SEPARATOR ', ') AS roles
  FROM s_menu m
  LEFT JOIN s_menu_rol mr ON mr.menu_id = m.id
  LEFT JOIN s_roles r ON r.id = mr.rol_id
 WHERE m.padre_id = 200
 GROUP BY m.id, m.nombre, m.url, m.orden
 ORDER BY m.orden;
