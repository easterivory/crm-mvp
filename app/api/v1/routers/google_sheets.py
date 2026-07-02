from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user, get_db
from app.schemas.google_sheets import (
    GoogleSheetsConfigOut,
    GoogleSheetsConfigUpdate,
    GoogleSheetsTestConnectionOut,
)
from app.services.google_sheets_config_service import GoogleSheetsConfigService
from app.services.google_sheets_service import GoogleSheetsService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/projects/{project_id}/google-sheets",
    tags=["google-sheets"],
)


@router.get("", response_model=GoogleSheetsConfigOut)
async def get_google_sheets_config(
    project_id: UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GoogleSheetsConfigOut:
    return await GoogleSheetsConfigService(db).get_or_create_config(
        project_id=project_id,
        actor=current_user,
    )


@router.patch("", response_model=GoogleSheetsConfigOut)
async def update_google_sheets_config(
    project_id: UUID,
    data: GoogleSheetsConfigUpdate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GoogleSheetsConfigOut:
    return await GoogleSheetsConfigService(db).update_config(
        project_id=project_id,
        data=data,
        actor=current_user,
    )


@router.post("/test-connection", response_model=GoogleSheetsTestConnectionOut)
async def test_google_sheets_connection(
    project_id: UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GoogleSheetsTestConnectionOut:
    await GoogleSheetsConfigService(db).get_or_create_config(
        project_id=project_id,
        actor=current_user,
    )
    try:
        success, message = await GoogleSheetsService(db).test_connection_result(project_id)
    except Exception as exc:
        logger.exception("Google Sheets test connection endpoint failed project_id=%s", project_id)
        success = False
        message = str(exc) or exc.__class__.__name__
    if success:
        return GoogleSheetsTestConnectionOut(
            success=True,
            message=message,
        )
    return GoogleSheetsTestConnectionOut(
        success=False,
        message=f"Ошибка подключения: {message}",
    )
