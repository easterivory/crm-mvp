from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import String, and_, cast, case, distinct, func, or_, select, text, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import AuditAction, EntityType, RoleName
from app.models.audit_log import AuditLog
from app.models.funnel import ChatFunnelState, FunnelRuntimeLog, FunnelStep
from app.models.lead import Lead
from app.models.message import Message
from app.models.partner import LeadSubmission
from app.models.project import Project
from app.models.role import Role
from app.models.user import User, UserProjectAccess
from app.schemas.manager_analytics import ManagerPerformanceOut
from app.repositories.lifecycle_metrics_repository import LifecycleMetricsRepository


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
        if date_from is not None and date_to is not None and date_from > date_to:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="date_from must be before or equal to date_to",
            )
        start_at, end_at = self._date_bounds(date_from=date_from, date_to=date_to)

        taken_filters = [
            AuditLog.project_id == project_id,
            AuditLog.action == AuditAction.LEAD_MANAGER_ASSIGNED,
            AuditLog.entity_type == EntityType.LEAD,
            AuditLog.actor_id.is_not(None),
            AuditLog.meta["to_manager_id"].astext == cast(AuditLog.actor_id, String),
        ]
        self._append_period(taken_filters, AuditLog.created_at, start_at, end_at)
        taken_events = (
            select(
                AuditLog.actor_id.label("manager_id"),
                AuditLog.entity_id.label("lead_id"),
                AuditLog.created_at.label("assigned_at"),
            )
            .where(*taken_filters)
            .subquery()
        )
        taken_totals = (
            select(
                taken_events.c.manager_id,
                func.count(distinct(taken_events.c.lead_id)).label("chats_taken"),
            )
            .group_by(taken_events.c.manager_id)
            .subquery()
        )

        completion_events = union_all(
            select(
                Lead.id.label("lead_id"),
                FunnelRuntimeLog.created_at.label("completed_at"),
            )
            .join(FunnelRuntimeLog, FunnelRuntimeLog.chat_id == Lead.chat_id)
            .join(FunnelStep, FunnelStep.id == FunnelRuntimeLog.step_id)
            .where(
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
                FunnelRuntimeLog.status == "success",
                FunnelStep.step_type == "finish",
            ),
            select(
                Lead.id.label("lead_id"),
                ChatFunnelState.completed_at.label("completed_at"),
            )
            .join(ChatFunnelState, ChatFunnelState.chat_id == Lead.chat_id)
            .where(
                Lead.project_id == project_id,
                Lead.is_deleted.is_(False),
                ChatFunnelState.completed_at.is_not(None),
            ),
        ).subquery()

        expired_filters = [
            AuditLog.project_id == project_id,
            AuditLog.action == AuditAction.LEAD_MANAGER_REMOVED,
            AuditLog.entity_type == EntityType.LEAD,
            AuditLog.meta["reason"].astext == "chat_lease_expired",
            AuditLog.meta["from_manager_id"].astext.is_not(None),
        ]
        self._append_period(expired_filters, AuditLog.created_at, start_at, end_at)
        expired_events = (
            select(
                AuditLog.meta["from_manager_id"].astext.label("manager_id"),
                AuditLog.entity_id.label("lead_id"),
                AuditLog.created_at.label("expired_at"),
            )
            .where(*expired_filters)
            .subquery()
        )
        # A later cleanup expiry is not a lost chat once the client engaged or
        # completed the funnel during that manager's assignment.
        latest_assignment_at = (
            select(func.max(AuditLog.created_at))
            .where(
                AuditLog.project_id == project_id,
                AuditLog.action == AuditAction.LEAD_MANAGER_ASSIGNED,
                AuditLog.entity_type == EntityType.LEAD,
                AuditLog.entity_id == expired_events.c.lead_id,
                AuditLog.meta["to_manager_id"].astext == expired_events.c.manager_id,
                AuditLog.created_at <= expired_events.c.expired_at,
            )
            .correlate(expired_events)
            .scalar_subquery()
        )
        client_replied_before_expiry = (
            select(Message.id)
            .join(Lead, Lead.chat_id == Message.chat_id)
            .where(
                Lead.id == expired_events.c.lead_id,
                Message.sender_type == "user",
                Message.created_at >= latest_assignment_at,
                Message.created_at <= expired_events.c.expired_at,
            )
            .correlate(expired_events)
            .exists()
        )
        funnel_completed_before_expiry = (
            select(completion_events.c.lead_id)
            .where(
                completion_events.c.lead_id == expired_events.c.lead_id,
                completion_events.c.completed_at >= latest_assignment_at,
                completion_events.c.completed_at <= expired_events.c.expired_at,
            )
            .correlate(expired_events)
            .exists()
        )
        dropped_events = (
            select(
                expired_events.c.manager_id,
                expired_events.c.lead_id,
            )
            .where(
                latest_assignment_at.is_not(None),
                ~client_replied_before_expiry,
                ~funnel_completed_before_expiry,
            )
            .subquery()
        )
        expired_totals = (
            select(
                dropped_events.c.manager_id,
                func.count(distinct(dropped_events.c.lead_id)).label("chats_expired"),
            )
            .group_by(dropped_events.c.manager_id)
            .subquery()
        )

        retained_totals = (
            select(
                taken_events.c.manager_id,
                func.count(distinct(taken_events.c.lead_id)).label("chats_retained"),
            )
            .join(Lead, Lead.id == taken_events.c.lead_id)
            .join(Project, Project.id == Lead.project_id)
            .join(
                Message,
                and_(
                    Message.chat_id == Lead.chat_id,
                    Message.sender_type == "user",
                    Message.created_at >= taken_events.c.assigned_at,
                    or_(
                        Project.chat_lease_minutes <= 0,
                        Message.created_at
                        <= taken_events.c.assigned_at
                        + Project.chat_lease_minutes * text("INTERVAL '1 minute'"),
                    ),
                ),
            )
            .group_by(taken_events.c.manager_id)
            .subquery()
        )

        first_response_events = (
            select(
                taken_events.c.manager_id,
                taken_events.c.lead_id,
                func.min(
                    func.extract(
                        "epoch",
                        Message.created_at - taken_events.c.assigned_at,
                    )
                ).label("response_seconds"),
            )
            .join(Lead, Lead.id == taken_events.c.lead_id)
            .join(
                Message,
                and_(
                    Message.chat_id == Lead.chat_id,
                    Message.sender_type == "manager",
                    Message.created_at >= taken_events.c.assigned_at,
                    or_(
                        Message.operator_id == taken_events.c.manager_id,
                        Message.sender_id == taken_events.c.manager_id,
                    ),
                ),
            )
            .group_by(taken_events.c.manager_id, taken_events.c.lead_id)
            .subquery()
        )
        response_totals = (
            select(
                first_response_events.c.manager_id,
                func.count().label("answered_chats"),
                func.avg(first_response_events.c.response_seconds).label(
                    "average_first_response_seconds"
                ),
            )
            .group_by(first_response_events.c.manager_id)
            .subquery()
        )

        submission_filters = [
            Lead.project_id == project_id,
            Lead.is_deleted.is_(False),
            LeadSubmission.submitted_by_user_id.is_not(None),
            func.lower(LeadSubmission.status).in_(("success", "completed")),
        ]
        self._append_period(
            submission_filters,
            func.coalesce(LeadSubmission.completed_at, LeadSubmission.submitted_at),
            start_at,
            end_at,
        )
        submission_totals = (
            select(
                LeadSubmission.submitted_by_user_id.label("manager_id"),
                func.count(distinct(LeadSubmission.lead_id)).label("submitted_leads"),
                func.count(
                    distinct(
                        case(
                            (
                                or_(
                                    LeadSubmission.submitted_manually.is_(True),
                                    LeadSubmission.submission_source.in_(("manual", "vip")),
                                ),
                                LeadSubmission.lead_id,
                            ),
                            else_=None,
                        )
                    )
                ).label("manual_submissions"),
                func.count(
                    distinct(
                        case(
                            (LeadSubmission.submission_source == "auto", LeadSubmission.lead_id),
                            else_=None,
                        )
                    )
                ).label("auto_submissions"),
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

        lifecycle_events = LifecycleMetricsRepository._eligible_events(project_id)
        event_filters = [lifecycle_events.c.attributed_manager_id.is_not(None)]
        self._append_period(
            event_filters,
            lifecycle_events.c.occurred_at,
            start_at,
            end_at,
        )
        lifecycle_event_totals = (
            select(
                lifecycle_events.c.attributed_manager_id.label("manager_id"),
                func.count(
                    case(
                        (lifecycle_events.c.event_type == "registration", 1),
                        else_=None,
                    )
                ).label("registrations"),
                func.count(
                    case(
                        (lifecycle_events.c.event_type == "deposit", 1),
                        else_=None,
                    )
                ).label("deposits"),
                func.count(
                    case(
                        (lifecycle_events.c.event_type == "redeposit", 1),
                        else_=None,
                    )
                ).label("redeposits"),
            )
            .select_from(lifecycle_events)
            .where(
                *event_filters,
            )
            .group_by(lifecycle_events.c.attributed_manager_id)
            .subquery()
        )

        assigned_to_manager = (
            select(
                AuditLog.meta["to_manager_id"].astext.label("manager_id"),
                AuditLog.entity_id.label("lead_id"),
                AuditLog.created_at.label("assigned_at"),
            )
            .where(
                AuditLog.project_id == project_id,
                AuditLog.action == AuditAction.LEAD_MANAGER_ASSIGNED,
                AuditLog.entity_type == EntityType.LEAD,
                AuditLog.meta["to_manager_id"].astext.is_not(None),
            )
            .subquery()
        )

        pushed_filters = [
            Lead.project_id == project_id,
            Lead.is_deleted.is_(False),
            completion_events.c.completed_at >= assigned_to_manager.c.assigned_at,
        ]
        later_assignment_before_completion = (
            select(AuditLog.id)
            .where(
                AuditLog.project_id == project_id,
                AuditLog.action == AuditAction.LEAD_MANAGER_ASSIGNED,
                AuditLog.entity_type == EntityType.LEAD,
                AuditLog.entity_id == assigned_to_manager.c.lead_id,
                AuditLog.meta["to_manager_id"].astext.is_not(None),
                AuditLog.created_at > assigned_to_manager.c.assigned_at,
                AuditLog.created_at <= completion_events.c.completed_at,
            )
            .correlate(assigned_to_manager, completion_events)
            .exists()
        )
        pushed_filters.append(~later_assignment_before_completion)
        self._append_period(
            pushed_filters,
            completion_events.c.completed_at,
            start_at,
            end_at,
        )
        funnels_pushed_totals = (
            select(
                assigned_to_manager.c.manager_id,
                func.count(distinct(assigned_to_manager.c.lead_id)).label("funnels_pushed"),
            )
            .join(Lead, Lead.id == assigned_to_manager.c.lead_id)
            .join(
                completion_events,
                and_(
                    completion_events.c.lead_id == assigned_to_manager.c.lead_id,
                    completion_events.c.completed_at >= assigned_to_manager.c.assigned_at,
                ),
            )
            .where(*pushed_filters)
            .group_by(assigned_to_manager.c.manager_id)
            .subquery()
        )

        result = await self.db.execute(
            select(
                User.id.label("manager_id"),
                User.name,
                User.email,
                User.handler_code,
                func.coalesce(taken_totals.c.chats_taken, 0).label("chats_taken"),
                func.coalesce(retained_totals.c.chats_retained, 0).label("chats_retained"),
                func.coalesce(expired_totals.c.chats_expired, 0).label("chats_expired"),
                func.coalesce(response_totals.c.answered_chats, 0).label("answered_chats"),
                func.coalesce(response_totals.c.average_first_response_seconds, 0).label(
                    "average_first_response_seconds"
                ),
                func.coalesce(submission_totals.c.submitted_leads, 0).label("submitted_leads"),
                func.coalesce(submission_totals.c.manual_submissions, 0).label(
                    "manual_submissions"
                ),
                func.coalesce(submission_totals.c.auto_submissions, 0).label(
                    "auto_submissions"
                ),
                func.coalesce(submission_totals.c.valid_leads, 0).label("valid_leads"),
                func.coalesce(funnels_pushed_totals.c.funnels_pushed, 0).label("funnels_pushed"),
                func.coalesce(resumed_totals.c.returned_to_funnel, 0).label("returned_to_funnel"),
                func.coalesce(lifecycle_event_totals.c.registrations, 0).label("registrations"),
                func.coalesce(lifecycle_event_totals.c.deposits, 0).label("deposits"),
                func.coalesce(lifecycle_event_totals.c.redeposits, 0).label("redeposits"),
            )
            .join(Role, Role.id == User.role_id)
            .outerjoin(taken_totals, taken_totals.c.manager_id == User.id)
            .outerjoin(retained_totals, retained_totals.c.manager_id == User.id)
            .outerjoin(
                expired_totals,
                expired_totals.c.manager_id == cast(User.id, String),
            )
            .outerjoin(response_totals, response_totals.c.manager_id == User.id)
            .outerjoin(submission_totals, submission_totals.c.manager_id == User.id)
            .outerjoin(resumed_totals, resumed_totals.c.manager_id == User.id)
            .outerjoin(funnels_pushed_totals, funnels_pushed_totals.c.manager_id == cast(User.id, String))
            .outerjoin(
                lifecycle_event_totals,
                lifecycle_event_totals.c.manager_id == User.id,
            )
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
            answered_chats = int(row["answered_chats"] or 0)
            submitted_leads = int(row["submitted_leads"] or 0)
            valid_leads = int(row["valid_leads"] or 0)
            items.append(
                ManagerPerformanceOut(
                    manager_id=row["manager_id"],
                    name=row["name"],
                    email=row["email"],
                    handler_code=row["handler_code"],
                    chats_taken=chats_taken,
                    chats_retained=int(row["chats_retained"] or 0),
                    chats_expired=int(row["chats_expired"] or 0),
                    answered_chats=answered_chats,
                    unanswered_chats=max(chats_taken - answered_chats, 0),
                    average_first_response_seconds=round(
                        float(row["average_first_response_seconds"] or 0),
                        1,
                    ),
                    submitted_leads=submitted_leads,
                    submissions_total=submitted_leads,
                    manual_submissions=int(row["manual_submissions"] or 0),
                    auto_submissions=int(row["auto_submissions"] or 0),
                    valid_leads=valid_leads,
                    funnels_pushed=int(row["funnels_pushed"] or 0),
                    returned_to_funnel=int(row["returned_to_funnel"] or 0),
                    registrations=int(row["registrations"] or 0),
                    deposits=int(row["deposits"] or 0),
                    redeposits=int(row["redeposits"] or 0),
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
