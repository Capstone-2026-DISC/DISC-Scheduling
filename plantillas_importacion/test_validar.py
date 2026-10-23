import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "backend"))
from app.importacion.spec import ORDEN_DE_CARGA, PLANTILLAS  # noqa: E402
from app.importacion.validar import formatear, validar  # noqa: E402

CLI = AQUI / "validar_plantilla.py"


def test_hay_una_plantilla_por_coleccion_y_orden_de_carga_completo():
    assert sorted(ORDEN_DE_CARGA) == sorted(PLANTILLAS) and len(PLANTILLAS) == 14
    visto = set()
    for c in ORDEN_DE_CARGA:
        assert set(PLANTILLAS[c].dependencias) <= visto, f"{c} se carga antes que sus dependencias"
        visto.add(c)


@pytest.mark.parametrize("coleccion", sorted(PLANTILLAS))
def test_la_fila_de_ejemplo_de_cada_plantilla_es_valida(coleccion):
    informe = validar(PLANTILLAS[coleccion], (AQUI / "csv" / f"{coleccion}.csv").read_text(encoding="utf-8"))
    assert informe["ok"], formatear(informe)


@pytest.mark.parametrize("coleccion", sorted(PLANTILLAS))
def test_los_archivos_versionados_estan_al_dia(coleccion):
    p = PLANTILLAS[coleccion]
    esperado = ",".join(c.nombre for c in p.columnas)
    assert (AQUI / "csv" / f"{coleccion}.csv").read_text(encoding="utf-8").splitlines()[0] == esperado
    assert f"`{coleccion}`" in (AQUI / "README.md").read_text(encoding="utf-8")


def test_cada_error_dice_columna_falla_y_como_corregir():
    texto = "rut,nombre,email\n59999999-1,Ficticio,sin_arroba\n,Sin Rut,a@ejemplo.invalid\n59999999-K,Bien,\n59999999-K,Repetido,\n"
    informe = validar(PLANTILLAS["catalogo_persona"], texto)
    assert not informe["ok"] and informe["resumen"] == {"filas": 4, "con_errores": 3, "validas": 1}
    errores = [e for f in informe["filas"] for e in f["errores"]]
    assert all(set(e) == {"columna", "gravedad", "falla", "como_corregir"} and e["falla"] and e["como_corregir"] for e in errores)
    assert any("dígito verificador" in e["falla"] and "K" in e["falla"] for e in errores)
    assert any("Repite la clave de la fila 4" in e["falla"] for e in errores)


def test_encabezados_distintos_se_explican():
    informe = validar(PLANTILLAS["catalogo_persona"], "rut,nombres\n59999999-K,Alguien\n")
    textos = " ".join(e["falla"] for e in informe["errores_generales"])
    assert "Faltan columnas: nombre, email" in textos and "Columnas desconocidas: nombres" in textos


def test_enumerados_y_rangos():
    texto = ("departamento,codigo,nombre,capacidad,es_laboratorio,administrada_por,activa\n"
             ",ZZ-1,Sala,0,2,disc,1\n")
    informe = validar(PLANTILLAS["catalogo_sala"], texto)
    columnas = {e["columna"] for f in informe["filas"] for e in f["errores"]}
    assert columnas == {"capacidad", "es_laboratorio"}


def test_referencias_y_duplicados_contra_la_base(tmp_path):
    esquema = AQUI.parent / "db" / "esquema_plataforma.sql"
    con = sqlite3.connect(":memory:")
    con.executescript(esquema.read_text(encoding="utf-8"))
    con.execute("INSERT INTO catalogo_periodo (codigo) VALUES ('202620')")
    ok = validar(PLANTILLAS["catalogo_periodo"], "departamento,codigo,fecha_inicio,fecha_fin,estado\n,202710,,,\n", con)
    assert ok["ok"]
    dup = validar(PLANTILLAS["catalogo_periodo"], "departamento,codigo,fecha_inicio,fecha_fin,estado\n,202620,,,\n", con)
    assert "Ya existe" in dup["filas"][0]["errores"][0]["falla"]
    import base64
    from app.core.pii import Cifrador
    b64 = lambda b: base64.urlsafe_b64encode(b * 32).decode().rstrip("=")      # noqa: E731
    cif = Cifrador.desde_entorno("k1=" + b64(b"A"), "k1", b64(b"B"))
    docente = "rut,departamento,tipo_contrato,activo\n59999999-K,,hora,1\n"
    # sin las claves no se puede ubicar a la persona: se revisa la forma y no se inventan errores
    assert validar(PLANTILLAS["catalogo_docente"], docente, con)["ok"]
    sin_dep = validar(PLANTILLAS["catalogo_docente"], docente, con, cif)
    assert "No hay una persona" in sin_dep["filas"][0]["errores"][0]["falla"] and "catalogo_persona" in sin_dep["filas"][0]["errores"][0]["como_corregir"]
    sin_periodo = validar(PLANTILLAS["horarios_sesion"], "periodo,departamento,nrc,numero,duracion_bloques\n209910,,1,1,1\n", con)
    assert "no existe" in sin_periodo["filas"][0]["errores"][0]["falla"]


def test_la_linea_de_comandos_devuelve_codigo_segun_el_resultado(tmp_path):
    bueno = subprocess.run([sys.executable, str(CLI), "catalogo_persona", str(AQUI / "csv" / "catalogo_persona.csv")], capture_output=True, text=True)
    assert bueno.returncode == 0 and "0 con errores" in bueno.stdout
    malo = tmp_path / "malo.csv"
    malo.write_text("rut,nombre,email\n123,X,y\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(CLI), "catalogo_persona", str(malo)], capture_output=True, text=True)
    assert r.returncode == 1 and "Cómo corregirlo" in r.stdout
