-- Padrón: «Tablas Auxiliares» — 10/11/2026
--
-- Una opción de menú dentro de Padrón de Afiliados para los catálogos de la
-- ficha (afiliados_tablas.py): estado civil, nacionalidades, parentescos,
-- provincias, tipos de documento, motivos de alta y baja, atributos y tipos de
-- documentación. Las tablas ya existen: no se crea ni se cambia ninguna.
--
-- Se da a Administrador y Supervisor: cambiar un catálogo cambia lo que ven
-- todas las fichas. Para dársela a otro rol:
--     INSERT INTO s_menu_rol (menu_id, rol_id) VALUES (24, <rol>);
--
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X). Idempotente.
-- Los permisos se leen al iniciar sesión: hay que salir y volver a entrar.

INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (24, 20, 'Tablas Auxiliares', '/afiliados/tablas', NULL, 9, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url),
  padre_id = VALUES(padre_id), orden = VALUES(orden), activo = 1;

-- Desde s_menu y s_roles, no desde DUAL: si la opción no se creó, no inserta
-- nada en vez de cortar con el error de clave foránea.
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT m.id, r.id
  FROM s_menu m
  JOIN s_roles r ON r.id IN (1, 2) AND r.activo = 1
 WHERE m.id = 24
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = m.id AND x.rol_id = r.id);
