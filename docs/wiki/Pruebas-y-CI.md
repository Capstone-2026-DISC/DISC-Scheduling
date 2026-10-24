# Pruebas y CI


| Qué | Dónde | Con qué |
| --- | --- | --- |
| Reglas de integridad del esquema | `db/probar_esquema.py` | SQLite en memoria |
| Lógica de la API | `backend/tests` | Un Directus simulado (`tests/falso.py`); no comprueba permisos |
| Permisos, departamentos, borrado lógico, cifrado y auditoría | `backend/tests_integracion` | El stack real con `docker compose up` |
| Datos de prueba, plantillas y módulo de ejemplo | `datos_prueba`, `plantillas_importacion`, `ejemplos/modulo_simulado` | Pytest |
| Permisos reales de Directus | `docker compose logs configurar` | El paso `verificar` del configurador |

```bash
cd backend
python -m pytest -q tests ../datos_prueba/test_datos.py ../plantillas_importacion/test_validar.py ../ejemplos/modulo_simulado/test_modulo.py
python -m pytest -q tests_integracion        # con el stack arriba y LOGIN_RATE_PER_MINUTE alto en el .env
```

## Datos de prueba

`datos_prueba/generar_datos.py` genera datos ficticios y reproducibles (semilla fija) para probar y demostrar, y `datos_prueba/DATOS_DE_PRUEBA.md` explica qué hay, cómo se generaron y el rango de RUT ficticios. Nunca se usan datos reales en el repositorio.

## Etapas del CI

El CI corre en cada pull request y en cada push a `main`, `test` y las ramas personales. Tiene cuatro etapas, y cada una espera a la anterior:

| Etapa | Qué revisa |
| --- | --- |
| 1. Estilo, secretos y frontend | `ruff check` y `ruff format --check`; `gitleaks` sobre todo el historial; `npm ci` y `npm run build` |
| 2. Esquema, permisos y pruebas unitarias | Esquema y matriz de permisos generados al día, pruebas de la API, de los datos de prueba y de las plantillas |
| 3. Integración con el stack real | Docker Compose con Directus, API, frontend y módulo de ejemplo; verificación de permisos del configurador; pruebas de integración; `/health` y `/docs` |
| 4. Imágenes | Construye las imágenes de la API y del frontend; solo se publican desde `main` |

Además, cada pull request pasa por dos revisiones cortas:

- **Origen:** `main` solo recibe cambios desde `test`, y `test` solo desde las ramas personales.
- **Título:** debe seguir commits convencionales, por ejemplo `feat(api): add room listing`.

Dependabot propone cada semana las actualizaciones de las dependencias de Python, npm, GitHub Actions y Docker.

Antes de subir cambios, `ruff check .` y `ruff format --check .` (configurados en `pyproject.toml`) deben pasar.
