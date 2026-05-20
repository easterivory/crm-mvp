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
    telegram_token: str = Field(..., max_length=255)
    bot_username: Optional[str] = Field(None, max_length=255)


class BotUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    telegram_token: Optional[str] = Field(None, max_length=255)
    bot_username: Optional[str] = Field(None, max_length=255)


class BotOut(OrmBase):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    has_telegram_token: bool
    bot_username: Optional[str]
    active_funnel_id: Optional[uuid.UUID] = None
    active_funnel_version_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime
    is_deleted: bool


class BotWebhookOut(BaseModel):
    ok: bool
    webhook_url: str
    telegram_response: dict[str, Any]


class BotStepOut(OrmBase):
    id: uuid.UUID
    bot_version_id: uuid.UUID
    step_type: str
    config: dict[str, Any]
    next_step_id: Optional[uuid.UUID]
    fallback_step_id: Optional[uuid.UUID]
    created_at: datetime
    updated_at: datetime
