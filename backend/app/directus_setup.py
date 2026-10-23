"""Configura Directus de forma repetible (idempotente) a partir del esquema y de la base.

  python -m app.directus_setup nucleo       Directus sobre plataforma.db: colecciones, roles y usuarios
  python -m app.directus_setup satelites    Directus sobre satelites.db: un rol y un token por grupo
  python -m app.directus_setup verificar    Comprueba permisos reales contra ambas instancias

Variables: DIRECTUS_URL, ADMIN_EMAIL, ADMIN_PASSWORD (administrador de arranque de Directus); SATELITES_URL,
SAT_ADMIN_EMAIL, SAT_ADMIN_PASSWORD; SAT_TOKEN_G1..G4; SEED_ADMIN_PASSWORD, SEED_TEST_PASSWORD. Ninguna se guarda.
"""
import os
import sqlite3
import sys
import time

import httpx

from . import directus_matriz as matriz
from .core.config import get_settings
from .seed import ADMIN_EMAIL as SEED_ADMIN, PRUEBA_EMAIL as SEED_PRUEBA

GRUPOS = ("g1", "g2", "g3", "g4")
CARPETAS = {"identidad": "badge", "plataforma": "settings", "catalogo": "menu_book", "horarios": "calendar_month",
            "finanzas": "payments", "proyeccion": "trending_up"}


class Directus:
    def __init__(self, url: str, email: str, clave: str):
        self.http = httpx.Client(base_url=url, timeout=30)
        for _ in range(60):
            try:
                r = self.http.post("/auth/login", json={"email": email, "password": clave})
                if r.status_code != 429:
                    break
                time.sleep(15)
            except httpx.RequestError:
                time.sleep(2)
        else:
            raise RuntimeError(f"Directus no responde en {url}")
        if r.status_code != 200:
            raise RuntimeError(f"No se pudo iniciar sesión en Directus: {r.text[:200]}")
        self.http.headers["Authorization"] = f"Bearer {r.json()['data']['access_token']}"

    def pedir(self, metodo: str, ruta: str, **kw):
        for _ in range(8):               # el límite de peticiones de Directus también rige para este script
            r = self.http.request(metodo, ruta, **kw)
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
        datos = {"email": email, "role": rol_id, "status": "active", **extra}
        if clave:
            datos["password"] = clave
        u = self.buscar("/users", "email", email)
        if u:
            self.pedir("PATCH", f"/users/{u['id']}", json=datos)
            return u["id"]
        return self.pedir("POST", "/users", json=datos)["id"]

    def asegurar_campo_usuario(self, campo: str, tipo: str, nota: str) -> None:
        existentes = {f["field"] for f in self.pedir("GET", "/fields/directus_users")}
        if campo not in existentes:
            self.pedir("POST", "/fields/directus_users", json={"field": campo, "type": tipo,
                                                                "meta": {"interface": "input", "note": nota}, "schema": {}})

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


def _core():
    conn = sqlite3.connect(f"file:{get_settings().db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def configurar_nucleo() -> None:
    d = Directus(os.environ.get("DIRECTUS_URL", "http://directus:8055"), os.environ["ADMIN_EMAIL"], os.environ["ADMIN_PASSWORD"])
    core = _core()
    info = matriz.esquema(core)
    tablas = sorted(t for t in info if t not in matriz.SIN_ACCESO)
    d.rastrear(tablas)
    d.asegurar_campo_usuario("departamento_id", "integer", "Departamento al que se limita la lectura (id)")
    roles = {}
    for (codigo,) in core.execute("SELECT codigo FROM identidad_rol WHERE eliminado_en IS NULL AND activo = 1"):
        if codigo == "modulo_satelite":
            continue        # los satélites entran por la otra instancia, con réplica de solo lectura
        perms = {p[0] for p in core.execute("SELECT permiso FROM identidad_rol_permiso WHERE rol = ? AND revocado_en IS NULL", (codigo,))}
        pol = d.politica(f"disc_{codigo}")
        d.reemplazar_permisos(pol, matriz.permisos_de_lectura(info, perms))
        roles[codigo] = d.rol(f"disc_{codigo}", pol)
        print(f"rol {codigo}: {len(matriz.permisos_de_lectura(info, perms))} colecciones de lectura")
    # usuarios de Directus para los usuarios semilla (mismas claves que en la API; nunca se imprimen)
    for email, var in ((SEED_ADMIN, "SEED_ADMIN_PASSWORD"), (SEED_PRUEBA, "SEED_TEST_PASSWORD")):
        for fila in core.execute("SELECT ur.rol, ur.departamento_id FROM identidad_usuario u JOIN identidad_usuario_rol ur "
                                 "ON ur.usuario_id = u.id AND ur.revocado_en IS NULL WHERE u.email = ? LIMIT 1", (email,)):
            if fila["rol"] in roles and os.environ.get(var):
                d.usuario(email, os.environ[var], roles[fila["rol"]], departamento_id=fila["departamento_id"] or 1)
                print(f"usuario {email} -> rol {fila['rol']}")


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
        r = httpx.request(metodo, base + ruta, headers={"Authorization": f"Bearer {token}"}, timeout=15, **kw)
        if r.status_code != 429 or not reintentar:
            return r.status_code
        espera = r.headers.get("retry-after", "10")
        time.sleep(min(float(espera) if espera.replace(".", "").isdigit() else 10, 65) + 1)
    return 429


def verificar() -> int:
    errores = []

    def esperar(desc, obtenido, esperado):
        ok = obtenido in esperado
        print(("ok    " if ok else "FALLA ") + f"{desc} -> {obtenido}")
        if not ok:
            errores.append(desc)

    base = os.environ.get("DIRECTUS_URL", "http://directus:8055")
    r = httpx.post(base + "/auth/login", json={"email": SEED_PRUEBA, "password": os.environ["SEED_TEST_PASSWORD"]})
    esperar("consulta inicia sesión en Directus", r.status_code, (200,))
    tok = r.json()["data"]["access_token"]
    esperar("consulta lee catalogo_sala", _intento(base, tok, "GET", "/items/catalogo_sala"), (200,))
    esperar("consulta NO lee finanzas_tarifa", _intento(base, tok, "GET", "/items/finanzas_tarifa"), (403,))
    esperar("consulta NO lee catalogo_persona (datos personales)", _intento(base, tok, "GET", "/items/catalogo_persona"), (403,))
    esperar("consulta NO lee la auditoría", _intento(base, tok, "GET", "/items/plataforma_auditoria"), (403,))
    esperar("consulta NO lee identidad_sesion", _intento(base, tok, "GET", "/items/identidad_sesion"), (403,))
    esperar("consulta NO escribe en el núcleo", _intento(base, tok, "POST", "/items/catalogo_sala", json={"codigo": "ZZ"}), (403,))
    esperar("consulta NO borra", _intento(base, tok, "DELETE", "/items/catalogo_sala/1"), (403,))
    r = httpx.post(base + "/auth/login", json={"email": SEED_ADMIN, "password": os.environ["SEED_ADMIN_PASSWORD"]})
    tok_a = r.json()["data"]["access_token"]
    esperar("administrador lee finanzas_tarifa", _intento(base, tok_a, "GET", "/items/finanzas_tarifa"), (200,))
    esperar("administrador lee la auditoría", _intento(base, tok_a, "GET", "/items/plataforma_auditoria"), (200,))
    esperar("administrador NO escribe en el núcleo por Directus", _intento(base, tok_a, "POST", "/items/catalogo_sala", json={"codigo": "ZZ"}), (403,))
    usuarios = httpx.get(base + "/items/identidad_usuario", headers={"Authorization": f"Bearer {tok_a}"}).text
    esperar("el hash de clave no se expone", int("hash_clave" in usuarios), (0,))

    sin_firma = _core().execute("SELECT count(*) FROM plataforma_v_cambios_sin_usuario").fetchone()[0]
    esperar("ningún cambio de datos quedó sin usuario en la auditoría", sin_firma, (0,))

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
    else:
        sys.exit(__doc__)
