from fastapi import APIRouter, Depends, HTTPException, Response

from ....core import audit
from ....core.crud import crear_router
from ....core.deps import Usuario, get_directus, get_ip, requiere
from ....core.directus import Directus, exigir
from ....core.recurso import ahora
from . import repository as r
from . import schemas as s


def routers() -> list[APIRouter]:
    paralelos = crear_router(r.PARALELO, ruta="paralelos", etiqueta="horarios", ver="horarios.ver", editar="horarios.editar",
                             entrada=s.ParaleloIn, parcial=s.ParaleloPatch, relacion=("periodo_id", "catalogo_periodo"))
    sesiones = crear_router(r.SESION, ruta="sesiones", etiqueta="horarios", ver="horarios.ver", editar="horarios.editar",
                            entrada=s.SesionIn, parcial=s.SesionPatch, relacion=("paralelo_id", "horarios_paralelo"))
    restricciones = crear_router(r.RESTRICCION, ruta="restricciones", etiqueta="horarios", ver="restricciones.ver",
                                 editar="restricciones.gestionar", entrada=s.RestriccionIn, parcial=s.RestriccionPatch)
    propuestas = crear_router(r.PROPUESTA, ruta="propuestas", etiqueta="horarios", ver="horarios.ver", editar="horarios.aprobar",
                              entrada=s.Vacio, parcial=s.Vacio, permite_crear=False)

    @propuestas.post("/{propuesta_id}/aprobar", status_code=204, summary="Aprobar una propuesta de horario",
                     description="Requiere `horarios.aprobar` en el departamento del periodo. La propuesta debe estar completa y sin "
                                 "violaciones de reglas duras (lo exige la base de datos); la aprobada anterior pasa a reemplazada. "
                                 "403 si el permiso es de otro departamento.")
    def aprobar(propuesta_id: int, usuario: Usuario = Depends(requiere("horarios.aprobar")),
                directus: Directus = Depends(get_directus), ip: str | None = Depends(get_ip)):
        visible = directus.uno("horarios_propuesta", propuesta_id, token=usuario.token, ip=ip, campos="id,estado,completa")
        if visible.estado in (403, 404):
            raise HTTPException(404, "No encontrada")
        propuesta = exigir(visible).datos
        # Directus no cuenta a quien no es administrador por qué la base rechazó el cambio: se explica aquí. Las mismas reglas
        # las impone un trigger del esquema, que sigue siendo la red de seguridad.
        if propuesta["estado"] not in ("borrador", "aprobada"):
            raise HTTPException(409, "Solo un borrador puede aprobarse")
        if not propuesta["completa"]:
            raise HTTPException(409, "La propuesta no está completa: faltan sesiones por asignar")
        duras = exigir(directus.listar("horarios_hallazgo", token=usuario.token, ip=ip, campos="id", limite=1,
                                       filtro={"_and": [{"propuesta_id": {"_eq": propuesta_id}}, {"severidad": {"_eq": "dura"}}]}))
        if duras.datos:
            raise HTTPException(409, "La propuesta tiene violaciones de restricciones duras")
        resp = directus.pedir("PATCH", f"/items/horarios_propuesta/{propuesta_id}", token=usuario.token, ip=ip,
                              json={"estado": "aprobada", "aprobada_por": usuario.mirror_id})
        if resp.estado == 403:
            audit.registrar(directus, usuario_id=usuario.mirror_id, ip=ip, accion="acceso_denegado", resultado="denegado",
                            entidad="horarios_propuesta", entidad_id=propuesta_id, detalle={"operacion": "aprobar"})
        exigir(resp)
        return Response(status_code=204)

    return [paralelos, sesiones, restricciones, propuestas]
