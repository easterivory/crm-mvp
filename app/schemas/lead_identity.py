import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DuplicateSubmissionHistory(BaseModel):
    partner_integration_id: uuid.UUID
    partner_name: str
    status: str
    partner_status: str | None = None
    error_message: str | None = None
    partner_feedback: str | None = None
    created_at: datetime


class DuplicateLeadDetail(BaseModel):
    lead_id: uuid.UUID
    project_name: str
    bot_name: str | None = None
    created_at: datetime
    match_type: str
    matched_fields: list[str] = Field(default_factory=list)
    lead_status: str | None = None
    is_trash: bool
    is_deleted: bool
    submission_history: list[DuplicateSubmissionHistory] = Field(default_factory=list)


class DuplicateSubmissionConflict(BaseModel):
    lead_id: uuid.UUID
    partner_name: str
    duplicate: DuplicateLeadDetail
    blocking_submission: DuplicateSubmissionHistory
