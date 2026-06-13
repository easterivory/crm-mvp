from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.google_sheets import ProjectGoogleSheetsConfig
from app.services.google_sheets_export_queue import enqueue_lead_sheets_export


class GoogleSheetsTriggerService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def enqueue_if_status_triggered(
        self,
        *,
        lead_id: UUID,
        project_id: UUID,
        status_id: UUID,
    ) -> str | None:
        config = await self._get_active_config(project_id)
        if config is None:
            return None

        trigger_statuses = {str(item) for item in config.trigger_statuses or []}
        if str(status_id) not in trigger_statuses:
            return None

        return await enqueue_lead_sheets_export(lead_id=lead_id, project_id=project_id)

    async def _get_active_config(
        self,
        project_id: UUID,
    ) -> ProjectGoogleSheetsConfig | None:
        result = await self.db.execute(
            select(ProjectGoogleSheetsConfig).where(
                ProjectGoogleSheetsConfig.project_id == project_id,
                ProjectGoogleSheetsConfig.is_enabled.is_(True),
                ProjectGoogleSheetsConfig.spreadsheet_id.is_not(None),
                ProjectGoogleSheetsConfig.spreadsheet_id != "",
            )
        )
        return result.scalar_one_or_none()
