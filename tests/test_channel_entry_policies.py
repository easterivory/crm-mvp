import asyncio
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models.chat import Chat
from app.models.channel_tracking import TelegramChannelSubscriptionEvent
from app.schemas.telegram import TelegramChatMemberUpdated
from app.services.channel_join_funnel_service import ChannelJoinFunnelService, entry_requests_restart


@pytest.mark.parametrize("payload,expected", [
    ({}, False), ({"_restart_funnel": False}, False),
    ({"_restart_funnel": True}, True),
    ({"_restart_funnel": True, "_restart_applied": True}, False),
])
def test_restart_requires_explicit_policy_and_only_applies_once(payload, expected):
    assert entry_requests_restart(payload) is expected


def test_telegram_request_origin_is_preserved():
    event = TelegramChatMemberUpdated.model_validate({
        "chat": {"id": -100123, "type": "channel"}, "date": 1, "via_join_request": True,
        "old_chat_member": {"status": "left", "user": {"id": 42, "first_name": "Lead"}},
        "new_chat_member": {"status": "member", "user": {"id": 42, "first_name": "Lead"}},
    })
    assert event.via_join_request
    assert event.model_dump()["via_join_request"]


def test_upgrade_defaults_and_downgrade_preserve_existing_channel():
    file = Path(__file__).parents[1] / "alembic/versions/20260926_0078_channel_start_options.py"
    spec = importlib.util.spec_from_file_location("channel_policy_migration", file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE telegram_channels (id INTEGER PRIMARY KEY)"))
            conn.execute(text("INSERT INTO telegram_channels VALUES (1)"))
            with Operations.context(MigrationContext.configure(conn)):
                module.upgrade()
                assert conn.execute(text("SELECT restart_funnel_on_rejoin, start_funnel_on_direct_join FROM telegram_channels")).one() == (0, 0)
                module.downgrade()
                assert conn.execute(text("SELECT * FROM telegram_channels")).one() == (1,)
    finally:
        engine.dispose()


def test_unknown_direct_join_is_skipped_without_creating_chat():
    pytest.importorskip("aiosqlite")
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Chat.__table__.create)
                await conn.execute(text("CREATE TABLE messages (chat_id CHAR(32), sender_type TEXT)"))
            async with async_sessionmaker(engine)() as db:
                event = TelegramChannelSubscriptionEvent(event_type="join", project_id=uuid4(), tracker_bot_id=uuid4(), telegram_user_id=42)
                result = await ChannelJoinFunnelService(db).start_for_join_request(event=event, user_chat_id=42)
                assert not result.started
                assert result.chat_id is None
                assert result.error.startswith("Пропуск:")
                assert await db.scalar(text("SELECT count(*) FROM chats")) == 0
        finally:
            await engine.dispose()
    asyncio.run(run())
