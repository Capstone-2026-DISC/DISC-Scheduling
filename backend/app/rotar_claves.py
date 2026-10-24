"""Rotación de claves de cifrado: vuelve a cifrar el RUT y el correo con la clave actual (DATA_KEY_ID).

Pasos: 1) agregar la clave nueva a DATA_KEYS sin quitar la vieja y poner su id en DATA_KEY_ID; 2) reiniciar la API;
3) docker compose run --rm configurar python -m app.rotar_claves; 4) cuando no quede nada con la clave vieja, quitarla de DATA_KEYS.
Se hace por Directus, con la cuenta de administración (ADMIN_EMAIL y ADMIN_PASSWORD), no con la sesión de una persona.
Las filas crudas de importaciones no se rotan: se anonimizan al cerrar el periodo.
El índice ciego del RUT depende de INDEX_KEY: cambiarla obliga a recalcular todos los índices (no lo hace este script).
"""

import os

from .core import pii
from .core.config import get_settings
from .core.directus import Directus, exigir

COLUMNAS = (
    ("catalogo_persona", "rut_cifrado", pii.COL_RUT),
    ("catalogo_persona", "email_cifrado", pii.COL_EMAIL),
    ("horarios_envio_horario", "email_destino_cifrado", pii.COL_EMAIL_ENVIO),
)


def rotar(d: Directus, token: str, cif: pii.Cifrador) -> dict:
    cuenta = {}
    for coleccion, col, nombre in COLUMNAS:
        n = 0
        filas = exigir(d.listar(coleccion, token=token, campos=f"id,{col}", limite=-1)).datos or []
        for f in filas:
            valor = f.get(col)
            if not valor or valor.split(":", 2)[1] == cif.clave_actual:
                continue
            exigir(
                d.pedir("PATCH", f"/items/{coleccion}/{f['id']}", token=token, json={col: cif.recifrar(valor, nombre)})
            )
            n += 1
        cuenta[f"{coleccion}.{col}"] = n
    return cuenta


def main() -> None:
    s = get_settings()
    d = Directus(s.directus_url, s.servicio_token)
    r = exigir(
        d.pedir(
            "POST",
            "/auth/login",
            json={"email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"], "mode": "json"},
        )
    )
    print("recifrado con", s.data_key_id, rotar(d, r.datos["access_token"], s.cifrador()))


if __name__ == "__main__":
    main()
