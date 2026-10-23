import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.seed import ADMIN_EMAIL, PRUEBA_EMAIL, sembrar
from app.core.db import conectar

ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema_plataforma.sql"
CLAVE_ADMIN = "Clave-Admin-de-prueba-1"
CLAVE_PRUEBA = "Clave-Prueba-de-prueba-2"


def hacer_settings(tmp_path, **cambios) -> Settings:
    base = dict(db_path=str(tmp_path / "plataforma.db"), esquema_path=str(ESQUEMA),
                jwt_secret="x" * 48, modulos=("base", "financiero", "predictivo"),
                intentos_maximos=3, bloqueo_minutos=15, login_por_minuto_ip=1000)
    base.update(cambios)
    return Settings(**base)


@pytest.fixture
def settings(tmp_path):
    return hacer_settings(tmp_path)


@pytest.fixture
def app(settings):
    app = create_app(settings)
    conn = conectar(settings.db_path)
    sembrar(conn, CLAVE_ADMIN, CLAVE_PRUEBA)
    conn.close()
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def db(settings, app):
    conn = conectar(settings.db_path)
    yield conn
    conn.close()


def entrar(client, email, clave):
    r = client.post("/auth/login", json={"email": email, "clave": clave})
    assert r.status_code == 200, r.text
    return r.json()


def cabecera(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.fixture
def admin(client):
    return cabecera(entrar(client, ADMIN_EMAIL, CLAVE_ADMIN))


@pytest.fixture
def consulta(client):
    return cabecera(entrar(client, PRUEBA_EMAIL, CLAVE_PRUEBA))
