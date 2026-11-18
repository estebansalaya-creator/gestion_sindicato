-- =============================================================================
-- El grupo cae con el titular (decidido el 17/11/2026)
--
-- AEDA deja a los familiares sin fecha de baja aunque el titular se haya ido,
-- y el importador los trajo activos: al 17/11/2026, 445 familiares activos con
-- el titular de baja (las métricas contaban 2.529 familiares; con el titular
-- activo son 2.081). Se les pone la fecha y el motivo de baja de su titular,
-- con su renglón en la auditoría (p_afiliados_movimientos), como lo hace la
-- baja del grupo desde la ficha.
--
-- No toca a los familiares sin titular en el padrón (3 al 17/11/2026: dos sin
-- CUIL de grupo y uno que es su propio titular con parentesco 10): siguen en el
-- control «Familiares sin titular activo» de Métricas, para corregirlos a mano.
--
-- Corrido en Railway el 17/11/2026: 445 bajas y 890 renglones de auditoría;
-- quedaron 2.084 familiares activos (2.081 con titular activo + los 3 sin titular).
-- Sin tablas temporales: app_sindicato no tiene CREATE TEMPORARY TABLES.
-- Se puede volver a correr: la segunda vez no encuentra a nadie.
-- =============================================================================

-- Los titulares de baja (y que no figuran además activos con el mismo CUIL).
-- El GROUP BY materializa la tabla derivada: sin él MySQL no deja leer
-- p_afiliados mientras la actualiza (error 1093).
START TRANSACTION;

INSERT INTO p_afiliados_movimientos
    (id_afiliado, cuil, fecha_vigencia, tipo_movimiento, origen, origen_ref,
     campo, campo_label, valor_anterior, valor_actual, usuario, observaciones)
SELECT f.id_afiliado, f.cuil, t.fecha_baja, 'BAJA', 'MANUAL', 'sql/afiliados_baja_grupo_20261117.sql',
       c.campo, c.label, c.antes,
       IF(c.campo = 'activo', 'no',
          CONCAT(LPAD(DAY(t.fecha_baja), 2, '0'), '/', LPAD(MONTH(t.fecha_baja), 2, '0'), '/', YEAR(t.fecha_baja))),
       'script', 'Baja del grupo con el titular (en AEDA sigue sin baja)'
  FROM p_afiliados f
  JOIN (SELECT t.cuil, MAX(t.fecha_baja) AS fecha_baja FROM p_afiliados t
         WHERE t.cod_parentesco = 0 AND t.activo = 0 AND t.fecha_baja IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM p_afiliados t2
                            WHERE t2.cuil = t.cuil AND t2.cod_parentesco = 0 AND t2.activo = 1)
         GROUP BY t.cuil) t ON t.cuil = f.cuil_titular
  JOIN (SELECT 'activo' AS campo, 'Activo' AS label, 'sí' AS antes
        UNION ALL SELECT 'fecha_baja', 'Fecha de baja', NULL) c
 WHERE f.activo = 1 AND f.cod_parentesco > 0;

UPDATE p_afiliados f
  JOIN (SELECT t.cuil, MAX(t.fecha_baja) AS fecha_baja, MAX(t.id_motivo_baja) AS id_motivo_baja
          FROM p_afiliados t
         WHERE t.cod_parentesco = 0 AND t.activo = 0 AND t.fecha_baja IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM p_afiliados t2
                            WHERE t2.cuil = t.cuil AND t2.cod_parentesco = 0 AND t2.activo = 1)
         GROUP BY t.cuil) t ON t.cuil = f.cuil_titular
   SET f.activo = 0, f.fecha_baja = t.fecha_baja, f.id_motivo_baja = t.id_motivo_baja
 WHERE f.activo = 1 AND f.cod_parentesco > 0;

COMMIT;

-- Control: tiene que dar 0.
SELECT COUNT(*) AS familiares_activos_con_titular_de_baja
  FROM p_afiliados f
  JOIN p_afiliados t ON t.cuil = f.cuil_titular AND t.cod_parentesco = 0 AND t.activo = 0
 WHERE f.activo = 1 AND f.cod_parentesco > 0
   AND NOT EXISTS (SELECT 1 FROM p_afiliados t2
                    WHERE t2.cuil = f.cuil_titular AND t2.cod_parentesco = 0 AND t2.activo = 1);
