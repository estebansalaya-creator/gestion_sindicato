-- Afiliados: fuera la marca «AEDA — Afiliado al Gremio» — 07/11/2026
--
-- El catálogo p_afiliado_atributo vino copiado de la obra social, donde «AEDA»
-- distingue a los beneficiarios que además son afiliados al gremio. Esta es la
-- base del gremio: acá todos lo son, y la marca no distingue nada.
-- importar_aeda_afiliados.py la había cargado desde afi_benef.aeda en 1.511
-- afiliados; ya no la carga.
--
-- Se borran las marcas y el atributo queda inactivo —no se borra—: así deja de
-- aparecer como casilla en la ficha del afiliado sin romper nada que lo
-- referencie.
--
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X). Idempotente.

DELETE pa
  FROM p_atributos_por_afiliado pa
  JOIN p_afiliado_atributo a ON a.id = pa.id_atributo
 WHERE a.rotulo = 'AEDA';

UPDATE p_afiliado_atributo SET activo = 0 WHERE rotulo = 'AEDA';
