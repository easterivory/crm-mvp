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
        bot_id: UUID | None,
        external_chat_id: str,
        text: str,
        reply_markup: dict | None = None,
    ) -> None:
        token = (
            await self.bot_repo.get_bot_token_by_id(bot_id, project_id)
            if bot_id is not None
            else await self.bot_repo.get_active_bot_token(project_id)
        )
        if not token:
            return

        message_text = text.strip()
        if not message_text:
            return

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload: dict = {"chat_id": external_chat_id, "text": message_text}
        if reply_markup:
            payload["reply_markup"] = reply_markup

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

    async def set_webhook(
        self,
        token: str,
        webhook_url: str,
        secret_token: str | None = None,
    ) -> dict:
        params: dict[str, str] = {"url": webhook_url}
        if secret_token:
            params["secret_token"] = secret_token

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{token}/setWebhook",
                params=params,
            )
            payload = response.json()

        if response.status_code >= 400 or payload.get("ok") is not True:
            raise RuntimeError(payload.get("description") or "Telegram rejected setWebhook")

        return payload

    async def delete_webhook(self, token: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{token}/deleteWebhook",
                params={"drop_pending_updates": "false"},
            )
            payload = response.json()

        if response.status_code >= 400 or payload.get("ok") is not True:
            raise RuntimeError(payload.get("description") or "Telegram rejected deleteWebhook")

        return payload

    async def get_me(self, token: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"https://api.telegram.org/bot{token}/getMe")
            payload = response.json()

        if response.status_code >= 400 or payload.get("ok") is not True:
            raise RuntimeError(payload.get("description") or "Telegram rejected getMe")

        result = payload.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("Telegram getMe response does not contain bot identity")
        return result

    async def get_file(self, token: str, file_id: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"https://api.telegram.org/bot{token}/getFile",
                params={"file_id": file_id},
            )
            payload = response.json()

        if response.status_code >= 400 or payload.get("ok") is not True:
            raise RuntimeError(payload.get("description") or "Telegram rejected getFile")

        result = payload.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("Telegram getFile response does not contain file metadata")
        return result

    async def get_webhook_info(self, token: str) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"https://api.telegram.org/bot{token}/getWebhookInfo")
            payload = response.json()

        if response.status_code >= 400 or payload.get("ok") is not True:
            raise RuntimeError(payload.get("description") or "Telegram rejected getWebhookInfo")

        result = payload.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("Telegram getWebhookInfo response does not contain webhook metadata")
        return result

    async def answer_callback_query(self, token: str, callback_query_id: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                    json={"callback_query_id": callback_query_id},
                )
        except httpx.HTTPError:
            logger.debug("Telegram answerCallbackQuery failed", exc_info=True)
