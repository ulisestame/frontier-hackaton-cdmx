# Decisiones

Este documento responde las tres preguntas del reto:
- qué consideramos PII;
- qué conservamos a propósito y por qué;
- cuánto costó correr el pipeline.

Cierra con las decisiones de diseño, el incidente de crecimiento de fuentes y las limitaciones conocidas. El detalle de cada cambio está en las PRs #1 a #11.

## 1. Qué consideramos PII

Todo dato que identifica a una persona natural, dondequiera que aparezca: columnas de tablas, texto de chats y documentos, metadatos de PDF y HTML, front matter, comentarios HTML, texto oculto, nombres de archivo y adjuntos. Cada forma se reemplaza por un seudónimo de la misma categoría. El seudónimo es el mismo para la misma persona en todas las fuentes y en todas las corridas.

| Categoría | Cómo se reemplaza |
| --- | --- |
| Nombres de personas: clientes, empleados, autores de chat, terceros nombrados en el texto | Un nombre colombiano del mismo género. Se conserva la forma: completo, corto, solo nombres de pila, mayúsculas, sin tildes, slug en nombres de archivo. |
| Correos, también deletreados ("arroba", "punto") | Un correo que imita el patrón del original (inicial y apellido, nombre.apellido, con o sin dígitos) con el nombre del seudónimo. El dominio corporativo se conserva; los personales pasan a un proveedor común. |
| Cédulas y documentos | Misma longitud y formato (puntos, prefijos), misma serie inicial y al menos la mitad de los dígitos distintos. |
| Celulares | Mismo formato (+57, espacios, guiones), prefijo móvil válido y lejos del original. |
| Direcciones | Misma forma (calle, carrera, diagonal; completa o abreviada; apartamento, oficina, casa), con números distintos. |
| Fechas de nacimiento | Se corren entre 200 y 1.500 días y conservan su formato: ISO, día/mes/año, mes/día/año en los documentos en inglés, "d de mes de año". |
| Placas, pasaportes, cuentas y tarjetas | Mismo formato. Las tarjetas siguen siendo válidas por Luhn. |
| Usuarios y handles: menciones `@usuario`, agente de un PQR | Un handle con el patrón del original. |

Ningún seudónimo puede coincidir con un valor real de otra persona. Todos los valores reales del registro se reservan antes de generar, también entre tipos de dígitos (cédula, celular, cuenta), porque el jurado compara cadenas de dígitos sin importar su tipo.

**Cuasi-identificadores.** La ciudad, el barrio, la ocupación o el año no son PII por sí solos, pero juntos pueden señalar a una persona. Por eso se generalizan, sin borrarlos:
- **En la tabla de clientes:** la ocupación pasa a su sector ("profesional de medios", "profesional del derecho"). El barrio pasa a otro barrio de la misma ciudad.
- **En autodescripciones de texto libre** ("soy …, vivo en …, desde …"): la ocupación pasa a su sector, el barrio a la ciudad y el año a "hace unos años". Si el barrio existe en varias ciudades, se usa la ciudad del dueño del registro.

## 2. Qué conservamos a propósito y por qué

- **Organizaciones y marcas**: bancos, billeteras, comercios, operadores, reguladores y la propia Kipu Pay. No son personas naturales y son justamente la información de negocio que el comprador quiere.
- **Lugares**: ciudades, centros comerciales, plazas. Un apellido que también es lugar sigue siendo apellido cuando nombra a una persona, y lo decide el contexto.
- **Figuras públicas**: artistas, deportistas, políticos y próceres. No son PII en este contexto y borrarlas destruiría el texto.
- **Montos, fechas de transacciones y de PQR, estados, canales y tipos**: datos de negocio que no identifican a nadie.
- **Llaves entre tablas** (`CL-`, `TX-`, `PQR-`, `KP-`, `PG-`, radicados): las tablas deben seguir uniendo las mismas filas. La estructura se puntúa y el dataset la necesita.
- **El nombre del bot (Kipi)**: no es una persona.
- **El dominio corporativo de los correos**: conserva que el correo es de un empleado. Lo personal (nombre y patrón) se reemplaza.
- **Buzones de rol** (soporte, pagos, cobranza…): no pertenecen a una persona.
- **Ciudad del cliente, tipo de documento y fecha de vinculación; cargo, ciudad y fecha de ingreso del empleado**: por sí solos no identifican, y son útiles para entrenar. La combinación rara se rompe generalizando barrio y ocupación.

## 3. Cuánto costó

- **Tokens: 0.** Esta versión no llama a ningún modelo de lenguaje; `/v1/health` reporta `models: []`.
- **Tiempo, en local**, corpus completo:
  - después del crecimiento (10.856 registros): unos 60 s;
  - antes del crecimiento (8.297 registros): unos 36 s.
  - La primera versión tardaba unos 516 s.
  - La PR #7 la bajó a unos 340 s, con una sola regex precompilada para las ocupaciones.
  - La PR #9 la bajó a unos 36 s: la autoverificación ya no normaliza la salida completa en cada consulta.
- **Tiempo, en producción**: la corrida 1, con la versión de la PR #7, tardó unos 8 minutos en Railway. Desde la PR #9 el pipeline es unas 10 veces más rápido en local.
- **Infraestructura**: un contenedor siempre encendido en Railway y un volumen persistente para el estado. Ningún otro servicio.

## Decisiones de diseño

- **Reglas primero.** Un modelo de lenguaje quedaría solo para el residuo ambiguo, con caché y fail-closed. En esta versión no hizo falta: las reglas pasan el validador y los tests públicos sin gastar tokens. Descartado: todo con un modelo (costo, resultados no deterministas y riesgo de reescribir el texto en vez de reemplazar).
- **Determinismo.** HMAC(secreto, persona) más el mapa persistido: la misma persona conserva su seudónimo entre fuentes, corridas y procesos, y una persona nueva recibe uno nuevo y único. Descartado: valores aleatorios o marcadores como `[NOMBRE]`, que rompen la consistencia y la utilidad.
- **Fusión solo con coincidencia exacta.** Dos registros son la misma persona solo por un identificador duro, nunca por la ciudad o el cargo. Un cliente migrado se une a uno existente solo si su cédula coincide con exactamente uno; ante cualquier ambigüedad, no se fusiona.
- **Fail-closed.** Lo que no se puede clasificar se trata como sensible, porque la fuga pesa 45 de 100 puntos. Se reemplaza, nunca se reescribe el texto.
- **El pipeline corre aparte y el estado vive en disco.** La API responde aun si una corrida se cae, y las salidas se publican de golpe, nunca a medias.

## Incidente INC-PII-01

- **Qué pasó.** A las 15:00 llegó el ticket "Kipu Pay compró Págalo", y a las 15:45:29 nuestro vigilante detectó el crecimiento de las fuentes: 10.856 registros, 2 canales nuevos y nada eliminado.
- **Qué probamos antes de gastar una corrida.** Corrimos sobre una réplica exacta del estado publicado. Aparecieron 12 clientes migrados duplicados con un id nuevo y la cédula cruda de un PQR sin cliente.
- **Resultado.** Con la corrección, las 202 personas publicadas conservan sus seudónimos, los 12 clientes migrados quedan unidos a su persona, el validador pasa y no hay fugas. Detalle en la [PR #11](https://github.com/ulisestame/frontier-hackaton-cdmx/pull/11).

## Limitaciones conocidas

- **`entities.json` se sirve sin autenticación** (`GET /v1/entities` y `GET /v1/output/entities.json`) porque el contrato del reto lo exige. Contiene las formas originales y es solo para el jurado: nunca viaja con el dataset. En un despliegue real iría detrás de autenticación o no se expondría.
- **Casos ambiguos de nombres.** A veces una mención puede ser de varias personas y el registro no lo decide. Se resuelve con desempates deterministas: el contexto del registro y del hilo, los identificadores duros y luego reglas fijas.
  - El resultado es reproducible, aunque puede no ser el que elegiría una persona.
  - Un nombre de pila suelto que nada decide puede quedar como está, porque no identifica por sí solo.
  - En el corpus real, la calificación local reporta 18 casos ambiguos.
- **Un solo volumen y una sola réplica.** Perder el volumen sin respaldo rompería la continuidad de los seudónimos. El secreto los hace deterministas, pero el mapa persistido resuelve colisiones y unicidad.
- **Siguiente paso:**
  - un modelo de lenguaje solo para el residuo ambiguo, con caché y fail-closed;
  - PostgreSQL para el registro y almacenamiento de objetos para las salidas, cuando haga falta más de una réplica;
  - formatos para el comprador generados solo desde la salida anonimizada, nunca desde `entities.json`.
