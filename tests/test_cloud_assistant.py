"""Real PostgreSQL approval/auth tests; no live cloud, partner or Telegram calls."""
import asyncio
import base64
import hashlib
import json
import os
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException, FastAPI
import httpx
from sqlalchemy import func, select, update

from app.core.assistant import now, digest, issuer_url, resource_url
from app.core.config import settings
from app.core.security import create_access_token
from app.models import AuditLog, User
from app.models.assistant import AssistantConnection, AssistantCode, AssistantToken, AssistantProposal
from app.models.gambling_offer import GamblingOffer
from app.models.postback import PostbackEndpoint, PostbackReceipt
from app.repositories.user_repository import UserRepository
from app.schemas.assistant import AuthorizeIn, PrepareIn, SecureInputIn
from app.services.assistant_oauth import authorize, exchange, authenticate
from app.services.assistant_changes import AssistantChanges, put_input
from app.services.assistant_tools import AssistantTools
from test_gambling_offers import fixture

PG = pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
VERIFIER = "v" * 50
CALLBACK = "https://chat.example/callback"


def configure(monkeypatch, actor, pid):
    for key, value in {"ASSISTANT_ENABLED": True, "ASSISTANT_MCP_ENABLED": True, "ASSISTANT_CHANGES_ENABLED": True,
        "ASSISTANT_ALLOWED_USER_IDS": str(actor.id), "ASSISTANT_ALLOWED_PROJECT_IDS": str(pid),
        "ASSISTANT_MCP_RESOURCE_URL": "https://assistant.example/mcp", "BASE_URL": "https://crm.example",
        "ASSISTANT_INPUT_KEY": Fernet.generate_key().decode(),
        "ASSISTANT_OAUTH_CLIENTS_JSON": json.dumps({"qa": {"redirect_uris": [CALLBACK]}})}.items():
        monkeypatch.setattr(settings, key, value)


def auth_query(**changes):
    data = {"response_type": "code", "client_id": "qa", "redirect_uri": CALLBACK, "resource": resource_url(), "state": "qa-state",
        "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("="),
        "code_challenge_method": "S256", "scope": "crm.catalog.read crm.configuration.read crm.changes.prepare crm.diagnostics.read crm.analytics.read"}
    data.update(changes)
    return urlencode(data)


async def login(sessions, actor, pid):
    async with sessions() as db:
        actor = await UserRepository(db).get_by_id(actor.id)
        result = await authorize(db, actor, AuthorizeIn(authorization_query=auth_query(), project_ids=[pid]))
        await db.commit()
        code = parse_qs(urlsplit(result["redirect_uri"]).query)["code"][0]
    async with sessions() as db:
        result, status = await exchange(db, token_body(code=code), {})
        assert status == 200, result
        await db.commit()
        return result, code


def token_body(**changes):
    p = {"grant_type": "authorization_code", "client_id": "qa", "resource": resource_url(), "redirect_uri": CALLBACK, "code_verifier": VERIFIER}
    p.update(changes)
    return urlencode(p)


@PG
def test_oauth_pkce_single_use_refresh_and_revocation(monkeypatch):
    async def run():
        async with fixture() as (sessions, pid, actor, *_):
            configure(monkeypatch, actor, pid)
            token, code = await login(sessions, actor, pid)
            async with sessions() as db:
                actual, conn, scopes = await authenticate(db, token["access_token"])
                assert actual.id == actor.id and "crm.changes.prepare" in scopes
                assert conn.resource == resource_url()
                assert "iss=" in (await authorize(db, actual, AuthorizeIn(authorization_query=auth_query(), project_ids=[pid])))["redirect_uri"]
                response, status = await exchange(db, token_body(code=code), {})
                assert status == 400 and response["error"] == "invalid_grant"
                body = token_body(grant_type="refresh_token", refresh_token=token["refresh_token"])
                rotated, status = await exchange(db, body, {})
                assert status == 200, rotated
                await db.commit()
            async with sessions() as db:
                _, status = await exchange(db, body, {})
                assert status == 400
                await db.commit()
            async with sessions() as db:
                with pytest.raises(HTTPException): await authenticate(db, rotated["access_token"])
                stored = (await db.scalars(select(AssistantToken))).all()
                assert all(token["access_token"] not in str(r.__dict__) for r in stored)
                with pytest.raises(HTTPException): await authenticate(db, create_access_token(actor.id))
    asyncio.run(run())


@PG
@pytest.mark.parametrize("change", [{"resource": "https://evil.example"}, {"redirect_uri": "https://evil.example"},
    {"code_challenge_method": "plain"}, {"scope": "admin"}])
def test_oauth_rejects_untrusted_flow_before_creating_connection(monkeypatch, change):
    async def run():
        async with fixture() as (sessions, pid, actor, *_):
            configure(monkeypatch, actor, pid)
            async with sessions() as db:
                user = await UserRepository(db).get_by_id(actor.id)
                with pytest.raises(HTTPException): await authorize(db, user, AuthorizeIn(authorization_query=auth_query(**change), project_ids=[pid]))
                assert await db.scalar(select(func.count()).select_from(AssistantConnection)) == 0
    asyncio.run(run())


async def make_plan(db, actor, conn, pid, request_id="qa-request-1", name="QA offer", supersedes=None):
    ref = await put_input(db, actor, SecureInputIn(project_id=pid, value="https://example.org/path?partner=private-affiliate-value"))
    data = PrepareIn(project_id=pid, request_id=request_id, supersedes_proposal_id=supersedes, operations=[{
        "kind": "offer.create_inactive", "name": name, "partner_name": "QA PP", "source_url_ref": ref["id"],
        "identifier_parameter": "sub1", "postback_mapping": {"identifier_param": "sub1", "event_type_param": "event",
            "external_event_id_param": "transaction", "amount_param": "amount", "currency_param": "currency"}}])
    return await AssistantChanges(db).prepare(actor, conn, data), data


@PG
def test_no_business_write_until_human_approval_and_parallel_approval_is_once(monkeypatch):
    async def run():
        async with fixture() as (sessions, pid, actor, *_):
            configure(monkeypatch, actor, pid)
            token, _ = await login(sessions, actor, pid)
            async with sessions() as db:
                user, conn, scopes = await authenticate(db, token["access_token"])
                plan, data = await make_plan(db, user, conn, pid)
                again = await AssistantChanges(db).prepare(user, conn, data)
                assert again["id"] == plan["id"]
                assert await db.scalar(select(func.count()).select_from(GamblingOffer)) == 0
                assert await db.scalar(select(func.count()).select_from(PostbackEndpoint)) == 0
                cloud = await AssistantTools(db, user, conn, scopes).call("crm_get_change", {"project_id": str(pid), "proposal_id": plan["id"]})
                assert "private-affiliate-value" not in str(cloud)
                await db.commit()
            async def apply():
                async with sessions() as db:
                    user = await UserRepository(db).get_by_id(actor.id)
                    result = await AssistantChanges(db).apply(user, UUID(plan["id"]), plan["plan_hash"])
                    await db.commit()
                    return result
            results = await asyncio.gather(*(apply() for _ in range(5)))
            assert all(r["status"] == "applied" for r in results)
            assert len({json.dumps(r["result"], sort_keys=True) for r in results}) == 1
            async with sessions() as db:
                offer = await db.scalar(select(GamblingOffer)); endpoint = await db.scalar(select(PostbackEndpoint))
                assert offer and not offer.is_active and endpoint and not endpoint.is_active
                assert await db.scalar(select(func.count()).select_from(GamblingOffer)) == 1
                assert await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "assistant.apply")) == 1
    asyncio.run(run())


@PG
@pytest.mark.parametrize("change", ["expired", "project", "revoke", "flag"])
def test_pending_plan_cannot_bypass_changed_state_or_permissions(monkeypatch, change):
    async def run():
        async with fixture() as (sessions, pid, actor, *_):
            configure(monkeypatch, actor, pid)
            token, _ = await login(sessions, actor, pid)
            async with sessions() as db:
                user, conn, _ = await authenticate(db, token["access_token"])
                plan, _ = await make_plan(db, user, conn, pid)
                await db.commit()
                if change == "expired":
                    row = await db.get(AssistantProposal, UUID(plan["id"])); row.expires_at = now() - timedelta(seconds=1)
                elif change == "project":
                    from app.models import Project
                    (await db.get(Project, pid)).name = "Edited after plan"
                elif change == "revoke": conn.revoked_at = now()
                else: monkeypatch.setattr(settings, "ASSISTANT_CHANGES_ENABLED", False)
                await db.commit()
                if change in {"revoke", "flag"}:
                    with pytest.raises(HTTPException): await AssistantChanges(db).apply(user, UUID(plan["id"]), plan["plan_hash"])
                else:
                    result = await AssistantChanges(db).apply(user, UUID(plan["id"]), plan["plan_hash"])
                    assert result["status"] == ("expired" if change == "expired" else "stale")
                assert await db.scalar(select(func.count()).select_from(GamblingOffer)) == 0
    asyncio.run(run())


@PG
def test_tools_deny_cross_project_and_extra_operation_fields(monkeypatch):
    async def run():
        async with fixture() as (sessions, pid, actor, *_):
            configure(monkeypatch, actor, pid); token, _ = await login(sessions, actor, pid)
            async with sessions() as db:
                user, conn, scopes = await authenticate(db, token["access_token"])
                tools = AssistantTools(db, user, conn, scopes)
                for name, body in [("crm_list_objects", {"project_id": str(uuid4()), "kind": "bots"}),
                    ("crm_get_lead_summary", {"project_id": str(pid), "lead_id": str(uuid4())}), ("approve", {})]:
                    with pytest.raises(HTTPException): await tools.call(name, body)
                with pytest.raises(ValueError): PrepareIn(project_id=pid, request_id="qa-request-1", operations=[{
                    "kind": "offer.create_inactive", "name": "x", "partner_name": "x", "source_url_ref": str(uuid4()), "is_active": True}])
                access = await tools.call("crm_get_access", {})
                assert len(access["data"]["projects"]) == 1
    asyncio.run(run())


@PG
def test_bad_pkce_does_not_consume_code_and_resource_change_revokes_access(monkeypatch):
    async def run():
        async with fixture() as (sessions, pid, actor, *_):
            configure(monkeypatch, actor, pid)
            async with sessions() as db:
                user = await UserRepository(db).get_by_id(actor.id)
                reply = await authorize(db, user, AuthorizeIn(authorization_query=auth_query(), project_ids=[pid]))
                code = parse_qs(urlsplit(reply["redirect_uri"]).query)["code"][0]
                await db.commit()
                bad, status = await exchange(db, token_body(code=code, code_verifier="wrong" * 10), {})
                assert status == 400
                assert (await db.get(AssistantCode, digest(code))).consumed_at is None
                good, status = await exchange(db, token_body(code=code), {})
                assert status == 200, good
                await db.commit()
                monkeypatch.setattr(settings, "ASSISTANT_MCP_RESOURCE_URL", "https://other.example/mcp")
                with pytest.raises(HTTPException): await authenticate(db, good["access_token"])
    asyncio.run(run())


@PG
def test_confidential_oauth_client_requires_correct_basic_secret(monkeypatch):
    async def run():
        async with fixture() as (sessions, pid, actor, *_):
            configure(monkeypatch, actor, pid)
            monkeypatch.setattr(settings, "ASSISTANT_OAUTH_CLIENTS_JSON", json.dumps({"qa": {"redirect_uris": [CALLBACK], "secret_sha256": digest("test-client-secret")}}))
            async with sessions() as db:
                user = await UserRepository(db).get_by_id(actor.id)
                reply = await authorize(db, user, AuthorizeIn(authorization_query=auth_query(), project_ids=[pid]))
                code = parse_qs(urlsplit(reply["redirect_uri"]).query)["code"][0]; await db.commit()
                _, status = await exchange(db, token_body(code=code), {})
                assert status == 401
                headers = {"Authorization": "Basic " + base64.b64encode(b"qa:test-client-secret").decode()}
                good, status = await exchange(db, token_body(code=code), headers)
                assert status == 200, good
    asyncio.run(run())


@PG
def test_lost_prepare_response_replacement_and_cancelled_approval(monkeypatch):
    async def run():
        async with fixture() as (sessions, pid, actor, *_):
            configure(monkeypatch, actor, pid); token, _ = await login(sessions, actor, pid)
            async with sessions() as db:
                user, conn, _ = await authenticate(db, token["access_token"])
                first, data = await make_plan(db, user, conn, pid)
                with pytest.raises(HTTPException):
                    await AssistantChanges(db).prepare(user, conn, data.model_copy(update={"operations": []}))
                next_plan, _ = await make_plan(db, user, conn, pid, request_id="qa-request-2", name="New", supersedes=UUID(first["id"]))
                await db.commit()
                assert (await db.get(AssistantProposal, UUID(first["id"]))).status == "cancelled"
                with pytest.raises(HTTPException): await AssistantChanges(db).apply(user, UUID(first["id"]), first["plan_hash"])
                result = await AssistantChanges(db).apply(user, UUID(next_plan["id"]), next_plan["plan_hash"])
                assert result["status"] == "applied"
    asyncio.run(run())


@PG
def test_multi_operation_failure_rolls_back_all_effects(monkeypatch):
    from app.services.gambling_offer_service import GamblingOfferService
    async def run():
        async with fixture() as (sessions, pid, actor, *_):
            configure(monkeypatch, actor, pid); token, _ = await login(sessions, actor, pid)
            async with sessions() as db:
                user, conn, _ = await authenticate(db, token["access_token"])
                _, data = await make_plan(db, user, conn, pid)
                await db.rollback()
            async with sessions() as db:
                user, conn, _ = await authenticate(db, token["access_token"])
                ref = await put_input(db, user, SecureInputIn(project_id=pid, value="https://example.org"))
                operation = data.operations[0].model_copy(update={"source_url_ref": UUID(ref["id"])})
                data = data.model_copy(update={"operations": [operation, operation.model_copy(update={"name": "Second"})]})
                plan = await AssistantChanges(db).prepare(user, conn, data); await db.commit()
                original = GamblingOfferService.save
                calls = []
                async def save(service, *args, **kwargs):
                    calls.append(1)
                    if len(calls) == 2: raise RuntimeError("private payload must not leak")
                    return await original(service, *args, **kwargs)
                monkeypatch.setattr(GamblingOfferService, "save", save)
                result = await AssistantChanges(db).apply(user, UUID(plan["id"]), plan["plan_hash"])
                assert result["status"] == "failed" and "private payload" not in str(result)
                await db.commit()
                assert await db.scalar(select(func.count()).select_from(GamblingOffer)) == 0
                assert await db.scalar(select(func.count()).select_from(PostbackEndpoint)) == 0
                assert await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "assistant.apply")) == 0
    asyncio.run(run())


@PG
def test_ui_and_cloud_tokens_cannot_cross_approval_boundary(monkeypatch):
    from app.api.v1.routers import assistant as routes
    from app.core.assistant import assistant_db
    from app.api.v1.dependencies import get_current_user, get_db
    async def run():
        async with fixture() as (sessions, pid, actor, *_):
            configure(monkeypatch, actor, pid); token, _ = await login(sessions, actor, pid)
            app = FastAPI(); app.include_router(routes.router); app.include_router(routes.oauth_router)
            async def dependency():
                async with sessions() as db:
                    try: yield db; await db.commit()
                    except BaseException: await db.rollback(); raise
            app.dependency_overrides[assistant_db] = dependency
            app.dependency_overrides[get_db] = dependency
            native = create_access_token(actor.id)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://crm.example") as client:
                headers = {"Authorization": "Bearer " + token["access_token"], "Origin": "https://crm.example"}
                response = await client.post("/api/v1/assistant/proposals/" + str(uuid4()) + "/approve-and-apply", headers=headers, json={"expected_plan_hash": "a"*64})
                assert response.status_code == 401
                response = await client.get("/api/v1/assistant/session", headers={"Authorization": "Bearer " + native})
                assert response.status_code == 401
                response = await client.post("/api/v1/assistant/secure-inputs", headers={"Authorization": "Bearer " + native, "Origin": "https://evil.example"}, json={"project_id": str(pid), "value": "https://example.org"})
                assert response.status_code == 403
                monkeypatch.setattr(settings, "ASSISTANT_ENABLED", False)
                assert (await client.get("/api/v1/assistant/connections", headers={"Authorization": "Bearer " + native})).status_code == 404
            from app.core.redis import close_redis
            await close_redis()
    asyncio.run(run())


@PG
def test_inactive_endpoint_cannot_be_edited_after_ever_being_enabled(monkeypatch):
    from app.services.postback_endpoint_service import PostbackEndpointService
    from app.schemas.postback import PostbackEndpointCreate, PostbackEndpointUpdate
    async def run():
        async with fixture() as (sessions, pid, actor, *_):
            configure(monkeypatch, actor, pid); token, _ = await login(sessions, actor, pid)
            async with sessions() as db:
                user, conn, _ = await authenticate(db, token["access_token"])
                service = PostbackEndpointService(db)
                endpoint = await service.create_endpoint(project_id=pid, actor=user, data=PostbackEndpointCreate(name="Unused", is_active=False))
                row = await db.get(PostbackEndpoint, endpoint.id); assert not row.ever_active
                for active in [True, False]: await service.update_endpoint(endpoint_id=row.id, project_id=pid, actor=user, data=PostbackEndpointUpdate(is_active=active))
                assert row.ever_active
                with pytest.raises(HTTPException): await AssistantChanges(db).prepare(user, conn, PrepareIn(project_id=pid, request_id="qa-request-1", operations=[{"kind": "postback.update_disabled", "endpoint_id": row.id, "name": "Changed"}]))
    asyncio.run(run())


@PG
def test_schema_migration_is_additive_and_legacy_endpoint_history_is_unknown(monkeypatch):
    import importlib.util
    from pathlib import Path
    from sqlalchemy import text
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    async def run():
        async with fixture() as (sessions, pid, actor, leads, *_):
            engine = sessions.kw["bind"]
            async with engine.begin() as db:
                for name in ["assistant_secure_inputs", "assistant_change_proposals", "assistant_oauth_tokens", "assistant_oauth_codes", "assistant_connections"]:
                    await db.execute(text(f'DROP TABLE "{name}"'))
                await db.execute(text("ALTER TABLE postback_endpoints DROP COLUMN ever_active"))
                endpoint_id = uuid4()
                await db.execute(text("INSERT INTO postback_endpoints(id,project_id,name,secret_token,event_type,is_active) VALUES (:id,:pid,'legacy','legacy-qa','registration',false)"), {"id": endpoint_id, "pid": pid})
            module_spec = importlib.util.spec_from_file_location("assistant_migration", Path(__file__).parents[1] / "alembic/versions/20261107_0098_cloud_assistant.py")
            migration = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(migration)
            async with engine.begin() as db:
                def upgrade(connection):
                    with Operations.context(MigrationContext.configure(connection)): migration.upgrade()
                await db.run_sync(upgrade)
            async with sessions() as db:
                from app.models import Lead
                assert await db.scalar(select(func.count()).select_from(Lead)) == len(leads)
                endpoint = await db.get(PostbackEndpoint, endpoint_id)
                assert endpoint.ever_active and not endpoint.is_active and endpoint.secret_token == "legacy-qa"
                assert await db.scalar(select(func.count()).select_from(AssistantConnection)) == 0
    asyncio.run(run())


@PG
def test_standalone_endpoint_update_preserves_disabled_state_and_offer_update_preserves_finance(monkeypatch):
    from app.services.postback_endpoint_service import PostbackEndpointService
    from app.schemas.postback import PostbackEndpointCreate
    from app.schemas.gambling_offer import OfferWrite, PayoutPolicyWrite
    from app.services.offer_payout_service import OfferPayoutService
    from app.services.gambling_offer_service import GamblingOfferService
    async def run():
        async with fixture() as (sessions, pid, actor, *_):
            configure(monkeypatch, actor, pid); token, _ = await login(sessions, actor, pid)
            async with sessions() as db:
                user, conn, _ = await authenticate(db, token["access_token"])
                endpoint = await PostbackEndpointService(db).create_endpoint(project_id=pid, actor=user, data=PostbackEndpointCreate(name="Never active", is_active=False))
                data = PrepareIn(project_id=pid, request_id="qa-update-endpoint", operations=[{"kind": "postback.update_disabled", "endpoint_id": endpoint.id, "name": "New name"}])
                plan = await AssistantChanges(db).prepare(user, conn, data); await db.commit()
                result = await AssistantChanges(db).apply(user, UUID(plan["id"]), plan["plan_hash"])
                assert result["status"] == "applied", result
                await db.commit()
                row = await db.get(PostbackEndpoint, endpoint.id); assert row.name == "New name" and not row.is_active and not row.ever_active
                policy = await OfferPayoutService(db).save_policy(pid, user, PayoutPolicyWrite(name="Private finance", partner_name="QA PP", terms={"rate": "10"}))
                offer = await GamblingOfferService(db).save(pid, user, OfferWrite(name="Off", partner_name="QA PP", source_url="https://example.org", is_active=False, payout_policy_id=policy["id"]))
                data = PrepareIn(project_id=pid, request_id="qa-update-offer", operations=[{"kind": "offer.update_inactive", "offer_id": offer["id"], "name": "Renamed"}])
                plan = await AssistantChanges(db).prepare(user, conn, data); await db.commit()
                assert "Private finance" not in str(plan) and str(policy["id"]) not in str(plan)
                result = await AssistantChanges(db).apply(user, UUID(plan["id"]), plan["plan_hash"])
                assert result["status"] == "applied", result
                row = await db.get(GamblingOffer, offer["id"])
                assert row.name == "Renamed" and row.payout_policy_id == policy["id"] and not row.is_active
    asyncio.run(run())


@PG
def test_real_ui_approval_request_requires_origin_hash_and_login(monkeypatch):
    from app.api.v1.routers import assistant as routes
    from app.core.assistant import assistant_db
    from app.api.v1.dependencies import get_db
    async def run():
        async with fixture() as (sessions, pid, actor, *_):
            configure(monkeypatch, actor, pid); token, _ = await login(sessions, actor, pid)
            async with sessions() as db:
                user, conn, _ = await authenticate(db, token["access_token"])
                plan, _ = await make_plan(db, user, conn, pid); await db.commit()
            app = FastAPI(); app.include_router(routes.router)
            async def dependency():
                async with sessions() as db:
                    try: yield db; await db.commit()
                    except BaseException: await db.rollback(); raise
            app.dependency_overrides[assistant_db] = dependency; app.dependency_overrides[get_db] = dependency
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://crm.example") as client:
                path = "/api/v1/assistant/proposals/" + plan["id"] + "/approve-and-apply"
                auth = {"Authorization": "Bearer " + create_access_token(actor.id)}
                assert (await client.get(path, headers=auth)).status_code == 405
                assert (await client.post(path, headers=auth, json={"expected_plan_hash": plan["plan_hash"]})).status_code == 403
                auth["Origin"] = "https://crm.example"
                assert (await client.post(path, headers=auth, json={"expected_plan_hash": "b"*64})).status_code == 409
                good = await client.post(path, headers=auth, json={"expected_plan_hash": plan["plan_hash"]})
                assert good.status_code == 200 and good.json()["status"] == "applied", good.text
                again = await client.post(path, headers=auth, json={"expected_plan_hash": plan["plan_hash"]})
                assert again.json()["result"] == good.json()["result"]
            from app.core.redis import close_redis
            await close_redis()
    asyncio.run(run())


@PG
def test_every_read_tool_is_scoped_and_draft_preview_has_no_business_side_effects(monkeypatch):
    cache = {}
    async def cached(key, value=None):
        if value is not None: cache[key] = value
        else: return cache.get(key)
    monkeypatch.setattr("app.services.assistant_tools.cached_report", cached)
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bot_id, link_id):
            configure(monkeypatch, actor, pid); token, _ = await login(sessions, actor, pid)
            async with sessions() as db:
                user, conn, scopes = await authenticate(db, token["access_token"])
                tools = AssistantTools(db, user, conn, scopes)
                for kind in ["bots", "tracking_links", "funnel_versions", "offers", "postback_endpoints"]:
                    result = await tools.call("crm_list_objects", {"project_id": str(pid), "kind": kind})
                    assert "items" in result["data"]
                result = await tools.call("crm_get_configuration", {"project_id": str(pid), "kind": "bot", "object_id": str(bot_id)})
                assert result["data"]["id"] == str(bot_id)
                result = await tools.call("crm_get_tracking", {"project_id": str(pid), "link_id": str(link_id)})
                assert "spend" not in result["data"]["summary"] and result["data"]["timezone"] == "UTC"
                assert "daily" in result["data"]
                cached_result = await tools.call("crm_get_tracking", {"project_id": str(pid), "link_id": str(link_id)})
                assert cached_result["data"]["cached"] is True
                assert cached_result["data"]["generated_at"] == result["data"]["generated_at"]
                conn.policy_version += 1
                changed = await tools.call("crm_get_tracking", {"project_id": str(pid), "link_id": str(link_id)})
                assert changed["data"]["cached"] is False
                result = await tools.call("crm_get_postback_diagnostics", {"project_id": str(pid)})
                assert result["data"]["counts"] == {}
                result = await tools.call("crm_preview_postback", {"project_id": str(pid), "draft_contract": {"identifier_param": "sub", "event_type_param": "type"}, "sample": {"sub": "qa-token", "type": "reg"}})
                assert result["data"]["status"] == "syntax_valid" and not result["data"]["business_writes"]
                assert await db.scalar(select(func.count()).select_from(PostbackReceipt)) == 0
                assert await db.scalar(select(func.count()).select_from(GamblingOffer)) == 0
                with pytest.raises(HTTPException): await tools.call("crm_get_tracking", {"project_id": str(pid), "link_id": str(uuid4())})
    asyncio.run(run())


def test_report_cache_uses_separate_namespace_and_thirty_second_expiry(monkeypatch):
    from app.core import assistant, redis as redis_module
    class Redis:
        data = {}
        async def set(self, key, value, *, ex):
            assert key.startswith("crm:assistant:report:") and ex == 30
            self.data[key] = value
        async def get(self, key): return self.data.get(key)
    redis = Redis()
    async def get(): return redis
    monkeypatch.setattr(redis_module, "get_redis", get)
    async def run():
        assert await assistant.cached_report("qa") is None
        await assistant.cached_report("qa", {"summary": {"starts": 1}})
        assert await assistant.cached_report("qa") == {"summary": {"starts": 1}}
        await assistant.cached_report("huge", {"x": "x" * 65536})
        assert await assistant.cached_report("huge") is None
    asyncio.run(run())


@PG
def test_draft_assignment_does_not_publish_or_change_current_funnel(monkeypatch):
    from app.models import Bot
    from app.models.funnel import Funnel, FunnelVersion
    from app.schemas.gambling_offer import OfferWrite
    from app.services.gambling_offer_service import GamblingOfferService
    async def run():
        async with fixture() as (sessions, pid, actor, _, bot_id, _):
            configure(monkeypatch, actor, pid); token, _ = await login(sessions, actor, pid)
            async with sessions() as db:
                user, conn, _ = await authenticate(db, token["access_token"])
                offer = await GamblingOfferService(db).save(pid, user, OfferWrite(name="Existing", partner_name="PP", source_url="https://example.org"))
                funnel = Funnel(project_id=pid, bot_id=bot_id, name="QA"); db.add(funnel); await db.flush()
                current = FunnelVersion(funnel_id=funnel.id, version_number=1, status="published")
                draft = FunnelVersion(funnel_id=funnel.id, version_number=2, status="draft")
                db.add_all([current, draft]); await db.flush()
                bot = await db.get(Bot, bot_id); bot.active_funnel_id, bot.active_funnel_version_id = funnel.id, current.id
                data = PrepareIn(project_id=pid, request_id="qa-assignment-1", operations=[{"kind": "funnel.assign_offer_draft", "version_id": draft.id, "offer_id": offer["id"]}])
                plan = await AssistantChanges(db).prepare(user, conn, data); await db.commit()
                result = await AssistantChanges(db).apply(user, UUID(plan["id"]), plan["plan_hash"])
                assert result["status"] == "applied"
                assert draft.status == "draft" and draft.offer_id == offer["id"]
                assert current.offer_id is None and bot.active_funnel_version_id == current.id
                with pytest.raises(HTTPException): await AssistantChanges(db).prepare(user, conn, data.model_copy(update={"request_id": "qa-assignment-2", "operations": [data.operations[0].model_copy(update={"version_id": current.id})]}))
    asyncio.run(run())


@PG
def test_ui_confirm_cannot_use_expired_or_foreign_secure_input(monkeypatch):
    async def run():
        async with fixture() as (sessions, pid, actor, *_):
            configure(monkeypatch, actor, pid); token, _ = await login(sessions, actor, pid)
            async with sessions() as db:
                user, conn, scopes = await authenticate(db, token["access_token"])
                plan, data = await make_plan(db, user, conn, pid)
                await db.commit()
                from app.models.assistant import AssistantSecureInput
                ref = await db.get(AssistantSecureInput, data.operations[0].source_url_ref)
                ref.expires_at = now() - timedelta(seconds=1); await db.commit()
                result = await AssistantChanges(db).apply(user, UUID(plan["id"]), plan["plan_hash"])
                assert result["status"] == "stale"
                assert await db.scalar(select(func.count()).select_from(GamblingOffer)) == 0
                with pytest.raises(HTTPException):
                    await AssistantTools(db, user, conn, scopes).call("crm_prepare_change", {"project_id": str(pid), "request_id": "qa-foreign-ref", "operations": [{"kind": "offer.create_inactive", "source_url_ref": str(uuid4()), "name": "QA", "partner_name": "PP", "postbacks_enabled": False}]})
    asyncio.run(run())


@PG
@pytest.mark.parametrize("removed", ["user", "project", "scope", "role"])
def test_approval_rechecks_current_access_not_the_preparation_grant(monkeypatch, removed):
    async def run():
        async with fixture() as (sessions, pid, actor, *_):
            configure(monkeypatch, actor, pid); token, _ = await login(sessions, actor, pid)
            async with sessions() as db:
                user, conn, _ = await authenticate(db, token["access_token"])
                plan, _ = await make_plan(db, user, conn, pid); await db.commit()
            async with sessions() as db:
                if removed == "user": monkeypatch.setattr(settings, "ASSISTANT_ALLOWED_USER_IDS", "")
                elif removed == "project": monkeypatch.setattr(settings, "ASSISTANT_ALLOWED_PROJECT_IDS", "")
                elif removed == "scope":
                    conn = await db.get(AssistantConnection, conn.id)
                    conn.scopes = ["crm.catalog.read"]
                else:
                    from app.models import Role
                    role = Role(name="assistant_denied_test"); db.add(role); await db.flush()
                    (await db.get(User, actor.id)).role_id = role.id
                await db.commit()
                user = await UserRepository(db).get_by_id(actor.id)
                with pytest.raises(HTTPException): await AssistantChanges(db).apply(user, UUID(plan["id"]), plan["plan_hash"])
                assert await db.scalar(select(func.count()).select_from(GamblingOffer)) == 0
    asyncio.run(run())


@PG
def test_legacy_revision_cannot_prove_endpoint_was_never_active(monkeypatch):
    from app.models.postback import PostbackEndpointRevision
    from app.schemas.postback import PostbackEndpointCreate
    from app.services.postback_endpoint_service import PostbackEndpointService
    async def run():
        async with fixture() as (sessions, pid, actor, *_):
            configure(monkeypatch, actor, pid); token, _ = await login(sessions, actor, pid)
            async with sessions() as db:
                user, conn, _ = await authenticate(db, token["access_token"])
                endpoint = await PostbackEndpointService(db).create_endpoint(project_id=pid, actor=user, data=PostbackEndpointCreate(name="QA rollback", is_active=False))
                revision = await db.get(PostbackEndpointRevision, (endpoint.id, endpoint.revision))
                revision.config_json = {k: v for k, v in revision.config_json.items() if k != "activity_history_version"}
                await db.commit()
                with pytest.raises(HTTPException):
                    await AssistantChanges(db).prepare(user, conn, PrepareIn(project_id=pid, request_id="qa-legacy-revision", operations=[{"kind": "postback.update_disabled", "endpoint_id": endpoint.id, "name": "Unsafe"}]))
    asyncio.run(run())


def test_disabled_module_does_not_create_pool_and_limiter_fails_closed(monkeypatch):
    from app.core import assistant, redis as redis_module
    async def run():
        monkeypatch.setattr(settings, "ASSISTANT_ENABLED", False)
        def unexpected_pool(): raise AssertionError("Disabled module initialized a database pool")
        monkeypatch.setattr(assistant, "session_factory", unexpected_pool)
        with pytest.raises(HTTPException) as disabled: await assistant.assistant_db().__anext__()
        assert disabled.value.status_code == 404
        async def unavailable(): raise ConnectionError("private redis address")
        monkeypatch.setattr(redis_module, "get_redis", unavailable)
        with pytest.raises(HTTPException) as limited: await assistant.limit("qa", 1, 1)
        assert limited.value.status_code == 503 and limited.value.detail == "assistant_limiter_unavailable"
        with pytest.raises(HTTPException) as heavy:
            async with assistant.heavy_lease(): raise AssertionError("Must not run without a global lease")
        assert heavy.value.status_code == 503
    asyncio.run(run())


def test_oauth_token_protocol_errors_are_safe_standard_responses(monkeypatch):
    async def run():
        configure(monkeypatch, SimpleNamespace(id=uuid4()), uuid4())
        for body, error, status in [
            (token_body(client_id="not-configured"), "invalid_client", 401),
            (token_body() + "&client_id=duplicate", "invalid_request", 400),
            (token_body(resource="https://foreign.example/mcp"), "invalid_target", 400),
        ]:
            response, actual = await exchange(None, body, {})
            assert actual == status and response == {"error": error}
    asyncio.run(run())


@PG
def test_saved_endpoint_preview_and_minimal_lead_summary_are_read_only(monkeypatch):
    from decimal import Decimal
    from app.models import Lead
    from app.models.lead_event import LeadEvent
    from app.schemas.postback import PostbackEndpointCreate, PostbackEndpointUpdate, PostbackParameterMapping
    from app.services.postback_endpoint_service import PostbackEndpointService
    async def run():
        async with fixture() as (sessions, pid, actor, leads, *_):
            configure(monkeypatch, actor, pid); token, _ = await login(sessions, actor, pid)
            async with sessions() as db:
                user, conn, scopes = await authenticate(db, token["access_token"])
                conn.scopes = [*conn.scopes, "crm.leads.summary.read"]; scopes.add("crm.leads.summary.read")
                lead = await db.get(Lead, leads[0]); lead.name = "PRIVATE CONTACT CANARY"
                db.add(LeadEvent(project_id=pid, lead_id=lead.id, event_type="deposit", source="manual",
                    amount=Decimal("123.45"), currency="USD", occurred_at=now(), payload_json={"secret": "PRIVATE PAYLOAD CANARY"}))
                service = PostbackEndpointService(db)
                endpoint = await service.create_endpoint(project_id=pid, actor=user, data=PostbackEndpointCreate(name="QA preview", is_active=False,
                    parameter_mapping=PostbackParameterMapping(identifier_type="lead_id", identifier_param="lead", external_event_id_param="transaction")))
                await db.commit()
                tools = AssistantTools(db, user, conn, scopes)
                arguments = {"project_id": str(pid), "endpoint_id": str(endpoint.id), "sample": {"lead": str(lead.id), "transaction": "qa-preview"}}
                disabled = await tools.call("crm_preview_postback", arguments)
                assert disabled["data"]["status"] == "syntax_valid"
                assert disabled["data"]["identity_resolution"] == "not_performed_for_disabled_endpoint"
                await service.update_endpoint(endpoint_id=endpoint.id, project_id=pid, actor=user, data=PostbackEndpointUpdate(is_active=True))
                await db.commit()
                active = await tools.call("crm_preview_postback", arguments)
                assert active["data"]["status"] == "matched" and not active["data"]["business_writes"]
                summary = await tools.call("crm_get_lead_summary", {"project_id": str(pid), "lead_id": str(lead.id)})
                assert summary["data"]["events"][0]["amount"] == "123.45"
                secret = (await db.get(PostbackEndpoint, endpoint.id)).secret_token
                assert "PRIVATE" not in str(summary) and secret not in str(active)
                assert await db.scalar(select(func.count()).select_from(PostbackReceipt)) == 0
                assert await db.scalar(select(func.count()).select_from(LeadEvent)) == 1
    asyncio.run(run())


@PG
def test_nonempty_graph_and_receipt_pagination_exclude_private_payloads(monkeypatch):
    from app.models.funnel import Funnel, FunnelVersion, FunnelStep, FunnelEdge
    from app.schemas.postback import PostbackEndpointCreate
    from app.services.postback_endpoint_service import PostbackEndpointService
    async def run():
        async with fixture() as (sessions, pid, actor, _, bot_id, _):
            configure(monkeypatch, actor, pid); token, _ = await login(sessions, actor, pid)
            async with sessions() as db:
                user, conn, scopes = await authenticate(db, token["access_token"])
                funnel = Funnel(project_id=pid, bot_id=bot_id, name="QA graph"); db.add(funnel); await db.flush()
                version = FunnelVersion(funnel_id=funnel.id, version_number=1, status="draft"); db.add(version); await db.flush()
                first = FunnelStep(funnel_version_id=version.id, key="first", title="First", step_type="message", block_type="message",
                    config_json={"source_url": "https://example.org/PRIVATE-GRAPH-CANARY"})
                second = FunnelStep(funnel_version_id=version.id, key="second", title="Second", step_type="message", block_type="message")
                db.add_all([first, second]); await db.flush()
                db.add(FunnelEdge(funnel_version_id=version.id, from_step_id=first.id, to_step_id=second.id, condition_json={"private": "PRIVATE-GRAPH-CANARY"}))
                endpoint = await PostbackEndpointService(db).create_endpoint(project_id=pid, actor=user, data=PostbackEndpointCreate(name="QA receipts", is_active=False))
                for status in ["matched", "invalid"]:
                    db.add(PostbackReceipt(endpoint_id=endpoint.id, project_id=pid, received_at=now(), request_method="POST", event_type="registration",
                        status=status, body_payload={"private": "PRIVATE-RECEIPT-CANARY"}, error_message="PRIVATE-ERROR-CANARY"))
                await db.commit()
                tools = AssistantTools(db, user, conn, scopes)
                graph = await tools.call("crm_get_configuration", {"project_id": str(pid), "kind": "funnel_version", "object_id": str(version.id)})
                assert len(graph["data"]["steps"]) == 2 and len(graph["data"]["edges"]) == 1
                args = {"project_id": str(pid), "endpoint_id": str(endpoint.id), "limit": 1}
                page1 = await tools.call("crm_get_postback_diagnostics", args)
                page2 = await tools.call("crm_get_postback_diagnostics", {**args, "cursor": page1["data"]["next_cursor"]})
                assert page1["data"]["counts"] == {"matched": 1, "invalid": 1}
                assert page1["data"]["business_delivery_verified"] is False
                assert page1["data"]["items"][0]["id"] != page2["data"]["items"][0]["id"]
                assert page2["data"]["next_cursor"] is None
                secret = (await db.get(PostbackEndpoint, endpoint.id)).secret_token
                assert "PRIVATE" not in str([graph, page1, page2]) and secret not in str([page1, page2])
    asyncio.run(run())
