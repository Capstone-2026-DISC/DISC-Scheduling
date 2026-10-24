# Límites conocidos y pendiente


- El administrador de arranque de Directus es una cuenta de emergencia: puede escribir sin pasar por la API. Sus cambios quedan en el registro de actividad con su usuario.
- Si Directus cae, la API responde 503 y los módulos de los grupos también quedan sin servicio.
- Los módulos de los grupos no tienen límite de peticiones (ver Satélites).
- Un usuario tiene un solo rol y un solo departamento.
- Los módulos de corridas de FET y de cálculo de costos todavía solo tienen sus datos y permisos.
- Autenticación institucional para Directus.
