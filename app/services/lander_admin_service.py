from __future__ import annotations

import asyncio
import re
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.constants import RoleName
from app.core.facebook_events import normalize_facebook_event_mappings
from app.core.lander_urls import (
    build_lander_public_url,
    effective_campaign_utm_defaults,
)
from app.models.lander import ProjectDomain, ProjectLander
from app.models.lead_status import LeadStatus
from app.models.tag import Tag
from app.models.tracking import TrackingLink
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.schemas.lander import (
    LanderFacebookCampaignOut,
    ProjectDomainCreate,
    ProjectDomainOut,
    ProjectLanderCreate,
    LanderRuntimeConfigOut,
    ProjectLanderOut,
    ProjectLanderUpdate,
)
from app.services.access_control import require_project_access
from app.services.domain_dns_service import DomainDnsService
from app.schemas.tracking import TrackingLinkCreate
from app.services.tracking_service import TrackingService
from app.services.channel_tracking_service import (
    ChannelTrackingService,
    PreparedChannelInvite,
)


class LanderAdminService:
    LANDER_TYPES = {"default_tg_redirect", "custom_upload"}
    SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.project_repo = ProjectRepository(db)

    async def list_domains(
        self,
        *,
        project_id: UUID,
        actor: User,
    ) -> list[ProjectDomainOut]:
        await self._ensure_lander_project_access(actor=actor, project_id=project_id)
        result = await self.db.execute(
            select(ProjectDomain)
            .where(
                ProjectDomain.project_id == project_id,
                ProjectDomain.is_active.is_(True),
            )
            .order_by(ProjectDomain.created_at.desc())
        )
        domains = list(result.scalars().all())
        return list(
            await asyncio.gather(*(self._to_domain_out(domain) for domain in domains))
        )

    async def create_domain(
        self,
        *,
        project_id: UUID,
        data: ProjectDomainCreate,
        actor: User,
    ) -> ProjectDomainOut:
        await self._ensure_admin_project_access(actor=actor, project_id=project_id)
        domain_name = data.domain_name
        existing_result = await self.db.execute(
            select(ProjectDomain).where(ProjectDomain.domain_name == domain_name)
        )
        existing = existing_result.scalar_one_or_none()
        if existing is not None and existing.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Domain already exists",
            )
        if existing is not None:
            existing.is_active = True
            await self.db.flush()
            await self.db.refresh(existing)
            return ProjectDomainOut.model_validate(existing)

        domain = ProjectDomain(project_id=project_id, domain_name=domain_name)
        self.db.add(domain)
        await self.db.flush()
        await self.db.refresh(domain)
        return ProjectDomainOut.model_validate(domain)

    async def delete_domain(
        self,
        *,
        project_id: UUID,
        domain_id: UUID,
        actor: User,
    ) -> None:
        await self._ensure_admin_project_access(actor=actor, project_id=project_id)
        result = await self.db.execute(
            select(ProjectDomain).where(
                ProjectDomain.id == domain_id,
                ProjectDomain.project_id == project_id,
                ProjectDomain.is_active.is_(True),
            )
        )
        domain = result.scalar_one_or_none()
        if domain is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Domain not found",
            )
        await self.db.execute(
            update(ProjectLander)
            .where(
                ProjectLander.project_id == project_id,
                ProjectLander.domain_id == domain.id,
            )
            .values(domain_id=None, updated_at=func.now())
        )
        domain.is_active = False
        await self.db.flush()

    async def list_landers(
        self,
        *,
        project_id: UUID,
        actor: User,
    ) -> list[ProjectLanderOut]:
        await self._ensure_lander_project_access(actor=actor, project_id=project_id)
        statement = (
            select(ProjectLander)
            .options(
                selectinload(ProjectLander.domain),
                selectinload(ProjectLander.tracking_link).selectinload(TrackingLink.bot),
                selectinload(ProjectLander.tracking_link).selectinload(TrackingLink.channel),
            )
            .where(ProjectLander.project_id == project_id)
            .order_by(ProjectLander.created_at.desc())
        )
        if actor.role_name == RoleName.BUYER:
            statement = statement.join(
                TrackingLink,
                TrackingLink.id == ProjectLander.tracking_link_id,
            ).where(TrackingLink.buyer_id == actor.id)
        result = await self.db.execute(statement)
        return [self._to_lander_out(item) for item in result.scalars().all()]

    async def get_runtime_config(
        self,
        *,
        project_id: UUID,
        actor: User,
    ) -> LanderRuntimeConfigOut:
        await self._ensure_lander_project_access(actor=actor, project_id=project_id)
        statuses_result = await self.db.execute(
            select(LeadStatus).order_by(LeadStatus.sort_order.asc())
        )
        tags_result = await self.db.execute(
            select(Tag)
            .where(Tag.project_id == project_id)
            .order_by(Tag.name.asc(), Tag.created_at.desc())
        )
        return LanderRuntimeConfigOut(
            technical_domain=self._technical_domain(),
            lead_statuses=[
                {
                    "id": item.id,
                    "code": item.code,
                    "name": item.name,
                }
                for item in statuses_result.scalars().all()
            ],
            tags=[
                {
                    "id": item.id,
                    "name": item.name,
                    "color": item.color,
                }
                for item in tags_result.scalars().all()
            ],
        )

    async def create_lander(
        self,
        *,
        project_id: UUID,
        data: ProjectLanderCreate,
        actor: User,
    ) -> ProjectLanderOut:
        await self._ensure_lander_project_access(actor=actor, project_id=project_id)
        if actor.role_name == RoleName.BUYER and (
            data.campaign is None or data.tracking_link_id is not None
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Buyers can only create a new campaign with its own tracking link",
            )
        lander_type = self._validate_lander_type(data.type)
        slug = self._validate_slug(data.slug)
        if await self._slug_exists(slug):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Lander slug already exists",
            )
        if data.domain_id is not None:
            await self._ensure_domain_belongs_to_project(data.domain_id, project_id)
        else:
            self._technical_domain()
        tracking_link_id = data.tracking_link_id
        tracking_link = None
        campaign_tracking_code: str | None = None
        if tracking_link_id is not None:
            await self._ensure_tracking_link_belongs_to_project(tracking_link_id, project_id)
        elif data.campaign is not None:
            campaign = data.campaign
            fb_pixel_id = campaign.fb_pixel_id
            fb_capi_token = campaign.fb_capi_token
            if actor.role_name == RoleName.BUYER:
                fb_pixel_id = fb_pixel_id or actor.buyer_fb_pixel_id
                fb_capi_token = fb_capi_token or actor.buyer_fb_capi_token
                if not fb_pixel_id or not fb_capi_token:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=(
                            "Configure Facebook Pixel ID and CAPI token in the buyer bot "
                            "or enter them in the campaign form"
                        ),
                    )
            tracking_link = await TrackingService(self.db).create_tracking_link(
                data=TrackingLinkCreate(
                    project_id=project_id,
                    bot_id=campaign.bot_id,
                    destination_type=campaign.destination_type,
                    channel_id=campaign.channel_id,
                    channel_join_request=campaign.channel_join_request,
                    title=campaign.title,
                    code=campaign.code,
                    buyer_id=campaign.buyer_id,
                    buyer_name=campaign.buyer_name,
                    ad_type=campaign.ad_type,
                    payment_type=campaign.payment_type,
                    fb_pixel_id=fb_pixel_id,
                    fb_capi_token=fb_capi_token,
                    fb_campaign_enabled=True,
                    fb_event_mappings=campaign.fb_event_mappings,
                    fb_proxy_url=campaign.fb_proxy_url,
                    fb_test_event_code=campaign.fb_test_event_code,
                    base_conversion_rate=campaign.base_conversion_rate,
                    min_sample_size=campaign.min_sample_size,
                    target_funnel_step_key=campaign.target_funnel_step_key,
                ),
                actor=actor,
            )
            tracking_link_id = tracking_link.id
            campaign_tracking_code = tracking_link.code

        campaign_pixel_id = (
            tracking_link.fb_pixel_id
            if data.campaign is not None and tracking_link is not None
            else None
        )
        pixels_json = [pixel.model_dump() for pixel in data.pixels]
        if campaign_pixel_id and not pixels_json:
            pixels_json = [{"provider": "meta", "pixel_id": campaign_pixel_id}]

        lander = ProjectLander(
            project_id=project_id,
            domain_id=data.domain_id,
            name=data.name,
            type=lander_type,
            slug=slug,
            description=data.description,
            button_text=data.button_text,
            tracking_link_id=tracking_link_id,
            pixels_json=pixels_json,
            meta_events_json=[event.model_dump() for event in data.meta_events],
            utm_defaults_json=effective_campaign_utm_defaults(
                data.utm_defaults,
                tracking_code=campaign_tracking_code,
                is_facebook_campaign=data.campaign is not None,
            ),
            auto_redirect_enabled=data.auto_redirect_enabled,
        )
        self.db.add(lander)
        await self.db.flush()
        return self._to_lander_out(
            await self._get_lander(lander_id=lander.id, project_id=project_id)
        )

    async def update_lander(
        self,
        *,
        project_id: UUID,
        lander_id: UUID,
        data: ProjectLanderUpdate,
        actor: User,
    ) -> ProjectLanderOut:
        await self._ensure_lander_project_access(actor=actor, project_id=project_id)
        lander = await self._get_lander(lander_id=lander_id, project_id=project_id)
        self._ensure_buyer_owns_lander(actor=actor, lander=lander)

        validated_slug: str | None = None
        validated_lander_type: str | None = None
        if "domain_id" in data.model_fields_set:
            if data.domain_id is not None:
                await self._ensure_domain_belongs_to_project(data.domain_id, project_id)
            else:
                self._technical_domain()
        if "slug" in data.model_fields_set and data.slug is not None:
            validated_slug = self._validate_slug(data.slug)
            if await self._slug_exists(validated_slug, exclude_id=lander.id):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Lander slug already exists",
                )
        if "type" in data.model_fields_set and data.type is not None:
            validated_lander_type = self._validate_lander_type(data.type)
            if validated_lander_type == "custom_upload" and not lander.custom_html_path:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Upload a ZIP archive before enabling custom_upload",
                )

        prepared_invite: PreparedChannelInvite | None = None
        prepared_channel_id: UUID | None = None
        prepared_tracking_link_id: UUID | None = None
        campaign_pixels_json: list[dict] | None = None
        if data.facebook_campaign is not None:
            if lander.tracking_link is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Lander is not attached to a tracking link",
                )
            campaign = data.facebook_campaign
            link = lander.tracking_link
            tracking_service = TrackingService(self.db)
            await tracking_service._validate_facebook_event_mappings(
                project_id=project_id,
                mappings=campaign.fb_event_mappings,
            )
            desired_destination = (
                campaign.destination_type
                if "destination_type" in campaign.model_fields_set
                and campaign.destination_type is not None
                else link.destination_type
            )
            channel = None
            bot = link.bot
            bot_changed = False
            channel_changed = False
            join_request_changed = False
            desired_code = link.code
            code_changed = False
            if "code" in campaign.model_fields_set and campaign.code is not None:
                desired_code = tracking_service._normalize_code(
                    campaign.code,
                    required=True,
                )
                if desired_code != link.code:
                    await tracking_service._ensure_code_available(
                        desired_code,
                        exclude_id=link.id,
                    )
                    code_changed = True
            if desired_destination == "channel":
                channel_id = (
                    campaign.channel_id
                    if "channel_id" in campaign.model_fields_set
                    else link.channel_id
                )
                if channel_id is None:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="Choose a Telegram channel for channel traffic",
                    )
                channel = await tracking_service.channel_service.get_channel(
                    channel_id=channel_id,
                    project_id=project_id,
                )
                bot = channel.tracker_bot
                channel_changed = (
                    link.destination_type != "channel" or link.channel_id != channel.id
                )
                desired_join_request = (
                    campaign.channel_join_request
                    if "channel_join_request" in campaign.model_fields_set
                    and campaign.channel_join_request is not None
                    else link.channel_join_request
                )
                join_request_changed = desired_join_request != link.channel_join_request
                if channel_changed or join_request_changed:
                    prepared_invite = (
                        await tracking_service.channel_service.prepare_invite_link(
                            channel=channel,
                            code=desired_code,
                            creates_join_request=desired_join_request,
                        )
                    )
                    prepared_channel_id = channel.id
                    prepared_tracking_link_id = link.id
                bot_changed = bot.id != link.bot_id
                link.destination_type = "channel"
                link.channel_id = channel.id
                link.channel = channel
                link.channel_join_request = desired_join_request
                link.bot_id = bot.id
                link.bot = bot
                link.target_step_id = None
                link.target_funnel_id = None
                link.target_funnel_step_key = None
            else:
                requested_bot_id = (
                    campaign.bot_id
                    if "bot_id" in campaign.model_fields_set
                    else link.bot_id
                )
                if requested_bot_id is None:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="Choose a Telegram bot for bot traffic",
                    )
                bot = await tracking_service.bot_service.ensure_bot_username(
                    bot_id=requested_bot_id,
                    project_id=project_id,
                )
                bot_changed = bot.id != link.bot_id
                was_channel = link.destination_type == "channel"
                link.destination_type = "bot"
                link.channel_id = None
                link.channel = None
                link.channel_join_request = False
                link.bot_id = bot.id
                link.bot = bot
                link.target_step_id = None
                if was_channel:
                    await tracking_service.channel_service.mark_invites_not_current(
                        link.id
                    )
            if code_changed:
                link.code = desired_code
                link.ref_code = desired_code
            if "title" in campaign.model_fields_set and campaign.title is not None:
                link.title = campaign.title
                link.name = campaign.title
            if (
                actor.role_name != RoleName.BUYER
                and "buyer_name" in campaign.model_fields_set
            ):
                link.buyer_name = tracking_service._normalize_optional(campaign.buyer_name)
            if "ad_type" in campaign.model_fields_set:
                link.ad_type = tracking_service._normalize_optional(campaign.ad_type)
            if "payment_type" in campaign.model_fields_set:
                link.payment_type = tracking_service._normalize_optional(campaign.payment_type)
            if (
                "base_conversion_rate" in campaign.model_fields_set
                and campaign.base_conversion_rate is not None
            ):
                link.base_conversion_rate = campaign.base_conversion_rate
            if (
                "min_sample_size" in campaign.model_fields_set
                and campaign.min_sample_size is not None
            ):
                link.min_sample_size = campaign.min_sample_size
            if (
                desired_destination == "bot"
                and "target_funnel_step_key" in campaign.model_fields_set
            ):
                target_funnel_id, target_step_key = (
                    await tracking_service._resolve_target_funnel_step(
                        bot_id=link.bot_id,
                        project_id=project_id,
                        target_funnel_step_key=campaign.target_funnel_step_key,
                    )
                )
                link.target_funnel_id = target_funnel_id
                link.target_funnel_step_key = target_step_key
            elif desired_destination == "bot" and bot_changed:
                link.target_funnel_id = None
                link.target_funnel_step_key = None
            if desired_destination == "bot" and bot is not None and (
                bot_changed or code_changed or link.invite_link is None
            ):
                link.invite_link = tracking_service._build_invite_link(
                    bot.bot_username,
                    link.code,
                )
            elif prepared_invite is not None and channel is not None:
                link.invite_link = prepared_invite.invite_link
            link.fb_campaign_enabled = campaign.enabled
            link.fb_pixel_id = campaign.fb_pixel_id
            link.fb_event_mappings_json = [
                mapping.model_dump() for mapping in campaign.fb_event_mappings
            ]
            link.fb_test_event_code = campaign.fb_test_event_code
            if campaign.fb_capi_token is not None:
                link.fb_capi_token = campaign.fb_capi_token
            elif campaign.clear_fb_capi_token:
                link.fb_capi_token = None
            if campaign.fb_proxy_url is not None:
                link.fb_proxy_url = campaign.fb_proxy_url
            elif campaign.clear_fb_proxy_url:
                link.fb_proxy_url = None
            campaign_pixels_json = (
                [{"provider": "meta", "pixel_id": campaign.fb_pixel_id}]
                if campaign.fb_pixel_id
                else []
            )

        if "domain_id" in data.model_fields_set:
            lander.domain_id = data.domain_id
        if "name" in data.model_fields_set and data.name is not None:
            lander.name = data.name
        if validated_slug is not None:
            lander.slug = validated_slug
        if "description" in data.model_fields_set:
            lander.description = data.description
        if "button_text" in data.model_fields_set:
            lander.button_text = data.button_text
        if validated_lander_type is not None:
            lander.type = validated_lander_type
        if "pixels" in data.model_fields_set and data.pixels is not None:
            lander.pixels_json = [pixel.model_dump() for pixel in data.pixels]
        if campaign_pixels_json is not None:
            lander.pixels_json = campaign_pixels_json
        if "meta_events" in data.model_fields_set and data.meta_events is not None:
            lander.meta_events_json = [event.model_dump() for event in data.meta_events]
        if "utm_defaults" in data.model_fields_set and data.utm_defaults is not None:
            lander.utm_defaults_json = data.utm_defaults
        if (
            "auto_redirect_enabled" in data.model_fields_set
            and data.auto_redirect_enabled is not None
        ):
            lander.auto_redirect_enabled = data.auto_redirect_enabled

        try:
            if (
                prepared_invite is not None
                and prepared_channel_id is not None
                and prepared_tracking_link_id is not None
            ):
                await ChannelTrackingService(self.db).persist_invite_link(
                    project_id=project_id,
                    channel_id=prepared_channel_id,
                    tracking_link_id=prepared_tracking_link_id,
                    prepared=prepared_invite,
                )
            await self.db.flush()
        except Exception:
            await self.db.rollback()
            if prepared_invite is not None:
                await ChannelTrackingService(self.db).revoke_prepared_invite(
                    prepared=prepared_invite,
                )
            raise
        return self._to_lander_out(
            await self._get_lander(lander_id=lander.id, project_id=project_id)
        )

    async def delete_lander(
        self,
        *,
        project_id: UUID,
        lander_id: UUID,
        actor: User,
    ) -> None:
        await self._ensure_lander_project_access(actor=actor, project_id=project_id)
        lander = await self._get_lander(lander_id=lander_id, project_id=project_id)
        self._ensure_buyer_owns_lander(actor=actor, lander=lander)
        tracking_link = lander.tracking_link
        other_landers_count = 0
        if tracking_link is not None:
            count_result = await self.db.execute(
                select(func.count(ProjectLander.id)).where(
                    ProjectLander.tracking_link_id == tracking_link.id,
                    ProjectLander.id != lander.id,
                )
            )
            other_landers_count = int(count_result.scalar_one())
        result = await self.db.execute(
            delete(ProjectLander).where(
                ProjectLander.id == lander_id,
                ProjectLander.project_id == project_id,
            )
        )
        if result.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lander not found",
            )
        if (
            tracking_link is not None
            and tracking_link.fb_campaign_enabled
            and other_landers_count == 0
        ):
            tracking_link.is_active = False
            tracking_link.fb_campaign_enabled = False

    async def ensure_upload_access(
        self,
        *,
        project_id: UUID,
        lander_id: UUID,
        actor: User,
    ) -> None:
        await self._ensure_lander_project_access(actor=actor, project_id=project_id)
        lander = await self._get_lander(lander_id=lander_id, project_id=project_id)
        self._ensure_buyer_owns_lander(actor=actor, lander=lander)

    async def _ensure_admin_project_access(
        self,
        *,
        actor: User,
        project_id: UUID,
    ) -> None:
        if actor.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admin/super_admin can manage landers",
            )
        await self._ensure_active_project_access(actor=actor, project_id=project_id)

    async def _ensure_lander_project_access(
        self,
        *,
        actor: User,
        project_id: UUID,
    ) -> None:
        if actor.role_name not in {
            RoleName.SUPER_ADMIN,
            RoleName.ADMIN,
            RoleName.BUYER,
        }:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Current user cannot manage Facebook campaigns",
            )
        await self._ensure_active_project_access(actor=actor, project_id=project_id)

    async def _ensure_active_project_access(
        self,
        *,
        actor: User,
        project_id: UUID,
    ) -> None:
        require_project_access(actor, project_id)
        project = await self.project_repo.get_active(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

    @staticmethod
    def _ensure_buyer_owns_lander(*, actor: User, lander: ProjectLander) -> None:
        if actor.role_name != RoleName.BUYER:
            return
        if lander.tracking_link is None or lander.tracking_link.buyer_id != actor.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lander not found",
            )

    async def _slug_exists(self, slug: str, exclude_id: UUID | None = None) -> bool:
        statement = select(func.count(ProjectLander.id)).where(ProjectLander.slug == slug)
        if exclude_id is not None:
            statement = statement.where(ProjectLander.id != exclude_id)
        result = await self.db.execute(statement)
        return result.scalar_one() > 0

    async def _ensure_domain_belongs_to_project(
        self,
        domain_id: UUID,
        project_id: UUID,
    ) -> None:
        result = await self.db.execute(
            select(ProjectDomain.id).where(
                ProjectDomain.id == domain_id,
                ProjectDomain.project_id == project_id,
                ProjectDomain.is_active.is_(True),
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Domain does not belong to project",
            )

    async def _ensure_tracking_link_belongs_to_project(
        self,
        tracking_link_id: UUID,
        project_id: UUID,
    ) -> None:
        result = await self.db.execute(
            select(TrackingLink.id).where(
                TrackingLink.id == tracking_link_id,
                TrackingLink.project_id == project_id,
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Tracking link does not belong to project",
            )

    async def _get_lander(self, *, lander_id: UUID, project_id: UUID) -> ProjectLander:
        result = await self.db.execute(
            select(ProjectLander)
            .options(
                selectinload(ProjectLander.domain),
                selectinload(ProjectLander.tracking_link).selectinload(TrackingLink.bot),
                selectinload(ProjectLander.tracking_link).selectinload(TrackingLink.channel),
            )
            .execution_options(populate_existing=True)
            .where(
                ProjectLander.id == lander_id,
                ProjectLander.project_id == project_id,
            )
        )
        lander = result.scalar_one_or_none()
        if lander is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lander not found",
            )
        return lander

    @staticmethod
    def _technical_domain() -> str:
        domain = (settings.LANDER_TECH_DOMAIN or "").strip().lower().rstrip(".")
        if not domain:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="LANDER_TECH_DOMAIN is not configured",
            )
        return domain

    def _to_lander_out(self, lander: ProjectLander) -> ProjectLanderOut:
        domain_name = lander.domain.domain_name if lander.domain is not None else None
        public_host = domain_name or self._technical_domain()
        link = lander.tracking_link
        effective_utm_defaults = effective_campaign_utm_defaults(
            lander.utm_defaults_json,
            tracking_code=link.code if link is not None else None,
            is_facebook_campaign=bool(link is not None and link.fb_campaign_enabled),
        )
        return ProjectLanderOut.model_validate(lander).model_copy(
            update={
                "domain_name": domain_name,
                "public_url": build_lander_public_url(
                    host=public_host,
                    slug=lander.slug,
                    utm_defaults=effective_utm_defaults,
                ),
                "utm_defaults_json": effective_utm_defaults,
                "facebook_campaign_enabled": bool(
                    link is not None and link.fb_campaign_enabled
                ),
                "destination_type": (
                    link.destination_type if link is not None else "bot"
                ),
                "channel_id": link.channel_id if link is not None else None,
                "channel_title": (
                    link.channel.title
                    if link is not None and link.channel is not None
                    else None
                ),
                "fb_pixel_id": link.fb_pixel_id if link is not None else None,
                "has_fb_capi_token": bool(
                    link is not None and (link.fb_capi_token or "").strip()
                ),
                "has_fb_proxy": bool(
                    link is not None and (link.fb_proxy_url or "").strip()
                ),
                "fb_test_event_code": (
                    link.fb_test_event_code if link is not None else None
                ),
                "fb_event_mappings_json": list(
                    normalize_facebook_event_mappings(link.fb_event_mappings_json)
                    if link is not None
                    else []
                ),
                "facebook_campaign": (
                    LanderFacebookCampaignOut(
                        bot_id=link.bot_id,
                        destination_type=link.destination_type,
                        channel_id=link.channel_id,
                        channel_title=(
                            link.channel.title if link.channel is not None else None
                        ),
                        channel_join_request=link.channel_join_request,
                        title=link.title,
                        code=link.code,
                        buyer_name=link.buyer_name,
                        ad_type=link.ad_type,
                        payment_type=link.payment_type,
                        base_conversion_rate=link.base_conversion_rate,
                        min_sample_size=link.min_sample_size,
                        target_funnel_step_key=link.target_funnel_step_key,
                    )
                    if link is not None
                    else None
                ),
            }
        )

    async def _to_domain_out(self, domain: ProjectDomain) -> ProjectDomainOut:
        checker = DomainDnsService(
            technical_domain=self._technical_domain()
        )
        cname_check, routing_check = await asyncio.gather(
            checker.check_cname(domain.domain_name),
            checker.check_routing(domain.domain_name),
        )
        return ProjectDomainOut.model_validate(domain).model_copy(
            update={
                "cname_verified": cname_check.verified,
                "cname_target": cname_check.target,
                "cname_error": cname_check.error,
                "routing_verified": routing_check.verified,
                "routing_status_code": routing_check.status_code,
                "routing_error": routing_check.error,
            }
        )

    @classmethod
    def _validate_lander_type(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in cls.LANDER_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="type must be default_tg_redirect or custom_upload",
            )
        return normalized

    @classmethod
    def _validate_slug(cls, value: str) -> str:
        normalized = value.strip()
        if not cls.SLUG_RE.fullmatch(normalized):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="slug may contain only letters, digits, underscore and dash",
            )
        return normalized
