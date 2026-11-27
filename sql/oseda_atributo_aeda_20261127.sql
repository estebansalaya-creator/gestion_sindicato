-- oseda_atributo_aeda_20261127.sql
-- ============================================================================
-- Se corre en la base de OSEDA (contable). En Railway la base se llama `railway`.
-- Correrlo con un usuario administrador (root): crea un procedimiento y un
-- usuario. app_gestion no alcanza (no tiene CREATE ROUTINE ni CREATE USER).
-- En DBeaver: «Ejecutar script» (Alt+X). Idempotente.
--
-- Para qué
-- --------
-- Cuando gestion_sindicato da un alta, una baja o una reactivación, el
-- atributo AEDA («Afiliado al Gremio») del mismo CUIL en OSEDA tiene que
-- acompañar. Es la única excepción a la regla de oro (el sindicato no escribe
-- en contable), y por eso está acotada en MySQL y no en el código:
--
--   · El usuario `sind_oseda` NO tiene permisos sobre ninguna tabla. Solo
--     puede ejecutar este procedimiento.
--   · El procedimiento corre con los permisos de quien lo creó (SQL SECURITY
--     DEFINER) y lo único que sabe hacer es poner o sacar el atributo AEDA a
--     un TITULAR que ya existe, por CUIL. A un familiar no lo toca: en OSEDA
--     el atributo AEDA es del titular. No da altas en el padrón de OSEDA,
--     no toca otros atributos ni otros campos.
--   · Cada cambio deja su movimiento en p_afiliados_movimientos con el mismo
--     formato que la pantalla de atributos de gestion_adm, origen SISTEMA y
--     origen_ref «gestion_sindicato», para distinguirlo de lo manual.
--
-- Ojo: AEDA tiene «afecta coberturas» = 1. Poner o sacar el atributo cambia la
-- cobertura que se factura.
--
-- Devuelve una fila con `resultado`:
--   AGREGADO · QUITADO · YA_ESTABA · NO_ESTABA
--   SIN_AFILIADO (el CUIL no está en OSEDA) · NO_TITULAR (en OSEDA es familiar: no se toca)
-- ============================================================================

USE railway;     -- en una base local de prueba: USE contable;

DROP PROCEDURE IF EXISTS sp_sindicato_atributo_aeda;

DELIMITER $$
CREATE PROCEDURE sp_sindicato_atributo_aeda(
    IN p_cuil    VARCHAR(11),
    IN p_accion  VARCHAR(10),      -- AGREGAR | QUITAR
    IN p_usuario VARCHAR(60),      -- quién lo hizo en gestion_sindicato
    IN p_motivo  VARCHAR(20)       -- ALTA | BAJA | REACTIVACION, para la observación
)
SQL SECURITY DEFINER
COMMENT 'Único punto de escritura de gestion_sindicato en contable: atributo AEDA por CUIL'
BEGIN
    DECLARE v_atr INT;
    DECLARE v_af  INT;
    DECLARE v_par INT;
    DECLARE v_hay INT DEFAULT 0;
    DECLARE v_res VARCHAR(20);
    DECLARE v_obs VARCHAR(300);

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    IF p_accion NOT IN ('AGREGAR', 'QUITAR') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sp_sindicato_atributo_aeda: acción inválida';
    END IF;

    -- Por rótulo y no por id: el id 4 es el de hoy en Railway, no tiene por
    -- qué ser el mismo en otra instalación.
    SET v_atr = (SELECT id FROM p_afiliado_atributo WHERE rotulo = 'AEDA' ORDER BY id LIMIT 1);
    IF v_atr IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sp_sindicato_atributo_aeda: no existe el atributo AEDA';
    END IF;

    START TRANSACTION;

    SELECT MAX(id_afiliado), MAX(cod_parentesco) INTO v_af, v_par
      FROM p_afiliados WHERE cuil = p_cuil;

    IF v_af IS NULL THEN
        SET v_res = 'SIN_AFILIADO';
    ELSEIF v_par <> 0 THEN
        -- El atributo AEDA es del titular: en un familiar no significa nada.
        SET v_res = 'NO_TITULAR';
    ELSE
        SET v_hay = (SELECT COUNT(*) FROM p_atributos_por_afiliado
                      WHERE id_afiliado = v_af AND id_atributo = v_atr);
        SET v_obs = LEFT(CONCAT(IF(p_accion = 'AGREGAR', 'Se asignó', 'Se quitó'),
                                ' el atributo «AEDA» desde gestion_sindicato (',
                                LOWER(IFNULL(p_motivo, 'cambio')), ' en el gremio)'), 300);

        IF p_accion = 'AGREGAR' AND v_hay = 0 THEN
            INSERT INTO p_atributos_por_afiliado (id_atributo, id_afiliado, observaciones, usuario)
            VALUES (v_atr, v_af, LEFT(CONCAT('gestion_sindicato: ', IFNULL(p_motivo, '')), 200),
                    LEFT(p_usuario, 60));
            SET v_res = 'AGREGADO';
        ELSEIF p_accion = 'QUITAR' AND v_hay > 0 THEN
            DELETE FROM p_atributos_por_afiliado WHERE id_afiliado = v_af AND id_atributo = v_atr;
            SET v_res = 'QUITADO';
        ELSE
            SET v_res = IF(p_accion = 'AGREGAR', 'YA_ESTABA', 'NO_ESTABA');
        END IF;

        IF v_res IN ('AGREGADO', 'QUITADO') THEN
            INSERT INTO p_afiliados_movimientos
                (id_afiliado, cuil, tipo_movimiento, origen, origen_ref, campo, campo_label,
                 valor_anterior, valor_actual, usuario, observaciones)
            VALUES (v_af, p_cuil, 'MODIFICACION', 'SISTEMA', 'gestion_sindicato', 'atributo', 'Atributo',
                    IF(v_res = 'QUITADO', 'AEDA', NULL), IF(v_res = 'AGREGADO', 'AEDA', NULL),
                    LEFT(p_usuario, 80), v_obs);
        END IF;
    END IF;

    COMMIT;
    SELECT v_res AS resultado, v_af AS id_afiliado_oseda;
END$$
DELIMITER ;

-- Usuario de gestion_sindicato para OSEDA. Cambiar la contraseña antes de
-- correrlo y llevarla a SIND_OSEDA_AEDA_PASS (nunca al repositorio); SIND_OSEDA_AEDA_USER=sind_oseda.
CREATE USER IF NOT EXISTS 'sind_oseda'@'%' IDENTIFIED BY 'CAMBIAR_ESTA_CLAVE';
GRANT EXECUTE ON PROCEDURE sp_sindicato_atributo_aeda TO 'sind_oseda'@'%';

-- Control: tiene que mostrar USAGE y el EXECUTE del procedimiento, nada más.
SHOW GRANTS FOR 'sind_oseda'@'%';
