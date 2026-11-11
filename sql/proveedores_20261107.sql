-- Proveedores — 07/11/2026
--
-- Lo que necesita el ABM de proveedores (proveedores.py) y su importador
-- (importar_aeda_proveedores.py). c_proveedores y sus cuentas ya estaban:
-- vinieron de `contable` con la misma estructura que usa gestion_adm.
--
--   1. c_proveedores_movimientos: la auditoría de la ficha, una fila por campo
--      que cambia (como p_afiliados_movimientos). Misma estructura que en
--      gestion_adm. Sin clave foránea a propósito: si se borra el proveedor, su
--      historia queda.
--   2. Rubro de pasivo «Proveedores»: el grupo de pasivo de AEDA. Los rubros que
--      vinieron de la obra social (Integración, Galeno, Droguerías…) no le
--      sirven al gremio. Con la cuenta contable de «Acreedores Varios»; revisarla
--      cuando se cargue el plan de cuentas.
--   3. RG 830, regímenes 78 (bienes muebles y de cambio) y 31 (alquileres): los
--      usan proveedores de AEDA y la tabla solo tenía 94, 116 y 119. Valores de
--      la tabla de retenciones de AEDA (adm_rg2784), que son los de la RG 4525.
--
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X). Idempotente.

USE sindicato;

-- 1 ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS c_proveedores_movimientos (
  id_movimiento   INT          NOT NULL AUTO_INCREMENT,
  id_proveedor    INT          NOT NULL,
  cuit            VARCHAR(11)  NULL COMMENT 'CUIT al momento del movimiento',
  fecha           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  tipo_movimiento ENUM('ALTA','BAJA','REACTIVACION','MODIFICACION','ELIMINACION') NOT NULL DEFAULT 'MODIFICACION',
  origen          VARCHAR(30)  NOT NULL DEFAULT 'MANUAL' COMMENT 'MANUAL, IMPORTACION',
  origen_ref      VARCHAR(120) NULL COMMENT 'Pantalla o proceso que lo originó',
  campo           VARCHAR(64)  NOT NULL COMMENT 'Columna de c_proveedores (o cuenta_pasivo / cuenta_gasto)',
  campo_label     VARCHAR(80)  NULL,
  valor_anterior  VARCHAR(255) NULL,
  valor_actual    VARCHAR(255) NULL,
  usuario         VARCHAR(255) NULL,
  observaciones   VARCHAR(300) NULL,
  created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id_movimiento),
  KEY ix_cpm_proveedor (id_proveedor, fecha),
  KEY ix_cpm_fecha (fecha),
  KEY ix_cpm_campo (campo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Auditoría de cambios de c_proveedores: una fila por campo modificado';

-- 2 ─────────────────────────────────────────────────────────────────────────
INSERT INTO c_rubros_de_pasivo (nombre, c_plan_de_cuentasId)
SELECT 'Proveedores', b.c_plan_de_cuentasId
  FROM (SELECT c_plan_de_cuentasId FROM c_rubros_de_pasivo WHERE nombre = 'Acreedores Varios' LIMIT 1) b
 WHERE NOT EXISTS (SELECT 1 FROM c_rubros_de_pasivo WHERE nombre = 'Proveedores');

-- 3 ─────────────────────────────────────────────────────────────────────────
INSERT INTO rg830_escala
  (codigo_regimen, descripcion, tipo_calculo, alicuota_fija,
   monto_no_sujeto_inscripto, monto_no_sujeto_no_inscripto, alicuota_no_inscripto,
   retencion_minima_inscripto, retencion_minima_no_inscripto,
   resolucion, vigencia_desde, vigencia_hasta, activa, observaciones)
SELECT n.* FROM (
  SELECT '78' AS codigo_regimen,
         'Enajenación de bienes muebles y bienes de cambio.' AS descripcion,
         'fija' AS tipo_calculo, 2.00 AS alicuota_fija,
         224000.00 AS monto_no_sujeto_inscripto, NULL AS monto_no_sujeto_no_inscripto,
         10.00 AS alicuota_no_inscripto, 240.00 AS retencion_minima_inscripto,
         240.00 AS retencion_minima_no_inscripto, 'RG 4525/2019' AS resolucion,
         DATE('2019-08-01') AS vigencia_desde, NULL AS vigencia_hasta, 1 AS activa,
         'Valores de la tabla de retenciones de AEDA (adm_rg2784, concepto C).' AS observaciones
  UNION ALL
  SELECT '31', 'Alquileres o arrendamientos de bienes inmuebles urbanos.',
         'fija', 6.00, 11200.00, NULL, 28.00, 240.00, 240.00, 'RG 4525/2019',
         DATE('2019-08-01'), NULL, 1,
         'Valores de la tabla de retenciones de AEDA (adm_rg2784, concepto A).'
) n
 WHERE NOT EXISTS (SELECT 1 FROM rg830_escala x
                    WHERE LPAD(TRIM(x.codigo_regimen), 3, '0') = LPAD(n.codigo_regimen, 3, '0'));

-- Control
SELECT id, nombre FROM c_rubros_de_pasivo ORDER BY id;
SELECT codigo_regimen, tipo_calculo, alicuota_fija, monto_no_sujeto_inscripto, activa
  FROM rg830_escala ORDER BY LPAD(codigo_regimen, 3, '0'), vigencia_desde;
