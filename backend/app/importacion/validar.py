"""Validación de plantillas de importación. Cada problema dice la columna, qué falló y cómo corregirlo, con la forma
que usa plataforma_fila_importada.errores: {columna, gravedad, falla, como_corregir}."""
import csv
import io
import re
import sqlite3
from datetime import date

from ..core.pii import normalizar_rut
from .spec import PLANTILLAS, REF_DESTINO, Col, Plantilla

PERIODO_RE = re.compile(r"^\d{4}(10|20)$")
ASIG_RE = re.compile(r"^[A-Z]{4}-\d{5}$")
RUT_RE = re.compile(r"^\d{7,8}-[\dK]$")


def dv_rut(cuerpo: str) -> str:
    suma, mult = 0, 2
    for d in reversed(cuerpo):
        suma += int(d) * mult
        mult = 2 if mult == 7 else mult + 1
    resto = 11 - suma % 11
    return "0" if resto == 11 else "K" if resto == 10 else str(resto)


def error(col: str, falla: str, como: str, gravedad: str = "bloqueante") -> dict:
    return {"columna": col, "gravedad": gravedad, "falla": falla, "como_corregir": como}


def leer_csv(texto: str) -> tuple[list[str], list[dict]]:
    lector = csv.DictReader(io.StringIO(texto.lstrip("﻿")))
    filas = [{(k or "").strip(): (v or "").strip() for k, v in f.items()} for f in lector]
    return [c.strip() for c in (lector.fieldnames or [])], filas


def _celda(col: Col, valor: str):
    """(valor normalizado, error|None). Un valor vacío es válido si la columna no es obligatoria."""
    if valor == "":
        if col.requerido:
            return None, error(col.nombre, "Falta el valor, la columna es obligatoria.",
                               f"Complete la columna «{col.nombre}». {col.regla}".strip())
        return None, None
    t = col.tipo
    try:
        if t in ("entero", "bool"):
            if not re.fullmatch(r"-?\d+", valor):
                raise ValueError("no es un número entero")
            n = int(valor)
            if t == "bool" and n not in (0, 1):
                raise ValueError("debe ser 0 o 1")
            if col.minimo is not None and n < col.minimo or col.maximo is not None and n > col.maximo:
                raise ValueError(f"fuera del rango permitido ({col.minimo} a {col.maximo})")
            return n, None
        if t == "decimal":
            n = float(valor.replace(",", "."))
            if col.minimo is not None and n < col.minimo or col.maximo is not None and n > col.maximo:
                raise ValueError(f"fuera del rango permitido ({col.minimo} a {col.maximo})")
            return n, None
        if t == "fecha":
            date.fromisoformat(valor)
            return valor, None
        if t == "enum":
            if valor not in col.valores:
                raise ValueError("no es un valor permitido")
            return valor, None
        if t == "periodo":
            if not PERIODO_RE.match(valor):
                raise ValueError("el periodo son seis dígitos y termina en 10 o 20")
            return valor, None
        if t == "codigo_asig":
            if not ASIG_RE.match(valor):
                raise ValueError("el código es cuatro letras mayúsculas, guion y cinco dígitos")
            return valor, None
        if t == "rut":
            v = normalizar_rut(valor)                        # acepta puntos, minúscula y la falta del guion
            if not RUT_RE.match(v):
                raise ValueError("el RUT son siete u ocho dígitos, guion y dígito verificador")
            if dv_rut(v.split("-")[0]) != v[-1]:
                raise ValueError(f"el dígito verificador no corresponde (debería ser {dv_rut(v.split('-')[0])})")
            return v, None
        if t == "texto" and col.nombre == "email" and "@" not in valor:
            raise ValueError("no parece un correo")
        return valor, None
    except ValueError as e:
        ejemplo = f" Ejemplo: {col.ejemplo}." if col.ejemplo else ""
        permitidos = f" Valores permitidos: {', '.join(col.valores)}." if col.valores else ""
        visto = "" if col.es_pii else f" «{valor}»"           # un dato personal no se repite en el informe
        return None, error(col.nombre, f"Valor{visto} inválido: {e}.", f"Corrija «{col.nombre}».{permitidos}{ejemplo}")


def _buscar(con, sql: str, *args):
    fila = con.execute(sql, args).fetchone()
    return None if fila is None else fila[0]


def resolver(con: sqlite3.Connection, plantilla: Plantilla, datos: dict, cif=None) -> tuple[dict, list[dict]]:
    """Traduce claves naturales a ids. Devuelve las columnas de la base y los errores de referencia.
    `cif` (core.pii.Cifrador) cifra el RUT y el correo y permite buscar personas por su índice ciego; sin él no se
    puede comprobar ni cargar nada que dependa de una persona."""
    destino, errores = {}, []
    dept = None
    dcol = next((c for c in plantilla.columnas if c.ref == "departamento"), None)
    codigo_depto = (datos.get(dcol.nombre) if dcol else None) or "DISC"
    dept = _buscar(con, "SELECT id FROM identidad_departamento WHERE codigo = upper(?) AND eliminado_en IS NULL", codigo_depto)
    if dcol and dept is None:
        errores.append(error(dcol.nombre, f"El departamento «{codigo_depto}» no existe.", "Use el código de un departamento creado, por ejemplo DISC."))
    periodo_id = None
    for col in plantilla.columnas:
        valor = datos.get(col.nombre)
        dest = col.destino or REF_DESTINO.get(col.ref or "", col.nombre)
        if col.ref is None:
            if plantilla.coleccion == "catalogo_persona" and col.nombre in ("rut", "email"):
                continue                                   # se cifran más abajo
            if dest != "-" and valor is not None:
                destino[dest] = valor
            continue
        if col.ref == "departamento":
            if dest != "-" and dept is not None:
                destino[dest] = dept
            continue
        if col.ref == "periodo":
            periodo_id = _buscar(con, "SELECT id FROM catalogo_periodo WHERE departamento_id = ? AND codigo = ?", dept or 1, valor) if valor else None
            if valor and periodo_id is None:
                errores.append(error(col.nombre, f"El periodo {valor} no existe.", "Cargue primero la plantilla catalogo_periodo, o corrija el código."))
            elif dest != "-" and periodo_id is not None:
                destino[dest] = periodo_id
            continue
        if valor is None:
            continue
        if col.ref == "persona_rut":
            if cif is None:
                continue                                   # sin las claves no se puede ubicar a la persona
            pid = _buscar(con, "SELECT id FROM catalogo_persona WHERE rut_indice = ? AND eliminado_en IS NULL", cif.indice_rut(valor))
            if pid is None:
                errores.append(error(col.nombre, f"No hay una persona con RUT {valor}.", "Cargue primero la plantilla catalogo_persona, o corrija el RUT."))
            elif dest == "docente_id" and _buscar(con, "SELECT 1 FROM catalogo_docente WHERE persona_id = ?", pid) is None:
                errores.append(error(col.nombre, f"La persona {valor} no es docente.", "Cargue primero la plantilla catalogo_docente."))
            else:
                destino[dest] = pid
        elif col.ref == "asignatura":
            aid = _buscar(con, "SELECT id FROM catalogo_asignatura WHERE codigo = ? AND eliminado_en IS NULL", valor)
            if aid is None:
                errores.append(error(col.nombre, f"No existe la asignatura {valor}.", "Cargue primero la plantilla catalogo_asignatura, o corrija el código."))
            else:
                destino[dest] = aid
        elif col.ref == "paralelo_nrc":
            pid = _buscar(con, "SELECT id FROM horarios_paralelo WHERE nrc = ? AND periodo_id = ? AND eliminado_en IS NULL", valor, periodo_id)
            if pid is None:
                errores.append(error(col.nombre, f"No existe un paralelo con NRC {valor} en ese periodo.", "Cargue primero la plantilla horarios_paralelo, o corrija el NRC."))
            else:
                destino[dest] = pid
        elif col.ref == "categoria_letra":
            letra = (datos.get("letra") or "").upper()
            cid = _buscar(con, "SELECT id FROM finanzas_categoria WHERE tipo_persona = ? AND letra = ?", valor, letra)
            if cid is None:
                errores.append(error("letra", f"No existe la categoría {valor} letra «{letra}».", "Use una letra de categoría existente (A a D para profesor_hora, A a C para ayudante)."))
            else:
                destino[dest] = cid
    if cif is not None and plantilla.coleccion == "catalogo_persona":
        from ..core import pii
        if datos.get("rut"):
            destino["rut_cifrado"] = cif.cifrar(pii.normalizar_rut(datos["rut"]), pii.COL_RUT)
            destino["rut_indice"] = cif.indice_rut(datos["rut"])
        if datos.get("email"):
            destino["email_cifrado"] = cif.cifrar(datos["email"], pii.COL_EMAIL)
    return destino, errores


def validar(plantilla: Plantilla, texto: str, con: sqlite3.Connection | None = None, cif=None) -> dict:
    """Informe: {ok, encabezados, filas: [{fila, datos, destino, errores}], resumen}. Con `con` se comprueban referencias
    y duplicados contra la base; sin ella solo la forma de cada celda."""
    encabezados, filas = leer_csv(texto)
    esperados = [c.nombre for c in plantilla.columnas]
    general = []
    faltan = [c for c in esperados if c not in encabezados]
    sobran = [c for c in encabezados if c not in esperados]
    if faltan:
        general.append(error(",".join(faltan), f"Faltan columnas: {', '.join(faltan)}.", "Use la plantilla oficial sin quitar encabezados."))
    if sobran:
        general.append(error(",".join(sobran), f"Columnas desconocidas: {', '.join(sobran)}.", "Quítelas o corrija el nombre; los encabezados deben coincidir con la plantilla."))
    if not filas and not general:
        general.append(error("", "El archivo no tiene filas de datos.", "Agregue al menos una fila debajo del encabezado."))
    resultado, vistas = [], {}
    for n, fila in enumerate(filas, start=2):                 # la fila 1 es el encabezado
        errores, datos = [], {}
        if not faltan:
            for col in plantilla.columnas:
                val, err = _celda(col, fila.get(col.nombre, ""))
                datos[col.nombre] = val
                if err:
                    errores.append(err)
        destino = {}
        if con is not None and not errores:
            destino, e_ref = resolver(con, plantilla, datos, cif)
            errores += e_ref
            # la clave de una persona es su índice ciego; sin las claves esa comprobación no se puede hacer
            comprobable = cif is not None or not any(c.es_pii for c in plantilla.columnas if c.nombre in plantilla.clave)
            if not e_ref and comprobable:
                clave_db = {}
                for c in plantilla.columnas:
                    if c.nombre not in plantilla.clave or (c.destino or "") == "-":
                        continue
                    dest = "rut_indice" if plantilla.coleccion == "catalogo_persona" and c.nombre == "rut" else (
                        c.destino or REF_DESTINO.get(c.ref or "", c.nombre))
                    if dest in destino:
                        clave_db[dest] = destino[dest]
                if clave_db and con.execute(f"SELECT 1 FROM {plantilla.tabla_db} WHERE " + " AND ".join(f"{k} IS ?" for k in clave_db),
                                            list(clave_db.values())).fetchone():
                    errores.append(error(",".join(plantilla.clave), "Ya existe una fila con esa clave en la base.",
                                         "Quite la fila: la importación solo agrega, no actualiza."))
        if not errores:
            k = tuple(datos.get(c) for c in plantilla.clave)
            if k in vistas:
                errores.append(error(",".join(plantilla.clave), f"Repite la clave de la fila {vistas[k]}.", "Deje una sola fila por clave."))
            else:
                vistas[k] = n
        resultado.append({"fila": n, "datos": datos, "destino": destino, "errores": errores})
    con_error = sum(1 for f in resultado if f["errores"])
    return {"coleccion": plantilla.coleccion, "ok": not general and con_error == 0, "errores_generales": general,
            "filas": resultado, "resumen": {"filas": len(resultado), "con_errores": con_error, "validas": len(resultado) - con_error}}


def formatear(informe: dict) -> str:
    """Texto legible para la persona que carga el archivo."""
    r = informe["resumen"]
    out = [f"{informe['coleccion']}: {r['filas']} filas, {r['validas']} válidas, {r['con_errores']} con errores."]
    for e in informe["errores_generales"]:
        out.append(f"  Archivo · {e['falla']} Cómo corregirlo: {e['como_corregir']}")
    for f in informe["filas"]:
        for e in f["errores"]:
            out.append(f"  Fila {f['fila']} · {e['columna']} · {e['falla']} Cómo corregirlo: {e['como_corregir']}")
    return "\n".join(out)
