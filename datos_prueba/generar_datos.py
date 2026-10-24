#!/usr/bin/env python3
"""Genera datos de prueba FICTICIOS y reproducibles para la plataforma.

Nada de lo que sale de aquí corresponde a personas, cursos o cifras reales. Con la misma semilla produce
exactamente los mismos archivos. Ver DATOS_DE_PRUEBA.md.

Uso: python3 datos_prueba/generar_datos.py [--semilla N] [--db RUTA] [--csv CARPETA]
"""

import argparse
import base64
import csv
import hashlib
import random
import sqlite3
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ.parent / "backend"))
from app.core import pii  # noqa: E402

ESQUEMA = RAIZ.parent / "db" / "esquema_plataforma.sql"
SEMILLA_POR_DEFECTO = 20262026

# Claves de cifrado SOLO para estos datos ficticios. Son públicas a propósito (están en el repositorio) y no protegen
# nada: sirven para que la base de prueba tenga la misma forma cifrada que la real y para poder leerla en las pruebas.
# Nunca se usan en un entorno con datos reales; esas claves salen del .env (scripts/configure.py).
DATA_KEYS_PRUEBA = "k1=" + base64.urlsafe_b64encode(
    hashlib.sha256(b"disc-scheduling datos de prueba: cifrado").digest()
).decode().rstrip("=")
INDEX_KEY_PRUEBA = (
    base64.urlsafe_b64encode(hashlib.sha256(b"disc-scheduling datos de prueba: indice").digest()).decode().rstrip("=")
)


def cifrador_de_prueba() -> "pii.Cifrador":
    return pii.Cifrador.desde_entorno(DATA_KEYS_PRUEBA, "k1", INDEX_KEY_PRUEBA)


def nonce_fijo(columna: str, valor: str) -> bytes:
    """Nonce derivado del dato, solo para que los datos de prueba salgan idénticos con la misma semilla.
    En producción el nonce es aleatorio por valor."""
    return hashlib.sha256(f"{columna}:{valor}".encode()).digest()[:12]


# RUT ficticios: cuerpo de 8 dígitos entre 59.000.000 y 59.999.999. Los RUT de personas naturales chilenas están por
# debajo de 50.000.000 (los extranjeros con RUT provisorio usan otro formato), así que este rango no debería
# corresponder a una persona. Puede coincidir con una empresa u organización real; no se garantiza que no exista.
RUT_MIN, RUT_MAX = 59_000_000, 59_999_999

SILABAS_NOMBRE = ["ma", "ro", "li", "ve", "ta", "no", "ki", "su", "be", "da", "fi", "lo", "ze", "pa", "ni", "cu"]
SILABAS_APELLIDO = ["vel", "quin", "tar", "mor", "sal", "gren", "dul", "bar", "fen", "tol", "ris", "lam", "cor", "ven"]
FINAL_NOMBRE = ["a", "o", "el", "io", "an", "ia"]
FINAL_APELLIDO = ["ez", "ini", "ado", "eri", "ura", "oli"]

TABLAS_CSV = [
    "catalogo_periodo",
    "catalogo_programa",
    "catalogo_asignatura",
    "catalogo_plan_nivel",
    "catalogo_sala",
    "catalogo_persona",
    "catalogo_docente",
    "catalogo_ayudante",
    "horarios_paralelo",
    "horarios_paralelo_docente",
    "horarios_sesion",
    "horarios_disponibilidad_docente",
    "finanzas_tarifa",
    "finanzas_presupuesto",
    "finanzas_nombramiento",
    "proyeccion_inscripcion_historica",
]


def digito_verificador(cuerpo: int) -> str:
    suma, mult = 0, 2
    for d in reversed(str(cuerpo)):
        suma += int(d) * mult
        mult = 2 if mult == 7 else mult + 1
    resto = 11 - suma % 11
    return "0" if resto == 11 else "K" if resto == 10 else str(resto)


def sin_tildes(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()


class Generador:
    def __init__(self, semilla: int):
        self.r = random.Random(semilla)
        self.ruts: set[int] = set()

    def palabra(self, silabas: list[str], finales: list[str], n: int) -> str:
        return ("".join(self.r.choice(silabas) for _ in range(n)) + self.r.choice(finales)).capitalize()

    def persona(self) -> tuple[str, str, str]:
        while True:
            cuerpo = self.r.randint(RUT_MIN, RUT_MAX)
            if cuerpo not in self.ruts:
                self.ruts.add(cuerpo)
                break
        nombre = self.palabra(SILABAS_NOMBRE, FINAL_NOMBRE, 2)
        ap1 = self.palabra(SILABAS_APELLIDO, FINAL_APELLIDO, 2)
        ap2 = self.palabra(SILABAS_APELLIDO, FINAL_APELLIDO, 1)
        correo = sin_tildes(f"{nombre}.{ap1}{len(self.ruts)}").lower() + "@ejemplo.invalid"
        return f"{cuerpo}-{digito_verificador(cuerpo)}", f"{nombre} {ap1} {ap2}", correo


def crear_base(ruta: Path) -> sqlite3.Connection:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if ruta.exists():
        ruta.unlink()
    con = sqlite3.connect(ruta, isolation_level=None)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(ESQUEMA.read_text(encoding="utf-8"))
    return con


def cargar(con: sqlite3.Connection, g: Generador) -> dict:
    r = g.r
    ex = con.execute
    con.execute("BEGIN")
    # periodos: el vigente y dos cerrados para el historial de inscritos
    ex(
        "INSERT INTO catalogo_periodo (codigo, fecha_inicio, fecha_fin, estado) VALUES ('202520', '2025-08-04', '2025-12-20', 'cerrado')"
    )
    ex(
        "INSERT INTO catalogo_periodo (codigo, fecha_inicio, fecha_fin, estado) VALUES ('202610', '2026-03-09', '2026-07-18', 'cerrado')"
    )
    ex(
        "INSERT INTO catalogo_periodo (codigo, fecha_inicio, fecha_fin, estado) VALUES ('202620', '2026-08-03', '2026-12-19', 'vigente')"
    )
    for i, tipo in enumerate(("pregrado", "pregrado", "minor"), 1):
        ex(
            "INSERT INTO catalogo_programa (codigo, nombre, tipo) VALUES (?, ?, ?)",
            (f"PRG{i}", f"Programa de prueba {i}", tipo),
        )
    for i in range(1, 13):
        ex(
            "INSERT INTO catalogo_asignatura (codigo, nombre, area, requiere_laboratorio) VALUES (?, ?, ?, ?)",
            (
                f"FAIC-{100 + i:05d}",
                f"Asignatura de prueba {i:02d}",
                r.choice(["Ficticia A", "Ficticia B", "Ficticia C"]),
                1 if i in (3, 6, 9) else 0,
            ),
        )
    for asig in range(1, 13):
        for prog in r.sample([1, 2, 3], r.randint(1, 2)):
            ex(
                "INSERT INTO catalogo_plan_nivel (programa_id, asignatura_id, nivel, caracter) VALUES (?, ?, ?, ?)",
                (prog, asig, r.randint(1, 8), r.choice(["obligatoria", "obligatoria", "electiva"])),
            )
    for i in range(1, 7):
        ex(
            "INSERT INTO catalogo_sala (codigo, nombre, capacidad, es_laboratorio, administrada_por) VALUES (?, ?, ?, ?, 'disc')",
            (f"ZZ-{100 + i}", f"Sala de prueba {i}", r.choice([20, 30, 40, 50, 60]), 1 if i <= 2 else 0),
        )

    # personas: 14 docentes (6 de planta, 8 por hora) y 6 ayudantes
    cif = cifrador_de_prueba()
    for n in range(20):
        rut, nombre, correo = g.persona()
        pid = ex(
            "INSERT INTO catalogo_persona (rut_cifrado, rut_indice, nombre, email_cifrado) VALUES (?, ?, ?, ?)",
            (
                cif.cifrar(rut, pii.COL_RUT, nonce_fijo(pii.COL_RUT, rut)),
                cif.indice_rut(rut),
                nombre,
                cif.cifrar(correo, pii.COL_EMAIL, nonce_fijo(pii.COL_EMAIL, correo)),
            ),
        ).lastrowid
        if n < 14:
            ex(
                "INSERT INTO catalogo_docente (persona_id, tipo_contrato) VALUES (?, ?)",
                (pid, "planta" if n < 6 else "hora"),
            )
        else:
            ex("INSERT INTO catalogo_ayudante (persona_id) VALUES (?)", (pid,))

    # oferta del periodo vigente (id 3): cátedra para todas, laboratorio para las que lo requieren
    nrc = 59000
    paralelos = []
    for asig in range(1, 13):
        componentes = [("C1", "catedra")] + ([("L01", "laboratorio")] if asig in (3, 6, 9) else [])
        for codigo, comp in componentes:
            nrc += 1
            pid = ex(
                "INSERT INTO horarios_paralelo (periodo_id, asignatura_id, nrc, codigo, componente, cupo_estimado, sesiones_semana) "
                "VALUES (3, ?, ?, ?, ?, ?, ?)",
                (asig, nrc, codigo, comp, r.randint(18, 55), 2 if comp == "catedra" else 1),
            ).lastrowid
            paralelos.append((pid, comp))
            for numero in range(1, (2 if comp == "catedra" else 1) + 1):
                ex("INSERT INTO horarios_sesion (paralelo_id, numero) VALUES (?, ?)", (pid, numero))
            ex("INSERT INTO horarios_paralelo_docente (paralelo_id, docente_id) VALUES (?, ?)", (pid, r.randint(1, 14)))

    dias, bloques = ["Lu", "Ma", "Mi", "Ju", "Vi"], ["A", "B", "C", "D", "E", "F"]
    for docente in range(7, 15):  # los docentes por hora declaran qué bloques no pueden
        for dia, bloque in r.sample([(d, b) for d in dias for b in bloques], 6):
            ex(
                "INSERT INTO horarios_disponibilidad_docente (periodo_id, docente_id, dia, bloque, tipo) VALUES (3, ?, ?, ?, 'no_disponible')",
                (docente, dia, bloque),
            )

    # finanzas: valores ficticios por categoría (los de verdad se levantan con el Encargado Docente)
    categorias = [f[0] for f in ex("SELECT id FROM finanzas_categoria ORDER BY id").fetchall()]
    for cid in categorias:
        ex(
            "INSERT INTO finanzas_tarifa (categoria_id, valor_hora, vigente_desde) VALUES (?, ?, '2026-03-01')",
            (cid, 10_000 + 1_500 * cid),
        )
    ex("INSERT INTO finanzas_presupuesto (anio, tipo_persona, monto_anual) VALUES (2026, 'profesor_hora', 18000000)")
    ex("INSERT INTO finanzas_presupuesto (anio, tipo_persona, monto_anual) VALUES (2026, 'ayudante', 6000000)")
    for docente in range(7, 15):
        paralelo = paralelos[(docente - 7) % len(paralelos)][0]
        ex(
            "INSERT INTO finanzas_nombramiento (persona_id, periodo_id, categoria_id, paralelo_id, horas_semanales, fecha_inicio, fecha_fin, origen, creado_en) "
            "VALUES (?, 3, ?, ?, ?, '2026-08-03', '2026-12-19', 'manual', '2026-08-01T00:00:00Z')",
            (docente, r.randint(1, 4), paralelo, r.choice([3, 4.5, 6])),
        )
    for ayudante in range(15, 21):
        ex(
            "INSERT INTO finanzas_nombramiento (persona_id, periodo_id, categoria_id, horas_semanales, fecha_inicio, fecha_fin, origen, creado_en) "
            "VALUES (?, 3, ?, ?, '2026-08-03', '2026-12-19', 'manual', '2026-08-01T00:00:00Z')",
            (ayudante, r.randint(5, 7), r.choice([4, 6, 8])),
        )

    for asig in range(1, 13):  # historial de inscritos de los dos periodos cerrados
        base = r.randint(20, 55)
        for periodo in (1, 2):
            ex(
                "INSERT INTO proyeccion_inscripcion_historica (asignatura_id, periodo_id, fuente, inscritos) VALUES (?, ?, 'planilla', ?)",
                (asig, periodo, max(0, base + r.randint(-8, 8))),
            )
    con.execute("COMMIT")
    return {t: ex(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLAS_CSV}


def exportar_personas(con: sqlite3.Connection, carpeta: Path) -> None:
    """catalogo_persona se exporta en el formato de la plantilla de importación (rut, nombre, email en claro y ficticios),
    no como la tabla, que solo tiene texto cifrado."""
    cif = cifrador_de_prueba()
    with open(carpeta / "catalogo_persona.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["rut", "nombre", "email"])
        for fila in con.execute("SELECT rut_cifrado, nombre, email_cifrado FROM catalogo_persona ORDER BY id"):
            w.writerow(
                [cif.descifrar(fila[0], pii.COL_RUT), fila[1], cif.descifrar(fila[2], pii.COL_EMAIL) if fila[2] else ""]
            )


def exportar_csv(con: sqlite3.Connection, carpeta: Path) -> None:
    carpeta.mkdir(parents=True, exist_ok=True)
    exportar_personas(con, carpeta)
    for tabla in (t for t in TABLAS_CSV if t != "catalogo_persona"):
        cursor = con.execute(f"SELECT * FROM {tabla} ORDER BY 1")
        with open(carpeta / f"{tabla}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow([c[0] for c in cursor.description])
            w.writerows(cursor.fetchall())


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--semilla", type=int, default=SEMILLA_POR_DEFECTO)
    ap.add_argument("--db", type=Path, default=RAIZ / "salida" / "plataforma_prueba.db")
    ap.add_argument("--csv", type=Path, default=RAIZ / "csv")
    a = ap.parse_args(argv)
    con = crear_base(a.db)
    cuentas = cargar(con, Generador(a.semilla))
    exportar_csv(con, a.csv)
    con.close()
    print(f"semilla {a.semilla}: " + ", ".join(f"{t}={n}" for t, n in cuentas.items()))
    return cuentas


if __name__ == "__main__":
    main()
