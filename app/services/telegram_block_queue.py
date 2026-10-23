"""Durably defer a block observation while its sending transaction owns the chat."""
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from arq import create_pool

from app.core.arq_queues import JOBS_QUEUE_NAME
from app.services.funnel_job_queue import _redis_settings_from_url


async def enqueue_telegram_block_update(project_id: UUID, bot_id: UUID | None, external_chat_id: str, observed_at: datetime) -> None:
    identity = f"{project_id}:{bot_id}:{external_chat_id}:{observed_at.isoformat()}"
    redis = await create_pool(_redis_settings_from_url())
    try:
        await redis.enqueue_job(
            "persist_telegram_block_task", str(project_id), str(bot_id) if bot_id else None,
            str(external_chat_id), observed_at.isoformat(),
            _job_id="telegram-block:" + sha256(identity.encode()).hexdigest(),
            _queue_name=JOBS_QUEUE_NAME,
        )
    finally:
        await redis.aclose()
