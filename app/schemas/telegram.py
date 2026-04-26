"""
Telegram Update payload schemas.

Only the fields required for message processing are declared.
Telegram sends many additional fields (via, forward_from, etc.) that are
silently ignored via model_config extra="ignore".

Python reserves `from` as a keyword, so the sender field in TelegramMessage
is mapped via Field(alias="from") and populate_by_name=True is set so that
tests can also construct the model using the Python name from_user=...
"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class TelegramUser(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: int
    username: Optional[str] = None
    first_name: Optional[str] = None


class TelegramChat(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int


class TelegramMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    message_id: int
    text: Optional[str] = None
    chat: TelegramChat
    # "from" is a reserved word — alias it to from_user
    from_user: Optional[TelegramUser] = Field(None, alias="from")


class TelegramUpdate(BaseModel):
    """
    Top-level Telegram Update object.

    Only `message` updates are processed. All other update types
    (edited_message, callback_query, etc.) are ignored — TelegramService
    will return early when message is None.
    """
    model_config = ConfigDict(extra="ignore")

    update_id: int
    message: Optional[TelegramMessage] = None
