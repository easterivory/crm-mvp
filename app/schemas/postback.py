from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import OrmBase


PostbackIdentifierType = Literal[
    "lead_id",
    "chat_id",
    "telegram_id",
    "tracking_code",
    "external_id",
    "click_id",
    "submission_id",
    "player_id",
    "offer_token",
]


class PostbackParameterMapping(BaseModel):
    offer_id: UUID | None = None
    identifier_type: PostbackIdentifierType = "lead_id"
    identifier_param: str = Field(default="lead_id", min_length=1, max_length=255)
    amount_param: str | None = Field(default=None, max_length=255)
    currency_param: str | None = Field(default=None, max_length=255)
    event_type_param: str | None = Field(default=None, max_length=255)
    external_event_id_param: str | None = Field(default=None, max_length=255)
    occurred_at_param: str | None = Field(default=None, max_length=255)
    time_format: Literal["iso", "unix_seconds", "unix_ms"] = "iso"
    require_event_id: bool = False
    status_mapping: dict[str, str] = Field(default_factory=dict, max_length=100)
    status_transitions: dict[str, list[str]] = Field(default_factory=dict, max_length=100)
    event_aliases: dict[str, str] = Field(default_factory=dict, max_length=100)
    allowed_event_types: list[str] = Field(default_factory=list, max_length=100)
    event_namespace: str | None = Field(default=None, max_length=100, pattern=r"^[a-zA-Z0-9_.:-]+$")
    bind_external_id_param: str | None = Field(default=None, max_length=255)
    bind_external_type: Literal["player_id", "click_id", "external_id"] = "player_id"
    ack_text: str | None = Field(default=None, max_length=128)

    @field_validator("status_mapping", "event_aliases")
    @classmethod
    def clean_mapping(cls, value):
        if any(not k.strip() or not v.strip() for k, v in value.items()):
            raise ValueError("Mapping keys and values cannot be blank")
        return {k.strip().lower(): v.strip().lower() for k, v in value.items()}

    @field_validator("status_transitions")
    @classmethod
    def clean_transitions(cls, value):
        if any(not k.strip() or len(v) > 100 or any(not s.strip() for s in v) for k, v in value.items()):
            raise ValueError("Invalid status transition")
        return {k.strip().lower(): list(dict.fromkeys(s.strip().lower() for s in v)) for k, v in value.items()}


class PostbackEndpointCreate(BaseModel):
    processing_kind: Literal["lifecycle_event", "submission_status"] = "lifecycle_event"
    partner_integration_id: UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    event_type: str = Field(default="registration", min_length=1, max_length=100)
    parameter_mapping: PostbackParameterMapping = Field(
        default_factory=lambda: PostbackParameterMapping(require_event_id=True),
    )
    is_active: bool = True

    @field_validator("name", "event_type")
    @classmethod
    def strip_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value cannot be blank")
        return value.strip()


class PostbackEndpointUpdate(BaseModel):
    processing_kind: Literal["lifecycle_event", "submission_status"] | None = None
    partner_integration_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    event_type: str | None = Field(default=None, min_length=1, max_length=100)
    parameter_mapping: PostbackParameterMapping | None = None
    is_active: bool | None = None

    @field_validator("name", "event_type")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Value cannot be blank")
        return value.strip() if value is not None else None


class PostbackEndpointOut(OrmBase):
    is_archived: bool = False
    processing_kind: Literal["lifecycle_event", "submission_status"] = "lifecycle_event"
    revision: int = 1
    id: UUID
    project_id: UUID
    partner_integration_id: UUID | None
    name: str
    event_type: str
    parameter_mapping: PostbackParameterMapping
    is_active: bool
    url: str
    delivery_mode: Literal["direct", "relay"] = "direct"
    created_at: datetime
    updated_at: datetime


class PostbackReceiptOut(OrmBase):
    attempt_log: list[dict] = Field(default_factory=list)
    submission_id: UUID | None = None
    endpoint_revision: int | None = None
    received_at: datetime | None = None
    occurred_at: datetime | None = None
    processed_at: datetime | None = None
    id: UUID
    endpoint_id: UUID
    project_id: UUID
    lead_id: UUID | None
    lead_event_id: UUID | None
    request_method: str
    event_type: str
    status: str
    query_payload: dict[str, Any]
    body_payload: dict[str, Any]
    error_message: str | None
    created_at: datetime


class LeadEventCreate(BaseModel):
    offer_id: UUID | None = None
    occurred_at: datetime | None = None
    event_type: str = Field(min_length=1, max_length=100)
    amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=10)
    partner_integration_id: UUID | None = None
    external_event_id: str | None = Field(default=None, max_length=255)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def valid_event_time(cls, value):
        if value is not None and (value.tzinfo is None or value.year < 2000 or value > datetime.now(timezone.utc) + timedelta(minutes=5)):
            raise ValueError("Укажите время события с часовым поясом, не из будущего")
        return value

    @field_validator("event_type")
    @classmethod
    def normalize_event_type(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else None


class LeadEventOut(OrmBase):
    id: UUID
    project_id: UUID
    lead_id: UUID
    partner_integration_id: UUID | None
    postback_endpoint_id: UUID | None
    created_by_user_id: UUID | None
    tracking_link_id: UUID | None = None
    funnel_id: UUID | None = None
    funnel_version_id: UUID | None = None
    event_type: str
    source: str
    amount: Decimal | None
    currency: str | None
    external_event_id: str | None
    payload_json: dict[str, Any]
    occurred_at: datetime
    created_at: datetime


class PublicPostbackResult(BaseModel):
    status: Literal["processed", "unmatched", "duplicate", "ambiguous", "invalid", "conflict", "stale"]
    receipt_id: UUID
    lead_id: UUID | None = None
    event_id: UUID | None = None
    submission_id: UUID | None = None


class PostbackDryRun(BaseModel):
    query_payload: dict[str, Any] = Field(default_factory=dict)
    body_payload: dict[str, Any] = Field(default_factory=dict)


class PostbackBindingCreate(BaseModel):
    identifier_type: Literal["click_id", "external_id", "player_id"]
    external_id: str = Field(min_length=1, max_length=255)
    lead_id: UUID
    submission_id: UUID | None = None

    @field_validator("external_id")
    @classmethod
    def clean_external_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("External ID cannot be blank")
        return value.strip()
