"""Eventos de la aplicación en plataforma_auditoria (solo inserción), escritos por Directus con el token del servicio.

Los cambios de datos y los inicios de sesión exitosos los registra Directus en su propio registro de actividad. Aquí van
los eventos que Directus no ve: intentos fallidos, accesos denegados, lectura de datos personales, importaciones y
publicaciones. Si Directus no responde el evento se pierde sin romper la petición, que de todos modos habría fallado.
"""

import json
import logging

from .directus import Directus, DirectusCaido

log = logging.getLogger("auditoria")


def registrar(
    directus: Directus,
    *,
    usuario_id: int | None,
    ip: str | None,
    accion: str,
    resultado: str = "ok",
    entidad: str,
    entidad_id: str | int | None = None,
    detalle: dict | None = None,
    departamento_id: int | None = None,
) -> None:
    cuerpo = {
        "usuario_id": usuario_id,
        "ip": ip,
        "departamento_id": departamento_id,
        "accion": accion,
        "resultado": resultado,
        "entidad": entidad,
        "entidad_id": None if entidad_id is None else str(entidad_id),
        "despues": None if detalle is None else json.dumps(detalle, ensure_ascii=False),
    }
    try:
        r = directus.como_servicio("POST", "/items/plataforma_auditoria", json=cuerpo)
        if r.estado >= 400:
            log.error("no se pudo registrar %s: %s %s", accion, r.estado, r.mensaje)
    except DirectusCaido:
        log.error("Directus no responde: se perdió el evento %s", accion)
