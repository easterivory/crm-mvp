from __future__ import annotations

from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from arq import create_pool
from arq.connections import RedisSettings

from app.core.config import settings


def backup_redis_settings() -> Any:
    parsed = urlparse(settings.REDIS_URL)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int((parsed.path or "/0").lstrip("/") or "0"),
        password=parsed.password,
        ssl=parsed.scheme == "rediss",
    )


async def enqueue_manual_backup() -> str:
    redis = await create_pool(backup_redis_settings())
    try:
        job_id = f"manual-backup:{uuid4().hex}"
        job = await redis.enqueue_job("run_tg_backup_job", True, _job_id=job_id)
        if job is None:
            raise RuntimeError("Could not enqueue backup job")
        return job.job_id
    finally:
        await redis.close()
