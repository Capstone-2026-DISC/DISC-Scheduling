"""Migración inicial: crea la base desde el esquema si el archivo no existe. Es el único paso, junto con el configurador
y el generador de datos de prueba, que abre SQLite directamente; el resto de la plataforma pasa por Directus.

Uso: python -m app.migrar       (variables: DB_PATH, SCHEMA_PATH)
"""
import os
import sqlite3
from pathlib import Path


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


def main() -> None:
    ruta = os.environ.get("DB_PATH", "/data/plataforma.db")
    creada = crear_si_falta(ruta, os.environ.get("SCHEMA_PATH", "/app/db/esquema_plataforma.sql"))
    print("base creada desde el esquema" if creada else "la base ya existe; no se cambió nada")


if __name__ == "__main__":
    main()
