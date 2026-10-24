"""Dependencias de FastAPI: IP de origen, cliente de Directus y usuario autenticado con sus permisos.

La sesión es la de Directus: el token de acceso que entrega el login es el que se manda en cada llamada y se reenvía a
Directus, que aplica sus permisos. La API solo averigua quién es la persona (GET /users/me) y qué permisos lógicos tiene su
rol, para decidir qué ofrecer y para auditar.
"""

import hashlib
import time
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import audit
from .config import Settings
from .directus import Directus, DirectusCaido, traducir

_bearer = HTTPBearer(auto_error=False)
PREFIJO_ROL = "disc_"


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_directus(request: Request) -> Directus:
    return request.app.state.directus


def get_cifrador(request: Request):
    return request.app.state.cifrador


def get_ip(request: Request, settings: Settings = Depends(get_settings)) -> str | None:
    if settings.confiar_proxy:
        reenviado = request.headers.get("x-forwarded-for")
        if reenviado:
            return reenviado.split(",")[0].strip()
    return request.client.host if request.client else None


def huella(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Usuario:
    id: str  # id del usuario en Directus (UUID)
    mirror_id: int | None  # id en identidad_usuario, el que usan las columnas eliminado_por, creada_por...
    email: str
    nombre: str
    rol: str  # código del rol: administrador, encargado_docente, consulta...
    departamento_id: int | None
    permisos: set[str] = field(default_factory=set)
    token: str = ""

    @property
    def global_(self) -> bool:
        """Ve y edita todos los departamentos (permiso departamentos.ver_otros)."""
        return "departamentos.ver_otros" in self.permisos

    def tiene(self, permiso: str) -> bool:
        return permiso in self.permisos

    def departamentos(self, permiso: str) -> set[int] | None:
        """None = todos los departamentos; conjunto vacío = ninguno."""
        if permiso not in self.permisos:
            return set()
        if self.global_:
            return None
        return {self.departamento_id} if self.departamento_id is not None else set()

    def puede_en(self, permiso: str, departamento_id: int | None) -> bool:
        deptos = self.departamentos(permiso)
        return deptos is None or (departamento_id is not None and departamento_id in deptos)


def permisos_del_rol(request: Request, rol: str) -> set[str]:
    cache = request.app.state.cache_roles
    hit = cache.obtener(rol)
    if hit is not None:
        return hit
    r = request.app.state.directus.como_servicio(
        "GET",
        "/items/identidad_rol_permiso",
        params={
            "filter": f'{{"_and":[{{"rol":{{"_eq":"{rol}"}}}},{{"revocado_en":{{"_null":true}}}}]}}',
            "fields": "permiso",
            "limit": -1,
        },
    )
    if r.estado >= 400:
        raise traducir(r)
    return cache.poner(rol, {f["permiso"] for f in r.datos or []})


def id_espejo(request: Request, directus_id: str) -> int | None:
    cache = request.app.state.cache_espejo
    hit = cache.obtener(directus_id)
    if hit is not None:
        return hit
    r = request.app.state.directus.como_servicio(
        "GET",
        "/items/identidad_usuario",
        params={"filter": f'{{"directus_id":{{"_eq":"{directus_id}"}}}}', "fields": "id", "limit": 1},
    )
    filas = r.datos if r.estado == 200 else []
    return cache.poner(directus_id, filas[0]["id"]) if filas else None


def usuario_actual(
    request: Request, cred: HTTPAuthorizationCredentials | None = Depends(_bearer), ip: str | None = Depends(get_ip)
) -> Usuario:
    sin_acceso = HTTPException(401, "Sesión inválida o vencida", headers={"WWW-Authenticate": "Bearer"})
    if cred is None:
        raise sin_acceso
    token = cred.credentials
    h = huella(token)
    estado = request.app.state
    if estado.revocados.get(h, 0) > time.time():
        raise sin_acceso
    hit = estado.cache_usuarios.obtener(h)
    if hit:
        return hit
    try:
        r = estado.directus.pedir(
            "GET",
            "/users/me",
            token=token,
            ip=ip,
            params={"fields": "id,email,first_name,status,departamento_id,role.name"},
        )
    except DirectusCaido:
        raise HTTPException(503, "Directus no responde") from None
    if r.estado in (401, 403) or not r.datos:
        raise sin_acceso
    if r.estado >= 400:
        raise traducir(r)
    d = r.datos
    nombre_rol = (d.get("role") or {}).get("name") or ""
    if d.get("status") != "active" or not nombre_rol.startswith(PREFIJO_ROL):
        raise HTTPException(403, "La cuenta no tiene un rol de la plataforma")
    rol = nombre_rol[len(PREFIJO_ROL) :]
    usuario = Usuario(
        id=d["id"],
        mirror_id=id_espejo(request, d["id"]),
        email=d["email"],
        nombre=d.get("first_name") or d["email"],
        rol=rol,
        departamento_id=d.get("departamento_id"),
        permisos=permisos_del_rol(request, rol),
        token=token,
    )
    return estado.cache_usuarios.poner(h, usuario)


def requiere(permiso: str):
    """Exige que el usuario tenga el permiso; el alcance fino (departamento) lo aplica Directus."""

    def dependencia(
        request: Request, usuario: Usuario = Depends(usuario_actual), ip: str | None = Depends(get_ip)
    ) -> Usuario:
        if not usuario.tiene(permiso):
            audit.registrar(
                request.app.state.directus,
                usuario_id=usuario.mirror_id,
                ip=ip,
                accion="acceso_denegado",
                resultado="denegado",
                entidad="api",
                entidad_id=request.url.path,
                detalle={"permiso": permiso, "metodo": request.method},
            )
            raise HTTPException(403, f"Falta el permiso {permiso}")
        return usuario

    return dependencia
