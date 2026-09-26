from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.channel_tracking import (
    TelegramChannelCreate,
    TelegramChannelEventOut,
    TelegramChannelOut,
    TelegramChannelPolicyUpdate,
)
from app.services.channel_tracking_service import ChannelTrackingService


router = APIRouter(
    prefix="/projects/{project_id}/telegram-channels",
    tags=["channel-tracking"],
)


@router.patch("/{channel_id}/funnel-policy", response_model=TelegramChannelOut)
async def update_channel_funnel_policy(
    project_id: UUID, channel_id: UUID, data: TelegramChannelPolicyUpdate,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> TelegramChannelOut:
    if current_user.role_name != "super_admin":
        raise HTTPException(status_code=403, detail="Only super_admin can change channel funnel policy")
    channel = await ChannelTrackingService(db).get_channel(
        project_id=project_id, channel_id=channel_id, require_active=True,
    )
    channel.restart_funnel_on_rejoin = data.restart_funnel_on_rejoin
    channel.start_funnel_on_direct_join = data.start_funnel_on_direct_join
    await db.flush()
    return TelegramChannelOut.model_validate(channel)


@router.get("", response_model=list[TelegramChannelOut])
async def list_telegram_channels(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TelegramChannelOut]:
    return await ChannelTrackingService(db).list_channels(
        project_id=project_id,
        actor=current_user,
    )


@router.post("", response_model=TelegramChannelOut, status_code=status.HTTP_201_CREATED)
async def create_telegram_channel(
    project_id: UUID,
    data: TelegramChannelCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TelegramChannelOut:
    return await ChannelTrackingService(db).create_or_update_channel(
        project_id=project_id,
        data=data,
        actor=current_user,
    )


@router.post("/{channel_id}/verify", response_model=TelegramChannelOut)
async def verify_telegram_channel(
    project_id: UUID,
    channel_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TelegramChannelOut:
    return await ChannelTrackingService(db).verify_channel(
        project_id=project_id,
        channel_id=channel_id,
        actor=current_user,
    )


@router.get("/{channel_id}/avatar", response_class=Response)
async def get_telegram_channel_avatar(
    project_id: UUID,
    channel_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    content, media_type = await ChannelTrackingService(db).resolve_channel_avatar(
        project_id=project_id,
        channel_id=channel_id,
        actor=current_user,
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/events", response_model=list[TelegramChannelEventOut])
async def list_telegram_channel_events(
    project_id: UUID,
    channel_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TelegramChannelEventOut]:
    return await ChannelTrackingService(db).list_recent_events(
        project_id=project_id,
        channel_id=channel_id,
        limit=limit,
        actor=current_user,
    )


@router.delete(
    "/{channel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_telegram_channel(
    project_id: UUID,
    channel_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await ChannelTrackingService(db).deactivate_channel(
        project_id=project_id,
        channel_id=channel_id,
        actor=current_user,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
