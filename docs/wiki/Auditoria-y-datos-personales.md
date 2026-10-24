# Auditoría y datos personales


- **Cambios de datos e inicios de sesión exitosos:** los registra Directus en `directus_activity` y `directus_revisions`, con usuario, IP (la real de la persona, que la API reenvía) y fecha. El configurador crea triggers que impiden modificar el registro y borrar lo de menos de 5 años.
- **Eventos que Directus no ve:** intentos fallidos, accesos denegados, cambios de permisos, lectura de datos personales, importaciones y publicaciones van a `plataforma_auditoria`, que es de solo inserción y se conserva 5 años.

## Borrado lógico

La API nunca emite `DELETE` sobre el núcleo: `DELETE /salas/1` actualiza `eliminado_en` y `eliminado_por`, y Directus oculta esas filas. Los roles no tienen permiso de borrar (salvo las asignaciones de un borrador), y un `DELETE` real, incluso del administrador de arranque, lo rechaza un trigger.

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
- Los CHECK del esquema impiden guardar en claro: un RUT o correo sin el prefijo `v1:` no entra. Directus, su registro de actividad y sus revisiones solo ven texto cifrado, y la auditoría nunca lleva el RUT.
- El dígito verificador lo validan la API y el importador, que explican cuál debería ser.
- `DATA_KEYS` (`k1=...,k2=...`, con `DATA_KEY_ID` para la que cifra) e `INDEX_KEY` son claves de 32 bytes en base64 que genera `scripts/configure.py`. **Respáldelas aparte de la base: sin ellas los datos cifrados no se recuperan.** Para rotar, agregue la clave nueva, cambie `DATA_KEY_ID`, reinicie y ejecute `docker compose run --rm configurar python -m app.rotar_claves`. Cambiar `INDEX_KEY` obliga a recalcular los índices.
- Lo que **no** se cifra: el nombre de las personas, los correos de inicio de sesión (`directus_users`) y el resto de la base. Para proteger el archivo completo hay que cifrar el volumen o el disco del servidor, y para el transporte poner un proxy con HTTPS delante.
