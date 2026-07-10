"""
TelegramSenderService - outgoing Telegram Bot API client.

Network/API failures are logged and returned as None. Callers decide whether
the local CRM write should be persisted or rejected for that workflow.
"""
import json
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.bot_repository import BotRepository
from app.utils.video_processor import (
    VideoProcessingError,
    crop_video_file_to_square,
    crop_video_to_square,
)

logger = logging.getLogger(__name__)


class TelegramSenderService:
    def __init__(self, db: AsyncSession) -> None:
        self.bot_repo = BotRepository(db)

    async def _get_token(self, project_id: UUID, bot_id: UUID | None) -> str | None:
        return (
            await self.bot_repo.get_bot_token_by_id(bot_id, project_id)
            if bot_id is not None
            else await self.bot_repo.get_active_bot_token(project_id)
        )

    async def send_message(
        self,
        project_id: UUID,
        bot_id: UUID | None,
        external_chat_id: str,
        text: str,
        reply_markup: dict | None = None,
    ) -> dict[str, Any] | None:
        token = await self._get_token(project_id, bot_id)
        if not token:
            return None

        message_text = text.strip()
        if not message_text:
            return None

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload: dict[str, Any] = {"chat_id": external_chat_id, "text": message_text}
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                if data.get("ok") is not True or not isinstance(data.get("result"), dict):
                    if self._is_bot_blocked_payload(data):
                        logger.info(
                            "Telegram sendMessage blocked by user: project_id=%s chat_id=%s",
                            project_id,
                            external_chat_id,
                        )
                        return None
                    logger.error(
                        "Telegram sendMessage failed: project_id=%s chat_id=%s response=%s",
                        project_id,
                        external_chat_id,
                        str(data)[:500],
                    )
                    return None
                return data["result"]
        except httpx.HTTPStatusError as exc:
            if self._is_bot_blocked_response(exc.response):
                logger.info(
                    "Telegram sendMessage blocked by user: project_id=%s chat_id=%s",
                    project_id,
                    external_chat_id,
                )
                return None
            logger.error(
                "Telegram sendMessage failed: project_id=%s chat_id=%s "
                "status_code=%s response=%s",
                project_id,
                external_chat_id,
                exc.response.status_code,
                exc.response.text[:500],
            )
            return None
        except httpx.HTTPError as exc:
            logger.error(
                "Telegram sendMessage failed: project_id=%s chat_id=%s error_type=%s",
                project_id,
                external_chat_id,
                exc.__class__.__name__,
            )
            return None
        except Exception:
            logger.exception(
                "Unexpected error while sending Telegram message: "
                "project_id=%s chat_id=%s",
                project_id,
                external_chat_id,
            )
            return None

    async def send_photo(
        self,
        project_id: UUID,
        bot_id: UUID | None,
        external_chat_id: str,
        photo: str | Path | bytes,
        *,
        caption: str | None = None,
        reply_markup: dict | None = None,
        file_name: str | None = None,
        mime_type: str | None = None,
    ) -> dict[str, Any] | None:
        return await self._send_media(
            method="sendPhoto",
            media_field="photo",
            project_id=project_id,
            bot_id=bot_id,
            external_chat_id=external_chat_id,
            media=photo,
            caption=caption,
            reply_markup=reply_markup,
            file_name=file_name,
            mime_type=mime_type,
        )

    async def edit_message_reply_markup(
        self,
        project_id: UUID,
        bot_id: UUID | None,
        external_chat_id: str,
        message_id: int,
        reply_markup: dict | None = None,
    ) -> bool:
        token = await self._get_token(project_id, bot_id)
        if not token:
            return False
        payload: dict[str, Any] = {
            "chat_id": external_chat_id,
            "message_id": message_id,
            "reply_markup": reply_markup or {"inline_keyboard": []},
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"https://api.telegram.org/bot{token}/editMessageReplyMarkup",
                    json=payload,
                )
                response.raise_for_status()
                return response.json().get("ok") is True
        except httpx.HTTPError as exc:
            logger.warning(
                "Telegram editMessageReplyMarkup failed: project_id=%s chat_id=%s "
                "message_id=%s error_type=%s",
                project_id,
                external_chat_id,
                message_id,
                exc.__class__.__name__,
            )
            return False
        except Exception:
            logger.exception(
                "Unexpected Telegram editMessageReplyMarkup failure: "
                "project_id=%s chat_id=%s message_id=%s",
                project_id,
                external_chat_id,
                message_id,
            )
            return False

    async def send_video(
        self,
        project_id: UUID,
        bot_id: UUID | None,
        external_chat_id: str,
        video: str | Path | bytes,
        *,
        caption: str | None = None,
        reply_markup: dict | None = None,
        file_name: str | None = None,
        mime_type: str | None = None,
    ) -> dict[str, Any] | None:
        return await self._send_media(
            method="sendVideo",
            media_field="video",
            project_id=project_id,
            bot_id=bot_id,
            external_chat_id=external_chat_id,
            media=video,
            caption=caption,
            reply_markup=reply_markup,
            file_name=file_name,
            mime_type=mime_type,
            timeout=90.0,
        )

    async def send_document(
        self,
        project_id: UUID,
        bot_id: UUID | None,
        external_chat_id: str,
        document: str | Path | bytes,
        *,
        caption: str | None = None,
        reply_markup: dict | None = None,
        file_name: str | None = None,
        mime_type: str | None = None,
    ) -> dict[str, Any] | None:
        return await self._send_media(
            method="sendDocument",
            media_field="document",
            project_id=project_id,
            bot_id=bot_id,
            external_chat_id=external_chat_id,
            media=document,
            caption=caption,
            reply_markup=reply_markup,
            file_name=file_name,
            mime_type=mime_type,
            timeout=90.0,
        )

    async def send_voice(
        self,
        project_id: UUID,
        bot_id: UUID | None,
        external_chat_id: str,
        voice: str | Path | bytes,
        *,
        caption: str | None = None,
        reply_markup: dict | None = None,
        file_name: str | None = None,
        mime_type: str | None = None,
    ) -> dict[str, Any] | None:
        return await self._send_media(
            method="sendVoice",
            media_field="voice",
            project_id=project_id,
            bot_id=bot_id,
            external_chat_id=external_chat_id,
            media=voice,
            caption=caption,
            reply_markup=reply_markup,
            file_name=file_name,
            mime_type=mime_type,
            timeout=90.0,
        )

    async def send_video_note(
        self,
        project_id: UUID,
        bot_id: UUID | None,
        external_chat_id: str,
        video_note: str | Path | bytes,
        *,
        reply_markup: dict | None = None,
        file_name: str | None = None,
        mime_type: str | None = None,
    ) -> dict[str, Any] | None:
        if isinstance(video_note, (bytes, Path)):
            try:
                cropped_video = (
                    await crop_video_to_square(video_note)
                    if isinstance(video_note, bytes)
                    else await crop_video_file_to_square(video_note)
                )
                return await self._send_media(
                    method="sendVideoNote",
                    media_field="video_note",
                    project_id=project_id,
                    bot_id=bot_id,
                    external_chat_id=external_chat_id,
                    media=cropped_video,
                    reply_markup=reply_markup,
                    file_name=self._video_note_file_name(file_name),
                    mime_type="video/mp4",
                    timeout=90.0,
                    supports_caption=False,
                )
            except VideoProcessingError as exc:
                logger.error(
                    "Telegram video_note crop failed; refusing to send a non-circular video: "
                    "project_id=%s chat_id=%s file_name=%s error=%s",
                    project_id,
                    external_chat_id,
                    file_name,
                    exc,
                )
                raise

        return await self._send_media(
            method="sendVideoNote",
            media_field="video_note",
            project_id=project_id,
            bot_id=bot_id,
            external_chat_id=external_chat_id,
            media=video_note,
            reply_markup=reply_markup,
            file_name=file_name,
            mime_type=mime_type,
            timeout=90.0,
            supports_caption=False,
        )

    @staticmethod
    def _video_note_file_name(file_name: str | None) -> str:
        if not file_name:
            return "video_note.mp4"
        stem = Path(file_name).stem.strip()
        return f"{stem or 'video_note'}.mp4"

    async def _send_media(
        self,
        *,
        method: str,
        media_field: str,
        project_id: UUID,
        bot_id: UUID | None,
        external_chat_id: str,
        media: str | Path | bytes,
        caption: str | None = None,
        reply_markup: dict | None = None,
        file_name: str | None = None,
        mime_type: str | None = None,
        timeout: float = 30.0,
        supports_caption: bool = True,
    ) -> dict[str, Any] | None:
        token = await self._get_token(project_id, bot_id)
        if not token:
            return None

        url = f"https://api.telegram.org/bot{token}/{method}"
        caption_text = caption.strip() if supports_caption and isinstance(caption, str) else ""
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if isinstance(media, Path):
                    data: dict[str, str] = {"chat_id": external_chat_id}
                    if caption_text:
                        data["caption"] = caption_text
                    if reply_markup:
                        data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
                    with media.open("rb") as media_file:
                        files = {
                            media_field: (
                                file_name or media.name,
                                media_file,
                                mime_type or "application/octet-stream",
                            )
                        }
                        response = await client.post(url, data=data, files=files)
                elif isinstance(media, bytes):
                    data = {"chat_id": external_chat_id}
                    if caption_text:
                        data["caption"] = caption_text
                    if reply_markup:
                        data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
                    files = {
                        media_field: (
                            file_name or f"{media_field}.bin",
                            media,
                            mime_type or "application/octet-stream",
                        )
                    }
                    response = await client.post(url, data=data, files=files)
                else:
                    payload: dict[str, Any] = {"chat_id": external_chat_id, media_field: media}
                    if caption_text:
                        payload["caption"] = caption_text
                    if reply_markup:
                        payload["reply_markup"] = reply_markup
                    response = await client.post(url, json=payload)
                response.raise_for_status()
                payload = response.json()
                if payload.get("ok") is not True or not isinstance(payload.get("result"), dict):
                    if self._is_bot_blocked_payload(payload):
                        logger.info(
                            "Telegram %s blocked by user: project_id=%s chat_id=%s",
                            method,
                            project_id,
                            external_chat_id,
                        )
                        return None
                    logger.error(
                        "Telegram %s failed: project_id=%s chat_id=%s response=%s",
                        method,
                        project_id,
                        external_chat_id,
                        str(payload)[:500],
                    )
                    return None
                return payload["result"]
        except httpx.HTTPStatusError as exc:
            if self._is_bot_blocked_response(exc.response):
                logger.info(
                    "Telegram %s blocked by user: project_id=%s chat_id=%s",
                    method,
                    project_id,
                    external_chat_id,
                )
                return None
            logger.error(
                "Telegram %s failed: project_id=%s chat_id=%s status_code=%s response=%s",
                method,
                project_id,
                external_chat_id,
                exc.response.status_code,
                exc.response.text[:500],
            )
            return None
        except httpx.HTTPError as exc:
            logger.error(
                "Telegram %s failed: project_id=%s chat_id=%s error_type=%s",
                method,
                project_id,
                external_chat_id,
                exc.__class__.__name__,
            )
            return None
        except OSError as exc:
            logger.error(
                "Telegram %s failed to read media file: project_id=%s chat_id=%s error=%s",
                method,
                project_id,
                external_chat_id,
                exc,
            )
            return None
        except Exception:
            logger.exception(
                "Unexpected error while sending Telegram media: method=%s project_id=%s chat_id=%s",
                method,
                project_id,
                external_chat_id,
            )
            return None

    @staticmethod
    def _is_bot_blocked_payload(payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        description = str(payload.get("description") or payload.get("error") or "")
        return TelegramSenderService._is_bot_blocked_text(description)

    @staticmethod
    def _is_bot_blocked_response(response: httpx.Response) -> bool:
        if response.status_code != 403:
            return False
        try:
            payload = response.json()
        except ValueError:
            return TelegramSenderService._is_bot_blocked_text(response.text)
        return TelegramSenderService._is_bot_blocked_payload(payload)

    @staticmethod
    def _is_bot_blocked_text(text: str) -> bool:
        normalized = text.lower()
        return (
            "bot was blocked by the user" in normalized
            or "forbidden: bot was blocked" in normalized
        )

    async def set_webhook(
        self,
        token: str,
        webhook_url: str,
        secret_token: str | None = None,
        allowed_updates: list[str] | tuple[str, ...] | None = None,
    ) -> dict:
        params: dict[str, str] = {"url": webhook_url}
        if secret_token:
            params["secret_token"] = secret_token
        if allowed_updates:
            params["allowed_updates"] = json.dumps(list(allowed_updates))

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

    async def set_bot_description(self, token: str, description: str | None) -> dict:
        return await self._post_bot_api(
            token=token,
            method="setMyDescription",
            json_payload={"description": description or ""},
        )

    async def set_bot_about_text(self, token: str, about_text: str | None) -> dict:
        return await self._post_bot_api(
            token=token,
            method="setMyShortDescription",
            json_payload={"short_description": about_text or ""},
        )

    async def set_bot_profile_photo(
        self,
        token: str,
        photo_bytes: bytes,
        *,
        file_name: str = "bot_profile.jpg",
        mime_type: str = "image/jpeg",
    ) -> dict:
        if not photo_bytes:
            raise RuntimeError("Telegram bot profile photo is empty")

        attach_name = "bot_profile_photo"
        return await self._post_bot_api(
            token=token,
            method="setMyProfilePhoto",
            data={"photo": json.dumps({"type": "static", "photo": f"attach://{attach_name}"})},
            files={attach_name: (file_name, photo_bytes, mime_type)},
            timeout=30.0,
        )

    async def answer_callback_query(self, token: str, callback_query_id: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                    json={"callback_query_id": callback_query_id},
                )
        except httpx.HTTPError:
            logger.debug("Telegram answerCallbackQuery failed", exc_info=True)

    async def _post_bot_api(
        self,
        *,
        token: str,
        method: str,
        json_payload: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        timeout: float = 10.0,
    ) -> dict:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{token}/{method}",
                json=json_payload,
                data=data,
                files=files,
            )
            payload = response.json()

        if response.status_code >= 400 or payload.get("ok") is not True:
            raise RuntimeError(payload.get("description") or f"Telegram rejected {method}")

        return payload
