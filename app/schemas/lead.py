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


class LeadStatusCreate(BaseModel):
    code: str = Field(..., max_length=50)
    name: str = Field(..., max_length=100)
    is_final: bool = False


class LeadStatusUpdate(BaseModel):
    status_id: uuid.UUID


class LeadStatusAdminUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    is_final: Optional[bool] = None


class LeadManagerUpdate(BaseModel):
    manager_id: Optional[uuid.UUID]


class LeadStatusOut(OrmBase):
    id: uuid.UUID
    code: str
    name: str
    sort_order: int
    is_final: bool
    created_at: datetime


class LeadTagOut(OrmBase):
    id: uuid.UUID
    name: str


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
    tags: list[LeadTagOut] = Field(default_factory=list)
    bot_id: Optional[uuid.UUID] = None
    bot_name: Optional[str] = None
    bot_username: Optional[str] = None
    tracking_link_id: Optional[uuid.UUID] = None
    tracking_code: Optional[str] = None
    tracking_ref_code: Optional[str] = None
    tracking_title: Optional[str] = None
    contact_name: Optional[str] = None
    external_chat_id: Optional[str] = None
    manager_name: Optional[str] = None
    status_code: Optional[str] = None
    status_name: Optional[str] = None
