"""Read-only reached-step metrics for the current acquisition cohort."""
from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import distinct, exists, func, select

from app.models.chat import Chat
from app.models.funnel import Funnel, FunnelVersion, FunnelStep, FunnelStepLog
from app.models.lead import Lead
from app.models.tracking import TrackingLink
from app.services.tracking_metrics_service import TrackingMetricsService
from app.repositories.tracking_metrics_repository import TrackingMetricsRepository


class TrackingStepMetricsService:
    def __init__(self, db):
        self.db = db
        self.metrics = TrackingMetricsService(db)

    async def options(self, actor, project_id, bot_id=None):
        await self.metrics._ensure_project_access(actor, project_id)
        await self.metrics._get_active_project_or_404(project_id)
        if bot_id:
            await self.metrics._ensure_bot_in_project(bot_id, project_id)
        # Include archived versions for historical analysis, retaining the latest
        # identity of each stable step key within its own funnel.
        stmt = (select(FunnelStep.id, FunnelStep.key, FunnelStep.title, Funnel.name, Funnel.id.label("funnel_id"),
                       Funnel.bot_id, FunnelVersion.version_number)
                .join(FunnelVersion, FunnelVersion.id == FunnelStep.funnel_version_id)
                .join(Funnel, Funnel.id == FunnelVersion.funnel_id)
                .where(Funnel.project_id == project_id, FunnelVersion.status != "draft")
                .order_by(Funnel.name, FunnelVersion.version_number.desc(), FunnelStep.key))
        if bot_id:
            stmt = stmt.where(Funnel.bot_id == bot_id)
        rows = (await self.db.execute(stmt)).all()
        seen, result = set(), []
        for row in rows:
            key = (row.funnel_id, row.key)
            if key not in seen:
                seen.add(key)
                result.append({"id": row.id, "name": f"{row.name} · {row.title}", "bot_id": row.bot_id})
        return result

    @staticmethod
    def query(*, project_id, step_key, funnel_id, date_from, date_to, bot_id=None, link_id=None, buyer_id=None):
        lifecycle = TrackingMetricsRepository._lead_lifecycle_at()
        start, end = TrackingMetricsRepository._date_bounds(date_from, date_to)
        day = func.date(func.timezone("UTC", lifecycle))
        reached = exists(select(FunnelStepLog.id).join(FunnelStep, FunnelStep.id == FunnelStepLog.step_id).where(
            FunnelStepLog.lead_id == Lead.id, FunnelStepLog.funnel_id == funnel_id,
            FunnelStep.key == step_key, FunnelStepLog.event_type == "entered",
            FunnelStepLog.created_at >= lifecycle))
        stmt = (select(day.label("date"), func.count(distinct(Lead.id)).label("count"))
                .select_from(Lead).join(Chat, Chat.id == Lead.chat_id)
                .outerjoin(TrackingLink, TrackingLink.id == Chat.tracking_link_id)
                .where(Lead.project_id == project_id, Chat.project_id == project_id,
                       Lead.is_deleted.is_(False), Chat.is_deleted.is_(False), Chat.reset_at.is_(None),
                       lifecycle >= start, lifecycle < end, reached))
        if bot_id:
            stmt = stmt.where(Chat.bot_id == bot_id)
        if link_id:
            stmt = stmt.where(Chat.tracking_link_id == link_id)
        if buyer_id:
            stmt = stmt.where(TrackingLink.buyer_id == buyer_id, TrackingLink.project_id == project_id)
        return stmt.group_by(day).order_by(day)

    async def get(self, actor, project_id, step_id: UUID, *, bot_id=None, link_id=None, buyer_id=None, date_from=None, date_to=None):
        await self.metrics._ensure_project_access(actor, project_id)
        await self.metrics._get_active_project_or_404(project_id)
        buyer_id = self.metrics.resolve_buyer_filter(actor, buyer_id)
        if bot_id:
            await self.metrics._ensure_bot_in_project(bot_id, project_id)
        if link_id:
            link = await self.metrics.link_repo.get_link_by_id(link_id)
            if not link or link.project_id != project_id or (buyer_id and link.buyer_id != buyer_id):
                raise HTTPException(404, "Ссылка не найдена")
        row = (await self.db.execute(select(FunnelStep.key, FunnelStep.title, Funnel.id, Funnel.name)
            .join(FunnelVersion, FunnelVersion.id == FunnelStep.funnel_version_id)
            .join(Funnel, Funnel.id == FunnelVersion.funnel_id)
            .where(FunnelStep.id == step_id, Funnel.project_id == project_id))).one_or_none()
        if row is None:
            raise HTTPException(404, "Шаг не найден в проекте")
        date_from, date_to = self.metrics._resolve_date_range(date_from, date_to)
        counts = dict((await self.db.execute(self.query(project_id=project_id, step_key=row.key, funnel_id=row.id,
            date_from=date_from, date_to=date_to, bot_id=bot_id, link_id=link_id, buyer_id=buyer_id))).all())
        daily = [{"date": date_from + timedelta(days=i), "count": counts.get(date_from + timedelta(days=i), 0)}
                 for i in range((date_to - date_from).days + 1)]
        return {"step_id": step_id, "name": f"{row.name} · {row.title}", "total": sum(d["count"] for d in daily), "daily": daily}
