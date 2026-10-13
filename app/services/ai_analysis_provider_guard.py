"""A short shared outage circuit, scoped to analysis and current credentials."""
from hashlib import sha256
import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings

logger = logging.getLogger(__name__)


def circuit_key(connection, model: str) -> str:
    identity = f"{connection.id}:{connection.credential_fingerprint}:{connection.base_url}:{model}"
    return "crm:ai-analysis:outage:" + sha256(identity.encode()).hexdigest()


async def provider_on_cooldown(connection, model: str) -> bool:
    try:
        async with Redis.from_url(settings.REDIS_URL, socket_connect_timeout=.5, socket_timeout=.5) as redis:
            return bool(await redis.exists(circuit_key(connection, model)))
    except (RedisError, OSError):
        logger.warning("Analysis provider circuit unavailable; continuing with configured provider")
        return False


async def note_provider_error(connection, model: str, error) -> None:
    if error.code not in {"provider_network_error", "provider_rate_limited", "provider_auth_error"} and not (
        error.status_code is not None and error.status_code >= 500
    ):
        return
    try:
        async with Redis.from_url(settings.REDIS_URL, socket_connect_timeout=.5, socket_timeout=.5) as redis:
            await redis.set(circuit_key(connection, model), error.code, ex=30)
    except (RedisError, OSError):
        logger.warning("Analysis provider circuit could not record an outage")
