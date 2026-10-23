"""Matriz rol x colección x operación de Directus, derivada del esquema y de identidad_rol_permiso.

Decisión de diseño (ver docs/directus.md): las escrituras al núcleo pasan SOLO por FastAPI, porque los triggers de
permiso y auditoría leen plataforma_contexto.usuario_id y Directus no lo fija. Por eso en Directus todas las
colecciones del núcleo son de solo lectura (incluido el rol Administrador); la columna "escritura" de la matriz
indica qué endpoint de la API cubre cada permiso.

El alcance por departamento se deduce de las claves foráneas: una tabla con departamento_id filtra por él; una
tabla que cuelga de otra (paralelo -> periodo) filtra a través de la relación.
"""
import sqlite3

# permiso de la base -> tablas que habilita para lectura en Directus
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
                           "identidad_usuario_rol", "plataforma_auditoria", "plataforma_modulo"],
    "departamentos.gestionar": ["identidad_departamento"],
}
# permisos de escritura de la base y la ruta de la API que los atiende (documentación de la matriz)
ESCRITURA_POR_API = {
    "catalogo.editar": "POST/PATCH/DELETE /periodos /programas /asignaturas /salas /personas /docentes /ayudantes",
    "catalogo.importar": "importación de la planilla (módulo de importación)",
    "horarios.editar": "POST/PATCH/DELETE /paralelos /sesiones",
    "horarios.generar": "worker de corridas de FET",
    "horarios.aprobar": "POST /propuestas/{id}/aprobar",
    "horarios.exportar": "exportación del horario",
    "horarios.enviar": "envío de horarios por correo",
    "restricciones.gestionar": "POST/PATCH/DELETE /restricciones",
    "finanzas.editar": "POST/PATCH/DELETE /tarifas /presupuestos /escenarios /nombramientos",
    "usuarios.gestionar": "/usuarios y /roles",
    "departamentos.gestionar": "gestión de departamentos",
}
# columnas que nunca se exponen por Directus
OCULTAS = {"identidad_usuario": {"hash_clave", "intentos_fallidos", "bloqueado_hasta"}}
# tablas que ningún rol lee
SIN_ACCESO = {"identidad_sesion", "plataforma_contexto"}
# este permiso levanta el filtro por departamento (lee los de todos)
PERMISO_GLOBAL = "departamentos.ver_otros"


def esquema(conn: sqlite3.Connection) -> dict:
    """tabla -> {'columnas': [...], 'fks': [(columna, tabla_padre), ...] ordenadas por conveniencia}"""
    info = {}
    for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                             "AND name NOT LIKE 'directus_%'"):
        cols = list(conn.execute(f"PRAGMA table_info({t})"))
        obligatorias = {c[1] for c in cols if c[3] or c[5]}
        fks = [(fk[3], fk[2]) for fk in conn.execute(f"PRAGMA foreign_key_list({t})")]
        # para heredar el departamento conviene una FK obligatoria (no deja filas fuera) y, entre ellas, el periodo
        fks.sort(key=lambda f: (f[0] not in obligatorias, f[1] != "catalogo_periodo"))
        info[t] = {"columnas": [c[1] for c in cols], "fks": fks}
    return info


def filtro_departamento(info: dict, tabla: str, variable: str = "$CURRENT_USER.departamento_id", _prof: int = 0):
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


def permisos_de_lectura(info: dict, permisos_del_rol: set[str]) -> list[dict]:
    """Permisos de Directus (colección, acción, campos, filtro) para un rol con esos permisos de base."""
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
                f = filtro_departamento(info, tabla)
                if f:
                    filtros.append(f)
            campos = [c for c in info[tabla]["columnas"] if c not in OCULTAS.get(tabla, set())]
            out.append({"collection": tabla, "action": "read", "fields": campos,
                        "permissions": {"_and": filtros} if len(filtros) > 1 else (filtros[0] if filtros else {})})
    return out


def matriz(conn_core: sqlite3.Connection) -> list[dict]:
    """Filas legibles de la matriz: rol, colección, lectura (Directus) y ruta de escritura (API)."""
    info = esquema(conn_core)
    filas = []
    for rol in [r[0] for r in conn_core.execute("SELECT codigo FROM identidad_rol WHERE eliminado_en IS NULL ORDER BY codigo")]:
        perms = {p[0] for p in conn_core.execute(
            "SELECT permiso FROM identidad_rol_permiso WHERE rol = ? AND revocado_en IS NULL", (rol,))}
        leer = permisos_de_lectura(info, perms)
        escribe = sorted(ESCRITURA_POR_API[p] for p in perms if p in ESCRITURA_POR_API)
        filas.append({"rol": rol, "lectura": sorted(p["collection"] for p in leer),
                      "alcance": "todos los departamentos" if PERMISO_GLOBAL in perms else "solo su departamento",
                      "escritura_por_api": escribe})
    return filas
