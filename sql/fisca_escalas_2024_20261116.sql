-- =============================================================================
-- fisca_escalas_2024_20261116.sql — Escalas de 2024 que faltaban (parcial)
-- =============================================================================
--
-- Pasadas de las circulares el 16/11/2026. Cada una rige SOLO su mes: los meses de
-- alrededor tuvieron aumentos que todavía no tenemos (ver abajo), así que no se
-- estiran. Siguen faltando 2023-10 a 2024-01 y 2024-05 a 2024-10.
--
-- Controles hechos al pasarlas (script de verificación del 16/11/2026):
--   * febrero y abril 2024 cierran al centavo contra el «conformado»
--     (básico + almuerzo × 22: 96.250 y 118.800);
--   * marzo 2024 = febrero × 1,1338 en todas las antigüedades;
--   * los «%» de las circulares de dic-24 en adelante son sobre el básico de ABRIL
--     2024: diciembre = abril × 1,34 y enero 2025 = diciembre + 5 % de abril.
--   * diciembre 2024, 4 años: el escaneo se lee 551.676,39; se cargó 551.576,39, el
--     que dan abril × 1,34 y enero 2025 (572.157,59) menos el 5 % de abril.
--
-- NOVIEMBRE 2024 ES CALCULADA, no publicada: diciembre («8 %») menos el 8 % del
-- básico de abril, antigüedad por antigüedad (= abril × 1,26). Almuerzo: 7.242 − 8 %
-- de 5.400 = 6.810 (el de enero 2025 sube justo el 5 % de 5.400). No se sabe desde
-- qué mes rige: se carga solo para 2024-11. Reemplazarla si aparece la circular.
--
-- Pista para los huecos: marzo 2024 («39 %») = 1,39 × una escala con inicial
-- 242.685,68 (septiembre 2023 × 1,7355), que tuvo que regir entre 2023-10 y 2024-01.
--
-- Requiere sql/fisca_escalas_20261114.sql. Idempotente.

USE sindicato;
SET NAMES utf8mb4;

-- Febrero 2024: 2024-02
INSERT INTO fisca_escala_salarial (periodo_desde, periodo_hasta, antiguedad, basico, almuerzo, origen)
SELECT '202402', '202402', j.i - 1, j.v, 4375.00, 'manual'
  FROM JSON_TABLE('[297526.82,305008.55,311694.82,331366.34,336158.57,347398.74,392038.94,396835.01,402406.27,408801.19,432345.89,439854.97,445765.49,451942.08,459330.23,465870.52,476770.84,483262.53,489463.65,496875.79,504481.82,509810.85,516399.35,522939.55,530158.19,561502.55,566492.58,572790.39,579476.07,584417.48,590909.28,596335.09,602826.95,609367.01,615907.16,622447.52]', '$[*]' COLUMNS (i FOR ORDINALITY, v DECIMAL(15,2) PATH '$')) j
ON DUPLICATE KEY UPDATE periodo_hasta = VALUES(periodo_hasta), basico = VALUES(basico), almuerzo = VALUES(almuerzo)
  , origen = IF(origen = 'aeda', origen, 'manual');

-- Marzo 2024 (39 %): 2024-03
INSERT INTO fisca_escala_salarial (periodo_desde, periodo_hasta, antiguedad, basico, almuerzo, origen)
SELECT '202403', '202403', j.i - 1, j.v, 4960.00, 'manual'
  FROM JSON_TABLE('[337333.10,345815.84,353396.71,375700.02,381133.49,393877.49,444490.07,449927.91,456244.60,463494.98,490189.80,498703.46,505404.76,512407.84,520784.38,528199.63,540558.35,547918.51,554949.35,563353.22,571976.84,578018.87,585488.83,592904.08,601088.40,636626.42,642284.02,649424.42,657004.56,662607.07,669967.45,676119.25,683479.63,690894.69,698309.95,705725.22]', '$[*]' COLUMNS (i FOR ORDINALITY, v DECIMAL(15,2) PATH '$')) j
ON DUPLICATE KEY UPDATE periodo_hasta = VALUES(periodo_hasta), basico = VALUES(basico), almuerzo = VALUES(almuerzo)
  , origen = IF(origen = 'aeda', origen, 'manual');

-- Abril 2024: 2024-04
INSERT INTO fisca_escala_salarial (periodo_desde, periodo_hasta, antiguedad, basico, almuerzo, origen)
SELECT '202404', '202404', j.i - 1, j.v, 5400.00, 'manual'
  FROM JSON_TABLE('[364319.75,373481.11,381668.45,405756.03,411624.17,425387.69,480049.28,485922.14,492744.16,500574.58,529404.98,538599.74,545837.14,553400.46,562447.13,570455.60,583803.02,591752.00,599345.30,608421.47,617734.98,624260.38,632327.93,640336.40,649175.48,687556.53,693666.74,701378.38,709564.93,715615.64,723564.85,730208.79,738158.00,746166.26,754174.74,762183.24]', '$[*]' COLUMNS (i FOR ORDINALITY, v DECIMAL(15,2) PATH '$')) j
ON DUPLICATE KEY UPDATE periodo_hasta = VALUES(periodo_hasta), basico = VALUES(basico), almuerzo = VALUES(almuerzo)
  , origen = IF(origen = 'aeda', origen, 'manual');

-- Noviembre 2024 — CALCULADA (diciembre − 8 % de abril): 2024-11
INSERT INTO fisca_escala_salarial (periodo_desde, periodo_hasta, antiguedad, basico, almuerzo, origen)
SELECT '202411', '202411', j.i - 1, j.v, 6810.00, 'manual'
  FROM JSON_TABLE('[459042.89,470586.20,480902.24,511252.60,518646.46,535988.48,604862.09,612261.90,620857.65,630723.97,667050.27,678635.67,687754.80,697284.58,708683.38,718774.06,735591.81,745607.52,755175.08,766611.05,778346.08,786568.07,796733.20,806823.87,817961.10,866321.23,874020.10,883736.75,894051.81,901675.71,911691.71,920063.07,930079.08,940169.49,950260.17,960350.88]', '$[*]' COLUMNS (i FOR ORDINALITY, v DECIMAL(15,2) PATH '$')) j
ON DUPLICATE KEY UPDATE periodo_hasta = VALUES(periodo_hasta), basico = VALUES(basico), almuerzo = VALUES(almuerzo)
  , origen = IF(origen = 'aeda', origen, 'manual');

-- Diciembre 2024 (8 %): 2024-12
INSERT INTO fisca_escala_salarial (periodo_desde, periodo_hasta, antiguedad, basico, almuerzo, origen)
SELECT '202412', '202412', j.i - 1, j.v, 7242.00, 'manual'
  FROM JSON_TABLE('[488188.47,500464.69,511435.72,543713.08,551576.39,570019.50,643266.03,651135.67,660277.18,670769.94,709402.67,721723.65,731421.77,741556.62,753679.15,764410.51,782296.05,792947.68,803122.70,815284.77,827764.88,836508.90,847319.43,858050.78,869895.14,921325.75,929513.44,939847.02,950817.00,958924.96,969576.90,978479.77,989131.72,999862.79,1010594.15,1021325.54]', '$[*]' COLUMNS (i FOR ORDINALITY, v DECIMAL(15,2) PATH '$')) j
ON DUPLICATE KEY UPDATE periodo_hasta = VALUES(periodo_hasta), basico = VALUES(basico), almuerzo = VALUES(almuerzo)
  , origen = IF(origen = 'aeda', origen, 'manual');

-- Verificación
SELECT periodo_desde, periodo_hasta, origen, COUNT(*) AS antiguedades, MIN(basico) AS inicial, MAX(basico) AS a_35,
       MAX(almuerzo) AS almuerzo
  FROM fisca_escala_salarial WHERE periodo_desde BETWEEN '202308' AND '202501' GROUP BY periodo_desde, periodo_hasta, origen
 ORDER BY periodo_desde;
