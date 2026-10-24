"""Directus simulado para las pruebas unitarias de la API.

Implementa lo justo de la API de Directus para ejercitar la lógica de la API (traducción de errores, cifrado, bloqueo
por intentos, comprobaciones previas, importaciones). NO aplica permisos por rol ni por departamento: eso lo hace
Directus de verdad y se prueba en tests_integracion contra una instancia real.
"""
import json
from collections import defaultdict

import httpx

ADMIN_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CONSULTA_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _coincide(fila: dict, filtro: dict | None) -> bool:
    if not filtro:
        return True
    for k, v in filtro.items():
        if k == "_and":
            if not all(_coincide(fila, f) for f in v):
                return False
        elif k == "_or":
            if not any(_coincide(fila, f) for f in v):
                return False
        else:
            valor = fila.get(k)
            for op, esperado in v.items():
                if op == "_eq" and valor != esperado:
                    return False
                if op == "_null" and ((valor is None) != esperado):
                    return False
                if op == "_in" and valor not in esperado:
                    return False
    return True


class DirectusFalso:
    def __init__(self):
        self.llamadas: list[tuple] = []
        self.items: dict[str, list[dict]] = defaultdict(list)
        self.sesiones: dict[str, dict] = {}          # access_token -> usuario
        self.refresh: dict[str, str] = {}            # refresh_token -> email
        self.usuarios = {}
        self.fallos: dict[tuple, tuple] = {}         # (método, ruta) -> (estado, cuerpo) para forzar errores
        self.agregar_usuario("encargado.docente@example.com", "Clave-Admin-de-prueba-1", ADMIN_ID, "disc_administrador", None)
        self.agregar_usuario("usuario.prueba@example.com", "Clave-Prueba-de-prueba-2", CONSULTA_ID, "disc_consulta", 1)
        todos = ["catalogo.ver", "catalogo.editar", "catalogo.importar", "personas.ver_datos_personales", "usuarios.gestionar",
                 "departamentos.ver_otros", "departamentos.gestionar", "horarios.ver", "horarios.editar", "horarios.generar",
                 "horarios.exportar", "horarios.aprobar", "horarios.enviar", "restricciones.ver", "restricciones.gestionar",
                 "finanzas.ver", "finanzas.editar", "proyeccion.ver"]
        for rol, perms in {"administrador": todos,
                           "encargado_docente": ["catalogo.ver", "catalogo.editar", "catalogo.importar", "personas.ver_datos_personales",
                                                 "horarios.ver", "horarios.editar", "finanzas.ver", "finanzas.editar"],
                           "consulta": ["catalogo.ver", "horarios.ver"]}.items():
            for p in perms:
                self.items["identidad_rol_permiso"].append({"id": len(self.items["identidad_rol_permiso"]) + 1, "rol": rol, "permiso": p, "revocado_en": None})
        self.items["identidad_usuario"] = [{"id": 1, "directus_id": ADMIN_ID, "email": "encargado.docente@example.com", "nombre": "Encargado Docente", "eliminado_en": None},
                                           {"id": 2, "directus_id": CONSULTA_ID, "email": "usuario.prueba@example.com", "nombre": "Usuario de prueba", "eliminado_en": None}]
        self.items["identidad_departamento"] = [{"id": 1, "codigo": "DISC"}, {"id": 2, "codigo": "DMAT"}]

    def agregar_usuario(self, email, clave, uid, rol, depto):
        self.usuarios[email] = {"id": uid, "email": email, "password": clave, "first_name": email.split("@")[0], "status": "active",
                                "departamento_id": depto, "intentos_fallidos": 0, "bloqueado_hasta": None,
                                "role": {"id": "r-" + rol, "name": rol} if rol else None}

    # -- helpers ----------------------------------------------------------------------------------------
    def _usuario_de(self, req):
        token = req.headers.get("authorization", "").removeprefix("Bearer ")
        return self.sesiones.get(token)

    def _json(self, estado, datos=None, errores=None):
        cuerpo = {"data": datos} if errores is None else {"errors": errores}
        if estado == 204:
            return httpx.Response(204)
        return httpx.Response(estado, json=cuerpo)

    def _error(self, estado, mensaje, codigo=""):
        return self._json(estado, errores=[{"message": mensaje, "extensions": {"code": codigo}}])

    # -- despacho ---------------------------------------------------------------------------------------
    def __call__(self, req: httpx.Request) -> httpx.Response:
        ruta, metodo = req.url.path, req.method
        cuerpo = json.loads(req.content) if req.content else None
        params = dict(req.url.params)
        self.llamadas.append((metodo, ruta, cuerpo, req.headers.get("authorization"), req.headers.get("x-forwarded-for")))
        if (metodo, ruta) in self.fallos:
            e, c = self.fallos[(metodo, ruta)]
            return httpx.Response(e, json=c)
        if ruta == "/server/health":
            return httpx.Response(200, json={"status": "ok"})
        if ruta == "/auth/login":
            u = self.usuarios.get(cuerpo["email"])
            if not u or u["password"] != cuerpo["password"] or u["status"] != "active":
                return self._error(401, "Invalid user credentials.", "INVALID_CREDENTIALS")
            return self._json(200, self._emitir(u))
        if ruta == "/auth/refresh":
            email = self.refresh.pop(cuerpo["refresh_token"], None)
            if not email:
                return self._error(401, "Invalid user credentials.", "INVALID_CREDENTIALS")
            return self._json(200, self._emitir(self.usuarios[email]))
        if ruta == "/auth/logout":
            self.refresh.pop(cuerpo["refresh_token"], None)
            return httpx.Response(204)
        if ruta == "/users/me":
            u = self._usuario_de(req)
            if not u:
                return self._error(401, "Invalid user credentials.", "INVALID_CREDENTIALS")
            if metodo == "PATCH":
                u["password"] = cuerpo["password"]
                return self._json(200, {"id": u["id"]})
            return self._json(200, {k: u[k] for k in ("id", "email", "first_name", "status", "departamento_id", "role")})
        if ruta == "/users":
            if metodo == "GET":
                filtro = json.loads(params["filter"]) if "filter" in params else None
                filas = [dict(u) for u in self.usuarios.values() if _coincide({"email": u["email"]}, filtro)]
                return self._json(200, filas)
            email = cuerpo["email"]
            self.agregar_usuario(email, cuerpo["password"], f"{len(self.usuarios):08d}-0000-0000-0000-000000000000", None, None)
            return self._json(200, {"id": self.usuarios[email]["id"]})
        if ruta.startswith("/users/"):
            uid = ruta.split("/")[2]
            for u in self.usuarios.values():
                if u["id"] == uid:
                    if "role" in cuerpo:
                        u["role"] = {"id": cuerpo["role"], "name": next((n for n in ("disc_administrador", "disc_consulta", "disc_encargado_docente") if "r-" + n == cuerpo["role"]), None)} if cuerpo["role"] else None
                    u.update({k: v for k, v in cuerpo.items() if k != "role"})
                    return self._json(200, {"id": uid})
            return self._error(403, "no permission", "FORBIDDEN")
        if ruta == "/roles":
            filtro = json.loads(params.get("filter", "{}"))
            nombre = filtro.get("name", {}).get("_eq", "")
            return self._json(200, [{"id": "r-" + nombre}])
        if ruta.startswith("/items/"):
            return self._items(metodo, ruta.split("/")[2:], cuerpo, params, req)
        return self._error(404, "ruta desconocida")

    def _emitir(self, u):
        n = len(self.sesiones)
        acceso, refresco = f"acceso-{u['id'][:4]}-{n}", f"refresco-{u['id'][:4]}-{n}-{'x' * 20}"
        self.sesiones[acceso] = u
        self.refresh[refresco] = u["email"]
        return {"access_token": acceso, "refresh_token": refresco, "expires": 600000}

    def _items(self, metodo, partes, cuerpo, params, req):
        coleccion = partes[0]
        filas = self.items[coleccion]
        if len(partes) == 2:                                     # una fila
            fila = next((f for f in filas if str(f.get("id", f.get("persona_id"))) == partes[1]), None)
            if fila is None or (metodo == "GET" and fila.get("eliminado_en")):
                return self._error(403, "You don't have permission to access this.", "FORBIDDEN")
            if metodo == "GET":
                return self._json(200, dict(fila))
            if metodo == "PATCH":
                fila.update(cuerpo)
                return self._json(200, dict(fila)) if not fila.get("eliminado_en") else httpx.Response(204)
        if metodo == "GET":
            filtro = json.loads(params["filter"]) if "filter" in params else None
            sel = [dict(f) for f in filas if _coincide(f, filtro) and not f.get("eliminado_en")]
            lim = int(params.get("limit", 100))
            return self._json(200, sel if lim < 0 else sel[int(params.get("offset", 0)):int(params.get("offset", 0)) + lim])
        if metodo == "POST":
            nuevos = cuerpo if isinstance(cuerpo, list) else [cuerpo]
            creados = []
            for n in nuevos:
                for clave in self._unicos.get(coleccion, ()):
                    if any(f.get(clave) == n.get(clave) for f in filas):
                        return self._error(400, f'Value "{n.get(clave)}" for field "{clave}" in collection "{coleccion}" has to be unique.', "RECORD_NOT_UNIQUE")
                fila = {"id": len(filas) + 1, **n}
                creados.append(fila)
            filas.extend(creados)
            if "fields" in params and not isinstance(cuerpo, list):
                return self._json(200, {k: creados[0][k] for k in params["fields"].split(",") if k in creados[0]})
            return self._json(200, creados if isinstance(cuerpo, list) else creados[0])
        return self._error(405, "método no soportado")

    _unicos = {"catalogo_persona": ("rut_indice",), "catalogo_sala": ("codigo",)}
