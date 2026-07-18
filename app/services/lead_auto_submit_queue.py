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


async def enqueue_lead_auto_submit(
    lead_id: UUID,
    partner_integration_id: UUID,
    *,
    forced_manual: bool = False,
) -> str | None:
    if create_pool is None:
        logger.warning(
            "ARQ is not installed; automatic partner submission was not queued "
            "lead_id=%s partner_integration_id=%s",
            lead_id,
            partner_integration_id,
        )
        return None

    redis = None
    try:
        redis = await create_pool(_redis_settings_from_url())
        job = await redis.enqueue_job(
            "auto_submit_lead_task",
            str(lead_id),
            str(partner_integration_id),
            forced_manual,
            _job_id=(
                f"lead-auto-submit:{lead_id}:{partner_integration_id}:"
                f"{'vip' if forced_manual else 'auto'}:{uuid4().hex}"
            ),
            _queue_name=JOBS_QUEUE_NAME,
        )
        return job.job_id if job is not None else None
    except Exception:
        logger.exception(
            "Could not enqueue automatic partner submission lead_id=%s "
            "partner_integration_id=%s",
            lead_id,
            partner_integration_id,
        )
        return None
    finally:
        if redis is not None:
            await redis.close()
