"""Bounded lease expiry is maintenance, not a prerequisite for reading counters."""
import asyncio
import logging
from uuid import uuid4

from redis.exceptions import RedisError

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, TimeoutError as PoolTimeout

from app.core.database import get_db_session
from app.core.redis import get_redis
from app.models.project import Project
from app.services.chat_lease_service import ChatLeaseService

logger = logging.getLogger(__name__)
PROJECT_BATCH_SIZE = 8
INTERVAL_SECONDS = 30
PASS_TIMEOUT_SECONDS = 20
LOCK_SECONDS = 25
LOCK_KEY = "crm:chat-lease-maintenance:v1"
_RELEASE_LOCK = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"


async def maintain_chat_leases_once(ctx):
    token = uuid4().hex
    acquired = False
    redis = None
    try:
        async with asyncio.timeout(1):
            redis = await get_redis()
            acquired = bool(await redis.set(LOCK_KEY, token, nx=True, ex=LOCK_SECONDS))
        if acquired:
            async with asyncio.timeout(PASS_TIMEOUT_SECONDS):
                result = await maintain_chat_leases_task(ctx)
            if result["released"]:
                logger.info("Chat lease maintenance released projects=%s released=%s", result["projects"], result["released"])
            return result
    except (TimeoutError, RedisError, OSError) as exc:
        logger.warning("Chat lease maintenance unavailable phase=pass error_type=%s", type(exc).__name__)
    finally:
        if acquired:
            try:
                async with asyncio.timeout(1):
                    await redis.eval(_RELEASE_LOCK, 1, LOCK_KEY, token)
            except (TimeoutError, RedisError, OSError):
                pass


async def run_chat_lease_maintenance():
    ctx = {}
    logger.info("Chat lease maintenance started interval_seconds=%s pass_timeout_seconds=%s", INTERVAL_SECONDS, PASS_TIMEOUT_SECONDS)
    try:
        while True:
            try:
                await maintain_chat_leases_once(ctx)
            except Exception as exc:
                # Keep an unexpected maintenance failure separate from API readiness.
                logger.error("Chat lease maintenance failed error_type=%s", type(exc).__name__)
            await asyncio.sleep(INTERVAL_SECONDS)
    finally:
        logger.info("Chat lease maintenance stopped")


async def maintain_chat_leases_task(ctx):
    cursor = ctx.get("chat_lease_cursor")
    try:
        async with asyncio.timeout(2):
            async with get_db_session() as db:
                await db.execute(text("SET LOCAL statement_timeout = '1500ms'"))
                stmt = select(Project.id).where(Project.is_deleted.is_(False),
                    Project.status != "archived", Project.chat_lease_minutes > 0).order_by(Project.id).limit(PROJECT_BATCH_SIZE)
                ids = list((await db.scalars(stmt.where(Project.id > cursor) if cursor else stmt)).all())
                if not ids and cursor:
                    ids = list((await db.scalars(stmt)).all())
        ctx["chat_lease_cursor"] = ids[-1] if len(ids) == PROJECT_BATCH_SIZE else None
    except (TimeoutError, PoolTimeout, DBAPIError, OSError) as exc:
        logger.warning("Chat lease maintenance unavailable phase=projects error_type=%s", type(exc).__name__)
        return {"projects": 0, "released": 0}
    released = 0
    for pid in ids:
        try:
            async with asyncio.timeout(2):
                async with get_db_session() as db:
                    await db.execute(text("SET LOCAL statement_timeout = '1500ms'"))
                    await db.execute(text("SET LOCAL lock_timeout = '300ms'"))
                    count = await ChatLeaseService(db).release_expired(project_id=pid, limit=100)
                    await db.commit()
                    released += count
        except (TimeoutError, PoolTimeout, DBAPIError, OSError) as exc:
            logger.warning("Chat lease maintenance unavailable project_id=%s phase=release error_type=%s sqlstate=%s",
                pid, type(exc).__name__, getattr(getattr(exc, "orig", None), "sqlstate", None))
    return {"projects": len(ids), "released": released}
