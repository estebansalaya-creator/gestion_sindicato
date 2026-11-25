-- =============================================================================
-- afiliados_foto_dni_20261125.sql — Foto del afiliado y pantalla «Carga de DNI»
-- =============================================================================
-- Pedido del 25/11/2026: subir las fotos del DNI en una pantalla general, que
-- busque al afiliado por el código del frente, guarde frente y dorso en su
-- documentación y recorte la cara para la foto de la ficha.
--
-- 1. p_afiliados.foto: la ruta del retrato, relativa a SIND_ADJUNTOS
--    (fotos/afiliado/<id>/<nombre>.jpg). NULL = sin foto.
-- 2. La opción de menú Padrón de Afiliados → Carga de DNI (/afiliados/dni),
--    para quien hoy tiene el ABM de afiliados (opción 21): modifica la ficha.
--    Desde el 22/11/2026 lo que ve cada uno está en s_menu_usuario, no en roles.
--
-- Los tipos «DNI — frente» y «DNI — dorso» de p_tipo_documentacion ya existen
-- (códigos dni_frente y dni_dorso): la pantalla los busca por código.
--
-- Correrlo ENTERO (Alt+X), en localhost y en Railway. Idempotente.
-- El menú se lee al iniciar sesión: hay que salir y volver a entrar.

USE sindicato;
SET NAMES utf8mb4;

-- 1. La columna (sin IF NOT EXISTS en ALTER de MySQL 8: se arma a mano).
SET @hay := (SELECT COUNT(*) FROM information_schema.COLUMNS
              WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'p_afiliados' AND COLUMN_NAME = 'foto');
SET @sql := IF(@hay = 0,
  "ALTER TABLE p_afiliados ADD COLUMN foto VARCHAR(160) NULL COMMENT 'Retrato: ruta relativa a SIND_ADJUNTOS' AFTER observaciones",
  "SELECT 'p_afiliados.foto ya existe' AS aviso");
PREPARE st FROM @sql; EXECUTE st; DEALLOCATE PREPARE st;

-- 2. La opción de menú, después del ABM.
SET @id := (SELECT id FROM s_menu WHERE url = '/afiliados/dni' LIMIT 1);
SET @id := COALESCE(@id, IF(EXISTS (SELECT 1 FROM s_menu WHERE id = 25), (SELECT MAX(id) + 1 FROM s_menu), 25));
INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (@id, 20, 'Carga de DNI', '/afiliados/dni', NULL, 2, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url),
  padre_id = VALUES(padre_id), orden = VALUES(orden), activo = 1;
-- El ABM queda primero entre los dos.
UPDATE s_menu SET orden = 2 WHERE id = 21;
UPDATE s_menu SET orden = 3 WHERE id = @id;
UPDATE s_menu SET orden = 4 WHERE id = 22 AND orden <= 3;

-- A quien tiene el ABM (en vez de a un rol: ver roles_sin_menu_20261122.sql).
INSERT IGNORE INTO s_menu_usuario (usuario_id, menu_id)
SELECT mu.usuario_id, @id FROM s_menu_usuario mu WHERE mu.menu_id = 21;

-- Verificación.
SELECT m.id, m.nombre, m.url, m.orden,
       (SELECT COUNT(*) FROM s_menu_usuario mu WHERE mu.menu_id = m.id) AS usuarios
  FROM s_menu m WHERE m.padre_id = 20 ORDER BY m.orden;
