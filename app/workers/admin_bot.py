"""Polling worker for the administrator Telegram bot."""
from __future__ import annotations

import asyncio
import logging

from app.core.database import get_db_session
from app.services.admin_bot_service import AdminBotService, AdminTelegramClient
from app.services.system_setting_service import SystemSettingService

logger = logging.getLogger(__name__)
RELOAD_CHECK_SECONDS = 25


async def run_loop() -> None:
    telegram: AdminTelegramClient | None = None
    current_token: str | None = None
    offset: int | None = None
    last_reload_at = 0.0
    logger.info("Starting admin Telegram bot polling worker")
    try:
        while True:
            try:
                now = asyncio.get_running_loop().time()
                if telegram is None or now - last_reload_at >= RELOAD_CHECK_SECONDS:
                    token = await _load_token()
                    last_reload_at = now
                    if token != current_token:
                        if telegram is not None:
                            await telegram.close()
                        telegram = AdminTelegramClient(token) if token else None
                        current_token = token
                        offset = None
                        if telegram is not None:
                            await telegram.set_commands()
                    if telegram is None:
                        await asyncio.sleep(RELOAD_CHECK_SECONDS)
                        continue

                updates = await telegram.get_updates(offset=offset, timeout_seconds=RELOAD_CHECK_SECONDS)
                for update in updates:
                    update_id = update.get("update_id")
                    if isinstance(update_id, int):
                        offset = update_id + 1
                    async with get_db_session() as db:
                        await AdminBotService(db, telegram).handle_update(update)
                        await db.commit()
            except Exception:
                logger.exception("Admin bot polling cycle failed")
                await asyncio.sleep(5)
    finally:
        if telegram is not None:
            await telegram.close()


async def _load_token() -> str | None:
    async with get_db_session() as db:
        return (await SystemSettingService(db).get_effective_global_config()).admin_bot_token


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_loop())
