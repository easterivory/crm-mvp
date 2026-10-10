from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
from pathlib import Path
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db_session
from app.core.redis import get_redis
from app.models.chat import Chat
from app.models.project import Project
from app.repositories.bot_repository import BotRepository
from app.services.chat_avatar_cache import ChatAvatarCache, MAX_SOURCE_BYTES, avatar_thumbnail
from app.services.telegram_account_gateway import TelegramAccountGateway
from app.services.telegram_sender import TelegramSenderService

logger = logging.getLogger(__name__)


class ChatAvatarService:
    _downloads = asyncio.Semaphore(4)

    def __init__(self, db: AsyncSession):
        self.db = db
        self.cache = ChatAvatarCache(
            Path(settings.CHAT_AVATAR_STORAGE_PATH) / "thumbnails.sqlite3",
            max_bytes=settings.CHAT_AVATAR_CACHE_MAX_MB * 1024 * 1024,
            max_entries=settings.CHAT_AVATAR_CACHE_MAX_ENTRIES,
        )

    async def get_avatar(self, *, chat_id: UUID, project_id: UUID,
                         background_tasks: BackgroundTasks | None = None) -> bytes | None:
        row = (await self.db.execute(select(
            Chat.bot_id, Chat.external_user_id, Chat.external_chat_id,
        ).join(Project, Project.id == Chat.project_id).where(
            Chat.id == chat_id, Chat.project_id == project_id,
            Chat.is_deleted.is_(False), Chat.reset_at.is_(None), Project.is_deleted.is_(False),
        ))).one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        bot_id, user_id, external_chat_id = row
        key = hashlib.sha256(f"{project_id}:{bot_id}:{user_id}:{external_chat_id}".encode()).hexdigest()
        # Snapshot scalars, then finish DB work before any external request.
        await self.db.commit()
        cached = None
        try:
            cached = await self.cache.get(key)
            if cached is not None and cached[1]:
                return cached[0]
            if cached and cached[0] and background_tasks is not None:
                background_tasks.add_task(refresh_chat_avatar, chat_id, project_id)
                return cached[0]
            async with asyncio.timeout(25):
                redis = await get_redis()
                lock = redis.lock(f"crm:chat-avatar:{key}", timeout=35, blocking=False)
                if not await lock.acquire():
                    return cached[0] if cached else None
                try:
                    async with self._downloads:
                        cached = await self.cache.get(key)
                        if cached is not None and cached[1]:
                            return cached[0]
                        repo = BotRepository(self.db)
                        transport = await repo.get_transport_type(bot_id, project_id) if bot_id else None
                        token = await repo.get_bot_token_by_id(bot_id, project_id) if bot_id and transport == "bot_api" else None
                        await self.db.commit()
                        try:
                            content = await self._fetch(transport, token, bot_id, user_id, external_chat_id)
                        except Exception as exc:
                            logger.info("Chat avatar unavailable chat_id=%s error_type=%s", chat_id, type(exc).__name__)
                            content = cached[0] if cached else None
                            await self.cache.put(key, content, ttl=300)
                            return content
                        await self.cache.put(key, content, ttl=max(60, settings.CHAT_AVATAR_CACHE_SECONDS))
                        return content
                finally:
                    try:
                        await lock.release()
                    except Exception:
                        pass
        except Exception as exc:
            logger.info("Chat avatar cache unavailable chat_id=%s error_type=%s", chat_id, type(exc).__name__)
            return cached[0] if cached else None

    async def _fetch(self, transport, token, bot_id, user_id, external_chat_id) -> bytes | None:
        if transport == "user_mtproto" and bot_id:
            result = await TelegramAccountGateway().invoke(
                bot_id=bot_id, operation="get_chat_avatar",
                payload={"external_chat_id": external_chat_id}, timeout_seconds=15,
            )
            encoded = result.get("content")
            if not encoded:
                return None
            if not isinstance(encoded, str) or len(encoded) > 100000:
                raise ValueError("Avatar response exceeds limit")
            return await asyncio.to_thread(avatar_thumbnail, base64.b64decode(encoded, validate=True))
        if transport != "bot_api" or not token or not str(user_id).isdigit():
            return None
        sender = TelegramSenderService(self.db)
        photos = (await sender.get_user_profile_photos(token, user_id=int(user_id), limit=1)).get("photos")
        if not photos:
            return None
        sizes = [item for item in photos[0] if isinstance(item, dict) and item.get("file_id")]
        if not sizes:
            return None
        smallest = min(sizes, key=lambda item: int(item.get("width") or 0) * int(item.get("height") or 0))
        info = await sender.get_file(token, smallest["file_id"])
        content = await sender.download_file(token, info["file_path"], max_bytes=MAX_SOURCE_BYTES)
        return await asyncio.to_thread(avatar_thumbnail, content)


async def refresh_chat_avatar(chat_id: UUID, project_id: UUID) -> None:
    try:
        async with get_db_session() as db:
            await ChatAvatarService(db).get_avatar(chat_id=chat_id, project_id=project_id)
    except Exception as exc:
        logger.info("Chat avatar background refresh unavailable chat_id=%s error_type=%s", chat_id, type(exc).__name__)
