"""Orquesta los routers del catálogo. Quién puede leer o editar, y en qué departamento, lo decide Directus."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ....core import audit, pii
from ....core.crud import crear_router
from ....core.deps import Usuario, get_cifrador, get_directus, get_ip, requiere
from ....core.directus import Directus, exigir
from ....core.openapi import ERRORES_ESCRITURA, RESPUESTAS
from ....core.recurso import Repositorio
from . import repository as r
from . import schemas as s


def personas() -> APIRouter:
    """Personas: el RUT y el correo se guardan cifrados (core/pii.py). Quien lee datos personales queda en la auditoría."""
    router = APIRouter(
        prefix="/personas", tags=["catálogo (datos personales)"], responses={**RESPUESTAS, **ERRORES_ESCRITURA}
    )
    repo = Repositorio(r.PERSONA)

    def validar_cuerpo(rut: str | None, email: str | None) -> None:
        if rut is not None and not pii.rut_valido(rut):
            v = pii.normalizar_rut(rut)
            ayuda = (
                f" Debería terminar en {pii.digito_verificador(v.split('-')[0])}."
                if pii.RUT_RE.match(v)
                else " Use el formato 12345678-5, sin puntos."
            )
            raise HTTPException(422, "RUT inválido: el dígito verificador no corresponde." + ayuda)
        if email and "@" not in email:
            raise HTTPException(422, "El correo no parece válido.")

    def auditar_lectura(directus, usuario, ip, cantidad: int, clave=None):
        audit.registrar(
            directus,
            usuario_id=usuario.mirror_id,
            ip=ip,
            accion="lectura_datos_personales",
            entidad="catalogo_persona",
            entidad_id=clave,
            detalle={"cantidad": cantidad},
        )

    def descifrado_fallido():
        return HTTPException(500, "No se pudo descifrar un dato personal; revise las claves de cifrado")

    @router.get(
        "",
        summary="Listar personas",
        description="Requiere `personas.ver_datos_personales`. Devuelve el RUT y el correo "
        "descifrados; cada lectura queda registrada en la auditoría con usuario e IP.",
    )
    def listar(
        limite: int = Query(100, ge=1, le=500),
        desplazamiento: int = Query(0, ge=0),
        usuario: Usuario = Depends(requiere("personas.ver_datos_personales")),
        directus: Directus = Depends(get_directus),
        cif=Depends(get_cifrador),
        ip: str | None = Depends(get_ip),
    ):
        try:
            filas = r.listar_personas(directus, usuario, ip, cif, limite, desplazamiento)
        except pii.DatoAlterado:
            raise descifrado_fallido() from None
        auditar_lectura(directus, usuario, ip, len(filas))
        return filas

    @router.get(
        "/{pid}",
        summary="Ver una persona",
        description="Requiere `personas.ver_datos_personales`. La lectura queda auditada.",
    )
    def leer(
        pid: int,
        usuario: Usuario = Depends(requiere("personas.ver_datos_personales")),
        directus: Directus = Depends(get_directus),
        cif=Depends(get_cifrador),
        ip: str | None = Depends(get_ip),
    ):
        try:
            fila = r.obtener_persona(directus, usuario, ip, cif, pid)
        except pii.DatoAlterado:
            raise descifrado_fallido() from None
        if fila is None:
            raise HTTPException(404, "No encontrado")
        auditar_lectura(directus, usuario, ip, 1, pid)
        return fila

    @router.post(
        "",
        status_code=201,
        summary="Crear una persona",
        description="Requiere `catalogo.editar`. El RUT se acepta con o sin puntos y se valida con su dígito verificador "
        "(422 dice cuál debería ser); 409 si ya existe. El RUT y el correo se guardan cifrados.",
    )
    def crear(
        datos: s.PersonaIn,
        usuario: Usuario = Depends(requiere("catalogo.editar")),
        directus: Directus = Depends(get_directus),
        cif=Depends(get_cifrador),
        ip: str | None = Depends(get_ip),
    ):
        validar_cuerpo(datos.rut, datos.email)
        if r.persona_por_rut(directus, usuario, ip, cif, datos.rut):
            raise HTTPException(409, "Ya existe una persona con ese RUT")
        return {"id": r.crear_persona(directus, usuario, ip, cif, datos.rut, datos.nombre, datos.email)}

    @router.patch(
        "/{pid}",
        status_code=204,
        summary="Modificar una persona",
        description="Requiere `catalogo.editar`. Cambia solo los campos enviados; las mismas validaciones que al crear.",
    )
    def actualizar(
        pid: int,
        datos: s.PersonaPatch,
        usuario: Usuario = Depends(requiere("catalogo.editar")),
        directus: Directus = Depends(get_directus),
        cif=Depends(get_cifrador),
        ip: str | None = Depends(get_ip),
    ):
        cambios = datos.model_dump(exclude_unset=True)
        if not cambios:
            raise HTTPException(422, "Indique al menos un campo")
        validar_cuerpo(cambios.get("rut"), cambios.get("email"))
        if "rut" in cambios:
            otra = r.persona_por_rut(directus, usuario, ip, cif, cambios["rut"])
            if otra is not None and otra != pid:
                raise HTTPException(409, "Ya existe una persona con ese RUT")
        exigir(
            directus.pedir(
                "PATCH",
                f"/items/catalogo_persona/{pid}",
                token=usuario.token,
                ip=ip,
                json=r.cambios_persona(cif, cambios),
            ),
            lectura_de_uno=True,
        )
        return Response(status_code=204)

    @router.delete(
        "/{pid}",
        status_code=204,
        summary="Eliminar una persona",
        description="Requiere `catalogo.editar`. Borrado lógico.",
    )
    def eliminar(
        pid: int,
        usuario: Usuario = Depends(requiere("catalogo.editar")),
        directus: Directus = Depends(get_directus),
        ip: str | None = Depends(get_ip),
    ):
        repo.eliminar(directus, usuario, ip, pid)
        return Response(status_code=204)

    return router


def routers() -> list[APIRouter]:
    return [
        crear_router(
            r.PERIODO,
            ruta="periodos",
            etiqueta="catálogo",
            ver="catalogo.ver",
            editar="catalogo.editar",
            entrada=s.PeriodoIn,
            parcial=s.PeriodoPatch,
        ),
        crear_router(
            r.PROGRAMA,
            ruta="programas",
            etiqueta="catálogo",
            ver="catalogo.ver",
            editar="catalogo.editar",
            entrada=s.ProgramaIn,
            parcial=s.ProgramaPatch,
        ),
        crear_router(
            r.ASIGNATURA,
            ruta="asignaturas",
            etiqueta="catálogo",
            ver="catalogo.ver",
            editar="catalogo.editar",
            entrada=s.AsignaturaIn,
            parcial=s.AsignaturaPatch,
        ),
        crear_router(
            r.SALA,
            ruta="salas",
            etiqueta="catálogo",
            ver="catalogo.ver",
            editar="catalogo.editar",
            entrada=s.SalaIn,
            parcial=s.SalaPatch,
        ),
        personas(),
        crear_router(
            r.DOCENTE,
            ruta="docentes",
            etiqueta="catálogo",
            ver="catalogo.ver",
            editar="catalogo.editar",
            entrada=s.DocenteIn,
            parcial=s.DocentePatch,
        ),
        crear_router(
            r.AYUDANTE,
            ruta="ayudantes",
            etiqueta="catálogo",
            ver="catalogo.ver",
            editar="catalogo.editar",
            entrada=s.AyudanteIn,
            parcial=s.AyudantePatch,
        ),
    ]
