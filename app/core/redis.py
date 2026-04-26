from typing import Optional

from redis.asyncio import Redis
from redis.asyncio import from_url

from app.core.config import settings

_redis_client: Optional[Redis] = None


async def get_redis() -> Redis:
    """Return the shared async Redis client, initialising on first call."""
    global _redis_client
    if _redis_client is None:
        _redis_client = from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def close_redis() -> None:
    """Close the Redis connection — called on app shutdown."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


async def ping_redis() -> bool:
    """Health check helper."""
    try:
        client = await get_redis()
        return await client.ping()
    except Exception:
        return False
