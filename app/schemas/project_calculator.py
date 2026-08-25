from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class ProjectCalculatorSnapshotOut(BaseModel):
    project_id: UUID
    project_name: str
    project_format: Literal["submission", "gambling"]
    bot_id: UUID | None = None
    date_from: date
    date_to: date
    clicks: int = 0
    starts: int = 0
    leads: int = 0
    submitted_leads: int = 0
    registrations: int = 0
    first_deposits: int = 0
    redeposits: int = 0
    channel_join_requests: int = 0
    channel_joins: int = 0
    spend: Decimal = Decimal("0")
