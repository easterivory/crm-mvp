from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.partner import LeadSubmission, PartnerIntegration
from app.models.user import User
from app.schemas.partner import (
    LeadSubmissionOut,
    PartnerIntegrationCreate,
    PartnerIntegrationOut,
    PartnerIntegrationUpdate,
    SubmitLeadRequest,
)
from app.workers.postback_worker import send_lead_postback

router = APIRouter()


@router.get("", response_model=List[PartnerIntegrationOut])
async def list_partner_integrations(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all partner integrations for a project."""
    result = await db.execute(
        select(PartnerIntegration)
        .where(PartnerIntegration.project_id == project_id)
        .order_by(PartnerIntegration.created_at.desc())
    )
    integrations = result.scalars().all()
    return integrations


@router.post("", response_model=PartnerIntegrationOut)
async def create_partner_integration(
    data: PartnerIntegrationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new partner integration."""
    integration = PartnerIntegration(
        project_id=data.project_id,
        name=data.name,
        postback_url=data.postback_url,
        auth_token=data.auth_token,
        is_active=data.is_active,
    )
    db.add(integration)
    await db.commit()
    await db.refresh(integration)
    return integration


@router.get("/{integration_id}", response_model=PartnerIntegrationOut)
async def get_partner_integration(
    integration_id: UUID,
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific partner integration."""
    result = await db.execute(
        select(PartnerIntegration).where(
            PartnerIntegration.id == integration_id,
            PartnerIntegration.project_id == project_id,
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(status_code=404, detail="Partner integration not found")
    return integration


@router.patch("/{integration_id}", response_model=PartnerIntegrationOut)
async def update_partner_integration(
    integration_id: UUID,
    project_id: UUID,
    data: PartnerIntegrationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a partner integration."""
    result = await db.execute(
        select(PartnerIntegration).where(
            PartnerIntegration.id == integration_id,
            PartnerIntegration.project_id == project_id,
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(status_code=404, detail="Partner integration not found")

    if data.name is not None:
        integration.name = data.name
    if data.postback_url is not None:
        integration.postback_url = data.postback_url
    if data.auth_token is not None:
        integration.auth_token = data.auth_token
    if data.is_active is not None:
        integration.is_active = data.is_active

    await db.commit()
    await db.refresh(integration)
    return integration


@router.delete("/{integration_id}")
async def delete_partner_integration(
    integration_id: UUID,
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a partner integration."""
    result = await db.execute(
        select(PartnerIntegration).where(
            PartnerIntegration.id == integration_id,
            PartnerIntegration.project_id == project_id,
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(status_code=404, detail="Partner integration not found")

    await db.delete(integration)
    await db.commit()
    return {"status": "deleted"}


@router.post("/submit", response_model=dict)
async def submit_lead_to_partner(
    data: SubmitLeadRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit a lead to a partner CRM (enqueues ARQ job)."""
    from app.core.redis import get_arq_pool

    pool = await get_arq_pool()
    job = await pool.enqueue_job(
        "send_lead_postback",
        str(data.lead_id),
        str(data.partner_integration_id),
    )

    return {
        "status": "enqueued",
        "job_id": job.job_id if job else None,
    }


@router.get("/submissions/{lead_id}", response_model=List[LeadSubmissionOut])
async def get_lead_submissions(
    lead_id: UUID,
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all submissions for a specific lead."""
    result = await db.execute(
        select(LeadSubmission)
        .where(LeadSubmission.lead_id == lead_id)
        .order_by(LeadSubmission.submitted_at.desc())
    )
    submissions = result.scalars().all()
    return submissions
