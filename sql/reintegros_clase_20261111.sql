-- =============================================================================
-- reintegros_clase_20261111.sql — Subsidio o reintegro, según el concepto
-- =============================================================================
--
-- Lo que se le paga a un afiliado es un SUBSIDIO (educación inicial,
-- nacimiento, casamiento, fallecimiento, ajuares, otros subsidios especiales)
-- o un REINTEGRO de un gasto (movilidad y mensajería, gastos gremiales,
-- honorarios). Lo dice el concepto: `c_concepto_de_gastos.clase_reintegro`.
--
-- De ahí lo toman las pantallas de reintegros (columna y filtro «Clase») y
-- importar_aeda_cc_afiliados.py (el asunto del expediente). Una solicitud con
-- renglones de las dos clases figura «Mixta».
--
-- Un concepto nuevo marcado «Es de reintegro» elige su clase en Tesorería →
-- Tablas → Conceptos de Gasto; sin clase cuenta como reintegro.
--
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X). Idempotente.

USE sindicato;

SET @hay := (SELECT COUNT(*) FROM information_schema.columns
              WHERE table_schema = DATABASE() AND table_name = 'c_concepto_de_gastos'
                AND column_name = 'clase_reintegro');
SET @sql := IF(@hay = 0,
  'ALTER TABLE c_concepto_de_gastos ADD COLUMN clase_reintegro ENUM(''subsidio'',''reintegro'') NULL
     COMMENT ''Si es_reintegro: subsidio o reintegro de un gasto'' AFTER es_reintegro',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- Los conceptos de AEDA (sql/reintegros_20261107.sql), por descripción.
UPDATE c_concepto_de_gastos SET clase_reintegro = 'subsidio'
 WHERE es_reintegro = 1 AND clase_reintegro IS NULL
   AND descripcion IN ('SUBSIDIO EDUCACIÓN INICIAL', 'OTROS SUBSIDIOS ESPECIALES', 'SUBSIDIO NACIMIENTO',
                       'SUBSIDIO CASAMIENTO', 'SUBSIDIO Y SERVICIO POR FALLECIMIENTO', 'AJUARES NACIMIENTO');
UPDATE c_concepto_de_gastos SET clase_reintegro = 'reintegro'
 WHERE es_reintegro = 1 AND clase_reintegro IS NULL
   AND descripcion IN ('MOVILIDAD Y MENSAJERIA', 'GASTOS GREMIALES', 'HONORARIOS');

-- Lo que quedó sin clase entre los de reintegro (si aparece algo, elegirla en la pantalla).
SELECT id, descripcion FROM c_concepto_de_gastos WHERE es_reintegro = 1 AND clase_reintegro IS NULL;
