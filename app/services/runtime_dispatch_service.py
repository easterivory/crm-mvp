"""Save queue intentions in the caller's transaction; never contact Redis here."""
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
import asyncio
import logging
from uuid import UUID

from sqlalchemy import event, select, update, text
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


class RuntimeDispatchDeliveryHandled(RuntimeError):
    def __init__(self, outcome: str, job_id: UUID | None = None):
        self.outcome, self.job_id = outcome, job_id
        super().__init__(outcome)


async def _delivery_continuation(db, exc, chat_id):
    from app.models import Bot, Chat, Project
    from app.models.funnel import FunnelScheduledJob
    from app.repositories.funnel_repository import FunnelRepository
    from app.services.ai_delivery_state_service import AIDeliveryStateService
    from app.services.funnel_runtime_service import FunnelRuntimeDeliveryError
    from app.services.telegram_sender import TelegramDeliveryError
    error = exc.telegram_error if isinstance(exc, FunnelRuntimeDeliveryError) else exc
    if not isinstance(error, TelegramDeliveryError): return None
    chat = await db.get(Chat, chat_id)
    if chat is None: return None
    if error.blocked or error.recipient_unavailable:
        # This is a terminal delivery outcome, not an uncertain send. Keep the
        # conversation/history, pause its automation, never replay the input.
        from app.services.funnel_runtime_service import FunnelRuntimeService
        if error.blocked:
            if not chat.is_blocked_by_user:
                from app.services.chat_user_block_service import ChatUserBlockService
                updated = await ChatUserBlockService(db).set_blocked_by_user(project_id=chat.project_id,
                    bot_id=chat.bot_id, external_chat_id=chat.external_chat_id, is_blocked_by_user=True,
                    observed_at=error.observed_at)
                if updated is None: return RuntimeDispatchDeliveryHandled("delivery_blocked_superseded")
        elif chat.last_user_message_at and chat.last_user_message_at > error.observed_at:
            return RuntimeDispatchDeliveryHandled("delivery_unavailable_superseded")
        await FunnelRuntimeService(db).pause_for_user_block(chat_id)
        return RuntimeDispatchDeliveryHandled("delivery_blocked" if error.blocked else "delivery_recipient_unavailable")
    safe = error.definitely_not_sent or error.error_code == 429 or error.status_code == 429
    if not safe or not isinstance(exc, FunnelRuntimeDeliveryError) or not exc.retry_state_id or not exc.retry_visit:
        return None
    if exc.retry_job_type not in {"message_sequence", "input_prompt"}: return None
    bot = await db.get(Bot, chat.bot_id) if chat.bot_id else None
    project = await db.get(Project, chat.project_id)
    if (not bot or bot.is_deleted or bot.transport_type != "bot_api" or not project
        or project.is_deleted or project.status != "active"): return None
    repo = FunnelRepository(db)
    state = await repo.get_chat_funnel_state(chat_id)
    if (state is None or state.id != exc.retry_state_id or state.is_paused or state.completed_at is not None
        or state.current_step_id != exc.retry_step_id or AIDeliveryStateService.visit(state) != exc.retry_visit
        or chat.is_deleted or chat.reset_at is not None or chat.is_blocked or chat.is_blocked_by_user): return None
    existing = await db.scalar(select(FunnelScheduledJob.id).where(FunnelScheduledJob.chat_id == chat_id,
        FunnelScheduledJob.step_id == state.current_step_id, FunnelScheduledJob.job_type == exc.retry_job_type,
        FunnelScheduledJob.status.in_(["pending", "running"])).limit(1))
    if existing: return None  # A competing continuation is not permission to duplicate it.
    payload = {**exc.retry_payload, "runtime_delivery_visit": exc.retry_visit}
    if exc.retry_job_type == "input_prompt":
        state.runtime_json = {**(state.runtime_json or {}), "input_prompt_pending_step_id": str(state.current_step_id)}
        state.waiting_for_answer = False
    delay = max(settings.FUNNEL_SCHEDULED_DELIVERY_RETRY_BASE_SECONDS, error.retry_after or 0, 1)
    job = await repo.create_scheduled_job(job_type=exc.retry_job_type, chat_id=chat_id, funnel_state_id=state.id,
        funnel_id=state.funnel_id, funnel_version_id=state.funnel_version_id, step_id=state.current_step_id,
        run_at=datetime.now(timezone.utc) + timedelta(seconds=delay), payload_json=payload)
    await save_runtime_dispatch(db, key=f"scheduled:{job.id}", kind="scheduled",
        payload={"job_id": str(job.id), "run_at": job.run_at.isoformat()})
    return RuntimeDispatchDeliveryHandled("delivery_retry_scheduled", job.id)


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
                        # Follow the same Chat -> state -> dispatch lock order as
                        # runtime writers; never upgrade a dispatch lock to Chat.
                        from app.services.funnel_runtime_service import FunnelRuntimeDeliveryError
                        from app.services.telegram_sender import TelegramDeliveryError
                        delivery_error = exc.telegram_error if isinstance(exc, FunnelRuntimeDeliveryError) else exc
                        delivery_chat_id = (claimed[1] or {}).get("chat_id")
                        if isinstance(delivery_error, TelegramDeliveryError) and delivery_chat_id:
                            from app.repositories.funnel_repository import FunnelRepository
                            await failure_db.execute(text("SET LOCAL lock_timeout = '2s'"))
                            await FunnelRepository(failure_db).lock_chat_for_runtime(UUID(str(delivery_chat_id)))
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
                            handled = None
                            if isinstance(delivery_error, TelegramDeliveryError):
                                row.diagnostics_json = {**row.diagnostics_json, "telegram_method": delivery_error.method,
                                    "telegram_error_code": delivery_error.error_code, "telegram_http_status": delivery_error.status_code,
                                    "definitely_not_sent": delivery_error.definitely_not_sent, "blocked": delivery_error.blocked,
                                    "recipient_unavailable": delivery_error.recipient_unavailable}
                                if delivery_chat_id:
                                    handled = await _delivery_continuation(failure_db, exc, UUID(str(delivery_chat_id)))
                                if handled:
                                    row.status, row.completed_at = "done", datetime.now(timezone.utc)
                                    row.last_error = None
                                    row.diagnostics_json = {**row.diagnostics_json, "delivery_outcome": handled.outcome,
                                        "continuation_scheduled": handled.job_id is not None,
                                        "continuation_job_id": str(handled.job_id) if handled.job_id else None}
                        await failure_db.commit()
                if row and handled:
                    logger.info("Runtime delivery resolved dispatch_id=%s outcome=%s continuation_job_id=%s",
                        claimed_id, handled.outcome, handled.job_id)
                    raise handled from exc
                if row and not safe_retry and isinstance(exc, Exception):
                    raise RuntimeDispatchNeedsReview(key) from exc
            except (RuntimeDispatchNeedsReview, RuntimeDispatchDeliveryHandled):
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
