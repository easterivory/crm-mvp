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


class MessageOut(OrmBase):
    id: uuid.UUID
    chat_id: uuid.UUID
    external_message_id: Optional[str]
    message_type: str
    sender_type: str
    sender_id: Optional[uuid.UUID]
    body: Optional[str]
    created_at: datetime
