"""POST /publicacion: regenera la réplica de solo lectura que consumen los satélites (ver app/publicacion.py)."""
import os
import sqlite3

from fastapi import APIRouter, Depends

from ...core import audit
from ...core.deps import Usuario, get_conn, get_ip, requiere
from ...publicacion import publicar

router = APIRouter(prefix="/publicacion", tags=["satélites"])


@router.post("")
def publicar_replica(usuario: Usuario = Depends(requiere("horarios.exportar")),
                     conn: sqlite3.Connection = Depends(get_conn), ip: str | None = Depends(get_ip)):
    cuentas = publicar(conn, os.environ.get("SATELITES_DB_PATH", "/satelites/satelites.db"))
    audit.registrar(conn, usuario_id=usuario.id, ip=ip, accion="publicacion_satelites", entidad="pub_estado",
                    detalle=cuentas)
    return {"publicado": cuentas}
