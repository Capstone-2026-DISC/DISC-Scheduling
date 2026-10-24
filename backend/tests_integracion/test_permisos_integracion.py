"""Permisos por rol y departamento, aplicados por Directus; borrado lógico; aprobación; usuarios."""
import os

import httpx

from .conftest import ADMIN, API, DIRECTUS, cab, crear_usuario, entrar, periodo_codigo, unico


def test_consulta_lee_pero_no_escribe_y_el_intento_queda_auditado(api, consulta, boot):
    assert api.get("/salas", headers=consulta).status_code == 200
    assert api.post("/salas", headers=consulta, json={"codigo": unico("X")}).status_code == 403
    assert api.get("/personas", headers=consulta).status_code == 403
    assert api.get("/tarifas", headers=consulta).status_code == 403
    assert api.get("/usuarios", headers=consulta).status_code == 403
    ev = boot.get("/items/plataforma_auditoria", params={"filter[accion][_eq]": "acceso_denegado", "sort": "-id", "limit": 1, "fields": "usuario_id,ip,resultado"}).json()["data"][0]
    assert ev["resultado"] == "denegado" and ev["usuario_id"] and ev["ip"]


def test_directus_tambien_rechaza_a_consulta_si_se_salta_la_api(consulta):
    """Los permisos no dependen de la API: con la sesión de consulta, Directus mismo dice que no."""
    t = httpx.post(DIRECTUS + "/auth/login", json={"email": "usuario.prueba@example.com", "password": os.environ["SEED_TEST_PASSWORD"], "mode": "json"}).json()["data"]["access_token"]
    h = {"Authorization": f"Bearer {t}"}
    assert httpx.post(DIRECTUS + "/items/catalogo_sala", headers=h, json={"codigo": unico("Z")}).status_code == 403
    assert httpx.patch(DIRECTUS + "/items/catalogo_sala/1", headers=h, json={"nombre": "x"}).status_code == 403
    assert httpx.delete(DIRECTUS + "/items/catalogo_sala/1", headers=h).status_code == 403
    assert httpx.get(DIRECTUS + "/items/catalogo_persona", headers=h).status_code == 403


def test_un_departamento_no_ve_ni_edita_lo_de_otro(api, ed_disc, ed_dmat, depto2):
    cod = unico("SD")
    sala = api.post("/salas", headers=ed_disc, json={"codigo": cod, "nombre": "Del DISC"}).json()["id"]
    assert api.get(f"/salas/{sala}", headers=ed_disc).json()["departamento_id"] == 1                  # el preset fija el departamento
    assert cod not in [s["codigo"] for s in api.get("/salas", headers=ed_dmat).json()]
    assert api.get(f"/salas/{sala}", headers=ed_dmat).status_code == 404
    assert api.patch(f"/salas/{sala}", headers=ed_dmat, json={"nombre": "robada"}).status_code == 404
    assert api.delete(f"/salas/{sala}", headers=ed_dmat).status_code == 404
    assert api.get(f"/salas/{sala}", headers=ed_disc).json()["nombre"] == "Del DISC"
    # y no puede escribir en el departamento ajeno ni mover lo suyo allá
    assert api.post("/salas", headers=ed_dmat, json={"codigo": unico("SX"), "departamento_id": 1}).status_code == 403
    propia = api.post("/salas", headers=ed_dmat, json={"codigo": unico("SM")}).json()["id"]
    assert api.get(f"/salas/{propia}", headers=ed_dmat).json()["departamento_id"] == depto2          # omitir el departamento no lo manda al DISC
    assert api.patch(f"/salas/{propia}", headers=ed_dmat, json={"departamento_id": 1}).status_code == 403


def test_lo_que_cuelga_de_un_periodo_hereda_su_departamento(api, ed_disc, ed_dmat):
    periodo = api.post("/periodos", headers=ed_disc, json={"codigo": periodo_codigo("10")}).json()["id"]
    asig = api.post("/asignaturas", headers=ed_disc, json={"nombre": unico("Asig")}).json()["id"]
    par = api.post("/paralelos", headers=ed_disc, json={"periodo_id": periodo, "asignatura_id": asig, "codigo": "C1"})
    assert par.status_code == 201
    pid = par.json()["id"]
    assert api.get(f"/paralelos/{pid}", headers=ed_dmat).status_code == 404
    assert api.patch(f"/paralelos/{pid}", headers=ed_dmat, json={"observacion": "x"}).status_code == 404
    assert api.post("/paralelos", headers=ed_dmat, json={"periodo_id": periodo, "asignatura_id": asig, "codigo": "Z"}).status_code == 403
    assert api.post("/sesiones", headers=ed_dmat, json={"paralelo_id": pid, "numero": 1}).status_code == 403
    assert api.post("/sesiones", headers=ed_disc, json={"paralelo_id": pid, "numero": 1}).status_code == 201


def test_eliminar_es_logico_y_el_borrado_real_esta_bloqueado(api, admin, boot):
    sala = api.post("/salas", headers=admin, json={"codigo": unico("SB")}).json()["id"]
    assert api.delete(f"/salas/{sala}", headers=admin).status_code == 204
    assert api.get(f"/salas/{sala}", headers=admin).status_code == 404
    assert sala not in [s["id"] for s in api.get("/salas", headers=admin).json()]
    assert api.delete(f"/salas/{sala}", headers=admin).status_code == 404
    fila = boot.get(f"/items/catalogo_sala/{sala}").json()["data"]
    assert fila["eliminado_en"] and fila["eliminado_por"]                                 # la fila sigue en la base
    r = boot.delete(f"/items/catalogo_sala/{sala}")                                       # ni el administrador de Directus la borra
    assert r.status_code >= 400 and "Borrado lógico" in r.text
    assert boot.get(f"/items/catalogo_sala/{sala}").json()["data"]["id"] == sala


def test_aprobacion_de_horarios_con_las_reglas_de_la_base(api, ed_disc, ed_dmat, consulta, boot):
    periodo = api.post("/periodos", headers=ed_disc, json={"codigo": periodo_codigo("20")}).json()["id"]
    perfil = boot.get("/items/horarios_perfil", params={"fields": "id", "limit": 1}).json()["data"][0]["id"]
    corrida = boot.post("/items/horarios_corrida", params={"fields": "id"}, json={"periodo_id": periodo, "perfil_id": perfil, "semilla": "[1,2,3,4,5,6]", "estado": "completa", "restricciones_usadas": "[]"}).json()["data"]["id"]
    inc = boot.post("/items/horarios_propuesta", params={"fields": "id"}, json={"periodo_id": periodo, "corrida_id": corrida, "nombre": "incompleta", "completa": 0}).json()["data"]["id"]
    ok = boot.post("/items/horarios_propuesta", params={"fields": "id"}, json={"periodo_id": periodo, "corrida_id": corrida, "nombre": "completa", "completa": 1}).json()["data"]["id"]
    assert api.post(f"/propuestas/{ok}/aprobar", headers=consulta).status_code == 403          # sin horarios.aprobar
    assert api.post(f"/propuestas/{ok}/aprobar", headers=ed_dmat).status_code == 404            # es de otro departamento
    r = api.post(f"/propuestas/{inc}/aprobar", headers=ed_disc)
    assert r.status_code == 409 and "no está completa" in r.json()["detail"]
    assert api.post(f"/propuestas/{ok}/aprobar", headers=ed_disc).status_code == 204
    fila = boot.get(f"/items/horarios_propuesta/{ok}").json()["data"]
    assert fila["estado"] == "aprobada" and fila["aprobada_por"] and fila["aprobada_en"]


def test_gestion_de_usuarios_y_reglas_de_roles(api, admin, ed_disc):
    assert api.get("/usuarios", headers=ed_disc).status_code == 403                             # el encargado no gestiona usuarios
    h, email, uid = crear_usuario(api, admin, "consulta", 1)
    usuarios = {u["email"]: u for u in api.get("/usuarios", headers=admin).json()}
    assert usuarios[email]["rol"] == "consulta" and usuarios[email]["departamento_id"] == 1
    yo = api.get("/auth/yo", headers=admin).json()["id"]
    assert api.post(f"/usuarios/{yo}/roles", headers=admin, json={"rol": "consulta", "departamento_id": 1}).status_code == 409
    assert api.delete(f"/usuarios/{yo}", headers=admin).status_code == 409
    assert api.post(f"/usuarios/{uid}/roles", headers=admin, json={"rol": "inventado"}).status_code == 422
    assert api.delete(f"/usuarios/{uid}/roles", headers=admin).status_code == 204
    assert api.get("/auth/yo", headers=h).status_code == 403                                    # sin rol ya no es de la plataforma
    assert api.delete(f"/usuarios/{uid}", headers=admin).status_code == 204
    assert email not in [u["email"] for u in api.get("/usuarios", headers=admin).json()]
    assert api.post("/auth/login", json={"email": email, "clave": "Clave-Larga-De-Prueba-77x"}).status_code == 401   # suspendido


def test_los_roles_y_sus_permisos(api, admin):
    roles = {r["codigo"]: r for r in api.get("/roles", headers=admin).json()}
    assert len(roles["administrador"]["permisos"]) == 18 and len(roles["encargado_docente"]["permisos"]) == 15 and len(roles["consulta"]["permisos"]) == 3
