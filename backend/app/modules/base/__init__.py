"""Módulo base: núcleo de identidad, catálogo y horarios."""
from fastapi import APIRouter

from .catalogo.router import router as catalogo
from .horarios.router import router as horarios
from .identidad.router import auth, gestion
from .importacion import router as importacion
from .publicacion import router as publicacion

NOMBRE = "base"
router = APIRouter()
for _r in (auth, gestion, catalogo, horarios, importacion, publicacion):
    router.include_router(_r)
