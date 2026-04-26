"""
GET /health — checks DB and Redis connectivity.
No authentication required.
"""
from fastapi import APIRouter
from sqlalchemy import text

from app.core.database import async_session_factory
from app.core.redis import ping_redis

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    # Database
    db_ok = False
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    # Redis
    redis_ok = await ping_redis()

    status = "ok" if (db_ok and redis_ok) else "degraded"

    return {
        "status": status,
        "components": {
            "api": "ok",
            "database": "ok" if db_ok else "error",
            "redis": "ok" if redis_ok else "error",
        },
    }
