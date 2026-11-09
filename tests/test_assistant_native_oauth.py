"""Native callback opt-in without relaxing HTTPS clients, PKCE or exact matching."""
import asyncio
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.config import settings
from app.models.assistant import AssistantConnection
from app.repositories.user_repository import UserRepository
from app.schemas.assistant import AuthorizeIn
from app.services.assistant_oauth import authorization_parameters, authorize, configured_client, exchange
from test_cloud_assistant import PG, auth_query, configure, token_body
from test_gambling_offers import fixture


CALLBACK = "http://127.0.0.1:48193/callback"


def native_client(monkeypatch, callback=CALLBACK, opt_in=True):
    monkeypatch.setattr(settings, "ASSISTANT_OAUTH_CLIENTS_JSON", json.dumps({
        "qa": {"redirect_uris": [callback], "allow_loopback_http": opt_in}}))


@pytest.mark.parametrize("opt_in", [False, None, "true", 1])
def test_http_callback_requires_explicit_boolean_opt_in(monkeypatch, opt_in):
    native_client(monkeypatch, opt_in=opt_in)
    with pytest.raises(HTTPException) as exc:
        configured_client("qa")
    assert exc.value.status_code == 503


@pytest.mark.parametrize("callback", [
    "http://localhost:48193/callback", "http://0.0.0.0:48193/callback",
    "http://127.0.0.2:48193/callback", "http://127.0.0.1.evil.example:48193/callback",
    "http://evil.example:48193/callback", "http://[::1]:48193/callback",
    "http://127.0.0.1/callback", "http://127.0.0.1:0/callback",
    "http://127.0.0.1:65536/callback", "http://127.0.0.1:bad/callback",
    "http://user@127.0.0.1:48193/callback", "http://127.0.0.1:48193/callback#fragment",
    "http://127.0.0.1:48193/callback?next=https://evil.example",
    "http://127.0.0.1:48193", "http://127.0.0.1:48193/call\nback",
    "\x00http://127.0.0.1:48193/callback", "http://127.0.0.1:48193/call\x7fback",
])
def test_native_opt_in_does_not_allow_arbitrary_http_or_ambiguous_uris(monkeypatch, callback):
    native_client(monkeypatch, callback)
    with pytest.raises(HTTPException):
        configured_client("qa")


def test_exact_native_callback_and_legacy_https_clients(monkeypatch):
    configure(monkeypatch, SimpleNamespace(id="unused"), "unused")
    assert configured_client("qa")["redirect_uris"] == ["https://chat.example/callback"]
    native_client(monkeypatch)
    assert configured_client("qa")["redirect_uris"] == [CALLBACK]
    query, _, scopes, _ = authorization_parameters(auth_query(redirect_uri=CALLBACK))
    assert query["redirect_uri"] == CALLBACK and "crm.catalog.read" in scopes
    for changes in [
        {"redirect_uri": CALLBACK.replace("48193", "48194")},
        {"redirect_uri": CALLBACK + "/other"},
        {"redirect_uri": CALLBACK.replace("127.0.0.1", "localhost")},
        {"redirect_uri": CALLBACK, "code_challenge_method": "plain"},
        {"redirect_uri": CALLBACK, "resource": "https://evil.example/mcp"},
    ]:
        with pytest.raises(HTTPException):
            authorization_parameters(auth_query(**changes))


@PG
def test_native_pkce_exchange_keeps_exact_uri_and_single_use(monkeypatch):
    async def run():
        async with fixture() as (sessions, pid, actor, *_):
            configure(monkeypatch, actor, pid)
            native_client(monkeypatch)
            async with sessions() as db:
                actual = await UserRepository(db).get_by_id(actor.id)
                result = await authorize(db, actual, AuthorizeIn(
                    authorization_query=auth_query(redirect_uri=CALLBACK), project_ids=[pid]))
                assert result["redirect_uri"].startswith(CALLBACK + "?")
                query = parse_qs(urlsplit(result["redirect_uri"]).query)
                assert query["iss"] == ["https://crm.example/assistant-oauth"]
                code = query["code"][0]
                await db.commit()
            async with sessions() as db:
                for changes in [
                    {"redirect_uri": CALLBACK.replace("48193", "48194")},
                    {"code_verifier": "wrong" * 10},
                ]:
                    body = token_body(**({"redirect_uri": CALLBACK, "code": code} | changes))
                    _, status = await exchange(db, body, {})
                    assert status == 400
                body = token_body(redirect_uri=CALLBACK, code=code)
                result, status = await exchange(db, body, {})
                assert status == 200 and result["access_token"]
                await db.commit()
            async with sessions() as db:
                _, status = await exchange(db, body, {})
                assert status == 400
                assert await db.scalar(select(func.count()).select_from(AssistantConnection)) == 1
    asyncio.run(run())
