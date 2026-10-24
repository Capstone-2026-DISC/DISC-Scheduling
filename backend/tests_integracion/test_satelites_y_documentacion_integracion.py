"""Réplica para los satélites, documentación y CORS contra el stack real."""
import os

import httpx

from .conftest import API, DIRECTUS, entrar


def _grupo(g):
    return {"Authorization": "Bearer " + os.environ[f"SAT_TOKEN_{g.upper()}"]}


def test_publicar_pide_permiso_y_los_grupos_leen_la_copia_sin_datos_personales(api, admin, consulta):
    assert api.post("/publicacion", headers=consulta).status_code == 403
    r = api.post("/publicacion", headers=admin)
    assert r.status_code == 200 and "pub_horario" in r.json()["publicado"]
    assert api.post("/publicacion", headers=admin).status_code == 200                      # repetir no duplica ni falla
    assert httpx.get(DIRECTUS + "/items/pub_sala", headers=_grupo("g1"), timeout=30).status_code == 200
    assert httpx.get(DIRECTUS + "/items/pub_estado", headers=_grupo("g1"), timeout=30).json()["data"][0]["publicado_en"]


def test_un_grupo_no_ve_el_nucleo_aunque_comparta_directus_y_archivo():
    g1 = _grupo("g1")
    for coleccion in ("catalogo_persona", "catalogo_docente", "catalogo_sala", "finanzas_tarifa", "plataforma_auditoria",
                      "identidad_usuario", "identidad_rol", "horarios_propuesta", "directus_activity", "directus_users",
                      "directus_permissions"):
        ruta = f"/items/{coleccion}" if not coleccion.startswith("directus_") else "/" + coleccion.removeprefix("directus_")
        assert httpx.get(DIRECTUS + ruta, headers=g1, timeout=30).status_code == 403, coleccion
    assert httpx.get(DIRECTUS + "/users/me", headers=g1, timeout=30).status_code in (200, 403)   # solo se ve a sí mismo, si acaso
    assert httpx.post(DIRECTUS + "/items/catalogo_sala", headers=g1, json={"codigo": "ZZ"}, timeout=30).status_code == 403
    assert httpx.delete(DIRECTUS + "/items/pub_sala/1", headers=g1, timeout=30).status_code == 403


def test_cada_grupo_escribe_solo_en_su_coleccion_y_sin_borrar():
    g1, g2 = _grupo("g1"), _grupo("g2")
    r = httpx.post(DIRECTUS + "/items/sat_g1_registro", headers=g1, json={"clave": "prueba", "valor": "{}"}, timeout=30)
    assert r.status_code == 200
    fila = r.json()["data"]["id"]
    assert httpx.post(DIRECTUS + "/items/sat_g2_registro", headers=g1, json={"clave": "x"}, timeout=30).status_code == 403
    assert httpx.get(DIRECTUS + "/items/sat_g1_registro", headers=g2, timeout=30).status_code == 403
    assert httpx.post(DIRECTUS + "/items/pub_sala", headers=g1, json={"codigo": "X", "es_laboratorio": 0}, timeout=30).status_code == 403
    assert httpx.delete(DIRECTUS + f"/items/sat_g1_registro/{fila}", headers=g1, timeout=30).status_code == 403
    assert httpx.patch(DIRECTUS + f"/items/sat_g1_registro/{fila}", headers=g1, json={"eliminado_en": "2026-01-01T00:00:00Z"}, timeout=30).status_code in (200, 204)


def test_el_token_de_un_grupo_no_sirve_como_sesion_de_persona(api):
    assert api.get("/auth/yo", headers=_grupo("g1")).status_code in (401, 403)
    assert api.get("/salas", headers=_grupo("g1")).status_code in (401, 403)


def test_la_documentacion_y_el_cors_de_la_api_en_vivo():
    assert httpx.get(API + "/docs").status_code == 200 and httpx.get(API + "/openapi.json").status_code == 200
    r = httpx.options(API + "/auth/login", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in httpx.options(API + "/auth/login", headers={"Origin": "http://ajeno.example", "Access-Control-Request-Method": "POST"}).headers


def test_health_informa_directus_y_modulos():
    h = httpx.get(API + "/health").json()
    assert h["status"] == "ok" and h["directus"] == "up" and "base" in h["modulos"]
