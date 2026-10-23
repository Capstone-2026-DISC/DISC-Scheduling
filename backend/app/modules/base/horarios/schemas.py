from typing import Any

from ....core.crud import modelo

_PARALELO = {"periodo_id": (int, ...), "asignatura_id": (int, ...), "nrc": (int, None), "codigo": (str, ...),
             "componente": (str, "catedra"), "estado": (str, "ok"), "cupo_estimado": (int, None),
             "sesiones_semana": (int, None), "requiere_laboratorio": (int, None), "liga_id": (int, None),
             "sesiones_seguidas": (int, 0), "docentes_alternan": (int, 0), "observacion": (str, None)}
_SESION = {"paralelo_id": (int, ...), "numero": (int, ...), "duracion_bloques": (int, 1)}
_RESTRICCION = {"departamento_id": (int, 1), "periodo_id": (int, None), "naturaleza": (str, ...), "tipo": (str, ...),
                "alcance": (dict[str, Any], {}), "parametros": (dict[str, Any], {}), "peso": (int, None),
                "vigente_desde": (str, None), "vigente_hasta": (str, None), "activa": (int, 1), "nota": (str, None)}

ParaleloIn, ParaleloPatch = modelo("ParaleloIn", _PARALELO), modelo("ParaleloPatch", _PARALELO, True)
SesionIn, SesionPatch = modelo("SesionIn", _SESION), modelo("SesionPatch", _SESION, True)
RestriccionIn, RestriccionPatch = modelo("RestriccionIn", _RESTRICCION), modelo("RestriccionPatch", _RESTRICCION, True)
Vacio = modelo("Vacio", {})
