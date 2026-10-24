"""Configura Directus de forma repetible (idempotente) a partir del esquema y de los roles de la plataforma.

  python -m app.directus_setup nucleo                       Directus del núcleo: colecciones, roles, política de la API y usuarios
  python -m app.directus_setup satelites                    Directus de los satélites: un rol y un token por grupo
  python -m app.directus_setup verificar                    Comprueba los permisos reales contra ambas instancias
  python -m app.directus_setup rol-permiso dar|quitar ROL PERMISO
                                                            Cambia un permiso lógico de un rol y regenera su política

Variables: DIRECTUS_URL, ADMIN_EMAIL, ADMIN_PASSWORD (administrador de arranque de Directus); API_SERVICE_TOKEN;
SEED_ADMIN_PASSWORD, SEED_TEST_PASSWORD; SATELITES_URL, SAT_ADMIN_EMAIL, SAT_ADMIN_PASSWORD, SAT_TOKEN_G1..G4;
SCHEMA_PATH y DB_PATH (para proteger el registro de actividad). Ninguna clave se imprime ni se guarda.
"""
import os
import sqlite3
import sys
import time
from pathlib import Path

import httpx

from . import directus_matriz as matriz

GRUPOS = ("g1", "g2", "g3", "g4")
CARPETAS = {"identidad": "badge", "plataforma": "settings", "catalogo": "menu_book", "horarios": "calendar_month",
            "finanzas": "payments", "proyeccion": "trending_up"}
PREFIJO = "disc_"
EMAIL_ADMIN = "encargado.docente@example.com"
EMAIL_PRUEBA = "usuario.prueba@example.com"
EMAIL_SERVICIO = "servicio.api@example.com"


class Directus:
    def __init__(self, url: str, email: str, clave: str):
        self.http = httpx.Client(base_url=url, timeout=60)
        self.email, self.clave = email, clave
        self._entrar(esperar=True)

    def _entrar(self, esperar: bool = False) -> None:
        for _ in range(60 if esperar else 3):
            try:
                r = self.http.post("/auth/login", json={"email": self.email, "password": self.clave})
                if r.status_code != 429:
                    break
                time.sleep(15)
            except httpx.RequestError:
                time.sleep(2)
        else:
            raise RuntimeError(f"Directus no responde en {self.http.base_url}")
        if r.status_code != 200:
            raise RuntimeError(f"No se pudo iniciar sesión en Directus: {r.text[:200]}")
        self.http.headers["Authorization"] = f"Bearer {r.json()['data']['access_token']}"

    def pedir(self, metodo: str, ruta: str, **kw):
        for intento in range(8):               # el límite de peticiones de Directus también rige para este script
            r = self.http.request(metodo, ruta, **kw)
            if r.status_code == 401 and intento == 0:
                self._entrar()                  # el token de acceso dura 10 minutos y esta tarea puede tardar más
                continue
            if r.status_code != 429:
                break
            espera = r.headers.get("retry-after")
            time.sleep(min(float(espera) if espera and espera.replace(".", "").isdigit() else 10, 65) + 1)
        if r.status_code >= 400:
            raise RuntimeError(f"{metodo} {ruta} -> {r.status_code}: {r.text[:300]}")
        return r.json().get("data") if r.content else None

    def buscar(self, ruta: str, campo: str, valor: str):
        datos = self.pedir("GET", ruta, params={f"filter[{campo}][_eq]": valor, "limit": 1})
        return datos[0] if datos else None

    # -- políticas, roles, permisos, usuarios ------------------------------------------------
    def politica(self, nombre: str, app_access: bool = True) -> str:
        p = self.buscar("/policies", "name", nombre)
        if p:
            return p["id"]
        return self.pedir("POST", "/policies", json={"name": nombre, "admin_access": False, "app_access": app_access})["id"]

    def rol(self, nombre: str, politica_id: str) -> str:
        r = self.buscar("/roles", "name", nombre)
        if not r:
            r = self.pedir("POST", "/roles", json={"name": nombre})
        enlazada = self.pedir("GET", "/access", params={"filter[role][_eq]": r["id"], "filter[policy][_eq]": politica_id, "limit": 1})
        if not enlazada:
            self.pedir("POST", "/access", json={"role": r["id"], "policy": politica_id})
        return r["id"]

    def reemplazar_permisos(self, politica_id: str, permisos: list[dict]) -> None:
        viejos = [p["id"] for p in self.pedir("GET", "/permissions", params={"filter[policy][_eq]": politica_id, "limit": -1})]
        if viejos:
            self.pedir("DELETE", "/permissions", json=viejos)
        if permisos:
            self.pedir("POST", "/permissions", json=[{**p, "policy": politica_id} for p in permisos])

    def usuario(self, email: str, clave: str | None, rol_id: str, **extra) -> str:
        """Crea el usuario si no existe. Si existe, ajusta rol y datos pero no pisa una clave que la persona ya cambió."""
        u = self.buscar("/users", "email", email)
        if u:
            self.pedir("PATCH", f"/users/{u['id']}", json={"role": rol_id, "status": "active", **extra})
            return u["id"]
        datos = {"email": email, "role": rol_id, "status": "active", **extra}
        if clave:
            datos["password"] = clave
        return self.pedir("POST", "/users", json=datos)["id"]

    def asegurar_campo(self, coleccion: str, campo: str, tipo: str, nota: str, defecto=None) -> None:
        existentes = {f["field"] for f in self.pedir("GET", f"/fields/{coleccion}")}
        if campo not in existentes:
            esquema = {"default_value": defecto} if defecto is not None else {}
            self.pedir("POST", f"/fields/{coleccion}", json={"field": campo, "type": tipo, "meta": {"interface": "input", "note": nota}, "schema": esquema})

    def rastrear(self, tablas: list[str]) -> None:
        """Registra cada tabla existente como colección de Directus y las agrupa en carpetas por prefijo."""
        existentes = {c["collection"] for c in self.pedir("GET", "/collections")}
        for prefijo, icono in CARPETAS.items():
            carpeta = f"grupo_{prefijo}"
            if carpeta not in existentes:
                self.pedir("POST", "/collections", json={"collection": carpeta, "schema": None,
                                                         "meta": {"icon": icono, "note": f"Tablas {prefijo}_*"}})
        for t in tablas:
            prefijo = t.split("_", 1)[0]
            grupo = f"grupo_{prefijo}" if prefijo in CARPETAS else None
            self.pedir("PATCH", f"/collections/{t}", json={"meta": {"group": grupo, "hidden": False}})


def esquema_del_archivo() -> dict:
    """El esquema se lee del archivo SQL en una base en memoria: no hace falta abrir la base real."""
    con = sqlite3.connect(":memory:")
    con.executescript(Path(os.environ.get("SCHEMA_PATH", "/app/db/esquema_plataforma.sql")).read_text(encoding="utf-8"))
    return matriz.esquema(con)


def roles_logicos(d: Directus) -> dict[str, set[str]]:
    roles = d.pedir("GET", "/items/identidad_rol", params={"fields": "codigo,activo,eliminado_en", "limit": -1}) or []
    perms = d.pedir("GET", "/items/identidad_rol_permiso", params={"fields": "rol,permiso,revocado_en", "limit": -1}) or []
    por_rol: dict[str, set[str]] = {r["codigo"]: set() for r in roles if r["activo"] and not r["eliminado_en"]}
    for p in perms:
        if not p["revocado_en"] and p["rol"] in por_rol:
            por_rol[p["rol"]].add(p["permiso"])
    por_rol.pop("modulo_satelite", None)       # los satélites entran por la otra instancia, con réplica de solo lectura
    return por_rol


def sincronizar_rol(d: Directus, info: dict, codigo: str, permisos: set[str]) -> str:
    pol = d.politica(PREFIJO + codigo)
    perms = matriz.permisos_propios() + matriz.permisos_de_lectura(info, permisos) + matriz.permisos_de_escritura(info, permisos)
    d.reemplazar_permisos(pol, perms)
    return d.rol(PREFIJO + codigo, pol)


def proteger_actividad() -> None:
    """El registro de actividad de Directus es la auditoría de los cambios de datos: se conserva 5 años y no se modifica.
    Es una migración (abre el archivo); por eso corre en el configurador y no en la API."""
    ruta = os.environ.get("DB_PATH", "/data/plataforma.db")
    if not os.access(ruta, os.W_OK):
        print("sin acceso de escritura a la base: no se protegió el registro de actividad")
        return
    con = sqlite3.connect(ruta, isolation_level=None, timeout=20)
    try:
        con.execute("PRAGMA busy_timeout = 20000")
        # Directus guarda la fecha como milisegundos desde 1970; las revisiones no tienen fecha propia: usan la de su actividad
        limite = "CAST(strftime('%s', 'now', '-5 years') AS INTEGER) * 1000"
        reglas = {"directus_activity": f"OLD.timestamp > {limite}",
                  "directus_revisions": f"(SELECT timestamp FROM directus_activity WHERE id = OLD.activity) > {limite}"}
        for tabla, condicion in reglas.items():
            con.execute(f"DROP TRIGGER IF EXISTS {tabla}_conservar")
            con.execute(f"CREATE TRIGGER {tabla}_conservar BEFORE DELETE ON {tabla} WHEN {condicion} "
                        f"BEGIN SELECT RAISE(ABORT, 'El registro de actividad se conserva durante 5 años'); END")
        con.execute("DROP TRIGGER IF EXISTS directus_activity_inmutable")
        con.execute("CREATE TRIGGER directus_activity_inmutable BEFORE UPDATE ON directus_activity "
                    "BEGIN SELECT RAISE(ABORT, 'El registro de actividad es de solo inserción'); END")
    finally:
        con.close()


def configurar_nucleo() -> None:
    d = Directus(os.environ.get("DIRECTUS_URL", "http://directus:8055"), os.environ["ADMIN_EMAIL"], os.environ["ADMIN_PASSWORD"])
    info = esquema_del_archivo()
    d.rastrear(sorted(t for t in info if t not in matriz.SIN_ACCESO))
    d.asegurar_campo("directus_users", "departamento_id", "integer", "Departamento al que se limita el acceso (vacío = todos)")
    d.asegurar_campo("directus_users", "intentos_fallidos", "integer", "Intentos de acceso fallidos seguidos", 0)
    d.asegurar_campo("directus_users", "bloqueado_hasta", "timestamp", "Bloqueo temporal por intentos fallidos")
    roles = {}
    for codigo, permisos in sorted(roles_logicos(d).items()):
        roles[codigo] = sincronizar_rol(d, info, codigo, permisos)
        print(f"rol {codigo}: {len([p for p in matriz.permisos_de_lectura(info, permisos)])} colecciones de lectura, "
              f"{len(matriz.permisos_de_escritura(info, permisos))} permisos de escritura")
    # cuenta de servicio de la API: solo puede crear y modificar usuarios con roles de la plataforma, no borra ni toca políticas
    pol_serv = d.politica("servicio_api", app_access=False)
    d.reemplazar_permisos(pol_serv, matriz.permisos_servicio(info, list(roles.values())))
    rol_serv = d.rol("servicio_api", pol_serv)
    if not os.environ.get("API_SERVICE_TOKEN"):
        raise RuntimeError("falta API_SERVICE_TOKEN")
    d.usuario(EMAIL_SERVICIO, None, rol_serv, token=os.environ["API_SERVICE_TOKEN"], first_name="Servicio de la API")
    # usuarios iniciales: viven en Directus y tienen espejo en identidad_usuario
    for email, nombre, var, rol, depto in ((EMAIL_ADMIN, "Encargado Docente", "SEED_ADMIN_PASSWORD", "administrador", None),
                                           (EMAIL_PRUEBA, "Usuario de prueba", "SEED_TEST_PASSWORD", "consulta", 1)):
        if rol not in roles or not os.environ.get(var):
            continue
        uid = d.usuario(email, os.environ[var], roles[rol], first_name=nombre, departamento_id=depto)
        if not d.buscar("/items/identidad_usuario", "directus_id", uid):
            d.pedir("POST", "/items/identidad_usuario", json={"directus_id": uid, "email": email, "nombre": nombre})
        print(f"usuario {email} -> rol {rol}")
    proteger_actividad()


def cambiar_rol_permiso(accion: str, rol: str, permiso: str) -> None:
    d = Directus(os.environ.get("DIRECTUS_URL", "http://directus:8055"), os.environ["ADMIN_EMAIL"], os.environ["ADMIN_PASSWORD"])
    if rol == "administrador" and accion == "quitar":
        sys.exit("No se quitan permisos al rol de sistema administrador")
    if not d.buscar("/items/identidad_permiso", "codigo", permiso) or not d.buscar("/items/identidad_rol", "codigo", rol):
        sys.exit(f"No existe el rol {rol} o el permiso {permiso}")
    fila = d.pedir("GET", "/items/identidad_rol_permiso", params={"filter[rol][_eq]": rol, "filter[permiso][_eq]": permiso, "limit": 1})
    if accion == "dar":
        if fila:
            d.pedir("PATCH", f"/items/identidad_rol_permiso/{fila[0]['id']}", json={"revocado_en": None})
        else:
            d.pedir("POST", "/items/identidad_rol_permiso", json={"rol": rol, "permiso": permiso})
    else:
        if fila:
            d.pedir("PATCH", f"/items/identidad_rol_permiso/{fila[0]['id']}", json={"revocado_en": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    info = esquema_del_archivo()
    sincronizar_rol(d, info, rol, roles_logicos(d).get(rol, set()))
    print(f"permiso {permiso} {'dado a' if accion == 'dar' else 'quitado de'} {rol}; política de Directus regenerada")


def configurar_satelites() -> None:
    d = Directus(os.environ.get("SATELITES_URL", "http://directus-satelites:8055"), os.environ["SAT_ADMIN_EMAIL"],
                 os.environ["SAT_ADMIN_PASSWORD"])
    ruta = os.environ.get("SATELITES_DB_PATH", "/satelites/satelites.db")
    sat = sqlite3.connect(ruta, isolation_level=None, timeout=10)
    sat.execute("PRAGMA busy_timeout = 5000")
    pub = [r[0] for r in sat.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'pub_%'")]
    for g in GRUPOS:     # una colección propia por grupo; con borrado lógico (sin permiso de DELETE)
        sat.execute(f"CREATE TABLE IF NOT EXISTS sat_{g}_registro (id INTEGER PRIMARY KEY, clave TEXT NOT NULL, "
                    "valor TEXT CHECK (valor IS NULL OR json_valid(valor)), "
                    "creado_en TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')), eliminado_en TEXT) STRICT")
    sat.close()
    d.pedir("POST", "/utils/cache/clear")
    for t in pub + [f"sat_{g}_registro" for g in GRUPOS]:
        d.pedir("PATCH", f"/collections/{t}", json={"meta": {"hidden": False}})
    for g in GRUPOS:
        pol = d.politica(f"satelite_{g}", app_access=False)
        permisos = [{"collection": t, "action": "read", "fields": ["*"], "permissions": {}} for t in pub]
        propia = f"sat_{g}_registro"
        permisos += [{"collection": propia, "action": "read", "fields": ["*"], "permissions": {"eliminado_en": {"_null": True}}},
                     {"collection": propia, "action": "create", "fields": ["clave", "valor"], "permissions": {}, "validation": {}},
                     {"collection": propia, "action": "update", "fields": ["clave", "valor", "eliminado_en"],
                      "permissions": {"eliminado_en": {"_null": True}}, "validation": {}}]
        d.reemplazar_permisos(pol, permisos)
        rol = d.rol(f"satelite_{g}", pol)
        token = os.environ.get(f"SAT_TOKEN_{g.upper()}")
        if not token:
            print(f"falta SAT_TOKEN_{g.upper()}: se omite el usuario del grupo")
            continue
        d.usuario(f"{g}@satelites.example.com", None, rol, token=token)
        print(f"satélite {g}: lectura pub_* ({len(pub)}), escritura solo en {propia}")



# ---- verificación ------------------------------------------------------------------------------
def _intento(base: str, token: str, metodo: str, ruta: str, reintentar: bool = True, **kw) -> int:
    for _ in range(8):
        r = httpx.request(metodo, base + ruta, headers={"Authorization": f"Bearer {token}"}, timeout=30, **kw)
        if r.status_code != 429 or not reintentar:
            return r.status_code
        espera = r.headers.get("retry-after", "10")
        time.sleep(min(float(espera) if espera.replace(".", "").isdigit() else 10, 65) + 1)
    return 429


def _sesion(base: str, email: str, clave: str) -> str:
    r = httpx.post(base + "/auth/login", json={"email": email, "password": clave, "mode": "json"}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"no se pudo iniciar sesión como {email}: {r.status_code}")
    return r.json()["data"]["access_token"]


def verificar() -> int:
    errores = []

    def esperar(desc, obtenido, esperado):
        ok = obtenido in esperado
        print(("ok    " if ok else "FALLA ") + f"{desc} -> {obtenido}")
        if not ok:
            errores.append(desc)

    base = os.environ.get("DIRECTUS_URL", "http://directus:8055")
    # consulta: lee lo suyo y no puede escribir ni ver lo reservado
    c = _sesion(base, EMAIL_PRUEBA, os.environ["SEED_TEST_PASSWORD"])
    esperar("consulta lee catalogo_sala", _intento(base, c, "GET", "/items/catalogo_sala"), (200,))
    esperar("consulta NO lee finanzas_tarifa", _intento(base, c, "GET", "/items/finanzas_tarifa"), (403,))
    esperar("consulta NO lee catalogo_persona (datos personales)", _intento(base, c, "GET", "/items/catalogo_persona"), (403,))
    esperar("consulta NO lee la auditoría", _intento(base, c, "GET", "/items/plataforma_auditoria"), (403,))
    esperar("consulta NO crea una sala", _intento(base, c, "POST", "/items/catalogo_sala", json={"codigo": "ZZ"}), (403,))
    esperar("consulta NO modifica una sala", _intento(base, c, "PATCH", "/items/catalogo_sala/1", json={"nombre": "x"}), (403,))
    esperar("consulta NO borra", _intento(base, c, "DELETE", "/items/catalogo_sala/1"), (403,))
    # Encargado Docente (rol administrador): escribe por Directus con su sesión, sin borrar de verdad
    a = _sesion(base, EMAIL_ADMIN, os.environ["SEED_ADMIN_PASSWORD"])
    esperar("administrador lee finanzas_tarifa", _intento(base, a, "GET", "/items/finanzas_tarifa"), (200,))
    esperar("administrador lee la auditoría", _intento(base, a, "GET", "/items/plataforma_auditoria"), (200,))
    codigo = f"VERIF-{int(time.time())}"          # único en cada corrida: la verificación se puede repetir
    r = httpx.post(base + "/items/catalogo_sala", headers={"Authorization": f"Bearer {a}"}, params={"fields": "id"},
                   json={"codigo": codigo, "nombre": "Sala de verificación"}, timeout=30)
    esperar("administrador crea una sala", r.status_code, (200,))
    sala = r.json()["data"]["id"] if r.status_code == 200 else 0
    esperar("administrador modifica esa sala", _intento(base, a, "PATCH", f"/items/catalogo_sala/{sala}", json={"nombre": "Otra"}), (200,))
    esperar("administrador la elimina (borrado lógico)", _intento(base, a, "PATCH", f"/items/catalogo_sala/{sala}", json={"eliminado_en": "2026-01-01T00:00:00Z"}), (200, 204))
    ocultas = httpx.get(base + "/items/catalogo_sala", headers={"Authorization": f"Bearer {a}"}, params={"filter[codigo][_eq]": codigo}, timeout=30).json()["data"]
    esperar("la sala eliminada ya no aparece", len(ocultas), (0,))
    esperar("administrador NO borra de verdad", _intento(base, a, "DELETE", f"/items/catalogo_sala/{sala}"), (403,))
    # el registro de actividad dice quién hizo el cambio
    boot = _sesion(base, os.environ["ADMIN_EMAIL"], os.environ["ADMIN_PASSWORD"])
    act = httpx.get(base + "/activity", headers={"Authorization": f"Bearer {boot}"}, timeout=30,
                    params={"filter[collection][_eq]": "catalogo_sala", "filter[item][_eq]": str(sala), "fields": "action,user.email,ip", "limit": -1}).json()["data"]
    esperar("Directus registró quién creó la sala", int(any(x["action"] == "create" and (x.get("user") or {}).get("email") == EMAIL_ADMIN for x in act)), (1,))
    # cuenta de servicio de la API: mínimos privilegios
    s = os.environ["API_SERVICE_TOKEN"]
    esperar("servicio puede registrar un evento de auditoría", _intento(base, s, "POST", "/items/plataforma_auditoria",
            json={"accion": "verificacion", "resultado": "ok", "entidad": "directus_setup"}), (200, 204))
    esperar("servicio NO lee políticas", _intento(base, s, "GET", "/policies"), (403,))
    esperar("servicio NO borra usuarios", _intento(base, s, "DELETE", "/users/00000000-0000-0000-0000-000000000000"), (403,))
    esperar("servicio NO escribe datos del núcleo", _intento(base, s, "POST", "/items/catalogo_sala", json={"codigo": "ZZ"}), (403,))
    adm_rol = httpx.get(base + "/roles", headers={"Authorization": f"Bearer {boot}"}, params={"filter[name][_eq]": "Administrator", "fields": "id"}, timeout=30).json()["data"]
    esperar("servicio NO puede dar el rol Administrator de Directus", _intento(base, s, "POST", "/users",
            json={"email": "intruso@example.com", "password": "Clave-Larga-Intruso-1x", "role": adm_rol[0]["id"]}), (400, 403))
    # el registro de actividad no se modifica ni se borra (trigger creado por proteger_actividad)
    ruta = os.environ.get("DB_PATH", "/data/plataforma.db")
    if os.access(ruta, os.W_OK):
        con = sqlite3.connect(ruta, isolation_level=None, timeout=20)
        try:
            for desc, sentencia in (("el registro de actividad reciente no se borra", "DELETE FROM directus_activity"),
                                    ("las revisiones recientes no se borran", "DELETE FROM directus_revisions"),
                                    ("el registro de actividad no se modifica", "UPDATE directus_activity SET ip = '0.0.0.0'")):
                con.execute("BEGIN IMMEDIATE")              # dentro de una transacción que siempre se revierte
                try:
                    con.execute(sentencia)
                    esperar(desc, 0, (1,))
                except sqlite3.Error as exc:
                    esperar(desc, int("solo inserción" in str(exc) or "se conserva" in str(exc)), (1,))
                finally:
                    con.execute("ROLLBACK")
        finally:
            con.close()

    sat = os.environ.get("SATELITES_URL")
    if sat and os.environ.get("SAT_TOKEN_G1") and os.environ.get("SAT_TOKEN_G2"):
        g1, g2 = os.environ["SAT_TOKEN_G1"], os.environ["SAT_TOKEN_G2"]
        esperar("g1 lee pub_sala", _intento(sat, g1, "GET", "/items/pub_sala"), (200,))
        esperar("g1 NO escribe en pub_sala", _intento(sat, g1, "POST", "/items/pub_sala", json={"codigo": "X", "es_laboratorio": 0}), (403,))
        esperar("g1 escribe en su colección", _intento(sat, g1, "POST", "/items/sat_g1_registro", json={"clave": "k", "valor": "{}"}), (200,))
        esperar("g1 NO escribe en la de g2", _intento(sat, g1, "POST", "/items/sat_g2_registro", json={"clave": "k"}), (403,))
        esperar("g1 NO lee la de g2", _intento(sat, g1, "GET", "/items/sat_g2_registro"), (403,))
        esperar("g1 NO borra (borrado lógico)", _intento(sat, g1, "DELETE", "/items/sat_g1_registro/1"), (403,))
        esperar("g1 NO lee usuarios ni roles", _intento(sat, g1, "GET", "/users"), (403,))
        esperar("g1 NO ve el núcleo (no está en su instancia)", _intento(sat, g1, "GET", "/items/catalogo_persona"), (403, 404))
        esperar("g2 con su token propio", _intento(sat, g2, "GET", "/items/sat_g2_registro"), (200,))
        esperar("token inválido", _intento(sat, "token-falso", "GET", "/items/pub_sala"), (401, 403))
        g4 = os.environ.get("SAT_TOKEN_G4", g1)
        codigos = {_intento(sat, g4, "GET", "/items/pub_sala", reintentar=False) for _ in range(120)}
        esperar("el límite de peticiones frena a un satélite que abusa", int(429 in codigos), (1,))
    print("verificación:", "con fallas" if errores else "todo correcto")
    return 1 if errores else 0


if __name__ == "__main__":
    accion = sys.argv[1] if len(sys.argv) > 1 else ""
    if accion == "nucleo":
        configurar_nucleo()
    elif accion == "satelites":
        configurar_satelites()
    elif accion == "verificar":
        sys.exit(verificar())
    elif accion == "rol-permiso" and len(sys.argv) == 5 and sys.argv[2] in ("dar", "quitar"):
        cambiar_rol_permiso(*sys.argv[2:5])
    else:
        sys.exit(__doc__)
