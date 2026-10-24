"""Política de claves. Las claves las guarda Directus (argon2); la API solo comprueba que una clave nueva sea razonable
antes de enviársela."""


def clave_valida(clave: str, email: str, minimo: int) -> str | None:
    """Devuelve el motivo si la clave no cumple la política, o None si es aceptable."""
    if len(clave) < minimo:
        return f"La clave debe tener al menos {minimo} caracteres."
    if clave.lower() == email.lower() or email.split("@")[0].lower() in clave.lower():
        return "La clave no puede contener el correo."
    if clave.isdigit() or clave.isalpha():
        return "La clave debe mezclar letras con números o símbolos."
    return None
