import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.schemas.common import OrmBase


class BotCreate(BaseModel):
    # Temporary backwards compatibility: existing frontend omits project_id,
    # so BotService falls back to the authenticated project for now.
    project_id: Optional[uuid.UUID] = None
    name: Optional[str] = Field(None, max_length=255)
    telegram_token: Optional[str] = Field(None, max_length=255)
    # Ignored by BotService. Kept only so old clients do not fail validation.
    bot_username: Optional[str] = Field(None, max_length=255)
    crm_description: Optional[str] = Field(None, max_length=4096)
    telegram_description: Optional[str] = Field(None, max_length=512)
    telegram_about: Optional[str] = Field(None, max_length=120)
    transport_type: str = Field(default="bot_api", pattern="^(bot_api|user_mtproto)$")


class BotUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    telegram_token: Optional[str] = Field(None, max_length=255)
    # Ignored by BotService. Telegram getMe is the source of truth.
    bot_username: Optional[str] = Field(None, max_length=255)
    crm_description: Optional[str] = Field(None, max_length=4096)
    telegram_description: Optional[str] = Field(None, max_length=512)
    telegram_about: Optional[str] = Field(None, max_length=120)


class BotOut(OrmBase):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    transport_type: str = "bot_api"
    has_telegram_token: bool
    telegram_bot_id: Optional[int] = None
    telegram_first_name: Optional[str] = None
    bot_username: Optional[str]
    crm_description: Optional[str] = None
    telegram_description: Optional[str] = None
    telegram_about: Optional[str] = None
    active_funnel_id: Optional[uuid.UUID] = None
    active_funnel_version_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime
    is_deleted: bool
    # Present only on create/update when Telegram accepted getMe but a
    # follow-up setup call (normally setWebhook) still needs attention.
    telegram_setup_warning: Optional[str] = None


class TelegramAccountConnectIn(BaseModel):
    api_id: int = Field(..., gt=0)
    api_hash: str = Field(..., min_length=32, max_length=32, pattern="^[0-9a-fA-F]{32}$")
    phone_number: str = Field(..., min_length=7, max_length=32)


class TelegramAccountCodeIn(BaseModel):
    code: str = Field(..., min_length=3, max_length=16)


class TelegramAccountPasswordIn(BaseModel):
    password: str = Field(..., min_length=1, max_length=256)


class TelegramAccountConnectionOut(BaseModel):
    bot_id: uuid.UUID
    auth_status: str
    connection_status: str
    api_id: Optional[int] = None
    api_hash_last_four: Optional[str] = None
    phone_number_masked: Optional[str] = None
    telegram_user_id: Optional[int] = None
    telegram_first_name: Optional[str] = None
    telegram_last_name: Optional[str] = None
    telegram_username: Optional[str] = None
    auth_expires_at: Optional[datetime] = None
    last_connected_at: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None
    last_error: Optional[str] = None


class BotWebhookOut(BaseModel):
    ok: bool
    webhook_url: str
    telegram_response: dict[str, Any]


class BotTelegramStatusOut(BaseModel):
    bot_id: uuid.UUID
    project_id: uuid.UUID
    telegram_bot_id: Optional[int] = None
    bot_username: Optional[str] = None
    telegram_first_name: Optional[str] = None
    get_me: dict[str, Any]
    webhook_info: dict[str, Any]
    identity_matches_crm: bool
    expected_webhook_url: str
    webhook_matches_expected: bool


class BotStepOut(OrmBase):
    id: uuid.UUID
    bot_version_id: uuid.UUID
    step_type: str
    config: dict[str, Any]
    next_step_id: Optional[uuid.UUID]
    fallback_step_id: Optional[uuid.UUID]
    created_at: datetime
    updated_at: datetime
