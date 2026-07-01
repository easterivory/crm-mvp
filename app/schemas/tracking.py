import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.constants import TrackingConversionStatus
from app.core.constants import TrackingCostModel
from app.core.constants import TrackingSpendSource
from app.schemas.common import OrmBase


class TrackingLinkCreate(BaseModel):
    project_id: Optional[uuid.UUID] = None
    bot_id: uuid.UUID
    title: Optional[str] = Field(None, max_length=255)
    name: Optional[str] = Field(None, max_length=255)
    code: Optional[str] = Field(None, max_length=100)
    ref_code: Optional[str] = Field(None, max_length=100)
    buyer_id: Optional[uuid.UUID] = None
    buyer_name: Optional[str] = Field(None, max_length=255)
    ad_type: Optional[str] = Field(None, max_length=100)
    payment_type: Optional[str] = Field(None, max_length=100)
    invite_link: Optional[str] = None
    fb_pixel_id: Optional[str] = Field(None, max_length=50)
    fb_capi_token: Optional[str] = Field(None, max_length=4096)
    cost_model: TrackingCostModel = TrackingCostModel.CPM
    price_per_unit: Decimal = Field(default=Decimal("0"), ge=0)
    spend: Decimal = Field(default=Decimal("0"), ge=0)
    base_conversion_rate: float = Field(default=10.0, ge=0, le=100)
    min_sample_size: int = Field(default=500, ge=1)
    target_step_id: Optional[uuid.UUID] = None
    target_funnel_step_key: Optional[str] = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def require_title_or_name(self) -> "TrackingLinkCreate":
        if not (self.title or self.name):
            raise ValueError("title is required")
        return self

    @field_validator("fb_pixel_id")
    @classmethod
    def normalize_fb_pixel_id(cls, value: Optional[str]) -> Optional[str]:
        return normalize_fb_pixel_id(value)

    @field_validator("fb_capi_token")
    @classmethod
    def normalize_fb_capi_token(cls, value: Optional[str]) -> Optional[str]:
        return normalize_fb_capi_token(value)


class TrackingLinkCostUpdate(BaseModel):
    cost_model: Optional[TrackingCostModel] = None
    price_per_unit: Optional[Decimal] = Field(None, ge=0)
    spend: Optional[Decimal] = Field(None, ge=0)


class TrackingLinkUpdate(TrackingLinkCostUpdate):
    name: Optional[str] = Field(None, max_length=255)
    title: Optional[str] = Field(None, max_length=255)
    code: Optional[str] = Field(None, max_length=100)
    ref_code: Optional[str] = Field(None, max_length=100)
    buyer_id: Optional[uuid.UUID] = None
    buyer_name: Optional[str] = Field(None, max_length=255)
    ad_type: Optional[str] = Field(None, max_length=100)
    payment_type: Optional[str] = Field(None, max_length=100)
    invite_link: Optional[str] = None
    fb_pixel_id: Optional[str] = Field(None, max_length=50)
    fb_capi_token: Optional[str] = Field(None, max_length=4096)
    is_active: Optional[bool] = None
    base_conversion_rate: Optional[float] = Field(None, ge=0, le=100)
    min_sample_size: Optional[int] = Field(None, ge=1)
    target_step_id: Optional[uuid.UUID] = None
    target_funnel_step_key: Optional[str] = Field(default=None, max_length=100)

    @field_validator("fb_pixel_id")
    @classmethod
    def normalize_fb_pixel_id(cls, value: Optional[str]) -> Optional[str]:
        return normalize_fb_pixel_id(value)

    @field_validator("fb_capi_token")
    @classmethod
    def normalize_fb_capi_token(cls, value: Optional[str]) -> Optional[str]:
        return normalize_fb_capi_token(value)


class TrackingLinkOut(OrmBase):
    id: uuid.UUID
    project_id: uuid.UUID
    bot_id: uuid.UUID
    name: str
    ref_code: str
    cost_model: TrackingCostModel
    price_per_unit: Decimal
    spend: Decimal
    base_conversion_rate: float
    min_sample_size: int
    target_step_id: Optional[uuid.UUID]
    fb_pixel_id: Optional[str] = None
    has_fb_capi_token: bool = False
    tracking_url: str = ""
    created_at: datetime


class TrackingLinkRead(OrmBase):
    id: uuid.UUID
    project_id: uuid.UUID
    bot_id: uuid.UUID
    code: str
    title: str
    buyer_id: Optional[uuid.UUID] = None
    buyer_name: Optional[str] = None
    ad_type: Optional[str] = None
    payment_type: Optional[str] = None
    invite_link: Optional[str] = None
    is_active: bool
    created_by_user_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime
    cost_model: TrackingCostModel
    price_per_unit: Decimal
    spend: Decimal
    base_conversion_rate: float
    min_sample_size: int
    target_funnel_id: Optional[uuid.UUID] = None
    target_funnel_step_key: Optional[str] = None
    target_funnel_step_title: Optional[str] = None
    fb_pixel_id: Optional[str] = None
    has_fb_capi_token: bool = False
    total_spend: Optional[Decimal] = None


def normalize_fb_pixel_id(value: Optional[str]) -> Optional[str]:
    normalized = (value or "").strip()
    if not normalized:
        return None
    if not re.fullmatch(r"\d{5,50}", normalized):
        raise ValueError("fb_pixel_id must contain 5-50 digits")
    return normalized


def normalize_fb_capi_token(value: Optional[str]) -> Optional[str]:
    normalized = (value or "").strip()
    return normalized or None


class TrackingFunnelStepOption(BaseModel):
    key: str
    title: str
    step_type: str
    block_type: str
    number: int = Field(..., ge=1)


class TrackingSpendCreate(BaseModel):
    spend_date: date
    amount: Decimal = Field(..., ge=0)
    currency: Optional[str] = Field(default="USD", min_length=3, max_length=3)
    comment: Optional[str] = None


class TrackingSpendUpdate(BaseModel):
    spend_date: Optional[date] = None
    amount: Optional[Decimal] = Field(None, ge=0)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    comment: Optional[str] = None


class TrackingSpendRead(OrmBase):
    id: uuid.UUID
    tracking_link_id: uuid.UUID
    spend_date: date
    amount: Decimal
    currency: str
    comment: Optional[str] = None
    source: TrackingSpendSource
    created_by_user_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime


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
    base_conversion_rate: float
    min_sample_size: int
    conversion_status: TrackingConversionStatus
