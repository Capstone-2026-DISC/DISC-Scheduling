"""Importación de CSV por la API sobre Directus (simulado): informe de errores, todo o nada, cifrado y alcance."""
from .conftest import cabecera, entrar, eventos

CSV = {"Content-Type": "text/csv"}
PERSONAS = "rut,nombre,email\n59999999-K,Persona Ficticia,persona@ejemplo.invalid\n"


def subir(client, headers, coleccion, texto, confirmar=False):
    return client.post(f"/importaciones/{coleccion}" + ("?confirmar=true" if confirmar else ""), content=texto.encode(), headers={**headers, **CSV})


def test_valida_sin_cargar_y_deja_la_importacion_lista(client, admin, directus):
    r = subir(client, admin, "catalogo_persona", PERSONAS)
    assert r.status_code == 200 and r.json()["estado"] == "lista" and r.json()["ok"] is True
    assert directus.items["catalogo_persona"] == []
    imp = directus.items["plataforma_importacion"][0]
    assert imp["estado"] == "lista" and len(imp["archivo_sha256"]) == 64 and imp["creada_por"] == 1


def test_confirmar_carga_cifrado_y_queda_trazado(client, admin, directus):
    r = subir(client, admin, "catalogo_persona", PERSONAS, True)
    assert r.json()["estado"] == "confirmada"
    fila = directus.items["catalogo_persona"][0]
    assert fila["rut_cifrado"].startswith("v1:k1:") and "59999999" not in str(directus.items["catalogo_persona"])
    assert directus.items["plataforma_importacion"][0]["estado"] == "confirmada"
    e = eventos(directus, "importacion")[0]
    assert e["usuario_id"] == 1 and e["ip"] == "testclient"
    enviado = next(l for l in directus.llamadas if l[0] == "POST" and l[1] == "/items/catalogo_persona")
    assert enviado[3] == admin["Authorization"]                # Directus recibe la sesión de quien importa


def test_con_errores_no_se_carga_nada_y_se_explica_cada_uno(client, admin, directus):
    texto = "rut,nombre,email\n59999999-K,Bien,\n58123456-0,Mal digito,\n,,x@ejemplo.invalid\n"
    r = subir(client, admin, "catalogo_persona", texto, confirmar=True).json()
    assert r["estado"] == "con_errores" and r["resumen"] == {"filas": 3, "con_errores": 2, "validas": 1}
    assert directus.items["catalogo_persona"] == []
    e = r["filas"][1]["errores"][0]
    assert e["columna"] == "rut" and "dígito verificador" in e["falla"] and e["como_corregir"] and "58123456" not in str(r)


def test_las_filas_crudas_guardan_cifrados_el_rut_y_el_correo(client, admin, directus):
    subir(client, admin, "catalogo_persona", "rut,nombre,email\n59999999-K,Persona Ficticia,p@ejemplo.invalid\n58123456-0,Mal,otro@ejemplo.invalid\n", True)
    guardado = str(directus.items["plataforma_fila_importada"])
    assert "Persona Ficticia" in guardado                    # el nombre queda para explicar errores
    for secreto in ("59999999", "58123456", "ejemplo.invalid"):
        assert secreto not in guardado.replace("Ejemplo: 59999999-K", "")
    assert "v1:k1:" in guardado


def test_un_rut_con_puntos_se_acepta_y_un_duplicado_se_detecta(client, admin, directus):
    subir(client, admin, "catalogo_persona", PERSONAS, True)
    otra = subir(client, admin, "catalogo_persona", "rut,nombre,email\n59.999.999-K,Otra,\n").json()
    assert otra["estado"] == "con_errores" and "Ya existe" in otra["filas"][0]["errores"][0]["falla"]
    dentro = subir(client, admin, "catalogo_persona", "rut,nombre,email\n59999998-1,A,\n59.999.998-1,B,\n").json()
    assert "Repite la clave de la fila 2" in dentro["filas"][1]["errores"][0]["falla"]


def test_si_directus_rechaza_la_carga_la_importacion_queda_con_errores(client, admin, directus):
    directus.fallos[("POST", "/items/catalogo_persona")] = (400, {"errors": [{"message": 'Value "x" for field "rut_indice" in collection "catalogo_persona" has to be unique.',
                                                                                "extensions": {"code": "RECORD_NOT_UNIQUE"}}]})
    r = subir(client, admin, "catalogo_persona", PERSONAS, True)
    assert r.status_code == 409 and directus.items["catalogo_persona"] == []
    assert directus.items["plataforma_importacion"][0]["estado"] == "con_errores"


def test_las_referencias_se_resuelven_por_clave_natural(client, admin, directus):
    subir(client, admin, "catalogo_persona", PERSONAS, True)
    r = subir(client, admin, "catalogo_docente", "rut,departamento,tipo_contrato,activo\n59999999-K,,hora,1\n", True)
    assert r.json()["estado"] == "confirmada"
    assert directus.items["catalogo_docente"][0] == {"id": 1, "persona_id": 1, "departamento_id": 1, "tipo_contrato": "hora", "activo": 1}
    faltante = subir(client, admin, "catalogo_docente", "rut,departamento,tipo_contrato,activo\n59999998-1,,planta,1\n").json()
    assert "catalogo_persona" in faltante["filas"][0]["errores"][0]["como_corregir"]


def test_se_consulta_a_directus_una_vez_por_tanda_de_rut_y_no_por_fila(client, admin, directus):
    ruts = ["59999999-K", "59999998-1", "59999997-3"]
    subir(client, admin, "catalogo_persona", "rut,nombre,email\n" + "".join(f"{r},P{i},\n" for i, r in enumerate(ruts)), True)
    antes = len(directus.llamadas)
    subir(client, admin, "catalogo_docente", "rut,departamento,tipo_contrato,activo\n" + "".join(f"{r},,hora,1\n" for r in ruts))
    consultas = [l for l in directus.llamadas[antes:] if l[0] == "GET" and l[1] == "/items/catalogo_persona"]
    assert len(consultas) == 1


def test_permisos_y_alcance_por_departamento(client, consulta, directus):
    assert subir(client, consulta, "catalogo_persona", PERSONAS).status_code == 403
    assert eventos(directus, "acceso_denegado")
    directus.agregar_usuario("encargado@example.com", "Clave-Larga-Enc-1x", "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee", "disc_encargado_docente", 1)
    directus.items["identidad_usuario"].append({"id": 3, "directus_id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee", "email": "encargado@example.com", "nombre": "E", "eliminado_en": None})
    ed = cabecera(entrar(client, "encargado@example.com", "Clave-Larga-Enc-1x"))
    otro = subir(client, ed, "catalogo_programa", "departamento,codigo,nombre,tipo\nDMAT,P1,Programa,pregrado\n", True).json()
    assert otro["estado"] == "con_errores" and otro["filas"][0]["errores"][0]["columna"] == "departamento"
    assert directus.items["catalogo_programa"] == []
    propio = subir(client, ed, "catalogo_programa", "departamento,codigo,nombre,tipo\nDISC,P1,Programa,pregrado\n", True).json()
    assert propio["estado"] == "confirmada" and directus.items["catalogo_programa"][0]["departamento_id"] == 1


def test_encabezados_equivocados_y_archivos_invalidos(client, admin):
    r = subir(client, admin, "catalogo_persona", "rut,nombres\n59999999-K,X\n").json()
    assert not r["ok"] and r["errores_generales"]
    assert client.post("/importaciones/inexistente", content=b"a", headers={**admin, **CSV}).status_code == 404
    assert client.post("/importaciones/catalogo_persona", content=b"\xff\xfe\x00", headers={**admin, **CSV}).status_code == 422
    assert client.post("/importaciones/catalogo_persona", content=b"x", headers=CSV).status_code == 401


def test_el_listado_de_plantillas_depende_de_los_permisos(client, admin, consulta):
    assert len(client.get("/importaciones/plantillas", headers=admin).json()) == 14
    assert client.get("/importaciones/plantillas", headers=consulta).json() == []
