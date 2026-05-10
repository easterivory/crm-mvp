"""
TrackingService - Telegram deep-link source management and attribution URLs.
"""
import secrets
import string
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.bot_repository import BotRepository
from app.repositories.tracking_repository import TrackingRepository
from app.schemas.tracking import (
    TrackingLinkCreate,
    TrackingLinkOut,
    TrackingLinkUpdate,
)
from app.services.bot_service import BotService


class TrackingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.tracking_repo = TrackingRepository(db)
        self.bot_repo = BotRepository(db)
        self.bot_service = BotService(db)

    async def list_links(
        self,
        project_id: UUID,
        limit: int,
        offset: int,
        bot_id: UUID | None = None,
    ) -> tuple[list[TrackingLinkOut], int]:
        if bot_id is not None:
            await self._ensure_bot_in_project(bot_id, project_id)

        links = await self.tracking_repo.list_by_project(
            project_id=project_id,
            limit=limit,
            offset=offset,
            bot_id=bot_id,
        )
        total = await self.tracking_repo.count_by_project(
            project_id=project_id,
            bot_id=bot_id,
        )
        return [self._to_out(link) for link in links], total

    async def get_link(self, link_id: UUID, project_id: UUID) -> TrackingLinkOut:
        link = await self.tracking_repo.get_by_id_in_project(link_id, project_id)
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
        name = self._normalize_required(data.name, "name")
        target_step_id = data.target_step_id
        if target_step_id is not None:
            await self._ensure_step_belongs_to_bot(target_step_id, bot.id, project_id)

        requested_ref_code = self._normalize_ref_code(data.ref_code)
        ref_code = requested_ref_code or await self._generate_unique_ref_code()

        try:
            async with self.db.begin_nested():
                link = await self.tracking_repo.create(
                    project_id=project_id,
                    bot_id=bot.id,
                    name=name,
                    ref_code=ref_code,
                    cost_model=data.cost_model,
                    price_per_unit=data.price_per_unit,
                    spend=data.spend,
                    target_step_id=target_step_id,
                )
        except IntegrityError:
            if requested_ref_code is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Tracking ref_code already exists",
                )
            ref_code = await self._generate_unique_ref_code()
            async with self.db.begin_nested():
                link = await self.tracking_repo.create(
                    project_id=project_id,
                    bot_id=bot.id,
                    name=name,
                    ref_code=ref_code,
                    cost_model=data.cost_model,
                    price_per_unit=data.price_per_unit,
                    spend=data.spend,
                    target_step_id=target_step_id,
                )

        link.bot = bot
        return self._to_out(link)

    async def update_link(
        self,
        link_id: UUID,
        project_id: UUID,
        data: TrackingLinkUpdate,
    ) -> TrackingLinkOut:
        link = await self.tracking_repo.get_by_id_in_project(link_id, project_id)
        if link is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tracking link not found",
            )

        values = data.model_dump(exclude_unset=True)
        if "name" in values:
            values["name"] = self._normalize_required(values["name"], "name")
        if "ref_code" in values:
            values["ref_code"] = self._normalize_ref_code(
                values["ref_code"],
                required=True,
            )
        if values.get("target_step_id") is not None:
            await self._ensure_step_belongs_to_bot(
                values["target_step_id"],
                link.bot_id,
                project_id,
            )

        if not values:
            return self._to_out(link)

        try:
            async with self.db.begin_nested():
                updated = await self.tracking_repo.update_by_id(link_id, **values)
        except IntegrityError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Tracking ref_code already exists",
            ) from exc

        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tracking link not found",
            )

        return await self.get_link(updated.id, project_id)

    async def delete_link(self, link_id: UUID, project_id: UUID) -> None:
        deleted = await self.tracking_repo.delete_from_project(link_id, project_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tracking link not found",
            )

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

    async def _generate_unique_ref_code(self) -> str:
        for _ in range(8):
            ref_code = self._random_ref_code()
            existing = await self.tracking_repo.get_by_ref_code(ref_code)
            if existing is None:
                return ref_code

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate a unique tracking ref_code",
        )

    @staticmethod
    def _random_ref_code() -> str:
        alphabet = string.ascii_letters + string.digits + "_-"
        return "".join(secrets.choice(alphabet) for _ in range(10))

    @staticmethod
    def _normalize_required(value: str | None, field_name: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field_name} must not be empty",
            )
        return normalized

    @classmethod
    def _normalize_ref_code(
        cls,
        value: str | None,
        *,
        required: bool = False,
    ) -> str | None:
        if value is None:
            if required:
                return cls._normalize_required(value, "ref_code")
            return None

        normalized = cls._normalize_required(value, "ref_code")
        if normalized is None:
            return None

        allowed = set(string.ascii_letters + string.digits + "_-")
        if any(char not in allowed for char in normalized):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="ref_code may contain only letters, digits, underscore, and dash",
            )
        if len(normalized) > 64:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="ref_code must be 64 characters or fewer",
            )
        return normalized

    @staticmethod
    def _to_out(link) -> TrackingLinkOut:
        username = (link.bot.bot_username or "").removeprefix("@")
        return TrackingLinkOut.model_validate(link).model_copy(
            update={"tracking_url": f"https://t.me/{username}?start={link.ref_code}"}
        )
