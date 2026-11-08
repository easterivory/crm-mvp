"""Incident QA: exact counter semantics, bounded failure retries and realistic states."""
import asyncio
import os
import time
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import Integer, String, and_, case, cast, func, literal, or_, select, text
from sqlalchemy.exc import DBAPIError

from app.core import telegram_intake
from app.models import Bot, Chat, Lead, Project, Tag
from app.models.funnel import ChatFunnelState, Funnel, FunnelStep, FunnelVersion
from app.models.lead import LeadTag
from app.models.partner import LeadSubmission, PartnerIntegration
from app.repositories.chat_repository import ChatRepository
from app.services import chat_workspace_counts_service as counters
from app.services.chat_service import ChatService
from test_gambling_offers import PG, fixture
from test_incident_20261108 import Cache


def reference_statement(pid, viewer, rules, confidence=True, project_format="submission", hide=False, bid=None):
    repo = ChatRepository(None)
    all_count = func.count(Chat.id)
    if hide:
        all_count = all_count.filter(or_(Lead.manager_id.is_(None), Lead.manager_id == viewer))
    stmt = select(
        func.count(Chat.id).filter(repo.priority_expr(rules)).label("priority"),
        func.count(Chat.id).filter(repo._workspace_unread_expr(project_format=project_format,
            push_unread_threshold=2, use_confidence_score=confidence)).label("unread"),
        func.count(Chat.id).filter(repo.unanswered_expr()).label("unanswered"),
        func.count(Chat.id).filter(Lead.manager_id == viewer).label("mine"),
        all_count.label("all"), func.count(Chat.id).filter(Chat.is_favorite.is_(True)).label("favorites"),
    ).select_from(Chat).outerjoin(Lead, and_(Lead.chat_id == Chat.id, Lead.is_deleted.is_(False))).where(
        Chat.project_id == pid, Chat.is_deleted.is_(False), Chat.reset_at.is_(None))
    return stmt.where(Chat.bot_id == bid) if bid else stmt


async def graph(db, pid, bid):
    funnel = Funnel(project_id=pid, bot_id=bid, name="Counter QA")
    db.add(funnel); await db.flush()
    version = FunnelVersion(funnel_id=funnel.id, version_number=1, status="published")
    db.add(version); await db.flush()
    step = FunnelStep(funnel_version_id=version.id, key="qa", title="QA", step_type="message", block_type="message", config_json={})
    db.add(step); await db.flush()
    return funnel, version, step


@PG
def test_counts_preserve_completed_submission_deleted_and_overlapping_tag_semantics():
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bid, _):
            async with sessions() as db:
                funnel, version, step = await graph(db, pid, bid)
                other_bot = Bot(project_id=pid, name="Other QA")
                other_project = Project(name="Other QA", slug="counter-other", project_format="submission")
                db.add_all([other_bot, other_project]); await db.flush()
                tags = [Tag(project_id=pid, name=f"HOT {n}") for n in range(3)]
                foreign = Tag(project_id=other_project.id, name="Foreign")
                db.add_all([*tags, foreign]); await db.flush()
                status_id = (await db.get(Lead, leads[0])).status_id
                now = datetime.now(timezone.utc)
                for n in range(6):
                    chat = Chat(project_id=pid, bot_id=other_bot.id if n % 2 else bid,
                        external_chat_id=f"extra-{n}", external_user_id=f"extra-{n}")
                    db.add(chat); await db.flush()
                    lead = Lead(project_id=pid, chat_id=chat.id, status_id=status_id)
                    db.add(lead); await db.flush(); leads.append(lead.id)
                for n, lid in enumerate(leads):
                    lead = await db.get(Lead, lid)
                    chat = await db.get(Chat, lead.chat_id)
                    lead.manager_id = actor.id if n else None
                    lead.score_percent = 100 if n == 2 else 30
                    lead.is_deleted = n == 7
                    chat.reset_at = now if n == 8 else None
                    chat.is_read = n == 6
                    chat.last_client_message_at = now
                    chat.has_out_of_scenario_message = n == 5
                    db.add(ChatFunnelState(chat_id=chat.id, funnel_id=funnel.id,
                        funnel_version_id=version.id, current_step_id=step.id, entered_step_at=now,
                        completed_at=now if n in [1, 2, 3, 7] else None))
                    if n in [1, 2, 3]:
                        db.add_all([LeadTag(lead_id=lid, tag_id=tags[0].id), LeadTag(lead_id=lid, tag_id=tags[1].id)])
                    if n == 4: db.add(LeadTag(lead_id=lid, tag_id=foreign.id))
                no_lead = Chat(project_id=pid, bot_id=bid, external_chat_id="no-lead", external_user_id="no-lead", is_read=False)
                db.add(no_lead)
                partner = PartnerIntegration(project_id=pid, name="QA", postback_url="https://example.org")
                db.add(partner); await db.flush()
                db.add_all([
                    LeadSubmission(lead_id=leads[3], partner_integration_id=partner.id, status="success"),
                    LeadSubmission(lead_id=leads[4], partner_integration_id=partner.id, status="manual_required"),
                ])
                await db.commit()
                rules = {"enabled": True, "tag_ids": [str(t.id) for t in [*tags, foreign]]}
                for confidence in [True, False]:
                    for fmt in ["submission", "gambling"]:
                        for hide in [True, False]:
                            for bot in [None, bid, other_bot.id]:
                                expected = dict((await db.execute(reference_statement(pid, actor.id, rules, confidence, fmt, hide, bot))).one()._mapping)
                                actual = await ChatRepository(db).workspace_counts(project_id=pid, viewer_id=actor.id,
                                    hide_assigned_from_all=hide, priority_rules=rules, use_confidence_score=confidence,
                                    project_format=fmt, push_unread_threshold=2, bot_id=bot)
                                assert actual == expected
    asyncio.run(run())


@PG
def test_only_counter_pool_disables_jit_and_parallel_workers(monkeypatch):
    monkeypatch.setattr(telegram_intake, "_factories", {})
    async def run():
        try:
            async with telegram_intake.get_intake_db_session() as intake:
                baseline = {key: await intake.scalar(text("SHOW " + key)) for key in ["jit", "max_parallel_workers_per_gather"]}
            async with telegram_intake.get_count_db_session() as db:
                assert await db.scalar(text("SHOW jit")) == "off"
                assert await db.scalar(text("SHOW max_parallel_workers_per_gather")) == "0"
                assert await db.scalar(text("SHOW default_transaction_read_only")) == "on"
                assert await db.scalar(text("SHOW statement_timeout")) == "3s"
            async with telegram_intake.get_intake_db_session() as intake:
                assert baseline == {key: await intake.scalar(text("SHOW " + key)) for key in baseline}
        finally:
            await telegram_intake.close_reserved_db_pools()
    asyncio.run(run())


@PG
def test_followers_wait_for_slow_success_without_duplicate_scans(monkeypatch):
    async def run():
        async with fixture() as (sessions, pid, actor, *_):
            cache = Cache()
            async def redis(): return cache
            monkeypatch.setattr(counters, "get_redis", redis)
            monkeypatch.setattr(counters, "get_count_db_session", sessions)
            original = ChatRepository.shared_workspace_counts
            calls = []
            async def slow(repo, **kwargs):
                calls.append(1); await asyncio.sleep(1.2)
                return await original(repo, **kwargs)
            monkeypatch.setattr(ChatRepository, "shared_workspace_counts", slow)
            async def request():
                async with sessions() as db: return await ChatService(db).get_workspace_counts(project_id=pid, actor=actor)
            result = await asyncio.gather(*(request() for _ in range(15)))
            assert len(calls) == 1 and all(row.all == 3 for row in result)
    asyncio.run(run())


@PG
def test_failed_scan_has_short_cooldown_and_safe_phase_logging(monkeypatch, caplog):
    class Canceled(Exception): sqlstate = "57014"
    async def run():
        async with fixture() as (sessions, pid, actor, *_):
            cache = Cache()
            async def redis(): return cache
            monkeypatch.setattr(counters, "get_redis", redis)
            monkeypatch.setattr(counters, "get_count_db_session", sessions)
            original = ChatRepository.shared_workspace_counts
            calls, working = [], False
            async def scan(repo, **kwargs):
                calls.append(1)
                if not working: raise DBAPIError("private-sql", {"token": "private-value"}, Canceled("private-error"))
                return await original(repo, **kwargs)
            monkeypatch.setattr(ChatRepository, "shared_workspace_counts", scan)
            async def request():
                async with sessions() as db: return await ChatService(db).get_workspace_counts(project_id=pid, actor=actor)
            for _ in range(5):
                with pytest.raises(HTTPException) as error: await request()
                assert error.value.status_code == 503
            assert len(calls) == 1
            assert "phase=aggregate" in caplog.text and "sqlstate=57014" in caplog.text
            assert "private-value" not in caplog.text and "private-sql" not in caplog.text
            working = True
            counters._state().failures.clear()
            for key in cache.deadlines:
                if key.endswith(":error"): cache.deadlines[key] = 0
            assert (await request()).all == 3 and len(calls) == 2
    asyncio.run(run())


@PG
@pytest.mark.skipif(os.getenv("CRM_LARGE_QA") != "1", reason="Explicit realistic 100k workload")
def test_counts_with_one_hundred_thousand_populated_funnel_states():
    async def run():
        async with fixture() as (sessions, pid, actor, leads, bid, _):
            async with sessions() as db:
                funnel, version, step = await graph(db, pid, bid)
                status_id = (await db.get(Lead, leads[0])).status_id
                n = func.generate_series(1, 100000).table_valued("n").render_derived().c.n
                await db.execute(Chat.__table__.insert().from_select(
                    ["id", "project_id", "bot_id", "external_chat_id", "external_user_id", "is_read", "last_client_message_at", "is_favorite"],
                    select(func.gen_random_uuid(), literal(pid), literal(bid), literal("state-bench-") + cast(n, String),
                        cast(n, String), n % 5 == 0, func.now(), n % 7 == 0)))
                number = cast(func.substr(Chat.external_chat_id, 13), Integer)
                await db.execute(Lead.__table__.insert().from_select(
                    ["id", "project_id", "chat_id", "status_id", "manager_id", "score_percent"],
                    select(func.gen_random_uuid(), literal(pid), Chat.id, literal(status_id),
                        case((number % 2 == 0, literal(actor.id, type_=Lead.__table__.c.manager_id.type)), else_=None), number % 100)
                    .where(Chat.external_chat_id.like("state-bench-%"))))
                tags = [Tag(project_id=pid, name=f"HOT {i}") for i in range(3)]
                db.add_all(tags); await db.flush()
                for tag, divisor in zip(tags, [3, 5, 7]):
                    await db.execute(LeadTag.__table__.insert().from_select(["lead_id", "tag_id"],
                        select(Lead.id, literal(tag.id)).join(Chat, Chat.id == Lead.chat_id).where(
                            Chat.external_chat_id.like("state-bench-%"), number % divisor == 0)))
                await db.execute(ChatFunnelState.__table__.insert().from_select(
                    ["id", "chat_id", "funnel_id", "funnel_version_id", "current_step_id", "entered_step_at", "completed_at"],
                    select(func.gen_random_uuid(), Chat.id, literal(funnel.id), literal(version.id), literal(step.id),
                        func.now() - text("interval '1 day'"), case((number % 3 == 0, func.now()), else_=None))
                    .where(Chat.external_chat_id.like("state-bench-%"))))
                for table in ["chats", "leads", "lead_tags", "tags", "chat_funnel_states", "lead_submissions"]:
                    await db.execute(text("ANALYZE " + table))
                await db.commit()
                rules = {"enabled": True, "tag_ids": [str(t.id) for t in tags]}
                before = time.monotonic()
                expected = dict((await db.execute(reference_statement(pid, actor.id, rules))).one()._mapping)
                old_ms = (time.monotonic() - before) * 1000
                before = time.monotonic()
                actual = await ChatRepository(db).shared_workspace_counts(project_id=pid, priority_rules=rules)
                new_ms = (time.monotonic() - before) * 1000
                assert actual["totals"] == {k: v for k, v in expected.items() if k != "mine"}
                assert actual["managers"][str(actor.id)] == expected["mine"]
                assert new_ms < 3000
                print(f"\n100k populated states/3 overlapping tags: reference={old_ms:.1f}ms optimized={new_ms:.1f}ms; equal metrics")
    asyncio.run(run())
