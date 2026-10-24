"""POST /publicacion: regenera la copia pub_* de solo lectura que consumen los satélites (ver app/publicacion.py)."""

from fastapi import APIRouter, Depends

from ...core import audit
from ...core.deps import Usuario, get_directus, get_ip, requiere
from ...core.directus import Directus
from ...publicacion import publicar

router = APIRouter(
    prefix="/publicacion",
    tags=["satélites"],
    responses={
        401: {"description": "Token ausente, inválido o vencido."},
        403: {"description": "Falta `horarios.exportar`."},
    },
)


@router.post(
    "",
    summary="Regenerar la copia para los satélites",
    description="Requiere `horarios.exportar`. Copia el catálogo y el horario aprobado, sin datos personales, a las tablas `pub_*` que "
    "leen los módulos de Proyecto Integrador por Directus.",
)
def publicar_replica(
    usuario: Usuario = Depends(requiere("horarios.exportar")),
    directus: Directus = Depends(get_directus),
    ip: str | None = Depends(get_ip),
):
    cuentas = publicar(directus)
    audit.registrar(
        directus,
        usuario_id=usuario.mirror_id,
        ip=ip,
        accion="publicacion_satelites",
        entidad="pub_estado",
        detalle=cuentas,
    )
    return {"publicado": cuentas}
