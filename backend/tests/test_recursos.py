"""Rutas CRUD genéricas sobre Directus: la API traduce, comprueba relaciones y audita; Directus decide los permisos."""
import pytest

from .conftest import eventos


def test_crear_listar_y_ver_una_sala_con_la_sesion_de_la_persona(client, admin, directus):
    r = client.post("/salas", headers=admin, json={"codigo": "SA-1", "nombre": "Sala"})
    assert r.status_code == 201 and r.json() == {"id": 1}
    envio = next(l for l in directus.llamadas if l[0] == "POST" and l[1] == "/items/catalogo_sala")
    assert envio[2] == {"codigo": "SA-1", "nombre": "Sala"} and envio[3] == admin["Authorization"] and envio[4] == "testclient"
    assert client.get("/salas", headers=admin).json()[0]["codigo"] == "SA-1"
    assert "eliminado_en" not in client.get("/salas/1", headers=admin).json()


def test_lectura_sin_permiso_logico_ni_llega_a_directus(client, consulta, directus):
    antes = len(directus.llamadas)
    assert client.post("/salas", headers=consulta, json={"codigo": "X"}).status_code == 403
    assert not any(m == "POST" and r == "/items/catalogo_sala" for m, r, *_ in directus.llamadas[antes:])


def test_eliminar_es_un_patch_de_eliminado_en_y_nunca_un_delete(client, admin, directus):
    client.post("/salas", headers=admin, json={"codigo": "SA-2"})
    assert client.delete("/salas/1", headers=admin).status_code == 204
    parche = next(l for l in directus.llamadas if l[0] == "PATCH" and l[1] == "/items/catalogo_sala/1")
    assert parche[2]["eliminado_en"].endswith("Z") and parche[2]["eliminado_por"] == 1
    assert not any(m == "DELETE" for m, *_ in directus.llamadas)
    assert client.get("/salas/1", headers=admin).status_code == 404 and client.get("/salas", headers=admin).json() == []


def test_un_403_de_directus_al_modificar_se_audita_y_una_fila_inexistente_es_404(client, admin, directus):
    client.post("/salas", headers=admin, json={"codigo": "SA-3"})
    directus.fallos[("PATCH", "/items/catalogo_sala/1")] = (403, {"errors": [{"message": "sin permiso", "extensions": {"code": "FORBIDDEN"}}]})
    assert client.patch("/salas/1", headers=admin, json={"nombre": "x"}).status_code == 403
    e = eventos(directus, "acceso_denegado")[0]
    assert e["entidad"] == "catalogo_sala" and e["entidad_id"] == "1" and e["resultado"] == "denegado"
    directus.fallos[("PATCH", "/items/catalogo_sala/77")] = (403, {"errors": [{"message": "no existe", "extensions": {"code": "FORBIDDEN"}}]})
    assert client.patch("/salas/77", headers=admin, json={"nombre": "x"}).status_code == 404


def test_un_codigo_repetido_es_409_con_el_motivo(client, admin):
    client.post("/salas", headers=admin, json={"codigo": "DUP"})
    r = client.post("/salas", headers=admin, json={"codigo": "DUP"})
    assert r.status_code == 409 and "DUP" in r.json()["detail"]


@pytest.mark.parametrize("ruta,cuerpo", [("/paralelos", {"periodo_id": 5, "asignatura_id": 1, "codigo": "C1"}),
                                          ("/sesiones", {"paralelo_id": 5, "numero": 1})])
def test_no_se_crea_algo_que_apunta_a_una_fila_que_la_persona_no_ve(client, admin, directus, ruta, cuerpo):
    """Directus no comprueba que se pueda ver la fila a la que apunta una clave foránea: lo hace la API."""
    r = client.post(ruta, headers=admin, json=cuerpo)
    assert r.status_code == 403
    assert not any(m == "POST" and rr.startswith("/items/horarios_") for m, rr, *_ in directus.llamadas)
    assert eventos(directus, "acceso_denegado")


def test_se_crea_si_la_relacion_es_visible(client, admin, directus):
    directus.items["catalogo_periodo"].append({"id": 5, "codigo": "202620", "departamento_id": 1})
    assert client.post("/paralelos", headers=admin, json={"periodo_id": 5, "asignatura_id": 1, "codigo": "C1"}).status_code == 201


def test_los_campos_no_declarados_se_rechazan(client, admin):
    assert client.post("/salas", headers=admin, json={"codigo": "S", "eliminado_en": "2020-01-01"}).status_code == 422
    assert client.patch("/salas/1", headers=admin, json={}).status_code in (404, 422)


def test_las_restricciones_guardan_json_y_quien_las_creo(client, admin, directus):
    r = client.post("/restricciones", headers=admin, json={"naturaleza": "dura", "tipo": "bloque_protegido", "parametros": {"dia": "Ju", "bloque": "C"}})
    assert r.status_code == 201
    guardado = directus.items["horarios_restriccion"][0]
    assert guardado["parametros"] == '{"dia": "Ju", "bloque": "C"}' and guardado["creada_por"] == 1
    assert client.get("/restricciones/1", headers=admin).json()["parametros"] == {"dia": "Ju", "bloque": "C"}


def test_aprobar_una_propuesta_envia_el_estado_y_quien_aprueba(client, admin, directus):
    directus.items["horarios_propuesta"].append({"id": 1, "periodo_id": 1, "estado": "borrador", "completa": 1})
    assert client.post("/propuestas/1/aprobar", headers=admin).status_code == 204
    parche = next(l for l in directus.llamadas if l[0] == "PATCH" and l[1] == "/items/horarios_propuesta/1")
    assert parche[2] == {"estado": "aprobada", "aprobada_por": 1}
    assert client.post("/propuestas/9/aprobar", headers=admin).status_code == 404


def test_la_regla_de_la_base_que_impide_aprobar_se_explica(client, admin, directus):
    directus.items["horarios_propuesta"].append({"id": 1, "periodo_id": 1, "estado": "borrador", "completa": 0})
    directus.fallos[("PATCH", "/items/horarios_propuesta/1")] = (500, {"errors": [{"message": "update `horarios_propuesta` set `estado` = 'aprobada' - SQLITE_CONSTRAINT: La propuesta no está completa: faltan sesiones por asignar", "extensions": {"code": "INTERNAL_SERVER_ERROR"}}]})
    r = client.post("/propuestas/1/aprobar", headers=admin)
    assert r.status_code == 409 and "no está completa" in r.json()["detail"]


def test_modulo_predictivo_es_solo_esqueleto(client, directus, admin):
    directus.items["identidad_rol_permiso"].append({"id": 98, "rol": "administrador", "permiso": "proyeccion.ver", "revocado_en": None})
    client.app.state.cache_roles.vaciar()
    r = client.get("/proyeccion/estado", headers=admin)
    assert r.status_code == 200 and r.json()["implementado"] is False
