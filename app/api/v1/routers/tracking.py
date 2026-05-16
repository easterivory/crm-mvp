from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id, get_current_user, get_db
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.tracking import (
    TrackingLinkCreate,
    TrackingLinkOut,
    TrackingLinkRead,
    TrackingLinkUpdate,
    TrackingSpendCreate,
    TrackingSpendRead,
    TrackingSpendUpdate,
)
from app.services.tracking_service import TrackingService

router = APIRouter(prefix="/tracking-links", tags=["tracking"])
v1_router = APIRouter(prefix="/tracking", tags=["tracking"])


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


@v1_router.get("/links", response_model=PaginatedResponse[TrackingLinkRead])
async def list_tracking_links_v1(
    project_id: UUID = Query(...),
    bot_id: Optional[UUID] = Query(default=None),
    is_active: Optional[bool] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[TrackingLinkRead]:
    items, total = await TrackingService(db).list_tracking_links(
        project_id=project_id,
        actor=current_user,
        limit=limit,
        offset=offset,
        bot_id=bot_id,
        is_active=is_active,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@v1_router.post(
    "/links",
    response_model=TrackingLinkRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_tracking_link_v1(
    data: TrackingLinkCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrackingLinkRead:
    return await TrackingService(db).create_tracking_link(
        data=data,
        actor=current_user,
    )


@v1_router.get("/links/{link_id}", response_model=TrackingLinkRead)
async def get_tracking_link_v1(
    link_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrackingLinkRead:
    return await TrackingService(db).get_tracking_link(
        link_id=link_id,
        actor=current_user,
    )


@v1_router.patch("/links/{link_id}", response_model=TrackingLinkRead)
async def update_tracking_link_v1(
    link_id: UUID,
    data: TrackingLinkUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrackingLinkRead:
    return await TrackingService(db).update_tracking_link(
        link_id=link_id,
        data=data,
        actor=current_user,
    )


@v1_router.post("/links/{link_id}/archive", response_model=TrackingLinkRead)
async def archive_tracking_link_v1(
    link_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrackingLinkRead:
    return await TrackingService(db).set_tracking_link_active(
        link_id=link_id,
        is_active=False,
        actor=current_user,
    )


@v1_router.post("/links/{link_id}/restore", response_model=TrackingLinkRead)
async def restore_tracking_link_v1(
    link_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrackingLinkRead:
    return await TrackingService(db).set_tracking_link_active(
        link_id=link_id,
        is_active=True,
        actor=current_user,
    )


@v1_router.get("/links/{link_id}/spends", response_model=list[TrackingSpendRead])
async def list_tracking_spends_v1(
    link_id: UUID,
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TrackingSpendRead]:
    return await TrackingService(db).list_spends(
        link_id=link_id,
        actor=current_user,
        date_from=date_from,
        date_to=date_to,
    )


@v1_router.post(
    "/links/{link_id}/spends",
    response_model=TrackingSpendRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_tracking_spend_v1(
    link_id: UUID,
    data: TrackingSpendCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrackingSpendRead:
    return await TrackingService(db).add_spend(
        link_id=link_id,
        data=data,
        actor=current_user,
    )


@v1_router.patch("/spends/{spend_id}", response_model=TrackingSpendRead)
async def update_tracking_spend_v1(
    spend_id: UUID,
    data: TrackingSpendUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrackingSpendRead:
    return await TrackingService(db).update_spend(
        spend_id=spend_id,
        data=data,
        actor=current_user,
    )


@v1_router.delete("/spends/{spend_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tracking_spend_v1(
    spend_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await TrackingService(db).delete_spend(
        spend_id=spend_id,
        actor=current_user,
    )
