# Flujo de trabajo

## Ramas

| Rama | Para qué |
| --- | --- |
| `main` | Lo que está listo para entregar. Solo recibe cambios desde `test` |
| `test` | Integración y pruebas. Solo recibe cambios desde las ramas personales |
| `Nicolás`, `Cristian`, `Fabián` | Una rama por integrante, donde se trabaja a diario |

`main` y `test` están protegidas: exigen un pull request con una aprobación, que el CI pase y que la rama esté al día.

## Cómo se trabaja

1. Se trabaja y se sube a la rama personal. El CI corre en cada push.
2. Cuando el cambio está listo, se abre un pull request hacia `test`.
3. Otra persona del equipo revisa y aprueba. Si se sube algo nuevo, la aprobación se descarta y hay que revisar de nuevo.
4. De `test` a `main` se pasa solo después de revisar el conjunto.

## Commits y pull requests

- Conventional commits, en una línea y en inglés: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `ci:`, `build:`, `style:`, `chore:`. El título del pull request sigue el mismo formato.
- Un commit hace una sola cosa y lo que dice su título.
- Los identificadores, comentarios, docstrings, pruebas y mensajes de commit van en inglés; los textos que ve la gente (mensajes de la API, documentación) van en español. Los nombres del esquema de datos son del dominio y se conservan en español.

## Estilo del código

- Python 3.12 con `ruff` (120 columnas, configuración en `pyproject.toml`); clases en `PascalCase`.
- El formato lo decide la herramienta: si `ruff format --check` pasa, está bien.
- Las dependencias se fijan con versión exacta.

## Reglas que no se saltan

- Todo acceso a los datos pasa por Directus. Ninguna parte de la API abre el archivo de la base.
- Nunca se suben claves, tokens ni datos reales. El repositorio es público y solo lleva datos de prueba ficticios.
- Los cambios de esquema, de permisos y de datos de prueba se hacen en el generador, no a mano: el CI revisa que lo generado esté al día.
