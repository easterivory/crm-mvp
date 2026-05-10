import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.core.constants import TrackingCostModel
from app.schemas.common import OrmBase


class TrackingLinkCreate(BaseModel):
    bot_id: uuid.UUID
    name: str = Field(..., max_length=255)
    ref_code: Optional[str] = Field(None, max_length=100)
    cost_model: TrackingCostModel = TrackingCostModel.FIX_PDP
    price_per_unit: Decimal = Field(default=Decimal("0"), ge=0)
    spend: Decimal = Field(default=Decimal("0"), ge=0)
    target_step_id: Optional[uuid.UUID] = None


class TrackingLinkCostUpdate(BaseModel):
    cost_model: Optional[TrackingCostModel] = None
    price_per_unit: Optional[Decimal] = Field(None, ge=0)
    spend: Optional[Decimal] = Field(None, ge=0)


class TrackingLinkUpdate(TrackingLinkCostUpdate):
    name: Optional[str] = Field(None, max_length=255)
    ref_code: Optional[str] = Field(None, max_length=100)
    target_step_id: Optional[uuid.UUID] = None


class TrackingLinkOut(OrmBase):
    id: uuid.UUID
    project_id: uuid.UUID
    bot_id: uuid.UUID
    name: str
    ref_code: str
    cost_model: TrackingCostModel
    price_per_unit: Decimal
    spend: Decimal
    target_step_id: Optional[uuid.UUID]
    tracking_url: str = ""
    created_at: datetime


class TrafficStatsOut(BaseModel):
    tracking_link_id: uuid.UUID
    name: str
    ref_code: str
    cost_model: TrackingCostModel
    clicks: int
    impressions: int
    leads: int
    spend: Decimal
    cpl: Decimal
