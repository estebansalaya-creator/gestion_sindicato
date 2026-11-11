# Base `sindicato` — estructura replicada desde `contable`

Fecha: 26/08/2026 · **141 tablas nuevas + 16 vistas + 202 FK** · collation unificada en `utf8mb4_0900_ai_ci`

Método: `CREATE TABLE ... LIKE contable.x` (copia tipos, índices, defaults y comentarios) + recreación
automática de FK desde `information_schema` + vistas con `REPLACE(definicion,'contable','sindicato')`.

**Fuera de alcance:** liquidación de planes / coberturas (`l_*`), fiscalización y acuerdos de pago (`f_*`
salvo `f_comprobantes_arca`), Mecanismo de Integración, SSSalud, débito automático Prisma, ARCA de nómina.

---

## Módulos creados

### Sistema / seguridad (18)
`s_usuarios` `s_roles` `s_usuario_rol` `s_areas` `s_area_usuario` `s_menu` `s_menu_prefijos`
`s_menu_rol` `s_menu_usuario` `s_menu_tablas` `s_accesos_directos` `s_accesos_denegados`
`s_configuracion` `s_contactos` `s_atributos` `s_atributos_def` `s_atributos_val` `s_log_procesos`

### Procesos desatendidos y mail (9)
`proc_procesos` `proc_corridas` `proc_corridas_log` `proc_solicitudes`
`mail_config` `mail_remitentes` `mail_tipos` `mail_tipo_copias` `mail_envios`

### Asistente IA (2)
`ia_consultas` `ia_usuario_config`

### Catálogos generales (14) — **con datos**
`arca_tipo_documento` `arca_tipo_comprobante` `arca_responsable_tipo` `arca_tasa_iva`
`arca_unidad_de_medida` `arca_feriados` `arca_c_actividad` `p_provincia` `c_codigo_de_banco`
`c_especies` `c_areas_contacto` `rg830_escala` `rg830_escala_tramos` · `c_numeradores` (vacía)

### Empleadores (3) — **`p_empresas` cargada con 2.854 empresas**
`p_empresas` `p_domicilios_explotacion` `p_relaciones_laborales`

### Padrón de afiliados (15) — estructura vacía, catálogos con datos
`p_afiliados` `p_afiliados_movimientos` `p_atributos_por_afiliado` `p_afiliado_atributo`
`p_documentacion` `p_certificados_discapacidad`
Catálogos cargados: `p_tipo_documento` `p_estado_civil` `p_nacionalidad` `p_parentesco`
`p_tipo_beneficiario` `p_situacion_revista` `p_motivo_movimiento` `p_tipo_documentacion`
`p_obras_sociales` (546)

> `p_afiliados` conserva las columnas `l_coberturaId` e `id_comercializador` **sin FK**: apuntaban a
> liquidación de planes y a comercializadores, ambos fuera de alcance.

### Proveedores y pasivo (13) — estructura vacía
`c_proveedores` `c_proveedores_certificados_exencion` `c_proveedores_cuentas_gasto`
`c_proveedores_cuentas_pasivo` `c_concepto_de_gastos` `c_rubros_de_pasivo` `c_rubros_de_activo`
`f_comprobantes_arca` `me_expedientes` `me_expediente_movimientos`
`c_pasivo_liquidacion` `c_pasivo_liquidacion_detalle` `c_pasivo_aplicacion`

### Reintegros a afiliados (5)
`c_reintegro_afiliados` `c_reintegro_afiliados_aprobacion` `c_reintegro_afiliados_detalle`
`c_reintegro_afiliados_detalle_adjunto` `pago_ordenes_reintegro_det`

### Circuito de pagos (18)
`pago_ordenes` `pago_ordenes_detalle` `pago_ordenes_anticipo_det` `pago_ordenes_concepto_det`
`pago_ordenes_sueldos_det` `pago_ordenes_aprobacion` `pago_config_aprobadores`
`pago_pagos` `pago_pagos_instrumentos` `pago_imputaciones` `pago_imputaciones_config`
`pago_retenciones` `pago_retenciones_certificado` `pago_transferencias_lote`
`pago_transferencias_lote_det` `c_nomina_empleados` `c_nomina_empleados_historial`
`c_pago_sueldos_imputaciones`

> No se replicó `pago_ordenes_integracion_det` (Mecanismo de Integración).

### Circuito de ingresos y facturación (11)
`ingreso_ordenes` `ingreso_ordenes_cuentas` `ingreso_ordenes_detalle` `c_motivos_de_ingreso`
`c_talonario` `c_talonario_clasificacion` `c_concepto_de_facturacion`
`c_comprobantes_emitidos` `c_comprobantes_emitidos_item` `c_comprobantes_emitidos_cobranza`
`c_comprobantes_aplicacion`

### Fondos / tesorería (8)
`c_cuentas_de_fondos` `c_chequeras` `c_movimientos_de_fondos` `c_movimiento_entre_cuentas`
`c_movimiento_entre_cuentas_det` `c_inversiones` `c_valores_de_terceros`
`c_valores_de_terceros_movimientos`

### Bancos y conciliación (9)
`c_extractos_bancarios` `c_debitos_creditos_bancarios` `c_extracto_cuil_asignado`
`c_cobro_cuil_equivalencia` `conc_reglas` `conciliacion_header` `conciliacion_items`
`conciliacion_grupos` `conciliacion_comprobantes`

### Contabilidad (17)
`c_ejercicios` `c_periodos` `c_cierres` `c_plan_de_cuentas` `c_clasificacion_plan_cuentas`
`c_plan_de_cuentas_clasificacion` `c_asientos` `c_asiento_detalle` `c_asientos_automaticos`
`c_asientos_automaticos_lineas` `c_balance_general` `c_balance_sumas_saldos`
`c_estado_resultados` `c_indices_inflacion` `c_indices_inflacion_periodos`
`c_contable_comprobante_tipo` `c_numeradores`

### Vistas (16)
`c_libro_mayor` `c_vista_plan_cuentas` `c_vista_ejercicios` `c_vista_balance_general`
`c_vista_estado_resultados` `v_plan_de_cuentas` `v_saldos_cuentas_fondos` `v_comprobantes_saldo`
`v_cc_proveedores_movimientos` `v_cc_proveedores_saldo` `v_saldo_expedientes`
`v_expedientes_liquidados_impagos` `v_retenciones_por_pago` `v_usuarios_nombre`
`v_reintegro_saldo` `v_reintegros_afiliados`

> `v_cuenta_corriente_saldo` no se replicó: depende de `l_configuracion` (liquidación de planes).

---

## FK omitidas a propósito

Las columnas quedan, sin constraint, porque la tabla padre está fuera de alcance:

| Tabla | Columna | Apuntaba a |
|---|---|---|
| `c_comprobantes_emitidos` | `id_liquidacion_grupofamiliar` | `l_liquidacion_grupofamiliar` |
| `c_comprobantes_emitidos` | `id_acuerdo_pago` | `f_acuerdos_pago` |
| `c_proveedores` | `idhospital` | `sssalud_hospitales` |
| `p_afiliados` | `l_coberturaId` | `l_cobertura` |
| `p_afiliados` | `id_comercializador` | `p_comercializadores` |

`c_comprobantes_emitidos.p_afiliadosId → p_afiliados` **sí** quedó activa.

---

## Tablas preexistentes en `sindicato` (no se tocaron)

`padron` (3.891) · `fisca_cuotarecepcion` (4.070) · `fisca_importacion_log` (1.074) ·
`inscripciones_dia_del_nino`

---

## Pendiente

1. **`padron` y `p_afiliados` conviven como padrones independientes.** No se migra por ahora.
   Más adelante van a vincularse; cuando se defina el criterio (por CUIL, o una columna de enlace
   explícita tipo `p_afiliados.id_padron`) se agrega la relación.
2. **Plan de cuentas**: armar el del sindicato o copiar las 282 cuentas de `contable` como base.
3. **Menú (`s_menu`, `s_menu_rol`)**: armar de cero o copiar los 172 nodos y podar módulos de OS.
4. **Usuarios y áreas**: alta de `s_usuarios` / `s_areas`.
5. **`c_ejercicios` apunta a `p_empresas`**: identificar el registro del sindicato antes de abrir el
   primer ejercicio contable.
6. **Proveedores**: quedaron vacíos por decisión — se cargan a mano o por importación.
