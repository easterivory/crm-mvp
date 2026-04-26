from datetime import date
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.models.daily_stats import DailyStats
from app.repositories.base import BaseRepository


class StatsRepository(BaseRepository[DailyStats]):
    model = DailyStats

    async def get_by_date(self, project_id: UUID, target_date: date) -> Optional[DailyStats]:
        result = await self.db.execute(
            select(DailyStats).where(
                DailyStats.project_id == project_id,
                DailyStats.date == target_date,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(self, project_id: UUID, target_date: date, **values: int) -> None:
        """Insert or update daily_stats for project+date (idempotent)."""
        stmt = (
            insert(DailyStats)
            .values(project_id=project_id, date=target_date, **values)
            .on_conflict_do_update(
                constraint="uq_daily_stats_project_date",
                set_=values,
            )
        )
        await self.db.execute(stmt)

    async def list_by_project(
        self, project_id: UUID, limit: int = 30, offset: int = 0
    ) -> list[DailyStats]:
        result = await self.db.execute(
            select(DailyStats)
            .where(DailyStats.project_id == project_id)
            .order_by(DailyStats.date.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())
