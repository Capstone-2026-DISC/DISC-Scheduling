"""Reglas de autenticación: bloqueo por intentos, rotación de refresh tokens y auditoría de cada evento."""
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from ....core import audit, security
from ....core.config import Settings
from ....core.db import escritura
from ....core.recurso import ahora_sql
from . import repository as repo


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _emitir(conn, settings: Settings, uid: int, familia: str, ip: str | None) -> dict:
    refresh, hash_ref = security.nuevo_refresh()
    expira = _iso(_ahora() + timedelta(days=settings.refresh_dias))
    conn.execute("INSERT INTO identidad_sesion (usuario_id, familia, token_hash, expira_en, ip) VALUES (?, ?, ?, ?, ?)",
                 (uid, familia, hash_ref, expira, ip))
    access, ttl = security.crear_access(settings, uid, familia)
    return {"access_token": access, "refresh_token": refresh, "token_type": "bearer", "expires_in": ttl}


def login(conn: sqlite3.Connection, settings: Settings, email: str, clave: str, ip: str | None) -> dict:
    usuario = repo.usuario_por_email(conn, email)
    uid = usuario["id"] if usuario else None
    ahora = _iso(_ahora())

    if usuario and usuario["bloqueado_hasta"] and usuario["bloqueado_hasta"] > ahora:
        with escritura(conn, None, ip):
            audit.registrar(conn, usuario_id=uid, ip=ip, accion="login", resultado="denegado",
                            entidad="identidad_usuario", entidad_id=uid, detalle={"motivo": "cuenta_bloqueada"})
        raise HTTPException(423, "Cuenta bloqueada temporalmente por intentos fallidos")

    habilitado = bool(usuario and usuario["activo"] == 1 and usuario["tipo"] == "persona")
    correcto = security.verificar_clave(usuario["hash_clave"] if habilitado else None, clave)

    if not (habilitado and correcto):
        with escritura(conn, None, ip):
            motivo = "usuario_desconocido" if not usuario else "clave_incorrecta" if habilitado else "usuario_inactivo"
            if usuario:
                intentos = usuario["intentos_fallidos"] + 1
                bloqueo = None
                if intentos >= settings.intentos_maximos:
                    bloqueo = _iso(_ahora() + timedelta(minutes=settings.bloqueo_minutos))
                    motivo = "bloqueo_por_intentos"
                conn.execute("UPDATE identidad_usuario SET intentos_fallidos = ?, bloqueado_hasta = ? WHERE id = ?",
                             (0 if bloqueo else intentos, bloqueo, uid))
            audit.registrar(conn, usuario_id=uid, ip=ip, accion="login", resultado="denegado",
                            entidad="identidad_usuario", entidad_id=uid,
                            detalle={"motivo": motivo, "correo_intentado": None if usuario else email.strip().lower()[:254]})
        raise HTTPException(401, "Correo o clave incorrectos")

    familia = secrets.token_hex(16)
    with escritura(conn, None, ip):
        conn.execute(f"UPDATE identidad_usuario SET intentos_fallidos = 0, bloqueado_hasta = NULL, "
                     f"ultimo_acceso_en = {ahora_sql()} WHERE id = ?", (uid,))
        if security.necesita_rehash(usuario["hash_clave"]):
            conn.execute("UPDATE identidad_usuario SET hash_clave = ? WHERE id = ?", (security.hashear_clave(clave), uid))
        tokens = _emitir(conn, settings, uid, familia, ip)
        audit.registrar(conn, usuario_id=uid, ip=ip, accion="login", entidad="identidad_usuario", entidad_id=uid)
    return tokens


def refrescar(conn: sqlite3.Connection, settings: Settings, refresh_token: str, ip: str | None) -> dict:
    fila = conn.execute("SELECT * FROM identidad_sesion WHERE token_hash = ?",
                        (security.hash_refresh(refresh_token),)).fetchone()
    invalido = HTTPException(401, "Sesión inválida o vencida")
    if fila is None:
        raise invalido
    uid, familia, ahora = fila["usuario_id"], fila["familia"], _iso(_ahora())
    if fila["revocada_en"] or fila["usado_en"]:
        # Un refresh ya usado que reaparece indica robo: se cierra toda la familia.
        with escritura(conn, None, ip):
            conn.execute(f"UPDATE identidad_sesion SET revocada_en = {ahora_sql()} WHERE familia = ? AND revocada_en IS NULL",
                         (familia,))
            audit.registrar(conn, usuario_id=uid, ip=ip, accion="refresh_reutilizado", resultado="denegado",
                            entidad="identidad_sesion", entidad_id=fila["id"])
        raise invalido
    usuario = repo.usuario_por_id(conn, uid)
    if fila["expira_en"] <= ahora or not usuario or usuario["activo"] != 1:
        raise invalido
    with escritura(conn, None, ip):
        conn.execute(f"UPDATE identidad_sesion SET usado_en = {ahora_sql()} WHERE id = ?", (fila["id"],))
        tokens = _emitir(conn, settings, uid, familia, ip)
        audit.registrar(conn, usuario_id=uid, ip=ip, accion="refresh", entidad="identidad_sesion", entidad_id=fila["id"])
    return tokens


def cerrar_sesion(conn: sqlite3.Connection, uid: int, familia: str, ip: str | None) -> None:
    with escritura(conn, None, ip):
        conn.execute(f"UPDATE identidad_sesion SET revocada_en = {ahora_sql()} WHERE familia = ? AND revocada_en IS NULL",
                     (familia,))
        audit.registrar(conn, usuario_id=uid, ip=ip, accion="logout", entidad="identidad_usuario", entidad_id=uid)


def cambiar_clave(conn, settings: Settings, uid: int, actual: str, nueva: str, ip: str | None) -> None:
    usuario = repo.usuario_por_id(conn, uid)
    if not security.verificar_clave(usuario["hash_clave"], actual):
        with escritura(conn, None, ip):
            audit.registrar(conn, usuario_id=uid, ip=ip, accion="cambio_clave", resultado="denegado",
                            entidad="identidad_usuario", entidad_id=uid, detalle={"motivo": "clave_actual_incorrecta"})
        raise HTTPException(403, "La clave actual no coincide")
    problema = security.clave_valida(nueva, usuario["email"], settings.clave_minima)
    if problema:
        raise HTTPException(422, problema)
    with escritura(conn, None, ip):
        conn.execute("UPDATE identidad_usuario SET hash_clave = ? WHERE id = ?", (security.hashear_clave(nueva), uid))
        conn.execute(f"UPDATE identidad_sesion SET revocada_en = {ahora_sql()} WHERE usuario_id = ? AND revocada_en IS NULL",
                     (uid,))
        audit.registrar(conn, usuario_id=uid, ip=ip, accion="cambio_clave", entidad="identidad_usuario", entidad_id=uid)
