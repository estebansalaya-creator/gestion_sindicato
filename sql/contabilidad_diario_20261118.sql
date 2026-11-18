-- =============================================================================
-- Libro Diario (pedido del 18/11/2026): el origen de cada asiento
--
-- c_asientos.origen / id_origen: de dónde vino el asiento cuando no se cargó a
-- mano. 'aeda' + adm_asientos.asto_id para los que trae importar_aeda_asientos.py
-- (así se puede volver a correr sin duplicar), 'excel' para los importados desde
-- la pantalla (id_origen vacío). Lo cargado a mano queda con origen NULL.
--
-- Las pantallas (Ejercicios, Asientos, Libro Diario) funcionan sin este script;
-- el importador de AEDA no.
-- =============================================================================

ALTER TABLE c_asientos
  ADD COLUMN origen VARCHAR(20) NULL COMMENT 'aeda, excel; NULL = cargado a mano' AFTER usuario,
  ADD COLUMN id_origen INT NULL COMMENT 'aeda: adm_asientos.asto_id' AFTER origen,
  ADD UNIQUE KEY uq_asiento_origen (origen, id_origen);
