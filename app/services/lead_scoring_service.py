from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead


class LeadScoringService:
    """Calculate lead quality score based on collected data."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def calculate_score(self, lead_id: UUID) -> int:
        """
        Calculate lead score (0-100) based on completeness and quality indicators.

        Scoring criteria:
        - Name: 15 points
        - Phone: 25 points
        - Age: 10 points
        - Country: 10 points
        - Call time: 10 points
        - Has card: 20 points
        - Custom fields: 10 points (if any exist)
        """
        result = await self.db.execute(select(Lead).where(Lead.id == lead_id))
        lead = result.scalar_one_or_none()

        if not lead:
            return 0

        score = 0

        if lead.name:
            score += 15

        if lead.phone:
            score += 25

        if lead.age is not None:
            score += 10

        if lead.country:
            score += 10

        if lead.call_time_text:
            score += 10

        if lead.has_card is True:
            score += 20

        if lead.custom_fields and len(lead.custom_fields) > 0:
            score += 10

        return min(score, 100)

    async def update_lead_score(self, lead_id: UUID) -> Optional[int]:
        """Calculate and update the lead's score_percent field."""
        score = await self.calculate_score(lead_id)

        result = await self.db.execute(select(Lead).where(Lead.id == lead_id))
        lead = result.scalar_one_or_none()

        if lead:
            lead.score_percent = score
            await self.db.commit()
            await self.db.refresh(lead)
            return score

        return None
