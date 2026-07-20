from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from app.core.config import settings
from app.services.telegram_sender import TelegramSenderService


logger = logging.getLogger(__name__)


class BotAvatarUnavailableError(RuntimeError):
    """Raised when Telegram has no usable profile photo for the bot."""


class TelegramBotAvatarService:
    """Fetch and locally cache the current Telegram profile photo of a bot."""

    _locks: dict[str, asyncio.Lock] = {}

    def __init__(
        self,
        *,
        sender: TelegramSenderService,
        storage_root: str | Path | None = None,
        cache_seconds: int | None = None,
        max_bytes: int | None = None,
    ) -> None:
        self.sender = sender
        self.storage_root = Path(storage_root or settings.LANDER_STORAGE_PATH) / "_bot_avatars"
        self.cache_seconds = max(
            0,
            cache_seconds
            if cache_seconds is not None
            else settings.LANDER_BOT_AVATAR_CACHE_SECONDS,
        )
        configured_max_bytes = settings.LANDER_BOT_AVATAR_MAX_MB * 1024 * 1024
        self.max_bytes = max_bytes if max_bytes is not None else configured_max_bytes

    async def get_avatar(
        self,
        *,
        bot_id: UUID,
        token: str,
        telegram_bot_id: int,
    ) -> tuple[bytes, str]:
        cache_path = self._cache_path(bot_id)
        cached = await self._read_cache(cache_path, require_fresh=True)
        if cached is not None:
            return cached, "image/jpeg"

        lock = self._locks.setdefault(str(bot_id), asyncio.Lock())
        async with lock:
            cached = await self._read_cache(cache_path, require_fresh=True)
            if cached is not None:
                return cached, "image/jpeg"
            try:
                photo_bytes = await self._download_current_avatar(
                    token=token,
                    telegram_bot_id=telegram_bot_id,
                )
                await self._write_cache(cache_path, photo_bytes)
                return photo_bytes, "image/jpeg"
            except (BotAvatarUnavailableError, RuntimeError, httpx.HTTPError, ValueError) as exc:
                stale = await self._read_cache(cache_path, require_fresh=False)
                if stale is not None:
                    logger.warning(
                        "Telegram bot avatar refresh failed; serving stale cache "
                        "bot_id=%s error_type=%s",
                        bot_id,
                        type(exc).__name__,
                    )
                    return stale, "image/jpeg"
                raise BotAvatarUnavailableError("Bot profile photo is unavailable") from None

    async def invalidate(self, bot_id: UUID) -> None:
        await asyncio.to_thread(self._cache_path(bot_id).unlink, missing_ok=True)

    async def _download_current_avatar(
        self,
        *,
        token: str,
        telegram_bot_id: int,
    ) -> bytes:
        profile_photos = await self.sender.get_user_profile_photos(
            token,
            user_id=telegram_bot_id,
            limit=1,
        )
        photos = profile_photos.get("photos")
        if not isinstance(photos, list) or not photos or not isinstance(photos[0], list):
            raise BotAvatarUnavailableError("Bot has no profile photo")
        sizes = [item for item in photos[0] if isinstance(item, dict) and item.get("file_id")]
        if not sizes:
            raise BotAvatarUnavailableError("Telegram returned no usable profile photo")
        largest = max(
            sizes,
            key=lambda item: (
                int(item.get("width") or 0) * int(item.get("height") or 0),
                int(item.get("file_size") or 0),
            ),
        )
        file_info = await self.sender.get_file(token, str(largest["file_id"]))
        file_path = file_info.get("file_path")
        if not isinstance(file_path, str) or not file_path.strip():
            raise BotAvatarUnavailableError("Telegram returned no profile photo path")
        return await self.sender.download_file(
            token,
            file_path.strip(),
            max_bytes=self.max_bytes,
        )

    def _cache_path(self, bot_id: UUID) -> Path:
        return self.storage_root / f"{bot_id}.jpg"

    async def _read_cache(self, path: Path, *, require_fresh: bool) -> bytes | None:
        def read() -> bytes | None:
            if not path.is_file():
                return None
            if require_fresh and time.time() - path.stat().st_mtime > self.cache_seconds:
                return None
            payload = path.read_bytes()
            return payload if payload else None

        return await asyncio.to_thread(read)

    async def _write_cache(self, path: Path, payload: bytes) -> None:
        if not payload or len(payload) > self.max_bytes:
            raise BotAvatarUnavailableError("Bot profile photo exceeds the configured limit")

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
            try:
                temp_path.write_bytes(payload)
                temp_path.replace(path)
            finally:
                temp_path.unlink(missing_ok=True)

        await asyncio.to_thread(write)
