-- oseda_aeda_pendientes_20261127.sql
-- ============================================================================
-- Se corre en la base `sindicato`. Idempotente.
--
-- Bandeja de lo que hay que reflejar en OSEDA (solo titulares). Las dos bases están en
-- servidores distintos, así que no hay una transacción que abarque a las dos:
-- el alta, baja o reactivación se graba acá junto con su fila en esta tabla
-- (todo o nada), y recién después se aplica en OSEDA. Si OSEDA no responde, la
-- fila queda PENDIENTE y la reintenta sincronizar_oseda_aeda.py. Nada se
-- pierde por un corte, y el orden se respeta: se procesa por id.
-- ============================================================================

USE sindicato;

CREATE TABLE IF NOT EXISTS p_afiliados_oseda_aeda (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    id_afiliado   INT NOT NULL,
    cuil          VARCHAR(11) NULL,
    motivo        ENUM('ALTA','BAJA','REACTIVACION') NOT NULL,
    accion        ENUM('AGREGAR','QUITAR') NOT NULL,
    estado        ENUM('PENDIENTE','APLICADO') NOT NULL DEFAULT 'PENDIENTE',
    resultado     VARCHAR(20) NULL COMMENT 'AGREGADO, QUITADO, YA_ESTABA, NO_ESTABA, SIN_AFILIADO, NO_TITULAR, SIN_CUIL',
    id_afiliado_oseda INT NULL COMMENT 'p_afiliados.id_afiliado en contable',
    ultimo_error  VARCHAR(500) NULL,
    intentos      INT NOT NULL DEFAULT 0,
    usuario       VARCHAR(80) NULL,
    creado        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    procesado     DATETIME NULL,
    KEY ix_oseda_aeda_estado (estado, id),
    KEY ix_oseda_aeda_afiliado (id_afiliado),
    CONSTRAINT fk_oseda_aeda_afiliado FOREIGN KEY (id_afiliado) REFERENCES p_afiliados (id_afiliado)
) COMMENT = 'Altas, bajas y reactivaciones a reflejar en el atributo AEDA de OSEDA (contable)';
