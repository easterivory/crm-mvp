"""Real image/cache/database checks without Telegram or repository mocks."""
import asyncio
import hashlib
import io
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, HTTPException
from PIL import Image
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, Bot, Chat, Project
from app.services.chat_avatar_cache import ChatAvatarCache, avatar_thumbnail
from app.services.chat_avatar_service import ChatAvatarService


def image_bytes():
    image = Image.new("RGBA", (640, 320), (20, 130, 70, 128))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_avatar_thumbnail_is_small_safe_jpeg_without_original_metadata():
    thumbnail = avatar_thumbnail(image_bytes())
    with Image.open(io.BytesIO(thumbnail)) as image:
        assert image.format == "JPEG"
        assert image.size == (128, 64)
        assert image.mode == "RGB"
        assert not image.getexif()
    assert len(thumbnail) < 64 * 1024
    with pytest.raises((ValueError, OSError)):
        avatar_thumbnail(b"not an image")
    with pytest.raises(ValueError):
        avatar_thumbnail(b"x" * (2 * 1024 * 1024 + 1))


def test_cache_expiry_negative_cache_lru_retention_and_disk_bound(tmp_path):
    async def run():
        path = tmp_path / "cache.sqlite3"
        cache = ChatAvatarCache(path, max_bytes=2 * 1024 * 1024, max_entries=3)
        content = avatar_thumbnail(image_bytes())
        assert await cache.get("absent") is None
        await cache.put("no-photo", None, ttl=86400)
        assert await cache.get("no-photo") == (None, True)
        await cache.put("old", content, ttl=-1)
        assert await cache.get("old") == (content, False)
        await cache.put("new", content, ttl=86400)
        await cache.put("fourth", content, ttl=86400)
        assert await cache.get("fourth") == (content, True)
        assert await cache.get("no-photo") is None
        assert await cache.get("new") == (content, True)
        with sqlite3.connect(path) as connection:
            assert connection.execute("SELECT count(*) FROM avatars").fetchone()[0] <= 3
            connection.execute("UPDATE avatars SET accessed=? WHERE key='fourth'", (time.time() - 31 * 86400,))
        assert await cache.get("fourth") is None
        # Different service instances share the same bounded SQLite cache.
        second = ChatAvatarCache(path, max_bytes=2 * 1024 * 1024, max_entries=3)
        await asyncio.gather(*(second.put(str(i), content, ttl=86400) for i in range(20)))
        with sqlite3.connect(path) as connection:
            assert connection.execute("SELECT count(*) FROM avatars").fetchone()[0] <= 3
        assert path.stat().st_size <= 2 * 1024 * 1024
        with pytest.raises(ValueError):
            await cache.put("oversized", b"x" * (64 * 1024 + 1), ttl=60)
    asyncio.run(run())


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
def test_cached_avatar_scope_and_chat_state_are_read_only(tmp_path):
    async def run():
        url = os.environ["CRM_TEST_POSTGRES_URL"]
        schema = "avatars_" + uuid4().hex
        root = create_async_engine(url)
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
        try:
            async with root.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                project = Project(name="Avatars", slug="avatars")
                db.add(project)
                await db.flush()
                bot = Bot(name="No network calls", project_id=project.id)
                db.add(bot)
                await db.flush()
                chat = Chat(project_id=project.id, bot_id=bot.id, external_chat_id="123",
                            external_user_id="123", is_read=False)
                db.add(chat)
                await db.commit()
                service = ChatAvatarService(db)
                service.cache = ChatAvatarCache(Path(tmp_path) / "avatars.sqlite3", max_bytes=1024 * 1024)
                key = hashlib.sha256(f"{project.id}:{bot.id}:123:123".encode()).hexdigest()
                thumbnail = avatar_thumbnail(image_bytes())
                await service.cache.put(key, thumbnail, ttl=86400)
                assert await service.get_avatar(chat_id=chat.id, project_id=project.id) == thumbnail
                with pytest.raises(HTTPException) as denied:
                    await service.get_avatar(chat_id=chat.id, project_id=uuid4())
                assert denied.value.status_code == 404
                await service.cache.put(key, thumbnail, ttl=-1)
                background = BackgroundTasks()
                assert await service.get_avatar(chat_id=chat.id, project_id=project.id, background_tasks=background) == thumbnail
                assert len(background.tasks) == 1
                await db.refresh(chat)
                assert chat.is_read is False
                assert chat.assignment_expires_at is None
                assert chat.last_read_at is None
                assert chat.last_message_at is None
                assert await db.scalar(select(Base.metadata.tables["chat_funnel_states"].c.id)) is None
                chat.reset_at = datetime.now(timezone.utc)
                await db.flush()
                with pytest.raises(HTTPException):
                    await service.get_avatar(chat_id=chat.id, project_id=project.id)
        finally:
            await engine.dispose()
            async with root.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await root.dispose()
    asyncio.run(run())
