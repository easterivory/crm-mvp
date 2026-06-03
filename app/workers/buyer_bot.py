"""Polling worker for the buyer Telegram bot."""
from __future__ import annotations

import asyncio
import logging

from pydantic import ValidationError

from app.core.config import settings
from app.core.database import get_db_session
from app.schemas.telegram import TelegramUpdate
from app.services.buyer_bot_service import (
    BuyerBotService,
    BuyerBotStateStore,
    BuyerTelegramClient,
)

logger = logging.getLogger(__name__)


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
    token = (settings.BUYER_BOT_TOKEN or "").strip()
    if not token:
        logger.warning("BUYER_BOT_TOKEN is not set; buyer bot worker is disabled")
        return

    telegram = BuyerTelegramClient(token)
    state_store = BuyerBotStateStore()
    offset: int | None = None
    logger.info("Starting buyer Telegram bot polling worker")

    try:
        while True:
            try:
                updates = await telegram.get_updates(offset=offset)
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
        await state_store.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run_loop())
