"""Documentación OpenAPI completa y CORS solo para los orígenes configurados."""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app

from .conftest import hacer_settings

ORIGEN = "http://localhost:3000"


def operaciones(client):
    spec = client.get("/openapi.json").json()
    return spec, [(m.upper(), p, o) for p, v in spec["paths"].items() for m, o in v.items()]


def test_las_paginas_de_documentacion_responden(client):
    assert client.get("/docs").status_code == client.get("/redoc").status_code == client.get("/openapi.json").status_code == 200


def test_toda_operacion_tiene_resumen_y_descripcion(client):
    _, ops = operaciones(client)
    assert len(ops) > 80
    sin = [(m, p) for m, p, o in ops if not (o.get("summary") and o.get("description"))]
    assert sin == []


def test_las_rutas_protegidas_documentan_sus_errores(client):
    spec, ops = operaciones(client)
    publicas = {"/health", "/auth/login", "/auth/refresh"}
    for m, p, o in ops:
        if p not in publicas:
            assert "401" in o["responses"], f"{m} {p} no documenta el 401"
    login = spec["paths"]["/auth/login"]["post"]["responses"]
    assert {"200", "401", "422", "423", "429"} <= set(login)
    assert "403" in spec["paths"]["/salas"]["post"]["responses"] and "404" in spec["paths"]["/salas/{clave}"]["delete"]["responses"]
    assert set(spec["paths"]["/health"]["get"]["responses"]) == {"200"}


def test_el_esquema_de_seguridad_es_bearer_y_hay_ejemplos_de_login(client):
    spec, _ = operaciones(client)
    assert spec["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
    assert spec["components"]["schemas"]["LoginIn"]["examples"][0]["email"]
    assert spec["components"]["schemas"]["TokenOut"]["examples"][0]["expires_in"] == 600
    assert {t["name"] for t in spec["tags"]} >= {"autenticación", "catálogo", "horarios", "importación"}


def test_cada_endpoint_dice_el_permiso_que_exige(client):
    _, ops = operaciones(client)
    for m, p, o in ops:
        if p in ("/health", "/auth/login", "/auth/refresh", "/auth/logout", "/auth/cambiar-clave", "/auth/yo"):
            continue
        assert "`" in o["description"], f"{m} {p} no menciona el permiso o la regla que aplica"


# ---- CORS -------------------------------------------------------------------------------------------
def preflight(client, origen, metodo="POST", ruta="/auth/login", cabeceras="content-type,authorization"):
    return client.options(ruta, headers={"Origin": origen, "Access-Control-Request-Method": metodo,
                                         "Access-Control-Request-Headers": cabeceras})


def test_sin_origenes_configurados_no_hay_cors(client):
    r = preflight(client, ORIGEN)
    assert "access-control-allow-origin" not in r.headers


def test_el_origen_configurado_puede_llamar_y_los_demas_no(tmp_path):
    c = TestClient(create_app(hacer_settings(tmp_path, cors_origenes=(ORIGEN,))))
    ok = preflight(c, ORIGEN)
    assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == ORIGEN
    assert "authorization" in ok.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in ok.headers          # se usa Authorization, no cookies
    ajeno = preflight(c, "http://sitio-ajeno.example")
    assert "access-control-allow-origin" not in ajeno.headers
    r = c.post("/auth/login", json={"email": "a@example.com", "clave": "x" * 14}, headers={"Origin": ORIGEN})
    assert r.status_code == 401 and r.headers["access-control-allow-origin"] == ORIGEN


def test_no_se_admite_comodin(tmp_path):
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        create_app(hacer_settings(tmp_path, cors_origenes=("*",)))


def test_cors_se_lee_del_entorno(monkeypatch):
    from app.core.config import Settings
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000/, http://127.0.0.1:3000 ,")
    assert Settings().cors_origenes == ("http://localhost:3000", "http://127.0.0.1:3000")
