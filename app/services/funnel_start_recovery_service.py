from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import MessageType, SenderType
from app.models.chat import Chat
from app.models.funnel import ChatFunnelState
from app.models.message import Message
from app.services.funnel_start_queue import (
    FunnelStartRequest,
    enqueue_funnel_starts,
)

logger = logging.getLogger(__name__)

START_COMMAND_RE = re.compile(r"^\s*/start(?:@[A-Za-z0-9_]+)?(?:\s|$)")
NEW_CYCLE_TOLERANCE = timedelta(seconds=2)


@dataclass(frozen=True)
class FunnelStartRecoveryResult:
    lookback_hours: int
    scanned: int
    eligible: int
    enqueued: int
    already_enqueued: int
    queue_failed: int
    already_running: int
    completed_current_cycle: int
    fresh_lifecycles: int

    @property
    def scheduled(self) -> int:
        return self.enqueued + self.already_enqueued


class FunnelStartRecoveryService:
    """Reconcile persisted Telegram /start messages that never reached runtime."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def recover(
        self,
        *,
        lookback_hours: int = 24,
        limit: int = 500,
        job_scope: str,
    ) -> FunnelStartRecoveryResult:
        normalized_hours = min(max(int(lookback_hours), 1), 24 * 30)
        normalized_limit = min(max(int(limit), 1), 5000)
        since = datetime.now(timezone.utc) - timedelta(hours=normalized_hours)

        result = await self.db.execute(
            select(
                Message.id.label("message_id"),
                Message.chat_id,
                Message.body,
                Message.created_at.label("message_created_at"),
                Chat.current_cycle_started_at,
                ChatFunnelState.id.label("state_id"),
                ChatFunnelState.completed_at.label("state_completed_at"),
            )
            .join(Chat, Chat.id == Message.chat_id)
            .outerjoin(ChatFunnelState, ChatFunnelState.chat_id == Chat.id)
            .where(
                Message.sender_type == SenderType.USER,
                Message.message_type == MessageType.TEXT,
                Message.funnel_processed_at.is_(None),
                Message.body.is_not(None),
                func.lower(func.ltrim(Message.body)).like("/start%"),
                Message.created_at >= since,
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
                Chat.is_blocked.is_(False),
                Chat.is_blocked_by_user.is_(False),
                Chat.bot_id.is_not(None),
            )
            .order_by(Message.created_at.asc(), Message.id.asc())
            .limit(normalized_limit)
        )

        requests: list[FunnelStartRequest] = []
        ignored_message_ids = []
        scanned = 0
        already_running = 0
        completed_current_cycle = 0
        fresh_lifecycles = 0

        for row in result.all():
            if START_COMMAND_RE.match(str(row.body or "")) is None:
                continue
            scanned += 1

            if row.state_id is None:
                requests.append(
                    FunnelStartRequest(
                        chat_id=row.chat_id,
                        message_id=row.message_id,
                        fresh_lifecycle=False,
                    )
                )
                continue

            if row.state_completed_at is None:
                already_running += 1
                ignored_message_ids.append(row.message_id)
                continue

            if self._starts_new_cycle(
                message_created_at=row.message_created_at,
                cycle_started_at=row.current_cycle_started_at,
                state_completed_at=row.state_completed_at,
            ):
                fresh_lifecycles += 1
                requests.append(
                    FunnelStartRequest(
                        chat_id=row.chat_id,
                        message_id=row.message_id,
                        fresh_lifecycle=True,
                    )
                )
                continue

            completed_current_cycle += 1
            ignored_message_ids.append(row.message_id)

        if ignored_message_ids:
            await self.db.execute(
                update(Message)
                .where(
                    Message.id.in_(ignored_message_ids),
                    Message.funnel_processed_at.is_(None),
                )
                .values(funnel_processed_at=datetime.now(timezone.utc))
            )

        enqueue_result = await enqueue_funnel_starts(requests, job_scope=job_scope)
        recovery = FunnelStartRecoveryResult(
            lookback_hours=normalized_hours,
            scanned=scanned,
            eligible=len(requests),
            enqueued=enqueue_result.enqueued,
            already_enqueued=enqueue_result.already_enqueued,
            queue_failed=enqueue_result.failed,
            already_running=already_running,
            completed_current_cycle=completed_current_cycle,
            fresh_lifecycles=fresh_lifecycles,
        )
        if recovery.eligible or recovery.queue_failed:
            logger.info(
                "Funnel start recovery completed lookback_hours=%s scanned=%s "
                "eligible=%s scheduled=%s failed=%s already_running=%s completed=%s",
                recovery.lookback_hours,
                recovery.scanned,
                recovery.eligible,
                recovery.scheduled,
                recovery.queue_failed,
                recovery.already_running,
                recovery.completed_current_cycle,
            )
        return recovery

    @staticmethod
    def _starts_new_cycle(
        *,
        message_created_at: datetime,
        cycle_started_at: datetime | None,
        state_completed_at: datetime,
    ) -> bool:
        if cycle_started_at is None:
            return False
        return (
            state_completed_at < cycle_started_at
            and message_created_at + NEW_CYCLE_TOLERANCE >= cycle_started_at
        )
