from __future__ import annotations

import hmac
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id, get_current_user, get_db
from app.core.config import settings
from app.core.constants import RoleName
from app.models.user import User
from app.schemas.buyer import BuyerFunnelDropOffStepOut, BuyerPerformanceOut
from app.schemas.manager_analytics import ManagerPerformanceOut
from app.services.buyer_analytics_service import BuyerAnalyticsService
from app.services.manager_analytics_service import ManagerAnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/buyers/funnel-drop-off", response_model=list[BuyerFunnelDropOffStepOut])
async def get_buyer_funnel_drop_off(
    buyer_telegram_id: int = Query(..., gt=0),
    token: str | None = Query(default=None),
    x_buyer_bot_token: str | None = Header(default=None, alias="X-Buyer-Bot-Token"),
    db: AsyncSession = Depends(get_db),
) -> list[BuyerFunnelDropOffStepOut]:
    _verify_buyer_bot_token(query_token=token, header_token=x_buyer_bot_token)
    return await BuyerAnalyticsService(db).get_funnel_dropoff_by_telegram_id(
        buyer_telegram_id=buyer_telegram_id,
    )


@router.get("/buyers", response_model=list[BuyerPerformanceOut])
async def get_buyers_performance(
    bot_id: UUID | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BuyerPerformanceOut]:
    _ensure_admin(current_user)
    return await BuyerAnalyticsService(db).get_project_performance(
        project_id=project_id,
        bot_id=bot_id,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/managers", response_model=list[ManagerPerformanceOut])
async def get_managers_performance(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ManagerPerformanceOut]:
    _ensure_admin(current_user)
    return await ManagerAnalyticsService(db).get_project_performance(
        project_id=project_id,
        date_from=date_from,
        date_to=date_to,
    )


def _verify_buyer_bot_token(
    *,
    query_token: str | None,
    header_token: str | None,
) -> None:
    expected = (settings.BUYER_BOT_INTERNAL_TOKEN or "").strip()
    if not expected:
        return

    provided = (header_token or query_token or "").strip()
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid buyer bot token",
        )


def _ensure_admin(user: User) -> None:
    if user.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin/super_admin can read buyer analytics",
        )
