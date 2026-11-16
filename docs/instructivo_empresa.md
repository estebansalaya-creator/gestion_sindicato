# Instructivo para la empresa: enlace de cuota sindical

## Qué es este enlace

Con este enlace la empresa presenta todos los meses la cuota sindical de {sigla} y mantiene al día la nómina de sus afiliados. Se entra sin usuario ni clave: el enlace es la llave.

- **Es personal de la empresa.** Úsenlo solo las personas a cargo de la liquidación de sueldos; no lo reenvíen ni lo publiquen.
- **Es el mismo todos los meses.** Guárdenlo en favoritos.
- **Si lo pierden o deja de funcionar**, pidan uno nuevo al sindicato. Al generar uno nuevo, el anterior deja de andar.

**Confidencialidad.** Por el enlace circulan datos personales, remuneraciones y afiliación sindical, que es un dato sensible (Ley 25.326, art. 2). El sindicato los usa solamente para liquidar y fiscalizar la cuota sindical (Ley 23.551, art. 38) y no los cede a terceros.

## Qué van a ver al entrar

La página tiene estos bloques, uno debajo del otro, con el nombre y el CUIT de la empresa arriba. Este instructivo se abre desde el botón **Instructivo** de la página.

| Bloque | Para qué sirve |
| --- | --- |
| Pago de la cuota y consultas | La cuenta donde se paga la cuota y a quién consultar. |
| Presentar la cuota sindical de un mes | Subir el archivo del Libro de Sueldos Digital o cargar las remuneraciones a mano. |
| Nómina | Ver qué afiliados tiene el sindicato trabajando en la empresa e informar una baja. |
| Informar un alta | Agregar a un afiliado que no figura en la nómina, con su ficha de afiliación. |
| Altas y bajas informadas | Seguir el estado de lo que informaron: en revisión, aprobada o rechazada. |
| Presentaciones | Ver lo presentado cada mes y descargar la planilla en Excel. |

## Presentar la cuota con el archivo del Libro de Sueldos Digital

Es la forma recomendada: el sistema arma solo la planilla con el archivo que la empresa ya le presenta a ARCA.

1. En su sistema de sueldos, generen el archivo de liquidación del mes para ARCA: el `.txt` de «Liquidación de SyJ – DJ F931».
2. En el bloque **Presentar la cuota sindical de un mes**, elijan ese archivo y toquen **Leer el archivo**.
3. El sistema toma el CUIT y el mes del archivo, busca a los afiliados y arma la planilla con la cuota. Todavía no está presentada.
4. Revisen la planilla (ver «Revisar la planilla antes de presentar»).
5. Si está bien, toquen **Presentar**. Si no, **Descartar** y suban otro archivo.

- **Más de una liquidación en el mes** (por ejemplo, el SAC aparte): suban la última, que trae las bases acumuladas del mes.
- **Lo último que presenten para un mes reemplaza a lo anterior.** Sirve para corregir.
- **Si el archivo tiene un error** —otro CUIT, un mes que no empezó o un formato que no es el de ARCA— no se guarda nada y la página dice qué renglones fallan.

## Presentar la cuota sin el archivo: carga a mano

Si no tienen el archivo, cargan la remuneración de cada afiliado y el sistema calcula la cuota igual.

1. En el bloque **Presentar la cuota sindical de un mes**, parte «Sin el archivo», elijan el mes y toquen **Cargar las remuneraciones**.
2. Aparece la nómina de ese mes y las altas que hayan informado, con una casilla por persona.
3. Escriban la remuneración sujeta a aportes del mes, la misma que declaran en el F.931. Usen coma para los centavos: `1.250.000,50`.
4. Si alguien no cobró en el mes, dejen su casilla vacía.
5. El total y la cuota se calculan mientras escriben. Toquen **Armar la planilla**.
6. Revisen la planilla. Con **Corregir las remuneraciones** vuelven a la carga; si está bien, toquen **Presentar**.

- **Falta alguien:** informen el alta (ver «Cómo informar un alta») y vuelvan a cargar el mes; ya aparece en la lista.
- **Volver a entrar a un mes** trae lo último que cargaron, para no escribirlo de nuevo.

## Revisar la planilla antes de presentar

La planilla tiene un renglón por afiliado, con su remuneración y la cuota a la alícuota del sindicato (hoy {alicuota}). Arriba figuran el total a pagar y la fecha de vencimiento.

| Columna | Qué indica |
| --- | --- |
| Origen | «En el archivo»; «No está en el archivo» (afiliado de su nómina que no figura, va en cero); «Cargada a mano»; «Alta informada» (en revisión, ya paga desde su fecha de alta). |
| Activo de la empresa | Si el padrón del sindicato lo tiene trabajando en la empresa. |
| Remuneración | La del archivo (Remuneración imponible 5) o la que cargaron a mano. |
| Cuota | Remuneración × alícuota. |
| Retenido en el recibo | Solo con el archivo: lo retenido con el concepto «Cuota Sindical», para comparar. |

- Si alguien de «No está en el archivo» ya no trabaja en la empresa, informen la baja.
- Al tocar **Presentar**, la planilla queda como la liquidación del mes y la página confirma el importe y el vencimiento.
- Ya presentada, **Descargar planilla** baja el Excel con el formato de la planilla de aportes.
- Después de presentar, paguen la cuota (ver «Cómo pagar la cuota»).

## Cómo pagar la cuota

La cuota se paga por transferencia o depósito en la cuenta del sindicato. El importe y el vencimiento figuran en la planilla presentada: la cuota vence el mismo día que el F.931 de la empresa, según la terminación de su CUIT.

[[pago]]

## La nómina y cómo informar una baja

La nómina lista a los afiliados que, según el padrón del sindicato, trabajan hoy en la empresa, con la fecha desde la que están. Revísenla cada tanto: es la base de la cuota.

Si alguien ya no trabaja en la empresa:

1. En su renglón, toquen **Informar baja**.
2. Pongan la fecha de baja y, si quieren, el motivo.
3. Toquen **Informar**. El renglón queda como «Baja informada … en revisión».

Hasta que el sindicato apruebe la baja, la cuota del mes lo sigue incluyendo. Si ese mes no cobró, va en cero: en el archivo no figura, y en la carga a mano dejen su casilla vacía.

## Cómo informar un alta

Informen el alta de un trabajador afiliado al que le corresponde cuota y que no figura en la nómina: un ingreso nuevo o alguien que se afilió.

1. En el bloque **Informar un alta**, escriban el **CUIL**.
2. **Apellido y nombres**: obligatorio si todavía no es afiliado del sindicato. Si ya lo es, el sistema lo toma del padrón.
3. **Fecha de alta en la empresa**.
4. **Ficha de afiliación**: la ficha firmada por el trabajador, en PDF o foto, de hasta 10 MB. Es opcional, pero agiliza la aprobación de un afiliado nuevo.
5. **Observaciones**, si hace falta aclarar algo.
6. Toquen **Informar el alta**.

La cuota del mes ya lo incluye desde la fecha de alta, aunque el sindicato todavía la esté revisando. El sistema no acepta un CUIL mal escrito ni el de alguien que ya está en la nómina.

## Seguimiento de altas y bajas

Cada alta o baja informada aparece en **Altas y bajas informadas** con su estado. El sindicato las revisa y recién al aprobarlas cambia el padrón.

| Estado | Qué significa | Efecto en la cuota |
| --- | --- | --- |
| En revisión | El sindicato todavía no la revisó. Se puede **Retirar**. | El alta ya cuenta desde su fecha; la baja todavía no. |
| Aprobada | Quedó en el padrón del sindicato. | El alta sigue en la nómina; la baja sale desde su fecha. |
| Rechazada | El sindicato no la aceptó; debajo figura el motivo. | No cambia nada. |
| Retirada | La retiró la empresa antes de la revisión. | No cambia nada. |

## Preguntas frecuentes

**Presenté un mes con un error.** Vuelvan a presentarlo, con el archivo o a mano: la última presentación del mes reemplaza a la anterior.

**El archivo da error.** Lean los mensajes: dicen qué falla y en qué renglón. Si no lo pueden resolver, carguen las remuneraciones a mano.

**Alguien de la nómina ya no trabaja en la empresa.** Informen la baja desde su renglón de la nómina.

**Falta un afiliado en la nómina.** Informen el alta, con la ficha de afiliación si la tienen.

**¿Dónde pago la cuota?** En la cuenta del sindicato que figura en «Cómo pagar la cuota» y en el bloque **Pago de la cuota y consultas** del enlace.

**Cambió la persona que liquida los sueldos.** Pidan al sindicato un enlace nuevo: el anterior deja de funcionar.

**Quiero la planilla de un mes ya presentado.** En **Presentaciones**, el botón de planilla de ese mes baja el Excel.

## Contacto

[[contacto]]
