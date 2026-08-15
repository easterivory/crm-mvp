"""Outgoing Telegram Bot API client with opt-in delivery diagnostics."""
import json
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.bot_repository import BotRepository
from app.services.chat_user_block_service import ChatUserBlockService
from app.utils.video_processor import (
    VideoProcessingError,
    crop_video_file_to_square,
    crop_video_to_square,
)

logger = logging.getLogger(__name__)


class TelegramDeliveryError(RuntimeError):
    """Safe, token-free description of a failed Telegram delivery attempt."""

    def __init__(
        self,
        *,
        method: str,
        description: str,
        status_code: int | None = None,
        error_code: int | None = None,
        retry_after: int | None = None,
        transient: bool = False,
        blocked: bool = False,
    ) -> None:
        normalized_description = " ".join(str(description).split())[:500]
        self.method = method
        self.description = normalized_description or "Telegram returned no error details"
        self.status_code = status_code
        self.error_code = error_code
        self.retry_after = retry_after
        self.transient = transient
        self.blocked = blocked

        details = [f"method={method}"]
        if status_code is not None:
            details.append(f"http_status={status_code}")
        if error_code is not None:
            details.append(f"telegram_error_code={error_code}")
        details.append(f"transient={str(transient).lower()}")
        if retry_after is not None:
            details.append(f"retry_after={retry_after}s")
        details.append(f"description={self.description}")
        super().__init__("Telegram delivery failed (" + ", ".join(details) + ")")


class TelegramSenderService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        release_transaction_before_network: bool = False,
        raise_on_delivery_error: bool = False,
    ) -> None:
        self.db = db
        self.bot_repo = BotRepository(db)
        self.release_transaction_before_network = release_transaction_before_network
        self.raise_on_delivery_error = raise_on_delivery_error

    async def _get_token(self, project_id: UUID, bot_id: UUID | None) -> str | None:
        token = (
            await self.bot_repo.get_bot_token_by_id(bot_id, project_id)
            if bot_id is not None
            else await self.bot_repo.get_active_bot_token(project_id)
        )
        if self.release_transaction_before_network and self.db.in_transaction():
            await self.db.commit()
        return token

    async def send_message(
        self,
        project_id: UUID,
        bot_id: UUID | None,
        external_chat_id: str,
        text: str,
        reply_markup: dict | None = None,
        reply_parameters: dict | None = None,
    ) -> dict[str, Any] | None:
        token = await self._get_token(project_id, bot_id)
        if not token:
            await self._handle_delivery_error(
                TelegramDeliveryError(
                    method="sendMessage",
                    description="Bot token is not configured",
                ),
                project_id=project_id,
                bot_id=bot_id,
                external_chat_id=external_chat_id,
            )
            return None

        message_text = text.strip()
        if not message_text:
            await self._handle_delivery_error(
                TelegramDeliveryError(
                    method="sendMessage",
                    description="Message text is empty",
                ),
                project_id=project_id,
                bot_id=bot_id,
                external_chat_id=external_chat_id,
            )
            return None

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload: dict[str, Any] = {"chat_id": external_chat_id, "text": message_text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if reply_parameters:
            payload["reply_parameters"] = reply_parameters

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            await self._handle_delivery_error(
                self._network_delivery_error("sendMessage", exc),
                project_id=project_id,
                bot_id=bot_id,
                external_chat_id=external_chat_id,
            )
            return None
        except Exception as exc:
            await self._handle_delivery_error(
                TelegramDeliveryError(
                    method="sendMessage",
                    description=f"Unexpected client error ({exc.__class__.__name__})",
                ),
                project_id=project_id,
                bot_id=bot_id,
                external_chat_id=external_chat_id,
            )
            return None

        return await self._result_or_delivery_error(
            method="sendMessage",
            response=response,
            project_id=project_id,
            bot_id=bot_id,
            external_chat_id=external_chat_id,
        )

    async def send_chat_action(
        self,
        project_id: UUID,
        bot_id: UUID | None,
        external_chat_id: str,
        action: str = "typing",
    ) -> bool:
        """Send a transient Telegram activity indicator.

        Failure is intentionally non-fatal: a typing indicator must never block
        delivery of the actual funnel message.
        """

        token = await self._get_token(project_id, bot_id)
        if not token:
            return False
        normalized_action = action.strip() or "typing"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"https://api.telegram.org/bot{token}/sendChatAction",
                    json={
                        "chat_id": external_chat_id,
                        "action": normalized_action,
                    },
                )
            if response.is_success:
                payload = response.json()
                return isinstance(payload, dict) and payload.get("ok") is True
            logger.info(
                "Telegram chat action was not accepted project_id=%s bot_id=%s "
                "chat_id=%s status=%s",
                project_id,
                bot_id,
                external_chat_id,
                response.status_code,
            )
        except (httpx.HTTPError, ValueError):
            logger.info(
                "Telegram chat action failed project_id=%s bot_id=%s chat_id=%s",
                project_id,
                bot_id,
                external_chat_id,
            )
        return False

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
        reply_parameters: dict | None = None,
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
            reply_parameters=reply_parameters,
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

    async def edit_message_text(
        self,
        *,
        project_id: UUID,
        bot_id: UUID | None,
        external_chat_id: str,
        message_id: int,
        text: str,
        reply_markup: dict | None = None,
    ) -> dict[str, Any] | None:
        payload: dict[str, Any] = {
            "chat_id": external_chat_id,
            "message_id": message_id,
            "text": text,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self._edit_message(
            method="editMessageText",
            project_id=project_id,
            bot_id=bot_id,
            external_chat_id=external_chat_id,
            payload=payload,
        )

    async def edit_message_caption(
        self,
        *,
        project_id: UUID,
        bot_id: UUID | None,
        external_chat_id: str,
        message_id: int,
        caption: str,
        reply_markup: dict | None = None,
    ) -> dict[str, Any] | None:
        payload: dict[str, Any] = {
            "chat_id": external_chat_id,
            "message_id": message_id,
            "caption": caption,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self._edit_message(
            method="editMessageCaption",
            project_id=project_id,
            bot_id=bot_id,
            external_chat_id=external_chat_id,
            payload=payload,
        )

    async def _edit_message(
        self,
        *,
        method: str,
        project_id: UUID,
        bot_id: UUID | None,
        external_chat_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        token = await self._get_token(project_id, bot_id)
        if not token:
            return None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"https://api.telegram.org/bot{token}/{method}",
                    json=payload,
                )
        except httpx.HTTPError as exc:
            await self._handle_delivery_error(
                self._network_delivery_error(method, exc),
                project_id=project_id,
                bot_id=bot_id,
                external_chat_id=external_chat_id,
            )
            return None
        return await self._result_or_delivery_error(
            method=method,
            response=response,
            project_id=project_id,
            bot_id=bot_id,
            external_chat_id=external_chat_id,
        )

    async def delete_message(
        self,
        *,
        project_id: UUID,
        bot_id: UUID | None,
        external_chat_id: str,
        message_id: int,
    ) -> bool:
        token = await self._get_token(project_id, bot_id)
        if not token:
            return False
        method = "deleteMessage"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"https://api.telegram.org/bot{token}/{method}",
                    json={
                        "chat_id": external_chat_id,
                        "message_id": message_id,
                    },
                )
        except httpx.HTTPError as exc:
            await self._handle_delivery_error(
                self._network_delivery_error(method, exc),
                project_id=project_id,
                bot_id=bot_id,
                external_chat_id=external_chat_id,
            )
            return False

        try:
            payload: Any = response.json()
        except ValueError:
            payload = None
        if (
            response.is_success
            and isinstance(payload, dict)
            and payload.get("ok") is True
            and payload.get("result") is True
        ):
            return True

        await self._handle_delivery_error(
            self._response_delivery_error(
                method=method,
                response=response,
                payload=payload,
            ),
            project_id=project_id,
            bot_id=bot_id,
            external_chat_id=external_chat_id,
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
        reply_parameters: dict | None = None,
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
            reply_parameters=reply_parameters,
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
        reply_parameters: dict | None = None,
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
            reply_parameters=reply_parameters,
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
        reply_parameters: dict | None = None,
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
            reply_parameters=reply_parameters,
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
        reply_parameters: dict | None = None,
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
                    reply_parameters=reply_parameters,
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
            reply_parameters=reply_parameters,
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
        reply_parameters: dict | None = None,
    ) -> dict[str, Any] | None:
        token = await self._get_token(project_id, bot_id)
        if not token:
            await self._handle_delivery_error(
                TelegramDeliveryError(
                    method=method,
                    description="Bot token is not configured",
                ),
                project_id=project_id,
                bot_id=bot_id,
                external_chat_id=external_chat_id,
            )
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
                    if reply_parameters:
                        data["reply_parameters"] = json.dumps(reply_parameters)
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
                    if reply_parameters:
                        data["reply_parameters"] = json.dumps(reply_parameters)
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
                    if reply_parameters:
                        payload["reply_parameters"] = reply_parameters
                    response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            await self._handle_delivery_error(
                self._network_delivery_error(method, exc),
                project_id=project_id,
                bot_id=bot_id,
                external_chat_id=external_chat_id,
            )
            return None
        except OSError as exc:
            await self._handle_delivery_error(
                TelegramDeliveryError(
                    method=method,
                    description=f"Media file could not be read ({exc.__class__.__name__})",
                ),
                project_id=project_id,
                bot_id=bot_id,
                external_chat_id=external_chat_id,
            )
            return None
        except Exception as exc:
            await self._handle_delivery_error(
                TelegramDeliveryError(
                    method=method,
                    description=f"Unexpected client error ({exc.__class__.__name__})",
                ),
                project_id=project_id,
                bot_id=bot_id,
                external_chat_id=external_chat_id,
            )
            return None

        return await self._result_or_delivery_error(
            method=method,
            response=response,
            project_id=project_id,
            bot_id=bot_id,
            external_chat_id=external_chat_id,
        )

    async def _result_or_delivery_error(
        self,
        *,
        method: str,
        response: httpx.Response,
        project_id: UUID,
        bot_id: UUID | None,
        external_chat_id: str,
    ) -> dict[str, Any] | None:
        try:
            payload: Any = response.json()
        except ValueError:
            payload = None

        if (
            response.is_success
            and isinstance(payload, dict)
            and payload.get("ok") is True
            and isinstance(payload.get("result"), dict)
        ):
            return payload["result"]

        error = self._response_delivery_error(
            method=method,
            response=response,
            payload=payload,
        )
        await self._handle_delivery_error(
            error,
            project_id=project_id,
            bot_id=bot_id,
            external_chat_id=external_chat_id,
        )
        return None

    @classmethod
    def _response_delivery_error(
        cls,
        *,
        method: str,
        response: httpx.Response,
        payload: Any,
    ) -> TelegramDeliveryError:
        description = ""
        error_code: int | None = None
        retry_after: int | None = None
        if isinstance(payload, dict):
            description = str(payload.get("description") or payload.get("error") or "")
            error_code = cls._optional_int(payload.get("error_code"))
            parameters = payload.get("parameters")
            if isinstance(parameters, dict):
                retry_after = cls._optional_int(parameters.get("retry_after"))
        if not description:
            description = response.text[:500] if response.text else "Invalid Telegram response"

        effective_code = error_code or response.status_code
        blocked = cls._is_bot_blocked_payload(payload) or cls._is_bot_blocked_text(description)
        transient = effective_code == 429 or response.status_code >= 500
        if response.is_success and not isinstance(payload, dict):
            transient = True
        return TelegramDeliveryError(
            method=method,
            description=description,
            status_code=response.status_code,
            error_code=error_code,
            retry_after=retry_after,
            transient=transient,
            blocked=blocked,
        )

    @staticmethod
    def _network_delivery_error(method: str, exc: httpx.HTTPError) -> TelegramDeliveryError:
        return TelegramDeliveryError(
            method=method,
            description=f"Network error ({exc.__class__.__name__})",
            transient=True,
        )

    async def _handle_delivery_error(
        self,
        error: TelegramDeliveryError,
        *,
        project_id: UUID,
        bot_id: UUID | None,
        external_chat_id: str,
    ) -> None:
        if error.blocked:
            await self._record_bot_blocked(
                project_id=project_id,
                bot_id=bot_id,
                external_chat_id=external_chat_id,
            )

        log_method = logger.info if error.blocked else (logger.warning if error.transient else logger.error)
        log_method(
            "Telegram delivery failed: method=%s project_id=%s bot_id=%s chat_id=%s "
            "http_status=%s telegram_error_code=%s transient=%s blocked=%s "
            "retry_after=%s description=%s",
            error.method,
            project_id,
            bot_id,
            external_chat_id,
            error.status_code,
            error.error_code,
            error.transient,
            error.blocked,
            error.retry_after,
            error.description,
        )
        if getattr(self, "raise_on_delivery_error", False):
            raise error

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
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

    @staticmethod
    async def _record_bot_blocked(
        *,
        project_id: UUID,
        bot_id: UUID | None,
        external_chat_id: str,
    ) -> None:
        try:
            await ChatUserBlockService.persist_blocked_from_telegram_error(
                project_id=project_id,
                bot_id=bot_id,
                external_chat_id=external_chat_id,
            )
        except Exception:
            logger.exception(
                "Could not persist Telegram user block project_id=%s bot_id=%s chat_id=%s",
                project_id,
                bot_id,
                external_chat_id,
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

    async def get_chat(self, token: str, chat_id: str | int) -> dict:
        payload = await self._post_bot_api(
            token=token,
            method="getChat",
            json_payload={"chat_id": chat_id},
        )
        result = payload.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("Telegram getChat response does not contain chat data")
        return result

    async def get_chat_member(
        self,
        token: str,
        *,
        chat_id: str | int,
        user_id: int,
    ) -> dict:
        payload = await self._post_bot_api(
            token=token,
            method="getChatMember",
            json_payload={"chat_id": chat_id, "user_id": user_id},
        )
        result = payload.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(
                "Telegram getChatMember response does not contain membership data"
            )
        return result

    async def create_chat_invite_link(
        self,
        token: str,
        *,
        chat_id: str | int,
        name: str,
        creates_join_request: bool = False,
        expire_date: int | None = None,
        member_limit: int | None = None,
    ) -> dict:
        json_payload: dict[str, str | int | bool] = {
            "chat_id": chat_id,
            "name": name[:32],
            "creates_join_request": creates_join_request,
        }
        if expire_date is not None:
            json_payload["expire_date"] = int(expire_date)
        if member_limit is not None and not creates_join_request:
            json_payload["member_limit"] = int(member_limit)
        payload = await self._post_bot_api(
            token=token,
            method="createChatInviteLink",
            json_payload=json_payload,
        )
        result = payload.get("result")
        if not isinstance(result, dict) or not str(result.get("invite_link") or "").strip():
            raise RuntimeError(
                "Telegram createChatInviteLink response does not contain an invite link"
            )
        return result

    async def send_join_request_message(
        self,
        token: str,
        *,
        user_chat_id: int,
        text: str,
    ) -> dict:
        message_text = text.strip()
        if not message_text:
            raise RuntimeError("Telegram join-request message is empty")
        if len(message_text) > 4096:
            raise RuntimeError("Telegram join-request message exceeds 4096 characters")
        payload = await self._post_bot_api(
            token=token,
            method="sendMessage",
            json_payload={"chat_id": user_chat_id, "text": message_text},
        )
        result = payload.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(
                "Telegram sendMessage response does not contain message data"
            )
        return result

    async def approve_chat_join_request(
        self,
        token: str,
        *,
        chat_id: str | int,
        user_id: int,
    ) -> bool:
        payload = await self._post_bot_api(
            token=token,
            method="approveChatJoinRequest",
            json_payload={"chat_id": chat_id, "user_id": user_id},
        )
        return payload.get("result") is True

    async def revoke_chat_invite_link(
        self,
        token: str,
        *,
        chat_id: str | int,
        invite_link: str,
    ) -> dict:
        payload = await self._post_bot_api(
            token=token,
            method="revokeChatInviteLink",
            json_payload={"chat_id": chat_id, "invite_link": invite_link},
        )
        result = payload.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(
                "Telegram revokeChatInviteLink response does not contain invite data"
            )
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

    async def get_user_profile_photos(
        self,
        token: str,
        *,
        user_id: int,
        limit: int = 1,
    ) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"https://api.telegram.org/bot{token}/getUserProfilePhotos",
                params={"user_id": user_id, "offset": 0, "limit": max(1, min(limit, 100))},
            )
            payload = response.json()

        if response.status_code >= 400 or payload.get("ok") is not True:
            raise RuntimeError(
                payload.get("description") or "Telegram rejected getUserProfilePhotos"
            )
        result = payload.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(
                "Telegram getUserProfilePhotos response does not contain profile photos"
            )
        return result

    async def download_file(
        self,
        token: str,
        file_path: str,
        *,
        max_bytes: int,
    ) -> bytes:
        normalized_path = file_path.strip().lstrip("/")
        path_parts = Path(normalized_path).parts
        if (
            not normalized_path
            or "://" in normalized_path
            or any(part in {"", ".", ".."} for part in path_parts)
        ):
            raise RuntimeError("Telegram returned an invalid file path")
        file_url = f"https://api.telegram.org/file/bot{token}/{normalized_path}"
        chunks: list[bytes] = []
        total_bytes = 0
        async with httpx.AsyncClient(timeout=30) as client:
            async with client.stream("GET", file_url) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue
                    total_bytes += len(chunk)
                    if total_bytes > max_bytes:
                        raise RuntimeError("Telegram file exceeds the configured size limit")
                    chunks.append(chunk)
        return b"".join(chunks)

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

    async def set_bot_commands(
        self,
        token: str,
        commands: list[dict[str, str]],
    ) -> dict:
        return await self._post_bot_api(
            token=token,
            method="setMyCommands",
            json_payload={"commands": commands},
        )

    async def get_bot_commands(self, token: str) -> list[dict[str, str]]:
        payload = await self._post_bot_api(
            token=token,
            method="getMyCommands",
        )
        result = payload.get("result")
        if not isinstance(result, list):
            raise RuntimeError("Telegram getMyCommands response does not contain commands")
        return [
            {
                "command": str(item.get("command") or "").strip(),
                "description": str(item.get("description") or "").strip(),
            }
            for item in result
            if isinstance(item, dict)
        ]

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
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"https://api.telegram.org/bot{token}/{method}",
                    json=json_payload,
                    data=data,
                    files=files,
                )
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Telegram {method} request failed: {type(exc).__name__}"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"Telegram {method} returned a non-JSON response "
                f"(HTTP {response.status_code})"
            ) from exc

        if response.status_code >= 400 or payload.get("ok") is not True:
            raise RuntimeError(payload.get("description") or f"Telegram rejected {method}")

        return payload
