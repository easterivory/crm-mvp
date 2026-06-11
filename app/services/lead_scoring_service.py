from typing import Any, Optional
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

        if lead.preferred_call_time or lead.call_time_text:
            score += 10

        if lead.has_card is True:
            score += 20

        if lead.custom_fields and len(lead.custom_fields) > 0:
            score += 10

        score += self._quality_adjustment(lead)

        return max(0, min(score, 100))

    async def update_lead_score(self, lead_id: UUID) -> Optional[int]:
        """Calculate and update the lead's score_percent field."""
        score = await self.calculate_score(lead_id)

        result = await self.db.execute(select(Lead).where(Lead.id == lead_id))
        lead = result.scalar_one_or_none()

        if lead:
            lead.score_percent = score
            return score

        return None

    @staticmethod
    def _quality_adjustment(lead: Lead) -> int:
        values: list[Any] = [
            lead.name,
            lead.phone,
            lead.username,
            lead.country,
            lead.preferred_call_time,
            lead.call_time_text,
            lead.has_card,
            *(lead.custom_fields or {}).values(),
        ]
        joined = " ".join(str(value).lower() for value in values if value is not None)
        adjustment = 0
        if any(marker in joined for marker in {"до 100", "100$", "$100", "до $100"}):
            adjustment -= 20
        if lead.has_card is True or any(
            marker in joined
            for marker in {
                "есть карта",
                "карта есть",
                "да, есть",
                "имею карту",
                "card yes",
            }
        ):
            adjustment += 30
        return adjustment
