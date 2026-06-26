"""
TrackingService - project-scoped tracking links, Telegram invite links, and spend.
"""
import re
import secrets
import string
import unicodedata
from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import TrackingSpendSource
from app.models.tracking import TrackingLink
from app.models.tracking import TrackingSpend
from app.models.funnel import FunnelStep, FunnelVersion
from app.models.user import User
from app.repositories.bot_repository import BotRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.tracking_repository import TrackingLinkRepository
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


class TrackingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.tracking_repo = TrackingRepository(db)
        self.link_repo = TrackingLinkRepository(db)
        self.spend_repo = TrackingSpendRepository(db)
        self.bot_repo = BotRepository(db)
        self.bot_service = BotService(db)
        self.project_repo = ProjectRepository(db)

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
        invite_link = self._normalize_optional(data.invite_link) or self._build_invite_link(
            bot.bot_username,
            code,
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
                    buyer_name=self._normalize_optional(data.buyer_name),
                    ad_type=self._normalize_optional(data.ad_type),
                    payment_type=self._normalize_optional(data.payment_type),
                    invite_link=invite_link,
                    fb_pixel_id=data.fb_pixel_id,
                    fb_capi_token=data.fb_capi_token,
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
                    buyer_name=self._normalize_optional(data.buyer_name),
                    ad_type=self._normalize_optional(data.ad_type),
                    payment_type=self._normalize_optional(data.payment_type),
                    invite_link=self._build_invite_link(bot.bot_username, code),
                    fb_pixel_id=data.fb_pixel_id,
                    fb_capi_token=data.fb_capi_token,
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

        values = self._build_link_update_values(data, link=link, allow_code_update=True)
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

        links = await self.link_repo.list_links(
            project_id=project_id,
            limit=limit,
            offset=offset,
            bot_id=bot_id,
            is_active=is_active,
        )
        total = await self.link_repo.count_links(
            project_id=project_id,
            bot_id=bot_id,
            is_active=is_active,
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
                FunnelStep.step_type.notin_(("trigger", "finish")),
            )
            .order_by(FunnelStep.position_y, FunnelStep.position_x, FunnelStep.created_at)
        )
        return [
            TrackingFunnelStepOption(
                key=step.key,
                title=step.title,
                step_type=step.step_type,
                block_type=step.block_type,
            )
            for step in result.scalars().all()
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

        await self._ensure_project_access(actor, data.project_id)
        project = await self._get_active_project_or_404(data.project_id)
        bot = await self.bot_service.ensure_bot_username(
            bot_id=data.bot_id,
            project_id=project.id,
        )

        title = self._normalize_required(data.title or data.name, "title")
        code = self._normalize_code(data.code or data.ref_code)
        code = code or await self._generate_unique_code(title)
        await self._ensure_code_available(code)

        target_step_id = data.target_step_id
        if target_step_id is not None:
            await self._ensure_step_belongs_to_bot(target_step_id, bot.id, project.id)
        target_funnel_id, target_funnel_step_key = await self._resolve_target_funnel_step(
            bot_id=bot.id,
            project_id=project.id,
            target_funnel_step_key=data.target_funnel_step_key,
        )

        invite_link = self._normalize_optional(data.invite_link) or self._build_invite_link(
            bot.bot_username,
            code,
        )

        try:
            link = await self.link_repo.create_link(
                project_id=project.id,
                bot_id=bot.id,
                name=title,
                title=title,
                ref_code=code,
                code=code,
                buyer_name=self._normalize_optional(data.buyer_name),
                ad_type=self._normalize_optional(data.ad_type),
                payment_type=self._normalize_optional(data.payment_type),
                invite_link=invite_link,
                fb_pixel_id=data.fb_pixel_id,
                fb_capi_token=data.fb_capi_token,
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
        except IntegrityError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Tracking code already exists",
            ) from exc

        link.bot = bot
        return await self._to_read(link, include_total_spend=True)

    async def update_tracking_link(
        self,
        link_id: UUID,
        data: TrackingLinkUpdate,
        actor: User,
    ) -> TrackingLinkRead:
        link = await self._get_link_for_actor(link_id, actor)
        values = self._build_link_update_values(data, link=link, allow_code_update=False)
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

        if not values:
            return await self._to_read(link, include_total_spend=True)

        updated = await self.link_repo.update_link(link.id, **values)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tracking link not found",
            )
        return await self._to_read(updated, include_total_spend=True)

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

        for field in ("buyer_name", "ad_type", "payment_type", "invite_link", "fb_pixel_id", "fb_capi_token"):
            if field in values:
                values[field] = self._normalize_optional(values[field])

        return values

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
        return f"https://t.me/{username}?start={code}"

    @classmethod
    def _to_out(cls, link: TrackingLink) -> TrackingLinkOut:
        username = (link.bot.bot_username or "").removeprefix("@")
        ref_code = link.ref_code or link.code
        return TrackingLinkOut.model_validate(link).model_copy(
            update={
                "tracking_url": f"https://t.me/{username}?start={ref_code}",
                "has_fb_capi_token": bool((link.fb_capi_token or "").strip()),
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
        invite_link = link.invite_link or self._build_invite_link(
            getattr(link.bot, "bot_username", None),
            code,
        )
        total_spend: Decimal | None = None
        if include_total_spend:
            total_spend = await self.spend_repo.sum_spend_by_link(link.id)

        return TrackingLinkRead(
            id=link.id,
            project_id=link.project_id,
            bot_id=link.bot_id,
            code=code,
            title=title,
            buyer_name=link.buyer_name,
            ad_type=link.ad_type,
            payment_type=link.payment_type,
            invite_link=invite_link,
            is_active=link.is_active,
            created_by_user_id=link.created_by_user_id,
            created_at=link.created_at,
            updated_at=link.updated_at,
            base_conversion_rate=link.base_conversion_rate,
            min_sample_size=link.min_sample_size,
            target_funnel_id=link.target_funnel_id,
            target_funnel_step_key=link.target_funnel_step_key,
            target_funnel_step_title=await self._target_funnel_step_title(link),
            fb_pixel_id=link.fb_pixel_id,
            has_fb_capi_token=bool((link.fb_capi_token or "").strip()),
            total_spend=total_spend,
        )
