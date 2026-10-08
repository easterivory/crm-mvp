"""Database acceptance without replacing repositories or Telegram responses."""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.constants import SenderType
from app.models.base import Base
from app.models.bot import Bot
from app.models.chat import Chat
from app.models.funnel import Funnel, FunnelVersion, FunnelStep
from app.models.message import Message
from app.models.project import Project
from app.repositories.funnel_repository import FunnelRepository
from app.repositories.message_repository import MessageRepository
from app.services.funnel_disappearing_message_service import FunnelDisappearingMessageService, MARKER
from app.services.funnel_runtime_service import FunnelRuntimeService
from app.services.telegram_sender import TelegramSenderService


def test_legacy_and_sequence_config_are_opt_in():
    step = FunnelStep(config_json={"text": "Welcome"}, block_type="generic_message")
    assert FunnelRuntimeService._message_sequence(step)[0]["disappear_after_next"] is False
    step.config_json = {"text": "Welcome", "disappear_after_next": True}
    assert FunnelRuntimeService._message_sequence(step)[0]["disappear_after_next"] is True
    step.config_json = {"text": "Welcome", "disappear_after_next": "true"}
    assert FunnelRuntimeService._message_sequence(step)[0]["disappear_after_next"] is False
    step.config_json = {"messages": [{"text": "One", "disappear_after_next": True}, {"text": "Two"}]}
    assert FunnelRuntimeService._message_sequence(step) == step.config_json["messages"]


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
def test_real_database_screen_lifecycle_and_history():
    async def run():
        url = os.environ["CRM_TEST_POSTGRES_URL"]
        schema = "screens_" + uuid4().hex
        root = create_async_engine(url)
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
        try:
            async with root.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                now = datetime.now(timezone.utc)
                project = Project(name="Screens", slug="screens")
                db.add(project)
                await db.flush()
                bot = Bot(project_id=project.id, name="Screens", transport_type="bot_api")
                db.add(bot)
                await db.flush()
                chat = Chat(project_id=project.id, bot_id=bot.id, external_chat_id="100", external_user_id="100",
                    current_cycle_started_at=now-timedelta(hours=1))
                foreign = Chat(project_id=project.id, bot_id=bot.id, external_chat_id="101", external_user_id="101")
                funnel = Funnel(project_id=project.id, bot_id=bot.id, name="Screens")
                db.add_all([chat, foreign, funnel])
                await db.flush()
                version = FunnelVersion(funnel_id=funnel.id, version_number=1, status="published")
                db.add(version)
                await db.flush()
                step = FunnelStep(funnel_version_id=version.id, key="screen", title="Screen", step_type="message",
                    block_type="generic_message", config_json={"disappear_after_next": True})
                db.add(step)
                await db.flush()
                repo = FunnelRepository(db)
                state = await repo.upsert_chat_funnel_state(chat_id=chat.id, funnel_id=funnel.id,
                    funnel_version_id=version.id, current_step_id=step.id, entered_step_at=now,
                    waiting_for_answer=True, runtime_json={"last_answer": "keep"})
                def message(external_id, **values):
                    return Message(chat_id=chat.id, sender_type=SenderType.BOT,
                        external_message_id=external_id, body="Screen", created_at=now, **values)
                first, second = message("1"), message("2")
                expired = Message(chat_id=chat.id, sender_type=SenderType.BOT,
                    external_message_id="3", body="Old", created_at=now-timedelta(hours=49))
                user = Message(chat_id=chat.id, sender_type=SenderType.USER,
                    external_message_id="4", body="Answer", created_at=now)
                manager = Message(chat_id=chat.id, sender_type=SenderType.MANAGER,
                    external_message_id="5", body="Reply", created_at=now)
                db.add_all([first, second, expired, user, manager])
                await db.flush()
                service = FunnelDisappearingMessageService(db, TelegramSenderService(db))
                await service.after_delivery(chat=chat, message=first)
                assert MARKER not in state.runtime_json  # old funnels do not acquire a marker
                await service.after_delivery(chat=chat, message=first, disappear_after_next=True)
                assert state.runtime_json[MARKER] == str(first.id)
                assert state.runtime_json["last_answer"] == "keep"
                assert (await service.candidate(chat, str(first.id), now=now)).id == first.id
                for marker in (None, "broken", str(uuid4()), str(expired.id), str(user.id), str(manager.id)):
                    assert await service.candidate(chat, marker, now=now) is None
                assert await service.candidate(foreign, str(first.id), now=now) is None
                # No bot token is configured: exercise the real sender's refusal path.
                await service.after_delivery(chat=chat, message=second, disappear_after_next=True)
                assert first.deleted_at is None
                assert state.runtime_json[MARKER] == str(second.id)
                chat.current_cycle_started_at = now + timedelta(seconds=1)
                assert await service.candidate(chat, str(second.id), now=now) is None
                await service.after_delivery(chat=chat, message=second)
                assert MARKER not in state.runtime_json
                # Persisted Telegram deletion receipts remain visible only in history.
                first.raw_payload_json = {"funnel_screen_deleted": True, "replaced_by_message_id": str(second.id)}
                messages = MessageRepository(db)
                await messages.mark_deleted(message_id=first.id, deleted_at=now)
                await messages.mark_deleted(message_id=second.id, deleted_at=now)
                history = await messages.list_by_chat(chat.id, include_account_tombstones=True)
                assert first.id in {item.id for item in history}
                assert second.id not in {item.id for item in history}
                inputs = await messages.list_by_chat(chat.id)
                assert first.id not in {item.id for item in inputs}
                await db.commit()
        finally:
            await engine.dispose()
            async with root.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await root.dispose()
    asyncio.run(run())
