"""Módulo predictivo: solo el esqueleto. Queda registrado y se activa con MODULES, pero la estimación de
inscritos aún no está implementada."""

from fastapi import APIRouter, Depends

from ...core.deps import Usuario, requiere

router = APIRouter(prefix="/proyeccion", tags=["predictivo (esqueleto)"])


@router.get(
    "/estado",
    summary="Estado del módulo predictivo",
    description="Requiere `proyeccion.ver`. El módulo es solo un esqueleto y devuelve `implementado: false`.",
    responses={
        401: {"description": "Token ausente, inválido o vencido."},
        403: {"description": "Falta `proyeccion.ver`."},
    },
)
def estado(_: Usuario = Depends(requiere("proyeccion.ver"))):
    return {
        "modulo": "predictivo",
        "implementado": False,
        "detalle": "Esqueleto: la estimación de inscritos por asignatura queda pendiente.",
    }
