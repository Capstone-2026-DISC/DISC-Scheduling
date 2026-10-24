"""Configuración de la aplicación. Todo sale del entorno; ningún secreto vive en el repositorio."""
import os
from dataclasses import dataclass, field


def _entero(nombre: str, defecto: int) -> int:
    return int(os.environ.get(nombre, defecto))


@dataclass(frozen=True)
class Settings:
    directus_url: str = field(default_factory=lambda: os.environ.get("DIRECTUS_URL", "http://directus:8055"))
    servicio_token: str = field(default_factory=lambda: os.environ.get("API_SERVICE_TOKEN", ""))
    satelites_db_path: str = field(default_factory=lambda: os.environ.get("SATELITES_DB_PATH", "/satelites/satelites.db"))
    data_keys: str = field(default_factory=lambda: os.environ.get("DATA_KEYS", ""))          # k1=<base64 de 32 bytes>,k2=...
    data_key_id: str = field(default_factory=lambda: os.environ.get("DATA_KEY_ID", "k1"))     # la que cifra de ahora en adelante
    index_key: str = field(default_factory=lambda: os.environ.get("INDEX_KEY", ""))           # HMAC del RUT; distinta de las anteriores
    intentos_maximos: int = field(default_factory=lambda: _entero("LOGIN_MAX_ATTEMPTS", 5))
    bloqueo_minutos: int = field(default_factory=lambda: _entero("LOGIN_LOCK_MINUTES", 15))
    login_por_minuto_ip: int = field(default_factory=lambda: _entero("LOGIN_RATE_PER_MINUTE", 10))
    confiar_proxy: bool = field(default_factory=lambda: os.environ.get("TRUST_PROXY", "0") == "1")
    modulos: tuple = field(default_factory=lambda: tuple(
        m.strip() for m in os.environ.get("MODULES", "base,financiero").split(",") if m.strip()))
    cors_origenes: tuple = field(default_factory=lambda: tuple(
        o.strip().rstrip("/") for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()))
    clave_minima: int = 12

    def validar(self) -> None:
        if len(self.servicio_token) < 32:
            raise RuntimeError("API_SERVICE_TOKEN debe tener al menos 32 caracteres (ver .env.example)")
        if "*" in self.cors_origenes:
            raise RuntimeError("CORS_ORIGINS no admite «*»: liste los orígenes del frontend, por ejemplo http://localhost:3000")
        self.cifrador()            # falla si faltan DATA_KEYS o INDEX_KEY, o no son de 32 bytes

    def cifrador(self):
        from .pii import Cifrador
        return Cifrador.desde_entorno(self.data_keys, self.data_key_id, self.index_key)


def get_settings() -> Settings:
    return Settings()
