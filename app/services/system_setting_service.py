from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.system_setting import SystemSetting

BUYER_BOT_TOKEN_KEY = "buyer_bot_token"
BUYER_BOT_USERNAME_KEY = "buyer_bot_username"
TRANSLATION_PROVIDER_KEY = "translation_provider"
TRANSLATION_API_KEY = "translation_api_key"
TRANSLATION_BASE_URL_KEY = "translation_base_url"


@dataclass(frozen=True, slots=True)
class BuyerBotConfig:
    token: Optional[str]
    username: Optional[str]


@dataclass(frozen=True, slots=True)
class TranslationProviderConfig:
    provider: Optional[str]
    api_key: Optional[str]
    base_url: Optional[str]


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

    async def get_translation_provider_config(self) -> TranslationProviderConfig:
        provider = await self.get_value(TRANSLATION_PROVIDER_KEY)
        api_key = await self.get_value(TRANSLATION_API_KEY)
        base_url = await self.get_value(TRANSLATION_BASE_URL_KEY)
        return TranslationProviderConfig(
            provider=self._normalize_translation_provider(provider),
            api_key=self._normalize_optional_value(api_key),
            base_url=self._normalize_optional_value(base_url),
        )

    async def set_translation_provider_config(
        self,
        *,
        provider: Optional[str],
        api_key: Optional[str],
        base_url: Optional[str],
    ) -> TranslationProviderConfig:
        await self.set_value(TRANSLATION_PROVIDER_KEY, self._normalize_translation_provider(provider))
        await self.set_value(TRANSLATION_API_KEY, self._normalize_optional_value(api_key))
        await self.set_value(TRANSLATION_BASE_URL_KEY, self._normalize_optional_value(base_url))
        return await self.get_translation_provider_config()

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

    @classmethod
    def _normalize_translation_provider(cls, provider: Optional[str]) -> Optional[str]:
        normalized = cls._normalize_optional_value(provider)
        if normalized is None:
            return None
        aliases = {
            "deepl": "deepl",
            "deep-l": "deepl",
            "google": "google",
            "google-translate": "google",
            "libre": "libretranslate",
            "libre-translate": "libretranslate",
            "libretranslate": "libretranslate",
        }
        return aliases.get(normalized.lower().replace("_", "-"))
