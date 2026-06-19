import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.common import OrmBase, PaginatedResponse


ProjectStatus = Literal["active", "archived"]


class ProjectBase(BaseModel):
    name: str = Field(..., max_length=255)
    slug: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    status: ProjectStatus = "active"
    sla_threshold_minutes: int = Field(default=30, ge=1)


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    slug: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    status: Optional[ProjectStatus] = None
    sla_threshold_minutes: Optional[int] = Field(None, ge=1)


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
