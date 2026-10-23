"""Fábrica de routers CRUD sobre un Recurso. Aplica permisos con alcance por departamento, traduce los
errores de los triggers y registra los accesos denegados en la auditoría."""
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, create_model

from . import audit
from .deps import Usuario, get_conn, get_ip, requiere
from .recurso import Recurso, Repositorio, traducir_error


def modelo(nombre: str, campos: dict[str, tuple[Any, Any]], opcionales: bool = False) -> type[BaseModel]:
    """Modelo pydantic estricto. campos: nombre -> (tipo, valor por defecto o ... si es obligatorio)."""
    defs = {k: ((t | None, None) if opcionales else (t, d)) for k, (t, d) in campos.items()}
    return create_model(nombre, __config__=ConfigDict(extra="forbid"), **defs)


def crear_router(recurso: Recurso, *, ruta: str, etiqueta: str, ver: str, editar: str,
                 entrada: type[BaseModel], parcial: type[BaseModel],
                 depto_payload: tuple[str, str] | None = None, permite_crear: bool = True) -> APIRouter:
    """depto_payload = (campo del cuerpo, SQL que devuelve el departamento dado ese valor); por defecto se usa
    el campo departamento_id del cuerpo (o el DISC, id 1, si no viene)."""
    repo = Repositorio(recurso)
    router = APIRouter(prefix=f"/{ruta}", tags=[etiqueta])

    def denegar(conn, usuario, ip, operacion, clave, depto):
        audit.registrar(conn, usuario_id=usuario.id, ip=ip, accion="acceso_denegado", resultado="denegado",
                        entidad=recurso.tabla, entidad_id=clave, departamento_id=depto,
                        detalle={"operacion": operacion, "permiso": editar})
        raise HTTPException(403, "Sin permiso en ese departamento")

    def depto_del_cuerpo(conn, datos: dict) -> int | None:
        if recurso.depto is None:
            return None
        if depto_payload:
            campo, sql = depto_payload
            valor = datos.get(campo)
            fila = conn.execute(sql, (valor,)).fetchone() if valor is not None else None
            return None if fila is None else fila[0]
        return datos.get("departamento_id", 1)

    @router.get("")
    def listar(limite: int = Query(100, ge=1, le=500), desplazamiento: int = Query(0, ge=0),
               usuario: Usuario = Depends(requiere(ver)), conn: sqlite3.Connection = Depends(get_conn)):
        return repo.listar(conn, usuario, usuario.departamentos(ver), None, limite, desplazamiento)

    @router.get("/{clave}")
    def leer(clave: int, usuario: Usuario = Depends(requiere(ver)), conn: sqlite3.Connection = Depends(get_conn)):
        return repo.obtener(conn, usuario, usuario.departamentos(ver), clave)

    if permite_crear:
        @router.post("", status_code=201)
        def crear(datos: entrada, usuario: Usuario = Depends(requiere(editar)),  # type: ignore[valid-type]
                  conn: sqlite3.Connection = Depends(get_conn), ip: str | None = Depends(get_ip)):
            cuerpo = datos.model_dump(exclude_unset=True)
            depto = depto_del_cuerpo(conn, cuerpo)
            if recurso.depto is not None and not usuario.puede_en(editar, depto):
                denegar(conn, usuario, ip, "crear", None, depto)
            try:
                return {"id": repo.crear(conn, usuario.id, ip, cuerpo)}
            except sqlite3.Error as exc:
                raise traducir_error(exc) from exc

    @router.patch("/{clave}", status_code=204)
    def actualizar(clave: int, datos: parcial, usuario: Usuario = Depends(requiere(editar)),  # type: ignore[valid-type]
                   conn: sqlite3.Connection = Depends(get_conn), ip: str | None = Depends(get_ip)):
        cuerpo = datos.model_dump(exclude_unset=True)
        if recurso.depto is not None:
            actual = repo.departamento_de(conn, clave)
            if actual is None and not conn.execute(
                    f"SELECT 1 FROM {recurso.tabla} t WHERE t.{recurso.pk} = ?", (clave,)).fetchone():
                raise HTTPException(404, "No encontrado")
            if not usuario.puede_en(editar, actual):
                denegar(conn, usuario, ip, "actualizar", clave, actual)
            if "departamento_id" in cuerpo and not usuario.puede_en(editar, cuerpo["departamento_id"]):
                denegar(conn, usuario, ip, "mover_de_departamento", clave, cuerpo["departamento_id"])
        try:
            repo.actualizar(conn, usuario.id, ip, clave, cuerpo)
        except sqlite3.Error as exc:
            raise traducir_error(exc) from exc
        return Response(status_code=204)

    if recurso.borrado_logico:
        @router.delete("/{clave}", status_code=204)
        def eliminar(clave: int, usuario: Usuario = Depends(requiere(editar)),
                     conn: sqlite3.Connection = Depends(get_conn), ip: str | None = Depends(get_ip)):
            actual = repo.departamento_de(conn, clave)
            if recurso.depto is not None and not usuario.puede_en(editar, actual):
                if actual is None and not conn.execute(
                        f"SELECT 1 FROM {recurso.tabla} t WHERE t.{recurso.pk} = ?", (clave,)).fetchone():
                    raise HTTPException(404, "No encontrado")
                denegar(conn, usuario, ip, "eliminar", clave, actual)
            try:
                repo.eliminar(conn, usuario.id, ip, clave)
            except sqlite3.Error as exc:
                raise traducir_error(exc) from exc
            return Response(status_code=204)

    return router
