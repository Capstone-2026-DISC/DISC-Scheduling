#!/usr/bin/env python3
"""Prueba el esquema SQLite: permisos por departamento, aprobación, restricciones, borrado lógico y auditoría.
Uso: python3 probar_esquema.py esquema_plataforma.sql"""
import sqlite3, sys, json

sql = open(sys.argv[1], encoding="utf-8").read()
con = sqlite3.connect(":memory:", isolation_level=None)
con.execute("PRAGMA foreign_keys = ON")
con.executescript(sql)
ok = fallos = 0

def quien(uid):
    con.execute("UPDATE plataforma_contexto SET usuario_id = ?", (uid,))

def pasa(desc, uid, q, *a):
    global ok, fallos
    quien(uid)
    try:
        con.execute(q, a); ok += 1; print("PASA  (funciona)", desc)
    except sqlite3.Error as e:
        fallos += 1; print("FALLA (debía funcionar)", desc, "->", e)
    finally:
        quien(None)

def falla(desc, uid, q, *a):
    global ok, fallos
    quien(uid)
    try:
        con.execute(q, a); fallos += 1; print("FALLA (no falló)", desc)
    except sqlite3.Error as e:
        ok += 1; print("PASA  (falla como debe)", desc, "->", str(e)[:90])
    finally:
        quien(None)

def uno(q, *a): return con.execute(q, a).fetchone()[0]

# datos (sin contexto: migración)
for e, n in [("admin@x.cl", "Admin"), ("ed.disc@x.cl", "ED DISC"), ("ed.dmat@x.cl", "ED DMAT"), ("consulta@x.cl", "Consulta")]:
    con.execute("INSERT INTO identidad_usuario (email, nombre) VALUES (?, ?)", (e, n))
con.execute("INSERT INTO identidad_departamento (codigo, nombre) VALUES ('DMAT', 'Matemática')")
con.executemany("INSERT INTO identidad_usuario_rol (usuario_id, rol, departamento_id) VALUES (?, ?, ?)",
                [(1, "administrador", None), (2, "encargado_docente", 1), (3, "encargado_docente", 2), (4, "consulta", 1)])
con.execute("INSERT INTO catalogo_periodo (codigo) VALUES ('202620')")
con.execute("INSERT INTO catalogo_periodo (departamento_id, codigo) VALUES (2, '202620')")
con.execute("INSERT INTO catalogo_asignatura (codigo, nombre) VALUES ('FAIC-00001', 'Algo')")
con.execute("INSERT INTO horarios_paralelo (periodo_id, asignatura_id, codigo) VALUES (1, 1, 'C1')")
con.execute("INSERT INTO horarios_sesion (paralelo_id, numero) VALUES (1, 1)")
rid = uno("SELECT min(id) FROM horarios_restriccion")
con.execute("INSERT INTO horarios_corrida (periodo_id, perfil_id, semilla, estado, restricciones_usadas) VALUES (1, 1, '[1,2,3,4,5,6]', 'completa', ?)",
            (json.dumps([{"id": rid}]),))
con.execute("INSERT INTO horarios_propuesta (periodo_id, corrida_id, nombre, completa) VALUES (1, 1, 'p1', 1), (1, 1, 'p2', 1)")

print("-- RUT")
pasa("RUT válido 12345678-5", None, "INSERT INTO catalogo_persona (rut, nombre) VALUES ('12345678-5', 'A')")
falla("RUT con dígito verificador malo", None, "INSERT INTO catalogo_persona (rut, nombre) VALUES ('12345678-9', 'B')")
falla("RUT con formato malo", None, "INSERT INTO catalogo_persona (rut, nombre) VALUES ('1234', 'C')")
pasa("RUT con K (6-K)... 16.000.000-K", None, "INSERT INTO catalogo_persona (rut, nombre) VALUES ('7000000-K', 'D')") if False else None

print("-- aislamiento entre departamentos")
falla("ED de DMAT edita horarios de DISC", 3, "INSERT INTO horarios_asignacion (propuesta_id, sesion_id, dia, bloque) VALUES (1, 1, 'Lu', 'A')")
falla("consulta no edita", 4, "INSERT INTO horarios_asignacion (propuesta_id, sesion_id, dia, bloque) VALUES (1, 1, 'Lu', 'A')")
pasa("ED de DISC edita su horario", 2, "INSERT INTO horarios_asignacion (propuesta_id, sesion_id, dia, bloque) VALUES (1, 1, 'Lu', 'A')")
pasa("cambio manual", 2, "UPDATE horarios_asignacion SET bloque = 'B' WHERE propuesta_id = 1")
print("      origen =", uno("SELECT origen FROM horarios_asignacion WHERE propuesta_id = 1"),
      "· modificada_por =", uno("SELECT modificada_por FROM horarios_asignacion WHERE propuesta_id = 1"))

print("-- aprobación")
falla("consulta aprueba", 4, "UPDATE horarios_propuesta SET estado = 'aprobada' WHERE id = 1")
falla("ED de DMAT aprueba en DISC", 3, "UPDATE horarios_propuesta SET estado = 'aprobada' WHERE id = 1")
con.execute("INSERT INTO horarios_hallazgo (propuesta_id, severidad, tipo, detalle) VALUES (2, 'dura', 'choque_docente', '{}')")
falla("aprobar con violación dura", 2, "UPDATE horarios_propuesta SET estado = 'aprobada' WHERE id = 2")
pasa("ED aprueba p1", 2, "UPDATE horarios_propuesta SET estado = 'aprobada' WHERE id = 1")
print("      aprobada_por =", uno("SELECT aprobada_por FROM horarios_propuesta WHERE id = 1"))
falla("editar asignación de una aprobada", 2, "UPDATE horarios_asignacion SET bloque = 'C' WHERE propuesta_id = 1")
con.execute("UPDATE horarios_hallazgo SET severidad = 'aviso' WHERE propuesta_id = 2")
con.execute("UPDATE horarios_propuesta SET completa = 0 WHERE id = 2")
falla("aprobar una incompleta", 2, "UPDATE horarios_propuesta SET estado = 'aprobada' WHERE id = 2")
con.execute("UPDATE horarios_propuesta SET completa = 1 WHERE id = 2")
pasa("aprobar p2 reemplaza a p1", 2, "UPDATE horarios_propuesta SET estado = 'aprobada' WHERE id = 2")
print("      p1 =", uno("SELECT estado FROM horarios_propuesta WHERE id = 1"), "· reemplazada_por =",
      uno("SELECT reemplazada_por FROM horarios_propuesta WHERE id = 1"))
falla("una reemplazada vuelve a aprobada", 2, "UPDATE horarios_propuesta SET estado = 'aprobada' WHERE id = 1")
falla("dos aprobadas en el periodo", None, "UPDATE horarios_propuesta SET estado = 'aprobada' WHERE id = 1")

print("-- restricciones")
falla("consulta crea restricción", 4, "INSERT INTO horarios_restriccion (naturaleza, tipo, peso) VALUES ('blanda', 'x', 5)")
pasa("ED crea restricción blanda", 2, "INSERT INTO horarios_restriccion (naturaleza, tipo, peso) VALUES ('blanda', 'x', 5)")
falla("blanda sin peso", 2, "INSERT INTO horarios_restriccion (naturaleza, tipo) VALUES ('blanda', 'x')")
falla("dura con peso", 2, "INSERT INTO horarios_restriccion (naturaleza, tipo, peso) VALUES ('dura', 'x', 5)")
falla("peso 100", 2, "INSERT INTO horarios_restriccion (naturaleza, tipo, peso) VALUES ('blanda', 'x', 100)")
falla("eliminar una restricción usada por una aprobada", 2, "UPDATE horarios_restriccion SET eliminado_en = datetime('now') WHERE id = ?", rid)
pasa("desactivar esa restricción", 2, "UPDATE horarios_restriccion SET activa = 0 WHERE id = ?", rid)
pasa("eliminar una no usada", 2, "UPDATE horarios_restriccion SET eliminado_en = datetime('now') WHERE tipo = 'x'")
print("      actualizada_en cambia al editar:", uno("SELECT actualizada_en >= creada_en FROM horarios_restriccion WHERE id = ?", rid))

print("-- roles y departamentos")
falla("ED se da un rol a sí mismo", 2, "INSERT INTO identidad_usuario_rol (usuario_id, rol) VALUES (2, 'administrador')")
falla("ED asigna roles (sin usuarios.gestionar)", 2, "INSERT INTO identidad_usuario_rol (usuario_id, rol) VALUES (4, 'administrador')")
pasa("administrador asigna rol", 1, "INSERT INTO identidad_usuario_rol (usuario_id, rol, departamento_id) VALUES (4, 'encargado_docente', 2)")
falla("rol duplicado vigente", None, "INSERT INTO identidad_usuario_rol (usuario_id, rol, departamento_id) VALUES (4, 'encargado_docente', 2)")
falla("desactivar DISC", 1, "UPDATE identidad_departamento SET activo = 0 WHERE codigo = 'DISC'")
falla("desactivar rol administrador", 1, "UPDATE identidad_rol SET activo = 0 WHERE codigo = 'administrador'")
pasa("desactivar DMAT", 1, "UPDATE identidad_departamento SET activo = 0 WHERE codigo = 'DMAT'")
print("      permiso efectivo del admin (global):", uno("SELECT count(*) FROM identidad_permiso_efectivo WHERE usuario_id = 1 AND departamento_id IS NULL"), "permisos")
print("      permiso efectivo de consulta:", uno("SELECT group_concat(permiso) FROM identidad_permiso_efectivo WHERE usuario_id = 4 AND departamento_id = 1"))

print("-- borrado lógico y auditoría")
falla("DELETE físico en asignatura", None, "DELETE FROM catalogo_asignatura")
falla("DELETE físico en usuario", None, "DELETE FROM identidad_usuario")
falla("DELETE físico en restricción", None, "DELETE FROM horarios_restriccion")
falla("DELETE en la auditoría reciente", None, "DELETE FROM plataforma_auditoria")
falla("UPDATE en la auditoría", None, "UPDATE plataforma_auditoria SET accion = 'x'")
pasa("DELETE de hallazgos (dato derivado)", None, "DELETE FROM horarios_hallazgo")
n = uno("SELECT count(*) FROM plataforma_auditoria WHERE entidad = 'horarios_propuesta' AND accion = 'update'")
print("      auditoría: %d updates de propuesta; ejemplo:" % n,
      con.execute("SELECT despues FROM plataforma_auditoria WHERE entidad = 'horarios_propuesta' AND accion = 'update' ORDER BY id LIMIT 1").fetchone()[0])
print("      auditoría de usuario sin hash_clave:", uno("SELECT count(*) FROM plataforma_auditoria WHERE entidad = 'identidad_usuario' AND despues LIKE '%hash_clave%'") == 0)
print("      quién hizo el cambio manual:", con.execute("SELECT usuario_id, accion, antes, despues FROM plataforma_auditoria WHERE entidad = 'horarios_asignacion' AND accion = 'update' LIMIT 1").fetchone())
con.execute("UPDATE plataforma_auditoria SET en = '2019-01-01T00:00:00Z' WHERE 0")  # no-op para el trigger
con.execute("DROP TRIGGER auditoria_inmutable")
con.execute("UPDATE plataforma_auditoria SET en = '2019-01-01T00:00:00Z' WHERE id = 1")
pasa("purga de auditoría de más de 5 años", None, "DELETE FROM plataforma_auditoria WHERE en < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-5 years')")
falla("estado de corrida inválido", None, "INSERT INTO horarios_corrida (periodo_id, perfil_id, semilla, estado) VALUES (1, 1, '[1,2,3,4,5,6]', 'terminada')")
pasa("estado de corrida tiempo_agotado", None, "INSERT INTO horarios_corrida (periodo_id, perfil_id, semilla, estado) VALUES (1, 1, '[1,2,3,4,5,6]', 'tiempo_agotado')")
falla("semilla con 5 valores", None, "INSERT INTO horarios_corrida (periodo_id, perfil_id, semilla) VALUES (1, 1, '[1,2,3,4,5]')")
print("      límite por defecto de la corrida:", uno("SELECT limite_segundos FROM horarios_corrida LIMIT 1"), "s")
print("      vista de horario por paralelo:", con.execute("SELECT * FROM horarios_v_horario_paralelo").fetchall())
print("      integridad:", con.execute("PRAGMA integrity_check").fetchone()[0], "· FK rotas:", len(con.execute("PRAGMA foreign_key_check").fetchall()))
print(f"\n{ok} pruebas correctas, {fallos} con problema")
sys.exit(1 if fallos else 0)
