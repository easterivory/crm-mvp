"""
StatsService — aggregates daily statistics for all projects.

Called by stats_worker once per day.
Counts lead status transitions for the target date and writes to daily_stats.
"""
from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import LeadStatusCode
from app.repositories.lead_repository import LeadRepository
from app.repositories.stats_repository import StatsRepository
from app.services.metrics_service import MetricsService


class StatsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.lead_repo = LeadRepository(db)
        self.stats_repo = StatsRepository(db)
        self.metrics = MetricsService(db)

    async def aggregate_for_date(self, project_id: UUID, target_date: date) -> None:
        """
        Compute and upsert daily_stats for project_id on target_date.
        Idempotent — safe to call multiple times for the same date.
        """
        status_counts = await self.lead_repo.aggregate_leads_by_status_for_date(
            project_id=project_id,
            target_date=target_date,
        )
        avg_response_seconds = await self.metrics.avg_response_seconds_for_project_date(
            project_id=project_id,
            target_date=target_date,
        )

        await self.stats_repo.upsert(
            project_id,
            target_date,
            new_chats=status_counts.get(LeadStatusCode.NEW, 0),
            processed_chats=status_counts.get(LeadStatusCode.IN_PROGRESS, 0),
            qualified_chats=status_counts.get(LeadStatusCode.QUALIFIED, 0),
            lost_chats=status_counts.get(LeadStatusCode.LOST, 0),
            avg_response_time_sec=(
                round(avg_response_seconds)
                if avg_response_seconds is not None
                else None
            ),
        )

    async def aggregate_today(self, project_id: UUID) -> None:
        """Compatibility helper used by stats_worker."""
        await self.aggregate_for_date(project_id, date.today())
