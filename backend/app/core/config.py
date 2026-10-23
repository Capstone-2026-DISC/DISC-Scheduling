"""Configuración de la aplicación. Todo sale del entorno; ningún secreto vive en el repositorio."""
import os
from dataclasses import dataclass, field


def _entero(nombre: str, defecto: int) -> int:
    return int(os.environ.get(nombre, defecto))


@dataclass(frozen=True)
class Settings:
    db_path: str = field(default_factory=lambda: os.environ.get("DB_PATH", "/data/plataforma.db"))
    esquema_path: str = field(default_factory=lambda: os.environ.get("SCHEMA_PATH", "/app/db/esquema_plataforma.sql"))
    jwt_secret: str = field(default_factory=lambda: os.environ.get("JWT_SECRET", ""))
    jwt_issuer: str = "disc-scheduling"
    access_minutos: int = field(default_factory=lambda: _entero("ACCESS_TOKEN_MINUTES", 10))
    refresh_dias: int = field(default_factory=lambda: _entero("REFRESH_TOKEN_DAYS", 7))
    intentos_maximos: int = field(default_factory=lambda: _entero("LOGIN_MAX_ATTEMPTS", 5))
    bloqueo_minutos: int = field(default_factory=lambda: _entero("LOGIN_LOCK_MINUTES", 15))
    login_por_minuto_ip: int = field(default_factory=lambda: _entero("LOGIN_RATE_PER_MINUTE", 10))
    confiar_proxy: bool = field(default_factory=lambda: os.environ.get("TRUST_PROXY", "0") == "1")
    modulos: tuple = field(default_factory=lambda: tuple(
        m.strip() for m in os.environ.get("MODULES", "base,financiero").split(",") if m.strip()))
    clave_minima: int = 12

    def validar(self) -> None:
        if len(self.jwt_secret) < 32:
            raise RuntimeError("JWT_SECRET debe tener al menos 32 caracteres (ver .env.example)")


def get_settings() -> Settings:
    return Settings()
