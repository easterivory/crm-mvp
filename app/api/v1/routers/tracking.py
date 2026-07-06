from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id, get_current_user, get_db
from app.core.constants import RoleName
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.tracking import (
    TrackingLinkCreate,
    TrackingFunnelStepOption,
    TrackingLinkOut,
    TrackingLinkRead,
    TrackingLinkUpdate,
    TrackingSpendCreate,
    TrackingSpendRead,
    TrackingSpendUpdate,
)
from app.schemas.tracking_metrics import (
    TrackingLinkMetricsResponse,
    TrackingMetricSummary,
    TrackingProjectMetricsResponse,
)
from app.services.tracking_metrics_service import TrackingMetricsService
from app.services.tracking_service import TrackingService

router = APIRouter(prefix="/tracking-links", tags=["tracking"])
v1_router = APIRouter(prefix="/tracking", tags=["tracking"])


@router.get("", response_model=PaginatedResponse[TrackingLinkOut])
async def list_tracking_links(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    bot_id: Optional[UUID] = Query(default=None),
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[TrackingLinkOut]:
    _ensure_legacy_tracking_access(current_user)
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrackingLinkOut:
    _ensure_legacy_tracking_access(current_user)
    return await TrackingService(db).create_link(project_id=project_id, data=data)


@router.get("/{link_id}", response_model=TrackingLinkOut)
async def get_tracking_link(
    link_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrackingLinkOut:
    _ensure_legacy_tracking_access(current_user)
    return await TrackingService(db).get_link(link_id=link_id, project_id=project_id)


@router.patch("/{link_id}", response_model=TrackingLinkOut)
async def update_tracking_link(
    link_id: UUID,
    data: TrackingLinkUpdate,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrackingLinkOut:
    _ensure_legacy_tracking_access(current_user)
    return await TrackingService(db).update_link(
        link_id=link_id,
        project_id=project_id,
        data=data,
    )


@router.delete("/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tracking_link(
    link_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    _ensure_legacy_tracking_access(current_user)
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
    _ensure_tracking_management_access(current_user)
    return await TrackingService(db).create_tracking_link(
        data=data,
        actor=current_user,
    )


@v1_router.get("/links/target-steps", response_model=list[TrackingFunnelStepOption])
async def list_tracking_target_steps_v1(
    project_id: UUID = Query(...),
    bot_id: UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TrackingFunnelStepOption]:
    return await TrackingService(db).list_target_funnel_steps(
        project_id=project_id,
        bot_id=bot_id,
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
    _ensure_tracking_management_access(current_user)
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
    _ensure_tracking_management_access(current_user)
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
    _ensure_tracking_management_access(current_user)
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
    _ensure_tracking_management_access(current_user)
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
    _ensure_tracking_management_access(current_user)
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
    _ensure_tracking_management_access(current_user)
    await TrackingService(db).delete_spend(
        spend_id=spend_id,
        actor=current_user,
    )


@v1_router.get("/metrics/project", response_model=TrackingProjectMetricsResponse)
async def get_project_tracking_metrics_v1(
    project_id: UUID = Query(...),
    bot_id: Optional[UUID] = Query(default=None),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrackingProjectMetricsResponse:
    return await TrackingMetricsService(db).get_project_metrics(
        current_user=current_user,
        project_id=project_id,
        bot_id=bot_id,
        date_from=date_from,
        date_to=date_to,
    )


@v1_router.get("/metrics/header", response_model=TrackingMetricSummary)
async def get_tracking_metrics_header_v1(
    project_id: UUID = Query(...),
    bot_id: Optional[UUID] = Query(default=None),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrackingMetricSummary:
    metrics = await TrackingMetricsService(db).get_project_metrics(
        current_user=current_user,
        project_id=project_id,
        bot_id=bot_id,
        date_from=date_from,
        date_to=date_to,
    )
    return metrics.summary


@v1_router.get("/metrics/links/{link_id}", response_model=TrackingLinkMetricsResponse)
async def get_link_tracking_metrics_v1(
    link_id: UUID,
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrackingLinkMetricsResponse:
    return await TrackingMetricsService(db).get_link_metrics(
        current_user=current_user,
        link_id=link_id,
        date_from=date_from,
        date_to=date_to,
    )


def _ensure_tracking_management_access(current_user: User) -> None:
    if current_user.role_name not in {
        RoleName.SUPER_ADMIN,
        RoleName.ADMIN,
        RoleName.OPERATOR,
        RoleName.BUYER,
    }:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current user cannot manage tracking links or spend",
        )


def _ensure_legacy_tracking_access(current_user: User) -> None:
    if current_user.role_name not in {
        RoleName.SUPER_ADMIN,
        RoleName.ADMIN,
        RoleName.OPERATOR,
    }:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Use the scoped tracking API for this role",
        )
