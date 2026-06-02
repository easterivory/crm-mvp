from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_project_id, get_current_user, get_db
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.partner import (
    LeadSubmissionOut,
    PartnerConnectionTestOut,
    PartnerIntegrationCreate,
    PartnerIntegrationOut,
    PartnerIntegrationUpdate,
    PartnerPostbackOut,
    SubmitLeadRequest,
    SubmitLeadResponse,
)
from app.services.partner_service import PartnerService
from app.services.postback_service import PostbackService

router = APIRouter(tags=["partners"])


@router.get("", response_model=PaginatedResponse[PartnerIntegrationOut])
async def list_partner_integrations(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[PartnerIntegrationOut]:
    """List all partner integrations for a project."""
    items, total = await PartnerService(db).list_integrations(
        project_id,
        current_user,
        limit=limit,
        offset=offset,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=PartnerIntegrationOut, status_code=status.HTTP_201_CREATED)
async def create_partner_integration(
    data: PartnerIntegrationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PartnerIntegrationOut:
    """Create a new partner integration."""
    return await PartnerService(db).create_integration(data, current_user)


@router.post("/postbacks/{integration_id}", response_model=PartnerPostbackOut)
async def receive_partner_postback(
    integration_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PartnerPostbackOut:
    """Public endpoint for partner feedback postbacks."""
    try:
        raw_payload = await request.json()
    except ValueError:
        raw_payload = {}
    payload = raw_payload if isinstance(raw_payload, dict) else {"payload": raw_payload}
    query_params = dict(request.query_params)
    result = await PostbackService(db).process_partner_postback(
        integration_id=integration_id,
        payload=payload,
        query_params=query_params,
    )
    return PartnerPostbackOut.model_validate(result)


@router.post("/{partner_id}/test-connection", response_model=PartnerConnectionTestOut)
async def test_partner_connection(
    partner_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PartnerConnectionTestOut:
    """Send a test lead to the partner and parse the broker response."""
    return await PartnerService(db).test_connection(
        integration_id=partner_id,
        project_id=project_id,
        actor=current_user,
    )


@router.get("/{integration_id}", response_model=PartnerIntegrationOut)
async def get_partner_integration(
    integration_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PartnerIntegrationOut:
    """Get a specific partner integration."""
    return await PartnerService(db).get_integration(integration_id, project_id, current_user)


@router.put("/{partner_id}", response_model=PartnerIntegrationOut)
async def replace_partner_integration(
    partner_id: UUID,
    data: PartnerIntegrationUpdate,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PartnerIntegrationOut:
    """Update partner integration settings."""
    return await PartnerService(db).update_integration(
        partner_id,
        project_id,
        data,
        current_user,
    )


@router.patch("/{integration_id}", response_model=PartnerIntegrationOut)
async def update_partner_integration(
    integration_id: UUID,
    data: PartnerIntegrationUpdate,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PartnerIntegrationOut:
    """Update a partner integration."""
    return await PartnerService(db).update_integration(
        integration_id,
        project_id,
        data,
        current_user,
    )


@router.delete("/{partner_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_partner_integration(
    partner_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a partner integration."""
    await PartnerService(db).delete_integration(partner_id, project_id, current_user)


@router.post("/submit", response_model=SubmitLeadResponse)
async def submit_lead_to_partner(
    data: SubmitLeadRequest,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SubmitLeadResponse:
    """Queue a lead submission to a partner CRM for the postback worker."""
    submission = await PartnerService(db).queue_lead_submission(
        lead_id=data.lead_id,
        partner_integration_id=data.partner_integration_id,
        project_id=project_id,
        actor=current_user,
    )
    return SubmitLeadResponse(status="queued", submission_id=submission.id)


@router.get("/submissions/{lead_id}", response_model=list[LeadSubmissionOut])
async def get_lead_submissions(
    lead_id: UUID,
    project_id: UUID = Depends(get_current_project_id),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[LeadSubmissionOut]:
    """Get all submissions for a specific lead."""
    return await PartnerService(db).list_lead_submissions(
        lead_id=lead_id,
        project_id=project_id,
        actor=current_user,
    )
