from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.core.constants import RoleName
from app.repositories.chat_repository import ChatRepository
from app.schemas.telegram import TelegramChat, TelegramMessage, TelegramUser
from app.services.chat_service import ChatService
from app.services.funnel_runtime_service import FunnelRuntimeService
from app.services.lead_confidence_service import (
    ConfidenceContext,
    LeadConfidenceResult,
    LeadConfidenceService,
)
from app.services.telegram_service import TelegramService


class LeadConfidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_confidence_applies_all_required_penalties(self) -> None:
        lead = SimpleNamespace(
            id=uuid4(),
            project_id=uuid4(),
            chat_id=uuid4(),
            phone="phone unavailable",
            name=None,
            country=None,
            has_card=None,
            custom_fields={},
        )
        chat = SimpleNamespace(tracking_link_id=None)
        project = SimpleNamespace(
            use_confidence_score=True,
            confidence_weights=None,
            confidence_thresholds=None,
            vip_tags=[],
        )
        service = LeadConfidenceService.__new__(LeadConfidenceService)
        service._load_context = AsyncMock(return_value=ConfidenceContext(
            lead=lead,
            chat=chat,
            project=project,
            applicable_fields=frozenset({"phone"}),
            minimum_amount=None,
            reask_count=0,
            max_answer_pause_hours=None,
            broadcast_followup=False,
        ))
        service.identity = SimpleNamespace(
            normalize_phone=lambda value: None,
            find_duplicates=AsyncMock(return_value=[SimpleNamespace(id=uuid4())]),
        )

        result = await service.calculate_confidence(lead)

        self.assertEqual(result.score_percent, 15)
        self.assertEqual(result.confidence_level, "low")
        self.assertEqual(
            [reason["code"] for reason in result.reasons],
            ["invalid_phone", "missing_tracking_link", "probable_duplicate"],
        )

    async def test_score_update_persists_metadata_and_queues_eligible_partners(self) -> None:
        lead = SimpleNamespace(
            id=uuid4(),
            project_id=uuid4(),
            score_percent=100,
            confidence_level="high",
            confidence_reasons=[],
            confidence_meta={},
            score_calculated_at=None,
            score_version=1,
            chat_id=uuid4(),
        )
        project = SimpleNamespace(
            use_confidence_score=True,
            confidence_weights=None,
            confidence_thresholds=None,
            vip_tags=[],
        )
        result = LeadConfidenceResult(
            score_percent=80,
            confidence_level="high",
            reasons=[{"code": "missing_tracking_link", "penalty": 20}],
            meta={"score_version": 1},
        )
        service = LeadConfidenceService.__new__(LeadConfidenceService)
        service.db = SimpleNamespace(flush=AsyncMock())
        service._load_context = AsyncMock(
            return_value=ConfidenceContext(
                lead=lead,
                chat=SimpleNamespace(),
                project=project,
                applicable_fields=frozenset(),
                minimum_amount=None,
                reask_count=0,
                max_answer_pause_hours=None,
                broadcast_followup=False,
            )
        )
        service.calculate_confidence = AsyncMock(return_value=result)
        service._route_auto_submit = AsyncMock()

        score = await service.update_lead_score(lead.id)

        self.assertEqual(score, 80)
        self.assertEqual(lead.score_percent, 80)
        self.assertEqual(lead.confidence_level, "high")
        self.assertEqual(lead.confidence_reasons, result.reasons)
        self.assertIsInstance(lead.score_calculated_at, datetime)
        service._route_auto_submit.assert_awaited_once_with(lead, result)


class ChatWorkspaceTests(unittest.IsolatedAsyncioTestCase):
    def test_workspace_filters_are_applied_server_side(self) -> None:
        project_id = uuid4()
        viewer_id = uuid4()
        repo = ChatRepository(AsyncMock())

        unread = repo._apply_filters(
            repo._base_select(project_id),
            only_unread=False,
            only_unanswered=False,
            only_red=False,
            only_hot_lead=False,
            sla_threshold_minutes=30,
            manager_id=None,
            assigned_user_id=None,
            unassigned=False,
            search_query=None,
            tracking_link_id=None,
            date_from=None,
            date_to=None,
            tag_ids=(),
            tag_mode="any",
            lead_statuses=(),
            funnel_state=None,
            workspace_view="unread",
            viewer_id=viewer_id,
        )
        all_visible = repo._apply_filters(
            repo._base_select(project_id),
            only_unread=False,
            only_unanswered=False,
            only_red=False,
            only_hot_lead=False,
            sla_threshold_minutes=30,
            manager_id=None,
            assigned_user_id=None,
            unassigned=False,
            search_query=None,
            tracking_link_id=None,
            date_from=None,
            date_to=None,
            tag_ids=(),
            tag_mode="any",
            lead_statuses=(),
            funnel_state=None,
            workspace_view="all",
            viewer_id=viewer_id,
            hide_assigned_from_all=True,
        )
        favorites = repo._apply_filters(
            repo._base_select(project_id),
            only_unread=False,
            only_unanswered=False,
            only_red=False,
            only_hot_lead=False,
            sla_threshold_minutes=30,
            manager_id=None,
            assigned_user_id=None,
            unassigned=False,
            search_query=None,
            tracking_link_id=None,
            date_from=None,
            date_to=None,
            tag_ids=(),
            tag_mode="any",
            lead_statuses=(),
            funnel_state=None,
            workspace_view="favorites",
            viewer_id=viewer_id,
        )

        unread_sql = str(unread.compile(dialect=postgresql.dialect()))
        all_sql = str(all_visible.compile(dialect=postgresql.dialect()))
        favorites_sql = str(favorites.compile(dialect=postgresql.dialect()))
        self.assertIn("chats.is_read IS false", unread_sql)
        self.assertIn("chats.is_read IS false AND", unread_sql)
        self.assertIn("NOT (EXISTS", unread_sql)
        self.assertIn("leads.manager_id IS NULL", unread_sql)
        self.assertIn("leads.score_percent", unread_sql)
        self.assertIn("NOT (EXISTS", all_sql)
        self.assertIn("leads.manager_id !=", all_sql)
        self.assertIn("chats.is_favorite IS true", favorites_sql)

    async def test_workspace_counts_use_one_aggregate_query(self) -> None:
        row = SimpleNamespace(
            _mapping={"unread": 2, "unanswered": 4, "mine": 3, "all": 5, "favorites": 1}
        )
        result = SimpleNamespace(one=lambda: row)
        db = SimpleNamespace(execute=AsyncMock(return_value=result))
        repo = ChatRepository(db)

        counts = await repo.workspace_counts(
            project_id=uuid4(),
            viewer_id=uuid4(),
            hide_assigned_from_all=True,
        )

        self.assertEqual(
            counts,
            {"unread": 2, "unanswered": 4, "mine": 3, "all": 5, "favorites": 1},
        )
        sql = str(
            db.execute.await_args.args[0].compile(dialect=postgresql.dialect())
        )
        self.assertIn("FILTER (WHERE", sql)
        self.assertIn("LEFT OUTER JOIN leads", sql)
        self.assertEqual(db.execute.await_count, 1)

    async def test_gambling_push_threshold_marks_chat_unread(self) -> None:
        result = SimpleNamespace(rowcount=1)
        db = SimpleNamespace(execute=AsyncMock(return_value=result))
        repo = ChatRepository(db)

        updated = await repo.increment_unanswered_push_count(chat_id=uuid4())

        self.assertTrue(updated)
        statement = db.execute.await_args.args[0]
        sql = str(statement.compile(dialect=postgresql.dialect()))
        self.assertIn("projects.project_format", sql)
        self.assertIn("projects.push_unread_threshold", sql)
        self.assertIn("CASE WHEN", sql)
        self.assertIn("chats.is_read", sql)

    async def test_opening_unassigned_chat_auto_assigns_only_manager(self) -> None:
        project_id = uuid4()
        chat_id = uuid4()
        manager_id = uuid4()
        project = SimpleNamespace(sla_threshold_minutes=30)
        chat = SimpleNamespace(id=chat_id)
        lead = SimpleNamespace(id=uuid4(), manager_id=None)
        output = SimpleNamespace(id=chat_id)
        service = ChatService.__new__(ChatService)
        service.db = AsyncMock()
        service.project_repo = SimpleNamespace(get_active=AsyncMock(return_value=project))
        service.chat_lease = SimpleNamespace(release_expired=AsyncMock(return_value=0))
        service.chat_repo = SimpleNamespace(
            get_active=AsyncMock(side_effect=[chat, chat]),
            latest_messages_for_chats=AsyncMock(return_value={}),
            lead_tags_for_chats=AsyncMock(return_value={}),
            lead_statuses_for_chats=AsyncMock(return_value={}),
            hot_lead_flags_for_chats=AsyncMock(return_value={}),
        )
        service.lead_repo = SimpleNamespace(
            get_existing_by_chat=AsyncMock(return_value=lead)
        )
        service.funnel_repo = SimpleNamespace(
            get_chat_funnel_contexts=AsyncMock(return_value={})
        )
        service._chat_out = MagicMock(return_value=output)
        assignment = SimpleNamespace(assign_manager=AsyncMock())
        actor = SimpleNamespace(id=manager_id, role_name=RoleName.MANAGER)

        with patch(
            "app.services.chat_service.AssignmentService",
            return_value=assignment,
        ):
            result = await service.get_chat(
                chat_id=chat_id,
                project_id=project_id,
                actor=actor,
            )

        self.assertIs(result, output)
        assignment.assign_manager.assert_awaited_once_with(
            lead_id=lead.id,
            project_id=project_id,
            manager_id=manager_id,
            actor_id=manager_id,
        )


class SmartResumeTests(unittest.IsolatedAsyncioTestCase):
    def _service(self, *, step, state, lead):
        service = FunnelRuntimeService.__new__(FunnelRuntimeService)
        service.chat_repo = SimpleNamespace(
            get_active=AsyncMock(return_value=SimpleNamespace()),
            set_assignment_expires_at=AsyncMock(return_value=True),
        )
        service.repo = SimpleNamespace(
            get_lead_by_chat=AsyncMock(return_value=lead),
            get_chat_funnel_state=AsyncMock(return_value=state),
            get_step=AsyncMock(return_value=step),
            cancel_scheduled_jobs_for_chat=AsyncMock(),
            upsert_chat_funnel_state=AsyncMock(),
        )
        service.audit = SimpleNamespace(log=AsyncMock())
        service.chat_audit = SimpleNamespace(log_event=AsyncMock())
        service.scoring = SimpleNamespace(update_lead_score=AsyncMock())
        service._execute_from_step = AsyncMock()
        service._move_from_step = AsyncMock()
        service._mark_completed = AsyncMock()
        return service

    async def test_move_to_selected_step_clears_waiting_and_executes_step(self) -> None:
        version_id = uuid4()
        step = SimpleNamespace(
            id=uuid4(),
            funnel_version_id=version_id,
            step_type="message",
            title="Повторить вопрос",
        )
        state = SimpleNamespace(
            funnel_id=uuid4(),
            funnel_version_id=version_id,
            current_step_id=uuid4(),
            completed_at=None,
            is_paused=True,
            runtime_json={"stale": True},
        )
        actor = SimpleNamespace(id=uuid4(), role_name=RoleName.ADMIN)
        service = self._service(step=step, state=state, lead=SimpleNamespace(id=uuid4()))

        resumed = await service.resume_funnel_from_manager(
            chat_id=uuid4(),
            project_id=uuid4(),
            actor=actor,
            target_step_id=step.id,
            manager_approved=False,
        )

        self.assertTrue(resumed)
        upsert = service.repo.upsert_chat_funnel_state.await_args.kwargs
        self.assertFalse(upsert["waiting_for_answer"])
        self.assertFalse(upsert["is_paused"])
        self.assertEqual(upsert["runtime_json"], {})
        service._execute_from_step.assert_awaited_once_with(
            chat_id=upsert["chat_id"],
            step=step,
        )

    async def test_manager_approval_moves_through_default_branch(self) -> None:
        version_id = uuid4()
        current_step = SimpleNamespace(
            id=uuid4(),
            funnel_version_id=version_id,
            step_type="question",
            title="Проверка",
        )
        next_step = SimpleNamespace(id=uuid4())
        state = SimpleNamespace(
            funnel_id=uuid4(),
            funnel_version_id=version_id,
            current_step_id=current_step.id,
            completed_at=None,
            is_paused=True,
            runtime_json={"answer": "manager-approved"},
        )
        actor = SimpleNamespace(id=uuid4(), role_name=RoleName.ADMIN)
        lead = SimpleNamespace(id=uuid4(), manager_id=uuid4())
        service = self._service(
            step=current_step,
            state=state,
            lead=lead,
        )
        service.db = AsyncMock()
        service._move_from_step.return_value = next_step
        chat_id = uuid4()
        assignment_expires_at = datetime.now(timezone.utc)
        lease = SimpleNamespace(
            assignment_deadline=AsyncMock(return_value=assignment_expires_at),
        )

        project_id = uuid4()
        with patch(
            "app.services.chat_lease_service.ChatLeaseService",
            return_value=lease,
        ):
            resumed = await service.resume_funnel_from_manager(
                chat_id=chat_id,
                project_id=project_id,
                actor=actor,
                target_step_id=None,
                manager_approved=True,
            )

        self.assertTrue(resumed)
        service._move_from_step.assert_awaited_once_with(
            chat_id=chat_id,
            step=current_step,
            answer=None,
        )
        service._execute_from_step.assert_awaited_once_with(
            chat_id=chat_id,
            step=next_step,
        )
        service.chat_repo.set_assignment_expires_at.assert_awaited_once_with(
            chat_id=chat_id,
            project_id=project_id,
            assignment_expires_at=assignment_expires_at,
        )


class RepeatedStartTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_chat_records_start_without_starting_funnel(self) -> None:
        project_id = uuid4()
        bot_id = uuid4()
        chat_id = uuid4()
        message_id = uuid4()
        message = TelegramMessage(
            message_id=10,
            chat=TelegramChat(id=42),
            from_user=TelegramUser(id=42, first_name="Анна"),
            text="/start campaign",
        )
        service = TelegramService.__new__(TelegramService)
        service._hydrate_start_payload = AsyncMock(
            return_value=SimpleNamespace(utm_key=None, utm_data=None)
        )
        service._resolve_tracking_link_id = AsyncMock(return_value=None)
        service._find_or_create_chat = AsyncMock(
            return_value=(
                SimpleNamespace(
                    id=chat_id,
                    external_chat_id="42",
                    is_blocked=False,
                ),
                False,
                False,
            )
        )
        persisted = SimpleNamespace(funnel_processed_at=None)
        service.message_repo = SimpleNamespace(
            get_by_id=AsyncMock(return_value=persisted),
            claim_funnel_processing=AsyncMock(return_value=True),
        )
        service._create_message = AsyncMock(
            return_value=SimpleNamespace(id=message_id, external_message_id="10")
        )
        service._find_or_create_lead = AsyncMock(
            return_value=SimpleNamespace(id=uuid4())
        )
        service._save_shared_contact = AsyncMock(return_value=False)
        service._attach_utm_bridge_data = AsyncMock()
        service.chat_repo = SimpleNamespace(mark_bot_restarted=AsyncMock(return_value=True))
        service.chat_audit = SimpleNamespace(log_event=AsyncMock())
        service._enqueue_facebook_event_safely = AsyncMock()
        service._process_runtime_or_legacy = AsyncMock()
        update = SimpleNamespace(
            update_id=1,
            message=message,
            callback_query=None,
            my_chat_member=None,
        )

        with (
            patch(
                "app.services.telegram_service.enqueue_funnel_start",
                new=AsyncMock(),
            ) as enqueue_start,
            patch(
                "app.services.telegram_service.enqueue_user_input",
                new=AsyncMock(),
            ) as enqueue_input,
        ):
            await service.handle_update(
                update=update,
                project_id=project_id,
                bot_id=bot_id,
            )

        service.chat_repo.mark_bot_restarted.assert_awaited_once_with(
            chat_id=chat_id,
            project_id=project_id,
        )
        service.message_repo.claim_funnel_processing.assert_awaited_once_with(
            [message_id]
        )
        enqueue_start.assert_not_awaited()
        enqueue_input.assert_not_awaited()
        service._process_runtime_or_legacy.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
