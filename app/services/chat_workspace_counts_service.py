"""Coalesce short-lived UI counters without holding a general DB connection."""
import asyncio
import hashlib
import json
import logging
import time
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import DBAPIError, TimeoutError as PoolTimeout

from app.core.redis import get_redis
from app.core.telegram_intake import get_count_db_session
from app.repositories.chat_repository import ChatRepository

logger = logging.getLogger(__name__)
FIELDS = {"priority", "unread", "unanswered", "mine", "all", "favorites"}
CACHE_SECONDS = 5
FAILURE_COOLDOWN_SECONDS = 3
FOLLOWER_WAIT_SECONDS = 6


def _decode(raw):
    try:
        data = json.loads(raw)
        if (isinstance(data, dict) and set(data) == {"totals", "managers", "unassigned"}
            and isinstance(data["totals"], dict) and set(data["totals"]) == FIELDS - {"mine"}
            and isinstance(data["managers"], dict)
            and all(type(v) is int and v >= 0 for v in [*data["totals"].values(), *data["managers"].values(), data["unassigned"]])): return data
    except (TypeError, ValueError): pass
    return None


async def workspace_counts(db, project, actor, bot_id, bot_ids, release_expired):
    started = time.monotonic()
    arguments = dict(project_id=project.id,
        priority_rules=project.priority_chat_rules, project_format=project.project_format,
        push_unread_threshold=project.push_unread_threshold, use_confidence_score=project.use_confidence_score,
        bot_id=bot_id, bot_ids=sorted(set(bot_ids or []), key=str))
    viewer_id, hide_assigned = str(actor.id), project.hide_assigned_chats_from_all
    def personal(data):
        mine = data["managers"].get(viewer_id, 0)
        return {**data["totals"], "mine": mine,
            "all": data["unassigned"] + mine if hide_assigned else data["totals"]["all"]}
    key = "crm:chat-counts:v1:" + hashlib.sha256(json.dumps({**arguments, "project_revision": str(project.updated_at)},
        default=str, sort_keys=True).encode()).hexdigest()
    ticket = uuid4().hex
    # Authentication/project reads have finished. Followers must not occupy the
    # API pool while waiting for the same aggregate to finish in another request.
    await db.commit()
    redis, locked = None, False
    try:
        redis = await get_redis()
        raw = await asyncio.wait_for(redis.get(key), 0.1)
        cached = _decode(raw)
        if cached is not None: return personal(cached)
        if await asyncio.wait_for(redis.get(key + ":error"), 0.1):
            raise HTTPException(503, "Счётчики временно недоступны. Повторите запрос.", headers={"Retry-After": "3"})
        locked = bool(await asyncio.wait_for(redis.set(key + ":lock", ticket, nx=True, ex=7), 0.1))
        if not locked:
            deadline = time.monotonic() + FOLLOWER_WAIT_SECONDS
            while time.monotonic() < deadline:
                await asyncio.sleep(0.05)
                cached = _decode(await asyncio.wait_for(redis.get(key), 0.1))
                if cached is not None: return personal(cached)
                if await asyncio.wait_for(redis.get(key + ":error"), 0.1):
                    raise HTTPException(503, "Счётчики временно недоступны. Повторите запрос.", headers={"Retry-After": "3"})
            raise HTTPException(503, "Счётчики обновляются. Повторите запрос.", headers={"Retry-After": "1"})
    except HTTPException: raise
    except Exception:
        redis = None  # The dedicated one-connection pool also bounds cache outages.
    phase = "lease_cleanup"
    phase_started = time.monotonic()
    timings = {}
    try:
        async with asyncio.timeout(2):
            await release_expired(project_id=project.id, limit=100)
            await db.commit()
        timings[phase] = round((time.monotonic() - phase_started) * 1000)
        phase, phase_started = "counter_pool", time.monotonic()
        async with asyncio.timeout(4):
            async with get_count_db_session() as count_db:
                await count_db.connection()
                timings[phase] = round((time.monotonic() - phase_started) * 1000)
                phase, phase_started = "aggregate", time.monotonic()
                counts = await ChatRepository(count_db).shared_workspace_counts(**arguments)
        timings[phase] = round((time.monotonic() - phase_started) * 1000)
        if redis is not None:
            try: await asyncio.wait_for(redis.set(key, json.dumps(counts), ex=CACHE_SECONDS), 0.1)
            except Exception: pass
        elapsed_ms = round((time.monotonic() - started) * 1000)
        if elapsed_ms >= 1000:
            logger.warning("Chat counters slow project_id=%s elapsed_ms=%s phases_ms=%s", arguments["project_id"], elapsed_ms, timings)
        return personal(counts)
    except (TimeoutError, PoolTimeout, DBAPIError, OSError) as exc:
        await db.rollback()
        if redis is not None:
            try: await asyncio.wait_for(redis.set(key + ":error", "1", ex=FAILURE_COOLDOWN_SECONDS), 0.1)
            except Exception: pass
        original = getattr(exc, "orig", None)
        logger.warning("Chat counters temporarily unavailable project_id=%s phase=%s elapsed_ms=%s phase_ms=%s error_type=%s sqlstate=%s phases_ms=%s",
            arguments["project_id"], phase, round((time.monotonic() - started) * 1000),
            round((time.monotonic() - phase_started) * 1000), type(exc).__name__,
            getattr(original, "sqlstate", None), timings)
        raise HTTPException(503, "Счётчики временно недоступны. Повторите запрос.", headers={"Retry-After": "1"}) from exc
    finally:
        if redis is not None and locked:
            try:
                await asyncio.wait_for(redis.eval("if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0",
                    1, key + ":lock", ticket), 0.1)
            except Exception: pass
