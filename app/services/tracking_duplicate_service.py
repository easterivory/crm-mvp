"""On-demand duplicate-card cohorts; never changes acquisition attribution."""
from datetime import date, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select, text, tuple_
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import aliased

from app.core.constants import RoleName
from app.models.chat import Chat
from app.models.lead import Lead
from app.models.tracking import TrackingLink
from app.repositories.tracking_metrics_repository import TrackingMetricsRepository
from app.services.access_control import accessible_project_ids
from app.services.lead_identity_service import LeadIdentityService
from app.services.tracking_metrics_service import TrackingMetricsService


class TrackingDuplicateService:
    def __init__(self, db):
        self.db = db
        self.metrics = TrackingMetricsService(db)

    @staticmethod
    def query(project_id, date_from, date_to, *, bot_id=None, buyer_id=None, link_id=None, visible_project_ids=None):
        previous = aliased(Lead)
        previous_chat = aliased(Chat)
        phone = LeadIdentityService._phone_digits_expr
        username = LeadIdentityService._username_expr
        identities = [
            and_(Chat.external_user_id.is_not(None), func.trim(Chat.external_user_id) != "",
                 previous_chat.external_user_id == func.trim(Chat.external_user_id)),
            and_(Lead.phone.is_not(None), phone(Lead) != "", previous.phone.is_not(None), phone(previous) == phone(Lead)),
            and_(Lead.username.is_not(None), func.trim(username(Lead)) != "", previous.username.is_not(None), username(previous) == func.trim(username(Lead))),
        ]

        def match(cross_project):
            branches = []
            for identity in identities:
                branch = select(previous.id).join(previous_chat, previous_chat.id == previous.chat_id).where(
                    previous.id != Lead.id, identity,
                    tuple_(previous.created_at, previous.id) < tuple_(Lead.created_at, Lead.id),
                    previous.project_id != project_id if cross_project else previous.project_id == project_id)
                if visible_project_ids is not None:
                    branch = branch.where(previous.project_id.in_(visible_project_ids))
                branches.append(branch.correlate(Lead, Chat).exists())
            return or_(*branches)

        start, end = TrackingMetricsRepository._date_bounds(date_from, date_to)
        cohort = select(Lead.id, Chat.tracking_link_id.label("link_id"), TrackingLink.title, TrackingLink.code,
            func.date(func.timezone("UTC", Lead.created_at)).label("date"),
            match(False).label("within_project"), match(True).label("cross_project"))
        cohort = cohort.select_from(Lead).join(Chat, Chat.id == Lead.chat_id).outerjoin(TrackingLink, TrackingLink.id == Chat.tracking_link_id).where(
            Lead.project_id == project_id, Chat.project_id == project_id, Lead.is_deleted.is_(False),
            Chat.is_deleted.is_(False), Chat.reset_at.is_(None), Lead.created_at >= start, Lead.created_at < end)
        if bot_id:
            cohort = cohort.where(Chat.bot_id == bot_id)
        if link_id:
            cohort = cohort.where(Chat.tracking_link_id == link_id)
        if buyer_id:
            cohort = cohort.where(TrackingLink.project_id == project_id, TrackingLink.buyer_id == buyer_id)
        cohort = cohort.cte("duplicate_cohort").prefix_with("MATERIALIZED", dialect="postgresql")
        return select(cohort.c.date, cohort.c.link_id, cohort.c.title, cohort.c.code,
            func.count().label("cards"),
            func.count().filter(or_(cohort.c.within_project, cohort.c.cross_project)).label("duplicates"),
            func.count().filter(cohort.c.within_project).label("within_project"),
            func.count().filter(cohort.c.cross_project).label("cross_project")).group_by(
                cohort.c.date, cohort.c.link_id, cohort.c.title, cohort.c.code)

    async def report(self, actor, project_id: UUID, *, bot_id=None, buyer_id=None, link_id=None, date_from=None, date_to=None):
        await self.metrics._ensure_project_access(actor, project_id)
        await self.metrics._get_active_project_or_404(project_id)
        buyer_id = self.metrics.resolve_buyer_filter(actor, buyer_id)
        if bot_id:
            await self.metrics._ensure_bot_in_project(bot_id, project_id)
        if link_id:
            link = await self.metrics.link_repo.get_link_by_id(link_id)
            if not link or link.project_id != project_id or (buyer_id and link.buyer_id != buyer_id):
                raise HTTPException(404, "Ссылка не найдена")
            if bot_id and bot_id != link.bot_id:
                raise HTTPException(422, "Ссылка не относится к выбранному боту")
        date_from, date_to = self.metrics._resolve_date_range(date_from, date_to)
        if (date_to - date_from).days > 3660:
            raise HTTPException(422, "Максимальный период отчёта — 10 лет.")
        visible = None if actor.role_name == RoleName.SUPER_ADMIN else accessible_project_ids(actor)
        try:
            async with self.db.begin_nested():
                old_timeout = await self.db.scalar(text("SHOW statement_timeout"))
                await self.db.execute(text("SET LOCAL statement_timeout = '15s'"))
                rows = (await self.db.execute(self.query(project_id, date_from, date_to, bot_id=bot_id,
                    buyer_id=buyer_id, link_id=link_id, visible_project_ids=visible))).mappings().all()
                await self.db.execute(select(func.set_config("statement_timeout", old_timeout, True)))
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) in {"57014", "53100", "53200"}:
                raise HTTPException(503, "Не удалось рассчитать пересечения. Выберите меньший период и повторите.") from exc
            raise
        fields = ("cards", "duplicates", "within_project", "cross_project")
        summary = {key: 0 for key in fields}
        sources, daily = {}, {}
        for row in rows:
            source = sources.setdefault(row["link_id"], {"link_id": row["link_id"], "title": row["title"], "code": row["code"], **dict.fromkeys(fields, 0)})
            day = daily.setdefault(row["date"], {"date": row["date"], **dict.fromkeys(fields, 0)})
            for key in fields:
                value = int(row[key])
                summary[key] += value
                source[key] += value
                day[key] += value
        return {"project_id": project_id, "date_from": date_from, "date_to": date_to, "summary": summary,
            "daily": [daily.get(day, {"date": day, **dict.fromkeys(fields, 0)}) for day in
                (date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1))],
            "sources": sorted(sources.values(), key=lambda item: (-item["duplicates"], item["title"] or ""))}
