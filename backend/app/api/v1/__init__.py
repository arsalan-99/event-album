from fastapi import APIRouter
from app.api.v1.health import router as health_router
from app.api.v1.events import router as events_router
from app.api.v1.photos import router as photos_router
from app.api.v1.guests import router as guests_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router)
api_v1_router.include_router(events_router)
api_v1_router.include_router(photos_router)
api_v1_router.include_router(guests_router)

__all__ = ["api_v1_router"]
