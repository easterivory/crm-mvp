from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import OrmBase


class BuyerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be empty")
        return normalized


class BuyerUserOut(OrmBase):
    id: uuid.UUID
    email: str
    name: str
    project_id: Optional[uuid.UUID]
    role_name: Optional[str] = None
    buyer_telegram_id: Optional[int] = None
    created_at: datetime


class BuyerInviteOut(BaseModel):
    buyer: BuyerUserOut
    invite_token: uuid.UUID
    invite_link: str


class BuyerFunnelDropOffStepOut(BaseModel):
    step_id: Optional[uuid.UUID]
    step_title: str
    entered_count: int
    completed_count: int
    dropoff_count: int
    reached_percent: Decimal
    dropoff_percent: Decimal


class BuyerPerformanceOut(BaseModel):
    buyer_id: uuid.UUID
    name: str
    email: str
    buyer_telegram_id: Optional[int] = None
    links_count: int
    total_spend: Decimal
    clicks: int
    leads: int
    lead_conversion_percent: Decimal
    cpl: Decimal
    submitted_leads: int
    submitted_conversion_percent: Decimal
    project_format: str = "submission"
    registrations: int = 0
    first_deposits: int = 0
    redeposits: int = 0
