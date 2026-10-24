"""Recursos de horarios. Directus decide por departamento; las filas que lo heredan del periodo se comprueban antes de
crear (core/crud.py, parámetro relacion)."""
from ....core.recurso import Recurso

PARALELO = Recurso("horarios_paralelo",
                   ("periodo_id", "asignatura_id", "nrc", "codigo", "componente", "estado", "cupo_estimado",
                    "sesiones_semana", "requiere_laboratorio", "liga_id", "sesiones_seguidas",
                    "docentes_alternan", "observacion"))
SESION = Recurso("horarios_sesion", ("paralelo_id", "numero", "duracion_bloques"))
RESTRICCION = Recurso("horarios_restriccion",
                      ("departamento_id", "periodo_id", "naturaleza", "tipo", "alcance", "parametros", "peso",
                       "vigente_desde", "vigente_hasta", "activa", "nota"),
                      json_cols=("alcance", "parametros"), autor="creada_por")
PROPUESTA = Recurso("horarios_propuesta", (), borrado_logico=False, json_cols=("metricas",))
