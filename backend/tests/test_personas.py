"""Datos personales: el RUT y el correo viajan cifrados hasta Directus, que solo ve texto cifrado."""
from app.core import pii

from .conftest import eventos

RUT, EMAIL = "59999999-K", "persona.ficticia@ejemplo.invalid"


def crear(client, admin, rut=RUT, **extra):
    return client.post("/personas", headers=admin, json={"rut": rut, "nombre": "Persona Ficticia", "email": EMAIL, **extra})


def test_directus_solo_recibe_texto_cifrado(client, admin, directus):
    r = crear(client, admin)
    assert r.status_code == 201
    enviado = next(l for l in directus.llamadas if l[0] == "POST" and l[1] == "/items/catalogo_persona")[2]
    assert enviado["rut_cifrado"].startswith("v1:k1:") and enviado["email_cifrado"].startswith("v1:k1:") and len(enviado["rut_indice"]) == 64
    guardado = str(directus.items["catalogo_persona"]) + str(directus.llamadas)
    for secreto in ("59999999", EMAIL, "persona.ficticia", "ejemplo.invalid"):
        assert secreto not in guardado, f"{secreto} viajó o se guardó en claro"
    assert "Persona Ficticia" in guardado                                          # el nombre no se cifra


def test_la_api_devuelve_los_datos_descifrados_y_audita_la_lectura(client, admin, directus):
    pid = crear(client, admin, rut="59.999.999-k").json()["id"]
    assert client.get(f"/personas/{pid}", headers=admin).json() == {"id": pid, "rut": RUT, "nombre": "Persona Ficticia", "email": EMAIL}
    assert client.get("/personas", headers=admin).json()[0]["rut"] == RUT
    lecturas = eventos(directus, "lectura_datos_personales")
    assert len(lecturas) == 2 and lecturas[0]["usuario_id"] == 1 and lecturas[0]["ip"] == "testclient"
    assert RUT not in str(lecturas)


def test_la_auditoria_nunca_lleva_el_rut_ni_el_correo(client, admin, directus):
    crear(client, admin)
    client.get("/personas", headers=admin)
    assert "59999999" not in str(directus.items["plataforma_auditoria"]) and "ejemplo.invalid" not in str(directus.items["plataforma_auditoria"])


def test_consulta_no_ve_datos_personales(client, consulta):
    assert client.get("/personas", headers=consulta).status_code == 403
    assert client.get("/personas/1", headers=consulta).status_code == 403
    assert client.post("/personas", headers=consulta, json={"rut": RUT, "nombre": "X"}).status_code == 403


def test_el_mismo_rut_escrito_distinto_es_un_duplicado(client, admin):
    assert crear(client, admin, rut="59.999.999-K").status_code == 201
    assert crear(client, admin, rut="59999999-k").status_code == 409
    otra = crear(client, admin, rut="59999998-1").json()["id"]
    assert client.patch(f"/personas/{otra}", headers=admin, json={"rut": "59999999-K"}).status_code == 409


def test_rut_invalido_explica_el_digito_correcto(client, admin):
    r = client.post("/personas", headers=admin, json={"rut": "59999999-1", "nombre": "X"})
    assert r.status_code == 422 and "terminar en K" in r.json()["detail"]
    assert client.post("/personas", headers=admin, json={"rut": "1234", "nombre": "X"}).status_code == 422
    assert client.post("/personas", headers=admin, json={"rut": RUT, "nombre": "X", "email": "sin-arroba"}).status_code == 422


def test_modificar_cifra_de_nuevo_y_cambia_el_indice(client, admin, directus):
    pid = crear(client, admin).json()["id"]
    antes = directus.items["catalogo_persona"][0]["rut_indice"]
    assert client.patch(f"/personas/{pid}", headers=admin, json={"rut": "59999998-1", "email": "otro@ejemplo.invalid"}).status_code == 204
    fila = directus.items["catalogo_persona"][0]
    assert fila["rut_indice"] != antes and "59999998" not in str(fila)
    assert client.get(f"/personas/{pid}", headers=admin).json()["rut"] == "59999998-1"


def test_eliminar_es_logico(client, admin, directus):
    pid = crear(client, admin).json()["id"]
    assert client.delete(f"/personas/{pid}", headers=admin).status_code == 204
    assert directus.items["catalogo_persona"][0]["eliminado_en"] and client.get(f"/personas/{pid}", headers=admin).status_code == 404
    assert not any(m == "DELETE" for m, *_ in directus.llamadas)


def test_un_dato_alterado_no_filtra_nada_y_avisa(client, admin, directus):
    pid = crear(client, admin).json()["id"]
    directus.items["catalogo_persona"][0]["rut_cifrado"] = "v1:k1:AAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    r = client.get(f"/personas/{pid}", headers=admin)
    assert r.status_code == 500 and "claves de cifrado" in r.json()["detail"] and RUT not in r.text


def test_rotar_claves_recifra_y_la_vieja_ya_no_hace_falta(client, admin, directus, settings):
    from app.rotar_claves import rotar
    from app.core.directus import Directus
    import httpx
    from .conftest import CLAVE_DATOS, CLAVE_INDICE
    import base64
    crear(client, admin)
    nueva = pii.Cifrador.desde_entorno(f"{CLAVE_DATOS},k2={base64.urlsafe_b64encode(b'E' * 32).decode().rstrip('=')}", "k2", CLAVE_INDICE)
    d = Directus("http://directus.test", transport=httpx.MockTransport(directus))
    directus.sesiones["tok-admin"] = directus.usuarios["encargado.docente@example.com"]
    assert rotar(d, "tok-admin", nueva)["catalogo_persona.rut_cifrado"] == 1
    fila = directus.items["catalogo_persona"][0]
    assert fila["rut_cifrado"].startswith("v1:k2:") and nueva.descifrar(fila["rut_cifrado"], pii.COL_RUT) == RUT
    assert rotar(d, "tok-admin", nueva)["catalogo_persona.rut_cifrado"] == 0
    assert fila["rut_indice"] == settings.cifrador().indice_rut(RUT)
