"""Explicit synthetic workload with production-like payload widths, never live DB."""
import asyncio
import os
import time

import pytest
from sqlalchemy import Integer, String, and_, case, cast, func, literal, select, text
from sqlalchemy.dialects import postgresql

from app.models import Bot, Chat, Lead, Tag
from app.models.funnel import ChatFunnelState
from app.models.lead import LeadTag
from app.repositories.chat_repository import ChatRepository
from test_chat_counts_coordination import environment, request, pytestmark as real_db_marks
from test_chat_counts_performance import graph

pytestmark = [*real_db_marks, pytest.mark.skipif(os.getenv("CRM_LARGE_QA") != "1", reason="Explicit 200k wide payload workload")]


def test_wide_payloads_sparse_assignments_and_simultaneous_project_counts(monkeypatch):
    async def run():
        async with environment(monkeypatch) as (sessions, actor, projects, _):
            pid, other_pid = projects[:2]
            async with sessions() as db:
                bid = await db.scalar(select(Bot.id).where(Bot.project_id == pid))
                other_bid = await db.scalar(select(Bot.id).where(Bot.project_id == other_pid))
                funnel, version, step = await graph(db, pid, bid)
                status = await db.scalar(select(Lead.status_id).where(Lead.project_id == pid).limit(1))
                n = func.generate_series(1, 200000).table_valued("n").render_derived().c.n
                await db.execute(Chat.__table__.insert().from_select(
                    ["id", "project_id", "bot_id", "external_chat_id", "external_user_id", "is_read", "last_client_message_at"],
                    select(func.gen_random_uuid(), case((n % 10 == 0, literal(other_pid, type_=Chat.__table__.c.project_id.type)),
                        else_=literal(pid, type_=Chat.__table__.c.project_id.type)),
                        case((n % 10 == 0, literal(other_bid, type_=Chat.__table__.c.bot_id.type)),
                            else_=literal(bid, type_=Chat.__table__.c.bot_id.type)), literal("wide-") + cast(n, String),
                        cast(n, String), n % 5 == 0, func.now())))
                number = cast(func.substr(Chat.external_chat_id, 6), Integer)
                await db.execute(Lead.__table__.insert().from_select(
                    ["id", "project_id", "chat_id", "status_id", "manager_id", "score_percent", "confidence_meta", "confidence_reasons"],
                    select(func.gen_random_uuid(), Chat.project_id, Chat.id, literal(status),
                        case((number % 1999 == 0, literal(actor.id, type_=Lead.__table__.c.manager_id.type)), else_=None),
                        number % 100, func.jsonb_build_object("qa", func.repeat("m", 780)),
                        func.jsonb_build_array(func.jsonb_build_object("qa", func.repeat("r", 420))))
                    .where(Chat.external_chat_id.like("wide-%"))))
                tags = [Tag(project_id=pid, name=f"Wide tag {i}") for i in range(3)]
                db.add_all(tags); await db.flush()
                for tag, divisor in zip(tags, [21, 33, 51]):
                    await db.execute(LeadTag.__table__.insert().from_select(["lead_id", "tag_id"],
                        select(Lead.id, literal(tag.id)).join(Chat, Chat.id == Lead.chat_id).where(
                            Chat.external_chat_id.like("wide-%"), number % divisor == 0)))
                await db.execute(ChatFunnelState.__table__.insert().from_select(
                    ["id", "chat_id", "funnel_id", "funnel_version_id", "current_step_id", "entered_step_at", "completed_at", "runtime_json"],
                    select(func.gen_random_uuid(), Chat.id, literal(funnel.id), literal(version.id), literal(step.id), func.now(),
                        case((number % 3 == 0, func.now()), else_=None), func.jsonb_build_object("qa", func.repeat("s", 680)))
                    .where(Chat.external_chat_id.like("wide-%"))))
                for table in ["chats", "leads", "tags", "lead_tags", "chat_funnel_states", "lead_submissions"]:
                    await db.execute(text("ANALYZE " + table))
                from app.models import Project
                project = await db.get(Project, pid)
                project.priority_chat_rules = {"enabled": True, "tag_ids": [str(t.id) for t in tags]}
                await db.commit()
                rules = project.priority_chat_rules
                await db.execute(text("SET LOCAL jit=off"))
                await db.execute(text("SET LOCAL max_parallel_workers_per_gather=0"))
                await db.execute(text("SET LOCAL work_mem='4MB'"))
                await db.execute(text("SET LOCAL statement_timeout='3s'"))
                repo = ChatRepository(db)
                base = repo._workspace_counts_statement(project_id=pid, viewer_id=actor.id,
                    hide_assigned_from_all=False, priority_rules=rules)
                columns = [column for column in base.selected_columns if column.key != "mine"]
                improved = base.with_only_columns(Lead.manager_id, *columns, maintain_column_froms=True).group_by(Lead.manager_id)
                legacy_columns = [func.count(Chat.id).filter(repo._workspace_unread_expr(project_format="submission",
                    push_unread_threshold=1, use_confidence_score=True, joined_lead=True,
                    joined_completed_state=True)).label("unread") if col.key == "unread" else col for col in columns]
                legacy = base.with_only_columns(Lead.manager_id, *legacy_columns, maintain_column_froms=True).outerjoin(
                    ChatFunnelState, and_(ChatFunnelState.chat_id == Chat.id, ChatFunnelState.completed_at.is_not(None))).group_by(Lead.manager_id)
                before = time.monotonic()
                expected = (await db.execute(legacy)).mappings().all()
                old_ms = (time.monotonic() - before) * 1000
                before = time.monotonic()
                actual = (await db.execute(improved)).mappings().all()
                new_ms = (time.monotonic() - before) * 1000
                assert {str(row["manager_id"]): dict(row) for row in actual} == {str(row["manager_id"]): dict(row) for row in expected}
                sql = str(improved.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
                plan = (await db.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql))).scalar_one()[0]
                def walk(node):
                    yield node
                    for child in node.get("Plans", []): yield from walk(child)
                state_scans = [node for node in walk(plan["Plan"]) if node.get("Relation Name") == "chat_funnel_states"]
                assert state_scans and all("Index" in node["Node Type"] for node in state_scans)
                assert sum(node["Actual Loops"] for node in state_scans) < 200
                print(f"\n200k wide payloads, sparse assignments: full-state join={old_ms:.1f}ms gated lookup={new_ms:.1f}ms; same counts; state probes={sum(n['Actual Loops'] for n in state_scans)}")
            before = time.monotonic()
            results = await asyncio.gather(*(request(sessions, actor, pid) for pid in projects))
            assert [row.all for row in results] == [180003, 20001, 2]
            assert time.monotonic() - before < 6
    asyncio.run(run())
