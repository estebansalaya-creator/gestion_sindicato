-- Padrón de afiliados: ajustes para recibir los datos de AEDA — 07/11/2026
--
-- `p_afiliados` vino de `contable` con los anchos del diseño de registro de la
-- SSS. AEDA (`aeda.dbo.afi_benef`) tiene la calle en un campo de 100 y 1.721
-- beneficiarios la tienen más larga que 20: con el ancho original la
-- importación corta con «Data too long» o, sin modo estricto, trunca en
-- silencio. Se amplía solo lo que AEDA desborda; localidad, número, piso y
-- depto entran como están.
--
-- Es idempotente: se puede correr de nuevo.

ALTER TABLE p_afiliados
  MODIFY domicilio_calle varchar(100) DEFAULT NULL;

-- AEDA usa el parentesco 10 «Otro» (4 beneficiarios). Sin la fila en el
-- catálogo, el combo del ABM no lo tiene y al guardar la ficha el parentesco
-- cambiaría solo al primero de la lista.
INSERT INTO p_parentesco (codigo, descripcion) VALUES (10, 'Otro')
ON DUPLICATE KEY UPDATE descripcion = VALUES(descripcion);

-- Nacionalidades del catálogo de AEDA que no estaban. Mismos códigos en las
-- dos tablas (12 = Argentina en ambas), así que se agregan sin traducir.
INSERT INTO p_nacionalidad (codigo, descripcion) VALUES
  (24,  'Bolivia'),
  (51,  'España'),
  (89,  'Italia'),
  (132, 'Paraguay')
ON DUPLICATE KEY UPDATE descripcion = VALUES(descripcion);
