from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import OrmBase


class GoogleSheetsConfigOut(OrmBase):
    id: UUID
    project_id: UUID
    is_enabled: bool
    spreadsheet_id: Optional[str] = None
    sheet_name: str
    trigger_statuses: list[str]
    service_account_email: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class GoogleSheetsConfigUpdate(BaseModel):
    spreadsheet_id: Optional[str] = Field(default=None, max_length=255)
    sheet_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    is_enabled: Optional[bool] = None
    trigger_statuses: Optional[list[str]] = None

    @field_validator("spreadsheet_id", "sheet_name")
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("trigger_statuses")
    @classmethod
    def normalize_trigger_statuses(
        cls,
        value: Optional[list[str]],
    ) -> Optional[list[str]]:
        if value is None:
            return None

        normalized: list[str] = []
        for item in value:
            item_value = str(item).strip()
            if item_value and item_value not in normalized:
                normalized.append(item_value)
        return normalized


class GoogleSheetsTestConnectionOut(BaseModel):
    success: bool
    message: str
