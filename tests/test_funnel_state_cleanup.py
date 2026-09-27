import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.repositories.funnel_repository import FunnelRepository

pytest.importorskip("aiosqlite")


@pytest.mark.parametrize("commit", [True, False])
def test_reset_detaches_all_jobs_with_foreign_keys_enforced(commit):
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        chat_id, other_chat_id, state_id, other_state_id = [uuid4() for _ in range(4)]
        statuses = ["pending", "running", "done", "failed", "cancelled"]
        try:
            async with engine.begin() as conn:
                await conn.execute(text("PRAGMA foreign_keys=ON"))
                await conn.execute(text("CREATE TABLE chat_funnel_states (id CHAR(32) PRIMARY KEY, chat_id CHAR(32))"))
                await conn.execute(text("CREATE TABLE funnel_scheduled_jobs (id INTEGER PRIMARY KEY, chat_id CHAR(32), funnel_state_id CHAR(32) REFERENCES chat_funnel_states(id), status TEXT, updated_at DATETIME)"))
                for chat, state in [(chat_id, state_id), (other_chat_id, other_state_id)]:
                    await conn.execute(text("INSERT INTO chat_funnel_states VALUES (:state,:chat)"), {"state": state.hex, "chat": chat.hex})
                    for status in statuses:
                        await conn.execute(text("INSERT INTO funnel_scheduled_jobs (chat_id,funnel_state_id,status) VALUES (:chat,:state,:status)"), {"chat": chat.hex, "state": state.hex, "status": status})
            async with async_sessionmaker(engine)() as db:
                await FunnelRepository(db).delete_chat_funnel_state(chat_id)
                if commit:
                    await db.commit()
                    # Repeated cleanup must also be safe.
                    await FunnelRepository(db).delete_chat_funnel_state(chat_id)
                    await db.commit()
                else:
                    await db.rollback()
                rows = (await db.execute(text("SELECT status, funnel_state_id FROM funnel_scheduled_jobs WHERE chat_id=:chat ORDER BY id"), {"chat": chat_id.hex})).all()
                expected = [("cancelled" if status in {"pending", "running"} else status, None) for status in statuses] if commit else [(status, state_id.hex) for status in statuses]
                assert rows == expected
                other = (await db.execute(text("SELECT status, funnel_state_id FROM funnel_scheduled_jobs WHERE chat_id=:chat ORDER BY id"), {"chat": other_chat_id.hex})).all()
                assert other == [(status, other_state_id.hex) for status in statuses]
                assert await db.scalar(text("SELECT count(*) FROM chat_funnel_states")) == (1 if commit else 2)
        finally:
            await engine.dispose()
    asyncio.run(run())
