"""Registro de eventos de negocio en plataforma_auditoria (solo inserción).

Los cambios de datos los audita el propio esquema con triggers; aquí van los eventos que la base
no ve: inicios y cierres de sesión, intentos fallidos, accesos denegados.
"""
import json
import sqlite3


def registrar(conn: sqlite3.Connection, *, usuario_id: int | None, ip: str | None, accion: str,
              resultado: str = "ok", entidad: str, entidad_id: str | int | None = None,
              detalle: dict | None = None, departamento_id: int | None = None) -> None:
    conn.execute(
        "INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, resultado, entidad, entidad_id, despues) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (usuario_id, ip, departamento_id, accion, resultado, entidad,
         None if entidad_id is None else str(entidad_id),
         None if detalle is None else json.dumps(detalle, ensure_ascii=False)))
