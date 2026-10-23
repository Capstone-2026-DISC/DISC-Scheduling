"""Repositorio genérico de tablas del núcleo: lectura con alcance por departamento, escritura con
contexto de usuario y borrado lógico. Cada módulo declara sus recursos; no se arma SQL con datos del cliente
(los nombres de tabla y columna salen de la declaración, los valores van como parámetros)."""
import json
import sqlite3
from dataclasses import dataclass, field

from fastapi import HTTPException

from . import audit
from .db import escritura


def ahora_sql() -> str:
    return "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"


@dataclass(frozen=True)
class Recurso:
    tabla: str
    escribibles: tuple[str, ...]
    pk: str = "id"
    # expresión SQL que da el departamento de una fila de la tabla (alias t); None = sin alcance
    depto: str | None = "t.departamento_id"
    borrado_logico: bool = True
    orden: str = "t.id"
    columnas_lectura: tuple[str, ...] | None = None     # None = todas menos eliminado_*
    ocultas_sin_permiso: dict = field(default_factory=dict)  # permiso -> columnas que exige
    json_cols: tuple[str, ...] = ()                           # columnas TEXT con JSON validado


def _columnas(conn: sqlite3.Connection, tabla: str) -> list[str]:
    return [f["name"] for f in conn.execute(f"PRAGMA table_info({tabla})")]


class Repositorio:
    def __init__(self, recurso: Recurso):
        self.r = recurso

    # -- lectura -------------------------------------------------------------------------
    def _seleccion(self, conn, usuario=None) -> str:
        cols = self.r.columnas_lectura or [c for c in _columnas(conn, self.r.tabla)
                                           if c not in ("eliminado_en", "eliminado_por")]
        if usuario is not None:
            for permiso, ocultas in self.r.ocultas_sin_permiso.items():
                if not usuario.tiene(permiso):
                    cols = [c for c in cols if c not in ocultas]
        return ", ".join(f"t.{c}" for c in cols)

    def _alcance(self, deptos: set[int] | None, params: list) -> str:
        if self.r.depto is None or deptos is None:
            return ""
        if not deptos:
            return " AND 0"
        params.extend(sorted(deptos))
        return f" AND {self.r.depto} IN ({','.join('?' * len(deptos))})"

    def listar(self, conn, usuario, deptos: set[int] | None, filtros: dict | None = None,
               limite: int = 100, desplazamiento: int = 0) -> list[dict]:
        params: list = []
        sql = f"SELECT {self._seleccion(conn, usuario)} FROM {self.r.tabla} t WHERE 1 = 1"
        if self.r.borrado_logico:
            sql += " AND t.eliminado_en IS NULL"
        for col, val in (filtros or {}).items():
            if col not in self.r.escribibles and col != self.r.pk:
                raise HTTPException(400, f"No se puede filtrar por {col}")
            sql += f" AND t.{col} = ?"
            params.append(val)
        sql += self._alcance(deptos, params)
        sql += f" ORDER BY {self.r.orden} LIMIT ? OFFSET ?"
        params += [limite, desplazamiento]
        return [self._salida(f) for f in conn.execute(sql, params)]

    def obtener(self, conn, usuario, deptos: set[int] | None, clave) -> dict:
        params: list = [clave]
        sql = f"SELECT {self._seleccion(conn, usuario)} FROM {self.r.tabla} t WHERE t.{self.r.pk} = ?"
        if self.r.borrado_logico:
            sql += " AND t.eliminado_en IS NULL"
        sql += self._alcance(deptos, params)
        fila = conn.execute(sql, params).fetchone()
        if fila is None:
            raise HTTPException(404, "No encontrado")
        return self._salida(fila)

    def departamento_de(self, conn, clave) -> int | None:
        if self.r.depto is None:
            return None
        fila = conn.execute(f"SELECT {self.r.depto} AS d FROM {self.r.tabla} t WHERE t.{self.r.pk} = ?",
                            (clave,)).fetchone()
        return None if fila is None else fila["d"]

    def _salida(self, fila) -> dict:
        d = dict(fila)
        for c in self.r.json_cols:
            if c in d and isinstance(d[c], str):
                d[c] = json.loads(d[c])
        return d

    # -- escritura -----------------------------------------------------------------------
    def _validar(self, datos: dict) -> dict:
        extra = set(datos) - set(self.r.escribibles)
        if extra:
            raise HTTPException(422, f"Campos no permitidos: {', '.join(sorted(extra))}")
        return {k: (json.dumps(v, ensure_ascii=False) if k in self.r.json_cols and not isinstance(v, str) else v)
                for k, v in datos.items()}

    def crear(self, conn, usuario_id: int, ip: str | None, datos: dict) -> dict:
        datos = self._validar(datos)
        cols = list(datos)
        sql = (f"INSERT INTO {self.r.tabla} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
               if cols else f"INSERT INTO {self.r.tabla} DEFAULT VALUES")
        with escritura(conn, usuario_id, ip):
            cur = conn.execute(sql, [datos[c] for c in cols])
            nuevo = cur.lastrowid
        return nuevo

    def actualizar(self, conn, usuario_id: int, ip: str | None, clave, datos: dict) -> None:
        datos = self._validar(datos)
        if not datos:
            raise HTTPException(422, "Indique al menos un campo")
        sets = ", ".join(f"{c} = ?" for c in datos)
        with escritura(conn, usuario_id, ip):
            cur = conn.execute(f"UPDATE {self.r.tabla} SET {sets} WHERE {self.r.pk} = ?"
                               + (" AND eliminado_en IS NULL" if self.r.borrado_logico else ""),
                               [*datos.values(), clave])
            if cur.rowcount == 0:
                raise HTTPException(404, "No encontrado")

    def eliminar(self, conn, usuario_id: int, ip: str | None, clave) -> None:
        """Borrado lógico: marca eliminado_en y eliminado_por. Nunca emite DELETE."""
        if not self.r.borrado_logico:
            raise HTTPException(405, "Este recurso no admite eliminación")
        with escritura(conn, usuario_id, ip):
            cur = conn.execute(f"UPDATE {self.r.tabla} SET eliminado_en = {ahora_sql()}, eliminado_por = ? "
                               f"WHERE {self.r.pk} = ? AND eliminado_en IS NULL", (usuario_id, clave))
            if cur.rowcount == 0:
                raise HTTPException(404, "No encontrado")


def traducir_error(exc: sqlite3.Error) -> HTTPException:
    """Los triggers y CHECK del esquema avisan con mensajes en español; se llevan al código HTTP que corresponde."""
    msg = str(exc)
    if "Sin permiso" in msg or "permiso" in msg.lower() and "Nadie" not in msg:
        return HTTPException(403, msg)
    if "Nadie puede" in msg or "no se puede" in msg or "no se desactiva" in msg:
        return HTTPException(409, msg)
    if isinstance(exc, sqlite3.IntegrityError):
        return HTTPException(409, f"No se pudo guardar: {msg}")
    return HTTPException(500, "Error de base de datos")
