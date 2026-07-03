from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import selectinload

from app.models.bot import Bot
from app.models.chat import Chat
from app.models.funnel import (
    ChatFunnelState,
    Funnel,
    FunnelEdge,
    FunnelFieldMapping,
    FunnelPushRule,
    FunnelRuntimeLog,
    FunnelScheduledJob,
    FunnelStepLog,
    FunnelStep,
    FunnelVersion,
)
from app.models.lead import Lead
from app.models.lead_status import LeadStatus
from app.models.project import Project
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

    async def get_published_version_for_broadcast(
        self,
        *,
        project_id: UUID,
        bot_id: UUID,
        funnel_id: UUID,
        version_id: Optional[UUID] = None,
    ) -> tuple[Optional[Funnel], Optional[FunnelVersion]]:
        stmt = (
            select(Funnel, FunnelVersion)
            .join(FunnelVersion, FunnelVersion.funnel_id == Funnel.id)
            .where(
                Funnel.id == funnel_id,
                Funnel.project_id == project_id,
                Funnel.bot_id == bot_id,
                Funnel.status == "active",
                FunnelVersion.status == "published",
            )
            .order_by(FunnelVersion.published_at.desc().nullslast())
            .limit(1)
        )
        if version_id is not None:
            stmt = stmt.where(FunnelVersion.id == version_id)
        result = await self.db.execute(stmt)
        row = result.first()
        if row is None:
            return None, None
        return row[0], row[1]

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
            select(FunnelVersion)
            .where(
                FunnelVersion.funnel_id == funnel_id,
                FunnelVersion.status == "published",
            )
            .order_by(
                FunnelVersion.published_at.desc().nullslast(),
                FunnelVersion.version_number.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_current_published_version(
        self,
        funnel_id: UUID,
    ) -> Optional[FunnelVersion]:
        result = await self.db.execute(
            select(FunnelVersion)
            .join(Funnel, Funnel.current_version_id == FunnelVersion.id)
            .where(
                Funnel.id == funnel_id,
                FunnelVersion.funnel_id == funnel_id,
                FunnelVersion.status == "published",
            )
            .limit(1)
        )
        current = result.scalar_one_or_none()
        if current is not None:
            return current
        return await self.get_published(funnel_id)

    async def list_published_versions(self, funnel_id: UUID) -> list[FunnelVersion]:
        result = await self.db.execute(
            select(FunnelVersion)
            .where(
                FunnelVersion.funnel_id == funnel_id,
                FunnelVersion.status == "published",
            )
            .order_by(
                FunnelVersion.published_at.desc().nullslast(),
                FunnelVersion.version_number.desc(),
            )
        )
        return list(result.scalars().all())

    async def get_published_for_bot(self, bot_id: UUID) -> Optional[FunnelVersion]:
        result = await self.db.execute(
            select(FunnelVersion)
            .join(Funnel, Funnel.id == FunnelVersion.funnel_id)
            .join(Bot, Bot.id == Funnel.bot_id)
            .where(
                Bot.id == bot_id,
                Bot.is_deleted.is_(False),
                Funnel.bot_id == bot_id,
                Funnel.id == Bot.active_funnel_id,
                Funnel.status == "active",
                FunnelVersion.id == Bot.active_funnel_version_id,
                FunnelVersion.status == "published",
            )
            .order_by(FunnelVersion.published_at.desc().nullslast())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_active_published_funnel_for_bot(
        self,
        bot_id: UUID,
        project_id: UUID,
    ) -> tuple[Optional[Funnel], Optional[FunnelVersion]]:
        result = await self.db.execute(
            select(Funnel, FunnelVersion)
            .select_from(Bot)
            .join(Funnel, Funnel.id == Bot.active_funnel_id)
            .join(FunnelVersion, FunnelVersion.id == Bot.active_funnel_version_id)
            .where(
                Bot.id == bot_id,
                Bot.project_id == project_id,
                Bot.is_deleted.is_(False),
                Funnel.id == Bot.active_funnel_id,
                Funnel.bot_id == Bot.id,
                Funnel.project_id == Bot.project_id,
                Funnel.status == "active",
                FunnelVersion.id == Bot.active_funnel_version_id,
                FunnelVersion.funnel_id == Funnel.id,
                FunnelVersion.status == "published",
            )
            .limit(1)
        )
        row = result.first()
        if row is None:
            return None, None
        return row[0], row[1]

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

    async def set_current_version_for_funnel(
        self,
        *,
        funnel_id: UUID,
        version_id: UUID,
    ) -> Optional[Funnel]:
        result = await self.db.execute(
            update(Funnel)
            .where(Funnel.id == funnel_id)
            .values(current_version_id=version_id, updated_at=func.now())
        )
        if result.rowcount == 0:
            return None
        return await self.get_by_id(funnel_id)

    async def sync_active_bot_version_for_funnel(
        self,
        *,
        funnel_id: UUID,
        version_id: UUID,
    ) -> None:
        await self.db.execute(
            update(Bot)
            .where(
                Bot.active_funnel_id == funnel_id,
                Bot.is_deleted.is_(False),
            )
            .values(active_funnel_version_id=version_id, updated_at=func.now())
        )

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
        await self.cancel_scheduled_jobs_for_chat(chat_id=chat_id)
        await self.db.execute(
            update(ChatFunnelState)
            .where(ChatFunnelState.chat_id == chat_id)
            .values(
                waiting_for_answer=False,
                is_paused=False,
                paused_at=None,
                paused_by_user_id=None,
                completed_at=func.now(),
                runtime_json={},
                updated_at=func.now(),
            )
        )

    async def delete_chat_funnel_state(self, chat_id: UUID) -> None:
        await self.cancel_scheduled_jobs_for_chat(chat_id=chat_id)
        await self.db.execute(
            delete(ChatFunnelState).where(ChatFunnelState.chat_id == chat_id)
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
            created_by_id=created_by_user_id,
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

    async def update_version_hold_mode(
        self,
        version_id: UUID,
        *,
        is_hold_active: bool,
    ) -> Optional[FunnelVersion]:
        result = await self.db.execute(
            update(FunnelVersion)
            .where(FunnelVersion.id == version_id)
            .values(is_hold_active=is_hold_active, updated_at=func.now())
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
        await self.db.flush()

        existing_result = await self.db.execute(
            select(FunnelStep.id).where(FunnelStep.funnel_version_id == version_id)
        )
        existing_step_ids = set(existing_result.scalars().all())
        incoming_step_ids = {step.id for step in graph.steps if step.id is not None}
        removed_step_ids = existing_step_ids - incoming_step_ids
        if removed_step_ids:
            await self.db.execute(
                delete(FunnelStep).where(
                    FunnelStep.funnel_version_id == version_id,
                    FunnelStep.id.in_(removed_step_ids),
                )
            )
            await self.db.flush()

        existing_incoming_step_ids = existing_step_ids & incoming_step_ids
        for step_id in existing_incoming_step_ids:
            await self.db.execute(
                update(FunnelStep)
                .where(
                    FunnelStep.id == step_id,
                    FunnelStep.funnel_version_id == version_id,
                )
                .values(key=f"__tmp_{step_id}", updated_at=func.now())
            )
        if existing_incoming_step_ids:
            await self.db.flush()

        for step_in in graph.steps:
            values = step_in.model_dump()
            step_id = values.pop("id", None)
            if step_id is not None and step_id in existing_step_ids:
                await self.db.execute(
                    update(FunnelStep)
                    .where(
                        FunnelStep.id == step_id,
                        FunnelStep.funnel_version_id == version_id,
                    )
                    .values(**values, updated_at=func.now())
                )
                continue
            self.db.add(self._step_from_values(version_id, step_id, values))
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
        waiting_for_answer: bool = False,
        is_paused: bool | None = None,
        paused_at: datetime | None = None,
        paused_by_user_id: UUID | None = None,
        completed_at: Optional[datetime] = None,
        runtime_json: Optional[dict] = None,
    ) -> ChatFunnelState:
        existing = await self.get_chat_funnel_state(chat_id)
        if existing is None:
            state = ChatFunnelState(
                chat_id=chat_id,
                funnel_id=funnel_id,
                funnel_version_id=funnel_version_id,
                current_step_id=current_step_id,
                entered_step_at=entered_step_at,
                waiting_for_answer=waiting_for_answer,
                is_paused=bool(is_paused),
                paused_at=paused_at if is_paused else None,
                paused_by_user_id=paused_by_user_id if is_paused else None,
                completed_at=completed_at,
                runtime_json=runtime_json or {},
            )
            self.db.add(state)
            await self.db.flush()
            await self.db.refresh(state)
            return state

        values = {
            "funnel_id": funnel_id,
            "funnel_version_id": funnel_version_id,
            "current_step_id": current_step_id,
            "entered_step_at": entered_step_at,
            "waiting_for_answer": waiting_for_answer,
            "completed_at": completed_at,
            "updated_at": func.now(),
        }
        if is_paused is not None:
            values.update(
                {
                    "is_paused": is_paused,
                    "paused_at": paused_at if is_paused else None,
                    "paused_by_user_id": paused_by_user_id if is_paused else None,
                }
            )
        if runtime_json is not None:
            values["runtime_json"] = runtime_json
        await self.db.execute(
            update(ChatFunnelState)
            .where(ChatFunnelState.chat_id == chat_id)
            .values(**values)
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

    async def update_chat_funnel_runtime(
        self,
        *,
        chat_id: UUID,
        runtime_json: dict,
    ) -> Optional[ChatFunnelState]:
        result = await self.db.execute(
            update(ChatFunnelState)
            .where(ChatFunnelState.chat_id == chat_id)
            .values(runtime_json=runtime_json, updated_at=func.now())
        )
        if result.rowcount == 0:
            return None
        return await self.get_chat_funnel_state(chat_id)

    async def set_chat_funnel_paused(
        self,
        *,
        chat_id: UUID,
        is_paused: bool,
        paused_at: datetime | None = None,
        paused_by_user_id: UUID | None = None,
    ) -> Optional[ChatFunnelState]:
        result = await self.db.execute(
            update(ChatFunnelState)
            .where(ChatFunnelState.chat_id == chat_id)
            .values(
                is_paused=is_paused,
                paused_at=paused_at if is_paused else None,
                paused_by_user_id=paused_by_user_id if is_paused else None,
                updated_at=func.now(),
            )
        )
        if result.rowcount == 0:
            return None
        return await self.get_chat_funnel_state(chat_id)

    async def create_scheduled_job(
        self,
        *,
        job_type: str,
        chat_id: UUID,
        funnel_state_id: Optional[UUID],
        funnel_id: UUID,
        funnel_version_id: UUID,
        step_id: UUID,
        run_at: datetime,
        payload_json: Optional[dict] = None,
    ) -> FunnelScheduledJob:
        job = FunnelScheduledJob(
            job_type=job_type,
            chat_id=chat_id,
            funnel_state_id=funnel_state_id,
            funnel_id=funnel_id,
            funnel_version_id=funnel_version_id,
            step_id=step_id,
            run_at=run_at,
            payload_json=payload_json or {},
        )
        self.db.add(job)
        await self.db.flush()
        await self.db.refresh(job)
        return job

    async def get_scheduled_job(self, job_id: UUID) -> Optional[FunnelScheduledJob]:
        result = await self.db.execute(
            select(FunnelScheduledJob).where(FunnelScheduledJob.id == job_id)
        )
        return result.scalar_one_or_none()

    async def list_due_scheduled_jobs(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> list[FunnelScheduledJob]:
        result = await self.db.execute(
            select(FunnelScheduledJob)
            .where(
                FunnelScheduledJob.status == "pending",
                FunnelScheduledJob.run_at <= now,
            )
            .order_by(FunnelScheduledJob.run_at.asc(), FunnelScheduledJob.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())

    async def claim_scheduled_job(self, job_id: UUID) -> bool:
        result = await self.db.execute(
            update(FunnelScheduledJob)
            .where(FunnelScheduledJob.id == job_id, FunnelScheduledJob.status == "pending")
            .values(
                status="running",
                attempts=FunnelScheduledJob.attempts + 1,
                updated_at=func.now(),
            )
        )
        return result.rowcount == 1

    async def mark_scheduled_job_done(self, job_id: UUID) -> None:
        await self.db.execute(
            update(FunnelScheduledJob)
            .where(FunnelScheduledJob.id == job_id)
            .values(status="done", updated_at=func.now())
        )

    async def mark_scheduled_job_failed(self, job_id: UUID, error: str) -> None:
        await self.db.execute(
            update(FunnelScheduledJob)
            .where(FunnelScheduledJob.id == job_id)
            .values(status="failed", last_error=error[:2000], updated_at=func.now())
        )

    async def cancel_scheduled_jobs_for_chat(
        self,
        *,
        chat_id: UUID,
        job_type: Optional[str] = None,
        step_id: Optional[UUID] = None,
    ) -> None:
        stmt = update(FunnelScheduledJob).where(
            FunnelScheduledJob.chat_id == chat_id,
            FunnelScheduledJob.status == "pending",
        )
        if job_type is not None:
            stmt = stmt.where(FunnelScheduledJob.job_type == job_type)
        if step_id is not None:
            stmt = stmt.where(FunnelScheduledJob.step_id == step_id)
        await self.db.execute(stmt.values(status="cancelled", updated_at=func.now()))

    async def get_chat_funnel_contexts(
        self,
        *,
        project_id: UUID,
        chat_ids: list[UUID],
    ) -> dict[UUID, dict]:
        if not chat_ids:
            return {}

        result = await self.db.execute(
            select(
                Chat.id.label("chat_id"),
                Funnel.id.label("active_funnel_id"),
                Funnel.name.label("active_funnel_name"),
                FunnelVersion.id.label("active_funnel_version_id"),
                FunnelVersion.version_number.label("active_funnel_version_number"),
                FunnelVersion.status.label("active_funnel_version_status"),
                ChatFunnelState.current_step_id.label("current_step_id"),
                FunnelStep.title.label("current_step_title"),
                ChatFunnelState.waiting_for_answer.label("waiting_for_answer"),
                ChatFunnelState.is_paused.label("is_paused"),
                ChatFunnelState.completed_at.label("completed_at"),
            )
            .select_from(Chat)
            .outerjoin(Bot, Bot.id == Chat.bot_id)
            .outerjoin(
                Funnel,
                (Funnel.id == Bot.active_funnel_id)
                & (Funnel.bot_id == Bot.id)
                & (Funnel.project_id == Chat.project_id)
                & (Funnel.status == "active"),
            )
            .outerjoin(
                FunnelVersion,
                (FunnelVersion.id == Bot.active_funnel_version_id)
                & (FunnelVersion.funnel_id == Funnel.id)
                & (FunnelVersion.status == "published"),
            )
            .outerjoin(
                ChatFunnelState,
                (ChatFunnelState.chat_id == Chat.id)
                & (ChatFunnelState.funnel_version_id == FunnelVersion.id),
            )
            .outerjoin(FunnelStep, FunnelStep.id == ChatFunnelState.current_step_id)
            .where(
                Chat.project_id == project_id,
                Chat.id.in_(chat_ids),
                Chat.is_deleted.is_(False),
            )
        )
        contexts: dict[UUID, dict] = {}
        for row in result.mappings().all():
            contexts[row["chat_id"]] = dict(row)

        runtime_result = await self.db.execute(
            select(
                ChatFunnelState.chat_id.label("chat_id"),
                Funnel.id.label("active_funnel_id"),
                Funnel.name.label("active_funnel_name"),
                FunnelVersion.id.label("active_funnel_version_id"),
                FunnelVersion.version_number.label("active_funnel_version_number"),
                FunnelVersion.status.label("active_funnel_version_status"),
                ChatFunnelState.current_step_id.label("current_step_id"),
                FunnelStep.title.label("current_step_title"),
                ChatFunnelState.waiting_for_answer.label("waiting_for_answer"),
                ChatFunnelState.is_paused.label("is_paused"),
                ChatFunnelState.completed_at.label("completed_at"),
            )
            .select_from(ChatFunnelState)
            .join(Funnel, Funnel.id == ChatFunnelState.funnel_id)
            .join(FunnelVersion, FunnelVersion.id == ChatFunnelState.funnel_version_id)
            .outerjoin(FunnelStep, FunnelStep.id == ChatFunnelState.current_step_id)
            .where(
                ChatFunnelState.chat_id.in_(chat_ids),
                Funnel.project_id == project_id,
            )
        )
        for row in runtime_result.mappings().all():
            contexts.setdefault(row["chat_id"], {"chat_id": row["chat_id"]}).update(dict(row))
        return contexts

    async def create_step_log(
        self,
        *,
        lead_id: UUID,
        funnel_id: UUID,
        funnel_version_id: UUID,
        step_id: UUID,
        step_name: str,
        event_type: str,
    ) -> FunnelStepLog:
        log = FunnelStepLog(
            lead_id=lead_id,
            funnel_id=funnel_id,
            funnel_version_id=funnel_version_id,
            step_id=step_id,
            step_name=step_name,
            event_type=event_type,
        )
        self.db.add(log)
        await self.db.flush()
        return log

    async def create_runtime_log(
        self,
        *,
        chat_id: UUID,
        funnel_version_id: UUID,
        step_id: UUID,
        status: str,
        error_message: Optional[str] = None,
    ) -> FunnelRuntimeLog:
        log = FunnelRuntimeLog(
            chat_id=chat_id,
            funnel_version_id=funnel_version_id,
            step_id=step_id,
            status=status,
            error_message=error_message[:4000] if error_message else None,
        )
        self.db.add(log)
        await self.db.flush()
        return log

    async def list_runtime_logs_by_chat(
        self,
        *,
        chat_id: UUID,
        limit: int = 200,
        since: Optional[datetime] = None,
    ) -> list[FunnelRuntimeLog]:
        stmt = (
            select(FunnelRuntimeLog)
            .options(selectinload(FunnelRuntimeLog.step))
            .where(FunnelRuntimeLog.chat_id == chat_id)
            .order_by(FunnelRuntimeLog.created_at.asc(), FunnelRuntimeLog.id.asc())
            .limit(limit)
        )
        if since is not None:
            stmt = stmt.where(FunnelRuntimeLog.created_at >= since)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_active_chat_ids_for_funnel(self, funnel_id: UUID) -> list[UUID]:
        result = await self.db.execute(
            select(ChatFunnelState.chat_id)
            .where(
                ChatFunnelState.funnel_id == funnel_id,
                ChatFunnelState.completed_at.is_(None),
            )
            .order_by(ChatFunnelState.updated_at.desc())
        )
        return list(result.scalars().all())

    async def get_drop_off_rows(self, funnel_version_id: UUID) -> list[dict]:
        result = await self.db.execute(
            select(
                FunnelStep.id.label("step_id"),
                FunnelStep.title.label("step_title"),
                FunnelStep.step_type.label("step_type"),
                FunnelStep.block_type.label("block_type"),
                func.count(func.distinct(FunnelStepLog.lead_id)).label("entered_leads"),
            )
            .select_from(FunnelStep)
            .outerjoin(
                FunnelStepLog,
                (FunnelStepLog.step_id == FunnelStep.id)
                & (FunnelStepLog.event_type == "entered"),
            )
            .where(FunnelStep.funnel_version_id == funnel_version_id)
            .group_by(
                FunnelStep.id,
                FunnelStep.title,
                FunnelStep.step_type,
                FunnelStep.block_type,
                FunnelStep.position_x,
                FunnelStep.position_y,
                FunnelStep.created_at,
            )
            .order_by(FunnelStep.position_x.asc(), FunnelStep.position_y.asc(), FunnelStep.created_at.asc())
        )
        return [dict(row) for row in result.mappings().all()]

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

    async def get_message_template_context(self, chat_id: UUID) -> dict:
        result = await self.db.execute(
            select(
                Chat.external_user_id,
                Chat.contact_name,
                Lead.name,
                Lead.phone,
                Lead.username,
                Lead.age,
                Lead.country,
                Lead.call_time_text,
                Lead.custom_fields,
                LeadStatus.code.label("lead_status"),
                Project.name.label("project"),
                Bot.name.label("bot"),
            )
            .select_from(Chat)
            .outerjoin(
                Lead,
                (Lead.chat_id == Chat.id) & Lead.is_deleted.is_(False),
            )
            .outerjoin(LeadStatus, LeadStatus.id == Lead.status_id)
            .join(Project, Project.id == Chat.project_id)
            .outerjoin(Bot, Bot.id == Chat.bot_id)
            .where(Chat.id == chat_id, Chat.reset_at.is_(None))
            .limit(1)
        )
        row = result.mappings().first()
        return dict(row) if row is not None else {}

    async def update_lead_mapped_fields(
        self,
        lead_id: UUID,
        direct_values: dict,
        custom_values: dict,
    ) -> None:
        values = dict(direct_values)
        if "call_time_text" in values and "preferred_call_time" not in values:
            values["preferred_call_time"] = values["call_time_text"]
        if "preferred_call_time" in values and "call_time_text" not in values:
            values["call_time_text"] = values["preferred_call_time"]
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
        return FunnelRepository._step_from_values(version_id, step_id, values)

    @staticmethod
    def _step_from_values(
        version_id: UUID,
        step_id: Optional[UUID],
        values: dict,
    ) -> FunnelStep:
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
