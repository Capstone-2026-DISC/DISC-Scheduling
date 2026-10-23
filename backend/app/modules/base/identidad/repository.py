"""Acceso a datos de identidad: usuarios, sesiones y roles."""
import sqlite3

from ....core.db import escritura
from ....core.recurso import ahora_sql


def usuario_por_email(conn: sqlite3.Connection, email: str):
    return conn.execute("SELECT * FROM identidad_usuario WHERE email = ? AND eliminado_en IS NULL",
                        (email.strip().lower(),)).fetchone()


def usuario_por_id(conn: sqlite3.Connection, uid: int):
    return conn.execute("SELECT * FROM identidad_usuario WHERE id = ? AND eliminado_en IS NULL", (uid,)).fetchone()


def listar_usuarios(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for u in conn.execute("SELECT id, email, nombre, tipo, activo, ultimo_acceso_en FROM identidad_usuario "
                          "WHERE eliminado_en IS NULL ORDER BY id"):
        roles = [dict(r) for r in conn.execute(
            "SELECT id, rol, departamento_id FROM identidad_usuario_rol WHERE usuario_id = ? AND revocado_en IS NULL",
            (u["id"],))]
        out.append({**dict(u), "roles": roles})
    return out


def listar_roles(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for r in conn.execute("SELECT codigo, nombre, descripcion, es_sistema FROM identidad_rol "
                          "WHERE eliminado_en IS NULL AND activo = 1 ORDER BY codigo"):
        permisos = [p["permiso"] for p in conn.execute(
            "SELECT permiso FROM identidad_rol_permiso WHERE rol = ? AND revocado_en IS NULL ORDER BY permiso",
            (r["codigo"],))]
        out.append({**dict(r), "permisos": permisos})
    return out


def crear_usuario(conn, actor_id: int, ip: str | None, email: str, nombre: str, hash_clave: str) -> int:
    with escritura(conn, actor_id, ip):
        return conn.execute("INSERT INTO identidad_usuario (email, nombre, hash_clave) VALUES (?, ?, ?)",
                            (email, nombre, hash_clave)).lastrowid


def asignar_rol(conn, actor_id, ip, usuario_id: int, rol: str, departamento_id: int | None) -> int:
    with escritura(conn, actor_id, ip):
        return conn.execute("INSERT INTO identidad_usuario_rol (usuario_id, rol, departamento_id, asignado_por) "
                            "VALUES (?, ?, ?, ?)", (usuario_id, rol, departamento_id, actor_id)).lastrowid


def revocar_rol(conn, actor_id, ip, asignacion_id: int) -> int:
    with escritura(conn, actor_id, ip):
        return conn.execute(f"UPDATE identidad_usuario_rol SET revocado_en = {ahora_sql()} "
                            "WHERE id = ? AND revocado_en IS NULL", (asignacion_id,)).rowcount


def dar_permiso(conn, actor_id, ip, rol: str, permiso: str) -> None:
    with escritura(conn, actor_id, ip):
        cur = conn.execute("UPDATE identidad_rol_permiso SET revocado_en = NULL WHERE rol = ? AND permiso = ?",
                           (rol, permiso))
        if cur.rowcount == 0:
            conn.execute("INSERT INTO identidad_rol_permiso (rol, permiso) VALUES (?, ?)", (rol, permiso))


def quitar_permiso(conn, actor_id, ip, rol: str, permiso: str) -> int:
    with escritura(conn, actor_id, ip):
        return conn.execute(f"UPDATE identidad_rol_permiso SET revocado_en = {ahora_sql()} "
                            "WHERE rol = ? AND permiso = ? AND revocado_en IS NULL", (rol, permiso)).rowcount


def eliminar_usuario(conn, actor_id, ip, uid: int) -> int:
    with escritura(conn, actor_id, ip):
        n = conn.execute(f"UPDATE identidad_usuario SET eliminado_en = {ahora_sql()}, eliminado_por = ?, activo = 0 "
                         "WHERE id = ? AND eliminado_en IS NULL", (actor_id, uid)).rowcount
        conn.execute(f"UPDATE identidad_sesion SET revocada_en = {ahora_sql()} WHERE usuario_id = ? AND revocada_en IS NULL",
                     (uid,))
        return n
