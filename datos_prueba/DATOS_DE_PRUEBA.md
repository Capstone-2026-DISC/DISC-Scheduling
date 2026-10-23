# Datos de prueba

**Todos los datos de esta carpeta son ficticios.** Ninguna persona, RUT, correo, curso, sala ni monto corresponde a la realidad. Existen para probar la plataforma, mostrarla y escribir pruebas sin tocar datos personales, que la Ley 19.628 y la nueva Ley 21.719 restringen. Los datos reales del departamento nunca entran a este repositorio.

## Qué hay

| Tabla | Filas | Contenido ficticio |
| --- | --- | --- |
| `catalogo_periodo` | 3 | 202520 y 202610 cerrados, 202620 vigente |
| `catalogo_programa` | 3 | Programas de prueba |
| `catalogo_asignatura` | 12 | Asignaturas de prueba con códigos `FAIC-00101` a `FAIC-00112` |
| `catalogo_plan_nivel` | 18 | Reparto de asignaturas en programas y niveles |
| `catalogo_sala` | 10 | 4 laboratorios del esquema más 6 salas de prueba |
| `catalogo_persona` | 20 | Nombres inventados, RUT ficticio y correo `@ejemplo.invalid` |
| `catalogo_docente` | 14 | 6 de planta y 8 por hora |
| `catalogo_ayudante` | 6 | Ayudantes |
| `horarios_paralelo` | 15 | Oferta del periodo 202620 con NRC ficticios |
| `horarios_sesion` | 27 | Sesiones semanales de cada paralelo |
| `horarios_paralelo_docente` | 15 | Docente asignado a cada paralelo |
| `horarios_disponibilidad_docente` | 48 | Bloques no disponibles de los docentes por hora |
| `finanzas_tarifa` | 7 | Valor hora inventado por categoría |
| `finanzas_presupuesto` | 2 | Presupuesto anual inventado |
| `finanzas_nombramiento` | 14 | Nombramientos de docentes por hora y ayudantes |
| `proyeccion_inscripcion_historica` | 24 | Inscritos inventados de los dos periodos cerrados |

## Cómo se generó

`generar_datos.py` usa solo la biblioteca estándar y una semilla fija (`20262026`), así que cada ejecución produce los mismos archivos. Los nombres se arman con sílabas al azar para que no coincidan con personas reales. El script crea una base SQLite desde `db/esquema_plataforma.sql`, carga los datos con los triggers del esquema activos y exporta cada tabla a `csv/`.

```bash
python3 datos_prueba/generar_datos.py                    # crea salida/plataforma_prueba.db y csv/
python3 datos_prueba/generar_datos.py --semilla 7        # otra variante, igual de ficticia
python3 -m pytest datos_prueba/test_datos.py -q
```

## RUT ficticios

Cada RUT tiene un dígito verificador válido, porque el esquema lo exige con un trigger. El cuerpo se elige entre **59.000.000 y 59.999.999**. Los RUT de personas naturales chilenas están por debajo de 50.000.000, así que este rango no debería corresponder a una persona. No se garantiza que no coincida con el RUT de alguna empresa u organización real. Las pruebas comprueban que ningún RUT generado salga de ese rango.

## Cuidados

- No copiar a esta carpeta nada de planillas del cliente, ni siquiera anonimizado a mano.
- No usar estos datos como si fueran reales en informes o demostraciones, y mencionar que son sintéticos.
- Las pruebas fallan si aparece un correo fuera de `@ejemplo.invalid` o un RUT fuera del rango.
