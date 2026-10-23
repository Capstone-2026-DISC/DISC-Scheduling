import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response

from ....core import audit
from ....core.crud import crear_router
from ....core.deps import Usuario, get_conn, get_ip, requiere
from ....core.recurso import Repositorio, traducir_error
from . import repository as r
from . import schemas as s


def routers() -> list[APIRouter]:
    paralelos = crear_router(r.PARALELO, ruta="paralelos", etiqueta="horarios", ver="horarios.ver",
                             editar="horarios.editar", entrada=s.ParaleloIn, parcial=s.ParaleloPatch,
                             depto_payload=("periodo_id", "SELECT departamento_id FROM catalogo_periodo WHERE id = ?"))
    sesiones = crear_router(r.SESION, ruta="sesiones", etiqueta="horarios", ver="horarios.ver", editar="horarios.editar",
                            entrada=s.SesionIn, parcial=s.SesionPatch,
                            depto_payload=("paralelo_id", "SELECT p.departamento_id FROM horarios_paralelo pa "
                                           "JOIN catalogo_periodo p ON p.id = pa.periodo_id WHERE pa.id = ?"))
    restricciones = crear_router(r.RESTRICCION, ruta="restricciones", etiqueta="horarios",
                                 ver="restricciones.ver", editar="restricciones.gestionar",
                                 entrada=s.RestriccionIn, parcial=s.RestriccionPatch)
    propuestas = crear_router(r.PROPUESTA, ruta="propuestas", etiqueta="horarios", ver="horarios.ver",
                              editar="horarios.aprobar", entrada=s.Vacio, parcial=s.Vacio, permite_crear=False)

    repo = Repositorio(r.PROPUESTA)

    @propuestas.post("/{propuesta_id}/aprobar", status_code=204, summary="Aprobar una propuesta de horario",
                     description="Requiere `horarios.aprobar` en el departamento del periodo. La propuesta debe estar completa y sin violaciones de reglas duras; la aprobada anterior pasa a reemplazada. 403 si el permiso es de otro departamento.")
    def aprobar(propuesta_id: int, usuario: Usuario = Depends(requiere("horarios.aprobar")),
                conn: sqlite3.Connection = Depends(get_conn), ip: str | None = Depends(get_ip)):
        depto = repo.departamento_de(conn, propuesta_id)
        if not conn.execute("SELECT 1 FROM horarios_propuesta WHERE id = ?", (propuesta_id,)).fetchone():
            raise HTTPException(404, "No encontrada")
        try:
            r.aprobar_propuesta(conn, usuario.id, ip, propuesta_id)
        except sqlite3.Error as exc:
            error = traducir_error(exc)
            if error.status_code == 403:
                audit.registrar(conn, usuario_id=usuario.id, ip=ip, accion="acceso_denegado", resultado="denegado",
                                entidad="horarios_propuesta", entidad_id=propuesta_id, departamento_id=depto,
                                detalle={"operacion": "aprobar"})
            raise error from exc
        return Response(status_code=204)

    return [paralelos, sesiones, restricciones, propuestas]
