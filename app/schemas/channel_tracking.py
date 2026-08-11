from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import OrmBase


class TelegramChannelCreate(BaseModel):
    tracker_bot_id: UUID
    telegram_chat_id: str = Field(..., min_length=1, max_length=255)

    @field_validator("telegram_chat_id")
    @classmethod
    def normalize_chat_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("telegram_chat_id must not be empty")
        if not normalized.startswith("@"):
            try:
                int(normalized)
            except ValueError as exc:
                raise ValueError(
                    "telegram_chat_id must be a numeric channel ID or @username"
                ) from exc
        return normalized


class TelegramChannelOut(OrmBase):
    id: UUID
    project_id: UUID
    tracker_bot_id: UUID
    telegram_chat_id: int
    title: str
    username: Optional[str] = None
    description: Optional[str] = None
    is_active: bool
    bot_is_admin: bool
    can_invite_users: bool
    verified_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class TelegramChannelEventOut(OrmBase):
    id: UUID
    channel_id: UUID
    tracking_link_id: Optional[UUID] = None
    telegram_user_id: int
    event_type: str
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    occurred_at: datetime


class TelegramChannelMetricsOut(BaseModel):
    join_requests: int = 0
    joins: int = 0
    leaves: int = 0
    active_subscribers: int = 0
    click_to_join_percent: float = 0.0
