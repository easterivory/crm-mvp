import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import OrmBase

TAG_COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"


class TagCreate(BaseModel):
    name: str = Field(..., max_length=100)
    color: str | None = Field(None, pattern=TAG_COLOR_PATTERN)


class TagUpdate(BaseModel):
    name: str | None = Field(None, max_length=100)
    color: str | None = Field(None, pattern=TAG_COLOR_PATTERN)


class TagOut(OrmBase):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    color: str
    created_at: datetime
