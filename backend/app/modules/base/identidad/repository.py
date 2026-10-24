"""Acceso a usuarios y roles. Las credenciales y la sesión son de Directus; el espejo (identidad_usuario) existe para que
las demás tablas sigan apuntando a un id entero. Todo se hace con el token del servicio, que solo puede crear y
modificar usuarios con roles de la plataforma, y nunca borrarlos ni tocar políticas."""

import json
from datetime import UTC, datetime, timedelta

from ....core.deps import PREFIJO_ROL
from ....core.directus import Directus, exigir, traducir

CAMPOS_USUARIO = "id,email,first_name,status,departamento_id,intentos_fallidos,bloqueado_hasta,role.id,role.name"


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def ahora_iso() -> str:
    return _iso(datetime.now(UTC))


def usuario_por_email(directus: Directus, email: str) -> dict | None:
    r = directus.como_servicio(
        "GET",
        "/users",
        params={"filter": json.dumps({"email": {"_eq": email.strip().lower()}}), "fields": CAMPOS_USUARIO, "limit": 1},
    )
    if r.estado >= 400:
        raise traducir(r)
    return (r.datos or [None])[0]


def registrar_fallo(directus: Directus, usuario: dict, maximo: int, minutos: int) -> str | None:
    """Suma un intento fallido y, si llega al máximo, bloquea la cuenta. Devuelve la hora de desbloqueo si la bloqueó."""
    intentos = (usuario.get("intentos_fallidos") or 0) + 1
    cambios = {"intentos_fallidos": intentos}
    bloqueo = None
    if intentos >= maximo:
        bloqueo = _iso(datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=minutos))
        cambios = {"intentos_fallidos": 0, "bloqueado_hasta": bloqueo}
    exigir(directus.como_servicio("PATCH", f"/users/{usuario['id']}", json=cambios))
    return bloqueo


def reiniciar_intentos(directus: Directus, usuario: dict) -> None:
    if usuario.get("intentos_fallidos") or usuario.get("bloqueado_hasta"):
        directus.como_servicio(
            "PATCH", f"/users/{usuario['id']}", json={"intentos_fallidos": 0, "bloqueado_hasta": None}
        )


# -- espejo -------------------------------------------------------------------------------------------------
def espejo_por_id(directus: Directus, mirror_id: int) -> dict | None:
    r = directus.como_servicio(
        "GET",
        f"/items/identidad_usuario/{mirror_id}",
        params={"fields": "id,directus_id,email,nombre,activo,eliminado_en"},
    )
    if r.estado == 404 or r.estado == 403:
        return None
    exigir(r)
    return r.datos if r.datos and not r.datos.get("eliminado_en") else None


def listar_usuarios(directus: Directus) -> list[dict]:
    r = exigir(directus.como_servicio("GET", "/users", params={"fields": CAMPOS_USUARIO, "limit": -1, "sort": "email"}))
    espejo = (
        exigir(
            directus.como_servicio(
                "GET", "/items/identidad_usuario", params={"fields": "id,directus_id,eliminado_en", "limit": -1}
            )
        ).datos
        or []
    )
    ids = {e["directus_id"]: e["id"] for e in espejo if not e.get("eliminado_en")}
    out = []
    for u in r.datos or []:
        if u["id"] not in ids:  # el administrador de arranque de Directus no es un usuario de la plataforma
            continue
        nombre_rol = (u.get("role") or {}).get("name") or ""
        out.append(
            {
                "id": ids[u["id"]],
                "email": u["email"],
                "nombre": u.get("first_name") or u["email"],
                "rol": nombre_rol[len(PREFIJO_ROL) :] if nombre_rol.startswith(PREFIJO_ROL) else None,
                "departamento_id": u.get("departamento_id"),
                "activo": u.get("status") == "active",
            }
        )
    return out


def rol_directus_id(directus: Directus, codigo: str) -> str | None:
    r = exigir(
        directus.como_servicio(
            "GET",
            "/roles",
            params={"filter": json.dumps({"name": {"_eq": PREFIJO_ROL + codigo}}), "fields": "id", "limit": 1},
        )
    )
    return (r.datos or [{}])[0].get("id")


def crear_usuario(directus: Directus, email: str, nombre: str, clave: str) -> tuple[int, str]:
    r = exigir(
        directus.como_servicio(
            "POST",
            "/users",
            json={"email": email, "password": clave, "first_name": nombre, "status": "active"},
            params={"fields": "id"},
        )
    )
    directus_id = r.datos["id"]
    e = exigir(
        directus.como_servicio(
            "POST",
            "/items/identidad_usuario",
            params={"fields": "id"},
            json={"directus_id": directus_id, "email": email, "nombre": nombre},
        )
    )
    return e.datos["id"], directus_id


def asignar_rol(directus: Directus, directus_id: str, rol_id: str, departamento_id: int | None) -> None:
    exigir(
        directus.como_servicio(
            "PATCH",
            f"/users/{directus_id}",
            json={"role": rol_id, "departamento_id": departamento_id, "status": "active"},
        )
    )


def revocar_rol(directus: Directus, directus_id: str) -> None:
    exigir(directus.como_servicio("PATCH", f"/users/{directus_id}", json={"role": None, "departamento_id": None}))


def eliminar_usuario(directus: Directus, mirror_id: int, directus_id: str, actor_espejo: int | None) -> None:
    """Borrado lógico: el usuario queda suspendido (no puede entrar) y el espejo, marcado como eliminado."""
    exigir(
        directus.como_servicio(
            "PATCH", f"/users/{directus_id}", json={"status": "suspended", "role": None, "departamento_id": None}
        )
    )
    exigir(
        directus.como_servicio(
            "PATCH",
            f"/items/identidad_usuario/{mirror_id}",
            json={"eliminado_en": ahora_iso(), "eliminado_por": actor_espejo, "activo": 0},
        )
    )


def listar_roles(directus: Directus) -> list[dict]:
    roles = (
        exigir(
            directus.como_servicio(
                "GET",
                "/items/identidad_rol",
                params={
                    "fields": "codigo,nombre,descripcion,es_sistema,eliminado_en,activo",
                    "limit": -1,
                    "sort": "codigo",
                },
            )
        ).datos
        or []
    )
    perms = (
        exigir(
            directus.como_servicio(
                "GET", "/items/identidad_rol_permiso", params={"fields": "rol,permiso,revocado_en", "limit": -1}
            )
        ).datos
        or []
    )
    por_rol: dict[str, list[str]] = {}
    for p in perms:
        if not p.get("revocado_en"):
            por_rol.setdefault(p["rol"], []).append(p["permiso"])
    return [
        {
            "codigo": r["codigo"],
            "nombre": r["nombre"],
            "descripcion": r["descripcion"],
            "es_sistema": r["es_sistema"],
            "permisos": sorted(por_rol.get(r["codigo"], [])),
        }
        for r in roles
        if not r.get("eliminado_en") and r.get("activo")
    ]
