from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.channel_tracking import (
    TelegramChannel,
    TelegramChannelInviteLink,
    TelegramChannelSubscription,
    TelegramChannelSubscriptionEvent,
)
from app.models.tracking import TrackingLink
from app.schemas.telegram import (
    TelegramChatJoinRequest,
    TelegramChatMember,
    TelegramChatMemberUpdated,
    TelegramUser,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChannelJoinRequestAction:
    event_id: UUID


class ChannelSubscriptionService:
    ACTIVE_MEMBER_STATUSES = frozenset({"member", "administrator", "creator"})

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def handle_chat_member_update(
        self,
        *,
        update_id: int,
        bot_id: UUID,
        event: TelegramChatMemberUpdated,
    ) -> bool:
        channel = await self._find_channel(
            bot_id=bot_id,
            telegram_chat_id=event.chat.id,
        )
        if channel is None:
            return False
        if await self._already_processed(bot_id=bot_id, update_id=update_id):
            return True

        old_active = self._is_active_member(event.old_chat_member)
        new_active = self._is_active_member(event.new_chat_member)
        if old_active == new_active:
            return True

        if new_active:
            event_type = "join"
            subscription_status = "member"
        else:
            new_status = str(event.new_chat_member.status or "").strip().lower()
            event_type = "kick" if new_status == "kicked" else "leave"
            subscription_status = "kicked" if event_type == "kick" else "left"

        invite_link = self._invite_url(event.invite_link)
        invite = await self._resolve_invite(channel.id, invite_link)
        user = event.new_chat_member.user
        occurred_at = self._from_unix(event.date)
        subscription = await self._get_subscription(channel.id, user.id)
        tracking_link_id = (
            invite.tracking_link_id
            if invite is not None
            else subscription.tracking_link_id
            if subscription is not None
            else None
        )
        inserted = await self._insert_event(
            channel=channel,
            bot_id=bot_id,
            update_id=update_id,
            event_type=event_type,
            user=user,
            tracking_link_id=tracking_link_id,
            invite_link=invite_link,
            previous_status=event.old_chat_member.status,
            new_status=event.new_chat_member.status,
            occurred_at=occurred_at,
            raw_payload=event.model_dump(mode="json", by_alias=True),
        )
        if not inserted:
            return True
        await self._upsert_subscription(
            channel=channel,
            bot_id=bot_id,
            user=user,
            tracking_link_id=tracking_link_id,
            status=subscription_status,
            occurred_at=occurred_at,
            update_id=update_id,
        )
        await self._queue_facebook_event(
            tracking_link_id=tracking_link_id,
            channel=channel,
            user=user,
            source_event=("channel_subscribe" if event_type == "join" else "channel_unsubscribe"),
            update_id=update_id,
            occurred_at=occurred_at,
        )
        return True

    async def handle_join_request(
        self,
        *,
        update_id: int,
        bot_id: UUID,
        event: TelegramChatJoinRequest,
    ) -> ChannelJoinRequestAction | None:
        channel = await self._find_channel(
            bot_id=bot_id,
            telegram_chat_id=event.chat.id,
        )
        if channel is None:
            return None
        if await self._already_processed(bot_id=bot_id, update_id=update_id):
            return None

        invite_link = self._invite_url(event.invite_link)
        invite = await self._resolve_invite(channel.id, invite_link)
        request_message_text, auto_approve = await self._join_request_options(
            invite.tracking_link_id if invite is not None else None
        )
        occurred_at = self._from_unix(event.date)
        inserted = await self._insert_event(
            channel=channel,
            bot_id=bot_id,
            update_id=update_id,
            event_type="join_request",
            user=event.from_user,
            tracking_link_id=(invite.tracking_link_id if invite is not None else None),
            invite_link=invite_link,
            previous_status=None,
            new_status="pending",
            occurred_at=occurred_at,
            raw_payload=event.model_dump(mode="json", by_alias=True),
            request_message_text=request_message_text,
            auto_approve_requested=auto_approve,
        )
        if not inserted:
            return None
        await self._upsert_subscription(
            channel=channel,
            bot_id=bot_id,
            user=event.from_user,
            tracking_link_id=(invite.tracking_link_id if invite is not None else None),
            status="pending",
            occurred_at=occurred_at,
            update_id=update_id,
        )
        if request_message_text or auto_approve:
            return ChannelJoinRequestAction(event_id=inserted.id)
        return None

    async def handle_tracker_membership(
        self,
        *,
        bot_id: UUID,
        event: TelegramChatMemberUpdated,
    ) -> bool:
        channel = await self._find_channel(
            bot_id=bot_id,
            telegram_chat_id=event.chat.id,
            require_active=False,
        )
        if channel is None:
            return False
        status = str(event.new_chat_member.status or "").strip().lower()
        channel.bot_is_admin = status in {"administrator", "creator"}
        channel.can_invite_users = status == "creator" or bool(
            event.new_chat_member.can_invite_users
        )
        channel.verified_at = datetime.now(timezone.utc)
        if status in {"left", "kicked"}:
            channel.is_active = False
        await self.db.flush()
        return True

    async def resolve_latest_tracking_link(
        self,
        *,
        project_id: UUID,
        telegram_user_id: int,
    ) -> UUID | None:
        """Return last-touch attribution from a confirmed channel join."""
        result = await self.db.execute(
            select(TelegramChannelSubscriptionEvent.tracking_link_id)
            .join(
                TrackingLink,
                TrackingLink.id
                == TelegramChannelSubscriptionEvent.tracking_link_id,
            )
            .where(
                TelegramChannelSubscriptionEvent.project_id == project_id,
                TelegramChannelSubscriptionEvent.telegram_user_id
                == telegram_user_id,
                TelegramChannelSubscriptionEvent.event_type == "join",
                TelegramChannelSubscriptionEvent.tracking_link_id.is_not(None),
                TrackingLink.destination_type == "channel",
            )
            .order_by(
                TelegramChannelSubscriptionEvent.occurred_at.desc(),
                TelegramChannelSubscriptionEvent.telegram_update_id.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _find_channel(
        self,
        *,
        bot_id: UUID,
        telegram_chat_id: int,
        require_active: bool = True,
    ) -> TelegramChannel | None:
        statement = select(TelegramChannel).where(
            TelegramChannel.tracker_bot_id == bot_id,
            TelegramChannel.telegram_chat_id == telegram_chat_id,
        )
        if require_active:
            statement = statement.where(TelegramChannel.is_active.is_(True))
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def _resolve_invite(
        self,
        channel_id: UUID,
        invite_link: str | None,
    ) -> TelegramChannelInviteLink | None:
        if not invite_link:
            return None
        result = await self.db.execute(
            select(TelegramChannelInviteLink).where(
                TelegramChannelInviteLink.channel_id == channel_id,
                TelegramChannelInviteLink.invite_link == invite_link,
            )
        )
        return result.scalar_one_or_none()

    async def _join_request_options(
        self,
        tracking_link_id: UUID | None,
    ) -> tuple[str | None, bool]:
        if tracking_link_id is None:
            return None, False
        result = await self.db.execute(
            select(
                TrackingLink.channel_join_request,
                TrackingLink.channel_request_message_enabled,
                TrackingLink.channel_request_message,
                TrackingLink.channel_auto_approve,
            ).where(TrackingLink.id == tracking_link_id)
        )
        row = result.one_or_none()
        if row is None or not bool(row.channel_join_request):
            return None, False
        message = (
            str(row.channel_request_message or "").strip()
            if bool(row.channel_request_message_enabled)
            else ""
        )
        return message or None, bool(row.channel_auto_approve)

    async def _get_subscription(
        self,
        channel_id: UUID,
        telegram_user_id: int,
    ) -> TelegramChannelSubscription | None:
        result = await self.db.execute(
            select(TelegramChannelSubscription).where(
                TelegramChannelSubscription.channel_id == channel_id,
                TelegramChannelSubscription.telegram_user_id == telegram_user_id,
            )
        )
        return result.scalar_one_or_none()

    async def _already_processed(self, *, bot_id: UUID, update_id: int) -> bool:
        result = await self.db.execute(
            select(TelegramChannelSubscriptionEvent.id).where(
                TelegramChannelSubscriptionEvent.tracker_bot_id == bot_id,
                TelegramChannelSubscriptionEvent.telegram_update_id == update_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def _insert_event(
        self,
        *,
        channel: TelegramChannel,
        bot_id: UUID,
        update_id: int,
        event_type: str,
        user: TelegramUser,
        tracking_link_id: UUID | None,
        invite_link: str | None,
        previous_status: str | None,
        new_status: str | None,
        occurred_at: datetime,
        raw_payload: dict,
        request_message_text: str | None = None,
        auto_approve_requested: bool = False,
    ) -> TelegramChannelSubscriptionEvent | None:
        item = TelegramChannelSubscriptionEvent(
            project_id=channel.project_id,
            channel_id=channel.id,
            tracking_link_id=tracking_link_id,
            tracker_bot_id=bot_id,
            telegram_user_id=user.id,
            telegram_update_id=update_id,
            event_type=event_type,
            previous_status=previous_status,
            new_status=new_status,
            invite_link=invite_link,
            username=self._clean(user.username),
            first_name=self._clean(user.first_name),
            last_name=self._clean(user.last_name),
            raw_payload=raw_payload,
            request_message_text=request_message_text,
            auto_approve_requested=auto_approve_requested,
            occurred_at=occurred_at,
        )
        try:
            async with self.db.begin_nested():
                self.db.add(item)
                await self.db.flush()
        except IntegrityError:
            # Telegram retries are expected. Keep the webhook idempotent.
            logger.info(
                "Duplicate Telegram channel update ignored bot_id=%s update_id=%s",
                bot_id,
                update_id,
            )
            return None
        return item

    async def _upsert_subscription(
        self,
        *,
        channel: TelegramChannel,
        bot_id: UUID,
        user: TelegramUser,
        tracking_link_id: UUID | None,
        status: str,
        occurred_at: datetime,
        update_id: int,
    ) -> None:
        item = await self._get_subscription(channel.id, user.id)
        if item is None:
            item = TelegramChannelSubscription(
                project_id=channel.project_id,
                channel_id=channel.id,
                tracking_link_id=tracking_link_id,
                tracker_bot_id=bot_id,
                telegram_user_id=user.id,
                status=status,
                last_event_at=occurred_at,
            )
            self.db.add(item)
        else:
            if item.last_update_id is not None and update_id <= item.last_update_id:
                logger.info(
                    "Stale Telegram channel update ignored for current state "
                    "channel_id=%s user_id=%s update_id=%s last_update_id=%s",
                    channel.id,
                    user.id,
                    update_id,
                    item.last_update_id,
                )
                return
            if tracking_link_id is not None and status in {"pending", "member"}:
                item.tracking_link_id = tracking_link_id
        item.username = self._clean(user.username)
        item.first_name = self._clean(user.first_name)
        item.last_name = self._clean(user.last_name)
        item.status = status
        item.last_event_at = occurred_at
        item.last_update_id = update_id
        if status == "member":
            item.first_joined_at = item.first_joined_at or occurred_at
            item.joined_at = occurred_at
            item.left_at = None
        elif status in {"left", "kicked"}:
            item.left_at = occurred_at
        await self.db.flush()

    async def _queue_facebook_event(
        self,
        *,
        tracking_link_id: UUID | None,
        channel: TelegramChannel,
        user: TelegramUser,
        source_event: str,
        update_id: int,
        occurred_at: datetime,
    ) -> None:
        if tracking_link_id is None:
            return
        try:
            from app.services.facebook_channel_event_service import (
                FacebookChannelEventService,
            )

            await FacebookChannelEventService(self.db).enqueue_event(
                tracking_link_id=tracking_link_id,
                channel=channel,
                user=user,
                source_event=source_event,
                update_id=update_id,
                occurred_at=occurred_at,
            )
        except Exception:
            logger.exception(
                "Could not queue Facebook channel event link_id=%s source=%s",
                tracking_link_id,
                source_event,
            )

    @classmethod
    def _is_active_member(cls, member: TelegramChatMember) -> bool:
        status = str(member.status or "").strip().lower()
        if status in cls.ACTIVE_MEMBER_STATUSES:
            return True
        return status == "restricted" and bool(member.is_member)

    @staticmethod
    def _invite_url(value) -> str | None:
        normalized = str(getattr(value, "invite_link", None) or "").strip()
        return normalized or None

    @staticmethod
    def _from_unix(value: int | None) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        return datetime.fromtimestamp(value, tz=timezone.utc)

    @staticmethod
    def _clean(value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized[:255] or None
