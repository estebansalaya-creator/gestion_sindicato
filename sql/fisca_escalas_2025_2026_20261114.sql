-- =============================================================================
-- fisca_escalas_2025_2026_20261114.sql — Escalas de la paritaria 2024-2026
-- =============================================================================
--
-- Las 12 escalas que AEDA no cargó en fis_escalas, pasadas de las circulares
-- firmadas (AEDA / CDA) el 14/11/2026. Básico por antigüedad (0 a 35) y almuerzo
-- diario. Controles hechos al pasarlas: enero y mayo 2025 cierran contra el
-- «sueldo conformado» (básico + comida art. 9 CCT 417/05) y, entre una escala y
-- la siguiente, todas las antigüedades suben en la misma proporción.
--
-- Cada vigencia llega hasta el mes anterior a la siguiente; la última
-- (Septiembre 2026) queda abierta (periodo_hasta NULL). Falta 2023-10 a 2024-12.
--
-- Requiere sql/fisca_escalas_20261114.sql. Correrlo ENTERO (Alt+X). Idempotente:
-- vuelve a dejar los valores de las circulares, sin tocar lo que vino de AEDA.

USE sindicato;
SET NAMES utf8mb4;

-- Enero 2025 (5 %): 2025-01 a 2025-02
INSERT INTO fisca_escala_salarial (periodo_desde, periodo_hasta, antiguedad, basico, almuerzo, origen)
SELECT '202501', '202502', j.i - 1, j.v, 7512.00, 'manual'
  FROM JSON_TABLE('[506404.46,519138.74,530519.14,564000.88,572157.59,591288.89,667268.50,675431.77,684914.38,695798.67,735872.92,748653.64,758713.63,769226.64,781801.51,792933.29,811486.20,822535.28,833089.96,845705.85,858651.63,867721.92,878935.83,890067.60,902353.91,955703.58,964196.77,974915.94,986295.25,994705.74,1005755.14,1014990.21,1026039.62,1037171.11,1048302.88,1059434.70]', '$[*]' COLUMNS (i FOR ORDINALITY, v DECIMAL(15,2) PATH '$')) j
ON DUPLICATE KEY UPDATE periodo_hasta = VALUES(periodo_hasta), basico = VALUES(basico), almuerzo = VALUES(almuerzo)
  , origen = IF(origen = 'aeda', origen, 'manual');

-- Marzo 2025 (4 %): 2025-03 a 2025-04
INSERT INTO fisca_escala_salarial (periodo_desde, periodo_hasta, antiguedad, basico, almuerzo, origen)
SELECT '202503', '202504', j.i - 1, j.v, 7728.00, 'manual'
  FROM JSON_TABLE('[520977.25,534077.99,545785.88,580231.12,588622.56,608304.39,686470.47,694868.66,704624.15,715821.65,757049.12,770197.63,780547.11,791362.66,804299.39,815751.51,834838.32,846205.36,857063.78,870042.71,883361.03,892692.34,904228.95,915681.05,928320.93,983205.84,991943.44,1002971.08,1014677.85,1023330.37,1034697.73,1044198.56,1055565.94,1067017.76,1078469.87,1089922.03]', '$[*]' COLUMNS (i FOR ORDINALITY, v DECIMAL(15,2) PATH '$')) j
ON DUPLICATE KEY UPDATE periodo_hasta = VALUES(periodo_hasta), basico = VALUES(basico), almuerzo = VALUES(almuerzo)
  , origen = IF(origen = 'aeda', origen, 'manual');

-- Mayo 2025 (5 %): 2025-05 a 2025-07
INSERT INTO fisca_escala_salarial (periodo_desde, periodo_hasta, antiguedad, basico, almuerzo, origen)
SELECT '202505', '202507', j.i - 1, j.v, 8115.00, 'manual'
  FROM JSON_TABLE('[547026.11,560781.89,573075.17,609242.67,618053.69,638719.61,720793.99,729612.09,739855.36,751612.73,794901.58,808707.51,819574.47,830930.79,844514.36,856539.09,876580.23,888515.62,899916.96,913544.84,927529.08,937326.95,949440.39,961465.11,974736.98,1032366.13,1041540.62,1053119.63,1065411.74,1074496.88,1086432.62,1096408.49,1108344.24,1120368.65,1132393.37,1144418.13]', '$[*]' COLUMNS (i FOR ORDINALITY, v DECIMAL(15,2) PATH '$')) j
ON DUPLICATE KEY UPDATE periodo_hasta = VALUES(periodo_hasta), basico = VALUES(basico), almuerzo = VALUES(almuerzo)
  , origen = IF(origen = 'aeda', origen, 'manual');

-- Agosto 2025 (5 %): 2025-08 a 2025-09
INSERT INTO fisca_escala_salarial (periodo_desde, periodo_hasta, antiguedad, basico, almuerzo, origen)
SELECT '202508', '202509', j.i - 1, j.v, 8500.00, 'manual'
  FROM JSON_TABLE('[573074.97,587485.79,600364.47,638254.23,647484.82,669134.83,755117.52,764355.52,775086.56,787403.81,832754.04,847217.39,858601.82,870498.92,884729.33,897326.67,918322.15,930825.89,942770.15,957046.98,971697.13,981961.57,994651.84,1007249.16,1021153.02,1081526.42,1091137.79,1103268.18,1116145.63,1125663.40,1138167.51,1148618.42,1161122.53,1173719.53,1186316.86,1198914.23]', '$[*]' COLUMNS (i FOR ORDINALITY, v DECIMAL(15,2) PATH '$')) j
ON DUPLICATE KEY UPDATE periodo_hasta = VALUES(periodo_hasta), basico = VALUES(basico), almuerzo = VALUES(almuerzo)
  , origen = IF(origen = 'aeda', origen, 'manual');

-- Octubre 2025 (5 %): 2025-10 a 2025-10
INSERT INTO fisca_escala_salarial (periodo_desde, periodo_hasta, antiguedad, basico, almuerzo, origen)
SELECT '202510', '202510', j.i - 1, j.v, 8890.00, 'manual'
  FROM JSON_TABLE('[599123.83,614189.68,627653.76,667265.79,676915.94,699550.05,789441.04,799098.96,810317.77,823194.90,870606.49,885727.27,897629.18,910067.06,924944.30,938114.24,960064.06,973136.16,985623.34,1000549.11,1015865.18,1026596.19,1039863.29,1053033.21,1067569.07,1130686.72,1140734.96,1153416.74,1166879.52,1176829.92,1189902.39,1200828.35,1213900.83,1227070.42,1240240.35,1253410.34]', '$[*]' COLUMNS (i FOR ORDINALITY, v DECIMAL(15,2) PATH '$')) j
ON DUPLICATE KEY UPDATE periodo_hasta = VALUES(periodo_hasta), basico = VALUES(basico), almuerzo = VALUES(almuerzo)
  , origen = IF(origen = 'aeda', origen, 'manual');

-- Noviembre 2025 (5 %): 2025-11 a 2026-01
INSERT INTO fisca_escala_salarial (periodo_desde, periodo_hasta, antiguedad, basico, almuerzo, origen)
SELECT '202511', '202601', j.i - 1, j.v, 9275.00, 'manual'
  FROM JSON_TABLE('[625172.70,640893.58,654943.05,696277.34,706347.07,729965.27,823764.56,833842.39,845548.98,858985.98,908458.95,924237.15,936656.54,949635.19,965159.27,978901.82,1001805.98,1015446.43,1028476.53,1044051.25,1060033.23,1071230.80,1085074.73,1098817.26,1113985.12,1179847.01,1190332.13,1203565.29,1217613.42,1227996.44,1241637.28,1253038.28,1266679.13,1280421.31,1294163.85,1307906.44]', '$[*]' COLUMNS (i FOR ORDINALITY, v DECIMAL(15,2) PATH '$')) j
ON DUPLICATE KEY UPDATE periodo_hasta = VALUES(periodo_hasta), basico = VALUES(basico), almuerzo = VALUES(almuerzo)
  , origen = IF(origen = 'aeda', origen, 'manual');

-- Febrero 2026 (5 %): 2026-02 a 2026-02
INSERT INTO fisca_escala_salarial (periodo_desde, periodo_hasta, antiguedad, basico, almuerzo, origen)
SELECT '202602', '202602', j.i - 1, j.v, 9680.00, 'manual'
  FROM JSON_TABLE('[652524.00,668932.68,683596.81,726739.48,737249.76,761901.25,859804.26,870322.99,882541.75,896566.62,948204.03,964672.53,977635.26,991181.73,1007384.99,1021728.77,1045634.99,1059872.21,1073472.38,1089728.49,1106409.69,1118097.15,1132546.75,1146890.52,1162721.97,1231465.31,1242409.16,1256221.27,1270884.00,1281721.28,1295958.91,1307858.70,1322096.34,1336439.74,1350783.52,1365127.34]', '$[*]' COLUMNS (i FOR ORDINALITY, v DECIMAL(15,2) PATH '$')) j
ON DUPLICATE KEY UPDATE periodo_hasta = VALUES(periodo_hasta), basico = VALUES(basico), almuerzo = VALUES(almuerzo)
  , origen = IF(origen = 'aeda', origen, 'manual');

-- Marzo 2026 (5 %): 2026-03 a 2026-04
INSERT INTO fisca_escala_salarial (periodo_desde, periodo_hasta, antiguedad, basico, almuerzo, origen)
SELECT '202603', '202604', j.i - 1, j.v, 10085.00, 'manual'
  FROM JSON_TABLE('[679875.31,696971.77,712250.57,757201.61,768152.44,793837.23,895843.96,906803.60,919534.54,934147.25,987949.11,1005107.90,1018613.98,1032728.27,1049610.71,1064555.73,1089460.04,1104297.99,1118468.23,1135405.73,1152786.14,1164963.50,1180018.77,1194963.78,1211458.81,1283083.62,1294486.19,1308877.26,1324154.59,1335446.13,1350280.54,1362670.13,1377513.55,1392458.17,1407403.18,1422348.25]', '$[*]' COLUMNS (i FOR ORDINALITY, v DECIMAL(15,2) PATH '$')) j
ON DUPLICATE KEY UPDATE periodo_hasta = VALUES(periodo_hasta), basico = VALUES(basico), almuerzo = VALUES(almuerzo)
  , origen = IF(origen = 'aeda', origen, 'manual');

-- Mayo 2026 (4 %): 2026-05 a 2026-05
INSERT INTO fisca_escala_salarial (periodo_desde, periodo_hasta, antiguedad, basico, almuerzo, origen)
SELECT '202605', '202605', j.i - 1, j.v, 10500.00, 'manual'
  FROM JSON_TABLE('[707070.32,724850.64,740740.59,787489.67,798878.54,825590.72,931677.72,943075.74,956315.90,971513.14,1027467.07,1045312.22,1059358.54,1074037.40,1091595.14,1107137.95,1133042.56,1148469.91,1163206.96,1180821.96,1198897.59,1211562.04,1227219.52,1242762.33,1259917.17,1334406.97,1346265.64,1361232.35,1377120.77,1388863.97,1404291.76,1417186.29,1432614.09,1448156.50,1463699.31,1479242.18]', '$[*]' COLUMNS (i FOR ORDINALITY, v DECIMAL(15,2) PATH '$')) j
ON DUPLICATE KEY UPDATE periodo_hasta = VALUES(periodo_hasta), basico = VALUES(basico), almuerzo = VALUES(almuerzo)
  , origen = IF(origen = 'aeda', origen, 'manual');

-- Junio 2026 (2 %): 2026-06 a 2026-07
INSERT INTO fisca_escala_salarial (periodo_desde, periodo_hasta, antiguedad, basico, almuerzo, origen)
SELECT '202606', '202607', j.i - 1, j.v, 10700.00, 'manual'
  FROM JSON_TABLE('[720667.82,738790.08,754985.60,802633.71,814241.59,841467.47,949594.60,961211.82,974706.59,990196.09,1047226.05,1065414.38,1079730.82,1094691.96,1112587.35,1128429.07,1154831.84,1170555.87,1185576.32,1203530.08,1221953.31,1234861.31,1250819.90,1266661.60,1284146.34,1360068.64,1372155.36,1387409.89,1403603.87,1415572.90,1431297.37,1444439.87,1460164.36,1476005.66,1491847.38,1507689.15]', '$[*]' COLUMNS (i FOR ORDINALITY, v DECIMAL(15,2) PATH '$')) j
ON DUPLICATE KEY UPDATE periodo_hasta = VALUES(periodo_hasta), basico = VALUES(basico), almuerzo = VALUES(almuerzo)
  , origen = IF(origen = 'aeda', origen, 'manual');

-- Agosto 2026 (3 %): 2026-08 a 2026-08
INSERT INTO fisca_escala_salarial (periodo_desde, periodo_hasta, antiguedad, basico, almuerzo, origen)
SELECT '202608', '202608', j.i - 1, j.v, 10800.00, 'manual'
  FROM JSON_TABLE('[741064.08,759699.23,776353.12,825349.75,837286.16,865282.59,976469.92,988415.92,1002292.62,1018220.51,1076864.52,1095567.62,1110289.24,1125673.81,1144075.67,1160365.74,1187515.76,1203684.81,1219130.37,1237592.25,1256536.89,1269810.21,1286220.46,1302510.52,1320490.11,1398561.15,1410989.95,1426676.21,1443328.50,1455636.28,1471805.79,1485320.25,1501489.77,1517779.41,1534069.47,1550359.59]', '$[*]' COLUMNS (i FOR ORDINALITY, v DECIMAL(15,2) PATH '$')) j
ON DUPLICATE KEY UPDATE periodo_hasta = VALUES(periodo_hasta), basico = VALUES(basico), almuerzo = VALUES(almuerzo)
  , origen = IF(origen = 'aeda', origen, 'manual');

-- Septiembre 2026 (1,5 %): 2026-09 en adelante
INSERT INTO fisca_escala_salarial (periodo_desde, periodo_hasta, antiguedad, basico, almuerzo, origen)
SELECT '202609', NULL, j.i - 1, j.v, 11000.00, 'manual'
  FROM JSON_TABLE('[751262.21,770153.81,787036.88,836707.78,848808.45,877190.14,989907.58,1002017.98,1016085.64,1032232.71,1091683.76,1110644.23,1125568.45,1141164.73,1159819.83,1176334.08,1203857.72,1220249.28,1235907.39,1254623.33,1273828.69,1287284.67,1303920.74,1320434.97,1338661.99,1417807.40,1430407.24,1446309.37,1463190.82,1475667.97,1492060.00,1505760.44,1522152.47,1538666.28,1555180.52,1571694.82]', '$[*]' COLUMNS (i FOR ORDINALITY, v DECIMAL(15,2) PATH '$')) j
ON DUPLICATE KEY UPDATE periodo_hasta = VALUES(periodo_hasta), basico = VALUES(basico), almuerzo = VALUES(almuerzo)
  , origen = IF(origen = 'aeda', origen, 'manual');

-- Verificación
SELECT periodo_desde, periodo_hasta, origen, COUNT(*) AS antiguedades, MIN(basico) AS inicial, MAX(basico) AS a_35,
       MAX(almuerzo) AS almuerzo
  FROM fisca_escala_salarial WHERE periodo_desde >= '202501' GROUP BY periodo_desde, periodo_hasta, origen
 ORDER BY periodo_desde;
