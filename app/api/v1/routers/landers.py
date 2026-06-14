from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.lander import (
    ProjectLanderCreate,
    ProjectLanderOut,
    ProjectLanderUploadOut,
)
from app.services.lander_admin_service import LanderAdminService
from app.services.lander_service import LanderService

router = APIRouter(prefix="/projects/{project_id}/landers", tags=["landers"])


@router.get("", response_model=list[ProjectLanderOut])
async def list_project_landers(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectLanderOut]:
    return await LanderAdminService(db).list_landers(
        project_id=project_id,
        actor=current_user,
    )


@router.post("", response_model=ProjectLanderOut, status_code=status.HTTP_201_CREATED)
async def create_project_lander(
    project_id: UUID,
    data: ProjectLanderCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectLanderOut:
    return await LanderAdminService(db).create_lander(
        project_id=project_id,
        data=data,
        actor=current_user,
    )


@router.post("/{lander_id}/upload", response_model=ProjectLanderUploadOut)
async def upload_project_lander_zip(
    project_id: UUID,
    lander_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProjectLanderUploadOut:
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only .zip files are supported",
        )

    service = LanderAdminService(db)
    await service.ensure_upload_access(
        project_id=project_id,
        lander_id=lander_id,
        actor=current_user,
    )
    zip_bytes = await file.read()
    if not zip_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded ZIP is empty",
        )

    try:
        custom_html_path = await LanderService(db).save_custom_lander_zip(
            lander_id=lander_id,
            zip_bytes=zip_bytes,
            project_id=project_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return ProjectLanderUploadOut(success=True, custom_html_path=custom_html_path)


@router.delete(
    "/{lander_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_project_lander(
    project_id: UUID,
    lander_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await LanderAdminService(db).delete_lander(
        project_id=project_id,
        lander_id=lander_id,
        actor=current_user,
    )
