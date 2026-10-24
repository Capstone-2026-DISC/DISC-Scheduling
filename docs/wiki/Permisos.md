# Permisos

Cada rol de la plataforma (`administrador`, `encargado_docente`, `consulta`...) es un rol de Directus con una política que el configurador genera desde `identidad_rol_permiso`; ver [Matriz de permisos](Matriz-de-permisos.md), que se genera y el CI mantiene al día.

- **Departamento.** Cada permiso se limita al departamento del usuario, deducido de las claves foráneas. Al crear, el departamento del usuario se fija solo (preset) y no se puede apuntar a otro (validación). Los roles con `departamentos.ver_otros` no llevan filtro.
- **Lo que cuelga de un periodo** (paralelos, sesiones) hereda su departamento. Directus no puede comprobar al crear que se vea la fila a la que apunta una clave foránea, así que la API lo hace antes de enviar. Quien llame a Directus directamente con su sesión podría saltarse esa comprobación; es un riesgo conocido y acotado.
- **Cambiar los permisos de un rol** se hace con el configurador, no con la API: `docker compose run --rm configurar python -m app.directus_setup rol-permiso dar|quitar ROL PERMISO`.
- **Usuarios.** Se gestionan por la API con una cuenta de servicio que solo puede crear y modificar usuarios con roles de la plataforma, nunca borrarlos ni dar el rol Administrator de Directus. Cada persona tiene un solo rol y un solo departamento (`departamento_id` vacío = todos).
- **Errores.** Directus oculta el detalle de los rechazos de la base a quien no es administrador. La API explica las reglas más comunes antes de enviar (por ejemplo por qué no se puede aprobar un horario) y, si no, responde 409 con un mensaje general. Los triggers del esquema siguen siendo la red de seguridad.

La tabla completa de roles y permisos está en la [Matriz de permisos](Matriz-de-permisos.md).
