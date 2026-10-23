import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ....core import audit, security
from ....core.openapi import ERRORES_ESCRITURA, RESPUESTAS
from ....core.config import Settings
from ....core.deps import Usuario, get_conn, get_ip, get_settings, requiere, usuario_actual
from ....core.recurso import traducir_error
from . import repository as repo
from . import service
from .schemas import (CambioClaveIn, LoginIn, PerfilOut, RefreshIn, RolAsignacionIn, TokenOut, UsuarioIn)

auth = APIRouter(prefix="/auth", tags=["autenticación"])
gestion = APIRouter(tags=["usuarios y roles"], responses={**RESPUESTAS, **ERRORES_ESCRITURA})


@auth.post("/login", response_model=TokenOut, summary="Iniciar sesión",
           description="Entrega un **token de acceso** (JWT, 10 minutos) y un **refresh token** (7 días, de un solo uso). "
                       "Tras 5 intentos fallidos la cuenta se bloquea 15 minutos, y hay un tope de 10 intentos por minuto "
                       "por IP. Cada intento, exitoso o no, queda en la auditoría con la IP.",
           responses={401: {"description": "Correo o clave incorrectos (el mensaje no distingue cuál)."},
                      422: {"description": "El cuerpo no tiene `email` y `clave`."},
                      423: {"description": "Cuenta bloqueada temporalmente por intentos fallidos; reintente pasado el bloqueo."},
                      429: {"description": "Demasiados intentos desde esa IP; espere un minuto."}})
def login(datos: LoginIn, request: Request, conn: sqlite3.Connection = Depends(get_conn),
          settings: Settings = Depends(get_settings), ip: str | None = Depends(get_ip)):
    if not request.app.state.limite_login.permitir(ip or "?"):
        raise HTTPException(429, "Demasiados intentos; espere un minuto")
    return service.login(conn, settings, datos.email, datos.clave, ip)


@auth.post("/refresh", response_model=TokenOut, summary="Renovar la sesión",
           description="Cambia un refresh token por un par nuevo de tokens. **El refresh token es de un solo uso**: guarde "
                       "siempre el nuevo. Si se presenta uno ya usado se interpreta como robo y se cierra toda la sesión.",
           responses={401: {"description": "Refresh token desconocido, vencido, ya usado o de una sesión cerrada."}})
def refresh(datos: RefreshIn, conn: sqlite3.Connection = Depends(get_conn),
            settings: Settings = Depends(get_settings), ip: str | None = Depends(get_ip)):
    return service.refrescar(conn, settings, datos.refresh_token, ip)


@auth.post("/logout", status_code=204, summary="Cerrar sesión",
           description="Revoca la sesión actual. El token de acceso deja de valer de inmediato, no al vencer.",
           responses={401: {"description": "Token ausente, inválido o ya revocado."}})
def logout(usuario: Usuario = Depends(usuario_actual), conn: sqlite3.Connection = Depends(get_conn),
           ip: str | None = Depends(get_ip)):
    service.cerrar_sesion(conn, usuario.id, usuario.familia, ip)
    return Response(status_code=204)


@auth.post("/cambiar-clave", status_code=204, summary="Cambiar la clave",
           description="Exige la clave actual. La nueva debe tener al menos 12 caracteres, mezclar letras con números o "
                       "símbolos y no contener el correo. Cierra todas las sesiones del usuario, incluida esta.",
           responses={401: {"description": "Token ausente o inválido."},
                      403: {"description": "La clave actual no coincide."},
                      422: {"description": "La clave nueva no cumple la política; `detail` dice por qué."}})
def cambiar_clave(datos: CambioClaveIn, usuario: Usuario = Depends(usuario_actual),
                  conn: sqlite3.Connection = Depends(get_conn), settings: Settings = Depends(get_settings),
                  ip: str | None = Depends(get_ip)):
    service.cambiar_clave(conn, settings, usuario.id, datos.actual, datos.nueva, ip)
    return Response(status_code=204)


@auth.get("/yo", response_model=PerfilOut, summary="Perfil y permisos del usuario",
          description="Devuelve quién es el usuario y sus permisos. Cada permiso trae la lista de departamentos donde vale; "
                      "`null` en la lista significa todos los departamentos. Úselo para decidir qué mostrar en el frontend.",
          responses={401: {"description": "Token ausente, inválido o vencido."}})
def yo(usuario: Usuario = Depends(usuario_actual)):
    return PerfilOut(id=usuario.id, email=usuario.email, nombre=usuario.nombre,
                     permisos={p: sorted(d for d in deptos if d is not None) + ([None] if None in deptos else [])
                               for p, deptos in sorted(usuario.permisos.items())})


def _ejecutar(accion, *args):
    try:
        return accion(*args)
    except sqlite3.Error as exc:
        raise traducir_error(exc) from exc


@gestion.get("/usuarios", summary="Listar usuarios", description="Requiere `usuarios.gestionar`. Incluye los roles vigentes de cada usuario.")
def listar_usuarios(_: Usuario = Depends(requiere("usuarios.gestionar")), conn: sqlite3.Connection = Depends(get_conn)):
    return repo.listar_usuarios(conn)


@gestion.post("/usuarios", status_code=201, summary="Crear un usuario", description="Requiere `usuarios.gestionar`. La clave debe cumplir la política (12 o más caracteres, letras con números o símbolos).")
def crear_usuario(datos: UsuarioIn, usuario: Usuario = Depends(requiere("usuarios.gestionar")),
                  conn: sqlite3.Connection = Depends(get_conn), settings: Settings = Depends(get_settings),
                  ip: str | None = Depends(get_ip)):
    email = datos.email.strip().lower()
    problema = security.clave_valida(datos.clave, email, settings.clave_minima)
    if problema:
        raise HTTPException(422, problema)
    if repo.usuario_por_email(conn, email):
        raise HTTPException(409, "Ya existe un usuario con ese correo")
    nuevo = _ejecutar(repo.crear_usuario, conn, usuario.id, ip, email, datos.nombre, security.hashear_clave(datos.clave))
    return {"id": nuevo, "email": email}


@gestion.delete("/usuarios/{uid}", status_code=204, summary="Eliminar un usuario", description="Requiere `usuarios.gestionar`. Borrado lógico: el usuario deja de poder entrar y sus sesiones se cierran. No se puede eliminar la propia cuenta.")
def eliminar_usuario(uid: int, usuario: Usuario = Depends(requiere("usuarios.gestionar")),
                     conn: sqlite3.Connection = Depends(get_conn), ip: str | None = Depends(get_ip)):
    if uid == usuario.id:
        raise HTTPException(409, "No puede eliminar su propia cuenta")
    if not _ejecutar(repo.eliminar_usuario, conn, usuario.id, ip, uid):
        raise HTTPException(404, "No encontrado")
    return Response(status_code=204)


@gestion.get("/roles", summary="Listar roles y sus permisos", description="Requiere `usuarios.gestionar`.")
def listar_roles(_: Usuario = Depends(requiere("usuarios.gestionar")), conn: sqlite3.Connection = Depends(get_conn)):
    return repo.listar_roles(conn)


@gestion.post("/usuarios/{uid}/roles", status_code=201, summary="Asignar un rol", description="Requiere `usuarios.gestionar` en ese departamento. `departamento_id` nulo = todos los departamentos. Nadie puede modificar sus propios roles. Queda auditado.")
def asignar_rol(uid: int, datos: RolAsignacionIn, usuario: Usuario = Depends(requiere("usuarios.gestionar")),
                conn: sqlite3.Connection = Depends(get_conn), ip: str | None = Depends(get_ip)):
    if not repo.usuario_por_id(conn, uid):
        raise HTTPException(404, "No encontrado")
    try:
        nuevo = repo.asignar_rol(conn, usuario.id, ip, uid, datos.rol, datos.departamento_id)
    except sqlite3.Error as exc:
        error = traducir_error(exc)
        if error.status_code == 403:
            audit.registrar(conn, usuario_id=usuario.id, ip=ip, accion="acceso_denegado", resultado="denegado",
                            entidad="identidad_usuario_rol", entidad_id=uid,
                            detalle={"rol": datos.rol, "departamento_id": datos.departamento_id})
        raise error from exc
    audit.registrar(conn, usuario_id=usuario.id, ip=ip, accion="permisos_cambiados", entidad="identidad_usuario",
                    entidad_id=uid, departamento_id=datos.departamento_id,
                    detalle={"operacion": "asignar_rol", "rol": datos.rol, "asignacion_id": nuevo})
    return {"id": nuevo}


@gestion.delete("/usuarios/{uid}/roles/{asignacion_id}", status_code=204, summary="Revocar un rol", description="Requiere `usuarios.gestionar`. Marca la asignación como revocada. Queda auditado.")
def revocar_rol(uid: int, asignacion_id: int, usuario: Usuario = Depends(requiere("usuarios.gestionar")),
                conn: sqlite3.Connection = Depends(get_conn), ip: str | None = Depends(get_ip)):
    if not _ejecutar(repo.revocar_rol, conn, usuario.id, ip, asignacion_id):
        raise HTTPException(404, "No encontrado")
    audit.registrar(conn, usuario_id=usuario.id, ip=ip, accion="permisos_cambiados", entidad="identidad_usuario",
                    entidad_id=uid, detalle={"operacion": "revocar_rol", "asignacion_id": asignacion_id})
    return Response(status_code=204)


@gestion.put("/roles/{rol}/permisos/{permiso}", status_code=204, summary="Dar un permiso a un rol", description="Requiere `usuarios.gestionar`. Surte efecto de inmediato. Queda auditado.")
def dar_permiso(rol: str, permiso: str, usuario: Usuario = Depends(requiere("usuarios.gestionar")),
                conn: sqlite3.Connection = Depends(get_conn), ip: str | None = Depends(get_ip)):
    _ejecutar(repo.dar_permiso, conn, usuario.id, ip, rol, permiso)
    audit.registrar(conn, usuario_id=usuario.id, ip=ip, accion="permisos_cambiados", entidad="identidad_rol",
                    entidad_id=rol, detalle={"operacion": "dar_permiso", "permiso": permiso})
    return Response(status_code=204)


@gestion.delete("/roles/{rol}/permisos/{permiso}", status_code=204, summary="Quitar un permiso a un rol", description="Requiere `usuarios.gestionar`. No se pueden quitar permisos al rol de sistema `administrador`. Queda auditado.")
def quitar_permiso(rol: str, permiso: str, usuario: Usuario = Depends(requiere("usuarios.gestionar")),
                   conn: sqlite3.Connection = Depends(get_conn), ip: str | None = Depends(get_ip)):
    if rol == "administrador":
        raise HTTPException(409, "No se quitan permisos al rol de sistema")
    if not _ejecutar(repo.quitar_permiso, conn, usuario.id, ip, rol, permiso):
        raise HTTPException(404, "No encontrado")
    audit.registrar(conn, usuario_id=usuario.id, ip=ip, accion="permisos_cambiados", entidad="identidad_rol",
                    entidad_id=rol, detalle={"operacion": "quitar_permiso", "permiso": permiso})
    return Response(status_code=204)
