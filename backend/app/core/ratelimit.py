"""Límite de peticiones por clave en memoria (ventana deslizante). Vale por proceso: con varios
procesos hay que moverlo a un almacén compartido; el bloqueo por usuario sí vive en la base."""
import threading
import time
from collections import defaultdict, deque


class LimiteTasa:
    def __init__(self, maximo: int, ventana_s: int = 60):
        self.maximo, self.ventana = maximo, ventana_s
        self._eventos: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def permitir(self, clave: str) -> bool:
        ahora = time.monotonic()
        with self._lock:
            cola = self._eventos[clave]
            while cola and ahora - cola[0] > self.ventana:
                cola.popleft()
            if len(cola) >= self.maximo:
                return False
            cola.append(ahora)
            return True
