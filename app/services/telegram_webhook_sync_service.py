from __future__ import annotations

import logging

from app.core.config import settings
from app.core.constants import TELEGRAM_WEBHOOK_ALLOWED_UPDATES
from app.core.database import get_db_session
from app.repositories.bot_repository import BotRepository
from app.services.telegram_sender import TelegramSenderService

logger = logging.getLogger(__name__)


async def sync_telegram_webhook_subscriptions() -> None:
    """Bring existing bot webhooks up to the current allowed update set."""
    base_url = str(settings.BASE_URL or "").strip().rstrip("/")
    if not base_url:
        logger.info("Telegram webhook sync skipped: BASE_URL is not configured")
        return

    try:
        async with get_db_session() as db:
            repo = BotRepository(db)
            sender = TelegramSenderService(db)
            expected_updates = set(TELEGRAM_WEBHOOK_ALLOWED_UPDATES)
            offset = 0

            while True:
                bots = await repo.list_active(limit=100, offset=offset)
                if not bots:
                    break

                for bot in bots:
                    token = str(bot.telegram_token or "").strip()
                    if not token:
                        continue
                    expected_url = f"{base_url}/api/v1/telegram/webhook/{bot.id}"
                    try:
                        info = await sender.get_webhook_info(token)
                        configured_updates = {
                            str(value) for value in info.get("allowed_updates") or []
                        }
                        if (
                            info.get("url") == expected_url
                            and expected_updates.issubset(configured_updates)
                        ):
                            continue
                        await sender.set_webhook(
                            token=token,
                            webhook_url=expected_url,
                            secret_token=settings.TELEGRAM_WEBHOOK_SECRET,
                            allowed_updates=TELEGRAM_WEBHOOK_ALLOWED_UPDATES,
                        )
                        logger.info(
                            "Telegram webhook subscription updated bot_id=%s",
                            bot.id,
                        )
                    except Exception:
                        logger.warning(
                            "Telegram webhook subscription sync failed bot_id=%s",
                            bot.id,
                            exc_info=True,
                        )

                if len(bots) < 100:
                    break
                offset += len(bots)
    except Exception:
        logger.exception("Telegram webhook subscription sync failed before completion")
