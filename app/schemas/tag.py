import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

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


class LeadTagsUpdate(BaseModel):
    add_tag_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    remove_tag_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def disjoint_changes(self):
        if set(self.add_tag_ids) & set(self.remove_tag_ids):
            raise ValueError("Один тег нельзя одновременно добавить и удалить")
        return self
