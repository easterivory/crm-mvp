"""
TrackingService - project-scoped tracking links, Telegram invite links, and spend.
"""
import re
import secrets
import string
import unicodedata
from datetime import date
from decimal import Decimal
from urllib.parse import quote
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import RoleName, TrackingCostModel, TrackingSpendSource
from app.core.facebook_events import normalize_facebook_event_mappings
from app.core.lander_urls import build_channel_tracking_url
from app.core.telegram_links import (
    build_telegram_bot_start_link,
    canonicalize_telegram_web_link,
)
from app.models.tracking import TrackingLink
from app.models.tracking import TrackingSpend
from app.models.funnel import FunnelStep, FunnelVersion
from app.models.user import User, UserProjectAccess
from app.repositories.bot_repository import BotRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.tracking_repository import TrackingLinkRepository
from app.repositories.tracking_metrics_repository import TrackingMetricsRepository
from app.repositories.tracking_repository import TrackingRepository
from app.repositories.tracking_repository import TrackingSpendRepository
from app.schemas.tracking import (
    TrackingLinkCreate,
    TrackingLinkOut,
    TrackingLinkRead,
    TrackingLinkUpdate,
    TrackingFunnelStepOption,
    TrackingSpendCreate,
    TrackingSpendRead,
    TrackingSpendUpdate,
)
from app.services.bot_service import BotService
from app.services.access_control import require_project_access
from app.services.facebook_campaign_service import FacebookCampaignService
from app.services.channel_tracking_service import (
    ChannelTrackingService,
    PreparedChannelInvite,
)


class TrackingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.tracking_repo = TrackingRepository(db)
        self.link_repo = TrackingLinkRepository(db)
        self.spend_repo = TrackingSpendRepository(db)
        self.bot_repo = BotRepository(db)
        self.bot_service = BotService(db)
        self.project_repo = ProjectRepository(db)
        self.channel_service = ChannelTrackingService(db)

    async def list_links(
        self,
        project_id: UUID,
        limit: int,
        offset: int,
        bot_id: UUID | None = None,
    ) -> tuple[list[TrackingLinkOut], int]:
        if bot_id is not None:
            await self._ensure_bot_in_project(bot_id, project_id)

        links = await self.link_repo.list_by_project(
            project_id=project_id,
            limit=limit,
            offset=offset,
            bot_id=bot_id,
        )
        total = await self.link_repo.count_by_project(
            project_id=project_id,
            bot_id=bot_id,
        )
        return [self._to_out(link) for link in links], total

    async def get_link(self, link_id: UUID, project_id: UUID) -> TrackingLinkOut:
        link = await self.link_repo.get_by_id_in_project(link_id, project_id)
        if link is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tracking link not found",
            )
        return self._to_out(link)

    async def create_link(
        self,
        project_id: UUID,
        data: TrackingLinkCreate,
    ) -> TrackingLinkOut:
        if data.destination_type != "bot" or data.bot_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The legacy tracking endpoint supports bot links only",
            )
        self._validate_cost_configuration(data.cost_model, data.price_per_unit)
        if (
            data.destination_type == "channel"
            and data.cost_model == TrackingCostModel.CPA
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="CPA by submitted lead is not available for channel traffic",
            )
        await self._validate_facebook_event_mappings(
            project_id=project_id,
            mappings=data.fb_event_mappings,
        )
        await self._ensure_bot_supports_tracking(data.bot_id, project_id)
        bot = await self.bot_service.ensure_bot_username(
            bot_id=data.bot_id,
            project_id=project_id,
        )
        title = self._normalize_required(data.title or data.name, "name")
        target_step_id = data.target_step_id
        if target_step_id is not None:
            await self._ensure_step_belongs_to_bot(target_step_id, bot.id, project_id)
        target_funnel_id, target_funnel_step_key = await self._resolve_target_funnel_step(
            bot_id=bot.id,
            project_id=project_id,
            target_funnel_step_key=data.target_funnel_step_key,
        )

        requested_code = self._normalize_code(data.code or data.ref_code)
        code = requested_code or await self._generate_unique_code(title)
        invite_link = canonicalize_telegram_web_link(
            self._normalize_optional(data.invite_link)
        ) or self._build_invite_link(bot.bot_username, code)
        buyer_id, buyer_name = await self._resolve_buyer(
            project_id=project_id,
            buyer_id=data.buyer_id,
            buyer_name=data.buyer_name,
        )

        try:
            async with self.db.begin_nested():
                link = await self.link_repo.create_link(
                    project_id=project_id,
                    bot_id=bot.id,
                    name=title,
                    title=title,
                    ref_code=code,
                    code=code,
                    buyer_id=buyer_id,
                    buyer_name=buyer_name,
                    ad_type=self._normalize_optional(data.ad_type),
                    payment_type=self._normalize_optional(data.payment_type),
                    invite_link=invite_link,
                    fb_pixel_id=data.fb_pixel_id,
                    fb_capi_token=data.fb_capi_token,
                    fb_campaign_enabled=data.fb_campaign_enabled,
                    fb_event_mappings_json=[
                        item.model_dump() for item in data.fb_event_mappings
                    ],
                    fb_proxy_url=data.fb_proxy_url,
                    fb_test_event_code=data.fb_test_event_code,
                    cost_model=data.cost_model,
                    price_per_unit=data.price_per_unit,
                    spend=data.spend,
                    base_conversion_rate=data.base_conversion_rate,
                    min_sample_size=data.min_sample_size,
                    target_step_id=target_step_id,
                    target_funnel_id=target_funnel_id,
                    target_funnel_step_key=target_funnel_step_key,
                )
        except IntegrityError as exc:
            if requested_code is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Tracking code already exists",
                ) from exc
            code = await self._generate_unique_code(title)
            async with self.db.begin_nested():
                link = await self.link_repo.create_link(
                    project_id=project_id,
                    bot_id=bot.id,
                    name=title,
                    title=title,
                    ref_code=code,
                    code=code,
                    buyer_id=buyer_id,
                    buyer_name=buyer_name,
                    ad_type=self._normalize_optional(data.ad_type),
                    payment_type=self._normalize_optional(data.payment_type),
                    invite_link=self._build_invite_link(bot.bot_username, code),
                    fb_pixel_id=data.fb_pixel_id,
                    fb_capi_token=data.fb_capi_token,
                    fb_campaign_enabled=data.fb_campaign_enabled,
                    fb_event_mappings_json=[
                        item.model_dump() for item in data.fb_event_mappings
                    ],
                    fb_proxy_url=data.fb_proxy_url,
                    fb_test_event_code=data.fb_test_event_code,
                    cost_model=data.cost_model,
                    price_per_unit=data.price_per_unit,
                    spend=data.spend,
                    base_conversion_rate=data.base_conversion_rate,
                    min_sample_size=data.min_sample_size,
                    target_step_id=target_step_id,
                    target_funnel_id=target_funnel_id,
                    target_funnel_step_key=target_funnel_step_key,
                )

        link.bot = bot
        await self._create_initial_manual_spend(link, data, actor_id=None)
        return self._to_out(link)

    async def update_link(
        self,
        link_id: UUID,
        project_id: UUID,
        data: TrackingLinkUpdate,
    ) -> TrackingLinkOut:
        link = await self.link_repo.get_by_id_in_project(link_id, project_id)
        if link is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tracking link not found",
            )

        if (
            "fb_event_mappings" in data.model_fields_set
            and data.fb_event_mappings is not None
        ):
            await self._validate_facebook_event_mappings(
                project_id=project_id,
                mappings=data.fb_event_mappings,
            )

        values = self._build_link_update_values(data, link=link, allow_code_update=True)
        values = self._normalize_channel_request_update(link=link, values=values)
        if {"cost_model", "price_per_unit"} & values.keys():
            if (
                link.destination_type == "channel"
                and values.get("cost_model", link.cost_model) == TrackingCostModel.CPA
            ):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="CPA by submitted lead is not available for channel traffic",
                )
            self._validate_cost_configuration(
                values.get("cost_model", link.cost_model),
                values.get("price_per_unit", link.price_per_unit),
            )
        if "buyer_id" in data.model_fields_set:
            buyer_id, buyer_name = await self._resolve_buyer(
                project_id=link.project_id,
                buyer_id=data.buyer_id,
                buyer_name=data.buyer_name,
            )
            values["buyer_id"] = buyer_id
            values["buyer_name"] = buyer_name
        if values.get("target_step_id") is not None:
            await self._ensure_step_belongs_to_bot(
                values["target_step_id"],
                link.bot_id,
                project_id,
            )
        if "target_funnel_step_key" in values:
            target_funnel_id, target_funnel_step_key = await self._resolve_target_funnel_step(
                bot_id=link.bot_id,
                project_id=project_id,
                target_funnel_step_key=values["target_funnel_step_key"],
            )
            values["target_funnel_id"] = target_funnel_id
            values["target_funnel_step_key"] = target_funnel_step_key

        if not values:
            return self._to_out(link)

        try:
            async with self.db.begin_nested():
                updated = await self.link_repo.update_link(link_id, **values)
        except IntegrityError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Tracking code already exists",
            ) from exc

        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tracking link not found",
            )

        return await self.get_link(updated.id, project_id)

    async def delete_link(self, link_id: UUID, project_id: UUID) -> None:
        deleted = await self.link_repo.delete_from_project(link_id, project_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tracking link not found",
            )

    async def list_tracking_links(
        self,
        *,
        project_id: UUID,
        actor: User,
        limit: int,
        offset: int,
        bot_id: UUID | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[TrackingLinkRead], int]:
        await self._ensure_project_access(actor, project_id)
        await self._get_active_project_or_404(project_id)
        if bot_id is not None:
            await self._ensure_bot_in_project(bot_id, project_id)

        buyer_id = actor.id if actor.role_name == RoleName.BUYER else None

        links = await self.link_repo.list_links(
            project_id=project_id,
            limit=limit,
            offset=offset,
            bot_id=bot_id,
            is_active=is_active,
            buyer_id=buyer_id,
        )
        total = await self.link_repo.count_links(
            project_id=project_id,
            bot_id=bot_id,
            is_active=is_active,
            buyer_id=buyer_id,
        )
        return [await self._to_read(link, include_total_spend=True) for link in links], total

    async def list_target_funnel_steps(
        self,
        *,
        project_id: UUID,
        bot_id: UUID,
        actor: User,
    ) -> list[TrackingFunnelStepOption]:
        await self._ensure_project_access(actor, project_id)
        await self._get_active_project_or_404(project_id)
        bot = await self.bot_repo.get_by_id_in_project(bot_id, project_id)
        if bot is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found")
        if bot.active_funnel_id is None or bot.active_funnel_version_id is None:
            return []

        result = await self.db.execute(
            select(FunnelStep)
            .join(FunnelVersion, FunnelVersion.id == FunnelStep.funnel_version_id)
            .where(
                FunnelVersion.id == bot.active_funnel_version_id,
                FunnelVersion.funnel_id == bot.active_funnel_id,
            )
            .order_by(FunnelStep.position_y, FunnelStep.position_x, FunnelStep.created_at)
        )
        ordered_steps = list(result.scalars().all())
        return [
            TrackingFunnelStepOption(
                key=step.key,
                title=step.title,
                step_type=step.step_type,
                block_type=step.block_type,
                number=number,
            )
            for number, step in enumerate(ordered_steps, start=1)
            if step.step_type not in {"trigger", "finish"}
        ]

    async def get_tracking_link(self, link_id: UUID, actor: User) -> TrackingLinkRead:
        link = await self._get_link_for_actor(link_id, actor)
        return await self._to_read(link, include_total_spend=True)

    async def create_tracking_link(
        self,
        data: TrackingLinkCreate,
        actor: User,
    ) -> TrackingLinkRead:
        if data.project_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="project_id is required",
            )

        self._validate_cost_configuration(data.cost_model, data.price_per_unit)
        if (
            data.destination_type == "channel"
            and data.cost_model == TrackingCostModel.CPA
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="CPA by submitted lead is not available for channel traffic",
            )
        await self._ensure_project_access(actor, data.project_id)
        project = await self._get_active_project_or_404(data.project_id)
        await self._validate_facebook_event_mappings(
            project_id=project.id,
            mappings=data.fb_event_mappings,
        )
        channel = None
        if data.destination_type == "channel":
            if data.channel_id is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="channel_id is required for channel tracking links",
                )
            channel = await self.channel_service.get_channel(
                channel_id=data.channel_id,
                project_id=project.id,
            )
            bot = channel.tracker_bot
        else:
            if data.bot_id is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="bot_id is required for bot tracking links",
                )
            await self._ensure_bot_supports_tracking(data.bot_id, project.id)
            bot = await self.bot_service.ensure_bot_username(
                bot_id=data.bot_id,
                project_id=project.id,
            )

        title = self._normalize_required(data.title or data.name, "title")
        code = self._normalize_code(data.code or data.ref_code)
        code = code or await self._generate_unique_code(title)
        await self._ensure_code_available(code)

        target_step_id = data.target_step_id
        if channel is not None and (
            target_step_id is not None or data.target_funnel_step_key is not None
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Funnel entry steps are not available for channel traffic",
            )
        if target_step_id is not None:
            await self._ensure_step_belongs_to_bot(target_step_id, bot.id, project.id)
        if channel is None:
            target_funnel_id, target_funnel_step_key = (
                await self._resolve_target_funnel_step(
                    bot_id=bot.id,
                    project_id=project.id,
                    target_funnel_step_key=data.target_funnel_step_key,
                )
            )
        else:
            target_funnel_id, target_funnel_step_key = None, None

        if actor.role_name == RoleName.BUYER:
            buyer_id, buyer_name = actor.id, actor.name
        else:
            buyer_id, buyer_name = await self._resolve_buyer(
                project_id=project.id,
                buyer_id=data.buyer_id,
                buyer_name=data.buyer_name,
            )

        prepared_invite: PreparedChannelInvite | None = None
        if channel is not None:
            if self._normalize_optional(data.invite_link):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Channel invite links are generated by the tracker bot",
                )
            prepared_invite = await self.channel_service.prepare_invite_link(
                channel=channel,
                code=code,
                creates_join_request=True,
            )
            invite_link = prepared_invite.invite_link
        else:
            invite_link = canonicalize_telegram_web_link(
                self._normalize_optional(data.invite_link)
            ) or self._build_invite_link(bot.bot_username, code)
        try:
            link = await self.link_repo.create_link(
                project_id=project.id,
                bot_id=bot.id,
                destination_type=data.destination_type,
                channel_id=channel.id if channel is not None else None,
                channel_join_request=(
                    True if channel is not None else False
                ),
                channel_request_message_enabled=(
                    data.channel_request_message_enabled
                    if channel is not None and data.channel_join_request
                    else False
                ),
                channel_request_message=(
                    self._normalize_optional(data.channel_request_message)
                    if channel is not None and data.channel_join_request
                    else None
                ),
                channel_auto_approve=(
                    data.channel_auto_approve
                    if channel is not None and data.channel_join_request
                    else False
                ),
                name=title,
                title=title,
                ref_code=code,
                code=code,
                buyer_id=buyer_id,
                buyer_name=buyer_name,
                ad_type=self._normalize_optional(data.ad_type),
                payment_type=self._normalize_optional(data.payment_type),
                invite_link=invite_link,
                fb_pixel_id=data.fb_pixel_id,
                fb_capi_token=data.fb_capi_token,
                fb_campaign_enabled=data.fb_campaign_enabled,
                fb_event_mappings_json=[
                    item.model_dump() for item in data.fb_event_mappings
                ],
                fb_proxy_url=data.fb_proxy_url,
                fb_test_event_code=data.fb_test_event_code,
                cost_model=data.cost_model,
                price_per_unit=data.price_per_unit,
                spend=data.spend,
                base_conversion_rate=data.base_conversion_rate,
                min_sample_size=data.min_sample_size,
                target_step_id=target_step_id,
                target_funnel_id=target_funnel_id,
                target_funnel_step_key=target_funnel_step_key,
                created_by_user_id=actor.id,
            )
            link.bot = bot
            link.channel = channel
            if channel is not None and prepared_invite is not None:
                await self.channel_service.persist_invite_link(
                    project_id=project.id,
                    channel_id=channel.id,
                    tracking_link_id=link.id,
                    prepared=prepared_invite,
                )
            await self._create_initial_manual_spend(link, data, actor_id=actor.id)
            await self.db.flush()
        except Exception as exc:
            await self.db.rollback()
            if prepared_invite is not None:
                await self.channel_service.revoke_prepared_invite(
                    prepared=prepared_invite,
                )
            if isinstance(exc, IntegrityError):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Tracking code already exists",
                ) from exc
            raise
        return await self._to_read(link, include_total_spend=True)

    async def _ensure_bot_supports_tracking(
        self,
        bot_id: UUID,
        project_id: UUID,
    ) -> None:
        transport_type = await self.bot_repo.get_transport_type(bot_id, project_id)
        if transport_type is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found")
        if transport_type == "user_mtproto":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Именной Telegram-аккаунт не поддерживает /start-реферальные ссылки. "
                    "Общая статистика по аккаунту доступна без трекинг-ссылки."
                ),
            )

    async def update_tracking_link(
        self,
        link_id: UUID,
        data: TrackingLinkUpdate,
        actor: User,
    ) -> TrackingLinkRead:
        link = await self._get_link_for_actor(link_id, actor)
        prepared_invite: PreparedChannelInvite | None = None
        channel = None
        if (
            "fb_event_mappings" in data.model_fields_set
            and data.fb_event_mappings is not None
        ):
            await self._validate_facebook_event_mappings(
                project_id=link.project_id,
                mappings=data.fb_event_mappings,
            )
        values = self._build_link_update_values(data, link=link, allow_code_update=False)
        values = self._normalize_channel_request_update(link=link, values=values)
        if link.destination_type == "channel":
            values.pop("invite_link", None)
            values.pop("target_step_id", None)
            values.pop("target_funnel_step_key", None)
            desired_join_request = values.get(
                "channel_join_request",
                link.channel_join_request,
            )
            if desired_join_request != link.channel_join_request:
                if link.channel_id is None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Channel tracking link has no channel",
                    )
                channel = await self.channel_service.get_channel(
                    channel_id=link.channel_id,
                    project_id=link.project_id,
                )
        if actor.role_name == RoleName.BUYER:
            values.pop("buyer_id", None)
            values.pop("buyer_name", None)
        if {"cost_model", "price_per_unit"} & values.keys():
            if (
                link.destination_type == "channel"
                and values.get("cost_model", link.cost_model) == TrackingCostModel.CPA
            ):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="CPA by submitted lead is not available for channel traffic",
                )
            self._validate_cost_configuration(
                values.get("cost_model", link.cost_model),
                values.get("price_per_unit", link.price_per_unit),
            )
        if actor.role_name != RoleName.BUYER and "buyer_id" in data.model_fields_set:
            buyer_id, buyer_name = await self._resolve_buyer(
                project_id=link.project_id,
                buyer_id=data.buyer_id,
                buyer_name=data.buyer_name,
            )
            values["buyer_id"] = buyer_id
            values["buyer_name"] = buyer_name
        if "target_step_id" in values and values["target_step_id"] is not None:
            await self._ensure_step_belongs_to_bot(
                values["target_step_id"],
                link.bot_id,
                link.project_id,
            )
        if "target_funnel_step_key" in values:
            target_funnel_id, target_funnel_step_key = await self._resolve_target_funnel_step(
                bot_id=link.bot_id,
                project_id=link.project_id,
                target_funnel_step_key=values["target_funnel_step_key"],
            )
            values["target_funnel_id"] = target_funnel_id
            values["target_funnel_step_key"] = target_funnel_step_key

        if channel is not None:
            prepared_invite = await self.channel_service.prepare_invite_link(
                channel=channel,
                code=link.code,
                creates_join_request=bool(
                    values.get("channel_join_request", link.channel_join_request)
                ),
            )
            values["invite_link"] = prepared_invite.invite_link

        if not values:
            return await self._to_read(link, include_total_spend=True)

        try:
            updated = await self.link_repo.update_link(link.id, **values)
            if updated is not None and prepared_invite is not None and channel is not None:
                await self.channel_service.persist_invite_link(
                    project_id=link.project_id,
                    channel_id=channel.id,
                    tracking_link_id=link.id,
                    prepared=prepared_invite,
                )
            await self.db.flush()
            if updated is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Tracking link not found",
                )
            return await self._to_read(updated, include_total_spend=True)
        except Exception:
            await self.db.rollback()
            if prepared_invite is not None:
                await self.channel_service.revoke_prepared_invite(
                    prepared=prepared_invite,
                )
            raise

    async def set_tracking_link_active(
        self,
        link_id: UUID,
        is_active: bool,
        actor: User,
    ) -> TrackingLinkRead:
        link = await self._get_link_for_actor(link_id, actor)
        updated = await self.link_repo.set_active(link.id, is_active)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tracking link not found",
            )
        return await self._to_read(updated, include_total_spend=True)

    async def list_spends(
        self,
        link_id: UUID,
        actor: User,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[TrackingSpendRead]:
        link = await self._get_link_for_actor(link_id, actor)
        spends = await self.spend_repo.list_spends(
            tracking_link_id=link.id,
            date_from=date_from,
            date_to=date_to,
        )
        return [TrackingSpendRead.model_validate(spend) for spend in spends]

    async def add_spend(
        self,
        link_id: UUID,
        data: TrackingSpendCreate,
        actor: User,
    ) -> TrackingSpendRead:
        link = await self._get_link_for_actor(link_id, actor)
        if link.cost_model != TrackingCostModel.CPM:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Manual spend is available only for the manual budget cost model",
            )
        spend = await self.spend_repo.create_spend(
            tracking_link_id=link.id,
            spend_date=data.spend_date,
            amount=data.amount,
            currency=self._normalize_currency(data.currency),
            comment=self._normalize_optional(data.comment),
            source=TrackingSpendSource.CRM_MANUAL,
            created_by_user_id=actor.id,
        )
        return TrackingSpendRead.model_validate(spend)

    async def update_spend(
        self,
        spend_id: UUID,
        data: TrackingSpendUpdate,
        actor: User,
    ) -> TrackingSpendRead:
        spend = await self._get_spend_for_actor(spend_id, actor)
        values = data.model_dump(exclude_unset=True)
        if "currency" in values:
            values["currency"] = self._normalize_currency(values["currency"])
        if "comment" in values:
            values["comment"] = self._normalize_optional(values["comment"])

        if not values:
            return TrackingSpendRead.model_validate(spend)

        updated = await self.spend_repo.update_spend(spend.id, **values)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tracking spend not found",
            )
        return TrackingSpendRead.model_validate(updated)

    async def delete_spend(self, spend_id: UUID, actor: User) -> None:
        spend = await self._get_spend_for_actor(spend_id, actor)
        deleted = await self.spend_repo.delete_spend(spend.id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tracking spend not found",
            )

    async def _get_link_for_actor(self, link_id: UUID, actor: User) -> TrackingLink:
        link = await self.link_repo.get_link_by_id(link_id)
        if link is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tracking link not found",
            )
        await self._ensure_project_access(actor, link.project_id)
        await self._get_active_project_or_404(link.project_id)
        if actor.role_name == RoleName.BUYER and link.buyer_id != actor.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tracking link not found",
            )
        return link

    async def _get_spend_for_actor(self, spend_id: UUID, actor: User) -> TrackingSpend:
        spend = await self.spend_repo.get_spend_by_id(spend_id)
        if spend is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tracking spend not found",
            )
        link = await self._get_link_for_actor(spend.tracking_link_id, actor)
        if link is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tracking link not found",
            )
        return spend

    async def _ensure_bot_in_project(self, bot_id: UUID, project_id: UUID) -> None:
        bot = await self.bot_repo.get_by_id_in_project(bot_id, project_id)
        if bot is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found")

    async def _ensure_step_belongs_to_bot(
        self,
        step_id: UUID,
        bot_id: UUID,
        project_id: UUID,
    ) -> None:
        belongs = await self.bot_repo.step_belongs_to_bot(
            step_id=step_id,
            bot_id=bot_id,
            project_id=project_id,
        )
        if not belongs:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="target_step_id does not belong to the selected bot",
            )

    async def _resolve_target_funnel_step(
        self,
        *,
        bot_id: UUID,
        project_id: UUID,
        target_funnel_step_key: str | None,
    ) -> tuple[UUID | None, str | None]:
        step_key = self._normalize_optional(target_funnel_step_key)
        if step_key is None:
            return None, None

        bot = await self.bot_repo.get_by_id_in_project(bot_id, project_id)
        if bot is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bot not found")
        if bot.active_funnel_id is None or bot.active_funnel_version_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Configure and publish an active funnel before choosing a target step",
            )

        result = await self.db.execute(
            select(FunnelStep)
            .join(FunnelVersion, FunnelVersion.id == FunnelStep.funnel_version_id)
            .where(
                FunnelVersion.id == bot.active_funnel_version_id,
                FunnelVersion.funnel_id == bot.active_funnel_id,
                FunnelStep.key == step_key,
                FunnelStep.step_type.notin_(("trigger", "finish")),
            )
            .limit(1)
        )
        step = result.scalar_one_or_none()
        if step is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="target_funnel_step_key does not belong to the active funnel",
            )
        return bot.active_funnel_id, step.key

    async def _target_funnel_step_title(self, link: TrackingLink) -> str | None:
        if link.target_funnel_id is None or not link.target_funnel_step_key:
            return None
        bot = link.bot
        if bot is None or bot.active_funnel_version_id is None:
            return None

        result = await self.db.execute(
            select(FunnelStep.title)
            .join(FunnelVersion, FunnelVersion.id == FunnelStep.funnel_version_id)
            .where(
                FunnelVersion.id == bot.active_funnel_version_id,
                FunnelVersion.funnel_id == link.target_funnel_id,
                FunnelStep.key == link.target_funnel_step_key,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _get_active_project_or_404(self, project_id: UUID):
        project = await self.project_repo.get_any_by_id(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        if project.is_deleted or project.status == "archived":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Project is archived",
            )
        return project

    @staticmethod
    async def _ensure_project_access(actor: User, project_id: UUID) -> None:
        require_project_access(actor, project_id)

    async def _ensure_code_available(
        self,
        code: str,
        exclude_id: UUID | None = None,
    ) -> None:
        existing = await self.link_repo.get_link_by_code(code)
        if existing is not None and existing.id != exclude_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Tracking code already exists",
            )
        existing_legacy = await self.link_repo.get_by_ref_code(code)
        if existing_legacy is not None and existing_legacy.id != exclude_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Tracking code already exists",
            )

    async def _generate_unique_code(self, title: str) -> str:
        base = self._slugify_code(title)[:48].strip("-_") or "link"
        for _ in range(8):
            suffix = secrets.token_hex(3)
            code = f"{base}-{suffix}"
            if await self.link_repo.get_link_by_code(code) is None:
                if await self.link_repo.get_by_ref_code(code) is None:
                    return code

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate a unique tracking code",
        )

    def _build_link_update_values(
        self,
        data: TrackingLinkUpdate,
        *,
        link: TrackingLink,
        allow_code_update: bool,
    ) -> dict:
        values = data.model_dump(exclude_unset=True)

        if "title" in values:
            title = self._normalize_required(values.pop("title"), "title")
            values["title"] = title
            values["name"] = title
        if "name" in values:
            title = self._normalize_required(values.pop("name"), "name")
            values["name"] = title
            values["title"] = title

        code_value = values.pop("code", None) if "code" in values else None
        ref_code_value = (
            values.pop("ref_code", None) if "ref_code" in values else None
        )
        if code_value is not None or ref_code_value is not None:
            if not allow_code_update:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Tracking code cannot be changed through v1 update",
                )
            code = self._normalize_code(code_value or ref_code_value, required=True)
            if code != link.code:
                values["code"] = code
                values["ref_code"] = code

        if "fb_event_mappings" in values:
            raw_mappings = values.pop("fb_event_mappings")
            values["fb_event_mappings_json"] = [
                item.model_dump() if hasattr(item, "model_dump") else dict(item)
                for item in (raw_mappings or [])
            ]

        for field in (
            "buyer_name",
            "ad_type",
            "payment_type",
            "invite_link",
            "fb_pixel_id",
            "fb_capi_token",
            "fb_proxy_url",
            "fb_test_event_code",
        ):
            if field in values:
                values[field] = self._normalize_optional(values[field])

        if "invite_link" in values:
            values["invite_link"] = canonicalize_telegram_web_link(
                values["invite_link"]
            )

        return values

    def _normalize_channel_request_update(
        self,
        *,
        link: TrackingLink,
        values: dict,
    ) -> dict:
        fields = {
            "channel_join_request",
            "channel_request_message_enabled",
            "channel_request_message",
            "channel_auto_approve",
        }
        if link.destination_type != "channel":
            if any(values.get(field) for field in fields):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Channel request options require a channel tracking link",
                )
            for field in fields:
                values.pop(field, None)
            return values

        join_request = bool(
            values.get("channel_join_request", link.channel_join_request)
        )
        message_enabled = bool(
            values.get(
                "channel_request_message_enabled",
                link.channel_request_message_enabled,
            )
        )
        message = self._normalize_optional(
            values.get(
                "channel_request_message",
                link.channel_request_message,
            )
        )
        if not join_request:
            values["channel_request_message_enabled"] = False
            values["channel_request_message"] = None
            values["channel_auto_approve"] = False
            return values
        if message_enabled and not message:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Set a join-request message before enabling automatic messaging"
                ),
            )
        if "channel_request_message" in values:
            values["channel_request_message"] = message
        return values

    async def _resolve_buyer(
        self,
        *,
        project_id: UUID,
        buyer_id: UUID | None,
        buyer_name: str | None,
    ) -> tuple[UUID | None, str | None]:
        if buyer_id is None:
            return None, self._normalize_optional(buyer_name)

        project_user_ids = select(UserProjectAccess.user_id).where(
            UserProjectAccess.project_id == project_id
        )
        linked_buyer_ids = select(TrackingLink.buyer_id).where(
            TrackingLink.project_id == project_id,
            TrackingLink.buyer_id.is_not(None),
        )
        result = await self.db.execute(
            select(User).where(
                User.id == buyer_id,
                User.is_deleted.is_(False),
                or_(User.project_id == project_id, User.id.in_(project_user_ids)),
                or_(
                    User.buyer_telegram_id.is_not(None),
                    User.buyer_invite_token.is_not(None),
                    User.id.in_(linked_buyer_ids),
                ),
            )
        )
        buyer = result.scalar_one_or_none()
        if buyer is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Buyer is not available in this project",
            )
        return buyer.id, buyer.name

    async def _validate_facebook_event_mappings(
        self,
        *,
        project_id: UUID,
        mappings: object,
    ) -> None:
        try:
            await FacebookCampaignService(self.db).validate_mapping_triggers(
                project_id=project_id,
                mappings=mappings,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

    async def _create_initial_manual_spend(
        self,
        link: TrackingLink,
        data: TrackingLinkCreate,
        *,
        actor_id: UUID | None,
    ) -> None:
        if data.cost_model != TrackingCostModel.CPM or Decimal(data.spend or 0) <= 0:
            return
        await self.spend_repo.create_spend(
            tracking_link_id=link.id,
            spend_date=date.today(),
            amount=data.spend,
            currency="USD",
            comment="Начальный рекламный бюджет из настроек tracking link",
            source=TrackingSpendSource.CRM_MANUAL,
            created_by_user_id=actor_id,
        )

    @staticmethod
    def _random_ref_code() -> str:
        alphabet = string.ascii_letters + string.digits + "_-"
        return "".join(secrets.choice(alphabet) for _ in range(10))

    @classmethod
    async def _generate_unique_ref_code(cls) -> str:
        # Kept for compatibility with tests or callers that used the old helper.
        return cls._random_ref_code()

    @staticmethod
    def _normalize_required(value: str | None, field_name: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field_name} must not be empty",
            )
        return normalized

    @staticmethod
    def _normalize_optional(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def _validate_cost_configuration(
        cost_model: TrackingCostModel | str,
        price_per_unit: Decimal,
    ) -> None:
        model = TrackingCostModel(cost_model)
        if model in {TrackingCostModel.FIX_PDP, TrackingCostModel.CPA}:
            if Decimal(price_per_unit or 0) <= 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="price_per_unit must be greater than zero for unit cost models",
                )

    @classmethod
    def _normalize_code(
        cls,
        value: str | None,
        *,
        required: bool = False,
    ) -> str | None:
        if value is None:
            if required:
                return cls._normalize_required(value, "code")
            return None

        normalized = cls._normalize_required(value, "code").lower()
        normalized = re.sub(r"\s+", "-", normalized)
        normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
        if any(char not in string.ascii_lowercase + string.digits + "_-" for char in normalized):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="code may contain only lowercase letters, digits, underscore, and dash",
            )
        if len(normalized) > 64:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="code must be 64 characters or fewer",
            )
        return normalized

    @staticmethod
    def _slugify_code(value: str) -> str:
        ascii_value = (
            unicodedata.normalize("NFKD", value)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
        slug = re.sub(r"[^a-z0-9_]+", "-", ascii_value.lower())
        slug = re.sub(r"-{2,}", "-", slug).strip("-")
        return slug or "link"

    @staticmethod
    def _normalize_currency(value: str | None) -> str:
        currency = (value or "USD").strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="currency must be a 3-letter ISO code",
            )
        return currency

    @staticmethod
    def _build_invite_link(bot_username: str | None, code: str) -> str | None:
        username = (bot_username or "").removeprefix("@")
        if not username:
            return None
        return build_telegram_bot_start_link(username, code)

    @classmethod
    def _to_out(cls, link: TrackingLink) -> TrackingLinkOut:
        username = (link.bot.bot_username or "").removeprefix("@")
        ref_code = link.ref_code or link.code
        invite_link = canonicalize_telegram_web_link(link.invite_link)
        if not invite_link and link.destination_type == "bot":
            invite_link = cls._build_invite_link(username, ref_code)
        return TrackingLinkOut.model_validate(link).model_copy(
            update={
                "invite_link": invite_link,
                "tracking_url": cls._public_tracking_url(
                    destination_type=link.destination_type,
                    code=ref_code,
                    bot_username=username,
                    invite_link=invite_link,
                ),
                "channel_title": (
                    link.channel.title if link.channel is not None else None
                ),
                "has_fb_capi_token": bool((link.fb_capi_token or "").strip()),
                "has_fb_proxy": bool((link.fb_proxy_url or "").strip()),
                "fb_event_mappings_json": normalize_facebook_event_mappings(
                    link.fb_event_mappings_json
                ),
            }
        )

    async def _to_read(
        self,
        link: TrackingLink,
        *,
        include_total_spend: bool = False,
    ) -> TrackingLinkRead:
        code = link.code or link.ref_code
        title = link.title or link.name
        invite_link = canonicalize_telegram_web_link(
            link.invite_link
        )
        if not invite_link and link.destination_type == "bot":
            invite_link = self._build_invite_link(
                getattr(link.bot, "bot_username", None),
                code,
            )
        total_spend: Decimal | None = None
        if include_total_spend:
            total_spend = await TrackingMetricsRepository(
                self.db
            ).aggregate_spend_by_link(
                link_id=link.id,
                date_from=link.created_at.date(),
                date_to=date.today(),
            )

        return TrackingLinkRead(
            id=link.id,
            project_id=link.project_id,
            bot_id=link.bot_id,
            destination_type=link.destination_type,
            channel_id=link.channel_id,
            channel_title=(link.channel.title if link.channel is not None else None),
            channel_join_request=link.channel_join_request,
            channel_request_message_enabled=link.channel_request_message_enabled,
            channel_request_message=link.channel_request_message,
            channel_auto_approve=link.channel_auto_approve,
            code=code,
            title=title,
            buyer_id=link.buyer_id,
            buyer_name=link.buyer_name,
            ad_type=link.ad_type,
            payment_type=link.payment_type,
            invite_link=invite_link,
            tracking_url=self._public_tracking_url(
                destination_type=link.destination_type,
                code=code,
                bot_username=getattr(link.bot, "bot_username", None),
                invite_link=invite_link,
            ),
            is_active=link.is_active,
            created_by_user_id=link.created_by_user_id,
            created_at=link.created_at,
            updated_at=link.updated_at,
            cost_model=link.cost_model,
            price_per_unit=link.price_per_unit,
            spend=link.spend,
            base_conversion_rate=link.base_conversion_rate,
            min_sample_size=link.min_sample_size,
            target_funnel_id=link.target_funnel_id,
            target_funnel_step_key=link.target_funnel_step_key,
            target_funnel_step_title=await self._target_funnel_step_title(link),
            fb_pixel_id=link.fb_pixel_id,
            has_fb_capi_token=bool((link.fb_capi_token or "").strip()),
            fb_campaign_enabled=link.fb_campaign_enabled,
            fb_event_mappings_json=normalize_facebook_event_mappings(
                link.fb_event_mappings_json
            ),
            has_fb_proxy=bool((link.fb_proxy_url or "").strip()),
            fb_test_event_code=link.fb_test_event_code,
            total_spend=total_spend,
        )

    @staticmethod
    def _public_tracking_url(
        *,
        destination_type: str,
        code: str,
        bot_username: str | None,
        invite_link: str | None,
    ) -> str | None:
        if destination_type == "channel":
            technical_host = str(settings.LANDER_TECH_DOMAIN or "").strip()
            if technical_host:
                return build_channel_tracking_url(host=technical_host, code=code)
            base_url = str(settings.BASE_URL or "").strip().rstrip("/")
            return f"{base_url}/join/{quote(code, safe='')}" if base_url else invite_link
        username = str(bot_username or "").removeprefix("@").strip()
        return build_telegram_bot_start_link(username, code) if username else invite_link
