"""Repositorio genérico de colecciones del núcleo sobre Directus.

Cada operación va con la sesión de la persona, así que los permisos por rol y departamento los aplica Directus. Nada de
esto abre SQLite ni arma SQL: se declara la colección y los campos que se pueden escribir, y se llama a su API.
El borrado es siempre lógico: se marca eliminado_en y eliminado_por, y los roles no tienen permiso de borrar.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException

from .deps import Usuario
from .directus import Directus, exigir


def ahora() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Recurso:
    tabla: str
    escribibles: tuple[str, ...]
    pk: str = "id"
    borrado_logico: bool = True
    json_cols: tuple[str, ...] = ()  # columnas TEXT con JSON validado
    autor: str | None = None  # columna donde queda quién lo creó (creada_por...), si existe
    orden: str = "id"


class Repositorio:
    def __init__(self, recurso: Recurso):
        self.r = recurso

    # -- lectura ---------------------------------------------------------------------------------------
    def _salida(self, fila: dict) -> dict:
        d = {k: v for k, v in fila.items() if k not in ("eliminado_en", "eliminado_por")}
        for c in self.r.json_cols:
            if isinstance(d.get(c), str):
                d[c] = json.loads(d[c])
        return d

    def listar(
        self,
        directus: Directus,
        usuario: Usuario,
        ip: str | None,
        limite: int,
        desplazamiento: int,
        filtros: dict | None = None,
    ) -> list[dict]:
        filtro = {c: {"_eq": v} for c, v in (filtros or {}).items()} or None
        r = exigir(
            directus.listar(
                self.r.tabla,
                token=usuario.token,
                ip=ip,
                filtro=filtro,
                limite=limite,
                desplazamiento=desplazamiento,
                orden=self.r.orden,
            )
        )
        return [self._salida(f) for f in r.datos or []]

    def obtener(self, directus: Directus, usuario: Usuario, ip: str | None, clave) -> dict:
        r = exigir(directus.uno(self.r.tabla, clave, token=usuario.token, ip=ip), lectura_de_uno=True)
        if not r.datos or (self.r.borrado_logico and r.datos.get("eliminado_en")):
            raise HTTPException(404, "No encontrado")
        return self._salida(r.datos)

    # -- escritura -------------------------------------------------------------------------------------
    def _validar(self, datos: dict) -> dict:
        extra = set(datos) - set(self.r.escribibles)
        if extra:
            raise HTTPException(422, f"Campos no permitidos: {', '.join(sorted(extra))}")
        return {
            k: (json.dumps(v, ensure_ascii=False) if k in self.r.json_cols and not isinstance(v, str) else v)
            for k, v in datos.items()
        }

    def crear(self, directus: Directus, usuario: Usuario, ip: str | None, datos: dict) -> int:
        cuerpo = self._validar(datos)
        if self.r.autor and usuario.mirror_id:
            cuerpo[self.r.autor] = usuario.mirror_id
        r = exigir(
            directus.pedir(
                "POST", f"/items/{self.r.tabla}", token=usuario.token, ip=ip, json=cuerpo, params={"fields": self.r.pk}
            )
        )
        if r.estado == 204 or not r.datos:
            raise HTTPException(500, "Directus creó el registro pero no devolvió su id")
        return r.datos[self.r.pk]

    def _modificar(
        self, directus: Directus, usuario: Usuario, ip: str | None, clave, cuerpo: dict, operacion: str, al_denegar
    ) -> None:
        r = directus.pedir("PATCH", f"/items/{self.r.tabla}/{clave}", token=usuario.token, ip=ip, json=cuerpo)
        if r.estado == 403:
            # Directus responde 403 tanto si no hay permiso como si la fila no existe: se distingue leyéndola
            existe = directus.uno(self.r.tabla, clave, token=usuario.token, ip=ip, campos=self.r.pk)
            if existe.estado in (403, 404):
                raise HTTPException(404, "No encontrado")
            al_denegar(operacion)
            raise HTTPException(403, "Sin permiso para esta operación")
        exigir(r)

    def actualizar(self, directus, usuario, ip, clave, datos: dict, al_denegar=lambda op: None) -> None:
        cuerpo = self._validar(datos)
        if not cuerpo:
            raise HTTPException(422, "Indique al menos un campo")
        self._modificar(directus, usuario, ip, clave, cuerpo, "actualizar", al_denegar)

    def eliminar(self, directus, usuario, ip, clave, al_denegar=lambda op: None) -> None:
        """Borrado lógico: marca eliminado_en y eliminado_por. Nunca emite un DELETE."""
        if not self.r.borrado_logico:
            raise HTTPException(405, "Este recurso no admite eliminación")
        self._modificar(
            directus,
            usuario,
            ip,
            clave,
            {"eliminado_en": ahora(), "eliminado_por": usuario.mirror_id},
            "eliminar",
            al_denegar,
        )
