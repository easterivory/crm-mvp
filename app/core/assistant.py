"""Shared policy, redaction primitives and a small, separately bounded DB pool."""
import hashlib
import asyncio
import json
from contextlib import asynccontextmanager
from uuid import uuid4
from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.services.access_control import require_project_access

SCOPES = frozenset({"crm.catalog.read", "crm.analytics.read", "crm.configuration.read",
    "crm.diagnostics.read", "crm.leads.summary.read", "crm.changes.prepare"})


def now(): return datetime.now(timezone.utc)


def digest(value):
    if not isinstance(value, str): value = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


def fail(code, status=403): raise HTTPException(status, code)


def enabled(mcp=False, changes=False):
    if not settings.ASSISTANT_ENABLED or mcp and not settings.ASSISTANT_MCP_ENABLED: fail("assistant_disabled", 404)
    if changes and not settings.ASSISTANT_CHANGES_ENABLED: fail("changes_disabled")


def user_policy(user):
    enabled()
    if user is None or user.is_deleted or user.role_name != "super_admin" or str(user.id) not in {s.strip() for s in settings.ASSISTANT_ALLOWED_USER_IDS.split(",")}:
        fail("assistant_access_denied")


def project_policy(user, project_id, connection=None):
    user_policy(user)
    if str(project_id) not in {s.strip() for s in settings.ASSISTANT_ALLOWED_PROJECT_IDS.split(",")}: fail("project_not_granted")
    require_project_access(user, project_id)
    if connection is not None and str(project_id) not in connection.project_ids: fail("project_not_granted")


def connection_policy(user, connection, scope=None, project_id=None):
    user_policy(user)
    if connection is None or connection.user_id != user.id or connection.revoked_at: fail("connection_revoked")
    if connection.resource != resource_url() or connection.issuer != issuer_url(): fail("invalid_token_resource", 401)
    if scope and scope not in connection.scopes: fail("scope_not_granted")
    if project_id: project_policy(user, project_id, connection)


def resource_url():
    value = settings.ASSISTANT_MCP_RESOURCE_URL.rstrip("/")
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        fail("assistant_resource_not_configured", 503)
    return value


def issuer_url():
    parts = urlsplit(settings.BASE_URL)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        fail("assistant_issuer_not_configured", 503)
    return settings.BASE_URL.rstrip("/") + "/assistant-oauth"


def safe_url(value):
    try:
        from urllib.parse import parse_qsl
        parts = urlsplit(value)
        return {"host": parts.hostname, "query_parameters": sorted({k for k, _ in parse_qsl(parts.query)})}
    except (ValueError, TypeError): return {"configured": bool(value)}


@lru_cache(maxsize=1)
def session_factory():
    engine = create_async_engine(settings.DATABASE_URL, pool_size=2, max_overflow=0, pool_timeout=2,
        pool_pre_ping=True, hide_parameters=True)
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def close_assistant_db():
    if session_factory.cache_info().currsize:
        engine = session_factory().kw["bind"]
        session_factory.cache_clear()
        await engine.dispose()


async def assistant_db():
    enabled()
    async with session_factory()() as db:
        try:
            await db.execute(text("SET LOCAL statement_timeout = '3000ms'"))
            await db.execute(text("SET LOCAL lock_timeout = '1000ms'"))
            yield db
            await db.commit()
        except BaseException:
            await db.rollback()
            raise


async def limit(key, count, seconds):
    from app.core.redis import get_redis
    try:
        redis = await get_redis()
        value = await redis.eval("local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n", 1,
            "crm:assistant:" + key, seconds)
    except Exception: fail("assistant_limiter_unavailable", 503)
    if value > count: fail("rate_limited", 429)


async def cached_report(key, value=None):
    from app.core.redis import get_redis
    async def operation():
        redis = await get_redis()
        full_key = "crm:assistant:report:" + key
        if value is not None:
            payload = json.dumps(value)
            if len(payload.encode()) <= 65536: await redis.set(full_key, payload, ex=30)
            return None
        payload = await redis.get(full_key)
        if payload and len(payload) <= 65536:
            parsed = json.loads(payload)
            if isinstance(parsed, dict): return parsed
        return None
    try: return await asyncio.wait_for(operation(), timeout=0.15)
    except Exception: return None  # Cache misses still use the bounded query path.


@asynccontextmanager
async def heavy_lease():
    from app.core.redis import get_redis
    key, ticket = "crm:assistant:heavy", uuid4().hex
    try:
        redis = await get_redis()
        acquired = await redis.eval("redis.call('ZREMRANGEBYSCORE',KEYS[1],'-inf',ARGV[1]); if redis.call('ZCARD',KEYS[1])>=2 then return 0 end; redis.call('ZADD',KEYS[1],ARGV[2],ARGV[3]); redis.call('EXPIRE',KEYS[1],20); return 1", 1,
            key, now().timestamp(), now().timestamp() + 15, ticket)
    except Exception: fail("assistant_limiter_unavailable", 503)
    if not acquired: fail("rate_limited", 429)
    try: yield
    finally:
        try: await redis.zrem(key, ticket)
        except Exception: pass
