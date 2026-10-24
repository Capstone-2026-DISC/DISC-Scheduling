"""Caché pequeña con vencimiento, segura entre hilos. Evita repetir en cada petición las consultas que casi no cambian
(quién es el dueño de un token, qué permisos tiene un rol)."""

import threading
import time


class Cache:
    def __init__(self, ttl_s: float):
        self.ttl, self._d, self._lock = ttl_s, {}, threading.Lock()

    def obtener(self, clave):
        with self._lock:
            hit = self._d.get(clave)
            if hit and hit[0] > time.monotonic():
                return hit[1]
            self._d.pop(clave, None)
        return None

    def poner(self, clave, valor):
        with self._lock:
            if len(self._d) > 5000:
                self._d.clear()
            self._d[clave] = (time.monotonic() + self.ttl, valor)
        return valor

    def olvidar(self, clave):
        with self._lock:
            self._d.pop(clave, None)

    def vaciar(self):
        with self._lock:
            self._d.clear()
