from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from app.schemas.common import OrmBase


class ScheduledMessageOut(OrmBase):
    id: uuid.UUID
    project_id: uuid.UUID
    chat_id: uuid.UUID
    created_by_user_id: uuid.UUID
    scheduled_at: datetime
    text: Optional[str]
    original_text: Optional[str]
    media_type: str
    file_name: Optional[str]
    mime_type: Optional[str]
    file_size: Optional[int]
    auto_translate: bool
    status: str
    attempts: int
    last_error: Optional[str]
    sent_message_id: Optional[uuid.UUID]
    created_at: datetime
