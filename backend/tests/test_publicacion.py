"""Réplica para satélites: se lee del núcleo por Directus y no lleva ningún dato personal."""
import sqlite3

import httpx

from app.core.directus import Directus
from app.publicacion import ORDEN, extraer, publicar

from .conftest import eventos


def sembrar(directus):
    it = directus.items
    it["catalogo_periodo"] += [{"id": 1, "codigo": "202620", "estado": "vigente", "departamento_id": 1},
                               {"id": 2, "codigo": "202620", "estado": "vigente", "departamento_id": 2}]
    it["catalogo_programa"].append({"id": 1, "codigo": "P1", "nombre": "Programa", "tipo": "pregrado", "departamento_id": 1, "eliminado_en": None})
    it["catalogo_asignatura"].append({"id": 1, "codigo": "FAIC-00001", "nombre": "Asignatura", "area": "A", "requiere_laboratorio": 0, "departamento_id": 1, "eliminado_en": None})
    it["catalogo_sala"] += [{"id": 1, "codigo": "S-1", "nombre": "Sala", "capacidad": 30, "es_laboratorio": 0, "activa": 1, "departamento_id": 1, "eliminado_en": None},
                            {"id": 2, "codigo": "S-OFF", "nombre": "Inactiva", "capacidad": 5, "es_laboratorio": 0, "activa": 0, "departamento_id": 1, "eliminado_en": None}]
    it["horarios_paralelo"] += [{"id": 1, "periodo_id": 1, "asignatura_id": 1, "codigo": "C1", "nrc": 5, "componente": "catedra", "cupo_estimado": 30, "eliminado_en": None},
                                {"id": 2, "periodo_id": 2, "asignatura_id": 1, "codigo": "OTRO", "nrc": 6, "componente": "catedra", "cupo_estimado": 1, "eliminado_en": None}]
    it["horarios_sesion"].append({"id": 1, "paralelo_id": 1, "numero": 1, "eliminado_en": None})
    it["horarios_propuesta"] += [{"id": 1, "periodo_id": 1, "estado": "borrador"}, {"id": 2, "periodo_id": 1, "estado": "aprobada"}]
    it["horarios_asignacion"] += [{"id": 1, "propuesta_id": 1, "sesion_id": 1, "dia": "Lu", "bloque": "A", "sala_id": 1},
                                  {"id": 2, "propuesta_id": 2, "sesion_id": 1, "dia": "Ma", "bloque": "B", "sala_id": 1}]
    it["catalogo_persona"].append({"id": 1, "rut_cifrado": "v1:k1:AAAA", "rut_indice": "a" * 64, "nombre": "Persona Ficticia", "email_cifrado": "v1:k1:BBBB"})


def cliente(directus):
    return Directus("http://directus.test", "s" * 40, transport=httpx.MockTransport(directus))


def test_solo_va_el_horario_aprobado_del_departamento_publicado(directus):
    sembrar(directus)
    d = extraer(cliente(directus))
    assert d["pub_horario"] == [(2, 1, 1, "Ma", "B", "S-1")]                      # no el borrador
    assert [p[0] for p in d["pub_paralelo"]] == [1] and [p[0] for p in d["pub_periodo"]] == [1]
    assert [s[1] for s in d["pub_sala"]] == ["S-1"]                                 # sin la sala inactiva


def test_nunca_se_consultan_colecciones_con_datos_personales(directus):
    sembrar(directus)
    extraer(cliente(directus))
    pedidas = {r.split("/")[2] for m, r, *_ in directus.llamadas if r.startswith("/items/")}
    assert pedidas.isdisjoint({"catalogo_persona", "catalogo_docente", "catalogo_ayudante", "finanzas_nombramiento",
                               "finanzas_tarifa", "plataforma_auditoria", "plataforma_fila_importada", "identidad_usuario"})
    assert all(l[3] == "Bearer " + "s" * 40 for l in directus.llamadas)              # con la cuenta de servicio


def test_la_replica_no_tiene_ningun_dato_personal_y_se_puede_repetir(directus, tmp_path):
    sembrar(directus)
    ruta = str(tmp_path / "sat.db")
    cuentas = publicar(cliente(directus), ruta)
    assert cuentas["pub_horario"] == 1 and cuentas == publicar(cliente(directus), ruta)
    sat = sqlite3.connect(ruta)
    tablas = {r[0] for r in sat.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert tablas == set(ORDEN) | {"pub_estado"}
    volcado = "\n".join(str(f) for t in tablas for f in sat.execute(f"SELECT * FROM {t}"))
    for prohibido in ("Persona Ficticia", "v1:k1", "rut", "ejemplo.invalid"):
        assert prohibido not in volcado


def test_publicar_por_api_pide_permiso_y_audita(client, admin, consulta, directus, tmp_path):
    sembrar(directus)
    client.app.state.settings = client.app.state.settings.__class__(**{**client.app.state.settings.__dict__, "satelites_db_path": str(tmp_path / "s.db")})
    assert client.post("/publicacion", headers=consulta).status_code == 403
    r = client.post("/publicacion", headers=admin)
    assert r.status_code == 200 and r.json()["publicado"]["pub_horario"] == 1
    assert eventos(directus, "publicacion_satelites")[0]["usuario_id"] == 1
