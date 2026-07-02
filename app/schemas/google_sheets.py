from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import OrmBase


DEFAULT_GOOGLE_SHEETS_EXPORT_FIELDS = [
    "created_at",
    "name",
    "phone",
    "telegram",
    "country",
    "age",
    "tracking_link",
    "buyer",
    "status",
    "cpl",
    "score",
]
ALLOWED_GOOGLE_SHEETS_EXPORT_FIELDS = frozenset(
    DEFAULT_GOOGLE_SHEETS_EXPORT_FIELDS
    + ["manager", "bot", "chat_id", "telegram_id"]
)


class GoogleSheetsConfigOut(OrmBase):
    id: UUID
    project_id: UUID
    is_enabled: bool
    spreadsheet_id: Optional[str] = None
    sheet_name: str
    trigger_statuses: list[str]
    bot_ids: list[str]
    export_fields: list[str]
    custom_field_keys: list[str]
    service_account_email: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class GoogleSheetsConfigUpdate(BaseModel):
    spreadsheet_id: Optional[str] = Field(default=None, max_length=255)
    sheet_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    is_enabled: Optional[bool] = None
    trigger_statuses: Optional[list[str]] = None
    bot_ids: Optional[list[str]] = None
    export_fields: Optional[list[str]] = None
    custom_field_keys: Optional[list[str]] = None

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

    @field_validator("bot_ids")
    @classmethod
    def normalize_bot_ids(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return None
        normalized: list[str] = []
        for item in value:
            parsed = str(UUID(str(item)))
            if parsed not in normalized:
                normalized.append(parsed)
        return normalized

    @field_validator("export_fields")
    @classmethod
    def normalize_export_fields(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return None
        normalized = [
            str(item).strip()
            for item in value
            if str(item).strip() in ALLOWED_GOOGLE_SHEETS_EXPORT_FIELDS
        ]
        normalized = list(dict.fromkeys(normalized))
        if not normalized:
            raise ValueError("Select at least one export field")
        return normalized

    @field_validator("custom_field_keys")
    @classmethod
    def normalize_custom_field_keys(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return None
        normalized: list[str] = []
        for item in value:
            key = str(item).strip()
            if not key:
                continue
            if not key.replace("_", "a").isalnum() or len(key) > 100:
                raise ValueError(f"Invalid custom field key: {key}")
            if key not in normalized:
                normalized.append(key)
        return normalized


class GoogleSheetsTestConnectionOut(BaseModel):
    success: bool
    message: str
