-- =============================================================================
-- beneficios_correo_20261117.sql — Correo saliente, Beneficios (Convenio YMCA y Campañas)
-- =============================================================================
--
-- Pedidos del 17/11/2026:
--   · «configurar correo saliente como en oseda»: las tablas mail_* vinieron con
--     la base; acá se completan como en gestion_adm (origen del envío, cuenta
--     propia del remitente) y la fila de configuración, APAGADA.
--     Pantalla: Administración del Sistema › Correo Saliente (correo.py).
--   · Convenio con la YMCA (gimnasio): nómina de adheridos que se carga en el
--     sistema, cuota fija para todos por vigencia, recibos de sus transferencias
--     aparte de la cuota sindical, cuota de cada grupo familiar y control de la
--     factura mensual del gimnasio (cantidad de la nómina × precio que factura).
--     La diferencia con lo cobrado la cubre el sindicato. (ben_convenio.py)
--   · Campañas: flyers que se mandan por correo a los afiliados. (ben_campanias.py)
--
-- Menú nuevo «Beneficios» (Administrador y Supervisor) y «Correo Saliente» en
-- Administración del Sistema (Administrador).
--
-- Correr ENTERO (Alt+X) con un usuario que pueda crear tablas, ANTES de subir el
-- código. Idempotente.
--
-- DESPUÉS: agregar SIND_FERNET_KEY (la misma en el .env local y en Railway) y
-- completar Correo Saliente; cargar el precio que factura el gimnasio en Beneficios
-- › Convenio YMCA › Datos del Convenio.

USE sindicato;
SET NAMES utf8mb4;

-- ── 1. Correo: lo que le falta a las tablas de la base ──────────────────────
SET @hay := (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE()
              AND table_name = 'mail_envios' AND column_name = 'origen_tipo');
SET @sql := IF(@hay = 0,
  'ALTER TABLE mail_envios
     ADD COLUMN origen_tipo VARCHAR(30) NULL COMMENT ''De qué documento salió (campania, orden_pago…)'' AFTER entidad_id,
     ADD COLUMN origen_id INT NULL AFTER origen_tipo,
     ADD KEY idx_origen (origen_tipo, origen_id)',
  'SELECT ''mail_envios ya tiene el origen'' AS aviso');
PREPARE st FROM @sql; EXECUTE st; DEALLOCATE PREPARE st;

SET @hay := (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE()
              AND table_name = 'mail_remitentes' AND column_name = 'smtp_usuario');
SET @sql := IF(@hay = 0,
  'ALTER TABLE mail_remitentes
     ADD COLUMN smtp_usuario VARCHAR(150) NULL COMMENT ''Cuenta propia del remitente. NULL = sale por la de mail_config'' AFTER firma,
     ADD COLUMN smtp_password_cif BLOB NULL COMMENT ''Contraseña de aplicación, cifrada con Fernet. Nunca en claro'' AFTER smtp_usuario',
  'SELECT ''mail_remitentes ya tiene la cuenta propia'' AS aviso');
PREPARE st FROM @sql; EXECUTE st; DEALLOCATE PREPARE st;

-- Arranca existiendo pero apagada: nada sale hasta que un administrador la complete y la pruebe.
INSERT INTO mail_config (id, host, puerto, seguridad, limite_diario, activo)
VALUES (1, '', 587, 'starttls', 500, 0)
ON DUPLICATE KEY UPDATE id = id;

-- ── 2. Convenios (YMCA) ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ben_convenio (
  id                INT AUTO_INCREMENT PRIMARY KEY,
  nombre            VARCHAR(100) NOT NULL,
  id_proveedor      INT          NULL COMMENT 'El gimnasio: de él son las facturas que se controlan',
  id_motivo_ingreso INT          NULL COMMENT 'El motivo de los recibos de los adheridos',
  cc_desde          CHAR(6)      NULL COMMENT 'Desde qué mes se lleva la cuota de cada adherido (antes AEDA cobraba agrupado)',
  activo            TINYINT(1)   NOT NULL DEFAULT 1,
  observaciones     VARCHAR(500) NULL,
  creado            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actualizado       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_ben_conv_prov   FOREIGN KEY (id_proveedor)      REFERENCES c_proveedores (id),
  CONSTRAINT fk_ben_conv_motivo FOREIGN KEY (id_motivo_ingreso) REFERENCES c_motivos_de_ingreso (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Convenios de beneficios con un proveedor (la YMCA)';

CREATE TABLE IF NOT EXISTS ben_convenio_precio (
  id               INT AUTO_INCREMENT PRIMARY KEY,
  id_convenio      INT           NOT NULL,
  periodo_desde    CHAR(6)       NOT NULL COMMENT 'AAAAMM: rige hasta la vigencia siguiente',
  precio_proveedor DECIMAL(15,2) NULL     COMMENT 'Lo que factura el proveedor por adherido y por mes',
  cuota_afiliado   DECIMAL(15,2) NOT NULL COMMENT 'Lo que paga cada adherido por mes',
  observaciones    VARCHAR(300)  NULL,
  id_usuario       INT           NULL,
  creado           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_ben_precio (id_convenio, periodo_desde),
  CONSTRAINT fk_ben_precio_conv FOREIGN KEY (id_convenio) REFERENCES ben_convenio (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Precio del proveedor y cuota del afiliado por vigencia';

CREATE TABLE IF NOT EXISTS ben_adherido (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  id_convenio     INT          NOT NULL,
  id_afiliado     INT          NOT NULL COMMENT 'Titular o familiar del padrón',
  periodo_desde   CHAR(6)      NOT NULL COMMENT 'Primer mes que paga (AAAAMM)',
  periodo_hasta   CHAR(6)      NULL     COMMENT 'Último mes; NULL = sigue',
  observaciones   VARCHAR(300) NULL,
  id_usuario_alta INT          NULL,
  id_usuario_baja INT          NULL,
  creado          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  actualizado     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_ben_adh_conv (id_convenio, periodo_desde),
  KEY idx_ben_adh_afi (id_afiliado),
  CONSTRAINT fk_ben_adh_conv FOREIGN KEY (id_convenio) REFERENCES ben_convenio (id),
  CONSTRAINT fk_ben_adh_afi  FOREIGN KEY (id_afiliado) REFERENCES p_afiliados (id_afiliado)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Nómina de adheridos de un convenio: quién y desde/hasta qué mes';

INSERT INTO ben_convenio (nombre, id_proveedor, id_motivo_ingreso, cc_desde, observaciones)
SELECT 'YMCA', (SELECT id FROM c_proveedores WHERE REPLACE(cuit, '-', '') = '30525370190' LIMIT 1),
       (SELECT recibo_afiliado_motivo FROM s_institucion WHERE id = 1), '202611',
       'Gimnasio con convenio. Hasta octubre de 2026 AEDA registró lo cobrado en una orden por mes, sin detalle por afiliado.'
 WHERE NOT EXISTS (SELECT 1 FROM ben_convenio);

-- La cuota de los afiliados que ya se usaba (Datos del Sindicato): $ 25.000 de abril a agosto
-- de 2026, $ 30.000 desde septiembre. El precio del gimnasio se carga en la pantalla.
INSERT IGNORE INTO ben_convenio_precio (id_convenio, periodo_desde, precio_proveedor, cuota_afiliado, observaciones)
SELECT c.id, v.p, NULL, v.c, 'Cuota que ya se cobraba (Datos del Sindicato)'
  FROM ben_convenio c
  JOIN (SELECT '202604' AS p, 25000.00 AS c UNION ALL SELECT '202609', 30000.00) v
 WHERE c.nombre = 'YMCA';

-- ── 3. Campañas ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ben_campania (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  titulo         VARCHAR(150) NOT NULL COMMENT 'Para reconocerla en la lista',
  asunto         VARCHAR(200) NOT NULL,
  cuerpo         TEXT         NULL     COMMENT 'Texto del mail; el flyer va debajo',
  flyer_archivo  VARCHAR(300) NULL     COMMENT 'Ruta relativa a SIND_ADJUNTOS',
  flyer_nombre   VARCHAR(200) NULL,
  flyer_tipo     VARCHAR(80)  NULL     COMMENT 'image/png, image/jpeg o application/pdf',
  destino        ENUM('titulares','todos','adheridos') NOT NULL DEFAULT 'titulares',
  id_convenio    INT          NULL     COMMENT 'Con destino «adheridos»',
  estado         ENUM('borrador','enviando','pausada','enviada','cancelada') NOT NULL DEFAULT 'borrador',
  total          INT          NOT NULL DEFAULT 0,
  enviados       INT          NOT NULL DEFAULT 0,
  errores        INT          NOT NULL DEFAULT 0,
  id_usuario     INT          NULL,
  creada         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  envio_desde    DATETIME     NULL,
  envio_hasta    DATETIME     NULL,
  nota           VARCHAR(500) NULL     COMMENT 'Por qué se pausó',
  actualizado    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_ben_camp_conv FOREIGN KEY (id_convenio) REFERENCES ben_convenio (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Campañas de beneficios por correo a los afiliados';

CREATE TABLE IF NOT EXISTS ben_campania_envio (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  id_campania  INT          NOT NULL,
  id_afiliado  INT          NULL,
  email        VARCHAR(150) NOT NULL,
  nombre       VARCHAR(150) NULL,
  estado       ENUM('pendiente','ok','error','baja') NOT NULL DEFAULT 'pendiente',
  error        VARCHAR(600) NULL,
  enviado_at   DATETIME     NULL,
  UNIQUE KEY uq_ben_envio (id_campania, email),
  KEY idx_ben_envio_estado (id_campania, estado),
  CONSTRAINT fk_ben_envio_camp FOREIGN KEY (id_campania) REFERENCES ben_campania (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Un renglón por dirección: lo que falta mandar y cómo salió cada uno';

-- Quien pidió no recibir más campañas (enlace del pie del mail o a mano). Ley 25.326.
CREATE TABLE IF NOT EXISTS ben_baja_correo (
  email        VARCHAR(150) NOT NULL PRIMARY KEY,
  fecha        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  origen       ENUM('enlace','manual') NOT NULL DEFAULT 'enlace',
  id_campania  INT          NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Direcciones que no reciben campañas';

-- ── 4. Menú ─────────────────────────────────────────────────────────────────
SET @m200 := COALESCE((SELECT id FROM s_menu WHERE url = '/admin/usuarios' LIMIT 1), 0);
SET @m200 := COALESCE((SELECT padre_id FROM s_menu WHERE id = @m200), 200);   -- Administración del Sistema

-- Beneficios
SET @m120 := (SELECT id FROM s_menu WHERE nombre = 'Beneficios' AND url IS NULL AND COALESCE(padre_id, 0) = COALESCE(NULL, 0) LIMIT 1);
SET @m120 := COALESCE(@m120, IF(EXISTS (SELECT 1 FROM s_menu WHERE id = 120), (SELECT MAX(id) + 1 FROM s_menu), 120));
INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (@m120, NULL, 'Beneficios', NULL, '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24"><g fill="none"><path fill="url(#m120fluentColorGift240)" d="M20 12.5v6.25a3.25 3.25 0 0 1-3.066 3.245L16.75 22h-9.5a3.25 3.25 0 0 1-3.245-3.066L4 18.75V12.5z"/><path fill="url(#m120fluentColorGift244)" d="M19.75 7c.69 0 1.25.56 1.25 1.25v3.5a1.25 1.25 0 0 1-1 1.225H4c-.57-.116-1-.62-1-1.225v-3.5C3 7.56 3.56 7 4.25 7z"/><path fill="url(#m120fluentColorGift241)" d="M11.25 22V12h1.5v10z"/><path fill="url(#m120fluentColorGift242)" d="M11.25 13V8h1.5v5z"/><path fill="#000" fill-rule="evenodd" d="M9.5 8.5A3.25 3.25 0 1 1 12 3.173A3.25 3.25 0 1 1 14.5 8.5zM7.75 5.25a1.75 1.75 0 1 1 3.5 0V7H9.5a1.75 1.75 0 0 1-1.75-1.75m5 1.75h1.75a1.75 1.75 0 1 0-1.75-1.75z" clip-rule="evenodd"/><path fill="url(#m120fluentColorGift243)" fill-rule="evenodd" d="M9.5 8.5A3.25 3.25 0 1 1 12 3.173A3.25 3.25 0 1 1 14.5 8.5zM7.75 5.25a1.75 1.75 0 1 1 3.5 0V7H9.5a1.75 1.75 0 0 1-1.75-1.75m5 1.75h1.75a1.75 1.75 0 1 0-1.75-1.75z" clip-rule="evenodd"/><defs><linearGradient id="m120fluentColorGift240" x1="10.98" x2="10.98" y1="25.733" y2="8.8" gradientUnits="userSpaceOnUse"><stop stop-color="#BB45EA"/><stop offset=".348" stop-color="#8B57ED"/><stop offset="1" stop-color="#5B2AB5"/></linearGradient><linearGradient id="m120fluentColorGift241" x1="11.25" x2="11.25" y1="6.375" y2="20.261" gradientUnits="userSpaceOnUse"><stop stop-color="#FB5937"/><stop offset="1" stop-color="#FFCD0F"/></linearGradient><linearGradient id="m120fluentColorGift242" x1="11.25" x2="11.25" y1="-13.429" y2="21.571" gradientUnits="userSpaceOnUse"><stop stop-color="#FB5937"/><stop offset="1" stop-color="#FFCD0F"/></linearGradient><linearGradient id="m120fluentColorGift243" x1="15.194" x2="11.905" y1="8.498" y2="-4.901" gradientUnits="userSpaceOnUse"><stop stop-color="#FF6F47"/><stop offset="1" stop-color="#FFCD0F"/></linearGradient><radialGradient id="m120fluentColorGift244" cx="0" cy="0" r="1" gradientTransform="matrix(23.183 0 0 9.33595 12 4.76)" gradientUnits="userSpaceOnUse"><stop offset=".196" stop-color="#5B2AB5"/><stop offset=".763" stop-color="#8B57ED"/><stop offset="1" stop-color="#BB45EA"/></radialGradient></defs></g></svg>', 5, 1, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url), padre_id = VALUES(padre_id),
  orden = VALUES(orden), nivel = VALUES(nivel), icono_svg = VALUES(icono_svg), activo = 1;
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT @m120, r.id FROM s_roles r
 WHERE r.nombre IN ('Administrador', 'Supervisor')
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = @m120 AND x.rol_id = r.id);

-- Convenio YMCA
SET @m121 := (SELECT id FROM s_menu WHERE nombre = 'Convenio YMCA' AND url IS NULL AND COALESCE(padre_id, 0) = COALESCE(@m120, 0) LIMIT 1);
SET @m121 := COALESCE(@m121, IF(EXISTS (SELECT 1 FROM s_menu WHERE id = 121), (SELECT MAX(id) + 1 FROM s_menu), 121));
INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (@m121, @m120, 'Convenio YMCA', NULL, '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24"><g fill="none"><circle cx="14" cy="10" r="8" fill="url(#m121fluentColorSport240)"/><circle cx="14" cy="10" r="8" fill="url(#m121fluentColorSport241)" fill-opacity=".8"/><path fill="url(#m121fluentColorSport244)" d="M9.468 3.407L14.5 8.439l.761-.761a4.23 4.23 0 0 1-.76-2.428c0-1.196.493-2.277 1.289-3.05c.596.137 1.168.34 1.706.602a2.75 2.75 0 0 0-1.147 3.789l2.753-2.754q.58.481 1.06 1.061L17.41 7.651a2.75 2.75 0 0 0 3.789-1.147A8 8 0 0 1 21.8 8.21a4.24 4.24 0 0 1-3.05 1.29a4.23 4.23 0 0 1-2.428-.762l-.761.762l5.032 5.032q-.43.624-.966 1.155L14.5 10.56l-3.97 3.97l-1.06-1.062l3.97-3.97l-5.127-5.126a8 8 0 0 1 1.155-.966" opacity=".6"/><path fill="url(#m121fluentColorSport242)" d="M4.25 9A2.25 2.25 0 0 0 2 11.25v2A8.75 8.75 0 0 0 10.75 22h2A2.25 2.25 0 0 0 15 19.75v-2A8.75 8.75 0 0 0 6.25 9z"/><path fill="url(#m121fluentColorSport243)" fill-opacity=".9" d="M4.25 9A2.25 2.25 0 0 0 2 11.25v2A8.75 8.75 0 0 0 10.75 22h2A2.25 2.25 0 0 0 15 19.75v-2A8.75 8.75 0 0 0 6.25 9z"/><path fill="#FFC470" d="M7.78 13.72a.75.75 0 0 0-1.06 1.06l2.5 2.5a.75.75 0 1 0 1.06-1.06z"/><defs><radialGradient id="m121fluentColorSport240" cx="0" cy="0" r="1" gradientTransform="rotate(-90 21.244 5.09)scale(27.9566)" gradientUnits="userSpaceOnUse"><stop stop-color="#EB4824"/><stop offset=".978" stop-color="#FF921F"/></radialGradient><radialGradient id="m121fluentColorSport241" cx="0" cy="0" r="1" gradientTransform="matrix(6.66667 -6.66667 9.1204 9.1204 8 16)" gradientUnits="userSpaceOnUse"><stop offset=".588" stop-color="#AA1D2D"/><stop offset=".931" stop-color="#EB4824" stop-opacity=".1"/></radialGradient><radialGradient id="m121fluentColorSport242" cx="0" cy="0" r="1" gradientTransform="rotate(53.531 -7.917 7.95)scale(16.9004 15.2827)" gradientUnits="userSpaceOnUse"><stop offset=".24" stop-color="#AE5606"/><stop offset="1" stop-color="#944600"/></radialGradient><radialGradient id="m121fluentColorSport243" cx="0" cy="0" r="1" gradientTransform="rotate(10.938 -129.48 47.962)scale(19.2374)" gradientUnits="userSpaceOnUse"><stop offset=".626" stop-color="#FFA43D" stop-opacity="0"/><stop offset=".927" stop-color="#FFA43D"/></radialGradient><linearGradient id="m121fluentColorSport244" x1="20.05" x2="11.576" y1="4.194" y2="12.667" gradientUnits="userSpaceOnUse"><stop offset=".713" stop-color="#8E250B"/><stop offset=".903" stop-color="#8E250B" stop-opacity="0"/></linearGradient></defs></g></svg>', 1, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url), padre_id = VALUES(padre_id),
  orden = VALUES(orden), nivel = VALUES(nivel), icono_svg = VALUES(icono_svg), activo = 1;
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT @m121, r.id FROM s_roles r
 WHERE r.nombre IN ('Administrador', 'Supervisor')
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = @m121 AND x.rol_id = r.id);

-- Nómina de Adheridos
SET @m122 := (SELECT id FROM s_menu WHERE url = '/beneficios/ymca/adheridos' LIMIT 1);
SET @m122 := COALESCE(@m122, IF(EXISTS (SELECT 1 FROM s_menu WHERE id = 122), (SELECT MAX(id) + 1 FROM s_menu), 122));
INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (@m122, @m121, 'Nómina de Adheridos', '/beneficios/ymca/adheridos', '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24"><g fill="none"><path fill="url(#m122fluentColorPeopleList240)" d="M4.25 14A2.25 2.25 0 0 0 2 16.25v.25S2 21 8 21s6-4.5 6-4.5v-.25A2.25 2.25 0 0 0 11.75 14z"/><path fill="url(#m122fluentColorPeopleList241)" d="M4.25 14A2.25 2.25 0 0 0 2 16.25v.25S2 21 8 21s6-4.5 6-4.5v-.25A2.25 2.25 0 0 0 11.75 14z"/><path fill="url(#m122fluentColorPeopleList242)" fill-opacity=".75" d="M4.25 14A2.25 2.25 0 0 0 2 16.25v.25S2 21 8 21s6-4.5 6-4.5v-.25A2.25 2.25 0 0 0 11.75 14z"/><path fill="url(#m122fluentColorPeopleList243)" d="M17 12a3 3 0 1 0 0-6a3 3 0 0 0 0 6"/><path fill="url(#m122fluentColorPeopleList244)" d="M8 12a4 4 0 1 0 0-8a4 4 0 0 0 0 8"/><path fill="url(#m122fluentColorPeopleList245)" d="M11 13a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-7a2 2 0 0 1-2-2z"/><path fill="url(#m122fluentColorPeopleList246)" d="M13.75 13a.75.75 0 0 0 0 1.5h5.5a.75.75 0 0 0 0-1.5zm0 2.75a.75.75 0 0 0 0 1.5h5.5a.75.75 0 0 0 0-1.5zm0 2.75a.75.75 0 0 0 0 1.5h5.5a.75.75 0 0 0 0-1.5z"/><defs><linearGradient id="m122fluentColorPeopleList240" x1="4.854" x2="7.41" y1="14.931" y2="21.927" gradientUnits="userSpaceOnUse"><stop offset=".125" stop-color="#BD96FF"/><stop offset="1" stop-color="#9C6CFE"/></linearGradient><linearGradient id="m122fluentColorPeopleList241" x1="8" x2="11.607" y1="13.167" y2="24.721" gradientUnits="userSpaceOnUse"><stop stop-color="#885EDB" stop-opacity="0"/><stop offset="1" stop-color="#E362F8"/></linearGradient><linearGradient id="m122fluentColorPeopleList242" x1="15" x2="9" y1="18" y2="18" gradientUnits="userSpaceOnUse"><stop stop-color="#0A1852" stop-opacity=".75"/><stop offset="1" stop-color="#0A1852" stop-opacity="0"/></linearGradient><linearGradient id="m122fluentColorPeopleList243" x1="15.427" x2="18.485" y1="6.798" y2="11.68" gradientUnits="userSpaceOnUse"><stop offset=".125" stop-color="#9C6CFE"/><stop offset="1" stop-color="#7A41DC"/></linearGradient><linearGradient id="m122fluentColorPeopleList244" x1="5.902" x2="9.98" y1="5.063" y2="11.574" gradientUnits="userSpaceOnUse"><stop offset=".125" stop-color="#BD96FF"/><stop offset="1" stop-color="#9C6CFE"/></linearGradient><linearGradient id="m122fluentColorPeopleList245" x1="14.929" x2="19.143" y1="11" y2="21.407" gradientUnits="userSpaceOnUse"><stop stop-color="#B3E0FF"/><stop offset="1" stop-color="#8CD0FF"/></linearGradient><linearGradient id="m122fluentColorPeopleList246" x1="9.5" x2="20" y1="8.1" y2="20" gradientUnits="userSpaceOnUse"><stop stop-color="#0FAFFF"/><stop offset="1" stop-color="#2764E7"/></linearGradient></defs></g></svg>', 1, 3, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url), padre_id = VALUES(padre_id),
  orden = VALUES(orden), nivel = VALUES(nivel), icono_svg = VALUES(icono_svg), activo = 1;
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT @m122, r.id FROM s_roles r
 WHERE r.nombre IN ('Administrador', 'Supervisor')
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = @m122 AND x.rol_id = r.id);

-- Recibos de Adheridos
SET @m123 := (SELECT id FROM s_menu WHERE url = '/beneficios/ymca/recibos' LIMIT 1);
SET @m123 := COALESCE(@m123, IF(EXISTS (SELECT 1 FROM s_menu WHERE id = 123), (SELECT MAX(id) + 1 FROM s_menu), 123));
INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (@m123, @m121, 'Recibos de Adheridos', '/beneficios/ymca/recibos', '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24"><g fill="none"><path fill="url(#m123fluentColorCoinMultiple240)" d="M12 22c3.866 0 7-1.79 7-4v-2H5v2c0 2.21 3.134 4 7 4"/><ellipse cx="12" cy="16" fill="url(#m123fluentColorCoinMultiple241)" rx="7" ry="4"/><path fill="url(#m123fluentColorCoinMultiple242)" d="M12 17c3.866 0 7-1.79 7-4v-2H5v2c0 2.21 3.134 4 7 4"/><ellipse cx="12" cy="11" fill="url(#m123fluentColorCoinMultiple243)" rx="7" ry="4"/><path fill="url(#m123fluentColorCoinMultiple244)" d="M12 12c3.866 0 7-1.79 7-4V6H5v2c0 2.21 3.134 4 7 4"/><ellipse cx="12" cy="6" fill="url(#m123fluentColorCoinMultiple245)" rx="7" ry="4"/><defs><linearGradient id="m123fluentColorCoinMultiple240" x1="8.713" x2="10.841" y1="17.472" y2="22.442" gradientUnits="userSpaceOnUse"><stop stop-color="#FFA43D"/><stop offset="1" stop-color="#FB5937"/></linearGradient><linearGradient id="m123fluentColorCoinMultiple241" x1="19.02" x2="11.741" y1="19.997" y2="9.577" gradientUnits="userSpaceOnUse"><stop stop-color="#FF8A69"/><stop offset="1" stop-color="#FFCD0F"/></linearGradient><linearGradient id="m123fluentColorCoinMultiple242" x1="8.713" x2="10.841" y1="12.472" y2="17.442" gradientUnits="userSpaceOnUse"><stop stop-color="#FFA43D"/><stop offset="1" stop-color="#FB5937"/></linearGradient><linearGradient id="m123fluentColorCoinMultiple243" x1="19.02" x2="11.741" y1="14.997" y2="4.577" gradientUnits="userSpaceOnUse"><stop stop-color="#FF8A69"/><stop offset="1" stop-color="#FFCD0F"/></linearGradient><linearGradient id="m123fluentColorCoinMultiple244" x1="8.713" x2="10.841" y1="7.472" y2="12.442" gradientUnits="userSpaceOnUse"><stop stop-color="#FFA43D"/><stop offset="1" stop-color="#FB5937"/></linearGradient><linearGradient id="m123fluentColorCoinMultiple245" x1="19.02" x2="11.741" y1="9.997" y2="-.423" gradientUnits="userSpaceOnUse"><stop stop-color="#FF8A69"/><stop offset="1" stop-color="#FFCD0F"/></linearGradient></defs></g></svg>', 2, 3, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url), padre_id = VALUES(padre_id),
  orden = VALUES(orden), nivel = VALUES(nivel), icono_svg = VALUES(icono_svg), activo = 1;
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT @m123, r.id FROM s_roles r
 WHERE r.nombre IN ('Administrador', 'Supervisor')
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = @m123 AND x.rol_id = r.id);

-- Cuotas de Adheridos
SET @m124 := (SELECT id FROM s_menu WHERE url = '/beneficios/ymca/cuotas' LIMIT 1);
SET @m124 := COALESCE(@m124, IF(EXISTS (SELECT 1 FROM s_menu WHERE id = 124), (SELECT MAX(id) + 1 FROM s_menu), 124));
INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (@m124, @m121, 'Cuotas de Adheridos', '/beneficios/ymca/cuotas', '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24"><g fill="none"><path fill="url(#m124fluentColorSavings240)" d="M21.071 8.86c.604.998.929 2.203.929 3.64c0 2.206-.833 3.75-1.68 4.738A6.7 6.7 0 0 1 19 18.421v1.83A1.75 1.75 0 0 1 17.25 22H16a1.5 1.5 0 0 1-1.5-1.5h-2A1.5 1.5 0 0 1 11 22H9.75A1.75 1.75 0 0 1 8 20.25v-.684a7 7 0 0 1-.464-.175A6.5 6.5 0 0 1 5.47 18.03a10 10 0 0 1-1.605-2.13a.49.49 0 0 0-.329-.259A1.84 1.84 0 0 1 2 13.828v-1.753c0-.843.61-1.562 1.44-1.7c.087-.015.216-.101.277-.284c.192-.576.565-1.434 1.253-2.121a8 8 0 0 1 1.658-1.246q.206-.117.372-.201V3.67c0-.938 1.13-1.323 1.74-.716c.33.329.81.768 1.341 1.134s1.033.66 1.454.66c4.248 0 7.684 1.051 9.536 4.11"/><path fill="url(#m124fluentColorSavings241)" d="M9 10a1 1 0 1 1-2 0a1 1 0 0 1 2 0"/><path fill="#9F1459" d="M10.55 6.503a1.2 1.2 0 0 1 1.568-.652l7.376 3.045a1.201 1.201 0 1 1-.917 2.221l-7.376-3.045a1.2 1.2 0 0 1-.652-1.57"/><path fill="url(#m124fluentColorSavings242)" d="M17.545 10.69a4.001 4.001 0 1 0-5.244-2.164z"/><path fill="url(#m124fluentColorSavings243)" fill-opacity=".8" d="M17.545 10.69a4.001 4.001 0 1 0-5.244-2.164z"/><defs><radialGradient id="m124fluentColorSavings240" cx="0" cy="0" r="1" gradientTransform="matrix(5.1875 18.18747 -18.81061 5.36523 8.125 4.563)" gradientUnits="userSpaceOnUse"><stop stop-color="#F08AF4"/><stop offset=".581" stop-color="#E869CE"/><stop offset="1" stop-color="#D7257D"/></radialGradient><radialGradient id="m124fluentColorSavings241" cx="0" cy="0" r="1" gradientTransform="rotate(59.532 -4.541 11.412)scale(1.69458)" gradientUnits="userSpaceOnUse"><stop stop-color="#B91D6B"/><stop offset="1" stop-color="#670938"/></radialGradient><linearGradient id="m124fluentColorSavings242" x1="18.745" x2="12.651" y1="9.82" y2="4.629" gradientUnits="userSpaceOnUse"><stop stop-color="#FF8A69"/><stop offset="1" stop-color="#FFCD0F"/></linearGradient><linearGradient id="m124fluentColorSavings243" x1="17.188" x2="14.563" y1="3.438" y2="9.75" gradientUnits="userSpaceOnUse"><stop offset=".67" stop-color="#FB5937" stop-opacity="0"/><stop offset="1" stop-color="#CD3E1D"/></linearGradient></defs></g></svg>', 3, 3, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url), padre_id = VALUES(padre_id),
  orden = VALUES(orden), nivel = VALUES(nivel), icono_svg = VALUES(icono_svg), activo = 1;
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT @m124, r.id FROM s_roles r
 WHERE r.nombre IN ('Administrador', 'Supervisor')
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = @m124 AND x.rol_id = r.id);

-- Control Mensual
SET @m125 := (SELECT id FROM s_menu WHERE url = '/beneficios/ymca/control' LIMIT 1);
SET @m125 := COALESCE(@m125, IF(EXISTS (SELECT 1 FROM s_menu WHERE id = 125), (SELECT MAX(id) + 1 FROM s_menu), 125));
INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (@m125, @m121, 'Control Mensual', '/beneficios/ymca/control', '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24"><g fill="none"><path fill="url(#m125fluentColorClipboardTask240)" d="M4 6.25A2.25 2.25 0 0 1 6.25 4h11.5A2.25 2.25 0 0 1 20 6.25v13.5A2.25 2.25 0 0 1 17.75 22H6.25A2.25 2.25 0 0 1 4 19.75z"/><path fill="url(#m125fluentColorClipboardTask243)" fill-opacity=".7" d="M4 6.25A2.25 2.25 0 0 1 6.25 4h11.5A2.25 2.25 0 0 1 20 6.25v13.5A2.25 2.25 0 0 1 17.75 22H6.25A2.25 2.25 0 0 1 4 19.75z"/><path fill="url(#m125fluentColorClipboardTask244)" fill-opacity=".4" d="M4 6.25A2.25 2.25 0 0 1 6.25 4h11.5A2.25 2.25 0 0 1 20 6.25v13.5A2.25 2.25 0 0 1 17.75 22H6.25A2.25 2.25 0 0 1 4 19.75z"/><path fill="url(#m125fluentColorClipboardTask241)" d="M8 4.25a2.25 2.25 0 0 0 2.25 2.25h3.5a2.25 2.25 0 0 0 0-4.5h-3.5A2.25 2.25 0 0 0 8 4.25"/><path fill="url(#m125fluentColorClipboardTask242)" fill-opacity=".9" d="M17.03 11.03a.75.75 0 1 0-1.06-1.06L11 14.94l-1.97-1.97a.75.75 0 0 0-1.06 1.06l2.5 2.5a.75.75 0 0 0 1.06 0z"/><defs><linearGradient id="m125fluentColorClipboardTask240" x1="4" x2="18.146" y1="5.8" y2="23.483" gradientUnits="userSpaceOnUse"><stop stop-color="#36DFF1"/><stop offset="1" stop-color="#0094F0"/></linearGradient><linearGradient id="m125fluentColorClipboardTask241" x1="12" x2="12" y1="2" y2="6.5" gradientUnits="userSpaceOnUse"><stop stop-color="#FFE06B"/><stop offset="1" stop-color="#FAB500"/></linearGradient><linearGradient id="m125fluentColorClipboardTask242" x1="18" x2="10.265" y1="18.5" y2="7.732" gradientUnits="userSpaceOnUse"><stop stop-color="#9DEAFF"/><stop offset="1" stop-color="#fff"/></linearGradient><radialGradient id="m125fluentColorClipboardTask243" cx="0" cy="0" r="1" gradientTransform="matrix(0 6.16892 -6.75 0 12 3)" gradientUnits="userSpaceOnUse"><stop stop-color="#0A1852"/><stop offset=".9" stop-color="#0A1852" stop-opacity="0"/></radialGradient><radialGradient id="m125fluentColorClipboardTask244" cx="0" cy="0" r="1" gradientTransform="matrix(0 2.79325 -4.95298 0 12 4.618)" gradientUnits="userSpaceOnUse"><stop stop-color="#0A1852"/><stop offset="1" stop-color="#0A1852" stop-opacity="0"/></radialGradient></defs></g></svg>', 4, 3, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url), padre_id = VALUES(padre_id),
  orden = VALUES(orden), nivel = VALUES(nivel), icono_svg = VALUES(icono_svg), activo = 1;
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT @m125, r.id FROM s_roles r
 WHERE r.nombre IN ('Administrador', 'Supervisor')
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = @m125 AND x.rol_id = r.id);

-- Datos del Convenio
SET @m126 := (SELECT id FROM s_menu WHERE url = '/beneficios/ymca/convenio' LIMIT 1);
SET @m126 := COALESCE(@m126, IF(EXISTS (SELECT 1 FROM s_menu WHERE id = 126), (SELECT MAX(id) + 1 FROM s_menu), 126));
INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (@m126, @m121, 'Datos del Convenio', '/beneficios/ymca/convenio', '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24"><g fill="none"><path fill="url(#m126fluentColorDocumentText240)" d="M6 22h12a2 2 0 0 0 2-2V9l-5-2l-2-5H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2"/><path fill="url(#m126fluentColorDocumentText243)" fill-opacity=".5" d="M6 22h12a2 2 0 0 0 2-2V9l-5-2l-2-5H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2"/><path fill="url(#m126fluentColorDocumentText241)" d="M13 7.5V2l7 7h-5.5A1.5 1.5 0 0 1 13 7.5"/><path fill="url(#m126fluentColorDocumentText242)" fill-opacity=".9" d="M8.75 11.5a.75.75 0 0 0 0 1.5h6.5a.75.75 0 0 0 0-1.5zm0 2.75a.75.75 0 0 0 0 1.5h6.5a.75.75 0 0 0 0-1.5zm0 2.75a.75.75 0 0 0 0 1.5h6.5a.75.75 0 0 0 0-1.5z"/><defs><linearGradient id="m126fluentColorDocumentText240" x1="15.2" x2="16.822" y1="2" y2="18.87" gradientUnits="userSpaceOnUse"><stop stop-color="#6CE0FF"/><stop offset="1" stop-color="#4894FE"/></linearGradient><linearGradient id="m126fluentColorDocumentText241" x1="16.488" x2="14.738" y1="4.917" y2="7.833" gradientUnits="userSpaceOnUse"><stop stop-color="#9FF0F9"/><stop offset="1" stop-color="#B3E0FF"/></linearGradient><linearGradient id="m126fluentColorDocumentText242" x1="16" x2="8.196" y1="21.3" y2="8.58" gradientUnits="userSpaceOnUse"><stop stop-color="#9DEAFF"/><stop offset="1" stop-color="#fff"/></linearGradient><radialGradient id="m126fluentColorDocumentText243" cx="0" cy="0" r="1" gradientTransform="matrix(-8.66665 9.09357 -5.3691 -5.11703 20.667 2.625)" gradientUnits="userSpaceOnUse"><stop offset=".362" stop-color="#4A43CB"/><stop offset="1" stop-color="#4A43CB" stop-opacity="0"/></radialGradient></defs></g></svg>', 5, 3, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url), padre_id = VALUES(padre_id),
  orden = VALUES(orden), nivel = VALUES(nivel), icono_svg = VALUES(icono_svg), activo = 1;
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT @m126, r.id FROM s_roles r
 WHERE r.nombre IN ('Administrador', 'Supervisor')
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = @m126 AND x.rol_id = r.id);

-- Campañas
SET @m127 := (SELECT id FROM s_menu WHERE url = '/beneficios/campanias' LIMIT 1);
SET @m127 := COALESCE(@m127, IF(EXISTS (SELECT 1 FROM s_menu WHERE id = 127), (SELECT MAX(id) + 1 FROM s_menu), 127));
INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (@m127, @m120, 'Campañas', '/beneficios/campanias', '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24"><g fill="none"><path fill="url(#m127fluentColorMegaphoneLoud240)" fill-rule="evenodd" d="M8 18a4 4 0 1 1 8 0a4 4 0 0 1-8 0m4-2.5a2.5 2.5 0 1 0 0 5a2.5 2.5 0 0 0 0-5" clip-rule="evenodd"/><path fill="url(#m127fluentColorMegaphoneLoud241)" fill-opacity=".8" fill-rule="evenodd" d="M8 18a4 4 0 1 1 8 0a4 4 0 0 1-8 0m4-2.5a2.5 2.5 0 1 0 0 5a2.5 2.5 0 0 0 0-5" clip-rule="evenodd"/><path fill="url(#m127fluentColorMegaphoneLoud242)" d="M9.076 4.318a2.325 2.325 0 0 1 3.795-.577l7.006 7.506a2.325 2.325 0 0 1-.758 3.712L6.968 20.343a1.8 1.8 0 0 1-1.964-.337L3.565 18.65a1.8 1.8 0 0 1-.387-2.091z"/><path fill="url(#m127fluentColorMegaphoneLoud243)" fill-opacity=".8" d="M9.076 4.318a2.325 2.325 0 0 1 3.795-.577l7.006 7.506a2.325 2.325 0 0 1-.758 3.712L6.968 20.343a1.8 1.8 0 0 1-1.964-.337L3.565 18.65a1.8 1.8 0 0 1-.387-2.091z"/><path fill="url(#m127fluentColorMegaphoneLoud244)" d="M17.212 2.237a.75.75 0 0 0-1.423-.474l-.75 2.249a.75.75 0 0 0 1.423.474zm4.568-.017a.75.75 0 0 1 0 1.06l-2.5 2.5a.75.75 0 1 1-1.06-1.06l2.5-2.5a.75.75 0 0 1 1.06 0M19 8.25a.75.75 0 0 1 .75-.75h2a.75.75 0 0 1 0 1.5h-2a.75.75 0 0 1-.75-.75"/><defs><linearGradient id="m127fluentColorMegaphoneLoud240" x1="17.714" x2="14.271" y1="27.143" y2="18.684" gradientUnits="userSpaceOnUse"><stop stop-color="#43E5CA"/><stop offset="1" stop-color="#0C74A1"/></linearGradient><linearGradient id="m127fluentColorMegaphoneLoud241" x1="10.286" x2="13.717" y1="15.143" y2="23.713" gradientUnits="userSpaceOnUse"><stop offset=".08" stop-color="#E362F8"/><stop offset=".656" stop-color="#96F" stop-opacity="0"/></linearGradient><linearGradient id="m127fluentColorMegaphoneLoud242" x1="3.625" x2="15.699" y1="6.282" y2="18.832" gradientUnits="userSpaceOnUse"><stop stop-color="#43E5CA"/><stop offset="1" stop-color="#1384B1"/></linearGradient><linearGradient id="m127fluentColorMegaphoneLoud243" x1="11.752" x2="19.408" y1="12.841" y2="25.419" gradientUnits="userSpaceOnUse"><stop stop-color="#96F" stop-opacity="0"/><stop offset=".63" stop-color="#E362F8"/></linearGradient><radialGradient id="m127fluentColorMegaphoneLoud244" cx="0" cy="0" r="1" gradientTransform="matrix(16.15331 -16.69065 16.69331 16.15589 7.212 17.047)" gradientUnits="userSpaceOnUse"><stop offset=".623" stop-color="#FB5937"/><stop offset=".935" stop-color="#FFA43D"/></radialGradient></defs></g></svg>', 2, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url), padre_id = VALUES(padre_id),
  orden = VALUES(orden), nivel = VALUES(nivel), icono_svg = VALUES(icono_svg), activo = 1;
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT @m127, r.id FROM s_roles r
 WHERE r.nombre IN ('Administrador', 'Supervisor')
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = @m127 AND x.rol_id = r.id);

-- Correo Saliente
SET @m211 := (SELECT id FROM s_menu WHERE url = '/admin/correo' LIMIT 1);
SET @m211 := COALESCE(@m211, IF(EXISTS (SELECT 1 FROM s_menu WHERE id = 211), (SELECT MAX(id) + 1 FROM s_menu), 211));
INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (@m211, @m200, 'Correo Saliente', '/admin/correo', '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24"><g fill="none"><path fill="#367AF2" d="M22 7.5v9.25a3.25 3.25 0 0 1-3.065 3.245L18.75 20H5.25a3.25 3.25 0 0 1-3.245-3.066L2 16.75V7.5l9.652 5.056a.75.75 0 0 0 .696 0z"/><path fill="url(#m211fluentColorMail240)" d="M22 7.5v9.25a3.25 3.25 0 0 1-3.065 3.245L18.75 20H5.25a3.25 3.25 0 0 1-3.245-3.066L2 16.75V7.5l9.652 5.056a.75.75 0 0 0 .696 0z"/><path fill="url(#m211fluentColorMail241)" d="M22 7.5v9.25a3.25 3.25 0 0 1-3.065 3.245L18.75 20H5.25a3.25 3.25 0 0 1-3.245-3.066L2 16.75V7.5l9.652 5.056a.75.75 0 0 0 .696 0z"/><path fill="url(#m211fluentColorMail242)" fill-opacity=".75" d="M22 7.5v9.25a3.25 3.25 0 0 1-3.065 3.245L18.75 20H5.25a3.25 3.25 0 0 1-3.245-3.066L2 16.75V7.5l9.652 5.056a.75.75 0 0 0 .696 0z"/><path fill="url(#m211fluentColorMail243)" fill-opacity=".7" d="M22 7.5v9.25a3.25 3.25 0 0 1-3.065 3.245L18.75 20H5.25a3.25 3.25 0 0 1-3.245-3.066L2 16.75V7.5l9.652 5.056a.75.75 0 0 0 .696 0z"/><path fill="url(#m211fluentColorMail244)" d="m2 7.86l9.652 5.056a.75.75 0 0 0 .696 0L22 7.86v-.61A3.25 3.25 0 0 0 18.75 4H5.25A3.25 3.25 0 0 0 2 7.25z"/><defs><linearGradient id="m211fluentColorMail240" x1="14.539" x2="20.005" y1="9.95" y2="20.515" gradientUnits="userSpaceOnUse"><stop offset=".199" stop-color="#0094F0" stop-opacity="0"/><stop offset=".431" stop-color="#0094F0"/></linearGradient><linearGradient id="m211fluentColorMail241" x1="9.143" x2="3.828" y1="8.816" y2="20.865" gradientUnits="userSpaceOnUse"><stop offset=".191" stop-color="#0094F0" stop-opacity="0"/><stop offset=".431" stop-color="#0094F0"/></linearGradient><linearGradient id="m211fluentColorMail242" x1="17.273" x2="18.143" y1="14.957" y2="21.151" gradientUnits="userSpaceOnUse"><stop stop-color="#2764E7" stop-opacity="0"/><stop offset="1" stop-color="#2764E7"/></linearGradient><linearGradient id="m211fluentColorMail243" x1="15.095" x2="16.681" y1="9.035" y2="21.643" gradientUnits="userSpaceOnUse"><stop offset=".533" stop-color="#FF6CE8" stop-opacity="0"/><stop offset="1" stop-color="#FF6CE8"/></linearGradient><linearGradient id="m211fluentColorMail244" x1="7.942" x2="13.98" y1="1.151" y2="17.089" gradientUnits="userSpaceOnUse"><stop stop-color="#6CE0FF"/><stop offset=".462" stop-color="#29C3FF"/><stop offset="1" stop-color="#4894FE"/></linearGradient></defs></g></svg>', 10, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url), padre_id = VALUES(padre_id),
  orden = VALUES(orden), nivel = VALUES(nivel), icono_svg = VALUES(icono_svg), activo = 1;
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT @m211, r.id FROM s_roles r
 WHERE r.nombre IN ('Administrador')
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = @m211 AND x.rol_id = r.id);

-- ── Control ─────────────────────────────────────────────────────────────────
SELECT m.id, m.padre_id, m.nombre, m.url, m.nivel FROM s_menu m
 WHERE m.url LIKE '/beneficios%' OR m.url = '/admin/correo' OR m.nombre = 'Beneficios' OR m.nombre = 'Convenio YMCA'
 ORDER BY m.nivel, m.orden;
SELECT c.*, (SELECT COUNT(*) FROM ben_convenio_precio p WHERE p.id_convenio = c.id) AS vigencias FROM ben_convenio c;
