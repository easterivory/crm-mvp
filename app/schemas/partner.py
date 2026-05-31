from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


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


class PartnerIntegrationOut(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    postback_url: str
    auth_token: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SubmitLeadRequest(BaseModel):
    lead_id: UUID
    partner_integration_id: UUID


class LeadSubmissionOut(BaseModel):
    id: UUID
    lead_id: UUID
    partner_integration_id: UUID
    status: str
    request_payload: Optional[dict]
    response_payload: Optional[dict]
    error_message: Optional[str]
    submitted_at: datetime
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True
