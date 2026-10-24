"""POST /importaciones/{coleccion}: valida un CSV con la plantilla de la colección y, si se pide, lo carga.

El cuerpo es el CSV (Content-Type: text/csv). Sin `confirmar` solo valida y deja la importación en 'lista' o
'con_errores'. Con `confirmar=true` carga todas las filas de la colección en una sola petición a Directus, que es todo o
nada. Todo va con la sesión de quien importa, así que Directus aplica sus permisos y su registro de actividad. Cada fila
cruda y sus errores quedan en plataforma_fila_importada, con el RUT y el correo cifrados."""
import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Request

from ...core import audit
from ...core.deps import Usuario, get_cifrador, get_directus, get_ip, usuario_actual
from ...core.directus import Directus, exigir, traducir
from ...core.openapi import ERRORES_ESCRITURA, RESPUESTAS
from ...importacion.referencias import DirectusReferencias
from ...importacion.spec import ORDEN_DE_CARGA, PLANTILLAS
from ...importacion.validar import validar

router = APIRouter(prefix="/importaciones", tags=["importación"], responses={**RESPUESTAS, **ERRORES_ESCRITURA})
LIMITE_BYTES = 5_000_000


@router.get("/plantillas", summary="Plantillas que el usuario puede cargar",
            description="Solo requiere sesión iniciada: lista las colecciones que el usuario puede cargar según sus permisos "
                        "(`catalogo.importar` o `finanzas.editar`), con sus columnas y las colecciones que deben cargarse antes.")
def plantillas(usuario: Usuario = Depends(usuario_actual)):
    return [{"coleccion": c, "descripcion": PLANTILLAS[c].descripcion, "permiso": PLANTILLAS[c].permiso_edicion,
             "depende_de": list(PLANTILLAS[c].dependencias), "columnas": [x.nombre for x in PLANTILLAS[c].columnas]}
            for c in ORDEN_DE_CARGA if usuario.tiene(PLANTILLAS[c].permiso_edicion)]


@router.post("/{coleccion}", summary="Validar o cargar un CSV",
             description="El cuerpo es el CSV en UTF-8 (`Content-Type: text/csv`), con los encabezados de la plantilla. Sin `confirmar` solo "
                         "valida; con `confirmar=true` carga todas las filas o ninguna. La respuesta trae, por fila, la columna, qué falló y "
                         "cómo corregirlo. El permiso depende de la colección (`catalogo.importar` o `finanzas.editar`) y se aplica por "
                         "departamento. Cada importación queda registrada con usuario e IP.",
             responses={413: {"description": "El archivo supera los 5 MB."}, 422: {"description": "No está en UTF-8."}})
async def importar(coleccion: str, request: Request, confirmar: bool = False, usuario: Usuario = Depends(usuario_actual),
                   directus: Directus = Depends(get_directus), ip: str | None = Depends(get_ip), cif=Depends(get_cifrador)):
    plantilla = PLANTILLAS.get(coleccion)
    if plantilla is None:
        raise HTTPException(404, "No hay plantilla para esa colección")
    if not usuario.tiene(plantilla.permiso_edicion):
        audit.registrar(directus, usuario_id=usuario.mirror_id, ip=ip, accion="acceso_denegado", resultado="denegado",
                        entidad=plantilla.tabla_db, detalle={"operacion": "importar", "permiso": plantilla.permiso_edicion})
        raise HTTPException(403, f"Falta el permiso {plantilla.permiso_edicion}")
    cuerpo = await request.body()
    if len(cuerpo) > LIMITE_BYTES:
        raise HTTPException(413, "El archivo supera los 5 MB")
    try:
        texto = cuerpo.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(422, "El archivo debe estar en UTF-8. Guárdelo como CSV UTF-8 desde la planilla.") from None
    return _importar(plantilla, texto, cuerpo, request.headers.get("x-archivo", f"{coleccion}.csv")[:200], confirmar,
                     usuario, directus, ip, cif)


def _importar(plantilla, texto, crudo, nombre_archivo, confirmar, usuario, directus, ip, cif):
    informe = validar(plantilla, texto, DirectusReferencias(directus, usuario, ip, cif), cif)
    # alcance por departamento: cada fila se carga solo donde el usuario tiene el permiso
    for f in informe["filas"]:
        depto = f["destino"].get("departamento_id")
        if depto is None and "periodo_id" in f["destino"]:
            fila = directus.uno("catalogo_periodo", f["destino"]["periodo_id"], token=usuario.token, ip=ip, campos="departamento_id")
            depto = (fila.datos or {}).get("departamento_id")
        if not f["errores"] and depto is not None and not usuario.puede_en(plantilla.permiso_edicion, depto):
            f["errores"].append({"columna": "departamento", "gravedad": "bloqueante",
                                 "falla": "No tiene permiso para cargar datos en ese departamento.",
                                 "como_corregir": "Quite la fila o pida el permiso al administrador."})
            informe["ok"] = False
            informe["resumen"]["con_errores"] += 1
            informe["resumen"]["validas"] -= 1
    estado = "lista" if informe["ok"] else "con_errores"
    imp = exigir(directus.pedir("POST", "/items/plataforma_importacion", token=usuario.token, ip=ip, params={"fields": "id"}, json={
        "fuente": plantilla.fuente, "version_importador": f"{plantilla.coleccion}@1", "archivo_nombre": nombre_archivo,
        "archivo_sha256": hashlib.sha256(crudo).hexdigest(), "estado": estado, "creada_por": usuario.mirror_id}))
    imp_id = imp.datos["id"]
    if informe["filas"]:
        exigir(directus.pedir("POST", "/items/plataforma_fila_importada", token=usuario.token, ip=ip, json=[
            {"importacion_id": imp_id, "numero_fila": f["fila"],
             "datos": json.dumps(_proteger(plantilla, f["datos"], cif), ensure_ascii=False),
             "errores": json.dumps(f["errores"], ensure_ascii=False)} for f in informe["filas"]]))
    if confirmar and informe["ok"]:
        filas = [{k: v for k, v in f["destino"].items() if v is not None and k != "-"} for f in informe["filas"]]
        r = directus.pedir("POST", f"/items/{plantilla.tabla_db}", token=usuario.token, ip=ip, json=filas)
        if r.estado >= 400:
            directus.pedir("PATCH", f"/items/plataforma_importacion/{imp_id}", token=usuario.token, ip=ip, json={"estado": "con_errores"})
            raise traducir(r)
        exigir(directus.pedir("PATCH", f"/items/plataforma_importacion/{imp_id}", token=usuario.token, ip=ip, json={"estado": "confirmada"}))
        estado = "confirmada"
    audit.registrar(directus, usuario_id=usuario.mirror_id, ip=ip, accion="importacion", entidad="plataforma_importacion",
                    entidad_id=imp_id, detalle={"coleccion": plantilla.coleccion, "estado": estado, **informe["resumen"]})
    for f in informe["filas"]:
        f.pop("destino", None)
    return {"importacion_id": imp_id, "estado": estado, **informe}


def _proteger(plantilla, datos: dict, cif) -> dict:
    """La fila cruda se conserva para poder explicar errores, pero el RUT y el correo van cifrados."""
    return {k: (cif.cifrar(str(v), f"plataforma_fila_importada.datos.{k}") if v is not None and _es_pii(plantilla, k) else v)
            for k, v in datos.items()}


def _es_pii(plantilla, nombre: str) -> bool:
    return any(c.nombre == nombre and c.es_pii for c in plantilla.columnas)
