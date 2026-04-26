"""
StatsService — aggregates daily statistics for all projects.

Called by stats_worker once per day.
Counts lead status transitions for the target date and writes to daily_stats.
"""
from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

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
        raise NotImplementedError
