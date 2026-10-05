"""Cohort intersection, deliberately separate from activity-total ratios."""
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import case, exists, func, select, true

from app.models.chat import Chat
from app.models.funnel import Funnel, FunnelVersion, FunnelStep, FunnelStepLog
from app.models.lead import Lead, LeadTag
from app.models.lead_event import LeadEvent
from app.models.tag import Tag
from app.models.tracking import TrackingLink
from app.repositories.lifecycle_metrics_repository import REGISTRATION_EVENT_TYPES, FIRST_DEPOSIT_EVENT_TYPES, REDEPOSIT_EVENT_TYPES
from app.repositories.tracking_metrics_repository import TrackingMetricsRepository
from app.services.tracking_metrics_service import TrackingMetricsService


class TrackingCohortService:
    def __init__(self, db):
        self.db = db
        self.metrics = TrackingMetricsService(db)

    async def predicate(self, key, project_id):
        lifecycle = TrackingMetricsRepository._lead_lifecycle_at()
        if key == "arrivals":
            return true()
        if key == "submitted_leads":
            submissions = TrackingMetricsRepository._first_successful_submissions()
            return exists(select(submissions.c.id).where(submissions.c.lead_id == Lead.id,
                submissions.c.project_id == project_id, submissions.c.success_number == 1,
                submissions.c.occurred_at >= lifecycle))
        event_types = {"registrations": REGISTRATION_EVENT_TYPES, "first_deposits": FIRST_DEPOSIT_EVENT_TYPES, "redeposits": REDEPOSIT_EVENT_TYPES}
        if key in event_types:
            return exists(select(LeadEvent.id).where(LeadEvent.project_id == project_id,
                LeadEvent.lead_id == Lead.id, LeadEvent.event_type.in_(event_types[key]), LeadEvent.occurred_at >= lifecycle))
        kind, separator, value = key.partition(":")
        try:
            item_id = UUID(value)
        except ValueError as exc:
            raise HTTPException(422, "Неизвестный показатель когорты") from exc
        if kind == "tag" and separator:
            if not await self.db.scalar(select(Tag.id).where(Tag.id == item_id, Tag.project_id == project_id)):
                raise HTTPException(404, "Тег не найден")
            return exists(select(LeadTag.lead_id).where(LeadTag.lead_id == Lead.id, LeadTag.tag_id == item_id))
        if kind == "step" and separator:
            row = (await self.db.execute(select(FunnelStep.key, Funnel.id).join(FunnelVersion,
                FunnelVersion.id == FunnelStep.funnel_version_id).join(Funnel, Funnel.id == FunnelVersion.funnel_id)
                .where(FunnelStep.id == item_id, Funnel.project_id == project_id))).one_or_none()
            if row is None:
                raise HTTPException(404, "Шаг не найден")
            return exists(select(FunnelStepLog.id).join(FunnelStep, FunnelStep.id == FunnelStepLog.step_id).where(
                FunnelStepLog.lead_id == Lead.id, FunnelStepLog.funnel_id == row.id, FunnelStep.key == row.key,
                FunnelStepLog.event_type == "entered", FunnelStepLog.created_at >= lifecycle))
        raise HTTPException(422, "Неизвестный показатель когорты")

    @staticmethod
    def query(project_id, date_from, date_to, source, target, *, bot_id=None, buyer_id=None, link_id=None):
        lifecycle = TrackingMetricsRepository._lead_lifecycle_at()
        start, end = TrackingMetricsRepository._date_bounds(date_from, date_to)
        stmt = (select(func.count(Lead.id).label("base"), func.sum(case((target, 1), else_=0)).label("converted"))
            .select_from(Lead).join(Chat, Chat.id == Lead.chat_id)
            .outerjoin(TrackingLink, TrackingLink.id == Chat.tracking_link_id)
            .where(Lead.project_id == project_id, Chat.project_id == project_id,
                Lead.is_deleted.is_(False), Chat.is_deleted.is_(False), Chat.reset_at.is_(None),
                lifecycle >= start, lifecycle < end, source))
        if bot_id:
            stmt = stmt.where(Chat.bot_id == bot_id)
        if buyer_id:
            stmt = stmt.where(TrackingLink.project_id == project_id, TrackingLink.buyer_id == buyer_id)
        if link_id:
            stmt = stmt.where(Chat.tracking_link_id == link_id)
        return stmt

    async def get(self, actor, project_id, source, target, *, bot_id=None, buyer_id=None, link_id=None, date_from=None, date_to=None):
        await self.metrics._ensure_project_access(actor, project_id)
        await self.metrics._get_active_project_or_404(project_id)
        buyer_id = self.metrics.resolve_buyer_filter(actor, buyer_id)
        if bot_id:
            await self.metrics._ensure_bot_in_project(bot_id, project_id)
        if link_id:
            link = await self.metrics.link_repo.get_link_by_id(link_id)
            if not link or link.project_id != project_id or (buyer_id and link.buyer_id != buyer_id):
                raise HTTPException(404, "Ссылка не найдена")
        date_from, date_to = self.metrics._resolve_date_range(date_from, date_to)
        source_filter, target_filter = await self.predicate(source, project_id), await self.predicate(target, project_id)
        row = (await self.db.execute(self.query(project_id, date_from, date_to, source_filter, target_filter,
            bot_id=bot_id, buyer_id=buyer_id, link_id=link_id))).one()
        return {"base": row.base, "converted": row.converted or 0,
            "percent": (row.converted or 0) * 100 / row.base if row.base else None,
            "date_from": date_from, "date_to": date_to}
