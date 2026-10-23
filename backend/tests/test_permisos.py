"""Permisos por rol y por departamento, borrado lógico y auditoría de cambios de permisos."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.core import security
from app.core.db import conectar
from app.main import create_app
from app.seed import ADMIN_EMAIL, PRUEBA_EMAIL

from .conftest import CLAVE_ADMIN, cabecera, entrar, hacer_settings

CLAVE_ED = "Clave-ED-de-prueba-33"


def crear_ed(db, email, depto_id, rol="encargado_docente"):
    uid = db.execute("INSERT INTO identidad_usuario (email, nombre, hash_clave) VALUES (?, ?, ?)",
                     (email, "ED prueba", security.hashear_clave(CLAVE_ED))).lastrowid
    db.execute("INSERT INTO identidad_usuario_rol (usuario_id, rol, departamento_id) VALUES (?, ?, ?)", (uid, rol, depto_id))
    return uid


@pytest.fixture
def dos_departamentos(client, db):
    db.execute("INSERT INTO identidad_departamento (codigo, nombre) VALUES ('DMAT', 'Departamento de prueba')")
    crear_ed(db, "ed.disc@ejemplo.invalid", 1)
    crear_ed(db, "ed.dmat@ejemplo.invalid", 2)
    return (cabecera(entrar(client, "ed.disc@ejemplo.invalid", CLAVE_ED)),
            cabecera(entrar(client, "ed.dmat@ejemplo.invalid", CLAVE_ED)))


def test_seed_tiene_al_encargado_docente_con_todos_los_permisos(client, admin):
    perfil = client.get("/auth/yo", headers=admin).json()
    assert perfil["email"] == ADMIN_EMAIL and perfil["nombre"] == "Encargado Docente"
    assert len(perfil["permisos"]) == 18 and all(None in d for d in perfil["permisos"].values())


def test_el_departamento_disc_existe_por_defecto(db):
    assert db.execute("SELECT codigo, predeterminado FROM identidad_departamento WHERE id = 1").fetchone()[:] == ("DISC", 1)


def test_el_seed_es_idempotente(db):
    from app.seed import sembrar
    assert sembrar(db, "otra-clave-12345", "otra-clave-12345") == {}
    assert db.execute("SELECT count(*) FROM identidad_usuario").fetchone()[0] == 2


def test_usuario_de_consulta_ve_pero_no_edita(client, consulta, db):
    assert client.get("/salas", headers=consulta).status_code == 200
    r = client.post("/salas", headers=consulta, json={"codigo": "X-1"})
    assert r.status_code == 403
    d = db.execute("SELECT * FROM plataforma_auditoria WHERE accion = 'acceso_denegado'").fetchone()
    assert d["usuario_id"] == 2 and d["ip"] == "testclient" and d["resultado"] == "denegado"


def test_consulta_no_ve_datos_personales_ni_finanzas_ni_usuarios(client, consulta):
    assert client.get("/personas", headers=consulta).status_code == 403
    assert client.get("/tarifas", headers=consulta).status_code == 403
    assert client.get("/usuarios", headers=consulta).status_code == 403
    assert client.get("/roles", headers=consulta).status_code == 403


def test_administrador_gestiona_datos_personales_con_rut_validado(client, admin):
    ok = client.post("/personas", headers=admin, json={"rut": "12345678-5", "nombre": "Persona Ficticia"})
    assert ok.status_code == 201
    malo = client.post("/personas", headers=admin, json={"rut": "12345678-9", "nombre": "Otra Ficticia"})
    assert malo.status_code == 409 and "RUT" in malo.json()["detail"]


def test_un_departamento_no_edita_los_horarios_de_otro(client, dos_departamentos, db):
    ed_disc, ed_dmat = dos_departamentos
    periodo = client.post("/periodos", headers=ed_disc, json={"codigo": "202620"}).json()["id"]
    asig = client.post("/asignaturas", headers=ed_disc, json={"nombre": "Asignatura de prueba"}).json()["id"]
    par = client.post("/paralelos", headers=ed_disc, json={"periodo_id": periodo, "asignatura_id": asig, "codigo": "C1"})
    assert par.status_code == 201
    pid = par.json()["id"]
    # el ED de DMAT lee solo lo suyo y no puede tocar lo del DISC
    assert client.get("/paralelos", headers=ed_dmat).json() == []
    assert client.get(f"/paralelos/{pid}", headers=ed_dmat).status_code == 404
    assert client.patch(f"/paralelos/{pid}", headers=ed_dmat, json={"observacion": "x"}).status_code == 403
    assert client.delete(f"/paralelos/{pid}", headers=ed_dmat).status_code == 403
    assert client.post("/periodos", headers=ed_dmat, json={"codigo": "202620", "departamento_id": 1}).status_code == 403
    assert client.post("/paralelos", headers=ed_dmat, json={"periodo_id": periodo, "asignatura_id": asig, "codigo": "Z"}).status_code == 403
    assert db.execute("SELECT count(*) FROM plataforma_auditoria WHERE resultado = 'denegado' AND accion = 'acceso_denegado'").fetchone()[0] >= 4
    # el del DISC sí edita lo suyo
    assert client.patch(f"/paralelos/{pid}", headers=ed_disc, json={"observacion": "ok"}).status_code == 204


def test_no_se_puede_mover_un_dato_a_otro_departamento_sin_permiso(client, dos_departamentos):
    ed_disc, _ = dos_departamentos
    sid = client.post("/salas", headers=ed_disc, json={"codigo": "S-1"}).json()["id"]
    assert client.patch(f"/salas/{sid}", headers=ed_disc, json={"departamento_id": 2}).status_code == 403


def test_aprobar_horarios_de_otro_departamento_lo_frena_el_trigger(client, dos_departamentos, db):
    ed_disc, ed_dmat = dos_departamentos
    pid = client.post("/periodos", headers=ed_disc, json={"codigo": "202620"}).json()["id"]
    db.execute("INSERT INTO horarios_propuesta (periodo_id, nombre, completa) VALUES (?, 'p1', 1)", (pid,))
    r = client.post("/propuestas/1/aprobar", headers=ed_dmat)
    assert r.status_code == 403
    assert db.execute("SELECT estado FROM horarios_propuesta WHERE id = 1").fetchone()[0] != "aprobada"


def test_modulo_financiero_con_su_permiso(client, admin, consulta):
    assert client.get("/presupuestos", headers=admin).status_code == 200
    assert client.get("/presupuestos", headers=consulta).status_code == 403


# ---- borrado lógico -------------------------------------------------------------------------
def test_delete_marca_eliminado_y_las_consultas_lo_excluyen(client, admin, db):
    sid = client.post("/salas", headers=admin, json={"codigo": "SD-1", "nombre": "Sala de prueba"}).json()["id"]
    assert client.delete(f"/salas/{sid}", headers=admin).status_code == 204
    fila = db.execute("SELECT eliminado_en, eliminado_por FROM catalogo_sala WHERE id = ?", (sid,)).fetchone()
    assert fila["eliminado_en"] and fila["eliminado_por"] == 1          # la fila sigue en la base
    assert client.get(f"/salas/{sid}", headers=admin).status_code == 404
    assert sid not in [s["id"] for s in client.get("/salas", headers=admin).json()]
    assert client.delete(f"/salas/{sid}", headers=admin).status_code == 404
    assert client.patch(f"/salas/{sid}", headers=admin, json={"nombre": "x"}).status_code == 404


def test_un_delete_real_lo_bloquea_el_trigger(db):
    db.execute("INSERT INTO catalogo_sala (codigo) VALUES ('SD-2')")
    with pytest.raises(sqlite3.IntegrityError, match="Borrado lógico"):
        db.execute("DELETE FROM catalogo_sala WHERE codigo = 'SD-2'")


def test_la_api_nunca_emite_delete_en_las_tablas_del_nucleo():
    import pathlib, re
    codigo = "\n".join(p.read_text() for p in pathlib.Path("app").rglob("*.py"))
    assert not re.search(r"DELETE\s+FROM\s+(?!identidad_sesion|\{tabla\})", codigo)


def test_eliminar_usuario_es_logico_y_cierra_sus_sesiones(client, admin, consulta, db):
    assert client.delete("/usuarios/2", headers=admin).status_code == 204
    assert db.execute("SELECT eliminado_en FROM identidad_usuario WHERE id = 2").fetchone()[0]
    assert client.get("/auth/yo", headers=consulta).status_code == 401
    assert 2 not in [u["id"] for u in client.get("/usuarios", headers=admin).json()]
    assert client.delete("/usuarios/1", headers=admin).status_code == 409        # no la propia cuenta


# ---- cambios de permisos --------------------------------------------------------------------
def test_asignar_rol_queda_auditado_con_usuario_e_ip(client, admin, db):
    r = client.post("/usuarios/2/roles", headers=admin, json={"rol": "encargado_docente", "departamento_id": 1})
    assert r.status_code == 201
    filas = db.execute("SELECT accion, entidad, usuario_id, ip FROM plataforma_auditoria "
                       "WHERE entidad IN ('identidad_usuario_rol') OR accion = 'permisos_cambiados'").fetchall()
    assert any(f["accion"] == "permisos_cambiados" and f["usuario_id"] == 1 and f["ip"] == "testclient" for f in filas)
    assert any(f["entidad"] == "identidad_usuario_rol" and f["accion"] == "insert" and f["usuario_id"] == 1 and f["ip"] == "testclient" for f in filas)


def test_quitar_un_permiso_a_un_rol_se_audita_y_surte_efecto(client, admin, consulta, db):
    assert client.get("/salas", headers=consulta).status_code == 200
    assert client.delete("/roles/consulta/permisos/catalogo.ver", headers=admin).status_code == 204
    assert client.get("/salas", headers=consulta).status_code == 403
    assert db.execute("SELECT count(*) FROM plataforma_auditoria WHERE accion = 'permisos_cambiados'").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM plataforma_auditoria WHERE entidad = 'identidad_rol_permiso' AND accion = 'update'").fetchone()[0] == 1
    assert client.put("/roles/consulta/permisos/catalogo.ver", headers=admin).status_code == 204
    assert client.get("/salas", headers=consulta).status_code == 200


def test_el_rol_de_sistema_no_pierde_permisos(client, admin):
    assert client.delete("/roles/administrador/permisos/usuarios.gestionar", headers=admin).status_code == 409


def test_nadie_modifica_sus_propios_roles(client, admin):
    r = client.post("/usuarios/1/roles", headers=admin, json={"rol": "consulta", "departamento_id": 1})
    assert r.status_code == 409 and "propios roles" in r.json()["detail"]


def test_un_encargado_docente_no_gestiona_usuarios(client, dos_departamentos):
    ed_disc, _ = dos_departamentos
    assert client.get("/usuarios", headers=ed_disc).status_code == 403
    assert client.post("/usuarios/2/roles", headers=ed_disc, json={"rol": "consulta", "departamento_id": 1}).status_code == 403


def test_crear_usuario_aplica_la_politica_de_claves(client, admin, db):
    assert client.post("/usuarios", headers=admin, json={"email": "nuevo@ejemplo.invalid", "nombre": "N", "clave": "corta"}).status_code == 422
    r = client.post("/usuarios", headers=admin, json={"email": "Nuevo@ejemplo.invalid", "nombre": "N", "clave": "Clave-Nueva-larga-5"})
    assert r.status_code == 201 and r.json()["email"] == "nuevo@ejemplo.invalid"
    assert client.post("/usuarios", headers=admin, json={"email": "nuevo@ejemplo.invalid", "nombre": "N", "clave": "Clave-Nueva-larga-5"}).status_code == 409
    assert "hash_clave" not in str(db.execute("SELECT despues FROM plataforma_auditoria WHERE entidad='identidad_usuario' AND accion='insert' ORDER BY id DESC").fetchone()[0])


# ---- módulos por configuración ---------------------------------------------------------------
def test_los_modulos_se_activan_por_configuracion(tmp_path):
    solo_base = TestClient(create_app(hacer_settings(tmp_path / "a" if False else tmp_path, modulos=("base",))))
    assert solo_base.get("/health").json()["modulos"] == ["base"]
    assert solo_base.get("/tarifas").status_code == 404 and solo_base.get("/proyeccion/estado").status_code == 404


def test_sin_modulo_base_no_arranca(tmp_path):
    with pytest.raises(RuntimeError, match="base"):
        create_app(hacer_settings(tmp_path, modulos=("financiero",)))


def test_modulo_predictivo_es_solo_esqueleto(client, admin):
    r = client.get("/proyeccion/estado", headers=admin)
    assert r.status_code == 200 and r.json()["implementado"] is False
