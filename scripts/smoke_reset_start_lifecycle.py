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
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import get_db_session
from app.repositories.bot_repository import BotRepository
from app.repositories.chat_repository import ChatRepository
from app.repositories.funnel_repository import FunnelRepository
from app.repositories.lead_repository import LeadRepository
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
        bot_repo = BotRepository(db)
        funnel_repo = FunnelRepository(db)
        lead_repo = LeadRepository(db)
        chat = await chat_repo.get_by_external(
            bot.project_id,
            external_chat_id,
            bot_id=bot.id,
        )
        if chat is None:
            raise SystemExit(
                f"Active chat not found for bot={bot.id} external_chat_id={external_chat_id}"
            )

        old_tracking_link_id = chat.tracking_link_id
        active_bot_version = await bot_repo.get_active_version_for_bot(bot.id, bot.project_id)
        active_funnel_version = await funnel_repo.get_published_for_bot(bot.id)

        await ChatService(db).reset_chat(chat.id, bot.project_id, actor_id)

        reset_chat = await chat_repo.get_reset_by_external(
            bot.project_id,
            external_chat_id,
            bot_id=bot.id,
        )
        if reset_chat is None:
            raise SystemExit("Chat was not hidden as reset")
        if reset_chat.tracking_link_id is not None:
            raise SystemExit("Reset chat kept active tracking_link_id")

        reset_lead = await lead_repo.get_by_chat(chat.id, bot.project_id)
        if reset_lead is None:
            raise SystemExit("Lead disappeared after reset")
        reset_status = await lead_repo.get_status(reset_lead.status_id)
        if reset_status is None or reset_status.code != "lost":
            raise SystemExit("Lead was not marked lost after reset")

        reset_bot_state = await bot_repo.get_chat_state(chat.id)
        if reset_bot_state is not None and (
            reset_bot_state.is_active
            or reset_bot_state.current_step_id is not None
            or reset_bot_state.variables
        ):
            raise SystemExit("Bot state was not reset/deactivated")

        reset_funnel_state = await funnel_repo.get_chat_funnel_state(chat.id)
        if reset_funnel_state is not None and reset_funnel_state.completed_at is None:
            raise SystemExit("Chat funnel state was not completed on reset")

        await db.commit()

        text = "/start" if not args.ref_code else f"/start {args.ref_code}"
        synthetic_id = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
        update = TelegramUpdate(
            update_id=synthetic_id,
            message=TelegramMessage(
                message_id=synthetic_id,
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
        if not args.ref_code and old_tracking_link_id is not None and reactivated.tracking_link_id is not None:
            raise SystemExit("Old tracking_link_id was reused without a new /start ref_code")

        lead = await lead_repo.get_by_chat(reactivated.id, bot.project_id)
        if lead is None:
            raise SystemExit("Lead was not present after reactivation")
        lead_status = await lead_repo.get_status(lead.status_id)
        if lead_status is None or lead_status.code != "new":
            raise SystemExit("Lead was not reset to new for the new cycle")

        bot_state = await bot_repo.get_chat_state(reactivated.id)
        if active_bot_version is not None and (
            bot_state is None
            or not bot_state.is_active
            or bot_state.bot_version_id != active_bot_version.id
        ):
            raise SystemExit("Bot state was not recreated for the active bot version")

        funnel_state = await funnel_repo.get_chat_funnel_state(reactivated.id)
        if active_funnel_version is not None and (
            funnel_state is None
            or funnel_state.completed_at is not None
            or funnel_state.funnel_version_id != active_funnel_version.id
        ):
            raise SystemExit("Chat funnel state was not recreated for the active funnel")

        print(
            "ok reset_start_lifecycle "
            f"chat_id={reactivated.id} reset_count={reactivated.reset_count}"
        )


if __name__ == "__main__":
    asyncio.run(main())
