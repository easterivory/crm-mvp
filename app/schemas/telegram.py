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


class TelegramFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    file_id: str
    file_unique_id: Optional[str] = None
    file_size: Optional[int] = None


class TelegramDocument(TelegramFile):
    file_name: Optional[str] = None
    mime_type: Optional[str] = None


class TelegramAudio(TelegramDocument):
    pass


class TelegramVideo(TelegramDocument):
    pass


class TelegramAnimation(TelegramDocument):
    pass


class TelegramVoice(TelegramFile):
    mime_type: Optional[str] = None


class TelegramSticker(TelegramFile):
    emoji: Optional[str] = None


class TelegramMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    message_id: int
    text: Optional[str] = None
    caption: Optional[str] = None
    media_group_id: Optional[str] = None
    chat: TelegramChat
    # "from" is a reserved word — alias it to from_user
    from_user: Optional[TelegramUser] = Field(None, alias="from")
    photo: Optional[list[TelegramFile]] = None
    video: Optional[TelegramVideo] = None
    voice: Optional[TelegramVoice] = None
    video_note: Optional[TelegramFile] = None
    document: Optional[TelegramDocument] = None
    audio: Optional[TelegramAudio] = None
    sticker: Optional[TelegramSticker] = None
    animation: Optional[TelegramAnimation] = None


class TelegramCallbackQuery(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    data: Optional[str] = None
    message: Optional[TelegramMessage] = None
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
    callback_query: Optional[TelegramCallbackQuery] = None
