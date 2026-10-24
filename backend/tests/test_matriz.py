"""La matriz de permisos de Directus: derivada del esquema y de los 18 permisos lógicos."""
import sqlite3
from pathlib import Path

import pytest

from app import directus_matriz as m

ESQUEMA = Path(__file__).resolve().parents[2] / "db" / "esquema_plataforma.sql"


@pytest.fixture(scope="module")
def info():
    con = sqlite3.connect(":memory:")
    con.executescript(ESQUEMA.read_text(encoding="utf-8"))
    return m.esquema(con), con


@pytest.fixture(scope="module")
def esq(info):
    return info[0]


def permisos_logicos(info):
    return {f[0] for f in info[1].execute("SELECT codigo FROM identidad_permiso")}


def por_clave(lista):
    return {(p["collection"], p["action"]): p for p in lista}


def test_la_matriz_cubre_los_18_permisos_del_esquema(info):
    todos = permisos_logicos(info)
    assert len(todos) == 18
    cubiertos = set(m.LECTURA) | set(m.ESCRITURA) | set(m.API_POR_PERMISO) | {m.PERMISO_GLOBAL}
    assert todos <= cubiertos, f"permisos sin tratamiento en la matriz: {sorted(todos - cubiertos)}"


def test_la_matriz_solo_menciona_tablas_que_existen(esq):
    for tablas in m.LECTURA.values():
        for t in tablas:
            assert t in esq, t
    for colecciones in m.ESCRITURA.values():
        for t in colecciones:
            assert t in esq, t


def test_toda_tabla_del_nucleo_tiene_clave_simple_para_directus(info):
    for t in info[0]:
        pks = [c for c in info[1].execute(f"PRAGMA table_info({t})") if c[5]]
        assert len(pks) == 1, f"{t} tiene clave compuesta; Directus la ignoraría"


def test_alcance_por_departamento_derivado_de_las_claves(esq):
    assert m.filtro_departamento(esq, "catalogo_sala") == {"departamento_id": {"_eq": m.VAR_DEPTO}}
    f = m.filtro_departamento(esq, "horarios_sesion")                  # sesion -> paralelo -> periodo -> departamento
    assert "paralelo_id" in f and "periodo_id" in f["paralelo_id"]
    assert m.filtro_departamento(esq, "catalogo_dia") is None


def test_lectura_por_rol(esq):
    cons = por_clave(m.permisos_de_lectura(esq, {"catalogo.ver", "horarios.ver", "restricciones.ver"}))
    assert ("catalogo_sala", "read") in cons and ("finanzas_tarifa", "read") not in cons and ("catalogo_persona", "read") not in cons
    assert "eliminado_en" in str(cons[("catalogo_sala", "read")]["permissions"]) and "departamento_id" in str(cons[("catalogo_sala", "read")]["permissions"])
    admin = por_clave(m.permisos_de_lectura(esq, {"catalogo.ver", "usuarios.gestionar", "personas.ver_datos_personales", m.PERMISO_GLOBAL}))
    assert "departamento_id" not in str(admin[("catalogo_sala", "read")]["permissions"])
    assert "rut_cifrado" in admin[("catalogo_persona", "read")]["fields"]            # la API los lee para descifrar
    assert ("identidad_sesion", "read") not in admin and ("plataforma_contexto", "read") not in admin


def test_sin_permisos_de_escritura_no_hay_escritura(esq):
    assert m.permisos_de_escritura(esq, {"catalogo.ver", "horarios.ver", "restricciones.ver"}) == []


def test_un_encargado_escribe_solo_en_su_departamento(esq):
    perms = {"catalogo.ver", "catalogo.editar", "horarios.editar", "restricciones.gestionar"}
    w = por_clave(m.permisos_de_escritura(esq, perms))
    sala = w[("catalogo_sala", "create")]
    assert sala["validation"] == {"departamento_id": {"_eq": m.VAR_DEPTO}} and sala["presets"] == {"departamento_id": m.VAR_DEPTO}
    upd = w[("catalogo_sala", "update")]
    assert "departamento_id" in str(upd["permissions"]) and "eliminado_en" in str(upd["permissions"]) and "validation" in upd
    assert "eliminado_en" in upd["fields"] and "eliminado_por" in upd["fields"] and "id" not in upd["fields"]
    par = w[("horarios_paralelo", "update")]
    assert "periodo_id" in str(par["permissions"])                                   # hereda el departamento del periodo
    assert "validation" not in w[("horarios_paralelo", "create")]                    # la API comprueba la relación antes de crear


def test_el_borrado_real_solo_existe_para_las_asignaciones_de_un_borrador(esq):
    todo = set(m.ESCRITURA)
    w = m.permisos_de_escritura(esq, todo | {m.PERMISO_GLOBAL})
    assert {p["collection"] for p in w if p["action"] == "delete"} == {"horarios_asignacion"}


def test_un_rol_global_no_lleva_filtros_ni_validaciones_de_departamento(esq):
    w = por_clave(m.permisos_de_escritura(esq, {"catalogo.editar", m.PERMISO_GLOBAL}))
    assert "validation" not in w[("catalogo_sala", "create")] and "presets" not in w[("catalogo_sala", "create")]
    assert "departamento_id" not in str(w[("catalogo_sala", "update")]["permissions"])


def test_aprobar_solo_toca_el_estado_y_quien_aprueba(esq):
    w = por_clave(m.permisos_de_escritura(esq, {"horarios.aprobar"}))
    assert w[("horarios_propuesta", "update")]["fields"] == ["estado", "aprobada_por"]
    assert ("horarios_propuesta", "create") not in w


def test_generar_o_editar_horarios_no_aprueba(esq):
    for perm in ("horarios.generar", "horarios.editar"):
        w = por_clave(m.permisos_de_escritura(esq, {perm}))
        campos = w.get(("horarios_propuesta", "update"), {"fields": []})["fields"]
        assert "estado" not in campos and "aprobada_por" not in campos
    ambos = por_clave(m.permisos_de_escritura(esq, {"horarios.generar", "horarios.aprobar"}))
    assert "estado" in ambos[("horarios_propuesta", "update")]["fields"]               # con el permiso de aprobar, sí


def test_nadie_escribe_la_auditoria_de_eventos_por_directus(esq):
    for p in m.permisos_de_escritura(esq, set(m.ESCRITURA) | {"usuarios.gestionar"}):
        assert p["collection"] != "plataforma_auditoria"


def test_gestionar_usuarios_no_se_da_por_directus(esq):
    assert not [p for p in m.permisos_de_escritura(esq, {"usuarios.gestionar"}) if p["collection"].startswith(("identidad_", "directus_"))]


def test_permisos_propios_para_ver_el_perfil_y_cambiar_la_clave():
    p = por_clave(m.permisos_propios())
    assert p[("directus_users", "read")]["permissions"] == {"id": {"_eq": "$CURRENT_USER"}}
    assert p[("directus_users", "update")]["fields"] == ["password"]


def test_la_cuenta_de_servicio_tiene_minimos_privilegios(esq):
    p = m.permisos_servicio(esq, ["rol-1", "rol-2"])
    acciones = {(x["collection"], x["action"]) for x in p}
    assert {c for c, a in acciones if a == "delete"} == set(m.PUBLICADAS) | {"pub_estado"}      # solo regenera la copia, nada del núcleo
    assert {c for c, a in acciones if a == "create" and c.startswith("pub_")} == set(m.PUBLICADAS) | {"pub_estado"}
    assert not any(c in ("directus_policies", "directus_permissions", "directus_roles") and a != "read" for c, a in acciones)
    crear = next(x for x in p if x["collection"] == "directus_users" and x["action"] == "create")
    assert crear["validation"] == {"_or": [{"role": {"_in": ["rol-1", "rol-2"]}}, {"role": {"_null": True}}]}   # nunca el rol Administrator
    assert ("catalogo_persona", "read") not in acciones and ("catalogo_docente", "read") not in acciones   # sin datos personales
    assert ("plataforma_auditoria", "create") in acciones and ("catalogo_sala", "create") not in acciones


def test_la_tabla_de_matriz_resume_cada_rol(esq):
    filas = m.matriz(esq, {"consulta": {"catalogo.ver"}, "administrador": {"catalogo.ver", "catalogo.editar", m.PERMISO_GLOBAL}})
    adm = next(f for f in filas if f["rol"] == "administrador")
    assert adm["alcance"] == "todos los departamentos" and "catalogo_sala (create)" in adm["escritura"] and adm["por_api"]
    assert next(f for f in filas if f["rol"] == "consulta")["escritura"] == []


def test_un_grupo_lee_la_copia_y_solo_escribe_en_lo_suyo():
    p = m.permisos_de_grupo("g1")
    acciones = {(x["collection"], x["action"]) for x in p}
    assert {c for c, a in acciones if a == "read"} == set(m.PUBLICADAS) | {"pub_estado", "sat_g1_registro"}
    assert {c for c, a in acciones if a != "read"} == {"sat_g1_registro"}                       # nunca pub_*, nunca otro grupo
    assert not any(a == "delete" for _, a in acciones)                                          # borrado lógico
    assert not any(c.startswith(("catalogo_", "finanzas_", "identidad_", "plataforma_", "directus_")) for c, _ in acciones)
