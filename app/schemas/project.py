import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.common import OrmBase


class ProjectCreate(BaseModel):
    name: str = Field(..., max_length=255)
    sla_threshold_minutes: int = Field(default=30, ge=1)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    sla_threshold_minutes: Optional[int] = Field(None, ge=1)


class ProjectOut(OrmBase):
    id: uuid.UUID
    name: str
    sla_threshold_minutes: int
    created_at: datetime
    is_deleted: bool
