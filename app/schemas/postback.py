from __future__ import annotations

from datetime import datetime
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
]


class PostbackParameterMapping(BaseModel):
    identifier_type: PostbackIdentifierType = "lead_id"
    identifier_param: str = Field(default="lead_id", min_length=1, max_length=255)
    amount_param: str | None = Field(default=None, max_length=255)
    currency_param: str | None = Field(default=None, max_length=255)
    event_type_param: str | None = Field(default=None, max_length=255)
    external_event_id_param: str | None = Field(default=None, max_length=255)


class PostbackEndpointCreate(BaseModel):
    partner_integration_id: UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    event_type: str = Field(default="registration", min_length=1, max_length=100)
    parameter_mapping: PostbackParameterMapping = Field(
        default_factory=PostbackParameterMapping,
    )
    is_active: bool = True

    @field_validator("name", "event_type")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class PostbackEndpointUpdate(BaseModel):
    partner_integration_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    event_type: str | None = Field(default=None, min_length=1, max_length=100)
    parameter_mapping: PostbackParameterMapping | None = None
    is_active: bool | None = None

    @field_validator("name", "event_type")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class PostbackEndpointOut(OrmBase):
    id: UUID
    project_id: UUID
    partner_integration_id: UUID | None
    name: str
    event_type: str
    parameter_mapping: PostbackParameterMapping
    is_active: bool
    url: str
    created_at: datetime
    updated_at: datetime


class PostbackReceiptOut(OrmBase):
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
    event_type: str = Field(min_length=1, max_length=100)
    amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=10)
    partner_integration_id: UUID | None = None
    external_event_id: str | None = Field(default=None, max_length=255)
    payload: dict[str, Any] = Field(default_factory=dict)

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
    event_type: str
    source: str
    amount: Decimal | None
    currency: str | None
    external_event_id: str | None
    payload_json: dict[str, Any]
    occurred_at: datetime
    created_at: datetime


class PublicPostbackResult(BaseModel):
    status: Literal["processed", "unmatched", "duplicate"]
    receipt_id: UUID
    lead_id: UUID | None = None
    event_id: UUID | None = None
