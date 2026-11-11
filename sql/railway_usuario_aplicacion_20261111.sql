-- railway_usuario_aplicacion — 11/11/2026
--
-- Se corre UNA vez en el MySQL de Railway donde se restauró `sindicato`,
-- conectado como root (DBeaver por el proxy público, o la solapa Data del
-- servicio). Es sql/usuario_aplicacion_20260826.sql para Railway.
--
-- ANTES DE CORRER: reemplazar <<CONTRASENA>> por una contraseña larga y
-- aleatoria (python -c "import secrets; print(secrets.token_urlsafe(32))").
-- Va a SIND_DB_PASS del servicio web y a ningún otro lado.
--
-- POR QUÉ HACE FALTA
-- Un restore trae la base, no los usuarios: `app_sindicato` no existe en el
-- servidor nuevo. Se crea con '%' y no con 'localhost' porque en Railway la
-- aplicación conecta desde otro contenedor (red privada) y los importadores de
-- AEDA desde tu máquina (proxy público): ninguno de los dos es localhost.
-- Los permisos son los mismos de siempre: solo datos de `sindicato`, sin DDL.

-- ── 1. La base tiene que llamarse `sindicato` ────────────────────────────────
-- db.py la tiene fija (DB_NAME). Si el restore quedó en `railway` —la base que
-- crea el servicio MySQL por defecto— la aplicación no la encuentra.
SELECT SCHEMA_NAME, DEFAULT_COLLATION_NAME,
       (SELECT COUNT(*) FROM information_schema.TABLES t
         WHERE t.TABLE_SCHEMA = s.SCHEMA_NAME AND t.TABLE_TYPE = 'BASE TABLE') AS tablas,
       (SELECT COUNT(*) FROM information_schema.VIEWS v
         WHERE v.TABLE_SCHEMA = s.SCHEMA_NAME) AS vistas
  FROM information_schema.SCHEMATA s
 WHERE SCHEMA_NAME = 'sindicato';
-- Esperado: 1 fila, ~141 tablas y 16 vistas (lo que había en localhost).

-- ── 2. El usuario de la aplicación ───────────────────────────────────────────
CREATE USER IF NOT EXISTS 'app_sindicato'@'%' IDENTIFIED BY '<<CONTRASENA>>';

GRANT SELECT, INSERT, UPDATE, DELETE
  ON sindicato.* TO 'app_sindicato'@'%';

FLUSH PRIVILEGES;

-- Tiene que mostrar USAGE ON *.* y los cuatro permisos sobre `sindicato`.*,
-- nada más.
SHOW GRANTS FOR 'app_sindicato'@'%';

-- ── 3. Las vistas ────────────────────────────────────────────────────────────
-- En localhost las 16 vistas tienen DEFINER root@localhost y SQL SECURITY
-- DEFINER. Si ese usuario no existe en este servidor, la vista se restauró
-- pero falla al usarla (error 1449, «The user specified as a definer does not
-- exist»), y con ella la cuenta corriente, los liquidados impagos, etc.
--
-- Esta consulta lista las que tienen un definer que no existe acá:
SELECT v.TABLE_NAME, v.DEFINER
  FROM information_schema.VIEWS v
 WHERE v.TABLE_SCHEMA = 'sindicato'
   AND v.DEFINER NOT IN (SELECT CONCAT(u.User, '@', u.Host) FROM mysql.user u);
-- Sin filas: no hay nada que hacer, pasar a la verificación.
--
-- Con filas: esta otra arma un ALTER por vista, que las deja con el usuario que
-- corre el script (root de Railway) como definer. Copiar la columna de
-- resultados, pegarla y ejecutarla como script.
SELECT CONCAT('ALTER DEFINER = CURRENT_USER SQL SECURITY DEFINER VIEW `sindicato`.`',
              v.TABLE_NAME, '` AS ', v.VIEW_DEFINITION, ';') AS sentencia
  FROM information_schema.VIEWS v
 WHERE v.TABLE_SCHEMA = 'sindicato'
   AND v.DEFINER NOT IN (SELECT CONCAT(u.User, '@', u.Host) FROM mysql.user u);

-- ── 4. Verificación con el usuario de la aplicación ──────────────────────────
-- Conectarse como app_sindicato (no como root) y correr esto. Tiene que
-- devolver números, no errores de permiso ni de definer.
SELECT (SELECT COUNT(*) FROM sindicato.s_usuarios)                 AS usuarios,
       (SELECT COUNT(*) FROM sindicato.p_afiliados)                AS afiliados,
       (SELECT COUNT(*) FROM sindicato.v_cc_proveedores_movimientos) AS movimientos_cc,
       (SELECT COUNT(*) FROM sindicato.v_expedientes_liquidados_impagos) AS impagos;
