from ....core.crud import modelo

_PERIODO = {
    "departamento_id": (int, 1),
    "codigo": (str, ...),
    "fecha_inicio": (str, None),
    "fecha_fin": (str, None),
    "estado": (str, "planificacion"),
}
_PROGRAMA = {"departamento_id": (int, 1), "codigo": (str, ...), "nombre": (str, None), "tipo": (str, None)}
_ASIGNATURA = {
    "departamento_id": (int, 1),
    "codigo": (str, None),
    "nombre": (str, ...),
    "area": (str, None),
    "requiere_laboratorio": (int, 0),
    "activa": (int, 1),
}
_SALA = {
    "departamento_id": (int, 1),
    "codigo": (str, ...),
    "nombre": (str, None),
    "capacidad": (int, None),
    "es_laboratorio": (int, 0),
    "administrada_por": (str, "disc"),
    "activa": (int, 1),
}
_PERSONA = {"rut": (str, ...), "nombre": (str, ...), "email": (str, None)}  # el RUT y el correo se cifran al guardar
_DOCENTE = {"persona_id": (int, ...), "departamento_id": (int, 1), "tipo_contrato": (str, ...), "activo": (int, 1)}
_AYUDANTE = {"persona_id": (int, ...), "departamento_id": (int, 1), "activo": (int, 1)}

PeriodoIn, PeriodoPatch = modelo("PeriodoIn", _PERIODO), modelo("PeriodoPatch", _PERIODO, True)
ProgramaIn, ProgramaPatch = modelo("ProgramaIn", _PROGRAMA), modelo("ProgramaPatch", _PROGRAMA, True)
AsignaturaIn, AsignaturaPatch = modelo("AsignaturaIn", _ASIGNATURA), modelo("AsignaturaPatch", _ASIGNATURA, True)
SalaIn, SalaPatch = modelo("SalaIn", _SALA), modelo("SalaPatch", _SALA, True)
PersonaIn, PersonaPatch = modelo("PersonaIn", _PERSONA), modelo("PersonaPatch", _PERSONA, True)
DocenteIn, DocentePatch = modelo("DocenteIn", _DOCENTE), modelo("DocentePatch", _DOCENTE, True)
AyudanteIn, AyudantePatch = modelo("AyudanteIn", _AYUDANTE), modelo("AyudantePatch", _AYUDANTE, True)
