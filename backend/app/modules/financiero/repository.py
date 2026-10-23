"""Recursos financieros: tarifas, presupuestos, escenarios y nombramientos."""
from ...core.recurso import Recurso

TARIFA = Recurso("finanzas_tarifa", ("categoria_id", "valor_hora", "vigente_desde", "escenario_id"), depto=None)
PRESUPUESTO = Recurso("finanzas_presupuesto", ("departamento_id", "anio", "tipo_persona", "monto_anual",
                                                "porcentaje_s1", "escenario_id"))
ESCENARIO = Recurso("finanzas_escenario", ("departamento_id", "nombre", "descripcion"))
NOMBRAMIENTO = Recurso("finanzas_nombramiento",
                       ("persona_id", "periodo_id", "categoria_id", "paralelo_id", "horas_semanales", "fecha_inicio",
                        "fecha_fin", "origen", "id_externo", "reemplaza_a", "estado"),
                       depto="(SELECT p.departamento_id FROM catalogo_periodo p WHERE p.id = t.periodo_id)",
                       borrado_logico=False)
