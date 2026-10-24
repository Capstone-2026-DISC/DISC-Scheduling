"""Cifrado del RUT y el correo: formato, claves, índice ciego, qué hay realmente en el archivo y en la auditoría."""
import base64

import pytest

from app.core import pii
from app.main import create_app

from .conftest import CLAVE_DATOS, CLAVE_INDICE, hacer_settings

RUT, EMAIL = "59999999-K", "persona.ficticia@ejemplo.invalid"


def k(byte: bytes) -> str:
    return base64.urlsafe_b64encode(byte * 32).decode().rstrip("=")


@pytest.fixture
def cif():
    return pii.Cifrador.desde_entorno(CLAVE_DATOS, "k1", CLAVE_INDICE)


# ---- el cifrador ------------------------------------------------------------------------------
def test_ida_y_vuelta_con_formato_versionado_y_nonce_distinto(cif):
    a, b = cif.cifrar(RUT, pii.COL_RUT), cif.cifrar(RUT, pii.COL_RUT)
    assert a.startswith("v1:k1:") and a != b and RUT not in a
    assert cif.descifrar(a, pii.COL_RUT) == cif.descifrar(b, pii.COL_RUT) == RUT


def test_un_texto_cifrado_no_se_traspasa_a_otra_columna(cif):
    guardado = cif.cifrar(RUT, pii.COL_RUT)
    with pytest.raises(pii.DatoAlterado):
        cif.descifrar(guardado, pii.COL_EMAIL)


def test_un_dato_manipulado_o_con_otra_clave_se_rechaza(cif):
    guardado = cif.cifrar(EMAIL, pii.COL_EMAIL)
    manipulado = guardado[:-3] + ("AAA" if not guardado.endswith("AAA") else "BBB")
    with pytest.raises(pii.DatoAlterado):
        cif.descifrar(manipulado, pii.COL_EMAIL)
    otra = pii.Cifrador.desde_entorno("k1=" + k(b"C"), "k1", CLAVE_INDICE)
    with pytest.raises(pii.DatoAlterado):
        otra.descifrar(guardado, pii.COL_EMAIL)
    for roto in ("", "v2:k1:xx", "v1:zz:xx", "no-cifrado"):
        with pytest.raises(pii.DatoAlterado):
            cif.descifrar(roto, pii.COL_EMAIL)


def test_el_rut_se_normaliza_y_valida():
    assert pii.normalizar_rut("12.345.678-5") == pii.normalizar_rut("123456785") == "12345678-5"
    assert pii.normalizar_rut(" 5.999.999-k ") == "5999999-K"
    assert pii.rut_valido("59999999-K") and pii.rut_valido("59.999.999-k")
    assert not pii.rut_valido("59999999-1") and not pii.rut_valido("1234") and not pii.rut_valido("")


def test_indice_ciego_estable_normalizado_y_atado_a_la_clave(cif):
    assert cif.indice_rut("59.999.999-k") == cif.indice_rut("59999999-K") and len(cif.indice_rut(RUT)) == 64
    assert cif.indice_rut("59999998-1") != cif.indice_rut(RUT)
    otra = pii.Cifrador.desde_entorno(CLAVE_DATOS, "k1", k(b"D"))
    assert otra.indice_rut(RUT) != cif.indice_rut(RUT)           # sin la clave no se puede recalcular el índice


def test_claves_mal_formadas_no_arrancan():
    with pytest.raises(pii.ClaveFaltante):
        pii.Cifrador.desde_entorno("k1=corta", "k1", CLAVE_INDICE)
    with pytest.raises(pii.ClaveFaltante):
        pii.Cifrador.desde_entorno(CLAVE_DATOS, "k9", CLAVE_INDICE)                       # id que no existe
    with pytest.raises(pii.ClaveFaltante):
        pii.Cifrador.desde_entorno(CLAVE_DATOS, "k1", CLAVE_DATOS.split("=")[1])         # índice igual a la de cifrado
    with pytest.raises(pii.ClaveFaltante):
        pii.Cifrador.desde_entorno("", "k1", CLAVE_INDICE)


def test_la_app_no_arranca_sin_claves_de_cifrado():
    with pytest.raises(pii.ClaveFaltante):
        create_app(hacer_settings(data_keys="", index_key=""))


def test_enmascarar(cif):
    assert cif.enmascarar_rut("59999999-K") == "*****999-K"
