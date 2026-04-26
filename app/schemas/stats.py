import uuid
from datetime import date, datetime
from typing import Optional

from app.schemas.common import OrmBase


class DailyStatsOut(OrmBase):
    id: uuid.UUID
    project_id: uuid.UUID
    date: date
    new_chats: int
    processed_chats: int
    qualified_chats: int
    lost_chats: int
    avg_response_time_sec: Optional[int]
    created_at: datetime
