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
    chats_retained: int
    chats_expired: int
    answered_chats: int
    unanswered_chats: int
    average_first_response_seconds: float
    submitted_leads: int
    submissions_total: int
    manual_submissions: int
    auto_submissions: int
    valid_leads: int
    funnels_pushed: int
    returned_to_funnel: int
    registrations: int
    deposits: int
    redeposits: int
    taken_to_submitted_percent: float
    submitted_to_valid_percent: float
    taken_to_valid_percent: float
