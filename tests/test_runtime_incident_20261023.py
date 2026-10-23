"""Regression checks for the October 23 incident against disposable PostgreSQL."""
import asyncio
import importlib.util
import os
import shutil
import subprocess
from hashlib import sha256
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import *  # noqa: F403
from app.models.base import Base
from app.models.bot import Bot
from app.models.chat import Chat
from app.models.lead import Lead
from app.models.lead_status import LeadStatus
from app.models.project import Project
from app.models.funnel import ChatFunnelState, Funnel, FunnelEdge, FunnelStep, FunnelVersion
from app.models.message import Message
from app.repositories.chat_repository import ChatRepository
from app.services.chat_user_block_service import ChatUserBlockService
from app.services.lead_confidence_service import LeadConfidenceService
from app.services.lead_identity_service import LeadIdentityService
from app.services.telegram_service import TelegramService
from app.services.message_service import MessageService
from app.services.telegram_sender import TelegramDeliveryError


@pytest.mark.parametrize("media_type,fallback_method", [("video_note", "sendVideo"), ("voice", "sendDocument")])
@pytest.mark.parametrize("failure", ["restricted", "timeout", "success"])
def test_media_fallback_only_after_explicit_restriction(monkeypatch, media_type, fallback_method, failure):
    media = b"test voice"
    if media_type == "video_note":
        if not shutil.which("ffmpeg"):
            pytest.skip("ffmpeg required for video-note preparation")
        media = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.2",
            "-c:v", "mpeg4", "-movflags", "frag_keyframe+empty_moov", "-f", "mp4", "pipe:1"],
            check=True, capture_output=True).stdout
    requests = []
    def respond(request):
        requests.append(request.url.path.rsplit("/", 1)[-1])
        if len(requests) == 1 and failure == "restricted":
            return httpx.Response(400, json={"ok": False, "error_code": 400, "description": "Bad Request: VOICE_MESSAGES_FORBIDDEN"})
        if failure == "timeout":
            raise httpx.ReadTimeout("test timeout", request=request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 12}})
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(respond), **kw))
    service = MessageService(MagicMock(), raise_on_telegram_delivery_error=True)
    service.telegram_sender._get_transport_type = AsyncMock(return_value="bot_api")
    service.telegram_sender._get_token = AsyncMock(return_value="test-token")
    async def run():
        return await service._send_media_to_telegram_by_type(media_type=media_type, media=media,
            project_id=uuid4(), bot_id=uuid4(), external_chat_id="42", caption="Caption",
            reply_markup={"inline_keyboard": [[{"text": "Next", "callback_data": "next"}]]},
            file_name=None, mime_type=None, allow_restricted_media_fallback=True)
    if failure == "timeout":
        with pytest.raises(TelegramDeliveryError):
            asyncio.run(run())
        assert len(requests) == 1
    else:
        assert asyncio.run(run())["message_id"] == 12
        assert len(requests) == (2 if failure == "restricted" else 1)
        if failure == "restricted":
            assert requests[-1] == fallback_method


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL URL not provided")
def test_identity_indexes_resource_failure_and_block_ordering(monkeypatch):
    async def run():
        schema = f"incident_{uuid4().hex}"
        role = f"identity_{uuid4().hex}"
        url = os.environ["CRM_TEST_POSTGRES_URL"]
        admin = create_async_engine(url)
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with admin.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with sessions() as db:
                project = Project(name="Incident QA", slug=schema, use_confidence_score=True)
                other = Project(name="Other", slug=f"other_{schema}")
                status = LeadStatus(name="New", code="new")
                db.add_all([project, other, status])
                await db.flush()
                bots = [Bot(project_id=p.id, name=f"Bot {i}") for i, p in enumerate([project, other])]
                db.add_all(bots)
                await db.flush()
                chats = [Chat(project_id=p.id, bot_id=bots[i % 2].id,
                              external_chat_id=str(i + 100), external_user_id="same" if i < 2 else str(i))
                         for i, p in enumerate([project, other, project, project])]
                db.add_all(chats)
                await db.flush()
                leads = [Lead(project_id=c.project_id, chat_id=c.id, status_id=status.id,
                              phone="+7 (900) 123-45-67" if i < 3 else None,
                              username="@Shared" if i < 2 else None, score_percent=73)
                         for i, c in enumerate(chats)]
                db.add_all(leads)
                await db.commit()
                source, duplicate, chat = leads[0].id, leads[1].id, chats[0]
                project_id, bot_id, chat_id = project.id, bots[0].id, chat.id
                identity = LeadIdentityService(db)
                assert await identity.count_duplicates(source, project_id) == 2
                assert len(await identity.find_duplicates(source, project_id)) == 2
                scoped = await identity.find_duplicates(source, project_id, visible_project_ids=[project_id])
                assert len(scoped) == 1
                assert not await identity.find_duplicates(source, project_id, visible_project_ids=[])

                await db.execute(text("SET LOCAL enable_seqscan = off"))
                await db.execute(text("SET LOCAL plan_cache_mode = force_generic_plan"))
                query = identity._candidate_ids_query(source, [and_(Lead.phone.is_not(None), identity._phone_digits_expr() == "79001234567")])
                sql = str(query.compile(engine.sync_engine, compile_kwargs={"literal_binds": True}))
                plan = " ".join((await db.execute(text("EXPLAIN " + sql))).scalars())
                assert "ix_leads_phone_digits" in plan
                await db.rollback()

            # A genuine PostgreSQL 53100 inside the duplicate lookup must not
            # roll back unrelated CRM writes or approve a lead with a stale score.
            async with admin.begin() as conn:
                await conn.execute(text(f'CREATE ROLE "{role}"'))
            async with engine.begin() as conn:
                await conn.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
                await conn.execute(text(f'GRANT SELECT, UPDATE ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"'))
                await conn.execute(text(f"""CREATE FUNCTION identity_resource_fault(value uuid) RETURNS boolean
                    LANGUAGE plpgsql AS $$ BEGIN
                    IF value = '{duplicate}'::uuid THEN
                        RAISE EXCEPTION 'disposable resource fault' USING ERRCODE = '53100';
                    END IF; RETURN true; END $$"""))
                await conn.execute(text("ALTER TABLE leads ENABLE ROW LEVEL SECURITY"))
                await conn.execute(text("CREATE POLICY identity_qa ON leads USING (identity_resource_fault(id))"))
            async with sessions() as db:
                await db.execute(text(f'SET LOCAL ROLE "{role}"'))
                lead = await db.get(Lead, source)
                lead.manager_comment = "must survive duplicate lookup failure"
                assert await LeadConfidenceService(db).update_lead_score(source) == 73
                assert lead.confidence_meta["calculation_deferred"]
                assert lead.score_percent == 73
                assert await db.scalar(text("SELECT 1")) == 1
                await db.commit()
            async with sessions() as db:
                assert (await db.get(Lead, source)).manager_comment == "must survive duplicate lookup failure"

            # A sending transaction owns the chat. The independent block writer
            # must yield immediately instead of waiting on its own caller.
            monkeypatch.setattr("app.services.chat_user_block_service.get_db_session", sessions)
            now = datetime.now(timezone.utc)
            async with sessions() as owner:
                await owner.execute(select(Chat.id).where(Chat.id == chat_id).with_for_update())
                applied = await asyncio.wait_for(ChatUserBlockService.persist_blocked_from_telegram_error(
                    project_id=project_id, bot_id=bot_id, external_chat_id="100",
                    observed_at=now, defer_if_locked=False), timeout=2)
                assert applied is False
                if os.getenv("CRM_TEST_REDIS_URL"):
                    from arq import create_pool
                    from arq.jobs import Job
                    from app.core.arq_queues import JOBS_QUEUE_NAME
                    from app.services.funnel_job_queue import _redis_settings_from_url
                    assert not await asyncio.wait_for(ChatUserBlockService.persist_blocked_from_telegram_error(
                        project_id=project_id, bot_id=bot_id, external_chat_id="100", observed_at=now), timeout=2)
                    redis = await create_pool(_redis_settings_from_url())
                    job_id = "telegram-block:" + sha256(f"{project_id}:{bot_id}:100:{now.isoformat()}".encode()).hexdigest()
                    try:
                        info = await Job(job_id, redis).info()
                        assert info.function == "persist_telegram_block_task"
                        assert info.args == (str(project_id), str(bot_id), "100", now.isoformat())
                    finally:
                        await redis.delete("arq:job:" + job_id)
                        await redis.zrem(JOBS_QUEUE_NAME, job_id)
                        await redis.aclose()
                await owner.rollback()
            assert await ChatUserBlockService.persist_blocked_from_telegram_error(
                project_id=project_id, bot_id=bot_id, external_chat_id="100", observed_at=now,
                defer_if_locked=False)
            async with sessions() as db:
                assert (await db.get(Chat, chat_id)).is_blocked_by_user is True
                await ChatRepository(db).set_blocked_by_user(project_id=project_id, bot_id=bot_id,
                    external_chat_id="100", is_blocked_by_user=False, observed_at=now + timedelta(seconds=1))
                await db.commit()
            assert await ChatUserBlockService.persist_blocked_from_telegram_error(
                project_id=project_id, bot_id=bot_id, external_chat_id="100", observed_at=now,
                defer_if_locked=False)
            async with sessions() as db:
                assert (await db.get(Chat, chat_id)).is_blocked_by_user is False

            # Recovered starts use the stored message, including internal flags.
            # An empty input prompt avoids Telegram calls in this database test.
            async with sessions() as db:
                bot = await db.get(Bot, bot_id)
                funnel = Funnel(project_id=project_id, bot_id=bot_id, name="Recovery")
                db.add(funnel)
                await db.flush()
                version = FunnelVersion(funnel_id=funnel.id, version_number=1, status="published")
                db.add(version)
                await db.flush()
                bot.active_funnel_id, bot.active_funnel_version_id = funnel.id, version.id
                funnel.current_version_id = version.id
                question = FunnelStep(funnel_version_id=version.id, key="question", title="Question",
                    step_type="input", block_type="generic_input", config_json={"prompt": " ", "timeout_seconds": 0})
                trigger = FunnelStep(funnel_version_id=version.id, key="start", title="Start",
                    step_type="trigger", block_type="generic_start", config_json={})
                db.add_all([question, trigger])
                await db.flush()
                db.add(FunnelEdge(funnel_version_id=version.id, from_step_id=trigger.id, to_step_id=question.id))
                start = Message(chat_id=chat_id, sender_type="user", message_type="text", body="/start",
                    raw_payload_json={"crm_repeated_start": False})
                db.add(start)
                await db.commit()
                assert await TelegramService(db).process_queued_funnel_start(chat_id=chat_id,
                    trigger_message_id=start.id, fresh_lifecycle=False) == "processed"
                state = await db.scalar(select(ChatFunnelState).where(ChatFunnelState.chat_id == chat_id))
                assert state is not None and state.current_step_id == question.id and state.waiting_for_answer
                await ChatUserBlockService(db).set_blocked_by_user(project_id=project_id, bot_id=bot_id,
                    external_chat_id="100", is_blocked_by_user=True, observed_at=now)
                await db.refresh(state)
                assert not state.is_paused
                await db.commit()

            spec = importlib.util.spec_from_file_location("incident_migration", Path(__file__).resolve().parents[1] / "alembic/versions/20261023_0087_telegram_block_state_order.py")
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            def migrate(conn, direction):
                with Operations.context(MigrationContext.configure(conn)):
                    getattr(migration, direction)()
            async with engine.begin() as conn:
                before = (await conn.execute(text("SELECT count(*) FROM chats"))).scalar_one()
                await conn.run_sync(migrate, "downgrade")
                await conn.run_sync(migrate, "upgrade")
                assert (await conn.execute(text("SELECT count(*) FROM chats"))).scalar_one() == before
        finally:
            await engine.dispose()
            async with admin.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
                await conn.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
            await admin.dispose()
    asyncio.run(run())
