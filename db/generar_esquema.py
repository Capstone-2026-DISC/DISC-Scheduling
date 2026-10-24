#!/usr/bin/env python3
"""Genera esquema_plataforma.sql (SQLite 3.44 o superior).

Las tablas y los datos base están escritos a mano aquí; los triggers repetitivos
(borrado lógico) se generan por tabla para que no se desvíen.
Uso: python3 generar_esquema.py > esquema_plataforma.sql
"""
import sys

TS = "TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))"
SD = "eliminado_en TEXT,\n  eliminado_por INTEGER REFERENCES identidad_usuario"


CABECERA = """-- =====================================================================
-- Plataforma DISC · estructura de la base de datos (SQLite 3.44 o superior)
--
-- Una sola base, plataforma.db. SQLite no tiene esquemas: el módulo va en el prefijo.
--   identidad_    departamentos, usuarios, roles y permisos (RBAC con alcance por departamento)
--   catalogo_     datos maestros: periodos, programas, asignaturas, salas,
--                 bloques, personas, docentes y ayudantes
--   horarios_     oferta del periodo (paralelos), reglas, corridas de FET y propuestas
--   finanzas_     categorías, valor hora, presupuestos y nombramientos
--   proyeccion_   inscritos históricos y estimaciones
--   plataforma_   importaciones, módulos habilitados y auditoría de los eventos de la aplicación
-- Módulos de los grupos (g1 a g4): cada uno tiene su propio archivo SQLite (g1.db ...);
-- el módulo base no los adjunta ni hay FK entre ellos: se hablan por la interfaz de integración.
--
-- Quién abre este archivo: solo Directus (PRAGMA foreign_keys = ON, journal_mode = WAL y busy_timeout = 5000).
-- La API de la plataforma le habla a Directus con la sesión de cada persona. Directus aplica los permisos por rol y
-- departamento (las políticas se generan desde identidad_rol_permiso) y deja el registro de quién cambió qué, con IP y
-- fecha, en directus_activity y directus_revisions. Las migraciones y el generador de datos de prueba son las únicas
-- excepciones. Los triggers de este archivo no dependen de quién escribe: guardan la integridad (borrado lógico,
-- aprobación de horarios, restricciones usadas) sea cual sea el camino de acceso.
--
-- Convenciones:
--   * nombres en español, snake_case y tablas en singular
--   * id interno INTEGER PRIMARY KEY + clave natural única (codigo, nrc; la persona, por el índice ciego de su RUT)
--   * tablas STRICT: booleanos como INTEGER 0/1, fechas y horas como texto ISO 8601 (UTC),
--     JSON como TEXT validado con json_valid()
--   * valores cerrados con CHECK
--   * dentro del núcleo las FK siguen un orden sin ciclos:
--       identidad, plataforma <- catalogo <- horarios <- finanzas
--       catalogo <- proyeccion
--   * terminología del ERS: paralelo (antes sección); NRC es el código de Banner
--   * departamentos: el DISC es el id 1 y existe siempre. Los datos maestros, restricciones,
--     períodos y presupuestos llevan departamento_id; lo demás lo hereda por el período.
--     Cada usuario de Directus tiene su departamento (campo departamento_id, nulo = todos) y las políticas de
--     Directus filtran por él: un departamento no edita los horarios de otro.
--   * borrado lógico: nada se elimina de forma efectiva. Las tablas mantenidas por
--     usuarios tienen eliminado_en/eliminado_por y un trigger impide el DELETE
--     (salvo datos derivados de un borrador: asignaciones, hallazgos y actividades de FET).
--   * auditoría: los cambios de datos y los inicios de sesión los registra Directus (directus_activity y
--     directus_revisions, protegidas contra modificación y borrado por triggers que crea el configurador).
--     plataforma_auditoria guarda los eventos que Directus no ve: intentos de acceso fallidos, accesos denegados,
--     lectura de datos personales, publicaciones e importaciones. Es de solo inserción y se conserva 5 años;
--     pasado ese plazo se purga con:
--       DELETE FROM plataforma_auditoria WHERE en < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-5 years');
--   * acceso de los satélites: lectura mediante Directus (opción A) sobre este mismo archivo;
--     identidad sigue siendo la fuente de usuarios y roles. Las tablas directus_* quedan aparte.
--   * datos personales cifrados: el RUT y el correo (catalogo_persona, envíos) van cifrados por la aplicación y el RUT
--     se busca por un índice ciego. Lo que SQLite no hace y vive en la aplicación: cifrar y descifrar, validar el
--     dígito verificador del RUT; las reglas de negocio de la verificación (hallazgos) las escribe
--     el verificador independiente.
--
-- Crear la base: sqlite3 plataforma.db < esquema_plataforma.sql
-- =====================================================================

PRAGMA foreign_keys = ON;
BEGIN;

"""

IDENTIDAD = """-- ---------------------------------------------------------------------
-- 1. identidad
-- ---------------------------------------------------------------------
CREATE TABLE identidad_departamento (
  id              INTEGER PRIMARY KEY,
  codigo          TEXT NOT NULL UNIQUE CHECK (codigo = upper(codigo)),     -- DISC
  nombre          TEXT NOT NULL,
  predeterminado  INTEGER NOT NULL DEFAULT 0 CHECK (predeterminado IN (0, 1)),   -- el DISC: id 1, no se elimina
  activo          INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
  creado_en       @TS@,
  @SD@
) STRICT;
CREATE UNIQUE INDEX departamento_predeterminado_uk ON identidad_departamento (predeterminado) WHERE predeterminado = 1;

-- Espejo de los usuarios de Directus, que es quien guarda las credenciales y la sesión. Existe para que las demás tablas
-- (eliminado_por, creada_por, aprobada_por...) sigan apuntando a un id entero. Lo mantiene la API.
CREATE TABLE identidad_usuario (
  id            INTEGER PRIMARY KEY,
  directus_id   TEXT NOT NULL UNIQUE CHECK (length(directus_id) = 36),   -- id (UUID) del usuario en Directus
  email         TEXT NOT NULL UNIQUE CHECK (email = lower(email)),
  nombre        TEXT NOT NULL,
  tipo          TEXT NOT NULL DEFAULT 'persona' CHECK (tipo IN ('persona', 'modulo')),
  activo        INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
  creado_en     @TS@,
  @SD@
) STRICT;

-- Roles editables. El rol de sistema (administrador) no se desactiva ni se elimina.
CREATE TABLE identidad_rol (
  codigo       TEXT PRIMARY KEY,                     -- administrador, encargado_docente, consulta, modulo_satelite, ...
  nombre       TEXT NOT NULL,
  descripcion  TEXT,
  es_sistema   INTEGER NOT NULL DEFAULT 0 CHECK (es_sistema IN (0, 1)),
  activo       INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
  @SD@
) STRICT;

CREATE TABLE identidad_permiso (
  codigo       TEXT PRIMARY KEY,                     -- horarios.generar, restricciones.gestionar, ...
  descripcion  TEXT NOT NULL
) STRICT;

-- Quitar un permiso a un rol marca revocado_en; volver a darlo lo limpia.
CREATE TABLE identidad_rol_permiso (
  id INTEGER PRIMARY KEY,                            -- clave sustituta: Directus no admite claves compuestas
  rol          TEXT NOT NULL REFERENCES identidad_rol,
  permiso      TEXT NOT NULL REFERENCES identidad_permiso,
  revocado_en  TEXT,
  UNIQUE (rol, permiso)
) STRICT;

CREATE TRIGGER departamento_protegido BEFORE UPDATE ON identidad_departamento
WHEN OLD.predeterminado = 1 AND (NEW.predeterminado = 0 OR NEW.activo = 0 OR NEW.eliminado_en IS NOT NULL)
BEGIN SELECT RAISE(ABORT, 'El departamento predeterminado no se puede desactivar ni eliminar'); END;

CREATE TRIGGER rol_protegido BEFORE UPDATE ON identidad_rol
WHEN OLD.es_sistema = 1 AND (NEW.es_sistema = 0 OR NEW.activo = 0 OR NEW.eliminado_en IS NOT NULL)
BEGIN SELECT RAISE(ABORT, 'El rol de sistema no se desactiva ni se elimina'); END;

"""

PLATAFORMA = """-- ---------------------------------------------------------------------
-- 2. plataforma (importaciones, módulos y auditoría de eventos)
-- ---------------------------------------------------------------------
CREATE TABLE plataforma_importacion (
  id                  INTEGER PRIMARY KEY,
  departamento_id     INTEGER NOT NULL DEFAULT 1 REFERENCES identidad_departamento,
  periodo_codigo      TEXT,                       -- sin FK para no depender de catalogo
  fuente              TEXT NOT NULL CHECK (fuente IN
                        ('planilla_encargado', 'banner', 'argos_csv', 'academicos', 'ayudantes', 'historico')),
  version_importador  TEXT NOT NULL,              -- p. ej. planilla_encargado@1
  archivo_nombre      TEXT NOT NULL,
  archivo_sha256      TEXT NOT NULL CHECK (length(archivo_sha256) = 64),
  estado              TEXT NOT NULL DEFAULT 'validando'
                      CHECK (estado IN ('validando', 'con_errores', 'lista', 'confirmada', 'descartada')),
  creada_por          INTEGER REFERENCES identidad_usuario,
  creada_en           @TS@
) STRICT;

-- Filas crudas tal como venían. El RUT y el correo se guardan cifrados; el nombre no. Al cerrar el periodo se anonimizan, no se borran:
--   UPDATE plataforma_fila_importada SET datos = '{}', anonimizada_en = strftime('%Y-%m-%dT%H:%M:%SZ','now')
--   WHERE importacion_id = ? AND anonimizada_en IS NULL;
-- errores lleva, por cada problema, la columna, qué falló y cómo corregirlo:
--   [{"columna": "RUT", "gravedad": "bloqueante", "falla": "...", "como_corregir": "..."}]
CREATE TABLE plataforma_fila_importada (
  id INTEGER PRIMARY KEY,                            -- clave sustituta: Directus no admite claves compuestas
  importacion_id  INTEGER NOT NULL REFERENCES plataforma_importacion ON DELETE RESTRICT,
  numero_fila     INTEGER NOT NULL,
  datos           TEXT NOT NULL CHECK (json_valid(datos)),
  errores         TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(errores)),
  anonimizada_en  TEXT,
  UNIQUE (importacion_id, numero_fila)
) STRICT;

CREATE TABLE plataforma_modulo (
  codigo      TEXT PRIMARY KEY,                   -- g1, g2, g3, g4
  nombre      TEXT NOT NULL,
  habilitado  INTEGER NOT NULL DEFAULT 0 CHECK (habilitado IN (0, 1)),   -- apagar sin volver a desplegar
  version     TEXT                                -- la que fija platform.lock
) STRICT;

-- Auditoría de eventos de la aplicación: solo inserción, 5 años. Cada fila dice quién, cuándo, desde qué IP y sobre qué
-- elemento. Los cambios de datos no pasan por aquí: los registra Directus en directus_activity y directus_revisions.
CREATE TABLE plataforma_auditoria (
  id               INTEGER PRIMARY KEY,
  en               @TS@,
  usuario_id       INTEGER REFERENCES identidad_usuario,
  departamento_id  INTEGER REFERENCES identidad_departamento,
  ip               TEXT,                          -- dirección de origen de la petición
  accion           TEXT NOT NULL,                 -- login, acceso_denegado, lectura_datos_personales, importacion, publicacion_satelites...
  resultado        TEXT NOT NULL DEFAULT 'ok' CHECK (resultado IN ('ok', 'denegado', 'error')),
  entidad          TEXT NOT NULL,
  entidad_id       TEXT,
  antes            TEXT CHECK (antes IS NULL OR json_valid(antes)),
  despues          TEXT CHECK (despues IS NULL OR json_valid(despues))
) STRICT;
CREATE INDEX auditoria_entidad_ix ON plataforma_auditoria (entidad, entidad_id);
CREATE INDEX auditoria_usuario_ix ON plataforma_auditoria (usuario_id, en);
CREATE INDEX auditoria_en_ix ON plataforma_auditoria (en);

CREATE TRIGGER auditoria_inmutable BEFORE UPDATE ON plataforma_auditoria
BEGIN SELECT RAISE(ABORT, 'La auditoría es de solo inserción'); END;
CREATE TRIGGER auditoria_retencion BEFORE DELETE ON plataforma_auditoria
WHEN OLD.en > strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-5 years')
BEGIN SELECT RAISE(ABORT, 'La auditoría se conserva durante 5 años'); END;

"""

CATALOGO = """-- ---------------------------------------------------------------------
-- 3. catalogo (datos maestros)
-- ---------------------------------------------------------------------
CREATE TABLE catalogo_periodo (
  id               INTEGER PRIMARY KEY,
  departamento_id  INTEGER NOT NULL DEFAULT 1 REFERENCES identidad_departamento,
  codigo           TEXT NOT NULL CHECK (codigo GLOB '[0-9][0-9][0-9][0-9][0-9][0-9]'),   -- 202620: año + 10 o 20
  fecha_inicio     TEXT,
  fecha_fin        TEXT,
  estado           TEXT NOT NULL DEFAULT 'planificacion' CHECK (estado IN ('planificacion', 'vigente', 'cerrado')),
  CHECK (fecha_inicio IS NULL OR fecha_fin IS NULL OR fecha_fin > fecha_inicio),
  UNIQUE (departamento_id, codigo)
) STRICT;

CREATE TABLE catalogo_programa (
  id               INTEGER PRIMARY KEY,
  departamento_id  INTEGER NOT NULL DEFAULT 1 REFERENCES identidad_departamento,
  codigo           TEXT NOT NULL,                 -- ICCI, IenCI, ICEL, PDIA, PMII, ...
  nombre           TEXT,
  tipo             TEXT CHECK (tipo IN ('pregrado', 'postgrado', 'servicio', 'minor')),
  @SD@,
  UNIQUE (departamento_id, codigo)
) STRICT;

CREATE TABLE catalogo_asignatura (
  id                    INTEGER PRIMARY KEY,
  departamento_id       INTEGER NOT NULL DEFAULT 1 REFERENCES identidad_departamento,
  -- Nulo mientras Banner no asigna código (filas ADD de la planilla);
  -- hasta entonces los demás módulos la referencian por id.
  codigo                TEXT UNIQUE CHECK (codigo GLOB '[A-Z][A-Z][A-Z][A-Z]-[0-9][0-9][0-9][0-9][0-9]'),
  nombre                TEXT NOT NULL,
  area                  TEXT,
  requiere_laboratorio  INTEGER NOT NULL DEFAULT 0 CHECK (requiere_laboratorio IN (0, 1)),   -- lo marca a mano el Encargado Docente (RPD-11)
  activa                INTEGER NOT NULL DEFAULT 1 CHECK (activa IN (0, 1)),
  @SD@
) STRICT;

-- Malla: en qué nivel de qué programa está cada asignatura.
CREATE TABLE catalogo_plan_nivel (
  id INTEGER PRIMARY KEY,                            -- clave sustituta: Directus no admite claves compuestas
  programa_id    INTEGER NOT NULL REFERENCES catalogo_programa,
  asignatura_id  INTEGER NOT NULL REFERENCES catalogo_asignatura,
  nivel          INTEGER CHECK (nivel BETWEEN 1 AND 12),   -- nulo para electivas sin nivel
  caracter       TEXT NOT NULL CHECK (caracter IN ('obligatoria', 'electiva')),
  UNIQUE (programa_id, asignatura_id)
) STRICT;

CREATE TABLE catalogo_dia (
  codigo  TEXT PRIMARY KEY CHECK (length(codigo) = 2),    -- Lu, Ma, Mi, Ju, Vi, Sa
  nombre  TEXT NOT NULL,
  orden   INTEGER NOT NULL UNIQUE
) STRICT;

CREATE TABLE catalogo_bloque (
  codigo       TEXT PRIMARY KEY CHECK (length(codigo) = 1),   -- A a G
  hora_inicio  TEXT NOT NULL,
  hora_fin     TEXT NOT NULL CHECK (hora_fin > hora_inicio),
  orden        INTEGER NOT NULL UNIQUE
) STRICT;

CREATE TABLE catalogo_sala (
  id                INTEGER PRIMARY KEY,
  departamento_id   INTEGER REFERENCES identidad_departamento,             -- dueño; nulo si es compartida o externa
  codigo            TEXT NOT NULL UNIQUE CHECK (codigo = upper(codigo)),   -- Y1-003, R-044, V2-ROB-1
  nombre            TEXT,
  capacidad         INTEGER CHECK (capacidad > 0),                         -- nula hasta confirmarla
  es_laboratorio    INTEGER NOT NULL DEFAULT 0 CHECK (es_laboratorio IN (0, 1)),
  administrada_por  TEXT NOT NULL DEFAULT 'externa' CHECK (administrada_por IN ('disc', 'externa')),
  activa            INTEGER NOT NULL DEFAULT 1 CHECK (activa IN (0, 1)),
  @SD@
) STRICT;

-- Datos personales mínimos: RUT, nombre y correo. No se guarda nada de estudiantes.
-- El RUT y el correo se guardan CIFRADOS (AES-256-GCM, en la aplicación; ver docs/backend.md): la base solo ve texto
-- cifrado, así que un volcado, una copia de seguridad, la auditoría o Directus no los muestran. El RUT no es clave en
-- ninguna tabla: las demás tablas apuntan a id. rut_indice es un HMAC-SHA256 con clave aparte del RUT normalizado
-- (12345678-5): permite buscar y exigir unicidad sin descifrar. Validar el dígito verificador es tarea de la aplicación.
CREATE TABLE catalogo_persona (
  id             INTEGER PRIMARY KEY,
  rut_cifrado    TEXT NOT NULL CHECK (rut_cifrado GLOB 'v1:*'),
  rut_indice     TEXT NOT NULL UNIQUE CHECK (length(rut_indice) = 64),
  nombre         TEXT NOT NULL,
  email_cifrado  TEXT CHECK (email_cifrado IS NULL OR email_cifrado GLOB 'v1:*'),
  @SD@
) STRICT;

CREATE TABLE catalogo_docente (
  persona_id       INTEGER PRIMARY KEY REFERENCES catalogo_persona,
  departamento_id  INTEGER NOT NULL DEFAULT 1 REFERENCES identidad_departamento,
  tipo_contrato    TEXT NOT NULL CHECK (tipo_contrato IN ('planta', 'hora')),
  activo           INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
  @SD@
) STRICT;

CREATE TABLE catalogo_ayudante (
  persona_id       INTEGER PRIMARY KEY REFERENCES catalogo_persona,
  departamento_id  INTEGER NOT NULL DEFAULT 1 REFERENCES identidad_departamento,
  activo           INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
  @SD@
) STRICT;

"""

HORARIOS = """-- ---------------------------------------------------------------------
-- 4. horarios
-- ---------------------------------------------------------------------
CREATE TABLE horarios_liga (
  id          INTEGER PRIMARY KEY,
  periodo_id  INTEGER NOT NULL REFERENCES catalogo_periodo,
  codigo      TEXT NOT NULL,                      -- ASYS, CYBR, L01, ...
  @SD@,
  UNIQUE (periodo_id, codigo)
) STRICT;

CREATE TABLE horarios_paralelo (
  id                    INTEGER PRIMARY KEY,
  periodo_id            INTEGER NOT NULL REFERENCES catalogo_periodo,
  asignatura_id         INTEGER NOT NULL REFERENCES catalogo_asignatura,
  nrc                   INTEGER,                  -- nulo en paralelos nuevos (ADD) hasta que Banner lo asigne
  codigo                TEXT NOT NULL,            -- C1, L01, T1; no es único: una cátedra y su taller comparten C1
  componente            TEXT NOT NULL DEFAULT 'catedra'
                        CHECK (componente IN ('catedra', 'laboratorio', 'taller', 'proyecto')),
  estado                TEXT NOT NULL DEFAULT 'ok' CHECK (estado IN ('ok', 'nueva', 'inactiva')),
  cupo_estimado         INTEGER CHECK (cupo_estimado >= 0),
  sesiones_semana       INTEGER CHECK (sesiones_semana BETWEEN 1 AND 6),
  requiere_laboratorio  INTEGER CHECK (requiere_laboratorio IN (0, 1)),   -- nulo: hereda el valor de la asignatura
  liga_id               INTEGER REFERENCES horarios_liga,
  sesiones_seguidas     INTEGER NOT NULL DEFAULT 0 CHECK (sesiones_seguidas IN (0, 1)),   -- RPD-14: si no, las sesiones van en días distintos
  docentes_alternan     INTEGER NOT NULL DEFAULT 0 CHECK (docentes_alternan IN (0, 1)),   -- RPD-02: dos docentes por módulos, se permite el choque
  observacion           TEXT,                     -- columna Argumento de la planilla
  importacion_id        INTEGER REFERENCES plataforma_importacion,
  @SD@
) STRICT;
CREATE UNIQUE INDEX paralelo_nrc_uk ON horarios_paralelo (periodo_id, nrc) WHERE nrc IS NOT NULL;
CREATE INDEX paralelo_periodo_ix ON horarios_paralelo (periodo_id);
CREATE INDEX paralelo_liga_ix ON horarios_paralelo (liga_id) WHERE liga_id IS NOT NULL;

-- Un paralelo puede tener varios docentes (la planilla trae casos con dos y tres RUT).
CREATE TABLE horarios_paralelo_docente (
  id INTEGER PRIMARY KEY,                            -- clave sustituta: Directus no admite claves compuestas
  paralelo_id  INTEGER NOT NULL REFERENCES horarios_paralelo ON DELETE RESTRICT,
  docente_id   INTEGER NOT NULL REFERENCES catalogo_docente,
  UNIQUE (paralelo_id, docente_id)
) STRICT;

-- Qué nivel de qué programa cursa el paralelo: son los grupos de estudiantes de FET.
CREATE TABLE horarios_paralelo_grupo (
  id INTEGER PRIMARY KEY,                            -- clave sustituta: Directus no admite claves compuestas
  paralelo_id  INTEGER NOT NULL REFERENCES horarios_paralelo ON DELETE RESTRICT,
  programa_id  INTEGER NOT NULL REFERENCES catalogo_programa,
  nivel        INTEGER CHECK (nivel BETWEEN 1 AND 12),   -- nulo para electivas
  UNIQUE (paralelo_id, programa_id)
) STRICT;

-- Cada sesión semanal es una actividad para FET.
CREATE TABLE horarios_sesion (
  id                INTEGER PRIMARY KEY,
  paralelo_id       INTEGER NOT NULL REFERENCES horarios_paralelo ON DELETE RESTRICT,
  numero            INTEGER NOT NULL,
  duracion_bloques  INTEGER NOT NULL DEFAULT 1 CHECK (duracion_bloques BETWEEN 1 AND 3),   -- 2 = doble, p. ej. Sa DE
  @SD@,
  UNIQUE (paralelo_id, numero)
) STRICT;

-- Sin fila = disponible y sin preferencia.
CREATE TABLE horarios_disponibilidad_docente (
  id INTEGER PRIMARY KEY,                            -- clave sustituta: Directus no admite claves compuestas
  periodo_id  INTEGER NOT NULL REFERENCES catalogo_periodo,
  docente_id  INTEGER NOT NULL REFERENCES catalogo_docente,
  dia         TEXT NOT NULL REFERENCES catalogo_dia,
  bloque      TEXT NOT NULL REFERENCES catalogo_bloque,
  tipo        TEXT NOT NULL CHECK (tipo IN ('no_disponible', 'preferido', 'evitar')),
  UNIQUE (periodo_id, docente_id, dia, bloque)
) STRICT;

-- Bloques en que una sala no está disponible (salas externas según ARGOS, o a mano).
CREATE TABLE horarios_bloqueo_sala (
  id INTEGER PRIMARY KEY,                            -- clave sustituta: Directus no admite claves compuestas
  periodo_id  INTEGER NOT NULL REFERENCES catalogo_periodo,
  sala_id     INTEGER NOT NULL REFERENCES catalogo_sala,
  dia         TEXT NOT NULL REFERENCES catalogo_dia,
  bloque      TEXT NOT NULL REFERENCES catalogo_bloque,
  fuente      TEXT NOT NULL CHECK (fuente IN ('g1', 'argos_csv', 'manual')),
  UNIQUE (periodo_id, sala_id, dia, bloque)
) STRICT;

-- Salas externas (R): solo se usan si fueron solicitadas y aprobadas (RPD-13).
CREATE TABLE horarios_sala_externa_autorizada (
  id INTEGER PRIMARY KEY,                            -- clave sustituta: Directus no admite claves compuestas
  periodo_id    INTEGER NOT NULL REFERENCES catalogo_periodo,
  sala_id       INTEGER NOT NULL REFERENCES catalogo_sala,
  aprobada_por  INTEGER REFERENCES identidad_usuario,
  aprobada_en   @TS@,
  revocada_en   TEXT,
  UNIQUE (periodo_id, sala_id)
) STRICT;

-- Bloques que ciencias básicas ocupa para un nivel: el DISC no puede usarlos en ese nivel.
CREATE TABLE horarios_reserva_nivel (
  id INTEGER PRIMARY KEY,                            -- clave sustituta: Directus no admite claves compuestas
  periodo_id   INTEGER NOT NULL REFERENCES catalogo_periodo,
  programa_id  INTEGER NOT NULL REFERENCES catalogo_programa,
  nivel        INTEGER NOT NULL,
  dia          TEXT NOT NULL REFERENCES catalogo_dia,
  bloque       TEXT NOT NULL REFERENCES catalogo_bloque,
  motivo       TEXT NOT NULL,                     -- p. ej. Cálculo II, paralelo 3
  UNIQUE (periodo_id, programa_id, nivel, dia, bloque)
) STRICT;

CREATE TABLE horarios_perfil (
  id           INTEGER PRIMARY KEY,
  nombre       TEXT NOT NULL UNIQUE,
  descripcion  TEXT,
  pesos        TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(pesos)),   -- peso de cada regla blanda en este perfil
  @SD@
) STRICT;

-- Reglas como filas: una regla nueva no cambia el esquema. Es el catálogo editable del departamento
-- (permiso restricciones.gestionar). periodo_id nulo = vale para todos sus períodos. Los bloques protegidos
-- (jueves C, miércoles D) son filas tipo 'bloque_protegido'. Una regla usada por un horario aprobado no se
-- elimina: se desactiva (trigger restriccion_usada).
CREATE TABLE horarios_restriccion (
  id               INTEGER PRIMARY KEY,
  departamento_id  INTEGER NOT NULL DEFAULT 1 REFERENCES identidad_departamento,
  periodo_id       INTEGER REFERENCES catalogo_periodo,
  naturaleza       TEXT NOT NULL CHECK (naturaleza IN ('dura', 'blanda')),
  tipo             TEXT NOT NULL,                 -- nivel_sin_choque, capacidad, liga, bloque_protegido, max_clases_docente_dia, ...
  alcance          TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(alcance)),       -- {"programa": "ICCI", "nivel": 5}
  parametros       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(parametros)),    -- {"dia": "Ju", "bloque": "C"}
  peso             INTEGER,                       -- solo blandas: 1 a 99, independiente de las demás
  vigente_desde    TEXT,
  vigente_hasta    TEXT,
  activa           INTEGER NOT NULL DEFAULT 1 CHECK (activa IN (0, 1)),
  nota             TEXT,
  creada_por       INTEGER REFERENCES identidad_usuario,
  creada_en        @TS@,
  actualizada_en   @TS@,
  @SD@,
  CHECK ((naturaleza = 'dura' AND peso IS NULL) OR (naturaleza = 'blanda' AND peso IS NOT NULL AND peso BETWEEN 1 AND 99)),
  CHECK (vigente_desde IS NULL OR vigente_hasta IS NULL OR vigente_hasta >= vigente_desde)
) STRICT;
CREATE INDEX restriccion_vigente_ix ON horarios_restriccion (departamento_id, periodo_id)
  WHERE activa = 1 AND eliminado_en IS NULL;

CREATE TABLE horarios_propuesta (
  id          INTEGER PRIMARY KEY,
  periodo_id  INTEGER NOT NULL REFERENCES catalogo_periodo,
  corrida_id  INTEGER REFERENCES horarios_corrida,   -- nulo si nació copiando otra
  origen_id   INTEGER REFERENCES horarios_propuesta,
  nombre      TEXT NOT NULL,
  -- Un ajuste sobre una aprobada se hace copiándola a un borrador (origen_id). Al aprobar el borrador,
  -- la anterior pasa a 'reemplazada' y se conserva.
  estado      TEXT NOT NULL DEFAULT 'borrador' CHECK (estado IN ('borrador', 'aprobada', 'reemplazada', 'descartada')),
  completa    INTEGER NOT NULL DEFAULT 0 CHECK (completa IN (0, 1)),   -- todas las sesiones requeridas están asignadas
  metricas    TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metricas)),   -- duras violadas, preferencias cumplidas, salas por pedir...
  reemplazada_por  INTEGER REFERENCES horarios_propuesta,
  aprobada_por     INTEGER REFERENCES identidad_usuario,
  aprobada_en      TEXT,
  creada_por  INTEGER REFERENCES identidad_usuario,
  creada_en   @TS@
) STRICT;
CREATE UNIQUE INDEX propuesta_aprobada_uk ON horarios_propuesta (periodo_id) WHERE estado = 'aprobada';

-- Una ejecución de fet-cl. También es la cola del worker (SQLite tiene un solo escritor, no hace falta SKIP LOCKED):
--   UPDATE horarios_corrida SET estado = 'en_curso', iniciada_en = strftime('%Y-%m-%dT%H:%M:%SZ','now')
--   WHERE id = (SELECT id FROM horarios_corrida WHERE estado = 'pendiente' ORDER BY creada_en LIMIT 1) RETURNING *;
CREATE TABLE horarios_corrida (
  id                 INTEGER PRIMARY KEY,
  periodo_id         INTEGER NOT NULL REFERENCES catalogo_periodo,
  perfil_id          INTEGER NOT NULL REFERENCES horarios_perfil,
  semilla            TEXT NOT NULL CHECK (json_valid(semilla) AND json_array_length(semilla) = 6),   -- --randomseeds10 a 22
  limite_segundos    INTEGER NOT NULL DEFAULT 60 CHECK (limite_segundos > 0),   -- un minuto por defecto
  -- Para reproducir y auditar: las restricciones y pesos tal como estaban al lanzar la corrida.
  restricciones_usadas  TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(restricciones_usadas)),   -- [{"id": 7, "naturaleza": "blanda", "tipo": "...", "parametros": {}, "peso": 5}]
  pesos_usados          TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(pesos_usados)),           -- pesos del perfil
  entrada_sha256        TEXT CHECK (entrada_sha256 IS NULL OR length(entrada_sha256) = 64),    -- huella de los datos de entrada
  base_propuesta_id  INTEGER REFERENCES horarios_propuesta,   -- reoptimización: respeta sus actividades fijadas
  -- Resultados del ERS: completa, inviable (demostrado), tiempo_agotado, cancelada, datos_invalidos y
  -- fallida (fallo técnico). 'parcial': el tiempo se agotó pero hay una mejor solución válida.
  estado             TEXT NOT NULL DEFAULT 'pendiente'
                     CHECK (estado IN ('pendiente', 'en_curso', 'completa', 'parcial', 'inviable',
                                       'tiempo_agotado', 'cancelada', 'datos_invalidos', 'fallida')),
  version_fet        TEXT,
  directorio         TEXT,                        -- carpeta del volumen con el .fet y los resultados
  mensaje            TEXT,                        -- p. ej. la actividad que no pudo ubicarse
  solicitada_por     INTEGER REFERENCES identidad_usuario,
  creada_en          @TS@,
  iniciada_en        TEXT,
  terminada_en       TEXT
) STRICT;
CREATE INDEX corrida_pendiente_ix ON horarios_corrida (creada_en) WHERE estado = 'pendiente';

-- Traducción entre el Id de actividad de FET y las sesiones.
-- Varias sesiones comparten fet_id cuando sus paralelos están ligados.
CREATE TABLE horarios_corrida_actividad (
  id INTEGER PRIMARY KEY,                            -- clave sustituta: Directus no admite claves compuestas
  corrida_id  INTEGER NOT NULL REFERENCES horarios_corrida ON DELETE RESTRICT,
  sesion_id   INTEGER NOT NULL REFERENCES horarios_sesion,
  fet_id      INTEGER NOT NULL,
  UNIQUE (corrida_id, sesion_id)
) STRICT;
CREATE INDEX corrida_actividad_fet_ix ON horarios_corrida_actividad (corrida_id, fet_id);

CREATE TABLE horarios_asignacion (
  id INTEGER PRIMARY KEY,                            -- clave sustituta: Directus no admite claves compuestas
  propuesta_id  INTEGER NOT NULL REFERENCES horarios_propuesta ON DELETE RESTRICT,
  sesion_id     INTEGER NOT NULL REFERENCES horarios_sesion,
  dia           TEXT NOT NULL REFERENCES catalogo_dia,
  bloque        TEXT NOT NULL REFERENCES catalogo_bloque,   -- bloque de inicio
  sala_id       INTEGER REFERENCES catalogo_sala,           -- nula si la sala está pendiente
  fijada        INTEGER NOT NULL DEFAULT 0 CHECK (fijada IN (0, 1)),   -- se respeta al reoptimizar
  origen        TEXT NOT NULL DEFAULT 'motor' CHECK (origen IN ('motor', 'manual')),
  modificada_por  INTEGER REFERENCES identidad_usuario,
  modificada_en   TEXT,
  UNIQUE (propuesta_id, sesion_id)
) STRICT;
CREATE INDEX asignacion_sala_ix ON horarios_asignacion (propuesta_id, sala_id, dia, bloque);
-- Sin UNIQUE por sala y bloque a propósito: los paralelos ligados comparten sala a la misma hora.
-- Los choques los detecta el verificador y quedan en horarios_hallazgo.

CREATE TABLE horarios_hallazgo (
  id            INTEGER PRIMARY KEY,
  propuesta_id  INTEGER NOT NULL REFERENCES horarios_propuesta ON DELETE RESTRICT,
  severidad     TEXT NOT NULL CHECK (severidad IN ('dura', 'blanda', 'aviso')),
  tipo          TEXT NOT NULL,                    -- choque_nivel, choque_docente, capacidad, preferencia, ...
  detalle       TEXT NOT NULL CHECK (json_valid(detalle))
) STRICT;
CREATE INDEX hallazgo_propuesta_ix ON horarios_hallazgo (propuesta_id, severidad);

-- Envío del horario aprobado a cada docente por correo (HOR-007). Un reenvío agrega otra fila.
CREATE TABLE horarios_envio_horario (
  id            INTEGER PRIMARY KEY,
  propuesta_id  INTEGER NOT NULL REFERENCES horarios_propuesta,
  docente_id    INTEGER NOT NULL REFERENCES catalogo_docente,
  email_destino_cifrado TEXT NOT NULL CHECK (email_destino_cifrado GLOB 'v1:*'),   -- correo del docente, cifrado como el de catalogo_persona
  estado        TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'enviado', 'error')),
  error         TEXT,
  creado_por    INTEGER REFERENCES identidad_usuario,
  creado_en     @TS@,
  enviado_en    TEXT
) STRICT;
CREATE INDEX envio_horario_propuesta_ix ON horarios_envio_horario (propuesta_id, estado);

-- Horario de cada paralelo en el formato de la planilla: "Ma C (Y1-001), Ju B (Y1-001)".
-- Usa group_concat con ORDER BY (SQLite 3.44 o superior).
CREATE VIEW horarios_v_horario_paralelo AS
SELECT a.propuesta_id,
       s.paralelo_id,
       group_concat(
         a.dia || ' ' || (SELECT group_concat(b2.codigo, '' ORDER BY b2.orden)
                          FROM catalogo_bloque b2
                          WHERE b2.orden BETWEEN b.orden AND b.orden + s.duracion_bloques - 1)
              || COALESCE(' (' || sa.codigo || ')', ''),
         ', ' ORDER BY d.orden, b.orden
       ) AS horario
FROM horarios_asignacion a
JOIN horarios_sesion s  ON s.id = a.sesion_id
JOIN catalogo_dia d     ON d.codigo = a.dia
JOIN catalogo_bloque b  ON b.codigo = a.bloque
LEFT JOIN catalogo_sala sa ON sa.id = a.sala_id
GROUP BY a.propuesta_id, s.paralelo_id;

-- Solo una propuesta en borrador se edita; una aprobada o reemplazada se copia. Quién puede editar lo decide Directus
-- (permiso horarios.editar en el departamento del período); la API marca el cambio como 'manual' y quién lo hizo.
CREATE TRIGGER asignacion_borrador_i BEFORE INSERT ON horarios_asignacion
WHEN (SELECT estado FROM horarios_propuesta WHERE id = NEW.propuesta_id) <> 'borrador'
BEGIN SELECT RAISE(ABORT, 'La propuesta no está en borrador: cópiela para editarla'); END;
CREATE TRIGGER asignacion_borrador_u BEFORE UPDATE ON horarios_asignacion
WHEN (SELECT estado FROM horarios_propuesta WHERE id = OLD.propuesta_id) <> 'borrador'
BEGIN SELECT RAISE(ABORT, 'La propuesta no está en borrador: cópiela para editarla'); END;
CREATE TRIGGER asignacion_borrador_d BEFORE DELETE ON horarios_asignacion
WHEN (SELECT estado FROM horarios_propuesta WHERE id = OLD.propuesta_id) <> 'borrador'
BEGIN SELECT RAISE(ABORT, 'La propuesta no está en borrador: cópiela para editarla'); END;

-- Aprobar: solo un borrador completo y sin violaciones duras. Quién puede aprobar lo decide Directus (horarios.aprobar).
-- La aprobada anterior pasa a 'reemplazada' y se conserva.
CREATE TRIGGER propuesta_reemplazada_fija BEFORE UPDATE OF estado ON horarios_propuesta
WHEN OLD.estado = 'reemplazada' AND NEW.estado <> OLD.estado
BEGIN SELECT RAISE(ABORT, 'Una propuesta reemplazada no cambia de estado'); END;
CREATE TRIGGER propuesta_aprobada_fija BEFORE UPDATE OF estado ON horarios_propuesta
WHEN OLD.estado = 'aprobada' AND NEW.estado NOT IN ('aprobada', 'reemplazada')
BEGIN SELECT RAISE(ABORT, 'Una propuesta aprobada solo puede pasar a reemplazada'); END;
CREATE TRIGGER propuesta_solo_borrador BEFORE UPDATE OF estado ON horarios_propuesta
WHEN NEW.estado = 'aprobada' AND OLD.estado NOT IN ('aprobada', 'borrador')
BEGIN SELECT RAISE(ABORT, 'Solo un borrador puede aprobarse'); END;
CREATE TRIGGER propuesta_completa BEFORE UPDATE OF estado ON horarios_propuesta
WHEN NEW.estado = 'aprobada' AND OLD.estado <> 'aprobada' AND NEW.completa = 0
BEGIN SELECT RAISE(ABORT, 'La propuesta no está completa: faltan sesiones por asignar'); END;
CREATE TRIGGER propuesta_sin_violaciones BEFORE UPDATE OF estado ON horarios_propuesta
WHEN NEW.estado = 'aprobada' AND OLD.estado <> 'aprobada'
 AND EXISTS (SELECT 1 FROM horarios_hallazgo h WHERE h.propuesta_id = NEW.id AND h.severidad = 'dura')
BEGIN SELECT RAISE(ABORT, 'La propuesta tiene violaciones de restricciones duras'); END;
CREATE TRIGGER propuesta_reemplaza_anterior BEFORE UPDATE OF estado ON horarios_propuesta
WHEN NEW.estado = 'aprobada' AND OLD.estado <> 'aprobada'
BEGIN
  UPDATE horarios_propuesta SET estado = 'reemplazada', reemplazada_por = NEW.id
  WHERE periodo_id = NEW.periodo_id AND estado = 'aprobada' AND id <> NEW.id;
END;
CREATE TRIGGER propuesta_aprobacion_registro AFTER UPDATE OF estado ON horarios_propuesta
WHEN NEW.estado = 'aprobada' AND OLD.estado <> 'aprobada'
BEGIN
  UPDATE horarios_propuesta SET aprobada_en = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = NEW.id;   -- aprobada_por lo envía la API
END;

-- Una restricción usada por un horario aprobado se desactiva, no se elimina.
CREATE TRIGGER restriccion_usada BEFORE UPDATE ON horarios_restriccion
WHEN NEW.eliminado_en IS NOT NULL AND OLD.eliminado_en IS NULL AND EXISTS (
       SELECT 1
       FROM horarios_propuesta p
       JOIN horarios_corrida c ON c.id = p.corrida_id, json_each(c.restricciones_usadas) j
       WHERE p.estado = 'aprobada' AND json_extract(j.value, '$.id') = NEW.id)
BEGIN SELECT RAISE(ABORT, 'La restricción la usó un horario aprobado: desactívela en vez de eliminarla'); END;
CREATE TRIGGER restriccion_actualizada AFTER UPDATE ON horarios_restriccion
WHEN NEW.actualizada_en IS OLD.actualizada_en
BEGIN
  UPDATE horarios_restriccion SET actualizada_en = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = NEW.id;
END;

"""

FINANZAS = """-- ---------------------------------------------------------------------
-- 5. finanzas
-- ---------------------------------------------------------------------
CREATE TABLE finanzas_categoria (
  id            INTEGER PRIMARY KEY,
  tipo_persona  TEXT NOT NULL CHECK (tipo_persona IN ('profesor_hora', 'ayudante')),
  letra         TEXT NOT NULL CHECK (length(letra) = 1),
  orden         INTEGER,                          -- jerarquía entre letras: por confirmar con el Encargado Docente
  UNIQUE (tipo_persona, letra)
) STRICT;

CREATE TABLE finanzas_escenario (
  id               INTEGER PRIMARY KEY,
  departamento_id  INTEGER NOT NULL DEFAULT 1 REFERENCES identidad_departamento,
  nombre           TEXT NOT NULL,                 -- p. ej. "subir 1.000 a cada categoría"
  descripcion      TEXT,
  creado_por       INTEGER REFERENCES identidad_usuario,
  creado_en        @TS@,
  @SD@,
  UNIQUE (departamento_id, nombre)
) STRICT;

-- Valor hora por categoría, con historial. escenario_id nulo = valores reales.
-- Los montos son pesos chilenos; el redondeo está pendiente (P-22).
CREATE TABLE finanzas_tarifa (
  id             INTEGER PRIMARY KEY,
  categoria_id   INTEGER NOT NULL REFERENCES finanzas_categoria,
  valor_hora     REAL NOT NULL CHECK (valor_hora > 0),
  vigente_desde  TEXT NOT NULL,
  escenario_id   INTEGER REFERENCES finanzas_escenario ON DELETE RESTRICT,
  @SD@
) STRICT;
CREATE UNIQUE INDEX tarifa_vigencia_uk ON finanzas_tarifa (categoria_id, vigente_desde, COALESCE(escenario_id, 0));

-- Un presupuesto anual por tipo; porcentaje_s1 es la parte del primer semestre.
CREATE TABLE finanzas_presupuesto (
  id               INTEGER PRIMARY KEY,
  departamento_id  INTEGER NOT NULL DEFAULT 1 REFERENCES identidad_departamento,
  anio             INTEGER NOT NULL,
  tipo_persona     TEXT NOT NULL CHECK (tipo_persona IN ('profesor_hora', 'ayudante')),
  monto_anual      REAL NOT NULL CHECK (monto_anual >= 0),
  porcentaje_s1    REAL NOT NULL DEFAULT 50 CHECK (porcentaje_s1 BETWEEN 0 AND 100),
  escenario_id     INTEGER REFERENCES finanzas_escenario ON DELETE RESTRICT,
  @SD@
) STRICT;
CREATE UNIQUE INDEX presupuesto_uk ON finanzas_presupuesto (departamento_id, anio, tipo_persona, COALESCE(escenario_id, 0));

-- Historial de la categoría de cada persona.
CREATE TABLE finanzas_categoria_persona (
  id INTEGER PRIMARY KEY,                            -- clave sustituta: Directus no admite claves compuestas
  persona_id     INTEGER NOT NULL REFERENCES catalogo_persona,
  categoria_id   INTEGER NOT NULL REFERENCES finanzas_categoria,
  vigente_desde  TEXT NOT NULL,
  UNIQUE (persona_id, categoria_id, vigente_desde)
) STRICT;

CREATE TABLE finanzas_nombramiento (
  id               INTEGER PRIMARY KEY,
  persona_id       INTEGER NOT NULL REFERENCES catalogo_persona,
  periodo_id       INTEGER NOT NULL REFERENCES catalogo_periodo,
  categoria_id     INTEGER NOT NULL REFERENCES finanzas_categoria,   -- define si es profesor hora o ayudante
  paralelo_id      INTEGER REFERENCES horarios_paralelo,             -- nulo si no se asocia a un paralelo
  horas_semanales  REAL NOT NULL CHECK (horas_semanales > 0),
  fecha_inicio     TEXT NOT NULL,
  fecha_fin        TEXT NOT NULL CHECK (fecha_fin >= fecha_inicio),
  origen           TEXT NOT NULL CHECK (origen IN ('horario', 'g4', 'manual')),
  id_externo       TEXT,                          -- id de la solicitud en el G4: sincronizar sin duplicar
  reemplaza_a      INTEGER REFERENCES finanzas_nombramiento,
  estado           TEXT NOT NULL DEFAULT 'vigente' CHECK (estado IN ('vigente', 'anulado')),
  creado_en        @TS@
) STRICT;
CREATE UNIQUE INDEX nombramiento_externo_uk ON finanzas_nombramiento (origen, id_externo)
  WHERE id_externo IS NOT NULL;
CREATE INDEX nombramiento_periodo_ix ON finanzas_nombramiento (periodo_id, estado);
CREATE INDEX nombramiento_persona_ix ON finanzas_nombramiento (persona_id);

-- Foto de un cálculo: el cálculo mismo se hace en el dominio (Python); aquí queda el resultado.
CREATE TABLE finanzas_calculo (
  id               INTEGER PRIMARY KEY,
  departamento_id  INTEGER NOT NULL DEFAULT 1 REFERENCES identidad_departamento,
  anio             INTEGER NOT NULL,
  escenario_id     INTEGER REFERENCES finanzas_escenario ON DELETE RESTRICT,
  reglas           TEXT NOT NULL CHECK (json_valid(reglas)),   -- horas por bloque, base del prorrateo, etc., al momento de calcular
  calculado_por    INTEGER REFERENCES identidad_usuario,
  calculado_en     @TS@
) STRICT;

CREATE TABLE finanzas_calculo_detalle (
  id INTEGER PRIMARY KEY,                            -- clave sustituta: Directus no admite claves compuestas
  calculo_id       INTEGER NOT NULL REFERENCES finanzas_calculo ON DELETE RESTRICT,
  nombramiento_id  INTEGER NOT NULL REFERENCES finanzas_nombramiento,
  mes              TEXT NOT NULL CHECK (mes GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-01'),
  horas            REAL NOT NULL,
  valor_hora       REAL NOT NULL,
  monto            REAL NOT NULL,
  UNIQUE (calculo_id, nombramiento_id, mes)
) STRICT;

CREATE VIEW finanzas_v_resumen_calculo AS
SELECT c.id AS calculo_id, c.anio, c.escenario_id, cat.tipo_persona, d.mes,
       sum(d.monto) AS monto
FROM finanzas_calculo c
JOIN finanzas_calculo_detalle d ON d.calculo_id = c.id
JOIN finanzas_nombramiento n    ON n.id = d.nombramiento_id
JOIN finanzas_categoria cat     ON cat.id = n.categoria_id
GROUP BY c.id, c.anio, c.escenario_id, cat.tipo_persona, d.mes;

"""

PROYECCION = """-- ---------------------------------------------------------------------
-- 6. proyeccion
-- ---------------------------------------------------------------------
-- Inscritos reales, agregados por asignatura: sin datos de estudiantes.
CREATE TABLE proyeccion_inscripcion_historica (
  id INTEGER PRIMARY KEY,                            -- clave sustituta: Directus no admite claves compuestas
  asignatura_id  INTEGER NOT NULL REFERENCES catalogo_asignatura,
  periodo_id     INTEGER NOT NULL REFERENCES catalogo_periodo,
  fuente         TEXT NOT NULL CHECK (fuente IN ('planilla', 'apa', 'argos')),
  inscritos      INTEGER NOT NULL CHECK (inscritos >= 0),
  UNIQUE (asignatura_id, periodo_id, fuente)
) STRICT;

-- Números que ya existen hoy: la proyección de ARGOS y la del Encargado Docente.
CREATE TABLE proyeccion_estimacion_externa (
  id INTEGER PRIMARY KEY,                            -- clave sustituta: Directus no admite claves compuestas
  asignatura_id  INTEGER NOT NULL REFERENCES catalogo_asignatura,
  periodo_id     INTEGER NOT NULL REFERENCES catalogo_periodo,
  fuente         TEXT NOT NULL CHECK (fuente IN ('argos', 'encargado_docente')),
  valor          INTEGER NOT NULL CHECK (valor >= 0),
  UNIQUE (asignatura_id, periodo_id, fuente)
) STRICT;

CREATE TABLE proyeccion_estimacion (
  id             INTEGER PRIMARY KEY,
  periodo_id     INTEGER NOT NULL REFERENCES catalogo_periodo,
  asignatura_id  INTEGER NOT NULL REFERENCES catalogo_asignatura,
  metodo         TEXT NOT NULL CHECK (metodo IN ('triangular', 'pert')),
  minimo         REAL NOT NULL,
  moda           REAL NOT NULL,
  maximo         REAL NOT NULL,
  p10            REAL,
  p50            REAL,
  p90            REAL,
  parametros     TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(parametros)),
  calculada_en   @TS@,
  CHECK (minimo <= moda AND moda <= maximo)
) STRICT;
CREATE INDEX estimacion_periodo_ix ON proyeccion_estimacion (periodo_id, asignatura_id);

"""

DATOS = """-- ---------------------------------------------------------------------
-- 7. Datos base
-- ---------------------------------------------------------------------
-- El DISC se inserta primero: es el id 1 que usan los DEFAULT de departamento_id.
INSERT INTO identidad_departamento (id, codigo, nombre, predeterminado) VALUES
  (1, 'DISC', 'Departamento de Ingeniería de Sistemas y Computación', 1);

INSERT INTO catalogo_dia (codigo, nombre, orden) VALUES
  ('Lu', 'Lunes', 1), ('Ma', 'Martes', 2), ('Mi', 'Miércoles', 3),
  ('Ju', 'Jueves', 4), ('Vi', 'Viernes', 5), ('Sa', 'Sábado', 6);

-- Bloques de la hoja "laboratorios" de la planilla.
INSERT INTO catalogo_bloque (codigo, hora_inicio, hora_fin, orden) VALUES
  ('A', '08:10', '09:40', 1), ('B', '09:55', '11:25', 2), ('C', '11:40', '13:10', 3),
  ('D', '14:30', '16:00', 4), ('E', '16:15', '17:45', 5), ('F', '18:00', '19:30', 6),
  ('G', '19:45', '21:15', 7);

-- Laboratorios que administra el DISC, con la capacidad que indica la planilla.
INSERT INTO catalogo_sala (departamento_id, codigo, nombre, capacidad, es_laboratorio, administrada_por) VALUES
  (1, 'Y1-005',   'Laboratorio de Redes',       20, 1, 'disc'),
  (1, 'Y1-003',   'LabSoft',                    50, 1, 'disc'),
  (1, 'V2-ROB-1', 'Laboratorio Robótica',       32, 1, 'disc'),
  (1, 'V2-UNIV',  'Laboratorio Universia',      32, 1, 'disc');

-- Letras de categoría; el orden entre ellas queda pendiente.
INSERT INTO finanzas_categoria (tipo_persona, letra) VALUES
  ('profesor_hora', 'A'), ('profesor_hora', 'B'), ('profesor_hora', 'C'), ('profesor_hora', 'D'),
  ('ayudante', 'A'), ('ayudante', 'B'), ('ayudante', 'C');

INSERT INTO horarios_perfil (nombre, descripcion) VALUES
  ('base',                  'Solo reglas duras y pesos por defecto'),
  ('prioriza_preferencias', 'Sube el peso de las preferencias de planta'),
  ('ahorra_laboratorios',   'Castiga usar laboratorios en cursos que no los requieren'),
  ('compacta_niveles',      'Reduce ventanas en el día de cada nivel');

-- Reglas de partida del DISC: los bloques protegidos son filas editables del catálogo.
INSERT INTO horarios_restriccion (naturaleza, tipo, parametros, nota) VALUES
  ('dura', 'bloque_protegido',        '{"dia": "Ju", "bloque": "C"}', 'RPD-09 · jueves en el bloque C'),
  ('dura', 'bloque_protegido',        '{"dia": "Mi", "bloque": "D"}', 'RPD-10 · reunión de departamento'),
  ('dura', 'sin_bloque_planta',       '{"bloque": "G"}',              'RPD-08 · profesores de planta sin el último bloque'),
  ('dura', 'max_clases_docente_dia',  '{"maximo": 2}',                'RPD-15 · máximo de clases por día de un docente');

-- Roles de partida; todos editables salvo el administrador (de sistema).
INSERT INTO identidad_rol (codigo, nombre, descripcion, es_sistema) VALUES
  ('administrador',     'Administrador',       'Ve y hace todo, en todos los departamentos', 1),
  ('encargado_docente', 'Encargado Docente',   'Administra los datos y horarios de su departamento', 0),
  ('consulta',          'Usuario de consulta', 'Jefes de Carrera y APA: horarios aprobados y ocupación de salas, sin datos personales ni financieros', 0),
  ('modulo_satelite',   'Módulo satélite',     'Credencial de un módulo de Proyecto Integrador: lectura según contrato', 0);

INSERT INTO identidad_permiso (codigo, descripcion) VALUES
  ('horarios.ver',                   'Ver propuestas y horarios'),
  ('horarios.editar',                'Editar borradores y mover clases a mano'),
  ('horarios.generar',               'Lanzar corridas de FET'),
  ('horarios.aprobar',               'Aprobar la versión definitiva de un periodo'),
  ('horarios.exportar',              'Exportar el horario a la planilla'),
  ('horarios.enviar',                'Enviar el horario a los docentes por correo'),
  ('catalogo.ver',                   'Ver datos maestros'),
  ('catalogo.editar',                'Crear y editar datos maestros'),
  ('catalogo.importar',              'Importar la planilla del periodo'),
  ('personas.ver_datos_personales',  'Ver RUT y correo de docentes y ayudantes'),
  ('restricciones.ver',              'Ver el catálogo de restricciones'),
  ('restricciones.gestionar',        'Crear, editar y eliminar restricciones'),
  ('finanzas.ver',                   'Ver costos y presupuesto'),
  ('finanzas.editar',                'Editar tarifas, presupuestos y nombramientos'),
  ('proyeccion.ver',                 'Ver proyecciones'),
  ('departamentos.gestionar',        'Crear, editar y desactivar departamentos'),
  ('departamentos.ver_otros',        'Leer datos de otros departamentos'),
  ('usuarios.gestionar',             'Gestionar usuarios, roles, permisos y credenciales de módulos');

INSERT INTO identidad_rol_permiso (rol, permiso)
SELECT 'administrador', codigo FROM identidad_permiso
UNION ALL
SELECT 'encargado_docente', codigo FROM identidad_permiso
 WHERE codigo NOT IN ('departamentos.gestionar', 'departamentos.ver_otros', 'usuarios.gestionar')
UNION ALL
SELECT 'consulta', codigo FROM identidad_permiso
 WHERE codigo IN ('horarios.ver', 'catalogo.ver', 'restricciones.ver')
UNION ALL
SELECT 'modulo_satelite', codigo FROM identidad_permiso
 WHERE codigo IN ('horarios.ver', 'catalogo.ver');

-- Los usuarios se crean en Directus con su rol y departamento; el configurador crea al Encargado Docente.

INSERT INTO plataforma_modulo (codigo, nombre) VALUES
  ('g1', 'ARGOS y gestión docente'),
  ('g2', 'Profesores'),
  ('g3', 'Asignaturas'),
  ('g4', 'Ayudantes');

"""

PUBLICACION = """
-- ---------------------------------------------------------------------
-- 6b. Publicación para los módulos de Proyecto Integrador
-- ---------------------------------------------------------------------
-- Viven en el mismo archivo y el mismo Directus que el núcleo, pero separadas por permisos: cada grupo (g1 a g4) tiene un
-- rol y un token que solo leen pub_* y solo escriben en su propia sat_<grupo>_registro. pub_* es una copia derivada que
-- regenera la API (python -m app.publicacion): sin personas, docentes, nombramientos, finanzas ni auditoría.
CREATE TABLE pub_periodo (id INTEGER PRIMARY KEY, codigo TEXT NOT NULL, estado TEXT NOT NULL) STRICT;
CREATE TABLE pub_programa (id INTEGER PRIMARY KEY, codigo TEXT NOT NULL, nombre TEXT, tipo TEXT) STRICT;
CREATE TABLE pub_asignatura (id INTEGER PRIMARY KEY, codigo TEXT, nombre TEXT NOT NULL, area TEXT,
                             requiere_laboratorio INTEGER NOT NULL) STRICT;
CREATE TABLE pub_sala (id INTEGER PRIMARY KEY, codigo TEXT NOT NULL, nombre TEXT, capacidad INTEGER,
                       es_laboratorio INTEGER NOT NULL) STRICT;
CREATE TABLE pub_paralelo (id INTEGER PRIMARY KEY, periodo_id INTEGER NOT NULL, asignatura_id INTEGER NOT NULL,
                           codigo TEXT NOT NULL, nrc INTEGER, componente TEXT, cupo_estimado INTEGER) STRICT;
CREATE TABLE pub_horario (id INTEGER PRIMARY KEY, paralelo_id INTEGER NOT NULL, sesion INTEGER NOT NULL,
                          dia TEXT NOT NULL, bloque TEXT NOT NULL, sala_codigo TEXT) STRICT;
CREATE TABLE pub_estado (id INTEGER PRIMARY KEY CHECK (id = 1), publicado_en TEXT NOT NULL) STRICT;
"""
SATELITES = ("g1", "g2", "g3", "g4")
REGISTRO_SATELITE = """CREATE TABLE sat_{g}_registro (
  id          INTEGER PRIMARY KEY,
  clave       TEXT NOT NULL,
  valor       TEXT CHECK (valor IS NULL OR json_valid(valor)),
  creado_en   @TS@,
  eliminado_en TEXT
) STRICT;"""
PUBLICACION += "\n".join(REGISTRO_SATELITE.format(g=g) for g in SATELITES) + "\n"

# Tablas con DELETE permitido (datos derivados de un borrador) y tablas con borrado lógico
BORRABLES = {"horarios_asignacion", "horarios_hallazgo", "horarios_corrida_actividad"}
SIN_BORRADO = [  # todas las tablas de negocio menos las borrables y la auditoría (que tiene su propio trigger)
    "identidad_departamento", "identidad_usuario", "identidad_rol", "identidad_permiso", "identidad_rol_permiso",
    "plataforma_importacion", "plataforma_fila_importada", "plataforma_modulo",
    "catalogo_periodo", "catalogo_programa", "catalogo_asignatura", "catalogo_plan_nivel", "catalogo_dia",
    "catalogo_bloque", "catalogo_sala", "catalogo_persona", "catalogo_docente", "catalogo_ayudante",
    "horarios_liga", "horarios_paralelo", "horarios_paralelo_docente", "horarios_paralelo_grupo", "horarios_sesion",
    "horarios_disponibilidad_docente", "horarios_bloqueo_sala", "horarios_sala_externa_autorizada",
    "horarios_reserva_nivel", "horarios_perfil", "horarios_restriccion", "horarios_propuesta", "horarios_corrida",
    "horarios_envio_horario", "finanzas_categoria", "finanzas_escenario", "finanzas_tarifa", "finanzas_presupuesto",
    "finanzas_categoria_persona", "finanzas_nombramiento", "finanzas_calculo", "finanzas_calculo_detalle",
    "proyeccion_inscripcion_historica", "proyeccion_estimacion_externa", "proyeccion_estimacion",
] + [f"sat_{g}_registro" for g in ("g1", "g2", "g3", "g4")]


def triggers_borrado():
    out = ["-- ---------------------------------------------------------------------",
           "-- 8. Borrado lógico (generado por db/generar_esquema.py)",
           "-- ---------------------------------------------------------------------",
           "-- Nada se elimina de forma efectiva: el DELETE se rechaza (use eliminado_en)."]
    for t in SIN_BORRADO:
        out.append(f"CREATE TRIGGER sin_borrado_{t} BEFORE DELETE ON {t}\n"
                   f"BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en {t}'); END;")
    out.append("")
    return "\n".join(out)


def main():
    ddl = IDENTIDAD + PLATAFORMA + CATALOGO + HORARIOS + FINANZAS + PROYECCION + PUBLICACION
    cuerpo = ddl.replace("@TS@", TS).replace("@SD@,", SD + ",").replace("@SD@", SD)
    sys.stdout.write(CABECERA + cuerpo + DATOS + triggers_borrado() + "\nCOMMIT;\n")


main()
