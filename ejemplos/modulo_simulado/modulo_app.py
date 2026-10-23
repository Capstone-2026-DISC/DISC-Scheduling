"""Módulo de ejemplo de Proyecto Integrador.

Muestra cómo un grupo se conecta al sistema: habla SOLO con la instancia de Directus de los satélites, con el
token de su grupo. Lee el catálogo y el horario aprobado (tablas pub_*), guarda datos propios en su colección
sat_<grupo>_registro y puede comprobar en vivo lo que no puede hacer. No usa el login ni los tokens del core.

Variables: DIRECTUS_URL, DIRECTUS_TOKEN (el token del grupo) y GRUPO (g1 a g4).
"""
import html
import os
from urllib.parse import quote
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

TABLAS = ("pub_periodo", "pub_programa", "pub_asignatura", "pub_sala", "pub_paralelo", "pub_horario")


def crear_app(url: str | None = None, token: str | None = None, grupo: str | None = None,
              transport: httpx.BaseTransport | None = None) -> FastAPI:
    url = (url or os.environ.get("DIRECTUS_URL", "http://directus-satelites:8055")).rstrip("/")
    token = token if token is not None else os.environ.get("DIRECTUS_TOKEN", "")
    grupo = grupo or os.environ.get("GRUPO", "g1")
    mia = f"sat_{grupo}_registro"
    otro = "sat_g2_registro" if grupo != "g2" else "sat_g1_registro"
    cliente = httpx.Client(base_url=url, headers={"Authorization": f"Bearer {token}"}, timeout=10, transport=transport)
    app = FastAPI(title=f"Módulo de ejemplo ({grupo})", docs_url=None, redoc_url=None)

    def pedir(metodo: str, ruta: str, **kw) -> tuple[int, dict | None]:
        """(estado HTTP, cuerpo). 0 si Directus no responde."""
        try:
            r = cliente.request(metodo, ruta, **kw)
        except httpx.RequestError:
            return 0, None
        try:
            return r.status_code, r.json() if r.content else None
        except ValueError:
            return r.status_code, None

    def filas(coleccion: str, limite: int = 200) -> tuple[int, list[dict]]:
        estado, cuerpo = pedir("GET", f"/items/{coleccion}", params={"limit": limite, "sort": "id"})
        return estado, (cuerpo or {}).get("data", []) if estado == 200 else []

    def tabla(datos: list[dict], vacio: str) -> str:
        if not datos:
            return f"<p class=nota>{html.escape(vacio)}</p>"
        cols = list(datos[0])
        cab = "".join(f"<th>{html.escape(str(c))}</th>" for c in cols)
        cuerpo = "".join("<tr>" + "".join(f"<td>{html.escape('—' if f.get(c) is None else str(f.get(c)))}</td>" for c in cols) + "</tr>" for f in datos)
        return f"<table><tr>{cab}</tr>{cuerpo}</table>"

    def pagina(mensaje: str = "", limites: str = "") -> str:
        bloques, estados = [], []
        for t in TABLAS:
            e, datos = filas(t, 5)
            estados.append(e)
            if e == 200:
                bloques.append(f"<h3>{t}</h3>{tabla(datos, 'Sin filas: el core aún no publicó datos (POST /publicacion).')}")
            else:
                bloques.append(f"<h3>{t}</h3><p class=error>No se pudo leer ({e}).</p>")
        e, mios = filas(mia)
        estados.append(e)
        conectado = any(x not in (0, 502, 503, 504) for x in estados)
        limitado = 429 in estados
        propios = tabla(mios, "Todavía no hay registros.") if e == 200 else f"<p class=error>No se pudo leer ({e}).</p>"
        ids = "".join(f"<form method=post action=/registro/{int(f['id'])}/eliminar class=en-linea>"
                      f"<button>Eliminar #{int(f['id'])}</button></form>" for f in mios if "id" in f)
        return f"""<!doctype html><html lang=es><meta charset=utf-8><meta name=viewport content="width=device-width, initial-scale=1">
<title>Módulo de ejemplo {html.escape(grupo)}</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem;color:#1b2430}}
table{{border-collapse:collapse;width:100%;margin:.5rem 0}}td,th{{border:1px solid #d5dae1;padding:.3rem .5rem;text-align:left}}
th{{background:#eef2f6}}.nota{{color:#5c6773}}.error{{color:#b3261e}}.ok{{color:#1b7f3b}}.aviso{{background:#fff4d6;padding:.5rem 1rem}}
.en-linea{{display:inline-block;margin:.2rem}}input{{padding:.3rem;margin-right:.5rem}}</style>
<h1>Módulo de ejemplo del grupo {html.escape(grupo)}</h1>
<p>Se conecta solo a Directus con el token de su grupo. Estado de la conexión:
<strong class={'ok' if conectado else 'error'}>{'conectado' if conectado else 'sin conexión'}</strong>.</p>
{f'<p class=aviso>{html.escape(mensaje)}</p>' if mensaje else ''}
{"<p class=aviso>Directus limitó las peticiones de este módulo (429). Espere un minuto y recargue.</p>" if limitado else ''}
<h2>Lo que lee del core (solo lectura)</h2>{''.join(bloques)}
<h2>Lo que guarda este módulo en {html.escape(mia)}</h2>{propios}
<form method=post action=/registro><input name=clave placeholder=clave required>
<input name=valor placeholder='valor (JSON, opcional)'><button>Guardar</button></form>{ids}
<h2>Lo que no puede hacer</h2><p class=nota>Cada intento debe ser rechazado. Ninguno cambia datos si los permisos están bien.</p>
<form method=post action=/limites><button>Probar mis límites</button></form>{limites}
</html>"""

    @app.get("/", response_class=HTMLResponse)
    def inicio(mensaje: str = ""):
        return pagina(mensaje[:200])

    @app.get("/salud")
    def salud():
        """Para el healthcheck del contenedor: no llama a Directus, que limita las peticiones por minuto."""
        return {"ok": True}

    @app.get("/estado")
    def estado():
        e, _ = pedir("GET", "/server/ping")
        lectura = {t: filas(t, 1)[0] for t in TABLAS}
        return {"grupo": grupo, "directus": url, "conectado": e == 200, "lectura": lectura, "coleccion_propia": mia}

    @app.post("/registro")
    def guardar(clave: str = Form(...), valor: str = Form("")):
        cuerpo = {"clave": clave[:200]}
        if valor.strip():
            cuerpo["valor"] = valor
        e, resp = pedir("POST", f"/items/{mia}", json=cuerpo)
        msg = "Registro guardado." if e == 200 else f"Directus rechazó el registro ({e})."
        if e == 400 and resp:
            msg += " " + "; ".join(x.get("message", "") for x in resp.get("errors", []))[:150]
        return RedirectResponse(f"/?mensaje={quote(msg)}", status_code=303)

    @app.post("/registro/{rid}/eliminar")
    def eliminar(rid: int):
        # borrado lógico: el token del grupo no tiene permiso de DELETE
        ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        e, _ = pedir("PATCH", f"/items/{mia}/{rid}", json={"eliminado_en": ahora})
        msg = "Registro eliminado (borrado lógico)." if e == 200 else f"No se pudo eliminar ({e})."
        return RedirectResponse(f"/?mensaje={quote(msg)}", status_code=303)

    @app.post("/limites", response_class=HTMLResponse)
    def limites():
        intentos = [
            ("Leer datos personales (catalogo_persona)", "GET", "/items/catalogo_persona", None),
            ("Escribir en el catálogo publicado (pub_sala)", "POST", "/items/pub_sala", {"codigo": "X", "es_laboratorio": 0}),
            (f"Escribir en la colección de otro grupo ({otro})", "POST", f"/items/{otro}", {"clave": "x"}),
            (f"Leer la colección de otro grupo ({otro})", "GET", f"/items/{otro}", None),
            ("Borrar de verdad un registro propio", "DELETE", f"/items/{mia}/1", None),
            ("Ver usuarios y roles", "GET", "/users", None),
        ]
        filas_ = []
        for desc, metodo, ruta, cuerpo in intentos:
            e, _ = pedir(metodo, ruta, **({"json": cuerpo} if cuerpo else {}))
            rechazado = e in (401, 403)
            filas_.append(f"<tr><td>{html.escape(desc)}</td><td>{metodo}</td><td>{e}</td>"
                          f"<td class={'ok' if rechazado else 'error'}>{'rechazado, correcto' if rechazado else 'NO fue rechazado'}</td></tr>")
        cuerpo = "<table><tr><th>Intento</th><th>Método</th><th>Respuesta</th><th>Resultado</th></tr>" + "".join(filas_) + "</table>"
        return pagina(limites=cuerpo)

    return app


def app_por_defecto() -> FastAPI:
    return crear_app()
