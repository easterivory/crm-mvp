"""
/api/v1/leads/{lead_id}/assign — manager assignment.

project_id is always taken from the authenticated user's JWT context.
actor_id is taken from the authenticated user — the request body only
carries the target manager_id (or null to unassign).

Endpoint implemented:
  POST /leads/{lead_id}/assign — assign_manager
"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id, get_current_user, get_db
from app.models.user import User
from app.schemas.lead import LeadManagerUpdate, LeadOut
from app.services.assignment_service import AssignmentService

router = APIRouter(prefix="/leads", tags=["assignments"])


@router.post("/{lead_id}/assign", response_model=LeadOut)
async def assign_manager(
    lead_id: UUID,
    data: LeadManagerUpdate,
    # SECURITY: project_id is never accepted from request
    project_id: UUID = Depends(get_current_project_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LeadOut:
    """
    Assigns (or unassigns) a manager for the given lead.

    Pass manager_id=<uuid> to assign. Pass manager_id=null to unassign.

    Validates:
      - lead exists in the current project (404 otherwise)
      - if manager_id is set, the user must belong to the same project (403)
      - no concurrent assignment change occurred (409 Conflict if race detected)

    Idempotent: assigning the same manager that is already assigned is a no-op.
    Writes a 'lead.manager_assigned' or 'lead.manager_removed' audit log entry.
    """
    return await AssignmentService(db).assign_manager(
        lead_id=lead_id,
        project_id=project_id,
        manager_id=data.manager_id,
        actor_id=current_user.id,
    )
