"""Réplica para satélites: se lee del núcleo por Directus y no lleva ningún dato personal."""
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


def test_la_copia_se_regenera_por_directus_sin_datos_personales_y_se_puede_repetir(directus):
    sembrar(directus)
    directus.items["pub_estado"] = []
    cuentas = publicar(cliente(directus))
    assert cuentas["pub_horario"] == 1 and cuentas == publicar(cliente(directus))           # repetir no duplica
    assert directus.items["pub_horario"] == [{"id": 1, "paralelo_id": 1, "sesion": 1, "dia": "Ma", "bloque": "B", "sala_codigo": "S-1"}] or \
        [f["dia"] for f in directus.items["pub_horario"]] == ["Ma"]
    assert len(directus.items["pub_estado"]) == 1 and directus.items["pub_estado"][0]["id"] == 1
    volcado = "\n".join(str(f) for t in ORDEN for f in directus.items[t])
    for prohibido in ("Persona Ficticia", "v1:k1", "rut", "ejemplo.invalid"):
        assert prohibido not in volcado
    escritas = {r.split("/")[2] for m, r, *_ in directus.llamadas if m in ("POST", "DELETE") and r.startswith("/items/pub_")}
    assert escritas <= set(ORDEN) | {"pub_estado"}                                           # solo toca la copia


def test_publicar_por_api_pide_permiso_y_audita(client, admin, consulta, directus):
    sembrar(directus)
    assert client.post("/publicacion", headers=consulta).status_code == 403
    r = client.post("/publicacion", headers=admin)
    assert r.status_code == 200 and r.json()["publicado"]["pub_horario"] == 1
    assert eventos(directus, "publicacion_satelites")[0]["usuario_id"] == 1
