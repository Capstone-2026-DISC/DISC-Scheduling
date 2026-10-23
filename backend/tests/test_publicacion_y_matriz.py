"""Réplica para satélites sin datos personales, matriz de Directus coherente con el esquema y cambios sin firma."""
import sqlite3

from app import directus_matriz as m
from app.core.db import conectar
from app.publicacion import COPIAS, publicar

from .conftest import cabecera, insertar_persona


def sembrar_horario(db, settings=None):
    db.execute("INSERT INTO catalogo_periodo (codigo) VALUES ('202620')")
    db.execute("INSERT INTO catalogo_asignatura (codigo, nombre) VALUES ('FAIC-00001', 'Asignatura de prueba')")
    insertar_persona(db, settings, "12345678-5", "Persona Ficticia", "p@ejemplo.invalid")
    db.execute("INSERT INTO horarios_paralelo (periodo_id, asignatura_id, codigo) VALUES (1, 1, 'C1')")
    db.execute("INSERT INTO horarios_sesion (paralelo_id, numero) VALUES (1, 1)")
    db.execute("INSERT INTO horarios_corrida (periodo_id, perfil_id, semilla, estado, restricciones_usadas) "
               "VALUES (1, 1, '[1,2,3,4,5,6]', 'completa', '[]')")
    db.execute("INSERT INTO horarios_propuesta (periodo_id, corrida_id, nombre, completa) VALUES (1, 1, 'borrador', 1), (1, 1, 'aprobada', 1)")
    db.execute("INSERT INTO horarios_asignacion (propuesta_id, sesion_id, dia, bloque, sala_id) VALUES (1, 1, 'Lu', 'A', 1)")
    db.execute("INSERT INTO horarios_asignacion (propuesta_id, sesion_id, dia, bloque, sala_id) VALUES (2, 1, 'Ma', 'B', 2)")
    db.execute("UPDATE horarios_propuesta SET estado = 'aprobada' WHERE id = 2")


def test_la_replica_solo_lleva_el_horario_aprobado_y_ningun_dato_personal(db, settings, tmp_path):
    sembrar_horario(db, settings)
    ruta = str(tmp_path / "sat.db")
    cuentas = publicar(db, ruta)
    assert cuentas["pub_horario"] == 1
    sat = sqlite3.connect(ruta)
    assert sat.execute("SELECT dia, bloque FROM pub_horario").fetchall() == [("Ma", "B")]     # no el borrador
    tablas = {r[0] for r in sat.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert all(t.startswith("pub_") for t in tablas)
    volcado = "\n".join(str(fila) for t in tablas for fila in sat.execute(f"SELECT * FROM {t}"))
    for prohibido in ("12345678", "Persona Ficticia", "ejemplo.invalid", "hash_clave", "argon2"):
        assert prohibido not in volcado


def test_publicar_es_repetible_y_reemplaza(db, settings, tmp_path):
    sembrar_horario(db, settings)
    ruta = str(tmp_path / "sat.db")
    publicar(db, ruta)
    assert publicar(db, ruta) == publicar(db, ruta)


def test_la_publicacion_por_api_pide_permiso_y_audita(client, admin, consulta, db, tmp_path, monkeypatch):
    monkeypatch.setenv("SATELITES_DB_PATH", str(tmp_path / "sat.db"))
    assert client.post("/publicacion", headers=consulta).status_code == 403
    r = client.post("/publicacion", headers=admin)
    assert r.status_code == 200 and "pub_sala" in r.json()["publicado"]
    assert db.execute("SELECT count(*) FROM plataforma_auditoria WHERE accion = 'publicacion_satelites'").fetchone()[0] == 1


def test_ninguna_tabla_publicada_nombra_columnas_sensibles():
    for consulta in COPIAS.values():
        for tabla in ("catalogo_persona", "identidad_", "finanzas_", "plataforma_auditoria", "catalogo_docente", "catalogo_ayudante"):
            assert tabla not in consulta


# ---- matriz de Directus ----------------------------------------------------------------------
def test_la_matriz_cubre_los_18_permisos_del_esquema(db):
    todos = {f[0] for f in db.execute("SELECT codigo FROM identidad_permiso")}
    assert len(todos) == 18
    cubiertos = set(m.LECTURA) | set(m.ESCRITURA_POR_API) | {m.PERMISO_GLOBAL}
    assert todos <= cubiertos, f"permisos sin tratamiento en la matriz: {sorted(todos - cubiertos)}"


def test_la_matriz_solo_menciona_tablas_que_existen(db):
    info = m.esquema(db)
    for tablas in m.LECTURA.values():
        for t in tablas:
            assert t in info, t


def test_toda_tabla_del_nucleo_tiene_clave_simple_para_directus(db):
    for t in m.esquema(db):
        pks = [c for c in db.execute(f"PRAGMA table_info({t})") if c["pk"]]
        assert len(pks) == 1, f"{t} tiene clave compuesta; Directus la ignoraría"


def test_alcance_por_departamento_derivado_de_las_claves(db):
    info = m.esquema(db)
    assert m.filtro_departamento(info, "catalogo_sala") == {"departamento_id": {"_eq": "$CURRENT_USER.departamento_id"}}
    f = m.filtro_departamento(info, "horarios_sesion")                  # sesion -> paralelo -> periodo -> departamento
    assert "paralelo_id" in f and "periodo_id" in f["paralelo_id"]
    assert m.filtro_departamento(info, "catalogo_dia") is None


def test_permisos_de_lectura_por_rol(db):
    info = m.esquema(db)
    cons = {p["collection"]: p for p in m.permisos_de_lectura(info, {"catalogo.ver", "horarios.ver", "restricciones.ver"})}
    assert "catalogo_sala" in cons and "finanzas_tarifa" not in cons and "catalogo_persona" not in cons
    assert "eliminado_en" in str(cons["catalogo_sala"]["permissions"])           # lo borrado no se ve
    assert "departamento_id" in str(cons["catalogo_sala"]["permissions"])        # y se limita a su departamento
    admin = {p["collection"]: p for p in m.permisos_de_lectura(info, {"catalogo.ver", "usuarios.gestionar", m.PERMISO_GLOBAL})}
    assert "departamento_id" not in str(admin["catalogo_sala"]["permissions"])   # global: sin filtro de departamento
    assert "hash_clave" not in admin["identidad_usuario"]["fields"]
    assert all(p["action"] == "read" for p in admin.values())                    # el núcleo se escribe solo por la API
    assert "identidad_sesion" not in admin


def test_nunca_hay_cambios_sin_usuario_si_se_usa_la_api(client, admin, db):
    client.post("/salas", headers=admin, json={"codigo": "ZZ-1"})
    client.post("/usuarios", headers=admin, json={"email": "otro@ejemplo.invalid", "nombre": "O", "clave": "Clave-Nueva-larga-5"})
    assert db.execute("SELECT count(*) FROM plataforma_v_cambios_sin_usuario").fetchone()[0] == 0


def test_una_escritura_por_fuera_de_la_api_queda_a_la_vista(db):
    db.execute("INSERT INTO catalogo_sala (codigo) VALUES ('FUERA-1')")          # como haría Directus: sin contexto
    fila = db.execute("SELECT entidad, accion FROM plataforma_v_cambios_sin_usuario").fetchone()
    assert tuple(fila) == ("catalogo_sala", "insert")
