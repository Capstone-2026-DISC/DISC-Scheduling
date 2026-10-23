"""POST /importaciones/{coleccion}: valida un CSV con la plantilla de la colección y, si se pide, lo carga.

El cuerpo es el CSV (Content-Type: text/csv). Sin `confirmar` solo valida y deja la importación en 'lista' o
'con_errores'. Con `confirmar=true` carga todas las filas en una sola transacción, o ninguna. Cada fila cruda y sus
errores quedan en plataforma_fila_importada, y la persona y la IP en la auditoría."""
import hashlib
import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request

from ...core import audit
from ...core.db import escritura
from ...core.deps import Usuario, get_cifrador, get_conn, get_ip, usuario_actual
from ...core.recurso import traducir_error
from ...importacion.spec import ORDEN_DE_CARGA, PLANTILLAS
from ...importacion.validar import validar

router = APIRouter(prefix="/importaciones", tags=["importación"])
LIMITE_BYTES = 5_000_000


@router.get("/plantillas")
def plantillas(usuario: Usuario = Depends(usuario_actual)):
    return [{"coleccion": c, "descripcion": PLANTILLAS[c].descripcion, "permiso": PLANTILLAS[c].permiso_edicion,
             "depende_de": list(PLANTILLAS[c].dependencias), "columnas": [x.nombre for x in PLANTILLAS[c].columnas]}
            for c in ORDEN_DE_CARGA if usuario.tiene(PLANTILLAS[c].permiso_edicion)]


@router.post("/{coleccion}")
async def importar(coleccion: str, request: Request, confirmar: bool = False,
                   usuario: Usuario = Depends(usuario_actual), conn: sqlite3.Connection = Depends(get_conn),
                   ip: str | None = Depends(get_ip), cif=Depends(get_cifrador)):
    plantilla = PLANTILLAS.get(coleccion)
    if plantilla is None:
        raise HTTPException(404, "No hay plantilla para esa colección")
    if not usuario.tiene(plantilla.permiso_edicion):
        audit.registrar(conn, usuario_id=usuario.id, ip=ip, accion="acceso_denegado", resultado="denegado",
                        entidad=plantilla.tabla_db, detalle={"operacion": "importar", "permiso": plantilla.permiso_edicion})
        raise HTTPException(403, f"Falta el permiso {plantilla.permiso_edicion}")
    cuerpo = await request.body()
    if len(cuerpo) > LIMITE_BYTES:
        raise HTTPException(413, "El archivo supera los 5 MB")
    try:
        texto = cuerpo.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(422, "El archivo debe estar en UTF-8. Guárdelo como CSV UTF-8 desde la planilla.") from None
    informe = validar(plantilla, texto, conn, cif)
    # alcance por departamento: cada fila se carga solo donde el usuario tiene el permiso
    for f in informe["filas"]:
        depto = _departamento_de(conn, f["destino"])
        if not f["errores"] and depto is not None and not usuario.puede_en(plantilla.permiso_edicion, depto):
            f["errores"].append({"columna": "departamento", "gravedad": "bloqueante",
                                 "falla": "No tiene permiso para cargar datos en ese departamento.",
                                 "como_corregir": "Quite la fila o pida el permiso al administrador."})
            informe["ok"] = False
            informe["resumen"]["con_errores"] += 1
            informe["resumen"]["validas"] -= 1
    estado = "lista" if informe["ok"] else "con_errores"
    try:
        with escritura(conn, usuario.id, ip):
            imp_id = conn.execute(
                "INSERT INTO plataforma_importacion (departamento_id, fuente, version_importador, archivo_nombre, archivo_sha256, estado, creada_por) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (1, plantilla.fuente, f"{coleccion}@1", request.headers.get("x-archivo", f"{coleccion}.csv")[:200],
                 hashlib.sha256(cuerpo).hexdigest(), estado, usuario.id)).lastrowid
            conn.executemany(
                "INSERT INTO plataforma_fila_importada (importacion_id, numero_fila, datos, errores) VALUES (?, ?, ?, ?)",
                [(imp_id, f["fila"], json.dumps(_proteger(plantilla, f["datos"], cif), ensure_ascii=False),
                  json.dumps(f["errores"], ensure_ascii=False)) for f in informe["filas"]])
            if confirmar and informe["ok"]:
                for f in informe["filas"]:
                    columnas = {k: v for k, v in f["destino"].items() if v is not None and k != "-"}
                    conn.execute(f"INSERT INTO {plantilla.tabla_db} ({', '.join(columnas)}) VALUES ({', '.join('?' * len(columnas))})",
                                 list(columnas.values()))
                conn.execute("UPDATE plataforma_importacion SET estado = 'confirmada' WHERE id = ?", (imp_id,))
                estado = "confirmada"
            audit.registrar(conn, usuario_id=usuario.id, ip=ip, accion="importacion", entidad="plataforma_importacion",
                            entidad_id=imp_id, detalle={"coleccion": coleccion, "estado": estado, **informe["resumen"]})
    except sqlite3.Error as exc:
        raise traducir_error(exc) from exc
    for f in informe["filas"]:
        f.pop("destino", None)
    return {"importacion_id": imp_id, "estado": estado, **informe}


def _proteger(plantilla, datos: dict, cif) -> dict:
    """La fila cruda se conserva para poder explicar errores, pero el RUT y el correo van cifrados."""
    return {k: (cif.cifrar(str(v), f"plataforma_fila_importada.datos.{k}") if v is not None and _es_pii(plantilla, k) else v)
            for k, v in datos.items()}


def _es_pii(plantilla, nombre: str) -> bool:
    return any(c.nombre == nombre and c.es_pii for c in plantilla.columnas)


def _departamento_de(conn, destino: dict) -> int | None:
    if "departamento_id" in destino:
        return destino["departamento_id"]
    if "periodo_id" in destino:
        fila = conn.execute("SELECT departamento_id FROM catalogo_periodo WHERE id = ?", (destino["periodo_id"],)).fetchone()
        return None if fila is None else fila[0]
    return None
