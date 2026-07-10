from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel


class ManagerPerformanceOut(BaseModel):
    manager_id: uuid.UUID
    name: str
    email: str
    handler_code: Optional[str] = None
    chats_taken: int
    submitted_leads: int
    valid_leads: int
    funnels_pushed: int
    returned_to_funnel: int
    taken_to_submitted_percent: float
    submitted_to_valid_percent: float
    taken_to_valid_percent: float
