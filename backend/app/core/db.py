"""Conexión SQLite y transacción de escritura con contexto de usuario.

Los triggers del esquema comprueban permisos y auditan leyendo plataforma_contexto, que la
aplicación fija dentro de BEGIN IMMEDIATE (SQLite admite un solo escritor, así que es seguro).
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def conectar(ruta: str) -> sqlite3.Connection:
    conn = sqlite3.connect(ruta, isolation_level=None, check_same_thread=False, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def crear_si_falta(ruta: str, esquema: str) -> bool:
    """Crea la base desde el esquema si el archivo no existe. Devuelve True si la creó."""
    if Path(ruta).exists() and Path(ruta).stat().st_size > 0:
        return False
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ruta, isolation_level=None)
    try:
        conn.executescript(Path(esquema).read_text(encoding="utf-8"))
        conn.execute("PRAGMA journal_mode = WAL")
    finally:
        conn.close()
    return True


@contextmanager
def escritura(conn: sqlite3.Connection, usuario_id: int | None, ip: str | None = None):
    """BEGIN IMMEDIATE con el usuario y la IP en el contexto; al terminar los limpia y confirma."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("UPDATE plataforma_contexto SET usuario_id = ?, ip = ? WHERE id = 1", (usuario_id, ip))
        yield conn
        conn.execute("UPDATE plataforma_contexto SET usuario_id = NULL, ip = NULL WHERE id = 1")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
