-- =============================================================================
-- afiliados_movimientos_baja_un_renglon_20261125.sql — La baja, un solo movimiento
-- =============================================================================
-- Pedido del 25/11/2026 (como en gestion_adm desde el 19/11/2026): una baja dejaba
-- tres renglones en Movimientos —Activo sí → no, Fecha de baja y Motivo de baja—.
-- Desde el código de hoy deja uno: campo `fecha_baja`, rótulo «Baja», valor
-- «25/11/2026 · RENUNCIA» (afiliados.CAMPO_BAJA).
--
-- Este script junta los que ya están cargados, que son de dos lados:
--   · las bajas del ABM (origen_ref 'ABM de afiliados'): activo + fecha_baja + motivo;
--   · las del grupo con el titular (sql/afiliados_baja_grupo_20261117.sql): activo +
--     fecha_baja, sin motivo (el motivo se toma de la ficha, si la baja sigue siendo esa).
-- Queda el renglón de fecha_baja con el motivo adentro; los otros se borran.
-- No toca las altas y bajas de la importación de AEDA (un renglón cada una).
--
-- Correrlo ENTERO (Alt+X), en localhost y en Railway. Se puede volver a correr.

USE sindicato;
SET NAMES utf8mb4;

-- Antes: cuántos renglones por baja.
SELECT COUNT(*) AS renglones, COUNT(DISTINCT id_afiliado, fecha) AS bajas
  FROM p_afiliados_movimientos WHERE tipo_movimiento = 'BAJA' AND origen = 'MANUAL';

START TRANSACTION;

-- 1. El motivo del ABM («7 · RENUNCIA») pasa al renglón de la fecha, sin el código.
UPDATE p_afiliados_movimientos f
  JOIN p_afiliados_movimientos m
    ON m.id_afiliado = f.id_afiliado AND m.fecha = f.fecha
   AND m.tipo_movimiento = 'BAJA' AND m.campo = 'id_motivo_baja'
   SET f.valor_actual = CONCAT(f.valor_actual, ' · ',
                               IF(m.valor_actual LIKE '% · %', SUBSTRING_INDEX(m.valor_actual, ' · ', -1), m.valor_actual))
 WHERE f.tipo_movimiento = 'BAJA' AND f.campo = 'fecha_baja'
   AND f.valor_actual NOT LIKE '%·%' AND m.valor_actual IS NOT NULL;

-- 2. Las del grupo con el titular no tenían motivo: el de la ficha, si sigue de baja con esa fecha.
UPDATE p_afiliados_movimientos f
  JOIN p_afiliados a ON a.id_afiliado = f.id_afiliado AND a.activo = 0 AND a.fecha_baja = f.fecha_vigencia
  JOIN p_motivo_movimiento mm ON mm.id = a.id_motivo_baja
   SET f.valor_actual = CONCAT(f.valor_actual, ' · ', mm.nombre)
 WHERE f.tipo_movimiento = 'BAJA' AND f.campo = 'fecha_baja' AND f.origen = 'MANUAL'
   AND f.valor_actual NOT LIKE '%·%';

-- 3. Rótulo «Baja», como el código nuevo.
UPDATE p_afiliados_movimientos SET campo_label = 'Baja'
 WHERE tipo_movimiento = 'BAJA' AND campo = 'fecha_baja' AND origen = 'MANUAL' AND campo_label <> 'Baja';

-- 4. Fuera los renglones de Activo y Motivo que acompañan a un renglón de fecha de la misma baja.
DELETE x FROM p_afiliados_movimientos x
  JOIN p_afiliados_movimientos f
    ON f.id_afiliado = x.id_afiliado AND f.fecha = x.fecha
   AND f.tipo_movimiento = 'BAJA' AND f.campo = 'fecha_baja'
 WHERE x.tipo_movimiento = 'BAJA' AND x.origen = 'MANUAL' AND x.campo IN ('activo', 'id_motivo_baja');

COMMIT;

-- Después: un renglón por baja (las dos cifras tienen que ser iguales).
SELECT COUNT(*) AS renglones, COUNT(DISTINCT id_afiliado, fecha) AS bajas
  FROM p_afiliados_movimientos WHERE tipo_movimiento = 'BAJA' AND origen = 'MANUAL';
SELECT id_afiliado, fecha, campo_label, valor_anterior, valor_actual, observaciones
  FROM p_afiliados_movimientos WHERE tipo_movimiento = 'BAJA' AND origen = 'MANUAL'
 ORDER BY id_movimiento DESC LIMIT 5;
