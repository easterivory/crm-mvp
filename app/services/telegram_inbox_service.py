"""Accept Telegram updates without running funnels or using Redis in the request."""
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telegram_delivery import TelegramInbox
from app.models import Bot


def telegram_peer_key(payload: dict) -> str:
    callback = payload.get("callback_query") or {}
    for message in (payload.get("message"), payload.get("edited_message"), callback.get("message")):
        if isinstance(message, dict) and (message.get("chat") or {}).get("id") is not None:
            return f"chat:{message['chat']['id']}"
    for key in ("chat_join_request", "chat_member", "my_chat_member"):
        item = payload.get(key) or {}
        if (item.get("chat") or {}).get("id") is not None:
            user = (item.get("from") or {}).get("id", "")
            return f"member:{item['chat']['id']}:{user}"
    query = payload.get("inline_query") or callback
    if (query.get("from") or {}).get("id") is not None:
        return f"chat:{query['from']['id']}"
    return f"update:{payload['update_id']}"


async def accept_telegram_update(db: AsyncSession, *, bot_id: UUID, payload: dict) -> None:
    if await db.scalar(select(Bot.id).where(Bot.id == bot_id, Bot.is_deleted.is_(False))) is None:
        return
    # Do not overwrite an already accepted payload or restart its processing.
    await db.execute(insert(TelegramInbox).values(
        bot_id=bot_id, update_id=payload["update_id"],
        peer_key=telegram_peer_key(payload), payload_json=payload,
    ).on_conflict_do_nothing(index_elements=[TelegramInbox.bot_id, TelegramInbox.update_id]))
