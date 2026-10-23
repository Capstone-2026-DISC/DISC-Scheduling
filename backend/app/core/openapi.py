"""Textos comunes de la documentación OpenAPI (/docs, /redoc, /openapi.json)."""

DESCRIPCION = """
API del módulo base de la plataforma de apoyo a la programación académica del DISC.

**Autenticación.** `POST /auth/login` entrega un token de acceso (JWT, dura 10 minutos) y un refresh token (7 días,
rota en cada uso). Las demás rutas piden `Authorization: Bearer <token de acceso>`. En esta página use el botón
*Authorize* y pegue el token de acceso.

**Permisos.** Cada ruta exige un permiso (se indica en su descripción). El alcance es por departamento: un usuario
solo lee y edita datos de los departamentos donde tiene el permiso.

**Borrado.** Ningún `DELETE` borra de verdad: marca la fila como eliminada y deja de aparecer en las consultas.

**Errores.** Todas las respuestas de error traen `{"detail": "mensaje en español"}`.
""".strip()

ETIQUETAS = [
    {"name": "estado", "description": "Disponibilidad del servicio."},
    {"name": "autenticación", "description": "Inicio y cierre de sesión, renovación de tokens y cambio de clave."},
    {"name": "usuarios y roles", "description": "Usuarios, roles y permisos. Exige `usuarios.gestionar`."},
    {"name": "catálogo", "description": "Datos maestros: periodos, programas, asignaturas, salas, docentes y ayudantes."},
    {"name": "catálogo (datos personales)", "description": "Personas con RUT y correo, que se guardan cifrados. "
                                                         "Leerlas exige `personas.ver_datos_personales` y queda auditado."},
    {"name": "horarios", "description": "Paralelos, sesiones, restricciones y propuestas de horario."},
    {"name": "finanzas", "description": "Tarifas, presupuestos, escenarios y nombramientos."},
    {"name": "importación", "description": "Carga de datos desde CSV con las plantillas, con informe de errores por fila."},
    {"name": "satélites", "description": "Publicación de la réplica de solo lectura para los módulos de Proyecto Integrador."},
    {"name": "predictivo (esqueleto)", "description": "Módulo aún sin implementar."},
]

# Respuestas de error que cualquier ruta protegida puede devolver
RESPUESTAS = {
    401: {"description": "Falta el token, es inválido o venció. Renueve con `/auth/refresh` o inicie sesión de nuevo."},
    403: {"description": "El usuario no tiene el permiso, o no lo tiene en ese departamento. El intento queda auditado."},
    422: {"description": "El cuerpo o los parámetros no cumplen la validación; `detail` dice qué corregir."},
}
ERRORES_ESCRITURA = {
    404: {"description": "No existe, o ya fue eliminado."},
    409: {"description": "Choca con una regla de datos (clave repetida, referencia inexistente, valor no permitido)."},
}
