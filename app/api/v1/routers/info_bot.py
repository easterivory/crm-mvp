import json
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user, get_db
from app.core.constants import RoleName
from app.models.bot import Bot
from app.models.user import User
from app.services.admin_bot_service import AdminTelegramClient
from app.services.ai_credential_service import AICredentialService
from app.services.info_bot_config import INFO_BOT_KEY, InfoBotConfigService
from app.services.system_setting_service import SystemSettingService

router = APIRouter(prefix="/settings/info-bot", tags=["settings"])


class InfoBotSettings(BaseModel):
    enabled: bool = False
    token: str | None = Field(default=None, max_length=255)
    clear_token: bool = False


def require_super_admin(user: User):
    if user.role_name != RoleName.SUPER_ADMIN:
        raise HTTPException(403, "Доступ только для суперадминистратора.")


@router.get("")
async def get_info_bot(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    require_super_admin(user)
    return InfoBotConfigService.public(await InfoBotConfigService(db).read())


@router.patch("")
async def save_info_bot(data: InfoBotSettings, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    require_super_admin(user)
    token = (data.token or "").strip()
    profile = None
    if token:
        if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
            raise HTTPException(422, "Неверный формат токена Telegram.")
        # Authentication opened a read transaction; do not keep it during HTTPS.
        await db.rollback()
        client = AdminTelegramClient(token)
        try:
            profile = await client.get_me()
            webhook = await client._post("getWebhookInfo", {})
            if (webhook.get("result") or {}).get("url"):
                raise HTTPException(422, "У этого бота уже установлен webhook. Используйте нового отдельного бота.")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, "Telegram не подтвердил токен. Проверьте токен и доступность Telegram.") from None
        finally:
            await client.close()
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": INFO_BOT_KEY})
    service = InfoBotConfigService(db)
    current = await service.read()
    config = dict(current)
    if token:
        settings_service = SystemSettingService(db)
        global_config = await settings_service.get_effective_global_config()
        buyer = await settings_service.get_effective_buyer_bot_config()
        bot_id = token.split(":", 1)[0]
        existing = await db.scalar(select(Bot.id).where(Bot.telegram_token.like(f"{bot_id}:%")).limit(1))
        other_tokens = (global_config.admin_bot_token, global_config.tg_backup_bot_token, buyer.token)
        if any(value and value.split(":", 1)[0] == bot_id for value in other_tokens) or existing:
            raise HTTPException(422, "Для инфобота нужен отдельный бот, не подключённый к CRM, алертам или бэкапам.")
        config.update(encrypted_token=AICredentialService().encrypt(token), username=profile.get("username"))
    elif data.clear_token:
        config = {}
    if data.enabled and not config.get("encrypted_token"):
        raise HTTPException(422, "Укажите токен отдельного инфобота.")
    config["enabled"] = data.enabled
    await service.settings.set_value(INFO_BOT_KEY, json.dumps(config))
    return service.public(config)
