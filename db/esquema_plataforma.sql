-- =====================================================================
-- Plataforma DISC · estructura de la base de datos (SQLite 3.44 o superior)
--
-- Una sola base, plataforma.db. SQLite no tiene esquemas: el módulo va en el prefijo.
--   identidad_    departamentos, usuarios, roles y permisos (RBAC con alcance por departamento)
--   catalogo_     datos maestros: periodos, programas, asignaturas, salas,
--                 bloques, personas, docentes y ayudantes
--   horarios_     oferta del periodo (paralelos), reglas, corridas de FET y propuestas
--   finanzas_     categorías, valor hora, presupuestos y nombramientos
--   proyeccion_   inscritos históricos y estimaciones
--   plataforma_   importaciones, módulos habilitados, contexto de sesión y auditoría
-- Módulos de los grupos (g1 a g4): cada uno tiene su propio archivo SQLite (g1.db ...);
-- el módulo base no los adjunta ni hay FK entre ellos: se hablan por la interfaz de integración.
--
-- Cómo se conecta la aplicación (una vez por conexión):
--   PRAGMA foreign_keys = ON;   PRAGMA journal_mode = WAL;   PRAGMA busy_timeout = 5000;
-- Cómo escribe (SQLite admite un solo escritor, así que el contexto es seguro):
--   BEGIN IMMEDIATE;
--   UPDATE plataforma_contexto SET usuario_id = <id de la persona usuaria>;
--   ... cambios ...
--   UPDATE plataforma_contexto SET usuario_id = NULL;
--   COMMIT;
-- Con usuario_id fijado, los triggers comprueban permisos y la auditoría registra quién.
-- Sin usuario (migraciones, worker de corridas) no se comprueba permiso.
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
--     La vista identidad_permiso_efectivo dice qué permiso tiene cada usuario y dónde
--     (departamento_id nulo = todos). Un departamento no edita los horarios de otro.
--   * borrado lógico: nada se elimina de forma efectiva. Las tablas mantenidas por
--     usuarios tienen eliminado_en/eliminado_por y un trigger impide el DELETE
--     (salvo datos derivados de un borrador: asignaciones, hallazgos y actividades de FET).
--   * auditoría: plataforma_auditoria registra quién, cuándo, qué elemento y qué cambió
--     (solo los campos que cambiaron). Es de solo inserción y se conserva 5 años;
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

-- ---------------------------------------------------------------------
-- 1. identidad
-- ---------------------------------------------------------------------
CREATE TABLE identidad_departamento (
  id              INTEGER PRIMARY KEY,
  codigo          TEXT NOT NULL UNIQUE CHECK (codigo = upper(codigo)),     -- DISC
  nombre          TEXT NOT NULL,
  predeterminado  INTEGER NOT NULL DEFAULT 0 CHECK (predeterminado IN (0, 1)),   -- el DISC: id 1, no se elimina
  activo          INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
  creado_en       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  eliminado_en TEXT,
  eliminado_por INTEGER REFERENCES identidad_usuario
) STRICT;
CREATE UNIQUE INDEX departamento_predeterminado_uk ON identidad_departamento (predeterminado) WHERE predeterminado = 1;

-- Personas y credenciales de módulos satélite: tipo 'modulo' (email técnico, p. ej. g2@modulos.local).
CREATE TABLE identidad_usuario (
  id            INTEGER PRIMARY KEY,
  email         TEXT NOT NULL UNIQUE CHECK (email = lower(email)),
  nombre        TEXT NOT NULL,
  tipo          TEXT NOT NULL DEFAULT 'persona' CHECK (tipo IN ('persona', 'modulo')),
  hash_clave    TEXT,                                -- argon2id; nulo si entra con el inicio de sesión institucional
  intentos_fallidos  INTEGER NOT NULL DEFAULT 0 CHECK (intentos_fallidos >= 0),   -- consecutivos; vuelve a 0 al entrar
  bloqueado_hasta    TEXT,                             -- bloqueo temporal por intentos fallidos
  ultimo_acceso_en   TEXT,
  activo        INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
  creado_en     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  eliminado_en TEXT,
  eliminado_por INTEGER REFERENCES identidad_usuario
) STRICT;

-- Roles editables. El rol de sistema (administrador) no se desactiva ni se elimina.
CREATE TABLE identidad_rol (
  codigo       TEXT PRIMARY KEY,                     -- administrador, encargado_docente, consulta, modulo_satelite, ...
  nombre       TEXT NOT NULL,
  descripcion  TEXT,
  es_sistema   INTEGER NOT NULL DEFAULT 0 CHECK (es_sistema IN (0, 1)),
  activo       INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
  eliminado_en TEXT,
  eliminado_por INTEGER REFERENCES identidad_usuario
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

-- Un rol se asigna dentro de un departamento. departamento_id nulo = todos los departamentos.
CREATE TABLE identidad_usuario_rol (
  id               INTEGER PRIMARY KEY,
  usuario_id       INTEGER NOT NULL REFERENCES identidad_usuario,
  rol              TEXT NOT NULL REFERENCES identidad_rol,
  departamento_id  INTEGER REFERENCES identidad_departamento,
  asignado_por     INTEGER REFERENCES identidad_usuario,
  asignado_en      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  revocado_en      TEXT
) STRICT;
CREATE UNIQUE INDEX usuario_rol_vigente_uk
  ON identidad_usuario_rol (usuario_id, rol, COALESCE(departamento_id, 0))
  WHERE revocado_en IS NULL;

-- Sesiones de la API: solo se guarda el hash del refresh token (rotativo). 'familia' agrupa los tokens
-- encadenados de un mismo inicio de sesión; reutilizar uno ya usado revoca toda la familia.
CREATE TABLE identidad_sesion (
  id           INTEGER PRIMARY KEY,
  usuario_id   INTEGER NOT NULL REFERENCES identidad_usuario,
  familia      TEXT NOT NULL,
  token_hash   TEXT NOT NULL UNIQUE CHECK (length(token_hash) = 64),
  creada_en    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  expira_en    TEXT NOT NULL,
  usado_en     TEXT,
  revocada_en  TEXT,
  ip           TEXT
) STRICT;
CREATE INDEX sesion_usuario_ix ON identidad_sesion (usuario_id, revocada_en);
CREATE INDEX sesion_familia_ix ON identidad_sesion (familia);

-- Qué puede hacer cada usuario y dónde. departamento_id nulo = en todos los departamentos.
CREATE VIEW identidad_permiso_efectivo AS
SELECT ur.usuario_id, ur.departamento_id, rp.permiso
FROM identidad_usuario_rol ur
JOIN identidad_usuario u      ON u.id = ur.usuario_id AND u.activo = 1 AND u.eliminado_en IS NULL
JOIN identidad_rol r          ON r.codigo = ur.rol AND r.activo = 1 AND r.eliminado_en IS NULL
JOIN identidad_rol_permiso rp ON rp.rol = r.codigo AND rp.revocado_en IS NULL
WHERE ur.revocado_en IS NULL;

CREATE TRIGGER departamento_protegido BEFORE UPDATE ON identidad_departamento
WHEN OLD.predeterminado = 1 AND (NEW.predeterminado = 0 OR NEW.activo = 0 OR NEW.eliminado_en IS NOT NULL)
BEGIN SELECT RAISE(ABORT, 'El departamento predeterminado no se puede desactivar ni eliminar'); END;

CREATE TRIGGER rol_protegido BEFORE UPDATE ON identidad_rol
WHEN OLD.es_sistema = 1 AND (NEW.es_sistema = 0 OR NEW.activo = 0 OR NEW.eliminado_en IS NOT NULL)
BEGIN SELECT RAISE(ABORT, 'El rol de sistema no se desactiva ni se elimina'); END;

-- Nadie modifica sus propios roles; gestionar los de otros exige usuarios.gestionar en ese departamento.
CREATE TRIGGER usuario_rol_propio_i BEFORE INSERT ON identidad_usuario_rol
WHEN (SELECT usuario_id FROM plataforma_contexto) IS NOT NULL AND NEW.usuario_id = (SELECT usuario_id FROM plataforma_contexto)
BEGIN SELECT RAISE(ABORT, 'Nadie puede modificar sus propios roles'); END;
CREATE TRIGGER usuario_rol_propio_u BEFORE UPDATE ON identidad_usuario_rol
WHEN (SELECT usuario_id FROM plataforma_contexto) IS NOT NULL AND NEW.usuario_id = (SELECT usuario_id FROM plataforma_contexto)
BEGIN SELECT RAISE(ABORT, 'Nadie puede modificar sus propios roles'); END;
CREATE TRIGGER usuario_rol_permiso_i BEFORE INSERT ON identidad_usuario_rol
WHEN (SELECT usuario_id FROM plataforma_contexto) IS NOT NULL AND NOT EXISTS (SELECT 1 FROM identidad_permiso_efectivo pe WHERE pe.usuario_id = (SELECT usuario_id FROM plataforma_contexto) AND pe.permiso = 'usuarios.gestionar' AND (pe.departamento_id IS NULL OR pe.departamento_id = NEW.departamento_id))
BEGIN SELECT RAISE(ABORT, 'Sin permiso para gestionar usuarios en ese departamento'); END;
CREATE TRIGGER usuario_rol_permiso_u BEFORE UPDATE ON identidad_usuario_rol
WHEN (SELECT usuario_id FROM plataforma_contexto) IS NOT NULL AND NOT EXISTS (SELECT 1 FROM identidad_permiso_efectivo pe WHERE pe.usuario_id = (SELECT usuario_id FROM plataforma_contexto) AND pe.permiso = 'usuarios.gestionar' AND (pe.departamento_id IS NULL OR pe.departamento_id = NEW.departamento_id))
BEGIN SELECT RAISE(ABORT, 'Sin permiso para gestionar usuarios en ese departamento'); END;

-- ---------------------------------------------------------------------
-- 2. plataforma (importaciones, módulos, contexto y auditoría)
-- ---------------------------------------------------------------------
-- Una fila: la persona que escribe en esta transacción (ver la cabecera).
CREATE TABLE plataforma_contexto (
  id          INTEGER PRIMARY KEY CHECK (id = 1),
  usuario_id  INTEGER REFERENCES identidad_usuario,
  ip          TEXT                                -- origen de la petición; lo fija la aplicación junto al usuario
) STRICT;
INSERT INTO plataforma_contexto (id, usuario_id, ip) VALUES (1, NULL, NULL);

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
  creada_en           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
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

-- Auditoría: solo inserción, 5 años. Cada fila dice quién, cuándo, sobre qué elemento y qué cambió
-- (antes y después de los campos que cambiaron). Los triggers 'auditar_*' están al final del archivo.
CREATE TABLE plataforma_auditoria (
  id               INTEGER PRIMARY KEY,
  en               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  usuario_id       INTEGER REFERENCES identidad_usuario,
  departamento_id  INTEGER REFERENCES identidad_departamento,
  ip               TEXT,                          -- dirección de origen de la petición
  accion           TEXT NOT NULL,                 -- insert, update, delete o una acción de negocio: acceso_denegado, ...
  resultado        TEXT NOT NULL DEFAULT 'ok' CHECK (resultado IN ('ok', 'denegado', 'error')),
  entidad          TEXT NOT NULL,
  entidad_id       TEXT,
  antes            TEXT CHECK (antes IS NULL OR json_valid(antes)),
  despues          TEXT CHECK (despues IS NULL OR json_valid(despues))
) STRICT;
CREATE INDEX auditoria_entidad_ix ON plataforma_auditoria (entidad, entidad_id);
CREATE INDEX auditoria_usuario_ix ON plataforma_auditoria (usuario_id, en);
CREATE INDEX auditoria_en_ix ON plataforma_auditoria (en);

-- Cambios en datos que nadie firmó: la API siempre fija el usuario; si aparece una fila aquí, alguien escribió por fuera
-- (p. ej. el administrador de arranque de Directus, que no fija plataforma_contexto). 'seed' marca la carga inicial.
CREATE VIEW plataforma_v_cambios_sin_usuario AS
SELECT id, en, accion, entidad, entidad_id, ip FROM plataforma_auditoria
WHERE usuario_id IS NULL AND accion IN ('insert', 'update', 'delete') AND COALESCE(ip, '') <> 'seed';

CREATE TRIGGER auditoria_inmutable BEFORE UPDATE ON plataforma_auditoria
BEGIN SELECT RAISE(ABORT, 'La auditoría es de solo inserción'); END;
CREATE TRIGGER auditoria_retencion BEFORE DELETE ON plataforma_auditoria
WHEN OLD.en > strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-5 years')
BEGIN SELECT RAISE(ABORT, 'La auditoría se conserva durante 5 años'); END;

-- ---------------------------------------------------------------------
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
  eliminado_en TEXT,
  eliminado_por INTEGER REFERENCES identidad_usuario,
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
  eliminado_en TEXT,
  eliminado_por INTEGER REFERENCES identidad_usuario
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
  eliminado_en TEXT,
  eliminado_por INTEGER REFERENCES identidad_usuario
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
  eliminado_en TEXT,
  eliminado_por INTEGER REFERENCES identidad_usuario
) STRICT;

CREATE TABLE catalogo_docente (
  persona_id       INTEGER PRIMARY KEY REFERENCES catalogo_persona,
  departamento_id  INTEGER NOT NULL DEFAULT 1 REFERENCES identidad_departamento,
  tipo_contrato    TEXT NOT NULL CHECK (tipo_contrato IN ('planta', 'hora')),
  activo           INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
  eliminado_en TEXT,
  eliminado_por INTEGER REFERENCES identidad_usuario
) STRICT;

CREATE TABLE catalogo_ayudante (
  persona_id       INTEGER PRIMARY KEY REFERENCES catalogo_persona,
  departamento_id  INTEGER NOT NULL DEFAULT 1 REFERENCES identidad_departamento,
  activo           INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
  eliminado_en TEXT,
  eliminado_por INTEGER REFERENCES identidad_usuario
) STRICT;

-- ---------------------------------------------------------------------
-- 4. horarios
-- ---------------------------------------------------------------------
CREATE TABLE horarios_liga (
  id          INTEGER PRIMARY KEY,
  periodo_id  INTEGER NOT NULL REFERENCES catalogo_periodo,
  codigo      TEXT NOT NULL,                      -- ASYS, CYBR, L01, ...
  eliminado_en TEXT,
  eliminado_por INTEGER REFERENCES identidad_usuario,
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
  eliminado_en TEXT,
  eliminado_por INTEGER REFERENCES identidad_usuario
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
  eliminado_en TEXT,
  eliminado_por INTEGER REFERENCES identidad_usuario,
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
  aprobada_en   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
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
  eliminado_en TEXT,
  eliminado_por INTEGER REFERENCES identidad_usuario
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
  creada_en        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  actualizada_en   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  eliminado_en TEXT,
  eliminado_por INTEGER REFERENCES identidad_usuario,
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
  creada_en   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
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
  creada_en          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
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
  creado_en     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
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

-- Solo una propuesta en borrador se edita; una aprobada o reemplazada se copia.
-- Si hay usuario en el contexto, además exige horarios.editar en el departamento del período:
-- un departamento no edita los horarios de otro. Un cambio hecho por una persona queda como 'manual'.
CREATE TRIGGER asignacion_borrador_i BEFORE INSERT ON horarios_asignacion
WHEN (SELECT estado FROM horarios_propuesta WHERE id = NEW.propuesta_id) <> 'borrador'
BEGIN SELECT RAISE(ABORT, 'La propuesta no está en borrador: cópiela para editarla'); END;
CREATE TRIGGER asignacion_borrador_u BEFORE UPDATE ON horarios_asignacion
WHEN (SELECT estado FROM horarios_propuesta WHERE id = OLD.propuesta_id) <> 'borrador'
BEGIN SELECT RAISE(ABORT, 'La propuesta no está en borrador: cópiela para editarla'); END;
CREATE TRIGGER asignacion_borrador_d BEFORE DELETE ON horarios_asignacion
WHEN (SELECT estado FROM horarios_propuesta WHERE id = OLD.propuesta_id) <> 'borrador'
BEGIN SELECT RAISE(ABORT, 'La propuesta no está en borrador: cópiela para editarla'); END;
CREATE TRIGGER asignacion_permiso_i BEFORE INSERT ON horarios_asignacion
WHEN (SELECT usuario_id FROM plataforma_contexto) IS NOT NULL AND NOT EXISTS (SELECT 1 FROM identidad_permiso_efectivo pe WHERE pe.usuario_id = (SELECT usuario_id FROM plataforma_contexto) AND pe.permiso = 'horarios.editar' AND (pe.departamento_id IS NULL OR pe.departamento_id = (SELECT pe.departamento_id FROM horarios_propuesta p JOIN catalogo_periodo pe ON pe.id = p.periodo_id WHERE p.id = NEW.propuesta_id)))
BEGIN SELECT RAISE(ABORT, 'Sin permiso para editar horarios de este departamento'); END;
CREATE TRIGGER asignacion_permiso_u BEFORE UPDATE ON horarios_asignacion
WHEN (SELECT usuario_id FROM plataforma_contexto) IS NOT NULL AND NOT EXISTS (SELECT 1 FROM identidad_permiso_efectivo pe WHERE pe.usuario_id = (SELECT usuario_id FROM plataforma_contexto) AND pe.permiso = 'horarios.editar' AND (pe.departamento_id IS NULL OR pe.departamento_id = (SELECT pe.departamento_id FROM horarios_propuesta p JOIN catalogo_periodo pe ON pe.id = p.periodo_id WHERE p.id = OLD.propuesta_id)))
BEGIN SELECT RAISE(ABORT, 'Sin permiso para editar horarios de este departamento'); END;
CREATE TRIGGER asignacion_permiso_d BEFORE DELETE ON horarios_asignacion
WHEN (SELECT usuario_id FROM plataforma_contexto) IS NOT NULL AND NOT EXISTS (SELECT 1 FROM identidad_permiso_efectivo pe WHERE pe.usuario_id = (SELECT usuario_id FROM plataforma_contexto) AND pe.permiso = 'horarios.editar' AND (pe.departamento_id IS NULL OR pe.departamento_id = (SELECT pe.departamento_id FROM horarios_propuesta p JOIN catalogo_periodo pe ON pe.id = p.periodo_id WHERE p.id = OLD.propuesta_id)))
BEGIN SELECT RAISE(ABORT, 'Sin permiso para editar horarios de este departamento'); END;
CREATE TRIGGER asignacion_manual_i AFTER INSERT ON horarios_asignacion
WHEN (SELECT usuario_id FROM plataforma_contexto) IS NOT NULL
BEGIN
  UPDATE horarios_asignacion SET origen = 'manual', modificada_por = (SELECT usuario_id FROM plataforma_contexto), modificada_en = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
  WHERE propuesta_id = NEW.propuesta_id AND sesion_id = NEW.sesion_id;
END;
CREATE TRIGGER asignacion_manual_u AFTER UPDATE ON horarios_asignacion
WHEN (SELECT usuario_id FROM plataforma_contexto) IS NOT NULL AND (OLD.dia IS NOT NEW.dia OR OLD.bloque IS NOT NEW.bloque OR OLD.sala_id IS NOT NEW.sala_id)
BEGIN
  UPDATE horarios_asignacion SET origen = 'manual', modificada_por = (SELECT usuario_id FROM plataforma_contexto), modificada_en = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
  WHERE propuesta_id = NEW.propuesta_id AND sesion_id = NEW.sesion_id;
END;

-- Aprobar: solo un borrador completo y sin violaciones duras, por quien tiene horarios.aprobar.
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
CREATE TRIGGER propuesta_permiso BEFORE UPDATE OF estado ON horarios_propuesta
WHEN NEW.estado = 'aprobada' AND OLD.estado <> 'aprobada' AND (SELECT usuario_id FROM plataforma_contexto) IS NOT NULL AND NOT EXISTS (SELECT 1 FROM identidad_permiso_efectivo pe WHERE pe.usuario_id = (SELECT usuario_id FROM plataforma_contexto) AND pe.permiso = 'horarios.aprobar' AND (pe.departamento_id IS NULL OR pe.departamento_id = (SELECT departamento_id FROM catalogo_periodo WHERE id = NEW.periodo_id)))
BEGIN SELECT RAISE(ABORT, 'Sin permiso para aprobar horarios de este departamento'); END;
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
  UPDATE horarios_propuesta SET aprobada_por = (SELECT usuario_id FROM plataforma_contexto), aprobada_en = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = NEW.id;
END;

-- Crear, editar o eliminar restricciones exige restricciones.gestionar en el departamento.
-- Una usada por un horario aprobado se desactiva, no se elimina.
CREATE TRIGGER restriccion_permiso_i BEFORE INSERT ON horarios_restriccion
WHEN (SELECT usuario_id FROM plataforma_contexto) IS NOT NULL AND NOT EXISTS (SELECT 1 FROM identidad_permiso_efectivo pe WHERE pe.usuario_id = (SELECT usuario_id FROM plataforma_contexto) AND pe.permiso = 'restricciones.gestionar' AND (pe.departamento_id IS NULL OR pe.departamento_id = NEW.departamento_id))
BEGIN SELECT RAISE(ABORT, 'Sin permiso para gestionar restricciones de este departamento'); END;
CREATE TRIGGER restriccion_permiso_u BEFORE UPDATE ON horarios_restriccion
WHEN (SELECT usuario_id FROM plataforma_contexto) IS NOT NULL AND NOT EXISTS (SELECT 1 FROM identidad_permiso_efectivo pe WHERE pe.usuario_id = (SELECT usuario_id FROM plataforma_contexto) AND pe.permiso = 'restricciones.gestionar' AND (pe.departamento_id IS NULL OR pe.departamento_id = NEW.departamento_id))
BEGIN SELECT RAISE(ABORT, 'Sin permiso para gestionar restricciones de este departamento'); END;
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

-- ---------------------------------------------------------------------
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
  creado_en        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  eliminado_en TEXT,
  eliminado_por INTEGER REFERENCES identidad_usuario,
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
  eliminado_en TEXT,
  eliminado_por INTEGER REFERENCES identidad_usuario
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
  eliminado_en TEXT,
  eliminado_por INTEGER REFERENCES identidad_usuario
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
  creado_en        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
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
  calculado_en     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
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

-- ---------------------------------------------------------------------
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
  calculada_en   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  CHECK (minimo <= moda AND moda <= maximo)
) STRICT;
CREATE INDEX estimacion_periodo_ix ON proyeccion_estimacion (periodo_id, asignatura_id);

-- ---------------------------------------------------------------------
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

-- El primer usuario administrador se crea en el despliegue (usuario_rol con departamento_id nulo).

INSERT INTO plataforma_modulo (codigo, nombre) VALUES
  ('g1', 'ARGOS y gestión docente'),
  ('g2', 'Profesores'),
  ('g3', 'Asignaturas'),
  ('g4', 'Ayudantes');

-- ---------------------------------------------------------------------
-- 8. Auditoría de cambios y borrado lógico (generados por bd/generar_esquema.py)
-- ---------------------------------------------------------------------
CREATE TRIGGER auditar_identidad_departamento_i AFTER INSERT ON identidad_departamento
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'insert', 'identidad_departamento', NEW.id, json_object('id', NEW.id, 'codigo', NEW.codigo, 'nombre', NEW.nombre, 'predeterminado', NEW.predeterminado, 'activo', NEW.activo, 'creado_en', NEW.creado_en, 'eliminado_en', NEW.eliminado_en, 'eliminado_por', NEW.eliminado_por));
END;
CREATE TRIGGER auditar_identidad_departamento_u AFTER UPDATE ON identidad_departamento
WHEN OLD.id IS NOT NEW.id OR OLD.codigo IS NOT NEW.codigo OR OLD.nombre IS NOT NEW.nombre OR OLD.predeterminado IS NOT NEW.predeterminado OR OLD.activo IS NOT NEW.activo OR OLD.creado_en IS NOT NEW.creado_en OR OLD.eliminado_en IS NOT NEW.eliminado_en OR OLD.eliminado_por IS NOT NEW.eliminado_por
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'update', 'identidad_departamento', NEW.id,
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, OLD.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'codigo' AS k, OLD.codigo AS v WHERE OLD.codigo IS NOT NEW.codigo UNION ALL SELECT 'nombre' AS k, OLD.nombre AS v WHERE OLD.nombre IS NOT NEW.nombre UNION ALL SELECT 'predeterminado' AS k, OLD.predeterminado AS v WHERE OLD.predeterminado IS NOT NEW.predeterminado UNION ALL SELECT 'activo' AS k, OLD.activo AS v WHERE OLD.activo IS NOT NEW.activo UNION ALL SELECT 'creado_en' AS k, OLD.creado_en AS v WHERE OLD.creado_en IS NOT NEW.creado_en UNION ALL SELECT 'eliminado_en' AS k, OLD.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, OLD.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)),
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, NEW.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'codigo' AS k, NEW.codigo AS v WHERE OLD.codigo IS NOT NEW.codigo UNION ALL SELECT 'nombre' AS k, NEW.nombre AS v WHERE OLD.nombre IS NOT NEW.nombre UNION ALL SELECT 'predeterminado' AS k, NEW.predeterminado AS v WHERE OLD.predeterminado IS NOT NEW.predeterminado UNION ALL SELECT 'activo' AS k, NEW.activo AS v WHERE OLD.activo IS NOT NEW.activo UNION ALL SELECT 'creado_en' AS k, NEW.creado_en AS v WHERE OLD.creado_en IS NOT NEW.creado_en UNION ALL SELECT 'eliminado_en' AS k, NEW.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, NEW.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)));
END;
CREATE TRIGGER auditar_identidad_departamento_d AFTER DELETE ON identidad_departamento
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'delete', 'identidad_departamento', OLD.id, json_object('id', OLD.id, 'codigo', OLD.codigo, 'nombre', OLD.nombre, 'predeterminado', OLD.predeterminado, 'activo', OLD.activo, 'creado_en', OLD.creado_en, 'eliminado_en', OLD.eliminado_en, 'eliminado_por', OLD.eliminado_por));
END;

CREATE TRIGGER auditar_identidad_usuario_i AFTER INSERT ON identidad_usuario
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'insert', 'identidad_usuario', NEW.id, json_object('id', NEW.id, 'email', NEW.email, 'nombre', NEW.nombre, 'tipo', NEW.tipo, 'activo', NEW.activo, 'creado_en', NEW.creado_en, 'eliminado_en', NEW.eliminado_en, 'eliminado_por', NEW.eliminado_por));
END;
CREATE TRIGGER auditar_identidad_usuario_u AFTER UPDATE ON identidad_usuario
WHEN OLD.id IS NOT NEW.id OR OLD.email IS NOT NEW.email OR OLD.nombre IS NOT NEW.nombre OR OLD.tipo IS NOT NEW.tipo OR OLD.activo IS NOT NEW.activo OR OLD.creado_en IS NOT NEW.creado_en OR OLD.eliminado_en IS NOT NEW.eliminado_en OR OLD.eliminado_por IS NOT NEW.eliminado_por
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'update', 'identidad_usuario', NEW.id,
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, OLD.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'email' AS k, OLD.email AS v WHERE OLD.email IS NOT NEW.email UNION ALL SELECT 'nombre' AS k, OLD.nombre AS v WHERE OLD.nombre IS NOT NEW.nombre UNION ALL SELECT 'tipo' AS k, OLD.tipo AS v WHERE OLD.tipo IS NOT NEW.tipo UNION ALL SELECT 'activo' AS k, OLD.activo AS v WHERE OLD.activo IS NOT NEW.activo UNION ALL SELECT 'creado_en' AS k, OLD.creado_en AS v WHERE OLD.creado_en IS NOT NEW.creado_en UNION ALL SELECT 'eliminado_en' AS k, OLD.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, OLD.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)),
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, NEW.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'email' AS k, NEW.email AS v WHERE OLD.email IS NOT NEW.email UNION ALL SELECT 'nombre' AS k, NEW.nombre AS v WHERE OLD.nombre IS NOT NEW.nombre UNION ALL SELECT 'tipo' AS k, NEW.tipo AS v WHERE OLD.tipo IS NOT NEW.tipo UNION ALL SELECT 'activo' AS k, NEW.activo AS v WHERE OLD.activo IS NOT NEW.activo UNION ALL SELECT 'creado_en' AS k, NEW.creado_en AS v WHERE OLD.creado_en IS NOT NEW.creado_en UNION ALL SELECT 'eliminado_en' AS k, NEW.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, NEW.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)));
END;
CREATE TRIGGER auditar_identidad_usuario_d AFTER DELETE ON identidad_usuario
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'delete', 'identidad_usuario', OLD.id, json_object('id', OLD.id, 'email', OLD.email, 'nombre', OLD.nombre, 'tipo', OLD.tipo, 'activo', OLD.activo, 'creado_en', OLD.creado_en, 'eliminado_en', OLD.eliminado_en, 'eliminado_por', OLD.eliminado_por));
END;

CREATE TRIGGER auditar_identidad_rol_i AFTER INSERT ON identidad_rol
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'insert', 'identidad_rol', NEW.codigo, json_object('codigo', NEW.codigo, 'nombre', NEW.nombre, 'descripcion', NEW.descripcion, 'es_sistema', NEW.es_sistema, 'activo', NEW.activo, 'eliminado_en', NEW.eliminado_en, 'eliminado_por', NEW.eliminado_por));
END;
CREATE TRIGGER auditar_identidad_rol_u AFTER UPDATE ON identidad_rol
WHEN OLD.codigo IS NOT NEW.codigo OR OLD.nombre IS NOT NEW.nombre OR OLD.descripcion IS NOT NEW.descripcion OR OLD.es_sistema IS NOT NEW.es_sistema OR OLD.activo IS NOT NEW.activo OR OLD.eliminado_en IS NOT NEW.eliminado_en OR OLD.eliminado_por IS NOT NEW.eliminado_por
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'update', 'identidad_rol', NEW.codigo,
          (SELECT json_group_object(k, v) FROM (SELECT 'codigo' AS k, OLD.codigo AS v WHERE OLD.codigo IS NOT NEW.codigo UNION ALL SELECT 'nombre' AS k, OLD.nombre AS v WHERE OLD.nombre IS NOT NEW.nombre UNION ALL SELECT 'descripcion' AS k, OLD.descripcion AS v WHERE OLD.descripcion IS NOT NEW.descripcion UNION ALL SELECT 'es_sistema' AS k, OLD.es_sistema AS v WHERE OLD.es_sistema IS NOT NEW.es_sistema UNION ALL SELECT 'activo' AS k, OLD.activo AS v WHERE OLD.activo IS NOT NEW.activo UNION ALL SELECT 'eliminado_en' AS k, OLD.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, OLD.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)),
          (SELECT json_group_object(k, v) FROM (SELECT 'codigo' AS k, NEW.codigo AS v WHERE OLD.codigo IS NOT NEW.codigo UNION ALL SELECT 'nombre' AS k, NEW.nombre AS v WHERE OLD.nombre IS NOT NEW.nombre UNION ALL SELECT 'descripcion' AS k, NEW.descripcion AS v WHERE OLD.descripcion IS NOT NEW.descripcion UNION ALL SELECT 'es_sistema' AS k, NEW.es_sistema AS v WHERE OLD.es_sistema IS NOT NEW.es_sistema UNION ALL SELECT 'activo' AS k, NEW.activo AS v WHERE OLD.activo IS NOT NEW.activo UNION ALL SELECT 'eliminado_en' AS k, NEW.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, NEW.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)));
END;
CREATE TRIGGER auditar_identidad_rol_d AFTER DELETE ON identidad_rol
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'delete', 'identidad_rol', OLD.codigo, json_object('codigo', OLD.codigo, 'nombre', OLD.nombre, 'descripcion', OLD.descripcion, 'es_sistema', OLD.es_sistema, 'activo', OLD.activo, 'eliminado_en', OLD.eliminado_en, 'eliminado_por', OLD.eliminado_por));
END;

CREATE TRIGGER auditar_identidad_rol_permiso_i AFTER INSERT ON identidad_rol_permiso
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'insert', 'identidad_rol_permiso', NEW.id, json_object('id', NEW.id, 'rol', NEW.rol, 'permiso', NEW.permiso, 'revocado_en', NEW.revocado_en));
END;
CREATE TRIGGER auditar_identidad_rol_permiso_u AFTER UPDATE ON identidad_rol_permiso
WHEN OLD.id IS NOT NEW.id OR OLD.rol IS NOT NEW.rol OR OLD.permiso IS NOT NEW.permiso OR OLD.revocado_en IS NOT NEW.revocado_en
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'update', 'identidad_rol_permiso', NEW.id,
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, OLD.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'rol' AS k, OLD.rol AS v WHERE OLD.rol IS NOT NEW.rol UNION ALL SELECT 'permiso' AS k, OLD.permiso AS v WHERE OLD.permiso IS NOT NEW.permiso UNION ALL SELECT 'revocado_en' AS k, OLD.revocado_en AS v WHERE OLD.revocado_en IS NOT NEW.revocado_en)),
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, NEW.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'rol' AS k, NEW.rol AS v WHERE OLD.rol IS NOT NEW.rol UNION ALL SELECT 'permiso' AS k, NEW.permiso AS v WHERE OLD.permiso IS NOT NEW.permiso UNION ALL SELECT 'revocado_en' AS k, NEW.revocado_en AS v WHERE OLD.revocado_en IS NOT NEW.revocado_en)));
END;
CREATE TRIGGER auditar_identidad_rol_permiso_d AFTER DELETE ON identidad_rol_permiso
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'delete', 'identidad_rol_permiso', OLD.id, json_object('id', OLD.id, 'rol', OLD.rol, 'permiso', OLD.permiso, 'revocado_en', OLD.revocado_en));
END;

CREATE TRIGGER auditar_identidad_usuario_rol_i AFTER INSERT ON identidad_usuario_rol
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NEW.departamento_id, 'insert', 'identidad_usuario_rol', NEW.id, json_object('id', NEW.id, 'usuario_id', NEW.usuario_id, 'rol', NEW.rol, 'departamento_id', NEW.departamento_id, 'asignado_por', NEW.asignado_por, 'asignado_en', NEW.asignado_en, 'revocado_en', NEW.revocado_en));
END;
CREATE TRIGGER auditar_identidad_usuario_rol_u AFTER UPDATE ON identidad_usuario_rol
WHEN OLD.id IS NOT NEW.id OR OLD.usuario_id IS NOT NEW.usuario_id OR OLD.rol IS NOT NEW.rol OR OLD.departamento_id IS NOT NEW.departamento_id OR OLD.asignado_por IS NOT NEW.asignado_por OR OLD.asignado_en IS NOT NEW.asignado_en OR OLD.revocado_en IS NOT NEW.revocado_en
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NEW.departamento_id, 'update', 'identidad_usuario_rol', NEW.id,
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, OLD.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'usuario_id' AS k, OLD.usuario_id AS v WHERE OLD.usuario_id IS NOT NEW.usuario_id UNION ALL SELECT 'rol' AS k, OLD.rol AS v WHERE OLD.rol IS NOT NEW.rol UNION ALL SELECT 'departamento_id' AS k, OLD.departamento_id AS v WHERE OLD.departamento_id IS NOT NEW.departamento_id UNION ALL SELECT 'asignado_por' AS k, OLD.asignado_por AS v WHERE OLD.asignado_por IS NOT NEW.asignado_por UNION ALL SELECT 'asignado_en' AS k, OLD.asignado_en AS v WHERE OLD.asignado_en IS NOT NEW.asignado_en UNION ALL SELECT 'revocado_en' AS k, OLD.revocado_en AS v WHERE OLD.revocado_en IS NOT NEW.revocado_en)),
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, NEW.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'usuario_id' AS k, NEW.usuario_id AS v WHERE OLD.usuario_id IS NOT NEW.usuario_id UNION ALL SELECT 'rol' AS k, NEW.rol AS v WHERE OLD.rol IS NOT NEW.rol UNION ALL SELECT 'departamento_id' AS k, NEW.departamento_id AS v WHERE OLD.departamento_id IS NOT NEW.departamento_id UNION ALL SELECT 'asignado_por' AS k, NEW.asignado_por AS v WHERE OLD.asignado_por IS NOT NEW.asignado_por UNION ALL SELECT 'asignado_en' AS k, NEW.asignado_en AS v WHERE OLD.asignado_en IS NOT NEW.asignado_en UNION ALL SELECT 'revocado_en' AS k, NEW.revocado_en AS v WHERE OLD.revocado_en IS NOT NEW.revocado_en)));
END;
CREATE TRIGGER auditar_identidad_usuario_rol_d AFTER DELETE ON identidad_usuario_rol
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), OLD.departamento_id, 'delete', 'identidad_usuario_rol', OLD.id, json_object('id', OLD.id, 'usuario_id', OLD.usuario_id, 'rol', OLD.rol, 'departamento_id', OLD.departamento_id, 'asignado_por', OLD.asignado_por, 'asignado_en', OLD.asignado_en, 'revocado_en', OLD.revocado_en));
END;

CREATE TRIGGER auditar_catalogo_periodo_i AFTER INSERT ON catalogo_periodo
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NEW.departamento_id, 'insert', 'catalogo_periodo', NEW.id, json_object('id', NEW.id, 'departamento_id', NEW.departamento_id, 'codigo', NEW.codigo, 'fecha_inicio', NEW.fecha_inicio, 'fecha_fin', NEW.fecha_fin, 'estado', NEW.estado));
END;
CREATE TRIGGER auditar_catalogo_periodo_u AFTER UPDATE ON catalogo_periodo
WHEN OLD.id IS NOT NEW.id OR OLD.departamento_id IS NOT NEW.departamento_id OR OLD.codigo IS NOT NEW.codigo OR OLD.fecha_inicio IS NOT NEW.fecha_inicio OR OLD.fecha_fin IS NOT NEW.fecha_fin OR OLD.estado IS NOT NEW.estado
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NEW.departamento_id, 'update', 'catalogo_periodo', NEW.id,
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, OLD.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'departamento_id' AS k, OLD.departamento_id AS v WHERE OLD.departamento_id IS NOT NEW.departamento_id UNION ALL SELECT 'codigo' AS k, OLD.codigo AS v WHERE OLD.codigo IS NOT NEW.codigo UNION ALL SELECT 'fecha_inicio' AS k, OLD.fecha_inicio AS v WHERE OLD.fecha_inicio IS NOT NEW.fecha_inicio UNION ALL SELECT 'fecha_fin' AS k, OLD.fecha_fin AS v WHERE OLD.fecha_fin IS NOT NEW.fecha_fin UNION ALL SELECT 'estado' AS k, OLD.estado AS v WHERE OLD.estado IS NOT NEW.estado)),
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, NEW.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'departamento_id' AS k, NEW.departamento_id AS v WHERE OLD.departamento_id IS NOT NEW.departamento_id UNION ALL SELECT 'codigo' AS k, NEW.codigo AS v WHERE OLD.codigo IS NOT NEW.codigo UNION ALL SELECT 'fecha_inicio' AS k, NEW.fecha_inicio AS v WHERE OLD.fecha_inicio IS NOT NEW.fecha_inicio UNION ALL SELECT 'fecha_fin' AS k, NEW.fecha_fin AS v WHERE OLD.fecha_fin IS NOT NEW.fecha_fin UNION ALL SELECT 'estado' AS k, NEW.estado AS v WHERE OLD.estado IS NOT NEW.estado)));
END;
CREATE TRIGGER auditar_catalogo_periodo_d AFTER DELETE ON catalogo_periodo
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), OLD.departamento_id, 'delete', 'catalogo_periodo', OLD.id, json_object('id', OLD.id, 'departamento_id', OLD.departamento_id, 'codigo', OLD.codigo, 'fecha_inicio', OLD.fecha_inicio, 'fecha_fin', OLD.fecha_fin, 'estado', OLD.estado));
END;

CREATE TRIGGER auditar_catalogo_programa_i AFTER INSERT ON catalogo_programa
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NEW.departamento_id, 'insert', 'catalogo_programa', NEW.id, json_object('id', NEW.id, 'departamento_id', NEW.departamento_id, 'codigo', NEW.codigo, 'nombre', NEW.nombre, 'tipo', NEW.tipo, 'eliminado_en', NEW.eliminado_en, 'eliminado_por', NEW.eliminado_por));
END;
CREATE TRIGGER auditar_catalogo_programa_u AFTER UPDATE ON catalogo_programa
WHEN OLD.id IS NOT NEW.id OR OLD.departamento_id IS NOT NEW.departamento_id OR OLD.codigo IS NOT NEW.codigo OR OLD.nombre IS NOT NEW.nombre OR OLD.tipo IS NOT NEW.tipo OR OLD.eliminado_en IS NOT NEW.eliminado_en OR OLD.eliminado_por IS NOT NEW.eliminado_por
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NEW.departamento_id, 'update', 'catalogo_programa', NEW.id,
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, OLD.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'departamento_id' AS k, OLD.departamento_id AS v WHERE OLD.departamento_id IS NOT NEW.departamento_id UNION ALL SELECT 'codigo' AS k, OLD.codigo AS v WHERE OLD.codigo IS NOT NEW.codigo UNION ALL SELECT 'nombre' AS k, OLD.nombre AS v WHERE OLD.nombre IS NOT NEW.nombre UNION ALL SELECT 'tipo' AS k, OLD.tipo AS v WHERE OLD.tipo IS NOT NEW.tipo UNION ALL SELECT 'eliminado_en' AS k, OLD.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, OLD.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)),
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, NEW.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'departamento_id' AS k, NEW.departamento_id AS v WHERE OLD.departamento_id IS NOT NEW.departamento_id UNION ALL SELECT 'codigo' AS k, NEW.codigo AS v WHERE OLD.codigo IS NOT NEW.codigo UNION ALL SELECT 'nombre' AS k, NEW.nombre AS v WHERE OLD.nombre IS NOT NEW.nombre UNION ALL SELECT 'tipo' AS k, NEW.tipo AS v WHERE OLD.tipo IS NOT NEW.tipo UNION ALL SELECT 'eliminado_en' AS k, NEW.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, NEW.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)));
END;
CREATE TRIGGER auditar_catalogo_programa_d AFTER DELETE ON catalogo_programa
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), OLD.departamento_id, 'delete', 'catalogo_programa', OLD.id, json_object('id', OLD.id, 'departamento_id', OLD.departamento_id, 'codigo', OLD.codigo, 'nombre', OLD.nombre, 'tipo', OLD.tipo, 'eliminado_en', OLD.eliminado_en, 'eliminado_por', OLD.eliminado_por));
END;

CREATE TRIGGER auditar_catalogo_asignatura_i AFTER INSERT ON catalogo_asignatura
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NEW.departamento_id, 'insert', 'catalogo_asignatura', NEW.id, json_object('id', NEW.id, 'departamento_id', NEW.departamento_id, 'codigo', NEW.codigo, 'nombre', NEW.nombre, 'area', NEW.area, 'requiere_laboratorio', NEW.requiere_laboratorio, 'activa', NEW.activa, 'eliminado_en', NEW.eliminado_en, 'eliminado_por', NEW.eliminado_por));
END;
CREATE TRIGGER auditar_catalogo_asignatura_u AFTER UPDATE ON catalogo_asignatura
WHEN OLD.id IS NOT NEW.id OR OLD.departamento_id IS NOT NEW.departamento_id OR OLD.codigo IS NOT NEW.codigo OR OLD.nombre IS NOT NEW.nombre OR OLD.area IS NOT NEW.area OR OLD.requiere_laboratorio IS NOT NEW.requiere_laboratorio OR OLD.activa IS NOT NEW.activa OR OLD.eliminado_en IS NOT NEW.eliminado_en OR OLD.eliminado_por IS NOT NEW.eliminado_por
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NEW.departamento_id, 'update', 'catalogo_asignatura', NEW.id,
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, OLD.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'departamento_id' AS k, OLD.departamento_id AS v WHERE OLD.departamento_id IS NOT NEW.departamento_id UNION ALL SELECT 'codigo' AS k, OLD.codigo AS v WHERE OLD.codigo IS NOT NEW.codigo UNION ALL SELECT 'nombre' AS k, OLD.nombre AS v WHERE OLD.nombre IS NOT NEW.nombre UNION ALL SELECT 'area' AS k, OLD.area AS v WHERE OLD.area IS NOT NEW.area UNION ALL SELECT 'requiere_laboratorio' AS k, OLD.requiere_laboratorio AS v WHERE OLD.requiere_laboratorio IS NOT NEW.requiere_laboratorio UNION ALL SELECT 'activa' AS k, OLD.activa AS v WHERE OLD.activa IS NOT NEW.activa UNION ALL SELECT 'eliminado_en' AS k, OLD.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, OLD.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)),
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, NEW.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'departamento_id' AS k, NEW.departamento_id AS v WHERE OLD.departamento_id IS NOT NEW.departamento_id UNION ALL SELECT 'codigo' AS k, NEW.codigo AS v WHERE OLD.codigo IS NOT NEW.codigo UNION ALL SELECT 'nombre' AS k, NEW.nombre AS v WHERE OLD.nombre IS NOT NEW.nombre UNION ALL SELECT 'area' AS k, NEW.area AS v WHERE OLD.area IS NOT NEW.area UNION ALL SELECT 'requiere_laboratorio' AS k, NEW.requiere_laboratorio AS v WHERE OLD.requiere_laboratorio IS NOT NEW.requiere_laboratorio UNION ALL SELECT 'activa' AS k, NEW.activa AS v WHERE OLD.activa IS NOT NEW.activa UNION ALL SELECT 'eliminado_en' AS k, NEW.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, NEW.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)));
END;
CREATE TRIGGER auditar_catalogo_asignatura_d AFTER DELETE ON catalogo_asignatura
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), OLD.departamento_id, 'delete', 'catalogo_asignatura', OLD.id, json_object('id', OLD.id, 'departamento_id', OLD.departamento_id, 'codigo', OLD.codigo, 'nombre', OLD.nombre, 'area', OLD.area, 'requiere_laboratorio', OLD.requiere_laboratorio, 'activa', OLD.activa, 'eliminado_en', OLD.eliminado_en, 'eliminado_por', OLD.eliminado_por));
END;

CREATE TRIGGER auditar_catalogo_sala_i AFTER INSERT ON catalogo_sala
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NEW.departamento_id, 'insert', 'catalogo_sala', NEW.id, json_object('id', NEW.id, 'departamento_id', NEW.departamento_id, 'codigo', NEW.codigo, 'nombre', NEW.nombre, 'capacidad', NEW.capacidad, 'es_laboratorio', NEW.es_laboratorio, 'administrada_por', NEW.administrada_por, 'activa', NEW.activa, 'eliminado_en', NEW.eliminado_en, 'eliminado_por', NEW.eliminado_por));
END;
CREATE TRIGGER auditar_catalogo_sala_u AFTER UPDATE ON catalogo_sala
WHEN OLD.id IS NOT NEW.id OR OLD.departamento_id IS NOT NEW.departamento_id OR OLD.codigo IS NOT NEW.codigo OR OLD.nombre IS NOT NEW.nombre OR OLD.capacidad IS NOT NEW.capacidad OR OLD.es_laboratorio IS NOT NEW.es_laboratorio OR OLD.administrada_por IS NOT NEW.administrada_por OR OLD.activa IS NOT NEW.activa OR OLD.eliminado_en IS NOT NEW.eliminado_en OR OLD.eliminado_por IS NOT NEW.eliminado_por
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NEW.departamento_id, 'update', 'catalogo_sala', NEW.id,
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, OLD.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'departamento_id' AS k, OLD.departamento_id AS v WHERE OLD.departamento_id IS NOT NEW.departamento_id UNION ALL SELECT 'codigo' AS k, OLD.codigo AS v WHERE OLD.codigo IS NOT NEW.codigo UNION ALL SELECT 'nombre' AS k, OLD.nombre AS v WHERE OLD.nombre IS NOT NEW.nombre UNION ALL SELECT 'capacidad' AS k, OLD.capacidad AS v WHERE OLD.capacidad IS NOT NEW.capacidad UNION ALL SELECT 'es_laboratorio' AS k, OLD.es_laboratorio AS v WHERE OLD.es_laboratorio IS NOT NEW.es_laboratorio UNION ALL SELECT 'administrada_por' AS k, OLD.administrada_por AS v WHERE OLD.administrada_por IS NOT NEW.administrada_por UNION ALL SELECT 'activa' AS k, OLD.activa AS v WHERE OLD.activa IS NOT NEW.activa UNION ALL SELECT 'eliminado_en' AS k, OLD.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, OLD.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)),
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, NEW.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'departamento_id' AS k, NEW.departamento_id AS v WHERE OLD.departamento_id IS NOT NEW.departamento_id UNION ALL SELECT 'codigo' AS k, NEW.codigo AS v WHERE OLD.codigo IS NOT NEW.codigo UNION ALL SELECT 'nombre' AS k, NEW.nombre AS v WHERE OLD.nombre IS NOT NEW.nombre UNION ALL SELECT 'capacidad' AS k, NEW.capacidad AS v WHERE OLD.capacidad IS NOT NEW.capacidad UNION ALL SELECT 'es_laboratorio' AS k, NEW.es_laboratorio AS v WHERE OLD.es_laboratorio IS NOT NEW.es_laboratorio UNION ALL SELECT 'administrada_por' AS k, NEW.administrada_por AS v WHERE OLD.administrada_por IS NOT NEW.administrada_por UNION ALL SELECT 'activa' AS k, NEW.activa AS v WHERE OLD.activa IS NOT NEW.activa UNION ALL SELECT 'eliminado_en' AS k, NEW.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, NEW.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)));
END;
CREATE TRIGGER auditar_catalogo_sala_d AFTER DELETE ON catalogo_sala
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), OLD.departamento_id, 'delete', 'catalogo_sala', OLD.id, json_object('id', OLD.id, 'departamento_id', OLD.departamento_id, 'codigo', OLD.codigo, 'nombre', OLD.nombre, 'capacidad', OLD.capacidad, 'es_laboratorio', OLD.es_laboratorio, 'administrada_por', OLD.administrada_por, 'activa', OLD.activa, 'eliminado_en', OLD.eliminado_en, 'eliminado_por', OLD.eliminado_por));
END;

CREATE TRIGGER auditar_catalogo_persona_i AFTER INSERT ON catalogo_persona
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'insert', 'catalogo_persona', NEW.id, json_object('id', NEW.id, 'rut_cifrado', NEW.rut_cifrado, 'rut_indice', NEW.rut_indice, 'nombre', NEW.nombre, 'email_cifrado', NEW.email_cifrado, 'eliminado_en', NEW.eliminado_en, 'eliminado_por', NEW.eliminado_por));
END;
CREATE TRIGGER auditar_catalogo_persona_u AFTER UPDATE ON catalogo_persona
WHEN OLD.id IS NOT NEW.id OR OLD.rut_cifrado IS NOT NEW.rut_cifrado OR OLD.rut_indice IS NOT NEW.rut_indice OR OLD.nombre IS NOT NEW.nombre OR OLD.email_cifrado IS NOT NEW.email_cifrado OR OLD.eliminado_en IS NOT NEW.eliminado_en OR OLD.eliminado_por IS NOT NEW.eliminado_por
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'update', 'catalogo_persona', NEW.id,
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, OLD.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'rut_cifrado' AS k, OLD.rut_cifrado AS v WHERE OLD.rut_cifrado IS NOT NEW.rut_cifrado UNION ALL SELECT 'rut_indice' AS k, OLD.rut_indice AS v WHERE OLD.rut_indice IS NOT NEW.rut_indice UNION ALL SELECT 'nombre' AS k, OLD.nombre AS v WHERE OLD.nombre IS NOT NEW.nombre UNION ALL SELECT 'email_cifrado' AS k, OLD.email_cifrado AS v WHERE OLD.email_cifrado IS NOT NEW.email_cifrado UNION ALL SELECT 'eliminado_en' AS k, OLD.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, OLD.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)),
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, NEW.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'rut_cifrado' AS k, NEW.rut_cifrado AS v WHERE OLD.rut_cifrado IS NOT NEW.rut_cifrado UNION ALL SELECT 'rut_indice' AS k, NEW.rut_indice AS v WHERE OLD.rut_indice IS NOT NEW.rut_indice UNION ALL SELECT 'nombre' AS k, NEW.nombre AS v WHERE OLD.nombre IS NOT NEW.nombre UNION ALL SELECT 'email_cifrado' AS k, NEW.email_cifrado AS v WHERE OLD.email_cifrado IS NOT NEW.email_cifrado UNION ALL SELECT 'eliminado_en' AS k, NEW.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, NEW.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)));
END;
CREATE TRIGGER auditar_catalogo_persona_d AFTER DELETE ON catalogo_persona
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'delete', 'catalogo_persona', OLD.id, json_object('id', OLD.id, 'rut_cifrado', OLD.rut_cifrado, 'rut_indice', OLD.rut_indice, 'nombre', OLD.nombre, 'email_cifrado', OLD.email_cifrado, 'eliminado_en', OLD.eliminado_en, 'eliminado_por', OLD.eliminado_por));
END;

CREATE TRIGGER auditar_catalogo_docente_i AFTER INSERT ON catalogo_docente
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NEW.departamento_id, 'insert', 'catalogo_docente', NULL, json_object('persona_id', NEW.persona_id, 'departamento_id', NEW.departamento_id, 'tipo_contrato', NEW.tipo_contrato, 'activo', NEW.activo, 'eliminado_en', NEW.eliminado_en, 'eliminado_por', NEW.eliminado_por));
END;
CREATE TRIGGER auditar_catalogo_docente_u AFTER UPDATE ON catalogo_docente
WHEN OLD.persona_id IS NOT NEW.persona_id OR OLD.departamento_id IS NOT NEW.departamento_id OR OLD.tipo_contrato IS NOT NEW.tipo_contrato OR OLD.activo IS NOT NEW.activo OR OLD.eliminado_en IS NOT NEW.eliminado_en OR OLD.eliminado_por IS NOT NEW.eliminado_por
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NEW.departamento_id, 'update', 'catalogo_docente', NULL,
          (SELECT json_group_object(k, v) FROM (SELECT 'persona_id' AS k, OLD.persona_id AS v WHERE OLD.persona_id IS NOT NEW.persona_id UNION ALL SELECT 'departamento_id' AS k, OLD.departamento_id AS v WHERE OLD.departamento_id IS NOT NEW.departamento_id UNION ALL SELECT 'tipo_contrato' AS k, OLD.tipo_contrato AS v WHERE OLD.tipo_contrato IS NOT NEW.tipo_contrato UNION ALL SELECT 'activo' AS k, OLD.activo AS v WHERE OLD.activo IS NOT NEW.activo UNION ALL SELECT 'eliminado_en' AS k, OLD.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, OLD.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)),
          (SELECT json_group_object(k, v) FROM (SELECT 'persona_id' AS k, NEW.persona_id AS v WHERE OLD.persona_id IS NOT NEW.persona_id UNION ALL SELECT 'departamento_id' AS k, NEW.departamento_id AS v WHERE OLD.departamento_id IS NOT NEW.departamento_id UNION ALL SELECT 'tipo_contrato' AS k, NEW.tipo_contrato AS v WHERE OLD.tipo_contrato IS NOT NEW.tipo_contrato UNION ALL SELECT 'activo' AS k, NEW.activo AS v WHERE OLD.activo IS NOT NEW.activo UNION ALL SELECT 'eliminado_en' AS k, NEW.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, NEW.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)));
END;
CREATE TRIGGER auditar_catalogo_docente_d AFTER DELETE ON catalogo_docente
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), OLD.departamento_id, 'delete', 'catalogo_docente', NULL, json_object('persona_id', OLD.persona_id, 'departamento_id', OLD.departamento_id, 'tipo_contrato', OLD.tipo_contrato, 'activo', OLD.activo, 'eliminado_en', OLD.eliminado_en, 'eliminado_por', OLD.eliminado_por));
END;

CREATE TRIGGER auditar_catalogo_ayudante_i AFTER INSERT ON catalogo_ayudante
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NEW.departamento_id, 'insert', 'catalogo_ayudante', NULL, json_object('persona_id', NEW.persona_id, 'departamento_id', NEW.departamento_id, 'activo', NEW.activo, 'eliminado_en', NEW.eliminado_en, 'eliminado_por', NEW.eliminado_por));
END;
CREATE TRIGGER auditar_catalogo_ayudante_u AFTER UPDATE ON catalogo_ayudante
WHEN OLD.persona_id IS NOT NEW.persona_id OR OLD.departamento_id IS NOT NEW.departamento_id OR OLD.activo IS NOT NEW.activo OR OLD.eliminado_en IS NOT NEW.eliminado_en OR OLD.eliminado_por IS NOT NEW.eliminado_por
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NEW.departamento_id, 'update', 'catalogo_ayudante', NULL,
          (SELECT json_group_object(k, v) FROM (SELECT 'persona_id' AS k, OLD.persona_id AS v WHERE OLD.persona_id IS NOT NEW.persona_id UNION ALL SELECT 'departamento_id' AS k, OLD.departamento_id AS v WHERE OLD.departamento_id IS NOT NEW.departamento_id UNION ALL SELECT 'activo' AS k, OLD.activo AS v WHERE OLD.activo IS NOT NEW.activo UNION ALL SELECT 'eliminado_en' AS k, OLD.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, OLD.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)),
          (SELECT json_group_object(k, v) FROM (SELECT 'persona_id' AS k, NEW.persona_id AS v WHERE OLD.persona_id IS NOT NEW.persona_id UNION ALL SELECT 'departamento_id' AS k, NEW.departamento_id AS v WHERE OLD.departamento_id IS NOT NEW.departamento_id UNION ALL SELECT 'activo' AS k, NEW.activo AS v WHERE OLD.activo IS NOT NEW.activo UNION ALL SELECT 'eliminado_en' AS k, NEW.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, NEW.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)));
END;
CREATE TRIGGER auditar_catalogo_ayudante_d AFTER DELETE ON catalogo_ayudante
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), OLD.departamento_id, 'delete', 'catalogo_ayudante', NULL, json_object('persona_id', OLD.persona_id, 'departamento_id', OLD.departamento_id, 'activo', OLD.activo, 'eliminado_en', OLD.eliminado_en, 'eliminado_por', OLD.eliminado_por));
END;

CREATE TRIGGER auditar_horarios_liga_i AFTER INSERT ON horarios_liga
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'insert', 'horarios_liga', NEW.id, json_object('id', NEW.id, 'periodo_id', NEW.periodo_id, 'codigo', NEW.codigo, 'eliminado_en', NEW.eliminado_en, 'eliminado_por', NEW.eliminado_por));
END;
CREATE TRIGGER auditar_horarios_liga_u AFTER UPDATE ON horarios_liga
WHEN OLD.id IS NOT NEW.id OR OLD.periodo_id IS NOT NEW.periodo_id OR OLD.codigo IS NOT NEW.codigo OR OLD.eliminado_en IS NOT NEW.eliminado_en OR OLD.eliminado_por IS NOT NEW.eliminado_por
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'update', 'horarios_liga', NEW.id,
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, OLD.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'periodo_id' AS k, OLD.periodo_id AS v WHERE OLD.periodo_id IS NOT NEW.periodo_id UNION ALL SELECT 'codigo' AS k, OLD.codigo AS v WHERE OLD.codigo IS NOT NEW.codigo UNION ALL SELECT 'eliminado_en' AS k, OLD.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, OLD.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)),
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, NEW.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'periodo_id' AS k, NEW.periodo_id AS v WHERE OLD.periodo_id IS NOT NEW.periodo_id UNION ALL SELECT 'codigo' AS k, NEW.codigo AS v WHERE OLD.codigo IS NOT NEW.codigo UNION ALL SELECT 'eliminado_en' AS k, NEW.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, NEW.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)));
END;
CREATE TRIGGER auditar_horarios_liga_d AFTER DELETE ON horarios_liga
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'delete', 'horarios_liga', OLD.id, json_object('id', OLD.id, 'periodo_id', OLD.periodo_id, 'codigo', OLD.codigo, 'eliminado_en', OLD.eliminado_en, 'eliminado_por', OLD.eliminado_por));
END;

CREATE TRIGGER auditar_horarios_paralelo_i AFTER INSERT ON horarios_paralelo
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'insert', 'horarios_paralelo', NEW.id, json_object('id', NEW.id, 'periodo_id', NEW.periodo_id, 'asignatura_id', NEW.asignatura_id, 'nrc', NEW.nrc, 'codigo', NEW.codigo, 'componente', NEW.componente, 'estado', NEW.estado, 'cupo_estimado', NEW.cupo_estimado, 'sesiones_semana', NEW.sesiones_semana, 'requiere_laboratorio', NEW.requiere_laboratorio, 'liga_id', NEW.liga_id, 'sesiones_seguidas', NEW.sesiones_seguidas, 'docentes_alternan', NEW.docentes_alternan, 'observacion', NEW.observacion, 'importacion_id', NEW.importacion_id, 'eliminado_en', NEW.eliminado_en, 'eliminado_por', NEW.eliminado_por));
END;
CREATE TRIGGER auditar_horarios_paralelo_u AFTER UPDATE ON horarios_paralelo
WHEN OLD.id IS NOT NEW.id OR OLD.periodo_id IS NOT NEW.periodo_id OR OLD.asignatura_id IS NOT NEW.asignatura_id OR OLD.nrc IS NOT NEW.nrc OR OLD.codigo IS NOT NEW.codigo OR OLD.componente IS NOT NEW.componente OR OLD.estado IS NOT NEW.estado OR OLD.cupo_estimado IS NOT NEW.cupo_estimado OR OLD.sesiones_semana IS NOT NEW.sesiones_semana OR OLD.requiere_laboratorio IS NOT NEW.requiere_laboratorio OR OLD.liga_id IS NOT NEW.liga_id OR OLD.sesiones_seguidas IS NOT NEW.sesiones_seguidas OR OLD.docentes_alternan IS NOT NEW.docentes_alternan OR OLD.observacion IS NOT NEW.observacion OR OLD.importacion_id IS NOT NEW.importacion_id OR OLD.eliminado_en IS NOT NEW.eliminado_en OR OLD.eliminado_por IS NOT NEW.eliminado_por
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'update', 'horarios_paralelo', NEW.id,
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, OLD.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'periodo_id' AS k, OLD.periodo_id AS v WHERE OLD.periodo_id IS NOT NEW.periodo_id UNION ALL SELECT 'asignatura_id' AS k, OLD.asignatura_id AS v WHERE OLD.asignatura_id IS NOT NEW.asignatura_id UNION ALL SELECT 'nrc' AS k, OLD.nrc AS v WHERE OLD.nrc IS NOT NEW.nrc UNION ALL SELECT 'codigo' AS k, OLD.codigo AS v WHERE OLD.codigo IS NOT NEW.codigo UNION ALL SELECT 'componente' AS k, OLD.componente AS v WHERE OLD.componente IS NOT NEW.componente UNION ALL SELECT 'estado' AS k, OLD.estado AS v WHERE OLD.estado IS NOT NEW.estado UNION ALL SELECT 'cupo_estimado' AS k, OLD.cupo_estimado AS v WHERE OLD.cupo_estimado IS NOT NEW.cupo_estimado UNION ALL SELECT 'sesiones_semana' AS k, OLD.sesiones_semana AS v WHERE OLD.sesiones_semana IS NOT NEW.sesiones_semana UNION ALL SELECT 'requiere_laboratorio' AS k, OLD.requiere_laboratorio AS v WHERE OLD.requiere_laboratorio IS NOT NEW.requiere_laboratorio UNION ALL SELECT 'liga_id' AS k, OLD.liga_id AS v WHERE OLD.liga_id IS NOT NEW.liga_id UNION ALL SELECT 'sesiones_seguidas' AS k, OLD.sesiones_seguidas AS v WHERE OLD.sesiones_seguidas IS NOT NEW.sesiones_seguidas UNION ALL SELECT 'docentes_alternan' AS k, OLD.docentes_alternan AS v WHERE OLD.docentes_alternan IS NOT NEW.docentes_alternan UNION ALL SELECT 'observacion' AS k, OLD.observacion AS v WHERE OLD.observacion IS NOT NEW.observacion UNION ALL SELECT 'importacion_id' AS k, OLD.importacion_id AS v WHERE OLD.importacion_id IS NOT NEW.importacion_id UNION ALL SELECT 'eliminado_en' AS k, OLD.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, OLD.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)),
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, NEW.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'periodo_id' AS k, NEW.periodo_id AS v WHERE OLD.periodo_id IS NOT NEW.periodo_id UNION ALL SELECT 'asignatura_id' AS k, NEW.asignatura_id AS v WHERE OLD.asignatura_id IS NOT NEW.asignatura_id UNION ALL SELECT 'nrc' AS k, NEW.nrc AS v WHERE OLD.nrc IS NOT NEW.nrc UNION ALL SELECT 'codigo' AS k, NEW.codigo AS v WHERE OLD.codigo IS NOT NEW.codigo UNION ALL SELECT 'componente' AS k, NEW.componente AS v WHERE OLD.componente IS NOT NEW.componente UNION ALL SELECT 'estado' AS k, NEW.estado AS v WHERE OLD.estado IS NOT NEW.estado UNION ALL SELECT 'cupo_estimado' AS k, NEW.cupo_estimado AS v WHERE OLD.cupo_estimado IS NOT NEW.cupo_estimado UNION ALL SELECT 'sesiones_semana' AS k, NEW.sesiones_semana AS v WHERE OLD.sesiones_semana IS NOT NEW.sesiones_semana UNION ALL SELECT 'requiere_laboratorio' AS k, NEW.requiere_laboratorio AS v WHERE OLD.requiere_laboratorio IS NOT NEW.requiere_laboratorio UNION ALL SELECT 'liga_id' AS k, NEW.liga_id AS v WHERE OLD.liga_id IS NOT NEW.liga_id UNION ALL SELECT 'sesiones_seguidas' AS k, NEW.sesiones_seguidas AS v WHERE OLD.sesiones_seguidas IS NOT NEW.sesiones_seguidas UNION ALL SELECT 'docentes_alternan' AS k, NEW.docentes_alternan AS v WHERE OLD.docentes_alternan IS NOT NEW.docentes_alternan UNION ALL SELECT 'observacion' AS k, NEW.observacion AS v WHERE OLD.observacion IS NOT NEW.observacion UNION ALL SELECT 'importacion_id' AS k, NEW.importacion_id AS v WHERE OLD.importacion_id IS NOT NEW.importacion_id UNION ALL SELECT 'eliminado_en' AS k, NEW.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, NEW.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)));
END;
CREATE TRIGGER auditar_horarios_paralelo_d AFTER DELETE ON horarios_paralelo
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'delete', 'horarios_paralelo', OLD.id, json_object('id', OLD.id, 'periodo_id', OLD.periodo_id, 'asignatura_id', OLD.asignatura_id, 'nrc', OLD.nrc, 'codigo', OLD.codigo, 'componente', OLD.componente, 'estado', OLD.estado, 'cupo_estimado', OLD.cupo_estimado, 'sesiones_semana', OLD.sesiones_semana, 'requiere_laboratorio', OLD.requiere_laboratorio, 'liga_id', OLD.liga_id, 'sesiones_seguidas', OLD.sesiones_seguidas, 'docentes_alternan', OLD.docentes_alternan, 'observacion', OLD.observacion, 'importacion_id', OLD.importacion_id, 'eliminado_en', OLD.eliminado_en, 'eliminado_por', OLD.eliminado_por));
END;

CREATE TRIGGER auditar_horarios_sesion_i AFTER INSERT ON horarios_sesion
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'insert', 'horarios_sesion', NEW.id, json_object('id', NEW.id, 'paralelo_id', NEW.paralelo_id, 'numero', NEW.numero, 'duracion_bloques', NEW.duracion_bloques, 'eliminado_en', NEW.eliminado_en, 'eliminado_por', NEW.eliminado_por));
END;
CREATE TRIGGER auditar_horarios_sesion_u AFTER UPDATE ON horarios_sesion
WHEN OLD.id IS NOT NEW.id OR OLD.paralelo_id IS NOT NEW.paralelo_id OR OLD.numero IS NOT NEW.numero OR OLD.duracion_bloques IS NOT NEW.duracion_bloques OR OLD.eliminado_en IS NOT NEW.eliminado_en OR OLD.eliminado_por IS NOT NEW.eliminado_por
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'update', 'horarios_sesion', NEW.id,
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, OLD.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'paralelo_id' AS k, OLD.paralelo_id AS v WHERE OLD.paralelo_id IS NOT NEW.paralelo_id UNION ALL SELECT 'numero' AS k, OLD.numero AS v WHERE OLD.numero IS NOT NEW.numero UNION ALL SELECT 'duracion_bloques' AS k, OLD.duracion_bloques AS v WHERE OLD.duracion_bloques IS NOT NEW.duracion_bloques UNION ALL SELECT 'eliminado_en' AS k, OLD.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, OLD.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)),
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, NEW.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'paralelo_id' AS k, NEW.paralelo_id AS v WHERE OLD.paralelo_id IS NOT NEW.paralelo_id UNION ALL SELECT 'numero' AS k, NEW.numero AS v WHERE OLD.numero IS NOT NEW.numero UNION ALL SELECT 'duracion_bloques' AS k, NEW.duracion_bloques AS v WHERE OLD.duracion_bloques IS NOT NEW.duracion_bloques UNION ALL SELECT 'eliminado_en' AS k, NEW.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, NEW.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)));
END;
CREATE TRIGGER auditar_horarios_sesion_d AFTER DELETE ON horarios_sesion
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'delete', 'horarios_sesion', OLD.id, json_object('id', OLD.id, 'paralelo_id', OLD.paralelo_id, 'numero', OLD.numero, 'duracion_bloques', OLD.duracion_bloques, 'eliminado_en', OLD.eliminado_en, 'eliminado_por', OLD.eliminado_por));
END;

CREATE TRIGGER auditar_horarios_restriccion_i AFTER INSERT ON horarios_restriccion
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NEW.departamento_id, 'insert', 'horarios_restriccion', NEW.id, json_object('id', NEW.id, 'departamento_id', NEW.departamento_id, 'periodo_id', NEW.periodo_id, 'naturaleza', NEW.naturaleza, 'tipo', NEW.tipo, 'alcance', json(NEW.alcance), 'parametros', json(NEW.parametros), 'peso', NEW.peso, 'vigente_desde', NEW.vigente_desde, 'vigente_hasta', NEW.vigente_hasta, 'activa', NEW.activa, 'nota', NEW.nota, 'creada_por', NEW.creada_por, 'creada_en', NEW.creada_en, 'actualizada_en', NEW.actualizada_en, 'eliminado_en', NEW.eliminado_en, 'eliminado_por', NEW.eliminado_por));
END;
CREATE TRIGGER auditar_horarios_restriccion_u AFTER UPDATE ON horarios_restriccion
WHEN OLD.id IS NOT NEW.id OR OLD.departamento_id IS NOT NEW.departamento_id OR OLD.periodo_id IS NOT NEW.periodo_id OR OLD.naturaleza IS NOT NEW.naturaleza OR OLD.tipo IS NOT NEW.tipo OR OLD.alcance IS NOT NEW.alcance OR OLD.parametros IS NOT NEW.parametros OR OLD.peso IS NOT NEW.peso OR OLD.vigente_desde IS NOT NEW.vigente_desde OR OLD.vigente_hasta IS NOT NEW.vigente_hasta OR OLD.activa IS NOT NEW.activa OR OLD.nota IS NOT NEW.nota OR OLD.creada_por IS NOT NEW.creada_por OR OLD.creada_en IS NOT NEW.creada_en OR OLD.actualizada_en IS NOT NEW.actualizada_en OR OLD.eliminado_en IS NOT NEW.eliminado_en OR OLD.eliminado_por IS NOT NEW.eliminado_por
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NEW.departamento_id, 'update', 'horarios_restriccion', NEW.id,
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, OLD.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'departamento_id' AS k, OLD.departamento_id AS v WHERE OLD.departamento_id IS NOT NEW.departamento_id UNION ALL SELECT 'periodo_id' AS k, OLD.periodo_id AS v WHERE OLD.periodo_id IS NOT NEW.periodo_id UNION ALL SELECT 'naturaleza' AS k, OLD.naturaleza AS v WHERE OLD.naturaleza IS NOT NEW.naturaleza UNION ALL SELECT 'tipo' AS k, OLD.tipo AS v WHERE OLD.tipo IS NOT NEW.tipo UNION ALL SELECT 'alcance' AS k, json(OLD.alcance) AS v WHERE OLD.alcance IS NOT NEW.alcance UNION ALL SELECT 'parametros' AS k, json(OLD.parametros) AS v WHERE OLD.parametros IS NOT NEW.parametros UNION ALL SELECT 'peso' AS k, OLD.peso AS v WHERE OLD.peso IS NOT NEW.peso UNION ALL SELECT 'vigente_desde' AS k, OLD.vigente_desde AS v WHERE OLD.vigente_desde IS NOT NEW.vigente_desde UNION ALL SELECT 'vigente_hasta' AS k, OLD.vigente_hasta AS v WHERE OLD.vigente_hasta IS NOT NEW.vigente_hasta UNION ALL SELECT 'activa' AS k, OLD.activa AS v WHERE OLD.activa IS NOT NEW.activa UNION ALL SELECT 'nota' AS k, OLD.nota AS v WHERE OLD.nota IS NOT NEW.nota UNION ALL SELECT 'creada_por' AS k, OLD.creada_por AS v WHERE OLD.creada_por IS NOT NEW.creada_por UNION ALL SELECT 'creada_en' AS k, OLD.creada_en AS v WHERE OLD.creada_en IS NOT NEW.creada_en UNION ALL SELECT 'actualizada_en' AS k, OLD.actualizada_en AS v WHERE OLD.actualizada_en IS NOT NEW.actualizada_en UNION ALL SELECT 'eliminado_en' AS k, OLD.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, OLD.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)),
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, NEW.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'departamento_id' AS k, NEW.departamento_id AS v WHERE OLD.departamento_id IS NOT NEW.departamento_id UNION ALL SELECT 'periodo_id' AS k, NEW.periodo_id AS v WHERE OLD.periodo_id IS NOT NEW.periodo_id UNION ALL SELECT 'naturaleza' AS k, NEW.naturaleza AS v WHERE OLD.naturaleza IS NOT NEW.naturaleza UNION ALL SELECT 'tipo' AS k, NEW.tipo AS v WHERE OLD.tipo IS NOT NEW.tipo UNION ALL SELECT 'alcance' AS k, json(NEW.alcance) AS v WHERE OLD.alcance IS NOT NEW.alcance UNION ALL SELECT 'parametros' AS k, json(NEW.parametros) AS v WHERE OLD.parametros IS NOT NEW.parametros UNION ALL SELECT 'peso' AS k, NEW.peso AS v WHERE OLD.peso IS NOT NEW.peso UNION ALL SELECT 'vigente_desde' AS k, NEW.vigente_desde AS v WHERE OLD.vigente_desde IS NOT NEW.vigente_desde UNION ALL SELECT 'vigente_hasta' AS k, NEW.vigente_hasta AS v WHERE OLD.vigente_hasta IS NOT NEW.vigente_hasta UNION ALL SELECT 'activa' AS k, NEW.activa AS v WHERE OLD.activa IS NOT NEW.activa UNION ALL SELECT 'nota' AS k, NEW.nota AS v WHERE OLD.nota IS NOT NEW.nota UNION ALL SELECT 'creada_por' AS k, NEW.creada_por AS v WHERE OLD.creada_por IS NOT NEW.creada_por UNION ALL SELECT 'creada_en' AS k, NEW.creada_en AS v WHERE OLD.creada_en IS NOT NEW.creada_en UNION ALL SELECT 'actualizada_en' AS k, NEW.actualizada_en AS v WHERE OLD.actualizada_en IS NOT NEW.actualizada_en UNION ALL SELECT 'eliminado_en' AS k, NEW.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, NEW.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)));
END;
CREATE TRIGGER auditar_horarios_restriccion_d AFTER DELETE ON horarios_restriccion
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), OLD.departamento_id, 'delete', 'horarios_restriccion', OLD.id, json_object('id', OLD.id, 'departamento_id', OLD.departamento_id, 'periodo_id', OLD.periodo_id, 'naturaleza', OLD.naturaleza, 'tipo', OLD.tipo, 'alcance', json(OLD.alcance), 'parametros', json(OLD.parametros), 'peso', OLD.peso, 'vigente_desde', OLD.vigente_desde, 'vigente_hasta', OLD.vigente_hasta, 'activa', OLD.activa, 'nota', OLD.nota, 'creada_por', OLD.creada_por, 'creada_en', OLD.creada_en, 'actualizada_en', OLD.actualizada_en, 'eliminado_en', OLD.eliminado_en, 'eliminado_por', OLD.eliminado_por));
END;

CREATE TRIGGER auditar_horarios_perfil_i AFTER INSERT ON horarios_perfil
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'insert', 'horarios_perfil', NEW.id, json_object('id', NEW.id, 'nombre', NEW.nombre, 'descripcion', NEW.descripcion, 'pesos', json(NEW.pesos), 'eliminado_en', NEW.eliminado_en, 'eliminado_por', NEW.eliminado_por));
END;
CREATE TRIGGER auditar_horarios_perfil_u AFTER UPDATE ON horarios_perfil
WHEN OLD.id IS NOT NEW.id OR OLD.nombre IS NOT NEW.nombre OR OLD.descripcion IS NOT NEW.descripcion OR OLD.pesos IS NOT NEW.pesos OR OLD.eliminado_en IS NOT NEW.eliminado_en OR OLD.eliminado_por IS NOT NEW.eliminado_por
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'update', 'horarios_perfil', NEW.id,
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, OLD.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'nombre' AS k, OLD.nombre AS v WHERE OLD.nombre IS NOT NEW.nombre UNION ALL SELECT 'descripcion' AS k, OLD.descripcion AS v WHERE OLD.descripcion IS NOT NEW.descripcion UNION ALL SELECT 'pesos' AS k, json(OLD.pesos) AS v WHERE OLD.pesos IS NOT NEW.pesos UNION ALL SELECT 'eliminado_en' AS k, OLD.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, OLD.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)),
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, NEW.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'nombre' AS k, NEW.nombre AS v WHERE OLD.nombre IS NOT NEW.nombre UNION ALL SELECT 'descripcion' AS k, NEW.descripcion AS v WHERE OLD.descripcion IS NOT NEW.descripcion UNION ALL SELECT 'pesos' AS k, json(NEW.pesos) AS v WHERE OLD.pesos IS NOT NEW.pesos UNION ALL SELECT 'eliminado_en' AS k, NEW.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, NEW.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)));
END;
CREATE TRIGGER auditar_horarios_perfil_d AFTER DELETE ON horarios_perfil
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'delete', 'horarios_perfil', OLD.id, json_object('id', OLD.id, 'nombre', OLD.nombre, 'descripcion', OLD.descripcion, 'pesos', json(OLD.pesos), 'eliminado_en', OLD.eliminado_en, 'eliminado_por', OLD.eliminado_por));
END;

CREATE TRIGGER auditar_horarios_propuesta_i AFTER INSERT ON horarios_propuesta
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'insert', 'horarios_propuesta', NEW.id, json_object('id', NEW.id, 'periodo_id', NEW.periodo_id, 'corrida_id', NEW.corrida_id, 'origen_id', NEW.origen_id, 'nombre', NEW.nombre, 'estado', NEW.estado, 'completa', NEW.completa, 'metricas', json(NEW.metricas), 'reemplazada_por', NEW.reemplazada_por, 'aprobada_por', NEW.aprobada_por, 'aprobada_en', NEW.aprobada_en, 'creada_por', NEW.creada_por, 'creada_en', NEW.creada_en));
END;
CREATE TRIGGER auditar_horarios_propuesta_u AFTER UPDATE ON horarios_propuesta
WHEN OLD.id IS NOT NEW.id OR OLD.periodo_id IS NOT NEW.periodo_id OR OLD.corrida_id IS NOT NEW.corrida_id OR OLD.origen_id IS NOT NEW.origen_id OR OLD.nombre IS NOT NEW.nombre OR OLD.estado IS NOT NEW.estado OR OLD.completa IS NOT NEW.completa OR OLD.metricas IS NOT NEW.metricas OR OLD.reemplazada_por IS NOT NEW.reemplazada_por OR OLD.aprobada_por IS NOT NEW.aprobada_por OR OLD.aprobada_en IS NOT NEW.aprobada_en OR OLD.creada_por IS NOT NEW.creada_por OR OLD.creada_en IS NOT NEW.creada_en
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'update', 'horarios_propuesta', NEW.id,
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, OLD.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'periodo_id' AS k, OLD.periodo_id AS v WHERE OLD.periodo_id IS NOT NEW.periodo_id UNION ALL SELECT 'corrida_id' AS k, OLD.corrida_id AS v WHERE OLD.corrida_id IS NOT NEW.corrida_id UNION ALL SELECT 'origen_id' AS k, OLD.origen_id AS v WHERE OLD.origen_id IS NOT NEW.origen_id UNION ALL SELECT 'nombre' AS k, OLD.nombre AS v WHERE OLD.nombre IS NOT NEW.nombre UNION ALL SELECT 'estado' AS k, OLD.estado AS v WHERE OLD.estado IS NOT NEW.estado UNION ALL SELECT 'completa' AS k, OLD.completa AS v WHERE OLD.completa IS NOT NEW.completa UNION ALL SELECT 'metricas' AS k, json(OLD.metricas) AS v WHERE OLD.metricas IS NOT NEW.metricas UNION ALL SELECT 'reemplazada_por' AS k, OLD.reemplazada_por AS v WHERE OLD.reemplazada_por IS NOT NEW.reemplazada_por UNION ALL SELECT 'aprobada_por' AS k, OLD.aprobada_por AS v WHERE OLD.aprobada_por IS NOT NEW.aprobada_por UNION ALL SELECT 'aprobada_en' AS k, OLD.aprobada_en AS v WHERE OLD.aprobada_en IS NOT NEW.aprobada_en UNION ALL SELECT 'creada_por' AS k, OLD.creada_por AS v WHERE OLD.creada_por IS NOT NEW.creada_por UNION ALL SELECT 'creada_en' AS k, OLD.creada_en AS v WHERE OLD.creada_en IS NOT NEW.creada_en)),
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, NEW.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'periodo_id' AS k, NEW.periodo_id AS v WHERE OLD.periodo_id IS NOT NEW.periodo_id UNION ALL SELECT 'corrida_id' AS k, NEW.corrida_id AS v WHERE OLD.corrida_id IS NOT NEW.corrida_id UNION ALL SELECT 'origen_id' AS k, NEW.origen_id AS v WHERE OLD.origen_id IS NOT NEW.origen_id UNION ALL SELECT 'nombre' AS k, NEW.nombre AS v WHERE OLD.nombre IS NOT NEW.nombre UNION ALL SELECT 'estado' AS k, NEW.estado AS v WHERE OLD.estado IS NOT NEW.estado UNION ALL SELECT 'completa' AS k, NEW.completa AS v WHERE OLD.completa IS NOT NEW.completa UNION ALL SELECT 'metricas' AS k, json(NEW.metricas) AS v WHERE OLD.metricas IS NOT NEW.metricas UNION ALL SELECT 'reemplazada_por' AS k, NEW.reemplazada_por AS v WHERE OLD.reemplazada_por IS NOT NEW.reemplazada_por UNION ALL SELECT 'aprobada_por' AS k, NEW.aprobada_por AS v WHERE OLD.aprobada_por IS NOT NEW.aprobada_por UNION ALL SELECT 'aprobada_en' AS k, NEW.aprobada_en AS v WHERE OLD.aprobada_en IS NOT NEW.aprobada_en UNION ALL SELECT 'creada_por' AS k, NEW.creada_por AS v WHERE OLD.creada_por IS NOT NEW.creada_por UNION ALL SELECT 'creada_en' AS k, NEW.creada_en AS v WHERE OLD.creada_en IS NOT NEW.creada_en)));
END;
CREATE TRIGGER auditar_horarios_propuesta_d AFTER DELETE ON horarios_propuesta
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'delete', 'horarios_propuesta', OLD.id, json_object('id', OLD.id, 'periodo_id', OLD.periodo_id, 'corrida_id', OLD.corrida_id, 'origen_id', OLD.origen_id, 'nombre', OLD.nombre, 'estado', OLD.estado, 'completa', OLD.completa, 'metricas', json(OLD.metricas), 'reemplazada_por', OLD.reemplazada_por, 'aprobada_por', OLD.aprobada_por, 'aprobada_en', OLD.aprobada_en, 'creada_por', OLD.creada_por, 'creada_en', OLD.creada_en));
END;

CREATE TRIGGER auditar_horarios_asignacion_i AFTER INSERT ON horarios_asignacion
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'insert', 'horarios_asignacion', NEW.id, json_object('id', NEW.id, 'propuesta_id', NEW.propuesta_id, 'sesion_id', NEW.sesion_id, 'dia', NEW.dia, 'bloque', NEW.bloque, 'sala_id', NEW.sala_id, 'fijada', NEW.fijada, 'origen', NEW.origen, 'modificada_por', NEW.modificada_por, 'modificada_en', NEW.modificada_en));
END;
CREATE TRIGGER auditar_horarios_asignacion_u AFTER UPDATE ON horarios_asignacion
WHEN OLD.id IS NOT NEW.id OR OLD.propuesta_id IS NOT NEW.propuesta_id OR OLD.sesion_id IS NOT NEW.sesion_id OR OLD.dia IS NOT NEW.dia OR OLD.bloque IS NOT NEW.bloque OR OLD.sala_id IS NOT NEW.sala_id OR OLD.fijada IS NOT NEW.fijada OR OLD.origen IS NOT NEW.origen OR OLD.modificada_por IS NOT NEW.modificada_por OR OLD.modificada_en IS NOT NEW.modificada_en
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'update', 'horarios_asignacion', NEW.id,
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, OLD.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'propuesta_id' AS k, OLD.propuesta_id AS v WHERE OLD.propuesta_id IS NOT NEW.propuesta_id UNION ALL SELECT 'sesion_id' AS k, OLD.sesion_id AS v WHERE OLD.sesion_id IS NOT NEW.sesion_id UNION ALL SELECT 'dia' AS k, OLD.dia AS v WHERE OLD.dia IS NOT NEW.dia UNION ALL SELECT 'bloque' AS k, OLD.bloque AS v WHERE OLD.bloque IS NOT NEW.bloque UNION ALL SELECT 'sala_id' AS k, OLD.sala_id AS v WHERE OLD.sala_id IS NOT NEW.sala_id UNION ALL SELECT 'fijada' AS k, OLD.fijada AS v WHERE OLD.fijada IS NOT NEW.fijada UNION ALL SELECT 'origen' AS k, OLD.origen AS v WHERE OLD.origen IS NOT NEW.origen UNION ALL SELECT 'modificada_por' AS k, OLD.modificada_por AS v WHERE OLD.modificada_por IS NOT NEW.modificada_por UNION ALL SELECT 'modificada_en' AS k, OLD.modificada_en AS v WHERE OLD.modificada_en IS NOT NEW.modificada_en)),
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, NEW.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'propuesta_id' AS k, NEW.propuesta_id AS v WHERE OLD.propuesta_id IS NOT NEW.propuesta_id UNION ALL SELECT 'sesion_id' AS k, NEW.sesion_id AS v WHERE OLD.sesion_id IS NOT NEW.sesion_id UNION ALL SELECT 'dia' AS k, NEW.dia AS v WHERE OLD.dia IS NOT NEW.dia UNION ALL SELECT 'bloque' AS k, NEW.bloque AS v WHERE OLD.bloque IS NOT NEW.bloque UNION ALL SELECT 'sala_id' AS k, NEW.sala_id AS v WHERE OLD.sala_id IS NOT NEW.sala_id UNION ALL SELECT 'fijada' AS k, NEW.fijada AS v WHERE OLD.fijada IS NOT NEW.fijada UNION ALL SELECT 'origen' AS k, NEW.origen AS v WHERE OLD.origen IS NOT NEW.origen UNION ALL SELECT 'modificada_por' AS k, NEW.modificada_por AS v WHERE OLD.modificada_por IS NOT NEW.modificada_por UNION ALL SELECT 'modificada_en' AS k, NEW.modificada_en AS v WHERE OLD.modificada_en IS NOT NEW.modificada_en)));
END;
CREATE TRIGGER auditar_horarios_asignacion_d AFTER DELETE ON horarios_asignacion
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'delete', 'horarios_asignacion', OLD.id, json_object('id', OLD.id, 'propuesta_id', OLD.propuesta_id, 'sesion_id', OLD.sesion_id, 'dia', OLD.dia, 'bloque', OLD.bloque, 'sala_id', OLD.sala_id, 'fijada', OLD.fijada, 'origen', OLD.origen, 'modificada_por', OLD.modificada_por, 'modificada_en', OLD.modificada_en));
END;

CREATE TRIGGER auditar_horarios_sala_externa_autorizada_i AFTER INSERT ON horarios_sala_externa_autorizada
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'insert', 'horarios_sala_externa_autorizada', NEW.id, json_object('id', NEW.id, 'periodo_id', NEW.periodo_id, 'sala_id', NEW.sala_id, 'aprobada_por', NEW.aprobada_por, 'aprobada_en', NEW.aprobada_en, 'revocada_en', NEW.revocada_en));
END;
CREATE TRIGGER auditar_horarios_sala_externa_autorizada_u AFTER UPDATE ON horarios_sala_externa_autorizada
WHEN OLD.id IS NOT NEW.id OR OLD.periodo_id IS NOT NEW.periodo_id OR OLD.sala_id IS NOT NEW.sala_id OR OLD.aprobada_por IS NOT NEW.aprobada_por OR OLD.aprobada_en IS NOT NEW.aprobada_en OR OLD.revocada_en IS NOT NEW.revocada_en
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'update', 'horarios_sala_externa_autorizada', NEW.id,
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, OLD.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'periodo_id' AS k, OLD.periodo_id AS v WHERE OLD.periodo_id IS NOT NEW.periodo_id UNION ALL SELECT 'sala_id' AS k, OLD.sala_id AS v WHERE OLD.sala_id IS NOT NEW.sala_id UNION ALL SELECT 'aprobada_por' AS k, OLD.aprobada_por AS v WHERE OLD.aprobada_por IS NOT NEW.aprobada_por UNION ALL SELECT 'aprobada_en' AS k, OLD.aprobada_en AS v WHERE OLD.aprobada_en IS NOT NEW.aprobada_en UNION ALL SELECT 'revocada_en' AS k, OLD.revocada_en AS v WHERE OLD.revocada_en IS NOT NEW.revocada_en)),
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, NEW.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'periodo_id' AS k, NEW.periodo_id AS v WHERE OLD.periodo_id IS NOT NEW.periodo_id UNION ALL SELECT 'sala_id' AS k, NEW.sala_id AS v WHERE OLD.sala_id IS NOT NEW.sala_id UNION ALL SELECT 'aprobada_por' AS k, NEW.aprobada_por AS v WHERE OLD.aprobada_por IS NOT NEW.aprobada_por UNION ALL SELECT 'aprobada_en' AS k, NEW.aprobada_en AS v WHERE OLD.aprobada_en IS NOT NEW.aprobada_en UNION ALL SELECT 'revocada_en' AS k, NEW.revocada_en AS v WHERE OLD.revocada_en IS NOT NEW.revocada_en)));
END;
CREATE TRIGGER auditar_horarios_sala_externa_autorizada_d AFTER DELETE ON horarios_sala_externa_autorizada
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'delete', 'horarios_sala_externa_autorizada', OLD.id, json_object('id', OLD.id, 'periodo_id', OLD.periodo_id, 'sala_id', OLD.sala_id, 'aprobada_por', OLD.aprobada_por, 'aprobada_en', OLD.aprobada_en, 'revocada_en', OLD.revocada_en));
END;

CREATE TRIGGER auditar_horarios_envio_horario_i AFTER INSERT ON horarios_envio_horario
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'insert', 'horarios_envio_horario', NEW.id, json_object('id', NEW.id, 'propuesta_id', NEW.propuesta_id, 'docente_id', NEW.docente_id, 'email_destino_cifrado', NEW.email_destino_cifrado, 'estado', NEW.estado, 'error', NEW.error, 'creado_por', NEW.creado_por, 'creado_en', NEW.creado_en, 'enviado_en', NEW.enviado_en));
END;
CREATE TRIGGER auditar_horarios_envio_horario_u AFTER UPDATE ON horarios_envio_horario
WHEN OLD.id IS NOT NEW.id OR OLD.propuesta_id IS NOT NEW.propuesta_id OR OLD.docente_id IS NOT NEW.docente_id OR OLD.email_destino_cifrado IS NOT NEW.email_destino_cifrado OR OLD.estado IS NOT NEW.estado OR OLD.error IS NOT NEW.error OR OLD.creado_por IS NOT NEW.creado_por OR OLD.creado_en IS NOT NEW.creado_en OR OLD.enviado_en IS NOT NEW.enviado_en
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'update', 'horarios_envio_horario', NEW.id,
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, OLD.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'propuesta_id' AS k, OLD.propuesta_id AS v WHERE OLD.propuesta_id IS NOT NEW.propuesta_id UNION ALL SELECT 'docente_id' AS k, OLD.docente_id AS v WHERE OLD.docente_id IS NOT NEW.docente_id UNION ALL SELECT 'email_destino_cifrado' AS k, OLD.email_destino_cifrado AS v WHERE OLD.email_destino_cifrado IS NOT NEW.email_destino_cifrado UNION ALL SELECT 'estado' AS k, OLD.estado AS v WHERE OLD.estado IS NOT NEW.estado UNION ALL SELECT 'error' AS k, OLD.error AS v WHERE OLD.error IS NOT NEW.error UNION ALL SELECT 'creado_por' AS k, OLD.creado_por AS v WHERE OLD.creado_por IS NOT NEW.creado_por UNION ALL SELECT 'creado_en' AS k, OLD.creado_en AS v WHERE OLD.creado_en IS NOT NEW.creado_en UNION ALL SELECT 'enviado_en' AS k, OLD.enviado_en AS v WHERE OLD.enviado_en IS NOT NEW.enviado_en)),
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, NEW.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'propuesta_id' AS k, NEW.propuesta_id AS v WHERE OLD.propuesta_id IS NOT NEW.propuesta_id UNION ALL SELECT 'docente_id' AS k, NEW.docente_id AS v WHERE OLD.docente_id IS NOT NEW.docente_id UNION ALL SELECT 'email_destino_cifrado' AS k, NEW.email_destino_cifrado AS v WHERE OLD.email_destino_cifrado IS NOT NEW.email_destino_cifrado UNION ALL SELECT 'estado' AS k, NEW.estado AS v WHERE OLD.estado IS NOT NEW.estado UNION ALL SELECT 'error' AS k, NEW.error AS v WHERE OLD.error IS NOT NEW.error UNION ALL SELECT 'creado_por' AS k, NEW.creado_por AS v WHERE OLD.creado_por IS NOT NEW.creado_por UNION ALL SELECT 'creado_en' AS k, NEW.creado_en AS v WHERE OLD.creado_en IS NOT NEW.creado_en UNION ALL SELECT 'enviado_en' AS k, NEW.enviado_en AS v WHERE OLD.enviado_en IS NOT NEW.enviado_en)));
END;
CREATE TRIGGER auditar_horarios_envio_horario_d AFTER DELETE ON horarios_envio_horario
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'delete', 'horarios_envio_horario', OLD.id, json_object('id', OLD.id, 'propuesta_id', OLD.propuesta_id, 'docente_id', OLD.docente_id, 'email_destino_cifrado', OLD.email_destino_cifrado, 'estado', OLD.estado, 'error', OLD.error, 'creado_por', OLD.creado_por, 'creado_en', OLD.creado_en, 'enviado_en', OLD.enviado_en));
END;

CREATE TRIGGER auditar_finanzas_escenario_i AFTER INSERT ON finanzas_escenario
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NEW.departamento_id, 'insert', 'finanzas_escenario', NEW.id, json_object('id', NEW.id, 'departamento_id', NEW.departamento_id, 'nombre', NEW.nombre, 'descripcion', NEW.descripcion, 'creado_por', NEW.creado_por, 'creado_en', NEW.creado_en, 'eliminado_en', NEW.eliminado_en, 'eliminado_por', NEW.eliminado_por));
END;
CREATE TRIGGER auditar_finanzas_escenario_u AFTER UPDATE ON finanzas_escenario
WHEN OLD.id IS NOT NEW.id OR OLD.departamento_id IS NOT NEW.departamento_id OR OLD.nombre IS NOT NEW.nombre OR OLD.descripcion IS NOT NEW.descripcion OR OLD.creado_por IS NOT NEW.creado_por OR OLD.creado_en IS NOT NEW.creado_en OR OLD.eliminado_en IS NOT NEW.eliminado_en OR OLD.eliminado_por IS NOT NEW.eliminado_por
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NEW.departamento_id, 'update', 'finanzas_escenario', NEW.id,
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, OLD.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'departamento_id' AS k, OLD.departamento_id AS v WHERE OLD.departamento_id IS NOT NEW.departamento_id UNION ALL SELECT 'nombre' AS k, OLD.nombre AS v WHERE OLD.nombre IS NOT NEW.nombre UNION ALL SELECT 'descripcion' AS k, OLD.descripcion AS v WHERE OLD.descripcion IS NOT NEW.descripcion UNION ALL SELECT 'creado_por' AS k, OLD.creado_por AS v WHERE OLD.creado_por IS NOT NEW.creado_por UNION ALL SELECT 'creado_en' AS k, OLD.creado_en AS v WHERE OLD.creado_en IS NOT NEW.creado_en UNION ALL SELECT 'eliminado_en' AS k, OLD.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, OLD.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)),
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, NEW.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'departamento_id' AS k, NEW.departamento_id AS v WHERE OLD.departamento_id IS NOT NEW.departamento_id UNION ALL SELECT 'nombre' AS k, NEW.nombre AS v WHERE OLD.nombre IS NOT NEW.nombre UNION ALL SELECT 'descripcion' AS k, NEW.descripcion AS v WHERE OLD.descripcion IS NOT NEW.descripcion UNION ALL SELECT 'creado_por' AS k, NEW.creado_por AS v WHERE OLD.creado_por IS NOT NEW.creado_por UNION ALL SELECT 'creado_en' AS k, NEW.creado_en AS v WHERE OLD.creado_en IS NOT NEW.creado_en UNION ALL SELECT 'eliminado_en' AS k, NEW.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, NEW.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)));
END;
CREATE TRIGGER auditar_finanzas_escenario_d AFTER DELETE ON finanzas_escenario
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), OLD.departamento_id, 'delete', 'finanzas_escenario', OLD.id, json_object('id', OLD.id, 'departamento_id', OLD.departamento_id, 'nombre', OLD.nombre, 'descripcion', OLD.descripcion, 'creado_por', OLD.creado_por, 'creado_en', OLD.creado_en, 'eliminado_en', OLD.eliminado_en, 'eliminado_por', OLD.eliminado_por));
END;

CREATE TRIGGER auditar_finanzas_tarifa_i AFTER INSERT ON finanzas_tarifa
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'insert', 'finanzas_tarifa', NEW.id, json_object('id', NEW.id, 'categoria_id', NEW.categoria_id, 'valor_hora', NEW.valor_hora, 'vigente_desde', NEW.vigente_desde, 'escenario_id', NEW.escenario_id, 'eliminado_en', NEW.eliminado_en, 'eliminado_por', NEW.eliminado_por));
END;
CREATE TRIGGER auditar_finanzas_tarifa_u AFTER UPDATE ON finanzas_tarifa
WHEN OLD.id IS NOT NEW.id OR OLD.categoria_id IS NOT NEW.categoria_id OR OLD.valor_hora IS NOT NEW.valor_hora OR OLD.vigente_desde IS NOT NEW.vigente_desde OR OLD.escenario_id IS NOT NEW.escenario_id OR OLD.eliminado_en IS NOT NEW.eliminado_en OR OLD.eliminado_por IS NOT NEW.eliminado_por
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'update', 'finanzas_tarifa', NEW.id,
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, OLD.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'categoria_id' AS k, OLD.categoria_id AS v WHERE OLD.categoria_id IS NOT NEW.categoria_id UNION ALL SELECT 'valor_hora' AS k, OLD.valor_hora AS v WHERE OLD.valor_hora IS NOT NEW.valor_hora UNION ALL SELECT 'vigente_desde' AS k, OLD.vigente_desde AS v WHERE OLD.vigente_desde IS NOT NEW.vigente_desde UNION ALL SELECT 'escenario_id' AS k, OLD.escenario_id AS v WHERE OLD.escenario_id IS NOT NEW.escenario_id UNION ALL SELECT 'eliminado_en' AS k, OLD.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, OLD.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)),
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, NEW.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'categoria_id' AS k, NEW.categoria_id AS v WHERE OLD.categoria_id IS NOT NEW.categoria_id UNION ALL SELECT 'valor_hora' AS k, NEW.valor_hora AS v WHERE OLD.valor_hora IS NOT NEW.valor_hora UNION ALL SELECT 'vigente_desde' AS k, NEW.vigente_desde AS v WHERE OLD.vigente_desde IS NOT NEW.vigente_desde UNION ALL SELECT 'escenario_id' AS k, NEW.escenario_id AS v WHERE OLD.escenario_id IS NOT NEW.escenario_id UNION ALL SELECT 'eliminado_en' AS k, NEW.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, NEW.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)));
END;
CREATE TRIGGER auditar_finanzas_tarifa_d AFTER DELETE ON finanzas_tarifa
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'delete', 'finanzas_tarifa', OLD.id, json_object('id', OLD.id, 'categoria_id', OLD.categoria_id, 'valor_hora', OLD.valor_hora, 'vigente_desde', OLD.vigente_desde, 'escenario_id', OLD.escenario_id, 'eliminado_en', OLD.eliminado_en, 'eliminado_por', OLD.eliminado_por));
END;

CREATE TRIGGER auditar_finanzas_presupuesto_i AFTER INSERT ON finanzas_presupuesto
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NEW.departamento_id, 'insert', 'finanzas_presupuesto', NEW.id, json_object('id', NEW.id, 'departamento_id', NEW.departamento_id, 'anio', NEW.anio, 'tipo_persona', NEW.tipo_persona, 'monto_anual', NEW.monto_anual, 'porcentaje_s1', NEW.porcentaje_s1, 'escenario_id', NEW.escenario_id, 'eliminado_en', NEW.eliminado_en, 'eliminado_por', NEW.eliminado_por));
END;
CREATE TRIGGER auditar_finanzas_presupuesto_u AFTER UPDATE ON finanzas_presupuesto
WHEN OLD.id IS NOT NEW.id OR OLD.departamento_id IS NOT NEW.departamento_id OR OLD.anio IS NOT NEW.anio OR OLD.tipo_persona IS NOT NEW.tipo_persona OR OLD.monto_anual IS NOT NEW.monto_anual OR OLD.porcentaje_s1 IS NOT NEW.porcentaje_s1 OR OLD.escenario_id IS NOT NEW.escenario_id OR OLD.eliminado_en IS NOT NEW.eliminado_en OR OLD.eliminado_por IS NOT NEW.eliminado_por
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NEW.departamento_id, 'update', 'finanzas_presupuesto', NEW.id,
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, OLD.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'departamento_id' AS k, OLD.departamento_id AS v WHERE OLD.departamento_id IS NOT NEW.departamento_id UNION ALL SELECT 'anio' AS k, OLD.anio AS v WHERE OLD.anio IS NOT NEW.anio UNION ALL SELECT 'tipo_persona' AS k, OLD.tipo_persona AS v WHERE OLD.tipo_persona IS NOT NEW.tipo_persona UNION ALL SELECT 'monto_anual' AS k, OLD.monto_anual AS v WHERE OLD.monto_anual IS NOT NEW.monto_anual UNION ALL SELECT 'porcentaje_s1' AS k, OLD.porcentaje_s1 AS v WHERE OLD.porcentaje_s1 IS NOT NEW.porcentaje_s1 UNION ALL SELECT 'escenario_id' AS k, OLD.escenario_id AS v WHERE OLD.escenario_id IS NOT NEW.escenario_id UNION ALL SELECT 'eliminado_en' AS k, OLD.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, OLD.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)),
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, NEW.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'departamento_id' AS k, NEW.departamento_id AS v WHERE OLD.departamento_id IS NOT NEW.departamento_id UNION ALL SELECT 'anio' AS k, NEW.anio AS v WHERE OLD.anio IS NOT NEW.anio UNION ALL SELECT 'tipo_persona' AS k, NEW.tipo_persona AS v WHERE OLD.tipo_persona IS NOT NEW.tipo_persona UNION ALL SELECT 'monto_anual' AS k, NEW.monto_anual AS v WHERE OLD.monto_anual IS NOT NEW.monto_anual UNION ALL SELECT 'porcentaje_s1' AS k, NEW.porcentaje_s1 AS v WHERE OLD.porcentaje_s1 IS NOT NEW.porcentaje_s1 UNION ALL SELECT 'escenario_id' AS k, NEW.escenario_id AS v WHERE OLD.escenario_id IS NOT NEW.escenario_id UNION ALL SELECT 'eliminado_en' AS k, NEW.eliminado_en AS v WHERE OLD.eliminado_en IS NOT NEW.eliminado_en UNION ALL SELECT 'eliminado_por' AS k, NEW.eliminado_por AS v WHERE OLD.eliminado_por IS NOT NEW.eliminado_por)));
END;
CREATE TRIGGER auditar_finanzas_presupuesto_d AFTER DELETE ON finanzas_presupuesto
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), OLD.departamento_id, 'delete', 'finanzas_presupuesto', OLD.id, json_object('id', OLD.id, 'departamento_id', OLD.departamento_id, 'anio', OLD.anio, 'tipo_persona', OLD.tipo_persona, 'monto_anual', OLD.monto_anual, 'porcentaje_s1', OLD.porcentaje_s1, 'escenario_id', OLD.escenario_id, 'eliminado_en', OLD.eliminado_en, 'eliminado_por', OLD.eliminado_por));
END;

CREATE TRIGGER auditar_finanzas_nombramiento_i AFTER INSERT ON finanzas_nombramiento
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'insert', 'finanzas_nombramiento', NEW.id, json_object('id', NEW.id, 'persona_id', NEW.persona_id, 'periodo_id', NEW.periodo_id, 'categoria_id', NEW.categoria_id, 'paralelo_id', NEW.paralelo_id, 'horas_semanales', NEW.horas_semanales, 'fecha_inicio', NEW.fecha_inicio, 'fecha_fin', NEW.fecha_fin, 'origen', NEW.origen, 'id_externo', NEW.id_externo, 'reemplaza_a', NEW.reemplaza_a, 'estado', NEW.estado, 'creado_en', NEW.creado_en));
END;
CREATE TRIGGER auditar_finanzas_nombramiento_u AFTER UPDATE ON finanzas_nombramiento
WHEN OLD.id IS NOT NEW.id OR OLD.persona_id IS NOT NEW.persona_id OR OLD.periodo_id IS NOT NEW.periodo_id OR OLD.categoria_id IS NOT NEW.categoria_id OR OLD.paralelo_id IS NOT NEW.paralelo_id OR OLD.horas_semanales IS NOT NEW.horas_semanales OR OLD.fecha_inicio IS NOT NEW.fecha_inicio OR OLD.fecha_fin IS NOT NEW.fecha_fin OR OLD.origen IS NOT NEW.origen OR OLD.id_externo IS NOT NEW.id_externo OR OLD.reemplaza_a IS NOT NEW.reemplaza_a OR OLD.estado IS NOT NEW.estado OR OLD.creado_en IS NOT NEW.creado_en
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes, despues)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'update', 'finanzas_nombramiento', NEW.id,
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, OLD.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'persona_id' AS k, OLD.persona_id AS v WHERE OLD.persona_id IS NOT NEW.persona_id UNION ALL SELECT 'periodo_id' AS k, OLD.periodo_id AS v WHERE OLD.periodo_id IS NOT NEW.periodo_id UNION ALL SELECT 'categoria_id' AS k, OLD.categoria_id AS v WHERE OLD.categoria_id IS NOT NEW.categoria_id UNION ALL SELECT 'paralelo_id' AS k, OLD.paralelo_id AS v WHERE OLD.paralelo_id IS NOT NEW.paralelo_id UNION ALL SELECT 'horas_semanales' AS k, OLD.horas_semanales AS v WHERE OLD.horas_semanales IS NOT NEW.horas_semanales UNION ALL SELECT 'fecha_inicio' AS k, OLD.fecha_inicio AS v WHERE OLD.fecha_inicio IS NOT NEW.fecha_inicio UNION ALL SELECT 'fecha_fin' AS k, OLD.fecha_fin AS v WHERE OLD.fecha_fin IS NOT NEW.fecha_fin UNION ALL SELECT 'origen' AS k, OLD.origen AS v WHERE OLD.origen IS NOT NEW.origen UNION ALL SELECT 'id_externo' AS k, OLD.id_externo AS v WHERE OLD.id_externo IS NOT NEW.id_externo UNION ALL SELECT 'reemplaza_a' AS k, OLD.reemplaza_a AS v WHERE OLD.reemplaza_a IS NOT NEW.reemplaza_a UNION ALL SELECT 'estado' AS k, OLD.estado AS v WHERE OLD.estado IS NOT NEW.estado UNION ALL SELECT 'creado_en' AS k, OLD.creado_en AS v WHERE OLD.creado_en IS NOT NEW.creado_en)),
          (SELECT json_group_object(k, v) FROM (SELECT 'id' AS k, NEW.id AS v WHERE OLD.id IS NOT NEW.id UNION ALL SELECT 'persona_id' AS k, NEW.persona_id AS v WHERE OLD.persona_id IS NOT NEW.persona_id UNION ALL SELECT 'periodo_id' AS k, NEW.periodo_id AS v WHERE OLD.periodo_id IS NOT NEW.periodo_id UNION ALL SELECT 'categoria_id' AS k, NEW.categoria_id AS v WHERE OLD.categoria_id IS NOT NEW.categoria_id UNION ALL SELECT 'paralelo_id' AS k, NEW.paralelo_id AS v WHERE OLD.paralelo_id IS NOT NEW.paralelo_id UNION ALL SELECT 'horas_semanales' AS k, NEW.horas_semanales AS v WHERE OLD.horas_semanales IS NOT NEW.horas_semanales UNION ALL SELECT 'fecha_inicio' AS k, NEW.fecha_inicio AS v WHERE OLD.fecha_inicio IS NOT NEW.fecha_inicio UNION ALL SELECT 'fecha_fin' AS k, NEW.fecha_fin AS v WHERE OLD.fecha_fin IS NOT NEW.fecha_fin UNION ALL SELECT 'origen' AS k, NEW.origen AS v WHERE OLD.origen IS NOT NEW.origen UNION ALL SELECT 'id_externo' AS k, NEW.id_externo AS v WHERE OLD.id_externo IS NOT NEW.id_externo UNION ALL SELECT 'reemplaza_a' AS k, NEW.reemplaza_a AS v WHERE OLD.reemplaza_a IS NOT NEW.reemplaza_a UNION ALL SELECT 'estado' AS k, NEW.estado AS v WHERE OLD.estado IS NOT NEW.estado UNION ALL SELECT 'creado_en' AS k, NEW.creado_en AS v WHERE OLD.creado_en IS NOT NEW.creado_en)));
END;
CREATE TRIGGER auditar_finanzas_nombramiento_d AFTER DELETE ON finanzas_nombramiento
BEGIN
  INSERT INTO plataforma_auditoria (usuario_id, ip, departamento_id, accion, entidad, entidad_id, antes)
  VALUES ((SELECT usuario_id FROM plataforma_contexto), (SELECT ip FROM plataforma_contexto), NULL, 'delete', 'finanzas_nombramiento', OLD.id, json_object('id', OLD.id, 'persona_id', OLD.persona_id, 'periodo_id', OLD.periodo_id, 'categoria_id', OLD.categoria_id, 'paralelo_id', OLD.paralelo_id, 'horas_semanales', OLD.horas_semanales, 'fecha_inicio', OLD.fecha_inicio, 'fecha_fin', OLD.fecha_fin, 'origen', OLD.origen, 'id_externo', OLD.id_externo, 'reemplaza_a', OLD.reemplaza_a, 'estado', OLD.estado, 'creado_en', OLD.creado_en));
END;

-- Nada se elimina de forma efectiva: el DELETE se rechaza (use eliminado_en).
CREATE TRIGGER sin_borrado_identidad_departamento BEFORE DELETE ON identidad_departamento
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en identidad_departamento'); END;
CREATE TRIGGER sin_borrado_identidad_usuario BEFORE DELETE ON identidad_usuario
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en identidad_usuario'); END;
CREATE TRIGGER sin_borrado_identidad_rol BEFORE DELETE ON identidad_rol
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en identidad_rol'); END;
CREATE TRIGGER sin_borrado_identidad_permiso BEFORE DELETE ON identidad_permiso
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en identidad_permiso'); END;
CREATE TRIGGER sin_borrado_identidad_rol_permiso BEFORE DELETE ON identidad_rol_permiso
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en identidad_rol_permiso'); END;
CREATE TRIGGER sin_borrado_identidad_usuario_rol BEFORE DELETE ON identidad_usuario_rol
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en identidad_usuario_rol'); END;
CREATE TRIGGER sin_borrado_plataforma_importacion BEFORE DELETE ON plataforma_importacion
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en plataforma_importacion'); END;
CREATE TRIGGER sin_borrado_plataforma_fila_importada BEFORE DELETE ON plataforma_fila_importada
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en plataforma_fila_importada'); END;
CREATE TRIGGER sin_borrado_plataforma_modulo BEFORE DELETE ON plataforma_modulo
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en plataforma_modulo'); END;
CREATE TRIGGER sin_borrado_catalogo_periodo BEFORE DELETE ON catalogo_periodo
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en catalogo_periodo'); END;
CREATE TRIGGER sin_borrado_catalogo_programa BEFORE DELETE ON catalogo_programa
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en catalogo_programa'); END;
CREATE TRIGGER sin_borrado_catalogo_asignatura BEFORE DELETE ON catalogo_asignatura
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en catalogo_asignatura'); END;
CREATE TRIGGER sin_borrado_catalogo_plan_nivel BEFORE DELETE ON catalogo_plan_nivel
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en catalogo_plan_nivel'); END;
CREATE TRIGGER sin_borrado_catalogo_dia BEFORE DELETE ON catalogo_dia
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en catalogo_dia'); END;
CREATE TRIGGER sin_borrado_catalogo_bloque BEFORE DELETE ON catalogo_bloque
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en catalogo_bloque'); END;
CREATE TRIGGER sin_borrado_catalogo_sala BEFORE DELETE ON catalogo_sala
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en catalogo_sala'); END;
CREATE TRIGGER sin_borrado_catalogo_persona BEFORE DELETE ON catalogo_persona
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en catalogo_persona'); END;
CREATE TRIGGER sin_borrado_catalogo_docente BEFORE DELETE ON catalogo_docente
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en catalogo_docente'); END;
CREATE TRIGGER sin_borrado_catalogo_ayudante BEFORE DELETE ON catalogo_ayudante
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en catalogo_ayudante'); END;
CREATE TRIGGER sin_borrado_horarios_liga BEFORE DELETE ON horarios_liga
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en horarios_liga'); END;
CREATE TRIGGER sin_borrado_horarios_paralelo BEFORE DELETE ON horarios_paralelo
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en horarios_paralelo'); END;
CREATE TRIGGER sin_borrado_horarios_paralelo_docente BEFORE DELETE ON horarios_paralelo_docente
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en horarios_paralelo_docente'); END;
CREATE TRIGGER sin_borrado_horarios_paralelo_grupo BEFORE DELETE ON horarios_paralelo_grupo
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en horarios_paralelo_grupo'); END;
CREATE TRIGGER sin_borrado_horarios_sesion BEFORE DELETE ON horarios_sesion
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en horarios_sesion'); END;
CREATE TRIGGER sin_borrado_horarios_disponibilidad_docente BEFORE DELETE ON horarios_disponibilidad_docente
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en horarios_disponibilidad_docente'); END;
CREATE TRIGGER sin_borrado_horarios_bloqueo_sala BEFORE DELETE ON horarios_bloqueo_sala
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en horarios_bloqueo_sala'); END;
CREATE TRIGGER sin_borrado_horarios_sala_externa_autorizada BEFORE DELETE ON horarios_sala_externa_autorizada
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en horarios_sala_externa_autorizada'); END;
CREATE TRIGGER sin_borrado_horarios_reserva_nivel BEFORE DELETE ON horarios_reserva_nivel
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en horarios_reserva_nivel'); END;
CREATE TRIGGER sin_borrado_horarios_perfil BEFORE DELETE ON horarios_perfil
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en horarios_perfil'); END;
CREATE TRIGGER sin_borrado_horarios_restriccion BEFORE DELETE ON horarios_restriccion
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en horarios_restriccion'); END;
CREATE TRIGGER sin_borrado_horarios_propuesta BEFORE DELETE ON horarios_propuesta
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en horarios_propuesta'); END;
CREATE TRIGGER sin_borrado_horarios_corrida BEFORE DELETE ON horarios_corrida
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en horarios_corrida'); END;
CREATE TRIGGER sin_borrado_horarios_envio_horario BEFORE DELETE ON horarios_envio_horario
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en horarios_envio_horario'); END;
CREATE TRIGGER sin_borrado_finanzas_categoria BEFORE DELETE ON finanzas_categoria
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en finanzas_categoria'); END;
CREATE TRIGGER sin_borrado_finanzas_escenario BEFORE DELETE ON finanzas_escenario
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en finanzas_escenario'); END;
CREATE TRIGGER sin_borrado_finanzas_tarifa BEFORE DELETE ON finanzas_tarifa
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en finanzas_tarifa'); END;
CREATE TRIGGER sin_borrado_finanzas_presupuesto BEFORE DELETE ON finanzas_presupuesto
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en finanzas_presupuesto'); END;
CREATE TRIGGER sin_borrado_finanzas_categoria_persona BEFORE DELETE ON finanzas_categoria_persona
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en finanzas_categoria_persona'); END;
CREATE TRIGGER sin_borrado_finanzas_nombramiento BEFORE DELETE ON finanzas_nombramiento
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en finanzas_nombramiento'); END;
CREATE TRIGGER sin_borrado_finanzas_calculo BEFORE DELETE ON finanzas_calculo
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en finanzas_calculo'); END;
CREATE TRIGGER sin_borrado_finanzas_calculo_detalle BEFORE DELETE ON finanzas_calculo_detalle
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en finanzas_calculo_detalle'); END;
CREATE TRIGGER sin_borrado_proyeccion_inscripcion_historica BEFORE DELETE ON proyeccion_inscripcion_historica
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en proyeccion_inscripcion_historica'); END;
CREATE TRIGGER sin_borrado_proyeccion_estimacion_externa BEFORE DELETE ON proyeccion_estimacion_externa
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en proyeccion_estimacion_externa'); END;
CREATE TRIGGER sin_borrado_proyeccion_estimacion BEFORE DELETE ON proyeccion_estimacion
BEGIN SELECT RAISE(ABORT, 'Borrado lógico: marque eliminado_en en proyeccion_estimacion'); END;

COMMIT;
