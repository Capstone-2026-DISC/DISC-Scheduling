"""Búsqueda de claves naturales en Directus, con la sesión de quien importa y con caché por importación."""
import json

from ..core.deps import Usuario
from ..core.directus import Directus, DirectusCaido, exigir
from .validar import Referencias


class DirectusReferencias(Referencias):
    def __init__(self, directus: Directus, usuario: Usuario, ip: str | None, cif=None):
        self.d, self.u, self.ip, self.cif = directus, usuario, ip, cif
        self._cache: dict = {}

    def _una(self, coleccion: str, filtro: dict, campos: str = "id") -> dict | None:
        clave = (coleccion, json.dumps(filtro, sort_keys=True), campos)
        if clave not in self._cache:
            r = exigir(self.d.listar(coleccion, token=self.u.token, ip=self.ip, filtro=filtro, campos=campos, limite=1, orden=None))
            self._cache[clave] = (r.datos or [None])[0]
        return self._cache[clave]

    def departamento(self, codigo):
        f = self._una("identidad_departamento", {"codigo": {"_eq": codigo.upper()}})
        return f["id"] if f else None

    def periodo(self, departamento_id, codigo):
        f = self._una("catalogo_periodo", {"_and": [{"departamento_id": {"_eq": departamento_id}}, {"codigo": {"_eq": codigo}}]})
        return f["id"] if f else None

    def persona(self, rut):
        if self.cif is None:
            return None
        f = self._una("catalogo_persona", {"_and": [{"rut_indice": {"_eq": self.cif.indice_rut(rut)}}, {"eliminado_en": {"_null": True}}]})
        return f["id"] if f else None

    def es_docente(self, persona_id):
        return self._una("catalogo_docente", {"persona_id": {"_eq": persona_id}}, "persona_id") is not None

    def asignatura(self, codigo):
        f = self._una("catalogo_asignatura", {"_and": [{"codigo": {"_eq": codigo}}, {"eliminado_en": {"_null": True}}]})
        return f["id"] if f else None

    def paralelo(self, nrc, periodo_id):
        f = self._una("horarios_paralelo", {"_and": [{"nrc": {"_eq": nrc}}, {"periodo_id": {"_eq": periodo_id}}, {"eliminado_en": {"_null": True}}]})
        return f["id"] if f else None

    def categoria(self, tipo, letra):
        f = self._una("finanzas_categoria", {"_and": [{"tipo_persona": {"_eq": tipo}}, {"letra": {"_eq": letra}}]})
        return f["id"] if f else None

    def existe(self, tabla, filtros):
        # "*": no todas las tablas tienen una columna id (catalogo_docente usa persona_id)
        return self._una(tabla, {"_and": [{c: ({"_null": True} if v is None else {"_eq": v})} for c, v in filtros.items()]}, "*") is not None

    def precargar(self, plantilla, filas):
        """Una consulta por cada tanda de 100 RUT en lugar de una por fila."""
        if self.cif is None:
            return
        ruts = sorted({f["rut"] for f in filas if f.get("rut")})
        for i in range(0, len(ruts), 100):
            lote = {self.cif.indice_rut(r): r for r in ruts[i:i + 100]}
            r = self.d.listar("catalogo_persona", token=self.u.token, ip=self.ip, campos="id,rut_indice",
                              filtro={"_and": [{"rut_indice": {"_in": list(lote)}}, {"eliminado_en": {"_null": True}}]}, limite=-1)
            if r.estado != 200:
                continue
            hallados = {f["rut_indice"]: f["id"] for f in r.datos or []}
            for indice in lote:
                filtro = {"_and": [{"rut_indice": {"_eq": indice}}, {"eliminado_en": {"_null": True}}]}
                clave = ("catalogo_persona", json.dumps(filtro, sort_keys=True), "id")
                self._cache[clave] = {"id": hallados[indice]} if indice in hallados else None
