-- Afiliados: apellido y nombres en una sola columna — 10/11/2026
--
-- AEDA guarda apellido y nombres juntos («DIAZ RAIDAN MAYRA CANDELA») y no hay
-- regla que los separe bien: falla justo con los apellidos compuestos. Se
-- importaban enteros en `apellido` con `nombre` vacío —los 5.733 del padrón
-- estaban así— y la ficha ofrecía dos campos que nadie separaba. Queda una sola
-- columna, `apellido_nombres`, y `nombre` se borra.
--
--   1. Si algún afiliado tiene `nombre` cargado, se pega al final de `apellido`
--      antes de borrar la columna: no se pierde nada.
--   2. `apellido` pasa a ser `apellido_nombres` varchar(100) —el más largo de
--      AEDA tiene 40, y 50 quedaba justo para un nombre completo cargado a
--      mano— y se borra `nombre`. El índice de búsqueda se rehace sobre la
--      columna nueva.
--   3. v_reintegros_afiliados toma el titular de la columna nueva.
--
-- Va junto con el código que usa `apellido_nombres` (afiliados.py,
-- reintegros_datos.py, importar_aeda_afiliados.py, importar_aeda_reintegros.py):
-- correr el script y reiniciar el sitio uno detrás del otro. Con la base nueva
-- y el código viejo —o al revés— el padrón y los reintegros dan error.
--
-- La auditoría (p_afiliados_movimientos) no se toca: los cambios viejos siguen
-- diciendo «Apellido» o «Nombre», que es lo que se cambió en su momento.
--
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X). Idempotente.

-- 1 ─────────────────────────────────────────────────────────────────────────
SET @hay := (SELECT COUNT(*) FROM information_schema.COLUMNS
              WHERE TABLE_SCHEMA = 'sindicato' AND TABLE_NAME = 'p_afiliados' AND COLUMN_NAME = 'nombre');

-- Primero el ancho: pegar el nombre con 50 podría no entrar.
SET @sql := IF(@hay = 1,
  'ALTER TABLE p_afiliados MODIFY apellido VARCHAR(100) NOT NULL',
  'SELECT ''p_afiliados.nombre ya no existe: nada que unir''');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

SET @sql := IF(@hay = 1,
  'UPDATE p_afiliados SET apellido = TRIM(CONCAT(apellido, '' '', TRIM(nombre))) WHERE TRIM(nombre) <> ''''',
  'SELECT ''p_afiliados.nombre ya no existe''');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- 2 ─────────────────────────────────────────────────────────────────────────
-- Una sola sentencia: o queda todo hecho o nada.
SET @sql := IF(@hay = 1,
  'ALTER TABLE p_afiliados
     DROP INDEX idx_afiliado_apellido,
     DROP COLUMN nombre,
     CHANGE COLUMN apellido apellido_nombres VARCHAR(100) NOT NULL
       COMMENT ''Apellido y nombres juntos, como los guarda AEDA'',
     ADD INDEX idx_afiliado_apellido_nombres (apellido_nombres)',
  'SELECT ''p_afiliados.apellido_nombres ya existe''');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- 3 ─────────────────────────────────────────────────────────────────────────
-- La misma vista de sql/reintegros_20261107.sql; cambia solo `titular`.
CREATE OR REPLACE SQL SECURITY DEFINER
VIEW v_reintegros_afiliados AS
SELECT r.id, r.nro_solicitud, r.anio, r.fecha_solicitud, r.estado,
       r.importe_solicitado, r.importe_aprobado, r.moneda, r.cbu_destino, r.alias_destino,
       r.id_orden_pago, op.nro_orden AS nro_orden_pago, op.estado AS estado_orden_pago,
       r.id_afiliado, a.cuil AS cuil_titular, a.nro_documento AS doc_titular,
       a.apellido_nombres AS titular,
       r.fecha_auditoria, r.fecha_aprobacion, r.motivo_rechazo,
       us.nombre AS usuario_solicitud, uau.nombre AS usuario_auditoria, ua.nombre AS usuario_aprobacion,
       (SELECT COUNT(0) FROM c_reintegro_afiliados_detalle d WHERE d.id_reintegro = r.id) AS renglones,
       (SELECT COUNT(0) FROM c_reintegro_afiliados_detalle d
          JOIN c_reintegro_afiliados_detalle_adjunto ad ON ad.id_detalle = d.id
         WHERE d.id_reintegro = r.id) AS adjuntos
  FROM c_reintegro_afiliados r
  JOIN p_afiliados a      ON a.id_afiliado = r.id_afiliado
  JOIN s_usuarios us      ON us.id = r.id_usuario_solicitud
  LEFT JOIN s_usuarios uau ON uau.id = r.id_usuario_auditoria
  LEFT JOIN s_usuarios ua  ON ua.id = r.id_usuario_aprobacion
  LEFT JOIN pago_ordenes op ON op.id = r.id_orden_pago;

-- Control: tiene que dar 0 filas con nombre vacío y la columna nueva en la lista.
SELECT COUNT(*) AS afiliados, SUM(apellido_nombres = '') AS sin_nombre,
       MAX(CHAR_LENGTH(apellido_nombres)) AS largo_max
  FROM p_afiliados;
