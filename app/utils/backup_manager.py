"""Database backup orchestration backed by global runtime settings."""
from __future__ import annotations

import asyncio
from typing import Any

from app.core.database import get_db_session
from app.services.backup_service import BackupError, create_database_backup, send_backup_to_telegram
from app.services.system_setting_service import SystemSettingService


async def run_configured_telegram_backup(*, force: bool = False) -> dict[str, Any]:
    """Create a compressed SQL dump and deliver it with the configured Telegram bot."""
    async with get_db_session() as db:
        config = await SystemSettingService(db).get_effective_global_config()

    if not force and not config.is_tg_backup_enabled:
        return {"status": "skipped", "reason": "disabled"}
    if not config.tg_backup_bot_token or not config.tg_backup_channel_id:
        raise BackupError("Telegram backup bot token and channel ID are required")

    result = await asyncio.to_thread(
        create_database_backup,
        send_to_telegram=False,
    )
    await asyncio.to_thread(
        send_backup_to_telegram,
        result,
        bot_token=config.tg_backup_bot_token,
        chat_id=config.tg_backup_channel_id,
    )
    result.telegram_sent = True
    return {"status": "completed", **result.to_json_dict()}
