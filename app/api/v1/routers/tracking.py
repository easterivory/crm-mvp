from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id, get_db
from app.schemas.common import PaginatedResponse
from app.schemas.tracking import (
    TrackingLinkCreate,
    TrackingLinkOut,
    TrackingLinkUpdate,
)
from app.services.tracking_service import TrackingService

router = APIRouter(prefix="/tracking-links", tags=["tracking"])


@router.get("", response_model=PaginatedResponse[TrackingLinkOut])
async def list_tracking_links(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    bot_id: Optional[UUID] = Query(default=None),
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[TrackingLinkOut]:
    items, total = await TrackingService(db).list_links(
        project_id=project_id,
        limit=limit,
        offset=offset,
        bot_id=bot_id,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=TrackingLinkOut, status_code=status.HTTP_201_CREATED)
async def create_tracking_link(
    data: TrackingLinkCreate,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> TrackingLinkOut:
    return await TrackingService(db).create_link(project_id=project_id, data=data)


@router.get("/{link_id}", response_model=TrackingLinkOut)
async def get_tracking_link(
    link_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> TrackingLinkOut:
    return await TrackingService(db).get_link(link_id=link_id, project_id=project_id)


@router.patch("/{link_id}", response_model=TrackingLinkOut)
async def update_tracking_link(
    link_id: UUID,
    data: TrackingLinkUpdate,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> TrackingLinkOut:
    return await TrackingService(db).update_link(
        link_id=link_id,
        project_id=project_id,
        data=data,
    )


@router.delete("/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tracking_link(
    link_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    await TrackingService(db).delete_link(link_id=link_id, project_id=project_id)
