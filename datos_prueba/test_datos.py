import csv
import re
import sqlite3
import sys
from pathlib import Path

import pytest

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
import generar_datos as gd  # noqa: E402


@pytest.fixture(scope="module")
def corrida(tmp_path_factory):
    base = tmp_path_factory.mktemp("datos")
    gd.main(["--db", str(base / "a.db"), "--csv", str(base / "csv_a")])
    gd.main(["--db", str(base / "b.db"), "--csv", str(base / "csv_b")])
    return base


def test_misma_semilla_mismos_archivos(corrida):
    for archivo in (corrida / "csv_a").glob("*.csv"):
        assert archivo.read_bytes() == (corrida / "csv_b" / archivo.name).read_bytes(), archivo.name


def test_otra_semilla_da_otros_datos(tmp_path):
    gd.main(["--semilla", "7", "--db", str(tmp_path / "c.db"), "--csv", str(tmp_path / "csv")])
    assert (tmp_path / "csv" / "catalogo_persona.csv").read_text() != (
        AQUI / "csv" / "catalogo_persona.csv"
    ).read_text()


def test_la_base_cargada_es_consistente(corrida):
    con = sqlite3.connect(corrida / "a.db")
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    assert con.execute("SELECT count(*) FROM catalogo_persona").fetchone()[0] == 20


def test_los_rut_son_validos_y_estan_en_el_rango_ficticio(corrida):
    con = sqlite3.connect(corrida / "a.db")
    cif = gd.cifrador_de_prueba()
    for (cifrado,) in con.execute("SELECT rut_cifrado FROM catalogo_persona"):
        rut = cif.descifrar(cifrado, "catalogo_persona.rut")
        cuerpo, dv = rut.split("-")
        assert gd.RUT_MIN <= int(cuerpo) <= gd.RUT_MAX
        assert gd.digito_verificador(int(cuerpo)) == dv


def test_todos_los_correos_son_ejemplo_invalid_y_unicos(corrida):
    con = sqlite3.connect(corrida / "a.db")
    cif = gd.cifrador_de_prueba()
    correos = [
        cif.descifrar(c, "catalogo_persona.email") for (c,) in con.execute("SELECT email_cifrado FROM catalogo_persona")
    ]
    assert all(re.fullmatch(r"[a-z0-9.]+@ejemplo\.invalid", c) for c in correos)
    assert len(set(correos)) == len(correos)


def test_los_csv_versionados_coinciden_con_la_semilla_por_defecto(corrida):
    for archivo in (AQUI / "csv").glob("*.csv"):
        assert (
            archivo.read_bytes() == (corrida / "csv_a" / archivo.name).read_bytes()
        ), f"{archivo.name} está desactualizado"


def test_documento_advierte_que_son_datos_ficticios():
    texto = (AQUI / "DATOS_DE_PRUEBA.md").read_text(encoding="utf-8")
    assert "ficticios" in texto.split("\n")[2].lower() and "59.000.000" in texto


def test_la_base_de_prueba_guarda_el_rut_y_el_correo_cifrados(corrida):
    crudo = (corrida / "a.db").read_bytes()
    con = sqlite3.connect(corrida / "a.db")
    for rut_cifrado, email_cifrado, indice in con.execute(
        "SELECT rut_cifrado, email_cifrado, rut_indice FROM catalogo_persona"
    ):
        assert rut_cifrado.startswith("v1:k1:") and email_cifrado.startswith("v1:k1:") and len(indice) == 64
    assert b"@ejemplo.invalid" not in crudo


def test_el_csv_de_personas_tiene_el_formato_de_la_plantilla_de_importacion():
    filas = list(csv.reader(open(AQUI / "csv" / "catalogo_persona.csv", encoding="utf-8")))
    plantilla = next(
        csv.reader(open(AQUI.parent / "plantillas_importacion" / "csv" / "catalogo_persona.csv", encoding="utf-8"))
    )
    assert filas[0] == plantilla == ["rut", "nombre", "email"] and len(filas) == 21
