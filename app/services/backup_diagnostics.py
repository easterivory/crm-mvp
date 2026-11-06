"""Effective backup-worker configuration; never include the bot token or credentials."""
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlsplit

from app.core.config import settings
from app.core.database import get_db_session
from app.services.system_setting_service import SystemSettingService

logger = logging.getLogger(__name__)


def transport_status(config=settings):
    try:
        parsed = urlsplit(config.BACKUP_TELEGRAM_API_BASE_URL)
        host = parsed.hostname or ""
        cloud = host.casefold() == "api.telegram.org"
        port = parsed.port
        valid = parsed.scheme in {"http", "https"} and bool(host) and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
        if cloud:
            valid = valid and parsed.scheme == "https" and port in {None, 443} and parsed.path in {"", "/"}
    except ValueError:
        host, cloud, valid = "", False, False
    configured = config.BACKUP_TELEGRAM_MAX_UPLOAD_MB
    valid = valid and configured > 0
    effective = min(configured, 49) if cloud else min(configured, 2000)
    return {"mode": "cloud" if cloud else "custom", "host": host,
        "configured_limit_mb": configured, "effective_limit_mb": effective,
        "warning": "Некорректный адрес backup API" if not valid else
            "Для больших бэкапов нужен отдельный Local Bot API и профиль backup-local-api" if effective <= 49 else None,
        "address_valid": valid, "local_api_verified": False}


async def record_backup_status(stage, **details):
    try:
        async with get_db_session() as db:
            await SystemSettingService(db).set_value("backup_runtime_status", json.dumps({
                **transport_status(), "stage": stage, "observed_at": datetime.now(timezone.utc).isoformat(), **details}))
            await db.commit()
    except Exception:
        logger.warning("Could not persist backup worker status")
