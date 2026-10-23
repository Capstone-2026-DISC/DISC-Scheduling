"""API del proyecto: núcleo compartido más los módulos activados por configuración."""
import os
import sqlite3

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import registry
from .core.config import Settings, get_settings
from .core.db import conectar, crear_si_falta
from .core.openapi import DESCRIPCION, ETIQUETAS
from .core.ratelimit import LimiteTasa


def directus_status() -> str:
    url = os.environ.get("DIRECTUS_URL", "http://directus:8055")
    try:
        response = httpx.get(f"{url}/server/health", timeout=2)
    except httpx.RequestError:
        return "down"
    return "up" if response.is_success else "down"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.validar()
    crear_si_falta(settings.db_path, settings.esquema_path)
    modulos = registry.cargar(settings.modulos)

    app = FastAPI(title="DISC Scheduling", version="0.1.0", description=DESCRIPCION, openapi_tags=ETIQUETAS)
    if settings.cors_origenes:       # sin orígenes configurados no se habilita CORS (la API solo responde a su propio origen)
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origenes), allow_credentials=False,
                           allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
                           allow_headers=["Authorization", "Content-Type", "X-Archivo"], max_age=600)
    app.state.settings = settings
    app.state.cifrador = settings.cifrador()
    app.state.limite_login = LimiteTasa(settings.login_por_minuto_ip)
    for modulo in modulos:
        app.include_router(modulo.router)

    @app.get("/health", tags=["estado"], summary="Estado del servicio",
             description="Público. Indica si la base de datos y Directus responden y qué módulos están activos. "
                         "Sirve para sondas de disponibilidad; no requiere token.")
    def health():
        try:
            conn = conectar(settings.db_path)
            conn.execute("SELECT 1 FROM plataforma_contexto").fetchone()
            conn.close()
            base = "up"
        except sqlite3.Error:
            base = "down"
        return {"status": "ok" if base == "up" else "degraded", "base_de_datos": base,
                "directus": directus_status(), "modulos": [m.NOMBRE for m in modulos]}

    return app


# uvicorn app.main:create_app --factory
