from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, String, and_, cast, false, func, not_, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Chat
from app.models.funnel import ChatFunnelState
from app.models.lead import Lead, LeadTag
from app.models.lead_status import LeadStatus
from app.models.tracking import TrackingLink
from app.repositories.chat_repository import ChatRepository
from app.schemas.broadcast import (
    AudienceFilter,
    AudiencePreviewResponse,
    AudiencePreviewSample,
    AudienceRule,
    AudienceRuleGroup,
)


class AudienceFilterService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def preview(
        self,
        *,
        project_id: UUID,
        bot_id: Optional[UUID],
        audience_filter: AudienceFilter | dict[str, Any],
        sample_limit: int = 20,
    ) -> AudiencePreviewResponse:
        parsed = self._parse_filter(audience_filter)
        stmt = self._audience_stmt(
            project_id=project_id,
            bot_id=bot_id,
            audience_filter=parsed,
        )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        count = (await self.db.execute(count_stmt)).scalar_one()
        audience_subquery = stmt.subquery()
        in_funnel_count = (
            await self.db.execute(
                select(func.count())
                .select_from(audience_subquery)
                .where(
                    select(ChatFunnelState.id)
                    .where(
                        ChatFunnelState.chat_id == audience_subquery.c.chat_id,
                        ChatFunnelState.completed_at.is_(None),
                    )
                    .exists()
                )
            )
        ).scalar_one()

        sample_stmt = stmt.limit(sample_limit)
        rows = (await self.db.execute(sample_stmt)).all()
        return AudiencePreviewResponse(
            count=count,
            in_funnel_count=in_funnel_count,
            sample=[
                AudiencePreviewSample(
                    chat_id=row.chat_id,
                    lead_id=row.lead_id,
                    lead_name=row.lead_name,
                    username=row.username,
                    status=row.status,
                )
                for row in rows
            ],
        )

    async def resolve_recipients(
        self,
        *,
        project_id: UUID,
        bot_id: UUID,
        audience_filter: AudienceFilter | dict[str, Any],
    ) -> list[tuple[UUID, UUID | None]]:
        parsed = self._parse_filter(audience_filter)
        stmt = self._audience_stmt(
            project_id=project_id,
            bot_id=bot_id,
            audience_filter=parsed,
        )
        rows = (await self.db.execute(stmt)).all()
        return [(row.chat_id, row.lead_id) for row in rows]

    def _parse_filter(self, value: AudienceFilter | dict[str, Any]) -> AudienceFilter:
        if isinstance(value, AudienceFilter):
            return value
        try:
            return AudienceFilter.model_validate(value or {})
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid audience filter: {exc}",
            ) from exc

    def _audience_stmt(
        self,
        *,
        project_id: UUID,
        bot_id: Optional[UUID],
        audience_filter: AudienceFilter,
    ):
        stmt = (
            select(
                Chat.id.label("chat_id"),
                Lead.id.label("lead_id"),
                Lead.name.label("lead_name"),
                Lead.username.label("username"),
                LeadStatus.code.label("status"),
            )
            .select_from(Chat)
            .outerjoin(Lead, (Lead.chat_id == Chat.id) & (Lead.is_deleted.is_(False)))
            .outerjoin(LeadStatus, LeadStatus.id == Lead.status_id)
            .where(
                Chat.project_id == project_id,
                Chat.is_deleted.is_(False),
                Chat.reset_at.is_(None),
                Chat.external_chat_id.is_not(None),
                Chat.external_chat_id != "",
            )
            .distinct(Chat.id)
            .order_by(Chat.id)
        )
        if bot_id is not None:
            stmt = stmt.where(Chat.bot_id == bot_id)

        include_expr = self._group_expr(audience_filter.include, default=true())
        exclude_expr = self._group_expr(audience_filter.exclude, default=false())
        return stmt.where(include_expr, not_(exclude_expr))

    def _group_expr(self, group: AudienceRuleGroup, default: ColumnElement) -> ColumnElement:
        if not group.rules:
            return default
        expressions = [self._rule_expr(rule) for rule in group.rules]
        return or_(*expressions) if group.mode == "any" else and_(*expressions)

    def _rule_expr(self, rule: AudienceRule) -> ColumnElement:
        field = rule.field
        operator = rule.operator
        raw_value = rule.value

        if field == "tag":
            values = self._uuid_values(raw_value, "tag")
            exists_expr = (
                select(LeadTag.lead_id)
                .where(LeadTag.lead_id == Lead.id, LeadTag.tag_id.in_(values))
                .exists()
            )
            return self._apply_set_operator(exists_expr, operator)

        if field == "lead_status":
            return self._apply_operator(LeadStatus.code, operator, raw_value)

        if field == "funnel_state":
            return self._apply_funnel_state_operator(operator, raw_value)

        if field == "funnel_id":
            return self._apply_funnel_uuid_operator("funnel_id", operator, raw_value)

        if field == "funnel_version_id":
            return self._apply_funnel_uuid_operator("funnel_version_id", operator, raw_value)

        if field == "current_step_id":
            return self._apply_funnel_uuid_operator("current_step_id", operator, raw_value, active_only=True)

        if field == "completed_funnel_id":
            return self._apply_funnel_uuid_operator(
                "funnel_id",
                operator,
                raw_value,
                completed_only=True,
            )

        if field == "completed_since":
            completed_at = (
                select(ChatFunnelState.id)
                .where(
                    ChatFunnelState.chat_id == Chat.id,
                    ChatFunnelState.completed_at.is_not(None),
                    ChatFunnelState.completed_at >= self._typed_value(raw_value, "datetime"),
                )
                .exists()
            )
            return completed_at if operator not in {"not_equals", "not_in", "empty"} else not_(completed_at)

        if field == "not_in_funnel":
            expr = self._funnel_state_expr("not_in_funnel")
            expected = self._bool_value(raw_value)
            return expr if expected else not_(expr)

        if field == "tracking_link":
            return self._apply_operator(Chat.tracking_link_id, operator, raw_value, value_type="uuid")

        if field == "assigned_user":
            return self._apply_operator(Lead.manager_id, operator, raw_value, value_type="uuid")

        if field == "last_message_at":
            return self._apply_operator(Chat.last_message_at, operator, raw_value, value_type="datetime")

        if field == "created_at":
            created_at = func.coalesce(Chat.current_cycle_started_at, Chat.created_at)
            return self._apply_operator(created_at, operator, raw_value, value_type="datetime")

        if field == "has_unanswered_incoming":
            expr = ChatRepository.unanswered_expr()
            expected = self._bool_value(raw_value)
            return expr if expected else not_(expr)

        if field == "bot_id":
            return self._apply_operator(Chat.bot_id, operator, raw_value, value_type="uuid")

        if field == "custom_field":
            key = rule.custom_field
            if not key and isinstance(raw_value, dict):
                key = raw_value.get("field")
                raw_value = raw_value.get("value")
            if not key:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="custom_field rule requires custom_field",
                )
            return self._apply_operator(
                Lead.custom_fields[key].astext,
                operator,
                raw_value,
            )

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported audience field: {field}",
        )

    def _apply_funnel_state_operator(self, operator: str, raw_value: Any) -> ColumnElement:
        values = self._string_values(raw_value)
        expressions = [self._funnel_state_expr(value) for value in values]
        expr = or_(*expressions) if expressions else false()
        if operator in {"not_equals", "not_in"}:
            return not_(expr)
        if operator in {"equals", "in"}:
            return expr
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported operator for funnel_state: {operator}",
        )

    def _apply_funnel_uuid_operator(
        self,
        column_name: str,
        operator: str,
        raw_value: Any,
        *,
        active_only: bool = False,
        completed_only: bool = False,
    ) -> ColumnElement:
        values = self._uuid_values(raw_value, column_name)
        column = getattr(ChatFunnelState, column_name)
        exists_expr = (
            select(ChatFunnelState.id)
            .where(
                ChatFunnelState.chat_id == Chat.id,
                column.in_(values) if values else false(),
            )
        )
        if active_only:
            exists_expr = exists_expr.where(ChatFunnelState.completed_at.is_(None))
        if completed_only:
            exists_expr = exists_expr.where(ChatFunnelState.completed_at.is_not(None))
        expr = exists_expr.exists()
        if operator in {"not_equals", "not_in", "empty"}:
            return not_(expr)
        if operator in {"equals", "in", "exists"}:
            return expr
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported operator for {column_name}: {operator}",
        )

    @staticmethod
    def _funnel_state_expr(funnel_state: str) -> ColumnElement:
        state_exists = (
            select(ChatFunnelState.id)
            .where(
                ChatFunnelState.chat_id == Chat.id,
                ChatFunnelState.completed_at.is_(None),
            )
            .exists()
        )
        waiting_exists = (
            select(ChatFunnelState.id)
            .where(
                ChatFunnelState.chat_id == Chat.id,
                ChatFunnelState.completed_at.is_(None),
                ChatFunnelState.waiting_for_answer.is_(True),
            )
            .exists()
        )
        completed_exists = (
            select(ChatFunnelState.id)
            .where(
                ChatFunnelState.chat_id == Chat.id,
                ChatFunnelState.completed_at.is_not(None),
            )
            .exists()
        )
        manual_after_completed = (
            select(ChatFunnelState.id)
            .where(
                ChatFunnelState.chat_id == Chat.id,
                ChatFunnelState.completed_at.is_not(None),
                Chat.last_user_message_at.is_not(None),
                Chat.last_user_message_at > ChatFunnelState.completed_at,
            )
            .exists()
        )
        if funnel_state == "waiting_for_answer":
            return waiting_exists
        if funnel_state == "in_funnel":
            return state_exists
        if funnel_state == "completed":
            return completed_exists
        if funnel_state == "not_started":
            any_state_exists = (
                select(ChatFunnelState.id)
                .where(ChatFunnelState.chat_id == Chat.id)
                .exists()
            )
            return ~any_state_exists
        if funnel_state in {"not_in_funnel", "not_in_active_funnel"}:
            return ~state_exists
        if funnel_state == "manual":
            return (~state_exists & ~completed_exists) | manual_after_completed
        return false()

    def _apply_set_operator(self, expr: ColumnElement, operator: str) -> ColumnElement:
        if operator in {"equals", "in", "exists"}:
            return expr
        if operator in {"not_equals", "not_in", "empty"}:
            return not_(expr)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported set operator: {operator}",
        )

    def _apply_operator(
        self,
        column: ColumnElement,
        operator: str,
        raw_value: Any,
        *,
        value_type: str = "string",
    ) -> ColumnElement:
        if operator == "exists":
            return column.is_not(None)
        if operator == "empty":
            return column.is_(None) | (cast(column, String) == "")

        if operator in {"in", "not_in"}:
            values = self._typed_values(raw_value, value_type)
            expr = column.in_(values) if values else false()
            return not_(expr) if operator == "not_in" else expr

        if operator in {"equals", "not_equals"}:
            value = self._typed_value(raw_value, value_type)
            expr = column == value
            return column != value if operator == "not_equals" else expr

        if operator == "before":
            return column < self._typed_value(raw_value, "datetime")
        if operator == "after":
            return column > self._typed_value(raw_value, "datetime")
        if operator == "between":
            values = self._typed_values(raw_value, "datetime")
            if len(values) != 2:
                raise HTTPException(status_code=422, detail="between requires two values")
            return column.between(values[0], values[1])
        if operator == "contains":
            return func.lower(cast(column, String)).like(f"%{str(raw_value).lower()}%")
        if operator == "gt":
            return column > self._typed_value(raw_value, value_type)
        if operator == "lt":
            return column < self._typed_value(raw_value, value_type)

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported audience operator: {operator}",
        )

    def _typed_values(self, raw_value: Any, value_type: str) -> list[Any]:
        return [self._typed_value(item, value_type) for item in self._list(raw_value)]

    def _typed_value(self, raw_value: Any, value_type: str) -> Any:
        if value_type == "uuid":
            try:
                return UUID(str(raw_value))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="Expected UUID value") from exc
        if value_type == "datetime":
            if isinstance(raw_value, datetime):
                return raw_value
            try:
                return datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="Expected ISO datetime value") from exc
        return str(raw_value)

    def _uuid_values(self, raw_value: Any, field_name: str) -> list[UUID]:
        values = []
        for item in self._list(raw_value):
            try:
                values.append(UUID(str(item)))
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"{field_name} values must be UUIDs",
                ) from exc
        return values

    def _string_values(self, raw_value: Any) -> list[str]:
        return [str(item) for item in self._list(raw_value) if str(item)]

    @staticmethod
    def _list(raw_value: Any) -> list[Any]:
        if raw_value is None:
            return []
        if isinstance(raw_value, list):
            return raw_value
        return [raw_value]

    @staticmethod
    def _bool_value(raw_value: Any) -> bool:
        if isinstance(raw_value, bool):
            return raw_value
        return str(raw_value).lower() in {"1", "true", "yes", "да"}
