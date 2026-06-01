import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.chat_event_log import ChatEventLog


class ChatEventLogOut(BaseModel):
    id: uuid.UUID
    chat_id: uuid.UUID
    user_id: Optional[uuid.UUID]
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    event_type: str
    old_value: Optional[str]
    new_value: Optional[str]
    created_at: datetime

    @classmethod
    def from_event(cls, event: ChatEventLog) -> "ChatEventLogOut":
        user = event.user
        return cls(
            id=event.id,
            chat_id=event.chat_id,
            user_id=event.user_id,
            user_name=user.name if user is not None else None,
            user_email=user.email if user is not None else None,
            event_type=event.event_type,
            old_value=event.old_value,
            new_value=event.new_value,
            created_at=event.created_at,
        )
