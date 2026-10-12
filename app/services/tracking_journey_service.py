"""Read-only funnel progression for the same acquisition cohort as tracking."""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import and_, case, exists, func, select
from sqlalchemy.orm import aliased

from app.models.chat import Chat
from app.models.funnel import ChatFunnelState, FunnelStep, FunnelStepLog, FunnelScheduledJob
from app.models.lead import Lead, LeadTag
from app.models.lead_status import LeadStatus
from app.models.tag import Tag
from app.models.tracking import TrackingLink
from app.repositories.tracking_metrics_repository import TrackingMetricsRepository
from app.services.tracking_step_metrics_service import TrackingStepMetricsService


BUCKETS = ("reached", "continued", "current", "waiting", "delayed", "manual", "stalled")


class TrackingJourneyService:
    def __init__(self, db):
        self.db = db
        self.steps = TrackingStepMetricsService(db)
        self.metrics = self.steps.metrics

    async def scope(self, actor, project_id, funnel_id, *, bot_id=None, buyer_id=None,
                    link_id=None, date_from=None, date_to=None):
        options = await self.steps.options(actor, project_id, bot_id)
        options = [option for option in options if option["funnel_id"] == funnel_id]
        if not options:
            raise HTTPException(404, "Опубликованная воронка не найдена")
        buyer_id = self.metrics.resolve_buyer_filter(actor, buyer_id)
        if link_id:
            link = await self.metrics.link_repo.get_link_by_id(link_id)
            if not link or link.project_id != project_id or (buyer_id and link.buyer_id != buyer_id):
                raise HTTPException(404, "Ссылка не найдена")
        date_from, date_to = self.metrics._resolve_date_range(date_from, date_to)
        lifecycle = TrackingMetricsRepository._lead_lifecycle_at()
        start, end = TrackingMetricsRepository._date_bounds(date_from, date_to)
        cohort = (select(Lead.id.label("lead_id"), Chat.id.label("chat_id"), lifecycle.label("lifecycle"))
            .select_from(Lead).join(Chat, Chat.id == Lead.chat_id)
            .outerjoin(TrackingLink, and_(TrackingLink.id == Chat.tracking_link_id,
                                         TrackingLink.project_id == project_id))
            .where(Lead.project_id == project_id, Chat.project_id == project_id,
                   Lead.is_deleted.is_(False), Chat.is_deleted.is_(False), Chat.reset_at.is_(None),
                   lifecycle >= start, lifecycle < end))
        if bot_id:
            cohort = cohort.where(Chat.bot_id == bot_id)
        if buyer_id:
            cohort = cohort.where(TrackingLink.project_id == project_id, TrackingLink.buyer_id == buyer_id)
        if link_id:
            cohort = cohort.where(Chat.tracking_link_id == link_id)
        return options, cohort.cte("journey_cohort"), date_from, date_to

    @staticmethod
    def observations(cohort, funnel_id, idle_hours, now):
        entered = (select(cohort.c.lead_id, cohort.c.chat_id, FunnelStep.key.label("step_key"),
                          func.min(FunnelStepLog.created_at).label("first_entry"))
            .join(FunnelStepLog, FunnelStepLog.lead_id == cohort.c.lead_id)
            .join(FunnelStep, FunnelStep.id == FunnelStepLog.step_id)
            .where(FunnelStepLog.funnel_id == funnel_id, FunnelStepLog.event_type == "entered",
                   FunnelStepLog.created_at >= cohort.c.lifecycle)
            .group_by(cohort.c.lead_id, cohort.c.chat_id, FunnelStep.key).cte("journey_entries"))
        current_step = aliased(FunnelStep)
        later_log, later_step = aliased(FunnelStepLog), aliased(FunnelStep)
        later_entry = exists(select(later_log.id).join(later_step, later_step.id == later_log.step_id).where(
            later_log.lead_id == entered.c.lead_id, later_log.funnel_id == funnel_id,
            later_log.event_type == "entered", later_log.created_at > entered.c.first_entry,
            later_step.key != entered.c.step_key))
        # PostgreSQL now() is constant within a transaction: adjacent automatic
        # steps can share a timestamp. The runtime snapshot also proves departure.
        runtime_departed = and_(ChatFunnelState.id.is_not(None),
            ChatFunnelState.entered_step_at >= entered.c.first_entry,
            (current_step.key != entered.c.step_key) | ChatFunnelState.completed_at.is_not(None))
        continued = later_entry | runtime_departed
        current = and_(ChatFunnelState.id.is_not(None), ChatFunnelState.completed_at.is_(None),
                       current_step.key == entered.c.step_key)
        manual = and_(current, ChatFunnelState.is_paused.is_(True))
        scheduled = exists(select(FunnelScheduledJob.id).where(
            FunnelScheduledJob.funnel_state_id == ChatFunnelState.id,
            FunnelScheduledJob.status.in_(["pending", "running"]),
            (FunnelScheduledJob.job_type.not_in(["input_timeout", "no_reply_timeout"]))
            | ChatFunnelState.waiting_for_answer.is_(False)))
        delayed = and_(current, ~manual, scheduled)
        waiting = and_(current, ~manual, ~scheduled, ChatFunnelState.waiting_for_answer.is_(True))
        last_activity = func.greatest(ChatFunnelState.entered_step_at,
                                      Chat.last_client_message_at, Chat.last_user_message_at)
        stalled = and_(waiting, last_activity <= now - timedelta(hours=idle_hours))
        # Continued is historical; the current-state columns are a separate snapshot.
        return (select(entered, continued.label("continued"), current.label("current"),
                       waiting.label("waiting"), delayed.label("delayed"), manual.label("manual"),
                       stalled.label("stalled"))
            .join(Chat, Chat.id == entered.c.chat_id)
            .outerjoin(ChatFunnelState, and_(ChatFunnelState.chat_id == Chat.id,
                                           ChatFunnelState.funnel_id == funnel_id))
            .outerjoin(current_step, current_step.id == ChatFunnelState.current_step_id).cte("journey_observations"))

    async def report(self, actor, project_id, funnel_id, *, idle_hours=24, **filters):
        options, cohort, date_from, date_to = await self.scope(actor, project_id, funnel_id, **filters)
        observed = self.observations(cohort, funnel_id, idle_hours, datetime.now(timezone.utc))
        rows = (await self.db.execute(select(observed.c.step_key, func.count().label("reached"),
            *[func.sum(case((observed.c[bucket].is_(True), 1), else_=0)).label(bucket)
              for bucket in BUCKETS if bucket != "reached"])
            .group_by(observed.c.step_key))).mappings().all()
        counts = {row["step_key"]: dict(row) for row in rows}
        items = []
        for option in options:
            item = {**option, **{bucket: 0 for bucket in BUCKETS}, **counts.get(option["key"], {})}
            item["conversion"] = item["continued"] * 100 / item["reached"] if item["reached"] else None
            items.append(item)
        return {"items": items, "date_from": date_from, "date_to": date_to, "idle_hours": idle_hours}

    async def chats(self, actor, project_id, funnel_id, step_id, *, bucket="reached", idle_hours=24,
                    limit=50, offset=0, **filters):
        options, cohort, _, _ = await self.scope(actor, project_id, funnel_id, **filters)
        option = next((option for option in options if option["id"] == step_id), None)
        if option is None:
            raise HTTPException(404, "Шаг не найден в воронке")
        observed = self.observations(cohort, funnel_id, idle_hours, datetime.now(timezone.utc))
        selection = select(observed.c.lead_id, observed.c.chat_id).where(observed.c.step_key == option["key"])
        if bucket != "reached":
            selection = selection.where(observed.c[bucket].is_(True))
        selection = selection.cte("journey_selection")
        total = await self.db.scalar(select(func.count()).select_from(selection))
        rows = (await self.db.execute(select(Chat.id.label("chat_id"), Lead.id.label("lead_id"),
            Lead.name, Lead.username, Chat.contact_name, Chat.last_message_at, LeadStatus.name.label("status"),
            TrackingLink.id.label("link_id"), TrackingLink.title.label("link_title"), TrackingLink.code.label("link_code"))
            .select_from(Chat).join(selection, selection.c.chat_id == Chat.id).join(Lead, Lead.id == selection.c.lead_id)
            .outerjoin(LeadStatus, LeadStatus.id == Lead.status_id)
            .outerjoin(TrackingLink, and_(TrackingLink.id == Chat.tracking_link_id,
                                         TrackingLink.project_id == project_id))
            .order_by(Chat.last_message_at.desc().nullslast(), Chat.id).limit(limit).offset(offset))).mappings().all()
        tags = {}
        if rows:
            for lead_id, name in (await self.db.execute(select(LeadTag.lead_id, Tag.name)
                .join(Tag, Tag.id == LeadTag.tag_id).where(Tag.project_id == project_id,
                    LeadTag.lead_id.in_([row["lead_id"] for row in rows])).order_by(Tag.name))).all():
                tags.setdefault(lead_id, []).append(name)
        return {"items": [{**row, "tags": tags.get(row["lead_id"], [])} for row in rows],
                "total": total, "limit": limit, "offset": offset}
