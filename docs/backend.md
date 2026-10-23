# Base técnica del backend

Todo el sistema usa SQLite. La API (FastAPI) y Directus trabajan sobre el mismo archivo `plataforma.db`, en modo WAL y con `busy_timeout`. El esquema vive en `db/esquema_plataforma.sql` y se genera con `db/generar_esquema.py`.

## Levantarlo

```bash
python3 scripts/configure.py            # crea .env con secretos aleatorios (no se sube)
docker compose up --build --wait
docker compose logs configurar          # roles, permisos y verificaciones de Directus
```

| Servicio | Puerto | Qué es |
| --- | --- | --- |
| `api` | 8000 | FastAPI. Crea la base desde el esquema si no existe y siembra los usuarios iniciales |
| `directus` | 8055 | Directus sobre `plataforma.db`, solo lectura del núcleo |
| `directus-satelites` | 8056 | Directus sobre `satelites.db`, para los grupos de Proyecto Integrador |
| `configurar` | | Corre una vez, configura ambas instancias y falla si alguna verificación no se cumple |

Las claves de los usuarios semilla salen de `SEED_ADMIN_PASSWORD` y `SEED_TEST_PASSWORD` del `.env`. Los usuarios son `encargado.docente@example.com` (rol Administrador, todos los permisos) y `usuario.prueba@example.com` (rol de consulta, solo lectura en el DISC). El departamento DISC es el id 1 y existe siempre.

## Autenticación

| Ruta | Qué hace |
| --- | --- |
| `POST /auth/login` | Entrega un token de acceso (10 minutos) y un refresh token (7 días) |
| `POST /auth/refresh` | Rota el refresh token. Reutilizar uno ya usado cierra toda la sesión |
| `POST /auth/logout` | Revoca la sesión, y el token de acceso deja de valer de inmediato |
| `POST /auth/cambiar-clave` | Exige la clave actual, valida la política y cierra las demás sesiones |
| `GET /auth/yo` | Perfil y permisos efectivos por departamento |

Las claves se guardan con argon2id y del refresh token solo se guarda su hash. Tras 5 intentos fallidos la cuenta se bloquea 15 minutos, y además hay un límite de 10 intentos por minuto y por IP. Los tiempos y límites se ajustan con variables de entorno (`app/core/config.py`).

## Datos personales cifrados

La base **no está cifrada completa**: Directus trae un SQLite sin SQLCipher (sqlite3 5.1.7 sobre SQLite 3.44.2, sin códec; se comprobó con `PRAGMA cipher_version`, que no devuelve nada), y con una clave configurada simplemente la ignoraría y no cifraría. Por eso se cifran a nivel de columna, desde la API, solo el RUT y el correo.

| Dato | Dónde | Cómo se guarda |
| --- | --- | --- |
| RUT de una persona | `catalogo_persona.rut_cifrado` | AES-256-GCM con nonce aleatorio, formato `v1:<clave>:<datos>` |
| Búsqueda y unicidad del RUT | `catalogo_persona.rut_indice` | HMAC-SHA256 del RUT normalizado con `INDEX_KEY`, distinta de las claves de cifrado |
| Correo de una persona | `catalogo_persona.email_cifrado` | Igual que el RUT |
| Correo de un envío de horario | `horarios_envio_horario.email_destino_cifrado` | Igual |
| RUT y correo de las filas crudas de una importación | `plataforma_fila_importada.datos` | Cifrados columna por columna |

- El RUT no es clave en ninguna tabla. Todas apuntan a `catalogo_persona.id`, y la unicidad la da el índice ciego.
- Cada texto cifrado lleva su columna como dato autenticado, así que uno copiado a otra columna no se descifra. Un dato alterado se rechaza.
- Los CHECK del esquema impiden guardar en claro: un RUT o correo sin el prefijo `v1:` no entra. La auditoría registra los cambios con el texto cifrado, nunca con el RUT.
- El dígito verificador ya no se valida con triggers, porque la base solo ve texto cifrado. Lo validan la API y el importador, que explican cuál debería ser.
- `DATA_KEYS` (`k1=...,k2=...`, con `DATA_KEY_ID` para la que cifra), e `INDEX_KEY` son claves de 32 bytes en base64 que genera `scripts/configure.py`. **Respáldelas aparte de la base: sin ellas los datos cifrados no se recuperan.** Para rotar, agregue la clave nueva, cambie `DATA_KEY_ID`, reinicie y ejecute `python -m app.rotar_claves`. Cambiar `INDEX_KEY` obliga a recalcular los índices.
- Directus no recibe las claves ni las columnas cifradas, y la réplica de los satélites no copia datos personales.
- Lo que **no** se cifra: el nombre de las personas, los correos de login de `identidad_usuario` (que Directus también guarda en `directus_users`), y el resto de la base. Para proteger el archivo completo hay que cifrar el volumen o el disco del servidor, y para el transporte poner un proxy con HTTPS delante.

## Auditoría

Cada inicio de sesión, fallido o exitoso, cierre de sesión, cambio de clave, refresh reutilizado, acceso denegado y cambio de permisos queda en `plataforma_auditoria` con usuario, IP y fecha. Los cambios de datos los registran los triggers del esquema (con los datos personales ya cifrados). La tabla es de solo inserción y se conserva 5 años. La vista `plataforma_v_cambios_sin_usuario` muestra cualquier cambio que no pasó por la API.

## Borrado lógico

La API nunca emite `DELETE` sobre el núcleo: `DELETE /salas/1` marca `eliminado_en` y `eliminado_por`, y las consultas excluyen esas filas. Un `DELETE` real contra la base lo rechaza un trigger. En Directus ningún rol tiene permiso de borrar, y el administrador de arranque también choca con el trigger.

## Módulos

`MODULES=base,financiero,predictivo` decide qué routers se montan. Cada módulo tiene router, servicio, esquemas y repositorio, y todos comparten `app/core` para autenticación, contexto de usuario en la conexión y auditoría.

| Módulo | Contenido |
| --- | --- |
| `base` | Identidad (usuarios, roles, permisos), catálogo, horarios y publicación para satélites |
| `financiero` | Tarifas, presupuestos, escenarios y nombramientos |
| `predictivo` | Solo el esqueleto, `GET /proyeccion/estado` |

## Directus y la auditoría

Los triggers de permiso y auditoría leen `plataforma_contexto.usuario_id`, que Directus no fija. Se eligió que **todas las escrituras al núcleo pasen solo por FastAPI**, que fija el usuario y la IP dentro de `BEGIN IMMEDIATE`. En Directus las colecciones del núcleo quedan de solo lectura para todos los roles, incluido el Administrador, con alcance por departamento deducido de las claves foráneas y sin filas borradas ni columnas secretas. La matriz completa está en [matriz_permisos.md](matriz_permisos.md).

Se descartó escribir por Directus con una extensión que fije el usuario, porque exige compartir una transacción entre procesos distintos y un fallo ahí atribuiría cambios a la persona equivocada. El administrador de arranque de Directus sigue pudiendo escribir sin usuario, y cualquier cambio así aparece en la vista `plataforma_v_cambios_sin_usuario`; el paso de verificación exige que esté vacía. Conviene guardar esa cuenta como acceso de emergencia.

## Satélites

Los grupos de Proyecto Integrador se conectan a una instancia aparte de Directus, sobre `satelites.db`, para no mezclar escritores con el núcleo.

- `python -m app.publicacion` o `POST /publicacion` (permiso `horarios.exportar`) regenera las tablas `pub_*`: catálogo del DISC y el horario de la propuesta aprobada. No se copia ninguna persona, docente, nombramiento, finanza ni auditoría.
- Cada grupo (`g1` a `g4`) tiene un rol y un token estático (`SAT_TOKEN_G1` a `G4` del `.env`). Lee `pub_*`, y solo escribe en su colección `sat_<grupo>_registro`, con borrado lógico y sin permiso de `DELETE`. No ve usuarios, roles ni la colección de otro grupo.
- La instancia limita las peticiones por IP (60 por minuto, ajustable con `RATE_LIMIT_POINTS`). El paso de verificación comprueba que el límite frena a un satélite que abusa.
- Para más colecciones de un grupo se crean con el prefijo `sat_<grupo>_` y se agregan a su política.

## Importación

Hay una plantilla por colección en `plantillas_importacion/` (CSV y XLSX, con una fila de ejemplo ficticia) y su README con columnas, tipos, reglas y orden de carga. `POST /importaciones/{coleccion}` valida el CSV y, con `?confirmar=true`, lo carga completo o no carga nada. Cada error dice la fila, la columna, qué falló y cómo corregirlo, y la importación queda registrada en `plataforma_importacion` y en la auditoría. La misma especificación (`backend/app/importacion/spec.py`) genera las plantillas, el README y las reglas de validación.

## Datos de prueba

`datos_prueba/generar_datos.py` genera datos ficticios y reproducibles (semilla fija) para probar y demostrar, y `datos_prueba/DATOS_DE_PRUEBA.md` explica qué hay, cómo se generaron y el rango de RUT ficticios. Nunca se usan datos reales en el repositorio.

## Pendiente

- Los módulos de corridas de FET y de cálculo de costos, que hoy solo tienen sus datos y permisos.
- Autenticación institucional para Directus. Hoy sus usuarios se crean con las mismas claves semilla.
- Un usuario de Directus con varios departamentos usa solo uno, porque el filtro acepta un valor.
