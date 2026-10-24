"""Réplica para los satélites, documentación y CORS contra el stack real."""
import os

import httpx

from .conftest import API, SATELITES, entrar


def test_publicar_pide_permiso_y_la_replica_no_tiene_datos_personales(api, admin, consulta):
    assert api.post("/publicacion", headers=consulta).status_code == 403
    r = api.post("/publicacion", headers=admin)
    assert r.status_code == 200 and "pub_horario" in r.json()["publicado"]
    g1 = {"Authorization": "Bearer " + os.environ["SAT_TOKEN_G1"]}
    assert httpx.get(SATELITES + "/items/pub_sala", headers=g1, timeout=30).status_code == 200
    for coleccion in ("catalogo_persona", "catalogo_docente", "finanzas_tarifa", "plataforma_auditoria"):
        assert httpx.get(f"{SATELITES}/items/{coleccion}", headers=g1, timeout=30).status_code in (403, 404)


def test_la_documentacion_y_el_cors_de_la_api_en_vivo():
    assert httpx.get(API + "/docs").status_code == 200 and httpx.get(API + "/openapi.json").status_code == 200
    r = httpx.options(API + "/auth/login", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in httpx.options(API + "/auth/login", headers={"Origin": "http://ajeno.example", "Access-Control-Request-Method": "POST"}).headers


def test_health_informa_directus_y_modulos():
    h = httpx.get(API + "/health").json()
    assert h["status"] == "ok" and h["directus"] == "up" and "base" in h["modulos"]
