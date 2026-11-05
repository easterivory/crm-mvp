import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import JSON, MetaData
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateTable

from app.core.hold_schedule import HoldSchedule, scheduled_hold_plan
from app.models import Base, Project, Bot, Chat, Lead
from app.models.funnel import Funnel, FunnelVersion, FunnelStep, ChatFunnelState
from app.models.lead_status import LeadStatus
from app.schemas.funnel import FunnelHoldModeUpdate
from app.schemas.project import ProjectUpdate
from app.services.funnel_runtime_service import FunnelRuntimeService
from app.services.funnel_service import FunnelService
from app.services.project_service import ProjectService


@pytest.mark.parametrize("clock,expected,deferred", [
    ("2026-11-02T14:59:59+00:00", "2026-11-02", False),
    ("2026-11-02T15:00:00+00:00", "2026-11-03", True),
    ("2026-11-02T20:59:59+00:00", "2026-11-03", True),
    ("2026-11-02T21:00:00+00:00", "2026-11-03", False),
    ("2026-11-06T15:00:00+00:00", "2026-11-07", True),
    ("2026-11-07T15:00:00+00:00", "2026-11-09", True),
    ("2026-11-08T06:00:00+00:00", "2026-11-09", True),
    ("2026-11-08T20:59:59+00:00", "2026-11-09", True),
])
def test_moscow_cutoff_midnight_and_weekend(clock, expected, deferred):
    plan = scheduled_hold_plan(HoldSchedule(enabled=True), datetime.fromisoformat(clock))
    assert plan["date"] == expected
    assert plan["is_hold"] is deferred


def test_custom_calendar_and_timezone():
    schedule = HoldSchedule(enabled=True, timezone="Asia/Tashkent", cutoff_time="12:30",
        working_days=[0, 2, 4], closed_dates=["2026-11-04"], before_cutoff="next_working_day")
    assert scheduled_hold_plan(schedule, datetime(2026, 11, 2, 2, tzinfo=timezone.utc))["date"] == "2026-11-06"
    schedule.before_cutoff = "today"
    assert scheduled_hold_plan(schedule, datetime(2026, 11, 2, 7, 29, tzinfo=timezone.utc))["date"] == "2026-11-02"
    assert scheduled_hold_plan(schedule, datetime(2026, 11, 2, 7, 30, tzinfo=timezone.utc))["date"] == "2026-11-06"
    sunday = HoldSchedule(working_days=[6])
    assert scheduled_hold_plan(sunday, datetime(2026, 11, 2, tzinfo=timezone.utc))["date"] == "2026-11-08"


@pytest.mark.parametrize("value", [
    {"timezone": "Not/AZone"}, {"timezone": "../etc/passwd"},
    {"cutoff_time": "24:00"}, {"cutoff_time": "8:00"}, {"cutoff_time": "18:60"},
    {"working_days": []}, {"working_days": [7]}, {"working_days": [True]},
    {"working_days": ["1"]}, {"closed_dates": ["2026-02-30"]}, {"unknown": 1},
])
def test_invalid_settings_rejected(value):
    with pytest.raises(ValidationError):
        HoldSchedule.model_validate(value)


def test_defaults_and_patch_contract():
    assert not HoldSchedule().enabled
    assert HoldSchedule(working_days=[5, 0, 0]).working_days == [0, 5]
    assert ProjectUpdate(name="Other setting").model_dump(exclude_unset=True) == {"name": "Other setting"}
    assert FunnelHoldModeUpdate(is_hold_active=True).hold_mode == "manual"
    with pytest.raises(ValueError):
        scheduled_hold_plan(HoldSchedule(), datetime(2026, 11, 2))


@asynccontextmanager
async def database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    tables = [Project, Bot, Chat, LeadStatus, Lead, Funnel, FunnelVersion, FunnelStep, ChatFunnelState]
    metadata = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(metadata)
    async with engine.begin() as conn:
        for model in tables:
            table = metadata.tables[model.__tablename__]
            for column in table.columns:
                if isinstance(column.type, JSONB):
                    column.type = JSON()
                    column.server_default = None
            await conn.execute(CreateTable(table))
    try:
        async with async_sessionmaker(engine, expire_on_commit=False, autoflush=False)() as db:
            project = Project(id=uuid4(), name="QA", slug="hold-qa", hold_schedule=HoldSchedule(enabled=True).model_dump(mode="json"))
            db.add(project); await db.flush()
            bot = Bot(id=uuid4(), project_id=project.id, name="QA")
            status = LeadStatus(id=uuid4(), name="New", code="new")
            db.add_all([bot, status]); await db.flush()
            chat = Chat(id=uuid4(), project_id=project.id, bot_id=bot.id, external_chat_id="123", external_user_id="123")
            funnel = Funnel(id=uuid4(), project_id=project.id, bot_id=bot.id, name="QA")
            db.add_all([chat, funnel]); await db.flush()
            version = FunnelVersion(id=uuid4(), funnel_id=funnel.id, version_number=1,
                hold_mode="project_schedule", status="published")
            lead = Lead(id=uuid4(), project_id=project.id, chat_id=chat.id, status_id=status.id,
                custom_fields={"unrelated": "kept"})
            db.add_all([version, lead]); await db.flush()
            step = FunnelStep(id=uuid4(), funnel_version_id=version.id, key="hold", title="HOLD",
                step_type="condition", block_type="generic_hold_router", config_json={})
            db.add(step); await db.flush()
            state = ChatFunnelState(id=uuid4(), chat_id=chat.id, funnel_id=funnel.id,
                funnel_version_id=version.id, current_step_id=step.id, entered_step_at=datetime.now(timezone.utc),
                waiting_for_answer=True, is_paused=True, runtime_json={"sent_message_ids": [111], "push_delivery_suspended": {"at_epoch": 123}})
            db.add(state); await db.commit()
            yield db, project, version, lead, state, step
    finally:
        await engine.dispose()


class Saturday(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 11, 7, 16, tzinfo=timezone.utc)


def test_runtime_persists_date_preserves_state_and_renders_template():
    async def run():
        async with database() as (db, project, version, lead, state, step):
            runtime = FunnelRuntimeService(db)
            runtime.scoring.update_lead_score = AsyncMock()
            with patch("app.services.funnel_runtime_service.datetime", Saturday):
                assert await runtime._condition_source_value(state.chat_id, "hold_mode", None) is True
                assert await runtime._evaluate_condition_outcome(chat_id=state.chat_id, step=step, answer=None) == "tomorrow"
            await db.commit()
            await db.refresh(lead); await db.refresh(state)
            assert lead.call_time_text == "09.11.2026"
            assert lead.preferred_call_time == "09.11.2026"
            assert lead.custom_fields["hold_date"] == "2026-11-09"
            assert lead.custom_fields["unrelated"] == "kept"
            assert state.waiting_for_answer and state.is_paused
            assert state.runtime_json["sent_message_ids"] == [111]
            assert state.runtime_json["push_delivery_suspended"] == {"at_epoch": 123}
            saved = dict(state.runtime_json["hold_schedule_plan"])
            project.hold_schedule = {"enabled": False}
            version.hold_mode = "manual"
            await db.flush()
            # Existing bookings remain fixed even when the calendar is disabled.
            assert await runtime._get_scheduled_hold_plan(chat_id=state.chat_id) == saved
            runtime.repo.get_message_template_context = AsyncMock(return_value={"custom_fields": lead.custom_fields})
            assert await runtime._render_text_template(state.chat_id, "Дата: {{hold_date_label}} ({{custom.hold_date}})") == "Дата: 09.11.2026 (2026-11-09)"
            # New run: a reset clears runtime; the old date is not reused for routing.
            state.runtime_json = {}
            assert await runtime._get_scheduled_hold_plan(chat_id=state.chat_id) is None
    asyncio.run(run())


def test_manual_and_disabled_project_preserve_legacy_behavior():
    async def run():
        async with database() as (db, project, version, lead, state, step):
            runtime = FunnelRuntimeService(db)
            version.hold_mode = "manual"; version.is_hold_active = True
            assert await runtime._condition_source_value(state.chat_id, "hold_mode", None) is True
            assert "hold_schedule_plan" not in state.runtime_json
            version.hold_mode = "project_schedule"; project.hold_schedule = {}
            assert await runtime._condition_source_value(state.chat_id, "hold_mode", None) is True
            version.is_hold_active = False
            assert await runtime._condition_source_value(state.chat_id, "hold_mode", None) is False
            assert lead.custom_fields == {"unrelated": "kept"}
    asyncio.run(run())


@pytest.mark.parametrize("deferred,button_label", [(False, "Сегодня"), (True, "На завтра")])
def test_date_assignment_routes_old_question_buttons(deferred, button_label):
    async def run():
        service = FunnelRuntimeService.__new__(FunnelRuntimeService)
        target = uuid4()
        step = SimpleNamespace(id=uuid4(), config_json={"buttons": [{"id": "b", "label": button_label, "target_step_id": str(target)}]})
        state = SimpleNamespace(funnel_id=uuid4(), funnel_version_id=uuid4(), entered_step_at=datetime.now(timezone.utc), runtime_json={})
        service.repo = SimpleNamespace(get_chat_funnel_state=AsyncMock(return_value=state),
            get_lead_by_chat=AsyncMock(return_value=None), upsert_chat_funnel_state=AsyncMock())
        service._get_scheduled_hold_plan = AsyncMock(return_value={"date_label": "09.11.2026", "is_hold": deferred})
        service._log_step_event = AsyncMock()
        service._move_to_step_id = AsyncMock(return_value="next")
        assert await service._apply_hold_call_time_override(chat_id=uuid4(), step=step, state=state) == "next"
        assert service._move_to_step_id.call_args.kwargs["target_step_id"] == str(target)
        assert service.repo.upsert_chat_funnel_state.call_args.kwargs["runtime_json"]["last_answer"] == "09.11.2026"
    asyncio.run(run())


def test_project_schedule_admin_guard_and_null_rejection():
    async def run():
        from fastapi import HTTPException
        service = ProjectService.__new__(ProjectService)
        service._ensure_project_access = lambda *args: None
        service.project_repo = SimpleNamespace(get_active=AsyncMock(return_value=SimpleNamespace()))
        for role, value, expected in [("manager", {}, 403), ("admin", None, 422)]:
            with pytest.raises(HTTPException) as exc:
                await service.update_project(uuid4(), ProjectUpdate(hold_schedule=value), SimpleNamespace(role_name=role))
            assert exc.value.status_code == expected
    asyncio.run(run())


def test_version_opt_in_requires_enabled_project_and_legacy_payload_stays_manual():
    async def run():
        from fastapi import HTTPException
        service = FunnelService.__new__(FunnelService)
        version = SimpleNamespace(id=uuid4())
        project = SimpleNamespace(hold_schedule={})
        service.db = SimpleNamespace(get=AsyncMock(return_value=project))
        service._ensure_write_allowed = lambda *args: None
        service._get_version_or_404 = AsyncMock(return_value=version)
        service.repo = SimpleNamespace(update_version_hold_mode=AsyncMock(return_value=None))
        kwargs = dict(funnel_id=uuid4(), version_id=version.id, project_id=uuid4(), current_user=SimpleNamespace())
        with pytest.raises(HTTPException) as exc:
            await service.set_hold_mode(**kwargs, data=FunnelHoldModeUpdate(is_hold_active=False, hold_mode="project_schedule"))
        assert exc.value.status_code == 422
        service.repo.update_version_hold_mode.assert_not_called()
    asyncio.run(run())


def test_schedule_migration_only_adds_disabled_defaults():
    import importlib.util
    spec = importlib.util.spec_from_file_location("hold_migration", "alembic/versions/20261103_0093_hold_schedule.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    from unittest.mock import Mock
    operations = Mock()
    with patch.object(module, "op", operations):
        module.upgrade()
    assert module.down_revision == "20261102_0092"
    assert operations.add_column.call_count == 2
    columns = {call.args[0]: call.args[1] for call in operations.add_column.call_args_list}
    assert columns["projects"].name == "hold_schedule"
    assert columns["funnel_versions"].server_default.arg == "manual"
    assert operations.execute.call_count == 1


def test_calendar_only_overrides_call_time_questions():
    async def run():
        runtime = FunnelRuntimeService.__new__(FunnelRuntimeService)
        runtime._get_scheduled_hold_plan = AsyncMock(return_value={"is_hold": False, "date_label": "02.11.2026"})
        for block, config, expected in [
            ("ask_age", {"save_to": "age"}, False),
            ("ask_phone", {"save_to": "phone"}, False),
            ("ask_call_time", {}, True),
            ("generic_input", {"save_to": "call_time_text"}, True),
        ]:
            assert await runtime._should_override_call_time_for_hold(chat_id=uuid4(),
                step=SimpleNamespace(block_type=block, config_json=config)) is expected
    asyncio.run(run())


@pytest.mark.skipif(not os.getenv("CRM_TEST_POSTGRES_URL"), reason="Disposable PostgreSQL required")
def test_real_postgres_upgrade_preserves_existing_rows():
    async def run():
        import os
        import importlib.util
        from sqlalchemy import text
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        schema = "hold_" + uuid4().hex
        engine = create_async_engine(os.environ["CRM_TEST_POSTGRES_URL"])
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
                await conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                await conn.execute(text("CREATE TABLE projects (id integer PRIMARY KEY, name text NOT NULL)"))
                await conn.execute(text("CREATE TABLE funnel_versions (id integer PRIMARY KEY, is_hold_active boolean NOT NULL)"))
                await conn.execute(text("INSERT INTO projects VALUES (1, 'Untouched')"))
                await conn.execute(text("INSERT INTO funnel_versions VALUES (1, true), (2, false)"))
                spec = importlib.util.spec_from_file_location("hold_pg_migration", "alembic/versions/20261103_0093_hold_schedule.py")
                module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
                def migrate(sync):
                    with Operations.context(MigrationContext.configure(sync)):
                        module.upgrade()
                await conn.run_sync(migrate)
                assert (await conn.execute(text("SELECT name, hold_schedule FROM projects"))).one() == ("Untouched", {})
                assert (await conn.execute(text("SELECT is_hold_active, hold_mode FROM funnel_versions ORDER BY id"))).all() == [(True, "manual"), (False, "manual")]
        finally:
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await engine.dispose()
    asyncio.run(run())
