from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id, get_current_user, get_db
from app.core.constants import RoleName
from app.models.user import User
from app.repositories.broadcast_repository import BroadcastRepository
from app.schemas.broadcast import BroadcastUploadOut
from app.schemas.common import PaginatedResponse
from app.schemas.funnel import (
    FunnelBlockRegistryOut,
    FunnelCopyIn,
    FunnelCopyOut,
    FunnelCreate,
    FunnelDropOffAnalyticsOut,
    FunnelGraphValidateIn,
    FunnelGraphValidationOut,
    FunnelGraphIn,
    FunnelGraphOut,
    FunnelHoldModeUpdate,
    FunnelOut,
    FunnelSelfRestartOut,
    FunnelStepOptionOut,
    FunnelUpdate,
    FunnelValidationOut,
    FunnelVersionOut,
    FunnelVersionUpdate,
)
from app.services.funnel_block_registry import FunnelBlockRegistry
from app.services.broadcast_service import BroadcastService
from app.services.funnel_service import FunnelService
from app.services.funnel_validator import FunnelGraphValidator

router = APIRouter(prefix="/funnels", tags=["funnels"])

FUNNEL_EDITOR_ROLES = {RoleName.SUPER_ADMIN, RoleName.ADMIN}


def _ensure_funnel_editor(current_user: User) -> None:
    if current_user.role_name not in FUNNEL_EDITOR_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin or super_admin can edit funnel versions",
        )


@router.get("/block-registry", response_model=FunnelBlockRegistryOut)
async def get_block_registry() -> FunnelBlockRegistryOut:
    return FunnelBlockRegistry().as_schema()


@router.get("/step-options", response_model=list[FunnelStepOptionOut])
async def list_funnel_step_options(
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[FunnelStepOptionOut]:
    return await FunnelService(db).list_current_step_options(
        project_id=project_id,
        current_user=current_user,
    )


@router.post("/media/uploads", response_model=BroadcastUploadOut, status_code=status.HTTP_201_CREATED)
async def upload_funnel_media(
    file: UploadFile = File(...),
    media_type: str | None = Form(default=None),
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BroadcastUploadOut:
    _ensure_funnel_editor(current_user)
    return await BroadcastService(db).upload_media(
        actor=current_user,
        project_id=project_id,
        file=file,
        media_type=media_type,
        persistent=True,
    )


@router.get("/media/uploads/{upload_id}", response_class=FileResponse)
async def get_funnel_media_upload(
    upload_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    _ensure_funnel_editor(current_user)
    upload = await BroadcastRepository(db).get_upload_in_project(upload_id, project_id)
    if upload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")

    path = Path(upload.storage_path)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload file not found")

    return FileResponse(
        path,
        media_type=upload.mime_type,
        filename=upload.file_name,
    )


@router.get("", response_model=PaginatedResponse[FunnelOut])
async def list_funnels(
    bot_id: Optional[UUID] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[FunnelOut]:
    return await FunnelService(db).list_funnels(
        project_id=project_id,
        current_user=current_user,
        bot_id=bot_id,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=FunnelOut, status_code=status.HTTP_201_CREATED)
async def create_funnel(
    data: FunnelCreate,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FunnelOut:
    return await FunnelService(db).create_funnel(
        project_id=project_id,
        data=data,
        current_user=current_user,
    )


@router.get("/{funnel_id}", response_model=FunnelOut)
async def get_funnel(
    funnel_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FunnelOut:
    return await FunnelService(db).get_funnel(
        funnel_id=funnel_id,
        project_id=project_id,
        current_user=current_user,
    )


@router.post("/{funnel_id}/restart-self", response_model=FunnelSelfRestartOut)
async def restart_funnel_for_buyer_self(
    funnel_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FunnelSelfRestartOut:
    return await FunnelService(db).restart_funnel_for_buyer_self(
        funnel_id=funnel_id,
        project_id=project_id,
        current_user=current_user,
    )


@router.patch("/{funnel_id}", response_model=FunnelOut)
async def update_funnel(
    funnel_id: UUID,
    data: FunnelUpdate,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FunnelOut:
    return await FunnelService(db).update_funnel(
        funnel_id=funnel_id,
        project_id=project_id,
        data=data,
        current_user=current_user,
    )


@router.post("/{funnel_id}/archive", response_model=FunnelOut)
async def archive_funnel(
    funnel_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FunnelOut:
    return await FunnelService(db).archive_funnel(
        funnel_id=funnel_id,
        project_id=project_id,
        current_user=current_user,
    )


@router.post("/{funnel_id}/validate", response_model=FunnelGraphValidationOut)
async def validate_graph(
    funnel_id: UUID,
    data: FunnelGraphValidateIn,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FunnelGraphValidationOut:
    _ensure_funnel_editor(current_user)
    await FunnelService(db).get_funnel(
        funnel_id=funnel_id,
        project_id=project_id,
        current_user=current_user,
    )
    result = FunnelGraphValidator().validate_graph(nodes=data.nodes, edges=data.edges)
    return FunnelGraphValidationOut(**result)


@router.get("/{funnel_id}/versions", response_model=list[FunnelVersionOut])
async def list_versions(
    funnel_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[FunnelVersionOut]:
    return await FunnelService(db).list_versions(
        funnel_id=funnel_id,
        project_id=project_id,
        current_user=current_user,
    )


@router.post("/{funnel_id}/versions/draft", response_model=FunnelVersionOut)
async def create_draft_version(
    funnel_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FunnelVersionOut:
    return await FunnelService(db).create_draft_version(
        funnel_id=funnel_id,
        project_id=project_id,
        current_user=current_user,
    )


@router.post(
    "/{funnel_id}/versions/{version_id}/draft",
    response_model=FunnelVersionOut,
)
async def create_draft_from_version(
    funnel_id: UUID,
    version_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FunnelVersionOut:
    return await FunnelService(db).create_draft_from_version(
        funnel_id=funnel_id,
        source_version_id=version_id,
        project_id=project_id,
        current_user=current_user,
    )


@router.get("/{funnel_id}/versions/{version_id}", response_model=FunnelVersionOut)
async def get_version(
    funnel_id: UUID,
    version_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FunnelVersionOut:
    return await FunnelService(db).get_version(
        funnel_id=funnel_id,
        version_id=version_id,
        project_id=project_id,
        current_user=current_user,
    )


@router.patch("/{funnel_id}/versions/{version_id}", response_model=FunnelVersionOut)
async def update_version(
    funnel_id: UUID,
    version_id: UUID,
    data: FunnelVersionUpdate,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FunnelVersionOut:
    return await FunnelService(db).update_version(
        funnel_id=funnel_id,
        version_id=version_id,
        project_id=project_id,
        data=data,
        current_user=current_user,
    )


@router.post("/{funnel_id}/versions/{version_id}/publish", response_model=FunnelVersionOut)
async def publish_version(
    funnel_id: UUID,
    version_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FunnelVersionOut:
    return await FunnelService(db).publish_version(
        funnel_id=funnel_id,
        version_id=version_id,
        project_id=project_id,
        current_user=current_user,
    )


@router.post("/{funnel_id}/versions/{version_id}/current", response_model=FunnelVersionOut)
async def set_current_version(
    funnel_id: UUID,
    version_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FunnelVersionOut:
    return await FunnelService(db).set_current_version(
        funnel_id=funnel_id,
        version_id=version_id,
        project_id=project_id,
        current_user=current_user,
    )


@router.post(
    "/{funnel_id}/versions/{version_id}/rollback",
    response_model=FunnelVersionOut,
)
async def rollback_version(
    funnel_id: UUID,
    version_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FunnelVersionOut:
    _ensure_funnel_editor(current_user)
    return await FunnelService(db).rollback_to_version(
        funnel_id=funnel_id,
        version_id=version_id,
        project_id=project_id,
        current_user=current_user,
    )


@router.post("/{funnel_id}/versions/{version_id}/toggle-hold", response_model=FunnelVersionOut)
async def set_hold_mode(
    funnel_id: UUID,
    version_id: UUID,
    data: FunnelHoldModeUpdate,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FunnelVersionOut:
    return await FunnelService(db).set_hold_mode(
        funnel_id=funnel_id,
        version_id=version_id,
        project_id=project_id,
        data=data,
        current_user=current_user,
    )


@router.patch("/{funnel_id}/versions/{version_id}/hold", response_model=FunnelVersionOut)
async def set_hold_mode_legacy(
    funnel_id: UUID,
    version_id: UUID,
    data: FunnelHoldModeUpdate,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FunnelVersionOut:
    return await FunnelService(db).set_hold_mode(
        funnel_id=funnel_id,
        version_id=version_id,
        project_id=project_id,
        data=data,
        current_user=current_user,
    )


@router.get(
    "/{funnel_id}/versions/{version_id}/analytics/drop-off",
    response_model=FunnelDropOffAnalyticsOut,
)
async def get_drop_off_analytics(
    funnel_id: UUID,
    version_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FunnelDropOffAnalyticsOut:
    return await FunnelService(db).get_drop_off_analytics(
        funnel_id=funnel_id,
        version_id=version_id,
        project_id=project_id,
        current_user=current_user,
    )


@router.get("/{funnel_id}/versions/{version_id}/graph", response_model=FunnelGraphOut)
async def get_graph(
    funnel_id: UUID,
    version_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FunnelGraphOut:
    return await FunnelService(db).get_graph(
        funnel_id=funnel_id,
        version_id=version_id,
        project_id=project_id,
        current_user=current_user,
    )


@router.put("/{funnel_id}/versions/{version_id}/graph", response_model=FunnelGraphOut)
async def save_graph(
    funnel_id: UUID,
    version_id: UUID,
    graph: FunnelGraphIn,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FunnelGraphOut:
    return await FunnelService(db).save_graph(
        funnel_id=funnel_id,
        version_id=version_id,
        project_id=project_id,
        graph=graph,
        current_user=current_user,
    )


@router.post(
    "/{funnel_id}/versions/{version_id}/validate",
    response_model=FunnelValidationOut,
)
async def validate_version(
    funnel_id: UUID,
    version_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FunnelValidationOut:
    return await FunnelService(db).validate_version(
        funnel_id=funnel_id,
        version_id=version_id,
        project_id=project_id,
        current_user=current_user,
    )


@router.post("/{funnel_id}/copy", response_model=FunnelCopyOut)
async def copy_funnel(
    funnel_id: UUID,
    data: FunnelCopyIn,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FunnelCopyOut:
    return await FunnelService(db).copy_funnel(
        funnel_id=funnel_id,
        project_id=project_id,
        data=data,
        current_user=current_user,
    )
