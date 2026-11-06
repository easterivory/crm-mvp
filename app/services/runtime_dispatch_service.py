"""Save queue intentions in the caller's transaction; never contact Redis here."""
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
import asyncio
import logging
from uuid import UUID

from sqlalchemy import event, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telegram_delivery import RuntimeDispatch
from app.core.database import get_db_session
from app.core.delivery_attempt import delivery_attempt
from app.core.config import settings
from app.core.db_retry import retryable_database_error, failure_details

logger = logging.getLogger(__name__)


class RuntimeDispatchNeedsReview(RuntimeError):
    pass


class RuntimeDispatchAlreadyHandled(RuntimeError):
    def __init__(self, status: str):
        self.status = status
        super().__init__(status)


@asynccontextmanager
async def protect_dispatch_replay(db: AsyncSession, kind: str, message_id: UUID):
    """A partial committed/send attempt is not a retryable queue failure."""
    key = f"{kind}:{message_id}"
    # A durable execution fence survives a process kill or a failed review
    # write. Redis acknowledgement alone is never permission to replay a send.
    async with get_db_session() as claim_db:
        claimed = (await claim_db.execute(update(RuntimeDispatch).where(
            RuntimeDispatch.dedupe_key == key, RuntimeDispatch.status == "pending",
        ).values(status="running", claimed_at=datetime.now(timezone.utc)).returning(RuntimeDispatch.id, RuntimeDispatch.payload_json))).first()
        claimed_id = claimed[0] if claimed else None
        status = None if claimed_id else await claim_db.scalar(select(RuntimeDispatch.status).where(RuntimeDispatch.dedupe_key == key))
        snapshot = None
        if claimed_id:
            from app.services.runtime_review_service import runtime_snapshot
            snapshot = await runtime_snapshot(claim_db, (claimed[1] or {}).get("chat_id"))
        await claim_db.commit()
    if status == "review":
        raise RuntimeDispatchNeedsReview(key)
    if status in {"done", "running"}:
        raise RuntimeDispatchAlreadyHandled("already_processed" if status == "done" else "already_processing")
    progress = {"committed": False, "external_io_started": False}
    token = delivery_attempt.set(progress)

    def committed(session):
        if not session.in_nested_transaction():
            progress["committed"] = True

    event.listen(db.sync_session, "after_commit", committed)
    try:
        yield
    except BaseException as exc:
        if claimed_id is not None:
            no_effects = not any(progress.values())
            safe_retry = False
            try:
                async with asyncio.timeout(10):
                    await db.rollback()
                    async with get_db_session() as failure_db:
                        row = await failure_db.scalar(select(RuntimeDispatch).where(
                            RuntimeDispatch.dedupe_key == key, RuntimeDispatch.status == "running",
                        ).with_for_update())
                        if row:
                            row.failure_count += 1
                            safe_retry = no_effects and retryable_database_error(exc) and row.failure_count < max(1, settings.RUNTIME_DISPATCH_MAX_FAILURES)
                            row.status, row.claimed_at = ("pending" if safe_retry else "review"), None
                            delay = min(60, max(1, settings.RUNTIME_DISPATCH_RETRY_BASE_SECONDS) * 2 ** min(row.failure_count - 1, 6))
                            row.available_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
                            row.diagnostics_json = {**failure_details(exc, **progress), "failure_count": row.failure_count,
                                "safe_to_replay": no_effects and snapshot is not None, "snapshot": snapshot,
                                "failed_at": datetime.now(timezone.utc).isoformat(), "retry_scheduled": safe_retry}
                            row.last_error = f"{type(exc).__name__}; sqlstate={row.diagnostics_json['sqlstate']}; safe_retry={safe_retry}; failures={row.failure_count}"
                        await failure_db.commit()
                if row and not safe_retry and isinstance(exc, Exception):
                    raise RuntimeDispatchNeedsReview(key) from exc
            except RuntimeDispatchNeedsReview:
                raise
            except Exception:
                logger.exception("Could not persist uncertain runtime dispatch kind=%s message_id=%s", kind, message_id)
        raise
    finally:
        event.remove(db.sync_session, "after_commit", committed)
        delivery_attempt.reset(token)


async def save_runtime_dispatch(
    db: AsyncSession, *, key: str, kind: str, payload: dict, delay_seconds: float = 0,
) -> None:
    await db.execute(insert(RuntimeDispatch).values(
        dedupe_key=key, kind=kind, payload_json=payload,
        available_at=datetime.now(timezone.utc) + timedelta(seconds=max(delay_seconds, 0)),
    ).on_conflict_do_nothing(index_elements=[RuntimeDispatch.dedupe_key]))


async def acknowledge_runtime_dispatch(db: AsyncSession, kind: str, message_id: UUID) -> None:
    await db.execute(update(RuntimeDispatch).where(
        RuntimeDispatch.dedupe_key == f"{kind}:{message_id}",
        RuntimeDispatch.status.in_(["pending", "running"]),
    ).values(status="done", claimed_at=None, completed_at=datetime.now(timezone.utc), last_error=None))


async def defer_runtime_dispatch(db: AsyncSession, kind: str, message_id: UUID, delay_seconds: int) -> None:
    await db.execute(update(RuntimeDispatch).where(
        RuntimeDispatch.dedupe_key == f"{kind}:{message_id}", RuntimeDispatch.status.in_(["pending", "running"]),
    ).values(status="pending", claimed_at=None, available_at=datetime.now(timezone.utc) + timedelta(seconds=max(delay_seconds, 1)),
             last_error="waiting_runtime"))
