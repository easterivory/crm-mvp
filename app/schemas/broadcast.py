import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import OrmBase


BroadcastStatus = Literal[
    "draft",
    "audience_ready",
    "scheduled",
    "sending",
    "paused",
    "sent",
    "failed",
    "cancelled",
]
RecipientStatus = Literal["pending", "sent", "failed", "skipped"]
ScheduleType = Literal["now", "scheduled"]
TimezoneMode = Literal["project", "lead_local", "fixed"]
AudienceMode = Literal["all", "any"]


class BroadcastContent(BaseModel):
    type: str = "message"
    messages: list[dict[str, Any]] = Field(default_factory=list)
    after_send_action: Optional[dict[str, Any]] = None


class AudienceRule(BaseModel):
    field: str
    operator: str
    value: Any = None
    custom_field: Optional[str] = None


class AudienceRuleGroup(BaseModel):
    mode: AudienceMode = "all"
    rules: list[AudienceRule] = Field(default_factory=list)


class AudienceFilter(BaseModel):
    include: AudienceRuleGroup = Field(default_factory=AudienceRuleGroup)
    exclude: AudienceRuleGroup = Field(
        default_factory=lambda: AudienceRuleGroup(mode="any", rules=[])
    )


class AudiencePreviewRequest(BaseModel):
    project_id: uuid.UUID
    bot_id: Optional[uuid.UUID] = None
    audience_filter: AudienceFilter = Field(default_factory=AudienceFilter)


class AudiencePreviewSample(BaseModel):
    chat_id: uuid.UUID
    lead_id: Optional[uuid.UUID] = None
    lead_name: Optional[str] = None
    username: Optional[str] = None
    status: Optional[str] = None


class AudiencePreviewResponse(BaseModel):
    count: int
    sample: list[AudiencePreviewSample] = Field(default_factory=list)
    in_funnel_count: int = 0


class BroadcastBase(BaseModel):
    project_id: uuid.UUID
    bot_id: Optional[uuid.UUID] = None
    name: str = Field(..., min_length=1, max_length=255)
    content_json: dict[str, Any] = Field(default_factory=dict)
    audience_filter_json: dict[str, Any] = Field(default_factory=dict)
    schedule_type: ScheduleType = "now"
    scheduled_at: Optional[datetime] = None
    timezone_mode: TimezoneMode = "project"


class BroadcastCreate(BroadcastBase):
    pass


class BroadcastUpdate(BaseModel):
    bot_id: Optional[uuid.UUID] = None
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    content_json: Optional[dict[str, Any]] = None
    audience_filter_json: Optional[dict[str, Any]] = None
    schedule_type: Optional[ScheduleType] = None
    scheduled_at: Optional[datetime] = None
    timezone_mode: Optional[TimezoneMode] = None


class BroadcastScheduleRequest(BaseModel):
    scheduled_at: datetime
    timezone_mode: TimezoneMode = "project"
    confirmation: Optional[str] = None

    @field_validator("confirmation")
    @classmethod
    def trim_confirmation(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if isinstance(value, str) else value


class BroadcastRecipientOut(OrmBase):
    id: uuid.UUID
    broadcast_id: uuid.UUID
    chat_id: uuid.UUID
    lead_id: Optional[uuid.UUID]
    status: RecipientStatus
    attempts: int = 0
    last_error: Optional[str]
    sent_at: Optional[datetime]
    created_at: datetime


class BroadcastOut(OrmBase):
    id: uuid.UUID
    project_id: uuid.UUID
    bot_id: Optional[uuid.UUID]
    name: str
    content_json: dict[str, Any]
    audience_filter_json: dict[str, Any]
    audience_count: int
    schedule_type: str
    scheduled_at: Optional[datetime]
    timezone_mode: str
    status: BroadcastStatus
    created_by_user_id: Optional[uuid.UUID]
    created_by_name: Optional[str] = None
    started_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    sent_at: Optional[datetime]


class BroadcastActionResponse(BaseModel):
    broadcast: BroadcastOut
    audience: AudiencePreviewResponse


class BroadcastReport(BaseModel):
    total_recipients: int = 0
    pending: int = 0
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    cancelled: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_examples: list[str] = Field(default_factory=list)


class BroadcastTemplateBase(BaseModel):
    project_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=255)
    content_json: dict[str, Any] = Field(default_factory=dict)


class BroadcastTemplateCreate(BroadcastTemplateBase):
    pass


class BroadcastTemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    content_json: Optional[dict[str, Any]] = None


class BroadcastTemplateOut(OrmBase):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    content_json: dict[str, Any]
    created_by_user_id: Optional[uuid.UUID]
    created_by_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class SendNowRequest(BaseModel):
    confirmation: Optional[str] = None

    @field_validator("confirmation")
    @classmethod
    def trim_confirmation(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if isinstance(value, str) else value
