# Despliegue

Requiere Docker con Compose v2 y Python 3 (solo para generar la configuración).


```bash
python3 scripts/configure.py            # crea .env con secretos aleatorios (no se sube)
docker compose up --build --wait
docker compose logs configurar          # roles, permisos y verificaciones de Directus
```

| Servicio | Puerto | Qué es |
| --- | --- | --- |
| `migrar` | | Una sola vez: crea `plataforma.db` desde el esquema si no existe |
| `directus` | 8055 | Directus sobre `plataforma.db`. Es lo único que abre ese archivo en funcionamiento normal, para las personas y para los grupos de Proyecto Integrador |
| `configurar` | | Una sola vez: carga roles y permisos, crea usuarios y un rol con token por grupo, publica la copia `pub_*` y falla si alguna verificación no se cumple |
| `api` | 8000 | FastAPI. Arranca cuando `configurar` terminó bien |
| `frontend` | 3000 | Interfaz web (Next.js) |

El orden es `migrar`, `directus`, `configurar`, `api`, `frontend`. Las claves de los usuarios iniciales salen de `SEED_ADMIN_PASSWORD` y `SEED_TEST_PASSWORD` del `.env`: `encargado.docente@example.com` (rol Administrador, todos los permisos) y `usuario.prueba@example.com` (consulta, solo lectura en el DISC). El departamento DISC es el id 1 y existe siempre. Todos los puertos escuchan solo en `127.0.0.1`.

**Datos y respaldos.** La base vive en el volumen `plataforma_data`. El RUT y el correo de las personas se guardan cifrados con `DATA_KEYS` e `INDEX_KEY` del `.env`: respáldelas por separado, porque sin ellas esos datos no se pueden recuperar.

**Detener.** `docker compose down` conserva los datos. `docker compose down -v` los borra.

**Antes de usar datos reales.** El tráfico va por HTTP y la base no está cifrada en disco. Para exponerlo en la red hay que poner HTTPS delante (por ejemplo Caddy con una CA interna) y cifrar el volumen del servidor. Mientras tanto, úsese con los datos de prueba de `datos_prueba/`.
