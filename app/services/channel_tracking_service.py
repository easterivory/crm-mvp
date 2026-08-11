from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import RoleName
from app.models.bot import Bot
from app.models.channel_tracking import (
    TelegramChannel,
    TelegramChannelInviteLink,
    TelegramChannelSubscriptionEvent,
)
from app.models.tracking import TrackingLink
from app.models.user import User
from app.repositories.bot_repository import BotRepository
from app.schemas.channel_tracking import (
    TelegramChannelCreate,
    TelegramChannelEventOut,
    TelegramChannelOut,
)
from app.services.access_control import require_project_access
from app.services.telegram_sender import TelegramSenderService


@dataclass(frozen=True)
class PreparedChannelInvite:
    invite_link: str
    telegram_name: str | None
    creates_join_request: bool
    telegram_chat_id: int
    bot_token: str = field(repr=False)


class ChannelTrackingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.bot_repo = BotRepository(db)
        self.sender = TelegramSenderService(db)

    async def list_channels(
        self,
        *,
        project_id: UUID,
        actor: User,
    ) -> list[TelegramChannelOut]:
        self._ensure_read_access(actor, project_id)
        result = await self.db.execute(
            select(TelegramChannel)
            .where(
                TelegramChannel.project_id == project_id,
                TelegramChannel.is_active.is_(True),
            )
            .order_by(TelegramChannel.title.asc(), TelegramChannel.created_at.desc())
        )
        return [TelegramChannelOut.model_validate(item) for item in result.scalars().all()]

    async def create_or_update_channel(
        self,
        *,
        project_id: UUID,
        data: TelegramChannelCreate,
        actor: User,
    ) -> TelegramChannelOut:
        self._ensure_manage_access(actor, project_id)
        bot = await self._get_tracker_bot(data.tracker_bot_id, project_id)
        chat_data, membership = await self._inspect_channel(
            bot=bot,
            chat_reference=data.telegram_chat_id,
        )
        chat_id = self._parse_channel_id(chat_data.get("id"))
        channel = await self._get_by_project_chat(project_id, chat_id)
        if channel is None:
            channel = TelegramChannel(
                project_id=project_id,
                tracker_bot_id=bot.id,
                telegram_chat_id=chat_id,
                title=self._channel_title(chat_data),
                username=self._optional_text(chat_data.get("username")),
                description=self._optional_text(chat_data.get("description")),
                is_active=True,
            )
            self.db.add(channel)
        else:
            channel.tracker_bot_id = bot.id
            channel.title = self._channel_title(chat_data)
            channel.username = self._optional_text(chat_data.get("username"))
            channel.description = self._optional_text(chat_data.get("description"))
            channel.is_active = True

        self._apply_membership(channel, membership)
        await self.db.flush()
        await self.db.refresh(channel)
        return TelegramChannelOut.model_validate(channel)

    async def verify_channel(
        self,
        *,
        project_id: UUID,
        channel_id: UUID,
        actor: User,
    ) -> TelegramChannelOut:
        self._ensure_manage_access(actor, project_id)
        channel = await self.get_channel(
            channel_id=channel_id,
            project_id=project_id,
            require_active=True,
        )
        bot = channel.tracker_bot
        chat_data, membership = await self._inspect_channel(
            bot=bot,
            chat_reference=str(channel.telegram_chat_id),
        )
        channel.title = self._channel_title(chat_data)
        channel.username = self._optional_text(chat_data.get("username"))
        channel.description = self._optional_text(chat_data.get("description"))
        self._apply_membership(channel, membership)
        await self.db.flush()
        await self.db.refresh(channel)
        return TelegramChannelOut.model_validate(channel)

    async def deactivate_channel(
        self,
        *,
        project_id: UUID,
        channel_id: UUID,
        actor: User,
    ) -> None:
        self._ensure_manage_access(actor, project_id)
        channel = await self.get_channel(
            channel_id=channel_id,
            project_id=project_id,
            require_active=True,
        )
        active_link_result = await self.db.execute(
            select(TrackingLink.id).where(
                TrackingLink.channel_id == channel.id,
                TrackingLink.is_active.is_(True),
            ).limit(1)
        )
        if active_link_result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Archive active channel tracking links before removing the channel",
            )
        channel.is_active = False
        await self.db.flush()

    async def list_recent_events(
        self,
        *,
        project_id: UUID,
        actor: User,
        channel_id: UUID | None = None,
        limit: int = 100,
    ) -> list[TelegramChannelEventOut]:
        self._ensure_read_access(actor, project_id)
        statement = select(TelegramChannelSubscriptionEvent).where(
            TelegramChannelSubscriptionEvent.project_id == project_id
        )
        if channel_id is not None:
            statement = statement.where(
                TelegramChannelSubscriptionEvent.channel_id == channel_id
            )
        result = await self.db.execute(
            statement.order_by(
                TelegramChannelSubscriptionEvent.occurred_at.desc()
            ).limit(max(1, min(limit, 500)))
        )
        return [
            TelegramChannelEventOut.model_validate(item)
            for item in result.scalars().all()
        ]

    async def resolve_channel_avatar(
        self,
        *,
        project_id: UUID,
        channel_id: UUID,
        actor: User,
    ) -> tuple[bytes, str]:
        self._ensure_read_access(actor, project_id)
        channel = await self.get_channel(
            channel_id=channel_id,
            project_id=project_id,
            require_active=True,
        )
        token = str(channel.tracker_bot.telegram_token or "").strip()
        if not token:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Channel avatar is unavailable",
            )
        await self._release_read_transaction()
        try:
            chat_data = await self.sender.get_chat(
                token,
                channel.telegram_chat_id,
            )
            photo = chat_data.get("photo")
            file_id = photo.get("big_file_id") if isinstance(photo, dict) else None
            if not file_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Channel has no profile photo",
                )
            file_data = await self.sender.get_file(token, str(file_id))
            file_path = str(file_data.get("file_path") or "").strip()
            if not file_path:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Channel avatar is unavailable",
                )
            content = await self.sender.download_file(
                token,
                file_path,
                max_bytes=5 * 1024 * 1024,
            )
        except HTTPException:
            raise
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Telegram did not return the channel avatar",
            ) from exc
        return content, mimetypes.guess_type(file_path)[0] or "image/jpeg"

    async def get_channel(
        self,
        *,
        channel_id: UUID,
        project_id: UUID,
        require_active: bool = True,
    ) -> TelegramChannel:
        statement = (
            select(TelegramChannel)
            .options(selectinload(TelegramChannel.tracker_bot))
            .where(
                TelegramChannel.id == channel_id,
                TelegramChannel.project_id == project_id,
            )
        )
        if require_active:
            statement = statement.where(TelegramChannel.is_active.is_(True))
        result = await self.db.execute(statement)
        channel = result.scalar_one_or_none()
        if channel is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Telegram channel not found",
            )
        return channel

    async def prepare_invite_link(
        self,
        *,
        channel: TelegramChannel,
        code: str,
        creates_join_request: bool,
    ) -> PreparedChannelInvite:
        bot = channel.tracker_bot
        token = str(bot.telegram_token or "").strip()
        if not token:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Tracker bot token is not configured",
            )
        if not channel.bot_is_admin or not channel.can_invite_users:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Tracker bot must be a channel administrator with permission "
                    "to invite users"
                ),
            )
        await self._release_read_transaction()
        telegram_name = f"crm-{code}"[:32]
        try:
            result = await self.sender.create_chat_invite_link(
                token,
                chat_id=channel.telegram_chat_id,
                name=telegram_name,
                creates_join_request=creates_join_request,
            )
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Telegram did not create the channel invite link: {exc}",
            ) from exc
        return PreparedChannelInvite(
            invite_link=str(result["invite_link"]),
            telegram_name=self._optional_text(result.get("name")) or telegram_name,
            creates_join_request=bool(result.get("creates_join_request")),
            telegram_chat_id=channel.telegram_chat_id,
            bot_token=token,
        )

    async def persist_invite_link(
        self,
        *,
        project_id: UUID,
        channel_id: UUID,
        tracking_link_id: UUID,
        prepared: PreparedChannelInvite,
    ) -> TelegramChannelInviteLink:
        await self.mark_invites_not_current(tracking_link_id)
        item = TelegramChannelInviteLink(
            project_id=project_id,
            channel_id=channel_id,
            tracking_link_id=tracking_link_id,
            invite_link=prepared.invite_link,
            telegram_name=prepared.telegram_name,
            creates_join_request=prepared.creates_join_request,
            is_current=True,
        )
        self.db.add(item)
        return item

    async def revoke_prepared_invite(
        self,
        *,
        prepared: PreparedChannelInvite,
    ) -> None:
        if not prepared.bot_token:
            return
        try:
            await self.sender.revoke_chat_invite_link(
                prepared.bot_token,
                chat_id=prepared.telegram_chat_id,
                invite_link=prepared.invite_link,
            )
        except RuntimeError:
            # The database operation already failed; revocation is best-effort
            # and must not mask the original error.
            return

    async def mark_invites_not_current(self, tracking_link_id: UUID) -> None:
        result = await self.db.execute(
            select(TelegramChannelInviteLink).where(
                TelegramChannelInviteLink.tracking_link_id == tracking_link_id,
                TelegramChannelInviteLink.is_current.is_(True),
            )
        )
        for item in result.scalars().all():
            item.is_current = False

    async def _get_tracker_bot(self, bot_id: UUID, project_id: UUID) -> Bot:
        bot = await self.bot_repo.get_by_id_in_project(bot_id, project_id)
        if bot is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tracker bot not found",
            )
        if not str(bot.telegram_token or "").strip() or bot.telegram_bot_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Configure and verify the tracker bot token first",
            )
        return bot

    async def _inspect_channel(
        self,
        *,
        bot: Bot,
        chat_reference: str,
    ) -> tuple[dict, dict]:
        token = str(bot.telegram_token or "").strip()
        await self._release_read_transaction()
        try:
            chat_data = await self.sender.get_chat(token, chat_reference)
            if str(chat_data.get("type") or "").lower() != "channel":
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="The specified Telegram chat is not a channel",
                )
            membership = await self.sender.get_chat_member(
                token,
                chat_id=self._parse_channel_id(chat_data.get("id")),
                user_id=int(bot.telegram_bot_id),
            )
        except HTTPException:
            raise
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Could not verify Telegram channel: {exc}",
            ) from exc

        member_status = str(membership.get("status") or "").lower()
        is_admin = member_status in {"administrator", "creator"}
        can_invite = member_status == "creator" or bool(
            membership.get("can_invite_users")
        )
        if not is_admin or not can_invite:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Add the tracker bot as a channel administrator and grant "
                    "permission to invite users"
                ),
            )
        return chat_data, membership

    async def _release_read_transaction(self) -> None:
        if not self.db.in_transaction():
            return
        if self.db.new or self.db.dirty or self.db.deleted:
            raise RuntimeError(
                "Cannot call Telegram while the database session has pending writes"
            )
        await self.db.commit()

    async def _get_by_project_chat(
        self,
        project_id: UUID,
        telegram_chat_id: int,
    ) -> TelegramChannel | None:
        result = await self.db.execute(
            select(TelegramChannel).where(
                TelegramChannel.project_id == project_id,
                TelegramChannel.telegram_chat_id == telegram_chat_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _apply_membership(channel: TelegramChannel, membership: dict) -> None:
        member_status = str(membership.get("status") or "").lower()
        channel.bot_is_admin = member_status in {"administrator", "creator"}
        channel.can_invite_users = member_status == "creator" or bool(
            membership.get("can_invite_users")
        )
        channel.verified_at = datetime.now(timezone.utc)

    @staticmethod
    def _parse_channel_id(value: object) -> int:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Telegram returned an invalid channel ID",
            ) from exc

    @staticmethod
    def _channel_title(chat_data: dict) -> str:
        title = str(chat_data.get("title") or "").strip()
        if not title:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Telegram channel has no title",
            )
        return title[:255]

    @staticmethod
    def _optional_text(value: object) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @staticmethod
    def _ensure_read_access(actor: User, project_id: UUID) -> None:
        if actor.role_name not in {
            RoleName.SUPER_ADMIN,
            RoleName.ADMIN,
            RoleName.BUYER,
        }:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Current user cannot access channel tracking",
            )
        require_project_access(actor, project_id)

    @staticmethod
    def _ensure_manage_access(actor: User, project_id: UUID) -> None:
        if actor.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admin/super_admin can configure tracker channels",
            )
        require_project_access(actor, project_id)
