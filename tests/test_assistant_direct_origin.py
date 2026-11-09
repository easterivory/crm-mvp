import asyncio
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request

from app.core.assistant import assistant_base_url, issuer_url
from app.core.assistant_boundary import AssistantBoundaryMiddleware
from app.core.config import settings
from app.api.v1.routers.assistant import oauth_router, ui_origin
from app.services.assistant_oauth import authenticate
from test_cloud_assistant import configure, auth_query, login, make_plan, PG
from test_gambling_offers import fixture


def test_legacy_base_is_unchanged_and_override_does_not_mutate_crm(monkeypatch):
    monkeypatch.setattr(settings, "BASE_URL", "https://crm.example")
    monkeypatch.setattr(settings, "ASSISTANT_PUBLIC_BASE_URL", "")
    assert issuer_url() == "https://crm.example/assistant-oauth"
    monkeypatch.setattr(settings, "ASSISTANT_PUBLIC_BASE_URL", "https://assistant.example/")
    assert assistant_base_url() == "https://assistant.example"
    assert issuer_url() == "https://assistant.example/assistant-oauth"
    assert settings.BASE_URL == "https://crm.example"


@pytest.mark.parametrize("value", ["http://assistant.example", "https://u:p@assistant.example", "https://assistant.example/path",
    "https://assistant.example?x=1", "https://assistant.example#f", "https://assistant.example:bad", "https://assistant.exa\nmple", "https://",
    "https://[", "https://assistant.example:0", "https://assistant.example:65536", "https://assistant.exa\x7fmple"])
def test_explicit_public_origin_rejects_unsafe_configuration(monkeypatch, value):
    monkeypatch.setattr(settings, "ASSISTANT_PUBLIC_BASE_URL", value)
    with pytest.raises(HTTPException) as exc: assistant_base_url()
    assert exc.value.status_code == 503


def test_discovery_consent_and_boundary_all_use_direct_origin(monkeypatch):
    async def run():
        configure(monkeypatch, SimpleNamespace(id="unused"), "unused")
        monkeypatch.setattr(settings, "ASSISTANT_PUBLIC_BASE_URL", "https://assistant.example")
        app = FastAPI()
        app.include_router(oauth_router)
        app.add_middleware(AssistantBoundaryMiddleware)
        @app.post("/api/v1/assistant/test-human")
        async def human(request: Request):
            ui_origin(request)
            return {"ok": True}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://assistant.example") as client:
            data = (await client.get("/assistant-oauth/.well-known/oauth-authorization-server")).json()
            assert data["issuer"] == issuer_url()
            assert data["authorization_endpoint"].startswith("https://assistant.example/")
            redirect = await client.get("/assistant-oauth/authorize", params=dict(parse_qsl(auth_query())), follow_redirects=False)
            assert redirect.status_code == 303
            assert urlsplit(redirect.headers["location"]).netloc == "assistant.example"
            assert (await client.post("/api/v1/assistant/test-human", headers={"Origin": "https://assistant.example"})).status_code == 200
            for origin in ("https://crm.example", "http://assistant.example", "https://evil.example"):
                assert (await client.post("/api/v1/assistant/test-human", headers={"Origin": origin})).status_code == 403
            assert (await client.post("/api/v1/assistant/test-human")).status_code == 403
    asyncio.run(run())


@PG
def test_direct_issuer_token_roundtrip_and_old_issuer_not_accepted(monkeypatch):
    async def run():
        async with fixture() as (sessions, pid, actor, *_):
            configure(monkeypatch, actor, pid)
            monkeypatch.setattr(settings, "ASSISTANT_PUBLIC_BASE_URL", "https://assistant.example")
            token, _ = await login(sessions, actor, pid)
            async with sessions() as db:
                user, connection, _ = await authenticate(db, token["access_token"])
                assert connection.issuer == "https://assistant.example/assistant-oauth"
                plan, _ = await make_plan(db, user, connection, pid)
                assert urlsplit(plan["approval_url"]).netloc == "assistant.example"
            monkeypatch.setattr(settings, "ASSISTANT_PUBLIC_BASE_URL", "")
            async with sessions() as db:
                with pytest.raises(HTTPException): await authenticate(db, token["access_token"])
    asyncio.run(run())
