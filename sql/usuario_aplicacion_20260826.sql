-- usuario_aplicacion del sindicato — 26/08/2026
--
-- ANTES DE CORRER ESTO: reemplazar <<CONTRASENA>> por una contraseña larga y
-- aleatoria. No queda escrita en el repositorio a propósito: va a la variable
-- SIND_DB_PASS del servidor y a ningún otro lado.
--
-- POR QUÉ UN USUARIO NUEVO Y NO app_gestion
-- `app_gestion` tiene permisos sobre `contable` y ninguno sobre `sindicato`.
-- Se podría agregarle `sindicato` y listo, pero entonces un solo usuario
-- comprometido alcanza las dos bases, y la regla de oro del proyecto —que este
-- código no escriba en `contable`— pasaría a depender otra vez de que el
-- código se porte bien. Con un usuario propio, esa regla la aplica MySQL:
-- `app_sindicato` no puede tocar `contable` ni equivocándose.
--
-- Es la contracara de lo que hace db.py fijando DB_NAME como constante. Uno
-- impide apuntar a la base equivocada; el otro impide que sirva de algo si
-- alguien lo intenta igual.
--
-- QUÉ NECESITA DE VERDAD
-- Se revisó el código antes de escribir esta lista:
--   SELECT/INSERT/UPDATE/DELETE  el dashboard, la importación de cuotas, el
--                                historial, la API y el login
-- Y nada más:
--   EXECUTE                      no se otorga: `sindicato` no tiene ninguna
--                                rutina (se verificó contra
--                                information_schema.ROUTINES)
--   CREATE TEMPORARY TABLES      no se otorga: ningún módulo crea temporales
--                                hoy. Si alguno lo necesita más adelante, se
--                                agrega ahí y se sabe por qué
--
-- LO QUE NO SE OTORGA, Y POR QUÉ IMPORTA
--   CREATE/ALTER/DROP/INDEX  la aplicación no hace DDL: el esquema se cambia
--                            con los scripts de esta carpeta, a mano
--   FILE                     es lo que permite leer y escribir archivos del
--                            servidor desde una consulta
--   PROCESS                  deja ver las consultas de las demás sesiones
--   SUPER / GRANT OPTION     no hace falta explicarlo
--   Cualquier cosa sobre mysql.* y sobre contable.*
--
-- SOLO 'localhost' POR AHORA
-- El sitio y la base corren en la misma máquina, así que una sola entrada
-- alcanza: la aplicación desde IIS, crear_usuario.py y las importaciones
-- desatendidas conectan todas por localhost. No se crea la entrada '%' porque
-- un usuario que puede conectar desde cualquier IP es superficie de ataque que
-- hoy no se usa. Si algún día la base se va a otra máquina, se agrega ahí —y
-- mejor con la IP de salida que con '%'.

CREATE USER IF NOT EXISTS 'app_sindicato'@'localhost' IDENTIFIED BY '<<CONTRASENA>>';

GRANT SELECT, INSERT, UPDATE, DELETE
  ON sindicato.* TO 'app_sindicato'@'localhost';

FLUSH PRIVILEGES;

-- ── Verificación ─────────────────────────────────────────────────────────────
-- Tiene que devolver exactamente los permisos de arriba sobre `sindicato`,
-- ninguna línea sobre `contable` y ninguna con ON *.* que no sea USAGE.
SHOW GRANTS FOR 'app_sindicato'@'localhost';
