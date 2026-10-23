"""Dependencias de FastAPI: conexión, IP de origen, usuario autenticado y comprobación de permisos."""
import sqlite3
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import audit, security
from .config import Settings
from .db import conectar

_bearer = HTTPBearer(auto_error=False)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_cifrador(request: Request):
    return request.app.state.cifrador


def get_conn(settings: Settings = Depends(get_settings)):
    conn = conectar(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_ip(request: Request, settings: Settings = Depends(get_settings)) -> str | None:
    if settings.confiar_proxy:
        reenviado = request.headers.get("x-forwarded-for")
        if reenviado:
            return reenviado.split(",")[0].strip()
    return request.client.host if request.client else None


@dataclass
class Usuario:
    id: int
    email: str
    nombre: str
    familia: str
    permisos: dict[str, set[int | None]] = field(default_factory=dict)   # permiso -> departamentos (None = todos)

    def tiene(self, permiso: str) -> bool:
        return permiso in self.permisos

    def departamentos(self, permiso: str) -> set[int] | None:
        """None = todos los departamentos; conjunto vacío = ninguno."""
        deptos = self.permisos.get(permiso)
        if deptos is None:
            return set()
        return None if None in deptos else {d for d in deptos if d is not None}

    def puede_en(self, permiso: str, departamento_id: int | None) -> bool:
        deptos = self.departamentos(permiso)
        return deptos is None or (departamento_id is not None and departamento_id in deptos)


def cargar_permisos(conn: sqlite3.Connection, usuario_id: int) -> dict[str, set[int | None]]:
    permisos: dict[str, set[int | None]] = {}
    for fila in conn.execute("SELECT permiso, departamento_id FROM identidad_permiso_efectivo WHERE usuario_id = ?",
                             (usuario_id,)):
        permisos.setdefault(fila["permiso"], set()).add(fila["departamento_id"])
    return permisos


def usuario_actual(request: Request, cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
                   conn: sqlite3.Connection = Depends(get_conn),
                   settings: Settings = Depends(get_settings), ip: str | None = Depends(get_ip)) -> Usuario:
    sin_acceso = HTTPException(401, "Sesión inválida o vencida", headers={"WWW-Authenticate": "Bearer"})
    if cred is None:
        raise sin_acceso
    datos = security.leer_access(settings, cred.credentials)
    if datos is None:
        raise sin_acceso
    uid = int(datos["sub"])
    viva = conn.execute("SELECT 1 FROM identidad_sesion WHERE familia = ? AND usuario_id = ? AND revocada_en IS NULL "
                        "LIMIT 1", (datos["fam"], uid)).fetchone()
    fila = conn.execute("SELECT id, email, nombre FROM identidad_usuario "
                        "WHERE id = ? AND activo = 1 AND eliminado_en IS NULL", (uid,)).fetchone()
    if not viva or not fila:
        raise sin_acceso
    return Usuario(fila["id"], fila["email"], fila["nombre"], datos["fam"], cargar_permisos(conn, uid))


def requiere(permiso: str):
    """Exige que el usuario tenga el permiso en algún departamento; el alcance fino lo aplica cada servicio."""
    def dependencia(request: Request, usuario: Usuario = Depends(usuario_actual),
                    conn: sqlite3.Connection = Depends(get_conn), ip: str | None = Depends(get_ip)) -> Usuario:
        if not usuario.tiene(permiso):
            audit.registrar(conn, usuario_id=usuario.id, ip=ip, accion="acceso_denegado", resultado="denegado",
                            entidad="api", entidad_id=request.url.path,
                            detalle={"permiso": permiso, "metodo": request.method})
            raise HTTPException(403, f"Falta el permiso {permiso}")
        return usuario
    return dependencia
