"""One Telegram start per person and project, independent of report filters."""
from sqlalchemy import and_, func, or_, select, tuple_
from sqlalchemy.orm import aliased

from app.core.constants import MessageType, SenderType
from app.models.chat import Chat
from app.models.message import Message


def is_telegram_start(message=Message):
    command = func.split_part(func.lower(func.trim(message.body)), " ", 1)
    return or_(command == "/start", command.like("/start@%"))


def is_first_project_start():
    earlier_chat = aliased(Chat, name="earlier_start_chat")
    earlier_message = aliased(Message, name="earlier_start_message")
    # Missing legacy IDs must not merge unrelated people. Repeated starts in
    # the same chat still deduplicate even when no Telegram user ID is stored.
    same_person = or_(
        earlier_chat.id == Chat.id,
        and_(
            Chat.external_user_id.is_not(None),
            Chat.external_user_id != "",
            earlier_chat.external_user_id == Chat.external_user_id,
        ),
    )
    earlier_start = (
        select(earlier_message.id)
        .select_from(earlier_chat)
        .join(earlier_message, earlier_message.chat_id == earlier_chat.id)
        .where(
            earlier_chat.project_id == Chat.project_id,
            same_person,
            earlier_message.sender_type == SenderType.USER,
            earlier_message.message_type == MessageType.TEXT,
            is_telegram_start(earlier_message),
            tuple_(earlier_message.created_at, earlier_message.id)
            < tuple_(Message.created_at, Message.id),
        )
        .correlate(Chat, Message)
    )
    # Deliberately search all dates/bots, including retained reset/deleted chats:
    # hiding an old chat must not turn a later duplicate into a new acquisition.
    return and_(is_telegram_start(), ~earlier_start.exists())
