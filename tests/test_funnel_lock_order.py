"""Exercise runtime row locking with independent real PostgreSQL sessions."""
import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, Bot, Chat, Project
from app.models.funnel import ChatFunnelState, Funnel, FunnelScheduledJob, FunnelStep, FunnelVersion
from app.repositories.funnel_repository import FunnelRepository
from app.services.ai_delivery_state_service import AIDeliveryStateService
from app.services.funnel_runtime_service import FunnelRuntimeLockError, FunnelRuntimeService


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
def test_incoming_and_runtime_use_chat_before_state_after_transaction_boundaries():
    async def run():
        schema = "locks_" + uuid4().hex
        url = os.environ["CRM_TEST_POSTGRES_URL"]
        root = create_async_engine(url)
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with root.begin() as db:
                await db.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as db:
                await db.run_sync(Base.metadata.create_all)
            async with sessions() as db:
                project = Project(name="Lock QA", slug="lock-qa")
                db.add(project); await db.flush()
                bot = Bot(name="Bot", project_id=project.id)
                db.add(bot); await db.flush()
                funnel = Funnel(name="Funnel", project_id=project.id, bot_id=bot.id)
                db.add(funnel); await db.flush()
                version = FunnelVersion(funnel_id=funnel.id, version_number=1, status="published")
                db.add(version); await db.flush()
                step = FunnelStep(funnel_version_id=version.id, key="wait", title="Wait",
                                  step_type="message", block_type="message", config_json={},
                                  position_x=0, position_y=0)
                chat = Chat(project_id=project.id, bot_id=bot.id, external_chat_id="1", external_user_id="1")
                independent = Chat(project_id=project.id, bot_id=bot.id, external_chat_id="2", external_user_id="2")
                db.add_all([step, chat, independent]); await db.flush()
                db.add(ChatFunnelState(chat_id=chat.id, funnel_id=funnel.id,
                                      funnel_version_id=version.id, current_step_id=step.id,
                                      entered_step_at=datetime.now(timezone.utc), waiting_for_answer=True))
                await db.commit()
                chat_id, other_id, step_id = chat.id, independent.id, step.id

            for operation in ("read", "advisory", "runtime", "pause", "reset", "ai"):
                async with sessions() as incoming, sessions() as runtime, sessions() as observer:
                    await incoming.execute(update(Chat).where(Chat.id == chat_id).values(is_read=False))
                    pid = await runtime.scalar(text("SELECT pg_backend_pid()"))
                    repo = FunnelRepository(runtime)
                    operations = {
                        "read": lambda: repo.get_chat_funnel_state(chat_id),
                        "advisory": lambda: repo.lock_chat_for_runtime(chat_id),
                        "runtime": lambda: repo.update_chat_funnel_runtime(chat_id=chat_id, runtime_json={"qa": True}),
                        "pause": lambda: repo.set_chat_funnel_paused(chat_id=chat_id, is_paused=False),
                        "reset": lambda: repo.reset_chat_funnel_state(chat_id),
                        "ai": lambda: AIDeliveryStateService(runtime).current(chat_id, step_id),
                    }
                    task = asyncio.create_task(operations[operation]())
                    try:
                        async with asyncio.timeout(5):
                            while not await observer.scalar(text(
                                "SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :pid"
                            ), {"pid": pid}):
                                await asyncio.sleep(0.01)
                        # Runtime must not hold the state while waiting for the chat.
                        await incoming.execute(select(ChatFunnelState.id).where(
                            ChatFunnelState.chat_id == chat_id).with_for_update(nowait=True))
                        await incoming.execute(update(ChatFunnelState).where(
                            ChatFunnelState.chat_id == chat_id).values(runtime_json={"incoming": operation}))
                        # Another chat remains available; no project/global mutex.
                        async with sessions() as unrelated:
                            async with asyncio.timeout(2):
                                assert await FunnelRepository(unrelated).lock_chat_for_runtime(other_id)
                            await unrelated.rollback()
                        await incoming.commit()
                        result = await asyncio.wait_for(task, 5)
                        if operation == "read":
                            assert result.runtime_json == {"incoming": operation}
                        await runtime.commit()
                    finally:
                        if not task.done():
                            task.cancel()
                            await asyncio.gather(task, return_exceptions=True)
                        await incoming.rollback()
                        await runtime.rollback()

            # Force a real deadlock at entry. Only this pre-execution conflict
            # may be retried; no Telegram delivery has happened yet.
            async with sessions() as runtime, sessions() as blocker, sessions() as observer:
                await runtime.execute(text("SET deadlock_timeout = '50ms'"))
                await blocker.execute(text("SET deadlock_timeout = '10s'"))
                await runtime.execute(select(Chat.id).where(Chat.id == other_id).with_for_update())
                await blocker.execute(select(Chat.id).where(Chat.id == chat_id).with_for_update())
                pid = await runtime.scalar(text("SELECT pg_backend_pid()"))
                job = FunnelScheduledJob(chat_id=chat_id, step_id=step_id, job_type="resume_step")
                task = asyncio.create_task(FunnelRuntimeService(runtime).process_scheduled_job(job))
                other_task = None
                try:
                    async with asyncio.timeout(5):
                        while not await observer.scalar(text(
                            "SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :pid"
                        ), {"pid": pid}):
                            await asyncio.sleep(0.01)
                    other_task = asyncio.create_task(blocker.execute(
                        select(Chat.id).where(Chat.id == other_id).with_for_update()))
                    with pytest.raises(FunnelRuntimeLockError) as failure:
                        await asyncio.wait_for(task, 5)
                    assert failure.value.sqlstate == "40P01"
                    assert failure.value.chat_id == chat_id
                    await runtime.rollback()
                    await asyncio.wait_for(other_task, 5)
                    await blocker.rollback()
                finally:
                    for pending in (task, other_task):
                        if pending is not None and not pending.done():
                            pending.cancel()
                            await asyncio.gather(pending, return_exceptions=True)
                    await runtime.rollback()
                    await blocker.rollback()
        finally:
            await engine.dispose()
            async with root.begin() as db:
                await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await root.dispose()
    asyncio.run(run())
