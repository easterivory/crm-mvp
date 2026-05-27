import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.schemas.common import OrmBase


class ChatFilterPresetCreate(BaseModel):
    project_id: Optional[uuid.UUID] = None
    name: str = Field(..., min_length=1, max_length=120)
    filters_json: dict[str, Any] = Field(default_factory=dict)
    is_shared: bool = False


class ChatFilterPresetUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    filters_json: Optional[dict[str, Any]] = None
    is_shared: Optional[bool] = None


class ChatFilterPresetOut(OrmBase):
    id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    name: str
    filters_json: dict[str, Any]
    is_shared: bool
    created_at: datetime
    updated_at: datetime
