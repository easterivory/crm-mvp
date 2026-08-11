from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class BuyerBotConfigOut(BaseModel):
    token: Optional[str] = None
    username: Optional[str] = None


class BuyerBotConfigUpdate(BaseModel):
    token: Optional[str] = Field(default=None, max_length=255)
    username: Optional[str] = Field(default=None, max_length=255)

    @field_validator("token", "username", mode="before")
    @classmethod
    def trim_optional_string(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: Optional[str]) -> Optional[str]:
        return value.removeprefix("@") if value else value


TranslationProvider = Literal["deepl", "google", "libretranslate"]


class TranslationProviderConfigOut(BaseModel):
    provider: Optional[TranslationProvider] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None


class TranslationProviderConfigUpdate(BaseModel):
    provider: Optional[TranslationProvider] = None
    api_key: Optional[str] = Field(default=None, max_length=500)
    base_url: Optional[str] = Field(default=None, max_length=500)

    @field_validator("api_key", "base_url", mode="before")
    @classmethod
    def trim_optional_string(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class SystemGlobalConfigOut(BaseModel):
    tg_backup_bot_token: Optional[str] = None
    tg_backup_channel_id: Optional[str] = None
    is_tg_backup_enabled: bool = False
    admin_bot_token: Optional[str] = None
    channel_join_auto_start: bool = True
    channel_join_auto_approve: bool = True


class SystemGlobalConfigUpdate(BaseModel):
    tg_backup_bot_token: Optional[str] = Field(default=None, max_length=255)
    tg_backup_channel_id: Optional[str] = Field(default=None, max_length=100)
    is_tg_backup_enabled: bool = False
    admin_bot_token: Optional[str] = Field(default=None, max_length=255)
    channel_join_auto_start: bool = True
    channel_join_auto_approve: bool = True

    @field_validator(
        "tg_backup_bot_token",
        "tg_backup_channel_id",
        "admin_bot_token",
        mode="before",
    )
    @classmethod
    def trim_global_optional_string(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class BackupJobOut(BaseModel):
    job_id: str


class ServerLogExportOut(BaseModel):
    file_name: str
    size_bytes: int
    period_minutes: int = 30


class FunnelStartRecoveryIn(BaseModel):
    lookback_hours: int = Field(default=24, ge=1, le=24 * 30)
    limit: int = Field(default=500, ge=1, le=5000)


class FunnelStartRecoveryOut(BaseModel):
    lookback_hours: int
    scanned: int
    eligible: int
    enqueued: int
    already_enqueued: int
    queue_failed: int
    already_running: int
    completed_current_cycle: int
    fresh_lifecycles: int
    scheduled: int
