import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ....core import audit, security
from ....core.config import Settings
from ....core.deps import Usuario, get_conn, get_ip, get_settings, requiere, usuario_actual
from ....core.recurso import traducir_error
from . import repository as repo
from . import service
from .schemas import (CambioClaveIn, LoginIn, PerfilOut, RefreshIn, RolAsignacionIn, TokenOut, UsuarioIn)

auth = APIRouter(prefix="/auth", tags=["autenticación"])
gestion = APIRouter(tags=["usuarios y roles"])


@auth.post("/login", response_model=TokenOut)
def login(datos: LoginIn, request: Request, conn: sqlite3.Connection = Depends(get_conn),
          settings: Settings = Depends(get_settings), ip: str | None = Depends(get_ip)):
    if not request.app.state.limite_login.permitir(ip or "?"):
        raise HTTPException(429, "Demasiados intentos; espere un minuto")
    return service.login(conn, settings, datos.email, datos.clave, ip)


@auth.post("/refresh", response_model=TokenOut)
def refresh(datos: RefreshIn, conn: sqlite3.Connection = Depends(get_conn),
            settings: Settings = Depends(get_settings), ip: str | None = Depends(get_ip)):
    return service.refrescar(conn, settings, datos.refresh_token, ip)


@auth.post("/logout", status_code=204)
def logout(usuario: Usuario = Depends(usuario_actual), conn: sqlite3.Connection = Depends(get_conn),
           ip: str | None = Depends(get_ip)):
    service.cerrar_sesion(conn, usuario.id, usuario.familia, ip)
    return Response(status_code=204)


@auth.post("/cambiar-clave", status_code=204)
def cambiar_clave(datos: CambioClaveIn, usuario: Usuario = Depends(usuario_actual),
                  conn: sqlite3.Connection = Depends(get_conn), settings: Settings = Depends(get_settings),
                  ip: str | None = Depends(get_ip)):
    service.cambiar_clave(conn, settings, usuario.id, datos.actual, datos.nueva, ip)
    return Response(status_code=204)


@auth.get("/yo", response_model=PerfilOut)
def yo(usuario: Usuario = Depends(usuario_actual)):
    return PerfilOut(id=usuario.id, email=usuario.email, nombre=usuario.nombre,
                     permisos={p: sorted(d for d in deptos if d is not None) + ([None] if None in deptos else [])
                               for p, deptos in sorted(usuario.permisos.items())})


def _ejecutar(accion, *args):
    try:
        return accion(*args)
    except sqlite3.Error as exc:
        raise traducir_error(exc) from exc


@gestion.get("/usuarios")
def listar_usuarios(_: Usuario = Depends(requiere("usuarios.gestionar")), conn: sqlite3.Connection = Depends(get_conn)):
    return repo.listar_usuarios(conn)


@gestion.post("/usuarios", status_code=201)
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


@gestion.delete("/usuarios/{uid}", status_code=204)
def eliminar_usuario(uid: int, usuario: Usuario = Depends(requiere("usuarios.gestionar")),
                     conn: sqlite3.Connection = Depends(get_conn), ip: str | None = Depends(get_ip)):
    if uid == usuario.id:
        raise HTTPException(409, "No puede eliminar su propia cuenta")
    if not _ejecutar(repo.eliminar_usuario, conn, usuario.id, ip, uid):
        raise HTTPException(404, "No encontrado")
    return Response(status_code=204)


@gestion.get("/roles")
def listar_roles(_: Usuario = Depends(requiere("usuarios.gestionar")), conn: sqlite3.Connection = Depends(get_conn)):
    return repo.listar_roles(conn)


@gestion.post("/usuarios/{uid}/roles", status_code=201)
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


@gestion.delete("/usuarios/{uid}/roles/{asignacion_id}", status_code=204)
def revocar_rol(uid: int, asignacion_id: int, usuario: Usuario = Depends(requiere("usuarios.gestionar")),
                conn: sqlite3.Connection = Depends(get_conn), ip: str | None = Depends(get_ip)):
    if not _ejecutar(repo.revocar_rol, conn, usuario.id, ip, asignacion_id):
        raise HTTPException(404, "No encontrado")
    audit.registrar(conn, usuario_id=usuario.id, ip=ip, accion="permisos_cambiados", entidad="identidad_usuario",
                    entidad_id=uid, detalle={"operacion": "revocar_rol", "asignacion_id": asignacion_id})
    return Response(status_code=204)


@gestion.put("/roles/{rol}/permisos/{permiso}", status_code=204)
def dar_permiso(rol: str, permiso: str, usuario: Usuario = Depends(requiere("usuarios.gestionar")),
                conn: sqlite3.Connection = Depends(get_conn), ip: str | None = Depends(get_ip)):
    _ejecutar(repo.dar_permiso, conn, usuario.id, ip, rol, permiso)
    audit.registrar(conn, usuario_id=usuario.id, ip=ip, accion="permisos_cambiados", entidad="identidad_rol",
                    entidad_id=rol, detalle={"operacion": "dar_permiso", "permiso": permiso})
    return Response(status_code=204)


@gestion.delete("/roles/{rol}/permisos/{permiso}", status_code=204)
def quitar_permiso(rol: str, permiso: str, usuario: Usuario = Depends(requiere("usuarios.gestionar")),
                   conn: sqlite3.Connection = Depends(get_conn), ip: str | None = Depends(get_ip)):
    if rol == "administrador":
        raise HTTPException(409, "No se quitan permisos al rol de sistema")
    if not _ejecutar(repo.quitar_permiso, conn, usuario.id, ip, rol, permiso):
        raise HTTPException(404, "No encontrado")
    audit.registrar(conn, usuario_id=usuario.id, ip=ip, accion="permisos_cambiados", entidad="identidad_rol",
                    entidad_id=rol, detalle={"operacion": "quitar_permiso", "permiso": permiso})
    return Response(status_code=204)
