"""Cifrado de datos personales (RUT y correo) a nivel de columna.

Por qué aquí y no en el motor: Directus trae un SQLite sin SQLCipher (sqlite3 5.1.7 sobre SQLite 3.44.2, sin códec),
así que no puede abrir una base cifrada entera. Se cifra solo lo que identifica a una persona y el resto de la base
queda legible para Directus.

* AES-256-GCM con nonce aleatorio por valor. El formato guardado es  v1:<id de clave>:<base64url(nonce + cifrado)>.
* La columna va como dato autenticado adicional: un texto cifrado copiado de una columna a otra no se descifra.
* El RUT se busca y se exige único con un índice ciego: HMAC-SHA256 del RUT normalizado con una clave distinta de la
  de cifrado. Sin esa clave no se puede recalcular el índice ni probar RUT al azar contra la base.
* Varias claves de cifrado conviven (DATA_KEYS) para rotar: se cifra con DATA_KEY_ID y se descifra con cualquiera.
"""

import base64
import hashlib
import hmac
import os
import re
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PREFIJO = "v1"
RUT_RE = re.compile(r"^\d{7,8}-[\dK]$")


class ClaveFaltante(RuntimeError):
    pass


class DatoAlterado(ValueError):
    """El texto cifrado no se pudo autenticar: clave equivocada, columna distinta o dato manipulado."""


def normalizar_rut(valor: str) -> str:
    """12.345.678-5, 12345678-5 y 123456785 dan 12345678-5. Devuelve el texto tal cual si no tiene forma de RUT."""
    v = re.sub(r"[.\s]", "", valor).upper()
    if "-" not in v and re.fullmatch(r"\d{7,8}[\dK]", v):
        v = v[:-1] + "-" + v[-1]
    return v


def digito_verificador(cuerpo: str) -> str:
    suma, mult = 0, 2
    for d in reversed(cuerpo):
        suma += int(d) * mult
        mult = 2 if mult == 7 else mult + 1
    resto = 11 - suma % 11
    return "0" if resto == 11 else "K" if resto == 10 else str(resto)


def rut_valido(valor: str) -> bool:
    v = normalizar_rut(valor)
    return bool(RUT_RE.match(v)) and digito_verificador(v.split("-")[0]) == v[-1]


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).decode().rstrip("=")


def _desde_b64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def _clave(valor: str, nombre: str) -> bytes:
    try:
        clave = _desde_b64(valor.strip())
    except Exception as exc:  # noqa: BLE001
        raise ClaveFaltante(f"{nombre} no es base64 válido") from exc
    if len(clave) != 32:
        raise ClaveFaltante(f"{nombre} debe ser de 32 bytes en base64 (genere una con scripts/configure.py)")
    return clave


@dataclass
class Cifrador:
    claves: dict[str, bytes]
    clave_actual: str
    clave_indice: bytes

    @classmethod
    def desde_entorno(cls, data_keys: str, data_key_id: str, index_key: str) -> "Cifrador":
        """data_keys = 'k1=<base64>,k2=<base64>'; data_key_id = la que cifra de ahora en adelante."""
        claves = {}
        for par in filter(None, (p.strip() for p in data_keys.split(","))):
            kid, _, valor = par.partition("=")
            if not re.fullmatch(r"[A-Za-z0-9]{1,12}", kid):
                raise ClaveFaltante("DATA_KEYS: el id de clave son letras y números (por ejemplo k1)")
            claves[kid] = _clave(valor, f"DATA_KEYS[{kid}]")
        if data_key_id not in claves:
            raise ClaveFaltante("DATA_KEY_ID no está entre las claves de DATA_KEYS")
        indice = _clave(index_key, "INDEX_KEY")
        if indice in claves.values():
            raise ClaveFaltante("INDEX_KEY debe ser distinta de las claves de cifrado")
        return cls(claves, data_key_id, indice)

    def cifrar(self, texto: str, columna: str, nonce: bytes | None = None) -> str:
        """`nonce` solo se pasa en datos de prueba que deben salir idénticos en cada ejecución."""
        nonce = nonce or os.urandom(12)
        cifrado = AESGCM(self.claves[self.clave_actual]).encrypt(nonce, texto.encode(), columna.encode())
        return f"{PREFIJO}:{self.clave_actual}:{_b64(nonce + cifrado)}"

    def descifrar(self, guardado: str, columna: str) -> str:
        try:
            prefijo, kid, cuerpo = guardado.split(":", 2)
            if prefijo != PREFIJO or kid not in self.claves:
                raise DatoAlterado("formato o clave desconocidos")
            crudo = _desde_b64(cuerpo)
            return AESGCM(self.claves[kid]).decrypt(crudo[:12], crudo[12:], columna.encode()).decode()
        except (InvalidTag, ValueError) as exc:
            raise DatoAlterado(f"no se pudo descifrar {columna}") from exc

    def indice_rut(self, rut: str) -> str:
        return hmac.new(self.clave_indice, b"rut:" + normalizar_rut(rut).encode(), hashlib.sha256).hexdigest()

    def recifrar(self, guardado: str, columna: str) -> str:
        """Pasa un valor a la clave actual (rotación)."""
        return self.cifrar(self.descifrar(guardado, columna), columna)

    def enmascarar_rut(self, rut: str) -> str:
        v = normalizar_rut(rut)
        return "*" * max(0, len(v) - 5) + v[-5:]


# columnas que se cifran; la clave es el nombre de la columna cifrada (también sirve como dato autenticado)
COL_RUT, COL_EMAIL, COL_EMAIL_ENVIO = (
    "catalogo_persona.rut",
    "catalogo_persona.email",
    "horarios_envio_horario.email_destino",
)
