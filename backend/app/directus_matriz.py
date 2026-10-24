"""Matriz rol x colección x operación de Directus, derivada del esquema y de identidad_rol_permiso.

Directus es la única capa de acceso a los datos: la API le habla con la sesión de cada persona y Directus aplica estos
permisos y registra la actividad. Cada rol de la plataforma (administrador, encargado_docente, consulta...) es un rol de
Directus con su política, generada aquí a partir de sus permisos lógicos (los 18 de identidad_permiso).

* El alcance por departamento se deduce de las claves foráneas: una tabla con departamento_id filtra por él; una tabla
  que cuelga de otra (paralelo -> periodo) filtra a través de la relación. Los roles con departamentos.ver_otros no
  llevan filtro. Al crear, el departamento del usuario se fija solo (preset) y no se puede apuntar a otro (validación).
* El borrado es lógico: nadie tiene permiso de DELETE, salvo sobre las asignaciones de un borrador. "Eliminar" es
  actualizar eliminado_en y eliminado_por.
* Gestionar usuarios no se da por Directus: lo hace la API con una cuenta de servicio acotada.
"""
import sqlite3

# permiso lógico -> colecciones que habilita para lectura
LECTURA = {
    "catalogo.ver": ["catalogo_periodo", "catalogo_programa", "catalogo_asignatura", "catalogo_plan_nivel", "catalogo_dia",
                     "catalogo_bloque", "catalogo_sala", "catalogo_docente", "catalogo_ayudante"],
    "personas.ver_datos_personales": ["catalogo_persona"],
    "catalogo.importar": ["plataforma_importacion", "plataforma_fila_importada"],
    "horarios.ver": ["horarios_liga", "horarios_paralelo", "horarios_paralelo_docente", "horarios_paralelo_grupo",
                     "horarios_sesion", "horarios_disponibilidad_docente", "horarios_bloqueo_sala",
                     "horarios_sala_externa_autorizada", "horarios_reserva_nivel", "horarios_perfil", "horarios_corrida",
                     "horarios_corrida_actividad", "horarios_propuesta", "horarios_asignacion", "horarios_hallazgo"],
    "horarios.enviar": ["horarios_envio_horario"],
    "restricciones.ver": ["horarios_restriccion"],
    "finanzas.ver": ["finanzas_categoria", "finanzas_escenario", "finanzas_tarifa", "finanzas_presupuesto",
                     "finanzas_categoria_persona", "finanzas_nombramiento", "finanzas_calculo", "finanzas_calculo_detalle"],
    "proyeccion.ver": ["proyeccion_inscripcion_historica", "proyeccion_estimacion_externa", "proyeccion_estimacion"],
    "usuarios.gestionar": ["identidad_usuario", "identidad_rol", "identidad_permiso", "identidad_rol_permiso",
                           "plataforma_auditoria", "plataforma_modulo"],
    "departamentos.gestionar": ["identidad_departamento"],
}
# permiso lógico -> {colección: acciones}. Las colecciones de la lista de importación se agregan en create.
_IMPORTABLES = ["catalogo_periodo", "catalogo_programa", "catalogo_asignatura", "catalogo_sala", "catalogo_persona",
                "catalogo_docente", "catalogo_ayudante", "horarios_paralelo", "horarios_sesion",
                "horarios_disponibilidad_docente", "proyeccion_inscripcion_historica"]
ESCRITURA = {
    "catalogo.editar": {c: ("create", "update") for c in ["catalogo_periodo", "catalogo_programa", "catalogo_asignatura",
                                                         "catalogo_plan_nivel", "catalogo_sala", "catalogo_persona",
                                                         "catalogo_docente", "catalogo_ayudante"]},
    "catalogo.importar": {**{c: ("create",) for c in _IMPORTABLES},
                          "plataforma_importacion": ("create", "update"), "plataforma_fila_importada": ("create",)},
    "horarios.editar": {**{c: ("create", "update") for c in ["horarios_liga", "horarios_paralelo", "horarios_paralelo_docente",
                                                             "horarios_paralelo_grupo", "horarios_sesion",
                                                             "horarios_disponibilidad_docente", "horarios_bloqueo_sala",
                                                             "horarios_sala_externa_autorizada", "horarios_reserva_nivel"]},
                        "horarios_asignacion": ("create", "update", "delete")},
    "horarios.generar": {c: ("create", "update") for c in ["horarios_corrida", "horarios_corrida_actividad", "horarios_hallazgo",
                                                           "horarios_propuesta"]},
    "horarios.aprobar": {"horarios_propuesta": ("update",)},
    "horarios.exportar": {"horarios_envio_horario": ("create", "update")},
    "horarios.enviar": {"horarios_envio_horario": ("create", "update")},
    "restricciones.gestionar": {"horarios_restriccion": ("create", "update")},
    "finanzas.editar": {c: ("create", "update") for c in ["finanzas_escenario", "finanzas_tarifa", "finanzas_presupuesto",
                                                          "finanzas_categoria_persona", "finanzas_nombramiento"]},
    "departamentos.gestionar": {"identidad_departamento": ("create", "update")},
}
# campos de una escritura restringida (el resto de la colección no se puede tocar con ese permiso)
CAMPOS_RESTRINGIDOS = {("horarios.aprobar", "horarios_propuesta"): ["estado", "aprobada_por"]}
# campos que un permiso NO puede escribir aunque escriba la colección: generar propuestas no es aprobarlas
CAMPOS_EXCLUIDOS = {("horarios.generar", "horarios_propuesta"): ["estado", "aprobada_por", "aprobada_en", "reemplazada_por"],
                    ("horarios.editar", "horarios_propuesta"): ["estado", "aprobada_por", "aprobada_en", "reemplazada_por"]}
# cómo se lleva a cabo cada permiso lógico a través de la API (documentación de la matriz)
API_POR_PERMISO = {
    "catalogo.editar": "POST/PATCH/DELETE /periodos /programas /asignaturas /salas /personas /docentes /ayudantes",
    "catalogo.importar": "POST /importaciones/{coleccion}",
    "horarios.editar": "POST/PATCH/DELETE /paralelos /sesiones",
    "horarios.generar": "worker de corridas de FET",
    "horarios.aprobar": "POST /propuestas/{id}/aprobar",
    "horarios.exportar": "POST /publicacion; exportación del horario",
    "horarios.enviar": "envío de horarios por correo",
    "restricciones.gestionar": "POST/PATCH/DELETE /restricciones",
    "finanzas.editar": "POST/PATCH/DELETE /tarifas /presupuestos /escenarios /nombramientos",
    "usuarios.gestionar": "/usuarios y asignación de roles, por la cuenta de servicio de la API",
    "departamentos.gestionar": "gestión de departamentos",
}
# columnas que nadie lee por Directus
OCULTAS = {"horarios_envio_horario": {"email_destino_cifrado"}}
# tablas que ningún rol toca
SIN_ACCESO: set[str] = set()
PERMISO_GLOBAL = "departamentos.ver_otros"       # este permiso levanta el filtro por departamento
SOLO_SERVICIO_ESCRIBE = {"plataforma_auditoria"}  # lo escribe la cuenta de servicio de la API, no las personas
VAR_DEPTO = "$CURRENT_USER.departamento_id"


def esquema(conn: sqlite3.Connection) -> dict:
    """tabla -> {'columnas': [...], 'pk': columna, 'fks': [(columna, tabla_padre), ...] ordenadas por conveniencia}.
    Se puede alimentar con una base en memoria creada desde db/esquema_plataforma.sql."""
    info = {}
    for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                             "AND name NOT LIKE 'directus_%'"):
        cols = list(conn.execute(f"PRAGMA table_info({t})"))
        obligatorias = {c[1] for c in cols if c[3] or c[5]}
        fks = [(fk[3], fk[2]) for fk in conn.execute(f"PRAGMA foreign_key_list({t})")]
        # para heredar el departamento conviene una FK obligatoria (no deja filas fuera) y, entre ellas, el periodo
        fks.sort(key=lambda f: (f[0] not in obligatorias, f[1] != "catalogo_periodo"))
        pk = next((c[1] for c in cols if c[5]), "id")
        info[t] = {"columnas": [c[1] for c in cols], "pk": pk, "fks": fks}
    return info


def filtro_departamento(info: dict, tabla: str, variable: str = VAR_DEPTO, _prof: int = 0):
    """Filtro de Directus que limita la tabla al departamento del usuario, o None si la tabla no tiene alcance."""
    cols = info[tabla]["columnas"]
    if tabla == "identidad_departamento":
        return {"id": {"_eq": variable}}
    if "departamento_id" in cols:
        return {"departamento_id": {"_eq": variable}}
    if _prof >= 3:
        return None
    for col, padre in info[tabla]["fks"]:
        if padre in info and padre != "identidad_usuario":
            interno = filtro_departamento(info, padre, variable, _prof + 1)
            if interno:
                return {col: interno}
    return None


def _y(*filtros):
    filtros = [f for f in filtros if f]
    return {} if not filtros else (filtros[0] if len(filtros) == 1 else {"_and": filtros})


def permisos_de_lectura(info: dict, permisos_del_rol: set[str]) -> list[dict]:
    """Permisos de lectura de Directus (colección, campos, filtro) para un rol con esos permisos lógicos."""
    global_ = PERMISO_GLOBAL in permisos_del_rol
    out = []
    for permiso, tablas in LECTURA.items():
        if permiso not in permisos_del_rol:
            continue
        for tabla in tablas:
            if tabla not in info or tabla in SIN_ACCESO:
                continue
            filtros = []
            if "eliminado_en" in info[tabla]["columnas"]:
                filtros.append({"eliminado_en": {"_null": True}})        # el borrado lógico no se ve
            if not global_:
                filtros.append(filtro_departamento(info, tabla))
            campos = [c for c in info[tabla]["columnas"] if c not in OCULTAS.get(tabla, set())]
            out.append({"collection": tabla, "action": "read", "fields": campos, "permissions": _y(*filtros)})
    return out


def permisos_de_escritura(info: dict, permisos_del_rol: set[str]) -> list[dict]:
    """create, update y delete. El alcance por departamento va en el filtro del update y en la validación y el preset del create."""
    global_ = PERMISO_GLOBAL in permisos_del_rol
    acciones: dict[tuple[str, str], set[str]] = {}
    for permiso, colecciones in ESCRITURA.items():
        if permiso not in permisos_del_rol:
            continue
        for tabla, accs in colecciones.items():
            if tabla not in info or tabla in SOLO_SERVICIO_ESCRIBE:
                continue
            for a in accs:
                acciones.setdefault((tabla, a), set()).add(permiso)
    out = []
    for (tabla, accion), permisos in sorted(acciones.items()):
        cols = info[tabla]["columnas"]
        pk = info[tabla]["pk"]
        # los campos que se pueden escribir son la unión de lo que permite cada permiso lógico que toca la colección
        campos: list[str] = []
        for p in sorted(permisos):
            if (p, tabla) in CAMPOS_RESTRINGIDOS:
                propios = list(CAMPOS_RESTRINGIDOS[(p, tabla)])
            else:
                propios = [c for c in cols if (c != pk or accion == "create") and c not in CAMPOS_EXCLUIDOS.get((p, tabla), [])]
            campos += [c for c in propios if c not in campos]
        if tabla in OCULTAS:
            campos = [c for c in campos if c not in OCULTAS[tabla]]
        dept = None if global_ else filtro_departamento(info, tabla)
        if accion == "delete":
            out.append({"collection": tabla, "action": "delete", "permissions": _y(dept)})
            continue
        permiso = {"collection": tabla, "action": accion, "fields": campos}
        if accion == "update":
            permiso["permissions"] = _y({"eliminado_en": {"_null": True}} if "eliminado_en" in cols else None, dept)
        if dept and "departamento_id" in cols:
            permiso["validation"] = {"departamento_id": {"_eq": VAR_DEPTO}}        # no se escribe en otro departamento
            if accion == "create":
                permiso["presets"] = {"departamento_id": VAR_DEPTO}               # si se omite, es el del usuario
        out.append(permiso)
    return out


def permisos_propios() -> list[dict]:
    """Lo que toda persona necesita: ver su perfil y su rol, cambiar su clave y conocer los departamentos (para elegirlos y
    para que una importación explique que no puede cargar en uno ajeno)."""
    return [
        {"collection": "identidad_departamento", "action": "read", "fields": ["id", "codigo", "nombre", "activo", "predeterminado"],
         "permissions": {"eliminado_en": {"_null": True}}},
        {"collection": "directus_users", "action": "read", "fields": ["id", "email", "first_name", "status", "role", "departamento_id"],
         "permissions": {"id": {"_eq": "$CURRENT_USER"}}},
        {"collection": "directus_users", "action": "update", "fields": ["password"], "permissions": {"id": {"_eq": "$CURRENT_USER"}}},
        {"collection": "directus_roles", "action": "read", "fields": ["id", "name"], "permissions": {"id": {"_eq": "$CURRENT_ROLE"}}},
    ]


def permisos_servicio(info: dict, roles_de_plataforma_ids: list[str]) -> list[dict]:
    """Cuenta de servicio de la API: crea y modifica usuarios (solo con roles de la plataforma), lleva el espejo y la
    auditoría, y lee lo que se publica a los satélites. No borra nada, no toca políticas ni permisos."""
    # el rol debe ser uno de la plataforma, o quedar vacío (quitar el rol): nunca el Administrator de Directus
    rol_valido = {"_or": [{"role": {"_in": roles_de_plataforma_ids}}, {"role": {"_null": True}}]}
    p = [
        {"collection": "directus_users", "action": "read",
         "fields": ["id", "email", "first_name", "status", "role", "departamento_id", "intentos_fallidos", "bloqueado_hasta"], "permissions": {}},
        {"collection": "directus_users", "action": "create", "fields": ["email", "password", "first_name", "status", "role", "departamento_id"],
         "validation": rol_valido},
        {"collection": "directus_users", "action": "update",
         "fields": ["role", "departamento_id", "status", "first_name", "intentos_fallidos", "bloqueado_hasta"], "permissions": {}, "validation": rol_valido},
        {"collection": "directus_roles", "action": "read", "fields": ["id", "name"], "permissions": {}},
        {"collection": "identidad_usuario", "action": "create", "fields": [c for c in info["identidad_usuario"]["columnas"] if c != "id"]},
        {"collection": "identidad_usuario", "action": "update", "fields": [c for c in info["identidad_usuario"]["columnas"] if c != "id"], "permissions": {}},
        {"collection": "plataforma_auditoria", "action": "create", "fields": [c for c in info["plataforma_auditoria"]["columnas"] if c not in ("id", "en")]},
    ]
    leer = ["identidad_usuario", "identidad_rol", "identidad_permiso", "identidad_rol_permiso", "identidad_departamento",
            "catalogo_periodo", "catalogo_programa", "catalogo_asignatura", "catalogo_sala", "horarios_paralelo",
            "horarios_propuesta", "horarios_sesion", "horarios_asignacion"]
    p += [{"collection": t, "action": "read", "fields": ["*"], "permissions": {}} for t in leer]
    return p


def matriz(info: dict, roles: dict[str, set[str]]) -> list[dict]:
    """Filas legibles: rol, alcance, colecciones que lee, colecciones que escribe y cómo se llega a ellas por la API."""
    filas = []
    for rol, perms in sorted(roles.items()):
        leer = permisos_de_lectura(info, perms)
        escribir = permisos_de_escritura(info, perms)
        filas.append({"rol": rol,
                      "alcance": "todos los departamentos" if PERMISO_GLOBAL in perms else "solo su departamento",
                      "lectura": sorted(p["collection"] for p in leer),
                      "escritura": sorted({f"{p['collection']} ({p['action']})" for p in escribir}),
                      "por_api": sorted(API_POR_PERMISO[p] for p in perms if p in API_POR_PERMISO)})
    return filas


def documento(info: dict, roles: dict[str, set[str]]) -> str:
    """docs/matriz_permisos.md: se genera, no se edita a mano (python -m app.directus_matriz)."""
    out = ["# Matriz de roles y permisos", "",
           "Se genera desde `identidad_rol_permiso` y el esquema con `python -m app.directus_matriz > docs/matriz_permisos.md`; "
           "el CI comprueba que esté al día. Son los permisos que el configurador carga en Directus para cada rol: la API actúa con la "
           "sesión de cada persona, así que son los de Directus los que valen.", "",
           "| Rol | Alcance | Lee | Escribe | Cómo se llega por la API |", "| --- | --- | --- | --- | --- |"]
    filas = matriz(info, roles)
    for f in filas:
        out.append(f"| `{f['rol']}` | {f['alcance']} | {len(f['lectura'])} colecciones | {len(f['escritura'])} permisos | "
                   + ("; ".join(f["por_api"]) or "solo lectura") + " |")
    out += ["", "## Reglas que aplican a todos los roles", "",
            "- **Departamento.** Salvo `departamentos.ver_otros`, cada permiso se limita al departamento del usuario, deducido de las claves "
            "foráneas. Al crear, el departamento del usuario se fija solo y no se puede apuntar a otro.",
            "- **Borrado lógico.** Nadie tiene permiso de borrar, salvo las asignaciones de un borrador. Eliminar es actualizar `eliminado_en` y `eliminado_por`.",
            "- **Gestionar usuarios** no se da por Directus: lo hace la API con una cuenta de servicio que solo puede crear y modificar usuarios con roles de la plataforma.",
            "- **Aprobar horarios.** Solo `horarios.aprobar` puede cambiar el estado de una propuesta; generar o editar horarios no.",
            "- **Datos cifrados.** `catalogo_persona` solo la leen quienes tienen `personas.ver_datos_personales`, y Directus entrega texto cifrado: la API lo descifra.", ""]
    for f in filas:
        out += [f"## `{f['rol']}`", "", f"**Lee** ({len(f['lectura'])}): " + ", ".join(f"`{t}`" for t in f["lectura"]) if f["lectura"] else "**Lee**: nada", ""]
        if f["escritura"]:
            out += ["**Escribe**: " + ", ".join(f"`{e}`" for e in f["escritura"]), ""]
        else:
            out += ["**Escribe**: nada", ""]
    out += ["## Cuentas especiales", "",
            "- **Servicio de la API** (`servicio_api`): crea y modifica usuarios (solo con roles de la plataforma, nunca el Administrator de Directus), mantiene el espejo `identidad_usuario`, escribe `plataforma_auditoria` y lee lo que se publica a los satélites. No borra nada ni toca políticas.",
            "- **Administrador de arranque de Directus**: cuenta de emergencia. Puede todo menos borrar de verdad, porque lo frenan los triggers del esquema.",
            "- **Satélites** (`satelite_g1` a `g4`): viven en otra instancia y leen la réplica `pub_*`; ver `docs/backend.md`.", ""]
    return "\n".join(out)


if __name__ == "__main__":
    import os
    import sys
    from pathlib import Path
    esquema_sql = Path(os.environ.get("SCHEMA_PATH", Path(__file__).resolve().parents[2] / "db" / "esquema_plataforma.sql"))
    con = sqlite3.connect(":memory:")
    con.executescript(esquema_sql.read_text(encoding="utf-8"))
    por_rol: dict[str, set[str]] = {r[0]: set() for r in con.execute("SELECT codigo FROM identidad_rol WHERE activo = 1 AND eliminado_en IS NULL")}
    for rol, permiso in con.execute("SELECT rol, permiso FROM identidad_rol_permiso WHERE revocado_en IS NULL"):
        if rol in por_rol:
            por_rol[rol].add(permiso)
    por_rol.pop("modulo_satelite", None)
    sys.stdout.write(documento(esquema(con), por_rol) + "\n")
