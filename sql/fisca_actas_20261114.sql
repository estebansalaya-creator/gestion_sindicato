-- =============================================================================
-- fisca_actas_20261114.sql — Actas de fiscalización y acuerdos de pago
-- =============================================================================
--
-- Pedido del 14/11/2026: generar el acta (la deuda de cuota sindical de un
-- empleador con los intereses resarcitorios de ARCA) y, sobre el acta cerrada,
-- el acuerdo de pago en cuotas. La cuota sindical vence el mismo día que el
-- F.931 del empleador, según la terminación del CUIT: este script también pasa
-- a ese vencimiento las liquidaciones ya hechas.
--
--   arca_vencimientos   vencimientos del F.931 (la tabla de gestion_adm; la
--                       llena importar_arca_tablas.py). Sin la fila, la regla de
--                       ARCA: 9 / 10 / 11 del mes siguiente, al día hábil.
--   arca_intereses      tasas de interés resarcitorio de ARCA por vigencia
--                       (cargadas acá, hasta la Res. 823/2025 ME: 2,75 % mensual)
--   fisca_acta          el acta: empleador, inspector, fechas y totales
--   fisca_acta_periodo  un renglón por período reclamado
--   fisca_acta_pago     los cobros fuera de término de cada período, con su interés
--   fisca_acuerdo       el acuerdo de pago de un acta cerrada
--   fisca_acuerdo_cuota el cronograma
--
-- Menú 14 y 15: Fiscalización de Cuotas → Actas de Fiscalización y Acuerdos de
-- Pago (Administrador y Supervisor).
--
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X), como root. Idempotente.

USE sindicato;
SET NAMES utf8mb4;

-- ─── Tablas de ARCA ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS arca_vencimientos (
  id                  INT NOT NULL AUTO_INCREMENT,
  periodo             CHAR(6) NOT NULL,
  digito_verificador  VARCHAR(1) NOT NULL       COMMENT 'Último dígito del CUIT',
  obligacion          VARCHAR(20) NOT NULL DEFAULT 'F931',
  fecha_vencimiento   DATE NOT NULL,
  origen              VARCHAR(20) NULL,
  rg_referencia       VARCHAR(50) NULL,
  observaciones       VARCHAR(200) NULL,
  updated_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_arca_venc (obligacion, periodo, digito_verificador)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Vencimientos de ARCA por período y terminación de CUIT (copia de gestion_adm)';

CREATE TABLE IF NOT EXISTS arca_intereses (
  id              INT NOT NULL AUTO_INCREMENT,
  vigencia_desde  DATE NOT NULL,
  vigencia_hasta  DATE NULL                   COMMENT 'Inclusive; NULL = vigente',
  resarcitorio    DECIMAL(8,4) NOT NULL       COMMENT '% mensual',
  punitorio       DECIMAL(8,4) NULL,
  devolucion      DECIMAL(8,4) NULL,
  resarcitorio_usd DECIMAL(8,4) NULL,
  punitorio_usd   DECIMAL(8,4) NULL,
  devolucion_usd  DECIMAL(8,4) NULL,
  resolucion      VARCHAR(60) NULL,
  tipo            VARCHAR(20) NULL,
  origen          VARCHAR(20) NULL,
  observaciones   VARCHAR(300) NULL,
  updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_arca_int_desde (vigencia_desde)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Tasas de interés de ARCA (art. 37 y 52 Ley 11.683), copia de gestion_adm';

INSERT INTO arca_intereses (vigencia_desde, vigencia_hasta, resarcitorio, punitorio, resolucion, tipo, origen) VALUES
  ('2011-01-01', '2019-02-28',  3.0000,  4.0000, 'R (MEyFP) 841/2010', 'fija',     'arca_web'),
  ('2019-03-01', '2019-03-31',  4.5000,  5.6000, 'R (MH) 50/2019',     'variable', 'arca_web'),
  ('2019-04-01', '2019-06-30',  3.7600,  4.6100, 'R (MH) 50/2019',     'variable', 'arca_web'),
  ('2019-07-01', '2019-07-31',  4.7300,  5.7600, 'R (MH) 50/2019',     'variable', 'arca_web'),
  ('2019-08-01', '2019-09-30',  4.7300,  5.7600, 'R (MH) 598/2019',    'variable', 'arca_web'),
  ('2019-10-01', '2019-12-31',  5.3400,  6.4900, 'R (MH) 598/2019',    'variable', 'arca_web'),
  ('2020-01-01', '2020-03-31',  3.6000,  4.4100, 'R (MH) 598/2019',    'variable', 'arca_web'),
  ('2020-04-01', '2020-06-30',  2.5000,  3.0800, 'R (MH) 598/2019',    'variable', 'arca_web'),
  ('2020-07-01', '2020-09-30',  2.7600,  3.3900, 'R (MH) 598/2019',    'variable', 'arca_web'),
  ('2020-10-01', '2020-12-31',  3.0200,  3.7100, 'R (MH) 598/2019',    'variable', 'arca_web'),
  ('2021-01-01', '2021-03-31',  3.3500,  4.1100, 'R (MH) 598/2019',    'variable', 'arca_web'),
  ('2021-04-01', '2021-06-30',  3.3500,  4.1100, 'R (MH) 598/2019',    'variable', 'arca_web'),
  ('2021-07-01', '2021-09-30',  3.3500,  4.1100, 'R (MH) 598/2019',    'variable', 'arca_web'),
  ('2021-10-01', '2021-12-31',  3.3500,  4.1100, 'R (MH) 598/2019',    'variable', 'arca_web'),
  ('2022-01-01', '2022-03-31',  3.3500,  4.1100, 'R (MH) 598/2019',    'variable', 'arca_web'),
  ('2022-04-01', '2022-06-30',  3.7200,  4.5600, 'R (MH) 598/2019',    'variable', 'arca_web'),
  ('2022-07-01', '2022-08-31',  4.2500,  5.1900, 'R (MH) 598/2019',    'variable', 'arca_web'),
  ('2022-09-01', '2024-01-31',  5.9100,  7.3700, 'R (ME) 559/2022',    'fija',     'arca_web'),
  ('2024-02-01', '2024-03-31', 15.2700, 17.6200, 'Res. 3/24 ME',       'variable', 'manual'),
  ('2024-04-01', '2024-05-31', 12.0700, 13.9300, 'Res. 3/24 ME',       'variable', 'manual'),
  ('2024-06-01', '2024-07-31',  6.4100,  7.3900, 'Res. 3/24 ME',       'variable', 'manual'),
  ('2024-08-01', '2024-09-30',  6.4100,  7.3900, 'Res. 3/24 ME',       'variable', 'manual'),
  ('2024-10-01', '2024-11-30',  6.4100,  7.3900, 'Res. 3/24 ME',       'variable', 'manual'),
  ('2024-12-01', '2025-01-31',  7.4700,  8.6200, 'Res. 3/24 ME',       'variable', 'manual'),
  ('2025-02-01', '2025-02-28',  7.2600,  8.3800, 'Res. 3/24 ME',       'variable', 'manual'),
  ('2025-03-01', '2025-06-30',  4.0000,  5.0000, 'Res. 3/24 ME / Res. 199/2025 ME', 'fija', 'manual'),
  ('2025-07-01', NULL,          2.7500,  3.5000, 'Res. 3/24 ME / Res. 823/2025 ME', 'fija', 'manual')
ON DUPLICATE KEY UPDATE vigencia_hasta = VALUES(vigencia_hasta), resarcitorio = VALUES(resarcitorio),
  punitorio = VALUES(punitorio), resolucion = VALUES(resolucion), tipo = VALUES(tipo);

-- ─── Datos del Sindicato: lugar y plazo de pago del acta ─────────────────────

DROP PROCEDURE IF EXISTS _actas_columnas;
DELIMITER //
CREATE PROCEDURE _actas_columnas()
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'sindicato'
                    AND table_name = 's_institucion' AND column_name = 'acta_plazo_dias') THEN
    ALTER TABLE s_institucion
      ADD COLUMN acta_plazo_dias INT NULL COMMENT 'Días para pagar el acta: propone la fecha de pago',
      ADD COLUMN acta_lugar_pago VARCHAR(300) NULL COMMENT 'Lugar de pago del acta y del acuerdo';
    UPDATE s_institucion SET acta_plazo_dias = 15 WHERE id = 1;
  END IF;
END //
DELIMITER ;
CALL _actas_columnas();
DROP PROCEDURE _actas_columnas;

-- ─── Actas ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS fisca_acta (
  id                    INT NOT NULL AUTO_INCREMENT,
  nro_acta              VARCHAR(20) NOT NULL       COMMENT 'ACTA-AAAA-NNNNNN (c_numeradores)',
  cuit                  VARCHAR(11) NOT NULL,
  razon_social          VARCHAR(200) NULL,
  domicilio             VARCHAR(300) NULL,
  actividad             VARCHAR(200) NULL,
  telefono              VARCHAR(100) NULL,
  email                 VARCHAR(150) NULL,
  fecha_acta            DATE NOT NULL,
  hora_acta             VARCHAR(5) NULL,
  fecha_calculo         DATE NOT NULL               COMMENT 'Hasta cuándo corren los intereses',
  periodo_desde         CHAR(6) NULL,
  periodo_hasta         CHAR(6) NULL,
  con_pagos_tarde       TINYINT(1) NOT NULL DEFAULT 1 COMMENT '1 = reclama el interés de lo pagado fuera de término',
  inspector             VARCHAR(150) NULL,
  inspector_dni         VARCHAR(20) NULL,
  representante         VARCHAR(200) NULL           COMMENT 'Quien atiende por el empleador',
  representante_dni     VARCHAR(20) NULL,
  representante_cargo   VARCHAR(100) NULL,
  fecha_pago            DATE NULL                   COMMENT 'Fecha hasta la que se intima el pago',
  lugar_pago            VARCHAR(300) NULL,
  observaciones         VARCHAR(1000) NULL,
  deuda                 DECIMAL(15,2) NOT NULL DEFAULT 0 COMMENT 'Saldo impago de las cuotas',
  interes_saldo         DECIMAL(15,2) NOT NULL DEFAULT 0 COMMENT 'Resarcitorio del saldo hasta la fecha de cálculo',
  interes_pagos         DECIMAL(15,2) NOT NULL DEFAULT 0 COMMENT 'Resarcitorio de lo pagado fuera de término',
  total                 DECIMAL(15,2) NOT NULL DEFAULT 0,
  estado                ENUM('abierta','cerrada','anulada') NOT NULL DEFAULT 'abierta',
  id_usuario_creacion   INT NULL,
  creado                TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  id_usuario_cierre     INT NULL,
  cerrado               DATETIME NULL,
  id_usuario_anulacion  INT NULL,
  anulado               DATETIME NULL,
  motivo_anulacion      VARCHAR(255) NULL,
  actualizado           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_fisca_acta_nro (nro_acta),
  KEY ix_fisca_acta_cuit (cuit, estado),
  CONSTRAINT fk_fisca_acta_uc FOREIGN KEY (id_usuario_creacion) REFERENCES s_usuarios (id),
  CONSTRAINT fk_fisca_acta_ucie FOREIGN KEY (id_usuario_cierre) REFERENCES s_usuarios (id),
  CONSTRAINT fk_fisca_acta_uan FOREIGN KEY (id_usuario_anulacion) REFERENCES s_usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Actas de fiscalización de cuota sindical';

CREATE TABLE IF NOT EXISTS fisca_acta_periodo (
  id                INT NOT NULL AUTO_INCREMENT,
  id_acta           INT NOT NULL,
  id_liquidacion    INT NOT NULL,
  periodo           CHAR(6) NOT NULL,
  vencimiento       DATE NOT NULL,
  liquidado         DECIMAL(15,2) NOT NULL,
  pagado_termino    DECIMAL(15,2) NOT NULL DEFAULT 0 COMMENT 'Aplicado con cobros hasta el vencimiento',
  pagado_tarde      DECIMAL(15,2) NOT NULL DEFAULT 0 COMMENT 'Aplicado con cobros después del vencimiento',
  saldo             DECIMAL(15,2) NOT NULL DEFAULT 0,
  dias_mora         INT NOT NULL DEFAULT 0          COMMENT 'Del vencimiento a la fecha de cálculo',
  interes_saldo     DECIMAL(15,2) NOT NULL DEFAULT 0,
  interes_pagos     DECIMAL(15,2) NOT NULL DEFAULT 0,
  total             DECIMAL(15,2) NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY uq_fisca_acta_per (id_acta, periodo),
  KEY ix_fisca_acta_per_liq (id_liquidacion),
  CONSTRAINT fk_fisca_acta_per_acta FOREIGN KEY (id_acta) REFERENCES fisca_acta (id) ON DELETE CASCADE,
  CONSTRAINT fk_fisca_acta_per_liq FOREIGN KEY (id_liquidacion) REFERENCES fisca_liquidacion (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Períodos reclamados en el acta';

CREATE TABLE IF NOT EXISTS fisca_acta_pago (
  id                 INT NOT NULL AUTO_INCREMENT,
  id_acta_periodo    INT NOT NULL,
  id_detalle         INT NOT NULL                 COMMENT 'ingreso_ordenes_detalle',
  id_orden           INT NOT NULL,
  nro_orden          VARCHAR(30) NULL,
  fecha_cobro        DATE NOT NULL,
  importe            DECIMAL(15,2) NOT NULL       COMMENT 'Lo aplicado a la cuota',
  dias               INT NOT NULL,
  interes            DECIMAL(15,2) NOT NULL,
  PRIMARY KEY (id),
  KEY ix_fisca_acta_pago_per (id_acta_periodo),
  CONSTRAINT fk_fisca_acta_pago_per FOREIGN KEY (id_acta_periodo) REFERENCES fisca_acta_periodo (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Cobros fuera de término de cada período del acta, con su interés';

-- ─── Acuerdos de pago ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS fisca_acuerdo (
  id                    INT NOT NULL AUTO_INCREMENT,
  nro_acuerdo           VARCHAR(20) NOT NULL       COMMENT 'AP-AAAA-NNNNNN (c_numeradores)',
  id_acta               INT NOT NULL,
  cuit                  VARCHAR(11) NOT NULL,
  razon_social          VARCHAR(200) NULL,
  fecha_acuerdo         DATE NOT NULL,
  monto_deuda           DECIMAL(15,2) NOT NULL     COMMENT 'El total del acta',
  interes_financiacion  DECIMAL(15,2) NOT NULL DEFAULT 0 COMMENT 'Lo que el cronograma suma por encima de la deuda',
  monto_total           DECIMAL(15,2) NOT NULL     COMMENT 'La suma de las cuotas',
  cantidad_cuotas       INT NOT NULL,
  forma_pago            VARCHAR(150) NULL,
  lugar_pago            VARCHAR(300) NULL,
  representante         VARCHAR(200) NULL,
  representante_dni     VARCHAR(20) NULL,
  representante_cargo   VARCHAR(100) NULL,
  observaciones         VARCHAR(1000) NULL,
  estado                ENUM('vigente','anulado','cancelado','judicializado') NOT NULL DEFAULT 'vigente',
  id_usuario_creacion   INT NULL,
  creado                TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  id_usuario_estado     INT NULL                   COMMENT 'Quien lo pasó a anulado, cancelado o judicializado',
  fecha_estado          DATETIME NULL,
  motivo_estado         VARCHAR(255) NULL,
  actualizado           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_fisca_acuerdo_nro (nro_acuerdo),
  KEY ix_fisca_acuerdo_acta (id_acta, estado),
  KEY ix_fisca_acuerdo_cuit (cuit),
  CONSTRAINT fk_fisca_acuerdo_acta FOREIGN KEY (id_acta) REFERENCES fisca_acta (id),
  CONSTRAINT fk_fisca_acuerdo_uc FOREIGN KEY (id_usuario_creacion) REFERENCES s_usuarios (id),
  CONSTRAINT fk_fisca_acuerdo_ue FOREIGN KEY (id_usuario_estado) REFERENCES s_usuarios (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Acuerdos de pago de actas de fiscalización';

CREATE TABLE IF NOT EXISTS fisca_acuerdo_cuota (
  id           INT NOT NULL AUTO_INCREMENT,
  id_acuerdo   INT NOT NULL,
  nro_cuota    INT NOT NULL,
  vencimiento  DATE NOT NULL,
  importe      DECIMAL(15,2) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_fisca_acuerdo_cuota (id_acuerdo, nro_cuota),
  CONSTRAINT fk_fisca_acuerdo_cuota FOREIGN KEY (id_acuerdo) REFERENCES fisca_acuerdo (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Cronograma del acuerdo de pago';

-- ─── El vencimiento de las liquidaciones pasa a ser el del F.931 ─────────────
-- Con la tabla de ARCA (después de importar_arca_tablas.py --aplicar, que lo
-- vuelve a hacer). Sin ella, la regla: 9 / 10 / 11 del mes siguiente, corrido
-- al día hábil siguiente (sábado, domingo o feriado de arca_feriados).

UPDATE fisca_liquidacion l
  JOIN arca_vencimientos v ON v.obligacion = 'F931' AND v.periodo = l.periodo AND v.digito_verificador = RIGHT(l.cuit, 1)
   SET l.vencimiento = v.fecha_vencimiento
 WHERE l.vencimiento <> v.fecha_vencimiento;

DROP TEMPORARY TABLE IF EXISTS _venc_regla;
CREATE TEMPORARY TABLE _venc_regla AS
SELECT l.id, DATE_ADD(DATE_ADD(STR_TO_DATE(CONCAT(l.periodo, '01'), '%Y%m%d'), INTERVAL 1 MONTH),
                      INTERVAL (CASE WHEN RIGHT(l.cuit, 1) IN ('0','1','2','3') THEN 8
                                     WHEN RIGHT(l.cuit, 1) IN ('4','5','6') THEN 9 ELSE 10 END) DAY) AS vto
  FROM fisca_liquidacion l
 WHERE NOT EXISTS (SELECT 1 FROM arca_vencimientos v
                    WHERE v.obligacion = 'F931' AND v.periodo = l.periodo AND v.digito_verificador = RIGHT(l.cuit, 1));
-- Al día hábil: hasta seis vueltas (un fin de semana largo con feriado puente).
UPDATE _venc_regla SET vto = vto + INTERVAL 1 DAY
 WHERE DAYOFWEEK(vto) IN (1, 7) OR vto IN (SELECT fecha FROM arca_feriados WHERE activo = 1);
UPDATE _venc_regla SET vto = vto + INTERVAL 1 DAY
 WHERE DAYOFWEEK(vto) IN (1, 7) OR vto IN (SELECT fecha FROM arca_feriados WHERE activo = 1);
UPDATE _venc_regla SET vto = vto + INTERVAL 1 DAY
 WHERE DAYOFWEEK(vto) IN (1, 7) OR vto IN (SELECT fecha FROM arca_feriados WHERE activo = 1);
UPDATE _venc_regla SET vto = vto + INTERVAL 1 DAY
 WHERE DAYOFWEEK(vto) IN (1, 7) OR vto IN (SELECT fecha FROM arca_feriados WHERE activo = 1);
UPDATE _venc_regla SET vto = vto + INTERVAL 1 DAY
 WHERE DAYOFWEEK(vto) IN (1, 7) OR vto IN (SELECT fecha FROM arca_feriados WHERE activo = 1);
UPDATE _venc_regla SET vto = vto + INTERVAL 1 DAY
 WHERE DAYOFWEEK(vto) IN (1, 7) OR vto IN (SELECT fecha FROM arca_feriados WHERE activo = 1);
UPDATE fisca_liquidacion l JOIN _venc_regla r ON r.id = l.id SET l.vencimiento = r.vto WHERE l.vencimiento <> r.vto;
DROP TEMPORARY TABLE _venc_regla;

-- ─── Menú ────────────────────────────────────────────────────────────────────

SET @id := (SELECT id FROM s_menu WHERE url = '/fiscalizacion/actas' LIMIT 1);
SET @id := COALESCE(@id, IF(EXISTS (SELECT 1 FROM s_menu WHERE id = 14), (SELECT MAX(id) + 1 FROM s_menu), 14));
INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (@id, 1, 'Actas de Fiscalización', '/fiscalizacion/actas', NULL, 9, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url), padre_id = VALUES(padre_id),
  orden = VALUES(orden), activo = 1;
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT @id, r.id FROM s_roles r WHERE r.nombre IN ('Administrador', 'Supervisor')
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = @id AND x.rol_id = r.id);

SET @id := (SELECT id FROM s_menu WHERE url = '/fiscalizacion/acuerdos' LIMIT 1);
SET @id := COALESCE(@id, IF(EXISTS (SELECT 1 FROM s_menu WHERE id = 15), (SELECT MAX(id) + 1 FROM s_menu), 15));
INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo)
VALUES (@id, 1, 'Acuerdos de Pago', '/fiscalizacion/acuerdos', NULL, 10, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url), padre_id = VALUES(padre_id),
  orden = VALUES(orden), activo = 1;
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT @id, r.id FROM s_roles r WHERE r.nombre IN ('Administrador', 'Supervisor')
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = @id AND x.rol_id = r.id);

SELECT m.id, m.nombre, m.url, m.orden FROM s_menu m WHERE m.padre_id = 1 ORDER BY m.orden;
