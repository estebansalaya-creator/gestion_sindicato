-- =============================================================================
-- chat_mensajes_20261122.sql — Mensajes internos entre usuarios (/mensajes)
-- 22/11/2026: el chat de gestion_adm, con las mismas tablas, en `sindicato`.
--
--   chat_conversaciones  DIRECTA (clave_directa «menor-mayor» de los dos id de
--                        s_usuarios: una sola entre dos personas) o GRUPO.
--   chat_participantes   quién está, si administra el grupo, hasta qué mensaje
--                        leyó y si la silenció.
--   chat_mensajes        texto y/o adjunto. id_usuario NULL = aviso del sistema
--                        («Ana agregó a Luis»). No se borran: el autor lo retira
--                        (borrado_el) y queda «Mensaje eliminado».
--   chat_presencia       la última vez que se vio a cada usuario: «En línea» o
--                        «Últ. vez hoy a las 14:32». Sin ella el chat anda igual.
--
-- No leídos: cada participante guarda el id del último mensaje que vio
-- (ultimo_leido); la conversación, el de su último mensaje. Hay algo nuevo si
-- ultimo_mensaje_id > ultimo_leido.
--
-- Adjuntos: el archivo NO va a la base. Queda en SIND_ADJUNTOS/chat/<id
-- conversación>/<32 hex>.<ext> (en Railway, el volumen /data) y se sirve por
-- /mensajes/adjunto/<id>, que controla que quien lo pide participe.
--
-- app_sindicato ya escribe en todo `sindicato`: no hacen falta GRANT.
-- Correrlo ENTERO (DBeaver, «Ejecutar script», Alt+X), DESPUÉS de desplegar el
-- código: si la opción aparece antes que la ruta, el que entre se come un 404.
-- Idempotente. El menú se relee solo al minuto (app._permisos_al_dia).
-- =============================================================================

SET NAMES utf8mb4;

-- ── 1. Las tablas ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chat_conversaciones (
    id_conversacion   INT UNSIGNED NOT NULL AUTO_INCREMENT,
    tipo              ENUM('DIRECTA','GRUPO') NOT NULL,
    nombre            VARCHAR(80)  NULL,                -- sólo GRUPO
    clave_directa     VARCHAR(23)  NULL,                -- sólo DIRECTA: '3-17'
    creado_por        INT          NULL,
    creado_el         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ultimo_mensaje_id BIGINT UNSIGNED NOT NULL DEFAULT 0,
    ultimo_mensaje_el DATETIME     NULL,
    PRIMARY KEY (id_conversacion),
    UNIQUE KEY uq_chatconv_directa (clave_directa),
    KEY ix_chatconv_ultimo (ultimo_mensaje_el),
    CONSTRAINT fk_chatconv_creador FOREIGN KEY (creado_por) REFERENCES s_usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS chat_participantes (
    id_conversacion   INT UNSIGNED NOT NULL,
    id_usuario        INT          NOT NULL,
    es_admin          TINYINT(1)   NOT NULL DEFAULT 0,  -- en GRUPO: agrega, quita y renombra
    ultimo_leido      BIGINT UNSIGNED NOT NULL DEFAULT 0,
    silenciada        TINYINT(1)   NOT NULL DEFAULT 0,  -- no suma al contador de la barra
    agregado_el       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id_conversacion, id_usuario),
    KEY ix_chatpart_usuario (id_usuario, id_conversacion),
    CONSTRAINT fk_chatpart_conv    FOREIGN KEY (id_conversacion) REFERENCES chat_conversaciones (id_conversacion) ON DELETE CASCADE,
    CONSTRAINT fk_chatpart_usuario FOREIGN KEY (id_usuario)      REFERENCES s_usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS chat_mensajes (
    id_mensaje        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    id_conversacion   INT UNSIGNED NOT NULL,
    id_usuario        INT          NULL,                -- NULL = aviso del sistema («Ana agregó a Luis»)
    texto             TEXT         NULL,
    adjunto_archivo   VARCHAR(255) NULL,                -- relativo a UPLOADS: chat/12/ab12….pdf
    adjunto_nombre    VARCHAR(200) NULL,                -- como lo subieron
    adjunto_mime      VARCHAR(100) NULL,
    adjunto_bytes     INT UNSIGNED NULL,
    adjunto_duracion  SMALLINT UNSIGNED NULL,           -- segundos, sólo mensajes de voz
    creado_el         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    borrado_el        DATETIME     NULL,
    PRIMARY KEY (id_mensaje),
    KEY ix_chatmsj_conv (id_conversacion, id_mensaje),
    UNIQUE KEY uq_chatmsj_archivo (adjunto_archivo),
    CONSTRAINT fk_chatmsj_conv    FOREIGN KEY (id_conversacion) REFERENCES chat_conversaciones (id_conversacion),
    CONSTRAINT fk_chatmsj_usuario FOREIGN KEY (id_usuario)      REFERENCES s_usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS chat_presencia (
    id_usuario  INT      NOT NULL,
    visto_el    DATETIME NOT NULL,
    PRIMARY KEY (id_usuario),
    CONSTRAINT fk_chatpres_usuario FOREIGN KEY (id_usuario) REFERENCES s_usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ── 2. La opción del menú: «Mensajes» en la raíz, al final ───────────────────
-- Una hoja de nivel 1 (con url, sin hijos). El botón de la barra de arriba
-- aparece sólo para quien la tiene. /mensajes cubre también /mensajes/api y
-- /mensajes/adjunto/<id>: el permiso es el de la opción (mensajes.habilitado).
INSERT INTO s_menu (padre_id, nombre, url, icono_svg, orden, nivel, activo)
SELECT NULL, 'Mensajes', '/mensajes',
       '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" width="18" height="18"><path stroke-linecap="round" stroke-linejoin="round" d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 01-.825-.242m9.345-8.334a2.126 2.126 0 00-.476-.095 48.64 48.64 0 00-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0011.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155"/></svg>',
       (SELECT COALESCE(MAX(x.orden), 0) + 1 FROM (SELECT orden FROM s_menu WHERE padre_id IS NULL) x),
       1, 1
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM (SELECT url FROM s_menu) x WHERE x.url = '/mensajes');

-- ── 3. Quién la tiene: todos los roles activos ───────────────────────────────
-- Mensajes es de todos. Con el rol alcanza (db.roles_y_menu suma rol y
-- opciones sueltas): los que se den de alta después la reciben con su rol.
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT nuevo.id, r.id
  FROM s_roles r
  JOIN (SELECT id FROM s_menu WHERE url = '/mensajes') nuevo
 WHERE r.activo = 1
   AND NOT EXISTS (SELECT 1 FROM (SELECT menu_id, rol_id FROM s_menu_rol) z
                    WHERE z.menu_id = nuevo.id AND z.rol_id = r.id);

-- Y suelta a los usuarios activos que no tienen ningún rol activo.
INSERT INTO s_menu_usuario (usuario_id, menu_id)
SELECT u.id, nuevo.id
  FROM s_usuarios u
  JOIN (SELECT id FROM s_menu WHERE url = '/mensajes') nuevo
 WHERE u.activo = 1
   AND NOT EXISTS (SELECT 1 FROM s_usuario_rol ur JOIN s_roles r ON r.id = ur.rol_id AND r.activo = 1
                    WHERE ur.usuario_id = u.id)
   AND NOT EXISTS (SELECT 1 FROM (SELECT usuario_id, menu_id FROM s_menu_usuario) z
                    WHERE z.usuario_id = u.id AND z.menu_id = nuevo.id);

-- ── Control ──────────────────────────────────────────────────────────────────
SELECT m.id, m.nivel, m.orden, m.nombre, m.url,
       (SELECT GROUP_CONCAT(r.nombre) FROM s_menu_rol mr JOIN s_roles r ON r.id = mr.rol_id
         WHERE mr.menu_id = m.id) AS roles,
       (SELECT COUNT(*) FROM s_menu_usuario mu WHERE mu.menu_id = m.id) AS usuarios_sueltos
  FROM s_menu m WHERE m.url = '/mensajes';
-- Todos los roles activos.

SELECT table_name, table_rows
  FROM information_schema.tables
 WHERE table_schema = DATABASE() AND table_name LIKE 'chat\_%';
-- 4 tablas: chat_conversaciones, chat_mensajes, chat_participantes, chat_presencia.
