-- =============================================================================
-- menu_fiscalizacion_20261115.sql — «Fiscalización» como submenú, como en OSEDA
-- =============================================================================
--
-- Pedido del 15/11/2026: las actas y los acuerdos de pago tienen que estar en el
-- menú como en OSEDA (gestion_adm: Recaudaciones › Fiscalizacion › Deuda por
-- Empleador, Actas de Fiscalizacion, Acuerdos de Pago, …, Inspectores). Acá:
--
--   Fiscalización de Cuotas › Fiscalización › Actas de Fiscalización
--                                            › Acuerdos de Pago
--                                            › Fiscalizadores
--
-- Las tres opciones ya existían (sueltas en Fiscalización de Cuotas, de
-- sql/fisca_actas_20261114.sql y sql/fisca_fiscalizadores_20261114.sql): se
-- mueven adentro de la rama nueva. La rama la tiene todo rol (y toda persona
-- con permisos sueltos) que tenga alguna de las tres: una opción cuya rama no
-- está permitida no se dibuja (app._armar_arbol).
--
-- «Deuda por Empleador» de OSEDA es acá la Cuenta Corriente de Empleadores
-- (Empleadores › Cuenta Corriente, con el botón «Acta de fiscalización»): no se
-- repite en esta rama porque una URL va en una sola opción.
--
-- Ícono: building-government-search de Fluent UI System Color Icons (MIT,
-- @iconify-json/fluent-color 1.2.21), 18 × 18, con los id m17… (svg_unico los
-- vuelve a renombrar al dibujarlo).
--
-- Correrlo ENTERO (Alt+X). Idempotente. Quien tiene la sesión abierta ve el
-- cambio al minuto (app._permisos_al_dia).

USE sindicato;
SET NAMES utf8mb4;

SET @rama := (SELECT id FROM s_menu WHERE padre_id = 1 AND url IS NULL AND nombre = 'Fiscalización' LIMIT 1);
SET @rama := COALESCE(@rama, IF(EXISTS (SELECT 1 FROM s_menu WHERE id = 17), (SELECT MAX(id) + 1 FROM s_menu), 17));

INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (@rama, 1, 'Fiscalización', NULL,
        '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24"><g fill="none"><path fill="#70777d" d="M11 4.5h1.5v2H11z"/><rect width="5" height="3" x="11" y="2" fill="#f83f54" rx=".5"/><path fill="url(#m17SVGDJptbWZQ)" d="M5 13a7 7 0 0 1 14 0v.5H5z"/><path fill="url(#m17SVGLDCxLdNP)" d="M5 13a7 7 0 0 1 14 0v.5H5z"/><path fill="url(#m17SVGD9eGUF8x)" d="M5 13a7 7 0 0 1 14 0v.5H5z"/><path fill="url(#m17SVGkd9qNdZB)" d="M4.5 13A2.5 2.5 0 0 0 2 15.5V18h.337a3.5 3.5 0 0 0 5.688.923l3 3.077H21.25a.75.75 0 0 0 .75-.75V15.5a2.5 2.5 0 0 0-2.5-2.5z"/><path fill="url(#m17SVGxrIxdGZY)" fill-opacity=".5" d="M4.5 13A2.5 2.5 0 0 0 2 15.5V18h.337a3.5 3.5 0 0 0 5.688.923l3 3.077H21.25a.75.75 0 0 0 .75-.75V15.5a2.5 2.5 0 0 0-2.5-2.5z"/><path fill="url(#m17SVGfk88dcxv)" fill-opacity=".6" d="M4.5 13A2.5 2.5 0 0 0 2 15.5V18h.337a3.5 3.5 0 0 0 5.688.923l3 3.077H21.25a.75.75 0 0 0 .75-.75V15.5a2.5 2.5 0 0 0-2.5-2.5z"/><path fill="url(#m17SVGFVuSQbsj)" fill-opacity=".6" d="M4.5 13A2.5 2.5 0 0 0 2 15.5V18h.337a3.5 3.5 0 0 0 5.688.923l3 3.077H21.25a.75.75 0 0 0 .75-.75V15.5a2.5 2.5 0 0 0-2.5-2.5z"/><path fill="#63686e" d="M19 16.25a.75.75 0 0 0-1.5 0v2.5a.75.75 0 0 0 1.5 0z"/><path fill="#ca6407" d="M16 9.75a.75.75 0 0 0-1.5 0v1.5a.75.75 0 0 0 1.5 0zM12 9a.75.75 0 0 1 .75.75v1.5a.75.75 0 0 1-1.5 0v-1.5A.75.75 0 0 1 12 9m-2.5.75a.75.75 0 0 0-1.5 0v1.5a.75.75 0 0 0 1.5 0z"/><path fill="url(#m17SVGX3TltbBH)" d="M9 16.5a3.5 3.5 0 1 1-7 0a3.5 3.5 0 0 1 7 0"/><path fill="url(#m17SVGrlqdQeJP)" d="M5.5 21a4.5 4.5 0 0 0 2.607-.832l2.613 2.612a.75.75 0 1 0 1.06-1.06l-2.612-2.613A4.5 4.5 0 1 0 5.5 21m0-1.5a3 3 0 1 1 0-6a3 3 0 0 1 0 6"/><defs><linearGradient id="m17SVGDJptbWZQ" x1="12" x2="12" y1="6" y2="13.5" gradientUnits="userSpaceOnUse"><stop stop-color="#ffc205"/><stop offset=".735" stop-color="#ffa43d"/><stop offset="1" stop-color="#e67505"/></linearGradient><linearGradient id="m17SVGkd9qNdZB" x1="9.813" x2="19.143" y1="13" y2="22.541" gradientUnits="userSpaceOnUse"><stop stop-color="#aab3bd"/><stop offset="1" stop-color="#889096"/></linearGradient><linearGradient id="m17SVGxrIxdGZY" x1="8.875" x2="14.159" y1="21.357" y2="15.647" gradientUnits="userSpaceOnUse"><stop offset=".136" stop-opacity=".689"/><stop offset=".622" stop-opacity="0"/></linearGradient><linearGradient id="m17SVGX3TltbBH" x1="7.25" x2="2" y1="14.167" y2="20" gradientUnits="userSpaceOnUse"><stop stop-color="#fdfdfd"/><stop offset="1" stop-color="#b3e0ff"/></linearGradient><linearGradient id="m17SVGrlqdQeJP" x1="1.579" x2="10.842" y1="21.842" y2="14.316" gradientUnits="userSpaceOnUse"><stop stop-color="#0094f0"/><stop offset="1" stop-color="#29c3ff"/></linearGradient><radialGradient id="m17SVGLDCxLdNP" cx="0" cy="0" r="1" gradientTransform="matrix(0 4.03846 -7.47142 0 16.9 7.154)" gradientUnits="userSpaceOnUse"><stop stop-color="#ffd638"/><stop offset="1" stop-color="#ffd638" stop-opacity="0"/></radialGradient><radialGradient id="m17SVGD9eGUF8x" cx="0" cy="0" r="1" gradientTransform="matrix(5 -6.5 6.38034 4.90795 5.5 17)" gradientUnits="userSpaceOnUse"><stop offset=".495" stop-color="#e67505"/><stop offset=".837" stop-color="#e67505" stop-opacity="0"/></radialGradient><radialGradient id="m17SVGfk88dcxv" cx="0" cy="0" r="1" gradientTransform="matrix(5 -5 4.99801 4.99801 5.5 16.5)" gradientUnits="userSpaceOnUse"><stop offset=".122"/><stop offset=".884" stop-opacity="0"/></radialGradient><radialGradient id="m17SVGFVuSQbsj" cx="0" cy="0" r="1" gradientTransform="rotate(96.929 4.617 15.69)scale(5.1807 11.3238)" gradientUnits="userSpaceOnUse"><stop stop-color="#ffb357"/><stop offset="1" stop-color="#ffb357" stop-opacity="0"/></radialGradient></defs></g></svg>',
        9, 2, 1)
ON DUPLICATE KEY UPDATE padre_id = 1, nombre = VALUES(nombre), url = NULL, icono_svg = VALUES(icono_svg),
  orden = 9, nivel = 2, activo = 1;

-- Adentro, en el orden de OSEDA: actas, acuerdos y los fiscalizadores (sus
-- «Inspectores») al final.
UPDATE s_menu SET padre_id = @rama, nivel = 3, orden = 1 WHERE url = '/fiscalizacion/actas';
UPDATE s_menu SET padre_id = @rama, nivel = 3, orden = 2 WHERE url = '/fiscalizacion/acuerdos';
UPDATE s_menu SET padre_id = @rama, nivel = 3, orden = 9 WHERE url = '/fiscalizacion/fiscalizadores';

-- La rama para quien tenga alguna de las tres.
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT DISTINCT @rama, mr.rol_id
  FROM s_menu_rol mr JOIN s_menu m ON m.id = mr.menu_id
 WHERE m.padre_id = @rama
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = @rama AND x.rol_id = mr.rol_id);
INSERT INTO s_menu_usuario (usuario_id, menu_id)
SELECT DISTINCT mu.usuario_id, @rama
  FROM s_menu_usuario mu JOIN s_menu m ON m.id = mu.menu_id
 WHERE m.padre_id = @rama
   AND NOT EXISTS (SELECT 1 FROM s_menu_usuario x WHERE x.usuario_id = mu.usuario_id AND x.menu_id = @rama);

SELECT m.id, m.padre_id, m.nivel, m.orden, m.nombre, m.url,
       (SELECT GROUP_CONCAT(r.nombre ORDER BY r.id) FROM s_menu_rol mr JOIN s_roles r ON r.id = mr.rol_id
         WHERE mr.menu_id = m.id) AS roles
  FROM s_menu m
 WHERE m.padre_id = 1 OR m.padre_id = @rama
 ORDER BY m.padre_id = @rama, m.orden;
