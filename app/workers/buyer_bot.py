"""Polling worker for the buyer Telegram bot."""
from __future__ import annotations

import asyncio
import logging

from pydantic import ValidationError

from app.core.database import get_db_session
from app.schemas.telegram import TelegramUpdate
from app.services.buyer_bot_service import (
    BuyerBotService,
    BuyerBotStateStore,
    BuyerTelegramClient,
)
from app.services.system_setting_service import SystemSettingService

logger = logging.getLogger(__name__)
RELOAD_CHECK_SECONDS = 25


async def process_update(
    raw_update: dict,
    telegram: BuyerTelegramClient,
    state_store: BuyerBotStateStore,
) -> None:
    try:
        update = TelegramUpdate.model_validate(raw_update)
    except ValidationError:
        logger.warning("Buyer bot received malformed Telegram update: %s", raw_update)
        return

    async with get_db_session() as db:
        try:
            await BuyerBotService(db, telegram, state_store).handle_update(update)
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def run_loop() -> None:
    state_store = BuyerBotStateStore()
    telegram: BuyerTelegramClient | None = None
    current_token: str | None = None
    offset: int | None = None
    last_reload_check_at = 0.0
    logger.info("Starting buyer Telegram bot polling worker")

    try:
        while True:
            try:
                loop_time = asyncio.get_running_loop().time()
                if telegram is None or loop_time - last_reload_check_at >= RELOAD_CHECK_SECONDS:
                    next_token = await _load_buyer_bot_token()
                    last_reload_check_at = loop_time

                    if not next_token:
                        if telegram is not None:
                            await telegram.close()
                            telegram = None
                            current_token = None
                            offset = None
                        logger.warning(
                            "Buyer bot token is not configured in system_settings or .env"
                        )
                        await asyncio.sleep(RELOAD_CHECK_SECONDS)
                        continue

                    if next_token != current_token:
                        if telegram is not None:
                            await telegram.close()
                        telegram = BuyerTelegramClient(next_token)
                        try:
                            await telegram.set_commands()
                        except RuntimeError:
                            logger.warning("Buyer Telegram bot command sync failed", exc_info=True)
                        current_token = next_token
                        offset = None
                        logger.info("Buyer Telegram bot polling started with refreshed token")

                if telegram is None:
                    await asyncio.sleep(RELOAD_CHECK_SECONDS)
                    continue

                updates = await telegram.get_updates(
                    offset=offset,
                    timeout_seconds=RELOAD_CHECK_SECONDS,
                )
                for raw_update in updates:
                    update_id = raw_update.get("update_id")
                    if isinstance(update_id, int):
                        offset = update_id + 1
                    try:
                        await process_update(raw_update, telegram, state_store)
                    except Exception:
                        logger.exception(
                            "Buyer bot failed to process update_id=%s",
                            raw_update.get("update_id"),
                        )
            except Exception:
                logger.exception("Buyer bot polling cycle failed")
                await asyncio.sleep(5)
    finally:
        if telegram is not None:
            await telegram.close()
        await state_store.close()


async def _load_buyer_bot_token() -> str | None:
    async with get_db_session() as db:
        config = await SystemSettingService(db).get_effective_buyer_bot_config()
        return config.token


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run_loop())
