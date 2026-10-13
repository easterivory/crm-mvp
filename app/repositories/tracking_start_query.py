"""One Telegram start per person and project, independent of report filters."""
from sqlalchemy import and_, func, literal_column, or_, select, tuple_
from sqlalchemy.orm import aliased

from app.models.chat import Chat
from app.models.message import Message


def is_telegram_start(message=Message):
    command = func.split_part(func.lower(func.trim(message.body)), literal_column("' '"), literal_column("1"))
    return or_(command == literal_column("'/start'"), command.like(literal_column("'/start@%'")))


def is_first_project_start():
    earlier_chat = aliased(Chat, name="earlier_start_chat")
    earlier_message = aliased(Message, name="earlier_start_message")
    # Missing legacy IDs must not merge unrelated people. Repeated starts in
    # the same chat still deduplicate even when no Telegram user ID is stored.
    before = tuple_(earlier_message.created_at, earlier_message.id) < tuple_(Message.created_at, Message.id)
    prior_same_chat = (select(earlier_message.id).where(
        earlier_message.chat_id == Chat.id,
        earlier_message.sender_type == literal_column("'user'"),
        earlier_message.message_type == literal_column("'text'"),
        is_telegram_start(earlier_message), before).correlate(Chat, Message))
    prior_other_chat = (
        select(earlier_message.id)
        .select_from(earlier_chat)
        .join(earlier_message, earlier_message.chat_id == earlier_chat.id)
        .where(
            earlier_chat.project_id == Chat.project_id,
            Chat.external_user_id.is_not(None), Chat.external_user_id != "",
            earlier_chat.external_user_id == Chat.external_user_id,
            earlier_chat.id != Chat.id,
            earlier_message.sender_type == literal_column("'user'"),
            earlier_message.message_type == literal_column("'text'"),
            is_telegram_start(earlier_message),
            before,
        )
        .correlate(Chat, Message)
    )
    # Deliberately search all dates/bots, including retained reset/deleted chats:
    # hiding an old chat must not turn a later duplicate into a new acquisition.
    return and_(Message.sender_type == literal_column("'user'"), Message.message_type == literal_column("'text'"),
                is_telegram_start(), ~prior_same_chat.exists(), ~prior_other_chat.exists())
