import httpx
from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)


def test_health_with_directus_up(monkeypatch):
    monkeypatch.setattr(main.httpx, "get", lambda *a, **k: httpx.Response(200))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "directus": "up"}


def test_health_with_directus_down(monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ConnectError("sin conexión")

    monkeypatch.setattr(main.httpx, "get", fail)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "directus": "down"}
