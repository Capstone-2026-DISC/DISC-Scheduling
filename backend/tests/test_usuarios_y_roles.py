"""Gestión de usuarios y roles: la API usa la cuenta de servicio de Directus y valida lo que Directus no sabe."""

from .conftest import ADMIN, PRUEBA, cabecera, entrar, eventos


def test_listar_usuarios_y_roles_pide_usuarios_gestionar(client, admin, consulta):
    lista = client.get("/usuarios", headers=admin).json()
    assert {u["email"] for u in lista} == {ADMIN, PRUEBA}
    assert next(u for u in lista if u["email"] == PRUEBA) == {
        "id": 2,
        "email": PRUEBA,
        "nombre": "usuario.prueba",
        "rol": "consulta",
        "departamento_id": 1,
        "activo": True,
    }
    assert client.get("/usuarios", headers=consulta).status_code == 403
    assert client.get("/roles", headers=consulta).status_code == 403


def test_un_intento_sin_permiso_queda_en_la_auditoria(client, directus, consulta):
    client.get("/usuarios", headers=consulta)
    e = eventos(directus, "acceso_denegado")[0]
    assert e["resultado"] == "denegado" and e["usuario_id"] == 2 and e["ip"] == "testclient"


def test_crear_usuario_aplica_la_politica_de_claves_y_no_repite_correos(client, admin, directus):
    assert (
        client.post(
            "/usuarios", headers=admin, json={"email": "persona.nueva@example.com", "nombre": "N", "clave": "corta"}
        ).status_code
        == 422
    )
    r = client.post(
        "/usuarios",
        headers=admin,
        json={"email": "Persona.Nueva@Example.com", "nombre": "N", "clave": "Clave-Nueva-larga-5"},
    )
    assert r.status_code == 201 and r.json()["email"] == "persona.nueva@example.com"
    assert directus.usuarios["persona.nueva@example.com"]["role"] is None  # sin rol no puede entrar
    espejo = [f for f in directus.items["identidad_usuario"] if f["email"] == "persona.nueva@example.com"]
    assert espejo and espejo[0]["directus_id"] == directus.usuarios["persona.nueva@example.com"]["id"]
    assert (
        client.post(
            "/usuarios",
            headers=admin,
            json={"email": "persona.nueva@example.com", "nombre": "N", "clave": "Clave-Nueva-larga-5"},
        ).status_code
        == 409
    )
    assert eventos(directus, "usuario_creado")


def test_la_clave_nueva_no_aparece_en_la_auditoria(client, admin, directus):
    client.post(
        "/usuarios",
        headers=admin,
        json={"email": "persona.equis@example.com", "nombre": "X", "clave": "Clave-Secreta-larga-9"},
    )
    assert "Clave-Secreta-larga-9" not in str(eventos(directus)) and "Clave-Secreta-larga-9" not in str(
        directus.items["identidad_usuario"]
    )


def test_asignar_y_quitar_rol(client, admin, directus):
    client.post(
        "/usuarios",
        headers=admin,
        json={"email": "persona.otra@example.com", "nombre": "N", "clave": "Clave-Nueva-larga-5"},
    )
    uid = directus.items["identidad_usuario"][-1]["id"]
    r = client.post(f"/usuarios/{uid}/roles", headers=admin, json={"rol": "consulta", "departamento_id": 1})
    assert r.status_code == 201
    assert (
        directus.usuarios["persona.otra@example.com"]["role"]["id"] == "r-disc_consulta"
        and directus.usuarios["persona.otra@example.com"]["departamento_id"] == 1
    )
    assert client.delete(f"/usuarios/{uid}/roles", headers=admin).status_code == 204
    assert directus.usuarios["persona.otra@example.com"]["role"] is None
    assert [e["despues"] for e in eventos(directus, "permisos_cambiados")]


def test_nadie_modifica_sus_propios_roles_ni_se_elimina_a_si_mismo(client, admin):
    assert (
        client.post("/usuarios/1/roles", headers=admin, json={"rol": "consulta", "departamento_id": 1}).status_code
        == 409
    )
    assert client.delete("/usuarios/1/roles", headers=admin).status_code == 409
    assert client.delete("/usuarios/1", headers=admin).status_code == 409


def test_un_rol_que_no_existe_o_un_usuario_que_no_existe(client, admin, directus):
    directus.fallos[("GET", "/roles")] = (200, {"data": []})
    assert client.post("/usuarios/2/roles", headers=admin, json={"rol": "inventado"}).status_code == 422
    assert client.post("/usuarios/99/roles", headers=admin, json={"rol": "consulta"}).status_code == 404
    assert client.delete("/usuarios/99", headers=admin).status_code == 404


def test_eliminar_usuario_es_logico(client, admin, directus):
    assert client.delete("/usuarios/2", headers=admin).status_code == 204
    assert directus.usuarios[PRUEBA]["status"] == "suspended" and directus.usuarios[PRUEBA]["role"] is None
    espejo = next(f for f in directus.items["identidad_usuario"] if f["id"] == 2)
    assert espejo["eliminado_en"] and espejo["eliminado_por"] == 1
    assert 2 not in [u["id"] for u in client.get("/usuarios", headers=admin).json()]
    assert not any(m == "DELETE" for m, *_ in directus.llamadas)


def test_un_usuario_de_departamento_solo_asigna_roles_en_el_suyo(client, directus):
    directus.agregar_usuario(
        "jefe@example.com", "Clave-Larga-Jefe-1x", "dddddddd-dddd-dddd-dddd-dddddddddddd", "disc_consulta", 1
    )
    directus.items["identidad_usuario"].append(
        {
            "id": 3,
            "directus_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
            "email": "jefe@example.com",
            "nombre": "J",
            "eliminado_en": None,
        }
    )
    directus.items["identidad_rol_permiso"].append(
        {"id": 99, "rol": "consulta", "permiso": "usuarios.gestionar", "revocado_en": None}
    )
    h = cabecera(entrar(client, "jefe@example.com", "Clave-Larga-Jefe-1x"))
    assert (
        client.post("/usuarios/2/roles", headers=h, json={"rol": "consulta", "departamento_id": 2}).status_code == 403
    )
    assert (
        client.post("/usuarios/2/roles", headers=h, json={"rol": "consulta", "departamento_id": None}).status_code
        == 403
    )
    assert (
        client.post("/usuarios/2/roles", headers=h, json={"rol": "consulta", "departamento_id": 1}).status_code == 201
    )
    assert any(e["resultado"] == "denegado" for e in eventos(directus, "acceso_denegado"))
