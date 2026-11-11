-- Guía de estilos en el menú — 07/11/2026
--
-- /estilos dibuja cada componente de static/css/sindicato.css con la línea para
-- copiarlo. Va en Administración del Sistema y solo para el rol Administrador:
-- es la referencia para armar pantallas, no una pantalla de trabajo.
--
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X). Ctrl+Enter ejecuta
-- solo la sentencia donde está el cursor, y si esa es la segunda, la opción
-- todavía no existe.
--
-- Idempotente. El menú se arma al iniciar sesión: hay que salir y volver a
-- entrar para verla.

INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (206, 200, 'Guía de estilos', '/estilos', NULL, 6, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url),
  padre_id = VALUES(padre_id), orden = VALUES(orden), activo = 1;

-- Desde s_menu y no desde DUAL: si la opción no se creó, no inserta nada en
-- vez de cortar con el error de clave foránea.
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT m.id, 1 FROM s_menu m
WHERE m.id = 206
  AND NOT EXISTS (SELECT 1 FROM s_menu_rol WHERE menu_id = 206 AND rol_id = 1);
