"""Traducción de los errores de Directus y piezas del núcleo que no dependen de él."""

import time

import pytest
from app.core.cache import Cache
from app.core.deps import Usuario
from app.core.directus import Respuesta, exigir, traducir
from app.core.ratelimit import LimiteTasa
from app.core.security import clave_valida
from fastapi import HTTPException


def err(estado, mensaje="", codigo=""):
    return Respuesta(estado, {"errors": [{"message": mensaje, "extensions": {"code": codigo}}]})


@pytest.mark.parametrize(
    "r,esperado",
    [
        (err(401), 401),
        (err(403), 403),
        (err(404), 404),
        (err(429), 429),
        (err(400, 'Value "x" for field "codigo" has to be unique.', "RECORD_NOT_UNIQUE"), 409),
        (
            err(400, 'Validation failed for field "departamento_id". Value has to be one of "1".', "FAILED_VALIDATION"),
            403,
        ),
        (err(400, 'Validation failed for field "capacidad".', "FAILED_VALIDATION"), 422),
        (
            err(
                500, "insert into x - SQLITE_CONSTRAINT: CHECK constraint failed: codigo GLOB", "INTERNAL_SERVER_ERROR"
            ),
            409,
        ),
        (err(400, "otra cosa"), 422),
        (err(502), 502),
    ],
)
def test_cada_error_de_directus_tiene_su_codigo_http(r, esperado):
    assert traducir(r).status_code == esperado


def test_el_mensaje_de_un_trigger_llega_al_usuario_sin_el_sql():
    e = traducir(
        err(
            500,
            "update `horarios_propuesta` set `estado` = 'aprobada' - SQLITE_CONSTRAINT: La propuesta no está completa",
            "INTERNAL_SERVER_ERROR",
        )
    )
    assert (
        e.status_code == 409
        and e.detail == "No se pudo guardar: La propuesta no está completa"
        and "update" not in e.detail
    )


def test_un_403_al_leer_una_fila_es_un_404_para_no_revelar_que_existe():
    assert traducir(err(403), lectura_de_uno=True).status_code == 404


def test_exigir_deja_pasar_lo_exitoso_y_lanza_lo_demas():
    assert exigir(Respuesta(200, {"data": 1})).datos == 1
    with pytest.raises(HTTPException):
        exigir(err(403))


def test_cache_vence_y_olvida():
    c = Cache(0.05)
    c.poner("a", 1)
    assert c.obtener("a") == 1
    time.sleep(0.07)
    assert c.obtener("a") is None
    c.poner("b", 2)
    c.olvidar("b")
    assert c.obtener("b") is None


def test_limite_de_tasa_por_clave():
    limite = LimiteTasa(2, ventana_s=60)
    assert [limite.permitir("ip1"), limite.permitir("ip1"), limite.permitir("ip1"), limite.permitir("ip2")] == [
        True,
        True,
        False,
        True,
    ]


@pytest.mark.parametrize(
    "clave,motivo",
    [
        ("corta1A", "12"),
        ("soloLetrasLargasSinNumeros", "mezclar"),
        ("123456789012345", "mezclar"),
        ("conelcorreo-usuario-9", "correo"),
    ],
)
def test_politica_de_claves(clave, motivo):
    assert motivo in clave_valida(clave, "usuario@example.com", 12)


def test_una_clave_razonable_pasa():
    assert clave_valida("Una-clave-razonable-93", "usuario@example.com", 12) is None


def test_alcance_por_departamento_de_un_usuario():
    persona = Usuario("u", 1, "e@x", "E", "consulta", 3, {"catalogo.ver"})
    assert persona.departamentos("catalogo.ver") == {3} and persona.departamentos("catalogo.editar") == set()
    assert (
        persona.puede_en("catalogo.ver", 3)
        and not persona.puede_en("catalogo.ver", 1)
        and not persona.puede_en("catalogo.ver", None)
    )
    todo = Usuario("u", 1, "e@x", "E", "administrador", None, {"catalogo.ver", "departamentos.ver_otros"})
    assert todo.global_ and todo.departamentos("catalogo.ver") is None and todo.puede_en("catalogo.ver", 99)
    sin_depto = Usuario("u", 1, "e@x", "E", "consulta", None, {"catalogo.ver"})
    assert sin_depto.departamentos("catalogo.ver") == set()  # sin departamento y sin ver_otros: no ve nada
