from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from app.core.arq_queues import JOBS_QUEUE_NAME
from app.core.config import settings

try:
    from arq import create_pool
    from arq.connections import RedisSettings
except ImportError:  # pragma: no cover - production installs arq from requirements.txt
    create_pool = None
    RedisSettings = None

logger = logging.getLogger(__name__)


def _redis_settings_from_url() -> Any:
    if RedisSettings is None:
        return None
    parsed = urlparse(settings.REDIS_URL)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int((parsed.path or "/0").lstrip("/") or "0"),
        password=parsed.password,
        ssl=parsed.scheme == "rediss",
    )


async def enqueue_funnel_scheduled_job(job_id: UUID, delay_seconds: int) -> str | None:
    if create_pool is None:
        logger.warning(
            "ARQ is not installed; DB scheduled worker will pick up funnel job_id=%s",
            job_id,
        )
        return None

    redis = None
    try:
        redis = await create_pool(_redis_settings_from_url())
        job = await redis.enqueue_job(
            "process_funnel_scheduled_job_task",
            str(job_id),
            _job_id=f"funnel-scheduled:{job_id}",
            _queue_name=JOBS_QUEUE_NAME,
            _defer_by=max(delay_seconds, 0),
        )
        return job.job_id if job is not None else None
    except Exception:
        logger.exception("Could not enqueue funnel scheduled job_id=%s", job_id)
        return None
    finally:
        if redis is not None:
            await redis.close()
