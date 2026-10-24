# Satélites (módulos de Proyecto Integrador)


Los grupos de Proyecto Integrador usan el mismo Directus y el mismo archivo que el núcleo, y se separan por permisos y por tablas, no por instancia.

- **Tablas.** `pub_*` es una copia derivada (catálogo del DISC y horario de la propuesta aprobada) y cada grupo tiene `sat_<grupo>_registro` (`sat_g1_registro` a `sat_g4_registro`, con borrado lógico por trigger).
- **Publicación.** `python -m app.publicacion` o `POST /publicacion` (permiso `horarios.exportar`) regenera `pub_*` por Directus con la cuenta de servicio, que lee el núcleo sin ver personas, docentes, nombramientos, finanzas ni auditoría. Directus es atómico por colección, no entre colecciones: durante una publicación un grupo podría ver una tabla ya nueva junto a otra vieja, y basta con repetir la lectura.
- **Permisos de cada grupo (`g1` a `g4`).** Un rol y un token estático (`SAT_TOKEN_G1` a `G4` del `.env`). Lee `pub_*`, y solo escribe en su colección, con borrado lógico y sin permiso de `DELETE`. No ve el núcleo, ni usuarios, ni roles, ni la colección de otro grupo, y su rol no es de la plataforma, así que no puede iniciar sesión como persona en la API. El configurador lo comprueba contra el Directus real.
- **Compartir archivo tiene un costo.** Un fallo de configuración de permisos expondría el núcleo a los grupos, y el registro de actividad queda en el mismo lugar. Por eso las pruebas de integración y el paso `verificar` revisan que un grupo reciba 403 en todo lo que no es suyo.
- **Límite de peticiones.** Directus limita por IP, y como la API concentra a todas las personas en una sola IP, el límite está desactivado. Los módulos de los grupos **no** tienen un límite de peticiones hoy. Si se necesita, hay que ponerlo en un proxy delante.
- `ejemplos/modulo_simulado/` es un módulo de ejemplo que usa exactamente este camino. Se levanta con `docker compose --profile demo up --build` y sirve de modelo para los grupos.
- Para más colecciones de un grupo se crean con el prefijo `sat_<grupo>_`, se agregan al esquema y a `permisos_de_grupo` en `directus_matriz.py`.

## Módulo de prueba

`ejemplos/modulo_simulado/` es un módulo de Proyecto Integrador mínimo. Sirve de modelo para los grupos y para comprobar la integración.

```bash
docker compose --profile demo up --build
```

Abra http://localhost:8090. El módulo habla solo con Directus, con el token de su grupo (`SAT_TOKEN_G1` del `.env`), y muestra:

- el catálogo y el horario aprobado que publica el core (`pub_*`, solo lectura);
- su propia colección `sat_g1_registro`, donde puede guardar y eliminar registros (el borrado es lógico);
- el botón «Probar mis límites», que intenta lo que no debe, como leer datos personales o escribir en la colección de otro grupo, y muestra que Directus lo rechaza.

Para otro grupo se cambian `GRUPO`, `DIRECTUS_TOKEN` y `DIRECTUS_URL`. Detalles en [su README](https://github.com/Capstone-2026-DISC/DISC-Scheduling/blob/main/ejemplos/modulo_simulado/README.md).
