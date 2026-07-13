from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Sequence
from urllib.parse import urlparse
from uuid import UUID

from app.core.arq_queues import JOBS_QUEUE_NAME
from app.core.config import settings

try:
    from arq import create_pool
    from arq.connections import RedisSettings
except ImportError:  # pragma: no cover
    create_pool = None
    RedisSettings = None

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FunnelStartRequest:
    chat_id: UUID
    message_id: UUID
    fresh_lifecycle: bool = False


@dataclass(frozen=True)
class FunnelStartEnqueueResult:
    requested: int
    enqueued: int
    already_enqueued: int
    failed: int

    @property
    def scheduled(self) -> int:
        return self.enqueued + self.already_enqueued


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
    result = await enqueue_funnel_starts(
        [
            FunnelStartRequest(
                chat_id=chat_id,
                message_id=message_id,
                fresh_lifecycle=fresh_lifecycle,
            )
        ]
    )
    return result.failed == 0 and result.scheduled == 1


async def enqueue_funnel_starts(
    requests: Sequence[FunnelStartRequest],
    *,
    job_scope: str | None = None,
) -> FunnelStartEnqueueResult:
    requested = len(requests)
    if requested == 0:
        return FunnelStartEnqueueResult(0, 0, 0, 0)
    if create_pool is None:
        return FunnelStartEnqueueResult(requested, 0, 0, requested)

    safe_scope = (
        re.sub(r"[^a-zA-Z0-9_-]+", "-", job_scope).strip("-")[:80]
        if job_scope
        else None
    )
    redis = None
    enqueued = 0
    already_enqueued = 0
    failed = 0
    try:
        redis = await create_pool(_redis_settings_from_url())
        for request in requests:
            job_id = (
                f"funnel-recovery:{safe_scope}:{request.message_id}"
                if safe_scope
                else f"funnel-start:{request.message_id}"
            )
            try:
                job = await redis.enqueue_job(
                    "process_funnel_start_task",
                    str(request.chat_id),
                    str(request.message_id),
                    request.fresh_lifecycle,
                    _job_id=job_id,
                    _queue_name=JOBS_QUEUE_NAME,
                )
                if job is None:
                    already_enqueued += 1
                else:
                    enqueued += 1
            except Exception:
                failed += 1
                logger.exception(
                    "Could not enqueue funnel start chat_id=%s message_id=%s",
                    request.chat_id,
                    request.message_id,
                )
    except Exception:
        logger.exception(
            "Could not connect to funnel start queue requests=%s",
            requested,
        )
        failed = requested
    finally:
        if redis is not None:
            await redis.close()
    return FunnelStartEnqueueResult(
        requested=requested,
        enqueued=enqueued,
        already_enqueued=already_enqueued,
        failed=failed,
    )
