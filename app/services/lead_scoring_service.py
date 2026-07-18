from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.lead_confidence_service import LeadConfidenceService


class LeadScoringService:
    """Backward-compatible facade for the production confidence engine."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.confidence = LeadConfidenceService(db)

    async def calculate_score(self, lead_id: UUID) -> int:
        result = await self.confidence.calculate_confidence_by_id(lead_id)
        if result is None:
            return 0
        return result.score_percent

    async def update_lead_score(self, lead_id: UUID) -> Optional[int]:
        """Calculate and update the lead's score_percent field."""
        return await self.confidence.update_lead_score(lead_id)
