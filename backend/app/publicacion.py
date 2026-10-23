"""Publicación para los módulos satélite.

Los grupos de Proyecto Integrador leen por Directus un archivo SQLite APARTE (satelites.db): una réplica de solo
lectura con tablas pub_*, que se regenera desde el núcleo. Así los satélites no comparten archivo con el único
escritor del núcleo y nunca tocan datos personales: aquí no se copia ninguna persona, docente, nombramiento,
finanza ni auditoría. Solo catálogo y el horario de la propuesta aprobada.

Uso: python -m app.publicacion        (o POST /publicacion con el permiso horarios.exportar)
"""
import sqlite3
from pathlib import Path

DDL = """
CREATE TABLE IF NOT EXISTS pub_periodo (id INTEGER PRIMARY KEY, codigo TEXT NOT NULL, estado TEXT NOT NULL) STRICT;
CREATE TABLE IF NOT EXISTS pub_programa (id INTEGER PRIMARY KEY, codigo TEXT NOT NULL, nombre TEXT, tipo TEXT) STRICT;
CREATE TABLE IF NOT EXISTS pub_asignatura (id INTEGER PRIMARY KEY, codigo TEXT, nombre TEXT NOT NULL, area TEXT,
                             requiere_laboratorio INTEGER NOT NULL) STRICT;
CREATE TABLE IF NOT EXISTS pub_sala (id INTEGER PRIMARY KEY, codigo TEXT NOT NULL, nombre TEXT, capacidad INTEGER,
                       es_laboratorio INTEGER NOT NULL) STRICT;
CREATE TABLE IF NOT EXISTS pub_paralelo (id INTEGER PRIMARY KEY, periodo_id INTEGER NOT NULL, asignatura_id INTEGER NOT NULL,
                           codigo TEXT NOT NULL, nrc INTEGER, componente TEXT, cupo_estimado INTEGER) STRICT;
CREATE TABLE IF NOT EXISTS pub_horario (id INTEGER PRIMARY KEY, paralelo_id INTEGER NOT NULL, sesion INTEGER NOT NULL,
                          dia TEXT NOT NULL, bloque TEXT NOT NULL, sala_codigo TEXT) STRICT;
CREATE TABLE IF NOT EXISTS pub_estado (id INTEGER PRIMARY KEY CHECK (id = 1), publicado_en TEXT NOT NULL) STRICT;
"""

COPIAS = {
    "pub_periodo": "SELECT id, codigo, estado FROM catalogo_periodo WHERE departamento_id = 1",
    "pub_programa": "SELECT id, codigo, nombre, tipo FROM catalogo_programa WHERE eliminado_en IS NULL AND departamento_id = 1",
    "pub_asignatura": "SELECT id, codigo, nombre, area, requiere_laboratorio FROM catalogo_asignatura "
                      "WHERE eliminado_en IS NULL AND departamento_id = 1",
    "pub_sala": "SELECT id, codigo, nombre, capacidad, es_laboratorio FROM catalogo_sala "
                "WHERE eliminado_en IS NULL AND activa = 1 AND departamento_id = 1",
    "pub_paralelo": "SELECT pa.id, pa.periodo_id, pa.asignatura_id, pa.codigo, pa.nrc, pa.componente, pa.cupo_estimado "
                    "FROM horarios_paralelo pa JOIN catalogo_periodo pe ON pe.id = pa.periodo_id "
                    "WHERE pa.eliminado_en IS NULL AND pe.departamento_id = 1",
    "pub_horario": "SELECT a.id, s.paralelo_id, s.numero, a.dia, a.bloque, sa.codigo "
                   "FROM horarios_asignacion a "
                   "JOIN horarios_propuesta p ON p.id = a.propuesta_id AND p.estado = 'aprobada' "
                   "JOIN horarios_sesion s ON s.id = a.sesion_id AND s.eliminado_en IS NULL "
                   "JOIN horarios_paralelo pa ON pa.id = s.paralelo_id AND pa.eliminado_en IS NULL "
                   "JOIN catalogo_periodo pe ON pe.id = pa.periodo_id AND pe.departamento_id = 1 "
                   "LEFT JOIN catalogo_sala sa ON sa.id = a.sala_id",
}


def publicar(core: sqlite3.Connection, ruta_satelites: str) -> dict:
    """Reemplaza las tablas pub_* en satelites.db. Devuelve cuántas filas quedaron en cada una."""
    Path(ruta_satelites).parent.mkdir(parents=True, exist_ok=True)
    sat = sqlite3.connect(ruta_satelites, isolation_level=None, timeout=10)
    try:
        sat.execute("PRAGMA journal_mode = WAL")
        sat.execute("PRAGMA busy_timeout = 5000")
        sat.execute("BEGIN IMMEDIATE")
        for sentencia in DDL.split(";"):
            if sentencia.strip():
                sat.execute(sentencia)
        cuentas = {}
        for tabla in reversed(list(COPIAS)):       # réplica: se regenera completa (no es el núcleo)
            sat.execute(f"DELETE FROM {tabla}")
        for tabla, consulta in COPIAS.items():
            filas = core.execute(consulta).fetchall()
            if filas:
                sat.executemany(f"INSERT INTO {tabla} VALUES ({','.join('?' * len(filas[0]))})", [tuple(f) for f in filas])
            cuentas[tabla] = len(filas)
        sat.execute("INSERT OR REPLACE INTO pub_estado (id, publicado_en) VALUES (1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))")
        sat.execute("COMMIT")
        return cuentas
    except BaseException:
        if sat.in_transaction:
            sat.execute("ROLLBACK")
        raise
    finally:
        sat.close()


def main() -> None:
    import os
    from .core.config import get_settings
    from .core.db import conectar
    ruta = os.environ.get("SATELITES_DB_PATH", "/satelites/satelites.db")
    cuentas = publicar(conectar(get_settings().db_path), ruta)
    print("publicado:", ", ".join(f"{k}={v}" for k, v in cuentas.items()))


if __name__ == "__main__":
    main()
