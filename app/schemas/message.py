import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.core.constants import MessageType, SenderType
from app.schemas.common import OrmBase


class MessageCreate(BaseModel):
    external_message_id: Optional[str] = Field(None, max_length=255)
    message_type: str = Field(default=MessageType.TEXT, max_length=30)
    sender_type: str = Field(..., max_length=20)
    sender_id: Optional[uuid.UUID] = None
    body: Optional[str] = None
    caption: Optional[str] = None
    telegram_file_id: Optional[str] = Field(None, max_length=512)
    file_unique_id: Optional[str] = Field(None, max_length=255)
    file_name: Optional[str] = Field(None, max_length=512)
    mime_type: Optional[str] = Field(None, max_length=255)
    file_size: Optional[int] = None
    media_group_id: Optional[str] = Field(None, max_length=255)
    raw_payload_json: Optional[dict] = None
    reply_markup: Optional[dict] = None


class MessageOut(OrmBase):
    id: uuid.UUID
    chat_id: uuid.UUID
    external_message_id: Optional[str]
    message_type: str
    sender_type: str
    sender_id: Optional[uuid.UUID]
    body: Optional[str]
    caption: Optional[str] = None
    telegram_file_id: Optional[str] = None
    file_unique_id: Optional[str] = None
    file_name: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    media_group_id: Optional[str] = None
    created_at: datetime
