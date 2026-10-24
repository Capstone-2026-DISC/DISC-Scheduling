"""Fábrica de routers CRUD sobre un Recurso. Cada llamada va a Directus con la sesión de la persona, que aplica los
permisos por rol y departamento; aquí se traducen los errores y se registran los accesos denegados en la auditoría."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, create_model

from . import audit
from .deps import Usuario, get_directus, get_ip, requiere
from .directus import Directus
from .openapi import ERRORES_ESCRITURA, RESPUESTAS
from .recurso import Recurso, Repositorio


def modelo(nombre: str, campos: dict[str, tuple[Any, Any]], opcionales: bool = False) -> type[BaseModel]:
    """Modelo pydantic estricto. campos: nombre -> (tipo, valor por defecto o ... si es obligatorio)."""
    defs = {k: ((t | None, None) if opcionales else (t, d)) for k, (t, d) in campos.items()}
    return create_model(nombre, __config__=ConfigDict(extra="forbid"), **defs)


def crear_router(
    recurso: Recurso,
    *,
    ruta: str,
    etiqueta: str,
    ver: str,
    editar: str,
    entrada: type[BaseModel],
    parcial: type[BaseModel],
    relacion: tuple[str, str] | None = None,
    permite_crear: bool = True,
) -> APIRouter:
    """relacion = (campo del cuerpo, colección a la que apunta). Directus no comprueba que se pueda ver la fila a la que
    apunta una clave foránea, así que antes de crear se lee con la sesión de la persona: si no la ve, no es de su
    departamento."""
    repo = Repositorio(recurso)
    router = APIRouter(prefix=f"/{ruta}", tags=[etiqueta], responses={**RESPUESTAS, **ERRORES_ESCRITURA})

    def denegar_fn(directus, usuario, ip, clave=None):
        def registrar(operacion: str):
            audit.registrar(
                directus,
                usuario_id=usuario.mirror_id,
                ip=ip,
                accion="acceso_denegado",
                resultado="denegado",
                entidad=recurso.tabla,
                entidad_id=clave,
                detalle={"operacion": operacion, "permiso": editar},
            )

        return registrar

    @router.get(
        "",
        summary=f"Listar {ruta}",
        description=f"Requiere `{ver}`. Directus entrega solo las filas de los departamentos "
        f"donde el usuario tiene acceso{', sin las eliminadas' if recurso.borrado_logico else ''}. "
        "Paginado con `limite` (hasta 500) y `desplazamiento`.",
    )
    def listar(
        limite: int = Query(100, ge=1, le=500),
        desplazamiento: int = Query(0, ge=0),
        usuario: Usuario = Depends(requiere(ver)),
        directus: Directus = Depends(get_directus),
        ip: str | None = Depends(get_ip),
    ):
        return repo.listar(directus, usuario, ip, limite, desplazamiento)

    @router.get(
        "/{clave}",
        summary=f"Ver un registro de {ruta}",
        description=f"Requiere `{ver}`. 404 si no existe, fue eliminado o es de un departamento sin acceso.",
    )
    def leer(
        clave: int,
        usuario: Usuario = Depends(requiere(ver)),
        directus: Directus = Depends(get_directus),
        ip: str | None = Depends(get_ip),
    ):
        return repo.obtener(directus, usuario, ip, clave)

    if permite_crear:

        @router.post(
            "",
            status_code=201,
            summary=f"Crear un registro en {ruta}",
            description=f"Requiere `{editar}` en el departamento del registro (el del usuario si no se indica otro). "
            "Devuelve el `id`. Solo se envían los campos que se quieren fijar; el resto toma el valor "
            "por defecto de la base.",
        )
        def crear(
            datos: entrada,
            usuario: Usuario = Depends(requiere(editar)),  # type: ignore[valid-type]
            directus: Directus = Depends(get_directus),
            ip: str | None = Depends(get_ip),
        ):
            cuerpo = datos.model_dump(exclude_unset=True)
            if relacion and cuerpo.get(relacion[0]) is not None:
                visible = directus.uno(relacion[1], cuerpo[relacion[0]], token=usuario.token, ip=ip, campos="id")
                if visible.estado != 200:
                    denegar_fn(directus, usuario, ip)("crear")
                    raise HTTPException(403, "Sin permiso en ese departamento")
            try:
                return {"id": repo.crear(directus, usuario, ip, cuerpo)}
            except HTTPException as exc:
                if exc.status_code == 403:
                    denegar_fn(directus, usuario, ip)("crear")
                raise

    @router.patch(
        "/{clave}",
        status_code=204,
        summary=f"Modificar un registro de {ruta}",
        description=f"Requiere `{editar}` en el departamento del registro. Cambia solo los campos enviados. "
        "Los intentos sin permiso quedan en la auditoría.",
    )
    def actualizar(
        clave: int,
        datos: parcial,
        usuario: Usuario = Depends(requiere(editar)),  # type: ignore[valid-type]
        directus: Directus = Depends(get_directus),
        ip: str | None = Depends(get_ip),
    ):
        repo.actualizar(
            directus, usuario, ip, clave, datos.model_dump(exclude_unset=True), denegar_fn(directus, usuario, ip, clave)
        )
        return Response(status_code=204)

    if recurso.borrado_logico:

        @router.delete(
            "/{clave}",
            status_code=204,
            summary=f"Eliminar un registro de {ruta}",
            description=f"Requiere `{editar}`. **Borrado lógico**: la fila se marca como eliminada y deja de aparecer; "
            "no se borra de la base.",
        )
        def eliminar(
            clave: int,
            usuario: Usuario = Depends(requiere(editar)),
            directus: Directus = Depends(get_directus),
            ip: str | None = Depends(get_ip),
        ):
            repo.eliminar(directus, usuario, ip, clave, denegar_fn(directus, usuario, ip, clave))
            return Response(status_code=204)

    return router
