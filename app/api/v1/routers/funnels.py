from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id, get_current_user, get_db
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.funnel import (
    FunnelBlockRegistryOut,
    FunnelCopyIn,
    FunnelCopyOut,
    FunnelCreate,
    FunnelDropOffAnalyticsOut,
    FunnelGraphIn,
    FunnelGraphOut,
    FunnelHoldModeUpdate,
    FunnelOut,
    FunnelUpdate,
    FunnelValidationOut,
    FunnelVersionOut,
    FunnelVersionUpdate,
)
from app.services.funnel_block_registry import FunnelBlockRegistry
from app.services.funnel_service import FunnelService

router = APIRouter(prefix="/funnels", tags=["funnels"])


@router.get("/block-registry", response_model=FunnelBlockRegistryOut)
async def get_block_registry() -> FunnelBlockRegistryOut:
    return FunnelBlockRegistry().as_schema()


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


@router.patch("/{funnel_id}/versions/{version_id}/hold", response_model=FunnelVersionOut)
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
