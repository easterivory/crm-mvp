from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import OrmBase


class PartnerIntegrationCreate(BaseModel):
    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    postback_url: str = Field(..., min_length=1, max_length=2048)
    auth_token: Optional[str] = Field(None, max_length=512)
    is_active: bool = True


class PartnerIntegrationUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    postback_url: Optional[str] = Field(None, min_length=1, max_length=2048)
    auth_token: Optional[str] = Field(None, max_length=512)
    is_active: Optional[bool] = None


class PartnerIntegrationOut(OrmBase):
    id: UUID
    project_id: UUID
    name: str
    postback_url: str
    has_auth_token: bool = False
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SubmitLeadRequest(BaseModel):
    lead_id: UUID
    partner_integration_id: UUID


class LeadSubmissionOut(OrmBase):
    id: UUID
    lead_id: UUID
    partner_integration_id: UUID
    status: str
    request_payload: Optional[dict]
    response_payload: Optional[dict]
    error_message: Optional[str]
    submitted_at: datetime
    completed_at: Optional[datetime]
