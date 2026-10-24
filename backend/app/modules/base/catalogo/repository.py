"""Recursos del catálogo (datos maestros). Directus decide qué departamentos puede leer y editar cada persona."""
import json

from ....core import pii
from ....core.deps import Usuario
from ....core.directus import Directus, exigir
from ....core.recurso import Recurso

PERIODO = Recurso("catalogo_periodo", ("departamento_id", "codigo", "fecha_inicio", "fecha_fin", "estado"), borrado_logico=False)
PROGRAMA = Recurso("catalogo_programa", ("departamento_id", "codigo", "nombre", "tipo"))
ASIGNATURA = Recurso("catalogo_asignatura", ("departamento_id", "codigo", "nombre", "area", "requiere_laboratorio", "activa"))
SALA = Recurso("catalogo_sala", ("departamento_id", "codigo", "nombre", "capacidad", "es_laboratorio", "administrada_por", "activa"))
# Los datos personales (RUT, correo) se guardan cifrados y solo los ve quien tiene personas.ver_datos_personales.
# Este recurso solo sirve para el borrado lógico; la lectura y la escritura pasan por las funciones de abajo.
PERSONA = Recurso("catalogo_persona", ())
DOCENTE = Recurso("catalogo_docente", ("persona_id", "departamento_id", "tipo_contrato", "activo"), pk="persona_id", orden="persona_id")
AYUDANTE = Recurso("catalogo_ayudante", ("persona_id", "departamento_id", "activo"), pk="persona_id", orden="persona_id")

CAMPOS_PERSONA = "id,rut_cifrado,nombre,email_cifrado,eliminado_en"


def _persona(cif: pii.Cifrador, fila: dict) -> dict:
    return {"id": fila["id"], "rut": cif.descifrar(fila["rut_cifrado"], pii.COL_RUT), "nombre": fila["nombre"],
            "email": cif.descifrar(fila["email_cifrado"], pii.COL_EMAIL) if fila.get("email_cifrado") else None}


def listar_personas(directus: Directus, usuario: Usuario, ip, cif: pii.Cifrador, limite: int, desplazamiento: int) -> list[dict]:
    r = exigir(directus.listar("catalogo_persona", token=usuario.token, ip=ip, campos=CAMPOS_PERSONA, limite=limite,
                               desplazamiento=desplazamiento))
    return [_persona(cif, f) for f in r.datos or [] if not f.get("eliminado_en")]


def obtener_persona(directus: Directus, usuario: Usuario, ip, cif: pii.Cifrador, pid: int) -> dict | None:
    r = directus.uno("catalogo_persona", pid, token=usuario.token, ip=ip, campos=CAMPOS_PERSONA)
    if r.estado in (403, 404) or not r.datos or r.datos.get("eliminado_en"):
        return None
    exigir(r)
    return _persona(cif, r.datos)


def persona_por_rut(directus: Directus, usuario: Usuario, ip, cif: pii.Cifrador, rut: str) -> int | None:
    r = exigir(directus.listar("catalogo_persona", token=usuario.token, ip=ip, campos="id,eliminado_en", limite=1,
                               filtro={"rut_indice": {"_eq": cif.indice_rut(rut)}}))
    filas = [f for f in r.datos or [] if not f.get("eliminado_en")]
    return filas[0]["id"] if filas else None


def crear_persona(directus: Directus, usuario: Usuario, ip, cif: pii.Cifrador, rut: str, nombre: str, email: str | None) -> int:
    rut = pii.normalizar_rut(rut)
    cuerpo = {"rut_cifrado": cif.cifrar(rut, pii.COL_RUT), "rut_indice": cif.indice_rut(rut), "nombre": nombre,
              "email_cifrado": cif.cifrar(email, pii.COL_EMAIL) if email else None}
    r = exigir(directus.pedir("POST", "/items/catalogo_persona", token=usuario.token, ip=ip, json=cuerpo, params={"fields": "id"}))
    return r.datos["id"]


def cambios_persona(cif: pii.Cifrador, cambios: dict) -> dict:
    cuerpo = {}
    if "rut" in cambios:
        rut = pii.normalizar_rut(cambios["rut"])
        cuerpo.update({"rut_cifrado": cif.cifrar(rut, pii.COL_RUT), "rut_indice": cif.indice_rut(rut)})
    if "nombre" in cambios:
        cuerpo["nombre"] = cambios["nombre"]
    if "email" in cambios:
        cuerpo["email_cifrado"] = cif.cifrar(cambios["email"], pii.COL_EMAIL) if cambios["email"] else None
    return cuerpo
