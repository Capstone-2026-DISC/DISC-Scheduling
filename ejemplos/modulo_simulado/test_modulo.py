"""Pruebas del módulo de ejemplo con un Directus simulado (sin red)."""

import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from modulo_app import crear_app  # noqa: E402

TOKEN = "token-de-prueba-del-grupo"


class DirectusFalso:
    def __init__(self):
        self.llamadas = []
        self.registros = [{"id": 1, "clave": "uno", "valor": None, "eliminado_en": None}]
        self.prohibido = {
            ("POST", "/items/pub_sala"),
            ("POST", "/items/sat_g2_registro"),
            ("GET", "/items/sat_g2_registro"),
            ("GET", "/items/catalogo_persona"),
            ("DELETE", "/items/sat_g1_registro/1"),
            ("GET", "/users"),
        }
        self.rechazar_escritura = False

    def __call__(self, req: httpx.Request) -> httpx.Response:
        clave = (req.method, req.url.path)
        cuerpo = json.loads(req.content) if req.content else None
        self.llamadas.append((req.method, req.url.path, cuerpo, req.headers.get("authorization")))
        if clave in self.prohibido:
            return httpx.Response(403, json={"errors": [{"message": "sin permiso"}]})
        if req.url.path == "/server/ping":
            return httpx.Response(200, text="pong")
        if req.method == "GET" and req.url.path == "/items/pub_sala":
            return httpx.Response(
                200, json={"data": [{"id": 1, "codigo": "<script>alert(1)</script>", "capacidad": 20}]}
            )
        if req.method == "GET" and req.url.path.startswith("/items/pub_"):
            return httpx.Response(200, json={"data": []})
        if req.method == "GET" and req.url.path == "/items/sat_g1_registro":
            return httpx.Response(200, json={"data": [r for r in self.registros if not r["eliminado_en"]]})
        if req.method == "POST" and req.url.path == "/items/sat_g1_registro":
            if self.rechazar_escritura:
                return httpx.Response(403, json={"errors": [{"message": "sin permiso"}]})
            self.registros.append({"id": 2, **cuerpo, "eliminado_en": None})
            return httpx.Response(200, json={"data": {"id": 2}})
        if req.method == "PATCH" and req.url.path.startswith("/items/sat_g1_registro/"):
            self.registros[0]["eliminado_en"] = cuerpo["eliminado_en"]
            return httpx.Response(200, json={"data": {}})
        return httpx.Response(404, json={"errors": []})


@pytest.fixture
def dir_():
    return DirectusFalso()


@pytest.fixture
def cliente(dir_):
    return TestClient(crear_app("http://directus", TOKEN, "g1", httpx.MockTransport(dir_)), follow_redirects=False)


def test_la_pagina_muestra_lo_que_lee_y_escapa_el_contenido(cliente):
    r = cliente.get("/")
    assert r.status_code == 200 and "conectado" in r.text and "pub_sala" in r.text
    assert "<script>alert(1)</script>" not in r.text and "&lt;script&gt;" in r.text


def test_todas_las_llamadas_llevan_el_token_del_grupo_y_el_token_no_aparece_en_la_pagina(cliente, dir_):
    cliente.get("/")
    assert dir_.llamadas and all(c[3] == f"Bearer {TOKEN}" for c in dir_.llamadas)
    assert TOKEN not in cliente.get("/").text and TOKEN not in cliente.get("/estado").text


def test_solo_habla_con_directus_y_con_rutas_de_lectura_o_de_su_coleccion(cliente, dir_):
    cliente.get("/")
    cliente.post("/registro", data={"clave": "k"})
    rutas = {(m, p) for m, p, *_ in dir_.llamadas}
    assert all(p.startswith(("/items/pub_", "/items/sat_g1_registro", "/server/ping")) for _, p in rutas)


def test_guardar_un_registro_en_la_coleccion_propia(cliente, dir_):
    r = cliente.post("/registro", data={"clave": "nota", "valor": '{"a": 1}'})
    assert r.status_code == 303
    envio = [c for c in dir_.llamadas if c[0] == "POST"][0]
    assert envio[1] == "/items/sat_g1_registro" and envio[2] == {"clave": "nota", "valor": '{"a": 1}'}
    assert "guardado" in cliente.get(r.headers["location"]).text


def test_si_directus_rechaza_la_escritura_la_pagina_lo_dice_sin_caerse(cliente, dir_):
    dir_.rechazar_escritura = True
    r = cliente.post("/registro", data={"clave": "nota"})
    assert "rechaz" in cliente.get(r.headers["location"]).text


def test_eliminar_es_borrado_logico_y_nunca_un_delete(cliente, dir_):
    r = cliente.post("/registro/1/eliminar")
    assert r.status_code == 303
    assert not any(m == "DELETE" for m, *_ in dir_.llamadas)
    parche = [c for c in dir_.llamadas if c[0] == "PATCH"][0]
    assert parche[2]["eliminado_en"].endswith("Z")
    assert "Todavía no hay registros" in cliente.get("/").text


def test_los_limites_se_prueban_solo_al_pedirlo_y_todos_deben_ser_rechazados(cliente, dir_):
    cliente.get("/")
    assert not any(m in ("POST", "DELETE") for m, *_ in dir_.llamadas)  # abrir la página no intenta nada riesgoso
    r = cliente.post("/limites")
    assert r.text.count("rechazado, correcto") == 6 and "NO fue rechazado" not in r.text


def test_si_un_limite_no_se_cumple_se_marca_en_rojo(cliente, dir_):
    dir_.prohibido.discard(("GET", "/users"))
    assert "NO fue rechazado" in cliente.post("/limites").text


def test_sin_directus_la_aplicacion_sigue_respondiendo(tmp_path):
    def caido(req):
        raise httpx.ConnectError("sin red")

    c = TestClient(crear_app("http://directus", TOKEN, "g1", httpx.MockTransport(caido)))
    assert c.get("/").status_code == 200 and "sin conexión" in c.get("/").text
    assert c.get("/estado").json()["conectado"] is False


def test_el_healthcheck_no_consume_peticiones_de_directus(cliente, dir_):
    assert cliente.get("/salud").json() == {"ok": True}
    assert dir_.llamadas == []


def test_abrir_la_pagina_cuesta_pocas_peticiones_para_no_agotar_el_limite_de_directus(cliente, dir_):
    cliente.get("/")
    assert len(dir_.llamadas) <= 7


def test_si_directus_limita_las_peticiones_la_pagina_avisa(dir_):
    def limitado(req):
        return httpx.Response(429, json={"errors": [{"message": "Too many requests"}]})

    c = TestClient(crear_app("http://directus", TOKEN, "g1", httpx.MockTransport(limitado)))
    assert "limitó las peticiones" in c.get("/").text
