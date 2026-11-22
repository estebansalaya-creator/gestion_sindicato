-- =============================================================================
-- s_log_errores_20261122.sql — Log de errores del sistema (/admin/errores)
-- 22/11/2026, el mismo de gestion_adm.
--
-- Cada error que se produce en una pantalla queda anotado con la fecha y hora,
-- el usuario, el método y la URL, el error (tipo y mensaje) y el traceback.
-- Lo escribe log_errores.py: las excepciones que nadie atajó (el «La pantalla
-- no se pudo abrir»), las respuestas 500 que arma el código y los flash que
-- se muestran desde un except. Ver el docstring del módulo.
--
-- El mismo error (misma `firma`) del mismo usuario dentro de 5 minutos suma
-- `veces` y corre `ultima` en lugar de abrir otra fila. Se guarda 180 días.
--
-- app_sindicato ya escribe en todo `sindicato`: no hacen falta GRANT.
-- Correrlo ENTERO (DBeaver, «Ejecutar script», Alt+X), DESPUÉS de desplegar el
-- código. Idempotente. El menú se relee solo al minuto (app._permisos_al_dia).
-- Sin la tabla la aplicación anda igual: el error queda sólo en el log de la
-- aplicación, como hasta ahora.
-- =============================================================================

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS s_log_errores (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  fecha         DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'La primera vez',
  ultima        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'La última vez (con veces > 1)',
  veces         INT UNSIGNED  NOT NULL DEFAULT 1,
  origen        ENUM('excepcion','respuesta','aviso') NOT NULL,
  status        SMALLINT      NULL     COMMENT 'El código HTTP, si hubo respuesta de error',
  tipo          VARCHAR(150)  NULL     COMMENT 'La clase de la excepción: OperationalError, KeyError…',
  mensaje       TEXT          NOT NULL,
  detalle       MEDIUMTEXT    NULL     COMMENT 'El traceback',
  lugar         VARCHAR(300)  NULL     COMMENT 'El último renglón de código propio: archivo:línea función',
  firma         CHAR(40)      NOT NULL COMMENT 'sha1 de origen + tipo + lugar: «el mismo error»',
  id_usuario    INT           NULL,
  usuario       VARCHAR(150)  NULL     COMMENT 'El nombre, como estaba en la sesión',
  metodo        VARCHAR(10)   NOT NULL,
  url           VARCHAR(1000) NOT NULL COMMENT 'Con los parámetros secretos tapados',
  endpoint      VARCHAR(150)  NULL,
  referer       VARCHAR(500)  NULL,
  ip            VARCHAR(64)   NULL,
  navegador     VARCHAR(300)  NULL,
  revisado      TINYINT(1)    NOT NULL DEFAULT 0,
  revisado_por  VARCHAR(150)  NULL,
  revisado_el   DATETIME      NULL,
  PRIMARY KEY (id),
  KEY ix_logerr_ultima (ultima),
  KEY ix_logerr_firma (firma, id_usuario, ultima),
  KEY ix_logerr_revisado (revisado, ultima),
  KEY ix_logerr_usuario (id_usuario)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Los errores de las pantallas: qué falló, dónde, a quién y cuándo';

-- ── La opción de menú: Administración del Sistema (200), al final ────────────
INSERT INTO s_menu (padre_id, nombre, url, icono_svg, orden, nivel, activo)
SELECT 200, 'Log de Errores', '/admin/errores', NULL,
       (SELECT COALESCE(MAX(x.orden), 0) + 1 FROM (SELECT orden FROM s_menu WHERE padre_id = 200) x),
       2, 1
  FROM DUAL
 WHERE EXISTS (SELECT 1 FROM (SELECT id FROM s_menu) y WHERE y.id = 200)
   AND NOT EXISTS (SELECT 1 FROM (SELECT url FROM s_menu) x WHERE x.url = '/admin/errores');

-- ── Quién la ve: los roles y las personas que tienen «Usuarios» ──────────────
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT nuevo.id, mr.rol_id
  FROM s_menu_rol mr
  JOIN s_menu origen ON origen.id = mr.menu_id AND origen.url = '/admin/usuarios'
  JOIN (SELECT id FROM s_menu WHERE url = '/admin/errores') nuevo
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT menu_id, rol_id FROM s_menu_rol) z
                    WHERE z.menu_id = nuevo.id AND z.rol_id = mr.rol_id);

INSERT INTO s_menu_usuario (usuario_id, menu_id)
SELECT mu.usuario_id, nuevo.id
  FROM s_menu_usuario mu
  JOIN s_menu origen ON origen.id = mu.menu_id AND origen.url = '/admin/usuarios'
  JOIN (SELECT id FROM s_menu WHERE url = '/admin/errores') nuevo
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT usuario_id, menu_id FROM s_menu_usuario) z
                    WHERE z.usuario_id = mu.usuario_id AND z.menu_id = nuevo.id);

-- ── Control ──────────────────────────────────────────────────────────────────
SELECT m.id, m.padre_id, m.orden, m.nombre, m.url,
       (SELECT GROUP_CONCAT(r.nombre) FROM s_menu_rol mr JOIN s_roles r ON r.id = mr.rol_id
         WHERE mr.menu_id = m.id) AS roles,
       (SELECT COUNT(*) FROM s_menu_usuario u WHERE u.menu_id = m.id) AS usuarios_sueltos
  FROM s_menu m WHERE m.url IN ('/admin/usuarios', '/admin/errores');
-- Las dos filas con los mismos roles.
