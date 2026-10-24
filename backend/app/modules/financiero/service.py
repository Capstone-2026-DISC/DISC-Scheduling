from fastapi import APIRouter

from ...core.crud import crear_router
from . import repository as r
from . import schemas as s


def routers() -> list[APIRouter]:
    comunes = dict(etiqueta="finanzas", ver="finanzas.ver", editar="finanzas.editar")
    return [
        crear_router(r.TARIFA, ruta="tarifas", entrada=s.TarifaIn, parcial=s.TarifaPatch, **comunes),
        crear_router(
            r.PRESUPUESTO, ruta="presupuestos", entrada=s.PresupuestoIn, parcial=s.PresupuestoPatch, **comunes
        ),
        crear_router(r.ESCENARIO, ruta="escenarios", entrada=s.EscenarioIn, parcial=s.EscenarioPatch, **comunes),
        crear_router(
            r.NOMBRAMIENTO,
            ruta="nombramientos",
            entrada=s.NombramientoIn,
            parcial=s.NombramientoPatch,
            relacion=("periodo_id", "catalogo_periodo"),
            **comunes,
        ),
    ]
