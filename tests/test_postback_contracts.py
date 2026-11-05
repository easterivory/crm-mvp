"""Business acceptance tests: real PostgreSQL, real matching, commits and reports."""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4, UUID
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func, text, MetaData
from sqlalchemy.ext.asyncio import create_async_engine

from tests.test_postback_relay import fixture, TOKEN, SECRET, enable, headers, DELIVERY_PATH
from app.models import Project, Bot, Chat, Lead
from app.models.lead_event import LeadEvent
from app.models.lead_status import LeadStatus
from app.models.partner import PartnerIntegration, LeadSubmission
from app.models.postback import (PostbackEndpoint, PostbackReceipt, PostbackBusinessEffect,
    PostbackEndpointRevision, PostbackBinding, PostbackFollowup, PostbackRelayDelivery)
from app.schemas.postback import PostbackEndpointUpdate, PostbackBindingCreate
from app.services.postback_contract_service import PostbackContractService, normalize, snapshot, remember_personal_link
from app.services.postback_endpoint_service import PostbackEndpointService
from app.services.postback_relay_service import manifest
from app.repositories.lifecycle_metrics_repository import LifecycleMetricsRepository
from postback_gateway.config import Config
from postback_gateway.queue import Queue
from postback_gateway.relay import Relay

PG = pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
ACTOR = SimpleNamespace(id=uuid4(), role_name="super_admin")


def test_overlong_partner_status_is_invalid_before_receipt_insert():
    status = "s" * 101
    with pytest.raises(ValueError, match="100 characters"):
        normalize({"processing_kind": "submission_status", "parameter_mapping": {
            "event_type_param": "status", "status_mapping": {status: "new"}}},
            {"lead_id": str(uuid4()), "status": status}, datetime.now(timezone.utc))


@pytest.mark.parametrize("value", ["Infinity", "NaN", "-1", "1.234", "10000000000000000", "nonsense"])
def test_invalid_money_cannot_become_a_retrying_database_error(value):
    with pytest.raises((ValueError, ArithmeticError)):
        normalize({"event_type": "deposit", "parameter_mapping": {"amount_param": "amount"}},
            {"lead_id": str(uuid4()), "amount": value}, datetime.now(timezone.utc))


@PG
def test_reg_fd_rd_retries_conflicts_and_real_report():
    async def run():
        async with fixture() as (sessions, app, pid, lid, eid):
            async with sessions() as db:
                endpoint = await db.get(PostbackEndpoint, eid)
                endpoint.parameter_mapping = {"event_type_param": "type", "external_event_id_param": "event_id",
                    "amount_param": "amount", "currency_param": "currency", "occurred_at_param": "at", "require_event_id": True}
                await db.commit()
            async def receive(payload):
                async with sessions() as db:
                    result = await PostbackEndpointService(db).receive(secret_token=TOKEN, request_method="POST", query_payload={}, body_payload=payload)
                    await db.commit()
                    return result
            timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            for kind, event_id in [("reg", "reg-1"), ("fd", "fd-1"), ("rd", "rd-1"), ("rd", "rd-2")]:
                payload = {"lead_id": str(lid), "type": kind, "event_id": event_id, "at": timestamp, "amount": "20.00", "currency": "usd"}
                results = await asyncio.gather(*(receive(payload) for _ in range(20)))
                assert sum(r.status == "processed" for r in results) == 1
                assert sum(r.status == "duplicate" for r in results) == 19
            conflict = await receive({"lead_id": str(lid), "type": "rd", "event_id": "rd-1", "at": timestamp, "amount": 21, "currency": "usd"})
            assert conflict.status == "conflict"
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(LeadEvent)) == 4
                assert await db.scalar(select(func.count()).select_from(PostbackBusinessEffect)) == 4
                report = await LifecycleMetricsRepository(db).aggregate_counts(project_id=pid,
                    date_from=datetime.now(timezone.utc).date(), date_to=datetime.now(timezone.utc).date())
                assert report == {"registrations": 1, "first_deposits": 1, "redeposits": 2}
    asyncio.run(run())


@PG
def test_exact_identity_ambiguity_cross_project_and_dry_run():
    async def run():
        async with fixture() as (sessions, app, pid, lid, eid):
            async with sessions() as db:
                lead = await db.get(Lead, lid); chat = await db.get(Chat, lead.chat_id)
                bot = Bot(project_id=pid, name="Second bot", transport_type="bot_api")
                db.add(bot); await db.flush()
                duplicate_chat = Chat(project_id=pid, bot_id=bot.id, external_chat_id=chat.external_chat_id, external_user_id=chat.external_user_id)
                db.add(duplicate_chat); await db.flush()
                duplicate = Lead(project_id=pid, chat_id=duplicate_chat.id, status_id=lead.status_id)
                db.add(duplicate); await db.flush()
                endpoint = await db.get(PostbackEndpoint, eid)
                endpoint.parameter_mapping = {"identifier_type": "telegram_id", "identifier_param": "id"}
                service = PostbackContractService(db)
                ambiguous = await service.receive(token=TOKEN, method="GET", query={"id": chat.external_user_id}, body={})
                assert ambiguous.status == "ambiguous"
                endpoint.parameter_mapping = {"identifier_type": "tracking_code", "identifier_param": "id"}
                invalid = await service.receive(token=TOKEN, method="GET", query={"id": "shared-link"}, body={})
                assert invalid.status == "invalid"
                endpoint.parameter_mapping = {"identifier_type": "lead_id", "identifier_param": "id"}
                unmatched = await service.receive(token=TOKEN, method="GET", query={"id": str(uuid4())}, body={})
                assert unmatched.status == "unmatched"
                before = await db.scalar(select(func.count()).select_from(PostbackReceipt))
                preview = await service.receive(token=TOKEN, method="GET", query={"id": str(lid)}, body={}, dry_run=True)
                assert preview["status"] == "matched" and preview["lead_id"] == str(lid)
                assert await db.scalar(select(func.count()).select_from(PostbackReceipt)) == before
                assert await db.scalar(select(func.count()).select_from(LeadEvent)) == 0
                actor = SimpleNamespace(role_name="admin", project_id=uuid4())
                with pytest.raises(HTTPException) as exc:
                    await PostbackEndpointService(db).list_endpoints(project_id=pid, actor=actor)
                assert exc.value.status_code == 403
                actor = SimpleNamespace(role_name="manager", project_id=pid)
                with pytest.raises(HTTPException):
                    await PostbackEndpointService(db).list_receipts(endpoint_id=eid, project_id=pid, actor=actor, limit=10)
    asyncio.run(run())


@PG
def test_submission_status_order_atomic_followups_and_no_early_external_calls():
    async def run():
        async with fixture() as (sessions, app, pid, lid, eid):
            async with sessions() as db:
                partner = PartnerIntegration(project_id=pid, name="Buyer", postback_url="https://buyer.invalid/submit")
                db.add(partner)
                for code in ("submitted", "qualified", "lost"):
                    db.add(LeadStatus(name=code, code=code))
                await db.flush()
                submission = LeadSubmission(lead_id=lid, partner_integration_id=partner.id, status="completed", partner_status="accepted",
                    external_id="1234")
                db.add(submission); await db.flush()
                endpoint = await db.get(PostbackEndpoint, eid)
                endpoint.partner_integration_id = partner.id; endpoint.processing_kind = "submission_status"
                endpoint.parameter_mapping = {"identifier_type": "submission_id", "identifier_param": "submission_id",
                    "event_type_param": "status", "external_event_id_param": "event_id", "occurred_at_param": "at", "require_event_id": True,
                    "status_mapping": {"approved": "qualified", "rejected": "lost", "accepted": "submitted"},
                    "status_transitions": {"approved": ["rejected"], "accepted": ["approved", "rejected"]}}
                sid = submission.id
                await db.commit()
            base = datetime.now(timezone.utc) - timedelta(minutes=1)
            def payload(status, event_id, delta):
                return {"submission_id": str(sid), "status": status, "event_id": event_id, "at": (base + timedelta(seconds=delta)).isoformat()}
            with patch("app.services.google_sheets_service.GoogleSheetsService.export_lead_to_sheet", new_callable=AsyncMock) as export:
                async with sessions() as db:
                    service = PostbackEndpointService(db)
                    kwargs = dict(secret_token=TOKEN, request_method="POST", query_payload={}, body_payload=payload("approved", "ok-1", 10))
                    first = await service.receive(**kwargs)
                    assert first.status == "processed"
                    await db.rollback()
                async with sessions() as db:
                    assert await db.scalar(select(func.count()).select_from(PostbackFollowup)) == 0
                    service = PostbackEndpointService(db)
                    first = await service.receive(**kwargs)
                    duplicate = await service.receive(**kwargs)
                    assert duplicate.status == "duplicate"
                    preview = await PostbackContractService(db).receive(token=TOKEN, method="POST", query={},
                        body=kwargs["body_payload"], dry_run=True)
                    assert preview["status"] == "duplicate"
                    stale = await service.receive(secret_token=TOKEN, request_method="POST", query_payload={}, body_payload=payload("accepted", "old-1", 0))
                    assert stale.status == "stale"
                    await db.commit()
                    submission = await db.get(LeadSubmission, sid)
                    assert submission.is_valid is True and submission.partner_status == "approved"
                    assert await db.scalar(select(func.count()).select_from(PostbackFollowup)) == 2
                    assert await db.scalar(select(func.count()).select_from(LeadEvent)) == 0
                    assert (await db.get(Lead, lid)).status_id == await db.scalar(select(LeadStatus.id).where(LeadStatus.code == "qualified"))
                export.assert_not_awaited()
            from app.workers.postback_followup_worker import deliver_postback_followups_task
            sent = []
            async def sender(db, job): sent.append(job.kind)
            await deliver_postback_followups_task(sessions=sessions, sender=sender)
            await deliver_postback_followups_task(sessions=sessions, sender=sender)
            assert sorted(sent) == ["facebook_status", "sheets_status"]
    asyncio.run(run())


@PG
def test_dry_run_validates_status_and_binding_without_writes():
    async def run():
        async with fixture() as (sessions, app, pid, lid, eid):
            async with sessions() as db:
                partner = PartnerIntegration(project_id=pid, name="Buyer", postback_url="https://buyer.invalid")
                db.add(partner); await db.flush()
                submission = LeadSubmission(lead_id=lid, partner_integration_id=partner.id, status="completed",
                    partner_status="approved", callback_occurred_at=datetime.now(timezone.utc) - timedelta(minutes=1))
                db.add(submission); await db.flush()
                endpoint = await db.get(PostbackEndpoint, eid)
                endpoint.processing_kind = "submission_status"; endpoint.partner_integration_id = partner.id
                endpoint.parameter_mapping = {"identifier_type": "submission_id", "identifier_param": "id",
                    "event_type_param": "status", "status_mapping": {"approved": "missing-crm-code", "rejected": "missing-crm-code"}}
                await db.commit()
                service = PostbackContractService(db)
                preview = await service.receive(token=TOKEN, method="POST", query={},
                    body={"id": str(submission.id), "status": "rejected"}, dry_run=True)
                assert preview["status"] == "conflict" and "transition" in preview["reason"]
                preview = await service.receive(token=TOKEN, method="POST", query={},
                    body={"id": str(submission.id), "status": "approved"}, dry_run=True)
                assert preview["status"] == "invalid" and "CRM status" in preview["reason"]
                for model in (PostbackReceipt, PostbackBusinessEffect, PostbackEndpointRevision, PostbackFollowup):
                    assert await db.scalar(select(func.count()).select_from(model)) == 0
                assert submission.partner_status == "approved"
                endpoint.processing_kind = "lifecycle_event"
                endpoint.parameter_mapping = {"identifier_type": "lead_id", "identifier_param": "id", "bind_external_id_param": "player"}
                db.add(PostbackBinding(project_id=pid, namespace=str(partner.id), identifier_type="player_id",
                    external_id="player-one", lead_id=uuid4(), attribution_json={}))
                await db.commit()
                preview = await service.receive(token=TOKEN, method="POST", query={},
                    body={"id": str(lid), "player": "player-one"}, dry_run=True)
                assert preview["status"] == "conflict" and "bound" in preview["reason"]
                assert await db.scalar(select(func.count()).select_from(LeadEvent)) == 0
    asyncio.run(run())


@PG
def test_emergency_rotation_rejects_already_queued_old_revision():
    async def run():
        async with fixture() as (sessions, app, pid, lid, eid):
            async with sessions() as db:
                endpoint = await db.get(PostbackEndpoint, eid)
                await snapshot(db, endpoint)
                received = datetime.now(timezone.utc)
                await PostbackEndpointService(db).rotate_secret(endpoint_id=eid, project_id=pid, actor=ACTOR, revoke_old=True)
                await db.commit()
                with pytest.raises(HTTPException) as exc:
                    await PostbackContractService(db).receive(token=TOKEN, method="POST", query={},
                        body={"lead_id": str(lid)}, endpoint_id=eid, revision=1, received_at=received)
                assert exc.value.status_code == 404
                assert await db.scalar(select(func.count()).select_from(LeadEvent)) == 0
    asyncio.run(run())


@PG
def test_transport_monitor_alerts_only_for_actual_faults(monkeypatch):
    async def run():
        from app.models.postback import PostbackRelayHealth
        from app.workers.postback_followup_worker import monitor_postback_transport_task
        alerts = AsyncMock(return_value=True)
        monkeypatch.setattr("app.services.operational_alert_service.send_operational_alert", alerts)
        async with fixture() as (sessions, app, pid, lid, eid):
            enable(monkeypatch, pid)
            missing = await monitor_postback_transport_task(sessions=sessions)
            assert missing["problems"] == ["gateway_heartbeat_missing"]
            async with sessions() as db:
                health = PostbackRelayHealth(instance_id=uuid4(), seen_at=datetime.now(timezone.utc),
                    stats_json={"counts": {}, "oldest_pending_seconds": 0, "free_bytes": 2**40})
                db.add(health); await db.commit(); hid = health.instance_id
            alerts.reset_mock()
            assert (await monitor_postback_transport_task(sessions=sessions))["problems"] == []
            alerts.assert_not_awaited()
            async with sessions() as db:
                health = await db.get(PostbackRelayHealth, hid)
                health.stats_json = {"counts": {"dead": 1}, "oldest_pending_seconds": 10000, "free_bytes": 0}
                db.add(PostbackFollowup(project_id=pid, receipt_id=uuid4(), kind="sheets_status", payload_json={},
                    created_at=datetime.now(timezone.utc) - timedelta(hours=1)))
                await db.commit()
            faults = await monitor_postback_transport_task(sessions=sessions)
            assert set(faults["problems"]) == {"gateway_dead_deliveries", "gateway_queue_stalled", "gateway_low_disk", "followup_queue_stalled"}
            assert alerts.await_count == 4
    asyncio.run(run())


@PG
def test_gateway_contract_revision_time_rotation_and_archive(tmp_path, monkeypatch):
    async def run():
        async with fixture() as (sessions, app, pid, lid, eid):
            enable(monkeypatch, pid)
            cfg = Config(crm_origin="http://crm.test", secret=SECRET, database=str(tmp_path / "queue.db"), min_free_bytes=0)
            queue = Queue(cfg); queue.initialize()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
                relay = Relay(cfg, queue, client)
                await relay.sync()
                delivery_id = queue.enqueue(TOKEN, "GET", {"lead_id": str(lid), "event_id": "before-edit"}, {})
                async with sessions() as db:
                    await PostbackEndpointService(db).update_endpoint(endpoint_id=eid, project_id=pid, actor=ACTOR,
                        data=PostbackEndpointUpdate(event_type="deposit"))
                    await db.commit()
                await relay.send_one()
                assert queue.stats()["counts"] == {"done": 1}
                async with sessions() as db:
                    event = await db.scalar(select(LeadEvent))
                    assert event.event_type == "registration"
                    receipt = await db.scalar(select(PostbackReceipt))
                    assert receipt.endpoint_revision == 1 and receipt.received_at is not None
                    rotated = await PostbackEndpointService(db).rotate_secret(endpoint_id=eid, project_id=pid, actor=ACTOR)
                    new_token = rotated.url.rsplit("/", 1)[1]
                    await db.commit()
                await relay.sync()
                assert len((await client.get("http://crm.test/internal/postback-relay/manifest", headers=headers(SECRET, "GET", "/internal/postback-relay/manifest"))).json()["token_hashes"]) == 2
                async with sessions() as db:
                    result = await PostbackEndpointService(db).receive(secret_token=TOKEN, request_method="GET",
                        query_payload={"lead_id": str(lid), "event_id": "grace"}, body_payload={})
                    assert result.status == "processed"
                    await db.commit()
                async with sessions() as db:
                    await PostbackEndpointService(db).delete_endpoint(endpoint_id=eid, project_id=pid, actor=ACTOR)
                    await db.commit()
                    assert await db.scalar(select(func.count()).select_from(PostbackReceipt)) == 2
                    with pytest.raises(HTTPException):
                        await PostbackEndpointService(db).receive(secret_token=new_token, request_method="GET", query_payload={"lead_id": str(lid)}, body_payload={})
    asyncio.run(run())


@PG
def test_personal_identity_binding_preserves_attribution_and_conflicting_bind_is_rejected():
    async def run():
        async with fixture() as (sessions, app, pid, lid, eid):
            async with sessions() as db:
                service = PostbackContractService(db)
                endpoint = await db.get(PostbackEndpoint, eid)
                binding = await service.bind(endpoint, PostbackBindingCreate(identifier_type="player_id", external_id="1234", lead_id=lid))
                assert binding.attribution_json["tracking_link_id"] is None and binding.attribution_json["buyer_id"] is None
                endpoint.parameter_mapping = {"identifier_type": "player_id", "identifier_param": "id", "external_event_id_param": "event_id"}
                wrong = await service.receive(token=TOKEN, method="GET", query={"id": "123", "event_id": "wrong"}, body={})
                assert wrong.status == "unmatched"
                right = await service.receive(token=TOKEN, method="GET", query={"id": "1234", "event_id": "right"}, body={})
                assert right.status == "processed" and right.lead_id == lid
                await db.commit()
                assert (await db.get(LeadEvent, right.event_id)).tracking_link_id is None
                await remember_personal_link(db, lid)
                await remember_personal_link(db, lid)
                await db.commit()
                assert await db.scalar(select(func.count()).select_from(PostbackBinding)) == 2
    asyncio.run(run())


@PG
def test_migration_0094_is_additive_and_preserves_legacy_flags():
    async def run():
        import importlib.util
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from app.models import Base
        engine = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"])
        schema = "pb_upgrade_" + uuid4().hex
        old = MetaData()
        for table in Base.metadata.tables.values(): table.to_metadata(old)
        for name in ("postback_endpoint_revisions", "postback_business_effects", "postback_bindings", "postback_relay_health", "postback_followups"):
            old.remove(old.tables[name])
        for table, columns in {"postback_endpoints": ["processing_kind", "revision", "is_archived"],
            "postback_receipts": ["submission_id", "endpoint_revision", "received_at", "occurred_at", "processed_at", "attempt_log"],
            "partner_integrations": ["legacy_callback_disabled"], "lead_submissions": ["external_id", "callback_occurred_at"]}.items():
            for column in columns: old.tables[table]._columns.remove(old.tables[table].c[column])
        for column in ("attribution_locked", "attributed_bot_id", "attributed_buyer_id"):
            old.tables["lead_events"]._columns.remove(old.tables["lead_events"].c[column])
        old.tables["lead_submissions"].indexes = {index for index in old.tables["lead_submissions"].indexes if index.name != "ix_lead_submissions_external_id"}
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
                await conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                await conn.run_sync(old.create_all)
                pid = uuid4(); partner_id = uuid4(); endpoint_id = uuid4()
                await conn.execute(old.tables["projects"].insert().values(id=pid, name="Preserved", slug="preserved"))
                await conn.execute(old.tables["partner_integrations"].insert().values(id=partner_id, project_id=pid, name="Legacy", postback_url="https://buyer.invalid"))
                await conn.execute(old.tables["postback_endpoints"].insert().values(id=endpoint_id, project_id=pid, name="Existing", secret_token=TOKEN, event_type="registration"))
                spec = importlib.util.spec_from_file_location("pb94", "alembic/versions/20261103_0094_postback_contracts.py")
                module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
                def upgrade(sync):
                    with Operations.context(MigrationContext.configure(sync)): module.upgrade()
                await conn.run_sync(upgrade)
                assert (await conn.execute(text("SELECT legacy_callback_disabled FROM partner_integrations"))).scalar() is False
                assert (await conn.execute(text("SELECT processing_kind, revision, is_archived FROM postback_endpoints"))).one() == ("lifecycle_event", 1, False)
                assert (await conn.execute(text("SELECT name FROM projects"))).scalar() == "Preserved"
        finally:
            async with engine.begin() as conn: await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await engine.dispose()
    asyncio.run(run())


@PG
def test_secure_api_reprocess_permissions_and_explicit_legacy_cutover():
    async def run():
        from app.api.v1.routers.postbacks import router as endpoints_router, public_router
        from app.api.v1.routers.partners import router as partners_router
        from app.api.v1.dependencies import get_current_user, get_current_project_id
        async with fixture() as (sessions, app, pid, lid, eid):
            app.include_router(endpoints_router, prefix="/api/v1"); app.include_router(public_router)
            app.include_router(partners_router, prefix="/api/v1/partners")
            app.dependency_overrides[get_current_user] = lambda: ACTOR
            app.dependency_overrides[get_current_project_id] = lambda: pid
            async with sessions() as db:
                endpoint = await db.get(PostbackEndpoint, eid)
                endpoint.parameter_mapping = {"identifier_type": "player_id", "identifier_param": "player_id", "external_event_id_param": "event_id"}
                partner = PartnerIntegration(project_id=pid, name="Legacy buyer", postback_url="https://buyer.invalid", legacy_callback_disabled=False)
                db.add(partner); await db.flush()
                partner_id = partner.id
                await db.commit()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://crm.test") as client:
                first = await client.get(f"/pb/{TOKEN}", params={"player_id": "player-7", "event_id": "evt-7"})
                assert first.json()["status"] == "unmatched"
                rid = first.json()["receipt_id"]
                binding = await client.post(f"/api/v1/postback-endpoints/{eid}/bindings", json={"identifier_type": "player_id", "external_id": "player-7", "lead_id": str(lid)})
                assert binding.status_code == 200
                dry = await client.post(f"/api/v1/postback-endpoints/{eid}/dry-run", json={"body_payload": {"player_id": "player-7", "event_id": "evt-7"}})
                assert dry.json()["status"] == "matched"
                async with sessions() as db: assert await db.scalar(select(func.count()).select_from(LeadEvent)) == 0
                replay = await client.post(f"/api/v1/postback-endpoints/{eid}/receipts/{rid}/reprocess")
                assert replay.json()["status"] == "processed"
                assert (await client.post(f"/api/v1/postback-endpoints/{eid}/receipts/{rid}/reprocess")).status_code == 409
                async with sessions() as db:
                    receipt = await db.get(PostbackReceipt, UUID(rid))
                    assert len(receipt.attempt_log) == 1 and receipt.attempt_log[0]["status"] == "unmatched"
                    assert await db.scalar(select(func.count()).select_from(LeadEvent)) == 1
                created = await client.post("/api/v1/postback-endpoints", json={"name": "Statuses", "processing_kind": "submission_status", "partner_integration_id": str(partner_id)})
                assert created.status_code == 201
                async with sessions() as db: assert not (await db.get(PartnerIntegration, partner_id)).legacy_callback_disabled
                assert (await client.post(f"/api/v1/postback-endpoints/{created.json()['id']}/close-legacy-status-route")).status_code == 200
                assert (await client.post(f"/api/v1/partners/postbacks/{partner_id}", json={"status": "accepted", "lead_id": str(lid)})).status_code == 410
                app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role_name="manager", project_id=pid)
                assert (await client.get("/api/v1/postback-endpoints")).status_code == 403
                assert (await client.get("/api/v1/postback-endpoints/transport")).status_code == 403
    asyncio.run(run())


@PG
def test_shared_namespace_auto_player_binding_and_original_day():
    async def run():
        async with fixture() as (sessions, app, pid, lid, eid):
            async with sessions() as db:
                endpoint = await db.get(PostbackEndpoint, eid)
                endpoint.parameter_mapping = {"external_event_id_param": "event_id", "event_namespace": "casino-one",
                    "bind_external_id_param": "player_id", "occurred_at_param": "at"}
                deposit = PostbackEndpoint(project_id=pid, name="FD", secret_token="f" * 43, event_type="deposit", parameter_mapping={
                    "identifier_type": "player_id", "identifier_param": "player_id", "external_event_id_param": "event_id", "event_namespace": "casino-one"})
                db.add(deposit); await db.flush()
                received = datetime.now(timezone.utc)
                occurred = received - timedelta(days=2)
                service = PostbackContractService(db)
                first = await service.receive(token=TOKEN, method="POST", query={}, body={"lead_id": str(lid),
                    "player_id": "p-1", "event_id": "reg", "at": occurred.isoformat()}, received_at=received)
                second = await service.receive(token=deposit.secret_token, method="GET", query={"player_id": "p-1", "event_id": "fd"}, body={})
                assert first.status == second.status == "processed"
                await db.commit()
                event = await db.get(LeadEvent, first.event_id)
                assert event.occurred_at == occurred
                report = await LifecycleMetricsRepository(db).aggregate_counts(project_id=pid,
                    date_from=occurred.date(), date_to=occurred.date())
                assert report["registrations"] == 1 and report["first_deposits"] == 0
                assert await db.scalar(select(func.count()).select_from(PostbackBinding)) == 1
    asyncio.run(run())


@PG
def test_followup_failure_is_not_blindly_resent(monkeypatch):
    async def run():
        from app.workers.postback_followup_worker import deliver_postback_followups_task
        monkeypatch.setattr("app.services.operational_alert_service.send_operational_alert", AsyncMock(return_value=True))
        async with fixture() as (sessions, app, pid, lid, eid):
            async with sessions() as db:
                row = PostbackFollowup(project_id=pid, receipt_id=uuid4(), kind="sheets_status", payload_json={})
                db.add(row); await db.commit(); job_id = row.id
            sender = AsyncMock(side_effect=TimeoutError("Unknown remote result"))
            await deliver_postback_followups_task(sessions=sessions, sender=sender)
            await deliver_postback_followups_task(sessions=sessions, sender=sender)
            sender.assert_awaited_once()
            async with sessions() as db:
                job = await db.get(PostbackFollowup, job_id)
                assert job.status == "review" and job.error == "TimeoutError"
    asyncio.run(run())


@PG
def test_personal_button_source_and_buyer_survive_chat_source_change(monkeypatch):
    async def run():
        from app.models.tracking import TrackingLink
        from app.models.user import User
        from app.models.role import Role
        from app.services.funnel_runtime_service import FunnelRuntimeService
        from app.workers.postback_worker import send_fb_capi_event_task
        from app.services.facebook_capi_service import FacebookCAPIService
        async with fixture() as (sessions, app, pid, lid, eid):
            async with sessions() as db:
                lead = await db.get(Lead, lid); chat = await db.get(Chat, lead.chat_id)
                role = Role(name="buyer"); db.add(role); await db.flush()
                buyers = [User(project_id=pid, role_id=role.id, email=f"buyer{i}@qa.invalid", name=f"Buyer {i}", password_hash="qa") for i in range(2)]
                db.add_all(buyers); await db.flush()
                links = [TrackingLink(project_id=pid, bot_id=chat.bot_id, name=f"Link {i}", title=f"Link {i}",
                    code=f"link-{i}", ref_code=f"link-{i}", buyer_id=buyers[i].id, fb_pixel_id="test-pixel", fb_capi_token="test-token") for i in range(2)]
                db.add_all(links); await db.flush()
                chat.tracking_link_id = links[0].id
                lead.custom_fields = {"fb_data": {"fbc": "fb.1.original", "event_source_url": "https://original.invalid"}}
                await db.flush()
                runtime = FunnelRuntimeService(db)
                step = SimpleNamespace(id=uuid4(), block_type="generic_message", config_json={})
                original_markup = {"inline_keyboard": [[{"text": "Register", "url": "https://casino.invalid/?sub_id={{lead_id}}"}]]}
                delivery = await runtime._message_item_delivery(chat_id=chat.id, step=step,
                    item={"type": "text", "text": "Register"}, reply_markup=original_markup)
                assert delivery["reply_markup"]["inline_keyboard"][0][0]["url"].endswith(str(lid))
                assert "{{lead_id}}" in original_markup["inline_keyboard"][0][0]["url"]
                chat.tracking_link_id = links[1].id
                lead.custom_fields = {"fb_data": {"fbc": "fb.1.new-source"}}
                await db.flush()
                result = await PostbackEndpointService(db).receive(secret_token=TOKEN, request_method="GET",
                    query_payload={"lead_id": str(lid).upper(), "event_id": "late-reg"}, body_payload={})
                await db.commit()
                event = await db.get(LeadEvent, result.event_id)
                assert event.tracking_link_id == links[0].id and event.attributed_buyer_id == buyers[0].id
                date = datetime.now(timezone.utc).date()
                metrics = LifecycleMetricsRepository(db)
                assert (await metrics.aggregate_counts(project_id=pid, date_from=date, date_to=date, link_id=links[0].id))["registrations"] == 1
                assert (await metrics.aggregate_counts(project_id=pid, date_from=date, date_to=date, link_id=links[1].id))["registrations"] == 0
                assert (await metrics.aggregate_counts(project_id=pid, date_from=date, date_to=date, buyer_id=buyers[0].id))["registrations"] == 1
                assert (await metrics.aggregate_counts(project_id=pid, date_from=date, date_to=date, buyer_id=buyers[1].id))["registrations"] == 0
                source_id = links[0].id
            monkeypatch.setattr("app.workers.postback_worker.get_db_session", sessions)
            remote = AsyncMock(return_value={"events_received": 1})
            monkeypatch.setattr(FacebookCAPIService, "send_event", remote)
            denied = await send_fb_capi_event_task({}, str(lid), str(source_id), "CompleteRegistration")
            assert denied["status"] == "failed"
            allowed = await send_fb_capi_event_task({}, str(lid), str(source_id), "CompleteRegistration",
                postback_attribution={"event_id": str(event.id), "fb_data": {"fbc": "fb.1.original"}})
            assert allowed["status"] == "completed"
            remote.assert_awaited_once()
            delivery_lead = remote.call_args.kwargs["lead"]
            assert FacebookCAPIService.build_user_data(delivery_lead)["fbc"] == "fb.1.original"
            async with sessions() as db:
                assert (await db.get(Lead, lid)).custom_fields["fb_data"]["fbc"] == "fb.1.new-source"
    asyncio.run(run())
