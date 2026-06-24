from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import OrmBase


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


class LanderTrackingCampaignCreate(BaseModel):
    bot_id: UUID
    title: str = Field(..., min_length=1, max_length=255)
    code: Optional[str] = Field(default=None, max_length=64)
    buyer_name: Optional[str] = Field(default=None, max_length=255)
    ad_type: Optional[str] = Field(default=None, max_length=100)
    payment_type: Optional[str] = Field(default=None, max_length=100)
    base_conversion_rate: float = Field(default=10.0, ge=0, le=100)
    min_sample_size: int = Field(default=500, ge=1)
    target_funnel_step_key: Optional[str] = Field(default=None, max_length=100)


class ProjectLanderBase(BaseModel):
    domain_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field(..., min_length=1, max_length=32)
    slug: str = Field(..., min_length=1, max_length=100)
    tracking_link_id: Optional[UUID] = None
    campaign: Optional[LanderTrackingCampaignCreate] = None
    pixels: list[LanderPixel] = Field(default_factory=list, max_length=1)
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


class ProjectLanderOut(OrmBase):
    id: UUID
    project_id: UUID
    domain_id: UUID
    name: str
    type: str
    slug: str
    tracking_link_id: Optional[UUID] = None
    pixels_json: list[dict] = Field(default_factory=list)
    utm_defaults_json: dict[str, str] = Field(default_factory=dict)
    custom_html_path: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProjectLanderUploadOut(BaseModel):
    success: bool
    custom_html_path: str
