from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import RoleName
from app.models.chat_filter_preset import ChatFilterPreset
from app.models.user import User
from app.repositories.chat_filter_preset_repository import ChatFilterPresetRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.chat_filter_preset import (
    ChatFilterPresetCreate,
    ChatFilterPresetOut,
    ChatFilterPresetUpdate,
)


class ChatFilterPresetService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ChatFilterPresetRepository(db)
        self.project_repo = ProjectRepository(db)

    async def list_presets(
        self,
        *,
        actor: User,
        project_id: UUID,
    ) -> list[ChatFilterPresetOut]:
        scoped_project_id = await self._resolve_project(actor, project_id)
        presets = await self.repo.list_visible(
            project_id=scoped_project_id,
            user_id=actor.id,
        )
        return [ChatFilterPresetOut.model_validate(preset) for preset in presets]

    async def create_preset(
        self,
        *,
        actor: User,
        data: ChatFilterPresetCreate,
    ) -> ChatFilterPresetOut:
        project_id = await self._resolve_project(actor, data.project_id)
        self._ensure_can_set_shared(actor, data.is_shared)
        try:
            async with self.db.begin_nested():
                preset = await self.repo.create(
                    project_id=project_id,
                    user_id=actor.id,
                    name=self._normalize_name(data.name),
                    filters_json=dict(data.filters_json or {}),
                    is_shared=data.is_shared,
                )
        except IntegrityError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Filter preset with this name already exists",
            ) from exc
        return ChatFilterPresetOut.model_validate(preset)

    async def update_preset(
        self,
        *,
        preset_id: UUID,
        actor: User,
        data: ChatFilterPresetUpdate,
    ) -> ChatFilterPresetOut:
        project_id = self._actor_project_or_none(actor)
        preset = await self._get_accessible_preset(
            preset_id=preset_id,
            actor=actor,
            project_id=project_id,
            for_write=True,
        )
        values = data.model_dump(exclude_unset=True)
        if "name" in values and values["name"] is not None:
            values["name"] = self._normalize_name(values["name"])
        if "filters_json" in values and values["filters_json"] is not None:
            values["filters_json"] = dict(values["filters_json"] or {})
        if "is_shared" in values:
            self._ensure_can_set_shared(actor, bool(values["is_shared"]))
        if not values:
            return ChatFilterPresetOut.model_validate(preset)

        try:
            async with self.db.begin_nested():
                updated = await self.repo.update_preset(
                    preset_id=preset.id,
                    values=values,
                )
        except IntegrityError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Filter preset with this name already exists",
            ) from exc
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Filter preset not found",
            )
        return ChatFilterPresetOut.model_validate(updated)

    async def delete_preset(
        self,
        *,
        preset_id: UUID,
        actor: User,
    ) -> None:
        preset = await self._get_accessible_preset(
            preset_id=preset_id,
            actor=actor,
            project_id=self._actor_project_or_none(actor),
            for_write=True,
        )
        deleted = await self.repo.delete_preset(preset.id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Filter preset not found",
            )

    async def _get_accessible_preset(
        self,
        *,
        preset_id: UUID,
        actor: User,
        project_id: UUID | None,
        for_write: bool,
    ) -> ChatFilterPreset:
        if actor.role_name == RoleName.SUPER_ADMIN:
            preset = await self.repo.get_by_id(preset_id)
        else:
            if project_id is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User is not associated with a project",
                )
            preset = await self.repo.get_in_project(
                preset_id=preset_id,
                project_id=project_id,
            )
        if preset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Filter preset not found",
            )
        if not self._can_read(actor, preset):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Filter preset is not accessible",
            )
        if for_write and not self._can_write(actor, preset):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Filter preset cannot be changed by current user",
            )
        return preset

    async def _resolve_project(
        self,
        actor: User,
        project_id: UUID | None,
    ) -> UUID:
        if actor.role_name == RoleName.SUPER_ADMIN:
            if project_id is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="project_id is required for super_admin scoped requests",
                )
            resolved = project_id
        else:
            if actor.project_id is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User is not associated with a project",
                )
            if project_id is not None and project_id != actor.project_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Project is not accessible for current user",
                )
            resolved = actor.project_id

        project = await self.project_repo.get_active(resolved)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        return resolved

    @staticmethod
    def _actor_project_or_none(actor: User) -> UUID | None:
        return None if actor.role_name == RoleName.SUPER_ADMIN else actor.project_id

    @staticmethod
    def _can_read(actor: User, preset: ChatFilterPreset) -> bool:
        if actor.role_name == RoleName.SUPER_ADMIN:
            return True
        return preset.project_id == actor.project_id and (
            preset.user_id == actor.id or preset.is_shared
        )

    @staticmethod
    def _can_write(actor: User, preset: ChatFilterPreset) -> bool:
        if preset.user_id == actor.id:
            return True
        return preset.is_shared and actor.role_name in {
            RoleName.SUPER_ADMIN,
            RoleName.ADMIN,
        }

    @staticmethod
    def _ensure_can_set_shared(actor: User, is_shared: bool) -> None:
        if is_shared and actor.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only super_admin/admin can create shared filter presets",
            )

    @staticmethod
    def _normalize_name(value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Preset name must not be empty",
            )
        return normalized
