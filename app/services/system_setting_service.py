from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.system_setting import SystemSetting

BUYER_BOT_TOKEN_KEY = "buyer_bot_token"
BUYER_BOT_USERNAME_KEY = "buyer_bot_username"


@dataclass(frozen=True, slots=True)
class BuyerBotConfig:
    token: Optional[str]
    username: Optional[str]


class SystemSettingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_value(self, key: str, default: Optional[str] = None) -> Optional[str]:
        normalized_key = self._normalize_key(key)
        result = await self.db.execute(
            select(SystemSetting.value).where(SystemSetting.key == normalized_key)
        )
        value = result.scalar_one_or_none()
        return default if value is None else value

    async def set_value(self, key: str, value: Optional[str]) -> None:
        normalized_key = self._normalize_key(key)
        setting = await self.db.get(SystemSetting, normalized_key)
        if setting is None:
            self.db.add(SystemSetting(key=normalized_key, value=value))
        else:
            setting.value = value
        await self.db.flush()

    async def get_buyer_bot_config(self) -> BuyerBotConfig:
        token = await self.get_value(BUYER_BOT_TOKEN_KEY)
        username = await self.get_value(BUYER_BOT_USERNAME_KEY)
        return BuyerBotConfig(
            token=self._normalize_optional_value(token),
            username=self._normalize_username(username),
        )

    async def get_effective_buyer_bot_config(self) -> BuyerBotConfig:
        db_config = await self.get_buyer_bot_config()
        return BuyerBotConfig(
            token=db_config.token or self._normalize_optional_value(settings.BUYER_BOT_TOKEN),
            username=db_config.username or self._normalize_username(settings.BUYER_BOT_USERNAME),
        )

    async def set_buyer_bot_config(
        self,
        *,
        token: Optional[str],
        username: Optional[str],
    ) -> BuyerBotConfig:
        await self.set_value(BUYER_BOT_TOKEN_KEY, self._normalize_optional_value(token))
        await self.set_value(BUYER_BOT_USERNAME_KEY, self._normalize_username(username))
        return await self.get_buyer_bot_config()

    @staticmethod
    def _normalize_key(key: str) -> str:
        normalized = key.strip()
        if not normalized:
            raise ValueError("System setting key must not be empty")
        if len(normalized) > 100:
            raise ValueError("System setting key must be 100 characters or fewer")
        return normalized

    @staticmethod
    def _normalize_optional_value(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @classmethod
    def _normalize_username(cls, username: Optional[str]) -> Optional[str]:
        normalized = cls._normalize_optional_value(username)
        return normalized.removeprefix("@") if normalized else None
