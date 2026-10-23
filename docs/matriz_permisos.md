# Matriz de roles y permisos

Se genera desde `identidad_rol_permiso` y el esquema con `backend/app/directus_matriz.py`; no se edita a mano.
Directus solo **lee** el núcleo; toda escritura pasa por la API, donde los triggers del esquema comprueban el permiso
y el departamento y la auditoría registra quién. La tabla dice qué lee cada rol en Directus y qué rutas de la API cubren sus permisos de escritura.

| Rol | Alcance de lectura | Colecciones de lectura en Directus | Escritura por la API |
| --- | --- | --- | --- |
| `administrador` | todos los departamentos | 48 | /usuarios y /roles; POST /propuestas/{id}/aprobar; POST/PATCH/DELETE /paralelos /sesiones; POST/PATCH/DELETE /periodos /programas /asignaturas /salas /personas /docentes /ayudantes; POST/PATCH/DELETE /restricciones; POST/PATCH/DELETE /tarifas /presupuestos /escenarios /nombramientos; envío de horarios por correo; exportación del horario; gestión de departamentos; importación de la planilla (módulo de importación); worker de corridas de FET |
| `consulta` | solo su departamento | 25 | ninguna |
| `encargado_docente` | solo su departamento | 40 | POST /propuestas/{id}/aprobar; POST/PATCH/DELETE /paralelos /sesiones; POST/PATCH/DELETE /periodos /programas /asignaturas /salas /personas /docentes /ayudantes; POST/PATCH/DELETE /restricciones; POST/PATCH/DELETE /tarifas /presupuestos /escenarios /nombramientos; envío de horarios por correo; exportación del horario; importación de la planilla (módulo de importación); worker de corridas de FET |

## Colecciones de lectura por rol

### `administrador`

`catalogo_asignatura`, `catalogo_ayudante`, `catalogo_bloque`, `catalogo_dia`, `catalogo_docente`, `catalogo_periodo`, `catalogo_persona`, `catalogo_plan_nivel`, `catalogo_programa`, `catalogo_sala`, `finanzas_calculo`, `finanzas_calculo_detalle`, `finanzas_categoria`, `finanzas_categoria_persona`, `finanzas_escenario`, `finanzas_nombramiento`, `finanzas_presupuesto`, `finanzas_tarifa`, `horarios_asignacion`, `horarios_bloqueo_sala`, `horarios_corrida`, `horarios_corrida_actividad`, `horarios_disponibilidad_docente`, `horarios_envio_horario`, `horarios_hallazgo`, `horarios_liga`, `horarios_paralelo`, `horarios_paralelo_docente`, `horarios_paralelo_grupo`, `horarios_perfil`, `horarios_propuesta`, `horarios_reserva_nivel`, `horarios_restriccion`, `horarios_sala_externa_autorizada`, `horarios_sesion`, `identidad_departamento`, `identidad_permiso`, `identidad_rol`, `identidad_rol_permiso`, `identidad_usuario`, `identidad_usuario_rol`, `plataforma_auditoria`, `plataforma_fila_importada`, `plataforma_importacion`, `plataforma_modulo`, `proyeccion_estimacion`, `proyeccion_estimacion_externa`, `proyeccion_inscripcion_historica`

### `consulta`

`catalogo_asignatura`, `catalogo_ayudante`, `catalogo_bloque`, `catalogo_dia`, `catalogo_docente`, `catalogo_periodo`, `catalogo_plan_nivel`, `catalogo_programa`, `catalogo_sala`, `horarios_asignacion`, `horarios_bloqueo_sala`, `horarios_corrida`, `horarios_corrida_actividad`, `horarios_disponibilidad_docente`, `horarios_hallazgo`, `horarios_liga`, `horarios_paralelo`, `horarios_paralelo_docente`, `horarios_paralelo_grupo`, `horarios_perfil`, `horarios_propuesta`, `horarios_reserva_nivel`, `horarios_restriccion`, `horarios_sala_externa_autorizada`, `horarios_sesion`

### `encargado_docente`

`catalogo_asignatura`, `catalogo_ayudante`, `catalogo_bloque`, `catalogo_dia`, `catalogo_docente`, `catalogo_periodo`, `catalogo_persona`, `catalogo_plan_nivel`, `catalogo_programa`, `catalogo_sala`, `finanzas_calculo`, `finanzas_calculo_detalle`, `finanzas_categoria`, `finanzas_categoria_persona`, `finanzas_escenario`, `finanzas_nombramiento`, `finanzas_presupuesto`, `finanzas_tarifa`, `horarios_asignacion`, `horarios_bloqueo_sala`, `horarios_corrida`, `horarios_corrida_actividad`, `horarios_disponibilidad_docente`, `horarios_envio_horario`, `horarios_hallazgo`, `horarios_liga`, `horarios_paralelo`, `horarios_paralelo_docente`, `horarios_paralelo_grupo`, `horarios_perfil`, `horarios_propuesta`, `horarios_reserva_nivel`, `horarios_restriccion`, `horarios_sala_externa_autorizada`, `horarios_sesion`, `plataforma_fila_importada`, `plataforma_importacion`, `proyeccion_estimacion`, `proyeccion_estimacion_externa`, `proyeccion_inscripcion_historica`

## Nunca expuestas por Directus

`identidad_sesion` y `plataforma_contexto` no se leen por ningún rol. De `identidad_usuario` no salen `hash_clave`, `intentos_fallidos` ni `bloqueado_hasta`.
