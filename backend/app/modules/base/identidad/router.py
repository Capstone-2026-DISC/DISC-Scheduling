from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ....core import audit, security
from ....core.config import Settings
from ....core.deps import Usuario, get_directus, get_ip, get_settings, requiere, usuario_actual
from ....core.directus import Directus, exigir
from ....core.openapi import ERRORES_ESCRITURA, RESPUESTAS
from . import repository as repo
from . import service
from .schemas import (CambioClaveIn, LoginIn, LogoutIn, PerfilOut, RefreshIn, RolAsignacionIn, TokenOut, UsuarioIn)

auth = APIRouter(prefix="/auth", tags=["autenticación"])
gestion = APIRouter(tags=["usuarios y roles"], responses={**RESPUESTAS, **ERRORES_ESCRITURA})


@auth.post("/login", response_model=TokenOut, summary="Iniciar sesión",
           description="Entrega un **token de acceso** (10 minutos) y un **refresh token** (7 días, de un solo uso). Los emite "
                       "Directus. Tras 5 intentos fallidos la cuenta se bloquea 15 minutos, y hay un tope de 10 intentos por "
                       "minuto por IP. Cada intento fallido queda en la auditoría con la IP; los exitosos, en el registro de "
                       "actividad de Directus y en la auditoría.",
           responses={401: {"description": "Correo o clave incorrectos (el mensaje no distingue cuál)."},
                      403: {"description": "Las credenciales son válidas pero la cuenta no tiene un rol de la plataforma."},
                      422: {"description": "El cuerpo no tiene `email` y `clave`."},
                      423: {"description": "Cuenta bloqueada temporalmente por intentos fallidos; reintente pasado el bloqueo."},
                      429: {"description": "Demasiados intentos desde esa IP; espere un minuto."}})
def login(datos: LoginIn, request: Request, directus: Directus = Depends(get_directus),
          settings: Settings = Depends(get_settings), ip: str | None = Depends(get_ip)):
    if not request.app.state.limite_login.permitir(ip or "?"):
        raise HTTPException(429, "Demasiados intentos; espere un minuto")
    return service.login(directus, settings, datos.email, datos.clave, ip)


@auth.post("/refresh", response_model=TokenOut, summary="Renovar la sesión",
           description="Cambia un refresh token por un par nuevo de tokens. **El refresh token es de un solo uso**: guarde "
                       "siempre el nuevo. Uno ya usado se rechaza con 401.",
           responses={401: {"description": "Refresh token desconocido, vencido, ya usado o de una sesión cerrada."}})
def refresh(datos: RefreshIn, directus: Directus = Depends(get_directus), ip: str | None = Depends(get_ip)):
    return service.refrescar(directus, datos.refresh_token, ip)


@auth.post("/logout", status_code=204, summary="Cerrar sesión",
           description="Cierra la sesión. Envíe el `refresh_token` para que Directus lo invalide; el token de acceso actual deja "
                       "de valer de inmediato en esta API aunque Directus lo mantendría hasta que venza.",
           responses={401: {"description": "Token ausente, inválido o ya revocado."}})
def logout(request: Request, datos: LogoutIn | None = None, usuario: Usuario = Depends(usuario_actual),
           directus: Directus = Depends(get_directus), ip: str | None = Depends(get_ip)):
    service.cerrar_sesion(directus, request.app.state, usuario, datos.refresh_token if datos else None, ip)
    return Response(status_code=204)


@auth.post("/cambiar-clave", status_code=204, summary="Cambiar la clave",
           description="Exige la clave actual. La nueva debe tener al menos 12 caracteres, mezclar letras con números o "
                       "símbolos y no contener el correo. Directus cierra todas las sesiones renovables del usuario y esta API "
                       "rechaza el token de acceso actual.",
           responses={401: {"description": "Token ausente o inválido."},
                      403: {"description": "La clave actual no coincide."},
                      422: {"description": "La clave nueva no cumple la política; `detail` dice por qué."}})
def cambiar_clave(datos: CambioClaveIn, request: Request, usuario: Usuario = Depends(usuario_actual),
                  directus: Directus = Depends(get_directus), settings: Settings = Depends(get_settings),
                  ip: str | None = Depends(get_ip)):
    service.cambiar_clave(directus, settings, request.app.state, usuario, datos.actual, datos.nueva, ip)
    return Response(status_code=204)


@auth.get("/yo", response_model=PerfilOut, summary="Perfil y permisos del usuario",
          description="Devuelve quién es el usuario, su rol y sus permisos. Cada permiso trae la lista de departamentos donde "
                      "vale; `null` en la lista significa todos los departamentos. Úselo para decidir qué mostrar en el "
                      "frontend.",
          responses={401: {"description": "Token ausente, inválido o vencido."}})
def yo(usuario: Usuario = Depends(usuario_actual)):
    return service.perfil(usuario)


def _usuario_o_404(directus: Directus, uid: int) -> dict:
    espejo = repo.espejo_por_id(directus, uid)
    if not espejo:
        raise HTTPException(404, "No encontrado")
    return espejo


def _evento(directus, ip, actor: Usuario, accion: str, uid: int, detalle: dict, departamento_id=None) -> None:
    audit.registrar(directus, usuario_id=actor.mirror_id, ip=ip, accion=accion, entidad="identidad_usuario", entidad_id=uid,
                    detalle=detalle, departamento_id=departamento_id)


@gestion.get("/usuarios", summary="Listar usuarios",
             description="Requiere `usuarios.gestionar`. Incluye el rol y el departamento de cada usuario.")
def listar_usuarios(_: Usuario = Depends(requiere("usuarios.gestionar")), directus: Directus = Depends(get_directus)):
    return repo.listar_usuarios(directus)


@gestion.post("/usuarios", status_code=201, summary="Crear un usuario",
              description="Requiere `usuarios.gestionar`. Se crea sin rol: no puede entrar hasta que se le asigne uno. La clave "
                          "debe cumplir la política (12 o más caracteres, letras con números o símbolos).")
def crear_usuario(datos: UsuarioIn, usuario: Usuario = Depends(requiere("usuarios.gestionar")),
                  directus: Directus = Depends(get_directus), settings: Settings = Depends(get_settings),
                  ip: str | None = Depends(get_ip)):
    email = datos.email.strip().lower()
    problema = security.clave_valida(datos.clave, email, settings.clave_minima)
    if problema:
        raise HTTPException(422, problema)
    if repo.usuario_por_email(directus, email):
        raise HTTPException(409, "Ya existe un usuario con ese correo")
    nuevo, _ = repo.crear_usuario(directus, email, datos.nombre, datos.clave)
    _evento(directus, ip, usuario, "usuario_creado", nuevo, {"email": email})
    return {"id": nuevo, "email": email}


@gestion.delete("/usuarios/{uid}", status_code=204, summary="Eliminar un usuario",
                description="Requiere `usuarios.gestionar`. Borrado lógico: el usuario queda suspendido y no puede entrar. "
                            "No se puede eliminar la propia cuenta.")
def eliminar_usuario(uid: int, usuario: Usuario = Depends(requiere("usuarios.gestionar")),
                     directus: Directus = Depends(get_directus), ip: str | None = Depends(get_ip)):
    espejo = _usuario_o_404(directus, uid)
    if espejo["directus_id"] == usuario.id:
        raise HTTPException(409, "No puede eliminar su propia cuenta")
    repo.eliminar_usuario(directus, uid, espejo["directus_id"], usuario.mirror_id)
    _evento(directus, ip, usuario, "usuario_eliminado", uid, {})
    return Response(status_code=204)


@gestion.get("/roles", summary="Listar roles y sus permisos",
             description="Requiere `usuarios.gestionar`. Los permisos de un rol se cambian con el configurador "
                         "(`directus_setup rol-permiso`), no desde la API.")
def listar_roles(_: Usuario = Depends(requiere("usuarios.gestionar")), directus: Directus = Depends(get_directus)):
    return repo.listar_roles(directus)


@gestion.post("/usuarios/{uid}/roles", status_code=201, summary="Asignar un rol",
              description="Requiere `usuarios.gestionar` en ese departamento. `departamento_id` nulo = todos los departamentos. "
                          "Reemplaza el rol que tuviera. Nadie puede modificar sus propios roles. Queda auditado.")
def asignar_rol(uid: int, datos: RolAsignacionIn, usuario: Usuario = Depends(requiere("usuarios.gestionar")),
                directus: Directus = Depends(get_directus), ip: str | None = Depends(get_ip)):
    espejo = _usuario_o_404(directus, uid)
    if espejo["directus_id"] == usuario.id:
        raise HTTPException(409, "Nadie puede modificar sus propios roles")
    if not usuario.puede_en("usuarios.gestionar", datos.departamento_id):
        audit.registrar(directus, usuario_id=usuario.mirror_id, ip=ip, accion="acceso_denegado", resultado="denegado",
                        entidad="identidad_usuario", entidad_id=uid, departamento_id=datos.departamento_id,
                        detalle={"operacion": "asignar_rol", "rol": datos.rol})
        raise HTTPException(403, "Sin permiso para gestionar usuarios en ese departamento")
    rol_id = repo.rol_directus_id(directus, datos.rol)
    if not rol_id:
        raise HTTPException(422, f"El rol {datos.rol} no existe")
    repo.asignar_rol(directus, espejo["directus_id"], rol_id, datos.departamento_id)
    _evento(directus, ip, usuario, "permisos_cambiados", uid, {"operacion": "asignar_rol", "rol": datos.rol},
            datos.departamento_id)
    return {"usuario_id": uid, "rol": datos.rol, "departamento_id": datos.departamento_id}


@gestion.delete("/usuarios/{uid}/roles", status_code=204, summary="Quitar el rol a un usuario",
                description="Requiere `usuarios.gestionar`. El usuario queda sin rol y no puede entrar. Nadie puede modificar "
                            "sus propios roles. Queda auditado.")
def revocar_rol(uid: int, usuario: Usuario = Depends(requiere("usuarios.gestionar")),
                directus: Directus = Depends(get_directus), ip: str | None = Depends(get_ip)):
    espejo = _usuario_o_404(directus, uid)
    if espejo["directus_id"] == usuario.id:
        raise HTTPException(409, "Nadie puede modificar sus propios roles")
    repo.revocar_rol(directus, espejo["directus_id"])
    _evento(directus, ip, usuario, "permisos_cambiados", uid, {"operacion": "quitar_rol"})
    return Response(status_code=204)
