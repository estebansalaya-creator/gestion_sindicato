-- =============================================================================
-- elecciones_20261118.sql — Elecciones: configuración, padrón electoral y
-- registro de quién vino a votar (pedido del 18/11/2026).
--
--   el_eleccion        una elección: motivo, día de la votación, lugar y horario,
--                      fecha de corte del padrón y antigüedad mínima
--   el_padron          el padrón electoral de la elección (una foto del padrón de
--                      afiliados al generarlo) y si cada uno votó: cuándo y quién
--                      lo registró
--   el_padron_mov      el rastro: votó, voto quitado, agregado o quitado del padrón
--
-- Se corre a mano, una vez (se puede volver a correr: no duplica).
-- Menú: Elecciones (rama 130) › Elecciones y Padrón (131, Administrador y
-- Supervisor) · Mesa de Votación (132, también Operador).
-- =============================================================================

CREATE TABLE IF NOT EXISTS el_eleccion (
  id                INT AUTO_INCREMENT PRIMARY KEY,
  motivo            VARCHAR(200)  NOT NULL COMMENT 'Motivo de la elección: renovación de comisión directiva, delegados…',
  fecha_votacion    DATE          NOT NULL COMMENT 'El día de la votación',
  hora_desde        TIME          NULL,
  hora_hasta        TIME          NULL,
  lugar             VARCHAR(200)  NULL,
  fecha_padron      DATE          NOT NULL COMMENT 'Corte del padrón: afiliado a esa fecha',
  antiguedad_meses  SMALLINT      NOT NULL DEFAULT 0 COMMENT 'Antigüedad mínima en el gremio a la fecha de corte',
  estado            ENUM('vigente','cerrada','anulada') NOT NULL DEFAULT 'vigente',
  padron_generado   DATETIME      NULL COMMENT 'Cuándo se armó el padrón',
  observaciones     VARCHAR(500)  NULL,
  motivo_anulacion  VARCHAR(300)  NULL,
  id_usuario        INT           NULL,
  id_usuario_cierre INT           NULL,
  fecha_cierre      DATETIME      NULL,
  creado            DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actualizado       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_el_fecha (fecha_votacion)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Elecciones del gremio';

CREATE TABLE IF NOT EXISTS el_padron (
  id                INT AUTO_INCREMENT PRIMARY KEY,
  id_eleccion       INT           NOT NULL,
  id_afiliado       INT           NOT NULL,
  orden             INT           NOT NULL COMMENT 'Número de orden en el padrón (alfabético)',
  cuil              VARCHAR(11)   NULL,
  nro_documento     VARCHAR(20)   NULL,
  apellido_nombres  VARCHAR(100)  NOT NULL,
  cuit_empleador    VARCHAR(11)   NULL,
  empleador         VARCHAR(200)  NULL,
  fecha_alta        DATE          NULL COMMENT 'Alta en el gremio, como estaba al armar el padrón',
  origen            ENUM('padron','manual') NOT NULL DEFAULT 'padron',
  voto              TINYINT(1)    NOT NULL DEFAULT 0,
  fecha_voto        DATETIME      NULL,
  id_usuario_voto   INT           NULL,
  creado            DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_el_padron (id_eleccion, id_afiliado),
  KEY idx_el_padron_doc (id_eleccion, nro_documento),
  KEY idx_el_padron_cuil (id_eleccion, cuil),
  KEY idx_el_padron_voto (id_eleccion, voto),
  CONSTRAINT fk_el_padron_el  FOREIGN KEY (id_eleccion) REFERENCES el_eleccion (id) ON DELETE CASCADE,
  CONSTRAINT fk_el_padron_afi FOREIGN KEY (id_afiliado) REFERENCES p_afiliados (id_afiliado)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Padrón electoral de cada elección y quién votó';

CREATE TABLE IF NOT EXISTS el_padron_mov (
  id                INT AUTO_INCREMENT PRIMARY KEY,
  id_eleccion       INT           NOT NULL,
  id_afiliado       INT           NOT NULL,
  accion            ENUM('voto','quita_voto','agregado','quitado') NOT NULL,
  detalle           VARCHAR(300)  NULL,
  id_usuario        INT           NULL,
  fecha             DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_el_mov (id_eleccion, fecha),
  CONSTRAINT fk_el_mov_el FOREIGN KEY (id_eleccion) REFERENCES el_eleccion (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Rastro del padrón electoral: votos, votos quitados, altas y quitas';

-- ── Menú ────────────────────────────────────────────────────────────────────
-- Elecciones
SET @m130 := (SELECT id FROM s_menu WHERE nombre = 'Elecciones' AND url IS NULL AND padre_id IS NULL LIMIT 1);
SET @m130 := COALESCE(@m130, IF(EXISTS (SELECT 1 FROM s_menu WHERE id = 130), (SELECT MAX(id) + 1 FROM s_menu), 130));
INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (@m130, NULL, 'Elecciones', NULL, '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24"><g fill="none"><path fill="url(#m130SVG3eth4W1S)" d="M6.25 3A3.25 3.25 0 0 0 3 6.25v11.5A3.25 3.25 0 0 0 6.25 21h11.5A3.25 3.25 0 0 0 21 17.75V6.25A3.25 3.25 0 0 0 17.75 3z"/><path fill="url(#m130SVGtSUABdlb)" d="m17.28 9.28l-6.754 6.747a.75.75 0 0 1-1.06 0L6.72 13.28a.75.75 0 0 1 1.06-1.06l2.217 2.216l6.223-6.217a.75.75 0 1 1 1.06 1.062"/><defs><linearGradient id="m130SVG3eth4W1S" x1="3.643" x2="16.065" y1="6.375" y2="19.281" gradientUnits="userSpaceOnUse"><stop stop-color="#36dff1"/><stop offset="1" stop-color="#2764e7"/></linearGradient><linearGradient id="m130SVGtSUABdlb" x1="8.616" x2="13.467" y1="8.634" y2="24.313" gradientUnits="userSpaceOnUse"><stop stop-color="#fff"/><stop offset="1" stop-color="#b3e0ff"/></linearGradient></defs></g></svg>', 3, 1, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url), padre_id = VALUES(padre_id),
  orden = VALUES(orden), nivel = VALUES(nivel), icono_svg = VALUES(icono_svg), activo = 1;
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT @m130, r.id FROM s_roles r
 WHERE r.nombre IN ('Administrador', 'Supervisor', 'Operador')
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = @m130 AND x.rol_id = r.id);

-- Elecciones y Padrón
SET @m131 := (SELECT id FROM s_menu WHERE url = '/elecciones' LIMIT 1);
SET @m131 := COALESCE(@m131, IF(EXISTS (SELECT 1 FROM s_menu WHERE id = 131), (SELECT MAX(id) + 1 FROM s_menu), 131));
INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (@m131, @m130, 'Elecciones y Padrón', '/elecciones', '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24"><g fill="none"><path fill="url(#m131SVGt5zIkdqB)" d="M21 7.5v10.25A3.25 3.25 0 0 1 17.75 21H6.25A3.25 3.25 0 0 1 3 17.75V7.5l9-1z"/><path fill="url(#m131SVGC4sBge8K)" d="M21 7.5v10.25A3.25 3.25 0 0 1 17.75 21H6.25A3.25 3.25 0 0 1 3 17.75V7.5l9-1z"/><path fill="url(#m131SVGf1bH4csv)" fill-opacity=".3" d="M21 7.5v10.25A3.25 3.25 0 0 1 17.75 21H6.25A3.25 3.25 0 0 1 3 17.75V7.5l9-1z"/><path fill="url(#m131SVGXrKzst3c)" d="M17.75 3A3.25 3.25 0 0 1 21 6.25V8H3V6.25A3.25 3.25 0 0 1 6.25 3z"/><path fill="url(#m131SVGHAkkzelU)" d="M17.5 12a5.5 5.5 0 1 1 0 11a5.5 5.5 0 0 1 0-11"/><path fill="url(#m131SVGUi1AWdea)" fill-rule="evenodd" d="M20.854 15.146a.5.5 0 0 1 0 .708l-4 4a.5.5 0 0 1-.708 0l-2-2a.5.5 0 0 1 .708-.708l1.646 1.647l3.646-3.647a.5.5 0 0 1 .708 0" clip-rule="evenodd"/><defs><linearGradient id="m131SVGt5zIkdqB" x1="9.429" x2="14.137" y1="6.5" y2="20.932" gradientUnits="userSpaceOnUse"><stop stop-color="#b3e0ff"/><stop offset="1" stop-color="#8cd0ff"/></linearGradient><linearGradient id="m131SVGC4sBge8K" x1="13.929" x2="16.625" y1="12.432" y2="24.267" gradientUnits="userSpaceOnUse"><stop stop-color="#dcf8ff" stop-opacity="0"/><stop offset="1" stop-color="#ff6ce8" stop-opacity=".7"/></linearGradient><linearGradient id="m131SVGXrKzst3c" x1="3.723" x2="5.356" y1="3" y2="11.537" gradientUnits="userSpaceOnUse"><stop stop-color="#0094f0"/><stop offset="1" stop-color="#2764e7"/></linearGradient><linearGradient id="m131SVGHAkkzelU" x1="12.393" x2="19.984" y1="14.063" y2="21.95" gradientUnits="userSpaceOnUse"><stop stop-color="#52d17c"/><stop offset="1" stop-color="#22918b"/></linearGradient><linearGradient id="m131SVGUi1AWdea" x1="15.313" x2="16.45" y1="15.51" y2="21.13" gradientUnits="userSpaceOnUse"><stop stop-color="#fff"/><stop offset="1" stop-color="#e3ffd9"/></linearGradient><radialGradient id="m131SVGf1bH4csv" cx="0" cy="0" r="1" gradientTransform="matrix(0 8.56818 -8.35714 0 17.786 19.023)" gradientUnits="userSpaceOnUse"><stop offset=".535" stop-color="#4a43cb"/><stop offset="1" stop-color="#4a43cb" stop-opacity="0"/></radialGradient></defs></g></svg>', 1, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url), padre_id = VALUES(padre_id),
  orden = VALUES(orden), nivel = VALUES(nivel), icono_svg = VALUES(icono_svg), activo = 1;
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT @m131, r.id FROM s_roles r
 WHERE r.nombre IN ('Administrador', 'Supervisor')
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = @m131 AND x.rol_id = r.id);

-- Mesa de Votación
SET @m132 := (SELECT id FROM s_menu WHERE url = '/elecciones/votacion' LIMIT 1);
SET @m132 := COALESCE(@m132, IF(EXISTS (SELECT 1 FROM s_menu WHERE id = 132), (SELECT MAX(id) + 1 FROM s_menu), 132));
INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (@m132, @m130, 'Mesa de Votación', '/elecciones/votacion', '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24"><g fill="none"><path fill="url(#m132SVGDgD0Ce7Q)" d="M15.755 14a2.25 2.25 0 0 1 2.248 2.249v.918a2.75 2.75 0 0 1-.512 1.6C15.945 20.928 13.42 22 10 22c-3.422 0-5.945-1.072-7.487-3.236a2.75 2.75 0 0 1-.51-1.596v-.92a2.25 2.25 0 0 1 2.249-2.25z"/><path fill="url(#m132SVGzmOIKbVn)" d="M15.755 14a2.25 2.25 0 0 1 2.248 2.249v.918a2.75 2.75 0 0 1-.512 1.6C15.945 20.928 13.42 22 10 22c-3.422 0-5.945-1.072-7.487-3.236a2.75 2.75 0 0 1-.51-1.596v-.92a2.25 2.25 0 0 1 2.249-2.25z"/><path fill="url(#m132SVGQCzeWcQa)" fill-opacity=".5" d="M15.755 14a2.25 2.25 0 0 1 2.248 2.249v.918a2.75 2.75 0 0 1-.512 1.6C15.945 20.928 13.42 22 10 22c-3.422 0-5.945-1.072-7.487-3.236a2.75 2.75 0 0 1-.51-1.596v-.92a2.25 2.25 0 0 1 2.249-2.25z"/><path fill="url(#m132SVGelmRgbGh)" d="M10 2.005a5 5 0 1 1 0 10a5 5 0 0 1 0-10"/><path fill="url(#m132SVGHAkkzelU)" d="M17.5 12a5.5 5.5 0 1 1 0 11a5.5 5.5 0 0 1 0-11"/><path fill="url(#m132SVGUi1AWdea)" fill-rule="evenodd" d="M20.854 15.146a.5.5 0 0 1 0 .708l-4 4a.5.5 0 0 1-.708 0l-2-2a.5.5 0 0 1 .708-.708l1.646 1.647l3.646-3.647a.5.5 0 0 1 .708 0" clip-rule="evenodd"/><defs><linearGradient id="m132SVGDgD0Ce7Q" x1="5.809" x2="8.394" y1="15.063" y2="23.319" gradientUnits="userSpaceOnUse"><stop offset=".125" stop-color="#9c6cfe"/><stop offset="1" stop-color="#7a41dc"/></linearGradient><linearGradient id="m132SVGzmOIKbVn" x1="10.004" x2="13.624" y1="13.047" y2="26.573" gradientUnits="userSpaceOnUse"><stop stop-color="#885edb" stop-opacity="0"/><stop offset="1" stop-color="#e362f8"/></linearGradient><linearGradient id="m132SVGelmRgbGh" x1="7.378" x2="12.474" y1="3.334" y2="11.472" gradientUnits="userSpaceOnUse"><stop offset=".125" stop-color="#9c6cfe"/><stop offset="1" stop-color="#7a41dc"/></linearGradient><linearGradient id="m132SVGHAkkzelU" x1="12.393" x2="19.984" y1="14.063" y2="21.95" gradientUnits="userSpaceOnUse"><stop stop-color="#52d17c"/><stop offset="1" stop-color="#22918b"/></linearGradient><linearGradient id="m132SVGUi1AWdea" x1="15.313" x2="16.45" y1="15.51" y2="21.13" gradientUnits="userSpaceOnUse"><stop stop-color="#fff"/><stop offset="1" stop-color="#e3ffd9"/></linearGradient><radialGradient id="m132SVGQCzeWcQa" cx="0" cy="0" r="1" gradientTransform="matrix(0 8.5 -8.49852 0 17.5 18.5)" gradientUnits="userSpaceOnUse"><stop offset=".493" stop-color="#30116e"/><stop offset=".912" stop-color="#30116e" stop-opacity="0"/></radialGradient></defs></g></svg>', 2, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url), padre_id = VALUES(padre_id),
  orden = VALUES(orden), nivel = VALUES(nivel), icono_svg = VALUES(icono_svg), activo = 1;
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT @m132, r.id FROM s_roles r
 WHERE r.nombre IN ('Administrador', 'Supervisor', 'Operador')
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = @m132 AND x.rol_id = r.id);
