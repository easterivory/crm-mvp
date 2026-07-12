from __future__ import annotations

import re
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.constants import RoleName
from app.models.lander import ProjectDomain, ProjectLander
from app.models.tracking import TrackingLink
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.schemas.lander import (
    ProjectDomainCreate,
    ProjectDomainOut,
    ProjectLanderCreate,
    LanderRuntimeConfigOut,
    ProjectLanderOut,
    ProjectLanderUpdate,
)
from app.services.access_control import require_project_access
from app.schemas.tracking import TrackingLinkCreate
from app.services.tracking_service import TrackingService


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
        await self._ensure_admin_project_access(actor=actor, project_id=project_id)
        result = await self.db.execute(
            select(ProjectDomain)
            .where(ProjectDomain.project_id == project_id)
            .order_by(ProjectDomain.created_at.desc())
        )
        return [ProjectDomainOut.model_validate(item) for item in result.scalars().all()]

    async def create_domain(
        self,
        *,
        project_id: UUID,
        data: ProjectDomainCreate,
        actor: User,
    ) -> ProjectDomainOut:
        await self._ensure_admin_project_access(actor=actor, project_id=project_id)
        domain_name = data.domain_name
        if await self._domain_exists(domain_name):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Domain already exists",
            )

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
            delete(ProjectDomain).where(
                ProjectDomain.id == domain_id,
                ProjectDomain.project_id == project_id,
            )
        )
        if result.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Domain not found",
            )

    async def list_landers(
        self,
        *,
        project_id: UUID,
        actor: User,
    ) -> list[ProjectLanderOut]:
        await self._ensure_admin_project_access(actor=actor, project_id=project_id)
        result = await self.db.execute(
            select(ProjectLander)
            .options(selectinload(ProjectLander.domain), selectinload(ProjectLander.tracking_link))
            .where(ProjectLander.project_id == project_id)
            .order_by(ProjectLander.created_at.desc())
        )
        return [self._to_lander_out(item) for item in result.scalars().all()]

    async def get_runtime_config(
        self,
        *,
        project_id: UUID,
        actor: User,
    ) -> LanderRuntimeConfigOut:
        await self._ensure_admin_project_access(actor=actor, project_id=project_id)
        return LanderRuntimeConfigOut(technical_domain=self._technical_domain())

    async def create_lander(
        self,
        *,
        project_id: UUID,
        data: ProjectLanderCreate,
        actor: User,
    ) -> ProjectLanderOut:
        await self._ensure_admin_project_access(actor=actor, project_id=project_id)
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
        if tracking_link_id is not None:
            await self._ensure_tracking_link_belongs_to_project(tracking_link_id, project_id)
        elif data.campaign is not None:
            campaign = data.campaign
            tracking_link = await TrackingService(self.db).create_tracking_link(
                data=TrackingLinkCreate(
                    project_id=project_id,
                    bot_id=campaign.bot_id,
                    title=campaign.title,
                    code=campaign.code,
                    buyer_name=campaign.buyer_name,
                    ad_type=campaign.ad_type,
                    payment_type=campaign.payment_type,
                    fb_pixel_id=campaign.fb_pixel_id,
                    fb_capi_token=campaign.fb_capi_token,
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

        campaign_pixel_id = data.campaign.fb_pixel_id if data.campaign is not None else None
        pixels_json = [pixel.model_dump() for pixel in data.pixels]
        if campaign_pixel_id and not pixels_json:
            pixels_json = [{"provider": "meta", "pixel_id": campaign_pixel_id}]

        lander = ProjectLander(
            project_id=project_id,
            domain_id=data.domain_id,
            name=data.name,
            type=lander_type,
            slug=slug,
            tracking_link_id=tracking_link_id,
            pixels_json=pixels_json,
            meta_events_json=[event.model_dump() for event in data.meta_events],
            utm_defaults_json=data.utm_defaults,
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
        await self._ensure_admin_project_access(actor=actor, project_id=project_id)
        lander = await self._get_lander(lander_id=lander_id, project_id=project_id)
        if "pixels" in data.model_fields_set and data.pixels is not None:
            lander.pixels_json = [pixel.model_dump() for pixel in data.pixels]
        if "meta_events" in data.model_fields_set and data.meta_events is not None:
            lander.meta_events_json = [event.model_dump() for event in data.meta_events]
        if (
            "auto_redirect_enabled" in data.model_fields_set
            and data.auto_redirect_enabled is not None
        ):
            lander.auto_redirect_enabled = data.auto_redirect_enabled
        if data.facebook_campaign is not None:
            if lander.tracking_link is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Lander is not attached to a tracking link",
                )
            campaign = data.facebook_campaign
            link = lander.tracking_link
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
            lander.pixels_json = (
                [{"provider": "meta", "pixel_id": campaign.fb_pixel_id}]
                if campaign.fb_pixel_id
                else []
            )
        await self.db.flush()
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
        await self._ensure_admin_project_access(actor=actor, project_id=project_id)
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

    async def ensure_upload_access(
        self,
        *,
        project_id: UUID,
        lander_id: UUID,
        actor: User,
    ) -> None:
        await self._ensure_admin_project_access(actor=actor, project_id=project_id)
        lander = await self._get_lander(lander_id=lander_id, project_id=project_id)
        if lander.type != "custom_upload":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="ZIP upload is available only for custom_upload landers",
            )

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
        require_project_access(actor, project_id)
        project = await self.project_repo.get_active(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

    async def _domain_exists(self, domain_name: str) -> bool:
        result = await self.db.execute(
            select(func.count(ProjectDomain.id)).where(ProjectDomain.domain_name == domain_name)
        )
        return result.scalar_one() > 0

    async def _slug_exists(self, slug: str) -> bool:
        result = await self.db.execute(
            select(func.count(ProjectLander.id)).where(ProjectLander.slug == slug)
        )
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
                selectinload(ProjectLander.tracking_link),
            )
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
        return ProjectLanderOut.model_validate(lander).model_copy(
            update={
                "domain_name": domain_name,
                "public_url": f"https://{public_host}/l/{lander.slug}",
                "facebook_campaign_enabled": bool(
                    link is not None and link.fb_campaign_enabled
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
                    link.fb_event_mappings_json if link is not None else []
                ),
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
