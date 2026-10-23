#!/usr/bin/env python3
"""Revisa un CSV contra la plantilla de su colección y explica cada error y cómo corregirlo.

Uso: python3 plantillas_importacion/validar_plantilla.py COLECCION archivo.csv [--db plataforma.db] [--json]
Sin --db solo se revisa la forma de cada celda; con --db también las referencias y los duplicados."""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.importacion.spec import PLANTILLAS  # noqa: E402
from app.importacion.validar import formatear, validar  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("coleccion", choices=sorted(PLANTILLAS))
    ap.add_argument("archivo", type=Path)
    ap.add_argument("--db", type=Path, help="base SQLite para comprobar referencias y duplicados (solo lectura)")
    ap.add_argument("--json", action="store_true", help="salida como JSON con la forma de plataforma_fila_importada.errores")
    a = ap.parse_args(argv)
    try:
        texto = a.archivo.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        print("El archivo debe estar en UTF-8. Guárdelo como CSV UTF-8 desde la planilla.", file=sys.stderr)
        return 2
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True) if a.db else None
    cif = None
    if con is not None and os.environ.get("DATA_KEYS") and os.environ.get("INDEX_KEY"):
        from app.core.config import Settings
        cif = Settings().cifrador()
    elif con is not None:
        print("Aviso: sin DATA_KEYS e INDEX_KEY no se pueden comprobar los RUT contra la base; se revisa lo demás.", file=sys.stderr)
    informe = validar(PLANTILLAS[a.coleccion], texto, con, cif)
    for f in informe["filas"]:
        f.pop("destino", None)
    print(json.dumps(informe, ensure_ascii=False, indent=2) if a.json else formatear(informe))
    return 0 if informe["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
