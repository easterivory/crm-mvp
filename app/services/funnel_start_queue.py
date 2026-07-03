from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from app.core.config import settings

try:
    from arq import create_pool
    from arq.connections import RedisSettings
except ImportError:  # pragma: no cover
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


async def enqueue_funnel_start(
    chat_id: UUID,
    message_id: UUID,
    *,
    fresh_lifecycle: bool,
) -> bool:
    if create_pool is None:
        return False
    redis = None
    try:
        redis = await create_pool(_redis_settings_from_url())
        await redis.enqueue_job(
            "process_funnel_start_task",
            str(chat_id),
            str(message_id),
            fresh_lifecycle,
            _job_id=f"funnel-start:{message_id}",
        )
        return True
    except Exception:
        logger.exception(
            "Could not enqueue funnel start chat_id=%s message_id=%s",
            chat_id,
            message_id,
        )
        return False
    finally:
        if redis is not None:
            await redis.close()
