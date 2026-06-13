from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

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


async def enqueue_lead_sheets_export(lead_id: UUID, project_id: UUID) -> str | None:
    if create_pool is None:
        logger.warning(
            "ARQ is not installed; Google Sheets export was not queued lead_id=%s",
            lead_id,
        )
        return None

    redis = None
    try:
        redis = await create_pool(_redis_settings_from_url())
        job = await redis.enqueue_job(
            "export_lead_to_sheets_task",
            str(lead_id),
            str(project_id),
            _job_id=f"google-sheets-export:{lead_id}:{uuid4().hex}",
            _defer_by=1,
        )
        return job.job_id if job is not None else None
    except Exception:
        logger.exception(
            "Could not enqueue Google Sheets export lead_id=%s project_id=%s",
            lead_id,
            project_id,
        )
        return None
    finally:
        if redis is not None:
            await redis.close()
