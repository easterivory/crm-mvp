"""Configurable, person-deduplicated journey; independent of funnel execution."""
from datetime import datetime, time, timedelta, timezone
from uuid import UUID, uuid5, NAMESPACE_URL
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import Integer, String, and_, case, cast, column, exists, func, literal, select, tuple_, union_all
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID, insert
from sqlalchemy.orm import aliased

from app.core.constants import MessageType, RoleName, SenderType
from app.models.chat import Chat
from app.models.channel_tracking import TelegramChannelSubscriptionEvent
from app.models.funnel import ChatFunnelState, Funnel, FunnelScheduledJob, FunnelStep, FunnelStepLog, FunnelVersion
from app.models.lead import Lead, LeadTag
from app.models.message import Message
from app.models.tag import Tag
from app.models.tracking import TrackingLink
from app.models.tracking_journey import LeadTagHistory, TrackingJourneyConfig
from app.repositories.tracking_start_query import is_telegram_start
from app.schemas.tracking_journey import JourneyConfig, JourneyStage
from app.services.tracking_step_metrics_service import TrackingStepMetricsService

MSK = ZoneInfo("Europe/Moscow")


def person_key(chat):
    # A missing ID never merges unrelated contacts. Username is not an identity.
    return case((and_(chat.external_user_id.is_not(None), chat.external_user_id != ""),
                 func.concat("tg:", chat.external_user_id)), else_=func.concat("chat:", chat.id))


def ratio(numerator, denominator):
    return numerator * 100 / denominator if denominator else None


class TrackingStageJourneyService:
    def __init__(self, db):
        self.db = db
        self.steps = TrackingStepMetricsService(db)
        self.metrics = self.steps.metrics

    @staticmethod
    def default_configuration(options, funnel_id):
        own_steps = sorted((o for o in options if o["funnel_id"] == funnel_id), key=lambda o: (-o["version_number"], o["number"]))
        if len(own_steps) > 399:
            return None
        return JourneyConfig(mode="steps", scope="funnel", stages=[
            JourneyStage(id=uuid5(NAMESPACE_URL, f"journey:{funnel_id}:start"), name="Первый приход", source="start"),
            *[JourneyStage(id=uuid5(NAMESPACE_URL, f"journey:{funnel_id}:step:{o['key']}"),
                name=f"#{o['number']} · {o['title']}"[:80], source="entered",
                step_refs=[{"funnel_id": funnel_id, "key": o["key"]}]) for o in own_steps]
        ]).model_dump(mode="json")

    async def configuration(self, actor, project_id, funnel_id, *, include_catalogue=True):
        await self.metrics._ensure_project_access(actor, project_id)
        await self.metrics._get_active_project_or_404(project_id)
        found = (await self.db.execute(select(Funnel.id, Funnel.bot_id).where(Funnel.id == funnel_id, Funnel.project_id == project_id,
            exists(select(FunnelVersion.id).where(FunnelVersion.funnel_id == Funnel.id, FunnelVersion.status != "draft"))))
            ).one_or_none()
        if not found:
            raise HTTPException(404, "Опубликованная воронка не найдена")
        saved = await self.db.scalar(select(TrackingJourneyConfig).where(TrackingJourneyConfig.funnel_id == funnel_id)
            .execution_options(populate_existing=True))
        if saved and saved.project_id != project_id:
            raise HTTPException(404, "Настройки этапов не найдены в проекте")
        options = None
        if saved and saved.config_json.get("mode", "stages") != "steps":
            config_data = saved.config_json
        else:
            options = await self.steps.options(actor, project_id, found.bot_id)
            config_data = self.default_configuration(options, funnel_id)
            if config_data is None and not include_catalogue:
                raise HTTPException(422, "В обзоре поддерживается до 399 шагов; настройте отдельные этапы")
            if saved and config_data is not None:
                config_data.update({"scope": saved.config_json.get("scope", "funnel"),
                                    "idle_hours": saved.config_json.get("idle_hours", 24)})
        result = {"config": config_data, "is_default": saved is None,
                  "can_edit": actor.role_name in {RoleName.ADMIN, RoleName.SUPER_ADMIN}}
        if not include_catalogue:
            return result
        if options is None:
            options = await self.steps.options(actor, project_id, found.bot_id)
        tags = (await self.db.execute(select(Tag.id, Tag.name).where(Tag.project_id == project_id).order_by(Tag.name))).mappings().all()
        legacy = await self.db.scalar(select(exists(select(LeadTagHistory.id)
            .join(Lead, Lead.id == LeadTagHistory.lead_id)
            .where(Lead.project_id == project_id, LeadTagHistory.source == "legacy_snapshot"))))
        return {**result, "default_config": self.default_configuration(options, funnel_id),
                "steps": options, "tags": tags, "has_legacy_tag_snapshot": legacy}

    async def save(self, actor, project_id, funnel_id, config: JourneyConfig):
        await self.metrics._ensure_project_access(actor, project_id)
        await self.metrics._get_active_project_or_404(project_id)
        if actor.role_name not in {RoleName.ADMIN, RoleName.SUPER_ADMIN}:
            raise HTTPException(403, "Настройка этапов доступна администратору")
        found = (await self.db.execute(select(Funnel.bot_id).where(Funnel.id == funnel_id, Funnel.project_id == project_id,
            exists(select(FunnelVersion.id).where(FunnelVersion.funnel_id == Funnel.id, FunnelVersion.status != "draft"))))).one_or_none()
        if found is None:
            raise HTTPException(404, "Опубликованная воронка не найдена")
        bot_id = found.bot_id
        options = await self.steps.options(actor, project_id, bot_id)
        references = {(s["funnel_id"], s["key"]) for s in options}
        keys = {key for owner, key in references if owner == funnel_id}
        requested_tags = {tag_id for stage in config.stages for tag_id in stage.tag_ids}
        tags = set((await self.db.scalars(select(Tag.id).where(Tag.project_id == project_id, Tag.id.in_(requested_tags)))).all())
        if any(set(s.step_keys) - keys or set(s.tag_ids) - tags or
               any((r.funnel_id, r.key) not in references or (config.scope == "funnel" and r.funnel_id != funnel_id)
                   for r in s.step_refs) for s in config.stages):
            raise HTTPException(422, "Шаги и теги должны принадлежать выбранной воронке и проекту")
        data = config.model_dump(mode="json")
        await self.db.execute(insert(TrackingJourneyConfig).values(
            funnel_id=funnel_id, project_id=project_id, config_json=data).on_conflict_do_update(
                index_elements=[TrackingJourneyConfig.funnel_id],
                set_={"config_json": data, "updated_at": datetime.now(timezone.utc)}))
        return {"config": data}

    async def query(self, actor, project_id, funnel_id, *, bot_id=None, buyer_id=None,
                    link_id=None, date_from=None, date_to=None):
        catalogue = await self.configuration(actor, project_id, funnel_id, include_catalogue=False)
        if not catalogue["config"]:
            raise HTTPException(409, "Настройте этапы и итоговый тег")
        config = JourneyConfig.model_validate(catalogue["config"])
        buyer_id = self.metrics.resolve_buyer_filter(actor, buyer_id)
        funnel_bot = await self.db.scalar(select(Funnel.bot_id).where(Funnel.id == funnel_id, Funnel.project_id == project_id))
        if bot_id and bot_id != funnel_bot:
            raise HTTPException(422, "Воронка не относится к выбранному боту")
        if link_id:
            link = await self.metrics.link_repo.get_link_by_id(link_id)
            if not link or link.project_id != project_id or (buyer_id and link.buyer_id != buyer_id):
                raise HTTPException(404, "Ссылка не найдена")
            if link.bot_id != funnel_bot:
                raise HTTPException(422, "Ссылка и воронка должны относиться к одному боту")
        date_from, date_to = self.metrics._resolve_date_range(date_from, date_to)
        if (date_to - date_from).days > 3660:
            raise HTTPException(422, "Диапазон не должен превышать 10 лет")
        start = datetime.combine(date_from, time.min, MSK)
        end = datetime.combine(date_to + timedelta(days=1), time.min, MSK)
        as_of = datetime.now(timezone.utc)

        start_rows = (select(Chat.id.label("chat_id"), Message.created_at.label("at"),
                Message.id.label("message_id"), Message.tracking_link_id,
                func.row_number().over(partition_by=Chat.id, order_by=(Message.created_at, Message.id)).label("rank"))
            .join(Message, Message.chat_id == Chat.id).where(Chat.project_id == project_id,
                Message.sender_type == SenderType.USER, Message.message_type == MessageType.TEXT,
                is_telegram_start(), Message.created_at <= as_of)
            .cte("stage_start_rows"))
        starts = select(start_rows).where(start_rows.c.rank == 1).cte("stage_starts")
        channel_rows = (select(TelegramChannelSubscriptionEvent.funnel_start_chat_id.label("chat_id"),
                TelegramChannelSubscriptionEvent.tracking_link_id,
                func.row_number().over(partition_by=TelegramChannelSubscriptionEvent.funnel_start_chat_id,
                    order_by=(TelegramChannelSubscriptionEvent.occurred_at, TelegramChannelSubscriptionEvent.id)).label("rank"))
            .where(TelegramChannelSubscriptionEvent.project_id == project_id,
                   TelegramChannelSubscriptionEvent.funnel_started_at.is_not(None),
                   TelegramChannelSubscriptionEvent.funnel_start_chat_id.is_not(None)).cte("stage_channel_rows"))
        channel = select(channel_rows).where(channel_rows.c.rank == 1).cte("stage_channel_origin")
        entries = (select(Chat.id.label("chat_id"), func.min(FunnelStepLog.created_at).label("at"))
            .join(Lead, Lead.chat_id == Chat.id).join(FunnelStepLog, FunnelStepLog.lead_id == Lead.id)
            .where(Chat.project_id == project_id, Lead.project_id == project_id, FunnelStepLog.event_type == "entered", FunnelStepLog.created_at <= as_of)
            .group_by(Chat.id).cte("stage_initial_entries"))
        acquired = func.least(starts.c.at, entries.c.at)
        first_is_start = and_(starts.c.at.is_not(None), (entries.c.at.is_(None)) | (starts.c.at <= entries.c.at))
        origin_link = case((first_is_start, starts.c.tracking_link_id),
                           (channel.c.chat_id.is_not(None), channel.c.tracking_link_id), else_=Chat.tracking_link_id)
        # Rank before all date/bot/link filters, including retained deleted chats.
        # A later duplicate must not become a new acquisition when filters change.
        ranked = (select(Chat.id.label("chat_id"), Chat.bot_id, Chat.external_user_id, origin_link.label("tracking_link_id"),
                         Chat.is_deleted, person_key(Chat).label("person"), acquired.label("acquired_at"),
                         func.row_number().over(partition_by=person_key(Chat),
                             order_by=(acquired, func.coalesce(starts.c.message_id, Chat.id), Chat.id)).label("rank"))
            .outerjoin(starts, starts.c.chat_id == Chat.id).outerjoin(entries, entries.c.chat_id == Chat.id)
            .outerjoin(channel, channel.c.chat_id == Chat.id)
            .where(Chat.project_id == project_id, acquired.is_not(None)).cte("stage_ranked"))
        cohort_query = (select(ranked).outerjoin(TrackingLink, and_(TrackingLink.id == ranked.c.tracking_link_id,
                          TrackingLink.project_id == project_id))
            .where(ranked.c.rank == 1, ranked.c.is_deleted.is_(False), ranked.c.bot_id == funnel_bot,
                   ranked.c.acquired_at >= start, ranked.c.acquired_at < end))
        if buyer_id:
            cohort_query = cohort_query.where(TrackingLink.buyer_id == buyer_id)
        if link_id:
            cohort_query = cohort_query.where(ranked.c.tracking_link_id == link_id)
        if config.scope == "funnel":
            # One ordered history scan replaces a correlated scan per person.
            identity = person_key(Chat)
            first_funnels = (select(identity.label("person"), FunnelStepLog.funnel_id)
                .select_from(Chat).join(Lead, Lead.chat_id == Chat.id)
                .join(FunnelStepLog, FunnelStepLog.lead_id == Lead.id)
                .where(Chat.project_id == project_id, Lead.project_id == project_id,
                       FunnelStepLog.event_type == "entered", FunnelStepLog.created_at <= as_of)
                .distinct(identity).order_by(identity, FunnelStepLog.created_at, FunnelStepLog.id)
                .cte("stage_first_funnels"))
            # Keep start-only people, but do not mix leads from unrelated funnels
            # of the same bot into a specific funnel's conversion denominator.
            cohort_query = cohort_query.outerjoin(first_funnels, first_funnels.c.person == ranked.c.person).where(
                first_funnels.c.funnel_id.is_(None) | (first_funnels.c.funnel_id == funnel_id))
        cohort = cohort_query.cte("stage_cohort")
        identified = and_(cohort.c.external_user_id.is_not(None), cohort.c.external_user_id != "")
        def member_rows(match, identity_filter):
            return (select(cohort.c.chat_id.label("origin_chat_id"), cohort.c.acquired_at,
                           Lead.id.label("lead_id"), Chat.id.label("chat_id"))
                .join(Chat, and_(Chat.project_id == project_id, match))
                .join(Lead, and_(Lead.chat_id == Chat.id, Lead.project_id == project_id))
                .where(identity_filter))
        # Keep anonymous contacts separate and let known IDs use the identity index.
        members = union_all(
            member_rows(Chat.external_user_id == cohort.c.external_user_id, identified),
            member_rows(Chat.id == cohort.c.chat_id, ~identified),
        ).cte("stage_members")
        facts = []
        tag_map, step_map = [], []
        for index, stage in enumerate(config.stages):
            if stage.source == "start":
                facts.append(select(cohort.c.chat_id, literal(index).label("stage"), cohort.c.acquired_at.label("at")))
            elif stage.source == "tag":
                tag_map.extend({"stage": index, "tag_id": str(tag_id)} for tag_id in set(stage.tag_ids))
            else:
                references = {(r.funnel_id, r.key) for r in stage.step_refs}
                references.update((funnel_id, key) for key in stage.step_keys)
                step_map.extend({"stage": index, "event_type": stage.source, "funnel_id": str(owner), "step_key": key}
                                for owner, key in sorted(references))
        # Read each history once, joining the selected stage mappings. JSONB keeps
        # even a large catalogue below PostgreSQL's prepared-parameter limit.
        if tag_map:
            tag_mapping = func.jsonb_to_recordset(cast(literal(tag_map, type_=JSONB), JSONB)).table_valued(
                column("stage", Integer), column("tag_id", PGUUID)).render_derived(name="stage_tag_map", with_types=True)
            facts.append(select(members.c.origin_chat_id, tag_mapping.c.stage, LeadTagHistory.occurred_at.label("at"))
                .join(LeadTagHistory, LeadTagHistory.lead_id == members.c.lead_id)
                .join(tag_mapping, tag_mapping.c.tag_id == LeadTagHistory.tag_id)
                .where(LeadTagHistory.occurred_at >= members.c.acquired_at, LeadTagHistory.occurred_at <= as_of))
        if step_map:
            step_mapping = func.jsonb_to_recordset(cast(literal(step_map, type_=JSONB), JSONB)).table_valued(
                column("stage", Integer), column("event_type", String), column("funnel_id", PGUUID),
                column("step_key", String)).render_derived(name="stage_step_map", with_types=True)
            facts.append(select(members.c.origin_chat_id, step_mapping.c.stage, FunnelStepLog.created_at.label("at"))
                .join(FunnelStepLog, FunnelStepLog.lead_id == members.c.lead_id)
                .join(FunnelStep, FunnelStep.id == FunnelStepLog.step_id)
                .join(step_mapping, and_(step_mapping.c.funnel_id == FunnelStepLog.funnel_id,
                    step_mapping.c.step_key == FunnelStep.key, step_mapping.c.event_type == FunnelStepLog.event_type))
                .where(FunnelStepLog.created_at >= members.c.acquired_at, FunnelStepLog.created_at <= as_of))
        events = union_all(*facts).cte("stage_events")
        first = (select(events.c.chat_id, events.c.stage, func.min(events.c.at).label("at"))
            .group_by(events.c.chat_id, events.c.stage).cte("stage_first"))
        timeline = (select(cohort, *[func.max(case((first.c.stage == i, first.c.at))).label(f"s{i}")
                                    for i in range(len(config.stages))])
            .outerjoin(first, first.c.chat_id == cohort.c.chat_id).group_by(*cohort.c).cte("stage_timeline"))
        last_stage = func.greatest(*[case((timeline.c[f"s{i}"].is_not(None), i), else_=-1)
                                     for i in range(len(config.stages))])
        member_chat = aliased(Chat)
        scheduled = exists(select(FunnelScheduledJob.id).where(
            FunnelScheduledJob.funnel_state_id == ChatFunnelState.id,
            FunnelScheduledJob.status.in_(["pending", "running"]),
            FunnelScheduledJob.job_type.not_in(["input_timeout", "no_reply_timeout"])))
        state_scope = (ChatFunnelState.funnel_id == funnel_id if config.scope == "funnel" else
            exists(select(Funnel.id).where(Funnel.id == ChatFunnelState.funnel_id, Funnel.bot_id == funnel_bot,
                                           Funnel.project_id == project_id)))
        stalled_people = (select(members.c.origin_chat_id).join(member_chat, member_chat.id == members.c.chat_id)
            .join(ChatFunnelState, ChatFunnelState.chat_id == member_chat.id)
            .where(state_scope,
                   ChatFunnelState.completed_at.is_(None), ChatFunnelState.is_paused.is_(False),
                   ChatFunnelState.waiting_for_answer.is_(True), ~scheduled,
                   func.greatest(ChatFunnelState.entered_step_at, member_chat.last_user_message_at,
                                 member_chat.last_client_message_at) <= as_of - timedelta(hours=config.idle_hours))
            .distinct().cte("stage_stalled_people"))
        wide = (select(timeline, last_stage.label("last_stage"),
                       stalled_people.c.origin_chat_id.is_not(None).label("stalled"))
            .outerjoin(stalled_people, stalled_people.c.origin_chat_id == timeline.c.chat_id).cte("stage_wide"))
        return config, wide, members, date_from, date_to

    @staticmethod
    def aggregates(config, wide):
        count = lambda condition: func.count().filter(condition)
        columns = [func.count().label("people")]
        for i in range(len(config.stages)):
            source = wide.c[f"s{i}"]
            remaining = wide.c.last_stage == i
            if config.stages[-1].role == "outcome":
                remaining = and_(remaining, wide.c[f"s{len(config.stages)-1}"].is_(None))
            columns += [count(source.is_not(None)).label(f"reached{i}"), count(remaining).label(f"remaining{i}"),
                        count(and_(remaining, wide.c.stalled)).label(f"stalled{i}")]
            if i < len(config.stages) - 1:
                columns.append(count(and_(source.is_not(None), wide.c[f"s{i+1}"] >= source)).label(f"next{i}"))
        offer = next((i for i, s in enumerate(config.stages) if s.role == "offer"), None)
        if offer is not None:
            columns.append(count(and_(wide.c[f"s{offer}"].is_not(None),
                wide.c[f"s{len(config.stages)-1}"] >= wide.c[f"s{offer}"])).label("offer_outcome"))
        return columns

    @staticmethod
    def present(config, row):
        items = []
        for i, stage in enumerate(config.stages):
            reached, onward = row[f"reached{i}"], row.get(f"next{i}")
            items.append({**stage.model_dump(mode="json"), "number": i + 1, "reached": reached,
                "remaining": row[f"remaining{i}"], "stalled": row[f"stalled{i}"], "next": onward,
                "conversion": ratio(onward, reached) if onward is not None else None,
                "not_yet_next": reached - onward if onward is not None else None})
        offer = next((i for i, s in enumerate(config.stages) if s.role == "offer"), None)
        has_outcome = config.stages[-1].role == "outcome"
        return {"people": row["people"], "outcomes": items[-1]["reached"] if has_outcome else None,
                "conversion": ratio(items[-1]["reached"], row["people"]) if has_outcome else None,
                "offer_conversion": ratio(row.get("offer_outcome", 0), row[f"reached{offer}"]) if offer is not None else None,
                "items": items}

    @staticmethod
    def period_start(day, granularity):
        if granularity == "week":
            return day - timedelta(days=day.weekday())
        if granularity == "month":
            return day.replace(day=1)
        return day

    async def report(self, actor, project_id, funnel_id, *, granularity="day", sources_offset=0, sources_limit=50, **filters):
        config, wide, members, date_from, date_to = await self.query(actor, project_id, funnel_id, **filters)
        columns = self.aggregates(config, wide)
        bucket = func.date_trunc(granularity, func.timezone("Europe/Moscow", wide.c.acquired_at))
        # Compute totals, cohort dynamics and source breakdown in one pass over
        # the same timeline, rather than rescanning message/log history three times.
        groups = (await self.db.execute(select(bucket.label("date"),
                wide.c.tracking_link_id.label("link_id"), TrackingLink.title, TrackingLink.code,
                func.grouping(bucket).label("date_group"),
                func.grouping(wide.c.tracking_link_id).label("link_group"), *columns,
                select(func.count(func.distinct(members.c.chat_id))).scalar_subquery().label("physical_chats"))
            .select_from(wide)
            .outerjoin(TrackingLink, and_(TrackingLink.id == wide.c.tracking_link_id, TrackingLink.project_id == project_id))
            .group_by(func.grouping_sets(tuple_(), tuple_(bucket),
                tuple_(wide.c.tracking_link_id, TrackingLink.title, TrackingLink.code))))).mappings().all()
        totals = next(r for r in groups if r["date_group"] and r["link_group"])
        daily = sorted((r for r in groups if not r["date_group"]), key=lambda r: r["date"])
        sources = sorted((r for r in groups if not r["link_group"]), key=lambda r: (-r["people"], str(r["link_id"])))
        indexed = {r["date"].date(): r for r in daily}
        cursor = self.period_start(date_from, granularity)
        zero = {c.name: 0 for c in columns}
        series = []
        while cursor <= date_to:
            series.append({"date": cursor, **self.present(config, indexed.get(cursor, zero))})
            cursor = (cursor.replace(year=cursor.year + (cursor.month == 12), month=cursor.month % 12 + 1)
                      if granularity == "month" else cursor + timedelta(days=7 if granularity == "week" else 1))
        return {**self.present(config, totals), "physical_chats": totals["physical_chats"],
                "date_from": date_from, "date_to": date_to, "timezone": "Europe/Moscow", "granularity": granularity,
                "daily": series, "sources_total": len(sources),
                "sources": [{"link_id": r["link_id"], "title": r["title"], "code": r["code"], **self.present(config, r)}
                            for r in sources[sources_offset:sources_offset + sources_limit]]}

    async def chats(self, actor, project_id, funnel_id, stage_id: UUID, *, bucket="reached", limit=50, offset=0, **filters):
        config, wide, _, _, _ = await self.query(actor, project_id, funnel_id, **filters)
        index = next((i for i, s in enumerate(config.stages) if s.id == stage_id), None)
        if index is None:
            raise HTTPException(404, "Этап не найден")
        condition = wide.c[f"s{index}"].is_not(None)
        if bucket != "reached":
            condition = wide.c.last_stage == index
            if config.stages[-1].role == "outcome":
                condition = and_(condition, wide.c[f"s{len(config.stages)-1}"].is_(None))
            if bucket == "stalled":
                condition = and_(condition, wide.c.stalled)
        selected = select(wide.c.chat_id, wide.c.tracking_link_id, wide.c[f"s{index}"].label("stage_at")).where(condition).cte("stage_selection")
        total_query = select(func.count().label("total")).select_from(selected).cte("stage_selection_total")
        page = (select(Chat.id.label("chat_id"), Lead.id.label("lead_id"), Lead.name,
                Lead.username, Chat.contact_name, Chat.last_message_at, TrackingLink.title.label("link_title"),
                TrackingLink.code.label("link_code"), selected.c.stage_at)
            .select_from(selected).join(Chat, Chat.id == selected.c.chat_id).outerjoin(Lead, Lead.chat_id == Chat.id)
            .outerjoin(TrackingLink, and_(TrackingLink.id == selected.c.tracking_link_id, TrackingLink.project_id == project_id))
            .order_by(Chat.last_message_at.desc().nullslast(), Chat.id).limit(limit).offset(offset).cte("stage_selection_page"))
        results = (await self.db.execute(select(total_query.c.total, *page.c).select_from(total_query)
            .outerjoin(page, literal(True)).order_by(page.c.last_message_at.desc().nullslast(), page.c.chat_id))).mappings().all()
        total = results[0]["total"]
        rows = [{key: value for key, value in row.items() if key != "total"} for row in results if row["chat_id"] is not None]
        tags = {}
        if rows:
            for lead_id, name in (await self.db.execute(select(LeadTag.lead_id, Tag.name).join(Tag, Tag.id == LeadTag.tag_id)
                .where(Tag.project_id == project_id, LeadTag.lead_id.in_([r["lead_id"] for r in rows])).order_by(Tag.name))).all():
                tags.setdefault(lead_id, []).append(name)
        return {"items": [{**r, "tags": tags.get(r["lead_id"], [])} for r in rows], "total": total}
