from datetime import datetime
from typing import Any, Literal, Optional
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.common import OrmBase


AuthType = Literal["header", "query_param", "bearer"]
RequestMethod = Literal["POST", "PUT", "PATCH"]
RequestBodyFormat = Literal["json", "form"]


def _normalize_string_list(value: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for item in value:
        stripped = item.strip()
        if not stripped:
            raise ValueError("Values must be non-empty strings")
        if stripped not in seen:
            normalized.append(stripped)
            seen.add(stripped)
    return normalized


def _normalize_string_mapping(value: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, mapped_key in value.items():
        source = key.strip()
        target = mapped_key.strip()
        if not source or not target:
            raise ValueError("Mapping keys and values must be non-empty strings")
        normalized[source] = target
    return normalized


def _normalize_postback_url(value: str) -> str:
    normalized = value.strip()
    if "{{" in normalized or "}}" in normalized:
        raise ValueError("API Endpoint URL must contain a real domain, not {{host}}")
    if any(character.isspace() for character in normalized):
        raise ValueError("API Endpoint URL must not contain spaces")
    try:
        parsed = urlsplit(normalized)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("API Endpoint URL is malformed") from exc
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("API Endpoint URL must start with http:// or https://")
    if not hostname or parsed.path.startswith("//"):
        raise ValueError("API Endpoint URL must contain a valid domain")
    return normalized


class PartnerAuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    header_name: Optional[str] = Field(None, min_length=1, max_length=255)
    query_param_name: Optional[str] = Field(None, min_length=1, max_length=255)
    token: Optional[str] = Field(None, min_length=1, max_length=2048)


class PartnerResponseMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status_path: str = Field("status", min_length=1, max_length=255)
    success_key: Optional[str] = Field(None, min_length=1, max_length=255)
    success_value: Optional[str] = Field(None, min_length=1, max_length=255)
    success_values: list[str] = Field(
        default_factory=lambda: ["success", "accepted", "ok"],
        min_length=1,
    )
    duplicate_key: Optional[str] = Field(None, min_length=1, max_length=255)
    duplicate_value: Optional[str] = Field(None, min_length=1, max_length=255)
    duplicate_values: list[str] = Field(default_factory=lambda: ["duplicate"], min_length=1)
    rejected_value: Optional[str] = Field(None, min_length=1, max_length=255)
    rejected_values: list[str] = Field(
        default_factory=lambda: ["rejected", "error"],
        min_length=1,
    )
    error_path: Optional[str] = Field(None, min_length=1, max_length=255)
    external_id_path: Optional[str] = Field(None, min_length=1, max_length=255)
    lead_id_path: Optional[str] = Field(None, min_length=1, max_length=255)
    submission_id_path: Optional[str] = Field(None, min_length=1, max_length=255)
    partner_status_path: Optional[str] = Field(None, min_length=1, max_length=255)
    status_mapping: dict[str, str] = Field(default_factory=dict)

    @field_validator("success_values", "duplicate_values", "rejected_values")
    @classmethod
    def validate_value_lists(cls, value: list[str]) -> list[str]:
        return _normalize_string_list(value)

    @field_validator("status_mapping")
    @classmethod
    def validate_status_mapping(cls, value: dict[str, str]) -> dict[str, str]:
        return _normalize_string_mapping(value)


class PartnerRetryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(3, ge=1, le=10)
    delays_seconds: list[int] = Field(default_factory=lambda: [60, 300, 900])
    timeout_seconds: int = Field(30, ge=1, le=120)

    @field_validator("delays_seconds")
    @classmethod
    def validate_delays(cls, value: list[int]) -> list[int]:
        if any(delay < 0 for delay in value):
            raise ValueError("Retry delays must be greater than or equal to zero")
        return value


class PartnerGeneratorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password_length: int = Field(12, ge=8, le=64)
    ipv4_cidrs: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("ipv4_cidrs")
    @classmethod
    def validate_ipv4_cidrs(cls, value: list[str]) -> list[str]:
        from ipaddress import IPv4Network

        normalized = _normalize_string_list(value)
        for cidr in normalized:
            try:
                IPv4Network(cidr, strict=False)
            except ValueError as exc:
                raise ValueError(f"Invalid IPv4 CIDR: {cidr}") from exc
        return normalized


class PartnerRequestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: RequestMethod = "POST"
    body_format: RequestBodyFormat = "json"
    omit_null_values: bool = True
    payload_template: dict[str, Any] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, str] = Field(default_factory=dict)
    secret_variables: dict[str, str] = Field(default_factory=dict)
    generator_config: PartnerGeneratorConfig = Field(default_factory=PartnerGeneratorConfig)

    @field_validator("headers", "query_params")
    @classmethod
    def validate_string_mappings(cls, value: dict[str, str]) -> dict[str, str]:
        return _normalize_string_mapping(value)

    @field_validator("secret_variables")
    @classmethod
    def validate_secret_variables(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, secret in value.items():
            normalized_key = key.strip()
            if not normalized_key:
                raise ValueError("Secret variable names must be non-empty strings")
            normalized[normalized_key] = secret
        return normalized


class PartnerIntegrationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    postback_url: str = Field(..., min_length=1, max_length=2048)
    auth_token: Optional[str] = Field(None, max_length=512)
    auth_type: AuthType = "header"
    auth_config: PartnerAuthConfig = Field(default_factory=PartnerAuthConfig)
    field_mapping: dict[str, str] = Field(default_factory=dict)
    required_fields: list[str] = Field(default_factory=list)
    response_mapping: PartnerResponseMapping = Field(default_factory=PartnerResponseMapping)
    retry_config: PartnerRetryConfig = Field(default_factory=PartnerRetryConfig)
    request_config: PartnerRequestConfig = Field(default_factory=PartnerRequestConfig)
    is_active: bool = True

    @field_validator("postback_url")
    @classmethod
    def validate_postback_url(cls, value: str) -> str:
        return _normalize_postback_url(value)

    @field_validator("field_mapping")
    @classmethod
    def validate_field_mapping(cls, value: dict[str, str]) -> dict[str, str]:
        return _normalize_string_mapping(value)

    @field_validator("required_fields")
    @classmethod
    def validate_required_fields(cls, value: list[str]) -> list[str]:
        return _normalize_string_list(value)

    @model_validator(mode="after")
    def normalize_legacy_auth_token(self) -> "PartnerIntegrationCreate":
        if self.auth_token and not self.auth_config.token:
            self.auth_config = self.auth_config.model_copy(
                update={
                    "header_name": self.auth_config.header_name or "Authorization",
                    "token": self.auth_token,
                }
            )
        return self


class PartnerIntegrationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    postback_url: Optional[str] = Field(None, min_length=1, max_length=2048)
    auth_token: Optional[str] = Field(None, max_length=512)
    auth_type: Optional[AuthType] = None
    auth_config: Optional[PartnerAuthConfig] = None
    field_mapping: Optional[dict[str, str]] = None
    required_fields: Optional[list[str]] = None
    response_mapping: Optional[PartnerResponseMapping] = None
    retry_config: Optional[PartnerRetryConfig] = None
    request_config: Optional[PartnerRequestConfig] = None
    is_active: Optional[bool] = None

    @field_validator("postback_url")
    @classmethod
    def validate_postback_url(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_postback_url(value) if value is not None else None

    @field_validator("field_mapping")
    @classmethod
    def validate_field_mapping(cls, value: Optional[dict[str, str]]) -> Optional[dict[str, str]]:
        return _normalize_string_mapping(value) if value is not None else None

    @field_validator("required_fields")
    @classmethod
    def validate_required_fields(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        return _normalize_string_list(value) if value is not None else None

    @model_validator(mode="after")
    def normalize_legacy_auth_token(self) -> "PartnerIntegrationUpdate":
        if self.auth_token and self.auth_config is None:
            self.auth_config = PartnerAuthConfig(
                header_name="Authorization",
                token=self.auth_token,
            )
        return self


class PartnerIntegrationOut(OrmBase):
    id: UUID
    project_id: UUID
    name: str
    postback_url: str
    has_auth_token: bool = False
    auth_type: AuthType
    auth_config: PartnerAuthConfig
    field_mapping: dict[str, str]
    required_fields: list[str]
    response_mapping: PartnerResponseMapping
    retry_config: PartnerRetryConfig
    request_config: PartnerRequestConfig
    secret_variable_keys: list[str] = Field(default_factory=list)
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SubmitLeadRequest(BaseModel):
    lead_id: UUID
    partner_integration_id: UUID


class SubmitLeadResponse(BaseModel):
    status: str
    submission_id: UUID


class LeadSubmissionPreviewOut(BaseModel):
    lead_id: UUID
    partner_id: UUID
    payload: dict[str, Any]


class PartnerConnectionTestOut(BaseModel):
    ok: bool
    connected: bool
    mapping_valid: bool
    accepted: bool
    status: str
    status_code: Optional[int] = None
    request_payload: dict[str, Any] = Field(default_factory=dict)
    request_metadata: dict[str, Any] = Field(default_factory=dict)
    response_payload: Optional[dict[str, Any]] = None
    parsed_response: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None


class PartnerPostbackOut(BaseModel):
    status: str
    submission_id: UUID
    lead_id: UUID
    partner_status: str


class LeadSubmissionOut(OrmBase):
    id: UUID
    lead_id: UUID
    partner_integration_id: UUID
    status: str
    request_payload: Optional[dict]
    response_payload: Optional[dict]
    error_message: Optional[str]
    partner_feedback: Optional[str]
    partner_status: Optional[str]
    partner_status_updated_at: Optional[datetime]
    submitted_by_user_id: Optional[UUID]
    is_valid: Optional[bool]
    validated_at: Optional[datetime]
    submitted_at: datetime
    completed_at: Optional[datetime]
