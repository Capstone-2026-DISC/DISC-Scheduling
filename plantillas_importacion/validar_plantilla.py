#!/usr/bin/env python3
"""Revisa un CSV contra la plantilla de su colección y explica cada error y cómo corregirlo.

Uso: python3 plantillas_importacion/validar_plantilla.py COLECCION archivo.csv [--json]
Solo revisa la forma de cada celda (tipos, rangos, listas cerradas, RUT con dígito verificador, claves repetidas dentro del
archivo). Las referencias a otras tablas y los duplicados contra la base los comprueba la API: POST /importaciones/{coleccion}."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.importacion.spec import PLANTILLAS  # noqa: E402
from app.importacion.validar import formatear, validar  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("coleccion", choices=sorted(PLANTILLAS))
    ap.add_argument("archivo", type=Path)
    ap.add_argument(
        "--json", action="store_true", help="salida como JSON con la forma de plataforma_fila_importada.errores"
    )
    a = ap.parse_args(argv)
    try:
        texto = a.archivo.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        print("El archivo debe estar en UTF-8. Guárdelo como CSV UTF-8 desde la planilla.", file=sys.stderr)
        return 2
    informe = validar(PLANTILLAS[a.coleccion], texto)
    for f in informe["filas"]:
        f.pop("destino", None)
    print(json.dumps(informe, ensure_ascii=False, indent=2) if a.json else formatear(informe))
    return 0 if informe["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
