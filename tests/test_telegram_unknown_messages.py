import pytest

from app.models.message import Message, MessageType
from app.schemas.telegram import TelegramMessage
from app.services.telegram_service import TelegramService


def convert(**fields):
    message = TelegramMessage.model_validate({
        "message_id": 123, "chat": {"id": 456, "type": "private"}, **fields,
    })
    return TelegramService._telegram_message_to_create(message)


@pytest.mark.parametrize(("field", "value", "expected"), [
    ("poll", {"question": "Выберите", "options": [{"text": "Да", "voter_count": 0}]}, "Да"),
    ("location", {"latitude": 41.3, "longitude": 69.2}, "41.3, 69.2"),
    ("venue", {"title": "Место", "address": "Адрес", "location": {"latitude": 1, "longitude": 2}}, "Адрес"),
    ("dice", {"emoji": "🎲", "value": 4}, "4"),
    ("story", {"id": 12, "chat": {"id": 456}}, "История Telegram"),
    ("future_message_kind", {"content": "Preserved"}, "Исходные данные сохранены"),
])
def test_structured_messages_preserve_payload_and_explain_content(field, value, expected):
    result = convert(**{field: value})
    assert result.message_type == MessageType.UNKNOWN
    assert result.body is None
    assert expected in Message(**result.model_dump(exclude={"parse_mode", "reply_markup", "upload_id"})).unsupported_content
    assert result.raw_payload_json[field] == value
    assert result.telegram_file_id is None


def test_unknown_caption_is_preserved():
    result = convert(caption="Подпись", future_message_kind={})
    assert result.raw_payload_json["caption"] == "Подпись"
    assert result.caption is None


def test_existing_photo_and_text_conversion_unchanged():
    photo = convert(photo=[{"file_id": "small", "file_size": 10}, {"file_id": "large", "file_size": 100}], caption="Фото")
    assert photo.message_type == MessageType.PHOTO
    assert photo.telegram_file_id == "large"
    assert photo.caption == "Фото"
    text = convert(text="Привет", entities=[{"type": "bold", "offset": 0, "length": 6}])
    assert text.message_type == MessageType.TEXT
    assert text.body == "Привет"
    assert text.raw_payload_json["entities"][0]["type"] == "bold"


def test_extra_fields_cannot_override_transport_metadata():
    result = convert(_transport="user_mtproto", mtproto_media_path="/tmp/private", telegram_result={"mtproto_media_path": "/tmp/private"})
    assert result.raw_payload_json["_transport"] == "bot_api"
    assert "mtproto_media_path" not in result.raw_payload_json
    assert "telegram_result" not in result.raw_payload_json


def test_legacy_unknown_does_not_claim_missing_payload_is_available():
    message = Message(message_type="unknown", raw_payload_json={"message_id": 123})
    assert message.unsupported_content is None
    message.raw_payload_json = None
    assert message.unsupported_content is None
