import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.constants import MessageType
from app.schemas.common import OrmBase


SNIPPET_TYPES = {
    MessageType.TEXT,
    MessageType.PHOTO,
    MessageType.VIDEO,
    MessageType.VOICE,
    MessageType.VIDEO_NOTE,
    MessageType.DOCUMENT,
}


class SnippetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field(..., max_length=30)
    content: Optional[str] = None
    file_id: Optional[str] = Field(None, max_length=512)
    channel: str = Field(default="telegram", max_length=30)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Snippet name cannot be blank")
        return normalized

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        if value not in SNIPPET_TYPES:
            raise ValueError(f"Unsupported snippet type: {value}")
        return value

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, value: str) -> str:
        if value != "telegram":
            raise ValueError("Only telegram snippets are supported")
        return value

    @model_validator(mode="after")
    def validate_payload(self) -> "SnippetCreate":
        content = self.content.strip() if isinstance(self.content, str) else self.content
        file_id = self.file_id.strip() if isinstance(self.file_id, str) else self.file_id
        if self.type == MessageType.TEXT and not content:
            raise ValueError("Text snippet requires content")
        if self.type != MessageType.TEXT and not file_id:
            raise ValueError("Media snippet requires file_id")
        self.content = content
        self.file_id = file_id
        return self


class SnippetOut(OrmBase):
    id: uuid.UUID
    project_id: uuid.UUID
    channel: str
    name: str
    type: str
    content: Optional[str]
    file_id: Optional[str]
    created_at: datetime
