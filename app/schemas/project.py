import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.core.constants import LeadStatusCode
from app.core.lead_confidence import (
    DEFAULT_CONFIDENCE_THRESHOLDS,
    DEFAULT_CONFIDENCE_WEIGHTS,
)
from app.schemas.common import OrmBase, PaginatedResponse


ProjectStatus = Literal["active", "archived"]
ProjectFormat = Literal["submission", "gambling"]


def default_tracking_lead_status_codes() -> list[str]:
    return list(LeadStatusCode.TRACKING_LEAD_DEFAULT)


class ProjectBase(BaseModel):
    name: str = Field(..., max_length=255)
    slug: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    status: ProjectStatus = "active"
    sla_threshold_minutes: int = Field(default=30, ge=1)
    tracking_lead_status_codes: list[str] = Field(
        default_factory=default_tracking_lead_status_codes,
        min_length=1,
    )
    use_confidence_score: bool = True
    hide_assigned_chats_from_all: bool = False
    chat_lease_minutes: int = Field(default=30, ge=0, le=10080)
    project_format: ProjectFormat = "submission"
    vip_tags: list[str] = Field(default_factory=list, max_length=100)
    push_unread_threshold: int = Field(default=1, ge=1, le=100)
    confidence_weights: Optional[dict[str, int]] = None
    confidence_thresholds: Optional[dict[str, int]] = None

    @field_validator("tracking_lead_status_codes")
    @classmethod
    def normalize_tracking_lead_status_codes(cls, value: list[str]) -> list[str]:
        return _normalize_tracking_lead_status_codes(value)

    @field_validator("vip_tags")
    @classmethod
    def normalize_vip_tags(cls, value: list[str]) -> list[str]:
        return _normalize_vip_tags(value)

    @field_validator("confidence_weights")
    @classmethod
    def validate_confidence_weights(
        cls,
        value: Optional[dict[str, int]],
    ) -> Optional[dict[str, int]]:
        return _validate_confidence_weights(value)

    @field_validator("confidence_thresholds")
    @classmethod
    def validate_confidence_thresholds(
        cls,
        value: Optional[dict[str, int]],
    ) -> Optional[dict[str, int]]:
        return _validate_confidence_thresholds(value)


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    slug: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    status: Optional[ProjectStatus] = None
    sla_threshold_minutes: Optional[int] = Field(None, ge=1)
    tracking_lead_status_codes: Optional[list[str]] = Field(default=None, min_length=1)
    use_confidence_score: Optional[bool] = None
    hide_assigned_chats_from_all: Optional[bool] = None
    chat_lease_minutes: Optional[int] = Field(default=None, ge=0, le=10080)
    project_format: Optional[ProjectFormat] = None
    vip_tags: Optional[list[str]] = Field(default=None, max_length=100)
    push_unread_threshold: Optional[int] = Field(default=None, ge=1, le=100)
    confidence_weights: Optional[dict[str, int]] = None
    confidence_thresholds: Optional[dict[str, int]] = None

    @field_validator("tracking_lead_status_codes")
    @classmethod
    def normalize_tracking_lead_status_codes(
        cls,
        value: Optional[list[str]],
    ) -> Optional[list[str]]:
        if value is None:
            return value
        return _normalize_tracking_lead_status_codes(value)

    @field_validator("vip_tags")
    @classmethod
    def normalize_vip_tags(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        return _normalize_vip_tags(value) if value is not None else None

    @field_validator("confidence_weights")
    @classmethod
    def validate_confidence_weights(
        cls,
        value: Optional[dict[str, int]],
    ) -> Optional[dict[str, int]]:
        return _validate_confidence_weights(value)

    @field_validator("confidence_thresholds")
    @classmethod
    def validate_confidence_thresholds(
        cls,
        value: Optional[dict[str, int]],
    ) -> Optional[dict[str, int]]:
        return _validate_confidence_thresholds(value)


class ProjectTranslationUpdate(BaseModel):
    operator_lang: Optional[str] = Field(None, min_length=1, max_length=10)
    default_client_lang: Optional[str] = Field(None, min_length=1, max_length=10)
    is_translation_enabled: Optional[bool] = None


class ProjectRead(OrmBase):
    id: uuid.UUID
    name: str
    slug: str
    description: Optional[str]
    status: ProjectStatus
    sla_threshold_minutes: int
    operator_lang: str
    default_client_lang: str
    is_translation_enabled: bool
    tracking_lead_status_codes: list[str]
    use_confidence_score: bool
    hide_assigned_chats_from_all: bool
    chat_lease_minutes: int
    project_format: ProjectFormat
    vip_tags: list[str]
    push_unread_threshold: int
    confidence_weights: Optional[dict[str, int]]
    confidence_thresholds: Optional[dict[str, int]]
    created_at: datetime
    updated_at: datetime
    is_deleted: bool


class ProjectOut(ProjectRead):
    pass


class ProjectDashboardHeaderOut(BaseModel):
    date: date
    project_format: ProjectFormat = "submission"
    subscribers_today: int
    conversion_today: Decimal
    leads_today: int
    chats_today: int
    submitted_today: int
    submitted_percent_today: Decimal
    spend_today: Decimal
    cpl_today: Decimal
    cost_per_submitted_today: Decimal
    registrations_today: int = 0
    deposits_today: int = 0
    redeposits_today: int = 0


ProjectListResponse = PaginatedResponse[ProjectRead]


def _normalize_tracking_lead_status_codes(value: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw_code in value:
        code = raw_code.strip().lower()
        if not code:
            continue
        if code not in normalized:
            normalized.append(code)
    if not normalized:
        raise ValueError("At least one tracking lead status must be selected")
    return normalized


def _normalize_vip_tags(value: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw_value in value:
        item = str(raw_value).strip()
        if item and item not in normalized:
            normalized.append(item)
    return normalized


def _validate_confidence_weights(
    value: Optional[dict[str, int]],
) -> Optional[dict[str, int]]:
    if value is None:
        return None
    unknown = set(value) - set(DEFAULT_CONFIDENCE_WEIGHTS)
    if unknown:
        raise ValueError(f"Unknown confidence weights: {', '.join(sorted(unknown))}")
    normalized: dict[str, int] = {}
    for key, penalty in value.items():
        if isinstance(penalty, bool) or not isinstance(penalty, int):
            raise ValueError(f"Confidence weight {key} must be an integer")
        if penalty < 0 or penalty > 100:
            raise ValueError(f"Confidence weight {key} must be between 0 and 100")
        normalized[key] = penalty
    return normalized


def _validate_confidence_thresholds(
    value: Optional[dict[str, int]],
) -> Optional[dict[str, int]]:
    if value is None:
        return None
    unknown = set(value) - set(DEFAULT_CONFIDENCE_THRESHOLDS)
    if unknown:
        raise ValueError(f"Unknown confidence thresholds: {', '.join(sorted(unknown))}")
    merged: dict[str, Any] = {**DEFAULT_CONFIDENCE_THRESHOLDS, **value}
    for key in DEFAULT_CONFIDENCE_THRESHOLDS:
        threshold = merged[key]
        if isinstance(threshold, bool) or not isinstance(threshold, int):
            raise ValueError(f"Confidence threshold {key} must be an integer")
        if threshold < 0 or threshold > 100:
            raise ValueError(f"Confidence threshold {key} must be between 0 and 100")
    if merged["medium_min"] > merged["high_min"]:
        raise ValueError("medium_min must be less than or equal to high_min")
    return {key: int(value[key]) for key in value}
