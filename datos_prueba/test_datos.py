import csv
import re
import sqlite3
import subprocess
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
    assert (tmp_path / "csv" / "catalogo_persona.csv").read_text() != (AQUI / "csv" / "catalogo_persona.csv").read_text()


def test_la_base_cargada_es_consistente(corrida):
    con = sqlite3.connect(corrida / "a.db")
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    assert con.execute("SELECT count(*) FROM catalogo_persona").fetchone()[0] == 20


def test_los_rut_son_validos_y_estan_en_el_rango_ficticio(corrida):
    con = sqlite3.connect(corrida / "a.db")
    for (rut,) in con.execute("SELECT rut FROM catalogo_persona"):
        cuerpo, dv = rut.split("-")
        assert gd.RUT_MIN <= int(cuerpo) <= gd.RUT_MAX
        assert gd.digito_verificador(int(cuerpo)) == dv


def test_todos_los_correos_son_ejemplo_invalid_y_unicos(corrida):
    con = sqlite3.connect(corrida / "a.db")
    correos = [c for (c,) in con.execute("SELECT email FROM catalogo_persona")]
    assert all(re.fullmatch(r"[a-z0-9.]+@ejemplo\.invalid", c) for c in correos)
    assert len(set(correos)) == len(correos)


def test_los_csv_versionados_coinciden_con_la_semilla_por_defecto(corrida):
    for archivo in (AQUI / "csv").glob("*.csv"):
        assert archivo.read_bytes() == (corrida / "csv_a" / archivo.name).read_bytes(), f"{archivo.name} está desactualizado"


def test_documento_advierte_que_son_datos_ficticios():
    texto = (AQUI / "DATOS_DE_PRUEBA.md").read_text(encoding="utf-8")
    assert "ficticios" in texto.split("\n")[2].lower() and "59.000.000" in texto
