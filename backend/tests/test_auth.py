import time

import jwt

from app.core import security
from app.seed import ADMIN_EMAIL, PRUEBA_EMAIL

from .conftest import CLAVE_ADMIN, cabecera, entrar, hacer_settings


def auditoria(db, accion, resultado=None):
    q = "SELECT * FROM plataforma_auditoria WHERE accion = ?"
    p = [accion]
    if resultado:
        q += " AND resultado = ?"
        p.append(resultado)
    return [dict(f) for f in db.execute(q + " ORDER BY id", p)]


def test_login_correcto_audita_usuario_ip_y_fecha(client, db):
    tokens = entrar(client, ADMIN_EMAIL, CLAVE_ADMIN)
    assert tokens["token_type"] == "bearer" and tokens["expires_in"] == 600
    fila = auditoria(db, "login", "ok")[0]
    assert fila["usuario_id"] == 1 and fila["ip"] == "testclient" and fila["en"].endswith("Z")


def test_la_clave_se_guarda_con_argon2id_y_no_en_claro(db):
    h = db.execute("SELECT hash_clave FROM identidad_usuario WHERE email = ?", (ADMIN_EMAIL,)).fetchone()[0]
    assert h.startswith("$argon2id$") and CLAVE_ADMIN not in h


def test_login_fallido_audita_sin_guardar_la_clave(client, db):
    r = client.post("/auth/login", json={"email": ADMIN_EMAIL, "clave": "zzClaveMalaUnica"})
    assert r.status_code == 401
    fila = auditoria(db, "login", "denegado")[0]
    assert fila["usuario_id"] == 1 and "clave_incorrecta" in fila["despues"] and "zzClaveMalaUnica" not in str(fila)


def test_usuario_desconocido_responde_igual_y_se_audita(client, db):
    a = client.post("/auth/login", json={"email": "nadie@ejemplo.invalid", "clave": "x" * 14})
    b = client.post("/auth/login", json={"email": ADMIN_EMAIL, "clave": "x" * 14})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()
    assert any("usuario_desconocido" in f["despues"] for f in auditoria(db, "login", "denegado"))


def test_bloqueo_tras_intentos_fallidos_incluso_con_la_clave_correcta(client, db):
    for _ in range(3):
        assert client.post("/auth/login", json={"email": PRUEBA_EMAIL, "clave": "mala-mala-mala"}).status_code == 401
    r = client.post("/auth/login", json={"email": PRUEBA_EMAIL, "clave": "Clave-Prueba-de-prueba-2"})
    assert r.status_code == 423
    motivos = [f["despues"] for f in auditoria(db, "login", "denegado")]
    assert any("bloqueo_por_intentos" in m for m in motivos) and any("cuenta_bloqueada" in m for m in motivos)


def test_un_acierto_reinicia_el_contador(client, db):
    for _ in range(2):
        client.post("/auth/login", json={"email": PRUEBA_EMAIL, "clave": "mala-mala-mala"})
    entrar(client, PRUEBA_EMAIL, "Clave-Prueba-de-prueba-2")
    assert db.execute("SELECT intentos_fallidos FROM identidad_usuario WHERE email = ?", (PRUEBA_EMAIL,)).fetchone()[0] == 0


def test_limite_de_peticiones_por_ip(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    app = create_app(hacer_settings(tmp_path, login_por_minuto_ip=3))
    c = TestClient(app)
    codigos = [c.post("/auth/login", json={"email": "a@ejemplo.invalid", "clave": "x" * 14}).status_code for _ in range(5)]
    assert codigos[:3] == [401, 401, 401] and codigos[3:] == [429, 429]


def test_acceso_sin_token_o_con_token_manipulado(client, settings):
    assert client.get("/auth/yo").status_code == 401
    assert client.get("/auth/yo", headers={"Authorization": "Bearer abc.def.ghi"}).status_code == 401
    sin_firma = jwt.encode({"sub": "1", "fam": "x", "iss": "disc-scheduling", "iat": 1, "exp": int(time.time()) + 99},
                           key="", algorithm="none")
    assert client.get("/auth/yo", headers={"Authorization": f"Bearer {sin_firma}"}).status_code == 401
    otra_firma = jwt.encode({"sub": "1", "fam": "x", "iss": "disc-scheduling", "iat": 1, "exp": int(time.time()) + 99, "typ": "access"},
                            key="otro-secreto-de-48-caracteres-xxxxxxxxxxxxxxxxx", algorithm="HS256")
    assert client.get("/auth/yo", headers={"Authorization": f"Bearer {otra_firma}"}).status_code == 401


def test_token_de_acceso_vencido(client, settings):
    pasado = int(time.time()) - 5
    t = jwt.encode({"sub": "1", "fam": "x", "iss": "disc-scheduling", "iat": pasado - 60, "exp": pasado, "typ": "access"},
                   settings.jwt_secret, algorithm="HS256")
    assert client.get("/auth/yo", headers={"Authorization": f"Bearer {t}"}).status_code == 401


def test_refresh_rota_y_la_reutilizacion_cierra_la_familia(client, db):
    t1 = entrar(client, ADMIN_EMAIL, CLAVE_ADMIN)
    r = client.post("/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert r.status_code == 200
    t2 = r.json()
    assert t2["refresh_token"] != t1["refresh_token"]
    assert client.get("/auth/yo", headers=cabecera(t2)).status_code == 200
    # reutilizar el primero (ya usado) es señal de robo: se revoca todo
    assert client.post("/auth/refresh", json={"refresh_token": t1["refresh_token"]}).status_code == 401
    assert client.get("/auth/yo", headers=cabecera(t2)).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": t2["refresh_token"]}).status_code == 401
    assert auditoria(db, "refresh_reutilizado", "denegado")


def test_el_refresh_solo_se_guarda_con_hash(client, db):
    t = entrar(client, ADMIN_EMAIL, CLAVE_ADMIN)
    assert db.execute("SELECT count(*) FROM identidad_sesion WHERE token_hash = ?", (t["refresh_token"],)).fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM identidad_sesion WHERE token_hash = ?",
                      (security.hash_refresh(t["refresh_token"]),)).fetchone()[0] == 1


def test_refresh_vencido(client, db):
    t = entrar(client, ADMIN_EMAIL, CLAVE_ADMIN)
    db.execute("UPDATE identidad_sesion SET expira_en = '2000-01-01T00:00:00Z'")
    assert client.post("/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401


def test_logout_invalida_el_token_de_inmediato_y_se_audita(client, db):
    t = entrar(client, ADMIN_EMAIL, CLAVE_ADMIN)
    h = cabecera(t)
    assert client.post("/auth/logout", headers=h).status_code == 204
    assert client.get("/auth/yo", headers=h).status_code == 401
    assert client.post("/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401
    fila = auditoria(db, "logout")[0]
    assert fila["usuario_id"] == 1 and fila["ip"] == "testclient"


def test_cambio_de_clave_exige_la_actual_valida_la_politica_y_cierra_sesiones(client, db):
    t = entrar(client, ADMIN_EMAIL, CLAVE_ADMIN)
    h = cabecera(t)
    assert client.post("/auth/cambiar-clave", headers=h, json={"actual": "mal", "nueva": "Otra-clave-larga-77"}).status_code == 403
    assert client.post("/auth/cambiar-clave", headers=h, json={"actual": CLAVE_ADMIN, "nueva": "corta1"}).status_code == 422
    assert client.post("/auth/cambiar-clave", headers=h, json={"actual": CLAVE_ADMIN, "nueva": "Otra-clave-larga-77"}).status_code == 204
    assert client.get("/auth/yo", headers=h).status_code == 401
    entrar(client, ADMIN_EMAIL, "Otra-clave-larga-77")
    assert auditoria(db, "cambio_clave", "ok") and auditoria(db, "cambio_clave", "denegado")


def test_usuario_eliminado_o_inactivo_no_entra(client, db):
    db.execute("UPDATE identidad_usuario SET activo = 0 WHERE email = ?", (PRUEBA_EMAIL,))
    assert client.post("/auth/login", json={"email": PRUEBA_EMAIL, "clave": "Clave-Prueba-de-prueba-2"}).status_code == 401


def test_sin_secreto_jwt_la_app_no_arranca(tmp_path):
    import pytest
    from app.main import create_app
    with pytest.raises(RuntimeError):
        create_app(hacer_settings(tmp_path, jwt_secret="corto"))
