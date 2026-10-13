"""Push scheduling regressions against disposable PostgreSQL, without mocks."""
import asyncio
import importlib.util
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, Bot, Chat, Project
from app.models.funnel import ChatFunnelState, Funnel, FunnelVersion, FunnelStep, FunnelPushRule
from app.repositories.funnel_repository import FunnelRepository


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
def test_pushes_skip_submission_backlog_and_sent_rows_before_limit():
    async def run():
        schema = "push_candidates_" + uuid4().hex
        url = os.environ["CRM_TEST_POSTGRES_URL"]
        root = create_async_engine(url)
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with root.begin() as db:
                await db.execute(text(f'CREATE SCHEMA "{schema}"'))
            async with engine.begin() as db:
                await db.run_sync(Base.metadata.create_all)
            async with sessions() as db:
                now = datetime.now(timezone.utc).replace(microsecond=123000)
                rollout = now - timedelta(minutes=20)
                projects = [Project(name=kind, slug=kind, project_format=kind,
                                    funnel_push_enabled_at=rollout) for kind in ("gambling", "submission")]
                db.add_all(projects)
                await db.flush()
                contexts = []
                for project in projects:
                    bot = Bot(project_id=project.id, name="Bot")
                    db.add(bot); await db.flush()
                    funnel = Funnel(project_id=project.id, bot_id=bot.id, name="Push")
                    db.add(funnel); await db.flush()
                    version = FunnelVersion(funnel_id=funnel.id, version_number=1, status="published")
                    db.add(version); await db.flush()
                    step = FunnelStep(funnel_version_id=version.id, key="wait", title="Wait",
                                      step_type="input", block_type="generic_input")
                    db.add(step); await db.flush()
                    rule = FunnelPushRule(funnel_version_id=version.id, step_id=step.id,
                                          delay_minutes=5, message_text="Reminder")
                    db.add(rule); await db.flush()
                    contexts.append((project, bot, funnel, version, step, rule))

                def add_chat(context, entered, *, runtime=None, **flags):
                    project, bot, funnel, version, step, _ = context
                    chat = Chat(id=uuid4(), project_id=project.id, bot_id=bot.id,
                                external_chat_id=uuid4().hex, external_user_id=uuid4().hex)
                    state = ChatFunnelState(chat_id=chat.id, funnel_id=funnel.id, funnel_version_id=version.id,
                        current_step_id=step.id, entered_step_at=entered, waiting_for_answer=True,
                        runtime_json=runtime or {})
                    for key, value in flags.items():
                        setattr(state if key in {"is_paused", "completed_at", "waiting_for_answer"} else chat, key, value)
                    db.add_all([chat, state])
                    return chat.id

                gambling, submission = contexts
                old = now - timedelta(days=1)
                # These rows used to fill the entire batch before Python removed them.
                for index in range(405):
                    entered = old.replace(microsecond=0 if index % 2 else 123000)
                    add_chat(gambling, entered, runtime={"push_rules_sent": {str(gambling[-1].id): entered.isoformat()}})
                add_chat(submission, old)
                ready_gambling = add_chat(gambling, now - timedelta(minutes=30))
                ready_submission = add_chat(submission, now - timedelta(minutes=10))
                cutoff_submission = add_chat(submission, rollout)
                add_chat(submission, now - timedelta(minutes=1))
                for flags in ({"is_paused": True}, {"completed_at": now}, {"waiting_for_answer": False},
                              {"is_blocked": True}, {"is_blocked_by_user": True}, {"is_deleted": True}, {"reset_at": now}):
                    add_chat(submission, now - timedelta(minutes=10), **flags)
                add_chat(submission, now - timedelta(minutes=10),
                         runtime={"push_delivery_suspended": {"at_epoch": now.timestamp()}})
                revisited = add_chat(submission, now - timedelta(minutes=10),
                    runtime={"push_rules_sent": {str(submission[-1].id): old.isoformat()}})
                await db.commit()
                repo = FunnelRepository(db)
                candidates = await repo.find_stuck_chats_for_push_rules(now=now, limit=1)
                assert [state.chat_id for state, _ in candidates] == [ready_gambling]
                candidates = await repo.find_stuck_chats_for_push_rules(now=now, limit=100)
                assert {state.chat_id for state, _ in candidates} == {
                    ready_gambling, ready_submission, cutoff_submission, revisited,
                }
                assert await repo.find_stuck_chats_for_push_rules(now=now, limit=0) == []
        finally:
            await engine.dispose()
            async with root.begin() as db:
                await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await root.dispose()
    asyncio.run(run())


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
def test_push_rollout_migration_upgrade_downgrade_preserves_existing_projects():
    async def run():
        schema = "push_migration_" + uuid4().hex
        engine = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"])
        path = Path(__file__).resolve().parents[1] / "alembic/versions/20261013_0086_submission_funnel_pushes.py"
        spec = importlib.util.spec_from_file_location("push_rollout_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        def migrate(conn, direction):
            with Operations.context(MigrationContext.configure(conn)):
                getattr(migration, direction)()

        try:
            async with engine.begin() as db:
                await db.execute(text(f'CREATE SCHEMA "{schema}"'))
                await db.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                await db.execute(text("CREATE TABLE projects (id integer PRIMARY KEY, name text NOT NULL)"))
                await db.execute(text("INSERT INTO projects VALUES (1, 'Existing')"))
                before = await db.scalar(text("SELECT now()"))
                await db.run_sync(migrate, "upgrade")
                assert await db.scalar(text("SELECT funnel_push_enabled_at FROM projects WHERE id=1")) == before
                await db.execute(text("INSERT INTO projects (id,name) VALUES (2,'New')"))
                assert await db.scalar(text("SELECT funnel_push_enabled_at FROM projects WHERE id=2")) == before
                await db.run_sync(migrate, "downgrade")
                assert (await db.execute(text("SELECT id,name FROM projects ORDER BY id"))).all() == [(1, "Existing"), (2, "New")]
                await db.run_sync(migrate, "upgrade")
                assert await db.scalar(text("SELECT count(*) FROM projects WHERE funnel_push_enabled_at IS NOT NULL")) == 2
        finally:
            async with engine.begin() as db:
                await db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await engine.dispose()
    asyncio.run(run())
