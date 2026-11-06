"""Database backup orchestration backed by global runtime settings."""
from __future__ import annotations

import asyncio
from typing import Any

from app.core.database import get_db_session
from app.services.backup_service import BackupError, create_database_backup, send_backup_to_telegram
from app.services.system_setting_service import SystemSettingService
from app.services.backup_diagnostics import record_backup_status


async def run_configured_telegram_backup(*, force: bool = False) -> dict[str, Any]:
    """Create a compressed SQL dump and deliver it with the configured Telegram bot."""
    async with get_db_session() as db:
        config = await SystemSettingService(db).get_effective_global_config()

    if not force and not config.is_tg_backup_enabled:
        return {"status": "skipped", "reason": "disabled"}
    if not config.tg_backup_bot_token or not config.tg_backup_channel_id:
        raise BackupError("Telegram backup bot token and channel ID are required")

    result = None
    stage = "creating"
    await record_backup_status(stage)
    try:
        result = await asyncio.to_thread(create_database_backup, send_to_telegram=False)
        stage = "uploading"
        await record_backup_status(stage, size_bytes=result.size_bytes, file_name=result.path.name, local_created=True)
        await asyncio.to_thread(send_backup_to_telegram, result,
            bot_token=config.tg_backup_bot_token, chat_id=config.tg_backup_channel_id)
    except Exception as exc:
        await record_backup_status("failed", failed_stage=stage, error_type=type(exc).__name__,
            local_created=result is not None, size_bytes=result.size_bytes if result else None,
            file_name=result.path.name if result else None, telegram_sent=False)
        raise
    result.telegram_sent = True
    await record_backup_status("completed", size_bytes=result.size_bytes, file_name=result.path.name,
        local_created=True, telegram_sent=True)
    return {"status": "completed", **result.to_json_dict()}
