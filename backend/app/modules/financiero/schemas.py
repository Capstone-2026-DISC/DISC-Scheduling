from ...core.crud import modelo

_TARIFA = {
    "categoria_id": (int, ...),
    "valor_hora": (float, ...),
    "vigente_desde": (str, ...),
    "escenario_id": (int, None),
}
_PRESUPUESTO = {
    "departamento_id": (int, 1),
    "anio": (int, ...),
    "tipo_persona": (str, ...),
    "monto_anual": (float, ...),
    "porcentaje_s1": (float, 50.0),
    "escenario_id": (int, None),
}
_ESCENARIO = {"departamento_id": (int, 1), "nombre": (str, ...), "descripcion": (str, None)}
_NOMBRAMIENTO = {
    "persona_id": (int, ...),
    "periodo_id": (int, ...),
    "categoria_id": (int, ...),
    "paralelo_id": (int, None),
    "horas_semanales": (float, ...),
    "fecha_inicio": (str, ...),
    "fecha_fin": (str, ...),
    "origen": (str, ...),
    "id_externo": (str, None),
    "reemplaza_a": (int, None),
    "estado": (str, "vigente"),
}

TarifaIn, TarifaPatch = modelo("TarifaIn", _TARIFA), modelo("TarifaPatch", _TARIFA, True)
PresupuestoIn, PresupuestoPatch = modelo("PresupuestoIn", _PRESUPUESTO), modelo("PresupuestoPatch", _PRESUPUESTO, True)
EscenarioIn, EscenarioPatch = modelo("EscenarioIn", _ESCENARIO), modelo("EscenarioPatch", _ESCENARIO, True)
NombramientoIn, NombramientoPatch = (
    modelo("NombramientoIn", _NOMBRAMIENTO),
    modelo("NombramientoPatch", _NOMBRAMIENTO, True),
)
