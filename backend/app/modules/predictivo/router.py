"""Módulo predictivo: solo el esqueleto. Queda registrado y se activa con MODULES, pero la estimación de
inscritos aún no está implementada."""
from fastapi import APIRouter, Depends

from ...core.deps import Usuario, requiere

router = APIRouter(prefix="/proyeccion", tags=["predictivo (esqueleto)"])


@router.get("/estado")
def estado(_: Usuario = Depends(requiere("proyeccion.ver"))):
    return {"modulo": "predictivo", "implementado": False,
            "detalle": "Esqueleto: la estimación de inscritos por asignatura queda pendiente."}
