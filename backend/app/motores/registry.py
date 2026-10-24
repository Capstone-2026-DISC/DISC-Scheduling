"""Registry and factory of engines: the rest of the code asks for an engine by name and never imports an adapter."""

from .cpsat import CpSatEngine
from .fet import FetEngine
from .model import Availability
from .port import TimetableEngine

_ENGINES: dict[str, type[TimetableEngine]] = {}


def register(engine: type[TimetableEngine]) -> type[TimetableEngine]:
    """Add an adapter. Usable as a decorator, so a new engine is one class and one line."""
    _ENGINES[engine.name] = engine
    return engine


def names() -> list[str]:
    return sorted(_ENGINES)


def create(name: str, **options) -> TimetableEngine:
    if name not in _ENGINES:
        raise KeyError(f"Motor desconocido: {name}. Disponibles: {', '.join(names())}")
    return _ENGINES[name](**options)


def availability() -> dict[str, Availability]:
    return {name: create(name).availability() for name in names()}


register(CpSatEngine)
register(FetEngine)
