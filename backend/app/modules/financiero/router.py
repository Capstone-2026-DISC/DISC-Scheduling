from fastapi import APIRouter

from .service import routers

router = APIRouter()
for _r in routers():
    router.include_router(_r)
