"""API base del proyecto."""
import os

import httpx
from fastapi import FastAPI

app = FastAPI(title="DISC Scheduling")


def directus_status() -> str:
    url = os.environ.get("DIRECTUS_URL", "http://directus:8055")
    try:
        response = httpx.get(f"{url}/server/health", timeout=2)
    except httpx.RequestError:
        return "down"
    return "up" if response.is_success else "down"


@app.get("/health")
def health():
    return {"status": "ok", "directus": directus_status()}
