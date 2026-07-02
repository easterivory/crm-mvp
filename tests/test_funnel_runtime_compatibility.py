from __future__ import annotations

import unittest
from types import SimpleNamespace
from uuid import uuid4

from app.core.constants import MessageType
from app.schemas.telegram import TelegramChat, TelegramContact, TelegramMessage, TelegramUser
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
                self.assertNotIn("inline_keyboard", markup)
                self.assertIs(markup["keyboard"][0][0]["request_contact"], True)
                self.assertIs(markup["one_time_keyboard"], True)

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
        self.assertIs(markup["keyboard"][0][0]["request_contact"], True)

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
