from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
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
            chat=chat,
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


if __name__ == "__main__":
    unittest.main()
