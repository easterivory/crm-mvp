from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from sqlalchemy import String, cast, case, distinct, func, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AuditAction, EntityType, RoleName
from app.models.audit_log import AuditLog
from app.models.funnel import ChatFunnelState, FunnelRuntimeLog, FunnelStep
from app.models.lead import Lead
from app.models.partner import LeadSubmission
from app.models.role import Role
from app.models.user import User, UserProjectAccess
from app.schemas.manager_analytics import ManagerPerformanceOut


class ManagerAnalyticsService:
    """Project-scoped quality metrics based on immutable manager actions."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_project_performance(
        self,
        *,
        project_id: UUID,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[ManagerPerformanceOut]:
        start_at, end_at = self._date_bounds(date_from=date_from, date_to=date_to)

        taken_filters = [
            AuditLog.project_id == project_id,
            AuditLog.action == AuditAction.LEAD_MANAGER_ASSIGNED,
            AuditLog.entity_type == EntityType.LEAD,
            AuditLog.actor_id.is_not(None),
            AuditLog.meta["to_manager_id"].astext == cast(AuditLog.actor_id, String),
        ]
        self._append_period(taken_filters, AuditLog.created_at, start_at, end_at)
        taken_totals = (
            select(
                AuditLog.actor_id.label("manager_id"),
                func.count(distinct(AuditLog.entity_id)).label("chats_taken"),
            )
            .where(*taken_filters)
            .group_by(AuditLog.actor_id)
            .subquery()
        )

        submission_filters = [
            Lead.project_id == project_id,
            Lead.is_deleted.is_(False),
            LeadSubmission.submitted_by_user_id.is_not(None),
        ]
        self._append_period(submission_filters, LeadSubmission.submitted_at, start_at, end_at)
        submission_totals = (
            select(
                LeadSubmission.submitted_by_user_id.label("manager_id"),
                func.count(distinct(LeadSubmission.lead_id)).label("submitted_leads"),
                func.count(
                    distinct(
                        case(
                            (LeadSubmission.is_valid.is_(True), LeadSubmission.lead_id),
                            else_=None,
                        )
                    )
                ).label("valid_leads"),
            )
            .join(Lead, Lead.id == LeadSubmission.lead_id)
            .where(*submission_filters)
            .group_by(LeadSubmission.submitted_by_user_id)
            .subquery()
        )

        resumed_filters = [
            AuditLog.project_id == project_id,
            AuditLog.action == AuditAction.CHAT_FUNNEL_RESUMED,
            AuditLog.entity_type == EntityType.CHAT,
            AuditLog.actor_id.is_not(None),
        ]
        self._append_period(resumed_filters, AuditLog.created_at, start_at, end_at)
        resumed_totals = (
            select(
                AuditLog.actor_id.label("manager_id"),
                func.count(distinct(AuditLog.entity_id)).label("returned_to_funnel"),
            )
            .where(*resumed_filters)
            .group_by(AuditLog.actor_id)
            .subquery()
        )

        assigned_to_manager = (
            select(
                AuditLog.meta["to_manager_id"].astext.label("manager_id"),
                AuditLog.entity_id.label("lead_id"),
                func.max(AuditLog.created_at).label("assigned_at"),
            )
            .where(
                AuditLog.project_id == project_id,
                AuditLog.action == AuditAction.LEAD_MANAGER_ASSIGNED,
                AuditLog.entity_type == EntityType.LEAD,
                AuditLog.meta["to_manager_id"].astext.is_not(None),
            )
            .group_by(AuditLog.meta["to_manager_id"].astext, AuditLog.entity_id)
            .subquery()
        )

        finish_log_filters = [
            FunnelRuntimeLog.chat_id == Lead.chat_id,
            FunnelRuntimeLog.status == "success",
            FunnelRuntimeLog.created_at >= assigned_to_manager.c.assigned_at,
            FunnelStep.step_type == "finish",
        ]
        self._append_period(finish_log_filters, FunnelRuntimeLog.created_at, start_at, end_at)
        finish_log_exists = (
            select(FunnelRuntimeLog.id)
            .join(FunnelStep, FunnelStep.id == FunnelRuntimeLog.step_id)
            .where(*finish_log_filters)
            .exists()
        )

        completed_state_filters = [
            ChatFunnelState.chat_id == Lead.chat_id,
            ChatFunnelState.completed_at.is_not(None),
            ChatFunnelState.completed_at >= assigned_to_manager.c.assigned_at,
        ]
        self._append_period(completed_state_filters, ChatFunnelState.completed_at, start_at, end_at)
        completed_state_exists = select(ChatFunnelState.id).where(*completed_state_filters).exists()

        pushed_source = union_all(
            select(
                assigned_to_manager.c.manager_id.label("manager_id"),
                Lead.id.label("lead_id"),
            )
            .join(Lead, Lead.id == assigned_to_manager.c.lead_id)
            .where(
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
                finish_log_exists,
            ),
            select(
                assigned_to_manager.c.manager_id.label("manager_id"),
                Lead.id.label("lead_id"),
            )
            .join(Lead, Lead.id == assigned_to_manager.c.lead_id)
            .where(
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
                completed_state_exists,
            ),
        ).subquery()
        funnels_pushed_totals = (
            select(
                pushed_source.c.manager_id,
                func.count(distinct(pushed_source.c.lead_id)).label("funnels_pushed"),
            )
            .group_by(pushed_source.c.manager_id)
            .subquery()
        )

        result = await self.db.execute(
            select(
                User.id.label("manager_id"),
                User.name,
                User.email,
                User.handler_code,
                func.coalesce(taken_totals.c.chats_taken, 0).label("chats_taken"),
                func.coalesce(submission_totals.c.submitted_leads, 0).label("submitted_leads"),
                func.coalesce(submission_totals.c.valid_leads, 0).label("valid_leads"),
                func.coalesce(funnels_pushed_totals.c.funnels_pushed, 0).label("funnels_pushed"),
                func.coalesce(resumed_totals.c.returned_to_funnel, 0).label("returned_to_funnel"),
            )
            .join(Role, Role.id == User.role_id)
            .outerjoin(taken_totals, taken_totals.c.manager_id == User.id)
            .outerjoin(submission_totals, submission_totals.c.manager_id == User.id)
            .outerjoin(resumed_totals, resumed_totals.c.manager_id == User.id)
            .outerjoin(funnels_pushed_totals, funnels_pushed_totals.c.manager_id == cast(User.id, String))
            .where(
                Role.name == RoleName.MANAGER,
                User.is_deleted.is_(False),
                or_(
                    User.project_id == project_id,
                    User.id.in_(
                        select(UserProjectAccess.user_id).where(
                            UserProjectAccess.project_id == project_id
                        )
                    ),
                ),
            )
            .order_by(User.name.asc(), User.created_at.asc())
        )

        items: list[ManagerPerformanceOut] = []
        for row in result.mappings().all():
            chats_taken = int(row["chats_taken"] or 0)
            submitted_leads = int(row["submitted_leads"] or 0)
            valid_leads = int(row["valid_leads"] or 0)
            items.append(
                ManagerPerformanceOut(
                    manager_id=row["manager_id"],
                    name=row["name"],
                    email=row["email"],
                    handler_code=row["handler_code"],
                    chats_taken=chats_taken,
                    submitted_leads=submitted_leads,
                    valid_leads=valid_leads,
                    funnels_pushed=int(row["funnels_pushed"] or 0),
                    returned_to_funnel=int(row["returned_to_funnel"] or 0),
                    taken_to_submitted_percent=self._ratio(submitted_leads, chats_taken),
                    submitted_to_valid_percent=self._ratio(valid_leads, submitted_leads),
                    taken_to_valid_percent=self._ratio(valid_leads, chats_taken),
                )
            )
        return items

    @staticmethod
    def _date_bounds(
        *,
        date_from: date | None,
        date_to: date | None,
    ) -> tuple[datetime | None, datetime | None]:
        start_at = (
            datetime.combine(date_from, time.min, tzinfo=timezone.utc)
            if date_from is not None
            else None
        )
        end_at = (
            datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
            if date_to is not None
            else None
        )
        return start_at, end_at

    @staticmethod
    def _append_period(
        filters: list,
        column,
        start_at: datetime | None,
        end_at: datetime | None,
    ) -> None:
        if start_at is not None:
            filters.append(column >= start_at)
        if end_at is not None:
            filters.append(column < end_at)

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round((numerator / denominator) * 100, 1)
