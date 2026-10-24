"""Pruebas de integración: contra el stack real (docker compose up), sin simulaciones.

Variables (salen del .env; en local se leen solos desde ../.env): API_URL, DIRECTUS_URL, SATELITES_URL, ADMIN_EMAIL,
ADMIN_PASSWORD, SEED_ADMIN_PASSWORD, SEED_TEST_PASSWORD, SAT_TOKEN_G1. Si la API no responde, las pruebas se omiten.
Son repetibles: cada una crea sus propios datos con nombres únicos y no toca las cuentas iniciales más que para entrar.
LOGIN_RATE_PER_MINUTE debe ser alto en el .env (cada prueba inicia sesión).
"""
import os
import random
import uuid
from pathlib import Path

import httpx
import pytest


def _cargar_env():
    ruta = Path(__file__).resolve().parents[2] / ".env"
    if ruta.exists():
        for linea in ruta.read_text().splitlines():
            if "=" in linea and not linea.startswith("#"):
                k, v = linea.split("=", 1)
                os.environ.setdefault(k, v)


_cargar_env()
API = os.environ.get("API_URL", "http://localhost:8000")
DIRECTUS = os.environ.get("DIRECTUS_URL", "http://localhost:8055")
SATELITES = os.environ.get("SATELITES_URL", "http://localhost:8056")
ADMIN = "encargado.docente@example.com"
PRUEBA = "usuario.prueba@example.com"
CLAVE_NUEVA = "Clave-Larga-De-Prueba-77x"


def pytest_collection_modifyitems(config, items):
    try:
        ok = httpx.get(API + "/health", timeout=5).json().get("directus") == "up"
    except Exception:                                   # noqa: BLE001
        ok = False
    if not ok:
        saltar = pytest.mark.skip(reason=f"la API no responde en {API}: levante el stack con docker compose up")
        for item in items:
            if "tests_integracion" in str(item.fspath):
                item.add_marker(saltar)


@pytest.fixture(scope="session")
def api():
    with httpx.Client(base_url=API, timeout=60) as c:
        yield c


def entrar(api, email, clave):
    r = api.post("/auth/login", json={"email": email, "clave": clave})
    assert r.status_code == 200, f"login de {email}: {r.status_code} {r.text}"
    return r.json()


def cab(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.fixture(scope="session")
def admin(api):
    return cab(entrar(api, ADMIN, os.environ["SEED_ADMIN_PASSWORD"]))


@pytest.fixture(scope="session")
def consulta(api):
    return cab(entrar(api, PRUEBA, os.environ["SEED_TEST_PASSWORD"]))


@pytest.fixture(scope="session")
def boot():
    """Sesión del administrador de arranque de Directus: solo para preparar datos y leer su registro de actividad."""
    r = httpx.post(DIRECTUS + "/auth/login", json={"email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"], "mode": "json"}, timeout=30)
    assert r.status_code == 200, r.text
    c = httpx.Client(base_url=DIRECTUS, headers={"Authorization": f"Bearer {r.json()['data']['access_token']}"}, timeout=60)
    yield c
    c.close()


@pytest.fixture(scope="session")
def depto2(boot):
    """Un segundo departamento (DMAT) para comprobar que no se mezclan."""
    r = boot.get("/items/identidad_departamento", params={"filter[codigo][_eq]": "DMAT", "fields": "id"}).json()["data"]
    if r:
        return r[0]["id"]
    return boot.post("/items/identidad_departamento", json={"codigo": "DMAT", "nombre": "Departamento de prueba"}, params={"fields": "id"}).json()["data"]["id"]


def unico(prefijo="p") -> str:
    """Valor único en mayúsculas (los códigos del esquema lo exigen). Para correos use unico(...).lower()."""
    return f"{prefijo}{uuid.uuid4().hex[:8]}".upper()


def periodo_codigo(semestre: str = "10") -> str:
    """Código de periodo (seis dígitos, termina en 10 o 20) que no choca con los de otras corridas."""
    return f"{random.randint(3000, 9899)}{semestre}"


def dv(cuerpo: int) -> str:
    suma, mult = 0, 2
    for d in reversed(str(cuerpo)):
        suma += int(d) * mult
        mult = 2 if mult == 7 else mult + 1
    r = 11 - suma % 11
    return "0" if r == 11 else "K" if r == 10 else str(r)


def rut_nuevo() -> str:
    cuerpo = random.randint(59_000_000, 59_999_999)
    return f"{cuerpo}-{dv(cuerpo)}"


def crear_usuario(api, admin, rol: str, depto: int | None, clave=CLAVE_NUEVA):
    """Crea un usuario por la API, le asigna rol y departamento y devuelve (cabeceras, email, id)."""
    email = f"{unico('usr')}@example.com".lower()
    r = api.post("/usuarios", headers=admin, json={"email": email, "nombre": f"Usuario {rol}", "clave": clave})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    r = api.post(f"/usuarios/{uid}/roles", headers=admin, json={"rol": rol, "departamento_id": depto})
    assert r.status_code == 201, r.text
    return cab(entrar(api, email, clave)), email, uid


@pytest.fixture(scope="session")
def ed_disc(api, admin):
    return crear_usuario(api, admin, "encargado_docente", 1)[0]


@pytest.fixture(scope="session")
def ed_dmat(api, admin, depto2):
    return crear_usuario(api, admin, "encargado_docente", depto2)[0]
