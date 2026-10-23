"""Especificación de las plantillas de importación: una sola fuente para la validación, las plantillas CSV y XLSX,
la documentación y la carga por la API.

Cada columna dice su tipo y si es obligatoria. Las referencias a otras tablas se escriben con la clave natural
(código, RUT, NRC, periodo) y no con el id interno, porque es lo que la persona tiene a mano."""
from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class Col:
    nombre: str
    tipo: str                      # texto, entero, decimal, fecha, bool, enum, rut, periodo, codigo_asig
    requerido: bool = True
    ejemplo: str = ""
    regla: str = ""
    valores: tuple = ()            # para enum
    ref: str | None = None         # departamento, periodo, persona_rut, asignatura, paralelo_nrc, categoria_letra
    destino: str | None = None     # columna de la base; por defecto el nombre
    minimo: float | None = None
    maximo: float | None = None

    @property
    def es_pii(self) -> bool:
        """Datos personales: no se repiten en los mensajes de error y se guardan cifrados en las filas crudas."""
        return self.tipo == "rut" or self.nombre == "email"


@dataclass(frozen=True)
class Plantilla:
    coleccion: str
    descripcion: str
    columnas: tuple[Col, ...]
    clave: tuple[str, ...]         # columnas que identifican una fila (no se repite en el archivo ni en la base)
    tabla: str = ""
    fuente: str = "planilla_encargado"          # valor de plataforma_importacion.fuente
    permiso_edicion: str = "catalogo.importar"
    dependencias: tuple[str, ...] = ()

    @property
    def tabla_db(self) -> str:
        return self.tabla or self.coleccion


DEPTO = Col("departamento", "texto", False, "DISC", "Código del departamento; si se deja vacío es DISC.", ref="departamento")
PERIODO = Col("periodo", "periodo", True, "202620", "Año y semestre en seis dígitos, 10 o 20 al final. Debe existir.", ref="periodo")
# variantes que solo sirven para ubicar otra fila (la tabla destino no tiene esa columna): destino "-"
DEPTO_AUX = replace(DEPTO, destino="-")
PERIODO_AUX = replace(PERIODO, destino="-")
REF_DESTINO = {"departamento": "departamento_id", "periodo": "periodo_id", "persona_rut": "persona_id", "asignatura": "asignatura_id",
               "paralelo_nrc": "paralelo_id", "categoria_letra": "categoria_id"}
BOOL = lambda nombre, ej="0", regla="0 = no, 1 = sí.": Col(nombre, "bool", False, ej, regla)  # noqa: E731

PLANTILLAS: dict[str, Plantilla] = {p.coleccion: p for p in (
    Plantilla("catalogo_periodo", "Periodos académicos.", (
        DEPTO,
        Col("codigo", "periodo", True, "202710", "Año y semestre en seis dígitos, 10 o 20 al final."),
        Col("fecha_inicio", "fecha", False, "2027-03-08", "AAAA-MM-DD."),
        Col("fecha_fin", "fecha", False, "2027-07-17", "AAAA-MM-DD, posterior al inicio."),
        Col("estado", "enum", False, "planificacion", "Estado del periodo.", ("planificacion", "vigente", "cerrado")),
    ), ("departamento", "codigo")),
    Plantilla("catalogo_programa", "Programas y carreras.", (
        DEPTO, Col("codigo", "texto", True, "PRG9", "Código corto del programa."),
        Col("nombre", "texto", False, "Programa de prueba 9"),
        Col("tipo", "enum", False, "pregrado", "Tipo de programa.", ("pregrado", "postgrado", "servicio", "minor")),
    ), ("departamento", "codigo")),
    Plantilla("catalogo_asignatura", "Asignaturas.", (
        DEPTO, Col("codigo", "codigo_asig", False, "FAIC-00199", "Cuatro letras mayúsculas, guion y cinco dígitos. Vacío si Banner aún no lo asigna."),
        Col("nombre", "texto", True, "Asignatura de prueba 99"), Col("area", "texto", False, "Ficticia A"),
        BOOL("requiere_laboratorio", "0", "1 si exige laboratorio o computador."), BOOL("activa", "1"),
    ), ("codigo",)),
    Plantilla("catalogo_sala", "Salas y laboratorios.", (
        DEPTO, Col("codigo", "texto", True, "ZZ-199", "Código de la sala."), Col("nombre", "texto", False, "Sala de prueba 99"),
        Col("capacidad", "entero", False, "40", "Asientos.", minimo=1, maximo=1000),
        BOOL("es_laboratorio", "0", "1 si es laboratorio."),
        Col("administrada_por", "texto", False, "disc", "Quién administra la sala."), BOOL("activa", "1"),
    ), ("codigo",)),
    Plantilla("catalogo_persona", "Personas (datos personales: RUT y correo).", (
        Col("rut", "rut", True, "59999999-K", "Con dígito verificador válido; se acepta con o sin puntos."),
        Col("nombre", "texto", True, "Nombre Inventado Ejemplo"), Col("email", "texto", False, "nombre@ejemplo.invalid", "Correo con arroba."),
    ), ("rut",), fuente="academicos"),
    Plantilla("catalogo_docente", "Docentes (la persona debe existir).", (
        Col("rut", "rut", True, "59999999-K", "RUT de una persona ya cargada.", ref="persona_rut", destino="persona_id"),
        DEPTO, Col("tipo_contrato", "enum", True, "hora", "Contrato.", ("planta", "hora")), BOOL("activo", "1"),
    ), ("rut",), fuente="academicos", dependencias=("catalogo_persona",)),
    Plantilla("catalogo_ayudante", "Ayudantes (la persona debe existir).", (
        Col("rut", "rut", True, "59999998-1", "RUT de una persona ya cargada.", ref="persona_rut", destino="persona_id"),
        DEPTO, BOOL("activo", "1"),
    ), ("rut",), fuente="ayudantes", dependencias=("catalogo_persona",)),
    Plantilla("horarios_paralelo", "Oferta del periodo: un paralelo por fila.", (
        PERIODO, DEPTO_AUX,
        Col("asignatura", "codigo_asig", True, "FAIC-00101", "Código de una asignatura ya cargada.", ref="asignatura", destino="asignatura_id"),
        Col("nrc", "entero", False, "59101", "Código de Banner; vacío en paralelos nuevos.", minimo=1),
        Col("codigo", "texto", True, "C1", "C1, L01, T1."),
        Col("componente", "enum", False, "catedra", "Componente.", ("catedra", "laboratorio", "taller", "proyecto")),
        Col("estado", "enum", False, "ok", "Estado.", ("ok", "nueva", "inactiva")),
        Col("cupo_estimado", "entero", False, "35", "Cupo.", minimo=0),
        Col("sesiones_semana", "entero", False, "2", "Entre 1 y 6.", minimo=1, maximo=6),
        BOOL("requiere_laboratorio", "0", "Vacío hereda el de la asignatura."),
        BOOL("sesiones_seguidas", "0", "1 si las sesiones van seguidas."), BOOL("docentes_alternan", "0", "1 si dos docentes se alternan por módulos."),
        Col("observacion", "texto", False, "", "Texto libre."),
    ), ("periodo", "asignatura", "codigo", "componente"), dependencias=("catalogo_periodo", "catalogo_asignatura")),
    Plantilla("horarios_sesion", "Sesiones semanales de un paralelo.", (
        PERIODO_AUX, DEPTO_AUX,
        Col("nrc", "entero", True, "59101", "NRC de un paralelo ya cargado.", ref="paralelo_nrc", destino="paralelo_id", minimo=1),
        Col("numero", "entero", True, "1", "Número de la sesión dentro del paralelo.", minimo=1),
        Col("duracion_bloques", "entero", False, "1", "Entre 1 y 3.", minimo=1, maximo=3),
    ), ("periodo", "nrc", "numero"), tabla="horarios_sesion", dependencias=("horarios_paralelo",)),
    Plantilla("horarios_disponibilidad_docente", "Bloques en que un docente no puede, prefiere o evita dictar.", (
        PERIODO, DEPTO_AUX, Col("rut", "rut", True, "59999999-K", "RUT de un docente ya cargado.", ref="persona_rut", destino="docente_id"),
        Col("dia", "enum", True, "Lu", "Día.", ("Lu", "Ma", "Mi", "Ju", "Vi", "Sa")),
        Col("bloque", "enum", True, "A", "Bloque horario.", ("A", "B", "C", "D", "E", "F", "G")),
        Col("tipo", "enum", True, "no_disponible", "Tipo de marca.", ("no_disponible", "preferido", "evitar")),
    ), ("periodo", "rut", "dia", "bloque"), dependencias=("catalogo_docente",)),
    Plantilla("finanzas_tarifa", "Valor hora por categoría.", (
        Col("tipo_persona", "enum", True, "profesor_hora", "Tipo.", ("profesor_hora", "ayudante"), ref="categoria_letra", destino="categoria_id"),
        Col("letra", "texto", True, "A", "Letra de la categoría, una sola.", destino="-"),
        Col("valor_hora", "decimal", True, "12000", "Pesos por hora, mayor que cero.", minimo=0.01),
        Col("vigente_desde", "fecha", True, "2026-03-01", "AAAA-MM-DD."),
    ), ("tipo_persona", "letra", "vigente_desde"), permiso_edicion="finanzas.editar"),
    Plantilla("finanzas_presupuesto", "Presupuesto anual por tipo de persona.", (
        DEPTO, Col("anio", "entero", True, "2027", "Año.", minimo=2000, maximo=2100),
        Col("tipo_persona", "enum", True, "profesor_hora", "Tipo.", ("profesor_hora", "ayudante")),
        Col("monto_anual", "decimal", True, "18000000", "Pesos, no negativo.", minimo=0),
        Col("porcentaje_s1", "decimal", False, "50", "Porcentaje del primer semestre, 0 a 100.", minimo=0, maximo=100),
    ), ("departamento", "anio", "tipo_persona"), permiso_edicion="finanzas.editar"),
    Plantilla("finanzas_nombramiento", "Nombramientos de docentes por hora y ayudantes.", (
        PERIODO, DEPTO_AUX, Col("rut", "rut", True, "59999999-K", "RUT de una persona ya cargada.", ref="persona_rut", destino="persona_id"),
        Col("tipo_persona", "enum", True, "profesor_hora", "Tipo.", ("profesor_hora", "ayudante"), ref="categoria_letra", destino="categoria_id"),
        Col("letra", "texto", True, "A", "Letra de la categoría.", destino="-"),
        Col("nrc", "entero", False, "59101", "NRC del paralelo, si se asocia a uno.", ref="paralelo_nrc", destino="paralelo_id", minimo=1),
        Col("horas_semanales", "decimal", True, "4.5", "Mayor que cero.", minimo=0.01),
        Col("fecha_inicio", "fecha", True, "2026-08-03", "AAAA-MM-DD."), Col("fecha_fin", "fecha", True, "2026-12-19", "No anterior al inicio."),
        Col("origen", "enum", True, "manual", "De dónde viene.", ("horario", "g4", "manual")),
    ), ("periodo", "rut", "tipo_persona", "letra", "nrc", "fecha_inicio"), permiso_edicion="finanzas.editar",
        dependencias=("catalogo_persona", "horarios_paralelo")),
    Plantilla("proyeccion_inscripcion_historica", "Inscritos de periodos pasados.", (
        Col("asignatura", "codigo_asig", True, "FAIC-00101", "Código de una asignatura ya cargada.", ref="asignatura", destino="asignatura_id"),
        PERIODO, DEPTO_AUX, Col("fuente", "enum", True, "planilla", "Origen del dato.", ("planilla", "apa", "argos")),
        Col("inscritos", "entero", True, "30", "Cero o más.", minimo=0),
    ), ("asignatura", "periodo", "fuente"), fuente="historico", permiso_edicion="catalogo.importar",
        dependencias=("catalogo_asignatura", "catalogo_periodo")),
)}

ORDEN_DE_CARGA = ["catalogo_periodo", "catalogo_programa", "catalogo_asignatura", "catalogo_sala", "catalogo_persona",
                  "catalogo_docente", "catalogo_ayudante", "horarios_paralelo", "horarios_sesion",
                  "horarios_disponibilidad_docente", "finanzas_tarifa", "finanzas_presupuesto", "finanzas_nombramiento",
                  "proyeccion_inscripcion_historica"]
