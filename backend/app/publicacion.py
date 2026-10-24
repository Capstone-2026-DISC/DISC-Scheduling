"""Publicación para los módulos satélite.

Los grupos de Proyecto Integrador leen por Directus las tablas pub_*: una copia derivada del catálogo y del horario de la
propuesta aprobada, que vive en el mismo archivo que el núcleo pero se separa por permisos (cada grupo solo lee pub_* y solo
escribe en su sat_<grupo>_registro). Aquí no se copia ninguna persona, docente, nombramiento, finanza ni auditoría.

Todo pasa por Directus con la cuenta de servicio: el núcleo se lee y pub_* se regenera. La copia se reemplaza tabla por
tabla (Directus es atómico por colección, no entre colecciones), así que un grupo que lea justo durante la publicación
puede ver una tabla ya nueva junto a otra aún vieja; se resuelve repitiendo la lectura.

Uso: python -m app.publicacion        (o POST /publicacion con el permiso horarios.exportar)
"""
import json
import time

from .core.directus import Directus, exigir

COLUMNAS = {
    "pub_periodo": ("id", "codigo", "estado"),
    "pub_programa": ("id", "codigo", "nombre", "tipo"),
    "pub_asignatura": ("id", "codigo", "nombre", "area", "requiere_laboratorio"),
    "pub_sala": ("id", "codigo", "nombre", "capacidad", "es_laboratorio"),
    "pub_paralelo": ("id", "periodo_id", "asignatura_id", "codigo", "nrc", "componente", "cupo_estimado"),
    "pub_horario": ("id", "paralelo_id", "sesion", "dia", "bloque", "sala_codigo"),
}
ORDEN = list(COLUMNAS)
SIN_ELIMINADAS = {"eliminado_en": {"_null": True}}


def _leer(d: Directus, coleccion: str, campos: str, filtro: dict | None = None) -> list[dict]:
    p = {"fields": campos, "limit": -1, "sort": "id"}
    if filtro:
        p["filter"] = json.dumps(filtro)
    return exigir(d.como_servicio("GET", f"/items/{coleccion}", params=p)).datos or []


def extraer(d: Directus) -> dict[str, list[tuple]]:
    """Lee del núcleo, por Directus, lo que se publica. Sin personas, docentes, finanzas ni auditoría."""
    disc = {"departamento_id": {"_eq": 1}}
    periodos = _leer(d, "catalogo_periodo", "id,codigo,estado", disc)
    ids_periodo = {p["id"] for p in periodos}
    salas = _leer(d, "catalogo_sala", "id,codigo,nombre,capacidad,es_laboratorio,activa,eliminado_en", disc)
    sala_codigo = {s["id"]: s["codigo"] for s in salas}
    paralelos = [p for p in _leer(d, "horarios_paralelo", "id,periodo_id,asignatura_id,codigo,nrc,componente,cupo_estimado,eliminado_en")
                 if p["periodo_id"] in ids_periodo and not p["eliminado_en"]]
    ids_paralelo = {p["id"] for p in paralelos}
    aprobadas = {p["id"] for p in _leer(d, "horarios_propuesta", "id,periodo_id,estado") if p["estado"] == "aprobada" and p["periodo_id"] in ids_periodo}
    sesiones = {s["id"]: s for s in _leer(d, "horarios_sesion", "id,paralelo_id,numero,eliminado_en") if s["paralelo_id"] in ids_paralelo and not s["eliminado_en"]}
    horario = [(a["id"], sesiones[a["sesion_id"]]["paralelo_id"], sesiones[a["sesion_id"]]["numero"], a["dia"], a["bloque"],
                sala_codigo.get(a["sala_id"]))
               for a in _leer(d, "horarios_asignacion", "id,propuesta_id,sesion_id,dia,bloque,sala_id")
               if a["propuesta_id"] in aprobadas and a["sesion_id"] in sesiones]
    return {
        "pub_periodo": [(p["id"], p["codigo"], p["estado"]) for p in periodos],
        "pub_programa": [(p["id"], p["codigo"], p["nombre"], p["tipo"]) for p in _leer(d, "catalogo_programa", "id,codigo,nombre,tipo", {"_and": [disc, SIN_ELIMINADAS]})],
        "pub_asignatura": [(a["id"], a["codigo"], a["nombre"], a["area"], a["requiere_laboratorio"])
                           for a in _leer(d, "catalogo_asignatura", "id,codigo,nombre,area,requiere_laboratorio", {"_and": [disc, SIN_ELIMINADAS]})],
        "pub_sala": [(s["id"], s["codigo"], s["nombre"], s["capacidad"], s["es_laboratorio"]) for s in salas if s["activa"] and not s["eliminado_en"]],
        "pub_paralelo": [(p["id"], p["periodo_id"], p["asignatura_id"], p["codigo"], p["nrc"], p["componente"], p["cupo_estimado"]) for p in paralelos],
        "pub_horario": horario,
    }


def publicar(d: Directus) -> dict:
    """Reemplaza las tablas pub_* por Directus. Devuelve cuántas filas quedaron en cada una."""
    datos = extraer(d)
    for tabla in ORDEN + ["pub_estado"]:      # primero se vacía todo: si falla una lectura de arriba no se toca nada
        exigir(d.como_servicio("DELETE", f"/items/{tabla}", json={"query": {"filter": {"id": {"_gte": 0}}}}))
    for tabla in ORDEN:
        filas = [dict(zip(COLUMNAS[tabla], f)) for f in datos[tabla]]
        if filas:
            exigir(d.como_servicio("POST", f"/items/{tabla}", json=filas, params={"fields": "id"}))
    exigir(d.como_servicio("POST", "/items/pub_estado", json={"id": 1, "publicado_en": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                           params={"fields": "id"}))
    return {t: len(datos[t]) for t in ORDEN}


def main() -> None:
    from .core.config import get_settings
    s = get_settings()
    cuentas = publicar(Directus(s.directus_url, s.servicio_token))
    print("publicado:", ", ".join(f"{k}={v}" for k, v in cuentas.items()))


if __name__ == "__main__":
    main()
