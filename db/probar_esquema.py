#!/usr/bin/env python3
"""Prueba las reglas de integridad del esquema SQLite: cifrado de datos personales, aprobación de horarios,
restricciones, borrado lógico y auditoría de eventos.

Los permisos por rol y departamento y el registro de quién cambió qué ya no viven aquí: los aplica y los registra
Directus, y se verifican en el CI contra una instancia real (backend/app/directus_setup.py).
Uso: python3 probar_esquema.py esquema_plataforma.sql"""
import json
import sqlite3
import sys

sql = open(sys.argv[1], encoding="utf-8").read()
con = sqlite3.connect(":memory:", isolation_level=None)
con.execute("PRAGMA foreign_keys = ON")
con.executescript(sql)
ok = fallos = 0


def pasa(desc, q, *a):
    global ok, fallos
    try:
        con.execute(q, a); ok += 1; print("PASA  (funciona)", desc)
    except sqlite3.Error as e:
        fallos += 1; print("FALLA (debía funcionar)", desc, "->", e)


def falla(desc, q, *a):
    global ok, fallos
    try:
        con.execute(q, a); fallos += 1; print("FALLA (no falló)", desc)
    except sqlite3.Error as e:
        ok += 1; print("PASA  (falla como debe)", desc, "->", str(e)[:90])


def uno(q, *a): return con.execute(q, a).fetchone()[0]


def verdad(desc, condicion):
    global ok, fallos
    if condicion:
        ok += 1; print("PASA ", desc)
    else:
        fallos += 1; print("FALLA", desc)


# datos de partida
UUID1, UUID2 = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
con.execute("INSERT INTO identidad_usuario (directus_id, email, nombre) VALUES (?, 'ed.disc@x.cl', 'ED DISC')", (UUID1,))
con.execute("INSERT INTO identidad_departamento (codigo, nombre) VALUES ('DMAT', 'Matemática')")
con.execute("INSERT INTO catalogo_periodo (codigo) VALUES ('202620')")
con.execute("INSERT INTO catalogo_asignatura (codigo, nombre) VALUES ('FAIC-00001', 'Algo')")
con.execute("INSERT INTO horarios_paralelo (periodo_id, asignatura_id, codigo) VALUES (1, 1, 'C1')")
con.execute("INSERT INTO horarios_sesion (paralelo_id, numero) VALUES (1, 1)")
rid = uno("SELECT min(id) FROM horarios_restriccion")
con.execute("INSERT INTO horarios_corrida (periodo_id, perfil_id, semilla, estado, restricciones_usadas) VALUES (1, 1, '[1,2,3,4,5,6]', 'completa', ?)",
            (json.dumps([{"id": rid}]),))
con.execute("INSERT INTO horarios_propuesta (periodo_id, corrida_id, nombre, completa) VALUES (1, 1, 'p1', 1), (1, 1, 'p2', 1)")

print("-- espejo de los usuarios de Directus")
falla("el mismo usuario de Directus dos veces", "INSERT INTO identidad_usuario (directus_id, email, nombre) VALUES (?, 'otro@x.cl', 'Otro')", UUID1)
falla("identificador de Directus que no es un UUID", "INSERT INTO identidad_usuario (directus_id, email, nombre) VALUES ('corto', 'otro@x.cl', 'Otro')")
falla("correo con mayúsculas", "INSERT INTO identidad_usuario (directus_id, email, nombre) VALUES (?, 'Otro@x.cl', 'Otro')", UUID2)
verdad("la base ya no guarda claves ni intentos de acceso", not any(
    c[1] in ("hash_clave", "intentos_fallidos", "bloqueado_hasta") for c in con.execute("PRAGMA table_info(identidad_usuario)")))
verdad("no hay tablas de contexto, sesión ni asignación de roles",
       uno("SELECT count(*) FROM sqlite_master WHERE name IN ('plataforma_contexto', 'identidad_sesion', 'identidad_usuario_rol')") == 0)

print("-- datos personales cifrados")
IDX1, IDX2 = "a" * 64, "b" * 64
pasa("persona con RUT y correo cifrados",
     "INSERT INTO catalogo_persona (rut_cifrado, rut_indice, nombre, email_cifrado) VALUES ('v1:k1:AAAA', ?, 'A', 'v1:k1:BBBB')", IDX1)
falla("el mismo RUT (mismo índice ciego) no se repite",
      "INSERT INTO catalogo_persona (rut_cifrado, rut_indice, nombre) VALUES ('v1:k1:CCCC', ?, 'B')", IDX1)
falla("un RUT en claro no entra donde va el cifrado",
      "INSERT INTO catalogo_persona (rut_cifrado, rut_indice, nombre) VALUES ('12345678-5', ?, 'C')", IDX2)
falla("un correo en claro no entra donde va el cifrado",
      "INSERT INTO catalogo_persona (rut_cifrado, rut_indice, nombre, email_cifrado) VALUES ('v1:k1:DDDD', ?, 'D', 'a@b.cl')", IDX2)
falla("el índice ciego tiene 64 caracteres",
      "INSERT INTO catalogo_persona (rut_cifrado, rut_indice, nombre) VALUES ('v1:k1:EEEE', 'corto', 'E')")
falla("el correo del envío no se guarda en claro",
      "INSERT INTO horarios_envio_horario (propuesta_id, docente_id, email_destino_cifrado) VALUES (1, 1, 'a@b.cl')")

print("-- edición de asignaciones")
pasa("se edita el horario de un borrador", "INSERT INTO horarios_asignacion (propuesta_id, sesion_id, dia, bloque) VALUES (1, 1, 'Lu', 'A')")
pasa("cambio de bloque", "UPDATE horarios_asignacion SET bloque = 'B' WHERE propuesta_id = 1")

print("-- aprobación")
con.execute("INSERT INTO horarios_hallazgo (propuesta_id, severidad, tipo, detalle) VALUES (2, 'dura', 'choque_docente', '{}')")
falla("aprobar con violación dura", "UPDATE horarios_propuesta SET estado = 'aprobada' WHERE id = 2")
pasa("aprobar p1", "UPDATE horarios_propuesta SET estado = 'aprobada', aprobada_por = 1 WHERE id = 1")
verdad("la hora de aprobación la pone la base", uno("SELECT aprobada_en IS NOT NULL FROM horarios_propuesta WHERE id = 1"))
verdad("quién aprobó lo envía la API", uno("SELECT aprobada_por FROM horarios_propuesta WHERE id = 1") == 1)
falla("editar asignación de una aprobada", "UPDATE horarios_asignacion SET bloque = 'C' WHERE propuesta_id = 1")
falla("borrar asignación de una aprobada", "DELETE FROM horarios_asignacion WHERE propuesta_id = 1")
falla("agregar asignación a una aprobada", "INSERT INTO horarios_asignacion (propuesta_id, sesion_id, dia, bloque) VALUES (1, 1, 'Ma', 'A')")
con.execute("UPDATE horarios_hallazgo SET severidad = 'aviso' WHERE propuesta_id = 2")
con.execute("UPDATE horarios_propuesta SET completa = 0 WHERE id = 2")
falla("aprobar una incompleta", "UPDATE horarios_propuesta SET estado = 'aprobada' WHERE id = 2")
con.execute("UPDATE horarios_propuesta SET completa = 1 WHERE id = 2")
pasa("aprobar p2 reemplaza a p1", "UPDATE horarios_propuesta SET estado = 'aprobada', aprobada_por = 1 WHERE id = 2")
verdad("p1 queda reemplazada por p2", con.execute("SELECT estado, reemplazada_por FROM horarios_propuesta WHERE id = 1").fetchone() == ("reemplazada", 2))
falla("una reemplazada vuelve a aprobada", "UPDATE horarios_propuesta SET estado = 'aprobada' WHERE id = 1")
falla("una aprobada solo puede pasar a reemplazada", "UPDATE horarios_propuesta SET estado = 'borrador' WHERE id = 2")

print("-- restricciones")
pasa("crear restricción blanda", "INSERT INTO horarios_restriccion (naturaleza, tipo, peso) VALUES ('blanda', 'x', 5)")
falla("blanda sin peso", "INSERT INTO horarios_restriccion (naturaleza, tipo) VALUES ('blanda', 'x')")
falla("dura con peso", "INSERT INTO horarios_restriccion (naturaleza, tipo, peso) VALUES ('dura', 'x', 5)")
falla("peso 100", "INSERT INTO horarios_restriccion (naturaleza, tipo, peso) VALUES ('blanda', 'x', 100)")
falla("eliminar una restricción usada por una aprobada", "UPDATE horarios_restriccion SET eliminado_en = datetime('now') WHERE id = ?", rid)
pasa("desactivar esa restricción", "UPDATE horarios_restriccion SET activa = 0 WHERE id = ?", rid)
pasa("eliminar una no usada", "UPDATE horarios_restriccion SET eliminado_en = datetime('now') WHERE tipo = 'x'")
verdad("actualizada_en cambia al editar", uno("SELECT actualizada_en >= creada_en FROM horarios_restriccion WHERE id = ?", rid))

print("-- departamentos y roles protegidos")
falla("desactivar DISC", "UPDATE identidad_departamento SET activo = 0 WHERE codigo = 'DISC'")
falla("eliminar DISC", "UPDATE identidad_departamento SET eliminado_en = datetime('now') WHERE codigo = 'DISC'")
falla("desactivar rol administrador", "UPDATE identidad_rol SET activo = 0 WHERE codigo = 'administrador'")
pasa("desactivar DMAT", "UPDATE identidad_departamento SET activo = 0 WHERE codigo = 'DMAT'")
verdad("el administrador tiene los 18 permisos", uno("SELECT count(*) FROM identidad_rol_permiso WHERE rol = 'administrador' AND revocado_en IS NULL") == 18)
verdad("consulta solo tiene tres", uno("SELECT count(*) FROM identidad_rol_permiso WHERE rol = 'consulta' AND revocado_en IS NULL") == 3)

print("-- borrado lógico y auditoría de eventos")
falla("DELETE físico en asignatura", "DELETE FROM catalogo_asignatura")
falla("DELETE físico en el espejo de usuarios", "DELETE FROM identidad_usuario")
falla("DELETE físico en restricción", "DELETE FROM horarios_restriccion")
pasa("DELETE de hallazgos (dato derivado)", "DELETE FROM horarios_hallazgo")
pasa("registrar un evento de la aplicación",
     "INSERT INTO plataforma_auditoria (usuario_id, ip, accion, resultado, entidad, despues) VALUES (1, '10.0.0.1', 'login', 'denegado', 'identidad_usuario', '{\"motivo\": \"clave_incorrecta\"}')")
falla("DELETE en la auditoría reciente", "DELETE FROM plataforma_auditoria")
falla("UPDATE en la auditoría", "UPDATE plataforma_auditoria SET accion = 'x'")
falla("resultado de auditoría inválido", "INSERT INTO plataforma_auditoria (accion, resultado, entidad) VALUES ('x', 'raro', 'y')")
con.execute("DROP TRIGGER auditoria_inmutable")
con.execute("UPDATE plataforma_auditoria SET en = '2019-01-01T00:00:00Z' WHERE id = 1")
pasa("purga de auditoría de más de 5 años", "DELETE FROM plataforma_auditoria WHERE en < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-5 years')")

print("-- corridas")
falla("estado de corrida inválido", "INSERT INTO horarios_corrida (periodo_id, perfil_id, semilla, estado) VALUES (1, 1, '[1,2,3,4,5,6]', 'terminada')")
pasa("estado de corrida tiempo_agotado", "INSERT INTO horarios_corrida (periodo_id, perfil_id, semilla, estado) VALUES (1, 1, '[1,2,3,4,5,6]', 'tiempo_agotado')")
falla("semilla con 5 valores", "INSERT INTO horarios_corrida (periodo_id, perfil_id, semilla) VALUES (1, 1, '[1,2,3,4,5]')")
verdad("límite por defecto de la corrida", uno("SELECT limite_segundos FROM horarios_corrida LIMIT 1") is not None)
verdad("la vista de horario por paralelo responde", len(con.execute("SELECT * FROM horarios_v_horario_paralelo").fetchall()) >= 0)
verdad("integridad referencial", con.execute("PRAGMA integrity_check").fetchone()[0] == "ok" and not con.execute("PRAGMA foreign_key_check").fetchall())
print(f"\n{ok} pruebas correctas, {fallos} con problema")
sys.exit(1 if fallos else 0)
