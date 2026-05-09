"""
TelegramSenderService - outgoing Telegram Bot API client.

Network/API failures are logged but never raised to callers. A temporary
Telegram outage must not roll back local CRM writes.
"""
import logging
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.bot_repository import BotRepository

logger = logging.getLogger(__name__)


class TelegramSenderService:
    def __init__(self, db: AsyncSession) -> None:
        self.bot_repo = BotRepository(db)

    async def send_message(
        self,
        project_id: UUID,
        external_chat_id: str,
        text: str,
    ) -> None:
        token = await self.bot_repo.get_active_bot_token(project_id)
        if not token:
            return

        message_text = text.strip()
        if not message_text:
            return

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": external_chat_id, "text": message_text}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Telegram sendMessage failed: project_id=%s chat_id=%s "
                "status_code=%s response=%s",
                project_id,
                external_chat_id,
                exc.response.status_code,
                exc.response.text[:500],
            )
        except httpx.HTTPError as exc:
            logger.error(
                "Telegram sendMessage failed: project_id=%s chat_id=%s error_type=%s",
                project_id,
                external_chat_id,
                exc.__class__.__name__,
            )
        except Exception:
            logger.exception(
                "Unexpected error while sending Telegram message: "
                "project_id=%s chat_id=%s",
                project_id,
                external_chat_id,
            )
