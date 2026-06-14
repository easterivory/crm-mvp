from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

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


class ProjectLanderBase(BaseModel):
    domain_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field(..., min_length=1, max_length=32)
    slug: str = Field(..., min_length=1, max_length=100)
    tracking_link_id: Optional[UUID] = None

    @field_validator("name", "type", "slug")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized


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
    custom_html_path: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProjectLanderUploadOut(BaseModel):
    success: bool
    custom_html_path: str
