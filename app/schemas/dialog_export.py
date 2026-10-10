from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, model_validator


class DialogExportRequest(BaseModel):
    bot_id: UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    format: Literal["txt", "jsonl"] = "txt"
    include_contacts: bool = False

    @model_validator(mode="after")
    def validate_dates(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("Начало периода должно быть не позже конца")
        return self


class DialogExportStatus(BaseModel):
    id: UUID
    status: Literal["queued", "running", "ready", "failed", "cancelled", "cancelling"]
    created_at: datetime
    request: DialogExportRequest
    chats: int = 0
    messages: int = 0
    size_bytes: int = 0
    error: str | None = None
