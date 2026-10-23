"""POST /publicacion: regenera la réplica de solo lectura que consumen los satélites (ver app/publicacion.py)."""
import os
import sqlite3

from fastapi import APIRouter, Depends

from ...core import audit
from ...core.deps import Usuario, get_conn, get_ip, requiere
from ...publicacion import publicar

router = APIRouter(prefix="/publicacion", tags=["satélites"], responses={401: {"description": "Token ausente, inválido o vencido."}, 403: {"description": "Falta `horarios.exportar`."}})


@router.post("", summary="Regenerar la réplica para los satélites", description="Requiere `horarios.exportar`. Copia el catálogo y el horario aprobado, sin datos personales, a la base que leen los módulos de Proyecto Integrador.")
def publicar_replica(usuario: Usuario = Depends(requiere("horarios.exportar")),
                     conn: sqlite3.Connection = Depends(get_conn), ip: str | None = Depends(get_ip)):
    cuentas = publicar(conn, os.environ.get("SATELITES_DB_PATH", "/satelites/satelites.db"))
    audit.registrar(conn, usuario_id=usuario.id, ip=ip, accion="publicacion_satelites", entidad="pub_estado",
                    detalle=cuentas)
    return {"publicado": cuentas}
