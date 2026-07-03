from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

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


async def enqueue_facebook_capi_event(
    *,
    lead_id: UUID,
    tracking_link_id: UUID,
    event_name: str,
    custom_data: dict[str, Any] | None = None,
    event_time: int | None = None,
) -> str | None:
    if create_pool is None:
        logger.warning(
            "ARQ is not installed; Facebook CAPI event was not queued lead_id=%s",
            lead_id,
        )
        return None

    redis = None
    try:
        redis = await create_pool(_redis_settings_from_url())
        job = await redis.enqueue_job(
            "send_fb_capi_event_task",
            str(lead_id),
            str(tracking_link_id),
            event_name,
            custom_data or {},
            event_time,
            _job_id=f"facebook-capi:{lead_id}:{event_name}:{uuid4().hex}",
            _queue_name=JOBS_QUEUE_NAME,
            _defer_by=1,
        )
        return job.job_id if job is not None else None
    except Exception:
        logger.exception(
            "Could not enqueue Facebook CAPI event lead_id=%s tracking_link_id=%s event_name=%s",
            lead_id,
            tracking_link_id,
            event_name,
        )
        return None
    finally:
        if redis is not None:
            await redis.close()
