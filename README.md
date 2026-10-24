<div align="center">

<img src="assets/banner.svg" alt="DISC Scheduling" width="100%">

# DISC Scheduling

Plataforma web de apoyo a la programación académica del Departamento de Ingeniería de Sistemas y Computación de la Universidad Católica del Norte

[![CI](https://github.com/Capstone-2026-DISC/DISC-Scheduling/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Capstone-2026-DISC/DISC-Scheduling/actions/workflows/ci.yml)

</div>

## Qué es

Cada semestre el Encargado Docente arma a mano la oferta académica del departamento y controla por separado el gasto en profesores hora y ayudantes. Esta plataforma guarda esos datos, aplica permisos por departamento, deja auditoría de cada cambio y servirá de base para que los grupos de Proyecto Integrador conecten sus módulos.

---

<div align="center">

<img src="assets/mockups.gif" alt="Maquetas de la interfaz: inicio de sesión, importación de la planilla, generación y revisión de horarios, versiones, exportación, usuarios, permisos, auditoría y costos" width="720">

</div>

---

## Arquitectura

```mermaid
flowchart LR
    persona(["Persona usuaria"]) --> frontend["frontend<br/>Next.js"] --> api["api<br/>FastAPI"]
    api -->|"sesión de la persona"| directus
    modulos["módulos de los grupos<br/>g1 a g4"] -->|"token del grupo"| directus

    directus["directus<br/>roles, permisos y actividad"] --> db[("plataforma.db")]
```

Todo usa SQLite y Directus es la única puerta a los datos: la API le habla con la sesión de cada persona, y los módulos de los grupos con el token de su grupo. Directus aplica los permisos por rol y departamento y registra quién cambió qué. Dentro de la misma base, cada grupo solo lee las tablas `pub_*` (una copia del catálogo y del horario aprobado, sin datos personales) y solo escribe en su propia tabla `sat_<grupo>_registro`. No ve nada del núcleo.

La API no abre `plataforma.db`: incluso la copia `pub_*` la regenera por Directus.

## Despliegue

Requiere Docker con Compose v2 y Python 3 (solo para generar la configuración).

```bash
git clone https://github.com/Capstone-2026-DISC/DISC-Scheduling.git
cd DISC-Scheduling
python3 scripts/configure.py          # crea .env con claves aleatorias; no se sube al repositorio
docker compose up --build --wait
docker compose logs configurar        # debe terminar con "verificación: todo correcto"
```

Los servicios `migrar` y `configurar` corren una vez: el primero crea la base desde el esquema y el segundo deja listos los roles, permisos y usuarios de Directus, incluido un rol y un token por grupo, y comprueba los permisos. La API arranca cuando `configurar` terminó bien. Si termina con error, el despliegue no está bien.

| Servicio | Puerto | Para qué |
| --- | --- | --- |
| `api` | 8000 | API en FastAPI. Documentación interactiva en http://localhost:8000/docs |
| `frontend` | 3000 | Interfaz web |
| `directus` | 8055 | Único acceso a los datos, también para los módulos de Proyecto Integrador. Cuenta de emergencia con `ADMIN_EMAIL` y `ADMIN_PASSWORD` del `.env` |
| `modulo-simulado` | 8090 | Módulo de ejemplo, solo con el perfil `demo` |

Todos los puertos escuchan solo en `127.0.0.1`.

**Usuarios iniciales.** Se crean en el primer arranque, con las claves `SEED_ADMIN_PASSWORD` y `SEED_TEST_PASSWORD` del `.env`.

| Usuario | Rol |
| --- | --- |
| `encargado.docente@example.com` | Administrador, con todos los permisos |
| `usuario.prueba@example.com` | Consulta, solo lectura en el DISC |

**Datos y respaldos.** La base vive en el volumen `plataforma_data`. El RUT y el correo de las personas se guardan cifrados con `DATA_KEYS` e `INDEX_KEY` del `.env`: respáldelas por separado, porque sin ellas esos datos no se pueden recuperar.

**Detener.** `docker compose down` conserva los datos. `docker compose down -v` los borra.

**Antes de usar datos reales.** El tráfico va por HTTP y la base no está cifrada en disco. Para exponerlo en la red hay que poner HTTPS delante (por ejemplo Caddy con una CA interna) y cifrar el volumen del servidor. Mientras tanto, úsese con los datos de prueba de `datos_prueba/`.

## Probar la API

Con el stack arriba, FastAPI publica su documentación en:

| Dirección | Qué es |
| --- | --- |
| http://localhost:8000/docs | Swagger UI: lista todos los endpoints y permite probarlos desde el navegador |
| http://localhost:8000/redoc | La misma documentación en lectura |
| http://localhost:8000/openapi.json | El contrato OpenAPI, para generar clientes |
| http://localhost:8000/health | Estado del servicio |

Para probar un endpoint protegido desde Swagger UI:

1. Abra `POST /auth/login`, pulse «Try it out» y envíe `{"email": "usuario.prueba@example.com", "clave": "<SEED_TEST_PASSWORD del .env>"}`.
2. Copie el `access_token` de la respuesta (dura 10 minutos; `POST /auth/refresh` entrega otro).
3. Pulse «Authorize» arriba a la derecha, pegue el token y confirme. Desde ahí `GET /salas`, `GET /periodos` y el resto de las lecturas responden con los permisos de ese usuario.

Lo mismo con `curl`:

```bash
TOKEN=$(curl -s localhost:8000/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"usuario.prueba@example.com","clave":"<SEED_TEST_PASSWORD>"}' | jq -r .access_token)
curl -s localhost:8000/salas -H "Authorization: Bearer $TOKEN"
```

El usuario de prueba solo lee. Para crear o modificar datos, entre con `encargado.docente@example.com` y `SEED_ADMIN_PASSWORD`.

## Módulo de prueba

`ejemplos/modulo_simulado/` es un módulo de Proyecto Integrador mínimo. Sirve de modelo para los grupos y para comprobar la integración.

```bash
docker compose --profile demo up --build
```

Abra http://localhost:8090. El módulo habla solo con Directus, con el token de su grupo (`SAT_TOKEN_G1` del `.env`), y muestra:

- el catálogo y el horario aprobado que publica el core (`pub_*`, solo lectura);
- su propia colección `sat_g1_registro`, donde puede guardar y eliminar registros (el borrado es lógico);
- el botón «Probar mis límites», que intenta lo que no debe, como leer datos personales o escribir en la colección de otro grupo, y muestra que Directus lo rechaza.

Para otro grupo se cambian `GRUPO`, `DIRECTUS_TOKEN` y `DIRECTUS_URL`. Detalles en [su README](ejemplos/modulo_simulado/README.md).

## Alcance actual

| Parte | Estado |
| --- | --- |
| Base de datos, roles, permisos por departamento y auditoría | Disponible |
| Login con JWT, renovación de sesión y bloqueo por intentos | Disponible |
| API de catálogo, horarios, finanzas y usuarios, documentada en `/docs` | Disponible |
| Importación de CSV con plantillas y errores explicados por fila | Disponible |
| Directus como capa de acceso a los datos, y réplica para los módulos de los grupos | Disponible |
| Interfaz web | En desarrollo |
| Generación de horarios con el motor de optimización | Pendiente de integrar |
| Cálculo del costo docente contra el presupuesto | Pendiente |
| Componente predictivo | Esqueleto |

## Desarrollo y pruebas

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest -q tests ../datos_prueba/test_datos.py ../plantillas_importacion/test_validar.py ../ejemplos/modulo_simulado/test_modulo.py
cd .. && python db/probar_esquema.py db/esquema_plataforma.sql
cd backend && python -m pytest -q tests_integracion      # con el stack arriba (docker compose up)
```

Antes de subir cambios, `ruff check .` y `ruff format --check .` (configurados en `pyproject.toml`) deben pasar.

El CI corre en cuatro etapas, y cada una espera a la anterior:

| Etapa | Qué revisa |
| --- | --- |
| 1. Estilo, secretos y frontend | `ruff`, búsqueda de claves en el historial con gitleaks, y compilación del frontend |
| 2. Esquema, permisos y pruebas unitarias | Esquema y matriz de permisos generados al día, pruebas de la API, de los datos de prueba y de las plantillas |
| 3. Integración con el stack real | Levanta Directus, API, frontend y el módulo de ejemplo con Docker Compose; comprueba los permisos reales y corre las pruebas de integración |
| 4. Imágenes | Construye las imágenes de la API y del frontend; solo se publican desde `main` |

Además, cada pull request revisa que venga de la rama que corresponde y que su título siga el formato de commits convencionales (`feat(api): add room listing`). Dependabot propone las actualizaciones de dependencias cada semana.

## Estructura

| Carpeta | Contenido |
| --- | --- |
| `backend/` | API en FastAPI, con módulos base, financiero y predictivo |
| `frontend/` | Interfaz en Next.js |
| `db/` | Esquema SQLite y su generador y pruebas |
| `ejemplos/modulo_simulado/` | Módulo de ejemplo de Proyecto Integrador |
| `plantillas_importacion/` | Plantillas CSV y XLSX por colección, con su validador |
| `datos_prueba/` | Generador de datos ficticios y reproducibles |
| `docs/` | Documentación técnica |
| `scripts/` | Generación de la configuración local |

## Documentación

- [Base técnica del backend](docs/backend.md): autenticación, cifrado, auditoría, borrado lógico y satélites.
- [Matriz de roles y permisos](docs/matriz_permisos.md)
- [Plantillas de importación](plantillas_importacion/README.md)
- [Datos de prueba](datos_prueba/DATOS_DE_PRUEBA.md)

## Equipo

| Integrante | Rol |
| --- | --- |
| Nicolás Álvarez Díaz | Estudiante |
| Fabián Carrasco Pallotti | Estudiante |
| Cristian Jiménez Fuentes | Estudiante |
| Dr. Brian Keith Norambuena | Profesor guía |
| Dr. Aldo Quelopana Retamales | Encargado docente |

Proyecto del Departamento de Ingeniería de Sistemas y Computación, Universidad Católica del Norte, Antofagasta.
