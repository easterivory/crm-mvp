from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


AIAPIStyle = Literal["openai_compatible", "gemini"]


class AIModelPricing(BaseModel):
    input_usd_per_million: Decimal = Field(ge=0, max_digits=14, decimal_places=6)
    output_usd_per_million: Decimal = Field(ge=0, max_digits=14, decimal_places=6)


class AIProviderConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9_-]+$")
    api_style: AIAPIStyle = "openai_compatible"
    base_url: str = Field(min_length=8, max_length=1000)
    api_key: str = Field(min_length=1, max_length=4000)
    default_model: Optional[str] = Field(default=None, max_length=255)
    is_active: bool = True
    request_timeout_seconds: int = Field(default=20, ge=1, le=120)
    supports_json_mode: bool = True
    pricing: dict[str, AIModelPricing] = Field(default_factory=dict)

    @field_validator("name", "api_key")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        return _required_text(value)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return _normalized_http_url(value)

    @field_validator("default_model")
    @classmethod
    def normalize_default_model(cls, value: Optional[str]) -> Optional[str]:
        return _optional_text(value)

    @field_validator("pricing")
    @classmethod
    def validate_pricing(cls, value: dict[str, AIModelPricing]) -> dict[str, AIModelPricing]:
        return _normalized_pricing(value)


class AIProviderConnectionUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    provider: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=50,
        pattern=r"^[a-z0-9_-]+$",
    )
    api_style: Optional[AIAPIStyle] = None
    base_url: Optional[str] = Field(default=None, min_length=8, max_length=1000)
    api_key: Optional[str] = Field(default=None, min_length=1, max_length=4000)
    clear_api_key: bool = False
    default_model: Optional[str] = Field(default=None, max_length=255)
    is_active: Optional[bool] = None
    request_timeout_seconds: Optional[int] = Field(default=None, ge=1, le=120)
    supports_json_mode: Optional[bool] = None
    pricing: Optional[dict[str, AIModelPricing]] = None

    @field_validator("name", "api_key")
    @classmethod
    def normalize_required_text(cls, value: Optional[str]) -> Optional[str]:
        return _required_text(value) if value is not None else None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: Optional[str]) -> Optional[str]:
        return _normalized_http_url(value) if value is not None else None

    @field_validator("default_model")
    @classmethod
    def normalize_default_model(cls, value: Optional[str]) -> Optional[str]:
        return _optional_text(value)

    @field_validator("pricing")
    @classmethod
    def validate_pricing(
        cls,
        value: Optional[dict[str, AIModelPricing]],
    ) -> Optional[dict[str, AIModelPricing]]:
        return _normalized_pricing(value) if value is not None else None

    @model_validator(mode="after")
    def validate_api_key_action(self):
        if self.api_key is not None and self.clear_api_key:
            raise ValueError("api_key and clear_api_key cannot be used together")
        return self


class AIProviderConnectionOut(BaseModel):
    id: UUID
    name: str
    provider: str
    api_style: AIAPIStyle
    base_url: str
    default_model: Optional[str]
    is_active: bool
    request_timeout_seconds: int
    supports_json_mode: bool
    pricing: dict[str, AIModelPricing]
    has_api_key: bool
    api_key_mask: Optional[str]
    created_at: datetime
    updated_at: datetime


class AIProviderOptionOut(BaseModel):
    id: UUID
    name: str
    provider: str
    default_model: Optional[str]


class AIProjectSettingsUpdate(BaseModel):
    is_enabled: bool = False
    primary_connection_id: Optional[UUID] = None
    primary_model: Optional[str] = Field(default=None, max_length=255)
    fallback_connection_id: Optional[UUID] = None
    fallback_model: Optional[str] = Field(default=None, max_length=255)
    master_prompt: Optional[str] = Field(default=None, max_length=30000)
    history_message_limit: int = Field(default=20, ge=1, le=100)
    max_context_chars: int = Field(default=16000, ge=1000, le=100000)
    default_temperature: Decimal = Field(default=Decimal("0.40"), ge=0, le=2)
    default_max_output_tokens: int = Field(default=400, ge=1, le=32000)
    typing_delay_per_char_ms: int = Field(default=30, ge=0, le=250)
    min_delay_ms: int = Field(default=500, ge=0, le=30000)
    max_delay_ms: int = Field(default=3500, ge=0, le=30000)
    daily_budget_usd: Optional[Decimal] = Field(default=None, ge=0)
    monthly_budget_usd: Optional[Decimal] = Field(default=None, ge=0)

    @field_validator(
        "primary_model",
        "fallback_model",
        "master_prompt",
    )
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        return _optional_text(value)

    @model_validator(mode="after")
    def validate_configuration(self):
        if self.max_delay_ms < self.min_delay_ms:
            raise ValueError("max_delay_ms must be greater than or equal to min_delay_ms")
        if self.is_enabled and (
            self.primary_connection_id is None or not self.primary_model
        ):
            raise ValueError(
                "Enabled AI settings require a primary connection and model"
            )
        if bool(self.fallback_connection_id) != bool(self.fallback_model):
            raise ValueError(
                "Fallback connection and fallback model must be configured together"
            )
        return self


class AIProjectSettingsOut(AIProjectSettingsUpdate):
    project_id: UUID
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AIProviderTestIn(BaseModel):
    model: Optional[str] = Field(default=None, max_length=255)

    @field_validator("model")
    @classmethod
    def normalize_model(cls, value: Optional[str]) -> Optional[str]:
        return _optional_text(value)


class AIProviderTestOut(BaseModel):
    ok: bool
    model: str
    latency_ms: int
    message: str


class AIModelListOut(BaseModel):
    models: list[str]
    live: bool
    warning: Optional[str] = None


class AIUsageLogOut(BaseModel):
    id: UUID
    connection_id: Optional[UUID]
    connection_name: Optional[str]
    api_key_mask: Optional[str]
    provider: str
    model: str
    status: str
    used_fallback: bool
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    total_tokens: Optional[int]
    estimated_cost_usd: Optional[Decimal]
    latency_ms: Optional[int]
    error_code: Optional[str]
    error_message: Optional[str]
    created_at: datetime


class AIUsageListOut(BaseModel):
    items: list[AIUsageLogOut]
    total: int


class AIUsageModelSummary(BaseModel):
    provider: str
    model: str
    requests: int
    total_tokens: int
    estimated_cost_usd: Decimal
    unknown_cost_requests: int


class AIUsageConnectionSummary(BaseModel):
    connection_id: Optional[UUID]
    connection_name: str
    provider: str
    api_key_mask: Optional[str]
    requests: int
    total_tokens: int
    estimated_cost_usd: Decimal
    unknown_cost_requests: int


class AIUsageSummaryOut(BaseModel):
    date_from: datetime
    date_to: datetime
    requests: int
    successful_requests: int
    failed_requests: int
    total_tokens: int
    estimated_cost_usd: Decimal
    unknown_cost_requests: int
    average_latency_ms: int
    by_model: list[AIUsageModelSummary]
    by_connection: list[AIUsageConnectionSummary]


class AIResponsePayload(BaseModel):
    messages: list[str] = Field(min_length=1, max_length=5)
    extracted_data: dict[str, Any] = Field(default_factory=dict)
    next_route_key: str = Field(min_length=1, max_length=100)

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, value: list[str]) -> list[str]:
        normalized = [str(message).strip() for message in value if str(message).strip()]
        if not normalized:
            raise ValueError("AI response must contain at least one message")
        if any(len(message) > 4096 for message in normalized):
            raise ValueError("AI response message exceeds Telegram limit")
        return normalized

    @field_validator("next_route_key")
    @classmethod
    def normalize_route(cls, value: str) -> str:
        return value.strip()


def _normalized_http_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if not normalized.lower().startswith(("https://", "http://")):
        raise ValueError("base_url must start with https:// or http://")
    return normalized


def _optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _required_text(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("value cannot be empty")
    return normalized


def _normalized_pricing(
    value: dict[str, AIModelPricing],
) -> dict[str, AIModelPricing]:
    if len(value) > 500:
        raise ValueError("pricing cannot contain more than 500 models")
    normalized: dict[str, AIModelPricing] = {}
    for raw_model, pricing in value.items():
        model = str(raw_model).strip()
        if not model or len(model) > 255:
            raise ValueError("pricing model names must contain 1 to 255 characters")
        if model in normalized:
            raise ValueError(f"duplicate pricing model: {model}")
        normalized[model] = pricing
    return normalized
