"""
GET /health — checks DB and Redis connectivity.
No authentication required.
"""
from fastapi import APIRouter

from app.services.health_service import HealthService

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    return await HealthService().get_health()
