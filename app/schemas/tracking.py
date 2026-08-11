import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.constants import TrackingConversionStatus
from app.core.constants import TrackingCostModel
from app.core.constants import TrackingSpendSource
from app.core.facebook_events import normalize_facebook_event_mappings
from app.schemas.common import OrmBase


TELEGRAM_MESSAGE_MAX_LENGTH = 4096


def normalize_channel_request_message(value: Optional[str]) -> Optional[str]:
    normalized = (value or "").strip()
    return normalized or None


def validate_channel_request_options(
    *,
    destination_type: str,
    channel_join_request: bool,
    message_enabled: bool,
    message: Optional[str],
    auto_approve: bool,
) -> None:
    if destination_type != "channel":
        if channel_join_request or message_enabled or message or auto_approve:
            raise ValueError("Channel request options require a channel destination")
        return
    if (message_enabled or auto_approve) and not channel_join_request:
        raise ValueError(
            "Join-request message and auto-approval require channel_join_request"
        )
    if message_enabled and not message:
        raise ValueError("channel_request_message is required when messaging is enabled")


class FacebookEventTrigger(BaseModel):
    type: Literal["funnel_action", "lead_status", "lead_tag"]
    value: Optional[str] = None


class FacebookEventMapping(BaseModel):
    source_event: str = Field(..., min_length=1, max_length=50)
    event_name: str = Field(..., min_length=1, max_length=40)
    enabled: bool = True
    parameters: dict[str, str] = Field(default_factory=dict)
    triggers: Optional[list[FacebookEventTrigger]] = Field(default=None, max_length=10)


def normalize_event_mapping_models(
    value: Optional[list[FacebookEventMapping]],
) -> list[FacebookEventMapping]:
    if value is None:
        return []
    normalized = normalize_facebook_event_mappings(
        [item.model_dump() if isinstance(item, BaseModel) else item for item in value]
    )
    return [FacebookEventMapping.model_validate(item) for item in normalized]


class TrackingLinkCreate(BaseModel):
    project_id: Optional[uuid.UUID] = None
    bot_id: Optional[uuid.UUID] = None
    destination_type: Literal["bot", "channel"] = "bot"
    channel_id: Optional[uuid.UUID] = None
    channel_join_request: bool = False
    channel_request_message_enabled: bool = False
    channel_request_message: Optional[str] = Field(
        default=None,
        max_length=TELEGRAM_MESSAGE_MAX_LENGTH,
    )
    channel_auto_approve: bool = False
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
    fb_campaign_enabled: bool = False
    fb_event_mappings: list[FacebookEventMapping] = Field(default_factory=list, max_length=20)
    fb_proxy_url: Optional[str] = Field(None, max_length=2048)
    fb_test_event_code: Optional[str] = Field(None, max_length=100)
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
        if self.destination_type == "bot" and self.bot_id is None:
            raise ValueError("bot_id is required for bot tracking links")
        if self.destination_type == "channel" and self.channel_id is None:
            raise ValueError("channel_id is required for channel tracking links")
        if self.destination_type == "bot" and self.channel_id is not None:
            raise ValueError("channel_id is only available for channel tracking links")
        validate_channel_request_options(
            destination_type=self.destination_type,
            channel_join_request=self.channel_join_request,
            message_enabled=self.channel_request_message_enabled,
            message=self.channel_request_message,
            auto_approve=self.channel_auto_approve,
        )
        return self

    @field_validator("channel_request_message")
    @classmethod
    def normalize_request_message(cls, value: Optional[str]) -> Optional[str]:
        return normalize_channel_request_message(value)

    @field_validator("fb_pixel_id")
    @classmethod
    def normalize_fb_pixel_id(cls, value: Optional[str]) -> Optional[str]:
        return normalize_fb_pixel_id(value)

    @field_validator("fb_capi_token")
    @classmethod
    def normalize_fb_capi_token(cls, value: Optional[str]) -> Optional[str]:
        return normalize_fb_capi_token(value)

    @field_validator("fb_event_mappings")
    @classmethod
    def normalize_fb_event_mappings(
        cls,
        value: list[FacebookEventMapping],
    ) -> list[FacebookEventMapping]:
        return normalize_event_mapping_models(value)

    @field_validator("fb_proxy_url")
    @classmethod
    def normalize_fb_proxy_url(cls, value: Optional[str]) -> Optional[str]:
        return normalize_fb_proxy_url(value)

    @field_validator("fb_test_event_code")
    @classmethod
    def normalize_fb_test_event_code(cls, value: Optional[str]) -> Optional[str]:
        return normalize_fb_test_event_code(value)


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
    fb_campaign_enabled: Optional[bool] = None
    fb_event_mappings: Optional[list[FacebookEventMapping]] = Field(default=None, max_length=20)
    fb_proxy_url: Optional[str] = Field(None, max_length=2048)
    fb_test_event_code: Optional[str] = Field(None, max_length=100)
    is_active: Optional[bool] = None
    base_conversion_rate: Optional[float] = Field(None, ge=0, le=100)
    min_sample_size: Optional[int] = Field(None, ge=1)
    target_step_id: Optional[uuid.UUID] = None
    target_funnel_step_key: Optional[str] = Field(default=None, max_length=100)
    channel_join_request: Optional[bool] = None
    channel_request_message_enabled: Optional[bool] = None
    channel_request_message: Optional[str] = Field(
        default=None,
        max_length=TELEGRAM_MESSAGE_MAX_LENGTH,
    )
    channel_auto_approve: Optional[bool] = None

    @field_validator("channel_request_message")
    @classmethod
    def normalize_request_message(cls, value: Optional[str]) -> Optional[str]:
        return normalize_channel_request_message(value)

    @field_validator("fb_pixel_id")
    @classmethod
    def normalize_fb_pixel_id(cls, value: Optional[str]) -> Optional[str]:
        return normalize_fb_pixel_id(value)

    @field_validator("fb_capi_token")
    @classmethod
    def normalize_fb_capi_token(cls, value: Optional[str]) -> Optional[str]:
        return normalize_fb_capi_token(value)

    @field_validator("fb_event_mappings")
    @classmethod
    def normalize_fb_event_mappings(
        cls,
        value: Optional[list[FacebookEventMapping]],
    ) -> Optional[list[FacebookEventMapping]]:
        return None if value is None else normalize_event_mapping_models(value)

    @field_validator("fb_proxy_url")
    @classmethod
    def normalize_fb_proxy_url(cls, value: Optional[str]) -> Optional[str]:
        return normalize_fb_proxy_url(value)

    @field_validator("fb_test_event_code")
    @classmethod
    def normalize_fb_test_event_code(cls, value: Optional[str]) -> Optional[str]:
        return normalize_fb_test_event_code(value)


class TrackingLinkOut(OrmBase):
    id: uuid.UUID
    project_id: uuid.UUID
    bot_id: uuid.UUID
    destination_type: Literal["bot", "channel"] = "bot"
    channel_id: Optional[uuid.UUID] = None
    channel_title: Optional[str] = None
    channel_join_request: bool = False
    channel_request_message_enabled: bool = False
    channel_request_message: Optional[str] = None
    channel_auto_approve: bool = False
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
    fb_campaign_enabled: bool = False
    fb_event_mappings_json: list[dict] = Field(default_factory=list)
    has_fb_proxy: bool = False
    fb_test_event_code: Optional[str] = None
    tracking_url: str = ""
    created_at: datetime


class TrackingLinkRead(OrmBase):
    id: uuid.UUID
    project_id: uuid.UUID
    bot_id: uuid.UUID
    destination_type: Literal["bot", "channel"] = "bot"
    channel_id: Optional[uuid.UUID] = None
    channel_title: Optional[str] = None
    channel_join_request: bool = False
    channel_request_message_enabled: bool = False
    channel_request_message: Optional[str] = None
    channel_auto_approve: bool = False
    code: str
    title: str
    buyer_id: Optional[uuid.UUID] = None
    buyer_name: Optional[str] = None
    ad_type: Optional[str] = None
    payment_type: Optional[str] = None
    invite_link: Optional[str] = None
    tracking_url: Optional[str] = None
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
    fb_campaign_enabled: bool = False
    fb_event_mappings_json: list[dict] = Field(default_factory=list)
    has_fb_proxy: bool = False
    fb_test_event_code: Optional[str] = None
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


def normalize_fb_proxy_url(value: Optional[str]) -> Optional[str]:
    from urllib.parse import urlsplit

    normalized = (value or "").strip()
    if not normalized:
        return None
    if any(character in normalized for character in ("\r", "\n", "\t")):
        raise ValueError("fb_proxy_url contains unsupported whitespace")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("fb_proxy_url must be an http(s) proxy URL")
    if parsed.query or parsed.fragment:
        raise ValueError("fb_proxy_url must not contain query parameters or fragments")
    return normalized


def normalize_fb_test_event_code(value: Optional[str]) -> Optional[str]:
    normalized = (value or "").strip()
    if not normalized:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", normalized):
        raise ValueError("fb_test_event_code contains unsupported characters")
    return normalized


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
