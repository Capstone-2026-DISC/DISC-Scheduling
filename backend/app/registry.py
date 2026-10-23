"""Registro de módulos por configuración: MODULES=base,financiero,predictivo.
Cada módulo es un paquete que expone `router` y `NOMBRE`; el núcleo compartido (auth, contexto de usuario en la
conexión y auditoría) vive en app.core y lo usan todos."""
from importlib import import_module

DISPONIBLES = {
    "base": "app.modules.base",
    "financiero": "app.modules.financiero",
    "predictivo": "app.modules.predictivo",
}


def cargar(nombres: tuple[str, ...]):
    desconocidos = [n for n in nombres if n not in DISPONIBLES]
    if desconocidos:
        raise RuntimeError(f"Módulos desconocidos en MODULES: {', '.join(desconocidos)}")
    if "base" not in nombres:
        raise RuntimeError("El módulo base es obligatorio (identidad y autenticación)")
    return [import_module(DISPONIBLES[n]) for n in nombres]
