"""Datos iniciales: departamento DISC (ya viene en el esquema), el usuario semilla "Encargado Docente" con rol
Administrador y un usuario de prueba con rol limitado.

Las claves salen de SEED_ADMIN_PASSWORD y SEED_TEST_PASSWORD; si faltan se generan al azar y se imprimen una sola
vez. Nunca se escriben en un archivo ni viven en el repositorio.
Uso: python -m app.seed
"""
import os
import secrets

from .core import security
from .core.config import get_settings
from .core.db import conectar, crear_si_falta, escritura

ADMIN_EMAIL = "encargado.docente@example.com"
PRUEBA_EMAIL = "usuario.prueba@example.com"


def _clave(nombre: str) -> tuple[str, bool]:
    valor = os.environ.get(nombre)
    if valor:
        return valor, False
    return secrets.token_urlsafe(18) + "9a", True


def sembrar(conn, clave_admin: str, clave_prueba: str) -> dict:
    """Idempotente: no toca usuarios que ya existen. Devuelve qué creó."""
    creados = {}
    with escritura(conn, None, "seed"):
        for email, nombre, clave, rol in (
                (ADMIN_EMAIL, "Encargado Docente", clave_admin, "administrador"),
                (PRUEBA_EMAIL, "Usuario de prueba", clave_prueba, "consulta")):
            if conn.execute("SELECT 1 FROM identidad_usuario WHERE email = ?", (email,)).fetchone():
                continue
            uid = conn.execute("INSERT INTO identidad_usuario (email, nombre, hash_clave) VALUES (?, ?, ?)",
                               (email, nombre, security.hashear_clave(clave))).lastrowid
            # administrador: todos los departamentos (nulo); consulta: solo el DISC (id 1)
            conn.execute("INSERT INTO identidad_usuario_rol (usuario_id, rol, departamento_id) VALUES (?, ?, ?)",
                         (uid, rol, None if rol == "administrador" else 1))
            creados[email] = rol
    return creados


def main() -> None:
    settings = get_settings()
    crear_si_falta(settings.db_path, settings.esquema_path)
    conn = conectar(settings.db_path)
    clave_admin, gen_a = _clave("SEED_ADMIN_PASSWORD")
    clave_prueba, gen_p = _clave("SEED_TEST_PASSWORD")
    creados = sembrar(conn, clave_admin, clave_prueba)
    for email in creados:
        print(f"creado {email} ({creados[email]})")
    if gen_a and ADMIN_EMAIL in creados:
        print(f"clave generada para {ADMIN_EMAIL}: {clave_admin}  (se muestra una sola vez)")
    if gen_p and PRUEBA_EMAIL in creados:
        print(f"clave generada para {PRUEBA_EMAIL}: {clave_prueba}  (se muestra una sola vez)")
    if not creados:
        print("los usuarios semilla ya existían; no se cambió nada")


if __name__ == "__main__":
    main()
