-- Reintegros a afiliados — 07/11/2026
--
-- Lo que necesita el módulo de reintegros (reintegros.py) y su importador
-- (importar_aeda_reintegros.py). Las tablas ya estaban: vinieron de `contable`
-- con la misma estructura que usa gestion_adm.
--
--   1. c_concepto_de_gastos.es_reintegro: qué conceptos ofrece la solicitud.
--   2. Los conceptos de AEDA que se usan en reintegros (subsidios, movilidad…),
--      con la cuenta, especie y alícuota de «REINTEGROS A AFILIADOS». Revisar
--      la imputación contable cuando se cargue el plan de cuentas.
--   3. v_reintegros_afiliados: el titular como «APELLIDO NOMBRE», igual que
--      el padrón. Con la coma de contable salía «LUCERO RUDY OCTAVIO, » —AEDA
--      trae el nombre entero en apellido— y con nombre NULL, sin titular.
--   4. Menú: Solicitudes (81, ahora en /reintegros/solicitud), Auditoría (82) y
--      Órdenes de pago (83). El permiso ES la opción de menú: la auditoría y
--      las órdenes se controlan en el servidor con esas opciones.
--      Auditoría: Administrador y Supervisor. Órdenes: Administrador.
--
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X). Idempotente.
-- Los permisos se leen al iniciar sesión: hay que salir y volver a entrar.

USE sindicato;

-- 1 ─────────────────────────────────────────────────────────────────────────
SET @hay := (SELECT COUNT(*) FROM information_schema.COLUMNS
              WHERE TABLE_SCHEMA = 'sindicato' AND TABLE_NAME = 'c_concepto_de_gastos'
                AND COLUMN_NAME = 'es_reintegro');
SET @sql := IF(@hay = 0,
  'ALTER TABLE c_concepto_de_gastos ADD COLUMN es_reintegro TINYINT(1) NOT NULL DEFAULT 0 COMMENT ''Se ofrece en la solicitud de reintegro'' AFTER esliquidacion',
  'SELECT ''es_reintegro ya existe''');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- 2 ─────────────────────────────────────────────────────────────────────────
-- «HONORARIOS» ya está en el catálogo: solo se marca.
INSERT INTO c_concepto_de_gastos
       (descripcion, c_plan_de_cuentasId, c_especiesId, arca_tasa_ivaid, esliquidacion, es_reintegro)
SELECT n.descripcion, b.c_plan_de_cuentasId, b.c_especiesId, b.arca_tasa_ivaid, b.esliquidacion, 1
  FROM (SELECT 'SUBSIDIO EDUCACIÓN INICIAL' AS descripcion
        UNION ALL SELECT 'OTROS SUBSIDIOS ESPECIALES'
        UNION ALL SELECT 'MOVILIDAD Y MENSAJERIA'
        UNION ALL SELECT 'SUBSIDIO NACIMIENTO'
        UNION ALL SELECT 'HONORARIOS'
        UNION ALL SELECT 'SUBSIDIO CASAMIENTO'
        UNION ALL SELECT 'GASTOS GREMIALES'
        UNION ALL SELECT 'SUBSIDIO Y SERVICIO POR FALLECIMIENTO'
        UNION ALL SELECT 'AJUARES NACIMIENTO') n
  JOIN (SELECT * FROM c_concepto_de_gastos WHERE descripcion = 'REINTEGROS A AFILIADOS' LIMIT 1) b
 WHERE NOT EXISTS (SELECT 1 FROM c_concepto_de_gastos x WHERE x.descripcion = n.descripcion);

UPDATE c_concepto_de_gastos SET es_reintegro = 1
 WHERE descripcion IN ('SUBSIDIO EDUCACIÓN INICIAL', 'OTROS SUBSIDIOS ESPECIALES',
                       'MOVILIDAD Y MENSAJERIA', 'SUBSIDIO NACIMIENTO', 'HONORARIOS',
                       'SUBSIDIO CASAMIENTO', 'GASTOS GREMIALES',
                       'SUBSIDIO Y SERVICIO POR FALLECIMIENTO', 'AJUARES NACIMIENTO');

-- 3 ─────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE SQL SECURITY DEFINER
VIEW v_reintegros_afiliados AS
SELECT r.id, r.nro_solicitud, r.anio, r.fecha_solicitud, r.estado,
       r.importe_solicitado, r.importe_aprobado, r.moneda, r.cbu_destino, r.alias_destino,
       r.id_orden_pago, op.nro_orden AS nro_orden_pago, op.estado AS estado_orden_pago,
       r.id_afiliado, a.cuil AS cuil_titular, a.nro_documento AS doc_titular,
       TRIM(CONCAT(a.apellido, ' ', COALESCE(a.nombre, ''))) AS titular,
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

-- 4 ─────────────────────────────────────────────────────────────────────────
UPDATE s_menu SET nombre = 'Solicitudes de Reintegro', url = '/reintegros/solicitud', orden = 1
 WHERE id = 81;

INSERT INTO s_menu (id, padre_id, nombre, url, icono_svg, orden, nivel, activo) VALUES
  (82, 80, 'Auditoría de Reintegros',       '/reintegros/auditoria', NULL, 2, 2, 1),
  (83, 80, 'Órdenes de Pago de Reintegros', '/reintegros/ordenes',   NULL, 3, 2, 1)
ON DUPLICATE KEY UPDATE nombre = VALUES(nombre), url = VALUES(url),
  padre_id = VALUES(padre_id), orden = VALUES(orden), activo = 1;

-- Desde s_menu y s_roles, no desde DUAL: si la opción no se creó, no inserta
-- nada en vez de cortar con el error de clave foránea.
INSERT INTO s_menu_rol (menu_id, rol_id)
SELECT m.id, r.id
  FROM s_menu m
  JOIN s_roles r ON (m.id = 82 AND r.id IN (1, 2)) OR (m.id = 83 AND r.id = 1)
 WHERE m.id IN (82, 83) AND r.activo = 1
   AND NOT EXISTS (SELECT 1 FROM s_menu_rol x WHERE x.menu_id = m.id AND x.rol_id = r.id);

-- Control: los conceptos que va a ofrecer la solicitud.
SELECT id, descripcion FROM c_concepto_de_gastos WHERE es_reintegro = 1 ORDER BY descripcion;
