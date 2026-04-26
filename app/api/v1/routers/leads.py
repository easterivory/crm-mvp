"""
/api/v1/leads — lead retrieval and status transitions.

project_id is always taken from the authenticated user's JWT context.

Endpoints implemented:
  POST  /leads/{lead_id}/status — change_status

Endpoints stubbed (Phase 3):
  GET   /leads
  GET   /leads/{lead_id}
  PATCH /leads/{lead_id}
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id, get_current_user, get_db
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.lead import LeadManagerUpdate, LeadOut, LeadStatusUpdate, LeadUpdate
from app.services.lead_service import LeadService

router = APIRouter(prefix="/leads", tags=["leads"])


@router.post("/{lead_id}/status", response_model=LeadOut)
async def change_status(
    lead_id: UUID,
    data: LeadStatusUpdate,
    # SECURITY: project_id is never accepted from request
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadOut:
    """
    Transitions the lead to a new status.

    Validates:
      - lead exists in the current project (404 otherwise)
      - current status is not terminal / is_final=True (422 otherwise)
      - target status exists in lead_statuses table (404 otherwise)
      - no concurrent status change occurred (409 Conflict if race detected)

    Writes a 'lead.status_changed' entry to audit_logs with the before/after
    status codes and the actor's user id.
    """
    return await LeadService(db).change_status(
        lead_id=lead_id,
        project_id=project_id,
        new_status_id=data.status_id,
        actor_id=current_user.id,
    )


# ── Stubs (Phase 3) ────────────────────────────────────────────────────────────

@router.get("", response_model=PaginatedResponse[LeadOut])
async def list_leads(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_id: Optional[UUID] = Query(default=None),
    manager_id: Optional[UUID] = Query(default=None),
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[LeadOut]:
    raise NotImplementedError


@router.get("/{lead_id}", response_model=LeadOut)
async def get_lead(
    lead_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> LeadOut:
    raise NotImplementedError


@router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead(
    lead_id: UUID,
    data: LeadUpdate,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
) -> LeadOut:
    raise NotImplementedError
