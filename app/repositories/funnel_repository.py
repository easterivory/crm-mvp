from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import delete, func, select, update

from app.models.bot import Bot
from app.models.chat import Chat
from app.models.funnel import (
    ChatFunnelState,
    Funnel,
    FunnelEdge,
    FunnelFieldMapping,
    FunnelPushRule,
    FunnelStep,
    FunnelVersion,
)
from app.models.lead import Lead
from app.repositories.base import BaseRepository
from app.schemas.funnel import (
    FunnelEdgeIn,
    FunnelFieldMappingIn,
    FunnelGraphIn,
    FunnelPushRuleIn,
    FunnelStepIn,
)


class FunnelRepository(BaseRepository[Funnel]):
    model = Funnel

    async def list_by_project(
        self,
        project_id: UUID,
        *,
        bot_id: Optional[UUID] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Funnel]:
        stmt = select(Funnel).where(Funnel.project_id == project_id)
        if bot_id is not None:
            stmt = stmt.where(Funnel.bot_id == bot_id)
        if status is not None:
            stmt = stmt.where(Funnel.status == status)
        stmt = stmt.order_by(Funnel.updated_at.desc()).limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_by_project(
        self,
        project_id: UUID,
        *,
        bot_id: Optional[UUID] = None,
        status: Optional[str] = None,
    ) -> int:
        stmt = select(func.count(Funnel.id)).where(Funnel.project_id == project_id)
        if bot_id is not None:
            stmt = stmt.where(Funnel.bot_id == bot_id)
        if status is not None:
            stmt = stmt.where(Funnel.status == status)
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def get_in_project(self, funnel_id: UUID, project_id: UUID) -> Optional[Funnel]:
        result = await self.db.execute(
            select(Funnel).where(Funnel.id == funnel_id, Funnel.project_id == project_id)
        )
        return result.scalar_one_or_none()

    async def update_in_project(
        self,
        funnel_id: UUID,
        project_id: UUID,
        **values,
    ) -> Optional[Funnel]:
        values["updated_at"] = func.now()
        result = await self.db.execute(
            update(Funnel)
            .where(Funnel.id == funnel_id, Funnel.project_id == project_id)
            .values(**values)
        )
        if result.rowcount == 0:
            return None
        return await self.get_in_project(funnel_id, project_id)

    async def bot_belongs_to_project(self, bot_id: UUID, project_id: UUID) -> bool:
        result = await self.db.execute(
            select(Bot.id)
            .where(Bot.id == bot_id, Bot.project_id == project_id, Bot.is_deleted.is_(False))
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def list_versions(self, funnel_id: UUID) -> list[FunnelVersion]:
        result = await self.db.execute(
            select(FunnelVersion)
            .where(FunnelVersion.funnel_id == funnel_id)
            .order_by(FunnelVersion.version_number.desc())
        )
        return list(result.scalars().all())

    async def get_version(self, version_id: UUID) -> Optional[FunnelVersion]:
        result = await self.db.execute(
            select(FunnelVersion).where(FunnelVersion.id == version_id)
        )
        return result.scalar_one_or_none()

    async def get_version_in_project(
        self,
        funnel_id: UUID,
        version_id: UUID,
        project_id: UUID,
    ) -> Optional[FunnelVersion]:
        result = await self.db.execute(
            select(FunnelVersion)
            .join(Funnel, Funnel.id == FunnelVersion.funnel_id)
            .where(
                FunnelVersion.id == version_id,
                FunnelVersion.funnel_id == funnel_id,
                Funnel.project_id == project_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_latest_draft(self, funnel_id: UUID) -> Optional[FunnelVersion]:
        result = await self.db.execute(
            select(FunnelVersion)
            .where(FunnelVersion.funnel_id == funnel_id, FunnelVersion.status == "draft")
            .order_by(FunnelVersion.version_number.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_published(self, funnel_id: UUID) -> Optional[FunnelVersion]:
        result = await self.db.execute(
            select(FunnelVersion).where(
                FunnelVersion.funnel_id == funnel_id,
                FunnelVersion.status == "published",
            )
        )
        return result.scalar_one_or_none()

    async def get_published_for_bot(self, bot_id: UUID) -> Optional[FunnelVersion]:
        result = await self.db.execute(
            select(FunnelVersion)
            .join(Funnel, Funnel.id == FunnelVersion.funnel_id)
            .join(Bot, Bot.id == Funnel.bot_id)
            .where(
                Funnel.bot_id == bot_id,
                Funnel.status == "active",
                FunnelVersion.status == "published",
                Bot.active_funnel_version_id == FunnelVersion.id,
            )
            .order_by(FunnelVersion.published_at.desc().nullslast())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_active_funnel_for_bot(
        self,
        bot_id: UUID,
        project_id: UUID,
    ) -> tuple[Optional[Funnel], Optional[FunnelVersion]]:
        result = await self.db.execute(
            select(Funnel, FunnelVersion)
            .select_from(Bot)
            .outerjoin(Funnel, Funnel.id == Bot.active_funnel_id)
            .outerjoin(FunnelVersion, FunnelVersion.id == Bot.active_funnel_version_id)
            .where(
                Bot.id == bot_id,
                Bot.project_id == project_id,
                Bot.is_deleted.is_(False),
            )
        )
        row = result.first()
        if row is None:
            return None, None
        return row[0], row[1]

    async def set_active_funnel_for_bot(
        self,
        *,
        bot_id: UUID,
        project_id: UUID,
        funnel_id: UUID,
        version_id: UUID,
    ) -> Optional[Bot]:
        result = await self.db.execute(
            update(Bot)
            .where(
                Bot.id == bot_id,
                Bot.project_id == project_id,
                Bot.is_deleted.is_(False),
            )
            .values(
                active_funnel_id=funnel_id,
                active_funnel_version_id=version_id,
                updated_at=func.now(),
            )
        )
        if result.rowcount == 0:
            return None
        bot_result = await self.db.execute(select(Bot).where(Bot.id == bot_id))
        return bot_result.scalar_one_or_none()

    async def clear_active_funnel_for_bot(
        self,
        *,
        bot_id: UUID,
        funnel_id: UUID,
    ) -> None:
        await self.db.execute(
            update(Bot)
            .where(Bot.id == bot_id, Bot.active_funnel_id == funnel_id)
            .values(
                active_funnel_id=None,
                active_funnel_version_id=None,
                updated_at=func.now(),
            )
        )

    async def archive_published_versions_for_bot(
        self,
        *,
        bot_id: UUID,
        exclude_version_id: Optional[UUID] = None,
    ) -> None:
        stmt = (
            update(FunnelVersion)
            .where(
                FunnelVersion.funnel_id == Funnel.id,
                Funnel.bot_id == bot_id,
                FunnelVersion.status == "published",
            )
        )
        if exclude_version_id is not None:
            stmt = stmt.where(FunnelVersion.id != exclude_version_id)
        await self.db.execute(stmt.values(status="archived", updated_at=func.now()))

    async def reset_chat_funnel_state(self, chat_id: UUID) -> None:
        await self.db.execute(
            update(ChatFunnelState)
            .where(ChatFunnelState.chat_id == chat_id)
            .values(completed_at=func.now(), updated_at=func.now())
        )

    async def next_version_number(self, funnel_id: UUID) -> int:
        result = await self.db.execute(
            select(func.coalesce(func.max(FunnelVersion.version_number), 0) + 1).where(
                FunnelVersion.funnel_id == funnel_id
            )
        )
        return result.scalar_one()

    async def create_version(
        self,
        *,
        funnel_id: UUID,
        version_number: int,
        created_by_user_id: Optional[UUID],
        status: str = "draft",
    ) -> FunnelVersion:
        version = FunnelVersion(
            funnel_id=funnel_id,
            version_number=version_number,
            status=status,
            created_by_user_id=created_by_user_id,
        )
        self.db.add(version)
        await self.db.flush()
        await self.db.refresh(version)
        return version

    async def update_version_status(
        self,
        version_id: UUID,
        status: str,
        *,
        published_at: Optional[datetime] = None,
    ) -> Optional[FunnelVersion]:
        values = {"status": status, "updated_at": func.now()}
        values["published_at"] = published_at
        result = await self.db.execute(
            update(FunnelVersion).where(FunnelVersion.id == version_id).values(**values)
        )
        if result.rowcount == 0:
            return None
        return await self.get_version(version_id)

    async def archive_published_versions(
        self,
        *,
        funnel_id: UUID,
        exclude_version_id: Optional[UUID] = None,
    ) -> None:
        stmt = update(FunnelVersion).where(
            FunnelVersion.funnel_id == funnel_id,
            FunnelVersion.status == "published",
        )
        if exclude_version_id is not None:
            stmt = stmt.where(FunnelVersion.id != exclude_version_id)
        await self.db.execute(
            stmt.values(status="archived", updated_at=func.now())
        )

    async def list_steps(self, version_id: UUID) -> list[FunnelStep]:
        result = await self.db.execute(
            select(FunnelStep)
            .where(FunnelStep.funnel_version_id == version_id)
            .order_by(FunnelStep.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_edges(self, version_id: UUID) -> list[FunnelEdge]:
        result = await self.db.execute(
            select(FunnelEdge)
            .where(FunnelEdge.funnel_version_id == version_id)
            .order_by(FunnelEdge.priority.asc(), FunnelEdge.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_push_rules(self, version_id: UUID) -> list[FunnelPushRule]:
        result = await self.db.execute(
            select(FunnelPushRule)
            .where(FunnelPushRule.funnel_version_id == version_id)
            .order_by(FunnelPushRule.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_field_mappings(self, version_id: UUID) -> list[FunnelFieldMapping]:
        result = await self.db.execute(
            select(FunnelFieldMapping)
            .where(FunnelFieldMapping.funnel_version_id == version_id)
            .order_by(FunnelFieldMapping.created_at.asc())
        )
        return list(result.scalars().all())

    async def replace_graph(self, version_id: UUID, graph: FunnelGraphIn) -> None:
        await self.db.execute(
            delete(FunnelFieldMapping).where(FunnelFieldMapping.funnel_version_id == version_id)
        )
        await self.db.execute(
            delete(FunnelPushRule).where(FunnelPushRule.funnel_version_id == version_id)
        )
        await self.db.execute(
            delete(FunnelEdge).where(FunnelEdge.funnel_version_id == version_id)
        )
        await self.db.execute(
            delete(FunnelStep).where(FunnelStep.funnel_version_id == version_id)
        )
        await self.db.flush()

        for step_in in graph.steps:
            self.db.add(self._step_from_in(version_id, step_in))
        await self.db.flush()

        for edge_in in graph.edges:
            self.db.add(self._edge_from_in(version_id, edge_in))
        for rule_in in graph.push_rules:
            self.db.add(self._push_rule_from_in(version_id, rule_in))
        for mapping_in in graph.field_mappings:
            self.db.add(self._field_mapping_from_in(version_id, mapping_in))
        await self.db.flush()

    async def clone_graph(self, source_version_id: UUID, target_version_id: UUID) -> None:
        steps = await self.list_steps(source_version_id)
        edges = await self.list_edges(source_version_id)
        push_rules = await self.list_push_rules(source_version_id)
        field_mappings = await self.list_field_mappings(source_version_id)

        id_map: dict[UUID, UUID] = {}
        for step in steps:
            cloned = FunnelStep(
                funnel_version_id=target_version_id,
                key=step.key,
                title=step.title,
                step_type=step.step_type,
                block_type=step.block_type,
                position_x=step.position_x,
                position_y=step.position_y,
                config_json=dict(step.config_json or {}),
                validation_json=dict(step.validation_json) if step.validation_json else None,
                ui_schema_json=dict(step.ui_schema_json) if step.ui_schema_json else None,
            )
            self.db.add(cloned)
            await self.db.flush()
            id_map[step.id] = cloned.id

        for edge in edges:
            if edge.from_step_id not in id_map or edge.to_step_id not in id_map:
                continue
            self.db.add(
                FunnelEdge(
                    funnel_version_id=target_version_id,
                    from_step_id=id_map[edge.from_step_id],
                    to_step_id=id_map[edge.to_step_id],
                    condition_json=dict(edge.condition_json) if edge.condition_json else None,
                    priority=edge.priority,
                )
            )

        for rule in push_rules:
            if rule.step_id not in id_map:
                continue
            self.db.add(
                FunnelPushRule(
                    funnel_version_id=target_version_id,
                    step_id=id_map[rule.step_id],
                    delay_minutes=rule.delay_minutes,
                    message_text=rule.message_text,
                    action_after_send=rule.action_after_send,
                    target_step_id=(
                        id_map.get(rule.target_step_id) if rule.target_step_id else None
                    ),
                    is_active=rule.is_active,
                )
            )

        for mapping in field_mappings:
            if mapping.step_id not in id_map:
                continue
            self.db.add(
                FunnelFieldMapping(
                    funnel_version_id=target_version_id,
                    step_id=id_map[mapping.step_id],
                    source=mapping.source,
                    lead_field_key=mapping.lead_field_key,
                    transform_rule_json=(
                        dict(mapping.transform_rule_json)
                        if mapping.transform_rule_json
                        else None
                    ),
                    is_required=mapping.is_required,
                )
            )
        await self.db.flush()

    async def upsert_chat_funnel_state(
        self,
        *,
        chat_id: UUID,
        funnel_id: UUID,
        funnel_version_id: UUID,
        current_step_id: UUID,
        entered_step_at: datetime,
        completed_at: Optional[datetime] = None,
    ) -> ChatFunnelState:
        existing = await self.get_chat_funnel_state(chat_id)
        if existing is None:
            state = ChatFunnelState(
                chat_id=chat_id,
                funnel_id=funnel_id,
                funnel_version_id=funnel_version_id,
                current_step_id=current_step_id,
                entered_step_at=entered_step_at,
                completed_at=completed_at,
            )
            self.db.add(state)
            await self.db.flush()
            await self.db.refresh(state)
            return state

        await self.db.execute(
            update(ChatFunnelState)
            .where(ChatFunnelState.chat_id == chat_id)
            .values(
                funnel_id=funnel_id,
                funnel_version_id=funnel_version_id,
                current_step_id=current_step_id,
                entered_step_at=entered_step_at,
                completed_at=completed_at,
                updated_at=func.now(),
            )
        )
        refreshed = await self.get_chat_funnel_state(chat_id)
        assert refreshed is not None
        return refreshed

    async def get_chat_funnel_state(self, chat_id: UUID) -> Optional[ChatFunnelState]:
        result = await self.db.execute(
            select(ChatFunnelState)
            .where(ChatFunnelState.chat_id == chat_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_step(self, step_id: UUID) -> Optional[FunnelStep]:
        result = await self.db.execute(select(FunnelStep).where(FunnelStep.id == step_id))
        return result.scalar_one_or_none()

    async def first_edge_from_step(self, step_id: UUID) -> Optional[FunnelEdge]:
        result = await self.db.execute(
            select(FunnelEdge)
            .where(FunnelEdge.from_step_id == step_id)
            .order_by(FunnelEdge.priority.asc(), FunnelEdge.created_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_lead_by_chat(self, chat_id: UUID) -> Optional[Lead]:
        result = await self.db.execute(
            select(Lead)
            .join(Chat, Chat.id == Lead.chat_id)
            .where(Lead.chat_id == chat_id, Chat.reset_at.is_(None), Lead.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def update_lead_mapped_fields(
        self,
        lead_id: UUID,
        direct_values: dict,
        custom_values: dict,
    ) -> None:
        values = dict(direct_values)
        if custom_values:
            lead = await self.get_lead_by_id(lead_id)
            existing = dict(lead.custom_fields or {}) if lead is not None else {}
            existing.update(custom_values)
            values["custom_fields"] = existing
        if not values:
            return
        values["updated_at"] = func.now()
        await self.db.execute(update(Lead).where(Lead.id == lead_id).values(**values))

    async def get_lead_by_id(self, lead_id: UUID) -> Optional[Lead]:
        result = await self.db.execute(select(Lead).where(Lead.id == lead_id))
        return result.scalar_one_or_none()

    async def find_stuck_chats_for_push_rules(
        self,
        *,
        now: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[tuple[ChatFunnelState, FunnelPushRule]]:
        now = now or datetime.now(timezone.utc)
        result = await self.db.execute(
            select(ChatFunnelState, FunnelPushRule)
            .join(
                FunnelPushRule,
                FunnelPushRule.step_id == ChatFunnelState.current_step_id,
            )
            .where(
                ChatFunnelState.completed_at.is_(None),
                FunnelPushRule.is_active.is_(True),
                ChatFunnelState.entered_step_at
                <= now - func.make_interval(0, 0, 0, 0, 0, FunnelPushRule.delay_minutes),
            )
            .limit(limit)
        )
        return [(state, rule) for state, rule in result.all()]

    @staticmethod
    def _step_from_in(version_id: UUID, step_in: FunnelStepIn) -> FunnelStep:
        values = step_in.model_dump()
        step_id = values.pop("id", None)
        if step_id is not None:
            values["id"] = step_id
        return FunnelStep(funnel_version_id=version_id, **values)

    @staticmethod
    def _edge_from_in(version_id: UUID, edge_in: FunnelEdgeIn) -> FunnelEdge:
        values = edge_in.model_dump()
        edge_id = values.pop("id", None)
        if edge_id is not None:
            values["id"] = edge_id
        return FunnelEdge(funnel_version_id=version_id, **values)

    @staticmethod
    def _push_rule_from_in(version_id: UUID, rule_in: FunnelPushRuleIn) -> FunnelPushRule:
        values = rule_in.model_dump()
        rule_id = values.pop("id", None)
        if rule_id is not None:
            values["id"] = rule_id
        return FunnelPushRule(funnel_version_id=version_id, **values)

    @staticmethod
    def _field_mapping_from_in(
        version_id: UUID,
        mapping_in: FunnelFieldMappingIn,
    ) -> FunnelFieldMapping:
        values = mapping_in.model_dump()
        mapping_id = values.pop("id", None)
        if mapping_id is not None:
            values["id"] = mapping_id
        return FunnelFieldMapping(funnel_version_id=version_id, **values)
