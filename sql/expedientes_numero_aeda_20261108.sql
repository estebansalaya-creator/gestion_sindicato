-- expedientes_numero_aeda_20261108.sql — Los expedientes de AEDA con su número de AEDA
--
-- importar_aeda_cc_proveedores.py los creó como «AEDA-2303/26»: el número de
-- AEDA sin los ceros y con un prefijo. gestion_adm dejó los que migró del
-- sistema viejo con el número tal cual («000025720/26»), y es el que figura
-- en los papeles. Este script pasa los ya importados a esa forma:
--
--     AEDA-2303/26  →  000002303/26        (nueve dígitos, como mse_expedientes.exp_nro)
--
-- El importador ya los crea así, y reconoce lo importado por el asunto
-- («[AEDA adm_pasivo N]»), no por el número: volver a correrlo no duplica.
-- El número solo está en me_expedientes.nro_expediente (las vistas lo leen
-- de ahí); no quedó copiado en observaciones ni comentarios.
--
-- Se puede correr más de una vez: solo toca los que todavía tienen el prefijo.

-- Antes: cuántos hay y si alguno chocaría con un número que ya existe.
SELECT COUNT(*) AS a_convertir
  FROM me_expedientes
 WHERE nro_expediente REGEXP '^AEDA-[0-9]+/[0-9]{2}$';

SELECT e.nro_expediente AS actual, x.nro_expediente AS ya_existe
  FROM me_expedientes e
  JOIN me_expedientes x
    ON x.nro_expediente = CONCAT(LPAD(SUBSTRING_INDEX(SUBSTRING(e.nro_expediente, 6), '/', 1), 9, '0'),
                                 '/', SUBSTRING_INDEX(e.nro_expediente, '/', -1))
 WHERE e.nro_expediente REGEXP '^AEDA-[0-9]+/[0-9]{2}$';
-- (la segunda tiene que venir vacía)

UPDATE me_expedientes
   SET nro_expediente = CONCAT(LPAD(SUBSTRING_INDEX(SUBSTRING(nro_expediente, 6), '/', 1), 9, '0'),
                               '/', SUBSTRING_INDEX(nro_expediente, '/', -1))
 WHERE nro_expediente REGEXP '^AEDA-[0-9]+/[0-9]{2}$';

-- Después: tiene que dar 0 con prefijo y los de AEDA con nueve dígitos.
SELECT SUM(nro_expediente LIKE 'AEDA-%')                        AS con_prefijo,
       SUM(nro_expediente REGEXP '^[0-9]{9}/[0-9]{2}$')         AS formato_aeda,
       SUM(nro_expediente LIKE 'EXP-%')                         AS cargados_aca,
       COUNT(*)                                                 AS total
  FROM me_expedientes;
