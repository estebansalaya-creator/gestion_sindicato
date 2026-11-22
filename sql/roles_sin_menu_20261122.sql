-- Roles sin opciones de menú — 22/11/2026
--
-- Pedido: «los roles están mejor definidos en el proyecto financiera… que no tenga asociación con
-- las opciones de menú; para eso está Permisos por Usuario; al crear un usuario, poder copiar los
-- permisos de otro».
--
-- Desde ahora lo que ve cada persona es SOLO lo que tiene en `s_menu_usuario` (db.roles_y_menu).
-- El rol es el nivel: el código pregunta solo por Administrador (que además ve siempre Usuarios,
-- Roles y Menú: db.MENU_ADMIN_SIEMPRE).
--
-- Este script hace que nadie pierda nada: a cada usuario le copia como propias las opciones que hoy
-- le dan sus roles activos, y después vacía `s_menu_rol` (la tabla queda, sin uso).
--
-- El orden con el código da igual: el código viejo suma rol + usuario, así que con las opciones ya
-- copiadas cada uno ve lo mismo antes y después del deploy. Se puede volver a correr.
--
-- OJO con los scripts de menú que vengan después: una opción nueva se asigna en `s_menu_usuario`
-- (a quién corresponda), ya no en `s_menu_rol`.

INSERT IGNORE INTO s_menu_usuario (usuario_id, menu_id)
SELECT DISTINCT ur.usuario_id, mr.menu_id
  FROM s_usuario_rol ur
  JOIN s_roles r     ON r.id = ur.rol_id AND r.activo = 1
  JOIN s_menu_rol mr ON mr.rol_id = ur.rol_id;

DELETE FROM s_menu_rol;

-- Verificación: opciones por usuario (tienen que ser las mismas que veían antes).
SELECT u.email, GROUP_CONCAT(DISTINCT r.nombre) AS roles, COUNT(DISTINCT mu.menu_id) AS opciones
  FROM s_usuarios u
  LEFT JOIN s_usuario_rol ur ON ur.usuario_id = u.id
  LEFT JOIN s_roles r        ON r.id = ur.rol_id
  LEFT JOIN s_menu_usuario mu ON mu.usuario_id = u.id
 GROUP BY u.id, u.email
 ORDER BY u.email;
