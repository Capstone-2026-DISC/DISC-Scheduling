"""Recursos del catálogo (datos maestros) y su alcance por departamento."""
import sqlite3

from ....core import pii
from ....core.db import escritura
from ....core.recurso import Recurso

PERIODO = Recurso("catalogo_periodo", ("departamento_id", "codigo", "fecha_inicio", "fecha_fin", "estado"),
                  borrado_logico=False)
PROGRAMA = Recurso("catalogo_programa", ("departamento_id", "codigo", "nombre", "tipo"))
ASIGNATURA = Recurso("catalogo_asignatura", ("departamento_id", "codigo", "nombre", "area",
                                              "requiere_laboratorio", "activa"))
SALA = Recurso("catalogo_sala", ("departamento_id", "codigo", "nombre", "capacidad", "es_laboratorio",
                                  "administrada_por", "activa"))
# Los datos personales (RUT, correo) se guardan cifrados y solo los ve quien tiene personas.ver_datos_personales.
# Este recurso solo sirve para el borrado lógico; la lectura y la escritura pasan por las funciones de abajo.
PERSONA = Recurso("catalogo_persona", (), depto=None)
DOCENTE = Recurso("catalogo_docente", ("persona_id", "departamento_id", "tipo_contrato", "activo"),
                  pk="persona_id", orden="t.persona_id")
AYUDANTE = Recurso("catalogo_ayudante", ("persona_id", "departamento_id", "activo"),
                   pk="persona_id", orden="t.persona_id")


# -- personas: RUT y correo cifrados --------------------------------------------------------------------
def _persona(cif: pii.Cifrador, fila) -> dict:
    return {"id": fila["id"], "rut": cif.descifrar(fila["rut_cifrado"], pii.COL_RUT), "nombre": fila["nombre"],
            "email": cif.descifrar(fila["email_cifrado"], pii.COL_EMAIL) if fila["email_cifrado"] else None}


def listar_personas(conn: sqlite3.Connection, cif: pii.Cifrador, limite: int, desplazamiento: int) -> list[dict]:
    filas = conn.execute("SELECT id, rut_cifrado, nombre, email_cifrado FROM catalogo_persona WHERE eliminado_en IS NULL "
                         "ORDER BY id LIMIT ? OFFSET ?", (limite, desplazamiento)).fetchall()
    return [_persona(cif, f) for f in filas]


def obtener_persona(conn: sqlite3.Connection, cif: pii.Cifrador, pid: int) -> dict | None:
    fila = conn.execute("SELECT id, rut_cifrado, nombre, email_cifrado FROM catalogo_persona WHERE id = ? AND eliminado_en IS NULL",
                        (pid,)).fetchone()
    return None if fila is None else _persona(cif, fila)


def persona_por_rut(conn: sqlite3.Connection, cif: pii.Cifrador, rut: str) -> int | None:
    fila = conn.execute("SELECT id FROM catalogo_persona WHERE rut_indice = ? AND eliminado_en IS NULL", (cif.indice_rut(rut),)).fetchone()
    return None if fila is None else fila["id"]


def crear_persona(conn, cif: pii.Cifrador, actor_id: int, ip: str | None, rut: str, nombre: str, email: str | None) -> int:
    rut = pii.normalizar_rut(rut)
    with escritura(conn, actor_id, ip):
        return conn.execute(
            "INSERT INTO catalogo_persona (rut_cifrado, rut_indice, nombre, email_cifrado) VALUES (?, ?, ?, ?)",
            (cif.cifrar(rut, pii.COL_RUT), cif.indice_rut(rut), nombre,
             cif.cifrar(email, pii.COL_EMAIL) if email else None)).lastrowid


def actualizar_persona(conn, cif: pii.Cifrador, actor_id: int, ip: str | None, pid: int, cambios: dict) -> int:
    sets, valores = [], []
    if "rut" in cambios:
        rut = pii.normalizar_rut(cambios["rut"])
        sets += ["rut_cifrado = ?", "rut_indice = ?"]
        valores += [cif.cifrar(rut, pii.COL_RUT), cif.indice_rut(rut)]
    if "nombre" in cambios:
        sets.append("nombre = ?")
        valores.append(cambios["nombre"])
    if "email" in cambios:
        sets.append("email_cifrado = ?")
        valores.append(cif.cifrar(cambios["email"], pii.COL_EMAIL) if cambios["email"] else None)
    with escritura(conn, actor_id, ip):
        return conn.execute(f"UPDATE catalogo_persona SET {', '.join(sets)} WHERE id = ? AND eliminado_en IS NULL",
                            [*valores, pid]).rowcount
