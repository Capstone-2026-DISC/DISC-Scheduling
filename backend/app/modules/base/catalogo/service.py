"""Orquesta los routers CRUD del catálogo. Las reglas de negocio (RUT válido, un departamento no edita a otro)
las aplican los triggers del esquema y el alcance de crear_router; aquí solo se declara qué se expone."""
from fastapi import APIRouter

from ....core.crud import crear_router
from . import repository as r
from . import schemas as s


def routers() -> list[APIRouter]:
    return [
        crear_router(r.PERIODO, ruta="periodos", etiqueta="catálogo", ver="catalogo.ver", editar="catalogo.editar",
                     entrada=s.PeriodoIn, parcial=s.PeriodoPatch),
        crear_router(r.PROGRAMA, ruta="programas", etiqueta="catálogo", ver="catalogo.ver", editar="catalogo.editar",
                     entrada=s.ProgramaIn, parcial=s.ProgramaPatch),
        crear_router(r.ASIGNATURA, ruta="asignaturas", etiqueta="catálogo", ver="catalogo.ver", editar="catalogo.editar",
                     entrada=s.AsignaturaIn, parcial=s.AsignaturaPatch),
        crear_router(r.SALA, ruta="salas", etiqueta="catálogo", ver="catalogo.ver", editar="catalogo.editar",
                     entrada=s.SalaIn, parcial=s.SalaPatch),
        crear_router(r.PERSONA, ruta="personas", etiqueta="catálogo (datos personales)",
                     ver="personas.ver_datos_personales", editar="catalogo.editar",
                     entrada=s.PersonaIn, parcial=s.PersonaPatch),
        crear_router(r.DOCENTE, ruta="docentes", etiqueta="catálogo", ver="catalogo.ver", editar="catalogo.editar",
                     entrada=s.DocenteIn, parcial=s.DocentePatch),
        crear_router(r.AYUDANTE, ruta="ayudantes", etiqueta="catálogo", ver="catalogo.ver", editar="catalogo.editar",
                     entrada=s.AyudanteIn, parcial=s.AyudantePatch),
    ]
