"""Genera credenciales locales sin sobrescribir una configuración existente."""
import os
from pathlib import Path
import base64
import secrets

target = Path(__file__).resolve().parents[1] / ".env"
def clave32() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")


values = {
    "DIRECTUS_SECRET": secrets.token_urlsafe(48),
    "ADMIN_EMAIL": "admin@example.com",
    "ADMIN_PASSWORD": secrets.token_urlsafe(32),
    "JWT_SECRET": secrets.token_urlsafe(48),
    "DATA_KEYS": "k1=" + clave32(),
    "DATA_KEY_ID": "k1",
    "INDEX_KEY": clave32(),
    "SEED_ADMIN_PASSWORD": secrets.token_urlsafe(18) + "9a",
    "SEED_TEST_PASSWORD": secrets.token_urlsafe(18) + "9a",
    "SAT_DIRECTUS_SECRET": secrets.token_urlsafe(48),
    "SAT_ADMIN_EMAIL": "admin.satelites@example.com",
    "SAT_ADMIN_PASSWORD": secrets.token_urlsafe(32),
    "SAT_TOKEN_G1": secrets.token_urlsafe(36),
    "SAT_TOKEN_G2": secrets.token_urlsafe(36),
    "SAT_TOKEN_G3": secrets.token_urlsafe(36),
    "SAT_TOKEN_G4": secrets.token_urlsafe(36),
    "CORS_ORIGINS": "http://localhost:3000",
    "MODULES": "base,financiero",
    "DIRECTUS_PORT": "8055",
    "API_PORT": "8000",
    "FRONTEND_PORT": "3000",
    "DEMO_PORT": "8090",
    "SATELITES_PORT": "8056",
}
try:
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit("Ya existe .env; se conserva sin cambios.") from None
with os.fdopen(fd, "w") as stream:
    stream.write("".join(f"{key}={value}\n" for key, value in values.items()))
print("Configuración creada en .env.")
