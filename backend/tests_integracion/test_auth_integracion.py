"""Sesión y cuentas contra Directus de verdad."""
import os

from .conftest import ADMIN, CLAVE_NUEVA, cab, crear_usuario, entrar, unico


def test_login_perfil_y_tokens_de_directus(api, admin, consulta):
    t = entrar(api, ADMIN, os.environ["SEED_ADMIN_PASSWORD"])
    assert t["token_type"] == "bearer" and t["expires_in"] == 600
    yo = api.get("/auth/yo", headers=cab(t)).json()
    assert yo["rol"] == "administrador" and yo["permisos"]["usuarios.gestionar"] == [None] and len(yo["permisos"]) == 18
    assert api.get("/auth/yo", headers=consulta).json()["permisos"]["catalogo.ver"] == [1]


def test_sin_token_o_con_token_falso_es_401(api):
    assert api.get("/auth/yo").status_code == 401
    assert api.get("/auth/yo", headers={"Authorization": "Bearer abc.def.ghi"}).status_code == 401


def test_credenciales_malas_son_401_y_no_dicen_que_fallo(api):
    a = api.post("/auth/login", json={"email": ADMIN, "clave": "x" * 14})
    b = api.post("/auth/login", json={"email": "nadie@example.com", "clave": "x" * 14})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_bloqueo_por_intentos_con_una_cuenta_propia(api, admin):
    _, email, _ = crear_usuario(api, admin, "consulta", 1)
    for _ in range(5):
        assert api.post("/auth/login", json={"email": email, "clave": "mala-mala-mala"}).status_code == 401
    assert api.post("/auth/login", json={"email": email, "clave": CLAVE_NUEVA}).status_code == 423


def test_refresh_rota_y_el_viejo_se_rechaza_y_el_logout_cierra_de_inmediato(api, admin):
    _, email, _ = crear_usuario(api, admin, "consulta", 1)
    t1 = entrar(api, email, CLAVE_NUEVA)
    t2 = api.post("/auth/refresh", json={"refresh_token": t1["refresh_token"]}).json()
    assert t2["refresh_token"] != t1["refresh_token"] and api.get("/auth/yo", headers=cab(t2)).status_code == 200
    assert api.post("/auth/refresh", json={"refresh_token": t1["refresh_token"]}).status_code == 401
    assert api.post("/auth/logout", headers=cab(t2), json={"refresh_token": t2["refresh_token"]}).status_code == 204
    assert api.get("/auth/yo", headers=cab(t2)).status_code == 401                     # la API lo rechaza al instante
    assert api.post("/auth/refresh", json={"refresh_token": t2["refresh_token"]}).status_code == 401


def test_cambio_de_clave_de_punta_a_punta(api, admin):
    h, email, _ = crear_usuario(api, admin, "consulta", 1)
    assert api.post("/auth/cambiar-clave", headers=h, json={"actual": "mal", "nueva": "Otra-clave-larga-77"}).status_code == 403
    assert api.post("/auth/cambiar-clave", headers=h, json={"actual": CLAVE_NUEVA, "nueva": "corta1"}).status_code == 422
    assert api.post("/auth/cambiar-clave", headers=h, json={"actual": CLAVE_NUEVA, "nueva": "Otra-clave-larga-77"}).status_code == 204
    assert api.get("/auth/yo", headers=h).status_code == 401
    assert api.post("/auth/login", json={"email": email, "clave": CLAVE_NUEVA}).status_code == 401
    entrar(api, email, "Otra-clave-larga-77")


def test_una_cuenta_sin_rol_no_entra_y_el_administrador_de_arranque_tampoco(api, admin):
    email = f"{unico('sinrol')}@example.com".lower()
    uid = api.post("/usuarios", headers=admin, json={"email": email, "nombre": "Sin rol", "clave": CLAVE_NUEVA}).json()["id"]
    assert api.post("/auth/login", json={"email": email, "clave": CLAVE_NUEVA}).status_code == 403
    assert api.post("/auth/login", json={"email": os.environ["ADMIN_EMAIL"], "clave": os.environ["ADMIN_PASSWORD"]}).status_code == 403
    assert api.delete(f"/usuarios/{uid}", headers=admin).status_code == 204


def test_directus_registra_quien_hizo_el_cambio_con_la_ip_real(api, admin, boot):
    codigo = unico("ZA")
    sala = api.post("/salas", headers=admin, json={"codigo": codigo, "nombre": "Sala de actividad"}).json()["id"]
    act = boot.get("/activity", params={"filter[collection][_eq]": "catalogo_sala", "filter[item][_eq]": str(sala), "fields": "action,ip,user.email"}).json()["data"]
    crea = next(a for a in act if a["action"] == "create")
    assert crea["user"]["email"] == ADMIN
    assert crea["ip"]
    # la IP que registra Directus es la que vio la API, no la del contenedor de la API
    mia = boot.get("/activity", params={"filter[action][_eq]": "login", "filter[user][email][_eq]": ADMIN, "fields": "ip", "sort": "-timestamp", "limit": 1}).json()["data"]
    assert mia and mia[0]["ip"] == crea["ip"]
