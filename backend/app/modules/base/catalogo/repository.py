"""Recursos del catálogo (datos maestros) y su alcance por departamento."""
from ....core.recurso import Recurso

PERIODO = Recurso("catalogo_periodo", ("departamento_id", "codigo", "fecha_inicio", "fecha_fin", "estado"),
                  borrado_logico=False)
PROGRAMA = Recurso("catalogo_programa", ("departamento_id", "codigo", "nombre", "tipo"))
ASIGNATURA = Recurso("catalogo_asignatura", ("departamento_id", "codigo", "nombre", "area",
                                              "requiere_laboratorio", "activa"))
SALA = Recurso("catalogo_sala", ("departamento_id", "codigo", "nombre", "capacidad", "es_laboratorio",
                                  "administrada_por", "activa"))
# Los datos personales (RUT, correo) solo los ve quien tiene personas.ver_datos_personales.
PERSONA = Recurso("catalogo_persona", ("rut", "nombre", "email"), depto=None)
DOCENTE = Recurso("catalogo_docente", ("persona_id", "departamento_id", "tipo_contrato", "activo"),
                  pk="persona_id", orden="t.persona_id")
AYUDANTE = Recurso("catalogo_ayudante", ("persona_id", "departamento_id", "activo"),
                   pk="persona_id", orden="t.persona_id")
