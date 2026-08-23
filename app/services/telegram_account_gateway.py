from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from app.core.config import settings
from app.core.redis import get_redis


TELEGRAM_ACCOUNT_COMMAND_QUEUE = "crm:telegram-account:commands"
logger = logging.getLogger(__name__)


class TelegramAccountGatewayError(RuntimeError):
    def __init__(self, message: str, *, transient: bool = False) -> None:
        self.transient = transient
        super().__init__(message)


class TelegramAccountGateway:
    """Small Redis RPC bridge to the process that owns live MTProto clients."""

    async def invoke(
        self,
        *,
        bot_id: UUID,
        operation: str,
        payload: dict[str, Any],
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        request_id = uuid4().hex
        response_key = f"crm:telegram-account:response:{request_id}"
        timeout = max(
            int(timeout_seconds or settings.TELEGRAM_ACCOUNT_RPC_TIMEOUT_SECONDS),
            1,
        )
        command = {
            "request_id": request_id,
            "bot_id": str(bot_id),
            "operation": operation,
            "payload": payload,
            "expires_at": time.time() + timeout,
        }
        redis = None
        try:
            redis = await get_redis()
            await redis.rpush(
                TELEGRAM_ACCOUNT_COMMAND_QUEUE,
                json.dumps(command, ensure_ascii=True, separators=(",", ":")),
            )
            response = await redis.blpop(response_key, timeout=timeout)
        except Exception as exc:
            raise TelegramAccountGatewayError(
                f"MTProto command queue is unavailable ({exc.__class__.__name__})",
                transient=True,
            ) from exc
        finally:
            if redis is not None:
                try:
                    await redis.delete(response_key)
                except Exception:
                    logger.warning(
                        "Could not clean MTProto response key request_id=%s",
                        request_id,
                        exc_info=True,
                    )

        if response is None:
            raise TelegramAccountGatewayError(
                "MTProto account worker did not respond in time",
                transient=True,
            )
        _, raw_payload = response
        try:
            envelope = json.loads(raw_payload)
        except (TypeError, json.JSONDecodeError) as exc:
            raise TelegramAccountGatewayError(
                "MTProto account worker returned an invalid response",
                transient=True,
            ) from exc
        if not isinstance(envelope, dict) or envelope.get("ok") is not True:
            error = envelope.get("error") if isinstance(envelope, dict) else None
            transient = bool(envelope.get("transient")) if isinstance(envelope, dict) else True
            raise TelegramAccountGatewayError(
                str(error or "MTProto command failed"),
                transient=transient,
            )
        result = envelope.get("result")
        return result if isinstance(result, dict) else {}

    @staticmethod
    async def stage_bytes(
        content: bytes,
        *,
        file_name: str | None,
    ) -> Path:
        suffix = Path(file_name or "upload.bin").suffix[:16] or ".bin"
        directory = Path(settings.TELEGRAM_ACCOUNT_MEDIA_STORAGE_PATH) / ".outbox"
        await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
        path = directory / f"{uuid4().hex}{suffix}"
        await asyncio.to_thread(path.write_bytes, content)
        return path
