import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.core.constants import TrackingConversionStatus


class TrackingMetricSummary(BaseModel):
    clicks: int = 0
    starts: int = 0
    leads: int = 0
    submitted_leads: int = 0
    deposits: int = 0
    spend: Decimal = Decimal("0")
    cr_to_lead: Decimal = Decimal("0")
    cr_to_submit: Decimal = Decimal("0")
    cr_to_deposit: Decimal = Decimal("0")
    cpl: Decimal = Decimal("0")
    cpsl: Decimal = Decimal("0")
    cpd: Decimal = Decimal("0")


class TrackingDailyMetric(BaseModel):
    date: date
    clicks: int = 0
    starts: int = 0
    leads: int = 0
    submitted_leads: int = 0
    deposits: int = 0
    spend: Decimal = Decimal("0")


class TrackingLinkMetric(BaseModel):
    link_id: uuid.UUID
    code: str
    title: str
    buyer_name: Optional[str] = None
    ad_type: Optional[str] = None
    payment_type: Optional[str] = None
    is_active: bool
    base_conversion_rate: float
    min_sample_size: int
    conversion_status: TrackingConversionStatus
    summary: TrackingMetricSummary


class TrackingBreakdownItem(BaseModel):
    key: str
    label: str
    count: int
    percent: Decimal


class TrackingFunnelStepItem(BaseModel):
    step_key: str
    label: str
    count: int
    dropoff_count: int
    dropoff_percent: Decimal


class TrackingProjectMetricsResponse(BaseModel):
    project_id: uuid.UUID
    bot_id: Optional[uuid.UUID] = None
    date_from: date
    date_to: date
    tracking_lead_status_codes: list[str] = Field(default_factory=list)
    summary: TrackingMetricSummary
    unattributed_summary: TrackingMetricSummary = Field(default_factory=TrackingMetricSummary)
    unattributed_daily: list[TrackingDailyMetric] = Field(default_factory=list)
    links: list[TrackingLinkMetric]
    daily: list[TrackingDailyMetric]


class TrackingLinkMetricsResponse(BaseModel):
    link_id: uuid.UUID
    project_id: uuid.UUID
    bot_id: uuid.UUID
    code: str
    title: str
    base_conversion_rate: float
    min_sample_size: int
    conversion_status: TrackingConversionStatus
    date_from: date
    date_to: date
    tracking_lead_status_codes: list[str] = Field(default_factory=list)
    summary: TrackingMetricSummary
    daily: list[TrackingDailyMetric]
    funnel_steps: list[TrackingFunnelStepItem] = []
    age_breakdown: list[TrackingBreakdownItem] = []
    country_breakdown: list[TrackingBreakdownItem] = []
