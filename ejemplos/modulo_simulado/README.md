# Módulo de ejemplo de Proyecto Integrador

Un módulo mínimo que muestra cómo se conecta un grupo al sistema. Sirve de modelo para los módulos reales y para probar los contratos de integración.

## Cómo se conecta

El módulo habla solo con la instancia de Directus de los satélites, con el token de su grupo. No usa el login ni los tokens del core.

| Qué hace | Cómo |
| --- | --- |
| Lee el catálogo y el horario aprobado | `GET /items/pub_*` (solo lectura, sin datos personales) |
| Guarda sus datos | `POST` y `PATCH` sobre `sat_<grupo>_registro` |
| Elimina un registro | `PATCH` de `eliminado_en`: el token del grupo no puede hacer `DELETE` |
| Comprueba sus límites | Intenta lo que no debe y espera un rechazo (botón «Probar mis límites») |

Los datos publicados por el core son estos: `pub_periodo`, `pub_programa`, `pub_asignatura`, `pub_sala`, `pub_paralelo` y `pub_horario`. Se regeneran con `POST /publicacion` del core.

## Ejecutarlo

Desde la raíz del repositorio, con el `.env` creado por `scripts/configure.py`:

```bash
docker compose --profile demo up --build
```

Abra http://localhost:8090. El perfil `demo` es opcional y no forma parte de la entrega: sin él, el módulo no se levanta.

## Límite de peticiones

Directus no limita hoy las peticiones de los módulos: comparte instancia con la API, que concentra a todas las personas en una sola IP. Aun así conviene cuidar el uso: abrir la página usa 7 consultas, y un módulo real que consulte mucho debería guardar en caché lo que lee del catálogo.

## Adaptarlo a otro grupo

Cambie estas variables, que están en `compose.yaml`:

| Variable | Valor |
| --- | --- |
| `GRUPO` | `g1`, `g2`, `g3` o `g4` |
| `DIRECTUS_TOKEN` | El token de ese grupo (`SAT_TOKEN_G1` a `SAT_TOKEN_G4` del `.env`) |
| `DIRECTUS_URL` | La dirección de Directus. Se cambia sin tocar el código, por ejemplo si hay un proxy delante |

## Pruebas

```bash
python -m pytest ejemplos/modulo_simulado/test_modulo.py
```

Usan un Directus simulado, así que no necesitan red ni Docker. Comprueban que el módulo solo toca las tablas `pub_*` y su colección, que el token nunca aparece en la página, que eliminar es siempre un borrado lógico y que, con permisos bien puestos, todos los intentos prohibidos son rechazados.
