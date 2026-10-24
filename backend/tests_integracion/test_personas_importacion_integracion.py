"""Datos personales cifrados de punta a punta e importación de CSV contra Directus de verdad."""
import random

from .conftest import rut_nuevo, unico

CSV = {"Content-Type": "text/csv"}


def subir(api, h, coleccion, texto, confirmar=False):
    return api.post(f"/importaciones/{coleccion}" + ("?confirmar=true" if confirmar else ""), content=texto.encode(), headers={**h, **CSV})


def test_el_rut_y_el_correo_estan_cifrados_en_directus_y_la_api_los_descifra(api, admin, consulta, boot):
    rut, correo = rut_nuevo(), f"{unico('p')}@ejemplo.invalid".lower()
    pid = api.post("/personas", headers=admin, json={"rut": rut, "nombre": "Persona Ficticia", "email": correo}).json()["id"]
    crudo = boot.get(f"/items/catalogo_persona/{pid}").json()["data"]                  # lo que ve Directus, incluso el administrador
    assert crudo["rut_cifrado"].startswith("v1:k1:") and crudo["email_cifrado"].startswith("v1:k1:") and len(crudo["rut_indice"]) == 64
    assert rut.split("-")[0] not in str(crudo) and correo not in str(crudo)
    assert api.get(f"/personas/{pid}", headers=admin).json() == {"id": pid, "rut": rut, "nombre": "Persona Ficticia", "email": correo}
    assert api.get(f"/personas/{pid}", headers=consulta).status_code == 403
    actividad = boot.get("/activity", params={"filter[collection][_eq]": "catalogo_persona", "filter[item][_eq]": str(pid), "fields": "action"}).json()["data"]
    assert any(a["action"] == "create" for a in actividad)
    revision = boot.get("/revisions", params={"filter[collection][_eq]": "catalogo_persona", "filter[item][_eq]": str(pid), "fields": "data"}).json()["data"]
    assert revision and rut.split("-")[0] not in str(revision) and correo not in str(revision)     # ni en el historial de revisiones


def test_la_lectura_de_datos_personales_queda_auditada_sin_el_rut(api, admin, boot):
    rut = rut_nuevo()
    pid = api.post("/personas", headers=admin, json={"rut": rut, "nombre": "X"}).json()["id"]
    api.get(f"/personas/{pid}", headers=admin)
    ev = boot.get("/items/plataforma_auditoria", params={"filter[accion][_eq]": "lectura_datos_personales", "sort": "-id", "limit": 1, "fields": "usuario_id,ip,despues"}).json()["data"][0]
    assert ev["usuario_id"] and ev["ip"] and rut.split("-")[0] not in str(ev)


def test_el_mismo_rut_escrito_distinto_es_un_duplicado_y_el_digito_se_valida(api, admin):
    rut = rut_nuevo()
    con_puntos = f"{int(rut.split('-')[0]):,}".replace(",", ".") + "-" + rut[-1]
    assert api.post("/personas", headers=admin, json={"rut": con_puntos.lower(), "nombre": "Una"}).status_code == 201
    assert api.post("/personas", headers=admin, json={"rut": rut, "nombre": "Otra"}).status_code == 409
    malo = rut.split("-")[0] + "-" + ("0" if rut[-1] != "0" else "1")
    r = api.post("/personas", headers=admin, json={"rut": malo, "nombre": "X"})
    assert r.status_code == 422 and "dígito verificador" in r.json()["detail"]


def test_importar_personas_valida_carga_y_explica_los_errores(api, admin, boot):
    rut, correo = rut_nuevo(), f"{unico('i')}@ejemplo.invalid".lower()
    texto = f"rut,nombre,email\n{rut},Persona Importada,{correo}\n"
    prueba = subir(api, admin, "catalogo_persona", texto).json()
    assert prueba["estado"] == "lista" and prueba["ok"]
    carga = subir(api, admin, "catalogo_persona", texto, True).json()
    assert carga["estado"] == "confirmada"
    fila = boot.get("/items/plataforma_fila_importada", params={"filter[importacion_id][_eq]": carga["importacion_id"], "fields": "datos,errores"}).json()["data"][0]
    assert rut.split("-")[0] not in str(fila) and correo not in str(fila) and "Persona Importada" in str(fila)
    again = subir(api, admin, "catalogo_persona", texto).json()
    assert again["estado"] == "con_errores" and "Ya existe" in again["filas"][0]["errores"][0]["falla"]
    malo = rut.split("-")[0][:-1] + "1-0"
    err = subir(api, admin, "catalogo_persona", f"rut,nombre,email\n{malo},X,\n").json()
    assert err["estado"] == "con_errores" and malo not in str(err) and err["filas"][0]["errores"][0]["como_corregir"]


def test_una_importacion_con_un_error_no_carga_ninguna_fila(api, admin):
    buena, repetida = rut_nuevo(), rut_nuevo()
    api.post("/personas", headers=admin, json={"rut": repetida, "nombre": "Ya estaba"})
    r = subir(api, admin, "catalogo_persona", f"rut,nombre,email\n{buena},Nueva,\n{repetida},Repetida,\n", True).json()
    assert r["estado"] == "con_errores"
    assert api.get("/personas", headers=admin, params={"limite": 500}).json()
    assert buena not in [p["rut"] for p in api.get("/personas", headers=admin, params={"limite": 500}).json()]


def test_el_alcance_por_departamento_vale_tambien_al_importar(api, ed_disc, ed_dmat, depto2):
    codigo = unico("PR").upper()
    r = subir(api, ed_dmat, "catalogo_programa", f"departamento,codigo,nombre,tipo\nDISC,{codigo},Programa,pregrado\n", True).json()
    assert r["estado"] == "con_errores" and r["filas"][0]["errores"][0]["columna"] == "departamento"
    propio = subir(api, ed_dmat, "catalogo_programa", f"departamento,codigo,nombre,tipo\nDMAT,{codigo},Programa,pregrado\n", True).json()
    assert propio["estado"] == "confirmada"
    assert api.get("/programas", headers=ed_disc).json() is not None and codigo not in [p["codigo"] for p in api.get("/programas", headers=ed_disc).json()]


def test_las_catorce_plantillas_se_cargan_en_el_orden_documentado(api, admin):
    """Cada plantilla, con datos propios de esta corrida, se carga y deja filas reales; las referencias se resuelven por clave natural."""
    from app.importacion.spec import ORDEN_DE_CARGA, PLANTILLAS
    n = random.randint(10_000, 99_999)
    periodo, rut_doc, rut_ayu, rut_hora = f"{random.randint(3100, 9800)}10", rut_nuevo(), rut_nuevo(), rut_nuevo()
    nrc = random.randint(100_000, 900_000)
    usados = {(f["anio"], f["tipo_persona"]) for f in api.get("/presupuestos", headers=admin, params={"limite": 500}).json()}
    libres = [(a, t) for a in range(2000, 2101) for t in ("profesor_hora", "ayudante") if (a, t) not in usados]
    anio, tipo_pres = random.choice(libres)               # el presupuesto es único por departamento, año y tipo
    valores = {
        "catalogo_periodo": {"codigo": periodo, "estado": "planificacion"},
        "catalogo_programa": {"codigo": f"PG{n}"}, "catalogo_asignatura": {"codigo": f"FAIC-{n:05d}", "nombre": f"Asignatura {n}"},
        "catalogo_sala": {"codigo": f"ZS-{n}"},
        "catalogo_persona": [{"rut": rut_doc, "nombre": "Docente Ficticio", "email": f"d{n}@ejemplo.invalid"},
                             {"rut": rut_ayu, "nombre": "Ayudante Ficticio", "email": ""}, {"rut": rut_hora, "nombre": "Hora Ficticio", "email": ""}],
        "catalogo_docente": [{"rut": rut_doc, "tipo_contrato": "hora"}], "catalogo_ayudante": [{"rut": rut_ayu}],
        "horarios_paralelo": {"periodo": periodo, "asignatura": f"FAIC-{n:05d}", "nrc": str(nrc), "codigo": "C1"},
        "horarios_sesion": {"periodo": periodo, "nrc": str(nrc), "numero": "1"},
        "horarios_disponibilidad_docente": {"periodo": periodo, "rut": rut_doc},
        "finanzas_tarifa": {"vigente_desde": f"{random.randint(2101, 2999)}-01-01", "valor_hora": "12345"},
        "finanzas_presupuesto": {"anio": str(anio), "tipo_persona": tipo_pres},
        "finanzas_nombramiento": {"periodo": periodo, "rut": rut_doc, "nrc": str(nrc)},
        "proyeccion_inscripcion_historica": {"asignatura": f"FAIC-{n:05d}", "periodo": periodo},
    }
    for coleccion in ORDEN_DE_CARGA:
        p = PLANTILLAS[coleccion]
        base = {c.nombre: c.ejemplo for c in p.columnas}
        v = valores.get(coleccion, {})
        filas = v if isinstance(v, list) else [v]
        texto = ",".join(base) + "\n" + "".join(",".join({**base, **f}[c] for c in base) + "\n" for f in filas)
        r = subir(api, admin, coleccion, texto, True)
        assert r.status_code == 200 and r.json()["estado"] == "confirmada", (coleccion, r.text[:600])
    sesiones = api.get("/sesiones", headers=admin, params={"limite": 500}).json()
    assert sesiones
