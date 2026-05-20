"""Service-level smoke for reset -> new Telegram /start lifecycle.

Usage:
  python scripts/smoke_reset_start_lifecycle.py \
    --bot-id <uuid> \
    --external-chat-id <telegram-chat-id> \
    --actor-id <crm-user-id> \
    --ref-code optional-ref

The script expects an existing active chat for the bot/external_chat_id. It
resets that chat through ChatService, sends a synthetic /start update through
TelegramService, then verifies that the chat is active again and visible.
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from app.core.database import get_db_session
from app.repositories.bot_repository import BotRepository
from app.repositories.chat_repository import ChatRepository
from app.schemas.telegram import TelegramChat, TelegramMessage, TelegramUpdate, TelegramUser
from app.services.chat_service import ChatService
from app.services.telegram_service import TelegramService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bot-id", required=True)
    parser.add_argument("--external-chat-id", required=True)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--ref-code", default="")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    bot_id = UUID(args.bot_id)
    actor_id = UUID(args.actor_id)
    external_chat_id = str(args.external_chat_id)

    async with get_db_session() as db:
        bot = await BotRepository(db).get_active(bot_id)
        if bot is None:
            raise SystemExit(f"Bot not found: {bot_id}")

        chat_repo = ChatRepository(db)
        chat = await chat_repo.get_by_external(
            bot.project_id,
            external_chat_id,
            bot_id=bot.id,
        )
        if chat is None:
            raise SystemExit(
                f"Active chat not found for bot={bot.id} external_chat_id={external_chat_id}"
            )

        await ChatService(db).reset_chat(chat.id, bot.project_id, actor_id)
        await db.commit()

        text = "/start" if not args.ref_code else f"/start {args.ref_code}"
        update = TelegramUpdate(
            update_id=900000001,
            message=TelegramMessage(
                message_id=900000001,
                text=text,
                chat=TelegramChat(id=int(external_chat_id)),
                from_user=TelegramUser(
                    id=int(external_chat_id),
                    username="reset_smoke",
                    first_name="Reset smoke",
                ),
            ),
        )

        await TelegramService(db).handle_webhook_update(update=update, bot_id=bot.id)
        await db.commit()

        reactivated = await chat_repo.get_by_external(
            bot.project_id,
            external_chat_id,
            bot_id=bot.id,
        )
        if reactivated is None or reactivated.reset_at is not None:
            raise SystemExit("Chat did not reactivate after synthetic /start")
        if reactivated.current_cycle_started_at is None:
            raise SystemExit("current_cycle_started_at was not set")
        if args.ref_code and reactivated.tracking_link_id is None:
            raise SystemExit("ref_code did not attach a tracking_link_id")

        print(
            "ok reset_start_lifecycle "
            f"chat_id={reactivated.id} reset_count={reactivated.reset_count}"
        )


if __name__ == "__main__":
    asyncio.run(main())
