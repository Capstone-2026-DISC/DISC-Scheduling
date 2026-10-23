"""Contraseñas (argon2id) y tokens (JWT de acceso corto y refresh opaco con rotación)."""
import hashlib
import secrets
import time
import uuid

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .config import Settings

_hasher = PasswordHasher()
# Hash de una clave descartable: se verifica cuando el usuario no existe para que la
# respuesta tarde lo mismo y no revele qué correos están registrados.
_HASH_FALSO = _hasher.hash(secrets.token_urlsafe(16))


def hashear_clave(clave: str) -> str:
    return _hasher.hash(clave)


def verificar_clave(hash_guardado: str | None, clave: str) -> bool:
    try:
        return _hasher.verify(hash_guardado or _HASH_FALSO, clave) and hash_guardado is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def necesita_rehash(hash_guardado: str) -> bool:
    return _hasher.check_needs_rehash(hash_guardado)


def clave_valida(clave: str, email: str, minimo: int) -> str | None:
    """Devuelve el motivo si la clave no cumple la política, o None si es aceptable."""
    if len(clave) < minimo:
        return f"La clave debe tener al menos {minimo} caracteres."
    if clave.lower() == email.lower() or email.split("@")[0].lower() in clave.lower():
        return "La clave no puede contener el correo."
    if clave.isdigit() or clave.isalpha():
        return "La clave debe mezclar letras con números o símbolos."
    return None


def crear_access(settings: Settings, usuario_id: int, familia: str) -> tuple[str, int]:
    ahora = int(time.time())
    expira = settings.access_minutos * 60
    payload = {"sub": str(usuario_id), "fam": familia, "jti": uuid.uuid4().hex, "typ": "access",
               "iss": settings.jwt_issuer, "iat": ahora, "exp": ahora + expira}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256"), expira


def leer_access(settings: Settings, token: str) -> dict | None:
    try:
        datos = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], issuer=settings.jwt_issuer,
                           options={"require": ["exp", "iat", "sub", "fam", "iss"]})
    except jwt.PyJWTError:
        return None
    return datos if datos.get("typ") == "access" else None


def nuevo_refresh() -> tuple[str, str]:
    """(token para el cliente, hash sha256 que se guarda)."""
    token = secrets.token_urlsafe(48)
    return token, hash_refresh(token)


def hash_refresh(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
