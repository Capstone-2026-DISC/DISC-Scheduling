"""Rotación de claves de cifrado: vuelve a cifrar el RUT y el correo con la clave actual (DATA_KEY_ID).

Pasos: 1) agregar la clave nueva a DATA_KEYS sin quitar la vieja y poner su id en DATA_KEY_ID; 2) reiniciar la API;
3) python -m app.rotar_claves; 4) cuando no quede nada con la clave vieja, quitarla de DATA_KEYS.
Las filas crudas de importaciones no se rotan: se anonimizan al cerrar el periodo.
El índice ciego del RUT depende de INDEX_KEY: cambiarla obliga a recalcular todos los índices (no lo hace este script).
"""
from .core import pii
from .core.config import get_settings
from .core.db import conectar, escritura

COLUMNAS = (("catalogo_persona", "id", "rut_cifrado", pii.COL_RUT), ("catalogo_persona", "id", "email_cifrado", pii.COL_EMAIL),
            ("horarios_envio_horario", "id", "email_destino_cifrado", pii.COL_EMAIL_ENVIO))


def rotar(conn, cif: pii.Cifrador) -> dict:
    cuenta = {}
    with escritura(conn, None, "rotacion_de_claves"):
        for tabla, pk, col, nombre in COLUMNAS:
            n = 0
            for fila in conn.execute(f"SELECT {pk}, {col} FROM {tabla} WHERE {col} IS NOT NULL").fetchall():
                if fila[col].split(":", 2)[1] == cif.clave_actual:
                    continue
                conn.execute(f"UPDATE {tabla} SET {col} = ? WHERE {pk} = ?", (cif.recifrar(fila[col], nombre), fila[pk]))
                n += 1
            cuenta[f"{tabla}.{col}"] = n
    return cuenta


def main() -> None:
    settings = get_settings()
    print("recifrado con", settings.data_key_id, rotar(conectar(settings.db_path), settings.cifrador()))


if __name__ == "__main__":
    main()
