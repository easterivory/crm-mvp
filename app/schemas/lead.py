import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.common import OrmBase


class LeadCreate(BaseModel):
    chat_id: uuid.UUID
    project_id: uuid.UUID


class LeadUpdate(BaseModel):
    phone: Optional[str] = Field(None, max_length=50)
    username: Optional[str] = Field(None, max_length=255)


class LeadStatusUpdate(BaseModel):
    status_id: uuid.UUID


class LeadManagerUpdate(BaseModel):
    manager_id: Optional[uuid.UUID]


class LeadOut(OrmBase):
    id: uuid.UUID
    project_id: uuid.UUID
    chat_id: uuid.UUID
    manager_id: Optional[uuid.UUID]
    status_id: uuid.UUID
    phone: Optional[str]
    username: Optional[str]
    updated_at: datetime
    created_at: datetime
    is_deleted: bool
