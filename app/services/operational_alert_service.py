"""Best-effort, deduplicated alerts for background worker incidents."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

from app.core.config import settings
from app.core.database import get_db_session
from app.core.redis import get_redis
from app.services.backup_service import send_telegram_message
from app.services.system_setting_service import SystemSettingService

logger = logging.getLogger(__name__)

_TELEGRAM_TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")
_URL_CREDENTIAL_RE = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^/@\s]+@", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class OperationalAlertConfig:
    bot_token: str | None
    chat_id: str | None

    @property
    def configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)


_config_cache: OperationalAlertConfig | None = None
_config_cached_at = 0.0
_local_dedupe: dict[str, float] = {}


def _environment_config() -> OperationalAlertConfig:
    return OperationalAlertConfig(
        bot_token=(settings.BACKUP_TELEGRAM_BOT_TOKEN or "").strip() or None,
        chat_id=(settings.BACKUP_TELEGRAM_CHAT_ID or "").strip() or None,
    )


async def _load_delivery_config(*, force: bool = False) -> OperationalAlertConfig:
    global _config_cache, _config_cached_at

    now = time.monotonic()
    cache_ttl = max(settings.OPERATIONAL_ALERT_CONFIG_CACHE_SECONDS, 1)
    if not force and _config_cache is not None and now - _config_cached_at < cache_ttl:
        return _config_cache

    fallback = _config_cache or _environment_config()
    try:
        timeout_seconds = max(settings.OPERATIONAL_ALERT_CONFIG_TIMEOUT_SECONDS, 0.1)
        async with asyncio.timeout(timeout_seconds):
            async with get_db_session() as db:
                config = await SystemSettingService(db).get_effective_global_config()
                await db.rollback()
        loaded = OperationalAlertConfig(
            bot_token=(config.tg_backup_bot_token or "").strip() or None,
            chat_id=(config.tg_backup_channel_id or "").strip() or None,
        )
    except Exception as exc:
        logger.warning(
            "Could not refresh operational alert destination; using cached/environment config: %s",
            exc.__class__.__name__,
        )
        return fallback

    _config_cache = loaded
    _config_cached_at = now
    return loaded


async def prime_operational_alert_config() -> bool:
    """Warm the destination cache while the database is healthy."""
    config = await _load_delivery_config(force=True)
    return config.configured


async def _reserve_alert_slot(dedupe_key: str) -> bool:
    cooldown = max(settings.OPERATIONAL_ALERT_COOLDOWN_SECONDS, 1)
    digest = hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()
    redis_key = f"crm:operational-alert:{digest}"
    try:
        async with asyncio.timeout(1.0):
            redis = await get_redis()
            return bool(await redis.set(redis_key, "1", ex=cooldown, nx=True))
    except Exception as exc:
        logger.warning(
            "Redis alert deduplication unavailable; using process-local cooldown: %s",
            exc.__class__.__name__,
        )

    now = time.monotonic()
    expired = [key for key, expires_at in _local_dedupe.items() if expires_at <= now]
    for key in expired:
        _local_dedupe.pop(key, None)
    if _local_dedupe.get(digest, 0.0) > now:
        return False
    _local_dedupe[digest] = now + cooldown
    return True


async def _release_alert_slot(dedupe_key: str) -> None:
    digest = hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()
    _local_dedupe.pop(digest, None)
    try:
        async with asyncio.timeout(1.0):
            redis = await get_redis()
            await redis.delete(f"crm:operational-alert:{digest}")
    except Exception:
        logger.debug("Could not release Redis operational alert slot", exc_info=True)


def _sanitize(value: object, *, limit: int = 700) -> str:
    normalized = " ".join(str(value).split())
    normalized = _TELEGRAM_TOKEN_RE.sub("***telegram-token***", normalized)
    normalized = _URL_CREDENTIAL_RE.sub(r"\g<scheme>***@", normalized)
    return normalized[:limit]


async def send_operational_alert(
    *,
    component: str,
    title: str,
    details: Mapping[str, object] | None = None,
    dedupe_key: str,
) -> bool:
    """Deliver one bounded alert and suppress repeated copies during an incident."""
    if not settings.OPERATIONAL_ALERTS_ENABLED:
        return False

    config = await _load_delivery_config()
    if not config.configured:
        logger.warning("Operational alert destination is not configured")
        return False
    if not await _reserve_alert_slot(dedupe_key):
        return False

    lines = [
        "CRM operational alert",
        f"time_utc: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"component: {_sanitize(component, limit=120)}",
        f"event: {_sanitize(title, limit=300)}",
    ]
    for key, value in (details or {}).items():
        lines.append(f"{_sanitize(key, limit=80)}: {_sanitize(value)}")

    try:
        await asyncio.to_thread(
            send_telegram_message,
            "\n".join(lines),
            bot_token=config.bot_token,
            chat_id=config.chat_id,
            timeout_seconds=settings.OPERATIONAL_ALERT_SEND_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        await _release_alert_slot(dedupe_key)
        logger.warning(
            "Operational alert delivery failed component=%s error_type=%s",
            component,
            exc.__class__.__name__,
        )
        return False
    return True
