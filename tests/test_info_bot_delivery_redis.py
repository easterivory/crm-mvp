"""Real Redis fencing and retained delivery checkpoints; no mocked clients."""
import asyncio
import json
import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from app.workers.info_bot import _checkpoint, OFFSET_SCRIPT, RELEASE_SCRIPT
from app.core.database import engine, get_db_session
from app.models.info_bot_delivery import InfoBotCursor, InfoBotDelivery
from app.repositories.info_bot_delivery_repository import InfoBotDeliveryRepository
from sqlalchemy import delete


@pytest.mark.skipif(not os.getenv("CRM_TEST_REDIS_URL") or not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable Redis and PostgreSQL required")
def test_info_bot_delivery_fencing_recovery_and_monotonic_offset():
    async def run():
        redis = Redis.from_url(os.environ["CRM_TEST_REDIS_URL"], decode_responses=True)
        assert engine.url.render_as_string(hide_password=False) == os.environ["CRM_TEST_POSTGRES_URL"]
        bot_id = uuid4().hex
        lock = "info-qa:poller:" + bot_id
        delivery, offset = lock + ":delivery:99", lock + ":offset"
        async with engine.begin() as db:
            await db.run_sync(lambda conn: InfoBotDelivery.__table__.create(conn, checkfirst=True))
            await db.run_sync(lambda conn: InfoBotCursor.__table__.create(conn, checkfirst=True))
        try:
            await redis.set(lock, "worker-a", ex=90)
            plan = {"chat_id": 1, "replies": [{"text": "Report"}], "sent": 0, "inflight": 0, "attempt_id": str(uuid4())}
            await _checkpoint(redis, lock, "worker-a", delivery, plan)
            assert json.loads(await redis.get(delivery))["inflight"] == 0
            # A replacement worker sees uncertainty rather than treating it as unsent.
            await redis.set(lock, "worker-b", ex=90)
            with pytest.raises(RuntimeError):
                await _checkpoint(redis, lock, "worker-a", delivery, {**plan, "sent": 1})
            assert json.loads(await redis.get(delivery))["sent"] == 0
            async with get_db_session() as db:
                with pytest.raises(RuntimeError):
                    await InfoBotDeliveryRepository(db).save_plan(bot_id, 99, {**plan, "attempt_id": str(uuid4())})
                await db.rollback()
            plan.pop("inflight"); plan["sent"] = 1
            await _checkpoint(redis, lock, "worker-b", delivery, plan)
            assert await redis.ttl(delivery) > 86000
            assert await redis.eval(OFFSET_SCRIPT, 2, lock, offset, "worker-b", 100) == 1
            assert await redis.eval(OFFSET_SCRIPT, 2, lock, offset, "worker-b", 90) == 1
            assert await redis.get(offset) == "100"
            assert await redis.eval(OFFSET_SCRIPT, 2, lock, offset, "worker-a", 110) == 0
            assert await redis.eval(RELEASE_SCRIPT, 1, lock, "worker-a") == 0
            assert await redis.get(lock) == "worker-b"
            async with get_db_session() as db:
                repo = InfoBotDeliveryRepository(db)
                await repo.save_offset(bot_id, 100)
                await repo.save_offset(bot_id, 90)
                await db.commit()
            await redis.delete(delivery, offset)
            async with get_db_session() as db:
                repo = InfoBotDeliveryRepository(db)
                assert (await repo.plan(bot_id, 99))["sent"] == 1
                assert await repo.offset(bot_id) == 100
        finally:
            await redis.delete(lock, delivery, offset)
            await redis.aclose()
            async with get_db_session() as db:
                await db.execute(delete(InfoBotDelivery).where(InfoBotDelivery.bot_id == bot_id))
                await db.execute(delete(InfoBotCursor).where(InfoBotCursor.bot_id == bot_id))
                await db.commit()
            await engine.dispose()
    asyncio.run(run())
