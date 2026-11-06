import asyncio
from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError, TimeoutError as PoolTimeout

from app.core.config import Settings, settings
from app.core.db_retry import retryable_database_error
from app.core.delivery_attempt import note_external_delivery
from app.core.lead_field_validation import LeadFieldValidationError, validate_lead_fields
from app.models import Chat, Message, Project, Role, User, AuditLog
from app.models.advertising import AdvertisingDelivery, AdvertisingEnrollment, AdvertisingSlot
from app.models.lead import LeadTag
from app.models.telegram_delivery import RuntimeDispatch
from app.services.backup_diagnostics import transport_status
from app.services.funnel_runtime_service import FunnelRuntimeService
from app.services.runtime_dispatch_service import RuntimeDispatchNeedsReview, protect_dispatch_replay, save_runtime_dispatch
from app.services.runtime_review_service import RuntimeReviewService
from app.services.telegram_sender import TelegramDeliveryError, TelegramSenderService
from app.workers.advertising_worker import process_enrollment
from test_advertising import fixture, enroll, due
from test_telegram_delivery_resilience import disposable_db

PG = pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")


@pytest.mark.parametrize("state,retry", [("22001", False), ("23505", False), ("23503", False),
    ("40001", True), ("40P01", True), ("08006", True), (None, False)])
def test_only_transient_database_failures_are_retryable(state, retry):
    orig = Exception("private customer parameters must not reach diagnostics")
    orig.sqlstate = state
    assert retryable_database_error(DBAPIError("statement", {}, orig)) is retry


@pytest.mark.parametrize("field,limit", [("country", 100), ("phone", 50), ("name", 255)])
def test_mapped_fields_are_bounded_without_truncating_customer_history(field, limit):
    from app.models.lead import Lead
    limit = Lead.__table__.c[field].type.length
    validate_lead_fields({field: "x" * limit})
    with pytest.raises(LeadFieldValidationError): validate_lead_fields({field: "x" * (limit + 1)})
    step = SimpleNamespace(block_type="generic_input", config_json={"save_to": field, "answer_type": "text"})
    service = object.__new__(FunnelRuntimeService)
    assert not service._validate_input_answer(step, "x" * (limit + 1))["valid"]
    if field == "country":
        assert service._validate_input_answer(step, "Узбекистан")["valid"]
        assert not service._validate_input_answer(step, "https://example.org bonus")["valid"]


@pytest.mark.parametrize("value", [9000000000000001, 2**31, -(2**31)-1])
def test_age_overflow_uses_question_fallback_before_sql(value):
    with pytest.raises(LeadFieldValidationError) as error:
        validate_lead_fields({"age": value})
    assert error.value.code == "out_of_range"
    assert str(value) not in str(error.value)
    service = object.__new__(FunnelRuntimeService)
    for answer_type in ("text", "number"):
        step = SimpleNamespace(block_type="generic_input", config_json={"save_to": "age", "answer_type": answer_type})
        assert service._validate_input_answer(step, str(value)) == {"valid": False, "storage_field_error": True}
        assert service._validate_input_answer(step, "25")["valid"]


@pytest.mark.parametrize("value", [0, 25, 120, -(2**31), 2**31-1])
def test_existing_integer_storage_boundaries_remain_compatible(value):
    validate_lead_fields({"age": value})


@pytest.mark.parametrize("error,known", [(httpx.ConnectError, True), (httpx.ConnectTimeout, True),
    (httpx.ReadTimeout, False), (httpx.WriteTimeout, False)])
def test_network_delivery_certainty(error, known):
    assert TelegramSenderService._network_delivery_error("sendMessage", error("network")).definitely_not_sent is known


def test_backup_cloud_limit_cannot_be_bypassed_by_just_changing_a_number():
    cfg = Settings(_env_file=None, DATABASE_URL="postgresql+asyncpg://localhost/test", SECRET_KEY="test", BACKUP_TELEGRAM_MAX_UPLOAD_MB=2000)
    assert transport_status(cfg)["effective_limit_mb"] == 49
    cfg.BACKUP_TELEGRAM_API_BASE_URL = "http://backup-telegram-api:8081"
    status = transport_status(cfg)
    assert status["effective_limit_mb"] == 2000 and status["local_api_verified"] is False
    cfg.BACKUP_TELEGRAM_API_BASE_URL = "http://user:private@host/path?secret=private"
    status = transport_status(cfg)
    assert not status["address_valid"] and "private" not in str(status)


async def setup_dispatch(sessions, bot_id, project_id):
    async with sessions() as db:
        chat = Chat(project_id=project_id, bot_id=bot_id, external_chat_id="QA", external_user_id="QA")
        db.add(chat); await db.flush()
        message = Message(chat_id=chat.id, sender_type="user", message_type="text", body="Private answer")
        db.add(message); await db.flush()
        await save_runtime_dispatch(db, key=f"input:{message.id}", kind="input", payload={"chat_id": str(chat.id), "message_id": str(message.id)})
        await db.commit()
        return chat.id, message.id


@PG
@pytest.mark.parametrize("partial", [False, True])
def test_permanent_error_is_quarantined_once_and_diagnostics_never_contain_input(monkeypatch, partial):
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            chat_id, message_id = await setup_dispatch(sessions, bot_id, project_id)
            orig = Exception("Private answer"); orig.sqlstate = "22001"
            async with sessions() as db:
                with pytest.raises(RuntimeDispatchNeedsReview):
                    async with protect_dispatch_replay(db, "input", message_id):
                        if partial: note_external_delivery()
                        raise DBAPIError("UPDATE leads", {"country": "Private answer"}, orig)
            async with sessions() as db:
                row = await db.scalar(select(RuntimeDispatch))
                assert row.status == "review" and row.failure_count == 1
                assert row.diagnostics_json["safe_to_replay"] is (not partial)
                assert row.diagnostics_json["sqlstate"] == "22001"
                assert "Private answer" not in str(row.diagnostics_json) + row.last_error
                with pytest.raises(RuntimeDispatchNeedsReview):
                    async with protect_dispatch_replay(db, "input", message_id): pytest.fail("Replayed")
                assert (await db.get(Message, message_id)).body == "Private answer"
    asyncio.run(run())


@PG
def test_transient_dispatch_failures_back_off_and_stop_at_limit(monkeypatch):
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            _, message_id = await setup_dispatch(sessions, bot_id, project_id)
            monkeypatch.setattr(settings, "RUNTIME_DISPATCH_MAX_FAILURES", 3)
            delays = []
            for attempt in range(1, 4):
                async with sessions() as db:
                    with pytest.raises(PoolTimeout if attempt < 3 else RuntimeDispatchNeedsReview):
                        async with protect_dispatch_replay(db, "input", message_id): raise PoolTimeout("pool")
                async with sessions() as db:
                    row = await db.scalar(select(RuntimeDispatch))
                    assert row.failure_count == attempt
                    assert row.status == ("pending" if attempt < 3 else "review")
                    delays.append((row.available_at - datetime.now(timezone.utc)).total_seconds())
            assert 3 < delays[0] < delays[1] < delays[2]
    asyncio.run(run())


@PG
def test_recovery_requires_project_admin_unchanged_state_and_effect_free_evidence(monkeypatch):
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            chat_id, message_id = await setup_dispatch(sessions, bot_id, project_id)
            async with sessions() as db:
                with pytest.raises(RuntimeDispatchNeedsReview):
                    async with protect_dispatch_replay(db, "input", message_id): raise LeadFieldValidationError("country", "too_long")
            async with sessions() as db:
                role = Role(name="super_admin"); db.add(role); await db.flush()
                user = User(role_id=role.id, email="qa-recovery@example.org", name="QA", password_hash="unused")
                db.add(user); await db.commit()
                actor = SimpleNamespace(role_name="super_admin", id=user.id)
                service = RuntimeReviewService(db)
                rows = await service.list(project_id, actor)
                assert len(rows) == 1 and rows[0]["can_retry"]
                with pytest.raises(HTTPException) as denied:
                    await service.list(project_id, SimpleNamespace(role_name="manager", project_id=project_id))
                assert denied.value.status_code == 403
                with pytest.raises(HTTPException): await service.retry(uuid4(), actor, rows[0]["id"], rows[0]["fingerprint"], "Review")
                await service.retry(project_id, actor, rows[0]["id"], rows[0]["fingerprint"], "Field validation fixed")
                await db.commit()
                with pytest.raises(HTTPException): await service.retry(project_id, actor, rows[0]["id"], rows[0]["fingerprint"], "Again")
                assert await db.scalar(select(func.count()).select_from(AuditLog)) == 1
                row = await db.scalar(select(RuntimeDispatch)); row.status = "review"; row.diagnostics_json = {}
                await db.commit()
                assert not (await service.list(project_id, actor))[0]["can_retry"]  # Legacy uncertainty never auto-authorises a replay.
    asyncio.run(run())


@PG
@pytest.mark.parametrize("change", ["new_input", "edit", "published_version"])
def test_new_customer_input_invalidates_recovery_snapshot(monkeypatch, change):
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            chat_id, message_id = await setup_dispatch(sessions, bot_id, project_id)
            async with sessions() as db:
                with pytest.raises(RuntimeDispatchNeedsReview):
                    async with protect_dispatch_replay(db, "input", message_id): raise LeadFieldValidationError("country", "too_long")
            async with sessions() as db:
                if change == "new_input":
                    db.add(Message(chat_id=chat_id, sender_type="user", message_type="text", body="New reply"))
                elif change == "edit":
                    (await db.get(Message, message_id)).edited_at = datetime.now(timezone.utc)
                else:
                    from app.models import Bot
                    from app.models.funnel import Funnel, FunnelVersion
                    funnel = Funnel(project_id=project_id, bot_id=bot_id, name="New funnel"); db.add(funnel); await db.flush()
                    version = FunnelVersion(funnel_id=funnel.id, version_number=1, status="published"); db.add(version); await db.flush()
                    (await db.get(Bot, bot_id)).active_funnel_version_id = version.id
                await db.commit()
                actor = SimpleNamespace(role_name="super_admin")
                assert not (await RuntimeReviewService(db).list(project_id, actor))[0]["can_retry"]
    asyncio.run(run())


@PG
def test_advertising_releases_chat_lock_during_network_and_retries_only_unsent_message():
    async def run():
        async with fixture() as (sessions, pid, bid, chats, slots, leads, hot):
            eid = await enroll(sessions, chats[0]); await process_enrollment(eid, sessions)
            # A legacy multi-message snapshot exercises per-message progress, even
            # though today's slot editor only permits one post.
            async with sessions() as db:
                slot = await db.get(AdvertisingSlot, slots[0]); slot.content_json = {"messages": [{"text": "A"}, {"text": "B"}]}
                await db.commit()
            calls = []
            async def send(db, chat, delivery):
                assert not db.in_transaction() and db.bind.pool.checkedout() == 0
                async with sessions() as other:
                    async with asyncio.timeout(1):
                        await other.execute(update(Chat).where(Chat.id == chat.id).values(is_favorite=True)); await other.commit()
                index = delivery.progress_json["next_index"]; calls.append(index)
                if calls == [0, 1]:
                    raise TelegramDeliveryError(method="sendMessage", description="ConnectError", transient=True, definitely_not_sent=True)
                db.add(Message(chat_id=chat.id, sender_type="bot", message_type="text", body=str(index)))
            await process_enrollment(eid, sessions, send)
            await process_enrollment(eid, sessions, send)
            await due(sessions, eid)
            await process_enrollment(eid, sessions, send)
            assert calls == [0, 1, 1]
            async with sessions() as db:
                d = await db.scalar(select(AdvertisingDelivery).where(AdvertisingDelivery.enrollment_id == eid, AdvertisingDelivery.position == 0))
                assert d.status == "sent" and d.progress_json["next_index"] == 2
                assert await db.scalar(select(func.count()).select_from(Message).where(Message.chat_id == chats[0])) == 2
    asyncio.run(run())


@PG
def test_tag_added_during_network_protects_remaining_messages():
    async def run():
        async with fixture() as (sessions, pid, bid, chats, slots, leads, hot):
            eid = await enroll(sessions, chats[0]); await process_enrollment(eid, sessions)
            async with sessions() as db:
                slot = await db.get(AdvertisingSlot, slots[0]); slot.content_json = {"messages": [{"text": "A"}, {"text": "B"}]}; await db.commit()
            calls = []
            async def send(db, chat, delivery):
                calls.append(delivery.progress_json["next_index"])
                async with sessions() as other:
                    other.add(LeadTag(lead_id=leads[0], tag_id=hot)); await other.commit()
            await process_enrollment(eid, sessions, send)
            await process_enrollment(eid, sessions, send)
            assert calls == [0]
            async with sessions() as db:
                assert (await db.get(AdvertisingEnrollment, eid)).status == "protected"
    asyncio.run(run())


@PG
def test_migration_0097_is_atomic_and_preserves_old_pending_records(monkeypatch):
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            _, message_id = await setup_dispatch(sessions, bot_id, project_id)
            async with sessions() as db:
                await db.execute(text("ALTER TABLE runtime_dispatches DROP COLUMN failure_count, DROP COLUMN diagnostics_json"))
                await db.execute(text("ALTER TABLE advertising_deliveries DROP COLUMN progress_json")); await db.commit()
                spec = importlib.util.spec_from_file_location("migration0097", "alembic/versions/20261106_0097_delivery_resilience.py")
                migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
                original = migration.op.add_column
                def fail_last(table, column):
                    if table == "advertising_deliveries": migration.op.execute("SELECT 1/0")
                    return original(table, column)
                def upgrade(sync):
                    with Operations.context(MigrationContext.configure(sync)): migration.upgrade()
                with monkeypatch.context() as patch:
                    patch.setattr(migration.op, "add_column", fail_last)
                    with pytest.raises(DBAPIError): await (await db.connection()).run_sync(upgrade)
                    await db.rollback()
                assert await db.scalar(text("SELECT count(*) FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='runtime_dispatches' AND column_name='failure_count'")) == 0
                await (await db.connection()).run_sync(upgrade); await db.commit()
                row = await db.scalar(select(RuntimeDispatch))
                assert row.status == "pending" and row.failure_count == 0 and row.diagnostics_json == {}
                assert (await db.get(Message, message_id)).body == "Private answer"
    asyncio.run(run())


@PG
def test_backup_worker_records_local_archive_when_delivery_fails(monkeypatch, tmp_path):
    import json
    from unittest.mock import AsyncMock
    from app.utils import backup_manager
    from app.services import backup_diagnostics
    from app.services.backup_service import BackupResult, BackupError
    from app.services.system_setting_service import SystemSettingService
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            monkeypatch.setattr(backup_manager, "get_db_session", sessions)
            monkeypatch.setattr(backup_diagnostics, "get_db_session", sessions)
            monkeypatch.setattr(SystemSettingService, "get_effective_global_config", AsyncMock(return_value=SimpleNamespace(
                is_tg_backup_enabled=True, tg_backup_bot_token="test-token", tg_backup_channel_id="test-destination")))
            result = BackupResult(path=tmp_path/"fixture.sql.gz", size_bytes=698045667, sha256="fixture", created_at=datetime.now(timezone.utc), encrypted=False)
            monkeypatch.setattr(backup_manager, "create_database_backup", lambda **kw: result)
            def failed(*args, **kwargs): raise BackupError("Too large")
            monkeypatch.setattr(backup_manager, "send_backup_to_telegram", failed)
            with pytest.raises(BackupError): await backup_manager.run_configured_telegram_backup()
            async with sessions() as db:
                status = json.loads(await SystemSettingService(db).get_value("backup_runtime_status"))
                assert status["stage"] == "failed" and status["local_created"] and not status["telegram_sent"]
                assert status["size_bytes"] == 698045667 and "test-token" not in str(status)
    asyncio.run(run())


@PG
def test_review_http_api_rejects_managers_and_other_projects(monkeypatch):
    from fastapi import FastAPI
    from app.api.v1.dependencies import get_current_project_id, get_current_user, get_db
    from app.api.v1.routers.settings import router
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            await setup_dispatch(sessions, bot_id, project_id)
            app = FastAPI(); app.include_router(router)
            actor = SimpleNamespace(role_name="manager", project_id=project_id)
            app.dependency_overrides[get_current_user] = lambda: actor
            app.dependency_overrides[get_current_project_id] = lambda: project_id
            async def db_dependency():
                async with sessions() as db:
                    yield db
                    await db.commit()
            app.dependency_overrides[get_db] = db_dependency
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://qa") as client:
                assert (await client.get("/settings/runtime-dispatches")).status_code == 403
                assert (await client.post(f"/settings/runtime-dispatches/{uuid4()}/retry", json={"fingerprint": "a"*64, "reason": "QA"})).status_code == 403
                assert (await client.get("/settings/global/backup/transport")).status_code == 403
                actor.role_name = "admin"
                assert (await client.get("/settings/runtime-dispatches?state=pending")).status_code == 200
                app.dependency_overrides[get_current_project_id] = lambda: uuid4()
                assert (await client.get("/settings/runtime-dispatches")).status_code == 403
    asyncio.run(run())


@PG
@pytest.mark.parametrize("field,answer_type,bad,good", [
    ("country", "text", "https://example.org " + "x"*101, "Узбекистан"),
    ("age", "number", "9000000000000001", "25"),
])
def test_invalid_field_answer_gets_one_fallback_and_next_answer_continues_same_funnel(monkeypatch, field, answer_type, bad, good):
    from app.models import Bot, Lead, LeadStatus
    from app.models.funnel import ChatFunnelState, Funnel, FunnelVersion, FunnelStep, FunnelEdge
    from app.services.telegram_inbox_service import accept_telegram_update
    from app.workers import telegram_delivery_worker as intake, postback_worker as jobs
    from test_telegram_delivery_resilience import payload
    async def run():
        async with disposable_db(monkeypatch) as (sessions, engine, bot_id, project_id):
            monkeypatch.setattr(jobs, "get_db_session", sessions)
            monkeypatch.setattr(settings, "TELEGRAM_INPUT_QUIET_SECONDS", 1)
            sent = []
            async def send(sender, **kw):
                if sender.db.in_transaction(): await sender.db.commit()
                note_external_delivery(); sent.append(kw["text"])
                return {"message_id": len(sent) + 100}
            monkeypatch.setattr(TelegramSenderService, "send_message", send)
            async with sessions() as db:
                db.add(LeadStatus(code="new", name="New"))
                f = Funnel(project_id=project_id, bot_id=bot_id, name="Country"); db.add(f); await db.flush()
                v = FunnelVersion(funnel_id=f.id, version_number=1, status="published"); db.add(v); await db.flush()
                bot = await db.get(Bot, bot_id); bot.active_funnel_id, bot.active_funnel_version_id = f.id, v.id
                start = FunnelStep(funnel_version_id=v.id, key="start", title="Start", step_type="trigger", block_type="generic_start", config_json={})
                question = FunnelStep(funnel_version_id=v.id, key="country", title="Country", step_type="input", block_type="generic_input",
                    config_json={"prompt": "Question?", "save_to": field, "answer_type": answer_type, "retry_message": "Уточните ответ", "timeout_seconds": 0})
                final = FunnelStep(funnel_version_id=v.id, key="final", title="Done", step_type="input", block_type="generic_input", config_json={"prompt": "Done", "timeout_seconds": 0})
                db.add_all([start, question, final]); await db.flush()
                db.add_all([FunnelEdge(funnel_version_id=v.id, from_step_id=start.id, to_step_id=question.id),
                    FunnelEdge(funnel_version_id=v.id, from_step_id=question.id, to_step_id=final.id, condition_json={"source_key": "input:next"})])
                await accept_telegram_update(db, bot_id=bot_id, payload=payload()); await db.commit()
                question_id, final_id = question.id, final.id
            assert await intake.process_next_inbox()
            async with sessions() as db: request = (await db.scalar(select(RuntimeDispatch))).payload_json
            await jobs.process_funnel_start_task({}, request["chat_id"], request["message_id"], True)
            for number, answer in [(2, bad), (3, good)]:
                update_payload = payload(number); update_payload["message"]["text"] = answer
                async with sessions() as db:
                    await accept_telegram_update(db, bot_id=bot_id, payload=update_payload); await db.commit()
                assert await intake.process_next_inbox()
                async with sessions() as db:
                    request = (await db.scalar(select(RuntimeDispatch).where(RuntimeDispatch.kind == "input").order_by(RuntimeDispatch.created_at.desc()).limit(1))).payload_json
                await asyncio.sleep(1.1)
                assert (await jobs.process_user_input_task({}, request["chat_id"], request["message_id"]))["status"] == "processed"
                async with sessions() as db:
                    state = await db.scalar(select(ChatFunnelState)); lead = await db.scalar(select(Lead))
                    assert state.current_step_id == (question_id if number == 2 else final_id)
                    assert getattr(lead, field) == (None if number == 2 else int(good) if field == "age" else good)
                    assert await db.scalar(select(func.count()).select_from(RuntimeDispatch).where(RuntimeDispatch.status == "review")) == 0
                    assert await db.scalar(select(func.count()).select_from(Message).where(Message.body == answer)) == 1
            assert sent == ["Question?", "Уточните ответ", "Done"]
    asyncio.run(run())


def test_slow_request_logging_does_not_include_query_or_private_path(caplog):
    from app.main import log_unhandled_request_errors
    from starlette.requests import Request
    from starlette.responses import Response
    async def run():
        request = Request({"type": "http", "method": "GET", "path": "/pb/private-token", "query_string": b"name=PrivateName",
            "headers": [], "route": SimpleNamespace(path="/pb/{token}")})
        async def response(req):
            await asyncio.sleep(1.01)
            return Response("ok")
        with caplog.at_level("WARNING"):
            result = await log_unhandled_request_errors(request, response)
        assert len(result.headers["X-Request-ID"]) == 32
        assert "elapsed_ms=" in caplog.text and "/pb/{token}" in caplog.text
        assert "private-token" not in caplog.text and "PrivateName" not in caplog.text
    asyncio.run(run())


@PG
@pytest.mark.parametrize("kind,attempts,outcome", [("connect", 3, "failed"), ("rate_limit", 3, "failed"), ("read_timeout", 1, "uncertain")])
def test_advertising_retry_limit_and_ambiguous_delivery_are_not_infinite(kind, attempts, outcome):
    async def run():
        async with fixture() as (sessions, pid, bid, chats, slots, leads, hot):
            eid = await enroll(sessions, chats[0]); await process_enrollment(eid, sessions)
            calls = []
            async def send(db, chat, delivery):
                calls.append(1)
                raise TelegramDeliveryError(method="sendMessage", description=kind, transient=True,
                    definitely_not_sent=kind == "connect", error_code=429 if kind == "rate_limit" else None,
                    retry_after=10 if kind == "rate_limit" else None)
            for _ in range(attempts):
                await due(sessions, eid); await process_enrollment(eid, sessions, send)
            await process_enrollment(eid, sessions, send)
            assert len(calls) == attempts
            async with sessions() as db:
                row = await db.scalar(select(AdvertisingDelivery).where(AdvertisingDelivery.enrollment_id == eid, AdvertisingDelivery.position == 0))
                assert row.status == outcome and row.progress_json["next_index"] == 0
    asyncio.run(run())


def test_cloud_backup_refuses_large_upload_before_opening_file_or_network(monkeypatch, tmp_path):
    from app.services import backup_service
    from app.services.backup_service import BackupResult, BackupError
    cfg = Settings(_env_file=None, DATABASE_URL="postgresql+asyncpg://localhost/test", SECRET_KEY="test", BACKUP_TELEGRAM_MAX_UPLOAD_MB=2000)
    monkeypatch.setattr(backup_service, "send_telegram_message", lambda *args, **kwargs: None)
    def network(*args, **kwargs): pytest.fail("Cloud oversize file must not be uploaded")
    monkeypatch.setattr(httpx, "Client", network)
    archive = BackupResult(path=tmp_path/"not-created.sql.gz", size_bytes=60*1048576, sha256="test", created_at=datetime.now(timezone.utc), encrypted=False)
    with pytest.raises(BackupError, match="limit is 49"):
        backup_service.send_backup_to_telegram(archive, config=cfg, bot_token="test", chat_id="test")
