"""Cohort quality metrics, independent from calendar-day activity totals."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import String, case, cast, distinct, func, literal, select

from app.models.chat import Chat
from app.models.channel_tracking import TelegramChannelSubscriptionEvent as ChannelEvent
from app.models.lead import Lead, LeadTag
from app.models.lead_status import LeadStatus
from app.models.tracking import TrackingEvent, TrackingSpend
from app.repositories.lifecycle_metrics_repository import LifecycleMetricsRepository
from app.repositories.tracking_metrics_repository import TrackingMetricsRepository


class TrafficQualityRepository:
    def __init__(self, db):
        self.db = db

    async def metrics(self, project, link, rule, now: datetime, timezone: str = "Europe/Moscow") -> dict:
        end = now - timedelta(hours=rule.maturation_hours)
        if "spend" in rule.expression:
            end = end.astimezone(ZoneInfo(timezone)).replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(hours=rule.window_hours)
        # Same Telegram user on a bot and personal account is one person, but
        # only chats with this confirmed link attribution enter the cohort.
        identity = func.coalesce(func.nullif(Chat.external_user_id, ""), cast(Chat.id, String))
        members = select(
            Lead.id.label("lead_id"), identity.label("person"),
            func.coalesce(Chat.current_cycle_started_at, Chat.created_at).label("entered_at"),
            LeadStatus.code.label("status"),
        ).select_from(Lead).join(Chat, Chat.id == Lead.chat_id).outerjoin(
            LeadStatus, LeadStatus.id == Lead.status_id,
        ).where(
            Chat.project_id == project.id, Chat.tracking_link_id == link.id,
            Chat.is_deleted.is_(False), Chat.reset_at.is_(None), Lead.is_deleted.is_(False),
        ).cte("quality_members")
        first = select(members.c.person, func.min(members.c.entered_at).label("entered_at")).group_by(members.c.person).cte("quality_first")
        cohort = select(first).where(first.c.entered_at >= start, first.c.entered_at < end).cte("quality_cohort")
        people = select(members).join(cohort, cohort.c.person == members.c.person).cte("quality_people")
        totals = (await self.db.execute(select(
            func.count(distinct(people.c.person)).label("leads"),
            func.count(distinct(people.c.person)).filter(people.c.status.in_(project.tracking_lead_status_codes)).label("qualified_leads"),
        ))).mappings().one()
        values = dict(totals)

        tagged = select(people.c.person).join(LeadTag, LeadTag.lead_id == people.c.lead_id).where(
            LeadTag.tag_id.in_(rule.tag_ids),
        ).group_by(people.c.person)
        if rule.tag_match == "all":
            tagged = tagged.having(func.count(distinct(LeadTag.tag_id)) == len(set(rule.tag_ids)))
        values["tagged_leads"] = await self.db.scalar(select(func.count()).select_from(tagged.subquery()))
        assessed = select(people.c.person).outerjoin(LeadTag, LeadTag.lead_id == people.c.lead_id).where(
            LeadTag.tag_id.in_(rule.assessed_tag_ids) | people.c.status.in_(rule.assessed_status_codes),
        ).distinct().subquery()
        values["assessed_leads"] = await self.db.scalar(select(func.count()).select_from(assessed))
        # For ratios among assessed people, count bad tags only within that set.
        if "assessed_leads" in rule.expression or rule.sample_metric == "assessed_leads":
            bad = tagged.subquery()
            values["tagged_leads"] = await self.db.scalar(select(func.count()).select_from(bad).join(assessed, assessed.c.person == bad.c.person))
        values["coverage"] = (100 * values["assessed_leads"] / values["leads"]) if values["leads"] else None

        events = LifecycleMetricsRepository._eligible_events(project.id)
        lifecycle = (await self.db.execute(select(
            func.count(distinct(people.c.person)).filter(events.c.event_type == "registration").label("registrations"),
            func.count(distinct(people.c.person)).filter(events.c.event_type == "deposit").label("first_deposits"),
            func.count(distinct(people.c.person)).filter(events.c.event_type == "redeposit").label("redepositors"),
            func.count(distinct(events.c.id)).filter(events.c.event_type == "redeposit").label("redeposits"),
        ).select_from(events).join(people, people.c.lead_id == events.c.lead_id).join(cohort, cohort.c.person == people.c.person).where(
            events.c.tracking_link_id == link.id, events.c.occurred_at >= cohort.c.entered_at, events.c.occurred_at <= now,
        ))).mappings().one()
        values.update(lifecycle)
        milestones = select(
            people.c.person,
            func.min(events.c.occurred_at).filter(events.c.event_type == "registration").label("reg"),
            func.min(events.c.occurred_at).filter(events.c.event_type == "deposit").label("fd"),
            func.max(events.c.occurred_at).filter(events.c.event_type == "redeposit").label("rd"),
        ).select_from(events).join(people, people.c.lead_id == events.c.lead_id).join(cohort, cohort.c.person == people.c.person).where(
            events.c.tracking_link_id == link.id, events.c.occurred_at >= cohort.c.entered_at, events.c.occurred_at <= now,
        ).group_by(people.c.person).subquery()
        paired = (await self.db.execute(select(
            func.count().filter(milestones.c.fd >= milestones.c.reg).label("registered_depositors"),
            func.count().filter(milestones.c.rd >= milestones.c.fd).label("deposited_redepositors"),
        ).select_from(milestones))).mappings().one()
        values.update(paired)
        submissions = TrackingMetricsRepository._first_successful_submissions()
        values["submitted_leads"] = await self.db.scalar(select(func.count(distinct(people.c.person))).select_from(
            submissions,
        ).join(people, people.c.lead_id == submissions.c.lead_id).join(cohort, cohort.c.person == people.c.person).where(
            submissions.c.success_number == 1, submissions.c.occurred_at >= cohort.c.entered_at,
            submissions.c.occurred_at <= now, submissions.c.tracking_link_id == link.id,
        ))
        if project.project_format == "gambling":
            values["submitted_leads"] = None
        values["clicks"] = await self.db.scalar(select(func.sum(TrackingEvent.clicks)).where(
            TrackingEvent.tracking_link_id == link.id, TrackingEvent.created_at >= start, TrackingEvent.created_at < end,
        ))
        values["spend"] = None
        if "spend" in rule.expression:
            spend = (await self.db.execute(select(TrackingSpend.currency, func.sum(TrackingSpend.amount)).where(
                TrackingSpend.tracking_link_id == link.id, TrackingSpend.spend_date >= start.date(),
                TrackingSpend.spend_date < end.date(),
            ).group_by(TrackingSpend.currency))).all()
            if len(spend) == 1:
                values["spend"] = float(spend[0][1])
        values.update(channel_join_requests=None, channel_joins=None, channel_leaves=None, funnel_starts=None, approved_requests=None, request_funnel_starts=None)
        if link.destination_type == "channel":
            entered = select(ChannelEvent.telegram_user_id.label("person"), func.min(ChannelEvent.occurred_at).label("entered_at")).where(
                ChannelEvent.tracking_link_id == link.id, ChannelEvent.event_type.in_(("join_request", "join")),
            ).group_by(ChannelEvent.telegram_user_id).cte("quality_channel_first")
            channel_cohort = select(entered).where(entered.c.entered_at >= start, entered.c.entered_at < end).cte("quality_channel_cohort")
            row = (await self.db.execute(select(
                func.count(distinct(ChannelEvent.telegram_user_id)).filter(ChannelEvent.event_type == "join_request").label("channel_join_requests"),
                func.count(distinct(ChannelEvent.telegram_user_id)).filter(ChannelEvent.event_type == "join").label("channel_joins"),
                func.count(distinct(ChannelEvent.telegram_user_id)).filter(ChannelEvent.event_type.in_(("leave", "kick"))).label("channel_leaves"),
                func.count(distinct(ChannelEvent.telegram_user_id)).filter(ChannelEvent.funnel_started_at.is_not(None)).label("funnel_starts"),
            ).join(channel_cohort, channel_cohort.c.person == ChannelEvent.telegram_user_id).where(
                ChannelEvent.tracking_link_id == link.id, ChannelEvent.occurred_at >= channel_cohort.c.entered_at,
                ChannelEvent.occurred_at <= now,
            ))).mappings().one()
            values.update(row)
            flags = select(
                ChannelEvent.telegram_user_id,
                func.count().filter(ChannelEvent.event_type == "join_request").label("requested"),
                func.count().filter(ChannelEvent.event_type == "join").label("joined"),
                func.count().filter(ChannelEvent.funnel_started_at.is_not(None)).label("started"),
            ).join(channel_cohort, channel_cohort.c.person == ChannelEvent.telegram_user_id).where(
                ChannelEvent.tracking_link_id == link.id, ChannelEvent.occurred_at >= channel_cohort.c.entered_at,
                ChannelEvent.occurred_at <= now,
            ).group_by(ChannelEvent.telegram_user_id).subquery()
            paired = (await self.db.execute(select(
                func.count().filter((flags.c.requested > 0) & (flags.c.joined > 0)).label("approved_requests"),
                func.count().filter((flags.c.requested > 0) & (flags.c.started > 0)).label("request_funnel_starts"),
            ).select_from(flags))).mappings().one()
            values.update(paired)
        return {"metrics": values, "period_from": start.isoformat(), "period_to": end.isoformat(), "observed_at": now.isoformat()}
