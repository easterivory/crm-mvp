from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ChatEventType, RoleName
from app.models.funnel import Funnel, FunnelVersion
from app.models.user import User
from app.repositories.funnel_repository import FunnelRepository
from app.schemas.common import PaginatedResponse
from app.schemas.funnel import (
    BotActiveFunnelGraphSummary,
    BotActiveFunnelOut,
    BotActiveFunnelSetIn,
    FunnelCopyIn,
    FunnelCopyOut,
    FunnelCreate,
    FunnelDropOffAnalyticsOut,
    FunnelDropOffStepOut,
    FunnelEdgeOut,
    FunnelFieldMappingOut,
    FunnelGraphIn,
    FunnelGraphOut,
    FunnelHoldModeUpdate,
    FunnelOut,
    FunnelPushRuleOut,
    FunnelStepIn,
    FunnelStepOut,
    FunnelUpdate,
    FunnelValidationIssue,
    FunnelValidationOut,
    FunnelVersionOut,
    FunnelVersionUpdate,
)
from app.services.funnel_block_registry import (
    LEAD_FIELD_KEYS,
    FunnelBlockRegistry,
)
from app.services.chat_audit_service import ChatAuditService
from app.services.funnel_validator import FunnelGraphValidator


logger = logging.getLogger(__name__)


class FunnelService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = FunnelRepository(db)
        self.registry = FunnelBlockRegistry()
        self.graph_validator = FunnelGraphValidator()

    async def list_funnels(
        self,
        *,
        project_id: UUID,
        current_user: User,
        bot_id: Optional[UUID],
        status_filter: Optional[str],
        limit: int,
        offset: int,
    ) -> PaginatedResponse[FunnelOut]:
        self._ensure_read_allowed(current_user)
        funnels = await self.repo.list_by_project(
            project_id,
            bot_id=bot_id,
            status=status_filter,
            limit=limit,
            offset=offset,
        )
        total = await self.repo.count_by_project(
            project_id,
            bot_id=bot_id,
            status=status_filter,
        )
        items = [await self._funnel_out(funnel) for funnel in funnels]
        return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)

    async def create_funnel(
        self,
        *,
        project_id: UUID,
        data: FunnelCreate,
        current_user: User,
    ) -> FunnelOut:
        self._ensure_write_allowed(current_user)
        if data.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Project is not accessible for current user",
            )
        await self._ensure_bot_in_project(data.bot_id, project_id)

        funnel = await self.repo.create(
            project_id=project_id,
            bot_id=data.bot_id,
            name=data.name,
            description=data.description,
            created_by_user_id=current_user.id,
        )
        draft = await self.repo.create_version(
            funnel_id=funnel.id,
            version_number=1,
            created_by_user_id=current_user.id,
        )
        await self.repo.replace_graph(
            draft.id,
            FunnelGraphIn(steps=[self._default_trigger_step()]),
        )
        return await self._funnel_out(funnel)

    async def get_funnel(
        self,
        *,
        funnel_id: UUID,
        project_id: UUID,
        current_user: User,
    ) -> FunnelOut:
        self._ensure_read_allowed(current_user)
        funnel = await self._get_funnel_or_404(funnel_id, project_id)
        return await self._funnel_out(funnel)

    async def update_funnel(
        self,
        *,
        funnel_id: UUID,
        project_id: UUID,
        data: FunnelUpdate,
        current_user: User,
    ) -> FunnelOut:
        self._ensure_write_allowed(current_user)
        funnel = await self._get_funnel_or_404(funnel_id, project_id)
        values = data.model_dump(exclude_unset=True)
        if "name" in values and values["name"] is not None:
            values["name"] = values["name"].strip()
        updated = await self.repo.update_in_project(funnel_id, project_id, **values)
        assert updated is not None
        return await self._funnel_out(updated)

    async def archive_funnel(
        self,
        *,
        funnel_id: UUID,
        project_id: UUID,
        current_user: User,
    ) -> FunnelOut:
        self._ensure_write_allowed(current_user)
        funnel = await self._get_funnel_or_404(funnel_id, project_id)
        updated = await self.repo.update_in_project(
            funnel_id,
            project_id,
            status="archived",
        )
        await self.repo.archive_published_versions(funnel_id=funnel_id)
        await self.repo.clear_active_funnel_for_bot(
            bot_id=funnel.bot_id,
            funnel_id=funnel.id,
        )
        assert updated is not None
        return await self._funnel_out(updated)

    async def list_versions(
        self,
        *,
        funnel_id: UUID,
        project_id: UUID,
        current_user: User,
    ) -> list[FunnelVersionOut]:
        self._ensure_read_allowed(current_user)
        funnel = await self._get_funnel_or_404(funnel_id, project_id)
        _, active_version = await self.repo.get_active_funnel_for_bot(
            funnel.bot_id,
            project_id,
        )
        active_version_id = active_version.id if active_version else None
        return [
            FunnelVersionOut.model_validate(version).model_copy(
                update={"is_active_for_bot": version.id == active_version_id}
            )
            for version in await self.repo.list_versions(funnel_id)
        ]

    async def create_draft_version(
        self,
        *,
        funnel_id: UUID,
        project_id: UUID,
        current_user: User,
    ) -> FunnelVersionOut:
        self._ensure_write_allowed(current_user)
        await self._get_funnel_or_404(funnel_id, project_id)

        existing_draft = await self.repo.get_latest_draft(funnel_id)
        if existing_draft is not None:
            return FunnelVersionOut.model_validate(existing_draft)

        version = await self.repo.create_version(
            funnel_id=funnel_id,
            version_number=await self.repo.next_version_number(funnel_id),
            created_by_user_id=current_user.id,
        )
        published = await self.repo.get_published(funnel_id)
        if published is not None:
            await self.repo.clone_graph(published.id, version.id)
        return FunnelVersionOut.model_validate(version)

    async def create_draft_from_version(
        self,
        *,
        funnel_id: UUID,
        source_version_id: UUID,
        project_id: UUID,
        current_user: User,
    ) -> FunnelVersionOut:
        self._ensure_write_allowed(current_user)
        await self._get_version_or_404(funnel_id, source_version_id, project_id)
        draft = await self.repo.create_version(
            funnel_id=funnel_id,
            version_number=await self.repo.next_version_number(funnel_id),
            created_by_user_id=current_user.id,
        )
        await self.repo.clone_graph(source_version_id, draft.id)
        return FunnelVersionOut.model_validate(draft)

    async def get_version(
        self,
        *,
        funnel_id: UUID,
        version_id: UUID,
        project_id: UUID,
        current_user: User,
    ) -> FunnelVersionOut:
        self._ensure_read_allowed(current_user)
        version = await self._get_version_or_404(funnel_id, version_id, project_id)
        funnel = await self._get_funnel_or_404(funnel_id, project_id)
        _, active_version = await self.repo.get_active_funnel_for_bot(
            funnel.bot_id,
            project_id,
        )
        return FunnelVersionOut.model_validate(version).model_copy(
            update={
                "is_active_for_bot": bool(
                    active_version is not None and active_version.id == version.id
                )
            }
        )

    async def update_version(
        self,
        *,
        funnel_id: UUID,
        version_id: UUID,
        project_id: UUID,
        data: FunnelVersionUpdate,
        current_user: User,
    ) -> FunnelVersionOut:
        self._ensure_write_allowed(current_user)
        version = await self._get_version_or_404(funnel_id, version_id, project_id)
        if data.status is None:
            return FunnelVersionOut.model_validate(version)
        if data.status == "published":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Use publish endpoint to publish funnel versions",
            )
        updated = await self.repo.update_version_status(version_id, data.status)
        assert updated is not None
        return FunnelVersionOut.model_validate(updated)

    async def get_active_funnel_for_bot(
        self,
        *,
        bot_id: UUID,
        project_id: UUID,
        current_user: User,
    ) -> BotActiveFunnelOut:
        self._ensure_read_allowed(current_user)
        await self._ensure_bot_in_project(bot_id, project_id)
        funnel, version = await self.repo.get_active_funnel_for_bot(bot_id, project_id)
        graph_summary = (
            await self._active_graph_summary(version.id)
            if version is not None
            else None
        )
        return BotActiveFunnelOut(
            bot_id=bot_id,
            active_funnel_id=funnel.id if funnel is not None else None,
            active_funnel_version_id=version.id if version is not None else None,
            funnel=await self._funnel_out(funnel) if funnel is not None else None,
            version=(
                FunnelVersionOut.model_validate(version).model_copy(
                    update={"is_active_for_bot": True}
                )
                if version is not None
                else None
            ),
            version_status=version.status if version is not None else None,
            version_number=version.version_number if version is not None else None,
            graph_summary=graph_summary,
        )

    async def set_active_funnel_for_bot(
        self,
        *,
        bot_id: UUID,
        project_id: UUID,
        data: BotActiveFunnelSetIn,
        current_user: User,
    ) -> BotActiveFunnelOut:
        self._ensure_write_allowed(current_user)
        await self._ensure_bot_in_project(bot_id, project_id)
        version = await self._get_version_or_404(data.funnel_id, data.version_id, project_id)
        funnel = await self._get_funnel_or_404(data.funnel_id, project_id)
        if funnel.bot_id != bot_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Funnel belongs to another bot",
            )
        if version.status != "published":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only published versions can be activated",
            )
        await self._activate_version_for_bot(
            funnel=funnel,
            version=version,
            project_id=project_id,
        )
        return await self.get_active_funnel_for_bot(
            bot_id=bot_id,
            project_id=project_id,
            current_user=current_user,
        )

    async def get_graph(
        self,
        *,
        funnel_id: UUID,
        version_id: UUID,
        project_id: UUID,
        current_user: User,
    ) -> FunnelGraphOut:
        self._ensure_read_allowed(current_user)
        await self._get_version_or_404(funnel_id, version_id, project_id)
        return await self._graph_out(version_id)

    async def save_graph(
        self,
        *,
        funnel_id: UUID,
        version_id: UUID,
        project_id: UUID,
        graph: FunnelGraphIn,
        current_user: User,
    ) -> FunnelGraphOut:
        self._ensure_write_allowed(current_user)
        version = await self._get_version_or_404(funnel_id, version_id, project_id)
        if version.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only draft versions can be edited",
            )
        draft_validation = self._validate_graph_payload(graph, strict_config=False)
        if draft_validation.errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[issue.model_dump(mode="json") for issue in draft_validation.errors],
            )
        await self.repo.replace_graph(version_id, graph)
        return await self._graph_out(version_id)

    async def validate_version(
        self,
        *,
        funnel_id: UUID,
        version_id: UUID,
        project_id: UUID,
        current_user: User,
    ) -> FunnelValidationOut:
        self._ensure_read_allowed(current_user)
        await self._get_version_or_404(funnel_id, version_id, project_id)
        graph = await self._graph_in_from_db(version_id)
        return self._validate_graph_payload(graph, strict_config=True)

    async def publish_version(
        self,
        *,
        funnel_id: UUID,
        version_id: UUID,
        project_id: UUID,
        current_user: User,
    ) -> FunnelVersionOut:
        self._ensure_write_allowed(current_user)
        version = await self._get_version_or_404(funnel_id, version_id, project_id)
        if version.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only draft versions can be published",
            )
        validation = await self.validate_version(
            funnel_id=funnel_id,
            version_id=version_id,
            project_id=project_id,
            current_user=current_user,
        )
        if validation.errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[issue.model_dump(mode="json") for issue in validation.errors],
            )

        funnel = await self._get_funnel_or_404(funnel_id, project_id)
        await self.repo.archive_published_versions_for_bot(
            bot_id=funnel.bot_id,
            exclude_version_id=version_id,
        )
        await self.repo.archive_published_versions(
            funnel_id=funnel_id,
            exclude_version_id=version_id,
        )
        published = await self.repo.update_version_status(
            version_id,
            "published",
            published_at=datetime.now(timezone.utc),
        )
        assert published is not None
        await self.repo.set_active_funnel_for_bot(
            bot_id=funnel.bot_id,
            project_id=project_id,
            funnel_id=funnel.id,
            version_id=published.id,
        )
        await self.repo.update_in_project(funnel_id, project_id)
        return FunnelVersionOut.model_validate(published).model_copy(
            update={"is_active_for_bot": True}
        )

    async def rollback_to_version(
        self,
        *,
        funnel_id: UUID,
        version_id: UUID,
        project_id: UUID,
        current_user: User,
    ) -> FunnelVersionOut:
        self._ensure_write_allowed(current_user)
        version = await self._get_version_or_404(funnel_id, version_id, project_id)
        funnel = await self._get_funnel_or_404(funnel_id, project_id)

        validation = self._validate_graph_payload(
            await self._graph_in_from_db(version.id),
            strict_config=True,
        )
        if validation.errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[issue.model_dump(mode="json") for issue in validation.errors],
            )

        _, active_version = await self.repo.get_active_funnel_for_bot(
            funnel.bot_id,
            project_id,
        )
        if active_version is not None and active_version.id == version.id:
            return FunnelVersionOut.model_validate(version).model_copy(
                update={"is_active_for_bot": True}
            )

        await self.repo.archive_published_versions_for_bot(
            bot_id=funnel.bot_id,
            exclude_version_id=version.id,
        )
        await self.repo.archive_published_versions(
            funnel_id=funnel.id,
            exclude_version_id=version.id,
        )
        published = await self.repo.update_version_status(
            version.id,
            "published",
            published_at=datetime.now(timezone.utc),
        )
        assert published is not None
        await self.repo.set_active_funnel_for_bot(
            bot_id=funnel.bot_id,
            project_id=project_id,
            funnel_id=funnel.id,
            version_id=published.id,
        )
        await self.repo.update_in_project(funnel.id, project_id)
        await self._log_rollback_audit(
            funnel=funnel,
            previous_version=active_version,
            new_version=published,
            project_id=project_id,
            current_user_id=current_user.id,
        )
        return FunnelVersionOut.model_validate(published).model_copy(
            update={"is_active_for_bot": True}
        )

    async def set_hold_mode(
        self,
        *,
        funnel_id: UUID,
        version_id: UUID,
        project_id: UUID,
        data: FunnelHoldModeUpdate,
        current_user: User,
    ) -> FunnelVersionOut:
        self._ensure_write_allowed(current_user)
        version = await self._get_version_or_404(funnel_id, version_id, project_id)
        updated = await self.repo.update_version_hold_mode(
            version.id,
            is_hold_active=data.is_hold_active,
        )
        assert updated is not None
        return FunnelVersionOut.model_validate(updated)

    async def get_drop_off_analytics(
        self,
        *,
        funnel_id: UUID,
        version_id: UUID,
        project_id: UUID,
        current_user: User,
    ) -> FunnelDropOffAnalyticsOut:
        self._ensure_read_allowed(current_user)
        await self._get_version_or_404(funnel_id, version_id, project_id)
        rows = await self.repo.get_drop_off_rows(version_id)
        first_count = int(rows[0]["entered_leads"] or 0) if rows else 0
        previous_count = first_count
        steps: list[FunnelDropOffStepOut] = []
        for row in rows:
            entered = int(row["entered_leads"] or 0)
            conversion_from_start = (entered / first_count * 100) if first_count else 0.0
            conversion_from_previous = (entered / previous_count * 100) if previous_count else 0.0
            steps.append(
                FunnelDropOffStepOut(
                    step_id=row["step_id"],
                    step_title=row["step_title"],
                    step_type=row["step_type"],
                    block_type=row["block_type"],
                    entered_leads=entered,
                    conversion_from_start=round(conversion_from_start, 2),
                    conversion_from_previous=round(conversion_from_previous, 2),
                )
            )
            previous_count = entered
        return FunnelDropOffAnalyticsOut(
            funnel_id=funnel_id,
            version_id=version_id,
            steps=steps,
        )

    async def _activate_version_for_bot(
        self,
        *,
        funnel: Funnel,
        version: FunnelVersion,
        project_id: UUID,
    ) -> None:
        await self.repo.archive_published_versions_for_bot(
            bot_id=funnel.bot_id,
            exclude_version_id=version.id,
        )
        await self.repo.archive_published_versions(
            funnel_id=funnel.id,
            exclude_version_id=version.id,
        )
        await self.repo.set_active_funnel_for_bot(
            bot_id=funnel.bot_id,
            project_id=project_id,
            funnel_id=funnel.id,
            version_id=version.id,
        )

    async def _log_rollback_audit(
        self,
        *,
        funnel: Funnel,
        previous_version: Optional[FunnelVersion],
        new_version: FunnelVersion,
        project_id: UUID,
        current_user_id: UUID,
    ) -> None:
        chat_ids = await self.repo.list_active_chat_ids_for_funnel(funnel.id)
        if not chat_ids:
            return
        previous_label = (
            f"v{previous_version.version_number}"
            if previous_version is not None
            else "нет активной версии"
        )
        new_label = f"v{new_version.version_number}"
        message = f"Откат воронки «{funnel.name}»: {previous_label} -> {new_label}"
        audit_service = ChatAuditService(self.db)
        for chat_id in chat_ids:
            try:
                await audit_service.log_event(
                    chat_id=chat_id,
                    user_id=current_user_id,
                    event_type=ChatEventType.NOTE_ADDED,
                    old_value=previous_label,
                    new_value=message,
                    project_id=project_id,
                )
            except Exception:
                logger.warning(
                    "Failed to write funnel rollback chat audit chat_id=%s funnel_id=%s",
                    chat_id,
                    funnel.id,
                    exc_info=True,
                )

    async def copy_funnel(
        self,
        *,
        funnel_id: UUID,
        project_id: UUID,
        data: FunnelCopyIn,
        current_user: User,
    ) -> FunnelCopyOut:
        self._ensure_write_allowed(current_user)
        source = await self._get_funnel_or_404(funnel_id, project_id)
        self._ensure_target_project_allowed(current_user, data.target_project_id)
        await self._ensure_bot_in_project(data.target_bot_id, data.target_project_id)

        if data.copy_from_version_id is not None:
            source_version = await self._get_version_or_404(
                funnel_id,
                data.copy_from_version_id,
                project_id,
            )
        else:
            source_version = await self.repo.get_published(funnel_id)
            if source_version is None:
                source_version = await self.repo.get_latest_draft(funnel_id)
        if source_version is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Funnel version to copy was not found",
            )

        copied = await self.repo.create(
            project_id=data.target_project_id,
            bot_id=data.target_bot_id,
            name=f"{source.name} (копия)",
            description=source.description,
            created_by_user_id=current_user.id,
        )
        draft = await self.repo.create_version(
            funnel_id=copied.id,
            version_number=1,
            created_by_user_id=current_user.id,
        )
        await self.repo.clone_graph(source_version.id, draft.id)
        return FunnelCopyOut(new_funnel_id=copied.id, new_version_id=draft.id)

    async def _funnel_out(self, funnel: Funnel) -> FunnelOut:
        draft = await self.repo.get_latest_draft(funnel.id)
        published = await self.repo.get_published(funnel.id)
        _, active_version = await self.repo.get_active_funnel_for_bot(
            funnel.bot_id,
            funnel.project_id,
        )
        return FunnelOut.model_validate(funnel).model_copy(
            update={
                "draft_version_id": draft.id if draft else None,
                "published_version_id": published.id if published else None,
                "is_active_for_bot": bool(
                    active_version is not None
                    and published is not None
                    and active_version.id == published.id
                ),
            }
        )

    async def _graph_out(self, version_id: UUID) -> FunnelGraphOut:
        return FunnelGraphOut(
            steps=[
                FunnelStepOut.model_validate(step)
                for step in await self.repo.list_steps(version_id)
            ],
            edges=[
                FunnelEdgeOut.model_validate(edge)
                for edge in await self.repo.list_edges(version_id)
            ],
            push_rules=[
                FunnelPushRuleOut.model_validate(rule)
                for rule in await self.repo.list_push_rules(version_id)
            ],
            field_mappings=[
                FunnelFieldMappingOut.model_validate(mapping)
                for mapping in await self.repo.list_field_mappings(version_id)
            ],
        )

    async def _active_graph_summary(self, version_id: UUID) -> BotActiveFunnelGraphSummary:
        steps = await self.repo.list_steps(version_id)
        edges = await self.repo.list_edges(version_id)
        first_message_text: Optional[str] = None
        message_step = next(
            (
                step
                for step in steps
                if step.step_type == "message"
                or step.block_type
                in {
                    "generic_message",
                    "send_text",
                    "send_inline_buttons",
                    "send_personalized_message",
                }
            ),
            None,
        )
        if message_step is not None:
            config = message_step.config_json or {}
            raw_text = None
            messages = config.get("messages")
            if isinstance(messages, list):
                first = next((item for item in messages if isinstance(item, dict)), None)
                if first is not None:
                    raw_text = (
                        first.get("text")
                        or first.get("message")
                        or first.get("message_text")
                    )
            raw_text = raw_text or (
                config.get("text")
                or config.get("message")
                or config.get("message_text")
                or config.get("body")
                or config.get("content")
            )
            first_message_text = str(raw_text).strip() if raw_text is not None else None
        return BotActiveFunnelGraphSummary(
            steps_count=len(steps),
            edges_count=len(edges),
            has_trigger=any(step.step_type == "trigger" for step in steps),
            first_message_text=first_message_text or None,
        )

    async def _graph_in_from_db(self, version_id: UUID) -> FunnelGraphIn:
        graph = await self._graph_out(version_id)
        return FunnelGraphIn(
            steps=[
                FunnelStepIn(
                    id=step.id,
                    key=step.key,
                    title=step.title,
                    step_type=step.step_type,
                    block_type=step.block_type,
                    position_x=step.position_x,
                    position_y=step.position_y,
                    config_json=step.config_json,
                    validation_json=step.validation_json,
                    ui_schema_json=step.ui_schema_json,
                )
                for step in graph.steps
            ],
            edges=[
                {
                    "id": edge.id,
                    "from_step_id": edge.from_step_id,
                    "to_step_id": edge.to_step_id,
                    "condition_json": edge.condition_json,
                    "priority": edge.priority,
                }
                for edge in graph.edges
            ],
            push_rules=[
                {
                    "id": rule.id,
                    "step_id": rule.step_id,
                    "delay_minutes": rule.delay_minutes,
                    "message_text": rule.message_text,
                    "action_after_send": rule.action_after_send,
                    "target_step_id": rule.target_step_id,
                    "is_active": rule.is_active,
                }
                for rule in graph.push_rules
            ],
            field_mappings=[
                {
                    "id": mapping.id,
                    "step_id": mapping.step_id,
                    "source": mapping.source,
                    "lead_field_key": mapping.lead_field_key,
                    "transform_rule_json": mapping.transform_rule_json,
                    "is_required": mapping.is_required,
                }
                for mapping in graph.field_mappings
            ],
        )

    def _validate_graph_payload(
        self,
        graph: FunnelGraphIn,
        *,
        strict_config: bool,
    ) -> FunnelValidationOut:
        errors: list[FunnelValidationIssue] = []
        warnings: list[FunnelValidationIssue] = []
        step_ids = {step.id for step in graph.steps if step.id is not None}

        if not graph.steps:
            errors.append(self._issue("empty_graph", "Добавьте хотя бы один блок.", "error"))
            return FunnelValidationOut(can_publish=False, errors=errors, warnings=warnings)

        triggers = [step for step in graph.steps if step.step_type == "trigger"]
        if not triggers:
            errors.append(
                self._issue("missing_trigger", "В воронке нужен стартовый триггер.", "error")
            )

        for step in graph.steps:
            if step.id is None:
                errors.append(
                    self._issue("missing_step_id", "У каждого блока должен быть UUID.", "error")
                )
                continue
            if not self.registry.is_known(step.step_type, step.block_type):
                errors.append(
                    self._issue(
                        "invalid_block_type",
                        f"Блок {step.block_type} не разрешён для категории {step.step_type}.",
                        "error",
                        step_id=step.id,
                    )
                )
                continue
            if self.registry.is_reserved(step.block_type):
                warnings.append(
                    self._issue(
                        "reserved_block",
                        f"Блок {step.block_type} зарезервирован и runtime v1 его не исполняет.",
                        "warning",
                        step_id=step.id,
                    )
                )
            if strict_config:
                for message in self.registry.validate_block(
                    step.step_type,
                    step.block_type,
                    step.config_json,
                ):
                    errors.append(
                        self._issue(
                            "invalid_block_config",
                            message,
                            "error",
                            step_id=step.id,
                        )
                    )

        adjacency: dict[UUID, list[UUID]] = {step_id: [] for step_id in step_ids}
        for edge in graph.edges:
            if edge.from_step_id not in step_ids:
                errors.append(
                    self._issue(
                        "edge_missing_from",
                        "Связь начинается из несуществующего блока.",
                        "error",
                        edge_id=edge.id,
                    )
                )
            if edge.to_step_id not in step_ids:
                errors.append(
                    self._issue(
                        "edge_missing_to",
                        "Связь ведёт в несуществующий блок.",
                        "error",
                        edge_id=edge.id,
                    )
                )
            if edge.from_step_id in step_ids and edge.to_step_id in step_ids:
                adjacency.setdefault(edge.from_step_id, []).append(edge.to_step_id)

        for step in graph.steps:
            if step.id is None:
                continue
            for target_key, raw_target in self._iter_config_target_values(step.config_json):
                if raw_target in (None, ""):
                    continue
                try:
                    target_id = (
                        raw_target
                        if isinstance(raw_target, UUID)
                        else UUID(str(raw_target))
                    )
                except (TypeError, ValueError):
                    errors.append(
                        self._issue(
                            "invalid_config_target",
                            f"Цель {target_key} должна быть UUID существующего блока.",
                            "error",
                            step_id=step.id,
                        )
                    )
                    continue
                if target_id not in step_ids:
                    errors.append(
                        self._issue(
                            "config_target_missing_step",
                            f"Цель {target_key} ведёт в несуществующий блок.",
                            "error",
                            step_id=step.id,
                        )
                    )
                    continue
                adjacency.setdefault(step.id, []).append(target_id)

        trigger_ids = [step.id for step in triggers if step.id is not None]
        for trigger_id in trigger_ids:
            if not adjacency.get(trigger_id):
                errors.append(
                    self._issue(
                        "trigger_without_edge",
                        "Стартовый блок должен вести к следующему блоку.",
                        "error",
                        step_id=trigger_id,
                    )
                )
        reachable = self._reachable(trigger_ids, adjacency)
        for step in graph.steps:
            if step.id is not None and step.step_type != "trigger" and step.id not in reachable:
                errors.append(
                    self._issue(
                        "orphan_step",
                        f"Блок «{step.title}» недостижим от триггера.",
                        "error",
                        step_id=step.id,
                    )
                )

        finish_reachable = any(
            step.id in reachable and step.step_type == "finish" for step in graph.steps
        )
        if not finish_reachable:
            warnings.append(
                self._issue(
                    "finish_not_reachable",
                    "Нет достижимого завершающего блока. Это допустимо, но сценарий может не завершаться.",
                    "warning",
                )
            )

        for rule in graph.push_rules:
            if rule.step_id not in step_ids:
                errors.append(
                    self._issue(
                        "push_rule_missing_step",
                        "Push rule ссылается на несуществующий блок.",
                        "error",
                    )
                )
            if rule.action_after_send == "move_to_step" and rule.target_step_id not in step_ids:
                errors.append(
                    self._issue(
                        "push_rule_missing_target",
                        "Для push rule с переходом нужен существующий целевой блок.",
                        "error",
                    )
                )

        for mapping in graph.field_mappings:
            if mapping.step_id not in step_ids:
                errors.append(
                    self._issue(
                        "field_mapping_missing_step",
                        "Field mapping ссылается на несуществующий блок.",
                        "error",
                    )
                )
            if mapping.lead_field_key not in LEAD_FIELD_KEYS:
                errors.append(
                    self._issue(
                        "field_mapping_invalid_key",
                        f"Поле лида {mapping.lead_field_key} не поддерживается.",
                        "error",
                        step_id=mapping.step_id,
                    )
                )

        algorithmic_validation = self.graph_validator.validate_graph(
            self._algorithmic_nodes(graph),
            self._algorithmic_edges(graph),
        )
        for message in algorithmic_validation["errors"]:
            if self._duplicates_existing_graph_issue(message, errors):
                continue
            errors.append(
                self._issue(
                    self._algorithmic_issue_code(message),
                    message,
                    "error",
                )
            )
        for message in algorithmic_validation["warnings"]:
            if self._duplicates_existing_graph_issue(message, warnings):
                continue
            warnings.append(
                self._issue(
                    "graph_warning",
                    message,
                    "warning",
                )
            )

        return FunnelValidationOut(
            can_publish=not errors,
            errors=errors,
            warnings=warnings,
        )

    @staticmethod
    def _algorithmic_nodes(graph: FunnelGraphIn) -> list[dict]:
        return [
            {
                "id": str(step.id),
                "title": step.title,
                "step_type": step.step_type,
                "block_type": step.block_type,
                "config_json": step.config_json,
            }
            for step in graph.steps
            if step.id is not None
        ]

    @staticmethod
    def _algorithmic_edges(graph: FunnelGraphIn) -> list[dict]:
        return [
            {
                "id": str(edge.id) if edge.id is not None else None,
                "from_step_id": str(edge.from_step_id),
                "to_step_id": str(edge.to_step_id),
            }
            for edge in graph.edges
        ]

    @staticmethod
    def _algorithmic_issue_code(message: str) -> str:
        normalized = message.lower()
        if "цикл" in normalized:
            return "infinite_loop_without_delay"
        if "тупиков" in normalized:
            return "dead_end_step"
        if "недостижим" in normalized:
            return "unreachable_step"
        return "graph_validation_error"

    @staticmethod
    def _duplicates_existing_graph_issue(
        message: str,
        issues: list[FunnelValidationIssue],
    ) -> bool:
        normalized = message.lower()
        if "недостижим" in normalized and any(issue.code == "orphan_step" for issue in issues):
            return True
        if "старт" in normalized and any(issue.code == "missing_trigger" for issue in issues):
            return True
        return any(issue.message == message for issue in issues)

    @staticmethod
    def _reachable(start_ids: list[UUID], adjacency: dict[UUID, list[UUID]]) -> set[UUID]:
        seen: set[UUID] = set()
        queue = list(start_ids)
        while queue:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            queue.extend(adjacency.get(current, []))
        return seen

    @staticmethod
    def _iter_config_target_values(config: dict) -> list[tuple[str, object]]:
        targets: list[tuple[str, object]] = []

        def add_from_mapping(mapping: object, key: str, label: str) -> None:
            if isinstance(mapping, dict) and mapping.get(key) not in (None, ""):
                targets.append((label, mapping.get(key)))

        def add_from_list(items: object, key: str, label: str) -> None:
            if not isinstance(items, list):
                return
            for index, item in enumerate(items):
                add_from_mapping(item, key, f"{label}[{index}].{key}")

        add_from_mapping(config, "target_step_id", "target_step_id")
        add_from_mapping(config, "timeout_target_step_id", "timeout_target_step_id")
        add_from_mapping(config, "fallback_target_step_id", "fallback_target_step_id")
        add_from_list(config.get("buttons"), "target_step_id", "buttons")
        add_from_list(config.get("choices"), "target_step_id", "choices")
        add_from_list(config.get("outcomes"), "target_step_id", "outcomes")

        messages = config.get("messages")
        if isinstance(messages, list):
            for message_index, message in enumerate(messages):
                if not isinstance(message, dict):
                    continue
                add_from_list(
                    message.get("buttons"),
                    "target_step_id",
                    f"messages[{message_index}].buttons",
                )

        return targets

    @staticmethod
    def _issue(
        code: str,
        message: str,
        severity: str,
        *,
        step_id: Optional[UUID] = None,
        edge_id: Optional[UUID] = None,
    ) -> FunnelValidationIssue:
        return FunnelValidationIssue(
            code=code,
            message=message,
            severity=severity,  # type: ignore[arg-type]
            step_id=step_id,
            edge_id=edge_id,
        )

    @staticmethod
    def _default_trigger_step() -> FunnelStepIn:
        return FunnelStepIn(
            key="start",
            title="Старт",
            step_type="trigger",
            block_type="generic_trigger",
            position_x=80,
            position_y=120,
            config_json={"trigger_type": "new_chat"},
        )

    async def _get_funnel_or_404(self, funnel_id: UUID, project_id: UUID) -> Funnel:
        funnel = await self.repo.get_in_project(funnel_id, project_id)
        if funnel is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Funnel not found",
            )
        return funnel

    async def _get_version_or_404(
        self,
        funnel_id: UUID,
        version_id: UUID,
        project_id: UUID,
    ) -> FunnelVersion:
        version = await self.repo.get_version_in_project(funnel_id, version_id, project_id)
        if version is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Funnel version not found",
            )
        return version

    async def _ensure_bot_in_project(self, bot_id: UUID, project_id: UUID) -> None:
        if not await self.repo.bot_belongs_to_project(bot_id, project_id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Bot does not exist in this project",
            )

    @staticmethod
    def _ensure_read_allowed(current_user: User) -> None:
        if current_user.role_name not in {
            RoleName.SUPER_ADMIN,
            RoleName.ADMIN,
            RoleName.MANAGER,
            RoleName.OPERATOR,
        }:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Funnel builder is not available for this role",
            )

    @staticmethod
    def _ensure_write_allowed(current_user: User) -> None:
        if current_user.role_name not in {
            RoleName.SUPER_ADMIN,
            RoleName.ADMIN,
            RoleName.MANAGER,
        }:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins and managers can edit funnels",
            )

    @staticmethod
    def _ensure_target_project_allowed(current_user: User, target_project_id: UUID) -> None:
        if current_user.role_name == RoleName.SUPER_ADMIN:
            return
        if current_user.project_id != target_project_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Target project is not accessible for current user",
            )
