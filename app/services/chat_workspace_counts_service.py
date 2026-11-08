"""Bounded counter refreshes; HTTP readers never compete for the SQL slot."""
import asyncio
import copy
import hashlib
import json
import logging
import math
import time
import weakref
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import DBAPIError, TimeoutError as PoolTimeout

from app.core.redis import get_redis
from app.core.telegram_intake import get_count_db_session
from app.repositories.chat_repository import ChatRepository

logger = logging.getLogger(__name__)
FIELDS = {"priority", "unread", "unanswered", "mine", "all", "favorites"}
CACHE_SECONDS = 15
SNAPSHOT_MAX_AGE_SECONDS = 60
FAILURE_COOLDOWN_SECONDS = 3
FOLLOWER_WAIT_SECONDS = 6
MAX_REFRESHES = 16
MAX_LOCAL_SNAPSHOTS = 128
_states = weakref.WeakKeyDictionary()


def _decode(raw):
    try:
        data = json.loads(raw)
        if (isinstance(data, dict) and set(data) == {"totals", "managers", "unassigned"}
            and isinstance(data["totals"], dict) and set(data["totals"]) == FIELDS - {"mine"}
            and isinstance(data["managers"], dict)
            and all(type(v) is int and v >= 0 for v in [*data["totals"].values(), *data["managers"].values(), data["unassigned"]])):
            return data
    except (TypeError, ValueError):
        pass
    return None


@dataclass(frozen=True)
class Snapshot:
    counts: dict
    as_of: float

    @property
    def age(self):
        return time.time() - self.as_of

    @property
    def valid(self):
        return 0 <= self.age <= SNAPSHOT_MAX_AGE_SECONDS


@dataclass
class RefreshState:
    admission: asyncio.Lock = field(default_factory=asyncio.Lock)
    tasks: dict = field(default_factory=dict)
    snapshots: OrderedDict = field(default_factory=OrderedDict)
    failures: OrderedDict = field(default_factory=OrderedDict)
    stopping: bool = False

    def remember(self, key, snapshot):
        old = self.snapshots.get(key)
        if old is None or snapshot.as_of >= old.as_of:
            self.snapshots[key] = snapshot
            self.snapshots.move_to_end(key)
        while len(self.snapshots) > MAX_LOCAL_SNAPSHOTS:
            self.snapshots.popitem(last=False)


def _state():
    loop = asyncio.get_running_loop()
    if loop not in _states:
        _states[loop] = RefreshState()
    return _states[loop]


async def _redis():
    try:
        return await asyncio.wait_for(get_redis(), 0.1)
    except Exception:
        return None


async def _snapshot(state, key, redis):
    snapshot = state.snapshots.get(key)
    if snapshot is not None and not snapshot.valid:
        state.snapshots.pop(key, None)
        snapshot = None
    if redis is not None:
        try:
            raw = json.loads(await asyncio.wait_for(redis.get(key), 0.1))
            stamp = raw["as_of"]
            counts = _decode(json.dumps(raw["counts"]))
            if type(stamp) in (int, float) and math.isfinite(stamp) and counts is not None:
                cached = Snapshot(counts, stamp)
                if cached.valid and (snapshot is None or cached.as_of > snapshot.as_of):
                    state.remember(key, cached)
                    snapshot = cached
        except Exception:
            pass  # Local snapshots and admission remain bounded during Redis outages.
    return snapshot


async def _cooling(state, key, redis):
    if state.failures.get(key, 0) > time.monotonic():
        return True
    if redis is not None:
        try:
            return bool(await asyncio.wait_for(redis.get(key + ":error"), 0.1))
        except Exception:
            pass
    return False


async def _refresh(state, key, arguments, force):
    started, phase = time.monotonic(), "admission"
    phase_started, timings = started, {}
    redis, locked, ticket = None, False, uuid4().hex
    remote_wait = False
    try:
        # Queued scopes hold no DB connection. The FIFO gate is outside the pool,
        # so another project cannot hit its 0.5s checkout timeout behind a scan.
        async with state.admission:
            timings[phase] = round((time.monotonic() - phase_started) * 1000)
            redis = await _redis()
            previous = await _snapshot(state, key, redis)
            if previous is not None and previous.age <= CACHE_SECONDS and not force:
                return previous
            if await _cooling(state, key, redis):
                return None
            if redis is not None:
                try:
                    locked = bool(await asyncio.wait_for(redis.set(key + ":lock", ticket, nx=True, ex=10), 0.1))
                except Exception:
                    redis = None
                else:
                    remote_wait = not locked
            if not remote_wait:
                phase, phase_started = "counter_pool", time.monotonic()
                async with asyncio.timeout(4):
                    async with get_count_db_session() as db:
                        await db.connection()
                        timings[phase] = round((time.monotonic() - phase_started) * 1000)
                        phase, phase_started = "aggregate", time.monotonic()
                        as_of = time.time()
                        counts = await ChatRepository(db).shared_workspace_counts(**arguments)
                timings[phase] = round((time.monotonic() - phase_started) * 1000)
                snapshot = Snapshot(counts, as_of)
                state.remember(key, snapshot)
                state.failures.pop(key, None)
                if redis is not None:
                    try:
                        await asyncio.wait_for(redis.set(key, json.dumps({"counts": counts, "as_of": as_of}),
                            ex=SNAPSHOT_MAX_AGE_SECONDS), 0.1)
                    except Exception:
                        pass
                elapsed = round((time.monotonic() - started) * 1000)
                if elapsed >= 1000:
                    logger.warning("Chat counters slow project_id=%s scope=%s elapsed_ms=%s phases_ms=%s",
                        arguments["project_id"], key[-12:], elapsed, timings)
                return snapshot
        # A peer owns this scope, but does not consume this process's SQL slot.
        # Wait outside admission so unrelated projects can still refresh.
        phase, phase_started = "peer_refresh", time.monotonic()
        deadline = time.monotonic() + 4.5
        while time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            snapshot = await _snapshot(state, key, redis)
            if snapshot is not None and (previous is None or snapshot.as_of > previous.as_of):
                return snapshot
            if await _cooling(state, key, redis):
                return None
        return None
    except (TimeoutError, PoolTimeout, DBAPIError, OSError) as exc:
        state.failures[key] = time.monotonic() + FAILURE_COOLDOWN_SECONDS
        state.failures.move_to_end(key)
        while len(state.failures) > MAX_LOCAL_SNAPSHOTS:
            state.failures.popitem(last=False)
        if redis is not None:
            try:
                await asyncio.wait_for(redis.set(key + ":error", "1", ex=FAILURE_COOLDOWN_SECONDS), 0.1)
            except Exception:
                pass
        logger.warning("Chat counters temporarily unavailable project_id=%s scope=%s phase=%s elapsed_ms=%s phase_ms=%s error_type=%s sqlstate=%s phases_ms=%s",
            arguments["project_id"], key[-12:], phase, round((time.monotonic() - started) * 1000),
            round((time.monotonic() - phase_started) * 1000), type(exc).__name__,
            getattr(getattr(exc, "orig", None), "sqlstate", None), timings)
        return None
    finally:
        if redis is not None and locked:
            try:
                await asyncio.wait_for(redis.eval("if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0",
                    1, key + ":lock", ticket), 0.1)
            except Exception:
                pass


def _schedule(state, key, arguments, force):
    existing = state.tasks.get(key)
    if existing is not None and not existing.done():
        return existing
    state.tasks.pop(key, None)
    if state.stopping or len(state.tasks) >= MAX_REFRESHES:
        return None
    task = asyncio.create_task(_refresh(state, key, arguments, force))
    state.tasks[key] = task
    def finished(done):
        if state.tasks.get(key) is done:
            state.tasks.pop(key, None)
        if not done.cancelled() and done.exception() is not None:
            logger.error("Chat counter refresh failed scope=%s error_type=%s", key[-12:], type(done.exception()).__name__)
    task.add_done_callback(finished)
    return task


async def close_counter_refreshes():
    state = _states.pop(asyncio.get_running_loop(), None)
    if state is not None:
        state.stopping = True
        tasks = list(state.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def workspace_counts(db, project, actor, bot_id, bot_ids, *, refresh=False):
    selected_bots = sorted(set(bot_ids or []), key=str)
    if bot_id is None and len(selected_bots) == 1:
        bot_id, selected_bots = selected_bots[0], []
    elif bot_id is not None and (not selected_bots or bot_id in selected_bots):
        selected_bots = []
    arguments = dict(project_id=project.id, priority_rules=copy.deepcopy(project.priority_chat_rules),
        project_format=project.project_format, push_unread_threshold=project.push_unread_threshold,
        use_confidence_score=project.use_confidence_score, bot_id=bot_id,
        bot_ids=selected_bots)
    viewer_id, hide_assigned = str(actor.id), project.hide_assigned_chats_from_all
    key = "crm:chat-counts:v2:" + hashlib.sha256(json.dumps({**arguments, "project_revision": str(project.updated_at)},
        default=str, sort_keys=True).encode()).hexdigest()
    await db.commit()  # Release authentication/project reads before cache or queue waits.
    state, redis = _state(), await _redis()
    snapshot = await _snapshot(state, key, redis)
    cooling = await _cooling(state, key, redis)
    task = None
    if not cooling and (refresh or snapshot is None or snapshot.age > CACHE_SECONDS):
        task = _schedule(state, key, arguments, refresh)
    if task is not None and (snapshot is None or refresh):
        # Cancellation of a reader must not cancel a shared refresh.
        done, _ = await asyncio.wait({task}, timeout=FOLLOWER_WAIT_SECONDS)
        if done:
            task.result()
            snapshot = await _snapshot(state, key, redis)
            cooling = await _cooling(state, key, redis)
    if snapshot is None or not snapshot.valid:
        raise HTTPException(503, "Счётчики обновляются. Повторите запрос.", headers={"Retry-After": "2"})
    pending = key in state.tasks and not state.tasks[key].done()
    mine = snapshot.counts["managers"].get(viewer_id, 0)
    return {**snapshot.counts["totals"], "mine": mine,
        "all": snapshot.counts["unassigned"] + mine if hide_assigned else snapshot.counts["totals"]["all"],
        "counts_as_of": datetime.fromtimestamp(snapshot.as_of, timezone.utc),
        "counts_stale": snapshot.age > CACHE_SECONDS or cooling or pending,
        "counts_refreshing": pending}
