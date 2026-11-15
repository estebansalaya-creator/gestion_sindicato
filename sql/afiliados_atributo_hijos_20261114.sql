-- =============================================================================
-- afiliados_atributo_hijos_20261114.sql — Atributo «Tiene hijos»
-- =============================================================================
--
-- Pedido del 14/11/2026: marcar al afiliado que tiene hijos aunque no estén
-- cargados en el padrón. En AEDA es `afi_benef.hijos` (0 / 1, solo en los
-- titulares: 1.032 activos y 307 de baja al 14/11/2026). importar_aeda_afiliados.py
-- no lo importaba: lo dejaba en observaciones («Hijos declarados en AEDA: 1.»),
-- que es de donde lo toma este script. Desde hoy el importador lo marca al dar
-- el alta; volver a correr este script después de una importación no duplica.
--
-- La marca se tilda o se saca en la ficha del afiliado (bloque Atributos, con su
-- auditoría) y se filtra en el listado del padrón (?atributo=<id>).
--
-- Correrlo ENTERO (Alt+X). Idempotente.

USE sindicato;
SET NAMES utf8mb4;

INSERT INTO p_afiliado_atributo (rotulo, descripcion, fuerza_activo, afecta_coberturas, activo, creado)
SELECT 'Tiene hijos', 'Declara tener hijos, aunque no estén cargados en el padrón (AEDA: afi_benef.hijos)', 0, 0, 1, NOW()
 WHERE NOT EXISTS (SELECT 1 FROM p_afiliado_atributo WHERE rotulo = 'Tiene hijos');

INSERT INTO p_atributos_por_afiliado (id_atributo, id_afiliado, observaciones, usuario, creado)
SELECT t.id, a.id_afiliado, '[AEDA afi_benef.hijos]', 'AEDA', NOW()
  FROM p_afiliados a
  JOIN p_afiliado_atributo t ON t.rotulo = 'Tiene hijos'
 WHERE a.observaciones LIKE '%Hijos declarados en AEDA:%'
   AND a.observaciones NOT LIKE '%Hijos declarados en AEDA: 0.%'
   AND NOT EXISTS (SELECT 1 FROM p_atributos_por_afiliado x WHERE x.id_atributo = t.id AND x.id_afiliado = a.id_afiliado);

SELECT t.rotulo, COUNT(x.id) AS afiliados,
       SUM(a.fecha_baja IS NULL) AS activos, SUM(a.fecha_baja IS NOT NULL) AS de_baja
  FROM p_afiliado_atributo t
  LEFT JOIN p_atributos_por_afiliado x ON x.id_atributo = t.id
  LEFT JOIN p_afiliados a ON a.id_afiliado = x.id_afiliado
 WHERE t.rotulo = 'Tiene hijos' GROUP BY t.rotulo;
