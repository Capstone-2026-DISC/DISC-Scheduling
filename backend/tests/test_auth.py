"""Inicio de sesión, renovación, cierre y cambio de clave sobre Directus (simulado)."""

import httpx
from app.main import create_app
from fastapi.testclient import TestClient

from .conftest import ADMIN, CLAVE_ADMIN, CLAVE_PRUEBA, PRUEBA, cabecera, entrar, eventos, hacer_settings


def test_login_correcto_devuelve_los_tokens_de_directus_y_reenvia_la_ip(client, directus):
    t = entrar(client, ADMIN, CLAVE_ADMIN)
    assert t["token_type"] == "bearer" and t["expires_in"] == 600 and t["access_token"] and t["refresh_token"]
    envio = next(llamada for llamada in directus.llamadas if llamada[1] == "/auth/login")
    assert envio[4] == "testclient"  # Directus registra la IP real, no la de la API
    assert eventos(directus, "login")[0]["resultado"] == "ok"


def test_login_fallido_audita_sin_guardar_la_clave(client, directus):
    r = client.post("/auth/login", json={"email": ADMIN, "clave": "zzClaveMalaUnica"})
    assert r.status_code == 401
    e = eventos(directus, "login")[0]
    assert (
        e["resultado"] == "denegado"
        and "clave_incorrecta" in e["despues"]
        and "zzClaveMalaUnica" not in str(directus.items)
    )


def test_usuario_desconocido_responde_igual_y_se_audita(client, directus):
    a = client.post("/auth/login", json={"email": "nadie@example.com", "clave": "x" * 14})
    b = client.post("/auth/login", json={"email": ADMIN, "clave": "x" * 14})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()
    assert any("usuario_desconocido" in e["despues"] for e in eventos(directus, "login"))


def test_bloqueo_tras_intentos_fallidos_incluso_con_la_clave_correcta(client, directus):
    for _ in range(3):
        assert client.post("/auth/login", json={"email": PRUEBA, "clave": "mala-mala-mala"}).status_code == 401
    assert client.post("/auth/login", json={"email": PRUEBA, "clave": CLAVE_PRUEBA}).status_code == 423
    motivos = " ".join(e["despues"] for e in eventos(directus, "login"))
    assert "bloqueo_por_intentos" in motivos and "cuenta_bloqueada" in motivos
    assert directus.usuarios[PRUEBA]["bloqueado_hasta"]


def test_un_acierto_reinicia_el_contador(client, directus):
    for _ in range(2):
        client.post("/auth/login", json={"email": PRUEBA, "clave": "mala-mala-mala"})
    assert directus.usuarios[PRUEBA]["intentos_fallidos"] == 2
    entrar(client, PRUEBA, CLAVE_PRUEBA)
    assert directus.usuarios[PRUEBA]["intentos_fallidos"] == 0


def test_el_bloqueo_vence(client, directus):
    for _ in range(3):
        client.post("/auth/login", json={"email": PRUEBA, "clave": "mala-mala-mala"})
    directus.usuarios[PRUEBA]["bloqueado_hasta"] = "2000-01-01T00:00:00Z"
    entrar(client, PRUEBA, CLAVE_PRUEBA)


def test_limite_de_peticiones_por_ip(directus):
    app = create_app(hacer_settings(login_por_minuto_ip=3), transport=httpx.MockTransport(directus))
    c = TestClient(app)
    codigos = [c.post("/auth/login", json={"email": "a@example.com", "clave": "x" * 14}).status_code for _ in range(5)]
    assert codigos[:3] == [401, 401, 401] and codigos[3:] == [429, 429]


def test_una_cuenta_sin_rol_de_plataforma_no_entra(client, directus):
    directus.agregar_usuario(
        "sinrol@example.com", "Clave-Larga-Sinrol-1x", "cccccccc-cccc-cccc-cccc-cccccccccccc", None, None
    )
    r = client.post("/auth/login", json={"email": "sinrol@example.com", "clave": "Clave-Larga-Sinrol-1x"})
    assert r.status_code == 403 and "rol de la plataforma" in r.json()["detail"]
    assert not directus.refresh  # la sesión que abrió la comprobación se cerró


def test_acceso_sin_token_con_token_falso_o_de_otro_origen(client):
    assert client.get("/auth/yo").status_code == 401
    assert client.get("/auth/yo", headers={"Authorization": "Bearer abc.def.ghi"}).status_code == 401


def test_perfil_con_permisos_por_departamento(client, admin, consulta):
    p = client.get("/auth/yo", headers=consulta).json()
    assert p["rol"] == "consulta" and p["permisos"] == {"catalogo.ver": [1], "horarios.ver": [1]}
    todo = client.get("/auth/yo", headers=admin).json()
    assert todo["permisos"]["catalogo.editar"] == [None] and todo["id"] == 1  # [null] = todos los departamentos


def test_refresh_rota_y_el_viejo_se_rechaza(client):
    t1 = entrar(client, ADMIN, CLAVE_ADMIN)
    r = client.post("/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert r.status_code == 200 and r.json()["refresh_token"] != t1["refresh_token"]
    assert client.get("/auth/yo", headers=cabecera(r.json())).status_code == 200
    assert client.post("/auth/refresh", json={"refresh_token": t1["refresh_token"]}).status_code == 401


def test_logout_el_acceso_deja_de_valer_de_inmediato_aunque_directus_lo_aceptaria(client, directus):
    t = entrar(client, ADMIN, CLAVE_ADMIN)
    h = cabecera(t)
    assert client.get("/auth/yo", headers=h).status_code == 200
    assert client.post("/auth/logout", headers=h, json={"refresh_token": t["refresh_token"]}).status_code == 204
    assert t["access_token"] in directus.sesiones  # Directus todavía lo daría por bueno
    assert client.get("/auth/yo", headers=h).status_code == 401  # pero esta API ya no
    assert client.post("/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401
    assert eventos(directus, "logout")


def test_cambio_de_clave_exige_la_actual_valida_la_politica_y_cierra_el_acceso(client, directus):
    t = entrar(client, ADMIN, CLAVE_ADMIN)
    h = cabecera(t)
    assert (
        client.post(
            "/auth/cambiar-clave", headers=h, json={"actual": "mal", "nueva": "Otra-clave-larga-77"}
        ).status_code
        == 403
    )
    assert (
        client.post("/auth/cambiar-clave", headers=h, json={"actual": CLAVE_ADMIN, "nueva": "corta1"}).status_code
        == 422
    )
    assert directus.usuarios[ADMIN]["password"] == CLAVE_ADMIN
    assert (
        client.post(
            "/auth/cambiar-clave", headers=h, json={"actual": CLAVE_ADMIN, "nueva": "Otra-clave-larga-77"}
        ).status_code
        == 204
    )
    assert directus.usuarios[ADMIN]["password"] == "Otra-clave-larga-77"
    assert client.get("/auth/yo", headers=h).status_code == 401
    entrar(client, ADMIN, "Otra-clave-larga-77")
    assert eventos(directus, "cambio_clave")


def test_la_clave_nueva_no_puede_contener_el_correo(client):
    h = cabecera(entrar(client, ADMIN, CLAVE_ADMIN))
    r = client.post("/auth/cambiar-clave", headers=h, json={"actual": CLAVE_ADMIN, "nueva": "encargado.docente-2026"})
    assert r.status_code == 422 and "correo" in r.json()["detail"]


def test_si_directus_cae_la_api_responde_503_y_no_se_cuelga(directus):
    def caido(req):
        raise httpx.ConnectError("sin red")

    c = TestClient(create_app(hacer_settings(), transport=httpx.MockTransport(caido)))
    assert c.post("/auth/login", json={"email": ADMIN, "clave": CLAVE_ADMIN}).status_code == 503
    assert c.get("/auth/yo", headers={"Authorization": "Bearer x"}).status_code == 503
    assert c.get("/health").json()["status"] == "degraded"


def test_sin_token_de_servicio_o_con_claves_malas_la_app_no_arranca():
    import pytest
    from app.core.pii import ClaveFaltante

    with pytest.raises(RuntimeError):
        create_app(hacer_settings(servicio_token="corto"))
    with pytest.raises(ClaveFaltante):
        create_app(hacer_settings(data_keys="", index_key=""))
