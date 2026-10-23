"""Carga por la API: informe de errores, todo o nada, permisos por departamento y auditoría."""
from pathlib import Path

import pytest

from .test_permisos import CLAVE_ED, crear_ed  # noqa: F401
from .conftest import cabecera, entrar

PLANT = Path(__file__).resolve().parents[2] / "plantillas_importacion" / "csv"
CSV = {"Content-Type": "text/csv"}


def subir(client, headers, coleccion, texto, confirmar=False):
    return client.post(f"/importaciones/{coleccion}" + ("?confirmar=true" if confirmar else ""),
                       content=texto.encode(), headers={**headers, **CSV})


def test_valida_sin_cargar_y_deja_la_importacion_lista(client, admin, db):
    r = subir(client, admin, "catalogo_persona", "rut,nombre,email\n59999999-K,Persona Ficticia Uno,uno@ejemplo.invalid\n")
    assert r.status_code == 200 and r.json()["estado"] == "lista" and r.json()["ok"] is True
    assert db.execute("SELECT count(*) FROM catalogo_persona").fetchone()[0] == 0
    fila = db.execute("SELECT estado, fuente, archivo_sha256 FROM plataforma_importacion").fetchone()
    assert fila["estado"] == "lista" and len(fila["archivo_sha256"]) == 64


def test_confirmar_carga_y_queda_trazado(client, admin, db):
    r = subir(client, admin, "catalogo_persona", "rut,nombre,email\n59999999-K,Persona Ficticia Uno,uno@ejemplo.invalid\n", True)
    assert r.json()["estado"] == "confirmada"
    assert db.execute("SELECT rut FROM catalogo_persona").fetchone()[0] == "59999999-K"
    a = db.execute("SELECT usuario_id, ip FROM plataforma_auditoria WHERE accion = 'importacion'").fetchone()
    assert a["usuario_id"] == 1 and a["ip"] == "testclient"
    assert db.execute("SELECT count(*) FROM plataforma_fila_importada").fetchone()[0] == 1


def test_con_errores_no_se_carga_nada_y_explica_cada_uno(client, admin, db):
    texto = "rut,nombre,email\n59999999-K,Bien,\n59999999-1,Mal digito,\n,,x@ejemplo.invalid\n"
    r = subir(client, admin, "catalogo_persona", texto, confirmar=True)
    cuerpo = r.json()
    assert cuerpo["estado"] == "con_errores" and cuerpo["resumen"] == {"filas": 3, "con_errores": 2, "validas": 1}
    assert db.execute("SELECT count(*) FROM catalogo_persona").fetchone()[0] == 0       # todo o nada
    errores = cuerpo["filas"][1]["errores"][0]
    assert errores["columna"] == "rut" and "dígito verificador" in errores["falla"] and errores["como_corregir"]
    guardado = db.execute("SELECT errores FROM plataforma_fila_importada WHERE numero_fila = 3").fetchone()[0]
    assert "como_corregir" in guardado


def test_una_clave_que_ya_existe_se_informa_y_no_actualiza(client, admin):
    base = "rut,nombre,email\n59999999-K,Persona Ficticia Uno,\n"
    assert subir(client, admin, "catalogo_persona", base, True).json()["estado"] == "confirmada"
    r = subir(client, admin, "catalogo_persona", "rut,nombre,email\n59999999-K,Otro Nombre,\n", True).json()
    assert r["estado"] == "con_errores" and "Ya existe" in r["filas"][0]["errores"][0]["falla"]


def test_las_referencias_se_resuelven_por_clave_natural_en_orden(client, admin, db):
    assert subir(client, admin, "catalogo_persona", "rut,nombre,email\n59999999-K,Persona Ficticia,\n", True).json()["estado"] == "confirmada"
    r = subir(client, admin, "catalogo_docente", "rut,departamento,tipo_contrato,activo\n59999999-K,,hora,1\n", True)
    assert r.json()["estado"] == "confirmada"
    assert db.execute("SELECT tipo_contrato, departamento_id FROM catalogo_docente").fetchone()[:] == ("hora", 1)
    # un docente cuya persona no está cargada dice qué falta cargar primero
    r = subir(client, admin, "catalogo_docente", "rut,departamento,tipo_contrato,activo\n59999998-1,,planta,1\n").json()
    assert "catalogo_persona" in r["filas"][0]["errores"][0]["como_corregir"]


def test_todas_las_plantillas_de_ejemplo_se_cargan_en_orden(client, admin, db):
    """Las plantillas versionadas no son solo forma: cargadas en el orden documentado producen datos reales."""
    from app.importacion.spec import ORDEN_DE_CARGA
    for coleccion in ORDEN_DE_CARGA:
        texto = (PLANT / f"{coleccion}.csv").read_text(encoding="utf-8")
        if coleccion == "catalogo_periodo":                      # el ejemplo del periodo es uno nuevo; 202620 hace falta
            texto += ",202620,2026-08-03,2026-12-19,vigente\n"
        if coleccion == "catalogo_asignatura":
            texto += ",FAIC-00101,Asignatura de prueba 01,,0,1\n"
        if coleccion == "catalogo_persona":
            texto += "59999998-1,Otra Persona Ficticia,\n"
        r = subir(client, admin, coleccion, texto, True)
        assert r.json()["estado"] == "confirmada", (coleccion, r.json()["resumen"],
                                                    [e for f in r.json()["filas"] for e in f["errores"]],
                                                    r.json()["errores_generales"])
    assert db.execute("SELECT count(*) FROM horarios_sesion").fetchone()[0] >= 1
    assert db.execute("SELECT count(*) FROM finanzas_nombramiento").fetchone()[0] == 1


def test_permisos_y_alcance_por_departamento(client, admin, consulta, db):
    # consulta no tiene catalogo.importar
    assert subir(client, consulta, "catalogo_persona", "rut,nombre,email\n59999999-K,X,\n").status_code == 403
    # un ED del DISC no puede cargar datos de otro departamento
    db.execute("INSERT INTO identidad_departamento (codigo, nombre) VALUES ('DMAT', 'Departamento de prueba')")
    crear_ed(db, "ed.disc@ejemplo.invalid", 1)
    ed = cabecera(entrar(client, "ed.disc@ejemplo.invalid", CLAVE_ED))
    r = subir(client, ed, "catalogo_programa", "departamento,codigo,nombre,tipo\nDMAT,P1,Programa,pregrado\n", True).json()
    assert r["estado"] == "con_errores" and "departamento" in r["filas"][0]["errores"][0]["columna"]
    assert subir(client, ed, "catalogo_programa", "departamento,codigo,nombre,tipo\nDISC,P1,Programa,pregrado\n", True).json()["estado"] == "confirmada"
    # finanzas exige finanzas.editar, que el ED sí tiene, pero la consulta no
    assert subir(client, consulta, "finanzas_presupuesto", "departamento,anio,tipo_persona,monto_anual,porcentaje_s1\nDISC,2027,ayudante,1,50\n").status_code == 403


def test_encabezados_equivocados_y_archivos_invalidos(client, admin):
    r = subir(client, admin, "catalogo_persona", "rut,nombres\n59999999-K,X\n").json()
    assert not r["ok"] and r["errores_generales"]
    assert client.post("/importaciones/inexistente", content=b"a", headers={**admin, **CSV}).status_code == 404
    assert client.post("/importaciones/catalogo_persona", content=b"\xff\xfe\x00", headers={**admin, **CSV}).status_code == 422
    assert client.post("/importaciones/catalogo_persona", content=b"x", headers=CSV).status_code == 401


def test_el_listado_de_plantillas_depende_de_los_permisos(client, admin, consulta):
    assert len(client.get("/importaciones/plantillas", headers=admin).json()) == 14
    assert client.get("/importaciones/plantillas", headers=consulta).json() == []
