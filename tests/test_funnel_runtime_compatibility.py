from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.core.constants import MessageType
from app.core.config import settings
from app.api.telegram_contact import telegram_contact_request
from app.models.message import Message
from app.repositories.funnel_repository import FunnelRepository
from app.schemas.telegram import (
    TelegramCallbackQuery,
    TelegramChat,
    TelegramContact,
    TelegramMessage,
    TelegramUser,
)
from app.services.funnel_runtime_service import FunnelRuntimeService
from app.services.funnel_start_recovery_service import (
    FunnelStartRecoveryService,
    START_COMMAND_RE,
)
from app.services.funnel_start_queue import FunnelStartEnqueueResult
from app.services.telegram_service import TelegramService


class _TemplateRepository:
    async def get_message_template_context(self, chat_id):
        return {
            "external_user_id": "42",
            "contact_name": "Fallback Name",
            "name": "Анна Иванова",
            "phone": "+79990001122",
            "username": "anna",
            "age": 30,
            "country": "RU",
            "call_time_text": "18:00",
            "lead_status": "qualified",
            "project": "Project A",
            "bot": "Sales Bot",
            "custom_fields": {"field_name": "custom value"},
        }

    async def get_chat_funnel_state(self, chat_id):
        return SimpleNamespace(runtime_json={"last_answer": "yes"})


class FunnelRuntimeCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.service = FunnelRuntimeService.__new__(FunnelRuntimeService)
        self.original_base_url = settings.BASE_URL
        settings.BASE_URL = "https://crm.example.com"

    def tearDown(self) -> None:
        settings.BASE_URL = self.original_base_url

    def test_contact_button_is_telegram_contact_request(self) -> None:
        step = SimpleNamespace(id=uuid4())
        variants = [
            {"label": "Поделиться номером", "value": "contact", "type": "contact"},
            {"label": "Поделиться номером", "value": "contact", "type": "branch"},
            {"label": "Поделиться номером", "request_contact": True},
            {"label": "Поделиться номером", "type": "request_contact"},
        ]

        for raw in variants:
            with self.subTest(raw=raw):
                buttons = self.service._normalize_buttons([raw])
                self.assertEqual(buttons[0]["type"], "contact")
                markup = self.service._reply_markup_for_buttons(step=step, buttons=buttons)
                self.assertNotIn("keyboard", markup)
                web_app = markup["inline_keyboard"][0][0]["web_app"]
                self.assertEqual(
                    web_app["url"],
                    "https://crm.example.com/telegram/contact-request",
                )

    def test_legacy_message_config_keeps_contact_request(self) -> None:
        step = SimpleNamespace(
            id=uuid4(),
            step_type="message",
            block_type="generic_message",
            config_json={
                "text": "Поделитесь номером",
                "buttons": [
                    {
                        "label": "Отправить номер",
                        "value": "contact",
                        "type": "branch",
                    }
                ],
            },
        )
        sequence = self.service._message_sequence(step)
        buttons = self.service._buttons_from_message_item(sequence[0])
        markup = self.service._reply_markup_for_buttons(step=step, buttons=buttons)
        self.assertIn("web_app", markup["inline_keyboard"][0][0])

    def test_contact_and_callback_buttons_can_share_one_message(self) -> None:
        step = SimpleNamespace(id=uuid4())
        target_step_id = uuid4()
        buttons = self.service._normalize_buttons(
            [
                {
                    "label": "Отправить номер",
                    "type": "contact",
                    "target_step_id": str(target_step_id),
                },
                {"label": "Позже", "value": "later", "type": "branch"},
            ]
        )
        self.assertEqual(buttons[0]["target_step_id"], str(target_step_id))
        markup = self.service._reply_markup_for_buttons(step=step, buttons=buttons)
        self.assertIn("web_app", markup["inline_keyboard"][0][0])
        self.assertIn("callback_data", markup["inline_keyboard"][1][0])

    def test_native_contact_uses_one_time_reply_keyboard(self) -> None:
        step = SimpleNamespace(id=uuid4())
        buttons = self.service._normalize_buttons(
            [
                {
                    "label": "Отправить номер",
                    "type": "contact",
                    "contact_mode": "native",
                }
            ]
        )

        markup = self.service._reply_markup_for_buttons(
            step=step,
            buttons=buttons,
            button_mode="reply",
        )

        self.assertTrue(markup["keyboard"][0][0]["request_contact"])
        self.assertTrue(markup["one_time_keyboard"])
        self.assertNotIn("inline_keyboard", markup)

    async def test_reply_button_text_uses_configured_message_target(self) -> None:
        step_id = uuid4()
        target_step_id = uuid4()
        step = SimpleNamespace(
            id=step_id,
            step_type="message",
            block_type="generic_message",
            config_json={
                "messages": [
                    {
                        "id": "message_1",
                        "text": "Выберите вариант",
                        "button_mode": "reply",
                        "buttons": [
                            {
                                "id": "yes",
                                "label": "Да",
                                "value": "yes",
                                "type": "branch",
                                "target_step_id": str(target_step_id),
                            }
                        ],
                    }
                ]
            },
        )
        state = SimpleNamespace(
            funnel_id=uuid4(),
            funnel_version_id=uuid4(),
            current_step_id=step_id,
            entered_step_at=None,
            waiting_for_answer=True,
            is_paused=False,
            completed_at=None,
            runtime_json={"message_sequence": {"step_id": str(step_id), "message_index": 0}},
        )
        self.service.repo = SimpleNamespace(
            get_chat_funnel_state=AsyncMock(return_value=state),
            get_step=AsyncMock(return_value=step),
            upsert_chat_funnel_state=AsyncMock(),
        )
        self.service.apply_field_mappings = AsyncMock()
        self.service._log_step_event = AsyncMock()
        next_step = SimpleNamespace(id=target_step_id)
        self.service._move_to_step_id = AsyncMock(return_value=next_step)
        self.service._execute_from_step = AsyncMock()

        chat_id = uuid4()
        handled = await self.service.process_incoming_message(
            chat_id=chat_id,
            text="Да",
            message_type=MessageType.TEXT,
        )

        self.assertTrue(handled)
        self.service._move_to_step_id.assert_awaited_once_with(
            chat_id=chat_id,
            target_step_id=str(target_step_id),
            from_step=step,
        )
        self.service._execute_from_step.assert_awaited_once()

    def test_expected_start_amount_has_own_field_without_changing_legacy_budget(self) -> None:
        expected_step = SimpleNamespace(
            block_type="ask_expected_start_amount",
            config_json={},
        )
        legacy_step = SimpleNamespace(block_type="ask_budget", config_json={})

        self.assertEqual(
            self.service._input_target_field(expected_step),
            "expected_start_amount",
        )
        self.assertEqual(self.service._input_target_field(legacy_step), "budget")

    async def test_contact_uses_its_target_even_with_callback_button(self) -> None:
        step_id = uuid4()
        target_step_id = uuid4()
        step = SimpleNamespace(
            id=step_id,
            step_type="message",
            block_type="generic_message",
            config_json={
                "messages": [
                    {
                        "id": "message_1",
                        "text": "Выберите вариант",
                        "buttons": [
                            {
                                "id": "answer",
                                "label": "Ответ",
                                "value": "answer",
                                "type": "branch",
                            },
                            {
                                "id": "contact",
                                "label": "Отправить номер",
                                "value": "contact",
                                "type": "contact",
                                "target_step_id": str(target_step_id),
                            },
                        ],
                    }
                ]
            },
        )
        state = SimpleNamespace(
            funnel_id=uuid4(),
            funnel_version_id=uuid4(),
            current_step_id=step_id,
            entered_step_at=None,
            waiting_for_answer=True,
            is_paused=False,
            completed_at=None,
            runtime_json={"message_sequence": {"step_id": str(step_id), "message_index": 0}},
        )
        self.service.repo = SimpleNamespace(
            get_chat_funnel_state=AsyncMock(return_value=state),
            get_step=AsyncMock(return_value=step),
            upsert_chat_funnel_state=AsyncMock(),
        )
        self.service.apply_field_mappings = AsyncMock()
        self.service._log_step_event = AsyncMock()
        next_step = SimpleNamespace(id=target_step_id)
        self.service._move_to_step_id = AsyncMock(return_value=next_step)
        self.service._execute_from_step = AsyncMock()

        handled = await self.service.process_incoming_message(
            chat_id=uuid4(),
            text="+79990001122",
            message_type=MessageType.CONTACT,
        )

        self.assertTrue(handled)
        self.service._move_to_step_id.assert_awaited_once()
        self.assertEqual(
            self.service._move_to_step_id.await_args.kwargs["target_step_id"],
            str(target_step_id),
        )
        self.service._execute_from_step.assert_awaited_once()

    def test_incoming_telegram_contact_becomes_phone_message(self) -> None:
        message = TelegramMessage(
            message_id=100,
            chat=TelegramChat(id=42),
            from_user=TelegramUser(id=42, first_name="Анна"),
            contact=TelegramContact(
                phone_number="+79990001122",
                first_name="Анна",
                user_id=42,
            ),
        )
        created = TelegramService._telegram_message_to_create(message)
        self.assertEqual(created.message_type, MessageType.CONTACT)
        self.assertEqual(created.body, "+79990001122")

    async def test_shared_contact_is_saved_to_lead_and_committed_immediately(self) -> None:
        telegram_service = TelegramService.__new__(TelegramService)
        telegram_service.lead_repo = SimpleNamespace(update_contact=AsyncMock())
        telegram_service.db = SimpleNamespace(commit=AsyncMock())
        project_id = uuid4()
        lead = SimpleNamespace(id=uuid4(), name="Старое имя")
        message = TelegramMessage(
            message_id=101,
            chat=TelegramChat(id=42),
            from_user=TelegramUser(id=42, first_name="Анна"),
            contact=TelegramContact(
                phone_number="+79990001122",
                first_name="Анна",
                last_name="Иванова",
                user_id=42,
            ),
        )

        saved = await telegram_service._save_shared_contact(
            lead=lead,
            project_id=project_id,
            message=message,
        )

        self.assertTrue(saved)
        telegram_service.lead_repo.update_contact.assert_awaited_once_with(
            lead.id,
            project_id,
            phone="+79990001122",
            name="Анна Иванова",
        )
        telegram_service.db.commit.assert_awaited_once()

    async def test_contact_web_app_button_is_removed_after_contact(self) -> None:
        telegram_service = TelegramService.__new__(TelegramService)
        outgoing = SimpleNamespace(
            external_message_id="77",
            raw_payload_json={
                "reply_markup": {
                    "inline_keyboard": [
                        [
                            {
                                "text": "Отправить номер",
                                "web_app": {
                                    "url": "https://crm.example.com/telegram/contact-request"
                                },
                            }
                        ]
                    ]
                }
            },
        )
        telegram_service.message_repo = SimpleNamespace(
            list_recent_outgoing_with_buttons=AsyncMock(return_value=[outgoing])
        )
        telegram_service.telegram_sender = SimpleNamespace(
            edit_message_reply_markup=AsyncMock(return_value=True)
        )
        chat = SimpleNamespace(id=uuid4(), external_chat_id="42")
        project_id = uuid4()
        bot_id = uuid4()

        await telegram_service._clear_latest_contact_button(
            chat_id=chat.id,
            external_chat_id=chat.external_chat_id,
            project_id=project_id,
            bot_id=bot_id,
        )

        telegram_service.telegram_sender.edit_message_reply_markup.assert_awaited_once_with(
            project_id,
            bot_id,
            "42",
            77,
        )

    async def test_contact_web_app_calls_native_contact_request(self) -> None:
        response = await telegram_contact_request()
        body = response.body.decode("utf-8")
        self.assertIn("app.requestContact", body)
        self.assertIn("app.close()", body)

    def test_sent_message_buttons_are_exposed_for_crm(self) -> None:
        message = Message(
            raw_payload_json={
                "reply_markup": {
                    "inline_keyboard": [
                        [{"text": "Ответ", "callback_data": "answer"}],
                        [
                            {
                                "text": "Отправить номер",
                                "web_app": {"url": "https://crm.example.com"},
                            }
                        ],
                    ]
                }
            }
        )
        self.assertEqual(message.buttons, ["Ответ", "Отправить номер"])

    async def test_funnel_trace_can_be_limited_to_current_chat_cycle(self) -> None:
        result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
        db = SimpleNamespace(execute=AsyncMock(return_value=result))
        since = datetime(2026, 7, 3, 10, 0, tzinfo=timezone.utc)

        await FunnelRepository(db).list_runtime_logs_by_chat(
            chat_id=uuid4(),
            since=since,
        )

        statement = db.execute.await_args.args[0]
        self.assertIn("funnel_runtime_logs.created_at >=", str(statement))

    def test_repeated_callback_has_stable_external_message_id(self) -> None:
        message = TelegramMessage(message_id=77, chat=TelegramChat(id=42), text="source")
        first = TelegramCallbackQuery(id="first", data="fr:step:0", message=message)
        repeated = TelegramCallbackQuery(id="second", data="fr:step:0", message=message)
        different = TelegramCallbackQuery(id="third", data="fr:step:1", message=message)
        first_id = TelegramService._callback_message_external_id(first)
        self.assertEqual(first_id, TelegramService._callback_message_external_id(repeated))
        self.assertNotEqual(first_id, TelegramService._callback_message_external_id(different))

    async def test_concurrent_funnel_start_is_idempotent_after_chat_lock(self) -> None:
        chat_id = uuid4()
        current_step = SimpleNamespace(id=uuid4())
        active_state = SimpleNamespace(
            completed_at=None,
            current_step_id=current_step.id,
            funnel_id=uuid4(),
            funnel_version_id=uuid4(),
        )
        self.service.repo = SimpleNamespace(
            lock_chat_for_runtime=AsyncMock(return_value=True),
            get_chat_funnel_state=AsyncMock(return_value=active_state),
            get_step=AsyncMock(return_value=current_step),
            list_steps=AsyncMock(),
        )

        result = await self.service.start_funnel_for_chat(
            chat_id=chat_id,
            funnel_id=uuid4(),
            funnel_version_id=uuid4(),
        )

        self.assertIs(result, current_step)
        self.service.repo.lock_chat_for_runtime.assert_awaited_once_with(chat_id)
        self.service.repo.list_steps.assert_not_awaited()

    async def test_fresh_lifecycle_does_not_restart_current_cycle(self) -> None:
        chat_id = uuid4()
        cycle_started_at = datetime.now(timezone.utc)
        chat = SimpleNamespace(
            id=chat_id,
            bot_id=uuid4(),
            current_cycle_started_at=cycle_started_at,
        )
        current_state = SimpleNamespace(completed_at=None)
        telegram_service = TelegramService.__new__(TelegramService)
        telegram_service.funnel_runtime = SimpleNamespace(
            lock_chat_for_runtime=AsyncMock(return_value=True),
            get_state_status=AsyncMock(return_value=("waiting_for_answer", current_state)),
            reset_chat_state=AsyncMock(),
            start_funnel_for_chat=AsyncMock(),
        )
        telegram_service.bot_repo = SimpleNamespace(reset_chat_state=AsyncMock())
        telegram_service._tracking_target_step_key = AsyncMock(return_value=None)

        await telegram_service._run_active_funnel_runtime(
            chat=chat,
            active_funnel_id=uuid4(),
            active_funnel_version_id=uuid4(),
            user_message=SimpleNamespace(body="/start", caption=None, message_type="text"),
            start_requested=True,
            fresh_lifecycle=True,
        )

        telegram_service.funnel_runtime.reset_chat_state.assert_not_awaited()
        telegram_service.funnel_runtime.start_funnel_for_chat.assert_not_awaited()

    async def test_fresh_lifecycle_restarts_completed_previous_cycle(self) -> None:
        chat_id = uuid4()
        cycle_started_at = datetime.now(timezone.utc)
        chat = SimpleNamespace(
            id=chat_id,
            bot_id=uuid4(),
            current_cycle_started_at=cycle_started_at,
        )
        previous_state = SimpleNamespace(
            completed_at=cycle_started_at - timedelta(minutes=1),
        )
        telegram_service = TelegramService.__new__(TelegramService)
        telegram_service.funnel_runtime = SimpleNamespace(
            lock_chat_for_runtime=AsyncMock(return_value=True),
            get_state_status=AsyncMock(return_value=("completed", previous_state)),
            reset_chat_state=AsyncMock(),
            start_funnel_for_chat=AsyncMock(),
        )
        telegram_service.bot_repo = SimpleNamespace(reset_chat_state=AsyncMock())
        telegram_service._tracking_target_step_key = AsyncMock(return_value=None)
        active_funnel_id = uuid4()
        active_version_id = uuid4()

        await telegram_service._run_active_funnel_runtime(
            chat=chat,
            active_funnel_id=active_funnel_id,
            active_funnel_version_id=active_version_id,
            user_message=SimpleNamespace(body="/start", caption=None, message_type="text"),
            start_requested=True,
            fresh_lifecycle=True,
        )

        telegram_service.funnel_runtime.reset_chat_state.assert_awaited_once_with(chat_id)
        telegram_service.funnel_runtime.start_funnel_for_chat.assert_awaited_once_with(
            chat_id=chat_id,
            funnel_id=active_funnel_id,
            funnel_version_id=active_version_id,
            start_step_key=None,
        )

    def test_funnel_start_recovery_only_accepts_real_start_commands(self) -> None:
        self.assertIsNotNone(START_COMMAND_RE.match("/start"))
        self.assertIsNotNone(START_COMMAND_RE.match(" /start@crm_bot ref-code"))
        self.assertIsNone(START_COMMAND_RE.match("/starter"))
        self.assertIsNone(START_COMMAND_RE.match("text /start"))

    def test_funnel_start_recovery_detects_reactivated_chat_cycle(self) -> None:
        completed_at = datetime(2026, 7, 13, 7, 0, tzinfo=timezone.utc)
        cycle_started_at = completed_at + timedelta(minutes=5)
        self.assertTrue(
            FunnelStartRecoveryService._starts_new_cycle(
                message_created_at=cycle_started_at + timedelta(milliseconds=100),
                cycle_started_at=cycle_started_at,
                state_completed_at=completed_at,
            )
        )
        self.assertFalse(
            FunnelStartRecoveryService._starts_new_cycle(
                message_created_at=cycle_started_at,
                cycle_started_at=completed_at - timedelta(minutes=5),
                state_completed_at=completed_at,
            )
        )

    async def test_start_queue_does_not_read_expired_chat_fields_after_commit(self) -> None:
        chat_id = uuid4()
        message_id = uuid4()
        bot_id = uuid4()
        project_id = uuid4()

        class ExpiringChat:
            id = chat_id
            external_chat_id = "42"
            is_blocked = False

            @property
            def current_cycle_started_at(self):
                raise AssertionError("expired ORM field was accessed")

            @property
            def created_at(self):
                raise AssertionError("expired ORM field was accessed")

        telegram_service = TelegramService.__new__(TelegramService)
        telegram_service.db = SimpleNamespace(commit=AsyncMock())
        telegram_service.message_repo = SimpleNamespace(
            get_by_id=AsyncMock(return_value=SimpleNamespace(funnel_processed_at=None)),
        )
        telegram_service._hydrate_start_payload = AsyncMock(
            return_value=SimpleNamespace(
                tracking_link_id=None,
                ref_code=None,
                utm_key=None,
                utm_data=None,
            )
        )
        telegram_service._resolve_tracking_link_id = AsyncMock(return_value=None)
        telegram_service._find_or_create_chat = AsyncMock(
            return_value=(ExpiringChat(), True, False)
        )
        telegram_service._create_message = AsyncMock(
            return_value=SimpleNamespace(id=message_id, external_message_id="100")
        )
        telegram_service._find_or_create_lead = AsyncMock(
            return_value=SimpleNamespace(id=uuid4())
        )
        telegram_service._save_shared_contact = AsyncMock(return_value=False)
        telegram_service._attach_utm_bridge_data = AsyncMock()
        telegram_service._enqueue_facebook_event_safely = AsyncMock()
        update = SimpleNamespace(
            my_chat_member=None,
            callback_query=None,
            update_id=1,
            message=TelegramMessage(
                message_id=100,
                chat=TelegramChat(id=42),
                from_user=TelegramUser(id=42, first_name="Анна"),
                text="/start",
            ),
        )

        with patch(
            "app.services.telegram_service.enqueue_funnel_start",
            new=AsyncMock(return_value=True),
        ) as enqueue_mock:
            await telegram_service.handle_update(
                update=update,
                project_id=project_id,
                bot_id=bot_id,
            )

        enqueue_mock.assert_awaited_once_with(
            chat_id,
            message_id,
            fresh_lifecycle=True,
        )

    async def test_debounced_input_recovers_pending_start_before_user_reply(self) -> None:
        now = datetime.now(timezone.utc)
        chat_id = uuid4()
        bot_id = uuid4()
        project_id = uuid4()
        chat = SimpleNamespace(
            id=chat_id,
            bot_id=bot_id,
            project_id=project_id,
            is_deleted=False,
            reset_at=None,
            is_blocked=False,
        )

        def incoming_message(body: str, created_at: datetime) -> SimpleNamespace:
            return SimpleNamespace(
                id=uuid4(),
                chat_id=chat_id,
                external_message_id=str(uuid4()),
                message_type="text",
                sender_type="user",
                sender_id=None,
                operator_id=None,
                body=body,
                translated_text=None,
                original_text=None,
                caption=None,
                telegram_file_id=None,
                file_unique_id=None,
                file_name=None,
                mime_type=None,
                file_size=None,
                media_group_id=None,
                buttons=[],
                created_at=created_at,
            )

        start_message = incoming_message("/start campaign", now - timedelta(seconds=10))
        reply_message = incoming_message("Анна, Москва", now - timedelta(seconds=5))
        telegram_service = TelegramService.__new__(TelegramService)
        telegram_service.chat_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=chat))
        telegram_service.message_repo = SimpleNamespace(
            get_latest_user_message=AsyncMock(return_value=reply_message),
            list_unprocessed_user_input_batch=AsyncMock(
                return_value=[start_message, reply_message]
            ),
            claim_funnel_processing=AsyncMock(return_value=True),
        )
        telegram_service._process_runtime_or_legacy = AsyncMock()

        result = await telegram_service.process_debounced_user_input(
            chat_id=chat_id,
            trigger_message_id=reply_message.id,
        )

        self.assertEqual(result, "processed")
        self.assertEqual(telegram_service._process_runtime_or_legacy.await_count, 2)
        start_call, reply_call = telegram_service._process_runtime_or_legacy.await_args_list
        self.assertTrue(start_call.kwargs["start_requested"])
        self.assertTrue(start_call.kwargs["fresh_lifecycle"])
        self.assertEqual(start_call.kwargs["user_message"].body, "/start campaign")
        self.assertFalse(reply_call.kwargs["start_requested"])
        self.assertEqual(reply_call.kwargs["user_message"].body, "Анна, Москва")

    async def test_recovery_queues_only_missing_or_reactivated_starts(self) -> None:
        now = datetime.now(timezone.utc)
        missing = SimpleNamespace(
            message_id=uuid4(),
            chat_id=uuid4(),
            body="/start ref-code",
            message_created_at=now,
            current_cycle_started_at=now,
            state_id=None,
            state_completed_at=None,
        )
        active = SimpleNamespace(
            message_id=uuid4(),
            chat_id=uuid4(),
            body="/start",
            message_created_at=now,
            current_cycle_started_at=now,
            state_id=uuid4(),
            state_completed_at=None,
        )
        previous_completion = now - timedelta(minutes=10)
        reactivated = SimpleNamespace(
            message_id=uuid4(),
            chat_id=uuid4(),
            body="/start next-cycle",
            message_created_at=now,
            current_cycle_started_at=now - timedelta(milliseconds=100),
            state_id=uuid4(),
            state_completed_at=previous_completion,
        )
        rows = SimpleNamespace(all=lambda: [missing, active, reactivated])
        db = SimpleNamespace(execute=AsyncMock(side_effect=[rows, SimpleNamespace()]))
        service = FunnelStartRecoveryService(db)

        with patch(
            "app.services.funnel_start_recovery_service.enqueue_funnel_starts",
            new=AsyncMock(
                return_value=FunnelStartEnqueueResult(
                    requested=2,
                    enqueued=2,
                    already_enqueued=0,
                    failed=0,
                )
            ),
        ) as enqueue_mock:
            result = await service.recover(
                lookback_hours=24,
                limit=100,
                job_scope="test-run",
            )

        requests = enqueue_mock.await_args.args[0]
        self.assertEqual([item.message_id for item in requests], [missing.message_id, reactivated.message_id])
        self.assertEqual([item.fresh_lifecycle for item in requests], [False, True])
        self.assertEqual(result.scheduled, 2)
        self.assertEqual(result.already_running, 1)
        self.assertEqual(result.fresh_lifecycles, 1)

    async def test_current_and_legacy_template_variables_are_preserved(self) -> None:
        self.service.repo = _TemplateRepository()
        rendered = await self.service._render_text_template(
            uuid4(),
            "{{first_name}}|{{username}}|{{phone}}|{{lead_status}}|{{project}}|"
            "{{bot}}|{{custom.field_name}}|{{field_name}}|{{custom.missing}}",
        )
        self.assertEqual(
            rendered,
            "Анна|anna|+79990001122|qualified|Project A|Sales Bot|"
            "custom value|custom value|",
        )

    def test_legacy_message_keeps_chat_action_disabled(self) -> None:
        step = SimpleNamespace(
            step_type="message",
            block_type="generic_message",
            config_json={"text": "Старое сообщение", "delay_seconds": 2},
        )

        message = self.service._message_sequence(step)[0]

        self.assertFalse(message["chat_action_enabled"])
        self.assertEqual(
            self.service._message_chat_action_duration_seconds(message),
            0,
        )

    def test_chat_action_matches_actual_message_type(self) -> None:
        step = SimpleNamespace(block_type="generic_message")
        cases = [
            ({"type": "text", "text": "Привет"}, "typing"),
            (
                {
                    "type": "voice",
                    "media": {"telegram_file_id": "voice-file-id"},
                },
                "record_voice",
            ),
            (
                {
                    "type": "video_note",
                    "media": {"telegram_file_id": "circle-file-id"},
                },
                "record_video_note",
            ),
        ]

        for item, expected in cases:
            with self.subTest(message_type=item["type"]):
                self.assertEqual(self.service._message_chat_action(step, item), expected)

    async def test_url_button_can_continue_message_sequence_when_enabled(self) -> None:
        chat_id = uuid4()
        step = SimpleNamespace(
            id=uuid4(),
            step_type="message",
            block_type="generic_message",
            config_json={
                "messages": [
                    {
                        "id": "message_1",
                        "type": "text",
                        "text": "Откройте ссылку",
                        "continue_after_buttons": True,
                        "buttons": [
                            {
                                "id": "site",
                                "label": "Открыть",
                                "type": "url",
                                "url": "https://example.com",
                            }
                        ],
                    }
                ]
            },
        )
        next_step = SimpleNamespace(id=uuid4())
        self.service._send_message_item = AsyncMock(return_value=True)
        self.service._move_from_step = AsyncMock(return_value=next_step)

        result = await self.service._execute_message_sequence(chat_id=chat_id, step=step)

        self.assertIs(result, next_step)
        self.service._move_from_step.assert_awaited_once_with(
            chat_id=chat_id,
            step=step,
            answer=None,
        )

    async def test_existing_url_button_without_flag_keeps_waiting(self) -> None:
        chat_id = uuid4()
        step = SimpleNamespace(
            id=uuid4(),
            step_type="message",
            block_type="generic_message",
            config_json={
                "messages": [
                    {
                        "id": "message_1",
                        "type": "text",
                        "text": "Откройте ссылку",
                        "buttons": [
                            {
                                "id": "site",
                                "label": "Открыть",
                                "type": "url",
                                "url": "https://example.com",
                            }
                        ],
                    }
                ]
            },
        )
        state = SimpleNamespace(
            funnel_id=uuid4(),
            funnel_version_id=uuid4(),
            entered_step_at=None,
            runtime_json={},
        )
        self.service.repo = SimpleNamespace(
            get_chat_funnel_state=AsyncMock(return_value=state),
            upsert_chat_funnel_state=AsyncMock(),
        )
        self.service._send_message_item = AsyncMock(return_value=True)
        self.service._move_from_step = AsyncMock()

        result = await self.service._execute_message_sequence(chat_id=chat_id, step=step)

        self.assertIs(result, step)
        self.service._move_from_step.assert_not_awaited()
        self.service.repo.upsert_chat_funnel_state.assert_awaited_once()

    async def test_branch_button_still_waits_when_continue_flag_is_present(self) -> None:
        chat_id = uuid4()
        step = SimpleNamespace(
            id=uuid4(),
            step_type="message",
            block_type="generic_message",
            config_json={
                "messages": [
                    {
                        "id": "message_1",
                        "type": "text",
                        "text": "Выберите вариант",
                        "continue_after_buttons": True,
                        "buttons": [
                            {
                                "id": "yes",
                                "label": "Да",
                                "type": "branch",
                                "value": "yes",
                            }
                        ],
                    }
                ]
            },
        )
        state = SimpleNamespace(
            funnel_id=uuid4(),
            funnel_version_id=uuid4(),
            entered_step_at=None,
            runtime_json={},
        )
        self.service.repo = SimpleNamespace(
            get_chat_funnel_state=AsyncMock(return_value=state),
            upsert_chat_funnel_state=AsyncMock(),
        )
        self.service._send_message_item = AsyncMock(return_value=True)
        self.service._move_from_step = AsyncMock()

        result = await self.service._execute_message_sequence(chat_id=chat_id, step=step)

        self.assertIs(result, step)
        self.service._move_from_step.assert_not_awaited()
        self.service.repo.upsert_chat_funnel_state.assert_awaited_once()

    async def test_enabled_chat_action_delays_only_its_message(self) -> None:
        chat_id = uuid4()
        step = SimpleNamespace(
            id=uuid4(),
            step_type="message",
            block_type="generic_message",
            config_json={
                "messages": [
                    {
                        "id": "message_1",
                        "type": "text",
                        "text": "Привет",
                        "delay_seconds": 0,
                        "chat_action_enabled": True,
                        "chat_action_duration_seconds": 7,
                    }
                ]
            },
        )
        scheduled_job_id = uuid4()
        self.service._schedule_job = AsyncMock(return_value=scheduled_job_id)
        self.service._send_message_item = AsyncMock()
        self.service._move_from_step = AsyncMock()

        with patch(
            "app.services.funnel_runtime_service.enqueue_funnel_chat_action",
            new=AsyncMock(return_value="chat-action-job"),
        ) as enqueue_mock:
            result = await self.service._execute_message_sequence(
                chat_id=chat_id,
                step=step,
            )

        self.assertIs(result, step)
        self.service._send_message_item.assert_not_awaited()
        self.service._schedule_job.assert_awaited_once_with(
            chat_id=chat_id,
            step=step,
            job_type="message_sequence",
            delay_seconds=7,
            payload_json={
                "message_index": 0,
                "chat_action_completed": True,
                "chat_action": "typing",
            },
        )
        enqueue_mock.assert_awaited_once_with(
            scheduled_job_id=scheduled_job_id,
            chat_id=chat_id,
            action="typing",
            duration_seconds=7,
        )


if __name__ == "__main__":
    unittest.main()
