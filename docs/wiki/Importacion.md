# Importación

Hay una plantilla por colección en `plantillas_importacion/` (CSV y XLSX, con una fila de ejemplo ficticia) y su README con columnas, tipos, reglas y orden de carga. `POST /importaciones/{coleccion}` valida el CSV y, con `?confirmar=true`, lo envía a Directus en una sola petición por colección, que es todo o nada. Cada error dice la fila, la columna, qué falló y cómo corregirlo, y la importación queda registrada en `plataforma_importacion` y en la auditoría. La misma especificación (`backend/app/importacion/spec.py`) genera las plantillas, el README y las reglas de validación.
