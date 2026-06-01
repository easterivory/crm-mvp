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


class ProjectRead(OrmBase):
    id: uuid.UUID
    name: str
    slug: str
    description: Optional[str]
    status: ProjectStatus
    sla_threshold_minutes: int
    created_at: datetime
    updated_at: datetime
    is_deleted: bool


class ProjectOut(ProjectRead):
    pass


class ProjectDashboardHeaderOut(BaseModel):
    date: date
    conversion_today: Decimal
    leads_today: int
    chats_today: int
    spend_today: Decimal
    cpl_today: Decimal


ProjectListResponse = PaginatedResponse[ProjectRead]
