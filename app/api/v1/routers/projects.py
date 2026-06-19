from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_db
from app.schemas.common import PaginatedResponse
from app.schemas.project import (
    ProjectCreate,
    ProjectDashboardHeaderOut,
    ProjectOut,
    ProjectTranslationUpdate,
    ProjectUpdate,
)
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=PaginatedResponse[ProjectOut])
async def list_projects(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[ProjectOut]:
    items, total = await ProjectService(db).list_projects(
        limit=limit,
        offset=offset,
        actor=current_user,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    data: ProjectCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    return await ProjectService(db).create_project(data, actor=current_user)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    return await ProjectService(db).get_project(project_id, actor=current_user)


@router.get("/{project_id}/dashboard-header", response_model=ProjectDashboardHeaderOut)
async def get_dashboard_header(
    project_id: UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectDashboardHeaderOut:
    return await ProjectService(db).dashboard_header(project_id, actor=current_user)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: UUID,
    data: ProjectUpdate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    return await ProjectService(db).update_project(project_id, data, actor=current_user)


@router.patch("/{project_id}/translation-settings", response_model=ProjectOut)
async def update_project_translation_settings(
    project_id: UUID,
    data: ProjectTranslationUpdate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    return await ProjectService(db).update_translation_settings(
        project_id,
        data,
        actor=current_user,
    )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_project(
    project_id: UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await ProjectService(db).archive_project(project_id, actor=current_user)


@router.post("/{project_id}/restore", response_model=ProjectOut)
async def restore_project(
    project_id: UUID,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    return await ProjectService(db).restore_project(project_id, actor=current_user)
