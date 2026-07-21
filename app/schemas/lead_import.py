from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import OrmBase


LeadImportStatus = Literal["created", "validated", "completed", "failed"]
LeadImportIssueLevel = Literal["error", "warning"]


class BotLeadImportOut(OrmBase):
    id: UUID
    project_id: UUID
    bot_id: UUID
    source_system: str
    spreadsheet_id: str
    spreadsheet_url: str
    worksheet_title: str
    status: LeadImportStatus
    total_rows: int
    imported_count: int
    updated_count: int
    skipped_count: int
    error_count: int
    completed_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class LeadImportIssue(BaseModel):
    row: int = Field(ge=2)
    field: str
    level: LeadImportIssueLevel
    message: str


class LeadImportPreviewOut(BaseModel):
    import_id: UUID
    checksum: str
    can_import: bool
    total_rows: int
    create_count: int
    skip_count: int
    error_count: int
    warning_count: int
    new_tags: list[str]
    new_statuses: list[str]
    issues: list[LeadImportIssue]


class LeadImportExecuteIn(BaseModel):
    preview_checksum: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class LeadImportExecuteOut(BaseModel):
    import_batch: BotLeadImportOut
    created_count: int
    skipped_count: int
    created_tag_count: int
    created_status_count: int
