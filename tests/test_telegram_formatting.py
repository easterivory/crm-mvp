import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest

from app.core.telegram_formatting import telegram_html, mtproto_entities
from app.services.funnel_runtime_service import FunnelRuntimeService
from app.services.telegram_sender import TelegramSenderService


def test_utf16_entities_and_nested_formatting():
    text, entities = telegram_html(' <b>😀 <i>Арслан</i></b> <a href="https://example.org/?a=1&amp;b=2">сайт</a> ')
    assert text == '😀 Арслан сайт'
    assert entities == [
        {"type": "bold", "offset": 0, "length": 9},
        {"type": "italic", "offset": 3, "length": 6},
        {"type": "text_link", "offset": 10, "length": 4, "url": "https://example.org/?a=1&b=2"},
    ]


def test_whitespace_inside_tags_keeps_entity_offsets():
    assert telegram_html('<b>  hello  </b>') == ('hello', [{"type": "bold", "offset": 0, "length": 5}])


@pytest.mark.parametrize("markup", ['<b>bad', '<b><i>x</b></i>', '<script>x</script>',
    '<a href="javascript:alert(1)">x</a>', '<b onclick="x">x</b>', '<i><code>x</code></i>', '<!--x-->'])
def test_invalid_markup_rejected(markup):
    with pytest.raises(ValueError):
        telegram_html(markup)


@pytest.mark.parametrize("tag,kind", [('b', 'MessageEntityBold'), ('i', 'MessageEntityItalic'),
    ('u', 'MessageEntityUnderline'), ('s', 'MessageEntityStrike'), ('tg-spoiler', 'MessageEntitySpoiler'),
    ('code', 'MessageEntityCode'), ('pre', 'MessageEntityPre'), ('blockquote', 'MessageEntityBlockquote')])
def test_account_entity_support(tag, kind):
    _, entities = telegram_html(f'<{tag}>text</{tag}>')
    converted = mtproto_entities(entities)
    assert type(converted[0]).__name__ == kind
    assert converted[0].length == 4


@pytest.mark.parametrize("formatted", [False, True])
@pytest.mark.parametrize("media", [False, True])
def test_bot_api_receives_entities_only_when_explicitly_enabled(monkeypatch, formatted, media):
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs))
    sender = TelegramSenderService(MagicMock())
    sender._get_transport_type = AsyncMock(return_value='bot_api')
    sender._get_token = AsyncMock(return_value='test-token')
    common = dict(project_id=uuid4(), bot_id=uuid4(), external_chat_id='42', parse_mode='HTML' if formatted else None)
    if media:
        asyncio.run(sender.send_photo(**common, photo='file-id', caption='<b>Hello</b>'))
    else:
        asyncio.run(sender.send_message(**common, text='<b>Hello</b>'))
    data = requests[0]
    assert data['caption' if media else 'text'] == ('Hello' if formatted else '<b>Hello</b>')
    key = 'caption_entities' if media else 'entities'
    assert (key in data) is formatted
    if formatted:
        assert data[key] == [{"type": "bold", "offset": 0, "length": 5}]


def test_template_values_are_literal_not_markup():
    runtime = FunnelRuntimeService.__new__(FunnelRuntimeService)
    runtime.repo = SimpleNamespace(get_message_template_context=AsyncMock(return_value={
        'name': 'Арслан <admin>', 'custom_fields': {'note': '<b>unsafe</b>'}}),
        get_chat_funnel_state=AsyncMock(return_value=None))
    result = asyncio.run(runtime._render_text_template(uuid4(), '<b>{{name}}</b> {{custom.note}}', html=True))
    text, entities = telegram_html(result)
    assert text == 'Арслан <admin> <b>unsafe</b>'
    assert len(entities) == 1


def test_message_sequence_carries_format_mode():
    runtime = FunnelRuntimeService.__new__(FunnelRuntimeService)
    runtime._create_outgoing_message = AsyncMock()
    step = SimpleNamespace(block_type='generic_message', config_json={})
    asyncio.run(runtime._send_message_item(chat_id=uuid4(), step=step,
        item={'text': '<i>Hi</i>', 'parse_mode': 'HTML'}, reply_markup=None))
    assert runtime._create_outgoing_message.await_args.kwargs['parse_mode'] == 'HTML'


@pytest.mark.parametrize("media", [False, True])
def test_account_gateway_receives_plain_text_and_entities(media, tmp_path):
    sender = TelegramSenderService(MagicMock())
    sender._get_transport_type = AsyncMock(return_value='user_mtproto')
    sender._invoke_account_gateway = AsyncMock(return_value={'message_id': 1})
    common = dict(project_id=uuid4(), bot_id=uuid4(), external_chat_id='42', parse_mode='HTML')
    if media:
        photo = tmp_path / 'photo.jpg'
        photo.write_bytes(b'file-upload-test')
        asyncio.run(sender.send_photo(**common, photo=photo, caption='<tg-spoiler>Hi</tg-spoiler>'))
    else:
        asyncio.run(sender.send_message(**common, text='<tg-spoiler>Hi</tg-spoiler>'))
    data = sender._invoke_account_gateway.await_args.kwargs['payload']
    assert data['caption' if media else 'text'] == 'Hi'
    assert data['entities'] == [{'type': 'spoiler', 'offset': 0, 'length': 2}]


def test_file_upload_sends_caption_entities(monkeypatch, tmp_path):
    requests = []
    def respond(request):
        requests.append(request.content)
        return httpx.Response(200, json={'ok': True, 'result': {'message_id': 1}})
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs))
    sender = TelegramSenderService(MagicMock())
    sender._get_transport_type = AsyncMock(return_value='bot_api')
    sender._get_token = AsyncMock(return_value='test-token')
    photo = tmp_path / 'photo.jpg'
    photo.write_bytes(b'file-upload-test')
    asyncio.run(sender.send_photo(project_id=uuid4(), bot_id=uuid4(), external_chat_id='42',
        photo=photo, caption='<u>Hi</u>', parse_mode='HTML'))
    assert b'name="caption_entities"' in requests[0]
    assert b'"type": "underline"' in requests[0]
    assert b'<u>' not in requests[0]


def test_broadcast_formatting_validation_does_not_parse_legacy_plain_text():
    from fastapi import HTTPException
    from app.services.broadcast_service import BroadcastService
    service = BroadcastService.__new__(BroadcastService)
    service._validate_content({'messages': [{'text': '<b>literal'}]})
    service._validate_content({'messages': [{'text': '<b>valid</b>', 'parse_mode': 'HTML'}]})
    with pytest.raises(HTTPException) as exc:
        service._validate_content({'messages': [{'text': '<b>invalid', 'parse_mode': 'HTML'}]})
    assert exc.value.status_code == 422


def test_funnel_formatting_validation_blocks_publish_not_draft():
    from app.schemas.funnel import FunnelGraphIn, FunnelStepIn
    from app.services.funnel_block_registry import FunnelBlockRegistry
    from app.services.funnel_service import FunnelService
    from app.services.funnel_validator import FunnelGraphValidator
    service = FunnelService.__new__(FunnelService)
    service.registry = FunnelBlockRegistry()
    service.graph_validator = FunnelGraphValidator()
    step = FunnelStepIn(id=uuid4(), key='message', title='Welcome', step_type='message',
        block_type='generic_message', config_json={'messages': [{'text': '<b>bad', 'parse_mode': 'HTML'}]})
    graph = FunnelGraphIn(steps=[step])
    assert not any(x.code == 'invalid_telegram_formatting' for x in service._validate_graph_payload(graph, strict_config=False).errors)
    assert any(x.code == 'invalid_telegram_formatting' for x in service._validate_graph_payload(graph, strict_config=True).errors)
