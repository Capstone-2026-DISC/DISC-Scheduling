"""Cliente de Directus: la única puerta de la API a los datos.

La API no abre el archivo SQLite. Todo pasa por Directus, que aplica los permisos por rol y departamento y registra
quién cambió qué. Hay dos formas de llamarlo:
  * con la sesión de la persona (token de acceso de Directus): lecturas y escrituras de datos, para que Directus
    sepa quién es y aplique sus permisos;
  * con el token del servicio (cuenta de mínimos privilegios): tareas que no son de una persona, como crear
    usuarios, contar intentos de acceso, escribir la auditoría de eventos o leer para publicar a los satélites.
"""

import json
import re
from dataclasses import dataclass

import httpx
from fastapi import HTTPException


class DirectusCaido(Exception):
    """Directus no responde."""


@dataclass
class Respuesta:
    estado: int
    cuerpo: dict | list | None

    @property
    def datos(self):
        return (self.cuerpo or {}).get("data") if isinstance(self.cuerpo, dict) else None

    @property
    def mensaje(self) -> str:
        errores = (self.cuerpo or {}).get("errors") if isinstance(self.cuerpo, dict) else None
        return "; ".join(e.get("message", "") for e in errores or [])

    @property
    def codigo(self) -> str:
        errores = (self.cuerpo or {}).get("errors") if isinstance(self.cuerpo, dict) else None
        return (errores[0].get("extensions", {}).get("code", "") if errores else "") or ""


class Directus:
    def __init__(self, url: str, servicio: str = "", transport: httpx.BaseTransport | None = None, timeout: float = 15):
        self.http = httpx.Client(base_url=url.rstrip("/"), timeout=timeout, transport=transport)
        self.servicio = servicio

    def cerrar(self):
        self.http.close()

    def _cabeceras(self, token: str | None, ip: str | None) -> dict:
        h = {}
        if token:
            h["Authorization"] = f"Bearer {token}"
        if ip:
            h["X-Forwarded-For"] = ip  # Directus lo usa para la IP de su registro de actividad
        return h

    def pedir(self, metodo: str, ruta: str, *, token: str | None = None, ip: str | None = None, **kw) -> Respuesta:
        try:
            r = self.http.request(metodo, ruta, headers=self._cabeceras(token, ip), **kw)
        except httpx.RequestError as exc:
            raise DirectusCaido(str(exc)) from exc
        try:
            cuerpo = r.json() if r.content else None
        except ValueError:
            cuerpo = None
        return Respuesta(r.status_code, cuerpo)

    def como_servicio(self, metodo: str, ruta: str, **kw) -> Respuesta:
        return self.pedir(metodo, ruta, token=self.servicio, **kw)

    # -- items ---------------------------------------------------------------------------------------
    def listar(
        self,
        coleccion: str,
        *,
        token: str | None,
        ip: str | None = None,
        filtro: dict | None = None,
        campos: str = "*",
        limite: int = 100,
        desplazamiento: int = 0,
        orden: str | None = "id",
    ) -> Respuesta:
        params = {"fields": campos, "limit": limite, "offset": desplazamiento}
        if orden:  # no todas las tablas tienen una columna id (catalogo_docente usa persona_id)
            params["sort"] = orden
        if filtro:
            params["filter"] = json.dumps(filtro)
        return self.pedir("GET", f"/items/{coleccion}", token=token, ip=ip, params=params)

    def uno(self, coleccion: str, clave, *, token: str | None, ip: str | None = None, campos: str = "*") -> Respuesta:
        return self.pedir("GET", f"/items/{coleccion}/{clave}", token=token, ip=ip, params={"fields": campos})


# ---- traducción de errores ---------------------------------------------------------------------------------
_SQLITE = re.compile(r"SQLITE_CONSTRAINT(?:_[A-Z]+)?: (.*)$", re.S)


def traducir(r: Respuesta, *, recurso: str = "", lectura_de_uno: bool = False) -> HTTPException:
    """Lleva un error de Directus al código HTTP y el mensaje que corresponden en esta API."""
    e, msg, cod = r.estado, r.mensaje, r.codigo
    if e == 401 or cod == "TOKEN_EXPIRED":
        return HTTPException(401, "Sesión inválida o vencida", headers={"WWW-Authenticate": "Bearer"})
    if e == 403:
        if lectura_de_uno:  # Directus responde 403 también cuando la fila no existe o es de otro departamento
            return HTTPException(404, "No encontrado")
        return HTTPException(403, "Sin permiso para esta operación")
    if e == 404:
        return HTTPException(404, "No encontrado")
    if e == 429:
        return HTTPException(429, "Demasiadas peticiones a Directus; reintente en un minuto")
    if cod == "RECORD_NOT_UNIQUE":
        return HTTPException(409, "Ya existe un registro con ese valor: " + re.sub(r"^Value ", "", msg)[:160])
    if cod == "FAILED_VALIDATION":
        if "departamento_id" in msg:
            return HTTPException(403, "Sin permiso para escribir en ese departamento")
        return HTTPException(422, msg[:300] or "Datos inválidos")
    m = _SQLITE.search(msg)
    if m:  # CHECK, FK, UNIQUE y los mensajes de los triggers del esquema (Directus los muestra solo a administradores)
        return HTTPException(409, f"No se pudo guardar: {m.group(1).strip()[:300]}")
    if e == 500 and cod == "INTERNAL_SERVER_ERROR":
        # Directus oculta el detalle a quien no es administrador: solo se sabe que la base rechazó el cambio
        return HTTPException(
            409,
            "La base de datos rechazó el cambio porque no cumple una regla de integridad (por ejemplo un valor "
            "fuera de lista, un código con minúsculas donde se exigen mayúsculas o una referencia que no existe).",
        )
    if e == 400:
        return HTTPException(422, msg[:300] or "Petición inválida")
    return HTTPException(502, "Error al hablar con Directus")


def exigir(r: Respuesta, **kw) -> Respuesta:
    """Devuelve la respuesta si fue exitosa; si no, lanza el HTTPException equivalente."""
    if r.estado >= 400:
        raise traducir(r, **kw)
    return r
