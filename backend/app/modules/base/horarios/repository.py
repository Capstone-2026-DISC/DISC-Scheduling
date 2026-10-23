"""Recursos de horarios. Los que no tienen departamento propio lo heredan del periodo."""
import sqlite3

from ....core.db import escritura
from ....core.recurso import Recurso

DEPTO_PERIODO = "(SELECT p.departamento_id FROM catalogo_periodo p WHERE p.id = t.periodo_id)"
DEPTO_PARALELO = ("(SELECT p.departamento_id FROM horarios_paralelo pa JOIN catalogo_periodo p ON p.id = pa.periodo_id "
                  "WHERE pa.id = t.paralelo_id)")

PARALELO = Recurso("horarios_paralelo",
                   ("periodo_id", "asignatura_id", "nrc", "codigo", "componente", "estado", "cupo_estimado",
                    "sesiones_semana", "requiere_laboratorio", "liga_id", "sesiones_seguidas",
                    "docentes_alternan", "observacion"), depto=DEPTO_PERIODO)
SESION = Recurso("horarios_sesion", ("paralelo_id", "numero", "duracion_bloques"), depto=DEPTO_PARALELO)
RESTRICCION = Recurso("horarios_restriccion",
                      ("departamento_id", "periodo_id", "naturaleza", "tipo", "alcance", "parametros", "peso",
                       "vigente_desde", "vigente_hasta", "activa", "nota"),
                      json_cols=("alcance", "parametros"))
PROPUESTA = Recurso("horarios_propuesta", (), depto=DEPTO_PERIODO, borrado_logico=False,
                    json_cols=("metricas",))


def aprobar_propuesta(conn: sqlite3.Connection, usuario_id: int, ip: str | None, propuesta_id: int) -> int:
    """Pasa la propuesta a 'aprobada'. Los triggers exigen horarios.aprobar en el departamento del periodo,
    que esté completa y sin violaciones, y reemplazan a la aprobada anterior."""
    with escritura(conn, usuario_id, ip):
        return conn.execute("UPDATE horarios_propuesta SET estado = 'aprobada' WHERE id = ?", (propuesta_id,)).rowcount
