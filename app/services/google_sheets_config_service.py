from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import RoleName
from app.models.google_sheets import ProjectGoogleSheetsConfig
from app.models.lead_status import LeadStatus
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.schemas.google_sheets import GoogleSheetsConfigOut, GoogleSheetsConfigUpdate
from app.services.access_control import require_project_access


class GoogleSheetsConfigService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.project_repo = ProjectRepository(db)

    async def get_or_create_config(
        self,
        *,
        project_id: UUID,
        actor: User,
    ) -> GoogleSheetsConfigOut:
        await self._ensure_admin_project_access(actor=actor, project_id=project_id)
        config = await self._get_config(project_id)
        if config is None:
            config = ProjectGoogleSheetsConfig(project_id=project_id)
            self.db.add(config)
            await self.db.flush()
            await self.db.refresh(config)
        return self._to_out(config)

    async def update_config(
        self,
        *,
        project_id: UUID,
        data: GoogleSheetsConfigUpdate,
        actor: User,
    ) -> GoogleSheetsConfigOut:
        await self._ensure_admin_project_access(actor=actor, project_id=project_id)
        config = await self._get_config(project_id)
        if config is None:
            config = ProjectGoogleSheetsConfig(project_id=project_id)
            self.db.add(config)
            await self.db.flush()

        values = data.model_dump(exclude_unset=True)
        if "sheet_name" in values and values["sheet_name"] is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="sheet_name must not be empty",
            )
        if "trigger_statuses" in values and values["trigger_statuses"] is not None:
            values["trigger_statuses"] = await self._normalize_existing_status_ids(
                values["trigger_statuses"]
            )

        for field, value in values.items():
            setattr(config, field, value)

        await self.db.flush()
        await self.db.refresh(config)
        return self._to_out(config)

    async def _get_config(
        self,
        project_id: UUID,
    ) -> ProjectGoogleSheetsConfig | None:
        result = await self.db.execute(
            select(ProjectGoogleSheetsConfig).where(
                ProjectGoogleSheetsConfig.project_id == project_id
            )
        )
        return result.scalar_one_or_none()

    async def _ensure_admin_project_access(
        self,
        *,
        actor: User,
        project_id: UUID,
    ) -> None:
        if actor.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only super_admin/admin can manage Google Sheets settings",
            )
        require_project_access(actor, project_id)
        project = await self.project_repo.get_active(project_id)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

    async def _normalize_existing_status_ids(self, status_ids: list[str]) -> list[str]:
        if not status_ids:
            return []
        try:
            parsed_ids = [UUID(item) for item in status_ids]
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="trigger_statuses must contain status UUIDs",
            ) from exc

        normalized_ids = [str(item) for item in parsed_ids]
        result = await self.db.execute(
            select(LeadStatus.id).where(LeadStatus.id.in_(parsed_ids))
        )
        existing = {str(item) for item in result.scalars().all()}
        missing = [item for item in normalized_ids if item not in existing]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown lead status ids: {', '.join(missing)}",
            )
        return normalized_ids

    @staticmethod
    def _to_out(config: ProjectGoogleSheetsConfig) -> GoogleSheetsConfigOut:
        return GoogleSheetsConfigOut.model_validate(config).model_copy(
            update={"service_account_email": settings.GOOGLE_SERVICE_ACCOUNT_EMAIL}
        )
