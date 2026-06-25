import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.core.constants import LeadStatusCode
from app.schemas.common import OrmBase, PaginatedResponse


ProjectStatus = Literal["active", "archived"]


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

    @field_validator("tracking_lead_status_codes")
    @classmethod
    def normalize_tracking_lead_status_codes(cls, value: list[str]) -> list[str]:
        return _normalize_tracking_lead_status_codes(value)


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    slug: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    status: Optional[ProjectStatus] = None
    sla_threshold_minutes: Optional[int] = Field(None, ge=1)
    tracking_lead_status_codes: Optional[list[str]] = Field(default=None, min_length=1)

    @field_validator("tracking_lead_status_codes")
    @classmethod
    def normalize_tracking_lead_status_codes(
        cls,
        value: Optional[list[str]],
    ) -> Optional[list[str]]:
        if value is None:
            return value
        return _normalize_tracking_lead_status_codes(value)


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
    created_at: datetime
    updated_at: datetime
    is_deleted: bool


class ProjectOut(ProjectRead):
    pass


class ProjectDashboardHeaderOut(BaseModel):
    date: date
    subscribers_today: int
    conversion_today: Decimal
    leads_today: int
    chats_today: int
    submitted_today: int
    submitted_percent_today: Decimal
    spend_today: Decimal
    cpl_today: Decimal
    cost_per_submitted_today: Decimal


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
