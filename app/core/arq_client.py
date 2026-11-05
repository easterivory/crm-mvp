"""A bounded producer pool per event loop; workers own their ARQ consumer pools."""
import asyncio
from contextlib import suppress
from weakref import WeakKeyDictionary

from arq.connections import ArqRedis
from redis.asyncio import ConnectionPool

from app.core.config import settings

_clients: WeakKeyDictionary = WeakKeyDictionary()


def get_arq_client() -> ArqRedis:
    loop = asyncio.get_running_loop()
    entry = _clients.get(loop)
    if entry is None:
        pool = ConnectionPool.from_url(
            settings.REDIS_URL,
            max_connections=settings.RUNTIME_REDIS_MAX_CONNECTIONS,
            socket_connect_timeout=settings.RUNTIME_REDIS_TIMEOUT_SECONDS,
            socket_timeout=settings.RUNTIME_REDIS_TIMEOUT_SECONDS,
            retry_on_timeout=False,
        )
        client = ArqRedis(pool_or_conn=pool)
        entry = (client, pool)
        _clients[loop] = entry
    return entry[0]


async def close_arq_client() -> None:
    entry = _clients.pop(asyncio.get_running_loop(), None)
    if entry is not None:
        client, pool = entry
        with suppress(Exception):
            async with asyncio.timeout(settings.RUNTIME_REDIS_TIMEOUT_SECONDS):
                await client.aclose()
                await pool.disconnect()


async def enqueue_runtime_job(function: str, *args, _queue_name: str, **kwargs):
    async with asyncio.timeout(settings.RUNTIME_REDIS_TIMEOUT_SECONDS):
        return await get_arq_client().enqueue_job(function, *args, _queue_name=_queue_name, **kwargs)
