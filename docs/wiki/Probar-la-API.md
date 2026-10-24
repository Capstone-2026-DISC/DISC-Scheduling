# Probar la API

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

## Documentación de la API y CORS

La API se documenta sola desde el código: `/docs` (Swagger), `/redoc` y `/openapi.json`. Cada operación tiene resumen, descripción con el permiso que exige y sus respuestas de error, y las pruebas fallan si alguna queda sin documentar. Para llamar a rutas protegidas en Swagger, use *Authorize* con el token de acceso.

El navegador solo puede llamar a la API desde los orígenes de `CORS_ORIGINS` (por defecto `http://localhost:3000`, separados por comas; no se admite `*`). Sin orígenes configurados no se habilita CORS. Los tokens van en el encabezado `Authorization`, no en cookies, así que CORS no admite credenciales.
