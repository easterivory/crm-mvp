from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import OrmBase
from app.core.facebook_events import (
    FACEBOOK_SOURCE_EVENT_DEFINITIONS,
    default_facebook_event_mappings,
)
from app.schemas.tracking import (
    FacebookEventMapping,
    normalize_event_mapping_models,
    normalize_fb_capi_token,
    normalize_fb_pixel_id,
    normalize_fb_proxy_url,
    normalize_fb_test_event_code,
)


class ProjectDomainBase(BaseModel):
    domain_name: str = Field(..., min_length=1, max_length=255)

    @field_validator("domain_name")
    @classmethod
    def normalize_domain_name(cls, value: str) -> str:
        normalized = value.strip().lower().removeprefix("http://").removeprefix("https://")
        normalized = normalized.split("/", maxsplit=1)[0].split(":", maxsplit=1)[0].rstrip(".")
        if not normalized:
            raise ValueError("domain_name must not be empty")
        return normalized


class ProjectDomainCreate(ProjectDomainBase):
    pass


class ProjectDomainOut(OrmBase):
    id: UUID
    project_id: UUID
    domain_name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class LanderPixel(BaseModel):
    provider: Literal["meta"]
    pixel_id: str = Field(..., min_length=1, max_length=120)

    @field_validator("pixel_id")
    @classmethod
    def normalize_pixel_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("pixel_id must not be empty")
        if not all(char.isascii() and (char.isalnum() or char in "._-") for char in normalized):
            raise ValueError("pixel_id contains unsupported characters")
        return normalized


class LanderMetaEvent(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or not normalized[0].isalpha() or not all(
            char.isascii() and (char.isalnum() or char == "_") for char in normalized
        ):
            raise ValueError("Meta event name must use Latin letters, numbers, or underscores")
        return normalized


class LanderTrackingCampaignCreate(BaseModel):
    bot_id: UUID
    title: str = Field(..., min_length=1, max_length=255)
    code: Optional[str] = Field(default=None, max_length=64)
    buyer_name: Optional[str] = Field(default=None, max_length=255)
    ad_type: Optional[str] = Field(default=None, max_length=100)
    payment_type: Optional[str] = Field(default=None, max_length=100)
    fb_pixel_id: Optional[str] = Field(default=None, max_length=50)
    fb_capi_token: Optional[str] = Field(default=None, max_length=4096)
    fb_proxy_url: Optional[str] = Field(default=None, max_length=2048)
    fb_test_event_code: Optional[str] = Field(default=None, max_length=100)
    fb_event_mappings: list[FacebookEventMapping] = Field(
        default_factory=lambda: [
            FacebookEventMapping.model_validate(item)
            for item in default_facebook_event_mappings()
        ],
        max_length=20,
    )
    base_conversion_rate: float = Field(default=10.0, ge=0, le=100)
    min_sample_size: int = Field(default=500, ge=1)
    target_funnel_step_key: Optional[str] = Field(default=None, max_length=100)

    @field_validator("fb_pixel_id")
    @classmethod
    def normalize_fb_pixel_id(cls, value: Optional[str]) -> Optional[str]:
        return normalize_fb_pixel_id(value)

    @field_validator("fb_capi_token")
    @classmethod
    def normalize_fb_capi_token(cls, value: Optional[str]) -> Optional[str]:
        return normalize_fb_capi_token(value)

    @field_validator("fb_proxy_url")
    @classmethod
    def normalize_fb_proxy_url(cls, value: Optional[str]) -> Optional[str]:
        return normalize_fb_proxy_url(value)

    @field_validator("fb_test_event_code")
    @classmethod
    def normalize_fb_test_event_code(cls, value: Optional[str]) -> Optional[str]:
        return normalize_fb_test_event_code(value)

    @field_validator("fb_event_mappings")
    @classmethod
    def normalize_fb_event_mappings(
        cls,
        value: list[FacebookEventMapping],
    ) -> list[FacebookEventMapping]:
        return normalize_event_mapping_models(value)


class ProjectLanderBase(BaseModel):
    domain_id: Optional[UUID] = None
    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field(..., min_length=1, max_length=32)
    slug: str = Field(..., min_length=1, max_length=100)
    tracking_link_id: Optional[UUID] = None
    campaign: Optional[LanderTrackingCampaignCreate] = None
    pixels: list[LanderPixel] = Field(default_factory=list, max_length=1)
    meta_events: list[LanderMetaEvent] = Field(default_factory=list, max_length=10)
    auto_redirect_enabled: bool = True
    utm_defaults: dict[str, str] = Field(default_factory=dict)

    @field_validator("name", "type", "slug")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("utm_defaults")
    @classmethod
    def normalize_utm_defaults(cls, value: dict[str, str]) -> dict[str, str]:
        allowed_keys = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"}
        normalized: dict[str, str] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key).strip().lower()
            item = str(raw_value).strip()
            if not item:
                continue
            if key not in allowed_keys:
                raise ValueError(f"Unsupported UTM parameter: {key}")
            if len(item) > 255:
                raise ValueError(f"UTM parameter {key} is too long")
            normalized[key] = item
        return normalized

    @model_validator(mode="after")
    def require_tracking_source(self) -> "ProjectLanderBase":
        if self.tracking_link_id is None and self.campaign is None:
            raise ValueError("tracking_link_id or campaign is required")
        if self.tracking_link_id is not None and self.campaign is not None:
            raise ValueError("Choose an existing tracking link or create a campaign, not both")
        return self


class ProjectLanderCreate(ProjectLanderBase):
    pass


class ProjectLanderUpdate(BaseModel):
    domain_id: Optional[UUID] = None
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    type: Optional[str] = Field(default=None, min_length=1, max_length=32)
    slug: Optional[str] = Field(default=None, min_length=1, max_length=100)
    pixels: Optional[list[LanderPixel]] = Field(default=None, max_length=1)
    meta_events: Optional[list[LanderMetaEvent]] = Field(default=None, max_length=10)
    utm_defaults: Optional[dict[str, str]] = None
    auto_redirect_enabled: Optional[bool] = None
    facebook_campaign: Optional["LanderFacebookCampaignUpdate"] = None

    @field_validator("name", "type", "slug")
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("utm_defaults")
    @classmethod
    def normalize_utm_defaults(
        cls,
        value: Optional[dict[str, str]],
    ) -> Optional[dict[str, str]]:
        if value is None:
            return None
        return ProjectLanderBase.normalize_utm_defaults(value)


class LanderFacebookCampaignUpdate(BaseModel):
    enabled: bool = True
    bot_id: Optional[UUID] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    code: Optional[str] = Field(default=None, min_length=1, max_length=64)
    buyer_name: Optional[str] = Field(default=None, max_length=255)
    ad_type: Optional[str] = Field(default=None, max_length=100)
    payment_type: Optional[str] = Field(default=None, max_length=100)
    base_conversion_rate: Optional[float] = Field(default=None, ge=0, le=100)
    min_sample_size: Optional[int] = Field(default=None, ge=1)
    target_funnel_step_key: Optional[str] = Field(default=None, max_length=100)
    fb_pixel_id: Optional[str] = Field(default=None, max_length=50)
    fb_capi_token: Optional[str] = Field(default=None, max_length=4096)
    clear_fb_capi_token: bool = False
    fb_proxy_url: Optional[str] = Field(default=None, max_length=2048)
    clear_fb_proxy_url: bool = False
    fb_test_event_code: Optional[str] = Field(default=None, max_length=100)
    fb_event_mappings: list[FacebookEventMapping] = Field(default_factory=list, max_length=20)

    @field_validator("fb_pixel_id")
    @classmethod
    def normalize_fb_pixel_id(cls, value: Optional[str]) -> Optional[str]:
        return normalize_fb_pixel_id(value)

    @field_validator("fb_capi_token")
    @classmethod
    def normalize_fb_capi_token(cls, value: Optional[str]) -> Optional[str]:
        return normalize_fb_capi_token(value)

    @field_validator("fb_proxy_url")
    @classmethod
    def normalize_fb_proxy_url(cls, value: Optional[str]) -> Optional[str]:
        return normalize_fb_proxy_url(value)

    @field_validator("fb_test_event_code")
    @classmethod
    def normalize_fb_test_event_code(cls, value: Optional[str]) -> Optional[str]:
        return normalize_fb_test_event_code(value)

    @field_validator("fb_event_mappings")
    @classmethod
    def normalize_fb_event_mappings(
        cls,
        value: list[FacebookEventMapping],
    ) -> list[FacebookEventMapping]:
        return normalize_event_mapping_models(value)

    @field_validator(
        "buyer_name",
        "ad_type",
        "payment_type",
        "target_funnel_step_key",
    )
    @classmethod
    def normalize_campaign_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("title", "code")
    @classmethod
    def normalize_required_campaign_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized


ProjectLanderUpdate.model_rebuild()


class LanderFacebookCampaignOut(BaseModel):
    bot_id: UUID
    title: str
    code: str
    buyer_name: Optional[str] = None
    ad_type: Optional[str] = None
    payment_type: Optional[str] = None
    base_conversion_rate: float
    min_sample_size: int
    target_funnel_step_key: Optional[str] = None


class ProjectLanderOut(OrmBase):
    id: UUID
    project_id: UUID
    domain_id: Optional[UUID]
    domain_name: Optional[str] = None
    public_url: str = ""
    name: str
    type: str
    slug: str
    tracking_link_id: Optional[UUID] = None
    pixels_json: list[dict] = Field(default_factory=list)
    meta_events_json: list[dict] = Field(default_factory=list)
    utm_defaults_json: dict[str, str] = Field(default_factory=dict)
    custom_html_path: Optional[str] = None
    auto_redirect_enabled: bool
    is_active: bool
    facebook_campaign_enabled: bool = False
    fb_pixel_id: Optional[str] = None
    has_fb_capi_token: bool = False
    has_fb_proxy: bool = False
    fb_test_event_code: Optional[str] = None
    fb_event_mappings_json: list[dict] = Field(default_factory=list)
    facebook_campaign: Optional[LanderFacebookCampaignOut] = None
    created_at: datetime
    updated_at: datetime


class ProjectLanderUploadOut(BaseModel):
    success: bool
    custom_html_path: str


class FacebookSourceEventOut(BaseModel):
    key: str
    label: str
    delivery: Literal["browser", "server"]
    trigger: Literal["automatic", "funnel"]


class LanderRuntimeConfigOut(BaseModel):
    technical_domain: str
    source_events: list[FacebookSourceEventOut] = Field(
        default_factory=lambda: [
            FacebookSourceEventOut.model_validate(item)
            for item in FACEBOOK_SOURCE_EVENT_DEFINITIONS
        ]
    )
    default_event_mappings: list[FacebookEventMapping] = Field(
        default_factory=lambda: [
            FacebookEventMapping.model_validate(item)
            for item in default_facebook_event_mappings()
        ]
    )
