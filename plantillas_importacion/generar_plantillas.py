#!/usr/bin/env python3
"""Genera las plantillas CSV (y XLSX si openpyxl está instalado) y el README desde backend/app/importacion/spec.py,
la misma especificación que usa la validación, para que documento y reglas no se desvíen.

Uso: python3 plantillas_importacion/generar_plantillas.py"""
import csv
import sys
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "backend"))
from app.importacion.spec import ORDEN_DE_CARGA, PLANTILLAS  # noqa: E402

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill
except ImportError:                                     # el XLSX es opcional
    openpyxl = None

TIPOS = {"texto": "texto", "entero": "número entero", "decimal": "número decimal", "fecha": "fecha AAAA-MM-DD", "bool": "0 o 1",
         "enum": "lista cerrada", "rut": "RUT sin puntos con guion", "periodo": "seis dígitos (202620)",
         "codigo_asig": "código FAIC-00000"}


def escribir_csv(p) -> None:
    with open(AQUI / "csv" / f"{p.coleccion}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow([c.nombre for c in p.columnas])
        w.writerow([c.ejemplo for c in p.columnas])


def escribir_xlsx(p) -> None:
    libro = openpyxl.Workbook()
    libro.properties.creator = "nico-alvz"                  # sin marcas de herramientas en los metadatos
    libro.properties.lastModifiedBy = "nico-alvz"
    libro.properties.created = libro.properties.modified = datetime(2026, 10, 23)   # el archivo sale igual cada vez
    hoja = libro.active
    hoja.title = "datos"
    hoja.append([c.nombre for c in p.columnas])
    hoja.append([c.ejemplo for c in p.columnas])
    for celda in hoja[1]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor="0B2545")
    for col in hoja.columns:
        hoja.column_dimensions[col[0].column_letter].width = max(14, len(str(col[0].value)) + 4)
    ayuda = libro.create_sheet("reglas")
    ayuda.append(["columna", "tipo", "obligatoria", "regla", "valores permitidos"])
    for c in p.columnas:
        ayuda.append([c.nombre, TIPOS[c.tipo], "sí" if c.requerido else "no", c.regla, ", ".join(c.valores)])
    libro.save(AQUI / "xlsx" / f"{p.coleccion}.xlsx")


def readme() -> str:
    out = ["# Plantillas de importación", "",
           "Cada plantilla corresponde a una colección de la plataforma. La primera fila es el encabezado, que no se puede cambiar, y la segunda es un ejemplo ficticio que se reemplaza por los datos. Los archivos están en `csv/` y, si hay `openpyxl`, también en `xlsx/` (una hoja `datos` y otra `reglas`).",
           "", "**Los ejemplos son ficticios.** Los datos reales del departamento no se suben nunca al repositorio.", "",
           "## Cómo cargarlas", "",
           "1. Copie la plantilla, reemplace la fila de ejemplo con sus datos y guárdela como **CSV UTF-8** (separado por comas).",
           "2. Revísela sin cargar nada:", "",
           "   ```bash", "   python3 plantillas_importacion/validar_plantilla.py catalogo_asignatura mis_asignaturas.csv", "   ```", "",
           "   o por la API, que además cruza las referencias contra la base:", "",
           "   ```bash",
           "   curl -X POST localhost:8000/importaciones/catalogo_asignatura -H \"Authorization: Bearer $TOKEN\" \\",
           "        -H 'Content-Type: text/csv' --data-binary @mis_asignaturas.csv",
           "   ```", "",
           "3. Si el informe no tiene errores, cárguela agregando `?confirmar=true`. Se carga completa o no se carga ninguna fila, y la importación queda registrada con quién, cuándo y desde qué IP.", "",
           "Cada error dice la fila, la columna, qué falló y cómo corregirlo. La importación solo agrega filas nuevas: una fila cuya clave ya existe se informa como error, no se actualiza.", "",
           "## Orden de carga", "",
           "Las referencias se escriben con la clave natural (código, RUT, NRC o periodo) y no con el id interno, por lo que la tabla referida debe cargarse antes.", "",
           "| Orden | Colección | Depende de | Permiso |", "| --- | --- | --- | --- |"]
    for n, c in enumerate(ORDEN_DE_CARGA, 1):
        p = PLANTILLAS[c]
        out.append(f"| {n} | `{c}` | {', '.join(f'`{d}`' for d in p.dependencias) or 'nada'} | `{p.permiso_edicion}` |")
    for c in ORDEN_DE_CARGA:
        p = PLANTILLAS[c]
        out += ["", f"## `{c}`", "", p.descripcion, "", f"Clave de la fila: {', '.join(f'`{k}`' for k in p.clave)}.", "",
                "| Columna | Tipo | Obligatoria | Regla | Ejemplo |", "| --- | --- | --- | --- | --- |"]
        for col in p.columnas:
            regla = col.regla + (f" Valores: {', '.join(col.valores)}." if col.valores else "")
            out.append(f"| `{col.nombre}` | {TIPOS[col.tipo]} | {'sí' if col.requerido else 'no'} | {regla.strip()} | {col.ejemplo or '(vacío)'} |")
    return "\n".join(out) + "\n"


def main() -> None:
    (AQUI / "csv").mkdir(exist_ok=True)
    if openpyxl:
        (AQUI / "xlsx").mkdir(exist_ok=True)
    for p in PLANTILLAS.values():
        escribir_csv(p)
        if openpyxl:
            escribir_xlsx(p)
    (AQUI / "README.md").write_text(readme(), encoding="utf-8")
    print(f"{len(PLANTILLAS)} plantillas CSV" + (f" y {len(PLANTILLAS)} XLSX" if openpyxl else " (sin XLSX: falta openpyxl)"))


if __name__ == "__main__":
    main()
