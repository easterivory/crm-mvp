from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id, get_current_user, get_db
from app.models.user import User
from app.schemas.partner import (
    LeadSubmissionOut,
    PartnerIntegrationCreate,
    PartnerIntegrationOut,
    PartnerIntegrationUpdate,
    SubmitLeadRequest,
)
from app.services.partner_service import PartnerService

router = APIRouter()


@router.get("", response_model=list[PartnerIntegrationOut])
async def list_partner_integrations(
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all partner integrations for a project."""
    return await PartnerService(db).list_integrations(project_id, current_user)


@router.post("", response_model=PartnerIntegrationOut, status_code=status.HTTP_201_CREATED)
async def create_partner_integration(
    data: PartnerIntegrationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new partner integration."""
    return await PartnerService(db).create_integration(data, current_user)


@router.get("/{integration_id}", response_model=PartnerIntegrationOut)
async def get_partner_integration(
    integration_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific partner integration."""
    return await PartnerService(db).get_integration(integration_id, project_id, current_user)


@router.patch("/{integration_id}", response_model=PartnerIntegrationOut)
async def update_partner_integration(
    integration_id: UUID,
    data: PartnerIntegrationUpdate,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a partner integration."""
    return await PartnerService(db).update_integration(
        integration_id,
        project_id,
        data,
        current_user,
    )


@router.delete("/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_partner_integration(
    integration_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a partner integration."""
    await PartnerService(db).delete_integration(integration_id, project_id, current_user)


@router.post("/submit", response_model=dict)
async def submit_lead_to_partner(
    data: SubmitLeadRequest,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Queue a lead submission to a partner CRM for the postback worker."""
    submission = await PartnerService(db).queue_lead_submission(
        lead_id=data.lead_id,
        partner_integration_id=data.partner_integration_id,
        project_id=project_id,
        actor=current_user,
    )
    return {
        "status": "queued",
        "submission_id": str(submission.id),
    }


@router.get("/submissions/{lead_id}", response_model=list[LeadSubmissionOut])
async def get_lead_submissions(
    lead_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all submissions for a specific lead."""
    return await PartnerService(db).list_lead_submissions(
        lead_id=lead_id,
        project_id=project_id,
        actor=current_user,
    )
