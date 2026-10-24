# Patrones de diseño

Los patrones que el código usa hoy y dónde están. Sirve para reconocerlos al leer o ampliar el sistema.

## Estructura general

| Patrón | Dónde | Para qué |
| --- | --- | --- |
| Arquitectura en capas | `router` → `service` → `repository` en cada módulo | El router habla HTTP, el servicio aplica las reglas y el repositorio habla con Directus |
| Monolito modular con registro de plugins | `app/registry.py` y la variable `MODULES` | Cada módulo es un paquete con su `router`; se activan por configuración |
| Fábrica de aplicación | `create_app()` en `app/main.py` | La aplicación se arma con su configuración y su transporte, lo que permite probarla con un Directus simulado |
| Inyección de dependencias | `Depends(...)` de FastAPI en `core/deps.py` | Los routers reciben el usuario, la IP y el cliente de Directus ya resueltos |

## Acceso a datos

| Patrón | Dónde | Para qué |
| --- | --- | --- |
| Fachada | `Directus` en `core/directus.py` | Una sola clase esconde la API REST de Directus, los tokens y las cabeceras |
| Repositorio genérico + descriptor declarativo | `Recurso` y `Repositorio` en `core/recurso.py` | Cada colección se declara con su tabla y sus campos escribibles; el repositorio hace el resto |
| Fábrica de routers | `crear_router()` en `core/crud.py` | De un `Recurso` sale el CRUD completo con su documentación |
| Capa anticorrupción | `traducir()` y `exigir()` en `core/directus.py` | Los errores de Directus se convierten en errores propios de la API (por ejemplo 403 oculto → 409) |
| Borrado lógico (tombstone) | `eliminado_en` y `eliminado_por`, con triggers | Nada se borra: se marca |
| Modelo de lectura derivado | Tablas `pub_*` y `publicacion.py` | Los módulos de los grupos leen una copia sin datos personales |

## Seguridad y auditoría

| Patrón | Dónde | Para qué |
| --- | --- | --- |
| Control de acceso por roles con alcance | `requiere("permiso")` en `core/deps.py` y la matriz de `directus_matriz.py` | La API revisa el permiso lógico y Directus aplica el departamento |
| Defensa en profundidad | La API, los permisos de Directus y los triggers del esquema | Un fallo en una capa no abre los datos |
| Registro de solo inserción | `plataforma_auditoria` y `directus_activity` con triggers | La auditoría no se modifica ni se borra en 5 años |
| Índice ciego | `rut_indice` en `core/pii.py` | Buscar y exigir unicidad del RUT sin guardarlo en claro |
| Claves versionadas | `v1:<clave>:...` y `DATA_KEYS` | Rotar claves de cifrado sin perder datos antiguos |
| Lista de denegación | Tokens cerrados en la API | Invalidar un token de acceso antes de que venza |
| Caché con vencimiento y límite de tasa | `core/cache.py` y `core/ratelimit.py` | Evitar consultas repetidas y frenar intentos de inicio de sesión |

## Una sola fuente de verdad y generación

| Patrón | Dónde | Para qué |
| --- | --- | --- |
| Generación de código y documentos | `db/generar_esquema.py`, `directus_matriz.py`, `importacion/spec.py` | El esquema SQL, la matriz de permisos y las plantillas de importación se generan, y el CI comprueba que estén al día |
| Configuración idempotente | `configurar` en `directus_setup.py` | Se puede ejecutar de nuevo sin duplicar roles ni permisos, y termina verificando lo que dejó |

## Motores de horarios

| Patrón | Dónde | Para qué |
| --- | --- | --- |
| Adaptador (puertos y adaptadores) | `CpSatEngine` y `FetEngine` frente a `TimetableEngine` | Cada motor traduce el mismo problema a su propio formato |
| Método plantilla | `TimetableEngine.solve()` | Validar, medir, capturar fallos y verificar son iguales para todos; el motor solo implementa `_solve()` |
| Estrategia | Elegir el motor por nombre en tiempo de ejecución | Cambiar de motor sin tocar a quien lo usa |
| Registro y fábrica | `registry.create()` | Quien pide un horario no importa los adaptadores |
| Degradación controlada | `availability()` y el estado `unavailable` | Un motor ausente se informa en vez de romper el arranque |
| Modelo neutral (objeto de valor inmutable) | `TimetableProblem` y `Solution` | Ninguna parte del sistema depende de un motor |

## Pruebas

| Patrón | Dónde | Para qué |
| --- | --- | --- |
| Doble de prueba (fake) | `tests/falso.py` | Un Directus simulado para probar la lógica de la API |
| Prueba contra el sistema real | `tests_integracion/` | Lo que depende de Directus de verdad (permisos, departamentos) se prueba con el stack levantado |
| Verificador independiente | `motores/check.py` | Ninguna solución de un motor se acepta sin revisarla |

## Lo que todavía no hay

- No hay una cola de trabajos: los motores corren en la misma petición. Hará falta cuando se expongan por la API.
- No hay eventos entre módulos: se comunican por Directus y por llamadas directas.
