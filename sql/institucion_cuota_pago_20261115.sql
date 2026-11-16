-- Datos del sindicato: dónde se paga la cuota sindical y a quién consultar — 15/11/2026
--
-- Lo que la empresa ve en su enlace (/empresas/<token>) y en el instructivo
-- en PDF que se abre desde ahí (instructivo_empresa.py):
--
--   cuota_cuenta_fondos       la cuenta bancaria donde se paga la cuota. Es una
--                             de Tesorería → Cuentas de Fondos: el banco, el
--                             número, el CBU y el alias salen de ahí, no se
--                             escriben dos veces. El titular y el CUIT son los
--                             del sindicato (Identificación).
--   cuota_pago_indicaciones   lo que tiene que hacer la empresa al pagar: qué
--                             poner de referencia, a dónde mandar el comprobante.
--   cuota_consultas_email     el correo para consultas sobre el enlace y la cuota.
--   cuota_consultas_telefono  el teléfono, opcional. Sin ellos se usan el email
--                             y el teléfono generales del sindicato.
--
-- Pantalla: Administración del Sistema → Datos del Sindicato, bloque «Pago de
-- la cuota sindical y consultas».
--
-- Correrlo ENTERO: en DBeaver, «Ejecutar script» (Alt+X). Idempotente.

USE sindicato;

DROP PROCEDURE IF EXISTS _institucion_cuota_pago;
DELIMITER //
CREATE PROCEDURE _institucion_cuota_pago()
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'sindicato'
                    AND table_name = 's_institucion' AND column_name = 'cuota_cuenta_fondos') THEN
    ALTER TABLE s_institucion
      ADD COLUMN cuota_cuenta_fondos      INT          NULL COMMENT 'c_cuentas_de_fondos.id: donde las empresas pagan la cuota sindical',
      ADD COLUMN cuota_pago_indicaciones  VARCHAR(500) NULL COMMENT 'Qué hace la empresa al pagar: referencia, a dónde manda el comprobante',
      ADD COLUMN cuota_consultas_email    VARCHAR(100) NULL COMMENT 'Correo para consultas de las empresas sobre el enlace y la cuota',
      ADD COLUMN cuota_consultas_telefono VARCHAR(50)  NULL COMMENT 'Teléfono para esas consultas';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE table_schema = 'sindicato'
                    AND table_name = 's_institucion' AND constraint_name = 'fk_institucion_cuota_cuenta') THEN
    ALTER TABLE s_institucion
      ADD CONSTRAINT fk_institucion_cuota_cuenta FOREIGN KEY (cuota_cuenta_fondos)
          REFERENCES c_cuentas_de_fondos (id) ON DELETE SET NULL;
  END IF;
END //
DELIMITER ;
CALL _institucion_cuota_pago();
DROP PROCEDURE _institucion_cuota_pago;

-- Para revisar: las cuentas bancarias habilitadas que se pueden elegir.
SELECT f.id, f.nombre, b.nombre AS banco, f.numero_de_cuenta, f.cbu, f.alias
  FROM c_cuentas_de_fondos f LEFT JOIN c_codigo_de_banco b ON b.id = f.c_codigo_de_bancoId
 WHERE f.tipo_de_cuenta = 'B' AND f.habilitada = 1
 ORDER BY f.nombre;
