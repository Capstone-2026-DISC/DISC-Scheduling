"""API del proyecto: núcleo compartido más los módulos activados por configuración.

La API no abre la base de datos: todo acceso a los datos pasa por Directus (core/directus.py)."""
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from . import registry
from .core.cache import Cache
from .core.config import Settings, get_settings
from .core.directus import Directus, DirectusCaido
from .core.openapi import DESCRIPCION, ETIQUETAS
from .core.ratelimit import LimiteTasa


def create_app(settings: Settings | None = None, transport: httpx.BaseTransport | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.validar()
    modulos = registry.cargar(settings.modulos)

    app = FastAPI(title="DISC Scheduling", version="0.2.0", description=DESCRIPCION, openapi_tags=ETIQUETAS)
    if settings.cors_origenes:       # sin orígenes configurados no se habilita CORS (la API solo responde a su propio origen)
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origenes), allow_credentials=False,
                           allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
                           allow_headers=["Authorization", "Content-Type", "X-Archivo"], max_age=600)
    app.state.settings = settings
    app.state.cifrador = settings.cifrador()
    app.state.directus = Directus(settings.directus_url, settings.servicio_token, transport=transport)
    app.state.limite_login = LimiteTasa(settings.login_por_minuto_ip)
    app.state.cache_usuarios = Cache(20)          # quién es el dueño de un token
    app.state.cache_roles = Cache(60)             # permisos lógicos de cada rol
    app.state.cache_espejo = Cache(300)           # id entero de cada usuario en identidad_usuario
    app.state.revocados = {}                      # tokens de acceso cerrados por esta API: huella -> vencimiento
    for modulo in modulos:
        app.include_router(modulo.router)

    @app.exception_handler(DirectusCaido)
    def directus_caido(_: Request, __: DirectusCaido):
        return JSONResponse(status_code=503, content={"detail": "Directus no responde; reintente en unos segundos"})

    @app.get("/health", tags=["estado"], summary="Estado del servicio",
             description="Público. Indica si Directus responde y qué módulos están activos. Sirve para sondas de disponibilidad; "
                         "no requiere token.")
    def health():
        try:
            r = app.state.directus.pedir("GET", "/server/health")
            directus = "up" if r.estado == 200 and (r.cuerpo or {}).get("status") in ("ok", "warn") else "down"
        except Exception:                          # noqa: BLE001
            directus = "down"
        return {"status": "ok" if directus == "up" else "degraded", "directus": directus, "modulos": [m.NOMBRE for m in modulos]}

    return app


# uvicorn app.main:create_app --factory
