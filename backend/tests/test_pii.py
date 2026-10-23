"""Cifrado del RUT y el correo: formato, claves, índice ciego, qué hay realmente en el archivo y en la auditoría."""
import base64
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import directus_matriz as m
from app.core import pii
from app.core.config import Settings
from app.main import create_app
from app.rotar_claves import rotar

from .conftest import CLAVE_DATOS, CLAVE_INDICE, hacer_settings, insertar_persona

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


def test_la_app_no_arranca_sin_claves_de_cifrado(tmp_path):
    with pytest.raises(pii.ClaveFaltante):
        create_app(hacer_settings(tmp_path, data_keys="", index_key=""))


def test_enmascarar(cif):
    assert cif.enmascarar_rut("59999999-K") == "*****999-K"


# ---- qué queda en el archivo, la auditoría y las importaciones ---------------------------------
def archivo_completo(settings) -> bytes:
    """El .db y su -wal, que es donde SQLite deja lo último escrito."""
    datos = b""
    for sufijo in ("", "-wal"):
        ruta = Path(settings.db_path + sufijo)
        datos += ruta.read_bytes() if ruta.exists() else b""
    return datos


def test_el_rut_y_el_correo_no_estan_en_claro_en_el_archivo_de_la_base(client, admin, settings, db):
    r = client.post("/personas", headers=admin, json={"rut": RUT, "nombre": "Persona Ficticia", "email": EMAIL})
    assert r.status_code == 201
    crudo = archivo_completo(settings)
    assert b"Persona Ficticia" in crudo                          # el nombre no se cifra (decisión explícita)
    for secreto in (RUT, "59999999", EMAIL, "persona.ficticia", "ejemplo.invalid"):
        assert secreto.encode() not in crudo, f"{secreto} aparece en claro en el archivo"


def test_la_auditoria_solo_guarda_texto_cifrado(client, admin, db):
    pid = client.post("/personas", headers=admin, json={"rut": RUT, "nombre": "Persona Ficticia", "email": EMAIL}).json()["id"]
    assert client.patch(f"/personas/{pid}", headers=admin, json={"email": "otro@ejemplo.invalid"}).status_code == 204
    texto = " ".join(str(tuple(f)) for f in db.execute("SELECT antes, despues FROM plataforma_auditoria WHERE entidad = 'catalogo_persona'"))
    assert "rut_cifrado" in texto and "email_cifrado" in texto
    for secreto in ("59999999", "ejemplo.invalid", "@"):
        assert secreto not in texto


def test_la_api_devuelve_los_datos_a_quien_corresponde_y_audita_la_lectura(client, admin, consulta, db):
    pid = client.post("/personas", headers=admin, json={"rut": "59.999.999-k", "nombre": "Persona Ficticia", "email": EMAIL}).json()["id"]
    fila = client.get(f"/personas/{pid}", headers=admin).json()
    assert fila == {"id": pid, "rut": RUT, "nombre": "Persona Ficticia", "email": EMAIL}
    assert client.get("/personas", headers=admin).json()[0]["rut"] == RUT
    assert client.get(f"/personas/{pid}", headers=consulta).status_code == 403
    lectura = db.execute("SELECT usuario_id, ip, despues FROM plataforma_auditoria WHERE accion = 'lectura_datos_personales' ORDER BY id").fetchall()
    assert len(lectura) == 2 and lectura[0]["usuario_id"] == 1 and lectura[0]["ip"] == "testclient"
    assert RUT not in str(tuple(lectura[0]))


def test_el_mismo_rut_escrito_distinto_es_un_duplicado(client, admin):
    assert client.post("/personas", headers=admin, json={"rut": "59.999.999-K", "nombre": "Una"}).status_code == 201
    assert client.post("/personas", headers=admin, json={"rut": "59999999-k", "nombre": "Otra"}).status_code == 409
    otra = client.post("/personas", headers=admin, json={"rut": "59999998-1", "nombre": "Dos"}).json()["id"]
    assert client.patch(f"/personas/{otra}", headers=admin, json={"rut": "59999999-K"}).status_code == 409
    assert client.patch(f"/personas/{otra}", headers=admin, json={"rut": "59999997-3"}).status_code in (204, 422)


def test_rut_invalido_explica_el_digito_correcto(client, admin):
    r = client.post("/personas", headers=admin, json={"rut": "59999999-1", "nombre": "X"})
    assert r.status_code == 422 and "terminar en K" in r.json()["detail"]
    assert client.post("/personas", headers=admin, json={"rut": "1234", "nombre": "X"}).status_code == 422


def test_un_dato_alterado_en_la_base_no_filtra_nada_y_avisa(client, admin, db):
    pid = client.post("/personas", headers=admin, json={"rut": RUT, "nombre": "X"}).json()["id"]
    db.execute("UPDATE catalogo_persona SET rut_cifrado = 'v1:k1:AAAAAAAAAAAAAAAAAAAAAAAAAAAA' WHERE id = ?", (pid,))
    r = client.get(f"/personas/{pid}", headers=admin)
    assert r.status_code == 500 and "claves de cifrado" in r.json()["detail"] and RUT not in r.text


def test_las_filas_crudas_de_una_importacion_guardan_cifrados_el_rut_y_el_correo(client, admin, db):
    csv = f"rut,nombre,email\n{RUT},Persona Ficticia,{EMAIL}\n58123456-0,Mal Digito,otro@ejemplo.invalid\n"
    client.post("/importaciones/catalogo_persona?confirmar=true", content=csv.encode(), headers={**admin, "Content-Type": "text/csv"})
    guardado = " ".join(f"{f['datos']} {f['errores']}" for f in db.execute("SELECT datos, errores FROM plataforma_fila_importada"))
    assert "Persona Ficticia" in guardado                         # el nombre sí queda, para poder explicar errores
    for secreto in ("59999999", "58123456", "ejemplo.invalid"):
        assert secreto not in guardado.replace("Ejemplo: 59999999-K", "")      # el ejemplo de la plantilla es ficticio y público
    assert "v1:k1:" in guardado


def test_el_informe_de_errores_no_repite_el_rut(client, admin):
    malo = "58123456-0"                                  # dígito verificador incorrecto a propósito
    r = client.post("/importaciones/catalogo_persona", content=f"rut,nombre,email\n{malo},X,\n".encode(), headers={**admin, "Content-Type": "text/csv"})
    assert "dígito verificador" in r.text and malo not in r.text


def test_importar_una_persona_deja_rut_cifrado_y_buscable(client, admin, db, settings):
    csv = f"rut,nombre,email\n{RUT},Persona Ficticia,{EMAIL}\n"
    assert client.post("/importaciones/catalogo_persona?confirmar=true", content=csv.encode(), headers={**admin, "Content-Type": "text/csv"}).json()["estado"] == "confirmada"
    fila = db.execute("SELECT rut_cifrado, rut_indice, email_cifrado FROM catalogo_persona").fetchone()
    cif = settings.cifrador()
    assert fila["rut_indice"] == cif.indice_rut(RUT) and cif.descifrar(fila["email_cifrado"], pii.COL_EMAIL) == EMAIL
    # y un segundo archivo con el mismo RUT escrito con puntos se detecta como duplicado
    otra = client.post("/importaciones/catalogo_persona", content=b"rut,nombre,email\n59.999.999-K,Otra,\n", headers={**admin, "Content-Type": "text/csv"}).json()
    assert otra["estado"] == "con_errores" and "Ya existe" in otra["filas"][0]["errores"][0]["falla"]


# ---- rotación ------------------------------------------------------------------------------------
def test_rotar_claves_recifra_y_la_vieja_ya_no_hace_falta(client, admin, db, settings):
    client.post("/personas", headers=admin, json={"rut": RUT, "nombre": "X", "email": EMAIL})
    vieja = settings.cifrador()
    nueva = pii.Cifrador.desde_entorno(f"{CLAVE_DATOS},k2={k(b'E')}", "k2", CLAVE_INDICE)
    antes = db.execute("SELECT rut_cifrado FROM catalogo_persona").fetchone()[0]
    assert antes.startswith("v1:k1:")
    assert rotar(db, nueva)["catalogo_persona.rut_cifrado"] == 1
    despues = db.execute("SELECT rut_cifrado, email_cifrado FROM catalogo_persona").fetchone()
    assert despues[0].startswith("v1:k2:") and despues[1].startswith("v1:k2:")
    assert nueva.descifrar(despues[0], pii.COL_RUT) == RUT
    assert rotar(db, nueva)["catalogo_persona.rut_cifrado"] == 0             # repetirlo no cambia nada
    solo_vieja = pii.Cifrador.desde_entorno(CLAVE_DATOS, "k1", CLAVE_INDICE)
    with pytest.raises(pii.DatoAlterado):
        solo_vieja.descifrar(despues[0], pii.COL_RUT)                          # quitar k1 ya es seguro
    assert vieja.indice_rut(RUT) == nueva.indice_rut(RUT)                      # el índice no cambia con la rotación


# ---- el resto del sistema ----------------------------------------------------------------------------
def test_directus_no_ve_las_columnas_cifradas():
    con = sqlite3.connect(":memory:")
    con.executescript((Path(__file__).resolve().parents[2] / "db" / "esquema_plataforma.sql").read_text(encoding="utf-8"))
    info = m.esquema(con)
    perm = {p["collection"]: p for p in m.permisos_de_lectura(info, {"personas.ver_datos_personales", "horarios.enviar", "catalogo.ver"})}
    assert set(perm["catalogo_persona"]["fields"]) == {"id", "nombre", "eliminado_en", "eliminado_por"}
    assert not any("cifrado" in c for c in perm["horarios_envio_horario"]["fields"])


def test_la_replica_de_satelites_no_tiene_columnas_personales():
    from app.publicacion import COPIAS
    assert not any(p in c for c in COPIAS.values() for p in ("rut", "email", "persona"))
