"""
AnalyticsService - traffic attribution and unit economics.
"""
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.tracking_repository import TrackingRepository
from app.schemas.tracking import TrafficStatsOut
from app.services.tracking_conversion import calculate_conversion_status
from app.services.tracking_cost_service import calculate_tracking_spend


class AnalyticsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.tracking_repo = TrackingRepository(db)

    async def get_traffic_stats(self, project_id: UUID) -> list[TrafficStatsOut]:
        rows = await self.tracking_repo.get_traffic_stats(project_id)

        stats: list[TrafficStatsOut] = []
        for (
            link,
            chat_starts,
            event_clicks,
            impressions,
            leads,
            submitted_leads,
            stored_manual_spend,
        ) in rows:
            starts = int(chat_starts or 0)
            clicks = max(starts, int(event_clicks or 0))
            impressions_count = int(impressions or 0)
            leads_count = int(leads or 0)
            manual_spend = Decimal(stored_manual_spend or link.spend or 0)
            spend = calculate_tracking_spend(
                cost_model=link.cost_model,
                price_per_unit=Decimal(link.price_per_unit or 0),
                manual_spend=manual_spend,
                starts=starts,
                submitted_leads=int(submitted_leads or 0),
            )
            cpl = self._calculate_cpl(spend=spend, leads=leads_count)

            stats.append(
                TrafficStatsOut(
                    tracking_link_id=link.id,
                    name=link.name,
                    ref_code=link.ref_code,
                    cost_model=link.cost_model,
                    clicks=clicks,
                    impressions=impressions_count,
                    leads=leads_count,
                    spend=spend,
                    cpl=cpl,
                    base_conversion_rate=link.base_conversion_rate,
                    min_sample_size=link.min_sample_size,
                    conversion_status=calculate_conversion_status(
                        clicks=clicks,
                        starts=starts,
                        leads=leads_count,
                        base_conversion_rate=link.base_conversion_rate,
                        min_sample_size=link.min_sample_size,
                    ),
                )
            )

        return stats

    @staticmethod
    def _calculate_cpl(*, spend: Decimal, leads: int) -> Decimal:
        if leads <= 0:
            return Decimal("0.00")
        return AnalyticsService._money(spend / Decimal(leads))

    @staticmethod
    def _money(value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
