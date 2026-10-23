# Plantillas de importación

Cada plantilla corresponde a una colección de la plataforma. La primera fila es el encabezado, que no se puede cambiar, y la segunda es un ejemplo ficticio que se reemplaza por los datos. Los archivos están en `csv/` y, si hay `openpyxl`, también en `xlsx/` (una hoja `datos` y otra `reglas`).

**Los ejemplos son ficticios.** Los datos reales del departamento no se suben nunca al repositorio.

## Cómo cargarlas

1. Copie la plantilla, reemplace la fila de ejemplo con sus datos y guárdela como **CSV UTF-8** (separado por comas).
2. Revísela sin cargar nada:

   ```bash
   python3 plantillas_importacion/validar_plantilla.py catalogo_asignatura mis_asignaturas.csv
   ```

   o por la API, que además cruza las referencias contra la base:

   ```bash
   curl -X POST localhost:8000/importaciones/catalogo_asignatura -H "Authorization: Bearer $TOKEN" \
        -H 'Content-Type: text/csv' --data-binary @mis_asignaturas.csv
   ```

3. Si el informe no tiene errores, cárguela agregando `?confirmar=true`. Se carga completa o no se carga ninguna fila, y la importación queda registrada con quién, cuándo y desde qué IP.

Cada error dice la fila, la columna, qué falló y cómo corregirlo. La importación solo agrega filas nuevas: una fila cuya clave ya existe se informa como error, no se actualiza.

## Orden de carga

Las referencias se escriben con la clave natural (código, RUT, NRC o periodo) y no con el id interno, por lo que la tabla referida debe cargarse antes.

| Orden | Colección | Depende de | Permiso |
| --- | --- | --- | --- |
| 1 | `catalogo_periodo` | nada | `catalogo.importar` |
| 2 | `catalogo_programa` | nada | `catalogo.importar` |
| 3 | `catalogo_asignatura` | nada | `catalogo.importar` |
| 4 | `catalogo_sala` | nada | `catalogo.importar` |
| 5 | `catalogo_persona` | nada | `catalogo.importar` |
| 6 | `catalogo_docente` | `catalogo_persona` | `catalogo.importar` |
| 7 | `catalogo_ayudante` | `catalogo_persona` | `catalogo.importar` |
| 8 | `horarios_paralelo` | `catalogo_periodo`, `catalogo_asignatura` | `catalogo.importar` |
| 9 | `horarios_sesion` | `horarios_paralelo` | `catalogo.importar` |
| 10 | `horarios_disponibilidad_docente` | `catalogo_docente` | `catalogo.importar` |
| 11 | `finanzas_tarifa` | nada | `finanzas.editar` |
| 12 | `finanzas_presupuesto` | nada | `finanzas.editar` |
| 13 | `finanzas_nombramiento` | `catalogo_persona`, `horarios_paralelo` | `finanzas.editar` |
| 14 | `proyeccion_inscripcion_historica` | `catalogo_asignatura`, `catalogo_periodo` | `catalogo.importar` |

## `catalogo_periodo`

Periodos académicos.

Clave de la fila: `departamento`, `codigo`.

| Columna | Tipo | Obligatoria | Regla | Ejemplo |
| --- | --- | --- | --- | --- |
| `departamento` | texto | no | Código del departamento; si se deja vacío es DISC. | DISC |
| `codigo` | seis dígitos (202620) | sí | Año y semestre en seis dígitos, 10 o 20 al final. | 202710 |
| `fecha_inicio` | fecha AAAA-MM-DD | no | AAAA-MM-DD. | 2027-03-08 |
| `fecha_fin` | fecha AAAA-MM-DD | no | AAAA-MM-DD, posterior al inicio. | 2027-07-17 |
| `estado` | lista cerrada | no | Estado del periodo. Valores: planificacion, vigente, cerrado. | planificacion |

## `catalogo_programa`

Programas y carreras.

Clave de la fila: `departamento`, `codigo`.

| Columna | Tipo | Obligatoria | Regla | Ejemplo |
| --- | --- | --- | --- | --- |
| `departamento` | texto | no | Código del departamento; si se deja vacío es DISC. | DISC |
| `codigo` | texto | sí | Código corto del programa. | PRG9 |
| `nombre` | texto | no |  | Programa de prueba 9 |
| `tipo` | lista cerrada | no | Tipo de programa. Valores: pregrado, postgrado, servicio, minor. | pregrado |

## `catalogo_asignatura`

Asignaturas.

Clave de la fila: `codigo`.

| Columna | Tipo | Obligatoria | Regla | Ejemplo |
| --- | --- | --- | --- | --- |
| `departamento` | texto | no | Código del departamento; si se deja vacío es DISC. | DISC |
| `codigo` | código FAIC-00000 | no | Cuatro letras mayúsculas, guion y cinco dígitos. Vacío si Banner aún no lo asigna. | FAIC-00199 |
| `nombre` | texto | sí |  | Asignatura de prueba 99 |
| `area` | texto | no |  | Ficticia A |
| `requiere_laboratorio` | 0 o 1 | no | 1 si exige laboratorio o computador. | 0 |
| `activa` | 0 o 1 | no | 0 = no, 1 = sí. | 1 |

## `catalogo_sala`

Salas y laboratorios.

Clave de la fila: `codigo`.

| Columna | Tipo | Obligatoria | Regla | Ejemplo |
| --- | --- | --- | --- | --- |
| `departamento` | texto | no | Código del departamento; si se deja vacío es DISC. | DISC |
| `codigo` | texto | sí | Código de la sala. | ZZ-199 |
| `nombre` | texto | no |  | Sala de prueba 99 |
| `capacidad` | número entero | no | Asientos. | 40 |
| `es_laboratorio` | 0 o 1 | no | 1 si es laboratorio. | 0 |
| `administrada_por` | texto | no | Quién administra la sala. | disc |
| `activa` | 0 o 1 | no | 0 = no, 1 = sí. | 1 |

## `catalogo_persona`

Personas (datos personales: RUT y correo).

Clave de la fila: `rut`.

| Columna | Tipo | Obligatoria | Regla | Ejemplo |
| --- | --- | --- | --- | --- |
| `rut` | RUT sin puntos con guion | sí | Sin puntos, con guion y dígito verificador válido. | 59999999-K |
| `nombre` | texto | sí |  | Nombre Inventado Ejemplo |
| `email` | texto | no | Correo con arroba. | nombre@ejemplo.invalid |

## `catalogo_docente`

Docentes (la persona debe existir).

Clave de la fila: `rut`.

| Columna | Tipo | Obligatoria | Regla | Ejemplo |
| --- | --- | --- | --- | --- |
| `rut` | RUT sin puntos con guion | sí | RUT de una persona ya cargada. | 59999999-K |
| `departamento` | texto | no | Código del departamento; si se deja vacío es DISC. | DISC |
| `tipo_contrato` | lista cerrada | sí | Contrato. Valores: planta, hora. | hora |
| `activo` | 0 o 1 | no | 0 = no, 1 = sí. | 1 |

## `catalogo_ayudante`

Ayudantes (la persona debe existir).

Clave de la fila: `rut`.

| Columna | Tipo | Obligatoria | Regla | Ejemplo |
| --- | --- | --- | --- | --- |
| `rut` | RUT sin puntos con guion | sí | RUT de una persona ya cargada. | 59999998-1 |
| `departamento` | texto | no | Código del departamento; si se deja vacío es DISC. | DISC |
| `activo` | 0 o 1 | no | 0 = no, 1 = sí. | 1 |

## `horarios_paralelo`

Oferta del periodo: un paralelo por fila.

Clave de la fila: `periodo`, `asignatura`, `codigo`, `componente`.

| Columna | Tipo | Obligatoria | Regla | Ejemplo |
| --- | --- | --- | --- | --- |
| `periodo` | seis dígitos (202620) | sí | Año y semestre en seis dígitos, 10 o 20 al final. Debe existir. | 202620 |
| `departamento` | texto | no | Código del departamento; si se deja vacío es DISC. | DISC |
| `asignatura` | código FAIC-00000 | sí | Código de una asignatura ya cargada. | FAIC-00101 |
| `nrc` | número entero | no | Código de Banner; vacío en paralelos nuevos. | 59101 |
| `codigo` | texto | sí | C1, L01, T1. | C1 |
| `componente` | lista cerrada | no | Componente. Valores: catedra, laboratorio, taller, proyecto. | catedra |
| `estado` | lista cerrada | no | Estado. Valores: ok, nueva, inactiva. | ok |
| `cupo_estimado` | número entero | no | Cupo. | 35 |
| `sesiones_semana` | número entero | no | Entre 1 y 6. | 2 |
| `requiere_laboratorio` | 0 o 1 | no | Vacío hereda el de la asignatura. | 0 |
| `sesiones_seguidas` | 0 o 1 | no | 1 si las sesiones van seguidas. | 0 |
| `docentes_alternan` | 0 o 1 | no | 1 si dos docentes se alternan por módulos. | 0 |
| `observacion` | texto | no | Texto libre. | (vacío) |

## `horarios_sesion`

Sesiones semanales de un paralelo.

Clave de la fila: `periodo`, `nrc`, `numero`.

| Columna | Tipo | Obligatoria | Regla | Ejemplo |
| --- | --- | --- | --- | --- |
| `periodo` | seis dígitos (202620) | sí | Año y semestre en seis dígitos, 10 o 20 al final. Debe existir. | 202620 |
| `departamento` | texto | no | Código del departamento; si se deja vacío es DISC. | DISC |
| `nrc` | número entero | sí | NRC de un paralelo ya cargado. | 59101 |
| `numero` | número entero | sí | Número de la sesión dentro del paralelo. | 1 |
| `duracion_bloques` | número entero | no | Entre 1 y 3. | 1 |

## `horarios_disponibilidad_docente`

Bloques en que un docente no puede, prefiere o evita dictar.

Clave de la fila: `periodo`, `rut`, `dia`, `bloque`.

| Columna | Tipo | Obligatoria | Regla | Ejemplo |
| --- | --- | --- | --- | --- |
| `periodo` | seis dígitos (202620) | sí | Año y semestre en seis dígitos, 10 o 20 al final. Debe existir. | 202620 |
| `departamento` | texto | no | Código del departamento; si se deja vacío es DISC. | DISC |
| `rut` | RUT sin puntos con guion | sí | RUT de un docente ya cargado. | 59999999-K |
| `dia` | lista cerrada | sí | Día. Valores: Lu, Ma, Mi, Ju, Vi, Sa. | Lu |
| `bloque` | lista cerrada | sí | Bloque horario. Valores: A, B, C, D, E, F, G. | A |
| `tipo` | lista cerrada | sí | Tipo de marca. Valores: no_disponible, preferido, evitar. | no_disponible |

## `finanzas_tarifa`

Valor hora por categoría.

Clave de la fila: `tipo_persona`, `letra`, `vigente_desde`.

| Columna | Tipo | Obligatoria | Regla | Ejemplo |
| --- | --- | --- | --- | --- |
| `tipo_persona` | lista cerrada | sí | Tipo. Valores: profesor_hora, ayudante. | profesor_hora |
| `letra` | texto | sí | Letra de la categoría, una sola. | A |
| `valor_hora` | número decimal | sí | Pesos por hora, mayor que cero. | 12000 |
| `vigente_desde` | fecha AAAA-MM-DD | sí | AAAA-MM-DD. | 2026-03-01 |

## `finanzas_presupuesto`

Presupuesto anual por tipo de persona.

Clave de la fila: `departamento`, `anio`, `tipo_persona`.

| Columna | Tipo | Obligatoria | Regla | Ejemplo |
| --- | --- | --- | --- | --- |
| `departamento` | texto | no | Código del departamento; si se deja vacío es DISC. | DISC |
| `anio` | número entero | sí | Año. | 2027 |
| `tipo_persona` | lista cerrada | sí | Tipo. Valores: profesor_hora, ayudante. | profesor_hora |
| `monto_anual` | número decimal | sí | Pesos, no negativo. | 18000000 |
| `porcentaje_s1` | número decimal | no | Porcentaje del primer semestre, 0 a 100. | 50 |

## `finanzas_nombramiento`

Nombramientos de docentes por hora y ayudantes.

Clave de la fila: `periodo`, `rut`, `tipo_persona`, `letra`, `nrc`, `fecha_inicio`.

| Columna | Tipo | Obligatoria | Regla | Ejemplo |
| --- | --- | --- | --- | --- |
| `periodo` | seis dígitos (202620) | sí | Año y semestre en seis dígitos, 10 o 20 al final. Debe existir. | 202620 |
| `departamento` | texto | no | Código del departamento; si se deja vacío es DISC. | DISC |
| `rut` | RUT sin puntos con guion | sí | RUT de una persona ya cargada. | 59999999-K |
| `tipo_persona` | lista cerrada | sí | Tipo. Valores: profesor_hora, ayudante. | profesor_hora |
| `letra` | texto | sí | Letra de la categoría. | A |
| `nrc` | número entero | no | NRC del paralelo, si se asocia a uno. | 59101 |
| `horas_semanales` | número decimal | sí | Mayor que cero. | 4.5 |
| `fecha_inicio` | fecha AAAA-MM-DD | sí | AAAA-MM-DD. | 2026-08-03 |
| `fecha_fin` | fecha AAAA-MM-DD | sí | No anterior al inicio. | 2026-12-19 |
| `origen` | lista cerrada | sí | De dónde viene. Valores: horario, g4, manual. | manual |

## `proyeccion_inscripcion_historica`

Inscritos de periodos pasados.

Clave de la fila: `asignatura`, `periodo`, `fuente`.

| Columna | Tipo | Obligatoria | Regla | Ejemplo |
| --- | --- | --- | --- | --- |
| `asignatura` | código FAIC-00000 | sí | Código de una asignatura ya cargada. | FAIC-00101 |
| `periodo` | seis dígitos (202620) | sí | Año y semestre en seis dígitos, 10 o 20 al final. Debe existir. | 202620 |
| `departamento` | texto | no | Código del departamento; si se deja vacío es DISC. | DISC |
| `fuente` | lista cerrada | sí | Origen del dato. Valores: planilla, apa, argos. | planilla |
| `inscritos` | número entero | sí | Cero o más. | 30 |
