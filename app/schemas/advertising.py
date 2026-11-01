from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


class AdvertisingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    bot_ids: list[UUID] = Field(default_factory=list, max_length=100)
    protected_tag_ids: list[UUID] = Field(default_factory=list, max_length=100)
    audience_tag_id: UUID | None = None
    timeout_minutes: int = Field(default=180, ge=1, le=43200)


class SlotWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    position: int = Field(default=0, ge=0, le=1000)
    enabled: bool = False
    delay_minutes: int = Field(default=120, ge=1, le=43200)
    revision: int | None = None
    content_json: dict


class BackfillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    created_before: datetime
    stop_main: bool = False
    start_slots: bool = False
    confirmation: str | None = None
    preview_id: UUID | None = None
