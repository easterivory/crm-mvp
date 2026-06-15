from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user, get_db
from app.core.constants import RoleName
from app.models.user import User
from app.schemas.system_setting import BuyerBotConfigOut, BuyerBotConfigUpdate
from app.services.system_setting_service import SystemSettingService

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/buyer-bot", response_model=BuyerBotConfigOut)
async def get_buyer_bot_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BuyerBotConfigOut:
    _ensure_settings_admin(current_user)
    config = await SystemSettingService(db).get_buyer_bot_config()
    return BuyerBotConfigOut(token=config.token, username=config.username)


@router.patch("/buyer-bot", response_model=BuyerBotConfigOut)
async def update_buyer_bot_settings(
    data: BuyerBotConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BuyerBotConfigOut:
    _ensure_settings_admin(current_user)
    service = SystemSettingService(db)
    current = await service.get_buyer_bot_config()
    values = data.model_dump(exclude_unset=True)
    config = await service.set_buyer_bot_config(
        token=values.get("token", current.token),
        username=values.get("username", current.username),
    )
    await db.commit()
    return BuyerBotConfigOut(token=config.token, username=config.username)


def _ensure_settings_admin(current_user: User) -> None:
    if current_user.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin/super_admin can manage system settings",
        )
