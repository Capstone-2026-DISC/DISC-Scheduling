"""Publicación para los módulos satélite.

Los grupos de Proyecto Integrador leen por Directus un archivo SQLite APARTE (satelites.db): una réplica de solo
lectura con tablas pub_*, que se regenera desde el núcleo. Así los satélites no comparten archivo con el núcleo y nunca
tocan datos personales: aquí no se copia ninguna persona, docente, nombramiento, finanza ni auditoría. Solo catálogo y el
horario de la propuesta aprobada.

El núcleo se LEE por Directus, con el token del servicio. La réplica se escribe directamente porque es un dato derivado,
regenerado completo en una sola transacción; no es el sistema de registro.

Uso: python -m app.publicacion        (o POST /publicacion con el permiso horarios.exportar)
"""
import json
import sqlite3
from pathlib import Path

from .core.directus import Directus, exigir

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
ORDEN = ["pub_periodo", "pub_programa", "pub_asignatura", "pub_sala", "pub_paralelo", "pub_horario"]
SIN_ELIMINADAS = {"eliminado_en": {"_null": True}}


def _leer(d: Directus, coleccion: str, campos: str, filtro: dict | None = None) -> list[dict]:
    p = {"fields": campos, "limit": -1, "sort": "id"}
    if filtro:
        p["filter"] = json.dumps(filtro)
    return exigir(d.como_servicio("GET", f"/items/{coleccion}", params=p)).datos or []


def extraer(d: Directus) -> dict[str, list[tuple]]:
    """Lee del núcleo, por Directus, lo que se publica. Sin personas, docentes, finanzas ni auditoría."""
    disc = {"departamento_id": {"_eq": 1}}
    periodos = _leer(d, "catalogo_periodo", "id,codigo,estado", disc)
    ids_periodo = {p["id"] for p in periodos}
    salas = _leer(d, "catalogo_sala", "id,codigo,nombre,capacidad,es_laboratorio,activa,eliminado_en", disc)
    sala_codigo = {s["id"]: s["codigo"] for s in salas}
    paralelos = [p for p in _leer(d, "horarios_paralelo", "id,periodo_id,asignatura_id,codigo,nrc,componente,cupo_estimado,eliminado_en")
                 if p["periodo_id"] in ids_periodo and not p["eliminado_en"]]
    ids_paralelo = {p["id"] for p in paralelos}
    aprobadas = {p["id"] for p in _leer(d, "horarios_propuesta", "id,periodo_id,estado") if p["estado"] == "aprobada" and p["periodo_id"] in ids_periodo}
    sesiones = {s["id"]: s for s in _leer(d, "horarios_sesion", "id,paralelo_id,numero,eliminado_en") if s["paralelo_id"] in ids_paralelo and not s["eliminado_en"]}
    horario = [(a["id"], sesiones[a["sesion_id"]]["paralelo_id"], sesiones[a["sesion_id"]]["numero"], a["dia"], a["bloque"],
                sala_codigo.get(a["sala_id"]))
               for a in _leer(d, "horarios_asignacion", "id,propuesta_id,sesion_id,dia,bloque,sala_id")
               if a["propuesta_id"] in aprobadas and a["sesion_id"] in sesiones]
    return {
        "pub_periodo": [(p["id"], p["codigo"], p["estado"]) for p in periodos],
        "pub_programa": [(p["id"], p["codigo"], p["nombre"], p["tipo"]) for p in _leer(d, "catalogo_programa", "id,codigo,nombre,tipo", {"_and": [disc, SIN_ELIMINADAS]})],
        "pub_asignatura": [(a["id"], a["codigo"], a["nombre"], a["area"], a["requiere_laboratorio"])
                           for a in _leer(d, "catalogo_asignatura", "id,codigo,nombre,area,requiere_laboratorio", {"_and": [disc, SIN_ELIMINADAS]})],
        "pub_sala": [(s["id"], s["codigo"], s["nombre"], s["capacidad"], s["es_laboratorio"]) for s in salas if s["activa"] and not s["eliminado_en"]],
        "pub_paralelo": [(p["id"], p["periodo_id"], p["asignatura_id"], p["codigo"], p["nrc"], p["componente"], p["cupo_estimado"]) for p in paralelos],
        "pub_horario": horario,
    }


def publicar(d: Directus, ruta_satelites: str) -> dict:
    """Reemplaza las tablas pub_* en satelites.db. Devuelve cuántas filas quedaron en cada una."""
    datos = extraer(d)
    Path(ruta_satelites).parent.mkdir(parents=True, exist_ok=True)
    sat = sqlite3.connect(ruta_satelites, isolation_level=None, timeout=10)
    try:
        sat.execute("PRAGMA journal_mode = WAL")
        sat.execute("PRAGMA busy_timeout = 5000")
        sat.execute("BEGIN IMMEDIATE")
        for sentencia in DDL.split(";"):
            if sentencia.strip():
                sat.execute(sentencia)
        for tabla in reversed(ORDEN):          # réplica: se regenera completa (no es el núcleo)
            sat.execute(f"DELETE FROM {tabla}")
        for tabla in ORDEN:
            filas = datos[tabla]
            if filas:
                sat.executemany(f"INSERT INTO {tabla} VALUES ({','.join('?' * len(filas[0]))})", filas)
        sat.execute("INSERT OR REPLACE INTO pub_estado (id, publicado_en) VALUES (1, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))")
        sat.execute("COMMIT")
        return {t: len(datos[t]) for t in ORDEN}
    except BaseException:
        if sat.in_transaction:
            sat.execute("ROLLBACK")
        raise
    finally:
        sat.close()


def main() -> None:
    import os
    from .core.config import get_settings
    s = get_settings()
    cuentas = publicar(Directus(s.directus_url, s.servicio_token), os.environ.get("SATELITES_DB_PATH", s.satelites_db_path))
    print("publicado:", ", ".join(f"{k}={v}" for k, v in cuentas.items()))


if __name__ == "__main__":
    main()
