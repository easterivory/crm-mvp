import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.common import OrmBase


class ChatCreate(BaseModel):
    bot_id: Optional[uuid.UUID] = None
    external_chat_id: str = Field(..., max_length=255)
    external_user_id: str = Field(..., max_length=255)
    contact_name: Optional[str] = Field(None, max_length=255)


class ChatUpdate(BaseModel):
    contact_name: Optional[str] = Field(None, max_length=255)


class ChatLanguageUpdate(BaseModel):
    client_lang: Optional[str] = Field(None, max_length=10)


class ChatTagOut(BaseModel):
    id: uuid.UUID
    name: str
    color: Optional[str] = None


class ChatLeadStatusOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class ChatOut(OrmBase):
    id: uuid.UUID
    project_id: uuid.UUID
    bot_id: Optional[uuid.UUID]
    tracking_link_id: Optional[uuid.UUID]
    external_chat_id: str
    external_user_id: str
    contact_name: Optional[str]
    client_lang: Optional[str] = None

    last_message_at: Optional[datetime]
    last_user_message_at: Optional[datetime]
    last_manager_reply_at: Optional[datetime]
    last_client_message_at: Optional[datetime]
    last_operator_message_at: Optional[datetime]
    is_read: bool = True
    unanswered_minutes: int = 0
    last_read_at: Optional[datetime]
    reset_at: Optional[datetime]
    reset_count: int = 0
    current_cycle_started_at: Optional[datetime]

    # Computed — populated by the service layer before returning
    unread: bool = False
    unanswered: bool = False
    is_red: bool = False
    last_incoming_at: Optional[datetime] = None
    last_outgoing_at: Optional[datetime] = None
    has_unanswered_incoming: bool = False

    last_message_text: Optional[str] = None
    last_message_type: Optional[str] = None
    last_message_caption: Optional[str] = None
    last_message_sender_type: Optional[str] = None
    last_message_created_at: Optional[datetime] = None
    last_message_file_name: Optional[str] = None

    search_hit_message_id: Optional[uuid.UUID] = None
    search_hit_text: Optional[str] = None
    search_hit_created_at: Optional[datetime] = None
    search_hit_sender_type: Optional[str] = None

    tags: list[ChatTagOut] = Field(default_factory=list)
    lead_status: Optional[ChatLeadStatusOut] = None

    active_funnel_id: Optional[uuid.UUID] = None
    active_funnel_name: Optional[str] = None
    active_funnel_version_id: Optional[uuid.UUID] = None
    active_funnel_version_number: Optional[int] = None
    active_funnel_version_status: Optional[str] = None
    current_step_id: Optional[uuid.UUID] = None
    current_step_title: Optional[str] = None
    waiting_for_answer: bool = False
    completed_at: Optional[datetime] = None
    lifecycle_status: str = "manual"

    updated_at: datetime
    created_at: datetime
    is_deleted: bool


class ChatFilters(BaseModel):
    q: Optional[str] = None
    bot_id: Optional[uuid.UUID] = None
    bot_ids: list[uuid.UUID] = Field(default_factory=list)
    unread: Optional[bool] = None
    unanswered: Optional[bool] = None
    has_unanswered_incoming: Optional[bool] = None
    is_red: Optional[bool] = None
    manager_id: Optional[uuid.UUID] = None
    assigned_user_id: Optional[uuid.UUID] = None
    unassigned: Optional[bool] = None
    tracking_link_id: Optional[uuid.UUID] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    tag_ids: list[uuid.UUID] = Field(default_factory=list)
    tag_mode: str = "any"
    lead_statuses: list[str] = Field(default_factory=list)
    funnel_state: Optional[str] = None
