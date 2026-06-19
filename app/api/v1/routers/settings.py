from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user, get_db
from app.core.constants import RoleName
from app.models.user import User
from app.schemas.system_setting import (
    BuyerBotConfigOut,
    BuyerBotConfigUpdate,
    TranslationProviderConfigOut,
    TranslationProviderConfigUpdate,
)
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


@router.get("/translation", response_model=TranslationProviderConfigOut)
async def get_translation_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TranslationProviderConfigOut:
    _ensure_settings_admin(current_user)
    config = await SystemSettingService(db).get_translation_provider_config()
    return TranslationProviderConfigOut(
        provider=config.provider,
        api_key=config.api_key,
        base_url=config.base_url,
    )


@router.patch("/translation", response_model=TranslationProviderConfigOut)
async def update_translation_settings(
    data: TranslationProviderConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TranslationProviderConfigOut:
    _ensure_settings_admin(current_user)
    service = SystemSettingService(db)
    current = await service.get_translation_provider_config()
    values = data.model_dump(exclude_unset=True)
    config = await service.set_translation_provider_config(
        provider=values.get("provider", current.provider),
        api_key=values.get("api_key", current.api_key),
        base_url=values.get("base_url", current.base_url),
    )
    await db.commit()
    return TranslationProviderConfigOut(
        provider=config.provider,
        api_key=config.api_key,
        base_url=config.base_url,
    )


def _ensure_settings_admin(current_user: User) -> None:
    if current_user.role_name not in {RoleName.SUPER_ADMIN, RoleName.ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admin/super_admin can manage system settings",
        )
