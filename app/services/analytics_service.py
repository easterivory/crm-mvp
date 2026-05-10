"""
AnalyticsService - traffic attribution and unit economics.
"""
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import TrackingCostModel
from app.repositories.tracking_repository import TrackingRepository
from app.schemas.tracking import TrafficStatsOut


class AnalyticsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.tracking_repo = TrackingRepository(db)

    async def get_traffic_stats(self, project_id: UUID) -> list[TrafficStatsOut]:
        rows = await self.tracking_repo.get_traffic_stats(project_id)

        stats: list[TrafficStatsOut] = []
        for link, chat_clicks, event_clicks, impressions, leads in rows:
            clicks = max(int(chat_clicks or 0), int(event_clicks or 0))
            impressions_count = int(impressions or 0)
            leads_count = int(leads or 0)
            spend = self._calculate_spend(
                cost_model=link.cost_model,
                price_per_unit=Decimal(link.price_per_unit or 0),
                manual_spend=Decimal(link.spend or 0),
                clicks=clicks,
                impressions=impressions_count,
                leads=leads_count,
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
                )
            )

        return stats

    @staticmethod
    def _calculate_spend(
        *,
        cost_model: TrackingCostModel,
        price_per_unit: Decimal,
        manual_spend: Decimal,
        clicks: int,
        impressions: int,
        leads: int,
    ) -> Decimal:
        if cost_model == TrackingCostModel.FIX_PDP:
            spend = Decimal(clicks) * price_per_unit
        elif cost_model == TrackingCostModel.CPM:
            spend = (Decimal(impressions) / Decimal("1000")) * price_per_unit
        elif cost_model == TrackingCostModel.CPA:
            spend = Decimal(leads) * price_per_unit if price_per_unit > 0 else manual_spend
        else:
            spend = manual_spend

        return AnalyticsService._money(spend)

    @staticmethod
    def _calculate_cpl(*, spend: Decimal, leads: int) -> Decimal:
        if leads <= 0:
            return Decimal("0.00")
        return AnalyticsService._money(spend / Decimal(leads))

    @staticmethod
    def _money(value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
