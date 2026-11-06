import json

import httpx
import pytest

from app.services.chatterfy_export_service import (
    API_BASE, ChatterfyExportError, ChatterfyReadClient, created_filter, probe_chats,
)

ACCESS = {key: "all" for key in ("chat.read", "chat.export", "message.read", "chat.contacts.read")}
START = "2026-07-31T21:00:00Z"
END = "2026-11-05T12:00:00Z"


def page(rows, cursor=None):
    return {"data": rows, "pagination": {"has_more": cursor is not None,
            **({"next_cursor": cursor} if cursor is not None else {})}}


def chat(cid="c1", **updates):
    return {"id": cid, "bot_id": "bot", "created_at": START, "external_id": "123", **updates}


def message(mid="m1", **updates):
    return {"id": mid, "chat_id": "c1", "type": "message", "sender_type": "incoming",
            "status": "ready", "content": "Hello", "created_at": START, "files": [], **updates}


def client_for(handler):
    return ChatterfyReadClient("private-test-key", transport=httpx.MockTransport(handler), interval=0, sleep=lambda _: None)


def test_cutoff_includes_moscow_midnight_without_one_second_hack():
    result = created_filter("2026-08-01T00:00:00+03:00", END)
    assert result == {"field": "created_at", "operator": "between", "value": [START, END]}
    with pytest.raises(ChatterfyExportError):
        created_filter("2026-08-01", END)
    with pytest.raises(ChatterfyExportError):
        created_filter(END, START)


def test_probe_reads_full_history_not_just_first_page_and_never_writes_crm(tmp_path):
    calls = []

    def handler(request):
        assert request.method == "POST"
        assert str(request.url).startswith(API_BASE)
        assert request.headers["ApiKey"] == "private-test-key"
        assert "Authorization" not in request.headers
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if request.url.path.endswith("/companies/v1/search"):
            return httpx.Response(200, json=page([{"id": "company"}]))
        if request.url.path.endswith("/bots/v1/search"):
            return httpx.Response(200, json=page([{"id": "bot", "name": "Andrey", "space_id": "space", "access": ACCESS, "token": "must-not-export"}]))
        if request.url.path.endswith("/chats/v1/stats"):
            assert body["filter"]["value"][0] == START
            return httpx.Response(200, json={"total": 100000})
        if request.url.path.endswith("/chats/v1/export"):
            assert body["filter"] == calls[-2][1]["filter"]
            return httpx.Response(200, json=page([chat()], "more-chats"))
        assert body["chat_id"] == "c1" and body["order"] == "asc"
        assert "filter" not in body  # Full history, not a cutoff on messages.
        if "cursor" not in body:
            return httpx.Response(200, json=page([message(created_at="2026-07-30T00:00:00Z")], "messages-2"))
        assert body["cursor"] == "messages-2"
        return httpx.Response(200, json=page([message("m2", sender_type="outcoming", sender="operator",
            reply_message_id="m1", edited_at=END, is_mailing=True, files=[{"type": "photo", "url": "https://media.example/photo"}])]))

    client = client_for(handler)
    try:
        report = probe_chats(client, tmp_path, bot_id="bot", end=END, sample_size=1)
    finally:
        client.close()
    assert report["matching_chats_reported"] == 100000
    assert report["all_chats_exported"] is False
    assert report["crm_writes"] == 0 and report["full_scope_verified"] is True
    row = report["chats"][0]
    assert row["message_count"] == 2 and row["pages"] == 2
    assert row["files"] == row["replies"] == row["edited"] == row["operator_messages"] == row["mailings"] == 1
    saved = json.loads((tmp_path / row["file"]).read_text())
    assert [m["id"] for m in saved["messages"]] == ["m1", "m2"]
    assert saved["pagination_complete"] is True
    assert (tmp_path / row["file"]).stat().st_mode & 0o077 == 0
    assert "private-test-key" not in (tmp_path / "probe-report.json").read_text()
    assert [p for p in tmp_path.iterdir() if p.suffix != ".json"] == []


@pytest.mark.parametrize("payload", [
    {"data": []}, {"data": [], "pagination": {"has_more": "false"}},
    {"data": [], "pagination": {"has_more": True}},
    {"data": None, "pagination": {"has_more": False}},
])
def test_unknown_pagination_is_not_reported_as_empty_complete_export(payload):
    client = client_for(lambda _: httpx.Response(200, json=payload))
    try:
        with pytest.raises(ChatterfyExportError):
            list(client.pages("/messages/v1/search", {"chat_id": "c1"}))
    finally:
        client.close()


def test_repeating_cursor_and_page_budget_stop_without_claiming_completeness():
    client = client_for(lambda _: httpx.Response(200, json=page([message()], "repeat")))
    try:
        with pytest.raises(ChatterfyExportError, match="repeating cursor"):
            list(client.pages("/messages/v1/search", {}))
        with pytest.raises(ChatterfyExportError, match="Page limit"):
            list(client.pages("/messages/v1/search", {}, max_pages=1))
    finally:
        client.close()


def test_write_paths_and_redirects_are_blocked_without_leaking_key():
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://other.example/private-test-key"})
    client = client_for(handler)
    try:
        with pytest.raises(ChatterfyExportError):
            client.call("/messages/v1/send", {})
        assert calls == []
        with pytest.raises(ChatterfyExportError) as error:
            client.call("/companies/v1/search", {})
        assert "private-test-key" not in str(error.value)
        assert len(calls) == 1
    finally:
        client.close()


@pytest.mark.parametrize('code', [401, 403])
def test_permissions_fail_closed_and_are_not_retried(code):
    client = client_for(lambda _: httpx.Response(code, json={"error": {"message": "private-test-key"}}))
    try:
        with pytest.raises(ChatterfyExportError) as error:
            client.call("/chats/v1/export", {})
        assert client.requests == 1 and "private-test-key" not in str(error.value)
    finally:
        client.close()


def test_rate_limit_wait_is_respected_and_retries_are_bounded():
    waits = []
    def handler(request):
        return httpx.Response(429, headers={"Retry-After": "2"})
    client = ChatterfyReadClient("key", transport=httpx.MockTransport(handler), interval=0, sleep=waits.append)
    try:
        with pytest.raises(ChatterfyExportError):
            client.call("/chats/v1/export", {})
        assert client.requests == 4
        assert waits.count(2) == 3
    finally:
        client.close()


@pytest.mark.parametrize('bad_chat', [chat(created_at="2026-07-31T20:59:59Z"), chat(bot_id="other")])
def test_out_of_range_or_wrong_bot_stops_probe(tmp_path, bad_chat):
    def handler(request):
        path = request.url.path
        data = page([{"id": "company"}]) if path.endswith("/companies/v1/search") else (
            page([{"id": "bot", "access": ACCESS}]) if path.endswith("/bots/v1/search") else (
            {"total": 1} if path.endswith("/chats/v1/stats") else page([bad_chat])))
        return httpx.Response(200, json=data)
    client = client_for(handler)
    try:
        with pytest.raises(ChatterfyExportError):
            probe_chats(client, tmp_path, bot_id="bot", end=END)
        assert not (tmp_path / "probe-report.json").exists()
    finally:
        client.close()


def test_full_access_must_be_verified_not_just_an_empty_api_list(tmp_path):
    def handler(request):
        return httpx.Response(200, json=page([{"id": "company"}] if request.url.path.endswith("/companies/v1/search") else [{"id": "bot", "access": {"chat.read": "own"}}]))
    client = client_for(handler)
    try:
        with pytest.raises(ChatterfyExportError, match="Full-scope"):
            probe_chats(client, tmp_path, bot_id="bot", end=END)
    finally:
        client.close()


@pytest.mark.parametrize('bad_message', [message(chat_id='another-chat'), message(sender_type='unknown'),
    message(files={'url': 'unexpected-schema'}), message(created_at='2026-08-01')])
def test_incompatible_message_data_never_produces_a_complete_report(tmp_path, bad_message):
    def handler(request):
        path = request.url.path
        if path.endswith('/companies/v1/search'):
            data = page([{'id': 'company'}])
        elif path.endswith('/bots/v1/search'):
            data = page([{'id': 'bot', 'access': ACCESS}])
        elif path.endswith('/chats/v1/stats'):
            data = {'total': 1}
        elif path.endswith('/chats/v1/export'):
            data = page([chat()])
        else:
            data = page([bad_message])
        return httpx.Response(200, json=data)
    client = client_for(handler)
    try:
        with pytest.raises(ChatterfyExportError):
            probe_chats(client, tmp_path, bot_id='bot', end=END)
        assert list(tmp_path.iterdir()) == []
    finally:
        client.close()


def test_request_budget_cannot_be_bypassed_by_retries():
    client = ChatterfyReadClient('key', transport=httpx.MockTransport(lambda _: httpx.Response(503)),
                                interval=0, sleep=lambda _: None, max_requests=2)
    try:
        with pytest.raises(ChatterfyExportError, match='budget'):
            client.call('/chats/v1/export', {})
        assert client.requests == 2
    finally:
        client.close()


def test_private_exports_are_not_overwritten(tmp_path):
    from app.services.chatterfy_export_service import write_private_json
    path = tmp_path / 'sample.json'
    write_private_json(path, {'original': True})
    with pytest.raises(FileExistsError):
        write_private_json(path, {'original': False})
    assert json.loads(path.read_text()) == {'original': True}


def test_wrong_username_is_rejected_before_requesting_any_chat_data(tmp_path):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=page([{'id': 'company'}] if request.url.path.endswith('/companies/v1/search')
            else [{'id': 'bot', 'username': 'different_bot', 'access': ACCESS}]))
    client = client_for(handler)
    try:
        with pytest.raises(ChatterfyExportError, match='username does not match'):
            probe_chats(client, tmp_path, bot_id='bot', end=END, expected_username='Andrey_smirniy_nobot')
        assert all('/chats/' not in p and '/messages/' not in p for p in calls)
        assert list(tmp_path.iterdir()) == []
    finally:
        client.close()


@pytest.mark.parametrize('page_size', [0, 101])
def test_history_page_size_validation_never_calls_api(page_size):
    from app.services.chatterfy_export_service import read_chat_history
    client = client_for(lambda _: pytest.fail('No request expected'))
    try:
        with pytest.raises(ChatterfyExportError):
            read_chat_history(client, chat(), expected_bot_id='bot', page_size=page_size)
    finally:
        client.close()


def test_history_refuses_chat_of_another_bot_before_any_request():
    from app.services.chatterfy_export_service import read_chat_history
    client = client_for(lambda _: pytest.fail('No request expected'))
    try:
        with pytest.raises(ChatterfyExportError, match='verified bot'):
            read_chat_history(client, chat(bot_id='other'), expected_bot_id='bot')
    finally:
        client.close()
