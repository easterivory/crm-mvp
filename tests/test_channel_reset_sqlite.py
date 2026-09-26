"""Exercise actual reset-chat lookup and reactivation against a local database."""
import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

pytest.importorskip("aiosqlite")

from app.models.chat import Chat
from app.models.channel_tracking import TelegramChannelSubscriptionEvent
from app.services.channel_join_funnel_service import ChannelJoinFunnelService


@pytest.mark.parametrize("mode", ["reset", "active", "deleted"])
def test_existing_identity_never_inserts_duplicate(mode):
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Chat.__table__.create)
            await connection.execute(text("CREATE TABLE funnel_scheduled_jobs (chat_id CHAR(32), status TEXT, updated_at DATETIME)"))
            await connection.execute(text("CREATE TABLE chat_funnel_states (chat_id CHAR(32))"))
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                now = datetime.now(timezone.utc)
                chat = Chat(id=uuid4(), project_id=uuid4(), bot_id=uuid4(), external_chat_id="42", external_user_id="42",
                            reset_at=now if mode == "reset" else None, is_deleted=mode == "deleted", created_at=now, updated_at=now)
                db.add(chat)
                await db.commit()
                await db.execute(text("INSERT INTO funnel_scheduled_jobs VALUES (:chat,'pending',CURRENT_TIMESTAMP)"), {"chat": chat.id.hex})
                event = TelegramChannelSubscriptionEvent(project_id=chat.project_id, tracker_bot_id=chat.bot_id,
                                                        telegram_user_id=42, first_name="Lead", tracking_link_id=None)
                found = await ChannelJoinFunnelService(db)._ensure_chat(event=event, user_chat_id=42)
                await db.commit()
                assert found.id == chat.id
                assert len((await db.scalars(select(Chat))).all()) == 1
                assert found.is_deleted == (mode == "deleted")
                if mode == "reset":
                    assert found.reset_at is None
                    assert found.current_cycle_started_at is not None
                    assert await db.scalar(text("SELECT status FROM funnel_scheduled_jobs")) == "cancelled"
                else:
                    assert await db.scalar(text("SELECT status FROM funnel_scheduled_jobs")) == "pending"
        finally:
            await engine.dispose()
    asyncio.run(run())
