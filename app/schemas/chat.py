import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.common import OrmBase


class ChatCreate(BaseModel):
    external_chat_id: str = Field(..., max_length=255)
    external_user_id: str = Field(..., max_length=255)
    contact_name: Optional[str] = Field(None, max_length=255)


class ChatUpdate(BaseModel):
    contact_name: Optional[str] = Field(None, max_length=255)


class ChatOut(OrmBase):
    id: uuid.UUID
    project_id: uuid.UUID
    tracking_link_id: Optional[uuid.UUID]
    external_chat_id: str
    external_user_id: str
    contact_name: Optional[str]

    last_message_at: Optional[datetime]
    last_user_message_at: Optional[datetime]
    last_manager_reply_at: Optional[datetime]
    last_read_at: Optional[datetime]

    # Computed — populated by the service layer before returning
    unread: bool = False
    unanswered: bool = False
    is_red: bool = False

    updated_at: datetime
    created_at: datetime
    is_deleted: bool


class ChatFilters(BaseModel):
    unread: Optional[bool] = None
    unanswered: Optional[bool] = None
    is_red: Optional[bool] = None
    manager_id: Optional[uuid.UUID] = None
