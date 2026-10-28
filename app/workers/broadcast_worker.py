"""Production worker for broadcast recipient delivery."""
from __future__ import annotations

import asyncio
import logging
import time
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select, update

from app.core.arq_queues import JOBS_QUEUE_NAME
from app.core.config import settings
from app.core.database import get_db_session, engine
from app.models.bot import Bot
from app.services.broadcast_transport import BroadcastHTTPClient
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
        bot_id = broadcast.bot_id
        project_id = broadcast.project_id
        await self.db.commit()
        # One owner per bot across polling and ARQ, including different campaigns.
        key = int.from_bytes(hashlib.blake2b(f"broadcast:{bot_id or broadcast_id}".encode(), digest_size=8).digest(), "big", signed=True)
        async with engine.connect() as lock_conn:
            acquired = await lock_conn.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
            await lock_conn.commit()
            if not acquired:
                return BroadcastRunResult(broadcast_id=broadcast_id, status="busy")
            try:
                async with BroadcastHTTPClient(rate=settings.BROADCAST_MESSAGES_PER_SECOND) as client:
                    self.http_client = client
                    self.media_cache = {}
                    return await self._process_owned(broadcast_id=broadcast_id, project_id=project_id)
            finally:
                try:
                    await lock_conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                    await lock_conn.commit()
                except BaseException:
                    await lock_conn.invalidate()
                    raise

    async def _process_owned(
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

        # A terminated process may have sent to Telegram before recording success.
        # Do not automatically replay these ambiguous deliveries.
        await self.db.execute(update(BroadcastRecipient).where(
            BroadcastRecipient.broadcast_id == broadcast.id,
            BroadcastRecipient.status == "sending",
        ).values(status="failed", last_error="Delivery interrupted; Telegram outcome unknown. Not retried."))
        transport = await self.db.scalar(select(Bot.transport_type).where(Bot.id == broadcast.bot_id))
        if transport != "bot_api":
            self.media_cache = None
        await self.db.commit()

        sent = 0
        failed = 0
        concurrency = max(1, min(settings.BROADCAST_CONCURRENCY, 16)) if transport == "bot_api" else 1
        micro_batch_size = max(1, min(settings.BROADCAST_BATCH_SIZE, 100))

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
                fresh = await self.repo.get_in_project(broadcast.id, project_id)
                return BroadcastRunResult(
                    broadcast_id=broadcast.id,
                    status=fresh.status if fresh else "not_found",
                    sent=sent,
                    failed=failed,
                )

            recipient_ids = [recipient.id for recipient in recipients]
            await self.db.commit()
            gate = asyncio.Semaphore(concurrency)
            async def deliver(recipient_id):
                async with gate:
                    async with get_db_session() as db:
                        worker = BroadcastDeliveryWorker(db)
                        worker.service.telegram_sender.http_client = self.http_client
                        worker.service.media_cache = self.media_cache
                        current = await worker._active_or_stopped(broadcast_id, project_id)
                        if current is None or current.status != ACTIVE_STATUS:
                            return None
                        claimed = await db.scalar(update(BroadcastRecipient).where(
                            BroadcastRecipient.id == recipient_id,
                            BroadcastRecipient.status == "pending",
                        ).values(status="sending").returning(BroadcastRecipient.id))
                        await db.commit()
                        if claimed is None:
                            return None
                        recipient = await db.get(BroadcastRecipient, recipient_id)
                        return await worker._deliver_recipient(current, recipient)
            batch_start = time.monotonic()
            results = await asyncio.gather(*(deliver(rid) for rid in recipient_ids), return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException):
                    raise result
                sent += result is True
                failed += result is False
            await self.repo.sync_progress_counts(broadcast_id, project_id)
            await self.db.commit()
            logger.info("Broadcast batch broadcast_id=%s recipients=%s sent=%s failed=%s elapsed_seconds=%.3f concurrency=%s",
                        broadcast_id, len(results), sum(r is True for r in results), sum(r is False for r in results), time.monotonic() - batch_start, concurrency)

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
        broadcast_id = broadcast.id
        project_id = broadcast.project_id
        recipient_id = recipient.id
        recipient_chat_id = recipient.chat_id
        try:
            context = await self.repo.get_recipient_context(recipient)
            if context is None:
                raise RuntimeError("Chat not found")
            chat, lead = context
            await self.service._send_to_recipient(broadcast, recipient_chat_id, chat, lead)
            await self.repo.mark_recipient_sent(recipient_id)
            await self.db.commit()
            logger.info(
                "Broadcast recipient delivered broadcast_id=%s recipient_id=%s chat_id=%s",
                broadcast_id,
                recipient_id,
                recipient_chat_id,
            )
            return True
        except Exception as exc:
            await self.db.rollback()
            error = self._error_message(exc)
            await self.repo.mark_recipient_failed(recipient_id, error)
            await self.db.commit()
            logger.warning(
                "Broadcast recipient failed broadcast_id=%s recipient_id=%s error=%s",
                broadcast_id,
                recipient_id,
                error,
            )
            return False

    async def _complete_broadcast(self, broadcast: Broadcast) -> None:
        counts = await self.repo.status_counts(broadcast.id)
        await self.db.execute(update(Broadcast).where(
            Broadcast.id == broadcast.id,
            Broadcast.status == ACTIVE_STATUS,
            Broadcast.is_deleted.is_(False),
        ).values(
            status=FINAL_STATUS,
            sent_count=counts.get("sent", 0),
            failed_count=counts.get("failed", 0),
            sent_at=datetime.now(timezone.utc),
        ))
        await self.db.commit()
        logger.info(
            "Broadcast delivery completed broadcast_id=%s sent=%s failed=%s skipped=%s",
            broadcast.id,
            counts.get("sent", 0),
            counts.get("failed", 0),
            counts.get("skipped", 0),
        )

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
            _queue_name=JOBS_QUEUE_NAME,
        )
        if job is None:
            fallback_job_id = f"broadcast:{broadcast_id}:{uuid4().hex}"
            logger.warning(
                "Broadcast ARQ job id already exists; enqueueing fallback job_id=%s broadcast_id=%s",
                fallback_job_id,
                broadcast_id,
            )
            job = await redis.enqueue_job(
                "process_broadcast",
                str(broadcast_id),
                str(project_id),
                _job_id=fallback_job_id,
                _queue_name=JOBS_QUEUE_NAME,
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
    redis_settings = _redis_settings_from_url()
