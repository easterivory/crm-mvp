from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import OrmBase


FunnelStatus = Literal["active", "archived"]
FunnelVersionStatus = Literal["draft", "published", "archived"]
FunnelStepType = Literal[
    "trigger",
    "message",
    "input",
    "condition",
    "action",
    "delay",
    "operator",
    "integration",
    "finish",
]
PushAction = Literal["stay", "move_to_step", "finish", "assign_operator"]
FieldMappingSource = Literal["user_answer", "button_value", "computed_value"]


class FunnelCreate(BaseModel):
    project_id: uuid.UUID
    bot_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be empty")
        return normalized


class FunnelUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)


class FunnelOut(OrmBase):
    id: uuid.UUID
    project_id: uuid.UUID
    bot_id: uuid.UUID
    name: str
    description: Optional[str]
    status: FunnelStatus
    created_by_user_id: Optional[uuid.UUID]
    created_at: datetime
    updated_at: datetime
    draft_version_id: Optional[uuid.UUID] = None
    published_version_id: Optional[uuid.UUID] = None
    is_active_for_bot: bool = False


class FunnelVersionOut(OrmBase):
    id: uuid.UUID
    funnel_id: uuid.UUID
    version_number: int
    status: FunnelVersionStatus
    created_by_user_id: Optional[uuid.UUID]
    created_by_id: Optional[uuid.UUID] = None
    change_log: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    published_at: Optional[datetime]
    is_hold_active: bool = False
    is_active_for_bot: bool = False


class FunnelVersionUpdate(BaseModel):
    status: Optional[FunnelVersionStatus] = None


class FunnelHoldModeUpdate(BaseModel):
    is_hold_active: bool


class FunnelDropOffStepOut(BaseModel):
    step_id: uuid.UUID
    step_title: str
    step_type: str
    block_type: str
    entered_leads: int
    conversion_from_start: float
    conversion_from_previous: float


class FunnelDropOffAnalyticsOut(BaseModel):
    funnel_id: uuid.UUID
    version_id: uuid.UUID
    steps: list[FunnelDropOffStepOut] = Field(default_factory=list)


class FunnelStepIn(BaseModel):
    id: Optional[uuid.UUID] = None
    key: str = Field(..., min_length=1, max_length=100)
    title: str = Field(..., min_length=1, max_length=255)
    step_type: FunnelStepType
    block_type: str = Field(..., min_length=1, max_length=100)
    position_x: float = 0
    position_y: float = 0
    config_json: dict[str, Any] = Field(default_factory=dict)
    validation_json: Optional[dict[str, Any]] = None
    ui_schema_json: Optional[dict[str, Any]] = None


class FunnelStepOut(OrmBase):
    id: uuid.UUID
    funnel_version_id: uuid.UUID
    key: str
    title: str
    step_type: FunnelStepType
    block_type: str
    position_x: float
    position_y: float
    config_json: dict[str, Any]
    validation_json: Optional[dict[str, Any]]
    ui_schema_json: Optional[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class FunnelEdgeIn(BaseModel):
    id: Optional[uuid.UUID] = None
    from_step_id: uuid.UUID
    to_step_id: uuid.UUID
    condition_json: Optional[dict[str, Any]] = None
    priority: int = 0


class FunnelEdgeOut(OrmBase):
    id: uuid.UUID
    funnel_version_id: uuid.UUID
    from_step_id: uuid.UUID
    to_step_id: uuid.UUID
    condition_json: Optional[dict[str, Any]]
    priority: int
    created_at: datetime
    updated_at: datetime


class FunnelPushRuleIn(BaseModel):
    id: Optional[uuid.UUID] = None
    step_id: uuid.UUID
    delay_minutes: int = Field(..., ge=1)
    message_text: str = Field(..., min_length=1, max_length=4000)
    action_after_send: PushAction = "stay"
    target_step_id: Optional[uuid.UUID] = None
    is_active: bool = True


class FunnelPushRuleOut(OrmBase):
    id: uuid.UUID
    funnel_version_id: uuid.UUID
    step_id: uuid.UUID
    delay_minutes: int
    message_text: str
    action_after_send: PushAction
    target_step_id: Optional[uuid.UUID]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class FunnelFieldMappingIn(BaseModel):
    id: Optional[uuid.UUID] = None
    step_id: uuid.UUID
    source: FieldMappingSource = "user_answer"
    lead_field_key: str = Field(..., min_length=1, max_length=100)
    transform_rule_json: Optional[dict[str, Any]] = None
    is_required: bool = False


class FunnelFieldMappingOut(OrmBase):
    id: uuid.UUID
    funnel_version_id: uuid.UUID
    step_id: uuid.UUID
    source: FieldMappingSource
    lead_field_key: str
    transform_rule_json: Optional[dict[str, Any]]
    is_required: bool
    created_at: datetime
    updated_at: datetime


class FunnelGraphIn(BaseModel):
    steps: list[FunnelStepIn] = Field(default_factory=list)
    edges: list[FunnelEdgeIn] = Field(default_factory=list)
    push_rules: list[FunnelPushRuleIn] = Field(default_factory=list)
    field_mappings: list[FunnelFieldMappingIn] = Field(default_factory=list)


class FunnelGraphOut(BaseModel):
    steps: list[FunnelStepOut]
    edges: list[FunnelEdgeOut]
    push_rules: list[FunnelPushRuleOut]
    field_mappings: list[FunnelFieldMappingOut]


class FunnelCopyIn(BaseModel):
    target_project_id: uuid.UUID
    target_bot_id: uuid.UUID
    copy_from_version_id: Optional[uuid.UUID] = None


class FunnelCopyOut(BaseModel):
    new_funnel_id: uuid.UUID
    new_version_id: uuid.UUID


class BotActiveFunnelSetIn(BaseModel):
    funnel_id: uuid.UUID
    version_id: uuid.UUID


class BotActiveFunnelGraphSummary(BaseModel):
    steps_count: int = 0
    edges_count: int = 0
    has_trigger: bool = False
    first_message_text: Optional[str] = None


class BotActiveFunnelOut(BaseModel):
    bot_id: uuid.UUID
    active_funnel_id: Optional[uuid.UUID] = None
    active_funnel_version_id: Optional[uuid.UUID] = None
    funnel: Optional[FunnelOut] = None
    version: Optional[FunnelVersionOut] = None
    version_status: Optional[FunnelVersionStatus] = None
    version_number: Optional[int] = None
    graph_summary: Optional[BotActiveFunnelGraphSummary] = None


class FunnelValidationIssue(BaseModel):
    code: str
    message: str
    severity: Literal["error", "warning"]
    step_id: Optional[uuid.UUID] = None
    edge_id: Optional[uuid.UUID] = None


class FunnelValidationOut(BaseModel):
    can_publish: bool
    errors: list[FunnelValidationIssue] = Field(default_factory=list)
    warnings: list[FunnelValidationIssue] = Field(default_factory=list)


class FunnelGraphValidateIn(BaseModel):
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


class FunnelGraphValidationOut(BaseModel):
    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class FunnelRuntimeLogOut(BaseModel):
    step_id: uuid.UUID
    step_key: str
    step_title: str
    status: Literal["success", "failed"]
    error_message: Optional[str] = None
    created_at: datetime

    @classmethod
    def from_runtime_log(cls, log: Any) -> "FunnelRuntimeLogOut":
        step = getattr(log, "step", None)
        return cls(
            step_id=log.step_id,
            step_key=getattr(step, "key", str(log.step_id)),
            step_title=getattr(step, "title", "Неизвестный шаг"),
            status=log.status,
            error_message=log.error_message,
            created_at=log.created_at,
        )


class ChatFunnelStepChoiceOut(BaseModel):
    id: uuid.UUID
    title: str
    step_type: str
    block_type: str


class ChatFunnelControlOut(BaseModel):
    is_available: bool
    is_paused: bool
    funnel_id: Optional[uuid.UUID] = None
    funnel_name: Optional[str] = None
    current_step_id: Optional[uuid.UUID] = None
    current_step_title: Optional[str] = None
    steps: list[ChatFunnelStepChoiceOut] = Field(default_factory=list)


class ChatFunnelResumeIn(BaseModel):
    step_id: uuid.UUID


class FunnelBlockDefinitionOut(BaseModel):
    step_type: str
    block_type: str
    label: str
    status: Literal["mvp", "supported", "reserved"]
    description: Optional[str] = None


class FunnelBlockRegistryOut(BaseModel):
    allowed_step_types: list[str]
    lead_field_keys: list[str]
    blocks: dict[str, list[FunnelBlockDefinitionOut]]
    reserved_future_blocks: list[str]
