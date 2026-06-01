"""Production worker for broadcast recipient delivery."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db_session
from app.models.broadcast import Broadcast, BroadcastRecipient
from app.repositories.broadcast_repository import BroadcastRepository
from app.services.broadcast_service import BroadcastService

try:
    from arq import create_pool
    from arq.connections import RedisSettings
except ImportError:  # pragma: no cover - production installs arq from requirements.txt
    create_pool = None
    RedisSettings = None

logger = logging.getLogger(__name__)

ACTIVE_STATUS = "processing"
STOP_STATUSES = {"paused", "cancelled"}
FINAL_STATUS = "completed"
TELEGRAM_RATE_LIMIT_PER_SECOND = 30
MAX_MICRO_BATCH_SIZE = 10


@dataclass(slots=True)
class BroadcastRunResult:
    broadcast_id: UUID
    status: str
    sent: int = 0
    failed: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "broadcast_id": str(self.broadcast_id),
            "status": self.status,
            "sent": self.sent,
            "failed": self.failed,
        }


class BroadcastDeliveryWorker:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = BroadcastRepository(db)
        self.service = BroadcastService(db)

    async def process_due_broadcasts(self, limit: int = 20) -> int:
        broadcasts = await self.repo.list_due_broadcasts(limit=limit)
        processed = 0
        for broadcast in broadcasts:
            result = await self.process_broadcast(
                broadcast_id=broadcast.id,
                project_id=broadcast.project_id,
            )
            processed += result.sent + result.failed
        return processed

    async def process_broadcast(
        self,
        *,
        broadcast_id: UUID,
        project_id: UUID | None = None,
    ) -> BroadcastRunResult:
        broadcast = await self._load_broadcast(broadcast_id, project_id)
        if broadcast is None:
            return BroadcastRunResult(broadcast_id=broadcast_id, status="not_found")

        project_id = broadcast.project_id
        if broadcast.status == "scheduled":
            broadcast = await self.repo.update_in_project(
                broadcast.id,
                project_id,
                status=ACTIVE_STATUS,
                started_at=datetime.now(timezone.utc),
            )
            await self.db.commit()
            if broadcast is None:
                return BroadcastRunResult(broadcast_id=broadcast_id, status="not_found")

        if broadcast.status != ACTIVE_STATUS:
            await self.repo.sync_progress_counts(broadcast.id, project_id)
            await self.db.commit()
            return BroadcastRunResult(broadcast_id=broadcast.id, status=broadcast.status)

        sent = 0
        failed = 0
        micro_batch_size = max(
            1,
            min(settings.BROADCAST_BATCH_SIZE, MAX_MICRO_BATCH_SIZE),
        )

        while True:
            fresh = await self._active_or_stopped(broadcast.id, project_id)
            if fresh is None:
                return BroadcastRunResult(
                    broadcast_id=broadcast.id,
                    status="not_found",
                    sent=sent,
                    failed=failed,
                )
            if fresh.status != ACTIVE_STATUS:
                return BroadcastRunResult(
                    broadcast_id=broadcast.id,
                    status=fresh.status,
                    sent=sent,
                    failed=failed,
                )

            recipients = await self.repo.list_pending_recipients(
                broadcast.id,
                limit=micro_batch_size,
                max_attempts=settings.BROADCAST_MAX_ATTEMPTS,
            )
            if not recipients:
                await self._complete_broadcast(fresh)
                return BroadcastRunResult(
                    broadcast_id=broadcast.id,
                    status=FINAL_STATUS,
                    sent=sent,
                    failed=failed,
                )

            batch_started_at = time.monotonic()
            estimated_requests = 0
            for recipient in recipients:
                fresh = await self._active_or_stopped(broadcast.id, project_id)
                if fresh is None:
                    return BroadcastRunResult(
                        broadcast_id=broadcast.id,
                        status="not_found",
                        sent=sent,
                        failed=failed,
                    )
                if fresh.status != ACTIVE_STATUS:
                    return BroadcastRunResult(
                        broadcast_id=broadcast.id,
                        status=fresh.status,
                        sent=sent,
                        failed=failed,
                    )

                estimated_requests += self._estimated_request_count(fresh)
                delivered = await self._deliver_recipient(fresh, recipient)
                if delivered:
                    sent += 1
                else:
                    failed += 1

            await self._respect_telegram_rate_limit(batch_started_at, estimated_requests)

    async def _load_broadcast(
        self,
        broadcast_id: UUID,
        project_id: UUID | None,
    ) -> Broadcast | None:
        if project_id is not None:
            return await self.repo.get_in_project(broadcast_id, project_id)
        return await self.repo.get_by_id(broadcast_id)

    async def _active_or_stopped(
        self,
        broadcast_id: UUID,
        project_id: UUID,
    ) -> Broadcast | None:
        fresh = await self.repo.get_in_project(broadcast_id, project_id)
        if fresh is None:
            return None
        if fresh.status in STOP_STATUSES:
            await self.repo.sync_progress_counts(fresh.id, fresh.project_id)
            await self.db.commit()
            logger.info(
                "Broadcast delivery stopped broadcast_id=%s status=%s sent_count=%s failed_count=%s",
                fresh.id,
                fresh.status,
                fresh.sent_count,
                fresh.failed_count,
            )
            return fresh
        if (
            fresh.status == ACTIVE_STATUS
            and fresh.stop_on_reply
            and fresh.started_at is not None
            and await self.repo.has_client_reply_after(fresh.id, fresh.started_at)
        ):
            updated = await self.repo.update_in_project(
                fresh.id,
                fresh.project_id,
                status="paused",
            )
            fresh = await self.repo.sync_progress_counts(fresh.id, fresh.project_id) or updated or fresh
            await self.db.commit()
            logger.info(
                "Broadcast delivery paused after client reply broadcast_id=%s sent_count=%s failed_count=%s",
                fresh.id,
                fresh.sent_count,
                fresh.failed_count,
            )
        return fresh

    async def _deliver_recipient(
        self,
        broadcast: Broadcast,
        recipient: BroadcastRecipient,
    ) -> bool:
        recipient_id = recipient.id
        try:
            context = await self.repo.get_recipient_context(recipient)
            if context is None:
                raise RuntimeError("Chat not found")
            chat, lead = context
            await self.service._send_to_recipient(broadcast, recipient.chat_id, chat, lead)
            await self.repo.mark_recipient_sent(recipient_id)
            await self.repo.increment_progress_counts(
                broadcast.id,
                broadcast.project_id,
                sent_delta=1,
            )
            await self.db.commit()
            logger.info(
                "Broadcast recipient delivered broadcast_id=%s recipient_id=%s chat_id=%s",
                broadcast.id,
                recipient_id,
                recipient.chat_id,
            )
            return True
        except Exception as exc:
            await self.db.rollback()
            error = self._error_message(exc)
            await self.repo.mark_recipient_failed(recipient_id, error)
            await self.repo.increment_progress_counts(
                broadcast.id,
                broadcast.project_id,
                failed_delta=1,
            )
            await self.db.commit()
            logger.warning(
                "Broadcast recipient failed broadcast_id=%s recipient_id=%s error=%s",
                broadcast.id,
                recipient_id,
                error,
            )
            return False

    async def _complete_broadcast(self, broadcast: Broadcast) -> None:
        counts = await self.repo.status_counts(broadcast.id)
        await self.repo.update_in_project(
            broadcast.id,
            broadcast.project_id,
            status=FINAL_STATUS,
            sent_count=counts.get("sent", 0),
            failed_count=counts.get("failed", 0),
            sent_at=datetime.now(timezone.utc),
        )
        await self.db.commit()
        logger.info(
            "Broadcast delivery completed broadcast_id=%s sent=%s failed=%s skipped=%s",
            broadcast.id,
            counts.get("sent", 0),
            counts.get("failed", 0),
            counts.get("skipped", 0),
        )

    @staticmethod
    def _estimated_request_count(broadcast: Broadcast) -> int:
        return max(1, len(BroadcastService._content_messages(broadcast.content_json or {})))

    @staticmethod
    async def _respect_telegram_rate_limit(
        batch_started_at: float,
        estimated_requests: int,
    ) -> None:
        if estimated_requests <= 0:
            return
        minimum_duration = estimated_requests / TELEGRAM_RATE_LIMIT_PER_SECOND
        elapsed = time.monotonic() - batch_started_at
        if elapsed < minimum_duration:
            await asyncio.sleep(minimum_duration - elapsed)

    @staticmethod
    def _error_message(exc: Exception) -> str:
        if isinstance(exc, HTTPException):
            return str(exc.detail)
        message = str(exc)
        return message if message else exc.__class__.__name__


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


async def enqueue_broadcast_job(broadcast_id: UUID, project_id: UUID) -> str | None:
    if create_pool is None:
        logger.warning(
            "ARQ is not installed; polling broadcast worker will pick up broadcast_id=%s",
            broadcast_id,
        )
        return None

    redis = await create_pool(_redis_settings_from_url())
    try:
        job = await redis.enqueue_job(
            "process_broadcast",
            str(broadcast_id),
            str(project_id),
            _job_id=f"broadcast:{broadcast_id}",
        )
        return job.job_id if job is not None else None
    finally:
        await redis.close()


async def run_once() -> int:
    async with get_db_session() as db:
        return await BroadcastDeliveryWorker(db).process_due_broadcasts()


async def run_loop(interval_seconds: float = 1.0) -> None:
    logger.info("Starting broadcast worker")
    while True:
        try:
            processed = await run_once()
            if processed:
                logger.info("Processed broadcast recipients count=%s", processed)
        except Exception:
            logger.exception("Broadcast worker loop failed")
        await asyncio.sleep(interval_seconds)


async def process_broadcast(
    ctx: dict,
    broadcast_id: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Compatibility entrypoint for ARQ-style callers."""
    try:
        parsed_broadcast_id = UUID(str(broadcast_id))
        parsed_project_id = UUID(str(project_id)) if project_id else None
    except (TypeError, ValueError) as exc:
        return {"status": "failed", "error": str(exc)}

    async with get_db_session() as db:
        result = await BroadcastDeliveryWorker(db).process_broadcast(
            broadcast_id=parsed_broadcast_id,
            project_id=parsed_project_id,
        )
        return result.as_dict()


async def process_due_broadcasts(ctx: dict) -> dict[str, Any]:
    """Compatibility entrypoint for ARQ-style callers."""
    async with get_db_session() as db:
        processed = await BroadcastDeliveryWorker(db).process_due_broadcasts()
        return {"status": "completed", "processed": processed}


class WorkerSettings:
    """ARQ compatibility settings."""
    functions = [process_broadcast, process_due_broadcasts]
    redis_settings = None
