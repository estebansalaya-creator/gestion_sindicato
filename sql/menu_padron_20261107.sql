-- Padrón de afiliados: consulta y ABM por separado — 07/11/2026
--
-- Agrega «Consulta del Padrón» (/afiliados/padron, solo lectura) junto a
-- «ABM de Afiliados» (/afiliados). El permiso ES la opción de menú (ver
-- db.puede): quien tiene el ABM entra también desde la consulta, con los
-- botones para editar; quien solo tiene la consulta, mira.
--
-- La consulta se da a los tres roles activos. El ABM queda como está (hoy lo
-- tienen los tres); para que un rol solo consulte, quitarle la opción 21:
--     DELETE FROM s_menu_rol WHERE menu_id = 21 AND rol_id = <rol>;
--
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X). Idempotente.
-- Los permisos se leen al iniciar sesión: hay que salir y volver a entrar.

INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (23, 20, 'Consulta del Padrón', '/afiliados/padron', NULL, 1, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url),
  padre_id = VALUES(padre_id), orden = VALUES(orden), activo = 1;

-- La consulta primero, después el ABM y las métricas.
UPDATE s_menu SET orden = 2 WHERE id = 21;
UPDATE s_menu SET orden = 3 WHERE id = 22;

-- Desde s_menu y s_roles, no desde DUAL: si la opción no se creó, no inserta
-- nada en vez de cortar con el error de clave foránea.
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT m.id, r.id
  FROM s_menu m
  JOIN s_roles r ON r.id IN (1, 2, 3) AND r.activo = 1
 WHERE m.id = 23
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = m.id AND x.rol_id = r.id);
