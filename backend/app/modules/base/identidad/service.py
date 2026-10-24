"""Autenticación sobre Directus: la sesión, el refresh y las claves son de Directus. Aquí se agregan lo que Directus no
hace: bloqueo por intentos fallidos, política de claves, cierre inmediato del token de acceso y la auditoría de eventos."""

import base64
import json
import time
from datetime import UTC, datetime

from fastapi import HTTPException

from ....core import audit, security
from ....core.config import Settings
from ....core.deps import PREFIJO_ROL, Usuario, huella
from ....core.directus import Directus, Respuesta, exigir
from . import repository as repo


def _dt(texto: str) -> datetime:
    return datetime.fromisoformat(texto.replace("Z", "+00:00")).astimezone(UTC)


def _tokens(r: Respuesta) -> dict:
    d = r.datos
    return {
        "access_token": d["access_token"],
        "refresh_token": d["refresh_token"],
        "token_type": "bearer",
        "expires_in": int(d["expires"] // 1000),
    }


def _espejo(directus: Directus, directus_id: str | None) -> int | None:
    if not directus_id:
        return None
    r = directus.como_servicio(
        "GET",
        "/items/identidad_usuario",
        params={"filter": json.dumps({"directus_id": {"_eq": directus_id}}), "fields": "id", "limit": 1},
    )
    filas = r.datos if r.estado == 200 else []
    return filas[0]["id"] if filas else None


def _login_directus(directus: Directus, email: str, clave: str, ip: str | None) -> Respuesta:
    return directus.pedir(
        "POST", "/auth/login", ip=ip, json={"email": email.strip().lower(), "password": clave, "mode": "json"}
    )


def login(directus: Directus, settings: Settings, email: str, clave: str, ip: str | None) -> dict:
    usuario = repo.usuario_por_email(directus, email)
    uid = usuario["id"] if usuario else None
    espejo = _espejo(directus, uid)

    if usuario and usuario.get("bloqueado_hasta") and _dt(usuario["bloqueado_hasta"]) > datetime.now(UTC):
        audit.registrar(
            directus,
            usuario_id=espejo,
            ip=ip,
            accion="login",
            resultado="denegado",
            entidad="identidad_usuario",
            entidad_id=espejo,
            detalle={"motivo": "cuenta_bloqueada"},
        )
        raise HTTPException(423, "Cuenta bloqueada temporalmente por intentos fallidos")

    r = _login_directus(directus, email, clave, ip)
    if r.estado != 200:
        motivo = "usuario_desconocido" if not usuario else "clave_incorrecta"
        if usuario:
            if repo.registrar_fallo(directus, usuario, settings.intentos_maximos, settings.bloqueo_minutos):
                motivo = "bloqueo_por_intentos"
        audit.registrar(
            directus,
            usuario_id=espejo,
            ip=ip,
            accion="login",
            resultado="denegado",
            entidad="identidad_usuario",
            entidad_id=espejo,
            detalle={"motivo": motivo, "correo_intentado": None if usuario else email.strip().lower()[:254]},
        )
        if r.estado == 429:
            raise HTTPException(429, "Demasiados intentos; espere un minuto")
        raise HTTPException(401, "Correo o clave incorrectos")

    nombre_rol = ((usuario or {}).get("role") or {}).get("name") or ""
    if not nombre_rol.startswith(PREFIJO_ROL):
        # credenciales válidas, pero de una cuenta que no es de la plataforma (p. ej. el administrador de arranque de Directus)
        directus.pedir("POST", "/auth/logout", json={"refresh_token": r.datos["refresh_token"], "mode": "json"})
        audit.registrar(
            directus,
            usuario_id=espejo,
            ip=ip,
            accion="login",
            resultado="denegado",
            entidad="identidad_usuario",
            entidad_id=espejo,
            detalle={"motivo": "cuenta_sin_rol_de_plataforma"},
        )
        raise HTTPException(403, "La cuenta no tiene un rol de la plataforma")
    repo.reiniciar_intentos(directus, usuario)
    audit.registrar(directus, usuario_id=espejo, ip=ip, accion="login", entidad="identidad_usuario", entidad_id=espejo)
    return _tokens(r)


def refrescar(directus: Directus, refresh_token: str, ip: str | None) -> dict:
    r = directus.pedir("POST", "/auth/refresh", ip=ip, json={"refresh_token": refresh_token, "mode": "json"})
    if r.estado != 200:
        audit.registrar(
            directus, usuario_id=None, ip=ip, accion="refresh", resultado="denegado", entidad="identidad_sesion"
        )
        raise HTTPException(401, "Sesión inválida o vencida")
    return _tokens(r)


def _vence(token: str) -> float:
    try:
        carga = token.split(".")[1]
        return float(json.loads(base64.urlsafe_b64decode(carga + "=" * (-len(carga) % 4)))["exp"])
    except (IndexError, ValueError, KeyError):
        return time.time() + 900


def revocar_acceso(estado, token: str) -> None:
    """Directus no invalida el token de acceso al cerrar sesión: dura hasta que vence. La API lo recuerda y lo rechaza."""
    estado.revocados[huella(token)] = _vence(token)
    estado.cache_usuarios.olvidar(huella(token))
    ahora = time.time()
    for k in [k for k, v in estado.revocados.items() if v < ahora]:
        estado.revocados.pop(k, None)


def cerrar_sesion(directus: Directus, estado, usuario: Usuario, refresh_token: str | None, ip: str | None) -> None:
    revocar_acceso(estado, usuario.token)
    if refresh_token:
        directus.pedir("POST", "/auth/logout", ip=ip, json={"refresh_token": refresh_token, "mode": "json"})
    audit.registrar(
        directus,
        usuario_id=usuario.mirror_id,
        ip=ip,
        accion="logout",
        entidad="identidad_usuario",
        entidad_id=usuario.mirror_id,
    )


def cambiar_clave(
    directus: Directus, settings: Settings, estado, usuario: Usuario, actual: str, nueva: str, ip: str | None
) -> None:
    r = _login_directus(directus, usuario.email, actual, ip)
    if r.estado != 200:
        audit.registrar(
            directus,
            usuario_id=usuario.mirror_id,
            ip=ip,
            accion="cambio_clave",
            resultado="denegado",
            entidad="identidad_usuario",
            entidad_id=usuario.mirror_id,
            detalle={"motivo": "clave_actual_incorrecta"},
        )
        raise HTTPException(403, "La clave actual no coincide")
    directus.pedir(
        "POST", "/auth/logout", json={"refresh_token": r.datos["refresh_token"], "mode": "json"}
    )  # la sesión de la comprobación
    problema = security.clave_valida(nueva, usuario.email, settings.clave_minima)
    if problema:
        raise HTTPException(422, problema)
    exigir(directus.pedir("PATCH", "/users/me", token=usuario.token, ip=ip, json={"password": nueva}))
    revocar_acceso(estado, usuario.token)  # Directus ya cerró los refresh tokens; falta el de acceso
    audit.registrar(
        directus,
        usuario_id=usuario.mirror_id,
        ip=ip,
        accion="cambio_clave",
        entidad="identidad_usuario",
        entidad_id=usuario.mirror_id,
    )


def perfil(usuario: Usuario) -> dict:
    permisos = {}
    for p in sorted(usuario.permisos):
        d = usuario.departamentos(p)
        permisos[p] = [None] if d is None else sorted(d)
    return {
        "id": usuario.mirror_id,
        "email": usuario.email,
        "nombre": usuario.nombre,
        "rol": usuario.rol,
        "permisos": permisos,
    }
