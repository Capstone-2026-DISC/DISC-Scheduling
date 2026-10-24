import base64

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

from .falso import DirectusFalso

CLAVE_DATOS = "k1=" + base64.urlsafe_b64encode(b"A" * 32).decode().rstrip("=")
CLAVE_INDICE = base64.urlsafe_b64encode(b"B" * 32).decode().rstrip("=")
CLAVE_ADMIN = "Clave-Admin-de-prueba-1"
CLAVE_PRUEBA = "Clave-Prueba-de-prueba-2"
ADMIN = "encargado.docente@example.com"
PRUEBA = "usuario.prueba@example.com"


def hacer_settings(**cambios) -> Settings:
    base = dict(directus_url="http://directus.test", servicio_token="s" * 40, data_keys=CLAVE_DATOS, data_key_id="k1",
                index_key=CLAVE_INDICE, intentos_maximos=3, bloqueo_minutos=15, login_por_minuto_ip=1000,
                modulos=("base", "financiero", "predictivo"), cors_origenes=())
    base.update(cambios)
    return Settings(**base)


@pytest.fixture
def directus():
    return DirectusFalso()


@pytest.fixture
def settings():
    return hacer_settings()


@pytest.fixture
def app(settings, directus):
    return create_app(settings, transport=httpx.MockTransport(directus))


@pytest.fixture
def client(app):
    return TestClient(app)


def entrar(client, email, clave):
    r = client.post("/auth/login", json={"email": email, "clave": clave})
    assert r.status_code == 200, r.text
    return r.json()


def cabecera(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.fixture
def admin(client):
    return cabecera(entrar(client, ADMIN, CLAVE_ADMIN))


@pytest.fixture
def consulta(client):
    return cabecera(entrar(client, PRUEBA, CLAVE_PRUEBA))


def eventos(directus, accion=None):
    """Eventos escritos en plataforma_auditoria (con el token del servicio)."""
    filas = directus.items["plataforma_auditoria"]
    return [f for f in filas if accion is None or f["accion"] == accion]
