from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.schemas.lander import ProjectLanderCreate, ProjectLanderUpdate
from app.services.lander_service import LanderService
from app.services.telegram_bot_avatar_service import (
    BotAvatarUnavailableError,
    TelegramBotAvatarService,
)


class DefaultTelegramLanderTests(unittest.TestCase):
    @staticmethod
    def _lander(**overrides):
        bot = SimpleNamespace(
            name="Internal name",
            telegram_first_name="Actual <Bot>",
            bot_username="actual_bot",
            telegram_description="Telegram profile description",
            telegram_about="Short description",
        )
        values = {
            "slug": "campaign_1",
            "description": "Custom <description>\nSecond line",
            "button_text": "Continue & open",
            "auto_redirect_enabled": False,
            "tracking_link": SimpleNamespace(bot=bot),
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_default_lander_uses_bot_identity_and_configured_copy(self) -> None:
        rendered = LanderService._render_default_redirect_html(
            self._lander(),
            "https://telegram.me/actual_bot?start=payload&source=test",
            "<script>pixel()</script>",
        )

        self.assertIn("Actual &lt;Bot&gt; - Telegram", rendered)
        self.assertIn("Custom &lt;description&gt;\nSecond line", rendered)
        self.assertIn("Continue &amp; open", rendered)
        self.assertIn('/l/campaign_1/bot-avatar', rendered)
        self.assertIn('class="telegram-header"', rendered)
        self.assertNotIn("DOWNLOAD", rendered)
        self.assertNotIn("window.setTimeout(openTelegram, 650);", rendered)
        self.assertIn("pixel()", rendered)

    def test_empty_content_falls_back_to_bot_profile_and_default_button(self) -> None:
        rendered = LanderService._render_default_redirect_html(
            self._lander(description=None, button_text=None, auto_redirect_enabled=True),
            "https://telegram.me/actual_bot?start=payload",
            "",
        )

        self.assertIn("Telegram profile description", rendered)
        self.assertIn(">Open in Telegram</a>", rendered)
        self.assertIn("window.setTimeout(openTelegram, 650);", rendered)

    def test_lander_copy_is_normalized_without_breaking_legacy_payloads(self) -> None:
        payload = ProjectLanderCreate.model_validate(
            {
                "name": "Landing",
                "type": "default_tg_redirect",
                "slug": "landing",
                "tracking_link_id": str(uuid4()),
                "description": "  Description  ",
                "button_text": "  Open  ",
            }
        )
        update = ProjectLanderUpdate.model_validate(
            {"description": "   ", "button_text": "   "}
        )

        self.assertEqual(payload.description, "Description")
        self.assertEqual(payload.button_text, "Open")
        self.assertIsNone(update.description)
        self.assertIsNone(update.button_text)


class TelegramBotAvatarServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_avatar_is_loaded_from_telegram_and_then_cached(self) -> None:
        sender = SimpleNamespace(
            get_user_profile_photos=AsyncMock(
                return_value={
                    "photos": [[
                        {"file_id": "small", "width": 80, "height": 80},
                        {"file_id": "large", "width": 320, "height": 320},
                    ]]
                }
            ),
            get_file=AsyncMock(return_value={"file_path": "photos/avatar.jpg"}),
            download_file=AsyncMock(return_value=b"jpeg-avatar"),
        )
        bot_id = uuid4()
        with tempfile.TemporaryDirectory() as temp_dir:
            service = TelegramBotAvatarService(
                sender=sender,
                storage_root=Path(temp_dir),
                cache_seconds=300,
                max_bytes=1024,
            )

            first, first_type = await service.get_avatar(
                bot_id=bot_id,
                token="secret-token",
                telegram_bot_id=123,
            )
            second, second_type = await service.get_avatar(
                bot_id=bot_id,
                token="secret-token",
                telegram_bot_id=123,
            )

        self.assertEqual(first, b"jpeg-avatar")
        self.assertEqual(second, first)
        self.assertEqual(first_type, "image/jpeg")
        self.assertEqual(second_type, "image/jpeg")
        sender.get_user_profile_photos.assert_awaited_once()
        sender.get_file.assert_awaited_once_with("secret-token", "large")
        sender.download_file.assert_awaited_once_with(
            "secret-token",
            "photos/avatar.jpg",
            max_bytes=1024,
        )

    async def test_missing_telegram_photo_is_reported_without_empty_cache(self) -> None:
        sender = SimpleNamespace(
            get_user_profile_photos=AsyncMock(return_value={"photos": []}),
            get_file=AsyncMock(),
            download_file=AsyncMock(),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            service = TelegramBotAvatarService(
                sender=sender,
                storage_root=Path(temp_dir),
                cache_seconds=300,
                max_bytes=1024,
            )
            with self.assertRaises(BotAvatarUnavailableError):
                await service.get_avatar(
                    bot_id=uuid4(),
                    token="secret-token",
                    telegram_bot_id=123,
                )

        sender.get_file.assert_not_awaited()
        sender.download_file.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
