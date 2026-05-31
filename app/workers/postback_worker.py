"""
ARQ worker for sending lead postbacks to partner CRMs.
"""
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.models.lead import Lead
from app.models.partner import LeadSubmission, PartnerIntegration

logger = logging.getLogger(__name__)


async def send_lead_postback(
    ctx: dict,
    lead_id: str,
    partner_integration_id: str,
) -> dict:
    """
    Send lead data to partner CRM via HTTP POST.

    Args:
        ctx: ARQ context
        lead_id: UUID of the lead to submit
        partner_integration_id: UUID of the partner integration

    Returns:
        dict with status and submission_id
    """
    async with async_session_factory() as db:
        try:
            lead_uuid = UUID(lead_id)
            partner_uuid = UUID(partner_integration_id)

            # Create submission record
            submission = LeadSubmission(
                lead_id=lead_uuid,
                partner_integration_id=partner_uuid,
                status="pending",
                submitted_at=datetime.utcnow(),
            )
            db.add(submission)
            await db.commit()
            await db.refresh(submission)

            # Fetch lead and partner integration
            lead_result = await db.execute(
                select(Lead).where(Lead.id == lead_uuid)
            )
            lead = lead_result.scalar_one_or_none()

            partner_result = await db.execute(
                select(PartnerIntegration).where(PartnerIntegration.id == partner_uuid)
            )
            partner = partner_result.scalar_one_or_none()

            if not lead or not partner:
                submission.status = "failed"
                submission.error_message = "Lead or partner integration not found"
                submission.completed_at = datetime.utcnow()
                await db.commit()
                return {"status": "failed", "submission_id": str(submission.id)}

            if not partner.is_active:
                submission.status = "failed"
                submission.error_message = "Partner integration is not active"
                submission.completed_at = datetime.utcnow()
                await db.commit()
                return {"status": "failed", "submission_id": str(submission.id)}

            # Build request payload
            payload = {
                "lead_id": str(lead.id),
                "name": lead.name,
                "phone": lead.phone,
                "username": lead.username,
                "age": lead.age,
                "country": lead.country,
                "call_time": lead.call_time_text,
                "has_card": lead.has_card,
                "score_percent": lead.score_percent,
                "custom_fields": lead.custom_fields,
                "created_at": lead.created_at.isoformat() if lead.created_at else None,
            }

            submission.request_payload = payload
            await db.commit()

            # Send HTTP POST request
            headers = {"Content-Type": "application/json"}
            if partner.auth_token:
                headers["Authorization"] = f"Bearer {partner.auth_token}"

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    partner.postback_url,
                    json=payload,
                    headers=headers,
                )

                submission.response_payload = {
                    "status_code": response.status_code,
                    "body": response.text[:1000],  # Limit response size
                }

                if response.status_code in (200, 201, 202):
                    submission.status = "success"
                else:
                    submission.status = "failed"
                    submission.error_message = f"HTTP {response.status_code}: {response.text[:500]}"

                submission.completed_at = datetime.utcnow()
                await db.commit()

                logger.info(
                    f"Postback sent for lead {lead_id} to {partner.name}: {submission.status}"
                )

                return {
                    "status": submission.status,
                    "submission_id": str(submission.id),
                    "http_status": response.status_code,
                }

        except httpx.TimeoutException:
            submission.status = "failed"
            submission.error_message = "Request timeout"
            submission.completed_at = datetime.utcnow()
            await db.commit()
            logger.error(f"Timeout sending postback for lead {lead_id}")
            return {"status": "failed", "submission_id": str(submission.id)}

        except Exception as e:
            submission.status = "failed"
            submission.error_message = str(e)[:1000]
            submission.completed_at = datetime.utcnow()
            await db.commit()
            logger.exception(f"Error sending postback for lead {lead_id}")
            return {"status": "failed", "submission_id": str(submission.id), "error": str(e)}


class WorkerSettings:
    """ARQ worker settings."""
    functions = [send_lead_postback]
    redis_settings = None  # Will be set from config
